from sakuya.wizard.SakuyaOperation import SakuyaOperation, build_sakuya_command, requires_ca_key_path

# pylint: disable=invalid-name


# region requires_ca_key_path

def test_requires_ca_key_path_returns_true_for_operations_requiring_ca_key_path():
	assert requires_ca_key_path(SakuyaOperation.SETUP)
	assert not requires_ca_key_path(SakuyaOperation.UPGRADE)
	assert not requires_ca_key_path(SakuyaOperation.RESET_DATA)
	assert requires_ca_key_path(SakuyaOperation.RENEW_CERTIFICATES)
	assert not requires_ca_key_path(SakuyaOperation.RENEW_VOTING_KEYS)

# endregion


# region build_sakuya_command

def _assert_can_build_sakuya_command_setup(has_custom_rest_overrides):
	# Act:
	args = build_sakuya_command(SakuyaOperation.SETUP, 'symbol', 'sakuya', 'cert/ca.key.pem', 'sai', has_custom_rest_overrides)

	# Assert:
	assert [
		'--directory', 'symbol',
		'setup',
		'--config', 'sakuya/config.ini',
		'--ca-key-path', 'cert/ca.key.pem',
		'--overrides', 'sakuya/overrides.ini',
		'--rest-overrides', 'sakuya/rest_overrides.json'
	] == args


def test_can_build_sakuya_command_setup():
	_assert_can_build_sakuya_command_setup(False)


def test_can_build_sakuya_command_setup_with_custom_rest_overrides():
	_assert_can_build_sakuya_command_setup(True)


def test_can_build_sakuya_command_upgrade():
	# Act:
	args = build_sakuya_command(SakuyaOperation.UPGRADE, 'symbol', 'sakuya', 'cert/ca.key.pem', 'sai')

	# Assert:
	assert [
		'--directory', 'symbol',
		'upgrade',
		'--config', 'sakuya/config.ini',
		'--overrides', 'sakuya/overrides.ini'
	] == args


def test_can_build_sakuya_command_reset_data():
	# Act:
	args = build_sakuya_command(SakuyaOperation.RESET_DATA, 'symbol', 'sakuya', 'cert/ca.key.pem', 'sai')

	# Assert:
	assert [
		'--directory', 'symbol',
		'reset-data',
		'--config', 'sakuya/config.ini',
	] == args


def test_can_build_sakuya_command_renew_certificates():
	# Act:
	args = build_sakuya_command(SakuyaOperation.RENEW_CERTIFICATES, 'symbol', 'sakuya', 'cert/ca.key.pem', 'sai')

	# Assert:
	assert [
		'--directory', 'symbol',
		'renew-certificates',
		'--config', 'sakuya/config.ini',
		'--ca-key-path', 'cert/ca.key.pem'
	] == args


def test_can_build_sakuya_command_renew_voting_keys():
	# Act:
	args = build_sakuya_command(SakuyaOperation.RENEW_VOTING_KEYS, 'symbol', 'sakuya', 'cert/ca.key.pem', 'sai')

	# Assert:
	assert [
		'--directory', 'symbol',
		'renew-voting-keys',
		'--config', 'sakuya/config.ini',
	] == args

# endregion
