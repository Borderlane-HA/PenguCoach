"""Real encrypted archives + filesystem transactions; service commands use a fake host."""
import io
import json
import os
import tarfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from apps.api.routers import admin_system as api
from pengucoach.auth.dependencies import admin_user
from pengucoach.maintenance import archive
from pengucoach.maintenance.drivers import Driver, read_env, write_env
from pengucoach.maintenance.engine import Engine, atomic_json, utc

PASSWORD='a strong backup password'


@pytest.fixture
def stage(tmp_path):
    path=tmp_path/'stage';path.mkdir()
    (path/'database.pgdump').write_bytes(b'PGDMP all users, prompts and sessions')
    (path/'environment.json').write_text(json.dumps({'PENGUCOACH_ENCRYPTION_KEY':Fernet.generate_key().decode()}))
    (path/'data/cache').mkdir(parents=True)
    (path/'data/cache/activity.json').write_text('{"cached":true}')
    return path


def packed(stage,tmp_path):
    path=tmp_path/'archive.tar.gz'
    archive.pack(stage,path,{'app_version':'0.1.0-alpha.73','created_at':utc(),'deployment':'native'})
    return path


def test_archive_roundtrip_and_fresh_system_key(stage,tmp_path):
    tar=packed(stage,tmp_path);encrypted=tmp_path/'portable.pcbackup'
    archive.encrypt(tar,encrypted,PASSWORD)
    assert encrypted.stat().st_mode&0o777==0o600
    assert b'PGDMP' not in encrypted.read_bytes()
    decoded=tmp_path/'decoded.tar.gz';archive.decrypt(encrypted,decoded,PASSWORD)
    manifest=archive.unpack(decoded,tmp_path/'out')
    assert manifest['app_version']=='0.1.0-alpha.73'
    for name in manifest['files']:assert (tmp_path/'out'/name).read_bytes()==(stage/name).read_bytes()
    assert read_env_file_json(tmp_path/'out/environment.json')==read_env_file_json(stage/'environment.json')


def read_env_file_json(path):return json.loads(path.read_text())


@pytest.mark.parametrize('damage',['password','truncate','tamper','trailing','header'])
def test_encryption_rejects_damage_and_removes_plaintext(tmp_path,damage):
    source=tmp_path/'plain';source.write_bytes(os.urandom(archive.CHUNK+129))
    encrypted=tmp_path/'a';archive.encrypt(source,encrypted,PASSWORD)
    data=bytearray(encrypted.read_bytes())
    if damage=='truncate':data=data[:-8]
    if damage=='tamper':data[-20]^=1
    if damage=='trailing':data.extend(b'extra')
    if damage=='header':data[:5]=b'BAD!!'
    encrypted.write_bytes(data)
    output=tmp_path/'out'
    with pytest.raises(ValueError):archive.decrypt(encrypted,output,'wrong password' if damage=='password' else PASSWORD)
    assert not output.exists()


def manipulated_tar(source,target,change):
    with tarfile.open(source,'r:gz') as src,tarfile.open(target,'w:gz') as dst:
        for member in src:
            data=src.extractfile(member).read();member,data,extra=change(member,data)
            member.size=len(data);dst.addfile(member,io.BytesIO(data))
            if extra:dst.addfile(member,io.BytesIO(data))


@pytest.mark.parametrize('damage',['traversal','absolute','symlink','duplicate','hash','runtime','environment_size','metadata'])
def test_archive_preflight_rejects_unsafe_payloads(stage,tmp_path,damage,monkeypatch):
    source=packed(stage,tmp_path);bad=tmp_path/'bad.tar.gz'
    def change(member,data):
        extra=False
        if member.name=='database.pgdump':
            if damage=='traversal':member.name='../escape'
            if damage=='absolute':member.name='/escape'
            if damage=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/etc/shadow'
            if damage=='duplicate':extra=True
            if damage=='hash':data=b'different dump'
        if member.name=='manifest.json':
            meta=json.loads(data)
            if damage=='runtime':
                meta['files']['data/backups/nested']=meta['files'].pop('data/cache/activity.json')
            if damage=='environment_size':meta['files']['environment.json']['size']=5*1024**2
            if damage=='metadata':meta['app_version']={'id':'secret'}
            data=json.dumps(meta).encode()
        if damage=='runtime' and member.name=='data/cache/activity.json':member.name='data/backups/nested'
        if damage=='environment_size' and member.name=='environment.json':data=b'x'*(5*1024**2)
        return member,data,extra
    manipulated_tar(source,bad,change)
    with pytest.raises(ValueError):archive.unpack(bad,tmp_path/'out')
    assert not (tmp_path/'escape').exists()


def test_manifest_cannot_override_backup_ids_or_local_key_mode(stage,tmp_path):
    source=packed(stage,tmp_path);bad=tmp_path/'injected.tar.gz'
    def change(member,data):
        if member.name=='manifest.json':data=json.dumps({**json.loads(data),'id':'../../escape','automatic':True,'password':'bad'}).encode()
        return member,data,False
    manipulated_tar(source,bad,change)
    result=archive.unpack(bad,tmp_path/'out')
    assert not {'id','automatic','password'}&result.keys()


class FakeHost:
    def __init__(self,config,log,shared):
        self.config,self.log,self.shared=config,log,shared
        self.root=Path(config['project']);self.env_file=Path(config['environment']);self.data=Path(config['data']);self.mode=config['deployment']
        self.managed_env=self.env_file.with_name('managed.env')
        self.link=Path(config['project']);self.releases=Path(str(self.link)+'-releases')
    # Release directories use the real link handling on the temporary filesystem.
    link_target=Driver.link_target
    prune_releases=Driver.prune_releases
    def release_layout(self):return self.mode=='native' and self.config.get('release_layout',True) is not False
    def installed_commit(self):return self.shared['head']
    def release_size(self):return 0
    def tool_versions(self):return dict(self.shared.get('tools',{}))
    def prepare_release(self,source,commit,version):
        path=self.releases/commit[:12];path.mkdir(parents=True)
        (path/'.pengucoach-release').write_text(json.dumps({'commit':commit,'version':version}))
        self.shared.setdefault('release_heads',{})[str(path)]=commit;self.shared['calls'].append('prepare_release')
        return path
    def build_release(self,release):
        assert not self.shared['paused'],'release must be built while the app runs'
        self.shared['calls'].append('build_release');self.fail('build')
    def point_link(self,release):
        heads=self.shared.setdefault('release_heads',{})
        if not self.link.is_symlink():heads[str(Driver.link_target(self))]=self.shared['head']
        Driver.point_link(self,release)
        self.shared['head']=heads.get(str(Path(release)),self.shared['head']);self.shared['calls'].append(('link',Path(release).name))
    def fail(self,point):
        if point in self.shared['fail']:
            self.shared['fail'].remove(point);raise RuntimeError('SIMULATED_'+point.upper())
    def ensure_managed(self):self.shared['calls'].append('ensure')
    def environment(self):
        values=read_env(self.env_file)
        if self.managed_env.is_file():values.update(read_env(self.managed_env))
        return values
    def version(self):return '0.1.0-alpha.73'
    def database_size(self):return 1024
    def set_maintenance(self,job_id):self.shared['calls'].append('maintenance_on')
    def clear_maintenance(self):self.shared['calls'].append('maintenance_off')
    def background_tasks(self):
        self.shared['calls'].append('tasks')
        return self.shared['tasks'].pop(0) if self.shared.get('tasks') else []
    def ensure_env_wiring(self):return False
    def host_step(self,script,source):self.shared['calls'].append(('step',Path(script).name));self.fail('step')
    def quiesce(self):self.shared['calls'].append('stop');self.shared['paused']=True
    def start(self):self.shared['calls'].append('start');self.shared['paused']=False
    def healthy(self):self.shared['calls'].append('health');self.fail('health')
    def dump(self,path):
        assert self.shared['paused'];path.write_text(json.dumps(self.shared['db']['pengucoach']))
    def prepare_database(self,path,name,encryption_key=None,migrate=True):
        self.shared['calls'].append('preflight' if migrate else 'rollback_db');self.fail('preflight' if migrate else 'rollback_db')
        self.shared['db'][name]=json.loads(path.read_text())
    def database_exists(self,name):return name in self.shared['db']
    def drop_database(self,name):self.shared['calls'].append('drop');self.shared['db'].pop(name,None)
    def swap_database(self,new,old):
        db=self.shared['db'];db[old]=db.pop('pengucoach');self.fail('between_renames');db['pengucoach']=db.pop(new)
    def rollback_database(self,old,discarded):
        db=self.shared['db']
        if old in db:db['pengucoach']=db.pop(old)
        db.pop(discarded,None)
    def fix_ownership(self):self.fail('files')
    def restore_environment(self,values):
        from pengucoach.maintenance.drivers import write_private_env
        write_private_env(self.managed_env,{'PENGUCOACH_ENCRYPTION_KEY':values['PENGUCOACH_ENCRYPTION_KEY'],'PENGUCOACH_JWT_SECRET':'rotated-after-restore'})
        self.fail('environment')
    def clear_queue(self):self.shared['calls'].append('clear_queue')
    def run(self,args,**kw):
        self.shared['calls'].append(args)
        if 'rev-parse' in args:return self.shared['head']
        if 'reset' in args:self.shared['head']=args[-1]
        return ''
    def update_source(self,source,commit):self.shared['head']=commit
    def build(self):self.shared['calls'].append('build');self.fail('build')
    def migrate(self,release=None):self.shared['db']['pengucoach']['schema']='new';self.fail('migrate')
    def images(self):return [{'tag':'api','id':'old-image'}]
    def rollback_images(self,images):self.shared['calls'].append(('rollback_images',images))


@pytest.fixture(params=['native','docker'])
def host(tmp_path,request):
    project=tmp_path/'project';project.mkdir();(project/'.git').mkdir();data=tmp_path/'data';data.mkdir()
    (data/'fit').mkdir();(data/'fit/activity.json').write_text('all cached telemetry')
    (data/'.npm').mkdir();(data/'.npm/cache-entry').write_text('build cache, never backed up')
    (data/'backups').mkdir();(data/'backups/legacy').write_text('do not recursively back up')
    (data/'celerybeat-schedule').write_text('runtime queue state')
    key=Fernet.generate_key().decode();cipher=Fernet(key.encode()).encrypt(b'all provider API credentials').decode()
    config={'state':str(tmp_path/'maintenance'),'deployment':request.param,'project':str(project),'environment':str(tmp_path/'env'),'data':str(data),'socket':str(tmp_path/'control.sock'),'repository':'https://github.com/Borderlane-HA/PenguCoach.git'}
    env={'PENGUCOACH_ENCRYPTION_KEY':key,'PENGUCOACH_JWT_SECRET':'before-jwt-with-at-least-32-characters','PENGUCOACH_DATABASE_URL':'postgresql+asyncpg://pengucoach:pw@localhost/pengucoach','PENGUCOACH_REDIS_URL':'redis://localhost/0'}
    Path(config['environment']).write_text(''.join(k+'='+v+'\n' for k,v in env.items()));Path(config['environment']).chmod(0o640)
    shared={'db':{'pengucoach':{'users':['admin','athlete'],'encrypted_credentials':cipher,'prompts':['custom'],'schema':'old'}},'fail':set(),'calls':[],'head':'a'*40,'paused':False}
    factory=lambda config,log:FakeHost(config,log,shared)
    engine=Engine(config,factory)
    return SimpleNamespace(config=config,engine=engine,factory=factory,shared=shared,data=data,env=env)


def backup(host,local=False):
    job=host.engine.submit({'operation':'backup','password':PASSWORD,'local':local},asynchronous=False)
    assert job['status']=='succeeded',job
    return job['backup']['id']


def test_backup_keeps_environment_and_existing_session_valid(host,monkeypatch):
    from pengucoach.auth import jwt

    monkeypatch.setattr(jwt.settings,'jwt_secret',host.env['PENGUCOACH_JWT_SECRET'])
    token=jwt.create_session_token('existing-admin')
    environment=Path(host.config['environment']).read_bytes()
    database=json.loads(json.dumps(host.shared['db']))
    backup(host)
    assert Path(host.config['environment']).read_bytes()==environment
    assert jwt.decode_session_token(token)=='existing-admin'
    assert host.shared['db']==database
    assert 'stop' in host.shared['calls'] and 'start' in host.shared['calls']
    assert 'clear_queue' not in host.shared['calls']


def restore(host,bid):return host.engine.submit({'operation':'restore','backup_id':bid,'password':PASSWORD,'confirmation':'RESTORE'},asynchronous=False)


def change_live(host):
    host.shared['db']['pengucoach']={'users':['new-install'],'schema':'different'}
    (host.data/'fit/activity.json').write_text('new data')
    (host.data/'user-assets').mkdir();(host.data/'user-assets/new-file').write_text('new install only')
    env={**host.env,'PENGUCOACH_ENCRYPTION_KEY':Fernet.generate_key().decode()};write_env(Path(host.config['environment']),env)
    return env


def test_full_backup_restore_preserves_all_users_keys_and_files(host):
    bid=backup(host);change_live(host)
    job=restore(host,bid)
    assert job['status']=='succeeded',job
    assert host.shared['db']['pengucoach']['users']==['admin','athlete']
    driver=host.factory(host.config,lambda _:None)
    key=driver.environment()['PENGUCOACH_ENCRYPTION_KEY']
    cipher=host.shared['db']['pengucoach']['encrypted_credentials']
    assert Fernet(key.encode()).decrypt(cipher.encode())==b'all provider API credentials'
    assert driver.environment()['PENGUCOACH_JWT_SECRET']=='rotated-after-restore'
    # The administrator's own environment file is never rewritten.
    assert read_env(host.config['environment'])['PENGUCOACH_JWT_SECRET']==host.env['PENGUCOACH_JWT_SECRET']
    assert Path(host.config['environment']).stat().st_mode&0o777==0o640
    assert driver.managed_env.stat().st_mode&0o777==0o600
    assert (host.data/'fit/activity.json').read_text()=='all cached telemetry'
    assert not (host.data/'user-assets').exists()
    assert (host.data/'.npm/cache-entry').is_file()
    assert (host.data/'backups/legacy').is_file()
    assert 'clear_queue' in host.shared['calls'] and not host.shared['paused']
    assert list(host.shared['db'])==['pengucoach']
    assert len(host.engine.backups())==2  # original portable + automatic pre-restore
    assert not list((host.engine.state/'work').iterdir())
    history=''.join(p.read_text() for p in (host.engine.state/'jobs').glob('*'))
    for secret in [PASSWORD,key,'all provider API credentials']:assert secret not in history


@pytest.mark.parametrize('failure',['preflight','between_renames','files','environment','health'])
def test_restore_failures_keep_previous_database_environment_and_files(host,failure):
    bid=backup(host);environment=change_live(host)
    before=json.loads(json.dumps(host.shared['db']['pengucoach']))
    host.shared['fail'].add(failure);job=restore(host,bid)
    assert job['status']=='failed',job
    assert not job.get('recovery_required')
    assert host.shared['db']=={'pengucoach':before}
    assert read_env(host.config['environment'])==environment
    assert not host.factory(host.config,lambda _:None).managed_env.exists()
    assert (host.data/'fit/activity.json').read_text()=='new data'
    assert (host.data/'user-assets/new-file').read_text()=='new install only'
    assert not host.shared['paused'] and not (host.data/'.maintenance-rollback').exists()
    if failure=='preflight':assert not job.get('rolled_back')
    else:assert job['rolled_back']


def test_automatic_backup_export_is_portable_to_fresh_host(host,tmp_path):
    bid=backup(host,local=True)
    job=host.engine.submit({'operation':'export','backup_id':bid,'password':PASSWORD},asynchronous=False)
    assert job['status']=='succeeded' and not job['backup']['automatic']
    exported=host.engine.state/'backups'/(job['backup']['id']+'.pcbackup')
    # Explicitly destroy the machine key: password-protected export must remain readable.
    (host.engine.state/'backup.key').write_text('another host key')
    decoded=tmp_path/'decoded';archive.decrypt(exported,decoded,PASSWORD)
    result=archive.unpack(decoded,tmp_path/'out')
    assert 'database.pgdump' in result['files']
    assert 'data/backups/legacy' not in result['files']
    assert 'data/fit/activity.json' in result['files']
    assert all('celerybeat' not in name and '.npm' not in name for name in result['files'])


def test_inspection_tracks_backup_and_wrong_password_never_stops_services(host):
    bid=backup(host);host.shared['calls'].clear()
    bad=host.engine.submit({'operation':'inspect','backup_id':bid,'password':'wrong'},asynchronous=False)
    assert bad['status']=='failed' and bad['error']=='BACKUP_PASSWORD_OR_INTEGRITY_INVALID'
    assert host.shared['calls']==[]
    good=host.engine.submit({'operation':'inspect','backup_id':bid,'password':PASSWORD},asynchronous=False)
    assert good['backup_id']==bid and good['inspection']['file_count']==3
    assert host.shared['calls']==[]


def test_operation_lock_shared_by_gui_shell_and_agent_instances(host):
    other=Engine(host.config,host.factory);host.engine.acquire()
    try:
        with pytest.raises(ValueError,match='MAINTENANCE_BUSY'):other.submit({'operation':'backup','local':True})
        with pytest.raises(ValueError,match='MAINTENANCE_BUSY'):host.engine.acquire()
    finally:host.engine.release()
    assert other.submit({'operation':'backup','local':True},asynchronous=False)['status']=='succeeded'


@pytest.mark.parametrize('failure',['build','migrate','health'])
def test_update_failure_restores_previous_revision_and_database(host,failure,tmp_path,monkeypatch):
    source=tmp_path/'trusted';source.mkdir()
    monkeypatch.setattr(host.engine,'fetch_source',lambda driver:(source,'b'*40,{'source':'branch','branch':'main'}))
    host.shared['fail'].add(failure);before=json.loads(json.dumps(host.shared['db']['pengucoach']))
    job=host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)
    assert job['status']=='failed' and job['rolled_back'] and not job.get('recovery_required'),job
    assert host.shared['head']=='a'*40 and host.shared['db']=={'pengucoach':before}
    assert not host.shared['paused']


def test_noop_update_does_not_stop_services_or_create_backup(host,monkeypatch):
    monkeypatch.setattr(host.engine,'fetch_source',lambda driver:(Path(host.config['project']),'a'*40,{'source':'branch','branch':'main'}))
    job=host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)
    assert job['status']=='succeeded' and not host.engine.backups()
    assert 'stop' not in host.shared['calls']
    assert not host.engine.lock.locked()


def test_recovery_after_kill_between_database_renames(host):
    bid=backup(host);change_live(host);driver=host.factory(host.config,lambda _:None)
    job={'id':uuid.uuid4().hex,'status':'running','created_at':utc(),'operation':'restore','prepared_database':'pc_new_123abc'}
    host.engine.save(job);work=host.engine.state/'work'/job['id'];work.mkdir()
    (work/'environment.before').write_text(json.dumps(read_env(host.config['environment'])))
    host.engine.transaction(driver,job,work,{'old_database':'pc_old_123abc','discard_database':'pc_bad_123abc'})
    host.shared['db']['pc_new_123abc']={'users':['from backup']}
    host.shared['db']['pc_old_123abc']=host.shared['db'].pop('pengucoach')
    Engine(host.config,host.factory).recover()
    assert host.shared['db']=={'pengucoach':{'users':['new-install'],'schema':'different'}}
    assert host.engine.jobs()[0]['rolled_back'] and not host.engine.jobs()[0]['recovery_required']


def test_interrupted_preflight_drops_scratch_database_without_changing_live(host):
    job={'id':uuid.uuid4().hex,'status':'running','created_at':utc(),'operation':'restore','prepared_database':'pc_new_aabb'}
    host.engine.save(job);(host.engine.state/'work'/job['id']).mkdir()
    host.shared['db']['pc_new_aabb']={'partial':'restore'}
    Engine(host.config,host.factory).recover()
    assert list(host.shared['db'])==['pengucoach']
    assert host.engine.jobs()[0]['error']=='MAINTENANCE_INTERRUPTED'


def test_committed_recovery_never_rolls_back_successful_restore(host):
    job={'id':uuid.uuid4().hex,'status':'running','created_at':utc(),'operation':'restore'}
    host.engine.save(job);work=host.engine.state/'work'/job['id'];work.mkdir()
    atomic_json(work/'transaction.json',{'old_database':'pc_old_aabb','discard_database':'pc_bad_aabb'})
    atomic_json(work/'committed.json',{'operation':'restore','old_database':'pc_old_aabb'})
    host.shared['db']['pc_old_aabb']={'before':'old'}
    (host.data/'.maintenance-rollback').mkdir()
    Engine(host.config,host.factory).recover()
    assert 'before' not in host.shared['db']['pengucoach'] and 'pc_old_aabb' not in host.shared['db']
    assert host.engine.jobs()[0]['status']=='succeeded'


def test_failed_recovery_blocks_changes_even_outside_latest_thirty_jobs(host):
    bad={'id':uuid.uuid4().hex,'status':'failed','created_at':'2000-01-01','operation':'restore','recovery_required':True}
    host.engine.save(bad)
    for _ in range(32):host.engine.save({'id':uuid.uuid4().hex,'status':'succeeded','created_at':utc()})
    assert host.engine.status()['recovery_required']
    with pytest.raises(ValueError,match='MAINTENANCE_RECOVERY_REQUIRED'):host.engine.submit({'operation':'backup','local':True})


def test_driver_protects_custom_compose_files_and_keeps_credentials_out_of_argv(tmp_path,monkeypatch):
    config={'project':str(tmp_path),'environment':str(tmp_path/'env'),'data':str(tmp_path/'data'),'deployment':'docker','compose_project':'pengucoach','compose_files':[str(tmp_path/'docker-compose.yml'),str(tmp_path/'mine.yml')],'repository':'https://github.com/Borderlane-HA/PenguCoach.git'}
    driver=Driver(config);calls=[]
    monkeypatch.setattr(driver,'run',lambda args,**kw:calls.append((args,kw)) or '')
    driver.update_source(tmp_path,'a'*40)
    clean=next(args for args,_ in calls if 'clean' in args)
    assert '.env' in clean and 'mine.yml' in clean
    monkeypatch.setattr(driver,'environment',lambda:{'PENGUCOACH_DATABASE_URL':'postgresql+asyncpg://u:secret@postgres/pengucoach','PENGUCOACH_ENCRYPTION_KEY':'private'})
    driver.prepare_database(tmp_path/'dump','pc_aabb',encryption_key='private')
    assert all('secret' not in ' '.join(args) and 'private' not in ' '.join(args) for args,_ in calls)
    migration=next((args,kw) for args,kw in calls if 'alembic' in args)
    assert migration[1]['env']['PENGUCOACH_DATABASE_URL'].endswith('/pc_aabb')


@pytest.mark.parametrize('db,redis,error',[
    ('remote','localhost','MANAGED_DATABASE_REQUIRED'),('localhost','remote','MANAGED_REDIS_REQUIRED'),
])
def test_external_infrastructure_is_rejected_before_modification(host,db,redis,error):
    driver=Driver(host.config)
    values={**host.env,'PENGUCOACH_DATABASE_URL':f'postgresql://u@{db}/pengucoach','PENGUCOACH_REDIS_URL':f'redis://{redis}/0'}
    driver.environment=lambda:values
    if host.config['deployment']=='docker':driver.mode='native'
    with pytest.raises(ValueError,match=error):driver.ensure_managed()


async def test_all_maintenance_api_routes_require_admin_and_forbid_command_injection(monkeypatch):
    app=FastAPI();app.include_router(api.router)
    async def deny():raise HTTPException(403,'ADMIN_REQUIRED')
    app.dependency_overrides[admin_user]=deny
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
        for method,path,body in [('GET','/status',None),('POST','/jobs',{'operation':'backup','password':PASSWORD}),('POST','/uploads',{'size':1}),('GET','/uploads/'+'a'*32,None),('POST','/uploads/'+'a'*32+'?offset=0',None),('POST','/uploads/'+'a'*32+'/complete',None),('GET','/backups/'+'a'*32+'/download',None),('DELETE','/backups/'+'a'*32+'?confirmation=DELETE',None)]:
            response=await client.request(method,'/admin/system'+path,json=body)
            assert response.status_code==403,(method,path,response.text)
    with pytest.raises(ValidationError):api.JobIn(operation='backup',local=True)
    with pytest.raises(ValidationError):api.JobIn(operation='update',command='rm -rf /')
    with pytest.raises(ValidationError):api.JobIn(operation='restore',backup_id='../etc')


async def test_api_bridge_role_status_busy_and_request_bounds(monkeypatch):
    app=FastAPI();app.include_router(api.router)
    app.dependency_overrides[admin_user]=lambda:SimpleNamespace(id=uuid.uuid4())
    proxy=AsyncMock(return_value={'id':'a'*32,'status':'queued'});monkeypatch.setattr(api,'proxy',proxy)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
        response=await client.post('/admin/system/jobs',json={'operation':'update','confirmation':'UPDATE'})
        assert response.status_code==202
        assert proxy.call_args.kwargs['json']['actor']
        proxy.side_effect=HTTPException(409,'MAINTENANCE_BUSY')
        response=await client.post('/admin/system/jobs',json={'operation':'backup','password':PASSWORD})
        assert response.status_code==409
        proxy.side_effect=None
        response=await client.post('/admin/system/uploads/'+'a'*32+'?offset=0',content=b'x'*(api.MAX_CHUNK+1))
        assert response.status_code==413
        assert (await client.delete('/admin/system/backups/'+'a'*32)).status_code==422
        assert (await client.post('/admin/system/uploads',json={'size':True})).status_code==422


async def test_agent_absent_is_a_setup_state(monkeypatch):
    monkeypatch.setattr(api.client,'request',AsyncMock(side_effect=httpx.ConnectError('offline')))
    assert (await api.status(object()))['available'] is False


def test_installer_embedded_python_compiles_and_original_shell_commands_remain():
    import ast
    source=Path('install/maintenance/install.sh').read_text()
    native=source.split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
    ast.parse(native)
    import re
    compose=Path('docker-compose.yml').read_text()
    for name in ['api','worker','scheduler','web']:
        block=re.search(r'^  '+name+r':\n(.*?)(?=^  [a-z][a-z-]*:|^volumes:|\Z)',compose,re.M|re.S).group(1)
        assert 'docker.sock' not in block
    assert 'maintenance-setup:' in compose
    for command in ['update','backup']:
        script=Path(f'install/proxmox/pengucoach-{command}.sh').read_text()
        assert f'pengucoach-maintenance {command} "$@"' in script
        assert 'exec /usr/local/bin/pengucoach-maintenance' in script


async def test_agent_http_upload_resume_download_and_api_streaming(host,monkeypatch):
    import http.client
    from pengucoach.maintenance.agent import Handler
    from pengucoach.maintenance import client as bridge
    bid=backup(host)
    class MemorySocket:
        def __init__(self,data):self.input=io.BytesIO(data);self.output=io.BytesIO()
        def makefile(self,*args,**kw):return self.input
        def settimeout(self,*args):pass
        def sendall(self,data):self.output.write(data)
    def respond(request):
        data=request.content
        headers=[('Host','maintenance'),('Content-Length',str(len(data))),('Connection','close')]
        raw=(request.method+' '+request.url.raw_path.decode()+' HTTP/1.0\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers)+'\r\n').encode()+data
        socket=MemorySocket(raw);Handler(socket,('local',0),SimpleNamespace(engine=host.engine))
        response=http.client.HTTPResponse(MemorySocket(socket.output.getvalue()));response.begin()
        return httpx.Response(response.status,headers=dict(response.getheaders()),content=response.read())
    original=httpx.AsyncClient
    transport=httpx.MockTransport(respond)
    monkeypatch.setattr(bridge,'client',lambda:original(transport=transport,base_url='http://maintenance',timeout=10))
    try:
        assert (await bridge.request('GET','/status'))['available']
        async with original(transport=transport,base_url='http://maintenance') as connection:
            data=(host.engine.state/'backups'/(bid+'.pcbackup')).read_bytes()
            created=(await connection.post('/uploads',json={'size':len(data)})).json();uid=created['id']
            path='/uploads/'+uid
            split=len(data)//2
            assert (await connection.post(path+'?offset=0',content=data[:split])).json()['offset']==split
            assert (await connection.get(path)).json()['offset']==split
            assert (await connection.post(path+'?offset=0',content=data[:split])).status_code==400
            assert (await connection.post(path+'/complete',json={})).status_code==400
            assert (await connection.post(path+f'?offset={split}',content=data[split:])).json()['offset']==len(data)
            assert (await connection.post(path+'/complete',json={})).json()['id']==uid
            assert (await connection.get('/backups/'+uid+'/download')).content==data
            assert (await connection.get('/backups/../../etc/shadow/download')).status_code==404
            # Admin-protected application streaming proxy transfers the identical archive.
            app=FastAPI();app.include_router(api.router)
            app.dependency_overrides[admin_user]=lambda:SimpleNamespace(id=uuid.uuid4())
            async with original(transport=httpx.ASGITransport(app=app),base_url='http://app') as web:
                download=await web.get('/admin/system/backups/'+uid+'/download')
                assert download.status_code==200 and download.content==data
                assert 'attachment' in download.headers['content-disposition']
                check=await web.post('/admin/system/jobs',json={'operation':'inspect','backup_id':uid,'password':PASSWORD})
                assert check.status_code==202 and PASSWORD not in check.text
            # Actual encrypted upload can be checked without any live app database.
            import asyncio
            for _ in range(60):
                result=next(j for j in host.engine.jobs() if j['id']==check.json()['id'])
                if result['status'] not in {'queued','running'}:break
                await asyncio.sleep(.05)
            assert result['status']=='succeeded' and result['backup_id']==uid
            assert (await connection.request('DELETE','/backups/'+uid,json={'confirmation':'DELETE'})).json()['deleted']
            assert (await connection.get('/backups/'+uid+'/download')).status_code==400
    finally:pass


def test_shell_connection_is_closed_without_requiring_context_manager(monkeypatch):
    from pengucoach.maintenance import cli
    closed=[]
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args):pass
        def getresponse(self):return SimpleNamespace(status=200,read=lambda:b'{"available":true}')
        def close(self):closed.append(True)
    monkeypatch.setattr(cli,'Connection',Connection)
    assert cli.call({'socket':'/example'},'GET','/status')['available']
    assert closed==[True]


async def test_restore_finishes_dead_jobs_but_preserves_answers_and_checkpoints(tmp_path,monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import select
    from pengucoach.db.base import Base
    from pengucoach.db.models import User,AiRun,BackgroundJob,GarminSyncRun
    from pengucoach.maintenance.app_restore import normalize_restored_jobs,RESTORED_JOB
    from apps.api.routers import jobs
    @compiles(JSONB,'sqlite')
    def sqlite_json(type_,compiler,**kw):return 'JSON'
    engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/jobs.sqlite')
    async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with factory() as db:
        user=User(username='test',email='test@host',password_hash='x');db.add(user);await db.flush()
        queued=BackgroundJob(user_id=user.id,job_type='coach_chat',status='queued')
        finished=BackgroundJob(user_id=user.id,job_type='coach_chat',status='finished',result={'content':'saved result'})
        run=AiRun(user_id=user.id,task_type='coach_chat',prompt='saved prompt',content='partial saved answer',metadata_json={'_continuation_job':{'task_id':'old'},'_resume':{'messages':['previous']},'continuation':{'available':True,'revision':3}})
        sync=GarminSyncRun(user_id=user.id,sync_type='historical',status='running')
        db.add_all([queued,finished,run,sync]);await db.commit()
        await normalize_restored_jobs(db);await db.refresh(queued);await db.refresh(finished);await db.refresh(run);await db.refresh(sync)
        assert queued.status=='cancelled' and queued.message==RESTORED_JOB
        assert finished.status=='finished' and finished.result['content']=='saved result'
        assert sync.status=='cancelled'
        assert run.content=='partial saved answer' and run.metadata_json['_resume']['messages']==['previous']
        assert run.metadata_json['continuation']=={'available':True,'revision':3}
        assert '_continuation_job' not in run.metadata_json
        monkeypatch.setattr(jobs,'AsyncResult',lambda *a,**kw:pytest.fail('restored cancelled jobs must not be polled in Redis'))
        result=await jobs.job_status(str(queued.id),user,db)
        assert result['ready'] and result['state']=='REVOKED'
    await engine.dispose()


def test_environment_roundtrip_preserves_credential_punctuation(tmp_path):
    path=tmp_path/'env';path.touch();path.chmod(0o640)
    values={'PENGUCOACH_ENCRYPTION_KEY':'key#with+punctuation=','CUSTOM_TOKEN':"space and 'quotes' # literal $HOME"}
    write_env(path,values)
    assert read_env(path)==values


def test_zip_install_can_backup_but_update_explains_missing_git(host,monkeypatch):
    (Path(host.config['project'])/'.git').rmdir()
    assert not host.engine.status()['can_update']
    assert backup(host)
    host.shared['calls'].clear()
    monkeypatch.setattr(host.engine,'fetch_source',lambda _:pytest.fail('must fail before a network request'))
    job=host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)
    assert job['status']=='failed' and job['error']=='UPDATE_REQUIRES_GIT_CHECKOUT'
    assert 'stop' not in host.shared['calls']


def test_docker_healthcheck_handles_older_standalone_hostname(tmp_path,monkeypatch):
    import subprocess
    driver=Driver({'project':str(tmp_path),'environment':str(tmp_path/'env'),'data':str(tmp_path),'deployment':'docker'})
    calls=[]
    def run(args,**kw):calls.append(args);return '200'
    monkeypatch.setattr(driver,'run',run);driver.healthy()
    script=next(args[-1] for args in calls if 'node' in args)
    for hostname,expected in [('0.0.0.0','127.0.0.1'),('old-container','old-container')]:
        value=subprocess.check_output(['node','-e','global.fetch=url=>{console.log(url);return Promise.resolve({ok:true,status:200})};'+script],env={**os.environ,'HOSTNAME':hostname},text=True)
        assert value.splitlines()==[f'http://{expected}:3000','200']
