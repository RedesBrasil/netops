"""Atualização real de tags antigas, supervisor congelado e dados v1 fictícios.

NETOPS_UPDATE_TEST_PACKAGE pode apontar o pacote oficial de HEAD para a rodada final.
Sem essa variável, a preparação usa um pacote exclusivamente fictício do working tree.
Nenhum teste conecta em equipamentos ou lê credenciais do operador.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

import deps
from update import engine
from update.common import REPOSITORY, STATE_DIR, distributed, private_dir, write_json
from update.release import build_package

PROJECT = Path(__file__).resolve().parents[4]
VERSION = '2.0.0'
MASTER = 'fixture-migration-update-master'
DOCUMENTS = ('hosts.yaml', 'topology.yaml', 'maps.yaml', 'backups.yaml')


def _files_from_working_tree():
    paths = subprocess.check_output(['git', '-C', str(PROJECT), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).split(b'\0')
    files = {}
    for raw in paths:
        if not raw:
            continue
        rel = raw.decode()
        source = PROJECT / rel
        if not distributed(rel) or not source.is_file() or source.is_symlink():
            continue
        content = source.read_bytes()
        if rel == 'core/config/core-config.yaml':
            content = re.sub(rb'^  version: "[0-9.]+"', b'  version: "2.0.0"', content, flags=re.M)
        files[rel] = {'raw': content, 'sha256': hashlib.sha256(content).hexdigest(),
                      'size': len(content), 'mode': 0o755 if source.stat().st_mode & 0o111 else 0o644}
    return files


@pytest.fixture(scope='module')
def auto_candidate(tmp_path_factory):
    base = tmp_path_factory.mktemp('auto-host-package')
    official = os.environ.get('NETOPS_UPDATE_TEST_PACKAGE')
    if official:
        package = Path(official).resolve()
        manifest = engine.unpack(package, base / 'verified', VERSION)
        files = {rel: {**info, 'raw': (base / 'verified' / rel).read_bytes()}
                 for rel, info in manifest['files'].items()}
    else:
        files = _files_from_working_tree()
        # A instalação fictícia roda offline (PIP_NO_INDEX) e compartilha o venv do teste,
        # que já tem as dependências atuais. Se o requirements.txt diferir das tags antigas,
        # o atualizador legado tentaria montar um venv novo pelo PyPI e o teste viraria
        # timeout de rede, não de migração. A troca de dependências tem teste próprio
        # (failure='dependencies').
        legacy = engine.git_files(PROJECT, 'v1.3.0')['requirements.txt']
        files['requirements.txt'] = {**files['requirements.txt'], 'raw': legacy['raw'],
                                     'sha256': legacy['sha256'], 'size': legacy['size']}
        package = base / 'candidate.tar.gz'
        build_package(files, VERSION, package)
    with __import__('tarfile').open(package, 'r:gz') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
    # Estes são os únicos contratos que supervisores 1.2.1/1.3.0 aceitam.
    assert manifest['protocol'] == 1 and not manifest.get('migrations')
    return package, files


class LegacyConsole:
    def __init__(self, base, tag, package, *, external=True, dangling=False, expect_failure=False):
        self.base, self.tag = base, tag
        self.expect_failure = expect_failure
        self.root = base / 'installation'
        self.root.mkdir()
        self.data = base / 'external-data' if external else self.root
        self.state = self.root / STATE_DIR
        self.version = tag.removeprefix('v')
        self.phase_history = []
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        files = engine.git_files(PROJECT, tag)
        for rel, info in files.items():
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(info['raw'])
            dest.chmod(info['mode'])
        self.old_supervisor = files['scripts/engine/update/supervisor.py']['sha256']
        self.old_requirements = files['requirements.txt']['raw']
        private_dir(self.state)
        write_json(self.state / 'installed.json', {
            'protocol': 1, 'repository': REPOSITORY, 'version': self.version, 'migrations': [],
            'files': {rel: {key: value for key, value in info.items() if key != 'raw'}
                      for rel, info in files.items()},
        })
        self.venv = PROJECT / '.venv' if (PROJECT / '.venv/bin/python3').exists() else Path(sys.prefix)
        (self.root / '.venv').symlink_to(self.venv, target_is_directory=True)
        self._documents(dangling)
        self.before = self.documents()
        assets = base / 'assets'
        assets.mkdir()
        shutil.copyfile(package, assets / 'release.tar.gz')
        asset = assets / 'release.tar.gz'
        write_json(assets / 'releases.json', [{
            'id': 202000, 'tag_name': 'v' + VERSION, 'body': 'Fixture de migração automática',
            'assets': [{'id': 202001, 'name': 'netops-' + VERSION + '.tar.gz',
                        'digest': 'sha256:' + hashlib.sha256(asset.read_bytes()).hexdigest(),
                        'size': asset.stat().st_size}],
        }])
        ghbin = base / 'bin'
        ghbin.mkdir()
        gh = ghbin / 'gh'
        gh.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
base = Path(os.environ['NETOPS_FIXTURE_ASSETS'])
argument = next(value for value in sys.argv if value.startswith('repos/'))
sys.stdout.buffer.write((base / ('release.tar.gz' if '/releases/assets/' in argument else 'releases.json')).read_bytes())
''')
        gh.chmod(0o755)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        home = base / 'home'
        home.mkdir()
        self.env = dict(os.environ, HOME=str(home), NETOPS_UI_HOME=str(home),
                        PATH=str(ghbin) + os.pathsep + os.environ['PATH'],
                        NETOPS_UI_HOST='127.0.0.1', NETOPS_UI_PORT=str(self.port),
                        NETOPS_UI_TERMINAL='0', NETOPS_UI_CLAUDE='0', NETOPS_UI_CLAUDE_PERSIST='0',
                        NETOPS_UI_DATA_ROOT=str(self.data), NETOPS_FIXTURE_ASSETS=str(assets),
                        PIP_NO_INDEX='1',
                        # start.sh de releases ANTIGAS (fixture) só entra em primeiro plano por env.
                        NETOPS_UI_FOREGROUND='1')
        for key in ('NETOPS_UPDATE_FROZEN', 'NETOPS_UPDATE_MANAGED', 'NETOPS_UPDATE_NONCE', 'NETOPS_UPDATE_RECOVERING'):
            self.env.pop(key, None)
        self.process = None
        self.log = None
        self.browser = self.browser_log = None

    def _documents(self, dangling):
        network = self.data / 'network'
        network.mkdir(parents=True, exist_ok=True)
        docs = {
            'hosts.yaml': {'version': 1, 'groups': {'linux-servers': {
                'vendor': 'linux', 'credential': 'fixture-reference', 'access': {'method': 'ssh'}}},
                'hosts': {'old-a': {'hostname': 'Host A fixture', 'mgmt_ip': '192.0.2.1', 'group': 'linux-servers'},
                          'old-b': {'hostname': 'Host B fixture', 'mgmt_ip': '192.0.2.2', 'group': 'linux-servers'}}},
            'topology.yaml': {'version': 1, 'links': [
                {'id': 'preserved-link', 'a': {'host': 'old-a', 'port': 'eth0'},
                 'b': {'host': 'missing' if dangling else 'old-b'}, 'speed': '1G'}], 'segments': []},
            'maps.yaml': {'version': 1, 'maps': [{
                'id': 'all', 'name': 'Rede geral', 'kind': 'all', 'members': [],
                'positions': {'old-a': {'x': 100, 'y': 100, 'z_index': 2}, 'old-b': {'x': 500, 'y': 100}},
                'objects': [{'id': 'shape', 'type': 'shape', 'label': '', 'color': '#123456',
                             'position': {'x': 100, 'y': 350}}],
                'visual_links': [{'id': 'preserved-visual', 'source': 'host:old-a', 'target': 'object:shape'}],
                'edges': {'preserved-link': {'route': {'axis': 'x', 'tracks': [320]}}}}, {
                'id': 'extra', 'name': 'Mapa adicional', 'kind': 'custom', 'members': ['old-a', 'old-b'],
                'positions': {'old-a': {'x': 70, 'y': 80}}, 'objects': [], 'visual_links': [], 'edges': {}}]},
            'backups.yaml': {'version': 2, 'services': [{'id': 'fixture', 'name': 'Backup fixture',
                'enabled': False, 'targets': {'hosts': ['old-a'], 'groups': []}}]},
        }
        for name, doc in docs.items():
            (network / name).write_text('# comentário fixture preservado\n' + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
        config = self.data / 'core/config'
        config.mkdir(parents=True, exist_ok=True)
        (config / 'project-config.yaml').write_text('project:\n  network_name: Migração fictícia\n')
        (self.data / 'memory').mkdir(exist_ok=True)
        (self.data / 'memory/MEMORY.md').write_text('memória fictícia preservada\n')
        self.archive = self.data / 'backups/old-a/2026-01-01/config.txt'
        self.archive.parent.mkdir(parents=True)
        self.archive.write_text('configuração fictícia sem credencial\n')
        from lib import vault
        from vault import cli
        meta, _ = vault.build_meta(MASTER)
        (network / 'credentials.yaml').write_text(cli._set_vault_block('version: 1\ncredentials: {}\n', meta))
        (network / 'credentials.yaml').chmod(0o600)

    def documents(self):
        return {name: (self.data / 'network' / name).read_bytes() for name in DOCUMENTS}

    def request(self, path, body=None, token=None):
        request = urllib.request.Request(self.url + '/api/' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', **({'X-Netops-Session': token} if token else {})})
        with self.opener.open(request, timeout=5) as response:
            return response.status, json.load(response)

    def login(self):
        return self.request('auth/login', {'master_password': MASTER})[1]['auth_token']

    def wait(self, predicate, timeout=95):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert self.process.poll() is None, 'Launcher fictício encerrou; veja ' + str(self.base / 'console.log')
            if not self.expect_failure:
                # Falha terminal inesperada: aborta já com o motivo, sem esperar o timeout.
                try:
                    job = json.loads((self.state / 'job.json').read_text())
                except (OSError, ValueError):
                    job = {}
                if job.get('phase') in ('failed', 'rolled_back'):
                    raise AssertionError(f"Atualização terminou em {job['phase']}: {job.get('detail')} "
                                         f"(log: {self.base / 'console.log'})")
            try:
                result = predicate()
                if result:
                    return result
            except (OSError, ValueError, KeyError, urllib.error.HTTPError):
                pass
            time.sleep(.06)
        raise AssertionError('Timeout em instalação fictícia: ' + str(self.base / 'console.log'))

    def __enter__(self):
        self.log = (self.base / 'console.log').open('wb')
        self.process = subprocess.Popen(['bash', str(self.root / 'scripts/engine/ui/start.sh'), '--no-vault-unlock'],
            cwd=self.root, env=self.env, stdout=self.log, stderr=self.log)
        try:
            self.wait(lambda: (self.state / 'supervisor.json').exists())
            assert self.request('config/meta')[1]['version'] == self.version
            runtimes = list((self.state / 'runtime').glob('*/update/supervisor.py'))
            assert len(runtimes) == 1
            assert hashlib.sha256(runtimes[0].read_bytes()).hexdigest() == self.old_supervisor
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_):
        if self.browser is not None and self.browser.poll() is None:
            self.browser.terminate()
            self.browser.wait(timeout=15)
        if self.browser_log is not None and not self.browser_log.closed:
            self.browser_log.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.log.close()
        destination = os.environ.get('NETOPS_UPDATE_TEST_ARTIFACTS')
        if destination:
            output = Path(destination) / self.base.name
            output.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.base / 'console.log', output / 'console.log')
            (output / 'summary.json').write_text(json.dumps({
                'tag': self.tag, 'root': str(self.root), 'data_root': str(self.data),
                'url': self.url, 'phases': self.phase_history,
                'supervisor_tag_sha256': self.old_supervisor,
                'stopped': self.process.poll() is not None,
            }, indent=2))
            for name in ('job.json', 'journal.json'):
                if (self.state / name).exists():
                    shutil.copyfile(self.state / name, output / name)
            if (self.base / 'browser').exists():
                shutil.copytree(self.base / 'browser', output / 'browser', dirs_exist_ok=True)
            if (self.base / 'browser.log').exists():
                shutil.copyfile(self.base / 'browser.log', output / 'browser.log')

    def apply(self):
        token = self.login()
        status, listing = self.request('updates/check', token=token)
        assert status == 200 and listing['releases'][0]['version'] == VERSION
        status, job = self.request('updates/apply', {'release_id': 202000, 'confirm': True}, token)
        assert status == 202 and job['phase'] == 'queued'

    def terminal_phase(self):
        phase = json.loads((self.state / 'job.json').read_text()).get('phase')
        if not self.phase_history or self.phase_history[-1] != phase:
            self.phase_history.append(phase)
        return phase


@pytest.mark.parametrize('tag,external', [('v1.3.0', True), ('v1.2.1', False)])
def test_real_legacy_supervisor_migrates_only_after_commit(tmp_path, auto_candidate, tag, external):
    package, _ = auto_candidate
    with LegacyConsole(tmp_path, tag, package, external=external) as console:
        old_pid = json.loads((console.state / 'supervisor.json').read_text())['server_pid']
        browser = browser_log = None
        if tag == 'v1.3.0' and os.environ.get('PLAYWRIGHT_MODULE'):
            browser_log = (tmp_path / 'browser.log').open('wb')
            browser = subprocess.Popen(['node', str(PROJECT / 'scripts/engine/ui/tests/auto-host-migration-update.browser.mjs')],
                env=dict(os.environ, NETOPS_E2E_URL=console.url, NETOPS_UPDATE_TEST_ROOT=str(console.root),
                         NETOPS_E2E_OUTPUT=str(tmp_path / 'browser')), stdout=browser_log, stderr=browser_log)
            console.browser, console.browser_log = browser, browser_log
        else:
            console.apply()
        def committed():
            # Ambos os registros precisam confirmar o código antes de qualquer conversão.
            phase_before = console.terminal_phase()
            journal_before = json.loads((console.state / 'journal.json').read_text()) if (console.state / 'journal.json').exists() else {}
            pid_before = json.loads((console.state / 'supervisor.json').read_text())['server_pid']
            recovering_before = (console.state / 'recovery-supervisor').exists()
            documents = console.documents()
            phase_after = console.terminal_phase()
            journal_after = json.loads((console.state / 'journal.json').read_text()) if (console.state / 'journal.json').exists() else {}
            pid_after = json.loads((console.state / 'supervisor.json').read_text())['server_pid']
            recovering_after = (console.state / 'recovery-supervisor').exists()
            if phase_before != 'completed' and phase_after != 'completed' and journal_before.get('phase') != 'completed' and journal_after.get('phase') != 'completed':
                assert documents == console.before, 'Migração ocorreu antes de commit: rollback legado ficaria incompatível'
            if pid_before == old_pid and pid_after == old_pid or recovering_before and recovering_after:
                assert documents == console.before, 'Migração antecipou publicação do novo PID ou remoção da barreira de rollback'
            return phase_after == 'completed'
        try:
            console.wait(committed)
        except BaseException:
            if browser is not None:
                browser.terminate()
                browser.wait(timeout=15)
                browser_log.close()
            raise
        console.wait(lambda: yaml.safe_load((console.data / 'network/hosts.yaml').read_text())['version'] == 2)
        # hosts.yaml é substituído antes dos demais documentos: o bloqueio deve
        # continuar até validar o commit de todos, inclusive para o login.
        console.wait(lambda: console.request('config/meta')[1].get('host_migration', {}).get('blocking') is False)
        token = console.login()
        state = console.wait(lambda: console.request('maps', token=token)[1])
        assert state['read_only'] is False and state['migration_required'] is False
        assert [host['id'] for host in state['hosts']] == [1, 2]
        link = state['topology']['links'][0]
        assert link['id'] == 'preserved-link' and link['a']['host'] == 1 and link['b']['host'] == 2
        general = next(value for value in state['maps'] if value['id'] == 'all')
        assert general['positions'][0] == {'host_id': 1, 'x': 100, 'y': 100, 'z_index': 2}
        assert general['edges']['preserved-link']['route']['tracks'] == [320]
        assert general['visual_links'][0]['source'] == {'kind': 'host', 'host_id': 1}
        assert general['objects'][0]['color'] == '#123456'
        assert next(value for value in state['maps'] if value['id'] == 'extra')['members'] == [1, 2]
        backups = yaml.safe_load((console.data / 'network/backups.yaml').read_text())
        assert backups['version'] == 3 and backups['services'][0]['targets']['hosts'] == [1]
        assert {'host_id': 1, 'directory': 'old-a'} in backups['legacy_sources']
        assert console.archive.read_text() == 'configuração fictícia sem credencial\n'
        assert (console.data / 'memory/MEMORY.md').read_text() == 'memória fictícia preservada\n'
        assert console.request('config/meta')[1]['version'] == VERSION
        assert json.loads((console.state / 'supervisor.json').read_text())['server_pid'] != old_pid
        assert (console.root / '.venv').resolve() == console.venv.resolve()
        if external:
            assert not (console.root / 'network/hosts.yaml').exists()
        migrated = console.documents()
        for _ in range(3):
            console.request('maps', token=token)
        assert console.documents() == migrated
        assert all(b'coment' in content for content in migrated.values())
        if browser is not None:
            try:
                assert browser.wait(timeout=65) == 0, (tmp_path / 'browser.log').read_text()
            finally:
                if browser.poll() is None:
                    browser.terminate()
                    browser.wait(timeout=15)
                browser_log.close()
            destination = os.environ.get('NETOPS_UPDATE_TEST_ARTIFACTS')
            if destination:
                output = Path(destination) / tmp_path.name
                output.mkdir(parents=True, exist_ok=True)
                shutil.copytree(tmp_path / 'browser', output / 'browser', dirs_exist_ok=True)
                shutil.copyfile(tmp_path / 'browser.log', output / 'browser.log')


@pytest.mark.parametrize('failure', ['startup', 'dependencies', 'invalid-references'])
def test_failed_candidate_keeps_v1_readable_by_old_supervisor(tmp_path, auto_candidate, failure):
    candidate_package, files = auto_candidate
    bad = {rel: dict(info) for rel, info in files.items()}
    if failure == 'invalid-references':
        broken = candidate_package
    else:
        rel = 'scripts/engine/ui/app.py' if failure == 'startup' else 'requirements.txt'
        raw = (b"raise RuntimeError('fixture readiness failure before commit')\n" + bad[rel]['raw']
               if failure == 'startup' else b'netops-nonexistent-offline-fixture-package==0.0.0\n')
        bad[rel].update(raw=raw, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        broken = tmp_path / 'broken.tar.gz'
        build_package(bad, VERSION, broken)
    with LegacyConsole(tmp_path, 'v1.3.0', broken, dangling=failure == 'invalid-references',
                       expect_failure=True) as console:
        console.apply()
        expected = 'failed' if failure == 'dependencies' else 'rolled_back'
        console.wait(lambda: console.terminal_phase() == expected)
        console.wait(lambda: console.request('config/meta')[1]['version'] == '1.3.0')
        assert console.documents() == console.before
        assert (console.root / '.venv').resolve() == console.venv.resolve()
        token = console.login()
        state = console.wait(lambda: console.request('maps', token=token)[1])
        assert isinstance(state['hosts'], dict) and 'old-a' in state['hosts']
        assert console.archive.read_text() == 'configuração fictícia sem credencial\n'
        assert not (console.data / 'network/.host-id-migration.json').exists()
        if failure == 'invalid-references':
            assert (console.state / 'host-migration-preflight.json').is_file()
