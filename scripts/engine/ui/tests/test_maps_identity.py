"""Identidade inteira em mapas e leitura legada sem modificar os arquivos reais."""
import copy

import pytest
import yaml


@pytest.mark.parametrize('ident', ['1', True, 1.0, 0, -1])
def test_map_rejects_noncanonical_host_identity(client, ident):
    state = client.get('/api/maps').json()
    value = copy.deepcopy(state['maps'][0])
    value.pop('host_ids')
    value['positions'] = [{'host_id': ident, 'x': 40, 'y': 60}]
    response = client.put('/api/maps/all', json={'map': value, 'hosts_rev': state['hosts_rev'],
                                              'topology_rev': state['topology']['rev']},
                          headers={'If-Match': state['rev']})
    assert response.status_code == 422, response.text


def test_duplicate_host_position_cannot_be_saved(client, env):
    state = client.get('/api/maps').json()
    value = copy.deepcopy(state['maps'][0])
    value.pop('host_ids')
    value['positions'] = [{'host_id': 1, 'x': 40, 'y': 60}, {'host_id': 1, 'x': 80, 'y': 90}]
    response = client.put('/api/maps/all', json={'map': value, 'hosts_rev': state['hosts_rev'],
                                              'topology_rev': state['topology']['rev']},
                          headers={'If-Match': state['rev']})
    assert response.status_code == 422, response.text
    assert not (env / 'network/maps.yaml').exists()


def test_legacy_inventory_remains_visible_read_only_without_implicit_migration(client, env):
    path = env / 'network/hosts.yaml'
    source = yaml.safe_load(path.read_text())
    aliases = {host['id']: f'old-{host["id"]}' for host in source['hosts']}
    source['version'] = 1
    source['hosts'] = {aliases[host['id']]: {k: v for k, v in host.items() if k != 'id'} for host in source['hosts']}
    source.pop('next_host_id', None)
    source.pop('legacy_aliases', None)
    path.write_text(yaml.safe_dump(source))
    maps = {'version': 1, 'maps': [{'id': 'all', 'name': 'Rede geral', 'kind': 'all',
            'positions': {'old-1': {'x': 40, 'y': 60}},
            'objects': [{'id': 'shape', 'type': 'shape', 'position': {'x': 80, 'y': 90}}],
            'visual_links': [{'id': 'v', 'source': 'host:old-1', 'target': 'object:shape'}]}]}
    (env / 'network/maps.yaml').write_text(yaml.safe_dump(maps))
    before = {name: (env / 'network' / name).read_bytes() for name in ('hosts.yaml', 'maps.yaml', 'topology.yaml')}
    response = client.get('/api/maps')
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['read_only'] is True
    assert state['migration_required'] is True
    assert state['maps'][0]['positions'] == [{'host_id': 'old-1', 'x': 40, 'y': 60}]
    assert {host['id'] for host in state['hosts']} == set(aliases.values())
    assert all((env / 'network' / name).read_bytes() == contents for name, contents in before.items())
