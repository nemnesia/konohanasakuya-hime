from pathlib import Path
from types import SimpleNamespace

import pytest

from sakuya.commands import upgrade as upgrade_command
from sakuya.commands.upgrade import _prepare_staged_directories
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.Preparer import Preparer


def test_prepare_staged_directories_only_creates_generated_parents(tmp_path):
	root = tmp_path / 'sakuya'
	for name in ('data', 'dbdata', 'logs', 'keys', 'seed', 'rest-cache'):
		(root / name).mkdir(parents=True)
	(root / 'data' / 'runtime.dat').write_text('keep', encoding='utf8')
	(root / 'dbdata' / 'database.dat').write_text('keep', encoding='utf8')

	config = SimpleNamespace(node=SimpleNamespace(
		features=NodeFeatures.API,
		full_api=True,
		api_https=True
	))
	_prepare_staged_directories(Preparer.DirectoryLocator(None, tmp_path), config)

	assert 'keep' == (root / 'data' / 'runtime.dat').read_text(encoding='utf8')
	assert 'keep' == (root / 'dbdata' / 'database.dat').read_text(encoding='utf8')
	assert (root / 'node-config').is_dir()
	assert (root / 'https-proxy').is_dir()
	for name in ('startup', 'mongo'):
		assert (root / name).is_dir() is False
	assert (root / 'rest-cache').is_dir()


def test_prepare_staged_directories_creates_full_api_and_https_directories(tmp_path):
	config = SimpleNamespace(node=SimpleNamespace(
		features=NodeFeatures.API,
		full_api=True,
		api_https=True))
	directories = Preparer.DirectoryLocator(None, tmp_path)
	upgrade_command._prepare_staged_directories(directories, config)

	assert directories.node_config.is_dir()
	assert directories.https_proxy.is_dir()
	assert directories.dbdata.is_dir() is False
	assert directories.rest_cache.is_dir() is False


async def test_upgrade_requires_existing_node_configuration(monkeypatch, tmp_path):
	config = SimpleNamespace(node=SimpleNamespace(features=NodeFeatures.PEER))
	monkeypatch.setattr(upgrade_command, 'parse_sakuya_configuration', lambda _path: config)

	with pytest.raises(RuntimeError, match='node configuration directory does not exist'):
		await upgrade_command.run_main(SimpleNamespace(config='config.ini', directory=tmp_path))
