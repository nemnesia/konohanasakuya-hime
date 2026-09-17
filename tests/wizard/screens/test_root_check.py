from types import SimpleNamespace

from sakuya.wizard.screens import root_check
from sakuya.wizard.screens.root_check import create


def test_is_running_as_root_configures_quit_navigation(monkeypatch):
	previous = object()
	next_button = SimpleNamespace(text='next', handler=None)
	screens = SimpleNamespace(navbar=SimpleNamespace(prev=previous, next=next_button))
	monkeypatch.setattr(root_check.os, 'getuid', lambda: 0)

	assert root_check.is_running_as_root(screens)
	assert screens.navbar.prev is None
	assert 'QUIT' == screens.navbar.next.text
	assert callable(screens.navbar.next.handler)


def test_is_running_as_root_returns_false_for_regular_user(monkeypatch):
	monkeypatch.setattr(root_check.os, 'getuid', lambda: 1000)
	assert not root_check.is_running_as_root(SimpleNamespace(navbar=SimpleNamespace()))
