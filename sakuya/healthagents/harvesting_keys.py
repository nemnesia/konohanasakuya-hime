from symbolchain.symbol.KeyPair import KeyPair
from symbollightapi.connector.SymbolConnector import SymbolConnector
from zenlog import log

from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.PeerDownloader import load_api_endpoints
from sakuya.internal.PemUtils import read_private_key_from_private_key_pem_file, read_public_key_from_public_key_pem_file

NAME = 'harvesting keys'


def should_run(node_config):
	"""ハーベスター機能が有効な場合だけ検査する。"""
	return NodeFeatures.HARVESTER in node_config.features


async def validate(context):
	"""remote／VRFリンクとハーベスト可能状態を検査する。"""
	if context.config.network.name not in ('mainnet', 'testnet'):
		return

	api_endpoints = load_api_endpoints(context.directories.resources)
	if not api_endpoints:
		log.error(_('health-harvesting-keys-unknown'))
		context.failed = True
		return

	remote_key = KeyPair(read_private_key_from_private_key_pem_file(context.directories.keys / 'remote.pem')).public_key
	vrf_key = KeyPair(read_private_key_from_private_key_pem_file(context.directories.keys / 'vrf.pem')).public_key
	account_public_key = read_public_key_from_public_key_pem_file(context.directories.certificates / 'ca.pubkey.pem')
	connector = SymbolConnector(api_endpoints[0])
	links = await connector.account_links(account_public_key)
	if links.linked_public_key != remote_key or links.vrf_public_key != vrf_key:
		log.error(_('health-harvesting-keys-mismatch'))
		context.failed = True

	# リンクが正しくても、ノードが実際にハーベスト可能とは限らない。
	harvesting = await connector.get(f'harvesting/{account_public_key}', 'harvesting')
	if ('canHarvest' in harvesting and not harvesting['canHarvest']) or (
		'isHarvesting' in harvesting and not harvesting['isHarvesting']):
		log.error(_('health-harvesting-keys-mismatch'))
		context.failed = True
