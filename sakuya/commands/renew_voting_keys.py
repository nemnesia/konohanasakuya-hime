import shutil
import tempfile
from pathlib import Path

from symbolchain import sc
from symbolchain.facade.SymbolFacade import SymbolFacade
from symbollightapi.connector.SymbolConnector import SymbolConnector
from zenlog import log

from sakuya.internal.AtomicFileSystem import replace_paths
from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.LinkTransactionBuilder import LinkTransactionBuilder
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.NodewatchClient import get_current_finalization_epoch
from sakuya.internal.PeerDownloader import load_api_endpoints
from sakuya.internal.PemUtils import read_public_key_from_public_key_pem_file
from sakuya.internal.Preparer import Preparer
from sakuya.internal.ShoestringConfiguration import parse_shoestring_configuration
from sakuya.internal.TransactionSerializer import write_transaction_to_file
from sakuya.internal.VoterConfigurator import VoterConfigurator, inspect_voting_key_files


def _load_voting_key_descriptors(directory, current_epoch):
	descriptors = inspect_voting_key_files(directory)
	return (
		[descriptor for descriptor in descriptors if descriptor.end_epoch >= current_epoch],
		[descriptor for descriptor in descriptors if descriptor.end_epoch < current_epoch]
	)


async def _get_network_time(resources_directory):
	api_endpoints = load_api_endpoints(resources_directory)
	if not api_endpoints:
		raise RuntimeError('no API endpoint is available')

	log.info(_('general-connecting-to-node').format(endpoint=api_endpoints[0]))
	return await SymbolConnector(api_endpoints[0]).network_time()


async def _get_account_links(resources_directory, account_public_key):
	api_endpoints = load_api_endpoints(resources_directory)
	if not api_endpoints:
		raise RuntimeError('no API endpoint is available')

	log.info(_('general-connecting-to-node').format(endpoint=api_endpoints[0]))
	return await SymbolConnector(api_endpoints[0]).account_links(account_public_key)


async def _get_transaction_status(resources_directory, transaction_hash):
	api_endpoints = load_api_endpoints(resources_directory)
	if not api_endpoints:
		raise RuntimeError('no API endpoint is available')

	statuses = await SymbolConnector(api_endpoints[0]).transaction_statuses([transaction_hash])
	for status in statuses:
		if str(status.get('hash', '')).lower() == str(transaction_hash).lower():
			return status.get('group'), status.get('code')
	return None, None


async def _save_transaction(transaction_config, resources_directory, output_directory, transaction_builder):
	network_time = await _get_network_time(resources_directory)
	aggregate_transaction, transaction_hash = transaction_builder.build(
		network_time.add_hours(transaction_config.timeout_hours),
		transaction_config.fee_multiplier,
		transaction_config.min_cosignatures_count)

	log.info(_('general-created-aggregate-transaction').format(transaction_hash=transaction_hash))
	write_transaction_to_file(aggregate_transaction, output_directory / 'renew_voting_keys_transaction.dat')


def _read_transaction(filepath):
	with open(filepath, 'rb') as infile:
		return sc.TransactionFactory.deserialize(infile.read())


def _cleanup_descriptors(transaction):
	return {
		(child.linked_public_key, child.start_epoch, child.end_epoch)
		for child in transaction.transactions
		if child.type_ == sc.TransactionType.VOTING_KEY_LINK and child.link_action == sc.LinkAction.UNLINK
	}


def _promote_pending_voting_keys(staged_voting_directory, transaction):
	cleanup_descriptors = _cleanup_descriptors(transaction)
	for descriptor in inspect_voting_key_files(staged_voting_directory):
		if (descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch) in cleanup_descriptors:
			(staged_voting_directory / f'private_key_tree{descriptor.ordinal}.dat').unlink()

	pending_directory = staged_voting_directory / 'pending'
	pending_descriptors = inspect_voting_key_files(pending_directory)
	active_descriptors = inspect_voting_key_files(staged_voting_directory)
	next_ordinal = max((descriptor.ordinal for descriptor in active_descriptors), default=0) + 1
	for descriptor in pending_descriptors:
		shutil.move(
			pending_directory / f'private_key_tree{descriptor.ordinal}.dat',
			staged_voting_directory / f'private_key_tree{next_ordinal}.dat')
		next_ordinal += 1
	shutil.rmtree(pending_directory)


async def _resolve_pending(config, directories, transaction_path, pending_directory):
	pending_descriptors = inspect_voting_key_files(pending_directory)
	if not pending_descriptors or not transaction_path.is_file():
		raise RuntimeError('pending voting key and transaction must exist together')

	transaction = _read_transaction(transaction_path)
	transaction_hash = SymbolFacade(config.network).hash_transaction(transaction)
	status, code = await _get_transaction_status(directories.resources, transaction_hash)
	if 'confirmed' == status:
		staged_directory = Path(tempfile.mkdtemp(dir=directories.output_directory.parent, prefix='.sakuya-voting-confirmed-'))
		try:
			staged_voting_directory = staged_directory / 'sakuya/keys/voting'
			shutil.copytree(directories.voting_keys, staged_voting_directory)
			_promote_pending_voting_keys(staged_voting_directory, transaction)
			replace_paths(staged_directory, directories.output_directory, ('sakuya/keys/voting',))
		finally:
			shutil.rmtree(staged_directory, ignore_errors=True)
		return

	if 'failed' == status:
		staged_directory = Path(tempfile.mkdtemp(dir=directories.output_directory.parent, prefix='.sakuya-voting-failed-'))
		try:
			staged_voting_directory = staged_directory / 'sakuya/keys/voting'
			shutil.copytree(directories.voting_keys, staged_voting_directory)
			shutil.rmtree(staged_voting_directory / 'pending')
			replace_paths(staged_directory, directories.output_directory, ('sakuya/keys/voting',))
		finally:
			shutil.rmtree(staged_directory, ignore_errors=True)
		log.error(f'pending voting key transaction failed: {code or "unknown"}')
		return

	log.warning(_('renew-voting-keys-pending'))


async def run_main(args):
	config = parse_shoestring_configuration(args.config)

	if NodeFeatures.VOTER not in config.node.features:
		log.error(_('renew-voting-keys-not-voting'))
		return

	directories = Preparer.DirectoryLocator(None, Path(args.directory).absolute())
	config_manager = ConfigurationManager(directories.resources)
	pending_directory = directories.voting_keys / 'pending'
	transaction_path = directories.output_directory / 'renew_voting_keys_transaction.dat'
	if pending_directory.is_symlink() or transaction_path.is_symlink():
		raise RuntimeError('pending voting key paths must not be symbolic links')
	pending_exists = pending_directory.exists()

	if pending_exists:
		await _resolve_pending(config, directories, transaction_path, pending_directory)
		return

	if transaction_path.exists():
		terminal_transaction = _read_transaction(transaction_path)
		status, _status_code = await _get_transaction_status(
			directories.resources, SymbolFacade(config.network).hash_transaction(terminal_transaction))
		if status not in ('confirmed', 'failed'):
			raise RuntimeError('existing voting key transaction is still pending')

	current_finalization_epoch = await get_current_finalization_epoch(config.services.nodewatch, config_manager)
	(active_voting_key_descriptors, _inactive_voting_key_descriptors) = _load_voting_key_descriptors(
		directories.voting_keys, current_finalization_epoch)
	if not active_voting_key_descriptors:
		log.warning(_('renew-voting-keys-no-voting-keys-found'))

	max_voting_keys_per_account = int(config_manager.lookup('config-network.properties', [('chain', 'maxVotingKeysPerAccount')])[0])
	account_public_key = read_public_key_from_public_key_pem_file(directories.certificates / 'ca.pubkey.pem')
	if config.network.name in ('mainnet', 'testnet'):
		existing_links = await _get_account_links(directories.resources, account_public_key)
		active_registered_keys = [
			link for link in existing_links.voting_public_keys if link.end_epoch >= current_finalization_epoch
		]
		local_descriptors = {
			(descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch)
			for descriptor in inspect_voting_key_files(directories.voting_keys)
		}
		cleanup_descriptors = [
			(link.public_key, link.start_epoch, link.end_epoch)
			for link in existing_links.voting_public_keys
			if link.end_epoch < current_finalization_epoch and (link.public_key, link.start_epoch, link.end_epoch) in local_descriptors
		]
	else:
		# private/custom networkはオンチェーン検証を行わず、Shoestring同様ローカル鍵を基準にする。
		active_registered_keys = active_voting_key_descriptors
		cleanup_descriptors = [
			(descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch)
			for descriptor in inspect_voting_key_files(directories.voting_keys)
			if descriptor.end_epoch < current_finalization_epoch
		]
	if len(active_registered_keys) >= max_voting_keys_per_account:
		log.error(_('renew-voting-keys-maximum-already-registered'))
		return

	transaction_builder = LinkTransactionBuilder(account_public_key, config.network)
	for public_key, start_epoch, end_epoch in sorted(
		cleanup_descriptors, key=lambda descriptor: (descriptor[1], descriptor[2], str(descriptor[0]))):
		transaction_builder.unlink_voting_public_key(public_key, start_epoch, end_epoch)

	staged_directory = Path(tempfile.mkdtemp(dir=directories.output_directory.parent, prefix='.sakuya-voting-'))
	try:
		staged_voting_keys = staged_directory / 'sakuya/keys/voting'
		shutil.copytree(directories.voting_keys, staged_voting_keys)
		pending_directory = staged_voting_keys / 'pending'
		pending_directory.mkdir()
		voter_configurator = VoterConfigurator(config_manager)
		new_epoch_range = voter_configurator.generate_voting_key_file(pending_directory, current_finalization_epoch)
		transaction_builder.link_voting_public_key(voter_configurator.voting_public_key, *new_epoch_range)
		await _save_transaction(config.transaction, directories.resources, staged_directory, transaction_builder)
		replace_paths(staged_directory, directories.output_directory, ('sakuya/keys/voting', 'renew_voting_keys_transaction.dat'))
	finally:
		shutil.rmtree(staged_directory, ignore_errors=True)


def add_arguments(parser):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
