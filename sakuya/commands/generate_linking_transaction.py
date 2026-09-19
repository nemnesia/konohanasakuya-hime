from pathlib import Path

from zenlog import log

from sakuya.commands.setup import _prepare_linking_transaction, _require_setup_completed
from sakuya.internal.PeerDownloader import find_api_node
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration


async def run_main(args):
	"""既存 setup の鍵と設定を使って linking transaction を再生成する。"""

	output_directory = Path(args.directory).absolute()
	_require_setup_completed(output_directory)
	config = parse_sakuya_configuration(args.config)
	api_endpoint = await find_api_node(config.services.nodewatch)
	preparer = Preparer(output_directory, config, log)
	preparer.load_keys()
	await _prepare_linking_transaction(preparer, api_endpoint)


def add_arguments(parser):
	"""linking transaction 再生成コマンドの引数を登録する。"""

	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
