import builtins
import sys
from types import SimpleNamespace

import pytest

from sakuya.wizard import __main__ as wizard_main


class FakeContainer:
	def __init__(self, *args, **kwargs):
		self.children = args[0] if args and isinstance(args[0], list) else []
		self.content = kwargs.get('content')


class FakeLayout:
	def __init__(self, *_args, **_kwargs):
		pass

	def focus(self, _element):
		pass


class FakeScreenContainer:
	def __init__(self, navbar):
		self.navbar = navbar
		self.current = 'current'
		self.message_box = None
		self._welcome = SimpleNamespace(buttons=[SimpleNamespace(handler=None)])

	def get(self, name):
		assert 'welcome' == name
		return self._welcome


def _patch_wizard_dependencies(monkeypatch, result, next_text):
	class Translation:
		def install(self):
			monkeypatch.setattr(builtins, '_', lambda message: message, raising=False)

	monkeypatch.setattr(wizard_main.gettext, 'translation', lambda *_args, **_kwargs: Translation())
	monkeypatch.setattr(wizard_main, 'create_message_box_float', lambda: SimpleNamespace(visible=False))
	monkeypatch.setattr(wizard_main.keybindings, 'initialize', lambda _visible: 'keys')
	monkeypatch.setattr(wizard_main.styles, 'initialize', lambda: 'styles')
	next_button = SimpleNamespace(text=next_text, state_filter=None, handler=None)
	navbar = SimpleNamespace(container='navbar', next=next_button, prev=SimpleNamespace(handler=None))
	monkeypatch.setattr(wizard_main.navigation, 'initialize', lambda: navbar)
	monkeypatch.setattr(wizard_main, 'ScreenContainer', FakeScreenContainer)
	monkeypatch.setattr(wizard_main, 'load_screens', lambda screens: None)
	monkeypatch.setattr(wizard_main, 'HSplit', FakeContainer)
	monkeypatch.setattr(wizard_main, 'Window', FakeContainer)
	monkeypatch.setattr(wizard_main, 'ConditionalContainer', FakeContainer)
	monkeypatch.setattr(wizard_main, 'FloatContainer', FakeContainer)
	monkeypatch.setattr(wizard_main, 'FormattedTextControl', FakeContainer)
	monkeypatch.setattr(wizard_main, 'Label', FakeContainer)
	monkeypatch.setattr(wizard_main, 'ValidationToolbar', FakeContainer)
	monkeypatch.setattr(wizard_main, 'Layout', FakeLayout)
	monkeypatch.setattr(wizard_main, 'TitleBar', lambda _content: SimpleNamespace())

	def create_next_clicked_handler(_screens, activate_screen, *_args):
		activate_screen('activated')
		return lambda: None

	monkeypatch.setattr(wizard_main, 'create_next_clicked_handler', create_next_clicked_handler)
	monkeypatch.setattr(wizard_main, 'create_prev_clicked_handler', lambda *_args: lambda: None)
	monkeypatch.setattr(wizard_main, 'create_operation_button_handler', lambda *_args: lambda: None)

	class Application:
		def __init__(self, *_args, **_kwargs):
			self.exit = lambda: None

		async def run_async(self):
			return result

	monkeypatch.setattr(wizard_main, 'Application', Application)
	return navbar


@pytest.mark.asyncio
async def test_wizard_main_returns_when_application_is_cancelled(monkeypatch):
	_patch_wizard_dependencies(monkeypatch, True, 'Next')
	await wizard_main.main()


@pytest.mark.asyncio
async def test_wizard_main_dispatches_selected_operation(monkeypatch):
	navbar = _patch_wizard_dependencies(monkeypatch, None, 'wizard-button-finish')
	dispatched = []

	async def dispatch(*_args):
		dispatched.append(True)

	monkeypatch.setattr(wizard_main, 'dispatch_sakuya_command', dispatch)
	await wizard_main.main()

	assert [True] == dispatched
	assert navbar.next.handler is not None


def test_wizard_module_guard_runs(monkeypatch):
	import runpy

	run_calls = []

	def fake_run(coroutine):
		run_calls.append(True)
		coroutine.close()

	monkeypatch.setattr(wizard_main.asyncio, 'run', fake_run)
	loaded_module = sys.modules.pop('sakuya.wizard.__main__')
	try:
		runpy.run_module('sakuya.wizard.__main__', run_name='__main__')
	finally:
		sys.modules['sakuya.wizard.__main__'] = loaded_module

	assert [True] == run_calls
