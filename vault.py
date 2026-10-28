"""Finance Hub 1.2 — user accounts and an encrypted database.

How it protects the data
  • The database lives on disk only as  finance.db.enc  — AES-256-GCM encrypted (authenticated: any change to the
    file is detected). It is decrypted into memory after a successful login and never written to disk in clear.
  • Every user has a separate database (data/<id>.enc) with its own random 256-bit key — users never see each
    other's data. A user's password unlocks that key:
    key-encryption key = PBKDF2-HMAC-SHA256(password, random salt, 600 000 rounds) → AES-256-GCM wraps the data key.
    Passwords themselves are never stored.
  • Each user gets a recovery key (shown once) that also unlocks their key — keep it on paper; without the password
    or the recovery key nobody (not even an administrator) can open that user's data.
  • users.json holds only salts and wrapped keys; copying the app folder gives nothing readable.
  • Import previews waiting for confirmation are sealed with the same key.
  • The app is locked after a period of inactivity and on restart; it listens only on this computer (127.0.0.1).
"""
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

MAGIC = b'FHUBENC1'
ITERATIONS = 600_000
ROLES = {'admin': 'Administrator (can add / remove users)', 'member': 'User'}


def _b64(b):
    return base64.b64encode(b).decode()


def _unb64(s):
    return base64.b64decode(s.encode())


def kek(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations, 32)


def wrap(key: bytes, secret: bytes, aad: bytes = b'') -> str:
    n = secrets.token_bytes(12)
    return _b64(n + AESGCM(key).encrypt(n, secret, aad))


def unwrap(key: bytes, blob: str, aad: bytes = b'') -> bytes:
    raw = _unb64(blob)
    return AESGCM(key).decrypt(raw[:12], raw[12:], aad)


def new_recovery_key() -> str:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    raw = ''.join(secrets.choice(alphabet) for _ in range(28))
    return '-'.join(raw[i:i + 4] for i in range(0, 28, 4))


def norm_recovery(s: str) -> str:
    return ''.join(ch for ch in (s or '').upper() if ch.isalnum())


class Conn:
    """A connection-like view of the single in-memory database (row factory per caller; close() is harmless)."""

    def __init__(self, vault):
        object.__setattr__(self, '_v', vault)
        object.__setattr__(self, 'row_factory', None)

    @property
    def _con(self):
        c = self._v.con
        if c is None:
            raise sqlite3.OperationalError('Finance Hub is locked — log in first.')
        return c

    def cursor(self):
        c = self._con.cursor()
        c.row_factory = self.row_factory
        return c

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

    def executescript(self, script):
        return self.cursor().executescript(script)

    def commit(self):
        self._con.commit()

    def rollback(self):
        self._con.rollback()

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, et, e, tb):
        if et is None:
            self.commit()
        else:
            self.rollback()
        return False

    def __getattr__(self, name):
        return getattr(self._con, name)


class Vault:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.data_dir = self.base / 'data'
        self.users_path = self.base / 'users.json'
        self.plain_path = self.base / 'finance.db'
        self.con = None
        self.dek = None
        self.user = None
        self.nonce = ''
        self.last = 0.0
        self.saved_changes = 0
        self.lock = threading.RLock()
        self.failed = {}

    # ── users file ──────────────────────────────────────────────────────────
    def users_doc(self):
        if not self.users_path.exists():
            return {'version': 2, 'users': {}, 'settings': {'idle_minutes': 30}}
        return json.loads(self.users_path.read_text(encoding='utf-8'))

    def save_users(self, doc):
        tmp = self.users_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(doc, indent=1), encoding='utf-8')
        os.replace(tmp, self.users_path)

    def is_setup(self):
        return self.users_path.exists() and bool(self.users_doc().get('users'))

    @property
    def unlocked(self):
        return self.con is not None and self.dek is not None

    @property
    def enc_path(self):
        u = self.users_doc()['users'].get(self.user or '')
        return self.data_dir / (u['db'] if u else 'none.enc')

    @property
    def files_dir(self):
        """1.5: folder for this user's sealed files (mail attachments waiting for review)."""
        d = self.data_dir / (self.enc_path.stem + '_files')
        d.mkdir(exist_ok=True)
        return d

    def db_path_for(self, username):
        return self.data_dir / self.users_doc()['users'][username]['db']

    def idle_minutes(self):
        return int(self.users_doc().get('settings', {}).get('idle_minutes', 30) or 0)

    # ── database file ───────────────────────────────────────────────────────
    def _encrypt_db(self, data: bytes, dek=None) -> bytes:
        n = secrets.token_bytes(12)
        return MAGIC + n + AESGCM(dek or self.dek).encrypt(n, zlib.compress(data, 6), MAGIC)

    def _decrypt_db(self, blob: bytes, dek: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            raise ValueError('not a Finance Hub encrypted database')
        n = blob[len(MAGIC):len(MAGIC) + 12]
        return zlib.decompress(AESGCM(dek).decrypt(n, blob[len(MAGIC) + 12:], MAGIC))

    def persist(self, force=False):
        """Write the in-memory database to the user's .enc file (atomic replace, keeps one previous copy)."""
        with self.lock:
            if not self.unlocked:
                return False
            if self.con.in_transaction:
                self.con.commit()
            changes = self.con.total_changes
            if not force and changes == self.saved_changes:
                return False
            path = self.enc_path
            blob = self._encrypt_db(self.con.serialize())
            tmp = path.with_suffix('.enc.tmp')
            tmp.write_bytes(blob)
            if path.exists():
                os.replace(path, path.with_suffix('.enc.prev'))
            os.replace(tmp, path)
            self.saved_changes = changes
            return True

    def _load(self, path, dek):
        try:
            data = self._decrypt_db(path.read_bytes(), dek)
        except (InvalidTag, ValueError, zlib.error, FileNotFoundError):
            prev = path.with_suffix('.enc.prev')
            if not prev.exists():
                raise
            data = self._decrypt_db(prev.read_bytes(), dek)       # last good copy (e.g. power cut while saving)
        con = sqlite3.connect(':memory:', check_same_thread=False)
        con.deserialize(data)
        return con

    def _open(self, dek, username):
        path = self.data_dir / self.users_doc()['users'][username]['db']
        self.con = self._load(path, dek)
        self.dek = dek
        self.user = username
        self.nonce = secrets.token_hex(16)
        self.last = time.time()
        self.saved_changes = self.con.total_changes

    def lock_now(self):
        with self.lock:
            if self.unlocked:
                try:
                    self.persist()
                finally:
                    self.con.close()
            self.con, self.dek, self.user, self.nonce = None, None, None, ''

    def connect(self):
        return Conn(self)

    # ── users ───────────────────────────────────────────────────────────────
    def _new_user(self, doc, username, password, role, full_name=''):
        """New user = new empty encrypted database with its own key (the person's name is stored only inside it)."""
        self.data_dir.mkdir(exist_ok=True)
        dek = secrets.token_bytes(32)
        db = f'{secrets.token_hex(8)}.enc'
        tmp = sqlite3.connect(':memory:')
        tmp.execute('CREATE TABLE IF NOT EXISTS hub_settings (key TEXT PRIMARY KEY, value TEXT)')
        if full_name:
            tmp.execute("INSERT INTO hub_settings (key, value) VALUES ('display_name', ?)", (full_name[:60],))
        tmp.commit()
        empty = tmp.serialize()
        tmp.close()
        (self.data_dir / db).write_bytes(self._encrypt_db(empty, dek))
        salt = secrets.token_bytes(16)
        doc['users'][username] = {'salt': _b64(salt), 'iterations': ITERATIONS, 'role': role, 'db': db,
                                  'key': wrap(kek(password, salt), dek, username.encode()), 'recovery': None,
                                  'created': datetime.now().isoformat(timespec='seconds'), 'last_login': ''}
        return dek

    def _rewrap(self, doc, username, password, dek):
        salt = secrets.token_bytes(16)
        doc['users'][username].update({'salt': _b64(salt), 'iterations': ITERATIONS,
                                       'key': wrap(kek(password, salt), dek, username.encode())})

    def _user_dek(self, doc, username, password):
        u = doc['users'].get(username)
        if not u:
            kek(password, b'0' * 16)            # same time whether or not the user exists
            return None
        try:
            return unwrap(kek(password, _unb64(u['salt']), u.get('iterations', ITERATIONS)), u['key'], username.encode())
        except InvalidTag:
            return None

    def setup(self, username, password, full_name=''):
        """First run: the first user (administrator) and their encrypted database."""
        doc = self.users_doc()
        doc['users'] = {}
        dek = self._new_user(doc, username, password, 'admin', full_name)
        self.save_users(doc)
        self._open(dek, username)
        return self.new_recovery()

    def login(self, username, password):
        """Returns (ok, message). Opening another user's data first saves and closes the current one."""
        username = (username or '').strip()
        wait = self.failed.get(username, (0, 0))
        if wait[0] >= 3 and time.time() - wait[1] < min(300, 5 * 2 ** (wait[0] - 3)):
            return False, 'Too many wrong attempts — wait a few minutes and try again.'
        doc = self.users_doc()
        dek = self._user_dek(doc, username, password)
        if dek is None:
            self.failed[username] = (wait[0] + 1, time.time())
            return False, 'Wrong user ID or password.'
        self.failed.pop(username, None)
        with self.lock:
            if self.unlocked and self.user != username:
                self.lock_now()
            if not self.unlocked:
                self._open(dek, username)
            else:
                self.nonce = secrets.token_hex(16)
                self.last = time.time()
        doc = self.users_doc()
        doc['users'][username]['last_login'] = datetime.now().isoformat(timespec='seconds')
        self.save_users(doc)
        return True, ''

    def needs_recovery_key(self):
        u = self.users_doc()['users'].get(self.user or '')
        return bool(u) and not u.get('recovery')

    def recover(self, username, recovery_key, new_password):
        doc = self.users_doc()
        u = doc['users'].get(username)
        r = u.get('recovery') if u else None
        if not r:
            return False, 'Unknown user, or no recovery key was set for this user.'
        try:
            dek = unwrap(kek(norm_recovery(recovery_key), _unb64(r['salt']), r.get('iterations', ITERATIONS)), r['key'], b'recovery')
        except InvalidTag:
            return False, 'That recovery key does not match.'
        self._rewrap(doc, username, new_password, dek)
        self.save_users(doc)
        return True, ''

    def role(self, username=None):
        return self.users_doc()['users'].get(username or self.user, {}).get('role', 'member')

    def add_user(self, username, password, role, full_name=''):
        doc = self.users_doc()
        if username in doc['users']:
            raise ValueError('that user ID already exists')
        self._new_user(doc, username, password, role if role in ROLES else 'member', full_name)
        self.save_users(doc)

    def set_password(self, username, password):
        """Only for the logged-in user (their key is open)."""
        if username != self.user:
            raise ValueError("a user's password can only be changed by that user (or with their recovery key)")
        doc = self.users_doc()
        self._rewrap(doc, username, password, self.dek)
        self.save_users(doc)

    def set_role(self, username, role):
        doc = self.users_doc()
        if role not in ROLES or username not in doc['users']:
            raise ValueError('bad role or user')
        if doc['users'][username]['role'] == 'admin' and role != 'admin' and \
                sum(1 for u in doc['users'].values() if u['role'] == 'admin') == 1:
            raise ValueError('keep at least one administrator')
        doc['users'][username]['role'] = role
        self.save_users(doc)

    def remove_user(self, username):
        """Removes the user and securely erases their encrypted database."""
        doc = self.users_doc()
        if username not in doc['users']:
            return
        if doc['users'][username]['role'] == 'admin' and sum(1 for u in doc['users'].values() if u['role'] == 'admin') == 1:
            raise ValueError('keep at least one administrator')
        db = self.data_dir / doc['users'][username]['db']
        del doc['users'][username]
        self.save_users(doc)
        for f in (db, db.with_suffix('.enc.prev')):
            if f.exists():
                secure_delete(f)
        files = self.data_dir / (db.stem + '_files')          # 1.5: sealed mail attachments
        if files.is_dir():
            for f in files.rglob('*'):
                if f.is_file():
                    secure_delete(f)
            for d in sorted((x for x in files.rglob('*') if x.is_dir()), reverse=True):
                d.rmdir()
            files.rmdir()

    def new_recovery(self):
        doc = self.users_doc()
        rk = new_recovery_key()
        salt = secrets.token_bytes(16)
        doc['users'][self.user]['recovery'] = {'salt': _b64(salt), 'iterations': ITERATIONS,
                                               'key': wrap(kek(norm_recovery(rk), salt), self.dek, b'recovery'),
                                               'created': datetime.now().isoformat(timespec='seconds')}
        self.save_users(doc)
        return rk

    def set_idle(self, minutes):
        doc = self.users_doc()
        doc.setdefault('settings', {})['idle_minutes'] = max(0, int(minutes))
        self.save_users(doc)

    # ── small encrypted blobs (import previews waiting for confirmation) ───
    def seal(self, obj) -> bytes:
        n = secrets.token_bytes(12)
        return b'FHSEAL1' + n + AESGCM(self.dek).encrypt(n, json.dumps(obj, default=str).encode(), b'seal')

    def seal_bytes(self, data: bytes) -> bytes:
        n = secrets.token_bytes(12)
        return b'FHBLOB1' + n + AESGCM(self.dek).encrypt(n, zlib.compress(data, 6), b'blob')

    def unseal_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(b'FHBLOB1'):
            raise ValueError('not a sealed file')
        return zlib.decompress(AESGCM(self.dek).decrypt(blob[7:19], blob[19:], b'blob'))

    def unseal(self, blob: bytes):
        if not blob.startswith(b'FHSEAL1'):
            return json.loads(blob.decode('utf-8'))       # older plain preview file
        return json.loads(AESGCM(self.dek).decrypt(blob[7:19], blob[19:], b'seal'))


def secure_delete(path: Path) -> bool:
    """Overwrite a file with random bytes, then remove it (best effort — SSDs may keep old blocks)."""
    try:
        p = Path(path)
        size = p.stat().st_size
        with open(p, 'r+b') as f:
            remaining = size
            while remaining > 0:
                chunk = min(remaining, 1 << 20)
                f.write(secrets.token_bytes(chunk))
                remaining -= chunk
            f.flush()
            os.fsync(f.fileno())
        p.unlink()
        return True
    except OSError:
        return False


def plaintext_copies(base: Path):
    """Unencrypted data left in the app folder: old databases and backups, uploaded statements, old previews."""
    base = Path(base)
    out = []
    for p in base.rglob('*'):
        if not p.is_file() or p.parent.name == 'data' and p.suffix in ('.enc', '.prev', '.tmp'):
            continue
        rel = p.relative_to(base).parts
        if rel and rel[0] == 'uploads':
            out.append(p)                      # statement copies and import previews
            continue
        if p.name.startswith('finance.db') or p.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm'):
            try:
                with open(p, 'rb') as f:
                    head = f.read(16)
            except OSError:
                continue
            if head.startswith(b'SQLite format 3') or p.name.endswith(('-wal', '-shm', '-journal')):
                out.append(p)
    return sorted(out)
