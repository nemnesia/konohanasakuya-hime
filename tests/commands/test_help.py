import runpy
import sys

import pytest

from sakuya.__main__ import main

# pylint: disable=invalid-name


async def _assert_can_run_help(capsys, args):
	# Act + Assert:
	with pytest.raises(SystemExit):
		await main(args)

	# Assert: spot check a few expected strings
	out = capsys.readouterr().out
	assert '\nSakuya Tool\n' in out
	assert '\nsubcommands:\n' in out


async def test_can_run_help_when_help_option_specified(capsys):
	await _assert_can_run_help(capsys, ['--help'])


async def test_can_run_help_when_no_command_provided(capsys):
	await _assert_can_run_help(capsys, [])


def test_main_module_guard_runs(monkeypatch):
	import sakuya.__main__ as main_module

	run_calls = []

	def fake_run(coroutine):
		run_calls.append(list(sys.argv[1:]))
		coroutine.close()

	monkeypatch.setattr(main_module.asyncio, 'run', fake_run)
	monkeypatch.setattr(sys, 'argv', ['sakuya', '--help'])
	runpy.run_path(main_module.__file__, run_name='__main__')

	assert [['--help']] == run_calls
