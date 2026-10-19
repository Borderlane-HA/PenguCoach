"""Native systemd and Linux Docker Compose adapters; no request-provided commands."""
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .archive import EXCLUDED

SERVICES = ['api','worker','scheduler']
INFRASTRUCTURE = {'PENGUCOACH_DATABASE_URL','PENGUCOACH_REDIS_URL','PENGUCOACH_DATA_DIR',
                  'PENGUCOACH_FRONTEND_ORIGIN','PENGUCOACH_COOKIE_SECURE','NEXT_PUBLIC_API_BASE_URL',
                  'PENGUCOACH_MAINTENANCE_SOCKET'}


def read_env(path):
    import shlex
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        name, value = line.split('=', 1)
        if re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
            parsed = shlex.split(value, comments=False)
            values[name] = ' '.join(parsed)
    return values


def write_env(path, values):
    import shlex
    temporary = Path(str(path)+'.maintenance-new')
    with temporary.open('w') as out:
        os.chmod(temporary, 0o600)
        for name, value in sorted(values.items()):
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):raise ValueError('ENVIRONMENT_KEY_INVALID')
            out.write(name+'='+shlex.quote(str(value))+'\n')
    previous = Path(path).stat()
    os.chown(temporary, previous.st_uid, previous.st_gid)
    os.chmod(temporary, previous.st_mode & 0o777)
    temporary.replace(path)


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

    def run(self, args, *, target=None, input_file=None, output_file=None, env=None, timeout=3600, quiet=False):
        # Never put environment contents, passwords or provider data into logs.
        if not quiet:self.log('Ausführen: '+Path(args[0]).name+' '+(' '.join(args[1:3])))
        command = list(args)
        if command[0] == "git":command = [command[0],"-c","safe.directory="+str(self.root),*command[1:]]
        if target and self.mode == 'native':command = ['runuser','-u',self.config.get('user','pengucoach'),'--',*command]
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

    def clear_queue(self):
        # Mark restored task records final before clearing transient queue/result state.
        if self.mode == 'docker':
            self.run([*self.compose,'run','--rm','--no-deps','-T','api','python','-m','pengucoach.maintenance.app_restore'],quiet=True)
        else:
            self.run([str(self.root/'.venv/bin/python'),'-m','pengucoach.maintenance.app_restore'],target=True,env=self.environment(),quiet=True)
        if self.mode == 'docker':
            self.run([*self.compose,'exec','-T','redis','redis-cli','FLUSHDB'],quiet=True)
        else:
            # The managed native installer uses Redis DB 0 exclusively for PenguCoach.
            self.run(['redis-cli','-n','0','FLUSHDB'],quiet=True)
        for name in EXCLUDED:
            if name.startswith('celerybeat-schedule'):(self.data/name).unlink(missing_ok=True)

    def environment(self):
        result = read_env(self.env_file)
        if self.mode == "docker":
            effective = json.loads(self.run([*self.compose,"config","--format","json"],quiet=True))
            result.update(effective["services"]["api"].get("environment") or {})
        if not result.get('PENGUCOACH_ENCRYPTION_KEY'):raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING')
        return result

    def restore_environment(self, values):
        import secrets
        current = read_env(self.env_file)
        merged = {**values,**{k:v for k,v in current.items() if k in INFRASTRUCTURE}}
        merged['PENGUCOACH_JWT_SECRET'] = secrets.token_hex(48)
        merged['PENGUCOACH_APP_VERSION'] = self.version()
        write_env(self.env_file, merged)

    def version(self):
        return str(tomllib.loads((self.root/'pyproject.toml').read_text())['project']['version'])

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
