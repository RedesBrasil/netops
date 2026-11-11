"""Interfaces de enlace opcionais, sem tocar em arquivos reais."""
import pytest
import yaml


@pytest.mark.parametrize('a,b', [({}, {}), ({'port': ''}, {'port': ''}),
                               ({'port': None}, {'port': None}),
                               ({'port': '  '}, {'port': '  '})])
def test_create_link_without_interfaces(client, env, a, b):
    topo = client.get('/api/topology').json()
    response = client.post('/api/topology/links', json={
        'a': {'host': 1, **a}, 'b': {'host': 2, **b}, 'speed': '10G',
    }, headers={'If-Match': topo['rev']})
    assert response.status_code == 200, response.text
    link = response.json()['links'][-1]
    assert link['a'] == {'host': 1}
    assert link['b'] == {'host': 2}
    stored = yaml.safe_load((env / 'network/topology.yaml').read_text())['links'][-1]
    assert 'port' not in stored['a'] and 'port' not in stored['b']
    maps = client.get('/api/maps').json()
    assert any(l['id'] == link['id'] for l in maps['topology']['links'])
    rendered = client.get('/api/topology/preview')
    assert rendered.status_code == 200
    assert '10G' in rendered.json()['markdown']


@pytest.mark.parametrize('side', ['a', 'b'])
def test_only_one_interface_is_enough(client, env, side):
    body = {'a': {'host': 1}, 'b': {'host': 2}}
    body[side]['port'] = ' sfp1 '
    response = client.post('/api/topology/links', json=body)
    assert response.status_code == 200, response.text
    link = response.json()['links'][-1]
    assert link[side]['port'] == 'sfp1'
    assert 'port' not in link['b' if side == 'a' else 'a']


@pytest.mark.parametrize('by_id', [False, True])
def test_clear_interfaces_on_existing_link(client, env, by_id):
    topo = client.get('/api/topology').json()
    link = topo['links'][0]
    assert link['a']['port'] and link['b']['port']
    path = '/api/topology/link/' + link['id'] if by_id else '/api/topology/links/0'
    response = client.put(path, json={'a': {'host': link['a']['host']},
                                     'b': {'host': link['b']['host'], 'port': ''}, 'speed': '1G'},
                          headers={'If-Match': topo['rev']})
    assert response.status_code == 200, response.text
    edited = response.json()['links'][0]
    assert edited['id'] == link['id']
    assert 'port' not in edited['a'] and 'port' not in edited['b']
    stored = yaml.safe_load((env / 'network/topology.yaml').read_text())['links'][0]
    assert 'port' not in stored['a'] and 'port' not in stored['b']


@pytest.mark.parametrize('a,b', [({}, {'host': 2}),
                               ({'host': 1}, {}),
                               ({'host': ''}, {'host': 2})])
def test_hosts_remain_required(client, env, a, b):
    before = (env / 'network/topology.yaml').read_bytes()
    response = client.post('/api/topology/links', json={'a': a, 'b': b})
    assert response.status_code == 422
    assert (env / 'network/topology.yaml').read_bytes() == before
