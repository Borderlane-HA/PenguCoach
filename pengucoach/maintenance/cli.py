"""Shell entry points share the host engine and its cross-process operation lock."""
import argparse
from contextlib import closing
import getpass
import http.client
import json
import os
import socket
import time
from pathlib import Path

from .engine import Engine


class Connection(http.client.HTTPConnection):
    def __init__(self,path):super().__init__('localhost',timeout=15);self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect(self.path)


def call(config, method, path, value=None):
    with closing(Connection(config['socket'])) as connection:
        connection.request(method,path,json.dumps(value) if value is not None else None,{'Content-Type':'application/json'})
        response=connection.getresponse();body=json.loads(response.read())
        if response.status>=400:raise RuntimeError(body.get('detail','MAINTENANCE_FAILED'))
        return body


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['update','backup','inspect','restore','export','status','recover'])
    parser.add_argument('backup_id',nargs='?');parser.add_argument('--password-file');parser.add_argument('--config',default='/etc/pengucoach-maintenance.json')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run as root on the PenguCoach host.')
    config=json.loads(Path(args.config).read_text())
    if args.operation=='recover':
        engine=Engine(config);engine.recover();print(json.dumps(engine.status(),indent=2));return
    if args.operation=='status':
        try:state=call(config,'GET','/status')
        except (OSError,ConnectionError,http.client.HTTPException):state={**Engine(config).status(),'agent_connected':False}
        print(json.dumps(state,indent=2));return
    payload={'operation':args.operation,'actor':'shell','confirmation':args.operation.upper()}
    if args.backup_id:payload['backup_id']=args.backup_id
    if args.password_file:payload['password']=Path(args.password_file).read_text().rstrip('\r\n')
    elif args.operation in {'restore','inspect','export'}:payload['password']=getpass.getpass('Backup password (empty for a local automatic backup): ')
    elif args.operation=='backup':payload['local']=True
    try:job=call(config,'POST','/jobs',payload)
    except (OSError,ConnectionError,http.client.HTTPException):
        engine=Engine(config);engine.recover();job=engine.submit(payload,asynchronous=False)
    last=None
    while job.get('status') in {'queued','running'}:
        if last!=job.get('message'):print('[PenguCoach] '+job.get('message',''),flush=True);last=job.get('message')
        time.sleep(1)
        try:
            rows=call(config,'GET','/status')['jobs'];job=next(row for row in rows if row['id']==job['id'])
        except (OSError,ConnectionError,http.client.HTTPException):
            # A committed job remains readable even while its service restarts.
            rows=Engine(config).jobs(limit=None)
            job=next((row for row in rows if row['id']==job['id']),job)
    if job.get('status')!='succeeded':raise SystemExit(job.get('error','MAINTENANCE_FAILED'))
    if job.get('backup'):print(str(Path(config['state'])/'backups'/(job['backup']['id']+'.pcbackup')))
    if job.get('inspection'):print(json.dumps(job['inspection'],indent=2))
    if args.operation=='update':print('[PenguCoach] Update completed.')


if __name__=='__main__':main()
