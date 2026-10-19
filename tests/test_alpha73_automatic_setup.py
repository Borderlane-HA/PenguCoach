"""Upgrade/setup tests use temporary host paths and a simulated systemd/Docker CLI."""
import ast
import fcntl
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from alembic.config import CommandLine
from apps.api.routers import admin_system as api
from pengucoach.maintenance import bootstrap as boot, client


@pytest.fixture
def native(tmp_path,monkeypatch):
    paths={
        'PROJECT':tmp_path/'project','ENVIRONMENT':tmp_path/'config/env','API_UNIT':tmp_path/'systemd/api.service',
        'CONFIG':tmp_path/'config/maintenance.json','SYSTEMD':tmp_path/'run/systemd','NATIVE_STATUS':tmp_path/'run/setup.json',
        'NATIVE_LOG':tmp_path/'logs/setup.log','NATIVE_SOCKET':tmp_path/'run/control.sock',
    }
    for key,path in paths.items():monkeypatch.setattr(boot,key,path)
    paths['PROJECT'].mkdir();paths['ENVIRONMENT'].parent.mkdir();paths['ENVIRONMENT'].touch()
    paths['API_UNIT'].parent.mkdir();paths['API_UNIT'].touch();paths['SYSTEMD'].mkdir(parents=True)
    state=SimpleNamespace(active=False,available=True,returncode=0,timeout=False,calls=[],waits=[])
    def run(args,**kw):
        state.calls.append((args,kw))
        if args[0]=='systemctl':return SimpleNamespace(returncode=0 if state.active else 3)
        assert args==['bash',str(paths['PROJECT']/'install/maintenance/install.sh'),'native',str(paths['PROJECT'])]
        if state.timeout:raise subprocess.TimeoutExpired(args,600)
        kw['stdout'].write('private setup log, example password=do-not-expose\n')
        if state.returncode==0:paths['CONFIG'].write_text('{}');state.active=True
        return SimpleNamespace(returncode=state.returncode)
    monkeypatch.setattr(boot.subprocess,'run',run)
    monkeypatch.setattr(boot.os,'geteuid',lambda:0)
    monkeypatch.setattr(boot,'agent_available',lambda path:state.available)
    monkeypatch.setattr(boot,'wait_agent',lambda path:state.waits.append(path) or state.available)
    return SimpleNamespace(paths=paths,state=state)


def upgrade():return CommandLine().parser.parse_args(['upgrade','head'])


def test_original_alpha72_update_step_automatically_installs_once(native):
    # This is the same CLI options object used by the already-shipped updater.
    assert boot.after_native_migration(boot.PROJECT,'postgresql+asyncpg://u:p@localhost:5432/pengucoach',upgrade())=='ready'
    assert json.loads(boot.NATIVE_STATUS.read_text())['status']=='ready'
    assert boot.NATIVE_LOG.stat().st_mode&0o777==0o600
    assert boot.NATIVE_STATUS.stat().st_mode&0o777==0o644
    assert 'do-not-expose' not in boot.NATIVE_STATUS.read_text()
    assert len(native.state.waits)==1
    assert boot.ensure_native(boot.PROJECT)=='ready'
    assert len([args for args,_ in native.state.calls if args[0]=='bash'])==1


@pytest.mark.parametrize('condition',['nonroot','other_project','no_systemd','no_api_unit','no_env'])
def test_automatic_native_setup_is_restricted_to_managed_root_deployment(native,condition,monkeypatch,tmp_path):
    project=boot.PROJECT
    if condition=='nonroot':monkeypatch.setattr(boot.os,'geteuid',lambda:1000)
    if condition=='other_project':project=tmp_path/'unrelated'
    if condition=='no_systemd':boot.SYSTEMD.rmdir()
    if condition=='no_api_unit':boot.API_UNIT.unlink()
    if condition=='no_env':boot.ENVIRONMENT.unlink()
    assert boot.ensure_native(project)=='skipped'
    assert native.state.calls==[] and not boot.NATIVE_STATUS.exists()


@pytest.mark.parametrize('database,command',[
    ('postgresql://localhost/pc_new_aabb','upgrade'),('postgresql://remote/pengucoach','upgrade'),
    ('postgresql://localhost:5433/pengucoach','upgrade'),('postgresql://localhost/pengucoach','stamp'),
    ('postgresql://localhost/pengucoach','downgrade'),('postgresql://localhost/pengucoach',None),
])
def test_preflight_other_databases_and_nonupgrade_commands_do_not_touch_host(native,database,command):
    options=None if command is None else SimpleNamespace(cmd=(type(command,(),{'__name__':command}),))
    # A real callable's name is the relevant Alembic command identity.
    if command is not None:
        def call():pass
        call.__name__=command;options.cmd=(call,)
    assert boot.after_native_migration(boot.PROJECT,database,options)=='skipped'
    assert native.state.calls==[]


@pytest.mark.parametrize('failure',['install','health','timeout'])
def test_setup_failure_does_not_raise_into_successful_application_migration(native,failure):
    if failure=='install':native.state.returncode=1
    if failure=='health':native.state.available=False
    if failure=='timeout':native.state.timeout=True
    assert boot.after_native_migration(boot.PROJECT,'postgresql://localhost/pengucoach',upgrade())=='failed'
    public=json.loads(boot.NATIVE_STATUS.read_text())
    assert public['status']=='failed' and public['code']=='MAINTENANCE_SETUP_FAILED'
    assert 'do-not-expose' not in json.dumps(public)


def test_running_recovery_and_operation_lock_never_restart_native_agent(native):
    boot.CONFIG.write_text('{}');native.state.active=True;native.state.available=False
    assert boot.ensure_native(boot.PROJECT)=='running'
    assert all(args[0]!='bash' for args,_ in native.state.calls)
    native.state.active=False;native.state.returncode=75
    assert boot.ensure_native(boot.PROJECT)=='deferred'
    assert json.loads(boot.NATIVE_STATUS.read_text())['code']=='MAINTENANCE_BUSY'


def test_migration_success_is_preserved_even_if_setup_status_cannot_be_written(native,monkeypatch):
    monkeypatch.setattr(boot,'ensure_native',lambda _:(_ for _ in ()).throw(PermissionError('private detail')))
    assert boot.after_native_migration(boot.PROJECT,'postgresql://localhost/pengucoach',upgrade())=='failed'


@pytest.fixture
def docker_setup(tmp_path,monkeypatch):
    control=tmp_path/'control';monkeypatch.setattr(boot,'CONTROL',control)
    monkeypatch.setenv('HOSTNAME','setup-id')
    project='my-project';root='/srv/pengu coach';files=[root+'/docker-compose.yml','/etc/custom/override.yml']
    own={'Id':'setup-id','Image':'sha256:new','Config':{'Image':'my-project-maintenance-setup','Labels':{
        'com.docker.compose.project':project,'com.docker.compose.project.working_dir':root,
        'com.docker.compose.project.config_files':','.join(files)}}}
    api_info={'Mounts':[{'Destination':'/data','Name':'my-data'},{'Destination':'/run/pengucoach-maintenance','Name':'my-control'}]}
    state=SimpleNamespace(own=own,api=api_info,existing=None,calls=[],requests=[],returncode=0,available=True)
    def inspect(target):
        if target=='setup-id':return own
        if target=='api-id':return api_info
        if state.existing:return state.existing
        raise RuntimeError('not found')
    def docker(args,**kw):
        state.calls.append(args)
        if args[0]=='ps':return 'api-id'
        if args[:2]==['volume','create']:return args[-1]
        pytest.fail('unexpected command '+repr(args))
    def run(args,**kw):
        state.requests.append((args,json.loads(kw['input'])))
        return SimpleNamespace(returncode=state.returncode)
    monkeypatch.setattr(boot,'inspect',inspect);monkeypatch.setattr(boot,'docker',docker)
    monkeypatch.setattr(boot.subprocess,'run',run)
    monkeypatch.setattr(boot,'agent_available',lambda _:state.available)
    monkeypatch.setattr(boot,'wait_agent',lambda _:state.available)
    return state


def test_normal_compose_setup_derives_real_project_and_external_config_mounts(docker_setup):
    assert boot.setup_docker()=='ready'
    args,payload=docker_setup.requests[0]
    assert args[0:3]==['docker','run','--rm']
    assert payload['config']['project']=='/srv/pengu coach'
    assert payload['config']['compose_project']=='my-project'
    assert payload['state']=='my-project_maintenance_state'
    assert payload['extra']==['-v','/etc/custom/override.yml:/etc/custom/override.yml:ro']
    assert payload['data']=='my-data' and payload['socket']=='my-control'
    assert json.loads((boot.CONTROL/'setup.json').read_text())['status']=='ready'


def test_unchanged_healthy_docker_helper_is_left_running(docker_setup):
    signature=hashlib.sha256(json.dumps(['/srv/pengu coach',['/srv/pengu coach/docker-compose.yml','/etc/custom/override.yml'],'my-data','my-control']).encode()).hexdigest()
    docker_setup.existing={'State':{'Running':True},'Image':'sha256:new','Config':{'Labels':{'io.pengucoach.maintenance.config':signature}}}
    assert boot.setup_docker()=='ready'
    assert not docker_setup.requests


@pytest.mark.parametrize('code,status',[(75,'deferred'),(1,'failed')])
def test_busy_or_failed_docker_setup_has_public_state_without_exposing_data(docker_setup,code,status):
    docker_setup.returncode=code
    assert boot.setup_docker()==status
    result=json.loads((boot.CONTROL/'setup.json').read_text())
    assert result['status']==status
    assert '/srv/' not in json.dumps(result)


def test_missing_compose_labels_and_unsupported_mounts_fail_explicitly(docker_setup):
    docker_setup.own['Config']['Labels']={}
    assert boot.setup_docker()=='failed'
    assert not docker_setup.requests


@pytest.mark.parametrize('busy',[False,True])
def test_docker_worker_preserves_branch_and_backups_and_respects_operation_lock(docker_setup,tmp_path,monkeypatch,busy):
    assert boot.setup_docker()=='ready'
    args,payload=docker_setup.requests[0];program=args[-1]
    state=tmp_path/'private-state';state.mkdir();(state/'backup.key').write_text('private machine key')
    (state/'config.json').write_text('{"branch":"develop"}')
    calls=[]
    monkeypatch.setattr(subprocess,'run',lambda argv,**kw:calls.append(argv) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(payload)))
    lock=(state/'operation.lock').open('a+')
    if busy:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        program=program.replace('/state/',str(state)+'/')
        if busy:
            with pytest.raises(SystemExit) as error:exec(compile(program,'docker-setup-worker','exec'),{})
            assert error.value.code==75 and not calls
        else:
            exec(compile(program,'docker-setup-worker','exec'),{})
            config=json.loads((state/'config.json').read_text())
            assert config['branch']=='develop' and config['project']=='/srv/pengu coach'
            assert (state/'config.json').stat().st_mode&0o777==0o600
            assert calls[-1][0:3]==['docker','run','-d']
            assert '/srv/pengu coach:/srv/pengu coach' in calls[-1]
            assert '--label' in calls[-1]
        assert (state/'backup.key').read_text()=='private machine key'
    finally:lock.close()


def test_legacy_migration_bridge_runs_after_online_commit_and_not_in_offline_mode():
    # The original Alpha.72 updater is deliberately unchanged and still reaches
    # the newly fetched env.py through its existing Alembic command.
    legacy=Path('../pengucoach-alpha72/install/proxmox/pengucoach-update.sh')
    if legacy.is_file():assert '.venv/bin/alembic -c alembic.ini upgrade head' in legacy.read_text()
    tree=ast.parse(Path('db/migrations/env.py').read_text())
    online=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_migrations_online')
    calls=[n for n in online.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
    assert calls[0].value.func.attr=='run'
    assert calls[-1].value.func.id=='after_native_migration'
    offline=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_migrations_offline')
    assert 'after_native_migration' not in ast.unparse(offline)


async def test_api_reports_public_setup_failure_without_changing_application_access(tmp_path,monkeypatch):
    file=tmp_path/'setup.json';file.write_text(json.dumps({'status':'failed','deployment':'native','code':'MAINTENANCE_SETUP_FAILED','password':'never expose'}))
    original=client.Path
    monkeypatch.setattr(client,'Path',lambda value:file if str(value).endswith('maintenance-setup.json') else original(tmp_path/'absent'))
    monkeypatch.setattr(client,'request',AsyncMock(side_effect=httpx.ConnectError('offline')))
    result=await api.status(object())
    assert result['available'] is False and result['setup']['status']=='failed'
    assert result['setup']['code']=='MAINTENANCE_SETUP_FAILED'
    assert 'password' not in json.dumps(result)


def test_matching_docker_helper_recovering_a_job_is_never_restarted(docker_setup):
    signature=hashlib.sha256(json.dumps(['/srv/pengu coach',['/srv/pengu coach/docker-compose.yml','/etc/custom/override.yml'],'my-data','my-control']).encode()).hexdigest()
    docker_setup.existing={'State':{'Running':True},'Image':'sha256:new','Config':{'Labels':{'io.pengucoach.maintenance.config':signature}}}
    docker_setup.available=False
    assert boot.setup_docker()=='running'
    assert not docker_setup.requests


def test_native_retry_repairs_incomplete_virtualenv_without_reinstalling_healthy_dependencies(tmp_path):
    source=Path('install/maintenance/install.sh').read_text()
    segment=source.split('if [[ ! -x "$BASE/venv/bin/python" ]]; then',1)[1].split('\ninstall -m 0644',1)[0]
    segment='if [[ ! -x "$BASE/venv/bin/python" ]]; then'+segment
    base=tmp_path/'maintenance';binary=base/'venv/bin/python';binary.parent.mkdir(parents=True)
    ready=tmp_path/'dependencies-ready';pip_count=tmp_path/'pip-installs'
    binary.write_text('''#!/usr/bin/env bash
set -e
if [[ "$1" == -c ]]; then [[ -f "$PC_TEST_DEPS_READY" ]]; exit; fi
if [[ "$1" == -m && "$2" == ensurepip ]]; then exit 0; fi
if [[ "$1" == -m && "$2" == pip ]]; then touch "$PC_TEST_DEPS_READY"; echo install >> "$PC_TEST_PIP_COUNT"; exit 0; fi
exit 99
''');binary.chmod(0o755)
    env={**os.environ,'BASE':str(base),'PC_TEST_DEPS_READY':str(ready),'PC_TEST_PIP_COUNT':str(pip_count)}
    assert not ready.exists()
    subprocess.run(['bash','-e','-c',segment],env=env,check=True)
    assert ready.is_file() and pip_count.read_text().splitlines()==['install']
    subprocess.run(['bash','-e','-c',segment],env=env,check=True)
    assert pip_count.read_text().splitlines()==['install']
