import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sakuya.__main__ import main
from sakuya.commands import health
from sakuya.commands.health import HealthAgentContext
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import ImportsConfiguration, NodeConfiguration, SakuyaConfiguration

from ..test.ConfigurationTestUtils import prepare_sakuya_configuration
from ..test.LogTestUtils import assert_all_messages_are_logged

# region HealthAgentContext


def _write_resources(directories, host, port, rest_port):
	with open(directories.resources / 'config-node.properties', 'wt', encoding='utf8') as outfile:
		outfile.write('\n'.join([
			'[node]',
			'',
			f'port = {port}',
			'',
			'[localnode]',
			'',
			f'host = {host}'
		]))

	with open(directories.node_config / 'rest.json', 'wt', encoding='utf8') as outfile:
		outfile.write(f'{{"port": {rest_port}}}\n')


def _create_configuration(api_https):
	return SakuyaConfiguration(
		*(4 * [None]),
		ImportsConfiguration(None, None, None),
		NodeConfiguration(NodeFeatures.PEER, None, None, None, api_https, False, 'CA', 'NODE'))


# pylint: disable=invalid-name

def test_can_detect_endpoints_without_host():
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with Preparer(output_directory, _create_configuration(False)) as preparer:
			preparer.create_subdirectories()
			_write_resources(preparer.directories, '', 1111, 2345)

			# Act:
			context = HealthAgentContext(preparer.directories, preparer.config)

			# Assert:
			assert ('localhost', 1111) == context.peer_endpoint
			assert 'http://localhost:2345' == context.rest_endpoint
			assert 'ws://localhost:2345/ws' == context.websocket_endpoint


def test_can_detect_endpoints_without_https():
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with Preparer(output_directory, _create_configuration(False)) as preparer:
			preparer.create_subdirectories()
			_write_resources(preparer.directories, 'symbol.fyi', 1111, 2345)

			# Act:
			context = HealthAgentContext(preparer.directories, preparer.config)

			# Assert:
			assert ('symbol.fyi', 1111) == context.peer_endpoint
			assert 'http://symbol.fyi:2345' == context.rest_endpoint
			assert 'ws://symbol.fyi:2345/ws' == context.websocket_endpoint


def test_can_detect_endpoints_with_https():
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with Preparer(output_directory, _create_configuration(True)) as preparer:
			preparer.create_subdirectories()
			_write_resources(preparer.directories, 'symbol.fyi', 1111, 2345)

			# Act:
			context = HealthAgentContext(preparer.directories, preparer.config)

			# Assert:
			assert ('symbol.fyi', 1111) == context.peer_endpoint
			assert 'https://symbol.fyi:3001' == context.rest_endpoint
			assert 'wss://symbol.fyi:3001/ws' == context.websocket_endpoint

# endregion


# region command

async def test_can_run_health_command(caplog):
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			with Preparer(output_directory, _create_configuration(False)) as preparer:
				preparer.create_subdirectories()
				preparer.generate_certificates(Path(output_directory) / 'ca.key.pem', require_ca=False)
				_write_resources(preparer.directories, 'symbol.fyi', 1111, 2345)

				config_filepath = prepare_sakuya_configuration(package_directory, NodeFeatures.PEER, '', api_https=False)

				# Act:
				with pytest.raises(RuntimeError, match='one or more health checks failed'):
					await main([
						'--directory', output_directory,
						'health',
						'--config', str(config_filepath),
					])

				# Assert:
			expected_messages = [
				'running health agent for peer certificate',
				'ca certificate not near expiry (7299 day(s))',
				'node certificate not near expiry (374 day(s))',
				'running health agent for peer API',
				'cannot access peer API at localhost on port 1111'
			]
			assert_all_messages_are_logged(expected_messages, caplog)


async def test_health_runs_all_agents_after_one_agent_raises(monkeypatch, tmp_path):
	config = SimpleNamespace(node=SimpleNamespace(api_https=False))
	directories = SimpleNamespace(resources=tmp_path, node_config=tmp_path)
	module = SimpleNamespace(NAME='test-agent', should_run=lambda _node: True)

	async def validate(_context):
		raise RuntimeError('secret must not be logged')

	module.validate = validate
	monkeypatch.setattr(health, 'parse_sakuya_configuration', lambda _path: config)
	monkeypatch.setattr(health.Preparer, 'DirectoryLocator', lambda _env, _directory: directories)
	monkeypatch.setattr(health.importlib, 'import_module', lambda _name: module)

	with pytest.raises(RuntimeError, match='one or more health checks failed'):
		await health.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))

# endregion
