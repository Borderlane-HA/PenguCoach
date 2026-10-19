"""Authenticated, streaming backup encryption and strict tar validation."""
import hashlib
import json
import os
import re
from datetime import datetime
import struct
import tarfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b'PENGUCOACH-BACKUP-1\n'
CHUNK = 1024 * 1024
MAX_BYTES = 100 * 1024**3
EXCLUDED = {'backups', 'celerybeat-schedule', 'celerybeat-schedule.db', 'celerybeat-schedule.dat',
            'celerybeat-schedule.bak', 'celerybeat-schedule.dir', '.maintenance-rollback'}


def digest(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(password.encode())


def encrypt(source, target, password):
    salt, nonce = os.urandom(16), os.urandom(8)
    header = MAGIC + salt + nonce
    cipher = AESGCM(key(password, salt))
    with open(source, 'rb') as src, open(target, 'xb') as dst:
        os.chmod(target, 0o600)
        dst.write(header)
        index = 0
        while True:
            block = src.read(CHUNK)
            counter = struct.pack('>I', index)
            encrypted = cipher.encrypt(nonce + counter, block, header + counter)
            dst.write(struct.pack('>I', len(encrypted)))
            dst.write(encrypted)
            if not block:break  # Authenticated end marker detects truncation.
            index += 1


def decrypt(source, target, password):
    try:
        with open(source, 'rb') as src, open(target, 'xb') as dst:
            os.chmod(target, 0o600)
            header = src.read(len(MAGIC) + 24)
            if len(header) != len(MAGIC) + 24 or not header.startswith(MAGIC):
                raise ValueError('BACKUP_FORMAT_INVALID')
            salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[-8:]
            cipher, index, total = AESGCM(key(password, salt)), 0, 0
            while True:
                length = src.read(4)
                if len(length) != 4:raise ValueError('BACKUP_TRUNCATED')
                length = struct.unpack('>I', length)[0]
                if not 16 <= length <= CHUNK + 16:raise ValueError('BACKUP_FORMAT_INVALID')
                block = src.read(length)
                if len(block) != length:raise ValueError('BACKUP_TRUNCATED')
                counter = struct.pack('>I', index)
                plain = cipher.decrypt(nonce + counter, block, header + counter)
                if not plain:
                    if src.read(1):raise ValueError('BACKUP_TRAILING_DATA')
                    break
                total += len(plain)
                if total > MAX_BYTES:raise ValueError('BACKUP_TOO_LARGE')
                dst.write(plain)
                index += 1
    except InvalidTag:
        Path(target).unlink(missing_ok=True)
        raise ValueError('BACKUP_PASSWORD_OR_INTEGRITY_INVALID') from None
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise


def pack(stage, target, metadata):
    stage = Path(stage)
    files = {}
    for path in sorted(stage.rglob('*')):
        if path.is_symlink():raise ValueError('BACKUP_SYMLINK_NOT_SUPPORTED')
        if path.is_file() and path != stage/'manifest.json':files[path.relative_to(stage).as_posix()] = {'size':path.stat().st_size, 'sha256':digest(path)}
    manifest = {'format':1, **metadata, 'files':files}
    (stage/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False))
    with tarfile.open(target, 'w:gz') as archive:
        for name in ['manifest.json', *files]:
            archive.add(stage/name, arcname=name, recursive=False)
    return manifest


def unpack(source, destination):
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(source, 'r:gz') as archive:
        members = []
        declared = 0
        for member in archive:
            declared += member.size
            if declared > MAX_BYTES or len(members) >= 250000:raise ValueError('BACKUP_TOO_LARGE')
            members.append(member)
        if len(members) > 250000:raise ValueError('BACKUP_TOO_MANY_FILES')
        names = [m.name for m in members]
        if len(set(names)) != len(names):raise ValueError('BACKUP_DUPLICATE_PATH')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not member.isfile() or not parts or member.name.startswith('/') or '\\' in member.name
                    or any(p in {'.','..'} for p in parts) or ':' in member.name
                    or str(PurePosixPath(member.name)) != member.name):
                raise ValueError('BACKUP_UNSAFE_PATH')
        entry = archive.getmember('manifest.json')
        if entry.size > 16*1024**2:raise ValueError('BACKUP_MANIFEST_TOO_LARGE')
        manifest = json.load(archive.extractfile(entry))
        if not isinstance(manifest,dict):raise ValueError('BACKUP_FORMAT_INVALID')
        files = manifest.get('files')
        if manifest.get('format') != 1 or not isinstance(files, dict):raise ValueError('BACKUP_FORMAT_INVALID')
        if not re.fullmatch(r'[0-9][A-Za-z0-9.+_-]{0,79}',str(manifest.get('app_version',''))):raise ValueError('BACKUP_VERSION_INVALID')
        try:datetime.fromisoformat(manifest['created_at'])
        except (ValueError,KeyError,TypeError):raise ValueError('BACKUP_DATE_INVALID') from None
        manifest={k:v for k,v in manifest.items() if k in {'format','app_version','created_at','deployment','files'}}
        if set(names) != {'manifest.json', *files}:raise ValueError('BACKUP_FILE_LIST_INVALID')
        if not {'database.pgdump','environment.json'} <= set(files):raise ValueError('BACKUP_INCOMPLETE')
        total = 0
        for member in members:
            if member.name == 'manifest.json':continue
            if member.name not in {'database.pgdump','environment.json'} and not member.name.startswith('data/'):
                raise ValueError('BACKUP_UNSAFE_PATH')
            if member.name.startswith('data/') and PurePosixPath(member.name).parts[1] in EXCLUDED:
                raise ValueError('BACKUP_RUNTIME_STATE_FORBIDDEN')
            expected = files[member.name]
            total += member.size
            if not isinstance(expected,dict):raise ValueError('BACKUP_FILE_LIST_INVALID')
            if member.name=='environment.json' and member.size>4*1024**2:raise ValueError('BACKUP_ENVIRONMENT_TOO_LARGE')
            if member.size != expected.get('size') or total > MAX_BYTES:raise ValueError('BACKUP_SIZE_INVALID')
            path = destination/member.name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.extractfile(member) as src, path.open('xb') as dst:
                os.chmod(path, 0o600)
                while block := src.read(CHUNK):dst.write(block)
            if digest(path) != expected.get('sha256'):raise ValueError('BACKUP_HASH_INVALID')
        (destination/'manifest.json').write_text(json.dumps(manifest))
        environment = json.loads((destination/'environment.json').read_text())
        if (not isinstance(environment,dict) or not environment.get('PENGUCOACH_ENCRYPTION_KEY')
                or any(not isinstance(v,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*',k) for k,v in environment.items())):
            raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING')
        return manifest
