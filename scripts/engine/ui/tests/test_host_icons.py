"""Ícones locais no cadastro canônico. Dados de hosts sempre isolados em tmp."""
import hashlib
import json
import struct

import pytest
import yaml


def _create(client, name='icon-host', **fields):
    rev = client.get('/api/hosts').json()['rev']
    return client.post('/api/hosts', json={
        'id': name, 'hostname': name, 'mgmt_ip': '192.0.2.50', 'group': 'linux-servers', **fields,
    }, headers={'If-Match': rev})


def test_local_icon_catalog_and_assets(client):
    import deps
    response = client.get('/api/meta/icons')
    assert response.status_code == 200
    icons = response.json()['icons']
    assert len(icons) == 10
    assert len({icon['id'] for icon in icons}) == len(icons)
    source = json.loads((deps.STATIC_DIR / 'icons/network/catalog.json').read_text())
    for icon, original in zip(icons, source):
        assert icon['id'] == original['id']
        assert icon['name'] == original['name']
        assert icon['url'] == '/icons/network/thumbnails/' + original['file']
        image = client.get(icon['url'])
        assert image.status_code == 200
        assert image.headers['content-type'] == 'image/png'
        assert image.content[:8] == b'\x89PNG\r\n\x1a\n'
        width, height = struct.unpack('>II', image.content[16:24])
        assert width <= 128 and height <= 128
        original_bytes = (deps.STATIC_DIR / 'icons/network' / original['file']).read_bytes()
        assert hashlib.sha256(original_bytes).hexdigest() == original['sha256']
        assert len(image.content) < len(original_bytes)


@pytest.mark.parametrize('icon', ['router', 'switch', 'linux-server', 'windows-server', 'access-point',
                                 'olt', 'cloud', 'pc', 'proxmox', 'vmware'])
def test_create_icon_persists_in_inventory_and_maps(client, env, icon):
    response = _create(client, icon=icon)
    assert response.status_code == 201, response.text
    assert response.json()['explicit']['icon'] == icon
    assert response.json()['effective']['icon'] == icon
    stored = yaml.safe_load((env / 'network/hosts.yaml').read_text())
    assert stored['hosts']['icon-host']['icon'] == icon
    assert client.get('/api/maps').json()['hosts']['icon-host']['icon'] == icon
    assert not (env / 'network/maps.yaml').exists()


def test_optional_default_and_reset_icon(client, env):
    assert _create(client).status_code == 201
    host = client.get('/api/hosts/icon-host').json()
    assert 'icon' not in host['explicit']
    assert client.get('/api/maps').json()['hosts']['icon-host']['icon'] == ''
    response = client.patch('/api/hosts/icon-host', json={'icon': 'router'}, headers={'If-Match': host['rev']})
    assert response.status_code == 200
    response = client.patch('/api/hosts/icon-host', json={'icon': None}, headers={'If-Match': response.json()['rev']})
    assert response.status_code == 200
    assert 'icon' not in response.json()['explicit']
    assert 'icon' not in yaml.safe_load((env / 'network/hosts.yaml').read_text())['hosts']['icon-host']


@pytest.mark.parametrize('icon', ['missing-icon', '../router.png', 'https://example.org/a.png', '', 'router.png', 'Router'])
def test_invalid_icon_does_not_write(client, env, icon):
    before = (env / 'network/hosts.yaml').read_bytes()
    response = _create(client, icon=icon)
    assert response.status_code == 422, response.text
    assert (env / 'network/hosts.yaml').read_bytes() == before


def test_rename_and_other_edits_preserve_icon(client):
    assert _create(client, icon='switch').status_code == 201
    host = client.get('/api/hosts/icon-host').json()
    response = client.post('/api/hosts/icon-host/rename', json={'to': 'renamed-icon'}, headers={'If-Match': host['rev']})
    assert response.status_code == 200
    response = client.patch('/api/hosts/renamed-icon', json={'notes': 'Atualizado'}, headers={'If-Match': response.json()['rev']})
    assert response.status_code == 200
    assert response.json()['effective']['icon'] == 'switch'
    assert client.get('/api/maps').json()['hosts']['renamed-icon']['icon'] == 'switch'


def test_catalog_and_writes_respect_auth_and_read_only(client, monkeypatch):
    import deps
    from app import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(deps, 'auth_required', lambda: True)
    anonymous = TestClient(create_app(), base_url='http://127.0.0.1')
    assert anonymous.get('/api/meta/icons').status_code == 401
    assert client.get('/api/meta/icons').status_code == 200
    monkeypatch.setattr(deps.STATE, 'read_only', True)
    assert _create(client, icon='router').status_code == 403
