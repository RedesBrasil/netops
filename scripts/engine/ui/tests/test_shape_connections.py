"""Formas sem IP continuam sendo objetos de mapa, não hosts do inventário."""
import copy

import pytest
import yaml


def _snapshot(client):
    r = client.get('/api/maps')
    assert r.status_code == 200, r.text
    return r.json()


def _save(client, m, s=None):
    s = s or _snapshot(client)
    m = copy.deepcopy(m)
    m.pop('host_ids', None)
    return client.put('/api/maps/' + m['id'], json={'map': m, 'hosts_rev': s['hosts_rev'], 'topology_rev': s['topology']['rev']}, headers={'If-Match': s['rev']})


def _map(client):
    m = _snapshot(client)['maps'][0]
    m['objects'] = [
        {'id': 'cloud', 'type': 'shape', 'position': {'x': 200, 'y': 250}, 'label': 'Internet', 'icon': 'cloud'},
        {'id': 'switch', 'type': 'shape', 'position': {'x': 600, 'y': 250}, 'label': 'Switch sem gerência', 'icon': 'switch'},
    ]
    return m


@pytest.mark.parametrize('source,target', [('host:rt-core-01', 'object:cloud'),
                                         ('object:cloud', 'host:rt-core-01'),
                                         ('object:cloud', 'object:switch')])
def test_shape_links_roundtrip_without_inventory_mutation(client, env, source, target):
    files = {name: (env / 'network' / name).read_bytes() for name in ('hosts.yaml', 'topology.yaml')}
    m = _map(client)
    for i in range(3):
        m['visual_links'].append({'id': 'visual-' + str(i), 'source': source, 'target': target, 'label': 'Ligação visual',
                                  'anchors': {'source': {'side': 'right', 'ratio': .5}, 'target': {'side': 'left', 'ratio': .5}},
                                  'route': {'axis': 'x', 'tracks': [440, 460, 510]}})
    r = _save(client, m)
    assert r.status_code == 200, r.text
    stored = next(m for m in r.json()['maps'] if m['id'] == 'all')
    assert len(stored['visual_links']) == 3
    assert stored['visual_links'][0]['route']['tracks'] == [440, 460, 510]
    assert stored['objects'][0]['icon'] == 'cloud'
    assert stored['objects'][1]['icon'] == 'switch'
    assert (env / 'network/hosts.yaml').read_bytes() == files['hosts.yaml']
    # Primeiro salvamento pode fixar IDs de enlaces legados, mas não cria enlaces.
    before = yaml.safe_load(files['topology.yaml'])['links']
    after = yaml.safe_load((env / 'network/topology.yaml').read_text())['links']
    assert len(after) == len(before)
    assert len(_snapshot(client)['hosts']) == 4
    assert _snapshot(client)['maps'][0]['visual_links'] == stored['visual_links']


def test_old_shape_without_icon_and_clear_icon(client, env):
    m = _map(client); m['objects'][1].pop('icon')
    assert _save(client, m).status_code == 200
    s = _snapshot(client); m = s['maps'][0]; m['objects'][0].pop('icon')
    assert _save(client, m, s).status_code == 200
    stored = yaml.safe_load((env / 'network/maps.yaml').read_text())['maps'][0]
    assert all('icon' not in o for o in stored['objects'])


@pytest.mark.parametrize('icon', ['../cloud.png', 'https://example.test/cloud.png', 'unknown-icon', ''])
def test_shape_icon_invalid_is_rejected(client, env, icon):
    m = _map(client); m['objects'][0]['icon'] = icon
    r = _save(client, m)
    assert r.status_code == 422
    assert not (env / 'network/maps.yaml').exists()


@pytest.mark.parametrize('source,target', [('object:cloud', 'object:cloud'),
                                         ('host:rt-core-01', 'object:unknown'),
                                         ('host:rt-core-01', 'host:rt-dist-01')])
def test_invalid_visual_link_does_not_write(client, env, source, target):
    m = _map(client)
    m['objects'].append({'id': 'note', 'type': 'note', 'label': 'Texto apenas', 'position': {'x': 0, 'y': 0}})
    m['visual_links'] = [{'id': 'v', 'source': source, 'target': target}]
    r = _save(client, m)
    assert r.status_code == 422
    assert not (env / 'network/maps.yaml').exists()


def test_alignment_saves_host_and_shape_positions_together(client):
    m = _map(client)
    m['positions'] = {'rt-core-01': {'x': 100, 'y': 100}, 'rt-dist-01': {'x': 322, 'y': 100}}
    m['objects'][0]['position'] = {'x': 544, 'y': 100}
    r = _save(client, m)
    assert r.status_code == 200, r.text
    stored = r.json()['maps'][0]
    assert stored['positions']['rt-core-01'] == {'x': 100, 'y': 100}
    assert stored['objects'][0]['position'] == {'x': 544, 'y': 100}
    assert stored['objects'][0]['icon'] == 'cloud'
    old = _save(client, m, {'rev': '0' * 64, 'hosts_rev': r.json()['hosts_rev'], 'topology': r.json()['topology']})
    assert old.status_code == 409


def test_shape_changes_are_blocked_in_read_only(client, monkeypatch):
    import deps
    m = _map(client)
    monkeypatch.setattr(deps.STATE, 'read_only', True)
    assert _save(client, m).status_code == 403
