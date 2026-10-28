"""Build a Finance Hub release:  python tools/make_release.py [--skip-tests] [--allow-findings]

1. checks the version (hub_version.py) has a CHANGELOG entry;
2. scans the code for anything that looks like personal data (PAN, card / account / Aadhaar numbers, IFSC, phone numbers,
   real e-mail addresses) — the program must never carry personal data;
3. runs the test suite (synthetic data only);
4. writes dist/FinanceHub_<version>.zip (+ MANIFEST.sha256 inside, and a .sha256 file beside it).
Data, users.json, uploads, backups, logs, .venv, .git and tests are never packed."""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from hub_version import VERSION  # noqa: E402

SKIP_DIRS = {'data', 'uploads', 'backups', 'logs', '.venv', '.git', 'dist', '__pycache__', 'tests', 'statements', '.pytest_cache'}
SKIP_FILES = {'users.json', 'requirements.lock', 'finance.db'}
TEXT_EXT = {'.py', '.pyw', '.html', '.md', '.bat', '.txt', '.json', '.js', '.css', '.cfg', '.toml'}
PATTERNS = {
    'PAN': re.compile(r'\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b'),
    'card / account number': re.compile(r'(?<![\w.])\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}(?![\w.])|(?<![\w.])\d{11,18}(?![\w.])'),
    'Aadhaar': re.compile(r'(?<!\d)\d{4} \d{4} \d{4}(?!\d)'),
    'IFSC': re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b'),
    'phone': re.compile(r'(?<![\d.])(?:\+91[ -]?)?[6-9]\d{9}(?![\d.])'),
    'e-mail': re.compile(r'\b[\w.+-]+@(?!example\.|test\b|financehub\.local|x\b|upi\b)[\w-]+\.[\w.]+\b'),
}
# generic look-alikes that are fine (synthetic examples, placeholders, version strings, well-known constants)
ALLOW = re.compile(r'^(0+|1234567890\d*|9876543210|1208160000001234|IN30000011112222|4000X+\d{4}|0{4,}\d+|1{4,}\d*|2{4,}\d*)$')
ALLOW_EMAIL = re.compile(r'@(gmail\.com|sbicard\.com|hdfcbank\.(net|com)|cdslstatement\.com|sbi\.co\.in|shop\.example)$')


def files():
    for p in sorted(BASE.rglob('*')):
        rel = p.relative_to(BASE)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or rel.name in SKIP_FILES or p.suffix in ('.pyc', '.enc', '.prev'):
            continue
        yield p, rel.as_posix()


def privacy_scan():
    found = []
    for p, rel in files():
        if p.suffix.lower() not in TEXT_EXT:
            continue
        for n, line in enumerate(p.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            for what, rx in PATTERNS.items():
                for m in rx.finditer(line):
                    v = m.group(0)
                    digits = re.sub(r'\D', '', v)
                    if what == 'e-mail' and (ALLOW_EMAIL.search(v) or v.split('@')[0] in ('me', 'hub', 'eCAS', 'alerts', 'statements', 'estatement', 'offers', 'noreply', 'a', 'b', 'build', 'hub.statements', 'family')):
                        continue
                    if what != 'e-mail' and (ALLOW.match(digits or v) or len(set(digits)) <= 2):
                        continue
                    if 'IN0' in line and what == 'card / account number':
                        continue
                    found.append(f'{rel}:{n}: {what}: {v}')
    return found


def main():
    args = set(sys.argv[1:])
    log = (BASE / 'CHANGELOG.md').read_text(encoding='utf-8')
    if f'## {VERSION} ' not in log and f'## {VERSION}\n' not in log:
        sys.exit(f'CHANGELOG.md has no entry for {VERSION} — add one first.')
    found = privacy_scan()
    if found:
        print('Possible personal data in the code:')
        print('\n'.join('  ' + f for f in found[:40]))
        if '--allow-findings' not in args:
            sys.exit('Release stopped. Remove the data (or re-run with --allow-findings after checking each line).')
    else:
        print('Privacy scan: nothing that looks like personal data.')
    if '--skip-tests' not in args and (BASE / 'tests' / 'run_all.py').exists():
        r = subprocess.run([sys.executable, str(BASE / 'tests' / 'run_all.py')])
        if r.returncode:
            sys.exit('Tests failed — release stopped.')
    dist = BASE / 'dist'
    dist.mkdir(exist_ok=True)
    out = dist / f'FinanceHub_{VERSION}.zip'
    manifest = []
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, rel in files():
            data = p.read_bytes()
            z.writestr(rel, data)
            manifest.append(f'{hashlib.sha256(data).hexdigest()}  {rel}')
        z.writestr('MANIFEST.sha256', '\n'.join(manifest) + '\n')
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / f'{out.name}.sha256').write_text(f'{h}  {out.name}\n')
    try:
        desc = subprocess.run(['git', 'describe', '--tags', '--dirty', '--always'], cwd=BASE, capture_output=True, text=True).stdout.strip()
    except OSError:
        desc = ''
    print(f'Built {out.relative_to(BASE)} — {len(manifest)} files, sha256 {h[:16]}…' + (f' (git {desc})' if desc else ''))


if __name__ == '__main__':
    main()
