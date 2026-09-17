import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sakuya.commands import reset_data
from sakuya.commands.reset_data import _copy_file_if_exists, _copy_votes_backup, _raise_walk_error, _validate_target


def test_validate_target_rejects_nested_symbolic_link():
	with tempfile.TemporaryDirectory() as output_directory:
		data_directory = Path(output_directory) / 'sakuya' / 'data'
		data_directory.mkdir(parents=True)
		(data_directory / 'external').symlink_to(Path(output_directory).parent)

		with pytest.raises(RuntimeError, match='symbolic link'):
			_validate_target(Path(output_directory), 'data')


def test_validate_target_rejects_symbolic_link_managed_root(tmp_path):
	(tmp_path / 'sakuya-target').mkdir()
	(tmp_path / 'sakuya').symlink_to(tmp_path / 'sakuya-target', target_is_directory=True)
	with pytest.raises(RuntimeError, match='managed directory does not exist'):
		_validate_target(tmp_path, 'data')


def test_validate_target_rejects_symbolic_link_in_votes_backup():
	with tempfile.TemporaryDirectory() as output_directory:
		data_directory = Path(output_directory) / 'sakuya' / 'data'
		votes_backup = data_directory / 'votes_backup'
		votes_backup.mkdir(parents=True)
		(votes_backup / '100').symlink_to(Path(output_directory).parent)

		with pytest.raises(RuntimeError, match='symbolic link'):
			_validate_target(Path(output_directory), 'data')


def test_reset_helpers_reject_invalid_paths(tmp_path):
	error = OSError('broken')
	error.filename = 'broken'
	with pytest.raises(RuntimeError, match='cannot inspect reset target'):
		_raise_walk_error(error)

	with pytest.raises(RuntimeError, match='managed directory does not exist'):
		_validate_target(tmp_path, 'data')

	managed = tmp_path / 'sakuya'
	managed.mkdir()
	with pytest.raises(RuntimeError, match='not a managed directory'):
		_validate_target(tmp_path, 'data')

	source = managed / 'source'
	source.mkdir()
	(source / 'file').mkdir()
	with pytest.raises(RuntimeError, match='cannot preserve unexpected path'):
		_copy_file_if_exists(source / 'file', tmp_path / 'copy')


def test_copy_votes_backup_handles_empty_and_invalid_backups(tmp_path):
	data = tmp_path / 'data'
	backup = tmp_path / 'backup'
	data.mkdir()
	backup.mkdir()
	assert _copy_votes_backup(data, backup) is None

	votes_backup = data / 'votes_backup'
	votes_backup.mkdir()
	(votes_backup / 'not-an-epoch').mkdir()
	with pytest.raises(RuntimeError, match='invalid voting backup directory'):
		_copy_votes_backup(data, backup)

	votes_backup = data / 'votes_backup'
	(votes_backup / 'not-an-epoch').rmdir()
	file_path = votes_backup / 'file'
	file_path.write_text('not a directory', encoding='utf8')
	assert _copy_votes_backup(data, backup) is None

	file_path.unlink()
	votes_backup.rmdir()
	votes_backup.symlink_to(tmp_path, target_is_directory=True)
	with pytest.raises(RuntimeError, match='cannot inspect unexpected path'):
		_copy_votes_backup(data, backup)


def test_copy_votes_backup_rejects_symbolic_link_epoch(tmp_path):
	data = tmp_path / 'data'
	backup = tmp_path / 'backup'
	votes_backup = data / 'votes_backup'
	votes_backup.mkdir(parents=True)
	(votes_backup / '100').symlink_to(tmp_path, target_is_directory=True)
	with pytest.raises(RuntimeError, match='cannot preserve unexpected path'):
		_copy_votes_backup(data, backup)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [OSError, KeyboardInterrupt, SystemExit])
async def test_reset_data_restores_directories_when_recreation_fails(monkeypatch, tmp_path, failure):
	managed_root = tmp_path / 'sakuya'
	data = managed_root / 'data'
	logs = managed_root / 'logs'
	data.mkdir(parents=True)
	logs.mkdir()
	(data / 'keep').write_text('data', encoding='utf8')
	(logs / 'keep').write_text('logs', encoding='utf8')
	monkeypatch.setattr(reset_data, 'parse_sakuya_configuration', lambda _config: SimpleNamespace(node=SimpleNamespace(full_api=False)))

	def fail_copy(*_args):
		raise failure('recreation failed')

	monkeypatch.setattr(reset_data, '_copy_file_if_exists', fail_copy)
	with pytest.raises(failure, match='recreation failed'):
		await reset_data.run_main(SimpleNamespace(
			config='config.ini', directory=tmp_path, purge_harvesters=False))

	assert 'data' == (data / 'keep').read_text(encoding='utf8')
	assert 'logs' == (logs / 'keep').read_text(encoding='utf8')
