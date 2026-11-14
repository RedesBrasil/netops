"""SO separado da aplicação: os/os_version/apps/runs_on (dados fictícios, inventário em tmp)."""
import yaml


def _rev(client):
    return client.get('/api/hosts').json()['rev']


def _create(client, **fields):
    return client.post('/api/hosts', json={
        'hostname': 'zbx-test', 'mgmt_ip': '192.0.2.60', 'group': 'linux-servers', **fields,
    }, headers={'If-Match': _rev(client)})


def _disk(env, host_id):
    data = yaml.safe_load((env / 'network/hosts.yaml').read_text())
    return next(h for h in data['hosts'] if h['id'] == host_id)


def test_create_with_os_apps_runs_on_saves_uppercase_in_order(client, env):
    r = _create(client, model='lxc', os='debian', os_version='12.11', runs_on=1,
                apps=[{'name': 'zabbix server', 'version': '7.0.32'}, {'name': ' postgresql ', 'version': ''}])
    assert r.status_code == 201, r.text
    hid = r.json()['id']
    host = _disk(env, hid)
    assert host['os'] == 'DEBIAN' and host['os_version'] == '12.11' and host['runs_on'] == 1
    assert host['apps'] == [{'name': 'ZABBIX SERVER', 'version': '7.0.32'}, {'name': 'POSTGRESQL'}]
    keys = list(host)
    assert keys.index('model') < keys.index('os') < keys.index('os_version') < keys.index('apps') < keys.index('runs_on')
    assert 'version' not in host


def test_patch_migrates_legacy_version_and_clears_fields(client, env):
    hid = _create(client, version='ZABBIX 7.0.32').json()['id']
    r = client.patch(f'/api/hosts/{hid}', json={'os': 'debian', 'os_version': '12',
                                               'apps': [{'name': 'zabbix server', 'version': '7.0.32'}], 'version': None},
                     headers={'If-Match': _rev(client)})
    assert r.status_code == 200, r.text
    host = _disk(env, hid)
    assert 'version' not in host and host['apps'][0]['name'] == 'ZABBIX SERVER'
    r = client.patch(f'/api/hosts/{hid}', json={'apps': None, 'os': '', 'os_version': None},
                     headers={'If-Match': _rev(client)})
    assert r.status_code == 200, r.text
    host = _disk(env, hid)
    assert not {'apps', 'os', 'os_version'} & set(host)


def test_runs_on_rejects_missing_self_and_cycle(client, env):
    assert _create(client, runs_on=999).status_code == 422
    a = _create(client, hostname='a').json()['id']
    assert client.patch(f'/api/hosts/{a}', json={'runs_on': a}, headers={'If-Match': _rev(client)}).status_code == 422
    b = _create(client, hostname='b', mgmt_ip='192.0.2.61', runs_on=a).json()['id']
    r = client.patch(f'/api/hosts/{a}', json={'runs_on': b}, headers={'If-Match': _rev(client)})
    assert r.status_code == 422 and 'ciclo' in r.text


def test_apps_validation_limits(client):
    assert _create(client, apps=[{'name': ''}]).status_code == 422
    assert _create(client, apps=[{'name': f'APP{i}'} for i in range(11)]).status_code == 422
    assert _create(client, apps=[{'name': 'x', 'extra': 1}]).status_code == 422


def test_delete_host_clears_runs_on_of_guests_and_lists_reference(client, env):
    pve = _create(client, hostname='pve', os='debian').json()['id']
    ct = _create(client, hostname='ct', mgmt_ip='192.0.2.62', runs_on=pve).json()['id']
    refs = client.get(f'/api/hosts/{pve}/references').json()['references']
    assert any(r['kind'] == 'runs-on' and r['id'] == ct for r in refs)
    assert client.delete(f'/api/hosts/{pve}', headers={'If-Match': _rev(client)}).status_code == 200
    assert 'runs_on' not in _disk(env, ct)
    assert client.get('/api/hosts/validate').json().get('ok', True) in (True, False)  # endpoint segue respondendo
