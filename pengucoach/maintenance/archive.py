"""Authenticated, streaming backup encryption and strict tar validation.

Format (unchanged since Alpha.73): MAGIC + salt + nonce, followed by AES-GCM
frames of at most CHUNK plaintext bytes and an authenticated empty end frame.
The plaintext is a gzip-compressed tar with database.pgdump, environment.json,
data/... and manifest.json. Alpha.75 writes the manifest last and streams the
whole pipeline, so no plaintext copy of the stored files is kept on disk.
Archives written by Alpha.73/74 (manifest first) remain fully readable.
"""
import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import tarfile
import zlib
from datetime import datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b'PENGUCOACH-BACKUP-1\n'
CHUNK = 1024 * 1024
MAX_BYTES = 100 * 1024**3
MAX_FILES = 250000
# Runtime state that is never stored or restored.
EXCLUDED = {'backups', 'celerybeat-schedule', 'celerybeat-schedule.db', 'celerybeat-schedule.dat',
            'celerybeat-schedule.bak', 'celerybeat-schedule.dir', '.maintenance-rollback'}
# Application data stored below PENGUCOACH_DATA_DIR. Everything else in that
# directory (service-user home files, build caches, legacy shell backups) is
# deliberately not part of a full backup and is left untouched by a restore.
DATA_INCLUDE = ('fit', 'parquet', 'user-assets', 'exports')
REQUIRED = {'database.pgdump', 'environment.json'}
SPACE_CHECK_BYTES = 64 * 1024**2


def digest(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(password.encode())


def free_bytes(path):
    path = Path(path)
    while not path.exists() and path != path.parent:path = path.parent
    return shutil.disk_usage(path).free


def space_guard(path, reserve):
    """Return a callable that aborts before a write fills the filesystem."""
    def check():
        if free_bytes(path) < reserve:raise ValueError('MAINTENANCE_DISK_SPACE')
    return check


class EncryptingWriter(io.RawIOBase):
    """Write-only stream that emits authenticated frames to a new file."""

    def __init__(self, target, password, guard=None):
        super().__init__()
        self.target = Path(target)
        salt, self.nonce = os.urandom(16), os.urandom(8)
        self.header = MAGIC + salt + self.nonce
        self.cipher = AESGCM(key(password, salt))
        self.out = open(self.target, 'xb')
        os.chmod(self.target, 0o600)
        self.out.write(self.header)
        self.buffer = bytearray()
        self.index = 0
        self.guard = guard
        self.since_check = 0

    def writable(self):return True

    def _frame(self, block):
        counter = struct.pack('>I', self.index)
        encrypted = self.cipher.encrypt(self.nonce + counter, bytes(block), self.header + counter)
        self.out.write(struct.pack('>I', len(encrypted)))
        self.out.write(encrypted)
        self.index += 1
        self.since_check += len(block)
        if self.guard and self.since_check >= SPACE_CHECK_BYTES:
            self.since_check = 0
            self.guard()

    def write(self, data):
        self.buffer.extend(data)
        while len(self.buffer) >= CHUNK:
            self._frame(self.buffer[:CHUNK])
            del self.buffer[:CHUNK]
        return len(data)

    def finish(self):
        if self.buffer:self._frame(self.buffer)
        self.buffer = bytearray()
        self._frame(b'')  # Authenticated end marker detects truncation.
        self.out.flush();os.fsync(self.out.fileno());self.out.close()

    def abort(self):
        try:self.out.close()
        finally:self.target.unlink(missing_ok=True)


class DecryptingReader(io.RawIOBase):
    """Read-only plaintext view of an encrypted backup; rejects any damage."""

    def __init__(self, source, password):
        super().__init__()
        self.src = open(source, 'rb')
        header = self.src.read(len(MAGIC) + 24)
        if len(header) != len(MAGIC) + 24 or not header.startswith(MAGIC):
            self.src.close();raise ValueError('BACKUP_FORMAT_INVALID')
        self.header = header
        salt, self.nonce = header[len(MAGIC):len(MAGIC)+16], header[-8:]
        self.cipher = AESGCM(key(password, salt))
        self.index = 0
        self.total = 0
        self.buffer = b''
        self.ended = False

    def readable(self):return True

    def _next(self):
        length = self.src.read(4)
        if len(length) != 4:raise ValueError('BACKUP_TRUNCATED')
        length = struct.unpack('>I', length)[0]
        if not 16 <= length <= CHUNK + 16:raise ValueError('BACKUP_FORMAT_INVALID')
        block = self.src.read(length)
        if len(block) != length:raise ValueError('BACKUP_TRUNCATED')
        counter = struct.pack('>I', self.index)
        try:plain = self.cipher.decrypt(self.nonce + counter, block, self.header + counter)
        except InvalidTag:raise ValueError('BACKUP_PASSWORD_OR_INTEGRITY_INVALID') from None
        self.index += 1
        if not plain:
            if self.src.read(1):raise ValueError('BACKUP_TRAILING_DATA')
            self.ended = True
            return
        self.total += len(plain)
        if self.total > MAX_BYTES + 1024**3:raise ValueError('BACKUP_TOO_LARGE')
        self.buffer = plain

    def readinto(self, target):
        while not self.buffer and not self.ended:self._next()
        if not self.buffer:return 0
        size = min(len(target), len(self.buffer))
        target[:size] = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return size

    def drain(self):
        """Authenticate every remaining frame, including the end marker."""
        while not self.ended:
            self.buffer = b''
            self._next()
        self.buffer = b''

    def close(self):
        try:self.src.close()
        finally:super().close()


class HashingReader:
    def __init__(self, stream):
        self.stream, self.hash, self.count = stream, hashlib.sha256(), 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data);self.count += len(data)
        return data

    def hexdigest(self):return self.hash.hexdigest()


class BackupWriter:
    """Single pass: files -> tar -> gzip -> encryption. Manifest is written last."""

    def __init__(self, target, password, guard=None):
        self.target = Path(target)
        self.raw = EncryptingWriter(self.target, password, guard)
        self.tar = tarfile.open(fileobj=self.raw, mode='w|gz', format=tarfile.PAX_FORMAT)
        self.files = {}

    def add(self, name, size, stream, mtime=0):
        if name in self.files or name == 'manifest.json':raise ValueError('BACKUP_DUPLICATE_PATH')
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = size, 0o600, int(mtime)
        reader = HashingReader(stream)
        self.tar.addfile(info, reader)
        if reader.count != size:raise ValueError('BACKUP_FILE_CHANGED')
        self.files[name] = {'size':size, 'sha256':reader.hexdigest()}

    def add_file(self, name, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):raise ValueError('BACKUP_SPECIAL_FILE_NOT_SUPPORTED')
            self.add(name, info.st_size, source, info.st_mtime)
            # A file growing while services are paused would make the copy inconsistent.
            if source.read(1):raise ValueError('BACKUP_FILE_CHANGED')

    def finish(self, metadata):
        manifest = {'format':1, **{k:v for k,v in metadata.items() if k not in {'format','files'}}, 'files':self.files}
        data = json.dumps(manifest, ensure_ascii=False).encode()
        info = tarfile.TarInfo('manifest.json');info.size, info.mode = len(data), 0o600
        self.tar.addfile(info, io.BytesIO(data))
        self.tar.close()
        self.raw.finish()
        return manifest

    def abort(self):
        self.raw.abort()


def data_entries(data):
    """Files of the application data set, as (archive name, path) pairs."""
    data = Path(data)
    for top in DATA_INCLUDE:
        base = data / top
        if base.is_symlink():raise ValueError('BACKUP_SYMLINK_NOT_SUPPORTED')
        if not base.exists():continue
        if not base.is_dir():raise ValueError('BACKUP_SPECIAL_FILE_NOT_SUPPORTED')
        for root, dirs, files in os.walk(base):
            dirs.sort();files.sort()
            for name in dirs:
                if (Path(root) / name).is_symlink():raise ValueError('BACKUP_SYMLINK_NOT_SUPPORTED')
            for name in files:
                path = Path(root) / name
                yield 'data/' + path.relative_to(data).as_posix(), path


def write_backup(target, password, metadata, entries, guard=None):
    writer = BackupWriter(target, password, guard)
    try:
        for name, path in entries:writer.add_file(name, path)
        return writer.finish(metadata)
    except BaseException:
        writer.abort()
        raise


def _safe_member(member):
    parts = PurePosixPath(member.name).parts
    if (not member.isfile() or not parts or member.name.startswith('/') or '\\' in member.name
            or any(p in {'.', '..'} for p in parts) or ':' in member.name
            or str(PurePosixPath(member.name)) != member.name):
        raise ValueError('BACKUP_UNSAFE_PATH')
    if member.name == 'manifest.json':return
    if member.name not in REQUIRED and not member.name.startswith('data/'):raise ValueError('BACKUP_UNSAFE_PATH')
    # Alpha.73/74 archives may also contain top-level data files (for example
    # service-user dotfiles). They stay readable; restore installs DATA_INCLUDE only.
    if member.name.startswith('data/') and len(parts) < 2:raise ValueError('BACKUP_UNSAFE_PATH')
    if member.name.startswith('data/') and parts[1] in EXCLUDED:raise ValueError('BACKUP_RUNTIME_STATE_FORBIDDEN')
    if member.name == 'environment.json' and member.size > 4*1024**2:raise ValueError('BACKUP_ENVIRONMENT_TOO_LARGE')


def _check_manifest(manifest, seen):
    if not isinstance(manifest, dict):raise ValueError('BACKUP_FORMAT_INVALID')
    files = manifest.get('files')
    if manifest.get('format') != 1 or not isinstance(files, dict):raise ValueError('BACKUP_FORMAT_INVALID')
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+_-]{0,79}', str(manifest.get('app_version', ''))):raise ValueError('BACKUP_VERSION_INVALID')
    try:datetime.fromisoformat(manifest['created_at'])
    except (ValueError, KeyError, TypeError):raise ValueError('BACKUP_DATE_INVALID') from None
    if set(seen) != set(files):raise ValueError('BACKUP_FILE_LIST_INVALID')
    if not REQUIRED <= set(files):raise ValueError('BACKUP_INCOMPLETE')
    for name, actual in seen.items():
        expected = files[name]
        if not isinstance(expected, dict):raise ValueError('BACKUP_FILE_LIST_INVALID')
        if expected.get('size') != actual['size']:raise ValueError('BACKUP_SIZE_INVALID')
        if expected.get('sha256') != actual['sha256']:raise ValueError('BACKUP_HASH_INVALID')
    return {k:v for k, v in manifest.items() if k in {'format','app_version','created_at','deployment','files'}}


def _check_environment(data):
    try:environment = json.loads(data)
    except ValueError:raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING') from None
    if (not isinstance(environment, dict) or not environment.get('PENGUCOACH_ENCRYPTION_KEY')
            or any(not isinstance(v, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', k) for k, v in environment.items())):
        raise ValueError('BACKUP_ENCRYPTION_KEY_MISSING')


def read_backup(source, password, *, extract_to=None, writer=None, guard=None):
    """Decrypt and fully validate a backup in one streaming pass.

    extract_to: write the payload below this directory (restore).
    writer: re-encrypt the payload into a BackupWriter (export).
    Without both, the archive is only verified (inspection).
    Returns the validated manifest. On any error nothing is trusted; callers
    remove partially extracted or re-encrypted output.
    """
    if extract_to and writer:raise ValueError('BACKUP_MODE_INVALID')
    reader = DecryptingReader(source, password)
    destination = Path(extract_to) if extract_to else None
    if destination:destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    seen, manifest, environment, count, total, written = {}, None, None, 0, 0, 0
    try:
        with tarfile.open(fileobj=reader, mode='r|gz') as tar:
            for member in tar:
                count += 1;total += max(member.size, 0)
                if count > MAX_FILES or total > MAX_BYTES:raise ValueError('BACKUP_TOO_LARGE')
                _safe_member(member)
                if member.name in seen or (member.name == 'manifest.json' and manifest is not None):
                    raise ValueError('BACKUP_DUPLICATE_PATH')
                stream = tar.extractfile(member)
                if member.name == 'manifest.json':
                    if member.size > 16*1024**2:raise ValueError('BACKUP_MANIFEST_TOO_LARGE')
                    try:manifest = json.loads(stream.read())
                    except ValueError:raise ValueError('BACKUP_FORMAT_INVALID') from None
                    continue
                if member.name == 'environment.json':
                    environment = stream.read(member.size + 1)
                    if len(environment) != member.size:raise ValueError('BACKUP_SIZE_INVALID')
                    stream = io.BytesIO(environment)
                hashing = HashingReader(stream)
                if writer:
                    writer.add(member.name, member.size, hashing, member.mtime)
                elif destination:
                    path = destination / member.name
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with path.open('xb') as out:
                        os.chmod(path, 0o600)
                        while block := hashing.read(CHUNK):
                            out.write(block);written += len(block)
                            if guard and written >= SPACE_CHECK_BYTES:written = 0;guard()
                while hashing.read(CHUNK):pass
                if hashing.count != member.size:raise ValueError('BACKUP_SIZE_INVALID')
                seen[member.name] = {'size':member.size, 'sha256':hashing.hexdigest()}
        reader.drain()
    except (tarfile.TarError, zlib.error, EOFError):
        raise ValueError('BACKUP_FORMAT_INVALID') from None
    finally:
        reader.close()
    if manifest is None:raise ValueError('BACKUP_FORMAT_INVALID')
    result = _check_manifest(manifest, seen)
    if environment is None:raise ValueError('BACKUP_INCOMPLETE')
    _check_environment(environment)
    return result


# --- Alpha.73 file-based helpers, kept for compatibility and tests ---------

def encrypt(source, target, password):
    writer = EncryptingWriter(target, password)
    try:
        with open(source, 'rb') as src:
            while block := src.read(CHUNK):writer.write(block)
        writer.finish()
    except BaseException:
        writer.abort()
        raise


def decrypt(source, target, password):
    reader = DecryptingReader(source, password)
    try:
        with open(target, 'xb') as dst:
            os.chmod(target, 0o600)
            while block := reader.read(CHUNK):dst.write(block)
            reader.drain()
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise
    finally:
        reader.close()


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
            if declared > MAX_BYTES or len(members) >= MAX_FILES:raise ValueError('BACKUP_TOO_LARGE')
            members.append(member)
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
        if not REQUIRED <= set(files):raise ValueError('BACKUP_INCOMPLETE')
        total = 0
        for member in members:
            if member.name == 'manifest.json':continue
            if member.name not in REQUIRED and not member.name.startswith('data/'):
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
        _check_environment((destination/'environment.json').read_text())
        return manifest
