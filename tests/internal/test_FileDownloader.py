import tempfile
from pathlib import Path

import pytest
from aiohttp import web

from sakuya.internal.FileDownloader import _matches_hash, _redact_uri, download_file

SHA3_HASH_ABC = (
	'B751850B1A57168A5693CD924B6B096E08F621827444F70D884F5D0240D2712E'
	'10E116E9192AF3C91A7EC57647E3934057340B4CF408D5A56592F8274EEC53F0'
)

# region server fixture


async def server_impl(aiohttp_client):
	class MockFileServer:
		def __init__(self):
			self.urls = []

		async def known_file(self, request):
			return await self._process(request, b'abc')

		async def _process(self, request, response_buffer):
			self.urls.append(str(request.url))
			return web.Response(body=response_buffer, headers={'Content-Type': 'application/octet-stream'})

	# create a mock server
	mock_server = MockFileServer()

	# create an app using the server
	app = web.Application()
	app.router.add_get('/known/file', mock_server.known_file)
	server = await aiohttp_client(app)  # pylint: disable=redefined-outer-name

	server.mock = mock_server
	return server


@pytest.fixture
async def server(aiohttp_client):
	return await server_impl(aiohttp_client)

# endregion


# pylint: disable=invalid-name

# region test utils

def _read_file_contents(filepath):
	with open(filepath, 'rb') as infile:
		return infile.read()


def _write_file_contents(filepath, contents):
	with open(filepath, 'wb') as outfile:
		outfile.write(contents)


def _assert_downloaded_abc_file(output_directory, other_expected_files=None):
	# Assert: single file was downloaded
	downloaded_files = sorted(list(path.name for path in Path(output_directory).iterdir()))
	assert sorted(['foo.zip'] + (other_expected_files or [])) == downloaded_files

	# - it has the correct contents
	assert b'abc' == _read_file_contents(Path(output_directory) / 'foo.zip')

# endregion


# region new file

async def _assert_can_download_new_file(server, extended_descriptor):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		# Act:
		await download_file({'name': 'foo.zip', 'url': f'{server.make_url("")}/known/file', **extended_descriptor}, output_directory)

		# Assert:
		assert [f'{server.make_url("")}/known/file'] == server.mock.urls
		_assert_downloaded_abc_file(output_directory)


async def test_can_download_new_file_without_hash(server):  # pylint: disable=redefined-outer-name
	await _assert_can_download_new_file(server, {})


async def test_can_download_new_file_with_matching_hash(server):  # pylint: disable=redefined-outer-name
	await _assert_can_download_new_file(server, {'hash': SHA3_HASH_ABC})


async def test_can_download_new_file_from_filesystem(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		_write_file_contents(Path(output_directory) / 'source.zip', b'abc')

		# Act:
		await download_file({'name': 'foo.zip', 'url': f'file://{Path(output_directory) / "source.zip"}'}, output_directory)

		# Assert: file was copied
		assert [] == server.mock.urls
		_assert_downloaded_abc_file(output_directory, ['source.zip'])


async def test_cannot_download_new_file_with_wrong_hash(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		# Act + Assert:
		with pytest.raises(RuntimeError):
			await download_file({
				'name': 'foo.zip', 'url': f'{server.make_url("")}/known/file', 'hash': 'A' + SHA3_HASH_ABC[1:]
			}, output_directory)


async def test_cannot_download_new_file_when_url_does_not_exist(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		# Act + Assert:
		with pytest.raises(RuntimeError):
			await download_file({'name': 'foo.zip', 'url': f'{server.make_url("")}/unknown/file'}, output_directory)

# endregion


# region existing file

async def test_cannot_download_overwrite_existing_file_without_hash(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		_write_file_contents(Path(output_directory) / 'foo.zip', b'abc')

		# Act:
		with pytest.raises(RuntimeError):
			await download_file({'name': 'foo.zip', 'url': f'{server.make_url("")}/known/file'}, output_directory)


async def test_can_skip_download_of_existing_file_with_matching_hash(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		_write_file_contents(Path(output_directory) / 'foo.zip', b'abc')

		# Act:
		await download_file({'name': 'foo.zip', 'url': f'{server.make_url("")}/known/file', 'hash': SHA3_HASH_ABC}, output_directory)

		# Assert: HTTP call was skipped
		assert [] == server.mock.urls
		_assert_downloaded_abc_file(output_directory)


async def test_can_download_overwrite_existing_file_with_wrong_hash(server):  # pylint: disable=redefined-outer-name
	# Arrange:
	with tempfile.TemporaryDirectory() as output_directory:
		_write_file_contents(Path(output_directory) / 'foo.zip', b'def')

		# Act:
		await download_file({'name': 'foo.zip', 'url': f'{server.make_url("")}/known/file', 'hash': SHA3_HASH_ABC}, output_directory)

		# Assert: HTTP call was skipped
		assert [f'{server.make_url("")}/known/file'] == server.mock.urls
		_assert_downloaded_abc_file(output_directory)


def test_matches_hash_supports_sha256_and_rejects_unknown_algorithm():
	assert 'relative/path' == _redact_uri('relative/path')
	assert 'https://example.com/path' == _redact_uri('https://user:password@example.com/path?secret=value')
	assert _matches_hash(b'abc', 'sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
	with pytest.raises(RuntimeError, match='unsupported package digest algorithm'):
		_matches_hash(b'abc', 'md5:900150983cd24fb0d6963f7d28e17f72')


async def test_download_fails_when_remote_file_is_unavailable(server):  # pylint: disable=redefined-outer-name
	with tempfile.TemporaryDirectory() as output_directory:
		with pytest.raises(RuntimeError, match='could not download file'):
			await download_file({'name': 'foo.zip', 'url': f'http://user:password@{server.host}:{server.port}/unknown'}, output_directory)

# endregion
