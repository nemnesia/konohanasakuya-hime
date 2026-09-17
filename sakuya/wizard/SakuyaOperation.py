from enum import Enum
from pathlib import Path


class SakuyaOperation(Enum):
	"""Supported Sakuya operations."""

	SETUP = 1
	UPGRADE = 2
	RESET_DATA = 3
	RENEW_CERTIFICATES = 4
	RENEW_VOTING_KEYS = 5


def requires_ca_key_path(operation):
	"""Determines if CA key is required for completing operation."""

	return operation in (SakuyaOperation.SETUP, SakuyaOperation.RENEW_CERTIFICATES)


def build_sakuya_command(
	operation,
	destination_directory,
	sakuya_directory,
	ca_pem_path,
	package,
	has_custom_rest_overrides=False
):  # pylint: disable=too-many-arguments,too-many-positional-arguments
	"""Builds Sakuya command arguments."""

	command_name = None
	if SakuyaOperation.SETUP == operation:
		command_name = 'setup'
	elif SakuyaOperation.UPGRADE == operation:
		command_name = 'upgrade'
	elif SakuyaOperation.RESET_DATA == operation:
		command_name = 'reset-data'
	elif SakuyaOperation.RENEW_CERTIFICATES == operation:
		command_name = 'renew-certificates'
	elif SakuyaOperation.RENEW_VOTING_KEYS == operation:
		command_name = 'renew-voting-keys'

	sakuya_args = [
		'--directory', str(destination_directory),
		command_name,
		'--config', str(Path(sakuya_directory) / 'config.ini')
	]

	if requires_ca_key_path(operation):
		sakuya_args.extend(['--ca-key-path', str(ca_pem_path)])

	if operation in (SakuyaOperation.SETUP, SakuyaOperation.UPGRADE):
		sakuya_args.extend(['--overrides', str(Path(sakuya_directory) / 'overrides.ini')])

	if SakuyaOperation.SETUP == operation:
		# initが常に生成する既定のREST設定もsetupへ明示的に渡す。
		sakuya_args.extend(['--rest-overrides', str(Path(sakuya_directory) / 'rest_overrides.json')])

	return sakuya_args
