import shutil
import tempfile
from pathlib import Path

from sakuya.wizard.SakuyaOperation import SakuyaOperation, build_sakuya_command
from sakuya.wizard.setup_file_generator import prepare_overrides_file, prepare_sakuya_files, try_prepare_rest_overrides_file


async def dispatch_sakuya_command(screens, executor):
	"""Dispatches a Sakuya command specified by screens to an async executor."""

	obligatory_settings = screens.get('obligatory')
	destination_directory = Path(obligatory_settings.destination_directory)
	sakuya_directory = destination_directory

	operation = screens.get('welcome').operation
	package = screens.get('network-type').current_value if SakuyaOperation.SETUP == operation else None

	if SakuyaOperation.SETUP == operation:
		with tempfile.TemporaryDirectory() as temp_directory:
			# init は managed output のいずれかが存在すると再実行を拒否するため、
			# Wizard 固有の overrides は init 完了後に上書きする。
			await prepare_sakuya_files(screens, Path(temp_directory))
			has_custom_rest_overrides = try_prepare_rest_overrides_file(screens, Path(temp_directory) / 'rest_overrides.json')
			prepare_overrides_file(screens, Path(temp_directory) / 'overrides.ini')

			sakuya_args = build_sakuya_command(
				operation,
				destination_directory,
				temp_directory,
				obligatory_settings.ca_pem_path,
				package,
				has_custom_rest_overrides)
			await executor(sakuya_args)

			for filename in ('config.ini', 'overrides.ini', 'rest_overrides.json'):
				source_path = Path(temp_directory) / filename
				if source_path.exists():
					shutil.copy(source_path, sakuya_directory)
	else:
		sakuya_args = build_sakuya_command(
			operation,
			destination_directory,
			sakuya_directory,
			obligatory_settings.ca_pem_path,
			package)
		await executor(sakuya_args)
