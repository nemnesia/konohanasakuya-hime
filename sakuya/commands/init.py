import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from prompt_toolkit.shortcuts import prompt
from zenlog import log

from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NODE_ROLES, features_for_node_role
from sakuya.internal.PackageResolver import NETWORK_NAMES, download_and_extract_package
from sakuya.wizard.ValidatingTextBox import is_hostname, is_json

_INIT_OPTION_NAMES = ('network', 'role', 'hostname', 'friendly_name', 'metadata')


def _has_extended_arguments(args):
	"""Returns whether the parser received any of the new init options."""

	return any(getattr(args, name, None) is not None for name in _INIT_OPTION_NAMES)


def _has_all_required_arguments(args):
	"""Returns whether all required init values were supplied on the CLI."""

	network_supplied = getattr(args, 'network', None) or getattr(args, 'package', None)
	role_supplied = getattr(args, 'role', None)
	hostname_supplied = getattr(args, 'hostname', None)
	friendly_name_supplied = getattr(args, 'friendly_name', None)
	return bool(network_supplied and role_supplied and hostname_supplied and friendly_name_supplied)


def _can_prompt():
	"""Returns whether this process has an interactive terminal."""

	return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_choice(label, choices):
	"""Prompts for one value from a list of choices."""

	choice_text = '\n'.join(f'  {index}) {choice}' for index, choice in enumerate(choices, 1))
	while True:
		value = prompt(f'{label}:\n{choice_text}\n> ').strip()
		try:
			index = int(value)
			if 1 <= index <= len(choices):
				return choices[index - 1]
		except ValueError:
			pass
		print(f'Please choose a number from 1 to {len(choices)}.')


def _prompt_hostname():
	"""Prompts for and validates a hostname."""

	while True:
		value = prompt('Hostname:\n> ').strip()
		if is_hostname(value):
			return value
		print('A valid hostname is required.')


def _prompt_metadata():
	"""Prompts for optional JSON metadata."""

	while True:
		value = prompt('Metadata (optional):\n> ').strip()
		if is_json(value):
			return value
		print('Metadata must be valid JSON.')


def _prompt_confirmation():
	"""Prompts for final confirmation, defaulting to yes."""

	value = prompt('Create this configuration? [Y/n]: ', default='y').strip().lower()
	return value in ('', 'y', 'yes')


def _validate_options(options):
	"""Validates resolved init options using the existing validators."""

	if options.role not in NODE_ROLES:
		raise ValueError(f'unknown node role: {options.role}')
	if options.hostname is not None and not is_hostname(options.hostname):
		raise ValueError(f'invalid hostname: {options.hostname}')
	if options.metadata is not None and not is_json(options.metadata):
		raise ValueError('metadata must be valid JSON')


def _resolve_options(args, interactive):
	"""Resolves CLI and interactive init values into one option set."""

	package = getattr(args, 'package', None)
	network = getattr(args, 'network', None)
	if network is not None and package is not None:
		raise ValueError('--network and --package cannot be used together')

	package = network or package or 'mainnet'
	role = getattr(args, 'role', None)
	hostname = getattr(args, 'hostname', None)
	friendly_name = getattr(args, 'friendly_name', None)
	metadata = getattr(args, 'metadata', None)

	# Calls from the existing wizard predate the interactive init options and
	# must continue to use the old package-only behavior.
	if not any(hasattr(args, name) for name in _INIT_OPTION_NAMES):
		return SimpleNamespace(package=package, role=None, hostname=None, friendly_name=None, metadata=None)

	# An explicit --package invocation is the original non-interactive path.
	if not _has_extended_arguments(args) and getattr(args, 'package', None) is not None:
		return SimpleNamespace(package=package, role=None, hostname=None, friendly_name=None, metadata=None)

	if interactive:
		if getattr(args, 'network', None) is None and getattr(args, 'package', None) is None:
			package = _prompt_choice('Network', NETWORK_NAMES)
		if role is None:
			role = _prompt_choice('Node role', NODE_ROLES)
		if hostname is None:
			hostname = _prompt_hostname()
		if friendly_name is None:
			friendly_name = prompt(f'Friendly name [{hostname}]:\n> ').strip() or hostname
		if metadata is None:
			metadata = _prompt_metadata()
		role = role or 'peer'
		if hostname is not None:
			friendly_name = friendly_name or hostname
		metadata = metadata or ''
		options = SimpleNamespace(
			package=package,
			role=role,
			hostname=hostname,
			friendly_name=friendly_name,
			metadata=metadata)
		_validate_options(options)

		print('\nConfiguration summary\n')
		print(f'  Network:       {package}')
		print(f'  Role:          {role}')
		print(f'  Hostname:      {hostname}')
		print(f'  Friendly name: {friendly_name}')
		print(f"  Metadata:      {metadata or '-'}\n")
		if not _prompt_confirmation():
			return None
	elif _has_extended_arguments(args) and hostname is None:
		raise ValueError('hostname is required in non-interactive mode')

	role = role or 'peer'
	if hostname is not None:
		friendly_name = friendly_name or hostname
	metadata = metadata or ''
	options = SimpleNamespace(
		package=package,
		role=role,
		hostname=hostname,
		friendly_name=friendly_name,
		metadata=metadata)
	_validate_options(options)
	return options


def _write_overrides(staged_overrides, options):
	"""Writes the optional node settings in the existing override format."""

	if options.hostname is None:
		staged_overrides.write_text('', encoding='utf8')
		return

	staged_overrides.write_text('\n'.join([
		'[node.localnode]',
		f'host = {options.hostname}',
		f'friendlyName = {options.friendly_name}',
		''
	]), encoding='utf8')


def _write_rest_overrides(staged_rest_overrides, options):
	"""Writes metadata in the existing REST override format."""

	if not options.metadata:
		staged_rest_overrides.write_text('{}\n', encoding='utf8')
		return

	staged_rest_overrides.write_text(
		json.dumps({'nodeMetadata': json.loads(options.metadata)}) + '\n',
		encoding='utf8')


def _commit(targets, config_filepath, staged_directory):
	"""Publishes all init outputs and rolls them back if publication fails."""

	target_paths = [target for _staged, target in targets]
	if len(set(target_paths)) != len(target_paths):
		raise RuntimeError('init output files must have distinct paths')
	if any(target.is_symlink() for target in target_paths):
		raise RuntimeError('init refuses to replace symbolic links')
	if config_filepath.exists():
		raise RuntimeError(f'Sakuya has already been initialized.\n\nConfiguration:\n  {config_filepath}')

	backup_directory = staged_directory / 'backup'
	backup_directory.mkdir()
	backups = []
	try:
		for _staged, target in targets:
			if target.exists() or target.is_symlink():
				backup = backup_directory / target.name
				shutil.copy2(target, backup)
				backups.append((backup, target))
		for staged, target in targets:
			log.info(_('general-copying-file').format(source_path=staged, destination_path=target))
			os.replace(staged, target)
	except BaseException:
		for _staged, target in targets:
			if target.exists() and not any(existing_target == target for _backup, existing_target in backups):
				target.unlink()
		for backup, target in backups:
			os.replace(backup, target)
		raise


async def run_main(args):
	config_filepath = Path(args.config)
	if config_filepath.is_symlink():
		raise RuntimeError('init refuses to replace symbolic links')
	if config_filepath.exists():
		raise RuntimeError(f'Sakuya has already been initialized.\n\nConfiguration:\n  {config_filepath}')

	interactive = _can_prompt() and any(hasattr(args, name) for name in _INIT_OPTION_NAMES) and not _has_all_required_arguments(args)
	options = _resolve_options(args, interactive)
	if options is None:
		return

	config_filepath.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.TemporaryDirectory() as temp_directory:
		await download_and_extract_package(options.package, Path(temp_directory))

		template_filepath = Path(temp_directory) / 'shoestring.ini'
		staged_directory = Path(tempfile.mkdtemp(dir=config_filepath.parent, prefix='.sakuya-init-'))
		try:
			staged_config = staged_directory / 'config.ini'
			staged_overrides = staged_directory / 'overrides.ini'
			staged_rest_overrides = staged_directory / 'rest_overrides.json'
			shutil.copy(template_filepath, staged_config)
			replacements = [
				('node', 'userId', os.getuid()),
				('node', 'groupId', os.getgid())
			]
			if options.role:
				replacements.extend([
					('node', 'features', features_for_node_role(options.role).to_formatted_string()),
					('node', 'lightApi', 'true' if 'light' == options.role else 'false')
				])
			ConfigurationManager(staged_directory).patch('config.ini', replacements)
			if options.package not in NETWORK_NAMES:
				with open(staged_config, 'at', encoding='utf8') as outfile:
					outfile.write(f'\n[package]\nsource = {options.package}\n')
			_write_overrides(staged_overrides, options)
			_write_rest_overrides(staged_rest_overrides, options)

			# Publish the config last: it is the initialization-complete marker.
			targets = [
				(staged_overrides, config_filepath.parent / 'overrides.ini'),
				(staged_rest_overrides, config_filepath.parent / 'rest_overrides.json'),
				(staged_config, config_filepath)
			]
			_commit(targets, config_filepath, staged_directory)
		finally:
			shutil.rmtree(staged_directory, ignore_errors=True)


def add_arguments(parser):
	package_group = parser.add_mutually_exclusive_group()
	package_group.add_argument('--package', help=_('argument-help-setup-package'))
	package_group.add_argument('--network', choices=NETWORK_NAMES, help='network name')
	parser.add_argument('--role', choices=NODE_ROLES, help='node role')
	parser.add_argument('--hostname', help='node hostname')
	parser.add_argument('--friendly-name', dest='friendly_name', help='friendly node name')
	parser.add_argument('--metadata', help='node metadata as JSON')
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
