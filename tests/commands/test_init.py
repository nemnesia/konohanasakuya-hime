import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from symbolchain.CryptoTypes import Hash256

from sakuya.__main__ import main
from sakuya.commands import init as init_command
from sakuya.internal.NodeFeatures import NodeFeatures
from sakuya.internal.PackageResolver import download_and_extract_package as real_download_and_extract_package
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


async def test_init_accepts_non_interactive_node_options():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			await main([
				'init',
				'--package', f'file://{Path(package_directory) / "resources.zip"}',
				'--role', 'dual',
				'--hostname', 'localhost',
				'--friendly-name', 'my-node',
				'--metadata', '{"animal":"wolf"}',
				'--config', str(config_filepath)
			])

			assert config_filepath.exists()
			assert '[node.localnode]' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert 'host = localhost' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert 'friendlyName = my-node' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert NodeFeatures.API == parse_sakuya_configuration(config_filepath).node.features
			assert {'animal': 'wolf'} == json.loads(
				(Path(output_directory) / 'rest_overrides.json').read_text(encoding='utf8'))['nodeMetadata']


async def test_second_init_is_rejected_without_changing_existing_configuration():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			package_uri = f'file://{Path(package_directory) / "resources.zip"}'
			await main(['init', '--package', package_uri, '--config', str(config_filepath)])
			original_config = config_filepath.read_bytes()

			with pytest.raises(RuntimeError, match='already been initialized'):
				await main(['init', '--package', package_uri, '--config', str(config_filepath)])

			assert original_config == config_filepath.read_bytes()


async def test_interactive_init_prompts_only_for_missing_values(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['localhost', '', '', 'y'])
			prompts = []

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)
			monkeypatch.setattr(init_command, 'prompt', lambda message, **_kwargs: prompts.append(message) or next(answers))

			await init_command.run_main(SimpleNamespace(
				package=None,
				network='sai',
				role='peer',
				hostname=None,
				friendly_name=None,
				metadata=None,
				config=Path(output_directory) / 'config.ini'))

			assert not any('Network:' in message for message in prompts)
			assert any('Hostname:' in message for message in prompts)
			assert 'host = localhost' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')


async def test_interactive_init_succeeds_without_arguments(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['1', '2', 'localhost', '', '', 'y'])

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)
			monkeypatch.setattr(init_command, 'prompt', lambda _message, **_kwargs: next(answers))

			await init_command.run_main(SimpleNamespace(
				package=None,
				network=None,
				role=None,
				hostname=None,
				friendly_name=None,
				metadata=None,
				config=Path(output_directory) / 'config.ini'))

			assert (Path(output_directory) / 'config.ini').exists()
			assert 'friendlyName = localhost' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')


async def test_interactive_init_can_be_cancelled(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['1', '2', 'localhost', '', '', 'n'])

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)
			monkeypatch.setattr(init_command, 'prompt', lambda _message, **_kwargs: next(answers))

			await init_command.run_main(SimpleNamespace(
				package=None,
				network=None,
				role=None,
				hostname=None,
				friendly_name=None,
				metadata=None,
				config=Path(output_directory) / 'config.ini'))

			assert not (Path(output_directory) / 'config.ini').exists()
			assert not (Path(output_directory) / 'overrides.ini').exists()

			await init_command.run_main(SimpleNamespace(
				package=f'file://{package_filepath}',
				network=None,
				role='peer',
				hostname='localhost',
				friendly_name='localhost',
				metadata='',
				config=Path(output_directory) / 'config.ini'))

			assert (Path(output_directory) / 'config.ini').exists()


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

			assert not config_filepath.exists()
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
