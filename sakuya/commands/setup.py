import ipaddress
import shutil
import socket
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

from symbollightapi.connector.SymbolConnector import SymbolConnector
from zenlog import log

from sakuya.internal.AtomicFileSystem import replace_paths
from sakuya.internal.ConfigurationManager import ConfigurationManager, load_patches_from_file
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.NodewatchClient import get_current_finalization_epoch
from sakuya.internal.PackageResolver import download_and_extract_package, resolve_package_identifier
from sakuya.internal.PeerDownloader import download_peers, find_api_node
from sakuya.internal.PemUtils import read_public_key_from_public_key_pem_file
from sakuya.internal.Preparer import Preparer
from sakuya.internal.ShoestringConfiguration import parse_shoestring_configuration
from sakuya.internal.TransactionSerializer import write_transaction_to_file
from sakuya.internal.VoterConfigurator import inspect_voting_key_files


def _resolve_hostname_and_configure_https(config, preparer):
	def is_ip_address(hostname):
		try:
			ipaddress.ip_address(hostname)
			return True
		except ValueError:
			return False

	def require_hostname(hostname):
		try:
			socket.getaddrinfo(hostname, 7890)
		except socket.gaierror as source_exception:
			raise RuntimeError(f'could not resolve address for host: {hostname}') from source_exception

	if config.node.api_https and NodeFeatures.API not in config.node.features:
		raise RuntimeError('HTTPS selected but required feature (API) is not selected')

	enable_https = NodeFeatures.API in config.node.features and config.node.api_https
	hostname = ConfigurationManager(preparer.directories.resources).lookup('config-node.properties', [('localnode', 'host')])[0]

	if is_ip_address(hostname):
		if enable_https:
			raise RuntimeError(f'hostname {hostname} looks like IP address and not a hostname and `apiHttps` is set to true')
	else:
		require_hostname(hostname)

	preparer.configure_https()
	return hostname


async def _prepare_keys_and_certificates(config, preparer, ca_key_path):
	# detect the current finalization epoch
	current_finalization_epoch = await get_current_finalization_epoch(config.services.nodewatch, preparer.config_manager)

	# prepare keys and certificates
	preparer.configure_keys(current_finalization_epoch)
	preparer.generate_certificates(ca_key_path, require_ca=False)


async def _prepare_linking_transaction(preparer, api_endpoint):
	log.info(_('general-connecting-to-node').format(endpoint=api_endpoint))
	connector = SymbolConnector(api_endpoint)

	account_public_key = read_public_key_from_public_key_pem_file(preparer.directories.certificates / 'ca.pubkey.pem')
	existing_links = await connector.account_links(account_public_key)
	if preparer.config.network.name in ('mainnet', 'testnet'):
		if preparer.harvester_configurator.is_imported:
			remote_key_mismatch = existing_links.linked_public_key != preparer.harvester_configurator.remote_key_pair.public_key
			vrf_key_mismatch = existing_links.vrf_public_key != preparer.harvester_configurator.vrf_key_pair.public_key
			if remote_key_mismatch or vrf_key_mismatch:
				raise RuntimeError('imported harvesting keys do not match on-chain links')

		if preparer.voter_configurator.is_imported:
			local_voting_links = {
				(descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch)
				for descriptor in inspect_voting_key_files(preparer.directories.voting_keys)
			}
			chain_voting_links = {
				(link.public_key, link.start_epoch, link.end_epoch)
				for link in existing_links.voting_public_keys
			}
			if local_voting_links != chain_voting_links:
				raise RuntimeError('imported voting keys do not match on-chain links')

	network_time = await connector.network_time()
	transaction = preparer.prepare_linking_transaction(account_public_key, existing_links, network_time.timestamp)

	if transaction:
		write_transaction_to_file(transaction, preparer.directories.output_directory / 'linking_transaction.dat')
	else:
		log.info(_('setup-no-state-changes-required'))


async def run_main(args):
	if 'setup' == getattr(args, 'command', 'setup'):
		# transaction-only は既存の出力を読むため、一時出力への初期化を行わない。
		if args.output_transaction_only:
			await _run_setup(args)
			return
		await _run_initial_setup_atomically(args)
		return

	await _run_setup(args)


async def _run_initial_setup_atomically(args):
	"""初期セットアップを一時ディレクトリで実行してから公開する。"""
	output_directory = Path(args.directory).absolute()
	output_directory.mkdir(parents=True, exist_ok=True)
	managed_paths = ('sakuya', 'docker-compose.yaml', 'docker-compose-recovery.yaml', 'linking_transaction.dat')
	if any((output_directory / path).exists() or (output_directory / path).is_symlink() for path in managed_paths):
		log.error(_('setup-resources-directory-exists').format(directory=output_directory / 'sakuya'))
		sys.exit(1)

	staged_directory = Path(tempfile.mkdtemp(dir=output_directory.parent, prefix='.sakuya-setup-'))
	ca_key_path = Path(args.ca_key_path).absolute()
	if ca_key_path.is_symlink():
		raise RuntimeError(f'CA key path must not be a symbolic link: {ca_key_path}')
	ca_key_was_generated = not ca_key_path.exists()
	ca_key_published = False
	try:
		staged_args = Namespace(**vars(args))
		staged_args.directory = staged_directory
		if ca_key_was_generated:
			staged_args.ca_key_path = staged_directory / ca_key_path.name
		await _run_setup(staged_args)
		if ca_key_was_generated and ca_key_path.parent != output_directory:
			shutil.copy2(staged_args.ca_key_path, ca_key_path)
			ca_key_path.chmod(0o400)
			ca_key_published = True
		elif ca_key_was_generated:
			managed_paths += (ca_key_path.name,)
		replace_paths(staged_directory, output_directory, managed_paths)
		ca_key_path.chmod(0o400)
	except Exception:
		if ca_key_published:
			ca_key_path.unlink(missing_ok=True)
		raise
	finally:
		shutil.rmtree(staged_directory, ignore_errors=True)


async def _run_setup(args):
	config = parse_shoestring_configuration(args.config)
	is_initial_setup = 'setup' == getattr(args, 'command', 'setup')

	if is_initial_setup and args.output_transaction_only:
		log.info(_('setup-status-output-transaction-only'))

		api_endpoint = await find_api_node(config.services.nodewatch)
		preparer = Preparer(Path(args.directory), config, log)
		preparer.load_keys()

		await _prepare_linking_transaction(preparer, api_endpoint)
		return

	with Preparer(Path(args.directory), config, log) as preparer:
		if is_initial_setup and preparer.directories.resources.exists():
			log.error(_('setup-resources-directory-exists').format(directory=preparer.directories.resources))
			sys.exit(1)

		if is_initial_setup:
			# setup basic directories
			preparer.create_subdirectories()

		# download resource package(s) and peers file(s)
		api_endpoints = await download_peers(
			config.services.nodewatch,
			preparer.directories.resources,
			config.node.full_api)
		package_identifier = resolve_package_identifier(args.config, config.network.name)
		await download_and_extract_package(package_identifier, preparer.directories.temp)

		# prepare nemesis data and resources
		if is_initial_setup:
			preparer.prepare_seed()

		preparer.prepare_resources()

		user_patches = {
			'node': [
				('localnode', 'host', 'read or ask 1'),
				('localnode', 'friendlyName', 'read or ask 2')
			]
		}

		if args.overrides and Path(args.overrides).is_file():
			user_patches = load_patches_from_file(args.overrides)

		preparer.configure_resources(user_patches)
		preparer.configure_rest(args.rest_overrides)

		hostname = _resolve_hostname_and_configure_https(config, preparer)

		preparer.configure_docker({
			'catapult_client_image': config.images.client,
			'catapult_rest_image': config.images.rest,
			'mongo_image': config.images.mongo,
			'user': f'{config.node.user_id}:{config.node.group_id}',
			'api_https': config.node.api_https,
			'light_api': NodeFeatures.API in config.node.features and not config.node.full_api,
			'domainname': hostname
		})

		if is_initial_setup:
			# prepare keys and certificates
			await _prepare_keys_and_certificates(config, preparer, args.ca_key_path)

			# generate transaction
			await _prepare_linking_transaction(preparer, api_endpoints[0])


def add_arguments(parser, is_initial_setup=True):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.add_argument('--overrides', help=_('argument-help-setup-overrides'))
	parser.add_argument('--rest-overrides', help=_('argument-help-setup-rest-overrides'))

	if is_initial_setup:
		parser.add_argument('--ca-key-path', help=_('argument-help-ca-key-path'))
		parser.add_argument('--output-transaction-only', help=_('argument-help-setup-output-transaction-only'), action='store_true')
		parser.set_defaults(func=run_main)
