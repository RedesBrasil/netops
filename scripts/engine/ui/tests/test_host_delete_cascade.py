"""Exclusão inteira remove referências em todos os mapas, só em dados fictícios."""
import copy

import yaml


def test_delete_host_cleans_both_physical_and_visual_ends_in_every_map(client, env):
    def snapshot():
        response = client.get('/api/maps')
        assert response.status_code == 200, response.text
        return response.json()

    def save(value):
        state = snapshot()
        value = copy.deepcopy(value)
        value.pop('host_ids', None)
        response = client.put('/api/maps/' + value['id'], json={
            'map': value, 'hosts_rev': state['hosts_rev'],
            'topology_rev': state['topology']['rev'],
        }, headers={'If-Match': state['rev']})
        assert response.status_code == 200, response.text

    # Há enlaces existentes com o host 2 na ponta A e na ponta B; crie paralelos
    # nos dois sentidos para provar que nenhum fica órfão após a exclusão.
    for source, target in [(1, 2), (2, 1)]:
        state = snapshot()
        response = client.post('/api/topology/links', json={
            'a': {'host': source}, 'b': {'host': target},
        }, headers={'If-Match': state['topology']['rev']})
        assert response.status_code == 200, response.text

    state = snapshot()
    affected = {link['id'] for link in state['topology']['links']
                if 2 in (link['a']['host'], link['b']['host'])}
    kept = {link['id']: link for link in state['topology']['links']
            if link['id'] not in affected}
    assert len(affected) == 4 and kept
    kept_disk = {link['id']: link for link in yaml.safe_load(
        (env / 'network/topology.yaml').read_text())['links']
        if link['id'] not in affected}
    general = next(value for value in state['maps'] if value['id'] == 'all')
    for index, map_id in enumerate(['all', 'cascade-one', 'cascade-two']):
        value = copy.deepcopy(general)
        value.update(id=map_id, name=map_id, members=[1, 2, 3, 4],
                     kind='all' if map_id == 'all' else 'custom')
        value['positions'] = [{'host_id': host_id, 'x': host_id * 200,
                               'y': index * 50, 'z_index': host_id}
                              for host_id in [1, 2, 3, 4]]
        value['objects'] = [
            {'id': object_id, 'type': 'shape', 'label': '',
             'position': {'x': 100, 'y': 300 + number * 200}}
            for number, object_id in enumerate(['first', 'second'])]
        value['visual_links'] = [
            {'id': 'host-as-source', 'source': {'kind': 'host', 'host_id': 2},
             'target': {'kind': 'object', 'object_id': 'first'}},
            {'id': 'host-as-target', 'source': {'kind': 'object', 'object_id': 'second'},
             'target': {'kind': 'host', 'host_id': 2}},
            {'id': 'keep-other-host', 'source': {'kind': 'host', 'host_id': 1},
             'target': {'kind': 'object', 'object_id': 'first'}},
            {'id': 'keep-objects', 'source': {'kind': 'object', 'object_id': 'first'},
             'target': {'kind': 'object', 'object_id': 'second'}},
        ]
        value['edges'] = {link_id: {'route': {'axis': 'x', 'tracks': [120]}}
                          for link_id in affected | set(kept)}
        save(value)

    before = snapshot()
    before_maps = {value['id']: value for value in before['maps']}
    assert set(before_maps) == {'all', 'cascade-one', 'cascade-two'}
    # Uma revisão antiga deve rejeitar a exclusão sem tocar qualquer arquivo.
    files_before = {name: (env / 'network' / name).read_bytes()
                    for name in ['hosts.yaml', 'topology.yaml', 'maps.yaml']}
    rejected = client.delete('/api/hosts/2', headers={'If-Match': '0' * 64})
    assert rejected.status_code == 409
    assert files_before == {name: (env / 'network' / name).read_bytes()
                            for name in files_before}

    response = client.delete('/api/hosts/2', headers={'If-Match': before['hosts_rev']})
    assert response.status_code == 200, response.text
    after = snapshot()
    assert 2 not in {host['id'] for host in after['hosts']}
    assert {link['id']: {key: value for key, value in link.items() if key != 'index'}
            for link in after['topology']['links']} == {
        link_id: {key: value for key, value in link.items() if key != 'index'}
        for link_id, link in kept.items()}
    for value in after['maps']:
        previous = before_maps[value['id']]
        assert 2 not in value['members'] and 2 not in value['host_ids']
        assert value['positions'] == [position for position in previous['positions']
                                      if position['host_id'] != 2]
        assert not (affected & set(value['edges']))
        assert value['edges'] == {key: route for key, route in previous['edges'].items()
                                  if key not in affected}
        assert value['visual_links'] == [link for link in previous['visual_links']
                                         if link['id'].startswith('keep-')]
        assert value['objects'] == previous['objects']

    # Valide os documentos gravados, não apenas o snapshot que filtra referências.
    stored_maps = yaml.safe_load((env / 'network/maps.yaml').read_text())['maps']
    for value in stored_maps:
        assert 2 not in value['members']
        assert all(position['host_id'] != 2 for position in value['positions'])
        assert not (affected & set(value['edges']))
        assert {link['id'] for link in value['visual_links']} == {
            'keep-other-host', 'keep-objects'}
    stored_links = yaml.safe_load((env / 'network/topology.yaml').read_text())['links']
    assert {link['id']: link for link in stored_links} == kept_disk
    assert client.get('/api/hosts/2').status_code == 404

