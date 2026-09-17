from symbolchain import sc
from symbolchain.facade.SymbolFacade import SymbolFacade
from symbollightapi.connector.SymbolConnector import SymbolConnector
from zenlog import log

from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.NodewatchClient import get_current_finalization_epoch
from sakuya.internal.PeerDownloader import load_api_endpoints
from sakuya.internal.PemUtils import read_public_key_from_public_key_pem_file
from sakuya.internal.VoterConfigurator import inspect_voting_key_files

NAME = 'voting keys'


def should_run(node_config):
	"""Voting機能が有効な場合だけ検査する。"""
	return NodeFeatures.VOTER in node_config.features


async def validate(context):
	"""ローカルVoting Keyとオンチェーンリンクを完全照合する。"""
	if context.config.network.name not in ('mainnet', 'testnet'):
		return

	pending_directory = context.directories.voting_keys / 'pending'
	transaction_path = context.directories.output_directory / 'renew_voting_keys_transaction.dat'
	has_pending_directory = pending_directory.exists()
	has_pending_keys = pending_directory.is_dir() and bool(inspect_voting_key_files(pending_directory))
	has_pending_transaction = transaction_path.is_file()

	current_finalization_epoch = await get_current_finalization_epoch(context.config.services.nodewatch, context.config_manager)
	api_endpoints = load_api_endpoints(context.directories.resources)
	if not api_endpoints:
		log.error(_('health-voting-keys-not-registered').format(epoch=current_finalization_epoch))
		context.failed = True
		return

	account_public_key = read_public_key_from_public_key_pem_file(context.directories.certificates / 'ca.pubkey.pem')
	connector = SymbolConnector(api_endpoints[0])
	if has_pending_transaction:
		try:
			with open(transaction_path, 'rb') as infile:
				transaction = sc.TransactionFactory.deserialize(infile.read())
			transaction_hash = SymbolFacade(context.config.network).hash_transaction(transaction)
			statuses = await connector.transaction_statuses([transaction_hash])
			transaction_status = next(
				(status for status in statuses if str(status.get('hash', '')).lower() == str(transaction_hash).lower()), None)
		except Exception:  # 外部状態を確認できない場合は安全側で失敗とする。
			transaction_status = None

		if not transaction_status or transaction_status.get('group') not in ('confirmed', 'failed'):
			log.error(_('health-voting-keys-not-registered').format(epoch='pending'))
			context.failed = True
			if not has_pending_keys:
				return

	if has_pending_directory and (not has_pending_keys or not has_pending_transaction):
		log.error(_('health-voting-keys-not-registered').format(epoch='pending'))
		context.failed = True
		return
	if has_pending_keys:
		# 終端状態のtransactionであっても、activeへの昇格・cleanupが未処理なら異常とする。
		log.error(_('health-voting-keys-not-registered').format(epoch='pending'))
		context.failed = True
		return

	existing_links = await connector.account_links(account_public_key)
	registered_current_keys = [
		link for link in existing_links.voting_public_keys
		if link.start_epoch <= current_finalization_epoch <= link.end_epoch
	]
	local_descriptors = inspect_voting_key_files(context.directories.voting_keys)
	registered_descriptors = {
		(link.public_key, link.start_epoch, link.end_epoch) for link in existing_links.voting_public_keys
	}
	local_descriptor_set = {
		(descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch) for descriptor in local_descriptors
	}
	if local_descriptor_set != registered_descriptors:
		# ローカルだけ、またはオンチェーンだけの鍵も登録不整合として扱う。
		context.failed = True
	first_gap_finalization_epoch = current_finalization_epoch

	for descriptor in local_descriptors:
		if (descriptor.public_key, descriptor.start_epoch, descriptor.end_epoch) not in registered_descriptors:
			log.error(_('health-voting-keys-not-registered').format(epoch=descriptor.start_epoch))
			continue
		if descriptor.end_epoch < current_finalization_epoch:
			log.warning(_('health-voting-keys-expired').format(start_epoch=descriptor.start_epoch, end_epoch=descriptor.end_epoch))
		elif descriptor.start_epoch <= current_finalization_epoch <= descriptor.end_epoch:
			log.info(_('health-voting-keys-active').format(start_epoch=descriptor.start_epoch, end_epoch=descriptor.end_epoch))
			first_gap_finalization_epoch = descriptor.end_epoch + 1
		else:
			log.info(_('health-voting-keys-future').format(start_epoch=descriptor.start_epoch, end_epoch=descriptor.end_epoch))

			if descriptor.start_epoch == first_gap_finalization_epoch:
				first_gap_finalization_epoch = descriptor.end_epoch + 1

	if not registered_current_keys or first_gap_finalization_epoch == current_finalization_epoch:
		log.error(_('health-voting-keys-not-registered').format(epoch=current_finalization_epoch))
		context.failed = True
	else:
		log.info(_('health-voting-keys-registered').format(
			start_epoch=current_finalization_epoch,
			end_epoch=first_gap_finalization_epoch - 1))
