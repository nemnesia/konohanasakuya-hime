import os
import shutil
import tempfile
from pathlib import Path


def replace_paths(staged_root, output_root, relative_paths):
	"""指定された生成物だけをバックアップ付きで差し替える。"""
	staged_root = Path(staged_root)
	output_root = Path(output_root)
	backup_root = Path(tempfile.mkdtemp(dir=output_root.parent, prefix='.sakuya-backup-'))
	backups = []
	installed = []

	try:
		for relative_path in relative_paths:
			target = output_root / relative_path
			if not target.exists() and not target.is_symlink():
				continue

			backup = backup_root / relative_path
			backup.parent.mkdir(parents=True, exist_ok=True)
			os.replace(target, backup)
			backups.append((backup, target))

		for relative_path in relative_paths:
			source = staged_root / relative_path
			if not source.exists() and not source.is_symlink():
				continue

			target = output_root / relative_path
			target.parent.mkdir(parents=True, exist_ok=True)
			os.replace(source, target)
			installed.append(target)
	# The replacement is a transaction boundary.  KeyboardInterrupt and
	# SystemExit must restore the previous state before the backup is removed.
	except BaseException:
		for target in reversed(installed):
			if target.is_dir() and not target.is_symlink():
				shutil.rmtree(target)
			elif target.exists() or target.is_symlink():
				target.unlink()

		for backup, target in reversed(backups):
			target.parent.mkdir(parents=True, exist_ok=True)
			os.replace(backup, target)
		raise
	finally:
		shutil.rmtree(backup_root, ignore_errors=True)
