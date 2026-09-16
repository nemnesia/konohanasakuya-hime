import gettext
from pathlib import Path

import pytest

from shoestring.__main__ import parse_args
from shoestring.internal.Directory import resolve_directory


def _parse_args(args):
	gettext.install('messages')
	return parse_args(args)


def test_explicit_directory_has_priority(monkeypatch, tmp_path):
	environment_directory = tmp_path / 'environment'
	current_directory = tmp_path / 'current'
	command_directory = tmp_path / 'command'
	monkeypatch.setenv('SHOESTRING_HOME', str(environment_directory))
	current_directory.mkdir()
	monkeypatch.chdir(current_directory)

	assert command_directory == resolve_directory(command_directory)


def test_environment_directory_is_used_when_option_is_omitted(monkeypatch, tmp_path):
	environment_directory = tmp_path / 'environment'
	monkeypatch.setenv('SHOESTRING_HOME', str(environment_directory))

	assert environment_directory == resolve_directory()
	args = _parse_args(['health', '--config', 'config.ini'])

	assert environment_directory == args.directory


def test_current_directory_is_used_when_option_and_environment_are_omitted(monkeypatch, tmp_path):
	monkeypatch.delenv('SHOESTRING_HOME', raising=False)
	monkeypatch.chdir(tmp_path)

	assert Path.cwd() == resolve_directory()
	args = _parse_args(['health', '--config', 'config.ini'])

	assert tmp_path == args.directory


def test_cli_directory_option_has_priority_over_environment(monkeypatch, tmp_path):
	environment_directory = tmp_path / 'environment'
	command_directory = tmp_path / 'command'
	monkeypatch.setenv('SHOESTRING_HOME', str(environment_directory))

	args = _parse_args(['--directory', str(command_directory), 'health', '--config', 'config.ini'])

	assert command_directory == args.directory


def test_cli_directory_option_is_a_top_level_option(tmp_path):
	args = _parse_args(['--directory', str(tmp_path), 'health', '--config', 'config.ini'])

	assert tmp_path == args.directory

	with pytest.raises(SystemExit):
		_parse_args(['health', '--directory', str(tmp_path), '--config', 'config.ini'])


@pytest.mark.parametrize('command, command_args', [
	('setup', ['--config', 'config.ini', '--ca-key-path', 'ca.key.pem']),
	('health', ['--config', 'config.ini']),
	('upgrade', ['--config', 'config.ini']),
	('renew-certificates', ['--config', 'config.ini', '--ca-key-path', 'ca.key.pem']),
	('renew-voting-keys', ['--config', 'config.ini']),
	('reset-data', ['--config', 'config.ini']),
])
def test_target_commands_receive_resolved_directory(tmp_path, command, command_args):
	args = _parse_args(['--directory', str(tmp_path), command, *command_args])

	assert tmp_path == args.directory
