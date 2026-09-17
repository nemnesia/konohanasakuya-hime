from pathlib import Path

import pytest

from sakuya.internal import AtomicFileSystem


def test_replace_paths_skips_missing_sources_and_targets(tmp_path):
	staged = tmp_path / 'staged'
	output = tmp_path / 'output'
	staged.mkdir()
	output.mkdir()

	AtomicFileSystem.replace_paths(staged, output, ('missing',))

	assert [] == list(output.iterdir())


def test_replace_paths_replaces_files_and_rolls_back_on_failure(monkeypatch, tmp_path):
	staged = tmp_path / 'staged'
	output = tmp_path / 'output'
	staged.mkdir()
	output.mkdir()
	(output / 'one').write_text('old-one', encoding='utf8')
	(output / 'two').write_text('old-two', encoding='utf8')
	(staged / 'one').write_text('new-one', encoding='utf8')
	(staged / 'two').write_text('new-two', encoding='utf8')

	original_replace = AtomicFileSystem.os.replace
	replace_count = 0

	def fail_on_second_install(source, target):
		nonlocal replace_count
		replace_count += 1
		if 4 == replace_count:
			raise OSError('simulated replacement failure')
		return original_replace(source, target)

	monkeypatch.setattr(AtomicFileSystem.os, 'replace', fail_on_second_install)
	with pytest.raises(OSError, match='simulated replacement failure'):
		AtomicFileSystem.replace_paths(staged, output, ('one', 'two'))

	assert 'old-one' == (output / 'one').read_text(encoding='utf8')
	assert 'old-two' == (output / 'two').read_text(encoding='utf8')


def test_replace_paths_removes_installed_directory_during_rollback(monkeypatch, tmp_path):
	staged = tmp_path / 'staged'
	output = tmp_path / 'output'
	(staged / 'one').mkdir(parents=True)
	(staged / 'two').write_text('new-two', encoding='utf8')
	(output / 'one').mkdir(parents=True)
	(output / 'two').write_text('old-two', encoding='utf8')

	original_replace = AtomicFileSystem.os.replace
	replace_count = 0

	def fail_on_second_install(source, target):
		nonlocal replace_count
		replace_count += 1
		if 4 == replace_count:
			raise OSError('simulated replacement failure')
		return original_replace(source, target)

	monkeypatch.setattr(AtomicFileSystem.os, 'replace', fail_on_second_install)
	with pytest.raises(OSError, match='simulated replacement failure'):
		AtomicFileSystem.replace_paths(staged, output, ('one', 'two'))

	assert (output / 'one').is_dir()
	assert 'old-two' == (output / 'two').read_text(encoding='utf8')
