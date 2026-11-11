"""Remoção da tela antiga sem perder o cadastro de enlaces ou a persistência YAML."""
from pathlib import Path

import yaml


def test_removed_topology_module_and_shared_link_form(client):
    ui = Path(__file__).resolve().parents[1]
    assert not (ui / 'static/js/pages/topology.js').exists()
    main = (ui / 'static/js/main.js').read_text()
    maps = (ui / 'static/js/pages/maps.js').read_text()
    assert 'TopologyPage' not in main
    assert 'pages/topology.js' not in main
    assert 'from "../components.js"' in maps
    assert 'export function LinkForm' in (ui / 'static/js/components.js').read_text()
    assert client.get('/js/pages/topology.js').status_code == 404
    assert client.get('/js/pages/maps.js').status_code == 200
    assert client.get('/api/topology').status_code == 200


def test_map_state_is_saved_as_utf8_yaml_and_reloaded(client, env):
    from app import create_app
    from fastapi.testclient import TestClient
    s = client.get('/api/maps').json()
    m = s['maps'][0]
    m.pop('host_ids', None)
    m['positions'] = [{'host_id': 1, 'x': 123, 'y': 456}]
    m['objects'] = [{'id': 'note', 'type': 'note', 'position': {'x': 40, 'y': 60}, 'label': 'Rede e documentação'}]
    r = client.put('/api/maps/all', json={'map': m, 'hosts_rev': s['hosts_rev'], 'topology_rev': s['topology']['rev']},
                   headers={'If-Match': s['rev']})
    assert r.status_code == 200, r.text
    path = env / 'network/maps.yaml'
    text = path.read_bytes().decode('utf-8')
    data = yaml.safe_load(text)
    assert data['version'] == 2
    stored = next(m for m in data['maps'] if m['id'] == 'all')
    assert stored['positions'] == [{'host_id': 1, 'x': 123, 'y': 456}]
    assert stored['objects'][0]['label'] == 'Rede e documentação'
    # Outra instância da aplicação lê o mesmo disco, sem estado anterior em RAM.
    fresh = TestClient(create_app(), base_url='http://127.0.0.1', headers=client.headers)
    after = fresh.get('/api/maps')
    assert after.status_code == 200
    assert after.json()['maps'][0]['positions'] == stored['positions']
    assert after.json()['maps'][0]['objects'] == r.json()['maps'][0]['objects']
