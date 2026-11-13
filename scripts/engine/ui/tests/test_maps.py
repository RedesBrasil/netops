"""Mapas, inventário compartilhado e persistência com rollback. Dados só em tmp."""
import copy

import pytest
import yaml


def snapshot(client):
    r = client.get('/api/maps')
    assert r.status_code == 200, r.text
    return r.json()


def save(client, m, s=None):
    s = s or snapshot(client)
    value = copy.deepcopy(m)
    value.pop('host_ids', None)
    return client.put('/api/maps/' + value['id'], json={'map': value, 'hosts_rev': s['hosts_rev'], 'topology_rev': s['topology']['rev']}, headers={'If-Match': s['rev']})


def seed_host(client, name, **extra):
    s = snapshot(client)
    body = {'hostname': name, 'mgmt_ip': '192.0.2.10', 'group': 'linux-servers', **extra}
    r = client.post('/api/hosts', json=body, headers={'If-Match': s['hosts_rev']})
    assert r.status_code == 201, r.text
    return r.json()


def test_reads_do_not_create_or_migrate_files(client, env):
    before = (env / 'network/topology.yaml').read_bytes()
    s = snapshot(client)
    assert not (env / 'network/maps.yaml').exists()
    assert before == (env / 'network/topology.yaml').read_bytes()
    general = next(m for m in s['maps'] if m['id'] == 'all')
    assert set(general['host_ids']) == {h['id'] for h in s['hosts']}
    assert all(set(h) == {'id', 'hostname', 'mgmt_ip', 'vendor', 'role', 'site', 'icon'} for h in s['hosts'])
    assert all(type(h['id']) is int for h in s['hosts'])
    assert len(s['topology']['links']) == len({l['id'] for l in s['topology']['links']})


def test_host_both_directions_and_site_inheritance(client):
    listed = seed_host(client, 'from-list', site='Filial')['id']
    s = snapshot(client)
    m = next(m for m in s['maps'] if m.get('site') == 'Filial')
    assert listed in m['host_ids']
    placed = seed_host(client, 'from-map', site='Filial', placement={'map_id': m['id'], 'maps_rev': s['rev'], 'x': 123, 'y': 456})['id']
    s = snapshot(client)
    assert client.get(f'/api/hosts/{placed}').status_code == 200
    m = next(m for m in s['maps'] if m.get('site') == 'Filial')
    assert m['positions'] == [{'host_id': placed, 'x': 123, 'y': 456}]
    groups = client.get('/api/groups').json()
    r = client.patch('/api/groups/linux-servers', json={'site': 'Herdado'}, headers={'If-Match': groups['rev']})
    assert r.status_code == 200
    inherited = seed_host(client, 'inherited')['id']
    assert inherited in next(m for m in snapshot(client)['maps'] if m.get('site') == 'Herdado')['host_ids']


def test_custom_map_and_rename_cascade(client, env):
    m = {'id': 'lab', 'name': 'Lab', 'kind': 'custom'}
    assert save(client, m).status_code == 200
    s = snapshot(client)
    ident = seed_host(client, 'old', placement={'map_id': 'lab', 'maps_rev': s['rev'], 'x': 20, 'y': 50})['id']
    s = snapshot(client)
    r = client.patch(f'/api/hosts/{ident}', json={'hostname': 'new'}, headers={'If-Match': s['hosts_rev']})
    assert r.status_code == 200, r.text
    m = next(m for m in snapshot(client)['maps'] if m['id'] == 'lab')
    assert m['members'] == [ident]
    assert m['positions'] == [{'host_id': ident, 'x': 20, 'y': 50}]
    assert client.get(f'/api/hosts/{ident}/references').json()['count'] >= 1
    assert next(h for h in snapshot(client)['hosts'] if h['id'] == ident)['hostname'] == 'NEW'


def test_stable_link_ids_and_table_edits(client, env):
    s = snapshot(client)
    ids = [l['id'] for l in s['topology']['links']]
    m = next(m for m in s['maps'] if m['id'] == 'all')
    m['edges'] = {ids[0]: {'route': {'axis': 'x', 'tracks': []}, 'anchors': {'source': {'side': 'right', 'ratio': .5}, 'target': {'side': 'top', 'ratio': .5}}}}
    r = save(client, m, s)
    assert r.status_code == 200, r.text
    assert [l['id'] for l in r.json()['topology']['links']] == ids
    disk = yaml.safe_load((env / 'network/topology.yaml').read_text())
    assert all(l.get('id') for l in disk['links'])
    t = r.json()['topology'];l = t['links'][0]
    body = {k: l[k] for k in ('a', 'b', 'media', 'speed', 'desc') if k in l}
    body['speed'] = '1G'
    r = client.put('/api/topology/links/0', json=body, headers={'If-Match': t['rev']})
    assert r.status_code == 200
    assert r.json()['links'][0]['id'] == ids[0]
    s = snapshot(client)
    assert ids[0] in s['maps'][0]['edges']
    r = client.delete('/api/topology/link/' + ids[0], headers={'If-Match': s['topology']['rev']})
    assert r.status_code == 200
    assert ids[0] not in snapshot(client)['maps'][0]['edges']


def test_delete_host_removes_links_and_positions(client):
    s = snapshot(client);m = s['maps'][0];host = m['host_ids'][0]
    m['positions'] = [{'host_id': host, 'x': 0, 'y': 0}]
    assert save(client, m, s).status_code == 200
    s = snapshot(client)
    assert client.delete(f'/api/hosts/{host}', headers={'If-Match': s['hosts_rev']}).status_code == 200
    s = snapshot(client)
    assert host not in {h['id'] for h in s['hosts']}
    assert all(host not in {p['host_id'] for p in m['positions']} and host not in m['host_ids'] for m in s['maps'])
    assert all(host not in (l['a']['host'], l['b']['host']) for l in s['topology']['links'])


def test_conflicts_do_not_overwrite(client, env):
    s = snapshot(client)
    assert save(client, s['maps'][0], s).status_code == 200
    before = (env / 'network/maps.yaml').read_bytes()
    assert save(client, s['maps'][0], s).status_code == 409
    assert (env / 'network/maps.yaml').read_bytes() == before
    s = snapshot(client);seed_host(client, 'another')
    assert save(client, s['maps'][0], s).status_code == 409


def test_failed_host_placement_rolls_back(client, env, monkeypatch):
    from services import yaml_io
    before = (env / 'network/hosts.yaml').read_bytes()
    original = yaml_io.atomic_write
    def fail_maps(path, *args, **kwargs):
        if path.name == 'maps.yaml':
            raise OSError('simulated')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(yaml_io, 'atomic_write', fail_maps)
    s = snapshot(client)
    with pytest.raises(OSError):
        seed_host(client, 'rollback', placement={'map_id': 'all', 'maps_rev': s['rev'], 'x': 0, 'y': 0})
    assert (env / 'network/hosts.yaml').read_bytes() == before
    assert not (env / 'network/maps.yaml').exists()


def test_validation_and_read_only(client, env):
    import deps
    s = snapshot(client);m = s['maps'][0]
    m['positions'] = [{'host_id': 99999, 'x': 1, 'y': 2}]
    assert save(client, m, s).status_code == 422
    m['positions'] = []
    m['objects'] = [{'id': 'ref', 'type': 'reference', 'position': {'x': 0, 'y': 0}, 'map_id': 'missing'}]
    assert save(client, m, s).status_code == 422
    m['objects'] = []
    deps.STATE.read_only = True
    assert save(client, m, s).status_code == 403
    assert not (env / 'network/maps.yaml').exists()


def test_delete_map_only_removes_visual_references(client):
    assert save(client, {'id': 'custom', 'name': 'Mapa adicional', 'kind': 'custom'}).status_code == 200
    s = snapshot(client);m = s['maps'][0]
    m['objects'] = [{'id': 'ref', 'type': 'reference', 'position': {'x': 0, 'y': 0}, 'map_id': 'custom'}]
    assert save(client, m, s).status_code == 200
    s = snapshot(client)
    r = client.delete('/api/maps/custom', headers={'If-Match': s['rev']})
    assert r.status_code == 200
    after = r.json()
    assert after['hosts'] == s['hosts']
    assert after['topology'] == s['topology']
    assert not after['maps'][0]['objects']


def test_duplicate_links_keep_independent_ids(client):
    s = snapshot(client)
    link = {'a': {'host': 1, 'port': 'e1'}, 'b': {'host': 2, 'port': 'e2'}, 'speed': '10G'}
    for _ in range(3):
        t = snapshot(client)['topology']
        assert client.post('/api/topology/links', json=link, headers={'If-Match': t['rev']}).status_code == 200
    t = snapshot(client)['topology']
    assert len(t['links']) == len(s['topology']['links']) + 3
    assert len({l['id'] for l in t['links']}) == len(t['links'])


def test_map_security_gate_and_origin(client, env, monkeypatch):
    import deps
    from app import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(deps, 'auth_required', lambda: True)
    anonymous = TestClient(create_app(), base_url='http://127.0.0.1')
    assert anonymous.get('/api/maps').status_code == 401
    s = snapshot(client)
    assert save(client, s['maps'][0], s).status_code == 200
    s = snapshot(client)
    body = {'map': {k: v for k, v in s['maps'][0].items() if k != 'host_ids'}, 'hosts_rev': s['hosts_rev'], 'topology_rev': s['topology']['rev']}
    # Com login ativo o gate é a sessão (token em header, sem cookie): domínio de proxy reverso passa.
    assert client.get('/api/maps', headers={'Host': 'proxy.exemplo.com'}).status_code == 200
    # Sem login (console aberto) Host/Origin estranhos seguem barrados.
    monkeypatch.setattr(deps, 'auth_required', lambda: False)
    assert client.put('/api/maps/all', json=body, headers={'If-Match': s['rev'], 'Origin': 'https://evil.invalid'}).status_code == 403
    assert client.get('/api/maps', headers={'Host': 'evil.invalid'}).status_code == 403


def test_invalid_nonfinite_coordinate_and_missing_revision(client):
    s = snapshot(client);m = s['maps'][0];m['positions'] = [{'host_id': m['host_ids'][0], 'x': 'NaN', 'y': 0}]
    assert save(client, m, s).status_code == 422
    m['positions'] = []
    value = {k: v for k, v in m.items() if k != 'host_ids'}
    assert client.put('/api/maps/all', json={'map': value, 'hosts_rev': s['hosts_rev'], 'topology_rev': s['topology']['rev']}).status_code == 422


def test_external_inventory_removal_does_not_block_layout_save(client, env):
    s = snapshot(client);m = s['maps'][0];name = m['host_ids'][0]
    m['positions'] = [{'host_id': name, 'x': 1, 'y': 2}]
    assert save(client, m, s).status_code == 200
    path = env / 'network/hosts.yaml'
    data = yaml.safe_load(path.read_text());data['hosts'] = [h for h in data['hosts'] if h['id'] != name];path.write_text(yaml.safe_dump(data))
    s = snapshot(client)
    assert name not in {p['host_id'] for p in s['maps'][0]['positions']}
    assert save(client, s['maps'][0], s).status_code == 200


def test_host_delete_rolls_back_all_three_files(client, env, monkeypatch):
    from services import yaml_io
    s = snapshot(client);m = s['maps'][0]
    assert save(client, m, s).status_code == 200
    before = {name: (env / 'network' / name).read_bytes() for name in ('hosts.yaml', 'maps.yaml', 'topology.yaml')}
    original = yaml_io.atomic_write
    failed = False
    def fail_once(path, *args, **kwargs):
        nonlocal failed
        if path.name == 'maps.yaml' and not failed:
            failed = True
            raise OSError('simulated')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(yaml_io, 'atomic_write', fail_once)
    with pytest.raises(OSError):
        client.delete('/api/hosts/1', headers={'If-Match': s['hosts_rev']})
    assert all((env / 'network' / name).read_bytes() == value for name, value in before.items())


def test_single_site_has_only_general_map(client, env):
    s = snapshot(client)
    assert {h['site'] for h in s['hosts']} == {'matriz'}
    assert [(m['id'], m['name']) for m in s['maps']] == [('all', 'Rede geral')]
    assert s['maps'][0]['host_ids'] == sorted(h['id'] for h in s['hosts'])
    assert not (env / 'network/maps.yaml').exists()


def test_multiple_sites_keep_distinct_maps(client):
    seed_host(client, 'filial-host', site='filial')
    s = snapshot(client)
    assert {m.get('site') for m in s['maps'] if m['kind'] == 'site'} == {'matriz', 'filial'}
    assert len(s['maps']) == 3


def test_host_without_site_keeps_general_separate(client):
    ident = seed_host(client, 'no-site')['id']
    s = snapshot(client)
    assert len(s['maps']) == 2
    assert ident in next(m for m in s['maps'] if m['id'] == 'all')['host_ids']
    assert ident not in next(m for m in s['maps'] if m.get('site') == 'matriz')['host_ids']


def _seed_duplicate_maps(client, env):
    from services import topology_svc
    link_id = topology_svc.load_topology()['links'][0]['id']
    data = {'version': 1, 'maps': [
        {'id': 'all', 'name': 'Rede geral', 'kind': 'all',
         'positions': {'rt-core-01': {'x': 100, 'y': 200}},
         'objects': [{'id': 'note', 'type': 'note', 'label': 'Geral', 'position': {'x': 10, 'y': 20}}],
         'visual_links': []},
        {'id': 'old-matriz', 'name': 'matriz', 'kind': 'site', 'site': 'matriz',
         'positions': {'rt-core-01': {'x': 999, 'y': 999}, 'rt-dist-01': {'x': 300, 'y': 400}},
         'edges': {link_id: {'route': {'axis': 'x', 'tracks': [550]}}},
         'objects': [
             {'id': 'note', 'type': 'note', 'label': 'Local', 'position': {'x': 30, 'y': 40}},
             {'id': 'self', 'type': 'reference', 'map_id': 'all', 'position': {'x': 50, 'y': 60}},
         ],
         'visual_links': [{'id': 'visual', 'source': 'host:rt-core-01', 'target': 'object:note', 'label': 'Local'},
                          {'id': 'self-link', 'source': 'host:rt-core-01', 'target': 'object:self'}]},
        {'id': 'teste', 'name': 'teste', 'kind': 'custom', 'members': ['rt-core-01'],
         'objects': [{'id': 'ref', 'type': 'reference', 'map_id': 'old-matriz', 'position': {'x': 7, 'y': 8}}]},
    ]}
    path = env / 'network/maps.yaml'
    path.write_text('# Layout existente\n' + yaml.safe_dump(data, allow_unicode=True))
    return path, link_id


def test_duplicate_site_merges_layout_without_writing_on_get(client, env):
    path, link_id = _seed_duplicate_maps(client, env)
    before = path.read_bytes()
    s = snapshot(client)
    assert path.read_bytes() == before
    assert [m['id'] for m in s['maps']] == ['all', 'teste']
    assert s['map_aliases']['old-matriz'] == 'all'
    general = s['maps'][0]
    assert general['positions'] == [{'host_id': 1, 'x': 100, 'y': 200}, {'host_id': 2, 'x': 300, 'y': 400}]
    assert general['edges'][link_id]['route']['tracks'] == [550]
    notes = {o['label']: o for o in general['objects']}
    assert set(notes) == {'Geral', 'Local'}
    assert notes['Geral']['id'] != notes['Local']['id']
    assert general['visual_links'][0]['target'] == {'kind': 'object', 'object_id': notes['Local']['id']}
    assert not any(o['id'] == 'self' for o in general['objects'])
    assert not any(v['id'] == 'self-link' for v in general['visual_links'])
    assert s['maps'][1]['objects'][0]['map_id'] == 'all'
    assert snapshot(client) == s


def test_save_consolidated_map_is_persistent_and_preserves_custom(client, env):
    path, _ = _seed_duplicate_maps(client, env)
    s = snapshot(client)
    r = save(client, s['maps'][0], s)
    assert r.status_code == 200, r.text
    assert [m['id'] for m in r.json()['maps']] == ['all', 'teste']
    disk = yaml.safe_load(path.read_text())
    assert [m['id'] for m in disk['maps']] == ['all', 'teste']
    assert disk['maps'][1]['objects'][0]['map_id'] == 'all'
    assert disk['maps'][1]['members'] == [1]
    assert disk['version'] == 2
    assert path.read_text().startswith('# Layout existente')
    assert len(list(path.parent.glob('maps.yaml.bak.*'))) >= 1
    assert snapshot(client) == r.json()


def test_stale_site_editor_does_not_overwrite_general(client, env):
    path, _ = _seed_duplicate_maps(client, env)
    s = snapshot(client)
    original = path.read_bytes()
    old = {'id': 'old-matriz', 'name': 'matriz', 'kind': 'site', 'site': 'matriz'}
    r = save(client, old, s)
    assert r.status_code == 409
    assert path.read_bytes() == original


def test_legacy_site_placement_goes_to_general(client):
    import hashlib
    s = snapshot(client)
    legacy_id = 'site-' + hashlib.sha256(b'matriz').hexdigest()[:20]
    ident = seed_host(client, 'legacy-placement', site='matriz', placement={
        'map_id': legacy_id, 'maps_rev': s['rev'], 'x': 42, 'y': 43,
    })['id']
    after = snapshot(client)
    assert len(after['maps']) == 1
    assert after['maps'][0]['positions'] == [{'host_id': ident, 'x': 42, 'y': 43}]


def test_site_maps_return_if_a_second_locality_is_added(client):
    s = snapshot(client)
    s['maps'][0]['positions'] = [{'host_id': 1, 'x': 100, 'y': 200}]
    assert save(client, s['maps'][0], s).status_code == 200
    seed_host(client, 'second-locality', site='Filial')
    after = snapshot(client)
    assert after['maps'][0]['positions'] == [{'host_id': 1, 'x': 100, 'y': 200}]
    assert {m.get('site') for m in after['maps'] if m['kind'] == 'site'} == {'matriz', 'Filial'}


def test_legacy_site_id_cannot_be_recreated_as_custom_map(client):
    import hashlib
    ident = 'site-' + hashlib.sha256(b'matriz').hexdigest()[:20]
    r = save(client, {'id': ident, 'name': 'Personalizado', 'kind': 'custom'})
    assert r.status_code == 409  # ID reservado pelo alias do mapa automático antigo


def test_delete_any_map_is_soft_and_not_recreated(client, env):
    assert save(client, {'id': 'custom', 'name': 'Mapa adicional', 'kind': 'custom'}).status_code == 200
    s = snapshot(client)
    r = client.delete('/api/maps/custom', headers={'If-Match': s['rev']})
    assert r.status_code == 200
    assert 'custom' not in [m['id'] for m in r.json()['maps']]
    assert 'custom' in (env_maps := (env / 'network/maps.yaml').read_text())  # registro permanece no arquivo
    assert 'deleted: true' in env_maps
    s = snapshot(client)
    assert 'custom' not in [m['id'] for m in s['maps']]
    assert client.delete('/api/maps/all', headers={'If-Match': s['rev']}).status_code == 422
