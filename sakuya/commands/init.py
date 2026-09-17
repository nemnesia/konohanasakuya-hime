import json
import os
import shutil
import tempfile
from pathlib import Path

from zenlog import log

from sakuya.internal.ConfigurationManager import ConfigurationManager
from sakuya.internal.PackageResolver import download_and_extract_package


async def run_main(args):
	with tempfile.TemporaryDirectory() as temp_directory:
		await download_and_extract_package(args.package, Path(temp_directory))

		template_filepath = Path(temp_directory) / 'shoestring.ini'
		config_filepath = Path(args.config)
		config_filepath.parent.mkdir(parents=True, exist_ok=True)
		staged_directory = Path(tempfile.mkdtemp(dir=config_filepath.parent, prefix='.sakuya-init-'))
		staged_config = staged_directory / 'config.ini'
		staged_overrides = staged_directory / 'overrides.ini'
		staged_rest_overrides = staged_directory / 'rest_overrides.json'
		shutil.copy(template_filepath, staged_config)
		ConfigurationManager(staged_directory).patch('config.ini', [
			('node', 'userId', os.getuid()),
			('node', 'groupId', os.getgid())
		])
		if args.package not in ('mainnet', 'testnet', 'sai'):
			with open(staged_config, 'at', encoding='utf8') as outfile:
				outfile.write(f'\n[package]\nsource = {args.package}\n')
		staged_overrides.write_text('', encoding='utf8')
		staged_rest_overrides.write_text(json.dumps({}) + '\n', encoding='utf8')

		targets = [
			(staged_config, config_filepath),
			(staged_overrides, config_filepath.parent / 'overrides.ini'),
			(staged_rest_overrides, config_filepath.parent / 'rest_overrides.json')
		]
		target_paths = [target for _staged, target in targets]
		if len(set(target_paths)) != len(target_paths):
			raise RuntimeError('init output files must have distinct paths')
		if any(target.is_symlink() for target in target_paths):
			raise RuntimeError('init refuses to replace symbolic links')
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
		finally:
			shutil.rmtree(staged_directory, ignore_errors=True)


def add_arguments(parser):
	parser.add_argument('--package', help=_('argument-help-setup-package'), default='mainnet')
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.set_defaults(func=run_main)
