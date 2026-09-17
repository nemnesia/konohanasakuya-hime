from collections import namedtuple

from sakuya.wizard.SakuyaOperation import SakuyaOperation
from sakuya.wizard.screens.welcome import create

Button = namedtuple('Button', ('text', 'operation'))

# pylint: disable=invalid-name


def test_can_create_screen():
	# Act:
	screen = create(None)

	# Assert: check id
	assert 'welcome' == screen.screen_id


def test_can_select_button():
	# Arrange:
	screen = create(None)

	# Act:
	screen.accessor.select(Button('upgrade', SakuyaOperation.UPGRADE))

	# Assert:
	assert SakuyaOperation.UPGRADE == screen.accessor.operation
	assert 'upgrade' == screen.accessor.operation_label


def test_can_generate_diagnostic_accessor_representation():
	# Arrange:
	screen = create(None)
	screen.accessor.select(Button('upgrade', SakuyaOperation.UPGRADE))

	# Act + Assert:
	assert '(command=\'upgrade\')' == repr(screen.accessor)
	assert [
		('command', 'upgrade')
	] == screen.accessor.tokens
