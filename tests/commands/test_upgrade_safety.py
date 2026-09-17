import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sakuya.commands import upgrade as upgrade_command
from sakuya.commands.upgrade import _prepare_staged_directories
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.Preparer import Preparer


def test_prepare_staged_directories_preserves_dbdata():
	with tempfile.TemporaryDirectory() as output_directory:
		root = Path(output_directory) / 'sakuya'
		for name in ('node-config', 'startup', 'mongo', 'https-proxy', 'rest-cache', 'dbdata'):
			(root / name).mkdir(parents=True)
		(root / 'dbdata' / 'database.dat').write_text('keep', encoding='utf8')

		config = SimpleNamespace(node=SimpleNamespace(
			features=NodeFeatures.API,
			full_api=True,
			api_https=False
		))
		_prepare_staged_directories(Preparer.DirectoryLocator(None, Path(output_directory)), config)

		assert 'keep' == (root / 'dbdata' / 'database.dat').read_text(encoding='utf8')
		assert (root / 'node-config').is_dir()
		assert (root / 'rest-cache').is_dir()
		assert (root / 'startup').is_dir() is False
		assert (root / 'mongo').is_dir() is False


def test_prepare_staged_directories_creates_full_api_and_https_directories(tmp_path):
	config = SimpleNamespace(node=SimpleNamespace(
		features=NodeFeatures.API,
		full_api=True,
		api_https=True))
	directories = Preparer.DirectoryLocator(None, tmp_path)
	upgrade_command._prepare_staged_directories(directories, config)

	assert directories.dbdata.is_dir()
	assert directories.rest_cache.is_dir()
	assert directories.https_proxy.is_dir()


async def test_upgrade_requires_existing_node_configuration(monkeypatch, tmp_path):
	config = SimpleNamespace(node=SimpleNamespace(features=NodeFeatures.PEER))
	monkeypatch.setattr(upgrade_command, 'parse_sakuya_configuration', lambda _path: config)

	with pytest.raises(RuntimeError, match='node configuration directory does not exist'):
		await upgrade_command.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))
