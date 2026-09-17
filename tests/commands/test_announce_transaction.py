import tempfile
from binascii import hexlify
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import Hash256, PrivateKey
from symbolchain.facade.SymbolFacade import SymbolFacade
from symbolchain.symbol.KeyPair import KeyPair

from sakuya.__main__ import main
from sakuya.commands import announce_transaction
from sakuya.internal.NodeFeatures import NodeFeatures

from ..test.ConfigurationTestUtils import prepare_sakuya_configuration
from ..test.MockNodewatchServer import setup_mock_nodewatch_server

# region server fixture


@pytest.fixture
async def server(aiohttp_client):
	return await setup_mock_nodewatch_server(aiohttp_client, True)

# endregion


# region tests

async def _run_test(server, expected_url_path, transaction_descriptor_factory):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		# - prepare Sakuya configuration
		config_filepath = prepare_sakuya_configuration(output_directory, NodeFeatures.PEER, server.make_url(''))

		# - generate and write out (unsigned) transaction
		facade = SymbolFacade('testnet')
		transaction_filepath = Path(output_directory) / 'transaction.dat'
		with open(transaction_filepath, 'wb') as outfile:
			transaction = facade.transaction_factory.create({
				**transaction_descriptor_factory(),
				'signer_public_key': KeyPair(PrivateKey.random()).public_key,
				'deadline': 1234000
			})
			transaction_buffer = transaction.serialize()
			outfile.write(transaction_buffer)

		# Act:
		await main([
			'announce-transaction',
			'--config', str(config_filepath),
			str(transaction_filepath)
		])

		# Assert:
		assert [
			f'{server.make_url("")}/api/symbol/nodes/peer',
			f'{server.make_url("")}/{expected_url_path}',
			f'{server.make_url("")}/transactionStatus'
		] == server.mock.urls
		assert [
			{'payload': hexlify(transaction_buffer).upper().decode('utf8')}
		] == server.mock.request_json_payloads


# pylint: disable=invalid-name


async def test_can_announce_regular_transaction(server):  # pylint: disable=redefined-outer-name
	await _run_test(server, 'transactions', lambda: {
		'type': 'account_key_link_transaction_v1',

		'linked_public_key': KeyPair(PrivateKey.random()).public_key,
		'link_action': 'link'
	})


def _create_aggregate_transaction_descriptor(transaction_type):
	return {
		'type': transaction_type,
		'fee': 0,
		'deadline': 0,
		'transactions_hash': Hash256.zero(),
		'transactions': []
	}


async def test_can_announce_aggregate_complete_transaction(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	def create_transaction_descriptor():
		return _create_aggregate_transaction_descriptor('aggregate_complete_transaction_v3')

	# Act + Assert:
	await _run_test(server, 'transactions', create_transaction_descriptor)


async def test_can_announce_aggregate_bonded_transaction(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	def create_transaction_descriptor():
		return _create_aggregate_transaction_descriptor('aggregate_bonded_transaction_v3')

	# Act + Assert:
	await _run_test(server, 'transactions/partial', create_transaction_descriptor)


def test_transient_exception_classification():
	assert announce_transaction._is_transient_exception(Exception())
	for status_code in (408, 425, 429, 500):
		assert announce_transaction._is_transient_exception(SimpleNamespace(http_status_code=status_code))
	assert not announce_transaction._is_transient_exception(SimpleNamespace(http_status_code=400))


async def test_announce_retries_transient_failure(monkeypatch):
	calls = []

	class TransientError(Exception):
		http_status_code = 503

	async def announce(_transaction):
		calls.append(True)
		if len(calls) == 1:
			raise TransientError()

	monkeypatch.setattr(announce_transaction, 'RETRY_INTERVAL_SECONDS', 0)
	await announce_transaction._announce_with_retry(object(), 1, announce)
	assert 2 == len(calls)


async def test_announce_does_not_retry_non_transient_failure():
	class PermanentError(Exception):
		http_status_code = 400

	async def announce(_transaction):
		raise PermanentError()

	with pytest.raises(PermanentError):
		await announce_transaction._announce_with_retry(object(), 1, announce)


async def test_wait_for_terminal_status_handles_transient_failure(monkeypatch):
	responses = [Exception(), [{'hash': 'other', 'group': 'confirmed'}], [{'hash': 'ABCD', 'group': 'confirmed'}]]

	class Connector:
		async def transaction_statuses(self, _hashes):
			response = responses.pop(0)
			if isinstance(response, Exception):
				raise response
			return response

	monkeypatch.setattr(announce_transaction, 'RETRY_INTERVAL_SECONDS', 0)
	assert 'confirmed' == await announce_transaction._wait_for_terminal_status(Connector(), 'abcd', 1)


async def test_wait_for_terminal_status_raises_for_failed_transaction():
	class Connector:
		async def transaction_statuses(self, _hashes):
			return [{'hash': 'ABCD', 'group': 'failed', 'code': 'FOO'}]

	with pytest.raises(RuntimeError, match='FOO'):
		await announce_transaction._wait_for_terminal_status(Connector(), 'abcd', 1)


async def test_wait_for_terminal_status_propagates_non_transient_failure():
	class PermanentError(Exception):
		http_status_code = 400

	class Connector:
		async def transaction_statuses(self, _hashes):
			raise PermanentError()

	with pytest.raises(PermanentError):
		await announce_transaction._wait_for_terminal_status(Connector(), 'abcd', 1)


async def test_wait_for_terminal_status_times_out(monkeypatch):
	monkeypatch.setattr(announce_transaction, 'RETRY_INTERVAL_SECONDS', 0)
	with pytest.raises(TimeoutError, match='ABCD'):
		await announce_transaction._wait_for_terminal_status(SimpleNamespace(), 'ABCD', 0)

# endregion
