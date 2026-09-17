import tempfile
from pathlib import Path

import pytest

from sakuya.__main__ import main
from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.PackageResolver import download_and_extract_package as real_download_and_extract_package

from ..test.ConfigurationTestUtils import prepare_shoestring_configuration
from ..test.FileSystemTestUtils import assert_expected_files_and_permissions
from ..test.MockNodewatchServer import setup_mock_nodewatch_server
from ..test.TestPackager import prepare_testnet_package
from .test_setup import (
	API_OUTPUT_FILES,
	HARVESTER_OUTPUT_FILES,
	HTTPS_OUTPUT_FILES,
	LIGHT_API_OUTPUT_FILES,
	PEER_OUTPUT_FILES,
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
	'sakuya/rest-cache',
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
	'sakuya/node-config/rest.json',
	'sakuya/rest-cache'
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
			prepare_shoestring_configuration(package_directory, node_features, server.make_url(''), api_https=api_https, light_api=light_api)
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
				assert_expected_files_and_permissions(output_directory, expected_output_files)

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

# endregion
