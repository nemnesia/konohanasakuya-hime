import configparser
import shutil
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZipFile

from aiohttp import ClientSession

from .FileDownloader import download_file

SYMBOL_GITHUB_URI = 'https://api.github.com/repos/symbol/symbol/releases'


async def _get_releases(releases_uri):
	async with ClientSession() as session:
		async with session.get(releases_uri) as response:
			response_json = await response.json()
			return response_json


def _find_asset(releases, asset_prefix):
	for release in releases:
		tag_name = release['tag_name']
		if not tag_name.startswith('client/catapult'):
			continue

		if not release.get('assets'):
			continue

		for asset in release['assets']:
			if asset['name'].startswith(asset_prefix):
				return {
					'tag': tag_name,
					'asset': asset
				}

	raise RuntimeError(f'couldn\'t find asset {asset_prefix}')


def _resolve_testnet_name(name):
	# testnet／saiはShoestring互換の固定ブランチZIPを使う。配布元に
	# パッケージdigestのAPIがないため、digest欠落だけでは失敗させない。
	if name in ('https://github.com/symbol/networks/tree/sai', 'sai', 'testnet'):
		return 'https://github.com/symbol/networks/archive/refs/heads/sai.zip'

	return name


def _validate_package_source(source):
	parsed = urlparse(source)
	if parsed.scheme not in ('file', 'http', 'https') or not parsed.netloc and 'file' != parsed.scheme:
		raise RuntimeError('package source must be a file:// or HTTP(S) URI')
	return source


async def resolve_package(package_identifier, asset_prefix='configuration-mainnet', releases_uri=SYMBOL_GITHUB_URI):
	"""Resolves a package identifier into an object specifying download instructions."""

	if 'mainnet' == package_identifier:
		releases = await _get_releases(releases_uri)
		asset_descriptor = _find_asset(releases, asset_prefix)
		download_descriptor = {
			'name': 'configuration-package.zip',
			'url': asset_descriptor['asset']['browser_download_url']
		}

		digest = asset_descriptor['asset'].get('digest')
		if not digest or ':' not in digest:
			raise RuntimeError('official package asset does not provide a usable digest')
		download_descriptor['hash'] = digest

		return download_descriptor

	url = _resolve_testnet_name(package_identifier)
	_validate_package_source(url)
	return {
		'name': 'configuration-package.zip',
		'url': url
	}


def resolve_package_identifier(config_filepath, network_name):
	"""Resolves the package source saved in the node configuration."""

	if 'mainnet' == network_name:
		return 'mainnet'
	if 'testnet' == network_name:
		return 'testnet'

	parser = configparser.ConfigParser()
	parser.read(config_filepath, encoding='utf8')
	if parser.has_option('package', 'source') and parser['package']['source']:
		return parser['package']['source']

	raise RuntimeError(f'package source is required for network {network_name}')


def _move_to_parent(destination_directory):
	# github generated zips have additional subdirectory on top-level
	# if it's zipfile like that, just move all the files up

	seed_directory = destination_directory / 'seed'
	if seed_directory.exists():
		return

	# find dir that contains extracted package
	for subdir in destination_directory.glob('*'):
		if not subdir.is_dir():
			continue

		seed_directory = subdir / 'seed'
		if not seed_directory.is_dir():
			continue

		for file in subdir.glob('*'):
			shutil.move(str(file), str(destination_directory))

		subdir.rmdir()

		break
	else:
		raise RuntimeError('could not find package candidate directory')


async def download_and_extract_package(package_identifier, destination_directory):
	"""Downloads and extracts configuration package."""

	download_descriptor = await resolve_package(package_identifier)
	await download_file(download_descriptor, destination_directory)

	# extract all to temp directory
	with ZipFile(destination_directory / 'configuration-package.zip') as package:
		destination = Path(destination_directory).absolute()
		for member in package.infolist():
			member_path = (destination / member.filename).resolve()
			if destination != member_path and destination not in member_path.parents:
				raise RuntimeError(f'package contains an unsafe path: {member.filename}')
		package.extractall(destination_directory)

	_move_to_parent(destination_directory)
