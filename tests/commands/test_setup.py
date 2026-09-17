import configparser
import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import PrivateKey
from symbolchain.PrivateKeyStorage import PrivateKeyStorage

from sakuya.__main__ import main
from sakuya.commands import setup as setup_command
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.PackageResolver import download_and_extract_package as real_download_and_extract_package

from ..test.CertificateTestUtils import assert_certificate_properties
from ..test.ConfigurationTestUtils import prepare_sakuya_configuration
from ..test.FileSystemTestUtils import assert_expected_files_and_permissions
from ..test.MockNodewatchServer import setup_mock_nodewatch_server
from ..test.TestPackager import prepare_testnet_package

# region server fixture


@pytest.fixture
async def server(aiohttp_client):
	return await setup_mock_nodewatch_server(aiohttp_client, True)


@pytest.fixture(autouse=True)
def local_test_package(monkeypatch):
	"""Use each test's locally-created package while keeping the CLI contract."""
	from sakuya.commands import setup as setup_command

	monkeypatch.setattr(
		setup_command,
		'resolve_package_identifier',
		lambda config_filepath, _network_name: f'file://{Path(config_filepath).parent / "resources.zip"}')
	monkeypatch.setattr(setup_command, 'download_and_extract_package', real_download_and_extract_package)

# endregion


# region output files

PEER_OUTPUT_FILES = {
	'sakuya': 0o700,
	'sakuya/data': 0o700,
	'docker-compose.yaml': 0o400,
	'docker-compose-recovery.yaml': 0o400,
	'sakuya/keys': 0o700,
	'sakuya/keys/cert': 0o700,
	'sakuya/keys/cert/ca.crt.pem': 0o400,
	'sakuya/keys/cert/ca.pubkey.pem': 0o400,
	'sakuya/keys/cert/node.crt.pem': 0o400,
	'sakuya/keys/cert/node.full.crt.pem': 0o400,
	'sakuya/keys/cert/node.key.pem': 0o400,
	'sakuya/logs': 0o700,
	'sakuya/seed': 0o700,
	'sakuya/seed/00000': 0o700,
	'sakuya/seed/00000/00001.dat': 0o400,
	'sakuya/seed/00000/00001.proof': 0o400,
	'sakuya/seed/00000/00001.stmt': 0o400,
	'sakuya/seed/00000/hashes.dat': 0o400,
	'sakuya/seed/00000/proof.heights.dat': 0o400,
	'sakuya/seed/index.dat': 0o400,
	'sakuya/seed/proof.index.dat': 0o400,
	'sakuya/node-config': 0o700,
	'sakuya/node-config/resources': 0o700,
	'sakuya/node-config/resources/config-extensions-recovery.properties': 0o400,
	'sakuya/node-config/resources/config-extensions-server.properties': 0o400,
	'sakuya/node-config/resources/config-finalization.properties': 0o400,
	'sakuya/node-config/resources/config-inflation.properties': 0o400,
	'sakuya/node-config/resources/config-logging-recovery.properties': 0o400,
	'sakuya/node-config/resources/config-logging-server.properties': 0o400,
	'sakuya/node-config/resources/config-network.properties': 0o400,
	'sakuya/node-config/resources/config-node.properties': 0o400,
	'sakuya/node-config/resources/config-task.properties': 0o400,
	'sakuya/node-config/resources/config-timesync.properties': 0o400,
	'sakuya/node-config/resources/config-user.properties': 0o400,
	'sakuya/node-config/resources/peers-p2p.json': 0o400
}

HTTPS_OUTPUT_FILES = {
	'sakuya/https-proxy': 0o700,
	'sakuya/https-proxy/nginx.conf.erb': 0o400
}

API_OUTPUT_FILES = {
	'sakuya/dbdata': 0o700,
	'sakuya/mongo': 0o700,
	'sakuya/mongo/mongoDbDrop.js': 0o400,
	'sakuya/mongo/mongoDbPrepare.js': 0o400,
	'sakuya/mongo/mongoLockHashDbPrepare.js': 0o400,
	'sakuya/mongo/mongoLockSecretDbPrepare.js': 0o400,
	'sakuya/mongo/mongoMetadataDbPrepare.js': 0o400,
	'sakuya/mongo/mongoMosaicDbPrepare.js': 0o400,
	'sakuya/mongo/mongoMultisigDbPrepare.js': 0o400,
	'sakuya/mongo/mongoNamespaceDbPrepare.js': 0o400,
	'sakuya/mongo/mongoRestrictionAccountDbPrepare.js': 0o400,
	'sakuya/mongo/mongoRestrictionMosaicDbPrepare.js': 0o400,
	'sakuya/rest-cache': 0o700,
	'sakuya/startup': 0o700,
	'sakuya/startup/delayrestapi.sh': 0o400,
	'sakuya/startup/mongors.sh': 0o400,
	'sakuya/startup/startBroker.sh': 0o400,
	'sakuya/startup/startRecovery.sh': 0o400,
	'sakuya/startup/startServer.sh': 0o400,
	'sakuya/startup/wait.sh': 0o400,
	'sakuya/node-config/resources/config-database.properties': 0o400,
	'sakuya/node-config/resources/config-extensions-broker.properties': 0o400,
	'sakuya/node-config/resources/config-logging-broker.properties': 0o400,
	'sakuya/node-config/resources/config-messaging.properties': 0o400,
	'sakuya/node-config/resources/config-pt.properties': 0o400,
	'sakuya/node-config/resources/peers-api.json': 0o400,
	'sakuya/node-config/rest.json': 0o400
}

LIGHT_API_OUTPUT_FILES = {
	'sakuya/node-config/rest.json': 0o400,
	'sakuya/rest-cache': 0o700
}

HARVESTER_OUTPUT_FILES = {
	'sakuya/keys/remote.pem': 0o400,
	'sakuya/keys/vrf.pem': 0o400,
	'sakuya/node-config/resources/config-harvesting.properties': 0o400
}

VOTER_OUTPUT_FILES = {
	'sakuya/keys/voting': 0o700,
	'sakuya/keys/voting/private_key_tree1.dat': 0o600
}

STATE_CHANGE_OUTPUT_FILES = {
	'linking_transaction.dat': 0o600
}

# endregion


# region assert_can_prepare_node

class CaMode(Enum):
	NONE = 0
	WITHOUT_PASSWORD = 1
	WITH_PASSWORD = 2


def _set_hostname_in_overrides(user_overrides_filepath, hostname):
	with open(user_overrides_filepath, 'wt', encoding='utf8') as outfile:
		outfile.write('\n'.join([
			'[node.localnode]',
			'',
			f'host = {hostname}',  # must be a name that resolves properly
			'friendlyName = Foo Ninja'
		]))


def _prepare_overrides(directory):
	_set_hostname_in_overrides(Path(directory) / 'user_overrides.ini', 'localhost')


async def _assert_can_prepare_node(
	server,  # pylint: disable=redefined-outer-name
	node_features,
	expected_output_files,
	ca_mode=CaMode.NONE,
	api_https=False
):
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			ca_password = 'abcd' if CaMode.WITH_PASSWORD == ca_mode else ''
			prepare_sakuya_configuration(
				package_directory,
				node_features,
				server.make_url(''),
				ca_password=ca_password,
				api_https=api_https,
				ca_common_name='my CA CN',
				node_common_name='my Node CN')
			_prepare_overrides(package_directory)
			prepare_testnet_package(package_directory, 'resources.zip')

			ca_private_key = None
			with tempfile.TemporaryDirectory() as ca_directory:
				if CaMode.NONE != ca_mode:
					ca_private_key = PrivateKey.random()
					private_key_storage = PrivateKeyStorage(ca_directory, ca_password)
					private_key_storage.save('xyz.key', ca_private_key)

				# Act:
				await main([
					'--directory', output_directory,
					'setup',
					'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(Path(package_directory) / 'user_overrides.ini')
				])

				# Assert: spot check all expected output files and permissions
				assert_expected_files_and_permissions(output_directory, expected_output_files)

				# - spot check all expected CA files are present
				ca_files = sorted(str(path.relative_to(ca_directory)) for path in Path(ca_directory).glob('**/*'))
				assert ['xyz.key.pem'] == ca_files

				if CaMode.NONE != ca_mode:
					# - original CA private key is preserved
					private_key_storage = PrivateKeyStorage(ca_directory, ca_password)
					reloaded_ca_private_key = private_key_storage.load('xyz.key')
					assert ca_private_key == reloaded_ca_private_key

				# - check certificates
				certificates_directory = Path(output_directory) / 'sakuya' / 'keys' / 'cert'
				assert_certificate_properties(certificates_directory / 'node.crt.pem', 'my CA CN', 'my Node CN', 375)
				assert_certificate_properties(certificates_directory / 'ca.crt.pem', 'my CA CN', 'my CA CN', 20 * 365)

# endregion


# pylint: disable=invalid-name


# region feature variance

async def test_can_prepare_peer_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.PEER, PEER_OUTPUT_FILES)


async def test_can_prepare_api_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.API, {**PEER_OUTPUT_FILES, **API_OUTPUT_FILES})


async def test_can_prepare_api_node_with_https(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {**PEER_OUTPUT_FILES, **API_OUTPUT_FILES, **HTTPS_OUTPUT_FILES}
	await _assert_can_prepare_node(server, NodeFeatures.API, expected_output_files, api_https=True)


async def test_can_prepare_harvester_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.HARVESTER, {
		**PEER_OUTPUT_FILES, **HARVESTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES
	})


async def test_can_prepare_voter_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.VOTER, {
		**PEER_OUTPUT_FILES, **VOTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES
	})


async def test_can_prepare_full_node(server):  # pylint: disable=redefined-outer-name
	expected_output_files = {
		**PEER_OUTPUT_FILES, **API_OUTPUT_FILES, **HARVESTER_OUTPUT_FILES, **VOTER_OUTPUT_FILES, **STATE_CHANGE_OUTPUT_FILES
	}
	await _assert_can_prepare_node(server, NodeFeatures.API | NodeFeatures.HARVESTER | NodeFeatures.VOTER, expected_output_files)

# endregion


# region CA variance

async def test_can_prepare_peer_node_with_existing_ca_without_password(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.PEER, PEER_OUTPUT_FILES, CaMode.WITHOUT_PASSWORD)


async def test_can_prepare_peer_node_with_existing_ca_with_password(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_node(server, NodeFeatures.PEER, PEER_OUTPUT_FILES, CaMode.WITH_PASSWORD)

# endregion


# region relative output path

async def test_can_prepare_node_with_relative_output_directory(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory(dir=os.getcwd()) as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_configuration(
				package_directory,
				NodeFeatures.PEER,
				server.make_url(''),
				api_https=False,
				ca_common_name='my CA CN',
				node_common_name='my Node CN')
			_prepare_overrides(package_directory)
			prepare_testnet_package(package_directory, 'resources.zip')

			with tempfile.TemporaryDirectory() as ca_directory:
				# Act:
				await main([
					'--directory', str(Path(output_directory).relative_to(os.getcwd())),
					'setup',
					'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(Path(package_directory) / 'user_overrides.ini')
				])

				# Assert: spot check all expected output files and permissions
				assert_expected_files_and_permissions(output_directory, PEER_OUTPUT_FILES)

				# - spot check all expected CA files are present
				ca_files = sorted(str(path.relative_to(ca_directory)) for path in Path(ca_directory).glob('**/*'))
				assert ['xyz.key.pem'] == ca_files

				# - check certificates
				certificates_directory = Path(output_directory) / 'sakuya' / 'keys' / 'cert'
				assert_certificate_properties(certificates_directory / 'node.crt.pem', 'my CA CN', 'my Node CN', 375)
				assert_certificate_properties(certificates_directory / 'ca.crt.pem', 'my CA CN', 'my CA CN', 20 * 365)

# endregion


# region overrides

async def _assert_can_prepare_with_hostname(server, hostname, node_features, api_https=None):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_configuration(package_directory, node_features, server.make_url(''), api_https=api_https)
			prepare_testnet_package(package_directory, 'resources.zip')

			user_overrides_filepath = Path(package_directory) / 'overrides.properties'
			_set_hostname_in_overrides(user_overrides_filepath, hostname)

			with tempfile.TemporaryDirectory() as ca_directory:
				# Act:
				await main([
					'--directory', output_directory,
					'setup',
					'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(user_overrides_filepath)
				])

				# Assert: check user properties were applied
				node_parser = configparser.ConfigParser()
				node_parser.optionxform = str
				node_parser.read(Path(output_directory) / 'sakuya' / 'node-config' / 'resources' / 'config-node.properties')

				assert hostname == node_parser['localnode']['host']
				assert 'Foo Ninja' == node_parser['localnode']['friendlyName']


async def test_can_apply_user_overrides(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_with_hostname(server, 'symbol.fyi', NodeFeatures.PEER, False)


async def test_can_apply_custom_rest_overrides(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			_prepare_overrides(package_directory)
			prepare_sakuya_configuration(package_directory, NodeFeatures.API, server.make_url(''))
			prepare_testnet_package(package_directory, 'resources.zip')

			rest_overrides_filepath = Path(package_directory) / 'metadata.json'
			with open(rest_overrides_filepath, 'wt', encoding='utf8') as outfile:
				outfile.write('\n'.join([
					'{',
					'  "nodeMetadata": {',
					'    "_info": "",',
					'    "animal": "wolf",',
					'    "weight": "43kg",',
					'    "height": "72cm"',
					'  }'
					'}'
				]))

			with tempfile.TemporaryDirectory() as ca_directory:
				# Act:
				await main([
					'--directory', output_directory,
					'setup',
					'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(Path(package_directory) / 'user_overrides.ini'),
					'--rest-overrides', str(rest_overrides_filepath)
				])

				# Assert: check custom node metadata was applied
				with open(Path(output_directory) / 'sakuya' / 'node-config' / 'rest.json', 'rt', encoding='utf8') as rest_config_infile:
					rest_config = json.load(rest_config_infile)

				assert {
					'_info': '',
					'animal': 'wolf',
					'weight': '43kg',
					'height': '72cm'
				} == rest_config['nodeMetadata']

# endregion


# region hostname checks

async def test_can_prepare_api_with_ip_without_https(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_with_hostname(server, '1.2.3.4', NodeFeatures.API, False)


async def test_can_prepare_api_with_hostname_with_https(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_with_hostname(server, 'symbol.fyi', NodeFeatures.API, True)


async def test_can_prepare_peer_with_hostname(server):  # pylint: disable=redefined-outer-name
	await _assert_can_prepare_with_hostname(server, 'symbol.fyi', NodeFeatures.PEER, False)


async def _assert_cannot_prepare_with_hostname(
	server,  # pylint: disable=redefined-outer-name
	hostname,
	node_features,
	expected_exception,
	api_https=None
):
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_configuration(package_directory, node_features, server.make_url(''), api_https=api_https)
			prepare_testnet_package(package_directory, 'resources.zip')

			user_overrides_filepath = Path(package_directory) / 'overrides.properties'
			_set_hostname_in_overrides(user_overrides_filepath, hostname)

			with tempfile.TemporaryDirectory() as ca_directory:
				# Act + Assert:
				with pytest.raises(RuntimeError) as excinfo:
					await main([
						'--directory', output_directory,
						'setup',
						'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
						'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
						'--overrides', str(user_overrides_filepath)
					])

				assert expected_exception in str(excinfo.value)


async def test_cannot_prepare_api_with_ip_with_https(server):  # pylint: disable=redefined-outer-name
	await _assert_cannot_prepare_with_hostname(
		server,
		'1.2.3.4',
		NodeFeatures.API,
		'hostname 1.2.3.4 looks like IP address and not a hostname',
		True)


async def test_cannot_prepare_with_invalid_hostname(server):  # pylint: disable=redefined-outer-name
	await _assert_cannot_prepare_with_hostname(
		server,
		'foo bar baz',
		NodeFeatures.PEER,
		'could not resolve address for host: foo bar baz',
		False)


async def test_cannot_prepare_peer_with_https(server):  # pylint: disable=redefined-outer-name
	await _assert_cannot_prepare_with_hostname(
		server,
		'symbol.fyi',
		NodeFeatures.PEER,
		'HTTPS selected but required feature (API) is not selected',
		True)

# endregion


# region directory checks

async def test_cannot_rerun_setup_when_directory_exists(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_configuration(package_directory, NodeFeatures.PEER, server.make_url(''), api_https=False)
			_prepare_overrides(package_directory)
			prepare_testnet_package(package_directory, 'resources.zip')

			# - create resources directory
			(Path(output_directory) / 'sakuya' / 'node-config' / 'resources').mkdir(parents=True)

			with tempfile.TemporaryDirectory() as ca_directory:
				# Act + Assert:
				with pytest.raises(SystemExit) as ex_info:
					await main([
						'--directory', output_directory,
						'setup',
						'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
						'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
						'--overrides', str(Path(package_directory) / 'user_overrides.ini')
					])

				assert 1 == ex_info.value.code

# endregion


# region output-transaction-only

def _read_file_contents(filepath):
	with open(filepath, 'rb') as infile:
		return infile.read()


async def _assert_can_regenerate_links(server, node_features):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			prepare_sakuya_configuration(package_directory, node_features, server.make_url(''), api_https=False)
			_prepare_overrides(package_directory)
			prepare_testnet_package(package_directory, 'resources.zip')

			with tempfile.TemporaryDirectory() as ca_directory:
				# - run initial setup
				setup_command_args = [
					'--directory', output_directory,
					'setup',
					'--config', str(Path(package_directory) / 'sai.shoestring.ini'),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(Path(package_directory) / 'user_overrides.ini')
				]
				await main(setup_command_args)

				# - read (and delete) generated transaction
				transaction_filepath = Path(output_directory) / 'linking_transaction.dat'
				original_transaction = _read_file_contents(transaction_filepath)
				transaction_filepath.unlink()

				# Sanity:
				assert not transaction_filepath.exists()

				# Act: rerun with --output-transaction-only
				await main(setup_command_args + ['--output-transaction-only'])

				# Assert: same transaction was generated
				assert transaction_filepath.exists()

				regenerated_transaction = _read_file_contents(transaction_filepath)
				assert original_transaction == regenerated_transaction


async def test_can_regenerate_links_harvester_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_regenerate_links(server, NodeFeatures.HARVESTER)


async def test_can_regenerate_links_voter_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_regenerate_links(server, NodeFeatures.VOTER)


async def test_can_regenerate_links_full_node(server):  # pylint: disable=redefined-outer-name
	await _assert_can_regenerate_links(server, NodeFeatures.API | NodeFeatures.HARVESTER | NodeFeatures.VOTER)


async def test_linking_transaction_rejects_imported_harvesting_keys_that_do_not_match(monkeypatch, tmp_path):
	preparer = SimpleNamespace(
		config=SimpleNamespace(network=SimpleNamespace(name='testnet')),
		directories=SimpleNamespace(certificates=tmp_path, voting_keys=tmp_path),
		harvester_configurator=SimpleNamespace(
			is_imported=True,
			remote_key_pair=SimpleNamespace(public_key='remote'),
			vrf_key_pair=SimpleNamespace(public_key='vrf')),
		voter_configurator=SimpleNamespace(is_imported=False))
	monkeypatch.setattr(setup_command, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def account_links(self, _account):
			return SimpleNamespace(linked_public_key='other', vrf_public_key='vrf', voting_public_keys=[])

	monkeypatch.setattr(setup_command, 'SymbolConnector', Connector)
	with pytest.raises(RuntimeError, match='imported harvesting keys'):
		await setup_command._prepare_linking_transaction(preparer, 'http://node')


async def test_linking_transaction_rejects_imported_voting_keys_that_do_not_match(monkeypatch, tmp_path):
	preparer = SimpleNamespace(
		config=SimpleNamespace(network=SimpleNamespace(name='testnet')),
		directories=SimpleNamespace(certificates=tmp_path, voting_keys=tmp_path),
		harvester_configurator=SimpleNamespace(is_imported=False),
		voter_configurator=SimpleNamespace(is_imported=True))
	monkeypatch.setattr(setup_command, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(
		setup_command,
		'inspect_voting_key_files',
		lambda _path: [SimpleNamespace(public_key='local', start_epoch=1, end_epoch=2)])

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def account_links(self, _account):
			return SimpleNamespace(linked_public_key=None, vrf_public_key=None, voting_public_keys=[])

	monkeypatch.setattr(setup_command, 'SymbolConnector', Connector)
	with pytest.raises(RuntimeError, match='imported voting keys'):
		await setup_command._prepare_linking_transaction(preparer, 'http://node')


async def test_initial_setup_rejects_symbolic_link_ca_key(tmp_path):
	output_directory = tmp_path / 'output'
	output_directory.mkdir()
	real_key = tmp_path / 'real-ca.key.pem'
	real_key.write_text('key', encoding='utf8')
	ca_key_path = tmp_path / 'ca.key.pem'
	ca_key_path.symlink_to(real_key)

	with pytest.raises(RuntimeError, match='must not be a symbolic link'):
		await setup_command._run_initial_setup_atomically(SimpleNamespace(
			directory=output_directory,
			ca_key_path=ca_key_path,
			output_transaction_only=False,
			command='setup'))


@pytest.mark.parametrize('failure', [OSError, KeyboardInterrupt, SystemExit])
async def test_initial_setup_removes_published_ca_key_when_commit_fails(monkeypatch, tmp_path, failure):
	output_directory = tmp_path / 'output'
	output_directory.mkdir()
	ca_key_path = tmp_path / 'keys' / 'ca.key.pem'
	ca_key_path.parent.mkdir()

	async def fake_run_setup(args):
		args.ca_key_path.parent.mkdir(parents=True, exist_ok=True)
		args.ca_key_path.write_text('generated', encoding='utf8')

	monkeypatch.setattr(setup_command, '_run_setup', fake_run_setup)
	monkeypatch.setattr(setup_command, 'replace_paths', lambda *_args: (_ for _ in ()).throw(failure('commit failed')))

	with pytest.raises(failure, match='commit failed'):
		await setup_command._run_initial_setup_atomically(SimpleNamespace(
			directory=output_directory,
			ca_key_path=ca_key_path,
			output_transaction_only=False,
			command='setup'))

	assert not ca_key_path.exists()


async def test_initial_setup_publishes_ca_key_in_output_directory(monkeypatch, tmp_path):
	output_directory = tmp_path / 'output'
	ca_key_path = output_directory / 'ca.key.pem'

	async def fake_run_setup(args):
		args.ca_key_path.write_text('generated', encoding='utf8')

	committed_paths = []

	def fake_replace_paths(staged_directory, output_directory, managed_paths):
		committed_paths.extend(managed_paths)
		source = Path(staged_directory) / 'ca.key.pem'
		source.replace(Path(output_directory) / 'ca.key.pem')

	monkeypatch.setattr(setup_command, '_run_setup', fake_run_setup)
	monkeypatch.setattr(setup_command, 'replace_paths', fake_replace_paths)

	await setup_command._run_initial_setup_atomically(SimpleNamespace(
		directory=output_directory,
		ca_key_path=ca_key_path,
		output_transaction_only=False,
		command='setup'))

	assert ca_key_path.read_text(encoding='utf8') == 'generated'
	assert 'ca.key.pem' in committed_paths


async def test_run_setup_rejects_existing_resources_on_initial_setup(monkeypatch, tmp_path):
	class FakePreparer:
		def __init__(self, *_args):
			self.directories = SimpleNamespace(resources=SimpleNamespace(exists=lambda: True))

		def __enter__(self):
			return self

		def __exit__(self, *_args):
			return False

	monkeypatch.setattr(setup_command, 'parse_sakuya_configuration', lambda _path: SimpleNamespace())
	monkeypatch.setattr(setup_command, 'Preparer', FakePreparer)

	with pytest.raises(SystemExit) as ex_info:
		await setup_command._run_setup(SimpleNamespace(
			config=tmp_path / 'config.ini',
			directory=tmp_path,
			command='setup',
			output_transaction_only=False))

	assert 1 == ex_info.value.code

# endregion
