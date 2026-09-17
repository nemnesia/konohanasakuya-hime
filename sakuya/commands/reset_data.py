import os
import shutil
import tempfile
from pathlib import Path

from zenlog import log

from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration


def _raise_walk_error(error):
	raise RuntimeError(f'cannot inspect reset target: {error.filename}') from error


def _validate_target(root, name):
	"""リセット対象が管理領域内の実ディレクトリであることを確認する。"""
	managed_root = root / 'sakuya'
	target = managed_root / name
	if managed_root.is_symlink() or not managed_root.is_dir():
		raise RuntimeError(f'managed directory does not exist at path {managed_root}')
	if target.is_symlink() or not target.is_dir():
		raise RuntimeError(f'reset target is not a managed directory: {target}')
	for current_root, directory_names, file_names in os.walk(target, followlinks=False, onerror=_raise_walk_error):
		for child_name in [*directory_names, *file_names]:
			child = Path(current_root) / child_name
			if child.is_symlink():
				raise RuntimeError(f'reset target contains a symbolic link: {child}')
	return target


def _copy_file_if_exists(source, destination):
	if not source.exists():
		return
	if source.is_symlink() or not source.is_file():
		raise RuntimeError(f'cannot preserve unexpected path: {source}')
	destination.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(source, destination)


def _copy_votes_backup(data_directory, backup_directory):
	votes_backup = data_directory / 'votes_backup'
	if not votes_backup.exists():
		return None
	if votes_backup.is_symlink() or not votes_backup.is_dir():
		raise RuntimeError(f'cannot inspect unexpected path: {votes_backup}')

	epochs = []
	for epoch in votes_backup.iterdir():
		if epoch.is_symlink():
			raise RuntimeError(f'cannot preserve unexpected path: {epoch}')
		if not epoch.is_dir():
			continue
		try:
			epochs.append(int(epoch.name))
		except ValueError as exception:
			raise RuntimeError(f'invalid voting backup directory: {epoch}') from exception

	if not epochs:
		return None

	max_epoch = max(epochs)
	shutil.copytree(votes_backup / str(max_epoch), backup_directory / 'votes')
	return max_epoch


async def run_main(args):
	config = parse_sakuya_configuration(args.config)
	root = Path(args.directory).absolute()
	data_directory = _validate_target(root, 'data')
	logs_directory = _validate_target(root, 'logs')
	targets = [data_directory, logs_directory]
	if config.node.full_api:
		targets.append(_validate_target(root, 'dbdata'))

	data_files_to_keep = ['voting_status.dat']
	if not args.purge_harvesters:
		data_files_to_keep.append('harvesters.dat')

	backup_root = Path(tempfile.mkdtemp(dir=root / 'sakuya', prefix='.reset-data-'))
	moved_targets = []
	try:
		preserved_data = backup_root / 'preserved'
		preserved_data.mkdir()
		max_epoch = _copy_votes_backup(data_directory, preserved_data)

		for target in targets:
			backup = backup_root / target.name
			os.replace(target, backup)
			moved_targets.append((backup, target))
			target.mkdir(mode=0o700)

		for filename in data_files_to_keep:
			_copy_file_if_exists(backup_root / 'data' / filename, data_directory / filename)
		if max_epoch is not None:
			(data_directory / 'votes_backup').mkdir()
			shutil.copytree(preserved_data / 'votes', data_directory / 'votes_backup' / str(max_epoch))

		for target in targets:
			log.info(_('reset-data-recreating-directory').format(directory=target))
	except BaseException:
		for _backup, target in reversed(moved_targets):
			if target.exists() or target.is_symlink():
				shutil.rmtree(target)
		for backup, target in reversed(moved_targets):
			os.replace(backup, target)
		raise
	finally:
		shutil.rmtree(backup_root, ignore_errors=True)


def add_arguments(parser):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.add_argument('--purge-harvesters', help=_('argument-help-reset-data-purge-harvesters'), action='store_true')
	parser.set_defaults(func=run_main)
