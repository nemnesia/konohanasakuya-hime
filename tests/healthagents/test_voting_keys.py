import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import Hash256, PrivateKey
from symbolchain.symbol.KeyPair import KeyPair
from symbolchain.symbol.Network import Network
from symbolchain.symbol.VotingKeysGenerator import VotingKeysGenerator

from sakuya.healthagents import voting_keys
from sakuya.healthagents.voting_keys import should_run, validate
from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import NodeConfiguration, SakuyaConfiguration, ServicesConfiguration
from sakuya.internal.VoterConfigurator import inspect_voting_key_files

from ..test.LogTestUtils import LogLevel, assert_all_messages_are_logged, assert_max_log_level
from ..test.MockNodewatchServer import setup_mock_nodewatch_server

# region server fixture


@pytest.fixture
async def server(aiohttp_client):
	return await setup_mock_nodewatch_server(aiohttp_client, True)

# endregion


# pylint: disable=invalid-name


# region should_run

def test_should_run_for_voter_role():
	# Act + Assert:
	assert should_run(NodeConfiguration(NodeFeatures.VOTER, *([None] * 7)))

	for features in (NodeFeatures.PEER, NodeFeatures.API, NodeFeatures.HARVESTER):
		assert not should_run(NodeConfiguration(features, *([None] * 7))), str(features)

# endregion


# region validate

def _assert_all_messages_are_logged(expected_messages, caplog):
	assert_all_messages_are_logged([
		'detected last finalized height as 2033136',
		'detected current finalization epoch as 2825'
	] + expected_messages, caplog)


def _prepare_directory(output_directory):
	directories = Preparer.DirectoryLocator(None, Path(output_directory))
	directories.resources.mkdir(parents=True)
	directories.voting_keys.mkdir(parents=True)

	with open(directories.resources / 'config-network.properties', 'wt', encoding='utf8') as outfile:
		outfile.write('\n'.join([
			'[chain]',
			'',
			'votingSetGrouping = 720'
		]))

	return directories


def _write_voting_keys_file(directory, ordinal, start_epoch, end_epoch):
	voting_keys_generator = VotingKeysGenerator(KeyPair(PrivateKey.random()))
	voting_key_buffer = voting_keys_generator.generate(start_epoch, end_epoch)

	output_filepath = directory / f'private_key_tree{ordinal}.dat'
	with open(output_filepath, 'wb') as outfile:
		outfile.write(voting_key_buffer)

	output_filepath.chmod(0o600)


async def _dispatch_validate(directories, server):  # pylint: disable=redefined-outer-name
	# Arrange:
	async def account_links(_connector, _account_public_key):
		return SimpleNamespace(voting_public_keys=[
			SimpleNamespace(
				public_key=descriptor.public_key,
				start_epoch=descriptor.start_epoch,
				end_epoch=descriptor.end_epoch
			)
			for descriptor in inspect_voting_key_files(directories.voting_keys)
		])

	original_account_links = voting_keys.SymbolConnector.account_links
	original_read_public_key = voting_keys.read_public_key_from_public_key_pem_file
	original_load_api_endpoints = voting_keys.load_api_endpoints
	voting_keys.SymbolConnector.account_links = account_links
	voting_keys.read_public_key_from_public_key_pem_file = lambda _path: KeyPair(PrivateKey.random()).public_key
	voting_keys.load_api_endpoints = lambda _resources: [server.make_url('')]

	context = SimpleNamespace(
		config_manager=ConfigurationManager(directories.resources),
		directories=directories,
		config=SakuyaConfiguration(
			Network('testnet', 0x98, datetime.fromtimestamp(1615853185, timezone.utc), Hash256.zero()),
			None,
			ServicesConfiguration(server.make_url('')),
			None,
			None,
			None),
		failed=False)

	# Act:
	try:
		await validate(context)
	finally:
		voting_keys.SymbolConnector.account_links = original_account_links
		voting_keys.read_public_key_from_public_key_pem_file = original_read_public_key
		voting_keys.load_api_endpoints = original_load_api_endpoints


async def test_validate_fails_when_past_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2725, 2824)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'expired voting keys discovered for epochs 2725 to 2824',
			'no voting keys are registered for the current epoch 2825'
		], caplog)
		assert_max_log_level(LogLevel.ERROR, caplog)


async def test_validate_warns_when_past_and_current_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2725, 2824)
		_write_voting_keys_file(directories.voting_keys, 2, 2825, 2924)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'expired voting keys discovered for epochs 2725 to 2824',
			'active voting keys discovered for epochs 2825 to 2924',
			'voting keys are registered from the current epoch 2825 until epoch 2924'
		], caplog)
		assert_max_log_level(LogLevel.WARNING, caplog)


async def test_validate_passes_when_current_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2825, 2924)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'active voting keys discovered for epochs 2825 to 2924',
			'voting keys are registered from the current epoch 2825 until epoch 2924'
		], caplog)
		assert_max_log_level(LogLevel.INFO, caplog)


async def test_validate_fails_when_future_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2925, 3024)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'future voting keys discovered for epochs 2925 to 3024',
			'no voting keys are registered for the current epoch 2825'
		], caplog)
		assert_max_log_level(LogLevel.ERROR, caplog)


async def test_validate_passes_when_current_and_future_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2825, 2924)
		_write_voting_keys_file(directories.voting_keys, 2, 2925, 3024)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'active voting keys discovered for epochs 2825 to 2924',
			'future voting keys discovered for epochs 2925 to 3024',
			'voting keys are registered from the current epoch 2825 until epoch 3024'
		], caplog)
		assert_max_log_level(LogLevel.INFO, caplog)


async def test_validate_fails_when_past_and_future_voting_keys_are_present(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2725, 2824)
		_write_voting_keys_file(directories.voting_keys, 2, 2925, 3024)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'expired voting keys discovered for epochs 2725 to 2824',
			'future voting keys discovered for epochs 2925 to 3024',
			'no voting keys are registered for the current epoch 2825'
		], caplog)
		assert_max_log_level(LogLevel.ERROR, caplog)


async def test_validate_passes_when_current_and_future_voting_keys_are_present_gaps(server, caplog):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		directories = _prepare_directory(output_directory)
		_write_voting_keys_file(directories.voting_keys, 1, 2825, 2924)
		_write_voting_keys_file(directories.voting_keys, 2, 2925, 3024)
		_write_voting_keys_file(directories.voting_keys, 3, 3026, 3124)  # note the gap
		_write_voting_keys_file(directories.voting_keys, 4, 3125, 3224)

		# Act:
		await _dispatch_validate(directories, server)

		# Assert:
		_assert_all_messages_are_logged([
			'active voting keys discovered for epochs 2825 to 2924',
			'future voting keys discovered for epochs 2925 to 3024',
			'future voting keys discovered for epochs 3026 to 3124',
			'future voting keys discovered for epochs 3125 to 3224',
			'voting keys are registered from the current epoch 2825 until epoch 3024'
		], caplog)
		assert_max_log_level(LogLevel.INFO, caplog)


@pytest.mark.asyncio
async def test_validate_skips_custom_network(tmp_path):
	directories = _prepare_directory(tmp_path)
	context = SimpleNamespace(
		config=SimpleNamespace(network=Network('private', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero())),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	context.directories.output_directory = Path(tmp_path)
	await validate(context)
	assert not context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_no_api_endpoint(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	context.directories.output_directory = Path(tmp_path)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: [])
	await validate(context)
	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_pending_transaction_is_not_terminal(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	directories.output_directory = Path(tmp_path)
	transaction_path = directories.output_directory / 'renew_voting_keys_transaction.dat'
	transaction_path.write_bytes(b'transaction')
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(voting_keys.sc.TransactionFactory, 'deserialize', lambda _data: 'transaction')
	monkeypatch.setattr(voting_keys.SymbolFacade, 'hash_transaction', lambda _self, _transaction: 'hash')

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def transaction_statuses(self, _hashes):
			return [{'hash': 'hash', 'group': 'pending'}]

	monkeypatch.setattr(voting_keys, 'SymbolConnector', Connector)
	await validate(context)
	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_pending_directory_has_no_transaction(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	directories.output_directory = Path(tmp_path)
	(directories.voting_keys / 'pending').mkdir()
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	await validate(context)
	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_pending_transaction_cannot_be_read(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	directories.output_directory = Path(tmp_path)
	(directories.output_directory / 'renew_voting_keys_transaction.dat').write_bytes(b'transaction')
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(
		voting_keys.sc.TransactionFactory,
		'deserialize',
		lambda _data: (_ for _ in ()).throw(ValueError('invalid transaction')))

	class Connector:
		def __init__(self, _endpoint):
			pass

	monkeypatch.setattr(voting_keys, 'SymbolConnector', Connector)
	await validate(context)

	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_terminal_pending_transaction_has_pending_keys(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	directories.output_directory = Path(tmp_path)
	(directories.voting_keys / 'pending').mkdir()
	_write_voting_keys_file(directories.voting_keys / 'pending', 1, 2825, 2924)
	(directories.output_directory / 'renew_voting_keys_transaction.dat').write_bytes(b'transaction')
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(voting_keys.sc.TransactionFactory, 'deserialize', lambda _data: 'transaction')
	monkeypatch.setattr(voting_keys.SymbolFacade, 'hash_transaction', lambda _self, _transaction: 'hash')

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def transaction_statuses(self, _hashes):
			return [{'hash': 'hash', 'group': 'confirmed'}]

	monkeypatch.setattr(voting_keys, 'SymbolConnector', Connector)
	await validate(context)

	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_local_and_chain_descriptors_mismatch(monkeypatch, tmp_path):
	directories = _prepare_directory(tmp_path)
	directories.output_directory = Path(tmp_path)
	local = SimpleNamespace(public_key='local', start_epoch=2825, end_epoch=2924)
	chain = SimpleNamespace(public_key='chain', start_epoch=2825, end_epoch=2924)
	context = SimpleNamespace(
		config=SimpleNamespace(
			network=Network('testnet', 0x98, datetime.fromtimestamp(0, timezone.utc), Hash256.zero()),
			services=SimpleNamespace(nodewatch='nodewatch')),
		directories=directories,
		config_manager=ConfigurationManager(directories.resources),
		failed=False)
	monkeypatch.setattr(voting_keys, 'get_current_finalization_epoch', lambda *_args: _async_value(2825))
	monkeypatch.setattr(voting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(voting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(
		voting_keys,
		'inspect_voting_key_files',
		lambda directory: [local] if Path(directory) == directories.voting_keys else [])

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def account_links(self, _account):
			return SimpleNamespace(voting_public_keys=[chain])

	monkeypatch.setattr(voting_keys, 'SymbolConnector', Connector)
	await validate(context)
	assert context.failed


async def _async_value(value):
	return value

# endregion
