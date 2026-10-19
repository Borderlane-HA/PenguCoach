"""Automatic host setup, including the first upgrade executed by older updaters.

Native setup is restricted to the managed root deployment. The migration bridge
runs only for an online CLI upgrade on its live database, after migration commit.
Docker Compose uses a short-lived setup helper; the running agent stays outside
that Compose stack so application restarts cannot stop its maintenance job.
"""
import argparse
import fcntl
import http.client
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

PROJECT = Path('/opt/pengucoach')
ENVIRONMENT = Path('/etc/pengucoach/pengucoach.env')
API_UNIT = Path('/etc/systemd/system/pengucoach-api.service')
CONFIG = Path('/etc/pengucoach-maintenance.json')
SYSTEMD = Path('/run/systemd/system')
NATIVE_STATUS = Path('/run/pengucoach-maintenance-setup.json')
NATIVE_LOG = Path('/var/log/pengucoach-maintenance-setup.log')
NATIVE_SOCKET = Path('/run/pengucoach-maintenance/control.sock')
CONTROL = Path('/control')
REPOSITORY = 'https://github.com/Borderlane-HA/PenguCoach.git'


def status_file(path, status, deployment, code=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {'status':status,'deployment':deployment,'updated_at':datetime.now(timezone.utc).isoformat()}
    if code:value['code'] = code
    temporary = path.with_name(path.name+'.new')
    fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o644)
    with os.fdopen(fd,'w') as out:
        os.chmod(temporary,0o644);json.dump(value,out);out.flush();os.fsync(out.fileno())
    temporary.replace(path)


def agent_available(path):
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            self.sock.settimeout(2);self.sock.connect(str(path))
    connection = Connection('localhost',timeout=2)
    try:
        connection.request('GET','/status')
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read(2*1024**2)).get('available') is True
    except (OSError,ValueError,http.client.HTTPException):return False
    finally:connection.close()


def wait_agent(path, timeout=20):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if agent_available(path):return True
        time.sleep(.3)
    return False


def managed_native(project):
    return (os.geteuid()==0 and Path(project).resolve()==PROJECT.resolve()
            and ENVIRONMENT.is_file() and API_UNIT.is_file() and SYSTEMD.is_dir())


def ensure_native(project):
    project = Path(project).resolve()
    if not managed_native(project):return 'skipped'
    NATIVE_STATUS.parent.mkdir(parents=True,exist_ok=True)
    # Multiple old/new shell invocations cannot initialize the host concurrently.
    with NATIVE_STATUS.with_suffix('.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 'running'
        try:
            active = subprocess.run(['systemctl','is-active','--quiet','pengucoach-maintenance'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode == 0
            if active and CONFIG.is_file():
                # Do not restart an agent that may be recovering an interrupted job.
                state = 'ready' if agent_available(NATIVE_SOCKET) else 'running'
                status_file(NATIVE_STATUS,state,'native')
                return state
            status_file(NATIVE_STATUS,'running','native')
            NATIVE_LOG.parent.mkdir(parents=True,exist_ok=True)
            fd = os.open(NATIVE_LOG,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as log:
                os.chmod(NATIVE_LOG,0o600)
                result = subprocess.run(['bash',str(project/'install/maintenance/install.sh'),'native',str(project)],
                    cwd=project,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            if result.returncode==75:
                status_file(NATIVE_STATUS,'deferred','native','MAINTENANCE_BUSY');return 'deferred'
            if result.returncode or not wait_agent(NATIVE_SOCKET):raise RuntimeError('MAINTENANCE_SETUP_FAILED')
            status_file(NATIVE_STATUS,'ready','native')
            print('[PenguCoach] System maintenance configured automatically.',flush=True)
            return 'ready'
        except Exception:
            status_file(NATIVE_STATUS,'failed','native','MAINTENANCE_SETUP_FAILED')
            print('[PenguCoach] Automatic maintenance setup failed; application update may continue. '
                  'See /var/log/pengucoach-maintenance-setup.log.',file=sys.stderr,flush=True)
            return 'failed'


def after_native_migration(project, database_url, command_options):
    # Alpha.72 and earlier run this already-existing root Alembic step after Git
    # checkout. Editing only the new shell updater would miss that first upgrade.
    command = getattr(command_options,'cmd',None)
    if not command or getattr(command[0],'__name__','') != 'upgrade':return 'skipped'
    database = urlsplit(database_url)
    if (database.hostname not in {'localhost','127.0.0.1','::1'} or database.port not in {None,5432}
            or database.path != '/pengucoach'):return 'skipped'
    try:return ensure_native(project)
    except Exception:
        print('[PenguCoach] Automatic maintenance setup could not be verified; application migration completed.',file=sys.stderr,flush=True)
        return 'failed'


def docker(args, *, input=None):
    result = subprocess.run(['docker',*args],input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    if result.returncode:raise RuntimeError('DOCKER_MAINTENANCE_SETUP_FAILED')
    return result.stdout.decode().strip()


def inspect(target):return json.loads(docker(['inspect',target]))[0]


def docker_context():
    own = inspect(os.environ.get('HOSTNAME',''))
    labels = own['Config'].get('Labels') or {}
    project = labels.get('com.docker.compose.project')
    root = labels.get('com.docker.compose.project.working_dir')
    files = [v for v in labels.get('com.docker.compose.project.config_files','').split(',') if v]
    if not project or not root or not Path(root).is_absolute() or not files:
        raise RuntimeError('DOCKER_COMPOSE_LABELS_REQUIRED')
    cid = docker(['ps','-a','-q','--filter','label=com.docker.compose.project='+project,
                  '--filter','label=com.docker.compose.service=api']).splitlines()
    if len(cid)!=1:raise RuntimeError('DOCKER_API_CONTAINER_REQUIRED')
    api = inspect(cid[0])
    mounts = {v['Destination']:v for v in api.get('Mounts',[])}
    data, control = mounts.get('/data',{}), mounts.get('/run/pengucoach-maintenance',{})
    if not data.get('Name') or not control.get('Name'):raise RuntimeError('DOCKER_MANAGED_VOLUMES_REQUIRED')
    return own,project,root,files,data['Name'],control['Name']


def setup_docker():
    CONTROL.mkdir(parents=True,exist_ok=True)
    with (CONTROL/'.setup.lock').open('a+') as lock:
        # Compose up and an explicit repair run may overlap; join the same setup.
        fcntl.flock(lock,fcntl.LOCK_EX)
        status = CONTROL/'setup.json'
        try:
            own,project,root,files,data,socket_volume = docker_context()
            name, state = 'pengucoach-maintenance-'+project, project+'_maintenance_state'
            image = own['Config']['Image']
            if not image:raise RuntimeError('DOCKER_SETUP_IMAGE_REQUIRED')
            signature=hashlib.sha256(json.dumps([root,files,data,socket_volume]).encode()).hexdigest()
            existing = None
            try:existing = inspect(name)
            except RuntimeError:pass
            if (existing and existing.get('State',{}).get('Running') and existing.get('Image')==own.get('Image')
                    and (existing.get('Config',{}).get('Labels') or {}).get('io.pengucoach.maintenance.config')==signature
                    ):
                current='ready' if agent_available(CONTROL/'control.sock') else 'running'
                status_file(status,current,'docker');return current
            status_file(status,'running','docker')
            docker(['volume','create',state])
            # A separate process holds the operation lock through stop/configure/start.
            # Never kill an agent in the middle of a WebUI or shell maintenance job.
            config = dict(deployment='docker',project=root,environment=root+'/.env',compose_files=files,
                          data='/app-data',state='/state',socket='/control/control.sock',compose_project=project,
                          repository=REPOSITORY,program='/opt/pengucoach-maintenance/program/pengucoach/maintenance',
                          restart_after_update=True)
            extra = []
            for file in files:
                if not Path(file).is_relative_to(root):extra += ['-v',file+':'+file+':ro']
            worker = r'''
import fcntl,json,os,pathlib,subprocess,sys
payload=json.load(sys.stdin)
with open('/state/operation.lock','a+') as lock:
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit(75)
    name=payload['name'];config=payload['config']
    subprocess.run(['docker','stop',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180)
    path=pathlib.Path('/state/config.json')
    previous=json.loads(path.read_text()) if path.exists() else {}
    config['branch']=previous.get('branch','main')
    fd=os.open(str(path)+'.new',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:os.chmod(str(path)+'.new',0o600);json.dump(config,out)
    pathlib.Path(str(path)+'.new').replace(path)
    subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    args=['docker','run','-d','--name',name,'--restart','unless-stopped',
          '--label','io.pengucoach.maintenance.config='+payload['signature'],
          '-v','/var/run/docker.sock:/var/run/docker.sock','-v',config['project']+':'+config['project'],
          *payload['extra'],'-v',payload['data']+':/app-data','-v',payload['socket']+':/control',
          '-v',payload['state']+':/state',payload['image']]
    subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180)
'''
            request = dict(name=name,config=config,image=image,extra=extra,data=data,socket=socket_volume,state=state,signature=signature)
            # Its exit code distinguishes an active operation from a setup error.
            result = subprocess.run(['docker','run','--rm','-i','--entrypoint','python3',
                '-v',state+':/state','-v','/var/run/docker.sock:/var/run/docker.sock',image,'-c',worker],
                input=json.dumps(request).encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=600)
            if result.returncode==75:
                status_file(status,'deferred','docker','MAINTENANCE_BUSY')
                print('[PenguCoach] Existing maintenance job continues; helper replacement deferred.',flush=True)
                return 'deferred'
            if result.returncode or not wait_agent(CONTROL/'control.sock'):
                raise RuntimeError('DOCKER_MAINTENANCE_SETUP_FAILED')
            status_file(status,'ready','docker')
            print('[PenguCoach] Docker system maintenance configured automatically: '+name,flush=True)
            return 'ready'
        except Exception:
            status_file(status,'failed','docker','DOCKER_MAINTENANCE_SETUP_FAILED')
            print('[PenguCoach] Automatic Docker maintenance setup failed. Inspect maintenance-setup logs.',file=sys.stderr,flush=True)
            return 'failed'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('deployment',choices=['native','docker'])
    parser.add_argument('--project',default=str(PROJECT))
    args = parser.parse_args()
    state = ensure_native(args.project) if args.deployment=='native' else setup_docker()
    raise SystemExit(1 if state in {'failed','skipped'} else 0)


if __name__=='__main__':main()
