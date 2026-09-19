import tempfile
from pathlib import Path

import pytest

from sakuya.__main__ import main
from sakuya.commands import upgrade as upgrade_command
from sakuya.internal import AtomicFileSystem
from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.PackageResolver import download_and_extract_package as real_download_and_extract_package

from ..test.ConfigurationTestUtils import prepare_sakuya_configuration, prepare_sakuya_setup_configuration
from ..test.FileSystemTestUtils import assert_expected_files_and_permissions
from ..test.MockNodewatchServer import setup_mock_nodewatch_server
from ..test.TestPackager import prepare_testnet_package
from .test_setup import (
	API_OUTPUT_FILES,
	HARVESTER_OUTPUT_FILES,
	HTTPS_OUTPUT_FILES,
	LIGHT_API_OUTPUT_FILES,
	PEER_OUTPUT_FILES,
	SETUP_STATE_OUTPUT_FILES,
	STATE_CHANGE_OUTPUT_FILES,
	VOTER_OUTPUT_FILES
)

# region server fixture


@pytest.fixture
async def server(aiohttp_client):
	return await setup_mock_nodewatch_server(aiohttp_client, True)


@pytest.fixture(autouse=True)
def local_test_package(monkeypatch):
	from sakuya.commands import setup as setup_command

	def resolve(config_filepath, _network_name):
		return f'file://{Path(config_filepath).parent / "resources.zip"}'

	monkeypatch.setattr(setup_command, 'resolve_package_identifier', resolve)
	monkeypatch.setattr(setup_command, 'download_and_extract_package', real_download_and_extract_package)

# endregion


# region changed files

PEER_CHANGED_FILES = [
	'docker-compose-recovery.yaml',
	'docker-compose.yaml',
	'sakuya',
	'sakuya/node-config',
	'sakuya/node-config/resources',
	'sakuya/node-config/resources/config-extensions-recovery.properties',
	'sakuya/node-config/resources/config-extensions-server.properties',
	'sakuya/node-config/resources/config-finalization.properties',
	'sakuya/node-config/resources/config-inflation.properties',
	'sakuya/node-config/resources/config-logging-recovery.properties',
	'sakuya/node-config/resources/config-logging-server.properties',
	'sakuya/node-config/resources/config-network.properties',
	'sakuya/node-config/resources/config-node.properties',
	'sakuya/node-config/resources/config-task.properties',
	'sakuya/node-config/resources/config-timesync.properties',
	'sakuya/node-config/resources/config-user.properties',
	'sakuya/node-config/resources/peers-p2p.json'
]

HTTPS_CHANGED_FILES = [
	'sakuya/https-proxy',
	'sakuya/https-proxy/nginx.conf.erb'
]

API_CHANGED_FILES = [
	'sakuya/mongo',
	'sakuya/mongo/mongoDbDrop.js',
	'sakuya/mongo/mongoDbPrepare.js',
	'sakuya/mongo/mongoLockHashDbPrepare.js',
	'sakuya/mongo/mongoLockSecretDbPrepare.js',
	'sakuya/mongo/mongoMetadataDbPrepare.js',
	'sakuya/mongo/mongoMosaicDbPrepare.js',
	'sakuya/mongo/mongoMultisigDbPrepare.js',
	'sakuya/mongo/mongoNamespaceDbPrepare.js',
	'sakuya/mongo/mongoRestrictionAccountDbPrepare.js',
	'sakuya/mongo/mongoRestrictionMosaicDbPrepare.js',
	'sakuya/startup',
	'sakuya/startup/delayrestapi.sh',
	'sakuya/startup/mongors.sh',
	'sakuya/startup/startBroker.sh',
	'sakuya/startup/startRecovery.sh',
	'sakuya/startup/startServer.sh',
	'sakuya/startup/wait.sh',
	'sakuya/node-config/resources/config-database.properties',
	'sakuya/node-config/resources/config-extensions-broker.properties',
	'sakuya/node-config/resources/config-logging-broker.properties',
	'sakuya/node-config/resources/config-messaging.properties',
	'sakuya/node-config/resources/config-pt.properties',
	'sakuya/node-config/resources/peers-api.json',
	'sakuya/node-config/rest.json'
]

LIGHT_API_CHANGED_FILES = [
	'sakuya/node-config/rest.json'
]

HARVESTER_CHANGED_FILES = [
	'sakuya/node-config/resources/config-harvesting.properties'
]

# endregion


# region assert_can_upgrade_node

def _set_hostname_in_overrides(user_overrides_filepath, hostname, friendly_name):
	with open(user_overrides_filepath, 'wt', encoding='utf8') as outfile:
		outfile.write('\n'.join([
			'[node.localnode]',
			'',
			f'host = {hostname}',  # must be a name that resolves properly
			f'friendlyName = {friendly_name}'
		]))


def _prepare_overrides(directory, friendly_name):
	_set_hostname_in_overrides(Path(directory) / 'user_overrides.ini', 'localhost', friendly_name)


def _get_mtimes_map(output_directory):
	return {str(path.relative_to(output_directory)): path.stat().st_mtime for path in Path(output_directory).glob('**/*')}


def _read_friendly_name(config_manager):
	return config_manager.lookup('config-node.properties', [('localnode', 'friendlyName')])[0]


def _read_harvester_private_keys(config_manager):
	return config_manager.lookup('config-harvesting.properties', [
		('harvesting', 'harvesterSigningPrivateKey'),
		('harvesting', 'harvesterVrfPrivateKey')
	])


def _get_changed_files(map1, map2):
	return sorted([key for key, value in map1.items() if value != map2[key]])


def _assert_changed_files(setup_mtimes_map, output_directory, expected_changed_files):
	upgrade_mtimes_map = _get_mtimes_map(output_directory)
	changed_files = _get_changed_files(setup_mtimes_map, upgrade_mtimes_map)
	assert expected_changed_files == changed_files


def _snapshot_files(output_directory, relative_paths):
	"""ファイル内容とinodeを取得して、runtime stateの不変性を確認する。"""
	snapshot = {}
	for relative_path in relative_paths:
		path = Path(output_directory) / relative_path
		paths = [path] if path.is_file() else path.glob('**/*') if path.is_dir() else []
		for filepath in paths:
			if not filepath.is_file():
				continue
			stat = filepath.stat()
			snapshot[str(filepath.relative_to(output_directory))] = (
				filepath.read_bytes(),
				stat.st_ino,
				stat.st_mtime_ns,
				stat.st_mode & 0o777
			)
	return snapshot


async def _prepare_full_https_node(server, output_directory, package_directory, ca_directory):
	node_features = NodeFeatures.API | NodeFeatures.HARVESTER | NodeFeatures.VOTER
	prepare_sakuya_configuration(package_directory, node_features, server.make_url(''), include_init_files=True, api_https=True)
	_prepare_overrides(package_directory, 'name from setup')
	prepare_testnet_package(package_directory, 'resources.zip')
	await main([
		'--directory', output_directory,
		'setup',
		'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
		'--overrides', str(Path(package_directory) / 'user_overrides.ini'),
		'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem')
	])


async def _assert_can_upgrade_node(
	server,  # pylint: disable=redefined-outer-name
	node_features,
	expected_output_files,
	expected_changed_files,
	api_https=False,
	light_api=False,
	files_to_remove=None
):  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_setup_configuration(
				package_directory,
				node_features,
				server.make_url(''),
				api_https=api_https,
				light_api=light_api)
			_prepare_overrides(package_directory, 'name from setup')
			prepare_testnet_package(package_directory, 'resources.zip')

			common_args = [
				'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
				'--overrides', str(Path(package_directory) / 'user_overrides.ini')
			]

			with tempfile.TemporaryDirectory() as ca_directory:
				# - prepare directory by running initial setup command
				await main([
					'--directory', output_directory,
					'setup',
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
				] + common_args)

				setup_mtimes_map = _get_mtimes_map(output_directory)

				config_manager = ConfigurationManager(Path(output_directory) / 'sakuya' / 'node-config' / 'resources')
				if NodeFeatures.HARVESTER in node_features:
					setup_harvester_private_keys = _read_harvester_private_keys(config_manager)

				if isinstance(files_to_remove, list):
					for filename in files_to_remove:
						(Path(output_directory) / filename).unlink()

				# Sanity:
				assert 'name from setup' == _read_friendly_name(config_manager)

				# Act: upgrade (with different overrides)
				_prepare_overrides(package_directory, 'name from upgrade')
				await main(['--directory', output_directory, 'upgrade'] + common_args)

				# Assert: spot check all expected output files and permissions
				assert_expected_files_and_permissions(output_directory, {
					**expected_output_files,
					**SETUP_STATE_OUTPUT_FILES
				})

				# - check expected changed files are changed
				_assert_changed_files(setup_mtimes_map, output_directory, expected_changed_files)

				# - check latest config overrides are used during upgrade
				assert 'name from upgrade' == _read_friendly_name(config_manager)

				if NodeFeatures.HARVESTER in node_features:
					# - original harvesting private keys are retained
					upgrade_harvester_private_keys = _read_harvester_private_keys(config_manager)
					assert setup_harvester_private_keys == upgrade_harvester_private_keys

# endregion


# pylint: disable=invalid-name


# region feature variance

async def test_can_upgrade_peer_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_upgrade_node(server, NodeFeatures.PEER, PEER_OUTPUT_FILES, PEER_CHANGED_FILES)


async def test_can_upgrade_api_node(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **API_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + API_CHANGED_FILES)
	await _assert_can_upgrade_node(server, NodeFeatures.API, expected_output_files, expected_changed_files)


async def test_can_upgrade_api_node_with_https(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **API_OUTPUT_FILES, **HTTPS_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + API_CHANGED_FILES + HTTPS_CHANGED_FILES)
	await _assert_can_upgrade_node(server, NodeFeatures.API, expected_output_files, expected_changed_files, api_https=True)


async def test_can_upgrade_light_api_node(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **LIGHT_API_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + LIGHT_API_CHANGED_FILES)
	await _assert_can_upgrade_node(server, NodeFeatures.API, expected_output_files, expected_changed_files, light_api=True)


async def test_can_upgrade_light_api_node_with_https(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **LIGHT_API_OUTPUT_FILES, **HTTPS_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + LIGHT_API_CHANGED_FILES + HTTPS_CHANGED_FILES)
	await _assert_can_upgrade_node(server, NodeFeatures.API, expected_output_files, expected_changed_files, api_https=True, light_api=True)


async def test_can_upgrade_harvester_node(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **HARVESTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + HARVESTER_CHANGED_FILES)
	await _assert_can_upgrade_node(server, NodeFeatures.HARVESTER, expected_output_files, expected_changed_files)


async def test_can_upgrade_voter_node(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **VOTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES}
	await _assert_can_upgrade_node(server, NodeFeatures.VOTER, expected_output_files, PEER_CHANGED_FILES)


async def test_can_upgrade_full_node(server):  # pylint: disable=redefined-outer-name
	node_features = NodeFeatures.API | NodeFeatures.HARVESTER | NodeFeatures.VOTER
	expected_output_files = {
		**PEER_OUTPUT_FILES, **API_OUTPUT_FILES, **HARVESTER_OUTPUT_FILES, **VOTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES
	}
	expected_changed_files = sorted(PEER_CHANGED_FILES + API_CHANGED_FILES + HARVESTER_CHANGED_FILES)
	await _assert_can_upgrade_node(server, node_features, expected_output_files, expected_changed_files)


async def test_can_upgrade_node_without_docker_recovery_file(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **API_OUTPUT_FILES}
	expected_changed_files = sorted(PEER_CHANGED_FILES + API_CHANGED_FILES)
	await _assert_can_upgrade_node(
		server,
		NodeFeatures.API,
		expected_output_files,
		expected_changed_files,
		files_to_remove=['docker-compose-recovery.yaml']
	)


async def test_upgrade_preserves_runtime_state_and_replaces_only_generated_artifacts(server, monkeypatch):
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as full_package_directory:
			with tempfile.TemporaryDirectory() as peer_package_directory:
				with tempfile.TemporaryDirectory() as ca_directory:
					await _prepare_full_https_node(server, output_directory, full_package_directory, ca_directory)

					# Sakuyaが生成・管理しない代表的な実行時データを追加する。
					runtime_files = [
						'sakuya/data/runtime.dat',
						'sakuya/dbdata/database.dat',
						'sakuya/logs/node.log',
						'sakuya/keys/runtime-key',
						'sakuya/seed/runtime-seed',
						'sakuya/rest-cache/runtime-cache',
						'sakuya/https-proxy/runtime-state',
						'sakuya/https-proxy/certificates/runtime-cert'
					]
					for relative_path in runtime_files:
						path = Path(output_directory) / relative_path
						path.parent.mkdir(parents=True, exist_ok=True)
						path.write_text(f'unchanged: {relative_path}', encoding='utf8')

					# upgradeで生成ファイルが変化することを確認できる状態にする。
					nginx_filepath = Path(output_directory) / 'sakuya/https-proxy/nginx.conf.erb'
					nginx_filepath.chmod(0o600)
					nginx_filepath.write_text('old generated configuration', encoding='utf8')

					runtime_snapshot = _snapshot_files(output_directory, [
						'sakuya/data',
						'sakuya/dbdata',
						'sakuya/logs',
						'sakuya/keys',
						'sakuya/seed',
						'sakuya/rest-cache',
						'sakuya/https-proxy/runtime-state',
						'sakuya/https-proxy/certificates'
					])

					prepare_sakuya_configuration(peer_package_directory, NodeFeatures.PEER, server.make_url(''), include_init_files=True, api_https=False)
					_prepare_overrides(peer_package_directory, 'name from upgrade')
					prepare_testnet_package(peer_package_directory, 'resources.zip')

					original_copytree = upgrade_command.shutil.copytree
					output_sakuya = Path(output_directory) / 'sakuya'

					def guarded_copytree(source, destination, *args, **kwargs):
						assert Path(source) != output_sakuya
						return original_copytree(source, destination, *args, **kwargs)

					monkeypatch.setattr(upgrade_command.shutil, 'copytree', guarded_copytree)
					await main([
						'--directory', output_directory,
						'upgrade',
						'--config', str(Path(peer_package_directory) / 'sai.shoestring.ini'),
						'--overrides', str(Path(peer_package_directory) / 'user_overrides.ini')
					])

					assert runtime_snapshot == _snapshot_files(output_directory, [
						'sakuya/data',
						'sakuya/dbdata',
						'sakuya/logs',
						'sakuya/keys',
						'sakuya/seed',
						'sakuya/rest-cache',
						'sakuya/https-proxy/runtime-state',
						'sakuya/https-proxy/certificates'
					])
					assert not (Path(output_directory) / 'sakuya/startup').exists()
					assert not (Path(output_directory) / 'sakuya/mongo').exists()
					assert not nginx_filepath.exists()
					assert 'name from upgrade' == _read_friendly_name(ConfigurationManager(
						Path(output_directory) / 'sakuya/node-config/resources'))


@pytest.mark.parametrize('failure', [OSError, KeyboardInterrupt, SystemExit])
async def test_upgrade_rolls_back_generated_artifacts_without_touching_runtime_state(server, monkeypatch, failure):
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as full_package_directory:
			with tempfile.TemporaryDirectory() as peer_package_directory:
				with tempfile.TemporaryDirectory() as ca_directory:
					await _prepare_full_https_node(server, output_directory, full_package_directory, ca_directory)
					for relative_path in (
						'sakuya/data/runtime.dat',
						'sakuya/dbdata/database.dat',
						'sakuya/logs/node.log',
						'sakuya/keys/runtime-key',
						'sakuya/seed/runtime-seed',
						'sakuya/rest-cache/runtime-cache',
						'sakuya/https-proxy/runtime-state'):
						path = Path(output_directory) / relative_path
						path.parent.mkdir(parents=True, exist_ok=True)
						path.write_text(f'unchanged: {relative_path}', encoding='utf8')

					runtime_paths = (
						'sakuya/data',
						'sakuya/dbdata',
						'sakuya/logs',
						'sakuya/keys',
						'sakuya/seed',
						'sakuya/rest-cache',
						'sakuya/https-proxy/runtime-state')
					runtime_snapshot = _snapshot_files(output_directory, runtime_paths)
					generated_snapshot = _snapshot_files(output_directory, upgrade_command.UPGRADE_MANAGED_PATHS)

					prepare_sakuya_configuration(peer_package_directory, NodeFeatures.PEER, server.make_url(''), include_init_files=True, api_https=False)
					_prepare_overrides(peer_package_directory, 'name from upgrade')
					prepare_testnet_package(peer_package_directory, 'resources.zip')

					original_replace = AtomicFileSystem.os.replace

					replace_count = 0

					def fail_during_install(source, target):
						nonlocal replace_count
						replace_count += 1
						if 8 == replace_count:
							raise failure('simulated upgrade interruption')
						return original_replace(source, target)

					monkeypatch.setattr(AtomicFileSystem.os, 'replace', fail_during_install)
					with pytest.raises(failure, match='simulated upgrade interruption'):
						await main([
							'--directory', output_directory,
							'upgrade',
							'--config', str(Path(peer_package_directory) / 'sai.shoestring.ini'),
							'--overrides', str(Path(peer_package_directory) / 'user_overrides.ini')
						])

					assert runtime_snapshot == _snapshot_files(output_directory, runtime_paths)
					assert generated_snapshot == _snapshot_files(output_directory, upgrade_command.UPGRADE_MANAGED_PATHS)

# endregion
