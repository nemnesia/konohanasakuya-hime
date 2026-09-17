from types import SimpleNamespace

from prompt_toolkit.keys import Keys

from sakuya.wizard import keybindings


def test_initialize_registers_navigation_and_exit_bindings():
	bindings = keybindings.initialize(lambda: False)
	assert 4 == len(bindings.bindings)

	exited = []
	event = SimpleNamespace(app=SimpleNamespace(exit=lambda: exited.append(True)))
	bindings.get_bindings_for_keys((Keys.ControlQ,))[-1].handler(event)
	assert [True] == exited
