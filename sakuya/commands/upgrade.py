import shutil
import tempfile
from argparse import Namespace
from pathlib import Path

from sakuya.internal.AtomicFileSystem import replace_paths
from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration

from .setup import add_arguments as add_setup_arguments
from .setup import run_main as run_setup_main

# upgradeで管理する生成物だけを列挙する。
# staging側に存在しない条件付き生成物は、不要な生成物として削除する。
UPGRADE_MANAGED_PATHS = (
	'sakuya/node-config',
	'sakuya/startup',
	'sakuya/mongo',
	'sakuya/https-proxy/nginx.conf.erb',
	'docker-compose.yaml',
	'docker-compose-recovery.yaml'
)


def _load_harvester_configuration_patches(config_manager):
	config_keys = [
		('harvesting', 'harvesterSigningPrivateKey'),
		('harvesting', 'harvesterVrfPrivateKey')
	]
	values = config_manager.lookup('config-harvesting.properties', config_keys)
	return [(*tuple[0], tuple[1]) for tuple in zip(config_keys, values)]


def _prepare_staged_directories(staged_directories, config):
	"""生成物のstagingに必要な親だけを作成する。"""
	staged_directories.node_config.mkdir(parents=True, exist_ok=True, mode=0o700)
	staged_directories.node_config.chmod(0o700)
	staged_directories.resources.mkdir(parents=True, exist_ok=True, mode=0o700)
	staged_directories.resources.chmod(0o700)
	if NodeFeatures.API in config.node.features and config.node.api_https:
		staged_directories.https_proxy.mkdir(parents=True, exist_ok=True, mode=0o700)


async def run_main(args):
	config = parse_sakuya_configuration(args.config)
	output_directory = Path(args.directory).absolute()
	directories = Preparer.DirectoryLocator(None, output_directory)

	config_manager = ConfigurationManager(directories.resources)
	harvester_config_patches = None
	if NodeFeatures.HARVESTER in config.node.features:
		harvester_config_patches = _load_harvester_configuration_patches(config_manager)

	if not directories.node_config.exists():
		raise RuntimeError(f'node configuration directory does not exist at path {directories.node_config}')

	staged_directory = Path(tempfile.mkdtemp(dir=output_directory.parent, prefix='.sakuya-upgrade-'))
	try:
		staged_directories = Preparer.DirectoryLocator(None, staged_directory)
		_prepare_staged_directories(staged_directories, config)

		staged_args = Namespace(**vars(args))
		staged_args.directory = staged_directory
		await run_setup_main(staged_args)

		if harvester_config_patches:
			harvesting_properties_filepath = staged_directories.resources / 'config-harvesting.properties'
			harvesting_properties_filepath.chmod(0o600)
			ConfigurationManager(staged_directories.resources).patch(
				harvesting_properties_filepath.name, harvester_config_patches)
			harvesting_properties_filepath.chmod(0o400)

		replace_paths(staged_directory, output_directory, UPGRADE_MANAGED_PATHS)
	finally:
		shutil.rmtree(staged_directory, ignore_errors=True)


def add_arguments(parser):
	add_setup_arguments(parser, False)
	parser.set_defaults(func=run_main)
