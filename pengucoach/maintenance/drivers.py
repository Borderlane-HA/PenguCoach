"""Native systemd and Linux Docker Compose adapters; no request-provided commands."""
import json
import os
import pwd
import re
import secrets
import shlex
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .archive import EXCLUDED
from .versions import display

SERVICES = ['api','worker','scheduler']
# Kept for compatibility with Alpha.73 rollback journals.
INFRASTRUCTURE = {'PENGUCOACH_DATABASE_URL','PENGUCOACH_REDIS_URL','PENGUCOACH_DATA_DIR',
                  'PENGUCOACH_FRONTEND_ORIGIN','PENGUCOACH_COOKIE_SECURE','NEXT_PUBLIC_API_BASE_URL',
                  'PENGUCOACH_MAINTENANCE_SOCKET'}
MAINTENANCE_KEY = 'pengucoach:maintenance'
DROPIN = '10-pengucoach-maintenance-env.conf'
TASK_PROBE = ("import json;from worker.celery_app import app;i=app.control.inspect(timeout=3);"
              "print(json.dumps({'active':i.active() or {},'reserved':i.reserved() or {}}))")


def _value(raw):
    raw = raw.strip()
    if raw[:1] in {'"', "'"}:
        try:return ' '.join(shlex.split(raw, comments=True))
        except ValueError:return raw.strip('"\'')
    # Unquoted values end at an inline comment preceded by whitespace (Compose/dotenv rule).
    return re.split(r'\s+#', raw, maxsplit=1)[0].strip()


def read_env(path):
    """Read a dotenv/systemd environment file without failing on unusual lines."""
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        if line.startswith('export '):line = line[7:].lstrip()
        name, value = line.split('=', 1)
        name = name.strip()
        if re.fullmatch(r'[A-Z_][A-Z0-9_]*', name):values[name] = _value(value)
    return values


def _render(values):
    lines = []
    for name, value in sorted(values.items()):
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name):raise ValueError('ENVIRONMENT_KEY_INVALID')
        lines.append(name+'='+shlex.quote(str(value))+'\n')
    return ''.join(lines)


def write_env(path, values):
    """Rewrite an existing environment file, keeping owner and mode (Alpha.73 journals)."""
    temporary = Path(str(path)+'.maintenance-new')
    with temporary.open('w') as out:
        os.chmod(temporary, 0o600)
        out.write(_render(values))
    previous = Path(path).stat()
    os.chown(temporary, previous.st_uid, previous.st_gid)
    os.chmod(temporary, previous.st_mode & 0o777)
    temporary.replace(path)


def write_private_env(path, values, header=''):
    """Write the maintenance-owned environment file (read by systemd/Compose as root)."""
    path = Path(path)
    temporary = path.with_name(path.name+'.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        os.chmod(temporary, 0o600)
        out.write(header+_render(values));out.flush();os.fsync(out.fileno())
    temporary.replace(path)


MANAGED_HEADER = ('# Written by PenguCoach system maintenance after a restore. Do not edit.\n'
                  '# Values here override the main environment file.\n')


class Driver:
    def __init__(self, config, log=lambda text:None):
        self.config, self.log = config, log
        self.root = Path(config['project']).resolve()
        self.env_file = Path(config['environment']).resolve()
        self.mode = config['deployment']
        self.compose = ['docker','compose','--project-directory',str(self.root)]
        for file in config.get('compose_files') or [str(self.root/'docker-compose.yml')]:self.compose += ['-f',file]
        if config.get('compose_project'):self.compose += ['--project-name',config['compose_project']]
        self.data = Path(config['data']).resolve()
        default = self.root/'.env.maintenance' if self.mode == 'docker' else self.env_file.with_name('pengucoach.managed.env')
        self.managed_env = Path(config.get('managed_environment') or default)
        self.systemd = Path(config.get('systemd_dir','/etc/systemd/system'))
        self._build_home = None

    def build_home(self):
        # The service user's home is the data directory. Build tools must not put
        # npm/pip caches there, otherwise they end up in every full backup.
        if self._build_home is None:
            home = Path(self.config.get('build_home','/var/cache/pengucoach-build'))
            home.mkdir(parents=True, exist_ok=True, mode=0o750)
            owner = pwd.getpwnam(self.config.get('user','pengucoach'))
            os.chown(home, owner.pw_uid, owner.pw_gid)
            self._build_home = home
        return self._build_home

    def run(self, args, *, target=None, input_file=None, output_file=None, env=None, timeout=3600, quiet=False):
        # Never put environment contents, passwords or provider data into logs.
        if not quiet:self.log('Ausführen: '+Path(args[0]).name+' '+(' '.join(args[1:3])))
        command = list(args)
        if command[0] == "git":command = [command[0],"-c","safe.directory="+str(self.root),*command[1:]]
        if target and self.mode == 'native':
            home = self.build_home()
            command = ['runuser','-u',self.config.get('user','pengucoach'),'--','env','HOME='+str(home),
                       'XDG_CACHE_HOME='+str(home/'.cache'),'npm_config_cache='+str(home/'.npm'),
                       'PIP_CACHE_DIR='+str(home/'.cache/pip'),*command]
        with open(input_file, 'rb') if input_file else open(os.devnull, 'rb') as src:
            with open(output_file, 'wb') if output_file else tempfile.TemporaryFile() as dst:
                result = subprocess.run(command, cwd=self.root, env={**os.environ,**(env or {})}, stdin=src,
                    stdout=dst, stderr=subprocess.PIPE, timeout=timeout, check=False)
                if result.returncode:
                    # Discard raw stderr: it can contain credentials, SQL and user data.
                    raise RuntimeError('MAINTENANCE_COMMAND_FAILED:'+Path(args[0]).name+':'+str(result.returncode))
                if output_file:return ''
                dst.seek(0)
                return dst.read(2*1024*1024).decode('utf-8','replace').strip()

    def db(self, executable, args, **kwargs):
        if self.mode == 'docker':command = [*self.compose,'exec','-T','postgres',executable,'-U','pengucoach',*args]
        else:command = ['runuser','-u','postgres','--',executable,*args]
        return self.run(command, quiet=True, **kwargs)

    def sql(self, statement):
        return self.db('psql',['-d','postgres','-v','ON_ERROR_STOP=1','-Atqc',statement])

    def quiesce(self):
        if self.mode == 'docker':self.run([*self.compose,'stop',*SERVICES],timeout=180)
        else:self.run(['systemctl','stop',*[f'pengucoach-{s}' for s in SERVICES]],timeout=180)

    def start(self):
        if self.mode == 'docker':self.run([*self.compose,'up','-d','--no-build','api','worker','scheduler','web'],timeout=300)
        else:self.run(['systemctl','start',*[f'pengucoach-{s}' for s in SERVICES],'pengucoach-web'],timeout=180)

    def healthy(self):
        for _ in range(45):
            try:
                if self.mode == 'docker':
                    # The setup endpoint performs a real database query using the API credentials.
                    script = ('import urllib.request; '
                              'print(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/setup/status",timeout=2).status)')
                    api = self.run([*self.compose,'exec','-T','api','python','-c',script],timeout=8,quiet=True)
                    web = self.run([*self.compose,'exec','-T','web','node','-e',
                        'const h=process.env.HOSTNAME;fetch("http://"+(!h||h==="0.0.0.0"?"127.0.0.1":h)+":3000",{signal:AbortSignal.timeout(3000)}).then(r=>{if(!r.ok)process.exit(1);console.log(r.status)}).catch(()=>process.exit(1))'],timeout=8,quiet=True)
                    if api == '200' and web == '200':return
                else:
                    import urllib.request
                    for address in ['http://127.0.0.1:8000/api/v1/setup/status','http://127.0.0.1:3000']:
                        with urllib.request.urlopen(address,timeout=3) as response:
                            if response.status != 200:raise RuntimeError('MAINTENANCE_HEALTHCHECK_FAILED')
                    return
            except Exception:pass
            time.sleep(2)
        raise RuntimeError('MAINTENANCE_HEALTHCHECK_FAILED')

    def ensure_managed(self):
        values = self.environment()
        database = urlsplit(values.get('PENGUCOACH_DATABASE_URL',''))
        redis = urlsplit(values.get('PENGUCOACH_REDIS_URL',''))
        hosts = {'postgres'} if self.mode == 'docker' else {'127.0.0.1','localhost','::1'}
        redis_hosts = {'redis'} if self.mode == 'docker' else {'127.0.0.1','localhost','::1'}
        if database.hostname not in hosts or database.path != '/pengucoach' or database.port not in {None,5432}:raise ValueError('MANAGED_DATABASE_REQUIRED')
        if redis.hostname not in redis_hosts or redis.path not in {'','/0'} or redis.port not in {None,6379}:raise ValueError('MANAGED_REDIS_REQUIRED')

    def dump(self, path):self.db('pg_dump',['-Fc','--no-owner','--no-acl','pengucoach'],output_file=path)

    def database_size(self):
        try:return int(self.sql("SELECT pg_database_size('pengucoach')") or 0)
        except (ValueError,RuntimeError):return 0

    def prepare_database(self, dump, name, encryption_key=None, migrate=True):
        if not re.fullmatch(r'pc_[a-f0-9_]+', name):raise ValueError('DATABASE_NAME_INVALID')
        self.db('createdb',['-O','pengucoach',name])
        try:
            self.db('pg_restore',['--exit-on-error','--no-owner','--no-acl','--role=pengucoach','-d',name],input_file=dump)
            if not migrate:return
            values = self.environment()
            url = values.get('PENGUCOACH_DATABASE_URL','postgresql+asyncpg://pengucoach:pengucoach@postgres:5432/pengucoach')
            parts = urlsplit(url)
            url = urlunsplit((parts.scheme,parts.netloc,'/'+name,parts.query,''))
            extra = {'PENGUCOACH_DATABASE_URL':url}
            if encryption_key:extra['PENGUCOACH_ENCRYPTION_KEY'] = encryption_key
            if self.mode == 'docker':
                # Environment overrides are inherited from this host process, never argv.
                self.run([*self.compose,'run','--rm','--no-deps','-T','-e','PENGUCOACH_DATABASE_URL',
                    '-e','PENGUCOACH_ENCRYPTION_KEY','api','alembic','-c','alembic.ini','upgrade','head'],env=extra,quiet=True)
            else:self.run([str(self.root/'.venv/bin/alembic'),'-c','alembic.ini','upgrade','head'],target=True,env={**values,**extra},quiet=True)
        except BaseException:
            self.drop_database(name)
            raise

    def drop_database(self, name):
        if not re.fullmatch(r'pc_[a-f0-9_]+', name):raise ValueError('DATABASE_NAME_INVALID')
        self.db('dropdb',['--if-exists',name])

    def database_exists(self, name):
        if not re.fullmatch(r'(pengucoach|pc_[a-f0-9_]+)',name):raise ValueError('DATABASE_NAME_INVALID')
        return self.sql("SELECT 1 FROM pg_database WHERE datname='"+name+"'") == '1'

    def swap_database(self, new, old):
        for name in (new,old):
            if not re.fullmatch(r'pc_[a-f0-9_]+',name):raise ValueError('DATABASE_NAME_INVALID')
        self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='pengucoach' AND pid<>pg_backend_pid()")
        self.sql(f'ALTER DATABASE pengucoach RENAME TO {old}')
        self.sql(f'ALTER DATABASE {new} RENAME TO pengucoach')

    def rollback_database(self, old, discarded):
        if self.database_exists(old):
            if self.database_exists('pengucoach'):
                self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='pengucoach' AND pid<>pg_backend_pid()")
                self.sql(f'ALTER DATABASE pengucoach RENAME TO {discarded}')
            self.sql(f'ALTER DATABASE {old} RENAME TO pengucoach')
        if self.database_exists(discarded):self.drop_database(discarded)

    def redis(self, *args):
        if self.mode == 'docker':return self.run([*self.compose,'exec','-T','redis','redis-cli',*args],quiet=True,timeout=30)
        # The managed native installer uses Redis DB 0 exclusively for PenguCoach.
        return self.run(['redis-cli','-n','0',*args],quiet=True,timeout=30)

    def clear_queue(self):
        # Mark restored task records final before clearing transient queue/result state.
        if self.mode == 'docker':
            self.run([*self.compose,'run','--rm','--no-deps','-T','api','python','-m','pengucoach.maintenance.app_restore'],quiet=True)
        else:
            self.run([str(self.root/'.venv/bin/python'),'-m','pengucoach.maintenance.app_restore'],target=True,env=self.environment(),quiet=True)
        self.redis('FLUSHDB')
        for name in EXCLUDED:
            if name.startswith('celerybeat-schedule'):(self.data/name).unlink(missing_ok=True)

    # --- Maintenance mode / background tasks -----------------------------

    def set_maintenance(self, job_id):
        """Ask API and scheduler to accept no new work (expires on its own)."""
        self.redis('SET',MAINTENANCE_KEY,str(job_id),'EX','21600')

    def clear_maintenance(self):
        self.redis('DEL',MAINTENANCE_KEY)

    def background_tasks(self):
        """Active and reserved Celery tasks, or None when the workers cannot be asked."""
        try:
            if self.mode == 'docker':
                output = self.run([*self.compose,'exec','-T','worker','python','-c',TASK_PROBE],quiet=True,timeout=30)
            else:
                output = self.run([str(self.root/'.venv/bin/python'),'-c',TASK_PROBE],target=True,env=self.environment(),quiet=True,timeout=30)
            state = json.loads(output.strip().splitlines()[-1])
        except (RuntimeError,ValueError,IndexError,OSError,subprocess.TimeoutExpired):
            return None
        tasks = []
        for kind in ('active','reserved'):
            for rows in (state.get(kind) or {}).values():
                for row in rows or []:
                    if isinstance(row,dict):tasks.append({'name':str(row.get('name') or ''),'id':str(row.get('id') or ''),'state':kind})
        return tasks

    # --- Environment -------------------------------------------------------

    def environment(self):
        result = read_env(self.env_file)
        if self.managed_env.is_file():result.update(read_env(self.managed_env))
        if self.mode == "docker":
            effective = json.loads(self.run([*self.compose,"config","--format","json"],quiet=True))
            result.update(effective["services"]["api"].get("environment") or {})
        if not result.get('PENGUCOACH_ENCRYPTION_KEY'):raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING')
        return result

    def ensure_env_wiring(self):
        """Native: load the maintenance-owned file after the main one (systemd drop-ins)."""
        if self.mode != 'native':return False
        content = f'[Service]\nEnvironmentFile=-{self.managed_env}\n'
        changed = False
        for service in SERVICES:
            directory = self.systemd/f'pengucoach-{service}.service.d'
            path = directory/DROPIN
            if path.is_file() and path.read_text() == content:continue
            directory.mkdir(parents=True,exist_ok=True,mode=0o755)
            temporary = path.with_name(path.name+'.new');temporary.write_text(content);os.chmod(temporary,0o644);temporary.replace(path)
            changed = True
        if changed:self.run(['systemctl','daemon-reload'],quiet=True,timeout=60)
        return changed

    def verify_managed(self, expected):
        """Fail before starting services if the overrides would not be loaded."""
        if self.mode == 'docker':
            effective = json.loads(self.run([*self.compose,"config","--format","json"],quiet=True))['services']
            for service in SERVICES:
                env = effective.get(service,{}).get('environment') or {}
                if any(env.get(k) != v for k,v in expected.items()):raise RuntimeError('MANAGED_ENV_NOT_LOADED')
        else:
            for service in SERVICES:
                files = self.run(['systemctl','show','-p','EnvironmentFiles','--value',f'pengucoach-{service}'],quiet=True,timeout=30)
                if str(self.managed_env) not in files:raise RuntimeError('MANAGED_ENV_NOT_LOADED')

    def restore_environment(self, values):
        """Apply the backup's encryption key and a new session secret without touching the user's file."""
        key = values.get('PENGUCOACH_ENCRYPTION_KEY')
        if not key:raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING')
        self.ensure_env_wiring()
        managed = read_env(self.managed_env) if self.managed_env.is_file() else {}
        managed.update(PENGUCOACH_ENCRYPTION_KEY=key,PENGUCOACH_JWT_SECRET=secrets.token_hex(48))
        write_private_env(self.managed_env,managed,MANAGED_HEADER)
        self.verify_managed({'PENGUCOACH_ENCRYPTION_KEY':key,'PENGUCOACH_JWT_SECRET':managed['PENGUCOACH_JWT_SECRET']})

    def version(self):
        return display(tomllib.loads((self.root/'pyproject.toml').read_text())['project']['version'])

    def fix_ownership(self):
        if self.mode == 'native':
            owner = pwd.getpwnam(self.config.get('user','pengucoach'))
            for base, dirs, files in os.walk(self.data):
                dirs[:] = [d for d in dirs if d not in EXCLUDED]
                os.chown(base,owner.pw_uid,owner.pw_gid)
                for name in files:
                    if not Path(base,name).is_symlink():os.chown(Path(base,name),owner.pw_uid,owner.pw_gid)

    def update_source(self, source, commit):
        # Repository and commit come from a root-owned fetch, not HTTP request data.
        self.run(['git','-c','core.hooksPath=/dev/null','fetch',self.config['repository'],commit],target=True)
        self.run(['git','-c','core.hooksPath=/dev/null','reset','--hard',commit],target=True)
        # Preserve deployment configuration files outside Git, including custom Compose overrides.
        protected = ['.env','.env.*','compose*.yml','compose*.yaml','docker-compose*.yml','docker-compose*.yaml']
        for file in self.config.get('compose_files',[]):
            try:protected.append(str(Path(file).relative_to(self.root)))
            except ValueError:pass
        exclusions = [part for pattern in protected for part in ['-e',pattern]]
        self.run(['git','-c','core.hooksPath=/dev/null','clean','-fd',*exclusions],target=True)
        if self.mode == 'docker':
            owner = self.root.stat()
            for base, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in {'node_modules','.venv','.next'}]
                for name in [*dirs,*files]:
                    path = Path(base)/name
                    if not path.is_symlink():os.chown(path,owner.st_uid,owner.st_gid)

    def images(self):
        if self.mode != 'docker':return []
        result = []
        for service in ['api','worker','scheduler','web']:
            cid = self.run([*self.compose,'ps','-a','-q',service],quiet=True)
            if cid:
                info = json.loads(self.run(['docker','inspect',cid],quiet=True))[0]
                result.append({'tag':info['Config']['Image'],'id':info['Image']})
        return result

    def build(self):
        if self.mode == 'docker':self.run([*self.compose,'build','api','worker','scheduler','web'],timeout=3600)
        else:
            self.run([str(self.root/'.venv/bin/pip'),'install','.'],target=True)
            web = self.root/'apps/web'
            self.run(['npm','--prefix',str(web),'install','--no-audit','--no-fund'],target=True)
            self.run(['npm','--prefix',str(web),'run','build'],target=True,
                env={'NEXT_PUBLIC_API_BASE_URL':'/api/v1','NODE_OPTIONS':'--max-old-space-size=768','NEXT_TELEMETRY_DISABLED':'1'})

    def migrate(self):
        if self.mode == 'docker':self.run([*self.compose,'run','--rm','--no-deps','-T','api','alembic','-c','alembic.ini','upgrade','head'])
        else:self.run([str(self.root/'.venv/bin/alembic'),'-c','alembic.ini','upgrade','head'],target=True,env=self.environment())

    def rollback_images(self, images):
        for image in images:self.run(['docker','image','tag',image['id'],image['tag']],quiet=True)

    def host_step(self, script, source, timeout=600):
        """Run one reviewed host step from the root-owned release checkout."""
        env = {'PENGUCOACH_DEPLOYMENT':self.mode,'PENGUCOACH_PROJECT':str(self.root),'PENGUCOACH_SOURCE':str(source),
               'PENGUCOACH_DATA':str(self.data),'PENGUCOACH_ENV_FILE':str(self.env_file),
               'PENGUCOACH_MANAGED_ENV':str(self.managed_env),'PENGUCOACH_SERVICE_USER':self.config.get('user','pengucoach')}
        if self.mode == 'docker':env['PENGUCOACH_COMPOSE']=shlex.join(self.compose)
        self.run(['bash',str(script)],env=env,timeout=timeout,quiet=True)
