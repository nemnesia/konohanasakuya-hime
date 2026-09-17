import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import Hash256

from sakuya.__main__ import main
from sakuya.commands import init as init_command
from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration

from ..test.TestPackager import prepare_testnet_package

# pylint: disable=invalid-name


async def test_can_download_configuration_file_template():
	# Arrange:
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')

		with tempfile.TemporaryDirectory() as temp_directory:
			config_filepath = Path(temp_directory) / 'my.shoestring.ini'

			# Sanity:
			assert not config_filepath.exists()

			# Act:
			await main([
				'init',
				'--package', f'file://{Path(package_directory) / "resources.zip"}',
				'--config', str(config_filepath)
			])

			# Assert:
			assert config_filepath.exists()

			config = parse_sakuya_configuration(config_filepath)
			assert Hash256('49D6E1CE276A85B70EAFE52349AACCA389302E7A9754BCF1221E79494FC665A4') == config.network.generation_hash_seed

			# - user and group ids are updated
			assert os.getuid() == config.node.user_id
		assert os.getgid() == config.node.group_id


async def test_init_rejects_duplicate_output_paths():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			with pytest.raises(RuntimeError, match='distinct paths'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=Path(output_directory) / 'overrides.ini'))


async def test_init_rejects_symbolic_link_output():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			config_filepath.with_name('existing.ini').write_text('original', encoding='utf8')
			config_filepath.symlink_to(config_filepath.with_name('existing.ini'))

			with pytest.raises(RuntimeError, match='symbolic links'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=config_filepath))


@pytest.mark.parametrize('failure', [OSError, KeyboardInterrupt, SystemExit])
async def test_init_restores_existing_files_when_commit_fails(monkeypatch, failure):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			output_directory = Path(output_directory)
			config_filepath = output_directory / 'config.ini'
			config_filepath.write_text('old-config', encoding='utf8')
			(config_filepath.parent / 'overrides.ini').write_text('old-overrides', encoding='utf8')
			(config_filepath.parent / 'rest_overrides.json').write_text('old-rest', encoding='utf8')

			original_replace = init_command.os.replace
			replace_count = 0

			def fail_on_second_replace(source, target):
				nonlocal replace_count
				replace_count += 1
				if 2 == replace_count:
					raise failure('simulated commit failure')
				return original_replace(source, target)

			monkeypatch.setattr(init_command.os, 'replace', fail_on_second_replace)
			with pytest.raises(failure, match='simulated commit failure'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=config_filepath))

			assert 'old-config' == config_filepath.read_text(encoding='utf8')
			assert 'old-overrides' == (output_directory / 'overrides.ini').read_text(encoding='utf8')
			assert 'old-rest' == (output_directory / 'rest_overrides.json').read_text(encoding='utf8')


async def test_init_removes_partially_installed_files_when_commit_fails(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			original_replace = init_command.os.replace
			replace_count = 0

			def fail_on_second_replace(source, target):
				nonlocal replace_count
				replace_count += 1
				if 2 == replace_count:
					raise OSError('simulated commit failure')
				return original_replace(source, target)

			monkeypatch.setattr(init_command.os, 'replace', fail_on_second_replace)
			with pytest.raises(OSError, match='simulated commit failure'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=config_filepath))

			assert not config_filepath.exists()
