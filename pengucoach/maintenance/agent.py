"""Root-owned host agent. Listens on a permission-controlled Unix socket only."""
import argparse
import fcntl
import http.server
import json
import os
import re
import socketserver
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from . import archive
from .engine import Engine, atomic_json, identifier, utc

MAX_CHUNK = 8*1024**2


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(15)

    def log_message(self,*args):pass

    def json(self, value, code=200):
        data = json.dumps(value,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)

    def body(self, maximum=65536):
        try:length = int(self.headers.get('Content-Length','-1'))
        except ValueError:raise ValueError('CONTENT_LENGTH_REQUIRED') from None
        if not 0 <= length <= maximum:raise ValueError('REQUEST_TOO_LARGE')
        value = self.rfile.read(length)
        if len(value) != length:raise ValueError('UPLOAD_INCOMPLETE')
        return value

    def do_GET(self):
        engine = self.server.engine
        try:
            path = urlsplit(self.path).path
            if path == '/status':return self.json(engine.status())
            if path == '/update':
                refresh = parse_qs(urlsplit(self.path).query).get('refresh',['0'])[0] == '1'
                return self.json(engine.update_preview(refresh=refresh))
            upload=re.fullmatch(r'/uploads/([a-f0-9]{32})',path)
            if upload:
                file=engine.state/'uploads'/(upload[1]+'.partial')
                return self.json({'id':upload[1],'offset':file.stat().st_size})
            match = re.fullmatch(r'/backups/([a-f0-9]{32})/download',path)
            if match:
                file, info = engine.source_backup(match[1])
                if info.get('automatic'):raise ValueError('BACKUP_EXPORT_PASSWORD_REQUIRED')
                self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                self.send_header('Content-Length',str(file.stat().st_size))
                self.send_header('Content-Disposition',f'attachment; filename="PenguCoach-{match[1]}.pcbackup"')
                self.send_header('Cache-Control','no-store');self.end_headers()
                with file.open('rb') as source:
                    while block := source.read(archive.CHUNK):self.wfile.write(block)
                return
            self.json({'detail':'NOT_FOUND'},404)
        except (ValueError,FileNotFoundError) as exc:self.json({'detail':str(exc) if isinstance(exc,ValueError) else 'NOT_FOUND'},400)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_DELETE(self):
        engine = self.server.engine
        try:
            match = re.fullmatch(r'/backups/([a-f0-9]{32})',urlsplit(self.path).path)
            if not match or json.loads(self.body()).get('confirmation') != 'DELETE':raise ValueError('CONFIRMATION_REQUIRED')
            engine.acquire()
            try:
                file, _ = engine.source_backup(match[1])
                file.unlink();file.with_suffix('.json').unlink()
            finally:engine.release()
            self.json({'deleted':True})
        except (ValueError,FileNotFoundError) as exc:
            detail = str(exc) if isinstance(exc,ValueError) else 'BACKUP_NOT_FOUND'
            self.json({'detail':detail},409 if detail=='MAINTENANCE_BUSY' else 400)

    def do_POST(self):
        engine = self.server.engine
        try:
            path = urlsplit(self.path).path
            if path == '/jobs':
                payload = json.loads(self.body())
                if not isinstance(payload,dict):raise ValueError('REQUEST_INVALID')
                return self.json(engine.submit(payload),202)
            if path == '/uploads':
                payload = json.loads(self.body())
                size = payload.get('size')
                if not isinstance(size,int) or isinstance(size,bool) or not 0 < size <= archive.MAX_BYTES:raise ValueError('BACKUP_SIZE_INVALID')
                uid = uuid.uuid4().hex
                # Partial uploads are private and expire, keeping abandoned files bounded.
                for old in (engine.state/'uploads').glob('*.json'):
                    partial = old.with_suffix('.partial')
                    # Expire by last activity, not by start: large uploads may take long.
                    active = max(old.stat().st_mtime,partial.stat().st_mtime if partial.exists() else 0)
                    if time.time()-active>86400:
                        old.with_suffix('.partial').unlink(missing_ok=True);old.unlink(missing_ok=True)
                if sum(p.stat().st_size for p in (engine.state/'uploads').glob('*.partial'))+size > archive.MAX_BYTES:
                    raise ValueError('UPLOAD_STORAGE_LIMIT')
                file = engine.state/'uploads'/(uid+'.partial')
                fd = os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
                atomic_json(file.with_suffix('.json'),{'id':uid,'size':size})
                return self.json({'id':uid,'chunk_bytes':MAX_CHUNK},201)
            match = re.fullmatch(r'/uploads/([a-f0-9]{32})(/complete)?',path)
            if match:
                uid = identifier(match[1]);file = engine.state/'uploads'/(uid+'.partial')
                info = json.loads(file.with_suffix('.json').read_text())
                if match[2]:
                    with file.open('r+b') as out:
                        fcntl.flock(out,fcntl.LOCK_EX)
                        if file.stat().st_size != info['size']:raise ValueError('UPLOAD_INCOMPLETE')
                        out.flush();os.fsync(out.fileno())
                        target = engine.state/'backups'/(uid+'.pcbackup');file.replace(target)
                    atomic_json(target.with_suffix('.json'),{'id':uid,'created_at':utc(),'imported':True,'automatic':False})
                    file.with_suffix('.json').unlink()
                    return self.json({'id':uid})
                offset = int(parse_qs(urlsplit(self.path).query).get('offset',['-1'])[0])
                if file.stat().st_size != offset:raise ValueError('UPLOAD_OFFSET_INVALID')
                block = self.body(MAX_CHUNK)
                if offset+len(block)>info['size']:raise ValueError('BACKUP_SIZE_INVALID')
                with file.open('r+b') as out:
                    fcntl.flock(out,fcntl.LOCK_EX)
                    out.seek(0,os.SEEK_END)
                    if out.tell()!=offset:raise ValueError('UPLOAD_OFFSET_INVALID')
                    out.write(block)
                os.utime(file.with_suffix('.json'))
                return self.json({'id':uid,'offset':offset+len(block)})
            self.json({'detail':'NOT_FOUND'},404)
        except (ValueError,KeyError,FileNotFoundError) as exc:
            message = str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]+',str(exc)) else 'REQUEST_INVALID'
            self.json({'detail':message},409 if message=='MAINTENANCE_BUSY' else 400)
        except Exception:self.json({'detail':'MAINTENANCE_AGENT_ERROR'},500)


def serve(config):
    engine = Engine(config)
    engine.recover()
    engine.startup()
    socket = Path(config['socket']);socket.parent.mkdir(parents=True,exist_ok=True)
    socket.unlink(missing_ok=True)
    with Server(str(socket),Handler) as server:
        server.engine = engine
        os.chmod(socket,0o660)
        if config.get('socket_gid') is not None:os.chown(socket,0,int(config['socket_gid']))
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--config',default='/etc/pengucoach-maintenance.json')
    args = parser.parse_args()
    serve(json.loads(Path(args.config).read_text()))
