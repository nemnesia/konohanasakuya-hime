import tempfile
from collections import namedtuple
from pathlib import Path

from sakuya.internal.ConfigurationManager import load_shoestring_patches_from_file
from sakuya.wizard.shoestring_dispatcher import dispatch_shoestring_command
from sakuya.wizard.ShoestringOperation import ShoestringOperation

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
		'welcome': WelcomeScreen(ShoestringOperation.SETUP)
	}


# pylint: disable=invalid-name


async def test_can_dispatch_setup_command():
	# Arrange:
	dispatched_args = []
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')

		with tempfile.TemporaryDirectory() as output_directory:
			# Act:
			await dispatch_shoestring_command(
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

			# - shoestring configuration files were created
			shoestring_directory = Path(output_directory)
			assert shoestring_directory.exists()
			assert (shoestring_directory / 'config.ini').exists()
			assert (shoestring_directory / 'overrides.ini').exists()
			assert (shoestring_directory / 'rest_overrides.json').exists()


async def test_can_dispatch_setup_command_with_custom_rest_overrides():
	# Arrange:
	dispatched_args = []
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')

		with tempfile.TemporaryDirectory() as output_directory:
			# Act:
			await dispatch_shoestring_command(
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

			# - shoestring configuration files were created
			shoestring_directory = Path(output_directory)
			assert shoestring_directory.exists()
			assert (shoestring_directory / 'config.ini').exists()
			assert (shoestring_directory / 'overrides.ini').exists()
			assert (shoestring_directory / 'rest_overrides.json').exists()


def _prepare_shoestring_file(output_filename):
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
		shoestring_directory = Path(package_directory)
		shoestring_filepath = shoestring_directory / 'config.ini'
		_prepare_shoestring_file(shoestring_filepath)

		# Act:
		await dispatch_shoestring_command({
			'obligatory': ObligatoryScreen(package_directory, str(Path(package_directory) / 'ca.pem')),
			'network-type': SingleValueScreen('sai'),
			'welcome': WelcomeScreen(ShoestringOperation.UPGRADE)
		}, _create_executor(dispatched_args))

		# Assert:
		assert [
			'--directory', package_directory,
			'upgrade',
			'--config', f'{shoestring_directory}/config.ini',
			'--overrides', f'{shoestring_directory}/overrides.ini',
		] == dispatched_args

		# node_patches is a superset of expected_keys
		node_patches = load_shoestring_patches_from_file(shoestring_filepath, ['node'])
		for key in expected_keys:
			assert key in node_patches
