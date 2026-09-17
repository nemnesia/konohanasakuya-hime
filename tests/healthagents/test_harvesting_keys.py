from pathlib import Path
from types import SimpleNamespace

import pytest

from sakuya.healthagents import harvesting_keys
from sakuya.internal.NodeFeatures import NodeFeatures


def _context(network_name='testnet'):
	return SimpleNamespace(
		config=SimpleNamespace(network=SimpleNamespace(name=network_name)),
		directories=SimpleNamespace(resources=Path('resources'), keys=Path('keys'), certificates=Path('certificates')),
		failed=False)


def test_should_run_only_for_harvester_role():
	assert harvesting_keys.should_run(SimpleNamespace(features=NodeFeatures.HARVESTER))
	assert not harvesting_keys.should_run(SimpleNamespace(features=NodeFeatures.PEER))


@pytest.mark.asyncio
async def test_validate_skips_custom_network():
	context = _context('private')
	await harvesting_keys.validate(context)
	assert not context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_no_api_endpoint(monkeypatch):
	context = _context()
	monkeypatch.setattr(harvesting_keys, 'load_api_endpoints', lambda _resources: [])
	await harvesting_keys.validate(context)
	assert context.failed


@pytest.mark.asyncio
@pytest.mark.parametrize('harvesting_response', [
	{'canHarvest': False},
	{'isHarvesting': False},
])
async def test_validate_fails_when_node_cannot_harvest(monkeypatch, harvesting_response):
	context = _context()
	monkeypatch.setattr(harvesting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(harvesting_keys, 'read_private_key_from_private_key_pem_file', lambda _path: 'remote')
	monkeypatch.setattr(harvesting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def account_links(self, _account):
			return SimpleNamespace(linked_public_key='remote', vrf_public_key='vrf')

		async def get(self, _path, _group):
			return harvesting_response

	monkeypatch.setattr(harvesting_keys, 'KeyPair', lambda key: SimpleNamespace(public_key='remote' if key == 'remote' else 'vrf'))
	monkeypatch.setattr(harvesting_keys, 'SymbolConnector', Connector)
	await harvesting_keys.validate(context)
	assert context.failed


@pytest.mark.asyncio
async def test_validate_fails_when_remote_or_vrf_link_does_not_match(monkeypatch):
	context = _context()
	monkeypatch.setattr(harvesting_keys, 'load_api_endpoints', lambda _resources: ['http://node'])
	monkeypatch.setattr(
		harvesting_keys,
		'read_private_key_from_private_key_pem_file',
		lambda path: 'remote' if str(path).endswith('remote.pem') else 'vrf')
	monkeypatch.setattr(harvesting_keys, 'read_public_key_from_public_key_pem_file', lambda _path: 'account')
	monkeypatch.setattr(harvesting_keys, 'KeyPair', lambda key: SimpleNamespace(public_key=key))

	class Connector:
		def __init__(self, _endpoint):
			pass

		async def account_links(self, _account):
			return SimpleNamespace(linked_public_key='other', vrf_public_key='vrf')

		async def get(self, _path, _group):
			return {'canHarvest': True}

	monkeypatch.setattr(harvesting_keys, 'SymbolConnector', Connector)
	await harvesting_keys.validate(context)
	assert context.failed
