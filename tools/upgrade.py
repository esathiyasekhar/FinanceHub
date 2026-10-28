"""Upgrade an installed Finance Hub from a release zip:  python tools/upgrade.py <FinanceHub_X.Y.zip>

Checks every file against the zip's MANIFEST.sha256, backs up the encrypted data, replaces the program files (data,
users.json, backups and logs are never touched), removes program files the new version no longer has, and updates the
packages in .venv. Quit the Hub (tray icon › Quit) before upgrading."""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
try:
    import hub_paths as _hp                      # 1.7: data may live in a separate folder
    DATA = _hp.DATA_ROOT
except Exception:  # noqa: BLE001  (upgrading from a version without hub_paths)
    DATA = BASE
KEEP = {'data', 'uploads', 'backups', 'logs', '.venv', '.git', 'dist'}


def running():
    try:
        port = os.environ.get('FINANCEHUB_PORT') or getattr(sys.modules.get('hub_paths'), 'PORT', 5000)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=2) as r:
            return r.read(20).startswith(b'FinanceHub')
    except Exception:  # noqa: BLE001
        return False


def main(zpath):
    side = Path(str(zpath) + '.sha256')
    if side.exists():
        want = side.read_text().split()[0]
        if hashlib.sha256(Path(zpath).read_bytes()).hexdigest() != want:
            sys.exit('The release zip does not match its .sha256 file — download it again.')
    z = zipfile.ZipFile(zpath)
    man = {}
    for line in z.read('MANIFEST.sha256').decode().splitlines():
        h, _, name = line.partition('  ')
        man[name] = h
    bad = [n for n, h in man.items() if hashlib.sha256(z.read(n)).hexdigest() != h]
    if bad:
        sys.exit(f'The release zip is damaged ({len(bad)} files do not match) — download it again.')
    if any(Path(n).parts[0] in KEEP or n == 'users.json' for n in man):
        sys.exit('This zip contains data folders — it is not a Finance Hub release.')
    if any(n.startswith(('/', '\\')) or '..' in Path(n).parts or ':' in n for n in man):
        sys.exit('The release zip contains unsafe file paths — not installed.')
    if set(n for n in z.namelist() if not n.endswith('/')) - set(man) - {'MANIFEST.sha256'}:
        sys.exit('The release zip contains files that are not in its manifest — not installed.')
    if running():
        sys.exit('Finance Hub is running — Quit it first (tray icon › Quit Finance Hub).')
    new_ver = next((l.split("'")[1] for l in z.read('hub_version.py').decode().splitlines() if l.startswith('VERSION')), '?')
    old_man = BASE / 'MANIFEST.sha256'
    old = {l.partition('  ')[2] for l in old_man.read_text().splitlines()} if old_man.exists() else set()
    data = DATA / 'data'
    if data.is_dir() and any(data.glob('*.enc')):
        dest = DATA / 'backups' / f'{datetime.now():%Y-%m-%d_%H%M%S}_before_{new_ver}'
        dest.mkdir(parents=True)
        for f in list(data.glob('*.enc')) + list(data.glob('*.enc.prev')):
            shutil.copy2(f, dest / f.name)
        for d in data.glob('*_files'):
            if d.is_dir():
                shutil.copytree(d, dest / d.name)
        if (DATA / 'users.json').exists():
            shutil.copy2(DATA / 'users.json', dest / 'users.json')
        (data / '.version').write_text(new_ver)          # the launcher need not back up the same data again
        import re
        olds = sorted(p for p in (DATA / 'backups').iterdir() if p.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}_\d{6}_before_', p.name))
        for p in olds[:-10]:
            shutil.rmtree(p, ignore_errors=True)
        print(f'Encrypted data backed up to backups/{dest.name}')
    for n in man:
        target = BASE / n
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(n))
    (BASE / 'MANIFEST.sha256').write_bytes(z.read('MANIFEST.sha256'))
    gone = [n for n in old - set(man) if Path(n).parts[0] not in KEEP]
    for n in gone:
        p = BASE / n
        if p.exists():
            p.unlink()
    print(f'Program files updated to Finance Hub {new_ver} ({len(man)} files, {len(gone)} old files removed).')
    py = BASE / '.venv' / ('Scripts' if sys.platform == 'win32' else 'bin') / ('python.exe' if sys.platform == 'win32' else 'python')
    if py.exists():
        subprocess.run([str(py), '-m', 'pip', 'install', '-r', str(BASE / 'requirements.txt'), '-q', '--disable-pip-version-check'])
        print('Packages updated.')
    else:
        print('Run install.bat once to set up the Hub\'s own Python environment and shortcuts.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
