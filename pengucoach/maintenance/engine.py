"""Persistent, single-operation host maintenance with recoverable transactions."""
import errno
import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import archive
from .drivers import RELEASE_MARKER, Driver, write_env
from .versions import display, newest_tag, version_key


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


REQUIREMENTS = 'install/release-requirements.json'
REQUIREMENT_ERRORS = {'upgrade_path':'UPDATE_REQUIRES_INTERMEDIATE','docker_compose':'DOCKER_COMPOSE_TOO_OLD',
                      'python':'PYTHON_TOO_OLD','node':'NODE_TOO_OLD'}


def _numbers(value):
    return tuple(int(x) for x in re.findall(r'\d+',str(value))[:3]) or (0,)


OPERATIONS = {'backup','update','inspect','restore','export','recover'}
CONFIRMED = {'update','restore','recover'}
# Interrupting these would leave half-written workouts in the user's Garmin account.
PROTECTED_TASKS = ('worker.tasks.garmin_workouts.',)
HOST_STEP = re.compile(r'(\d{3})-[a-z0-9][a-z0-9-]*\.(native|docker|all)\.sh')
NOOP = {'current':'Bereits auf dem aktuellen Stand',
        'newer_installed':'Die installierte Version ist neuer als das letzte Release',
        'contained':'Der installierte Stand enthält das letzte Release bereits'}


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
        self._preview = (0.0, None)
        self._preview_lock = threading.Lock()
        # The shell fallback runs operations in-process and must not exit itself.
        self.allow_restart = True
        key = self.state/'backup.key'
        if not key.exists():
            fd = os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as out:out.write(secrets.token_urlsafe(48))

    # --- Settings ------------------------------------------------------------

    @property
    def keep_automatic(self):return max(1,int(self.config.get('keep_automatic_backups',3)))
    @property
    def min_free(self):return max(0,int(self.config.get('min_free_bytes',1024**3)))
    @property
    def update_mode(self):return 'branch' if self.config.get('update_source') == 'branch' else 'release'

    def machine_key(self):return (self.state/'backup.key').read_text()

    # --- State -----------------------------------------------------------------

    def jobs(self, limit=30):
        result = []
        for path in sorted((self.state/'jobs').glob('*.json'),reverse=True):
            try:result.append(json.loads(path.read_text()))
            except (OSError,ValueError):pass
        result = sorted(result,key=lambda x:x.get('created_at',''),reverse=True)
        return result[:limit] if limit else result

    def backups(self):
        result = []
        for path in (self.state/'backups').glob('*.json'):
            try:
                row = json.loads(path.read_text())
                payload = self.state/'backups'/(identifier(row['id'])+'.pcbackup')
                if payload.is_file():
                    kind = row.get('kind') or ('imported' if row.get('imported') else 'legacy' if row.get('automatic') else 'manual')
                    result.append({**row,'kind':kind,'bytes':payload.stat().st_size})
            except (OSError,ValueError,KeyError):pass
        return sorted(result,key=lambda x:x['created_at'],reverse=True)

    def storage(self, backups=None):
        rows = self.backups() if backups is None else backups
        return {'backups_bytes':sum(r['bytes'] for r in rows),'free_bytes':archive.free_bytes(self.state),
                'keep_automatic':self.keep_automatic,'min_free_bytes':self.min_free}

    def status(self):
        jobs = self.jobs(limit=None)
        backups = self.backups()
        return {'available':True,'protocol':2,'deployment':self.config['deployment'],
                'jobs':jobs[:30],'backups':backups,'max_upload_bytes':archive.MAX_BYTES,
                'recovery_required':any(j.get('recovery_required') for j in jobs),
                'can_update':self.updatable(),
                'release_layout':self.config['deployment'] == 'native' and self.config.get('release_layout',True) is not False,
                'update_source':self.update_mode,'storage':self.storage(backups)}

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

    def prune_jobs(self, keep=200):
        rows = self.jobs(limit=None)
        for row in rows[keep:]:
            if row.get('recovery_required') or row.get('status') in {'queued','running'}:continue
            if (self.state/'work'/str(row.get('id'))).exists():continue
            try:(self.state/'jobs'/(identifier(row['id'])+'.json')).unlink(missing_ok=True)
            except (ValueError,KeyError):pass

    def prune_backups(self, protect=()):
        """Keep the newest safety backups; manual, shell, imported and exported backups stay."""
        safety = [r for r in self.backups() if r.get('kind') == 'safety']
        removed = []
        for row in safety[self.keep_automatic:]:
            if row['id'] in protect:continue
            for suffix in ('.pcbackup','.json'):(self.state/'backups'/(row['id']+suffix)).unlink(missing_ok=True)
            removed.append(row['id'])
        return removed

    # --- Submission ------------------------------------------------------------

    def submit(self, payload, *, asynchronous=True):
        operation = payload.get('operation')
        if operation not in OPERATIONS:raise ValueError('OPERATION_INVALID')
        if operation in CONFIRMED and payload.get('confirmation') != operation.upper():raise ValueError('CONFIRMATION_REQUIRED')
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

    # --- Backups -----------------------------------------------------------------

    def check_space(self, driver, extra=0):
        """Refuse before stopping anything when the safety backup would not fit."""
        estimate = driver.database_size() + extra
        for _, path in archive.data_entries(driver.data):
            try:estimate += path.stat().st_size
            except OSError:pass
        if archive.free_bytes(self.state) < estimate + self.min_free:raise ValueError('MAINTENANCE_DISK_SPACE')
        return estimate

    def snapshot(self, driver, stage):
        stage.mkdir(parents=True,exist_ok=True,mode=0o700)
        driver.log('Datenbank wird gesichert')
        driver.dump(stage/'database.pgdump')
        (stage/'environment.json').write_text(json.dumps(driver.environment()))
        os.chmod(stage/'environment.json',0o600)
        return {'app_version':driver.version(),'created_at':utc(),'deployment':driver.mode}

    def _row(self, bid, target, manifest, kind):
        row = {k:v for k,v in manifest.items() if k != 'files'}
        row.update(id=bid,automatic=kind in {'safety','local'},kind=kind,file_count=len(manifest.get('files',{})))
        atomic_json(target.with_suffix('.json'),row)
        return row

    def store_backup(self, driver, stage, metadata, password, kind):
        bid = uuid.uuid4().hex
        target = self.state/'backups'/(bid+'.pcbackup')
        staging = target.with_suffix('.partial')
        driver.log('Datenbank, Einstellungen und gespeicherte Dateien werden verschlüsselt gesichert')
        entries = [('database.pgdump',stage/'database.pgdump'),('environment.json',stage/'environment.json'),
                   *archive.data_entries(driver.data)]
        try:
            manifest = archive.write_backup(staging,password,metadata,entries,archive.space_guard(self.state,self.min_free//4))
            staging.replace(target)
            return self._row(bid,target,manifest,kind)
        finally:
            staging.unlink(missing_ok=True)

    def source_backup(self, bid):
        bid = identifier(bid)
        meta = self.state/'backups'/(bid+'.json')
        if not meta.is_file():raise ValueError('BACKUP_NOT_FOUND')
        return self.state/'backups'/(bid+'.pcbackup'),json.loads(meta.read_text())

    def _source_password(self, info, password):
        return self.machine_key() if info.get('automatic') else password

    def _verified(self, path, info, manifest):
        atomic_json(path.with_suffix('.json'),{**info,**{k:v for k,v in manifest.items() if k!='files'},
                                                'file_count':len(manifest.get('files',{})),'verified':True})

    def inspect_backup(self, bid, password):
        path, info = self.source_backup(bid)
        manifest = archive.read_backup(path,self._source_password(info,password))
        self._verified(path,info,manifest)
        return manifest

    def decode(self, bid, password, work):
        path, info = self.source_backup(bid)
        stage = work/'input'
        if archive.free_bytes(self.state) < path.stat().st_size + self.min_free:raise ValueError('MAINTENANCE_DISK_SPACE')
        manifest = archive.read_backup(path,self._source_password(info,password),extract_to=stage,
                                       guard=archive.space_guard(self.state,self.min_free//4))
        self._verified(path,info,manifest)
        return stage,manifest

    def export_backup(self, bid, source_password, password):
        path, info = self.source_backup(bid)
        if archive.free_bytes(self.state) < path.stat().st_size + self.min_free:raise ValueError('MAINTENANCE_DISK_SPACE')
        new = uuid.uuid4().hex
        target = self.state/'backups'/(new+'.pcbackup')
        staging = target.with_suffix('.partial')
        writer = archive.BackupWriter(staging,password,archive.space_guard(self.state,self.min_free//4))
        try:
            manifest = archive.read_backup(path,self._source_password(info,source_password),writer=writer)
            final = writer.finish({k:v for k,v in manifest.items() if k in {'app_version','created_at','deployment'}})
        except BaseException:
            writer.abort()
            raise
        staging.replace(target)
        self._verified(path,info,manifest)
        return self._row(new,target,final,'export')

    # --- Update source ---------------------------------------------------------

    def _git(self, *args, cwd=None, timeout=180, check=True):
        command = ['git','-c','core.hooksPath=/dev/null',*args]
        if cwd:command[1:1] = ['-C',str(cwd)]
        result = subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                timeout=timeout,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'},text=True)
        if check and result.returncode:raise RuntimeError('UPDATE_FETCH_FAILED')
        return result.stdout.strip() if check else result.returncode == 0

    def release_tags(self, timeout=30):
        output = self._git('ls-remote','--tags','--refs',self.config['repository'],timeout=timeout)
        return [line.split('refs/tags/',1)[1] for line in output.splitlines() if 'refs/tags/' in line]

    def release_target(self, installed, timeout=30):
        if self.update_mode == 'branch':
            return {'source':'branch','branch':self.config.get('branch','main')}
        tag, key = newest_tag(self.release_tags(timeout),installed)
        if not tag:raise ValueError('UPDATE_NO_RELEASE_FOUND')
        current = version_key(installed)
        return {'source':'release','tag':tag,'version':display(tag[1:] if tag[:1] in 'vV' else tag),
                'newer':current is None or key > current}

    def update_preview(self, refresh=False):
        """Which version an update would install; cached briefly, no lock needed."""
        with self._preview_lock:
            stamp, cached = self._preview
            if cached and not refresh and time.monotonic()-stamp < 60:return cached
            installed = self.driver().version()
            result = {'installed':installed,'source':self.update_mode,'checked_at':utc(),'can_update':self.updatable()}
            try:
                target = self.release_target(installed,timeout=10)
                if target['source'] == 'release':
                    result.update(target=target['version'],tag=target['tag'],available=target['newer'])
                    if target['newer']:
                        requirements = self.remote_requirements(target['tag'])
                        if requirements is not None:result['checks'] = self.requirement_checks(self.driver(),requirements,installed)
                else:result.update(branch=target['branch'],available=None)
            except (ValueError,RuntimeError,OSError,subprocess.TimeoutExpired) as exc:
                result.update(available=False,error=str(exc) if str(exc) == 'UPDATE_NO_RELEASE_FOUND' else 'UPDATE_CHECK_FAILED')
            self._preview = (time.monotonic(),result)
            return result

    def fetch_source(self, driver):
        source = self.state/'source'
        if not source.exists():
            driver.run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout',self.config['repository'],str(source)],timeout=180)
        # Root owns this repository. Never use application-controlled Git config.
        self._git('remote','set-url','origin',self.config['repository'],cwd=source)
        branch = self.config.get('branch','main')
        target = self.release_target(driver.version())
        self._git('fetch','--no-tags','origin',branch,cwd=source)
        if target['source'] == 'release':
            ref = 'refs/tags/'+target['tag']
            self._git('fetch','--no-tags','--force','origin',ref+':'+ref,cwd=source)
            self._git('checkout','--force','--detach',ref,cwd=source)
        else:
            self._git('checkout','--force','--detach','FETCH_HEAD',cwd=source)
        commit = self._git('rev-parse','HEAD',cwd=source)
        if not re.fullmatch('[a-f0-9]{40,64}',commit):raise ValueError('UPDATE_REVISION_INVALID')
        return source,commit,target

    def updatable(self):
        project = Path(self.config['project'])
        return (project/'.git').exists() or (project/RELEASE_MARKER).is_file()

    def requirement_checks(self, driver, requirements, installed):
        checks = []
        minimum = requirements.get('min_upgrade_from')
        if minimum:
            have, need = version_key(installed), version_key(minimum)
            checks.append({'key':'upgrade_path','ok':not (have and need and have < need),'required':str(minimum),'actual':installed})
        tools = driver.tool_versions()
        for key in ('docker_compose','python','node'):
            need = requirements.get(key+'_min')
            if need and key in tools:
                checks.append({'key':key,'ok':_numbers(tools[key]) >= _numbers(need),'required':str(need),'actual':tools[key]})
        return checks

    def check_requirements(self, driver, source, installed):
        path = Path(source)/REQUIREMENTS
        if not path.is_file():return []
        try:requirements = json.loads(path.read_text())
        except ValueError:raise ValueError('UPDATE_REQUIREMENTS_INVALID') from None
        if not isinstance(requirements,dict):raise ValueError('UPDATE_REQUIREMENTS_INVALID')
        checks = self.requirement_checks(driver,requirements,installed)
        for check in checks:
            if not check['ok']:raise ValueError(REQUIREMENT_ERRORS[check['key']]+':'+re.sub(r'[^A-Za-z0-9_.-]','',check['required']))
        return checks

    def remote_requirements(self, tag):
        """Requirements of a GitHub release without fetching it (preview only)."""
        match = re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?',str(self.config.get('repository','')))
        if not match:return None
        import urllib.error
        import urllib.parse
        import urllib.request
        url = f'https://raw.githubusercontent.com/{match[1]}/{match[2]}/{urllib.parse.quote(tag,safe="")}/{REQUIREMENTS}'
        try:
            with urllib.request.urlopen(url,timeout=8) as response:value = json.loads(response.read(65536))
        except urllib.error.HTTPError as exc:
            return {} if exc.code == 404 else None
        except (OSError,ValueError):return None
        return value if isinstance(value,dict) else None

    def update_needed(self, source, previous, commit, installed, target):
        if previous == commit:return 'current'
        if target.get('source') == 'release':
            new, old = version_key(target.get('version')), version_key(installed)
            if new and old and new < old:return 'newer_installed'
            # A checkout that already contains the tagged commit (e.g. main after a release) is not downgraded.
            if (self._git('cat-file','-e',previous+'^{commit}',cwd=source,check=False)
                    and self._git('merge-base','--is-ancestor',commit,previous,cwd=source,check=False)):
                return 'contained'
        return None

    # --- Host steps --------------------------------------------------------------

    def applied_steps(self):
        try:return json.loads((self.state/'host-steps.json').read_text()).get('applied',{})
        except (OSError,ValueError):return {}

    def pending_steps(self, driver, source):
        directory = Path(source)/'install/host-steps'
        if not directory.is_dir():return []
        applied, result = self.applied_steps(), []
        for path in sorted(directory.iterdir()):
            match = HOST_STEP.fullmatch(path.name)
            if not match or path.name in applied or match[2] not in {'all',driver.mode}:continue
            if path.is_symlink() or not path.is_file():raise ValueError('HOST_STEP_INVALID')
            result.append(path)
        return result

    def run_steps(self, driver, source):
        done = []
        for path in self.pending_steps(driver,source):
            driver.log('Systemschritt '+path.name[:-3]+' wird ausgeführt')
            try:driver.host_step(path,source)
            except Exception:raise RuntimeError('HOST_STEP_FAILED:'+path.name[:3]) from None
            done.append(path.name)
        return done

    def mark_steps(self, names, commit=None):
        if not names:return
        applied = self.applied_steps()
        for name in names:applied[name] = {'at':utc(),'commit':commit}
        atomic_json(self.state/'host-steps.json',{'applied':applied})

    def startup(self):
        """Wiring and host steps that an older updater could not run yet."""
        driver = self.driver()
        try:driver.ensure_env_wiring()
        except Exception:pass
        source = self.state/'source'
        if not (source/'.git').is_dir() or not self.updatable():return
        try:
            if driver.installed_commit() != self._git('rev-parse','HEAD',cwd=source):return
            if not self.pending_steps(driver,source):return
            self.acquire()
        except Exception:return
        job = {'id':uuid.uuid4().hex,'operation':'host_steps','status':'running','created_at':utc(),
               'actor':'system','message':'Systemschritte werden nachgeholt','events':[]}
        try:
            self.save(job)
            steps_driver = self.driver(job)
            done = self.run_steps(steps_driver,source)
            self.mark_steps(done,self._git('rev-parse','HEAD',cwd=source))
            job.update(status='succeeded',message='Abgeschlossen',finished_at=utc(),steps=done)
        except Exception as exc:
            job.update(status='failed',finished_at=utc(),error=str(exc) if re.fullmatch(r'HOST_STEP_[A-Z_]+(:\d{3})?',str(exc)) else 'HOST_STEP_FAILED')
        finally:
            try:self.save(job)
            finally:self.release()

    # --- Maintenance mode ------------------------------------------------------

    def drain(self, driver, job):
        """Stop accepting new work, then wait for running background tasks."""
        try:driver.set_maintenance(job['id'])
        except Exception:driver.log('Wartungsmodus konnte nicht gemeldet werden; laufende Aufgaben werden trotzdem abgewartet')
        deadline = time.monotonic()+float(self.config.get('drain_timeout',600))
        last = None
        while True:
            tasks = driver.background_tasks()
            if tasks is None:
                driver.log('Hintergrundaufgaben sind nicht abfragbar; die Dienste werden angehalten');return
            if not tasks:return
            protected = [t for t in tasks if t['name'].startswith(PROTECTED_TASKS)]
            if time.monotonic() >= deadline:
                if protected:raise ValueError('MAINTENANCE_PROTECTED_TASK_RUNNING')
                driver.log(f'{len(tasks)} Hintergrundaufgabe(n) werden beim Anhalten beendet');return
            if len(tasks) != last:
                last = len(tasks)
                driver.log(f'Wartungsmodus aktiv: warte auf {last} laufende Hintergrundaufgabe(n)')
            time.sleep(float(self.config.get('drain_poll_seconds',3)))

    # --- Transactions ------------------------------------------------------------

    def swap_data(self, driver, stage, work):
        journal = driver.data/'.maintenance-rollback'
        journal.mkdir(mode=0o700,exist_ok=False)
        state = {'directory':str(journal),'moved':[],'installed':[]}
        atomic_json(work/'data-journal.json',state)
        for name in archive.DATA_INCLUDE:
            path = driver.data/name
            if path.is_symlink():raise ValueError('RESTORE_TARGET_SYMLINK')
            if not path.exists():continue
            state['moved'].append(name);atomic_json(work/'data-journal.json',state)
            path.rename(journal/name)
        incoming = stage/'data'
        for name in archive.DATA_INCLUDE:
            path = incoming/name
            if not path.is_dir():continue
            state['installed'].append(name);atomic_json(work/'data-journal.json',state)
            destination = driver.data/name
            try:path.rename(destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV:raise
                shutil.copytree(path,destination)
        if incoming.is_dir():
            ignored = [p.name for p in incoming.iterdir() if p.name not in archive.DATA_INCLUDE]
            if ignored:driver.log(f'{len(ignored)} Einträge außerhalb der Anwendungsdaten wurden nicht übernommen')
        driver.fix_ownership()

    def rollback_data(self, driver, work):
        entry = work/'data-journal.json'
        if not entry.exists():return
        state = json.loads(entry.read_text())
        journal = driver.data/'.maintenance-rollback'
        for name in state['installed']:
            target = driver.data/name
            if target.is_dir() and not target.is_symlink():shutil.rmtree(target)
            else:target.unlink(missing_ok=True)
        for name in state['moved']:
            original = journal/name
            if original.exists():original.rename(driver.data/name)
        if journal.exists():shutil.rmtree(journal)
        entry.unlink()

    def save_managed(self, driver, work):
        path = driver.managed_env
        value = {'exists':path.is_file(),'content':path.read_text() if path.is_file() else ''}
        atomic_json(work/'managed.before',value)

    def restore_managed(self, driver, work):
        value = json.loads((work/'managed.before').read_text())
        if value.get('exists'):
            temporary = driver.managed_env.with_name(driver.managed_env.name+'.new')
            fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as out:out.write(value['content']);out.flush();os.fsync(out.fileno())
            temporary.replace(driver.managed_env)
        else:driver.managed_env.unlink(missing_ok=True)

    def transaction(self, driver, job, work, values):
        atomic_json(work/'transaction.json',values)
        job['transaction'] = True;self.save(job)

    def mark_stopped(self, work, **values):
        entry = work/'transaction.json'
        state = json.loads(entry.read_text())
        state.update(stopped=True,**values)
        atomic_json(entry,state)

    def rollback(self, driver, work, job):
        entry = work/'transaction.json'
        if not entry.exists():return
        state = json.loads(entry.read_text())
        # Journals before Alpha.76 always meant: services were stopped.
        stopped = state.get('stopped',True)
        driver.log('Vorheriger Zustand wird wiederhergestellt')
        if stopped:driver.quiesce()
        if state.get('mode') == 'release':
            if stopped and driver.mode == 'native':driver.run(['systemctl','stop','pengucoach-web'])
            old = Path(state['old_target']) if state.get('old_target') else None
            if old and old.is_dir() and (driver.link.is_symlink() or not driver.link.exists()):
                if not (driver.link.is_symlink() and driver.link.resolve() == old.resolve()):driver.point_link(old)
            release = Path(state['release']) if state.get('release') else None
            if release and release.exists() and not (driver.link.is_symlink() and driver.link.resolve() == release.resolve()):
                shutil.rmtree(release,ignore_errors=True)
        elif state.get('old_commit'):
            if stopped and driver.mode == 'native':driver.run(['systemctl','stop','pengucoach-web'])
            driver.run(['git','-c','core.hooksPath=/dev/null','reset','--hard',state['old_commit']],target=True)
            if driver.mode == 'docker':driver.rollback_images(state.get('images',[]))
            elif stopped:driver.build()
        if state.get('old_database'):
            driver.rollback_database(state['old_database'],state['discard_database'])
        elif state.get('database_may_have_changed'):
            name, old_db = 'pc_rb_'+job['id'][:16], 'pc_drop_'+job['id'][:16]
            if not state.get('rollback_database_ready'):
                if driver.database_exists(name):driver.drop_database(name)
                driver.prepare_database(work/'safety/database.pgdump',name,migrate=False)
                state['rollback_database_ready']=True;atomic_json(entry,state)
            # Reuse the rename recovery path: it handles a crash between either rename.
            driver.rollback_database(name,old_db)
        self.rollback_data(driver,work)
        if (work/'managed.before').exists():self.restore_managed(driver,work)
        if (work/'environment.before').exists():
            # Alpha.73/74 journals rewrote the main environment file.
            write_env(driver.env_file,json.loads((work/'environment.before').read_text()))
        if stopped:driver.start();driver.healthy()
        entry.unlink()
        job['rolled_back'] = True;self.save(job)

    def execute(self, job, payload):
        work = self.state/'work'/job['id'];work.mkdir(mode=0o700,exist_ok=True)
        driver = self.driver(job)
        restart_agent = False
        maintenance = False
        try:
            job['status']='running';self.save(job)
            operation = job['operation']
            password = str(payload.get('password') or '')
            if operation == 'recover':
                self._recover(skip=job['id'])
            elif operation == 'inspect':
                driver.log('Sicherung wird entschlüsselt und vollständig geprüft')
                metadata = self.inspect_backup(payload['backup_id'],password)
                job['inspection'] = {k:v for k,v in metadata.items() if k!='files'}
                job['inspection']['file_count'] = len(metadata['files'])
            elif operation == 'export':
                driver.log('Sicherung wird geprüft und mit dem neuen Passwort verschlüsselt')
                job['backup'] = self.export_backup(payload['backup_id'],password,password)
            if operation == 'restore':
                driver.log('Sicherung wird entschlüsselt und vollständig geprüft')
                stage, metadata = self.decode(payload['backup_id'],password,work)
            if operation in {'backup','update','restore'}:
                driver.ensure_managed()
                source = commit = target = None
                steps = []
                release = None
                if operation == 'update':
                    if not self.updatable():raise ValueError('UPDATE_REQUIRES_GIT_CHECKOUT')
                    driver.log('Neue Programmversion wird abgerufen')
                    source,commit,target = self.fetch_source(driver)
                    job['target'] = target;self.save(job)
                    previous = driver.installed_commit()
                    installed = driver.version()
                    reason = self.update_needed(source,previous,commit,installed,target)
                    if reason:
                        job.update(status='succeeded',message=NOOP[reason],finished_at=utc(),noop=reason);self.save(job);return
                    driver.log('Voraussetzungen der neuen Version werden geprüft')
                    self.check_requirements(driver,source,installed)
                    # Build the new version while the current one keeps serving users.
                    if driver.release_layout():
                        driver.log('Freier Speicherplatz wird geprüft')
                        self.check_space(driver,extra=int(driver.release_size()*1.2))
                        release = driver.releases/commit[:12]
                        self.transaction(driver,job,work,{'mode':'release','stopped':False,'release':str(release),'old_target':str(driver.link_target())})
                        driver.log('Neue Version wird bei laufender App vorbereitet')
                        driver.prepare_release(source,commit,target.get('version') or '')
                        driver.log('Abhängigkeiten und Weboberfläche werden gebaut – die App bleibt erreichbar')
                        driver.build_release(release)
                    elif driver.mode == 'docker':
                        self.transaction(driver,job,work,{'old_commit':previous,'images':driver.images(),'stopped':False})
                        driver.log('Neue Images werden gebaut – die App bleibt erreichbar')
                        driver.update_source(source,commit)
                        driver.build()
                if operation == 'restore':
                    # Fully restore/migrate a scratch DB before touching the live database.
                    temporary = 'pc_new_'+job['id'][:16]
                    env = json.loads((stage/'environment.json').read_text())
                    job['prepared_database']=temporary;self.save(job)
                    driver.log('Datenbank wird in einer Testkopie vorbereitet und migriert')
                    driver.prepare_database(stage/'database.pgdump',temporary,env.get('PENGUCOACH_ENCRYPTION_KEY'))
                driver.log('Freier Speicherplatz wird geprüft')
                self.check_space(driver)
                maintenance = True
                self.drain(driver,job)
                driver.log('Dienste werden für eine konsistente Sicherung angehalten')
                try:
                    driver.quiesce()
                    before = self.snapshot(driver,work/'safety')
                except BaseException:
                    driver.start()
                    raise
                try:
                    kind = 'safety' if operation != 'backup' else 'local' if payload.get('local') else 'manual'
                    backup = self.store_backup(driver,work/'safety',before,self.machine_key() if kind in {'safety','local'} else password,kind)
                    job['backup']=backup;self.save(job)
                    if operation == 'update':
                        if release is not None:
                            self.mark_stopped(work,database_may_have_changed=True)
                            driver.run(['systemctl','stop','pengucoach-web'])
                            driver.log('Neue Version wird aktiviert und die Datenbank migriert')
                            driver.point_link(release)
                            driver.migrate(release)
                        elif driver.mode == 'docker':
                            self.mark_stopped(work,database_may_have_changed=True)
                            driver.log('Datenbank wird migriert')
                            driver.migrate()
                        else:
                            # Native installation without release directories (release_layout: false).
                            driver.log('Programm und Abhängigkeiten werden aktualisiert')
                            self.transaction(driver,job,work,{'old_commit':previous,'images':[],'database_may_have_changed':True,'stopped':True})
                            driver.run(['systemctl','stop','pengucoach-web'])
                            driver.update_source(source,commit)
                            driver.build();driver.migrate()
                        steps = self.run_steps(driver,source)
                    elif operation == 'restore':
                        old = 'pc_old_'+job['id'][:16]
                        self.save_managed(driver,work)
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
                journal = json.loads((work/'transaction.json').read_text()) if (work/'transaction.json').exists() else {}
                atomic_json(work/'committed.json',{'operation':operation,'old_database':old if operation=='restore' else None,'steps':steps,'commit':commit,'old_target':journal.get('old_target')})
                (work/'transaction.json').unlink(missing_ok=True);sync_directory(work)
                shutil.rmtree(driver.data/'.maintenance-rollback',ignore_errors=True)
                self.mark_steps(steps,commit)
                if operation == 'restore':
                    try:driver.drop_database(old)
                    except Exception:job.update(cleanup_pending=True,cleanup_database=old)
                if operation in {'update','restore'}:
                    try:
                        removed = self.prune_backups(protect={backup['id']})
                        if removed:job['pruned_backups'] = len(removed)
                    except OSError:pass
                if release is not None:
                    try:
                        removed = driver.prune_releases(int(self.config.get('keep_releases',2)),protect={json.loads((work/'committed.json').read_text()).get('old_target') or ''} - {''})
                        if removed:job['pruned_releases'] = len(removed)
                    except OSError:pass
                if operation == 'update':
                    # Update agent code only from the root-owned, fixed upstream checkout.
                    program = self.config.get('program')
                    if program and (source/'pengucoach/maintenance').is_dir():
                        try:
                            for path in (source/'pengucoach/maintenance').glob('*.py'):
                                if path.is_symlink():raise ValueError('UPDATE_AGENT_SYMLINK')
                                target_file=Path(program)/path.name
                                temporary_file=target_file.with_suffix('.new')
                                shutil.copyfile(path,temporary_file);temporary_file.replace(target_file)
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
            if maintenance:
                try:driver.clear_maintenance()
                except Exception:pass
            if not job.get('recovery_required'):
                if job.get('prepared_database'):
                    try:
                        if driver.database_exists(job['prepared_database']):driver.drop_database(job['prepared_database'])
                    except Exception:pass
                if not job.get('cleanup_pending'):shutil.rmtree(work,ignore_errors=True)
            try:self.prune_jobs()
            except OSError:pass
            self.release()
        if restart_agent and self.allow_restart and self.config.get('restart_after_update'):
            # systemd Restart=always / Docker unless-stopped starts the new code.
            os._exit(0)

    def recover(self):
        self.acquire()
        try:self._recover()
        finally:self.release()

    def _recover(self, skip=None):
        for partial in (self.state/'backups').glob('*.partial'):partial.unlink(missing_ok=True)
        for row in self.jobs(limit=None):
            if row.get('id') == skip:continue
            if row.get('status') in {'queued','running'} and not (self.state/'work'/row['id']).exists():
                row.update(status='failed',error='MAINTENANCE_INTERRUPTED',finished_at=utc());self.save(row)
        for work in (self.state/'work').iterdir():
            if work.name == skip:continue
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
                    self.mark_steps(committed.get('steps') or [],committed.get('commit'))
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
        # Without a journal nothing can be rolled back. Release the block only when
        # the application demonstrably runs again; otherwise keep it for an administrator.
        for row in self.jobs(limit=None):
            if row.get('id') == skip or not row.get('recovery_required') or (self.state/'work'/row['id']).exists():continue
            try:
                driver = self.driver(row)
                driver.start();driver.healthy()
                row.update(recovery_required=False,recovery_note='NO_JOURNAL_SERVICES_HEALTHY')
            except Exception:pass
            self.save(row)
