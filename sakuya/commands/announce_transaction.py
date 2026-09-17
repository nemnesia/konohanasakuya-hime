import asyncio
import time

from symbolchain import sc
from symbolchain.facade.SymbolFacade import SymbolFacade
from symbollightapi.connector.SymbolConnector import SymbolConnector
from zenlog import log

from sakuya.internal.NodeDownloader import detect_api_endpoints
from sakuya.internal.ShoestringConfiguration import parse_shoestring_configuration

RETRY_INTERVAL_SECONDS = 1


def _is_transient_exception(exception):
	status_code = getattr(exception, 'http_status_code', None)
	return status_code is None or status_code in (408, 425, 429) or status_code >= 500


async def _announce_with_retry(transaction, timeout_seconds, announce_transaction):
	deadline = time.monotonic() + timeout_seconds
	while True:
		try:
			await announce_transaction(transaction)
			return
		except Exception as exception:  # REST障害だけを期限まで同じトランザクションで再試行する。
			if not _is_transient_exception(exception) or time.monotonic() >= deadline:
				raise
			await asyncio.sleep(RETRY_INTERVAL_SECONDS)


async def _wait_for_terminal_status(connector, transaction_hash, timeout_seconds):
	deadline = time.monotonic() + timeout_seconds
	while time.monotonic() < deadline:
		try:
			statuses = await connector.transaction_statuses([transaction_hash])
			for status in statuses:
				if str(status.get('hash', '')).lower() != str(transaction_hash).lower():
					continue
				if 'confirmed' == status.get('group'):
					return 'confirmed'
				if 'failed' == status.get('group'):
					raise RuntimeError(f'transaction was rejected with error {status.get("code", "unknown")}')
		except RuntimeError:
			raise
		except Exception as exception:
			if getattr(exception, 'http_status_code', None) not in (404, 408, 425, 429) and not _is_transient_exception(exception):
				raise
		await asyncio.sleep(RETRY_INTERVAL_SECONDS)

	raise TimeoutError(f'transaction {transaction_hash} did not reach a terminal state')


async def run_main(args):
	config = parse_shoestring_configuration(args.config)

	api_endpoint = (await detect_api_endpoints(config.services.nodewatch, 1))[0]

	log.info(_('general-connecting-to-node').format(endpoint=api_endpoint))
	connector = SymbolConnector(api_endpoint)

	with open(args.transaction, 'rb') as infile:
		transaction_bytes = infile.read()
		transaction = sc.TransactionFactory.deserialize(transaction_bytes)

	transaction_type = transaction.type_
	transaction_hash = SymbolFacade(config.network).hash_transaction(transaction)
	log.info(_('announce-transaction-preparing-to-announce').format(transaction_hash=transaction_hash, transaction_type=transaction_type))

	announce_transaction = connector.announce_transaction
	if sc.TransactionType.AGGREGATE_BONDED == transaction_type:
		announce_transaction = connector.announce_partial_transaction

	timeout_seconds = max(1, config.transaction.timeout_hours * 60 * 60)
	await _announce_with_retry(transaction, timeout_seconds, announce_transaction)
	status = await _wait_for_terminal_status(connector, transaction_hash, timeout_seconds)
	log.info(f'transaction {transaction_hash} reached terminal state: {status}')


def add_arguments(parser):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.add_argument('transaction', help=_('argument-help-announce-transaction-transaction'))
	parser.set_defaults(func=run_main)
