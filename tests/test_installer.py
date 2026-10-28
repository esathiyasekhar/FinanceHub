"""1.7 installer (setup.pyw) in silent mode — program and data folders, bringing old data, upgrade, uninstall.
Windows-only parts (UAC, shortcuts, registry, .venv packages) are skipped on other systems. SYNTHETIC data only."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import HUB, fresh  # noqa: E402

SP = Path(fresh('inst'))
subprocess.run([sys.executable, str(SP / 'tools' / 'make_release.py'), '--skip-tests', '--allow-findings'], check=True, capture_output=True)
setup_zip = next((SP / 'dist').glob('FinanceHub_*_Setup.zip'))
work = Path(tempfile.mkdtemp(prefix='fh_setup_'))
zipfile.ZipFile(setup_zip).extractall(work)
pkg = next(work.iterdir())
assert (pkg / 'setup.pyw').exists() and (pkg / 'Setup.cmd').exists() and list(pkg.glob('FinanceHub_*.zip'))

# an "old" portable Finance Hub folder with a user
old = Path(tempfile.mkdtemp(prefix='fh_old_'))
sys.path.insert(0, str(SP))
import vault as VT  # noqa: E402
V = VT.Vault(old)
V.setup('olduser', 'Old pass word 1', 'Old User')
V.connect().execute("CREATE TABLE IF NOT EXISTS marker (x TEXT)")
V.connect().execute("INSERT INTO marker VALUES ('from the old folder')")
V.persist(force=True)
V.lock_now()

prog = Path(tempfile.mkdtemp(prefix='fh_prog_')) / 'Finance Hub'
data = Path(tempfile.mkdtemp(prefix='fh_d_')) / 'Finance Hub'
r = subprocess.run([sys.executable, str(pkg / 'setup.pyw'), '--silent', '--program', str(prog), '--data', str(data),
                    '--import-from', str(old), '--no-packages'], capture_output=True, text=True)
print(r.stdout[-1500:], r.stderr[-1500:])
assert r.returncode == 0
cfg = json.loads((prog / 'financehub.json').read_text())
assert Path(cfg['data_dir']) == data
assert (prog / 'app.py').exists() and (prog / 'MANIFEST.sha256').exists() and (prog / 'installer' / 'setup.pyw').exists()
assert (data / 'users.json').exists() and list((data / 'data').glob('*.enc')), 'old data brought over'
assert (old / 'users.json').exists(), 'old folder untouched'
# the installed program uses the data folder from financehub.json
probe = subprocess.run([sys.executable, '-c', (
    "import os, sys; os.environ.pop('FINANCEHUB_DATA', None); sys.path.insert(0, '.');"
    "import hub_paths, vault; print(hub_paths.DATA_ROOT);"
    "V = vault.Vault(hub_paths.DATA_ROOT); ok, m = V.login('olduser', 'Old pass word 1');"
    "print(ok, V.connect().execute('SELECT x FROM marker').fetchone()[0])")], cwd=prog, capture_output=True, text=True,
    env={k: v for k, v in os.environ.items() if k != 'FINANCEHUB_DATA'})
print(probe.stdout, probe.stderr[-800:])
assert str(data) in probe.stdout and 'True from the old folder' in probe.stdout
# upgrade over the same folders keeps data and removes stale program files
(prog / 'stale_module.py').write_text('x')
with open(prog / 'MANIFEST.sha256', 'a') as f:
    f.write('0' * 64 + '  stale_module.py\n')
r = subprocess.run([sys.executable, str(pkg / 'setup.pyw'), '--silent', '--program', str(prog), '--data', str(data), '--no-packages'],
                   capture_output=True, text=True)
assert r.returncode == 0 and not (prog / 'stale_module.py').exists() and (data / 'users.json').exists()
# importing into a data folder that already has users changes nothing
r = subprocess.run([sys.executable, str(pkg / 'setup.pyw'), '--silent', '--program', str(prog), '--data', str(data),
                    '--import-from', str(old), '--no-packages'], capture_output=True, text=True)
assert 'already has users' in r.stdout
# a damaged release is refused
bad = Path(tempfile.mkdtemp(prefix='fh_bad_'))
for f in pkg.iterdir():
    (bad / f.name).write_bytes(f.read_bytes())
zp = next(bad.glob('FinanceHub_*.zip'))
zin = zipfile.ZipFile(zp)
items = {n: zin.read(n) for n in zin.namelist()}
items['app.py'] = items['app.py'] + b'\n# tampered\n'
zin.close()
with zipfile.ZipFile(zp, 'w') as z:
    for n, b in items.items():
        z.writestr(n, b)
r = subprocess.run([sys.executable, str(bad / 'setup.pyw'), '--silent', '--program', str(Path(tempfile.mkdtemp()) / 'p'),
                    '--data', str(Path(tempfile.mkdtemp()) / 'd'), '--no-packages'], capture_output=True, text=True)
assert r.returncode == 1 and 'damaged' in r.stdout
# uninstall removes the program, keeps the data
r = subprocess.run([sys.executable, str(prog / 'installer' / 'setup.pyw'), '--uninstall', '--silent'], capture_output=True, text=True)
assert not prog.exists() and (data / 'users.json').exists(), (r.stdout, r.stderr)
# uninstall from an unpacked Setup package must not touch the folder around it
r = subprocess.run([sys.executable, str(pkg / 'setup.pyw'), '--uninstall', '--silent'], capture_output=True, text=True)
assert r.returncode == 1 and pkg.exists() and work.exists(), 'must refuse: not an installation'
# the wizard window's flow, with a stand-in for tkinter (no display needed)
r = subprocess.run([sys.executable, str(Path(__file__).parent / '_tkstub' / 'drive_wizard.py'), str(pkg)], capture_output=True, text=True)
assert 'wizard flow OK' in r.stdout, r.stdout + r.stderr
print('ALL installer OK')
