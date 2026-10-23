"""Alpha.75 maintenance design: release tags, host steps, streaming backups,
retention, maintenance mode (drain), separate maintenance environment, recovery."""
import json
import os
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from pengucoach.maintenance import archive, versions
from pengucoach.maintenance.drivers import Driver, read_env
from pengucoach.maintenance.engine import Engine, utc

from tests.test_alpha73_maintenance import PASSWORD, backup, host  # noqa: F401  (fixture reuse)


def run_update(host, monkeypatch, tmp_path, *, steps=None, commit='b'*40):
    source=tmp_path/'release';(source/'install/host-steps').mkdir(parents=True,exist_ok=True)
    for name in steps or []:(source/'install/host-steps'/name).write_text('#!/usr/bin/env bash\n')
    monkeypatch.setattr(host.engine,'fetch_source',lambda driver:(source,commit,{'source':'release','tag':'v0.1.0-alpha.75','version':'0.1.0-alpha.75','newer':True}))
    return host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)


# --- 1. Release tags ---------------------------------------------------------------

def test_release_selection_matches_update_notice_rules():
    tags=['v0.1.0-alpha.74','v0.1.0-alpha.75','v0.1.0-alpha.9','nightly','v0.0.9']
    assert versions.newest_tag(tags,'0.1.0-alpha.74')[0]=='v0.1.0-alpha.75'
    # Stable installations never move to a pre-release.
    assert versions.newest_tag(['v0.2.0-alpha.1','v0.1.1'],'0.1.0')[0]=='v0.1.1'
    assert versions.newest_tag(['main'],'0.1.0-alpha.74')==(None,None)
    assert versions.display('0.1.0a43.post1')=='0.1.0-alpha.43.1'
    assert versions.version_key('0.1.0-alpha.43.post1')==versions.version_key('0.1.0-alpha.43.1')
    from pengucoach.common import releases
    assert releases.version_key is versions.version_key


def git(cwd,*args):
    return subprocess.run(['git','-c','user.email=t@t','-c','user.name=t','-c','init.defaultBranch=main',*args],cwd=cwd,
                          check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    repo=tmp_path/'upstream';repo.mkdir();git(repo,'init','-q')
    def commit(version,tag=None):
        (repo/'pyproject.toml').write_text(f'[project]\nname="pengucoach"\nversion="{version}"\n')
        git(repo,'add','-A');git(repo,'commit','-qm',version)
        if tag:git(repo,'tag',tag)
        return git(repo,'rev-parse','HEAD')
    return SimpleNamespace(repo=repo,commit=commit)


def test_update_installs_newest_release_tag_not_unreleased_main(upstream,tmp_path):
    c74=upstream.commit('0.1.0-alpha.74','v0.1.0-alpha.74')
    c75=upstream.commit('0.1.0-alpha.75','v0.1.0-alpha.75')
    upstream.commit('0.1.0-alpha.76')  # pushed to main, not released yet
    project=tmp_path/'project';project.mkdir()
    (project/'pyproject.toml').write_text('[project]\nname="pengucoach"\nversion="0.1.0-alpha.74"\n')
    config={'state':str(tmp_path/'state'),'deployment':'docker','project':str(project),'environment':str(tmp_path/'env'),
            'data':str(tmp_path/'data'),'repository':str(upstream.repo),'branch':'main'}
    engine=Engine(config)
    driver=Driver(config)
    source,commit,target=engine.fetch_source(driver)
    assert commit==c75 and target=={'source':'release','tag':'v0.1.0-alpha.75','version':'0.1.0-alpha.75','newer':True}
    assert 'alpha.75' in (source/'pyproject.toml').read_text()
    assert engine.update_needed(source,c74,commit,'0.1.0-alpha.74',target) is None
    assert engine.update_needed(source,c75,commit,'0.1.0-alpha.75',target)=='current'
    main=git(upstream.repo,'rev-parse','HEAD')
    # A checkout already ahead of the release (installed from main) is never moved back.
    assert engine.update_needed(source,main,commit,'0.1.0-alpha.75',target)=='contained'
    assert engine.update_needed(source,'f'*40,commit,'0.1.0-alpha.80',target)=='newer_installed'
    preview=engine.update_preview(refresh=True)
    assert preview['available'] and preview['target']=='0.1.0-alpha.75' and preview['installed']=='0.1.0-alpha.74'
    engine.config['update_source']='branch'
    _,branch_commit,branch_target=engine.fetch_source(driver)
    assert branch_commit==main and branch_target['source']=='branch'


def test_missing_release_is_an_explicit_error(upstream,tmp_path):
    upstream.commit('0.1.0-alpha.74')
    config={'state':str(tmp_path/'state'),'deployment':'docker','project':str(tmp_path),'environment':str(tmp_path/'env'),
            'data':str(tmp_path),'repository':str(upstream.repo)}
    (tmp_path/'pyproject.toml').write_text('[project]\nname="pengucoach"\nversion="0.1.0-alpha.74"\n')
    engine=Engine(config)
    with pytest.raises(ValueError,match='UPDATE_NO_RELEASE_FOUND'):engine.release_target('0.1.0-alpha.74')
    assert engine.update_preview(refresh=True)['error']=='UPDATE_NO_RELEASE_FOUND'


def test_noop_release_update_never_stops_services(host,monkeypatch,tmp_path):
    host.shared['head']='b'*40
    job=run_update(host,monkeypatch,tmp_path)
    assert job['status']=='succeeded' and job['noop']=='current'
    assert 'stop' not in host.shared['calls'] and 'maintenance_on' not in host.shared['calls']


# --- 2. Host steps -----------------------------------------------------------------

def test_host_steps_run_once_in_order_and_only_for_matching_deployment(host,monkeypatch,tmp_path):
    names=['076-later.all.sh','075-first.native.sh','075-docker-only.docker.sh','README.md','x-invalid.sh']
    job=run_update(host,monkeypatch,tmp_path,steps=names)
    assert job['status']=='succeeded',job
    ran=[call[1] for call in host.shared['calls'] if isinstance(call,tuple) and call[0]=='step']
    expected=['075-first.native.sh','076-later.all.sh'] if host.config['deployment']=='native' else ['075-docker-only.docker.sh','076-later.all.sh']
    assert ran==expected
    assert set(host.engine.applied_steps())==set(expected)
    host.shared['calls'].clear();host.shared['head']='a'*40
    assert run_update(host,monkeypatch,tmp_path,steps=names)['status']=='succeeded'
    assert not [c for c in host.shared['calls'] if isinstance(c,tuple) and c[0]=='step']


def test_failing_host_step_rolls_back_and_is_retried_next_time(host,monkeypatch,tmp_path):
    before=json.loads(json.dumps(host.shared['db']['pengucoach']))
    host.shared['fail'].add('step')
    job=run_update(host,monkeypatch,tmp_path,steps=['075-first.all.sh'])
    assert job['status']=='failed' and job['error']=='HOST_STEP_FAILED:075' and job['rolled_back']
    assert host.shared['head']=='a'*40 and host.shared['db']=={'pengucoach':before}
    assert host.engine.applied_steps()=={}
    assert run_update(host,monkeypatch,tmp_path,steps=['075-first.all.sh'])['status']=='succeeded'
    assert '075-first.all.sh' in host.engine.applied_steps()


def test_shipped_host_steps_are_valid_scripts_reading_from_the_release_checkout():
    steps=sorted(Path('install/host-steps').glob('*.sh'))
    assert steps
    from pengucoach.maintenance.engine import HOST_STEP
    for path in steps:
        assert HOST_STEP.fullmatch(path.name),path.name
        subprocess.run(['bash','-n',str(path)],check=True)
        text=path.read_text()
        assert 'set -Eeuo pipefail' in text
        assert '$PENGUCOACH_PROJECT/' not in text  # never install root files from the app-owned checkout


def test_nginx_step_adds_timeouts_and_upload_limit_once(tmp_path):
    script=Path('install/host-steps/075-nginx-proxy.native.sh').read_text()
    site=tmp_path/'site';site.write_text('server {\n    listen 80;\n    server_name _;\n    location /api/ {\n        proxy_pass http://127.0.0.1:8000;\n    }\n}\n')
    bin_dir=tmp_path/'bin';bin_dir.mkdir()
    for name in ['nginx','systemctl']:(bin_dir/name).write_text('#!/bin/sh\necho "$0 $*" >> "$CALLS"\n');(bin_dir/name).chmod(0o755)
    script=script.replace('/etc/nginx/sites-available/pengucoach',str(site))
    env={**os.environ,'PATH':str(bin_dir)+':'+os.environ['PATH'],'CALLS':str(tmp_path/'calls')}
    for _ in range(2):subprocess.run(['bash','-c',script],env=env,check=True)
    text=site.read_text()
    assert text.count('proxy_read_timeout 300s;')==1 and text.count('client_max_body_size 20m;')==1
    assert (tmp_path/'calls').read_text().count('reload nginx')==1


# --- 3. Streaming backups and the data set -----------------------------------------

def test_backup_contains_application_data_only_and_no_plaintext_copy(host,monkeypatch):
    seen=[]
    original=archive.write_backup
    def spy(target,password,metadata,entries,guard=None):
        entries=list(entries);seen.extend(name for name,_ in entries)
        work=Path(target).parent.parent/'work'
        staged=[p.relative_to(work).as_posix() for p in work.rglob('*') if p.is_file()]
        assert all(p.endswith(('database.pgdump','environment.json')) for p in staged),staged
        return original(target,password,metadata,entries,guard)
    monkeypatch.setattr(archive,'write_backup',spy)
    bid=backup(host)
    assert sorted(seen)==['data/fit/activity.json','database.pgdump','environment.json']
    manifest=host.engine.inspect_backup(bid,PASSWORD)
    assert 'data/.npm/cache-entry' not in manifest['files']


def test_alpha73_archive_with_extra_top_level_files_restores_application_data_only(host,tmp_path):
    stage=tmp_path/'legacy';(stage/'data/fit').mkdir(parents=True);(stage/'data/fit/old.fit').write_text('legacy activity')
    (stage/'data/.bashrc').write_text('service user dotfile')
    (stage/'database.pgdump').write_text(json.dumps({'users':['legacy'],'schema':'old'}))
    key=Fernet.generate_key().decode()
    (stage/'environment.json').write_text(json.dumps({'PENGUCOACH_ENCRYPTION_KEY':key}))
    packed=tmp_path/'legacy.tar.gz';archive.pack(stage,packed,{'app_version':'0.1.0-alpha.73','created_at':utc(),'deployment':'native'})
    bid=uuid.uuid4().hex;target=host.engine.state/'backups'/(bid+'.pcbackup')
    archive.encrypt(packed,target,PASSWORD)
    (target.with_suffix('.json')).write_text(json.dumps({'id':bid,'created_at':utc(),'imported':True,'automatic':False}))
    job=host.engine.submit({'operation':'restore','backup_id':bid,'password':PASSWORD,'confirmation':'RESTORE'},asynchronous=False)
    assert job['status']=='succeeded',job
    assert (host.data/'fit/old.fit').read_text()=='legacy activity'
    assert not (host.data/'.bashrc').exists()
    assert (host.data/'.npm/cache-entry').is_file()  # untouched, not application data
    assert host.factory(host.config,lambda _:None).environment()['PENGUCOACH_ENCRYPTION_KEY']==key


def test_export_reencrypts_without_writing_plaintext(host,monkeypatch):
    bid=backup(host,local=True)
    monkeypatch.setattr(archive,'read_backup',lambda *a,extract_to=None,**kw:(_ for _ in ()).throw(AssertionError('extract')) if extract_to else ORIGINAL(*a,**kw))
    job=host.engine.submit({'operation':'export','backup_id':bid,'password':PASSWORD},asynchronous=False)
    assert job['status']=='succeeded' and job['backup']['kind']=='export'
    assert ORIGINAL(host.engine.state/'backups'/(job['backup']['id']+'.pcbackup'),PASSWORD)['files']


ORIGINAL=archive.read_backup


def test_streaming_reader_rejects_damage_without_leaving_output(tmp_path):
    (tmp_path/'d.pgdump').write_bytes(os.urandom(archive.CHUNK*2+7))
    (tmp_path/'e.json').write_text(json.dumps({'PENGUCOACH_ENCRYPTION_KEY':'k'}))
    target=tmp_path/'b.pcbackup'
    archive.write_backup(target,PASSWORD,{'app_version':'0.1.0-alpha.75','created_at':utc()},
                         [('database.pgdump',tmp_path/'d.pgdump'),('environment.json',tmp_path/'e.json')])
    data=bytearray(target.read_bytes())
    for damage in ['flip','truncate','trailing']:
        bad=bytearray(data)
        if damage=='flip':bad[len(bad)//2]^=1
        if damage=='truncate':bad=bad[:-30]
        if damage=='trailing':bad.extend(b'x')
        path=tmp_path/f'{damage}.pcbackup';path.write_bytes(bad)
        with pytest.raises(ValueError):archive.read_backup(path,PASSWORD,extract_to=tmp_path/damage)
    with pytest.raises(ValueError,match='PASSWORD_OR_INTEGRITY'):archive.read_backup(target,'wrong password!')


# --- 4. Retention and space ----------------------------------------------------------

def test_safety_backups_are_rotated_but_own_and_legacy_backups_stay(host,monkeypatch,tmp_path):
    manual=backup(host);local=backup(host,local=True)
    legacy=uuid.uuid4().hex
    (host.engine.state/'backups'/(legacy+'.pcbackup')).write_bytes(b'x')
    (host.engine.state/'backups'/(legacy+'.json')).write_text(json.dumps({'id':legacy,'created_at':'2026-01-01T00:00:00+00:00','automatic':True}))
    for index in range(5):
        host.shared['head']='a'*40
        job=run_update(host,monkeypatch,tmp_path,commit=str(index)*40)
        assert job['status']=='succeeded',job
    rows=host.engine.backups()
    assert len([r for r in rows if r['kind']=='safety'])==3
    assert {manual,local,legacy}<={r['id'] for r in rows}
    assert host.engine.status()['storage']['keep_automatic']==3


def test_insufficient_space_refuses_before_any_service_stops(host,monkeypatch):
    monkeypatch.setattr(archive,'free_bytes',lambda path:10)
    job=host.engine.submit({'operation':'backup','password':PASSWORD},asynchronous=False)
    assert job['status']=='failed' and job['error']=='MAINTENANCE_DISK_SPACE'
    assert 'stop' not in host.shared['calls'] and 'maintenance_on' not in host.shared['calls']


def test_old_job_history_is_bounded(host):
    for index in range(230):host.engine.save({'id':uuid.uuid4().hex,'status':'succeeded','created_at':f'2026-01-01T00:{index//60:02d}:{index%60:02d}'})
    keep={'id':uuid.uuid4().hex,'status':'failed','recovery_required':True,'created_at':'2000-01-01'}
    host.engine.save(keep)
    host.engine.prune_jobs()
    rows=host.engine.jobs(limit=None)
    assert len(rows)==201 and any(r['id']==keep['id'] for r in rows)


# --- 5. Maintenance mode (drain) -------------------------------------------------------

def test_drain_waits_for_running_tasks_and_always_clears_maintenance_mode(host,monkeypatch):
    host.engine.config['drain_poll_seconds']=0
    host.shared['tasks']=[[{'name':'worker.tasks.ai.coach_chat','id':'1','state':'active'}],
                          [{'name':'worker.tasks.ai.coach_chat','id':'1','state':'active'}],[]]
    backup(host)
    calls=[c for c in host.shared['calls'] if isinstance(c,str)]
    assert calls.index('maintenance_on')<calls.index('stop')
    assert calls.count('tasks')==3 and calls[-1]=='maintenance_off'


def test_protected_garmin_export_blocks_maintenance_instead_of_being_killed(host):
    host.engine.config.update(drain_timeout=0,drain_poll_seconds=0)
    host.shared['tasks']=[[{'name':'worker.tasks.garmin_workouts.export_plan','id':'1','state':'active'}]]
    job=host.engine.submit({'operation':'backup','password':PASSWORD},asynchronous=False)
    assert job['status']=='failed' and job['error']=='MAINTENANCE_PROTECTED_TASK_RUNNING'
    assert 'stop' not in host.shared['calls'] and host.shared['calls'][-1]=='maintenance_off'


def test_unprotected_tasks_are_stopped_after_the_timeout(host):
    host.engine.config.update(drain_timeout=0,drain_poll_seconds=0)
    host.shared['tasks']=[[{'name':'worker.tasks.ai.coach_chat','id':'1','state':'active'}]]
    assert backup(host)


async def test_api_rejects_new_changes_during_maintenance_but_keeps_login_and_cancel(monkeypatch):
    from apps.api import main
    from pengucoach.common import maintenance_mode
    async def active():return True
    monkeypatch.setattr(maintenance_mode,'active_async',active)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://app') as client:
        response=await client.post('/api/v1/coach/jobs',json={})
        assert response.status_code==503 and response.json()['detail']=='MAINTENANCE_ACTIVE'
        assert response.headers['retry-after']=='30'
        assert (await client.get('/health')).status_code==200
    assert main._maintenance_allowed('/api/v1/auth/login')
    assert main._maintenance_allowed('/api/v1/jobs/'+'a'*36+'/cancel')
    assert main._maintenance_allowed('/api/v1/admin/system/jobs')
    assert not main._maintenance_allowed('/api/v1/settings/appearance')


async def test_maintenance_flag_fails_open_when_redis_is_unavailable(monkeypatch):
    from pengucoach.common import maintenance_mode
    class Broken:
        async def exists(self,key):raise ConnectionError('redis down')
    monkeypatch.setattr(maintenance_mode,'_async_client',Broken())
    monkeypatch.setattr(maintenance_mode,'_cache',{'at':-10.0,'value':True})
    assert await maintenance_mode.active_async() is False


async def test_scheduler_queues_no_syncs_in_maintenance_mode(monkeypatch):
    from pengucoach.common import maintenance_mode
    from worker.tasks import scheduler
    monkeypatch.setattr(maintenance_mode,'active',lambda:True)
    monkeypatch.setattr(scheduler,'SessionLocal',lambda:pytest.fail('database must not be touched'))
    assert (await scheduler._schedule())['skipped']=='maintenance'
    assert (await scheduler._schedule_sparkyfitness())['skipped']=='maintenance'


def test_driver_probes_celery_and_reports_unknown_state(tmp_path,monkeypatch):
    driver=Driver({'project':str(tmp_path),'environment':str(tmp_path/'env'),'data':str(tmp_path),'deployment':'docker'})
    monkeypatch.setattr(driver,'environment',lambda:{})
    monkeypatch.setattr(driver,'run',lambda args,**kw:'noise\n'+json.dumps({'active':{'w1':[{'name':'worker.tasks.fit.analyze_fit','id':'x'}]},'reserved':{'w1':[]}}))
    assert driver.background_tasks()==[{'name':'worker.tasks.fit.analyze_fit','id':'x','state':'active'}]
    monkeypatch.setattr(driver,'run',lambda args,**kw:(_ for _ in ()).throw(RuntimeError('MAINTENANCE_COMMAND_FAILED:docker:1')))
    assert driver.background_tasks() is None


# --- 6. Separate maintenance environment ----------------------------------------------

def test_env_reader_tolerates_hand_edited_files(tmp_path):
    path=tmp_path/'.env'
    path.write_text("# comment\nexport FOO=bar\nPENGUCOACH_X=abc  # note\nPENGUCOACH_Y=a   b\nPW=ab'c\nQ='x y' # z\nH=key#hash\n")
    assert read_env(path)=={'FOO':'bar','PENGUCOACH_X':'abc','PENGUCOACH_Y':'a   b','PW':"ab'c",'Q':'x y','H':'key#hash'}


def docker_driver(tmp_path,effective):
    (tmp_path/'.env').write_text('# my settings\nPENGUCOACH_ENCRYPTION_KEY=old-key  # keep me\n')
    driver=Driver({'project':str(tmp_path),'environment':str(tmp_path/'.env'),'data':str(tmp_path),'deployment':'docker'})
    def run(args,**kw):
        if 'config' in args:
            values=read_env(driver.managed_env) if driver.managed_env.exists() and effective else {}
            return json.dumps({'services':{s:{'environment':values} for s in ['api','worker','scheduler']}})
        return ''
    driver.run=run
    return driver


def test_restore_writes_only_the_maintenance_file_and_verifies_it_is_loaded(tmp_path):
    driver=docker_driver(tmp_path,effective=True)
    user=(tmp_path/'.env').read_text()
    driver.restore_environment({'PENGUCOACH_ENCRYPTION_KEY':'backup-key','OTHER':'ignored'})
    assert (tmp_path/'.env').read_text()==user
    managed=read_env(tmp_path/'.env.maintenance')
    assert managed['PENGUCOACH_ENCRYPTION_KEY']=='backup-key' and len(managed['PENGUCOACH_JWT_SECRET'])==96
    assert 'OTHER' not in managed and (tmp_path/'.env.maintenance').stat().st_mode&0o777==0o600


def test_restore_fails_safely_when_compose_does_not_load_the_maintenance_file(tmp_path):
    driver=docker_driver(tmp_path,effective=False)
    with pytest.raises(RuntimeError,match='MANAGED_ENV_NOT_LOADED'):driver.restore_environment({'PENGUCOACH_ENCRYPTION_KEY':'backup-key'})


def test_native_dropins_are_written_once_and_build_tools_get_their_own_home(tmp_path,monkeypatch):
    config={'project':str(tmp_path),'environment':str(tmp_path/'pengucoach.env'),'data':str(tmp_path/'data'),'deployment':'native',
            'systemd_dir':str(tmp_path/'systemd'),'build_home':str(tmp_path/'cache')}
    driver=Driver(config);calls=[]
    monkeypatch.setattr(driver,'build_home',lambda:tmp_path/'cache')
    monkeypatch.setattr('pengucoach.maintenance.drivers.subprocess.run',lambda command,**kw:calls.append(command) or SimpleNamespace(returncode=0))
    assert driver.ensure_env_wiring() and not driver.ensure_env_wiring()
    for service in ['api','worker','scheduler']:
        text=(tmp_path/f'systemd/pengucoach-{service}.service.d/10-pengucoach-maintenance-env.conf').read_text()
        assert text==f'[Service]\nEnvironmentFile=-{tmp_path}/pengucoach.managed.env\n'
    assert sum(1 for c in calls if c==['systemctl','daemon-reload'])==1
    driver.run(['npm','install'],target=True)
    command=calls[-1]
    assert command[:4]==['runuser','-u','pengucoach','--'] and 'HOME='+str(tmp_path/'cache') in command
    assert 'npm_config_cache='+str(tmp_path/'cache/.npm') in command and command[-2:]==['npm','install']


def test_update_no_longer_rewrites_any_environment_file(host,monkeypatch,tmp_path):
    before=Path(host.config['environment']).read_bytes()
    assert run_update(host,monkeypatch,tmp_path)['status']=='succeeded'
    assert Path(host.config['environment']).read_bytes()==before


# --- 7. Recovery from the web interface and small fixes --------------------------------

def test_recovery_job_clears_a_block_without_journal_once_services_are_healthy(host):
    stuck={'id':uuid.uuid4().hex,'status':'failed','created_at':utc(),'operation':'update','recovery_required':True}
    host.engine.save(stuck)
    with pytest.raises(ValueError,match='MAINTENANCE_RECOVERY_REQUIRED'):host.engine.submit({'operation':'backup','local':True})
    with pytest.raises(ValueError,match='CONFIRMATION_REQUIRED'):host.engine.submit({'operation':'recover'})
    job=host.engine.submit({'operation':'recover','confirmation':'RECOVER'},asynchronous=False)
    assert job['status']=='succeeded'
    row=next(r for r in host.engine.jobs(limit=None) if r['id']==stuck['id'])
    assert not row['recovery_required'] and row['recovery_note']=='NO_JOURNAL_SERVICES_HEALTHY'
    assert backup(host,local=True)


def test_recovery_keeps_block_when_application_stays_unhealthy(host):
    stuck={'id':uuid.uuid4().hex,'status':'failed','created_at':utc(),'operation':'update','recovery_required':True}
    host.engine.save(stuck);host.shared['fail'].add('health')
    host.engine.submit({'operation':'recover','confirmation':'RECOVER'},asynchronous=False)
    assert host.engine.status()['recovery_required']


def test_shell_reports_busy_agent_readably(monkeypatch,tmp_path,capsys):
    from pengucoach.maintenance import cli
    (tmp_path/'config.json').write_text(json.dumps({'socket':'/x','state':str(tmp_path/'state')}))
    monkeypatch.setattr(cli.os,'geteuid',lambda:0)
    monkeypatch.setattr(cli,'call',lambda *a:(_ for _ in ()).throw(RuntimeError('MAINTENANCE_BUSY')))
    monkeypatch.setattr('sys.argv',['pengucoach-maintenance','backup','--config',str(tmp_path/'config.json')])
    with pytest.raises(SystemExit) as error:cli.main()
    assert str(error.value)=='[PenguCoach] MAINTENANCE_BUSY'


def test_shell_fallback_never_exits_the_process_after_an_update(host,monkeypatch,tmp_path):
    host.engine.allow_restart=False;host.engine.config['restart_after_update']=True
    host.engine.config['program']=str(tmp_path/'program');(tmp_path/'program').mkdir()
    monkeypatch.setattr(os,'_exit',lambda code:pytest.fail('must not exit'))
    source=tmp_path/'release';(source/'pengucoach/maintenance').mkdir(parents=True);(source/'pengucoach/maintenance/engine.py').write_text('# new')
    monkeypatch.setattr(host.engine,'fetch_source',lambda driver:(source,'c'*40,{'source':'release','version':'0.1.0-alpha.75','tag':'v0.1.0-alpha.75','newer':True}))
    assert host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)['status']=='succeeded'
    assert (tmp_path/'program/engine.py').read_text()=='# new'


def test_deployment_files_wire_the_maintenance_environment_and_lock_file():
    compose=Path('docker-compose.yml').read_text()
    assert compose.count('path: .env.maintenance')==3 and compose.count('required: false')==3
    installer=Path('install/proxmox/install-app.sh').read_text()
    assert '10-pengucoach-maintenance-env.conf' in installer and 'pengucoach.managed.env' in installer
    assert '/var/cache/pengucoach-build' in installer
    gitignore=Path('.gitignore').read_text().splitlines()
    assert 'apps/web/package-lock.json' not in gitignore and '.env.maintenance' in gitignore
    assert 'package-lock.json' in Path('apps/web/Dockerfile').read_text()
