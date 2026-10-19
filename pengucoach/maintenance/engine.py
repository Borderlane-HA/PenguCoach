"""Persistent, single-operation host maintenance with recoverable transactions."""
import fcntl
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import archive
from .drivers import Driver, read_env, write_env


def utc():return datetime.now(timezone.utc).isoformat()
def identifier(value):
    value = str(value)
    if not re.fullmatch(r'[a-f0-9]{32}',value):raise ValueError('INVALID_ID')
    return value


def sync_directory(path):
    fd = os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic_json(path, value):
    temporary = Path(str(path)+'.new')
    with temporary.open('w') as out:
        os.chmod(temporary,0o600)
        json.dump(value,out,ensure_ascii=False)
        out.flush();os.fsync(out.fileno())
    temporary.replace(path)
    sync_directory(Path(path).parent)


def copy_data(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    for root, dirs, files in os.walk(source):
        relative = Path(root).relative_to(source)
        if relative == Path('.'):
            dirs[:] = [name for name in dirs if name not in archive.EXCLUDED]
            files = [name for name in files if name not in archive.EXCLUDED]
        for name in dirs:
            if (Path(root)/name).is_symlink():raise ValueError('BACKUP_SYMLINK_NOT_SUPPORTED')
        for name in files:
            path = Path(root)/name
            if path.is_symlink() or not path.is_file():raise ValueError('BACKUP_SPECIAL_FILE_NOT_SUPPORTED')
            destination = target/relative/name
            destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as src, destination.open('xb') as dst:
                os.chmod(destination,0o600)
                shutil.copyfileobj(src,dst,archive.CHUNK)


class Engine:
    def __init__(self, config, driver_factory=Driver):
        self.config = config
        self.state = Path(config['state'])
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.state,0o700)
        for name in ['jobs','backups','work','uploads']:(self.state/name).mkdir(exist_ok=True,mode=0o700)
        self.driver_factory = driver_factory
        self.lock = threading.Lock()
        self._lock_file = None
        key = self.state/'backup.key'
        if not key.exists():
            fd = os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as out:out.write(secrets.token_urlsafe(48))

    def machine_key(self):return (self.state/'backup.key').read_text()

    def jobs(self, limit=30):
        result = []
        for path in sorted((self.state/'jobs').glob('*.json'),reverse=True):
            try:result.append(json.loads(path.read_text()))
            except (OSError,ValueError):pass
        return sorted(result,key=lambda x:x.get('created_at',''),reverse=True)[:limit] if limit else result

    def backups(self):
        result = []
        for path in (self.state/'backups').glob('*.json'):
            try:
                row = json.loads(path.read_text())
                payload = self.state/'backups'/(identifier(row['id'])+'.pcbackup')
                if payload.is_file():result.append({**row,'bytes':payload.stat().st_size})
            except (OSError,ValueError,KeyError):pass
        return sorted(result,key=lambda x:x['created_at'],reverse=True)

    def status(self):
        return {'available':True,'protocol':1,'deployment':self.config['deployment'],
                'jobs':self.jobs(),'backups':self.backups(),'max_upload_bytes':archive.MAX_BYTES,
                'recovery_required':any(j.get('recovery_required') for j in self.jobs(limit=None)),
                'can_update':(Path(self.config['project'])/'.git').exists()}

    def driver(self, job=None):
        def log(message):
            if job:
                job['message'] = str(message)[:200]
                job['events'] = [*job.get('events',[]),{'at':utc(),'message':str(message)[:200]}][-100:]
                self.save(job)
        return self.driver_factory(self.config,log)

    def save(self, job):atomic_json(self.state/'jobs'/(job['id']+'.json'),job)

    def acquire(self):
        if not self.lock.acquire(blocking=False):raise ValueError('MAINTENANCE_BUSY')
        try:
            self._lock_file = open(self.state/'operation.lock','a+')
            fcntl.flock(self._lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            if self._lock_file:self._lock_file.close()
            self._lock_file = None;self.lock.release()
            raise ValueError('MAINTENANCE_BUSY') from None

    def release(self):
        if self._lock_file:self._lock_file.close();self._lock_file = None
        self.lock.release()

    def submit(self, payload, *, asynchronous=True):
        operation = payload.get('operation')
        if operation not in {'backup','update','inspect','restore','export'}:raise ValueError('OPERATION_INVALID')
        if operation in {'update','restore'} and payload.get('confirmation') != operation.upper():raise ValueError('CONFIRMATION_REQUIRED')
        if operation in {'restore','inspect','export'}:identifier(payload.get('backup_id'))
        password = str(payload.get('password') or '')
        if len(password) > 1024:raise ValueError('BACKUP_PASSWORD_INVALID')
        if operation in {'backup','export'} and not payload.get('local') and len(password) < 12:raise ValueError('BACKUP_PASSWORD_TOO_SHORT')
        if operation in {'update','restore','backup'} and any(j.get('recovery_required') for j in self.jobs(limit=None)):raise ValueError('MAINTENANCE_RECOVERY_REQUIRED')
        self.acquire()
        job = {'id':uuid.uuid4().hex,'operation':operation,'status':'queued','created_at':utc(),
               'actor':str(payload.get('actor') or 'shell')[:100],'message':'Auftrag angenommen','events':[]}
        if payload.get('backup_id'):job['backup_id']=identifier(payload['backup_id'])
        try:
            self.save(job)
            accepted = dict(job)
            if asynchronous:threading.Thread(target=self.execute,args=(job,dict(payload)),daemon=True).start()
            else:self.execute(job,dict(payload))
            return accepted if asynchronous else job
        except BaseException:
            if self.lock.locked():self.release()
            raise

    def snapshot(self, driver, stage):
        stage.mkdir(parents=True,exist_ok=True,mode=0o700)
        driver.log('Datenbank wird gesichert')
        driver.dump(stage/'database.pgdump')
        (stage/'environment.json').write_text(json.dumps(driver.environment()))
        os.chmod(stage/'environment.json',0o600)
        driver.log('Dateien und gespeicherte Daten werden gesichert')
        copy_data(driver.data,stage/'data')
        return {'app_version':driver.version(),'created_at':utc(),'deployment':driver.mode}

    def store_backup(self, stage, metadata, password, automatic=False):
        bid = uuid.uuid4().hex
        compressed = stage.parent/(bid+'.tar.gz')
        manifest = archive.pack(stage,compressed,metadata)
        target = self.state/'backups'/(bid+'.pcbackup')
        staging = target.with_suffix('.partial')
        try:
            archive.encrypt(compressed,staging,password)
            staging.replace(target)
            row = {k:v for k,v in manifest.items() if k != 'files'}
            row.update(id=bid,automatic=automatic)
            atomic_json(target.with_suffix('.json'),row)
            return row
        finally:
            compressed.unlink(missing_ok=True);staging.unlink(missing_ok=True)

    def source_backup(self, bid):
        bid = identifier(bid)
        meta = self.state/'backups'/(bid+'.json')
        if not meta.is_file():raise ValueError('BACKUP_NOT_FOUND')
        return self.state/'backups'/(bid+'.pcbackup'),json.loads(meta.read_text())

    def decode(self, bid, password, work):
        path, info = self.source_backup(bid)
        compressed = work/'input.tar.gz'
        archive.decrypt(path,compressed,self.machine_key() if info.get('automatic') else password)
        stage = work/'input'
        metadata = archive.unpack(compressed,stage)
        atomic_json(path.with_suffix('.json'),{**info,**{k:v for k,v in metadata.items() if k!='files'},'verified':True})
        compressed.unlink()
        return stage,metadata

    def fetch_source(self, driver):
        source = self.state/'source'
        if not source.exists():
            driver.run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout',self.config['repository'],str(source)],timeout=180)
        # Root owns this repository. Never use application-controlled Git config.
        import subprocess
        base = ['git','-C',str(source),'-c','core.hooksPath=/dev/null']
        for args in [['fetch','origin',self.config.get('branch','main')],['checkout','--force','FETCH_HEAD']]:
            result = subprocess.run([*base,*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
            if result.returncode:raise RuntimeError('UPDATE_FETCH_FAILED')
        commit = subprocess.check_output([*base,'rev-parse','HEAD'],text=True).strip()
        if not re.fullmatch('[a-f0-9]{40,64}',commit):raise ValueError('UPDATE_REVISION_INVALID')
        return source,commit

    def swap_data(self, driver, stage, work):
        journal = driver.data/'.maintenance-rollback'
        journal.mkdir(mode=0o700,exist_ok=False)
        atomic_json(work/'data-journal.json',{'directory':str(journal),'moved':[],'installed':[]})
        state = json.loads((work/'data-journal.json').read_text())
        for path in list(driver.data.iterdir()):
            if path.name in archive.EXCLUDED:continue
            if path.is_symlink():raise ValueError('RESTORE_TARGET_SYMLINK')
            state['moved'].append(path.name);atomic_json(work/'data-journal.json',state)
            path.rename(journal/path.name)
        incoming = stage/'data'
        if incoming.exists():
            for path in incoming.iterdir():
                state['installed'].append(path.name);atomic_json(work/'data-journal.json',state)
                destination = driver.data/path.name
                if path.is_dir():shutil.copytree(path,destination)
                else:shutil.copy2(path,destination)
        driver.fix_ownership()

    def rollback_data(self, driver, work):
        entry = work/'data-journal.json'
        if not entry.exists():return
        state = json.loads(entry.read_text())
        journal = driver.data/'.maintenance-rollback'
        for name in state['installed']:
            target = driver.data/name
            if target.is_dir():shutil.rmtree(target)
            else:target.unlink(missing_ok=True)
        for name in state['moved']:
            original = journal/name
            if original.exists():original.rename(driver.data/name)
        if journal.exists():shutil.rmtree(journal)
        entry.unlink()

    def transaction(self, driver, job, work, values):
        atomic_json(work/'transaction.json',values)
        job['transaction'] = True;self.save(job)

    def rollback(self, driver, work, job):
        entry = work/'transaction.json'
        if not entry.exists():return
        state = json.loads(entry.read_text())
        driver.log('Vorheriger Zustand wird wiederhergestellt')
        driver.quiesce()
        if state.get('old_commit'):
            if driver.mode == 'native':driver.run(['systemctl','stop','pengucoach-web'])
            driver.run(['git','-c','core.hooksPath=/dev/null','reset','--hard',state['old_commit']],target=True)
            if driver.mode == 'docker':driver.rollback_images(state.get('images',[]))
            else:driver.build()
        if state.get('old_database'):
            driver.rollback_database(state['old_database'],state['discard_database'])
        elif state.get('database_may_have_changed'):
            name, old = 'pc_rb_'+job['id'][:16], 'pc_drop_'+job['id'][:16]
            if not state.get('rollback_database_ready'):
                if driver.database_exists(name):driver.drop_database(name)
                driver.prepare_database(work/'safety/database.pgdump',name,migrate=False)
                state['rollback_database_ready']=True;atomic_json(entry,state)
            # Reuse the rename recovery path: it handles a crash between either rename.
            driver.rollback_database(name,old)
        self.rollback_data(driver,work)
        if (work/'environment.before').exists():
            write_env(driver.env_file,json.loads((work/'environment.before').read_text()))
        driver.start();driver.healthy()
        entry.unlink()
        job['rolled_back'] = True;self.save(job)

    def execute(self, job, payload):
        work = self.state/'work'/job['id'];work.mkdir(mode=0o700,exist_ok=True)
        driver = self.driver(job)
        restart_agent = False
        try:
            job['status']='running';self.save(job)
            operation = job['operation']
            password = str(payload.get('password') or '')
            if operation in {'inspect','export','restore'}:
                driver.log('Sicherung wird entschlüsselt und vollständig geprüft')
                stage, metadata = self.decode(payload['backup_id'],password,work)
                if operation == 'inspect':
                    job['inspection'] = {k:v for k,v in metadata.items() if k!='files'}
                    job['inspection']['file_count'] = len(metadata['files'])
                elif operation == 'export':
                    job['backup'] = self.store_backup(stage,{k:v for k,v in metadata.items() if k not in {'files','format'}},password)
            if operation in {'backup','update','restore'}:
                driver.ensure_managed()
                source = commit = None
                if operation == 'update':
                    if not (Path(self.config['project'])/'.git').exists():raise ValueError('UPDATE_REQUIRES_GIT_CHECKOUT')
                    driver.log('Neue Programmversion wird abgerufen')
                    source,commit = self.fetch_source(driver)
                    previous = driver.run(['git','rev-parse','HEAD'],target=True,quiet=True)
                    if previous == commit:
                        job.update(status='succeeded',message='Bereits auf dem aktuellen Stand',finished_at=utc());self.save(job);return
                if operation == 'restore':
                    # Fully restore/migrate a scratch DB before touching the live database.
                    temporary = 'pc_new_'+job['id'][:16]
                    env = json.loads((stage/'environment.json').read_text())
                    job['prepared_database']=temporary;self.save(job)
                    driver.prepare_database(stage/'database.pgdump',temporary,env.get('PENGUCOACH_ENCRYPTION_KEY'))
                driver.log('Dienste werden für eine konsistente Sicherung angehalten')
                try:
                    driver.quiesce()
                    before = self.snapshot(driver,work/'safety')
                except BaseException:
                    driver.start()
                    raise
                try:
                    automatic = operation != 'backup' or bool(payload.get('local'))
                    backup = self.store_backup(work/'safety',before,self.machine_key() if automatic else password,automatic)
                    job['backup']=backup;self.save(job)
                    if operation == 'update':
                        driver.log('Programm und Abhängigkeiten werden aktualisiert')
                        (work/'environment.before').write_text(json.dumps(driver.environment()))
                        self.transaction(driver,job,work,{'old_commit':previous,'images':driver.images(),'database_may_have_changed':True})
                        if driver.mode == 'native':driver.run(['systemctl','stop','pengucoach-web'])
                        driver.update_source(source,commit)
                        driver.build();driver.migrate()
                        values = read_env(driver.env_file);values['PENGUCOACH_APP_VERSION']=driver.version();write_env(driver.env_file,values)
                    elif operation == 'restore':
                        (work/'environment.before').write_text(json.dumps(driver.environment()))
                        old = 'pc_old_'+job['id'][:16]
                        self.transaction(driver,job,work,{'old_database':old,'discard_database':'pc_bad_'+job['id'][:16]})
                        driver.swap_database(temporary,old)
                        self.swap_data(driver,stage,work)
                        driver.restore_environment(env)
                        driver.clear_queue()
                except BaseException:
                    if (work/'transaction.json').exists() and not (work/'committed.json').exists():self.rollback(driver,work,job)
                    else:driver.start()
                    raise
                driver.log('Dienste starten; Erreichbarkeit wird geprüft')
                driver.start();driver.healthy()
                # Persist commit before deleting the rollback journal. Recovery then only cleans up.
                atomic_json(work/'committed.json',{'operation':operation,'old_database':old if operation=='restore' else None})
                (work/'transaction.json').unlink(missing_ok=True);sync_directory(work)
                shutil.rmtree(driver.data/'.maintenance-rollback',ignore_errors=True)
                if operation == 'restore':
                    try:driver.drop_database(old)
                    except Exception:job.update(cleanup_pending=True,cleanup_database=old)
                if operation == 'update':
                    # Update agent code only from the root-owned, fixed upstream checkout.
                    program = self.config.get('program')
                    if program and (source/'pengucoach/maintenance').is_dir():
                        try:
                            for path in (source/'pengucoach/maintenance').glob('*.py'):
                                if path.is_symlink():raise ValueError('UPDATE_AGENT_SYMLINK')
                                target=Path(program)/path.name
                                temporary=target.with_suffix('.new')
                                shutil.copyfile(path,temporary);temporary.replace(target)
                            restart_agent = True
                        except Exception:job['agent_refresh_required']=True
            job['status']='succeeded';job['message']='Abgeschlossen';job['finished_at']=utc();self.save(job)
        except BaseException as exc:
            try:
                if (work/'transaction.json').exists() and not (work/'committed.json').exists():self.rollback(driver,work,job)
            except BaseException:
                job['recovery_required']=True
            job.update(status='failed',finished_at=utc(),error=str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]*(?::[A-Za-z0-9_.-]+)*',str(exc)) else type(exc).__name__)
            # Only fixed codes or exception type are exposed, never raw subprocess output.
            if len(job['error'])>150 or not re.fullmatch(r'[A-Z0-9_:a-z.-]+',job['error']):job['error']='MAINTENANCE_FAILED'
            self.save(job)
        finally:
            payload.clear()  # passwords are never persisted in operation history.
            if not job.get('recovery_required'):
                if job.get('prepared_database'):
                    try:
                        if driver.database_exists(job['prepared_database']):driver.drop_database(job['prepared_database'])
                    except Exception:pass
                if not job.get('cleanup_pending'):shutil.rmtree(work,ignore_errors=True)
            self.release()
        if restart_agent and self.config.get('restart_after_update'):
            # systemd Restart=always / Docker unless-stopped starts the new code.
            os._exit(0)

    def recover(self):
        self.acquire()
        try:
            for partial in (self.state/'backups').glob('*.partial'):partial.unlink(missing_ok=True)
            for row in self.jobs(limit=None):
                if row.get('status') in {'queued','running'} and not (self.state/'work'/row['id']).exists():
                    row.update(status='failed',error='MAINTENANCE_INTERRUPTED',finished_at=utc());self.save(row)
            for work in (self.state/'work').iterdir():
                path = self.state/'jobs'/(work.name+'.json')
                if not path.exists():continue
                job = json.loads(path.read_text())
                if job.get('status') not in {'queued','running'} and not job.get('recovery_required') and not (work/'committed.json').exists():continue
                try:
                    driver = self.driver(job)
                    if (work/'committed.json').exists():
                        committed=json.loads((work/'committed.json').read_text())
                        if committed.get('old_database') and driver.database_exists(committed['old_database']):
                            driver.drop_database(committed['old_database'])
                        shutil.rmtree(driver.data/'.maintenance-rollback',ignore_errors=True)
                        job.update(status='succeeded',message='Abgeschlossen',finished_at=utc(),recovery_required=False,cleanup_pending=False)
                    else:
                        if (work/'transaction.json').exists():self.rollback(driver,work,job)
                        else:driver.start()
                        job.update(status='failed',error='MAINTENANCE_INTERRUPTED',finished_at=utc(),recovery_required=False)
                    if job.get('prepared_database') and driver.database_exists(job['prepared_database']):
                        driver.drop_database(job['prepared_database'])
                    shutil.rmtree(work)
                except Exception:job.update(status='failed',error='MAINTENANCE_RECOVERY_REQUIRED',recovery_required=True)
                self.save(job)
        finally:self.release()
