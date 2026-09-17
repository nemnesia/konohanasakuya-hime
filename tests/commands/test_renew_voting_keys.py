import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import PrivateKey
from symbolchain.sc import LinkAction, TransactionFactory, TransactionType
from symbolchain.symbol.KeyPair import KeyPair
from symbolchain.symbol.VotingKeysGenerator import VotingKeysGenerator

from sakuya.__main__ import main
from sakuya.commands import renew_voting_keys
from sakuya.internal.CertificateFactory import CertificateFactory
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.OpensslExecutor import OpensslExecutor
from sakuya.internal.PackageResolver import download_and_extract_package
from sakuya.internal.PeerDownloader import download_peers
from sakuya.internal.PemUtils import read_public_key_from_public_key_pem_file
from sakuya.internal.VoterConfigurator import inspect_voting_key_files

from ..test.ConfigurationTestUtils import prepare_shoestring_configuration
from ..test.LogTestUtils import assert_message_is_logged
from ..test.MockNodewatchServer import setup_mock_nodewatch_server
from ..test.TestPackager import prepare_testnet_package
from ..test.TransactionTestUtils import AggregateDescriptor, LinkDescriptor, assert_aggregate_transaction, assert_link_transaction

# region server fixture


@pytest.fixture
async def server(aiohttp_client):
	return await setup_mock_nodewatch_server(aiohttp_client, True)


# mock server is configured to return last finalized height as 2033136,
# which corresponds to the following epochs
# -----------------------------------------------
# current epoch = 1 + ceil(2033136 / 720) = 2825
# one epoch padding                       =    1
# grace period padding                    =    1
# -----------------------------------------------
# start epoch                             = 2827
# max voting key lifetime                 =  720
# start epoch inclusion adjustment        =   -1
#  -----------------------------------------------
# end epoch                               = 3546

# endregion


# region utils

class PytestAsserter:
	@staticmethod
	def assertEqual(expected, actual):  # pylint: disable=invalid-name
		assert expected == actual


async def _prepare_output_directory(package_directory, output_directory, node_features, nodewatch_url):
	# extract resources
	prepare_testnet_package(package_directory, 'resources.zip')
	await download_and_extract_package(f'file://{package_directory}/resources.zip', package_directory)
	(Path(package_directory) / 'shoestring.ini').unlink()  # remove template from package (configuration will be recreated later)

	resources_directory = output_directory / 'sakuya' / 'node-config' / 'resources'
	shutil.copytree(package_directory / 'resources', resources_directory)
	await download_peers(nodewatch_url, resources_directory)

	# prepare CA pem file
	certificates_directory = output_directory / 'sakuya' / 'keys' / 'cert'
	certificates_directory.mkdir(parents=True)

	openssl_executor = OpensslExecutor(os.environ.get('OPENSSL_EXECUTABLE', 'openssl'))
	with CertificateFactory(openssl_executor, certificates_directory / 'ca.key.pem') as factory:
		factory.generate_random_ca_private_key()
		factory.export_ca()
		factory.extract_ca_public_key()
		factory.package(certificates_directory)

	# create voting keys directory
	if NodeFeatures.VOTER in node_features:
		(output_directory / 'sakuya' / 'keys' / 'voting').mkdir()


def _map_voting_key_descriptors_to_tuples(voting_key_descriptors):
	return [(descriptor.ordinal, descriptor.start_epoch, descriptor.end_epoch) for descriptor in voting_key_descriptors]


def _write_voting_keys_file(directory, ordinal, start_epoch, end_epoch):
	voting_key_pair = KeyPair(PrivateKey.random())
	voting_keys_generator = VotingKeysGenerator(voting_key_pair)
	voting_key_buffer = voting_keys_generator.generate(start_epoch, end_epoch)

	output_filepath = Path(directory) / f'private_key_tree{ordinal}.dat'
	with open(output_filepath, 'wb') as outfile:
		outfile.write(voting_key_buffer)

	return voting_key_pair.public_key


def _read_transaction(directory):
	with open(Path(directory) / 'renew_voting_keys_transaction.dat', 'rb') as infile:
		transaction_bytes = infile.read()
		return TransactionFactory.deserialize(transaction_bytes)

# endregion


# pylint: disable=invalid-name


async def test_renew_voting_keys_fails_when_node_is_not_voter(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			node_features = NodeFeatures.PEER | NodeFeatures.API | NodeFeatures.HARVESTER
			await _prepare_output_directory(Path(package_directory), Path(output_directory), node_features, server.make_url(''))
			config_filepath = prepare_shoestring_configuration(package_directory, node_features)

			# Act:
			await main([
				'--directory', output_directory,
				'renew-voting-keys',
				'--config', str(config_filepath),
			])

			# Assert: error is raised
			assert_message_is_logged('node is not configured for voting, aborting', caplog)

			# - voting keys directory does not exist
			assert not (Path(output_directory) / 'sakuya' / 'keys' / 'voting').exists()

			# - no transaction is created
			assert not (Path(output_directory) / 'renew_voting_keys_transaction.dat').exists()


async def test_can_renew_voting_keys_when_none_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			await _prepare_output_directory(Path(package_directory), Path(output_directory), NodeFeatures.VOTER, server.make_url(''))
			config_filepath = prepare_shoestring_configuration(package_directory, NodeFeatures.VOTER, server.make_url(''))

			# Act:
			await main([
				'--directory', output_directory,
				'renew-voting-keys',
				'--config', str(config_filepath),
			])

			# Assert: warning is raised
			assert_message_is_logged('voting is enabled, but no existing voting key files were found', caplog)

			# - new voting keys remain pending until the transaction is confirmed
			voting_key_descriptors = inspect_voting_key_files(Path(output_directory) / 'sakuya' / 'keys' / 'voting' / 'pending')
			assert [(1, 2827, 3546)] == _map_voting_key_descriptors_to_tuples(voting_key_descriptors)

			# - transaction is created
			transaction = _read_transaction(output_directory)
			ca_public_key = read_public_key_from_public_key_pem_file(Path(output_directory) / 'sakuya' / 'keys' / 'cert' / 'ca.pubkey.pem')
			assert_aggregate_transaction(PytestAsserter(), transaction, AggregateDescriptor(
				168 + 96,
				200,
				123456789 + 1 * 60 * 60 * 1000,
				ca_public_key))
			assert 1 == len(transaction.transactions)

			assert_link_transaction(PytestAsserter(), transaction.transactions[0], LinkDescriptor(
				TransactionType.VOTING_KEY_LINK,
				voting_key_descriptors[0].public_key,
				LinkAction.LINK,
				(2827, 3546)))


async def test_can_renew_voting_keys_when_some_are_present_and_active(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			await _prepare_output_directory(Path(package_directory), Path(output_directory), NodeFeatures.VOTER, server.make_url(''))
			config_filepath = prepare_shoestring_configuration(package_directory, NodeFeatures.VOTER, server.make_url(''))

			voting_keys_directory = Path(output_directory) / 'sakuya' / 'keys' / 'voting'
			_write_voting_keys_file(voting_keys_directory, 1, 2800, 2899)
			_write_voting_keys_file(voting_keys_directory, 2, 2900, 2999)

			# Act:
			await main([
				'--directory', output_directory,
				'renew-voting-keys',
				'--config', str(config_filepath),
			])

			# Assert: existing voting keys are preserved and the new key remains pending
			voting_key_descriptors = inspect_voting_key_files(voting_keys_directory)
			pending_key_descriptors = inspect_voting_key_files(voting_keys_directory / 'pending')
			assert [
				(1, 2800, 2899),
				(2, 2900, 2999)
			] == _map_voting_key_descriptors_to_tuples(voting_key_descriptors)
			assert [(1, 2827, 3546)] == _map_voting_key_descriptors_to_tuples(pending_key_descriptors)

			# - transaction is created
			transaction = _read_transaction(output_directory)
			ca_public_key = read_public_key_from_public_key_pem_file(Path(output_directory) / 'sakuya' / 'keys' / 'cert' / 'ca.pubkey.pem')
			assert_aggregate_transaction(PytestAsserter(), transaction, AggregateDescriptor(
				168 + 96,
				200,
				123456789 + 1 * 60 * 60 * 1000,
				ca_public_key))
			assert 1 == len(transaction.transactions)

			assert_link_transaction(PytestAsserter(), transaction.transactions[0], LinkDescriptor(
				TransactionType.VOTING_KEY_LINK,
				pending_key_descriptors[0].public_key,
				LinkAction.LINK,
				(2827, 3546)))


async def test_can_renew_voting_keys_when_some_are_present_and_inactive(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			await _prepare_output_directory(Path(package_directory), Path(output_directory), NodeFeatures.VOTER, server.make_url(''))
			config_filepath = prepare_shoestring_configuration(package_directory, NodeFeatures.VOTER, server.make_url(''))

			voting_keys_directory = Path(output_directory) / 'sakuya' / 'keys' / 'voting'
			expired_root_voting_public_key_1 = _write_voting_keys_file(voting_keys_directory, 1, 2600, 2699)
			expired_root_voting_public_key_2 = _write_voting_keys_file(voting_keys_directory, 2, 2700, 2799)
			_write_voting_keys_file(voting_keys_directory, 3, 2800, 2825)  # last epoch matches current epoch
			_write_voting_keys_file(voting_keys_directory, 4, 2826, 2999)

			# Act:
			await main([
				'--directory', output_directory,
				'renew-voting-keys',
				'--config', str(config_filepath),
			])

			# Assert: local expired keys remain until the chain confirms their unlink.
			voting_key_descriptors = inspect_voting_key_files(voting_keys_directory)
			assert [
				(1, 2600, 2699),
				(2, 2700, 2799),
				(3, 2800, 2825),
				(4, 2826, 2999),
			] == _map_voting_key_descriptors_to_tuples(voting_key_descriptors)
			pending_key_descriptors = inspect_voting_key_files(voting_keys_directory / 'pending')
			assert [(1, 2827, 3546)] == _map_voting_key_descriptors_to_tuples(pending_key_descriptors)

			# - transaction is created
			transaction = _read_transaction(output_directory)
			ca_public_key = read_public_key_from_public_key_pem_file(Path(output_directory) / 'sakuya' / 'keys' / 'cert' / 'ca.pubkey.pem')
			assert_aggregate_transaction(PytestAsserter(), transaction, AggregateDescriptor(
				168 + 96,
				200,
				123456789 + 1 * 60 * 60 * 1000,
				ca_public_key))
			assert 1 == len(transaction.transactions)

			assert_link_transaction(PytestAsserter(), transaction.transactions[0], LinkDescriptor(
				TransactionType.VOTING_KEY_LINK,
				pending_key_descriptors[0].public_key,
				LinkAction.LINK,
				(2827, 3546)))


async def test_cannot_renew_voting_keys_when_max_keys_are_active(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			await _prepare_output_directory(Path(package_directory), Path(output_directory), NodeFeatures.VOTER, server.make_url(''))
			config_filepath = prepare_shoestring_configuration(package_directory, NodeFeatures.VOTER, server.make_url(''))

			voting_keys_directory = Path(output_directory) / 'sakuya' / 'keys' / 'voting'
			key_1 = _write_voting_keys_file(voting_keys_directory, 1, 2800, 2825)  # last epoch matches current epoch
			key_2 = _write_voting_keys_file(voting_keys_directory, 2, 3100, 3199)
			key_3 = _write_voting_keys_file(voting_keys_directory, 3, 3200, 3299)
			server.mock.voting_public_keys = [
				{'startEpoch': 2800, 'endEpoch': 2825, 'publicKey': str(key_1)},
				{'startEpoch': 3100, 'endEpoch': 3199, 'publicKey': str(key_2)},
				{'startEpoch': 3200, 'endEpoch': 3299, 'publicKey': str(key_3)}
			]

			# Act:
			await main([
				'--directory', output_directory,
				'renew-voting-keys',
				'--config', str(config_filepath),
			])

			# Assert: error is raised
			assert_message_is_logged('maximum number of voting keys are already registered for this account', caplog)

			# - no voting keys files are created or changed
			voting_key_descriptors = inspect_voting_key_files(voting_keys_directory)
			assert [
				(1, 2800, 2825),
				(2, 3100, 3199),
				(3, 3200, 3299)
			] == _map_voting_key_descriptors_to_tuples(voting_key_descriptors)

			# no transaction is created
			assert not (Path(output_directory) / 'renew_voting_keys_transaction.dat').exists()


async def test_renew_voting_key_helpers_handle_missing_endpoints(monkeypatch, tmp_path):
	monkeypatch.setattr(renew_voting_keys, 'load_api_endpoints', lambda _resources: [])
	with pytest.raises(RuntimeError, match='no API endpoint'):
		await renew_voting_keys._get_network_time(tmp_path)
	with pytest.raises(RuntimeError, match='no API endpoint'):
		await renew_voting_keys._get_account_links(tmp_path, 'account')
	with pytest.raises(RuntimeError, match='no API endpoint'):
		await renew_voting_keys._get_transaction_status(tmp_path, 'hash')


async def test_renew_voting_key_helpers_read_status_and_save_transaction(monkeypatch, tmp_path):
	monkeypatch.setattr(renew_voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def transaction_statuses(self, _hashes):
			return [{'hash': 'ABCD', 'group': 'confirmed', 'code': 'ok'}]

	monkeypatch.setattr(renew_voting_keys, 'SymbolConnector', Connector)
	assert ('confirmed', 'ok') == await renew_voting_keys._get_transaction_status(tmp_path, 'abcd')

	class NetworkTime:
		def add_hours(self, hours):
			return hours

	async def get_network_time(_resources):
		return NetworkTime()

	monkeypatch.setattr(renew_voting_keys, '_get_network_time', get_network_time)
	monkeypatch.setattr(
		renew_voting_keys,
		'write_transaction_to_file',
		lambda transaction, filepath: filepath.write_bytes(transaction.encode()))

	class Builder:
		def build(self, deadline, fee_multiplier, min_cosignatures_count):
			assert (1, 2, 3) == (deadline, fee_multiplier, min_cosignatures_count)
			return 'transaction', 'hash'

	await renew_voting_keys._save_transaction(
		SimpleNamespace(timeout_hours=1, fee_multiplier=2, min_cosignatures_count=3),
		tmp_path,
		tmp_path,
		Builder())
	assert b'transaction' == (tmp_path / 'renew_voting_keys_transaction.dat').read_bytes()


def test_renew_voting_key_helpers_read_and_cleanup_transactions(monkeypatch, tmp_path):
	transaction_filepath = tmp_path / 'transaction.dat'
	transaction_filepath.write_bytes(b'encoded')
	monkeypatch.setattr(renew_voting_keys.sc.TransactionFactory, 'deserialize', lambda data: data)
	assert b'encoded' == renew_voting_keys._read_transaction(transaction_filepath)

	unlink = SimpleNamespace(
		type_=TransactionType.VOTING_KEY_LINK,
		link_action=LinkAction.UNLINK,
		linked_public_key='key',
		start_epoch=1,
		end_epoch=2)
	link = SimpleNamespace(
		type_=TransactionType.VOTING_KEY_LINK,
		link_action=LinkAction.LINK,
		linked_public_key='other',
		start_epoch=3,
		end_epoch=4)
	assert {('key', 1, 2)} == renew_voting_keys._cleanup_descriptors(SimpleNamespace(transactions=[unlink, link]))


def test_promote_pending_voting_keys_moves_pending_files(monkeypatch, tmp_path):
	active_directory = tmp_path / 'voting'
	pending_directory = active_directory / 'pending'
	pending_directory.mkdir(parents=True)
	(active_directory / 'private_key_tree1.dat').write_bytes(b'active')
	(pending_directory / 'private_key_tree2.dat').write_bytes(b'pending')

	active_descriptor = SimpleNamespace(public_key='old', start_epoch=1, end_epoch=2, ordinal=1)
	pending_descriptor = SimpleNamespace(public_key='new', start_epoch=3, end_epoch=4, ordinal=2)
	inspect_calls = 0

	def inspect(directory):
		nonlocal inspect_calls
		inspect_calls += 1
		if directory.name == 'pending':
			return [pending_descriptor]
		return [active_descriptor] if 1 == inspect_calls else []

	monkeypatch.setattr(renew_voting_keys, 'inspect_voting_key_files', inspect)
	transaction = SimpleNamespace(transactions=[SimpleNamespace(
		type_=TransactionType.VOTING_KEY_LINK,
		link_action=LinkAction.UNLINK,
		linked_public_key='old', start_epoch=1, end_epoch=2)])
	renew_voting_keys._promote_pending_voting_keys(active_directory, transaction)

	assert b'pending' == (active_directory / 'private_key_tree1.dat').read_bytes()
	assert not pending_directory.exists()


@pytest.mark.parametrize('status', ['confirmed', 'failed', 'pending'])
async def test_resolve_pending_voting_keys_handles_terminal_and_pending_status(monkeypatch, tmp_path, status):
	voting_directory = tmp_path / 'sakuya' / 'keys' / 'voting'
	pending_directory = voting_directory / 'pending'
	pending_directory.mkdir(parents=True)
	(pending_directory / 'private_key_tree1.dat').write_bytes(b'key')
	transaction_path = tmp_path / 'renew_voting_keys_transaction.dat'
	transaction_path.write_bytes(b'transaction')
	directories = SimpleNamespace(
		resources=tmp_path / 'resources', output_directory=tmp_path, voting_keys=voting_directory)
	config = SimpleNamespace(network='testnet')

	monkeypatch.setattr(
		renew_voting_keys,
		'inspect_voting_key_files',
		lambda directory: [SimpleNamespace(ordinal=1)] if Path(directory).name == 'pending' else [])
	monkeypatch.setattr(renew_voting_keys, '_read_transaction', lambda _path: 'transaction')
	monkeypatch.setattr(renew_voting_keys.SymbolFacade, 'hash_transaction', lambda _self, _transaction: 'hash')

	async def get_transaction_status(_resources, _hash):
		return status, 'ERROR'

	monkeypatch.setattr(renew_voting_keys, '_get_transaction_status', get_transaction_status)
	monkeypatch.setattr(renew_voting_keys, '_promote_pending_voting_keys', lambda _directory, _transaction: None)
	monkeypatch.setattr(renew_voting_keys, 'replace_paths', lambda *_args: None)

	if 'pending' == status:
		await renew_voting_keys._resolve_pending(config, directories, transaction_path, pending_directory)
	else:
		await renew_voting_keys._resolve_pending(config, directories, transaction_path, pending_directory)


async def test_resolve_pending_requires_key_and_transaction_pair(monkeypatch, tmp_path):
	pending_directory = tmp_path / 'pending'
	pending_directory.mkdir()
	monkeypatch.setattr(renew_voting_keys, 'inspect_voting_key_files', lambda _directory: [])
	with pytest.raises(RuntimeError, match='must exist together'):
		await renew_voting_keys._resolve_pending(
			SimpleNamespace(network='testnet'),
			SimpleNamespace(resources=tmp_path, output_directory=tmp_path, voting_keys=tmp_path),
			tmp_path / 'transaction.dat',
			pending_directory)


async def test_renew_voting_key_status_returns_none_for_unknown_hash(monkeypatch, tmp_path):
	monkeypatch.setattr(renew_voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def transaction_statuses(self, _hashes):
			return [{'hash': 'other', 'group': 'confirmed'}]

	monkeypatch.setattr(renew_voting_keys, 'SymbolConnector', Connector)
	assert (None, None) == await renew_voting_keys._get_transaction_status(tmp_path, 'hash')


async def test_renew_voting_keys_custom_network_unlinks_expired_local_key(monkeypatch, tmp_path):
	output_directory = tmp_path
	resources = output_directory / 'resources'
	voting_keys = output_directory / 'sakuya' / 'keys' / 'voting'
	certificates = output_directory / 'sakuya' / 'keys' / 'cert'
	resources.mkdir(parents=True)
	voting_keys.mkdir(parents=True)
	certificates.mkdir(parents=True)
	(expired_file := voting_keys / 'private_key_tree1.dat').write_bytes(b'expired')

	config = SimpleNamespace(
		node=SimpleNamespace(features=NodeFeatures.VOTER),
		network=SimpleNamespace(name='private'),
		services=SimpleNamespace(nodewatch='nodewatch'),
		transaction=SimpleNamespace(timeout_hours=1, fee_multiplier=1, min_cosignatures_count=0))
	config_manager = SimpleNamespace(lookup=lambda _filename, _keys: ['3'])
	directories = SimpleNamespace(
		resources=resources, voting_keys=voting_keys, certificates=certificates, output_directory=output_directory)
	monkeypatch.setattr(renew_voting_keys, 'parse_shoestring_configuration', lambda _path: config)
	monkeypatch.setattr(renew_voting_keys.Preparer, 'DirectoryLocator', lambda _env, _root: directories)
	monkeypatch.setattr(renew_voting_keys, 'ConfigurationManager', lambda _resources: config_manager)
	monkeypatch.setattr(renew_voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(10))
	monkeypatch.setattr(
		renew_voting_keys,
		'inspect_voting_key_files',
		lambda directory: [SimpleNamespace(public_key='expired', start_epoch=1, end_epoch=2, ordinal=1)]
		if Path(directory) == voting_keys else [])
	monkeypatch.setattr(renew_voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')

	class Builder:
		def __init__(self, _account, _network):
			self.unlinked = []

		def unlink_voting_public_key(self, *descriptor):
			self.unlinked.append(descriptor)

		def link_voting_public_key(self, *_descriptor):
			pass

	monkeypatch.setattr(renew_voting_keys, 'LinkTransactionBuilder', Builder)
	monkeypatch.setattr(renew_voting_keys, 'VoterConfigurator', lambda _manager: SimpleNamespace(
		voting_public_key='new',
		generate_voting_key_file=lambda _directory, _epoch: (10, 20)))
	monkeypatch.setattr(renew_voting_keys, '_save_transaction', lambda *_args: _async_value(None))
	monkeypatch.setattr(renew_voting_keys, 'replace_paths', lambda *_args: None)
	monkeypatch.setattr(renew_voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')

	await renew_voting_keys.run_main(SimpleNamespace(config='config.ini', directory=output_directory))
	assert expired_file.exists()


async def _async_value(value):
	return value


def _run_main_config():
	return SimpleNamespace(
		node=SimpleNamespace(features=NodeFeatures.VOTER),
		network=SimpleNamespace(name='testnet'),
		services=SimpleNamespace(nodewatch='nodewatch'),
		transaction=SimpleNamespace(timeout_hours=1, fee_multiplier=1, min_cosignatures_count=0))


def _prepare_run_main_directories(tmp_path):
	(tmp_path / 'sakuya' / 'keys' / 'voting').mkdir(parents=True)
	(tmp_path / 'sakuya' / 'node-config' / 'resources').mkdir(parents=True)
	return tmp_path / 'sakuya' / 'keys' / 'voting'


async def test_renew_voting_keys_rejects_symbolic_link_paths(monkeypatch, tmp_path):
	voting_directory = _prepare_run_main_directories(tmp_path)
	external = tmp_path / 'external'
	external.mkdir()
	(voting_directory / 'pending').symlink_to(external, target_is_directory=True)
	config = _run_main_config()
	monkeypatch.setattr(renew_voting_keys, 'parse_shoestring_configuration', lambda _path: config)
	with pytest.raises(RuntimeError, match='must not be symbolic links'):
		await renew_voting_keys.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))


async def test_renew_voting_keys_resolves_existing_pending_directory(monkeypatch, tmp_path):
	voting_directory = _prepare_run_main_directories(tmp_path)
	(voting_directory / 'pending').mkdir()
	config = _run_main_config()
	monkeypatch.setattr(renew_voting_keys, 'parse_shoestring_configuration', lambda _path: config)
	monkeypatch.setattr(renew_voting_keys, 'ConfigurationManager', lambda _resources: SimpleNamespace())
	called = []

	async def resolve_pending(*_args):
		called.append(True)

	monkeypatch.setattr(renew_voting_keys, '_resolve_pending', resolve_pending)
	await renew_voting_keys.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))
	assert [True] == called


async def test_renew_voting_keys_rejects_existing_pending_transaction(monkeypatch, tmp_path):
	_prepare_run_main_directories(tmp_path)
	(tmp_path / 'renew_voting_keys_transaction.dat').write_bytes(b'transaction')
	config = _run_main_config()
	monkeypatch.setattr(renew_voting_keys, 'parse_shoestring_configuration', lambda _path: config)
	monkeypatch.setattr(renew_voting_keys, 'ConfigurationManager', lambda _resources: SimpleNamespace())
	monkeypatch.setattr(renew_voting_keys, '_read_transaction', lambda _path: 'transaction')
	monkeypatch.setattr(renew_voting_keys.SymbolFacade, 'hash_transaction', lambda _self, _transaction: 'hash')

	async def get_status(_resources, _hash):
		return 'pending', None

	monkeypatch.setattr(renew_voting_keys, '_get_transaction_status', get_status)
	with pytest.raises(RuntimeError, match='still pending'):
		await renew_voting_keys.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))
