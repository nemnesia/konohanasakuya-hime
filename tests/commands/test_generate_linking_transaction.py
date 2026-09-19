import tempfile
from pathlib import Path

import pytest

from sakuya.__main__ import main, parse_args
from sakuya.internal.NodeFeatures import NodeFeatures

from ..test.ConfigurationTestUtils import prepare_sakuya_setup_configuration
from ..test.TestPackager import prepare_testnet_package
from .test_setup import _prepare_overrides, local_test_package

# pylint: disable=invalid-name


@pytest.fixture
async def server(aiohttp_client):
	from ..test.MockNodewatchServer import setup_mock_nodewatch_server

	return await setup_mock_nodewatch_server(aiohttp_client, True)


def _snapshot_files(directory):
	return {
		str(filepath.relative_to(directory)): (filepath.read_bytes(), filepath.stat().st_mtime_ns)
		for filepath in Path(directory).glob('**/*')
		if filepath.is_file() and 'linking_transaction.dat' != filepath.name
	}


@pytest.mark.parametrize(
	'node_features',
	[NodeFeatures.HARVESTER, NodeFeatures.VOTER, NodeFeatures.API | NodeFeatures.HARVESTER | NodeFeatures.VOTER])
async def test_can_regenerate_linking_transaction_without_changing_setup_files(
	server, node_features):  # pylint: disable=redefined-outer-name
	with tempfile.TemporaryDirectory() as output_directory:
		with tempfile.TemporaryDirectory() as package_directory:
			config_filepath = prepare_sakuya_setup_configuration(
				package_directory, node_features, server.make_url(''), api_https=False)
			_prepare_overrides(package_directory)
			prepare_testnet_package(package_directory, 'resources.zip')

			with tempfile.TemporaryDirectory() as ca_directory:
				await main([
					'--directory', output_directory,
					'setup',
					'--config', str(config_filepath),
					'--ca-key-path', str(Path(ca_directory) / 'xyz.key.pem'),
					'--overrides', str(Path(package_directory) / 'user_overrides.ini')
				])

				transaction_filepath = Path(output_directory) / 'linking_transaction.dat'
				original_transaction = transaction_filepath.read_bytes()
				original_files = _snapshot_files(output_directory)
				transaction_filepath.unlink()

				await main([
					'--directory', output_directory,
					'generate-linking-transaction',
					'--config', str(config_filepath)
				])

				assert original_transaction == transaction_filepath.read_bytes()
				assert original_files == _snapshot_files(output_directory)


def test_setup_no_longer_accepts_output_transaction_only():
	with pytest.raises(SystemExit):
		parse_args(['setup', '--output-transaction-only'])
