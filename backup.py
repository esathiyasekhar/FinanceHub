"""Finance Hub 1.7 — backup and restore, to OneDrive, Google Drive or any folder.

A backup is one file, FinanceHub_<user ID>_<date>.fhb (a zip), holding:
  manifest.json  version, date, user ID, file hashes
  user.json      that user's entry from users.json — salts and the data key wrapped by the password / recovery key
  db.enc         the encrypted database exactly as on disk (AES-256-GCM)
  files/…        encrypted mail attachments waiting for review
Nothing in it is readable without the user's password (or recovery key), so it is safe in a cloud folder.

OneDrive and Google Drive are used through their folders on this PC (OneDrive, and Google Drive for desktop — e.g.
G:\\My Drive): the Hub writes the backup there and the sync app uploads it. Automatic backups (daily / weekly) run in the
background even while the Hub is locked, because the database file is already encrypted; one is made only when the data
changed since the last backup. Each user's settings are kept in users.json (folder, how often, how many to keep).

Restore:
  * your own data, while logged in — with your current password, or the password you had when the backup was made;
    the present data is backed up to the local backups folder first;
  * on a new computer — from the first-start page ("Restore from a backup"), with the password of that backup.
"""
import hashlib
import io
import json
import os
import re
import shutil
import string
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, send_file, session, g

FOLDER_NAME = 'Finance Hub backups'
EVERY = {'off': 'Only when I click Back up now', 'daily': 'Every day', 'weekly': 'Every week'}
VAULT = None


# ── where ───────────────────────────────────────────────────────────────────
def cloud_folders():
    """Folders of sync apps on this PC → [(label, path)] (only those that exist)."""
    out, seen = [], set()

    def add(label, p):
        try:
            p = Path(p)
            if p.is_dir() and str(p).lower() not in seen:
                seen.add(str(p).lower())
                out.append((label, str(p)))
        except OSError:
            pass
    for var, label in (('OneDriveConsumer', 'OneDrive (personal)'), ('OneDriveCommercial', 'OneDrive (work / school)'),
                       ('OneDrive', 'OneDrive')):
        if os.environ.get(var):
            add(label, os.environ[var])
    home = Path.home()
    add('OneDrive', home / 'OneDrive')
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            add(f'Google Drive ({letter}:)', f'{letter}:\\My Drive')
    add('Google Drive', home / 'Google Drive')
    add('Google Drive', home / 'My Drive')
    add('Dropbox', home / 'Dropbox')
    for extra in filter(None, os.environ.get('FINANCEHUB_CLOUD_DIRS', '').split(os.pathsep)):     # used by the tests
        add('Cloud folder', extra)
    return out


def target_dir(base):
    d = Path(base)
    if d.name != FOLDER_NAME:
        d = d / FOLDER_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── making a backup ─────────────────────────────────────────────────────────
def _entry_for_backup(entry):
    return {k: v for k, v in entry.items() if k in ('salt', 'iterations', 'role', 'db', 'key', 'recovery', 'created')}


def make_backup(vault, username, dest_dir=None, keep=None, persist=True):
    """Write a .fhb for one user. dest_dir None → bytes (for a download). → Path or bytes
    persist=False from the background thread: every request already saved its changes, so the file is current."""
    with vault.lock:
        if persist and vault.unlocked and vault.user == username:
            vault.persist()
        doc = vault.users_doc()
        entry = doc['users'][username]
        db = vault.data_dir / entry['db']
        db_bytes = db.read_bytes()
        files = {}
        fdir = vault.data_dir / (db.stem + '_files')
        if fdir.is_dir():
            for f in fdir.iterdir():
                if f.is_file():
                    files[f.name] = f.read_bytes()
    from hub_version import VERSION
    now = datetime.now()
    manifest = {'app': 'Finance Hub', 'format': 1, 'version': VERSION, 'created': now.isoformat(timespec='seconds'),
                'user': username, 'db': entry['db'], 'sha256': {'db.enc': hashlib.sha256(db_bytes).hexdigest()},
                'files': {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, indent=1))
        z.writestr('user.json', json.dumps(_entry_for_backup(entry)))
        z.writestr('db.enc', db_bytes)
        for n, b in files.items():
            z.writestr(f'files/{n}', b)
    data = buf.getvalue()
    if dest_dir is None:
        return data
    d = target_dir(dest_dir)
    name = f"FinanceHub_{re.sub(r'[^A-Za-z0-9._-]', '_', username)}_{now:%Y-%m-%d_%H%M%S}.fhb"
    tmp = d / (name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, d / name)
    if keep:                                      # this user's backups, also those made under an earlier user ID
        mine = sorted((b['created'], b['path']) for b in list_backups(dest_dir, db=entry['db']))
        for _, p in mine[:-int(keep)]:
            try:
                Path(p).unlink()
            except OSError:
                pass
    return d / name


def read_backup(src):
    """src: path or bytes → (manifest, user entry, db bytes, {file: bytes}); checks every hash."""
    z = zipfile.ZipFile(src if isinstance(src, (str, Path)) else io.BytesIO(src))
    names = set(z.namelist())
    if not {'manifest.json', 'user.json', 'db.enc'} <= names:
        raise ValueError('this is not a Finance Hub backup file')
    m = json.loads(z.read('manifest.json'))
    entry = json.loads(z.read('user.json'))
    db = z.read('db.enc')
    if hashlib.sha256(db).hexdigest() != m['sha256']['db.enc']:
        raise ValueError('the backup file is damaged (database does not match its checksum)')
    files = {}
    for n, h in m.get('files', {}).items():
        if '/' in n or '\\' in n or n.startswith('.'):
            raise ValueError('unsafe file name in backup')
        b = z.read(f'files/{n}')
        if hashlib.sha256(b).hexdigest() != h:
            raise ValueError('the backup file is damaged (an attachment does not match its checksum)')
        files[n] = b
    return m, entry, db, files


def list_backups(folder, username=None, db=None):
    out = []
    try:
        d = target_dir(folder) if folder else None
    except OSError:
        return out
    for p in sorted(d.glob('FinanceHub_*.fhb'), reverse=True) if d else []:
        try:
            with zipfile.ZipFile(p) as z:
                m = json.loads(z.read('manifest.json'))
        except Exception:  # noqa: BLE001
            continue
        if db and m.get('db') and m.get('db') != db:
            continue
        if username and not db and m.get('user') != username:
            continue
        out.append({'path': str(p), 'name': p.name, 'created': m.get('created', ''), 'version': m.get('version', ''),
                    'user': m.get('user', ''), 'size': p.stat().st_size})
    return out


# ── restoring ───────────────────────────────────────────────────────────────
def _backup_dek(vault, m, entry, db, password):
    """The data key that opens this backup: the current one, or from the backup's own wrapped key and a password."""
    import vault as VT
    if vault.unlocked:
        try:
            vault._decrypt_db(db, vault.dek)
            return vault.dek
        except Exception:  # noqa: BLE001
            pass
    for secret, aad in ((password or '', m['user'].encode()), (VT.norm_recovery(password or ''), b'recovery')):
        try:
            if aad == b'recovery':
                r = entry.get('recovery')
                if not r:
                    continue
                return VT.unwrap(VT.kek(secret, VT._unb64(r['salt']), r.get('iterations', VT.ITERATIONS)), r['key'], b'recovery')
            return VT.unwrap(VT.kek(secret, VT._unb64(entry['salt']), entry.get('iterations', VT.ITERATIONS)), entry['key'], aad)
        except Exception:  # noqa: BLE001
            continue
    raise ValueError('that password (or recovery key) does not open this backup')


def restore_mine(vault, src, password):
    """Replace the logged-in user's data with a backup. The present data is saved to the local backups folder first."""
    import hub_paths
    m, entry, db, files = read_backup(src)
    mine = vault.users_doc()['users'][vault.user]['db']
    if entry.get('db') != mine and m.get('user') != vault.user:
        raise ValueError(f"this backup belongs to another user ({m.get('user')}) — log in as that user to restore it")
    dek_b = _backup_dek(vault, m, entry, db, password)
    plain = vault._decrypt_db(db, dek_b)
    user = vault.user
    safety = make_backup(vault, user, hub_paths.BACKUP_DIR / 'before-restore', keep=10)
    with vault.lock:
        doc = vault.users_doc()
        path = vault.data_dir / doc['users'][user]['db']
        tmp = path.with_suffix('.enc.tmp')
        tmp.write_bytes(vault._encrypt_db(plain, vault.dek))
        os.replace(tmp, path)
        fdir = vault.data_dir / (path.stem + '_files')
        if fdir.is_dir():
            shutil.rmtree(fdir)
        if files:
            fdir.mkdir()
            for n, b in files.items():
                if dek_b != vault.dek:
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    import zlib
                    raw = zlib.decompress(AESGCM(dek_b).decrypt(b[7:19], b[19:], b'blob'))
                    b = vault.seal_bytes(raw)
                (fdir / n).write_bytes(b)
        vault.con.close()
        vault.con = None
        vault._open(vault.dek, user)
    return m, safety


def restore_fresh(vault, src, password):
    """First start on a new computer: bring back one user (as administrator) from a backup."""
    if vault.is_setup():
        raise ValueError('this Finance Hub already has users — log in and restore from Backup & restore')
    m, entry, db, files = read_backup(src)
    if not re.fullmatch(r'[0-9a-f]{16}\.enc', str(entry.get('db', ''))) or not re.fullmatch(r'[A-Za-z0-9._-]{3,40}', str(m.get('user', ''))):
        raise ValueError('this backup file is not valid')
    dek = _backup_dek(vault, m, entry, db, password)
    vault._decrypt_db(db, dek)                          # proves the key before anything is written
    vault.data_dir.mkdir(parents=True, exist_ok=True)
    (vault.data_dir / entry['db']).write_bytes(db)
    if files:
        fdir = vault.data_dir / (Path(entry['db']).stem + '_files')
        fdir.mkdir(exist_ok=True)
        for n, b in files.items():
            (fdir / n).write_bytes(b)
    doc = vault.users_doc()
    doc['users'] = {m['user']: dict(entry, role='admin', last_login='')}
    doc.pop('escrow', None)
    vault.save_users(doc)
    return m


# ── automatic backups (background, also while locked) ───────────────────────
def settings_of(vault, username):
    return dict({'dir': '', 'every': 'off', 'keep': 10, 'last': '', 'last_mtime': 0, 'last_error': ''},
                **vault.users_doc()['users'].get(username, {}).get('backup', {}))


def save_settings(vault, username, **kw):
    with vault.lock:
        doc = vault.users_doc()
        b = doc['users'][username].setdefault('backup', {})
        b.update(kw)
        vault.save_users(doc)


def run_due(vault, now=None):
    now = now or datetime.now()
    done = 0
    for name, u in list(vault.users_doc().get('users', {}).items()):
        b = u.get('backup') or {}
        if b.get('every') not in ('daily', 'weekly') or not b.get('dir'):
            continue
        db = vault.data_dir / u['db']
        if not db.exists():
            continue
        gap = timedelta(hours=20) if b['every'] == 'daily' else timedelta(days=6, hours=12)
        last = datetime.fromisoformat(b['last']) if b.get('last') else None
        if last and now - last < gap:
            continue
        if last and db.stat().st_mtime <= float(b.get('last_mtime') or 0):
            continue                                     # nothing changed since the last backup
        try:
            make_backup(vault, name, b['dir'], keep=int(b.get('keep') or 10), persist=False)
            save_settings(vault, name, last=now.isoformat(timespec='seconds'), last_mtime=db.stat().st_mtime, last_error='')
            done += 1
        except Exception as e:  # noqa: BLE001
            save_settings(vault, name, last_error=f'{now:%d %b %H:%M}: {e}'[:200])
    return done


# ── pages ────────────────────────────────────────────────────────────────────
def register(app, vault):
    global VAULT
    VAULT = vault
    import notify
    notify.EXTRA_TICKS.append(lambda: run_due(vault))

    def page():
        s = settings_of(vault, vault.user)
        clouds = cloud_folders()
        found = list_backups(s['dir'], vault.user, db=vault.users_doc()['users'][vault.user]['db']) if s['dir'] else []
        return render_template('backup.html', s=s, clouds=clouds, found=found, EVERY=EVERY,
                               folder=str(target_dir(s['dir'])) if s['dir'] else '')

    def save():
        f = request.form
        d = (f.get('custom') or '').strip() if f.get('where') == 'custom' else (f.get('where') or '').strip()
        if d:
            try:
                target_dir(d)
            except OSError as e:
                flash(f'That folder cannot be used: {e}', 'warning')
                return redirect(url_for('backup_page'))
        save_settings(vault, vault.user, dir=d, every=f.get('every') if f.get('every') in EVERY else 'off',
                      keep=max(1, min(100, int(f.get('keep') or 10))) if str(f.get('keep') or '10').isdigit() else 10)
        flash('Backup settings saved.', 'success')
        return redirect(url_for('backup_page'))

    def now_():
        s = settings_of(vault, vault.user)
        if not s['dir']:
            flash('Choose where to keep backups first.', 'warning')
            return redirect(url_for('backup_page'))
        try:
            p = make_backup(vault, vault.user, s['dir'], keep=s['keep'])
            db = vault.enc_path
            save_settings(vault, vault.user, last=datetime.now().isoformat(timespec='seconds'), last_mtime=db.stat().st_mtime, last_error='')
            flash(f'Backed up to {p}.', 'success')
        except Exception as e:  # noqa: BLE001
            flash(f'Backup failed: {e}', 'danger')
        return redirect(url_for('backup_page'))

    def download():
        data = make_backup(vault, vault.user)
        return send_file(io.BytesIO(data), as_attachment=True, mimetype='application/octet-stream',
                         download_name=f"FinanceHub_{vault.user}_{datetime.now():%Y-%m-%d_%H%M}.fhb")

    def restore():
        f = request.form
        try:
            if f.get('path'):
                s = settings_of(vault, vault.user)
                p = Path(f['path'])
                if not s['dir'] or p.parent.resolve() != target_dir(s['dir']).resolve():
                    raise ValueError('choose a backup from your backup folder')
                src = p
            else:
                up = request.files.get('file')
                if not up or not up.filename:
                    raise ValueError('choose a backup file')
                src = up.read()
            m, safety = restore_mine(vault, src, f.get('password', ''))
            session['vault'] = vault.nonce
            flash(f"Restored the backup of {m['created'][:16].replace('T', ' ')} (made by version {m['version']}). "
                  f"What you had before was saved as {Path(safety).name} in the local backups folder.", 'success')
        except Exception as e:  # noqa: BLE001
            flash(f'Not restored: {e}', 'danger')
        return redirect(url_for('backup_page'))

    def setup_restore():
        """Open page (no users yet): restore one user from a backup file."""
        if vault.is_setup():
            return redirect(url_for('login'))
        if request.method == 'POST':
            up = request.files.get('file')
            try:
                if not up or not up.filename:
                    raise ValueError('choose the backup file (.fhb)')
                m = restore_fresh(vault, up.read(), request.form.get('password', ''))
                flash(f"Restored {m['user']} from the backup of {m['created'][:10]}. Log in with that user ID and the password "
                      "you had then (or reset it with the recovery key).", 'success')
                return redirect(url_for('login'))
            except Exception as e:  # noqa: BLE001
                flash(f'Not restored: {e}', 'danger')
        return render_template('auth_restore.html')

    for rule, ep, fn, methods in [('/backup', 'backup_page', page, ['GET']), ('/backup/save', 'backup_save', save, ['POST']),
                                  ('/backup/now', 'backup_now', now_, ['POST']), ('/backup/download', 'backup_download', download, ['GET']),
                                  ('/backup/restore', 'backup_restore', restore, ['POST']),
                                  ('/setup/restore', 'setup_restore', setup_restore, ['GET', 'POST'])]:
        app.add_url_rule(rule, ep, fn, methods=methods)
