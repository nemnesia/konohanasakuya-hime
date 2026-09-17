from hashlib import sha3_512, sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientSession
from zenlog import log


def _redact_uri(uri):
	"""認証情報やクエリを除いたURIを返す。"""
	parts = urlsplit(uri)
	if not parts.scheme:
		return uri
	return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))


def _calculate_buffer_hash(buffer, algorithm='sha3-512'):
	hasher = sha256() if 'sha256' == algorithm else sha3_512()
	hasher.update(buffer)
	return hasher.hexdigest()


def _calculate_file_hash(filepath, algorithm='sha3-512'):
	with open(filepath, 'rb') as infile:
		return _calculate_buffer_hash(infile.read(), algorithm)


def _matches_hash(buffer_or_filepath, expected_hash, is_file=False):
	algorithm = 'sha3-512'
	value = expected_hash
	if ':' not in expected_hash:
		algorithm = 'sha3-512'
	else:
		algorithm, value = expected_hash.split(':', 1)
		algorithm = algorithm.lower()
	if algorithm not in ('sha256', 'sha3-512') or not value:
		raise RuntimeError(f'unsupported package digest algorithm: {algorithm}')

	actual = _calculate_file_hash(buffer_or_filepath, algorithm) if is_file else _calculate_buffer_hash(buffer_or_filepath, algorithm)
	return actual.lower() == value.lower()


async def _get_file(file_uri):
	async with ClientSession() as session:
		async with session.get(file_uri) as response:
			response_buffer = await response.read()
			if 200 != response.status:
				raise RuntimeError(f'could not download file from "{_redact_uri(file_uri)}"')

			return response_buffer


async def download_file(descriptor, output_directory):
	"""Downloads a file specified by a download descriptor."""

	descriptor_name = descriptor['name']
	output_path = Path(output_directory) / descriptor_name

	if output_path.is_file():
		if 'hash' not in descriptor:
			raise RuntimeError(f'{output_path} exists, remove manually and retry')

		if _matches_hash(output_path, descriptor['hash'], True):
			log.info(_('file-downloader-already-downloaded').format(name=descriptor_name))
			return

		log.info(_('file-downloader-exists-with-invalid-hash'))
		output_path.unlink()

	url = descriptor['url']
	if url.startswith('file://'):
		with open(url[6:], 'rb') as infile:
			file_buffer = infile.read()
	else:
		file_buffer = await _get_file(url)

	if 'hash' in descriptor and not _matches_hash(file_buffer, descriptor['hash']):
		raise RuntimeError(_('file-downloader-downloaded-with-invalid-hash').format(name=descriptor_name))

	with open(output_path, 'wb') as outfile:
		outfile.write(file_buffer)
