import importlib
import json
from pathlib import Path

from zenlog import log

from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration


class HealthAgentContext:
	"""Context passed to health agent validation routines."""

	def __init__(self, directories, config):
		"""Creates a new context."""

		self.directories = directories
		self.config = config
		self.config_manager = ConfigurationManager(self.directories.resources)
		self.failed = False

	@property
	def peer_endpoint(self):
		"""Peer endpoint."""

		host = self._load_hostname()
		port = int(self.config_manager.lookup('config-node.properties', [('node', 'port')])[0])
		return (host, port)

	@property
	def rest_endpoint(self):
		"""REST endpoint."""

		scheme = 'https' if self.config.node.api_https else 'http'
		hostname = self._load_hostname()
		port = self._load_rest_port()
		return f'{scheme}://{hostname}:{port}'

	@property
	def websocket_endpoint(self):
		"""Websocket endpoint."""

		scheme = 'wss' if self.config.node.api_https else 'ws'
		hostname = self._load_hostname()
		port = self._load_rest_port()
		return f'{scheme}://{hostname}:{port}/ws'

	def _load_hostname(self):
		host = self.config_manager.lookup('config-node.properties', [('localnode', 'host')])[0]
		return host or 'localhost'

	def _load_rest_port(self):
		if self.config.node.api_https:
			return 3001  # assume default HTTPS port

		with open(self.directories.node_config / 'rest.json', 'rt', encoding='utf8') as infile:
			rest_json = json.loads(infile.read())
			return int(rest_json['port'])


async def run_main(args):
	config = parse_sakuya_configuration(args.config)
	context = HealthAgentContext(Preparer.DirectoryLocator(None, Path(args.directory)), config)

	for agent_name in ('peer_certificate', 'peer_api', 'voting_keys', 'harvesting_keys', 'rest_https_certificate', 'rest_api', 'websockets'):
		module = importlib.import_module(f'sakuya.healthagents.{agent_name}')

		if module.should_run(config.node):
			log.debug(_('health-running-health-agent').format(module_name=module.NAME))
			try:
				await module.validate(context)
			except Exception:  # 各チェックを最後まで実行し、全体結果だけを最後に失敗させる。
				context.failed = True
				# 例外文字列に資格情報が含まれる可能性があるため、そのまま出力しない。
				log.error(f'{module.NAME} health check failed')

	if context.failed:
		raise RuntimeError('one or more health checks failed')


def add_arguments(parser):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
