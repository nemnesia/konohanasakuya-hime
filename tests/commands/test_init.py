import json
import os
import stat
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
				'--directory', temp_directory,
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


async def test_prompt_uses_async_prompt_session(monkeypatch):
	calls = []

	async def prompt_async(_session, message, **kwargs):
		calls.append((message, kwargs))
		return 'answer'

	monkeypatch.setattr(init_command.PromptSession, 'prompt_async', prompt_async)

	assert 'answer' == await init_command._prompt('Prompt: ', default='y')
	assert [('Prompt: ', {'default': 'y'})] == calls


async def test_init_accepts_non_interactive_node_options():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			await main([
				'--directory', output_directory,
				'init',
				'--package', f'file://{Path(package_directory) / "resources.zip"}',
				'--role', 'dual',
				'--hostname', 'localhost',
				'--friendly-name', 'my-node',
				'--config', str(config_filepath)
			])

			assert config_filepath.exists()
			assert '[node.localnode]' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert 'host = localhost' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert 'friendlyName = my-node' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert NodeFeatures.API == parse_sakuya_configuration(config_filepath).node.features
			assert {} == json.loads(
				(Path(output_directory) / 'rest_overrides.json').read_text(encoding='utf8'))['nodeMetadata']


async def test_cli_init_shows_user_summary_and_writes_detailed_log(capsys):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			await main([
				'--directory', output_directory,
				'init',
				'--package', f'file://{Path(package_directory) / "resources.zip"}',
				'--config', str(config_filepath)
			])

			captured = capsys.readouterr()
			assert 'Sakuya initialization completed.' in captured.out
			assert 'copying FILE' not in captured.out
			assert 'copying FILE' not in captured.err
			log_filepath = Path(output_directory) / 'cli.log'
			assert stat.S_IMODE(log_filepath.stat().st_mode) == 0o600
			assert 'copying FILE' in log_filepath.read_text(encoding='utf8')


@pytest.mark.parametrize('host', ['203.0.113.10', '2001:db8::10'])
async def test_init_accepts_ip_addresses_non_interactively(host):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			await main([
				'--directory', output_directory,
				'init',
				'--package', f'file://{Path(package_directory) / "resources.zip"}',
				'--role', 'peer',
				'--hostname', host,
				'--friendly-name', 'my-node',
				'--config', str(config_filepath)
			])

			overrides = (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert f'host = {host}' in overrides


async def test_init_rejects_invalid_host_non_interactively():
	with tempfile.TemporaryDirectory() as output_directory:
		with pytest.raises(ValueError, match='invalid hostname or IP address'):
			await init_command.run_main(SimpleNamespace(
				package='mainnet',
				role='peer',
				hostname='not a host',
				friendly_name='my-node',
				config=Path(output_directory) / 'config.ini'))


async def test_second_init_is_rejected_without_changing_existing_configuration(capsys):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			package_uri = f'file://{Path(package_directory) / "resources.zip"}'
			await main(['--directory', output_directory, 'init', '--package', package_uri, '--config', str(config_filepath)])
			original_config = config_filepath.read_bytes()

			with pytest.raises(SystemExit) as error:
				await main(['--directory', output_directory, 'init', '--package', package_uri, '--config', str(config_filepath)])

			assert 1 == error.value.code
			assert 'Sakuya has already been initialized.' in capsys.readouterr().out

			assert original_config == config_filepath.read_bytes()


async def test_interactive_init_prompts_only_for_missing_values(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['2001:db8::10', '', 'y'])
			prompts = []

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)

			async def prompt(message, **_kwargs):
				prompts.append(message)
				return next(answers)

			monkeypatch.setattr(init_command, '_prompt', prompt)

			await init_command.run_main(SimpleNamespace(
				package=None,
				network='sai',
				role='peer',
				hostname=None,
				friendly_name=None,
				config=Path(output_directory) / 'config.ini'))

			assert not any('Network:' in message for message in prompts)
			assert any('Host (hostname or IP address):' in message for message in prompts)
			assert 'host = 2001:db8::10' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')


async def test_interactive_init_succeeds_without_arguments(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['1', '2', 'localhost', '', 'y'])
			prompts = []

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)

			async def prompt(message, **_kwargs):
				prompts.append(message)
				return next(answers)

			monkeypatch.setattr(init_command, '_prompt', prompt)

			await init_command.run_main(SimpleNamespace(
				package=None,
				network=None,
				role=None,
				hostname=None,
				friendly_name=None,
				config=Path(output_directory) / 'config.ini'))

			assert (Path(output_directory) / 'config.ini').exists()
			assert 'friendlyName = localhost' in (Path(output_directory) / 'overrides.ini').read_text(encoding='utf8')
			assert any('Step 1 of 4: Network' in message for message in prompts)
			network_prompt = next(message for message in prompts if 'Step 1 of 4: Network' in message)
			assert '2) sai' in network_prompt
			assert 'testnet' not in network_prompt
			assert any('Step 2 of 4: Node role' in message for message in prompts)
			role_prompt = next(message for message in prompts if 'Step 2 of 4: Node role' in message)
			assert '1) light' in role_prompt
			assert '2) dual' in role_prompt
			assert '3) peer' in role_prompt
			assert 'Recommended for typical use.' in role_prompt
			assert 'contribute to application development' in role_prompt
			assert any('2001:db8::10' in message for message in prompts)
			assert any('Step 4 of 4: Friendly name' in message for message in prompts)


async def test_interactive_init_can_be_cancelled(monkeypatch):
	with tempfile.TemporaryDirectory() as package_directory:
		package_filepath = prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			answers = iter(['1', '2', 'localhost', '', 'n'])

			async def download_local_package(_package, destination):
				await real_download_and_extract_package(f'file://{package_filepath}', destination)

			monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
			monkeypatch.setattr(init_command, 'download_and_extract_package', download_local_package)

			async def prompt(_message, **_kwargs):
				return next(answers)

			monkeypatch.setattr(init_command, '_prompt', prompt)

			await init_command.run_main(SimpleNamespace(
				package=None,
				network=None,
				role=None,
				hostname=None,
				friendly_name=None,
				config=Path(output_directory) / 'config.ini'))

			assert not (Path(output_directory) / 'config.ini').exists()
			assert not (Path(output_directory) / 'overrides.ini').exists()

			await init_command.run_main(SimpleNamespace(
				package=f'file://{package_filepath}',
				network=None,
				role='peer',
				hostname='localhost',
				friendly_name='localhost',
				config=Path(output_directory) / 'config.ini'))

			assert (Path(output_directory) / 'config.ini').exists()


@pytest.mark.parametrize('cancel_exception', [KeyboardInterrupt, EOFError])
async def test_cli_prompt_cancellation_does_not_show_exception(cancel_exception, monkeypatch, capsys):
	with tempfile.TemporaryDirectory() as output_directory:
		async def prompt(_message, **_kwargs):
			raise cancel_exception()

		monkeypatch.setattr(init_command, '_can_prompt', lambda: True)
		monkeypatch.setattr(init_command, '_prompt', prompt)

		await init_command.run_main(SimpleNamespace(
			command='init',
			directory=output_directory,
			package=None,
			network=None,
			role=None,
			hostname=None,
			friendly_name=None,
			config=Path(output_directory) / 'config.ini'))

		captured = capsys.readouterr()
		assert 'Sakuya initialization cancelled.' in captured.out
		assert cancel_exception.__name__ not in captured.out
		assert not (Path(output_directory) / 'config.ini').exists()
		assert not (Path(output_directory) / 'overrides.ini').exists()
		assert not (Path(output_directory) / 'rest_overrides.json').exists()


async def test_init_rejects_duplicate_output_paths():
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			with pytest.raises(RuntimeError, match='distinct paths'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=Path(output_directory) / 'overrides.ini'))


@pytest.mark.parametrize('existing_names', [
	('config.ini',),
	('overrides.ini',),
	('rest_overrides.json',),
	('config.ini', 'overrides.ini'),
	('config.ini', 'rest_overrides.json'),
	('overrides.ini', 'rest_overrides.json'),
	('config.ini', 'overrides.ini', 'rest_overrides.json')
])
async def test_init_rejects_existing_managed_state_without_changing_files(existing_names):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			output_directory = Path(output_directory)
			config_filepath = output_directory / 'config.ini'
			original_contents = {}
			for filename in existing_names:
				filepath = output_directory / filename
				original_contents[filename] = f'original-{filename}'
				filepath.write_text(original_contents[filename], encoding='utf8')

			expected_error = 'already been initialized' if 3 == len(existing_names) else 'Incomplete or conflicting'
			with pytest.raises(RuntimeError, match=expected_error):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=config_filepath))

			for filename, contents in original_contents.items():
				assert contents == (output_directory / filename).read_text(encoding='utf8')


@pytest.mark.parametrize('symlink_name', ['config.ini', 'overrides.ini', 'rest_overrides.json'])
async def test_init_rejects_symbolic_link_output(symlink_name):
	with tempfile.TemporaryDirectory() as package_directory:
		prepare_testnet_package(package_directory, 'resources.zip')
		with tempfile.TemporaryDirectory() as output_directory:
			config_filepath = Path(output_directory) / 'config.ini'
			symlink_filepath = Path(output_directory) / symlink_name
			symlink_target = Path(output_directory) / f'{symlink_name}.target'
			symlink_target.write_text('original', encoding='utf8')
			symlink_filepath.symlink_to(symlink_target)

			with pytest.raises(RuntimeError, match='symbolic links'):
				await init_command.run_main(SimpleNamespace(
					package=f'file://{Path(package_directory) / "resources.zip"}',
					config=config_filepath))

			assert symlink_filepath.is_symlink()
			assert 'original' == symlink_target.read_text(encoding='utf8')


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
