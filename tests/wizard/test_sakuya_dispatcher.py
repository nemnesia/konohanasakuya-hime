import json
import tempfile
from collections import namedtuple
from pathlib import Path

from sakuya.internal.ConfigurationManager import load_configuration_patches_from_file
from sakuya.wizard.sakuya_dispatcher import dispatch_sakuya_command
from sakuya.wizard.SakuyaOperation import SakuyaOperation

from ..test.TestPackager import prepare_testnet_package

CertificatesScreen = namedtuple('CertificatesScreen', ['ca_common_name', 'node_common_name'])
NodeSettingsScreen = namedtuple('NodeSettingsScreen', ['domain_name', 'friendly_name', 'api_https', 'metadata_info'])
ObligatoryScreen = namedtuple('ObligatoryScreen', ['destination_directory', 'ca_pem_path'])
SingleValueScreen = namedtuple('SingleValueScreen', ['current_value'])
ToggleScreen = namedtuple('ToggleScreen', ['active'])
WelcomeScreen = namedtuple('WelcomeScreen', ['operation'])


def _create_executor(dispatched_args):
	async def executor(args):
		dispatched_args.extend(args)

	return executor


def _strip_folder(path):
	return Path(path).name


def _create_setup_screens(
	package_directory,
	output_directory,
	node_type,
	node_metadata,
):  # pylint: disable=too-many-arguments,too-many-positional-arguments
	return {
		'obligatory': ObligatoryScreen(output_directory, Path(package_directory) / 'ca.pem'),
		'node-settings': NodeSettingsScreen('symbol.fyi', 'node explorer', False, node_metadata),
		'network-type': SingleValueScreen(f'file://{Path(package_directory) / "resources.zip"}'),
		'node-type': SingleValueScreen(node_type),
		'harvesting': ToggleScreen(False),
		'voting': ToggleScreen(False),
		'certificates': CertificatesScreen('ca', 'peer'),
		'welcome': WelcomeScreen(SakuyaOperation.SETUP)
	}


# pylint: disable=invalid-name


async def test_can_dispatch_setup_command():
	# Arrange:
	dispatched_args = []
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')

		with tempfile.TemporaryDirectory() as output_directory:
			# Act:
			await dispatch_sakuya_command(
				_create_setup_screens(package_directory, output_directory, 'peer', None),
				_create_executor(dispatched_args))

			# Assert:
			for i in (4, 8, 10):
				dispatched_args[i] = _strip_folder(dispatched_args[i])  # strip temporary folder used during setup

			assert [
				'--directory', output_directory,
				'setup',
				'--config', 'config.ini',
				'--ca-key-path', str(Path(package_directory) / 'ca.pem'),
				'--overrides', 'overrides.ini',
				'--rest-overrides', 'rest_overrides.json'
			] == dispatched_args

			# - Sakuya configuration files were created
			sakuya_directory = Path(output_directory)
			assert sakuya_directory.exists()
			assert (sakuya_directory / 'config.ini').exists()
			assert (sakuya_directory / 'overrides.ini').exists()
			assert (sakuya_directory / 'rest_overrides.json').exists()
			assert '[node.localnode]' in (sakuya_directory / 'overrides.ini').read_text(encoding='utf8')
			assert {} == json.loads((sakuya_directory / 'rest_overrides.json').read_text(encoding='utf8'))['nodeMetadata']


async def test_can_dispatch_setup_command_with_custom_rest_overrides():
	# Arrange:
	dispatched_args = []
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')

		with tempfile.TemporaryDirectory() as output_directory:
			# Act:
			await dispatch_sakuya_command(
				_create_setup_screens(package_directory, output_directory, 'dual', '{"animal": "wolf"}'),
				_create_executor(dispatched_args))

			# Assert:
			for i in (4, 8, 10):
				dispatched_args[i] = _strip_folder(dispatched_args[i])  # strip temporary folder used during setup

			assert [
				'--directory', output_directory,
				'setup',
				'--config', 'config.ini',
				'--ca-key-path', str(Path(package_directory) / 'ca.pem'),
				'--overrides', 'overrides.ini',
				'--rest-overrides', 'rest_overrides.json'
			] == dispatched_args

			# - Sakuya configuration files were created
			sakuya_directory = Path(output_directory)
			assert sakuya_directory.exists()
			assert (sakuya_directory / 'config.ini').exists()
			assert (sakuya_directory / 'overrides.ini').exists()
			assert (sakuya_directory / 'rest_overrides.json').exists()
			assert 'host = symbol.fyi' in (sakuya_directory / 'overrides.ini').read_text(encoding='utf8')
			assert {'animal': 'wolf'} == json.loads(
				(sakuya_directory / 'rest_overrides.json').read_text(encoding='utf8'))['nodeMetadata']


def _prepare_sakuya_file(output_filename):
	with open(output_filename, 'wt', encoding='utf8') as outfile:
		outfile.write('\n'.join([
			'[network]',
			'ubuntuCore = 24.04',
			'',
			'[imports]',
			'rest = symbol-rest:2.4.0',
			'',
			'[transaction]',
			'fee = 20',
			'',
			'[node]',
			'apiHttps = false',
			'caCommonName = upgrade',
			'nodeCommonName = node.upgrade',
			'features = API'
		]))


async def test_can_dispatch_upgrade_command():
	# Arrange:
	expected_keys = [
		('node', 'apiHttps', 'false'),
		('node', 'caCommonName', 'upgrade'),
		('node', 'nodeCommonName', 'node.upgrade'),
		('node', 'features', 'API')
	]
	dispatched_args = []
	with tempfile.TemporaryDirectory() as package_directory:
		sakuya_directory = Path(package_directory)
		sakuya_filepath = sakuya_directory / 'config.ini'
		_prepare_sakuya_file(sakuya_filepath)

		# Act:
		await dispatch_sakuya_command({
			'obligatory': ObligatoryScreen(package_directory, str(Path(package_directory) / 'ca.pem')),
			'network-type': SingleValueScreen('sai'),
			'welcome': WelcomeScreen(SakuyaOperation.UPGRADE)
		}, _create_executor(dispatched_args))

		# Assert:
		assert [
			'--directory', package_directory,
			'upgrade',
			'--config', f'{sakuya_directory}/config.ini',
			'--overrides', f'{sakuya_directory}/overrides.ini',
		] == dispatched_args

		# node_patches is a superset of expected_keys
		node_patches = load_configuration_patches_from_file(sakuya_filepath, ['node'])
		for key in expected_keys:
			assert key in node_patches
