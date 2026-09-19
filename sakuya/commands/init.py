"""Sakuya の初期設定を対話またはコマンドラインから実行する。"""

import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from prompt_toolkit import PromptSession
from zenlog import log

from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.NodeFeatures import NODE_ROLES, features_for_node_role
from sakuya.internal.PackageResolver import NETWORK_NAMES, download_and_extract_package
from sakuya.wizard.ValidatingTextBox import is_hostname, is_ip_address

_INIT_OPTION_NAMES = ('network', 'role', 'hostname', 'friendly_name')
_CLI_LOG_MAX_BYTES = 5 * 1024 * 1024


def _has_extended_arguments(args):
	"""新しい init 用オプションが1つ以上指定されているかを返す。"""

	return any(getattr(args, name, None) is not None for name in _INIT_OPTION_NAMES)


def _has_all_required_arguments(args):
	"""init に必要な値がすべてコマンドラインで指定されているかを返す。"""

	network_supplied = getattr(args, 'network', None) or getattr(args, 'package', None)
	role_supplied = getattr(args, 'role', None)
	hostname_supplied = getattr(args, 'hostname', None)
	friendly_name_supplied = getattr(args, 'friendly_name', None)
	return bool(network_supplied and role_supplied and hostname_supplied and friendly_name_supplied)


def _can_prompt():
	"""標準入出力が対話可能な端末に接続されているかを返す。"""

	return sys.stdin.isatty() and sys.stdout.isatty()


def _interactive_network_names():
	"""対話画面用のネットワーク一覧を返す（testnet は sai と表示する）。"""

	return tuple(dict.fromkeys('sai' if name == 'testnet' else name for name in NETWORK_NAMES))


def _role_descriptions():
	"""サポート対象のノードロールに対応する説明文を返す。"""

	return {
		'light': _('init-wizard-role-light-description'),
		'dual': _('init-wizard-role-dual-description'),
		'peer': _('init-wizard-role-peer-description')
	}


def _is_cli_invocation(args):
	"""指定された引数が CLI の init サブコマンドから渡されたものかを返す。"""

	return 'init' == getattr(args, 'command', None)


class _CliLogHandler(logging.FileHandler):
	"""詳細な init ログをローテーションなしのサイズ制限付きファイルへ書き込む。"""

	def __init__(self, filename):
		"""ログファイルを作成し、所有者以外から読めない権限に設定する。"""

		super().__init__(filename, mode='a', encoding='utf8')
		os.chmod(filename, 0o600)

	def emit(self, record):
		"""ログを追記し、ファイルサイズが上限を超えないようにする。"""

		try:
			message = f'{self.format(record)}{self.terminator}'
			encoded_message = message.encode('utf8')
			if len(encoded_message) >= _CLI_LOG_MAX_BYTES:
				self.stream.seek(0)
				self.stream.truncate(0)
				encoded_message = encoded_message[-_CLI_LOG_MAX_BYTES:]
				message = encoded_message.decode('utf8', errors='ignore')
			elif os.path.getsize(self.baseFilename) + len(encoded_message) > _CLI_LOG_MAX_BYTES:
				self.stream.seek(0)
				self.stream.truncate(0)
			self._write(message)
		except Exception:  # pylint: disable=broad-except
			self.handleError(record)

	def _write(self, message):
		"""整形済みのログメッセージをフラッシュする。"""

		self.stream.write(message)
		self.flush()


def _cli_log_path(args):
	"""CLI 経由の init で使用する詳細ログのパスを返す。"""

	directory = getattr(args, 'directory', None)
	return None if directory is None else Path(directory) / 'cli.log'


@contextmanager
def _init_logging(args):
	"""init の詳細ログを cli.log へ送り、コンソールへの出力を抑制する。"""

	log_filepath = _cli_log_path(args)
	if log_filepath is None:
		yield None
		return

	log_filepath.parent.mkdir(parents=True, exist_ok=True)
	file_handler = _CliLogHandler(log_filepath)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
	previous_stream_level = log.stream.level
	previous_propagate = log.logger.propagate
	log.logger.addHandler(file_handler)
	log.logger.propagate = False
	log.stream.setLevel(logging.CRITICAL + 1)
	try:
		yield log_filepath
	finally:
		log.logger.removeHandler(file_handler)
		file_handler.close()
		log.logger.propagate = previous_propagate
		log.stream.setLevel(previous_stream_level)


async def _prompt(message, **kwargs):
	"""イベントループをネストさせずに、対話入力を1つ読み取る。"""

	return await PromptSession().prompt_async(message, **kwargs)


def _managed_output_paths(config_filepath):
	"""指定された設定パスに対する init 管理対象ファイルの一覧を返す。"""

	return (
		config_filepath,
		config_filepath.parent / 'overrides.ini',
		config_filepath.parent / 'rest_overrides.json')


def _existing_managed_paths(config_filepath):
	"""シンボリックリンクも含め、既に存在する管理対象ファイルを返す。"""

	return tuple(path for path in _managed_output_paths(config_filepath) if path.exists() or path.is_symlink())


def _check_managed_output_state(config_filepath):
	"""初期化済み・不完全・競合・安全でない出力状態を拒否する。"""

	managed_paths = _managed_output_paths(config_filepath)
	existing_paths = _existing_managed_paths(config_filepath)
	# 壊れたリンクは Path.exists() が False になるため、is_symlink() も確認する。
	if any(path.is_symlink() for path in existing_paths):
		raise RuntimeError('init refuses to replace symbolic links')
	if not existing_paths:
		return

	# 管理対象が全て揃っている場合と一部だけ残っている場合を区別する。
	path_list = '\n'.join(f'  {path}' for path in existing_paths)
	if len(existing_paths) == len(managed_paths):
		raise RuntimeError(f'Sakuya has already been initialized.\n\nManaged files:\n{path_list}')

	raise RuntimeError(f'Incomplete or conflicting Sakuya initialization state detected.\n\nManaged files:\n{path_list}')


async def _prompt_choice(label, choices, instruction, descriptions=None):
	"""選択肢から1つ選ぶように利用者へ問い合わせる。"""

	choice_lines = []
	for index, choice in enumerate(choices, 1):
		choice_lines.append(f'  {index}) {choice}')
		if descriptions and choice in descriptions:
			choice_lines.append(f'      {descriptions[choice]}')
	choice_text = '\n'.join(choice_lines)
	while True:
		selection = _('init-wizard-selection-prompt')
		value = (await _prompt(f'{label}\n{instruction}\n\n{choice_text}\n\n{selection}\n> ')).strip()
		try:
			index = int(value)
			if 1 <= index <= len(choices):
				return choices[index - 1]
		except ValueError:
			pass
		print(_('init-wizard-choice-error').format(count=len(choices)))


async def _prompt_hostname():
	"""ホスト名またはIPアドレスを問い合わせ、既存 validator で検証する。"""

	while True:
		step = _('init-wizard-step-host')
		instruction = _('init-wizard-host-instruction')
		examples = _('init-wizard-host-examples')
		prompt = _('init-wizard-host-prompt')
		value = (await _prompt(f'{step}\n{instruction}\n{examples}\n\n{prompt}\n> ')).strip()
		if is_hostname(value) or is_ip_address(value):
			return value
		print(_('init-wizard-host-error'))


async def _prompt_confirmation():
	"""最終確認を問い合わせる。空入力は「はい」として扱う。"""

	value = (await _prompt(_('init-wizard-confirmation'), default='y')).strip().lower()
	return value in ('', 'y', 'yes')


def _print_interactive_intro():
	"""対話型初期設定ウィザードの導入文を表示する。"""

	title = _('init-wizard-title')
	intro = _('init-wizard-intro')
	output_files = _('init-wizard-output-files')
	metadata = _('init-wizard-metadata')
	cancel = _('init-wizard-cancel')
	print(f'\n{title}\n')
	print(intro)
	print(output_files)
	print(metadata)
	print(f'{cancel}\n')


def _validate_options(options):
	"""解決済みの init オプションを既存の validator で検証する。"""

	if options.role not in NODE_ROLES:
		raise ValueError(f'unknown node role: {options.role}')
	if options.hostname is not None and not (is_hostname(options.hostname) or is_ip_address(options.hostname)):
		raise ValueError(f'invalid hostname or IP address: {options.hostname}')


async def _resolve_options(args, interactive):
	"""CLI 引数と対話入力を統合し、共通の init オプションへ解決する。"""

	package = getattr(args, 'package', None)
	network = getattr(args, 'network', None)
	if network is not None and package is not None:
		raise ValueError('--network and --package cannot be used together')

	package = network or package or 'mainnet'
	role = getattr(args, 'role', None)
	hostname = getattr(args, 'hostname', None)
	friendly_name = getattr(args, 'friendly_name', None)

	# 既存ウィザードからの呼び出しは新しい対話オプション導入前の形式なので、
	# 従来どおり package のみを使う動作を維持する。
	if not any(hasattr(args, name) for name in _INIT_OPTION_NAMES):
		return SimpleNamespace(package=package, role=None, hostname=None, friendly_name=None)

	# --package のみを明示した呼び出しは、従来の非対話経路として扱う。
	if not _has_extended_arguments(args) and getattr(args, 'package', None) is not None:
		return SimpleNamespace(package=package, role=None, hostname=None, friendly_name=None)

	if interactive:
		if getattr(args, 'network', None) is None and getattr(args, 'package', None) is None:
			package = await _prompt_choice(
				_('init-wizard-step-network'),
				_interactive_network_names(),
				_('init-wizard-network-instruction'))
		if role is None:
			role = await _prompt_choice(
				_('init-wizard-step-role'),
				NODE_ROLES,
				_('init-wizard-role-instruction'),
				_role_descriptions())
		if hostname is None:
			hostname = await _prompt_hostname()
		if friendly_name is None:
			step = _('init-wizard-step-friendly')
			instruction = _('init-wizard-friendly-instruction')
			default = _('init-wizard-friendly-default').format(hostname=hostname)
			prompt = _('init-wizard-friendly-prompt').format(hostname=hostname)
			friendly_name = (await _prompt(f'{step}\n{instruction}\n{default}\n\n{prompt}\n> ')).strip() or hostname
		role = role or 'peer'
		if hostname is not None:
			friendly_name = friendly_name or hostname
		options = SimpleNamespace(
			package=package,
			role=role,
			hostname=hostname,
			friendly_name=friendly_name)
		_validate_options(options)

		summary_title = _('init-wizard-summary-title')
		summary_network = _('init-wizard-summary-network')
		summary_role = _('init-wizard-summary-role')
		summary_host = _('init-wizard-summary-host')
		summary_friendly = _('init-wizard-summary-friendly')
		summary_metadata = _('init-wizard-summary-metadata')
		print(f'\n{summary_title}\n')
		print(f'  {summary_network}:       {package}')
		print(f'  {summary_role}:          {role}')
		print(f'  {summary_host}:      {hostname}')
		print(f'  {summary_friendly}: {friendly_name}')
		print(f'  {summary_metadata}\n')
		if not await _prompt_confirmation():
			return None
	elif _has_extended_arguments(args) and hostname is None:
		raise ValueError('hostname is required in non-interactive mode')

	role = role or 'peer'
	if hostname is not None:
		friendly_name = friendly_name or hostname
	options = SimpleNamespace(
		package=package,
		role=role,
		hostname=hostname,
		friendly_name=friendly_name)
	_validate_options(options)
	return options


def _write_overrides(staged_overrides, options):
	"""任意のノード設定を既存の overrides.ini 形式で書き込む。"""

	if options.hostname is None:
		staged_overrides.write_text('', encoding='utf8')
		return

	staged_overrides.write_text('\n'.join([
		'[node.localnode]',
		f'host = {options.hostname}',
		f'friendlyName = {options.friendly_name}',
		''
	]), encoding='utf8')


def _write_rest_overrides_template(staged_rest_overrides):
	"""編集可能な REST メタデータの雛形を書き込む。"""

	staged_rest_overrides.write_text(json.dumps({'nodeMetadata': {}}, indent=2) + '\n', encoding='utf8')


def _commit(targets, config_filepath, staged_directory):
	"""init の成果物を公開し、公開途中に失敗した場合はロールバックする。"""

	target_paths = [target for _staged, target in targets]
	if len(set(target_paths)) != len(target_paths):
		raise RuntimeError('init output files must have distinct paths')
	_check_managed_output_state(config_filepath)

	backup_directory = staged_directory / 'backup'
	backup_directory.mkdir()
	backups = []
	try:
		# 通常は未初期化状態だが、公開直前にも再確認して競合を防ぐ。
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


async def _run_main(args):
	"""初期設定の入力、検証、生成、公開を実行する。"""

	is_cli = _is_cli_invocation(args)
	config_filepath = Path(args.config)
	_check_managed_output_state(config_filepath)

	interactive = _can_prompt() and any(hasattr(args, name) for name in _INIT_OPTION_NAMES) and not _has_all_required_arguments(args)
	if interactive:
		_print_interactive_intro()
	try:
		options = await _resolve_options(args, interactive)
	except (KeyboardInterrupt, EOFError):
		# 問い合わせ中の Ctrl-C / EOF はエラーではなく正常なキャンセルとして扱う。
		options = None
	if options is None:
		if is_cli:
			print(_('init-cancelled'))
		return
	if is_cli:
		print(_('init-start'))

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
			_write_rest_overrides_template(staged_rest_overrides)

			# 管理対象3ファイルを全て staging してから、設定ファイルを最後に公開する。
			# これにより設定ファイルだけが先に存在する中途半端な状態を避ける。
			managed_paths = _managed_output_paths(config_filepath)
			targets = [
				(staged_overrides, managed_paths[1]),
				(staged_rest_overrides, managed_paths[2]),
				(staged_config, managed_paths[0])
			]
			_commit(targets, config_filepath, staged_directory)
			return managed_paths
		finally:
			shutil.rmtree(staged_directory, ignore_errors=True)


async def run_main(args):
	"""画面向けの簡潔な出力と、ファイル向けの詳細ログを伴って init を実行する。"""

	is_cli = _is_cli_invocation(args)
	with _init_logging(args) as log_filepath:
		try:
			managed_paths = await _run_main(args)
		except Exception as ex:
			if log_filepath:
				log.error(_('init-failure-detail').format(reason=ex))
			if is_cli:
				print(_('init-failed').format(reason=ex))
				raise SystemExit(1) from None
			raise

		if is_cli and managed_paths:
			for filepath in managed_paths:
				print(_('init-created-file').format(filepath=filepath))
			print(_('init-success'))
			if log_filepath:
				print(_('init-log-file').format(filepath=log_filepath))


def add_arguments(parser):
	"""init サブコマンドのコマンドライン引数を parser に登録する。"""

	package_group = parser.add_mutually_exclusive_group()
	package_group.add_argument('--package', help=_('argument-help-setup-package'))
	package_group.add_argument('--network', choices=NETWORK_NAMES, help='network name')
	parser.add_argument('--role', choices=NODE_ROLES, help='node role')
	parser.add_argument('--hostname', help='node hostname')
	parser.add_argument('--friendly-name', dest='friendly_name', help='friendly node name')
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
