"""Finance Hub — Windows setup (1.7).

Run by Setup.cmd (double-click). A small wizard asks for:
  * the program folder   (default C:\\Program Files\\Finance Hub)
  * the data folder      (default D:\\Finance Hub — or C:\\Finance Hub Data when there is no D: drive)
  * optionally an existing Finance Hub folder whose data should be brought over
  * shortcuts, start with Windows, start now
and then installs: program files (checked against the release manifest), financehub.json (where the data lives), the
Hub's own Python environment (.venv) with its packages, Start-menu / Desktop shortcuts, and an entry in
Settings › Apps (uninstall). Program Files needs administrator rights: Windows asks once (UAC) for that part.

Upgrading: run the newer Setup — it finds the installed copy and keeps the data folder. Uninstalling (Settings › Apps,
or Setup.cmd /uninstall) removes the program but never the data folder.

Command line (also used for the elevated part and by the tests):
  setup.pyw --silent --program DIR --data DIR [--import-from DIR] [--no-packages] [--log FILE] [--elevated]
  setup.pyw --uninstall [--silent]
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = 'Finance Hub'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\FinanceHub'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
KEEP = {'data', 'uploads', 'backups', 'logs', '.venv', 'users.json', 'financehub.json', 'requirements.lock'}
IS_WIN = os.name == 'nt'


# ── helpers ─────────────────────────────────────────────────────────────────
def payload():
    """The release zip shipped next to this file (FinanceHub_<version>.zip)."""
    zips = sorted(HERE.glob('FinanceHub_*.zip'))
    if not zips:
        raise SystemExit('The Finance Hub release (FinanceHub_<version>.zip) is missing next to setup.pyw.')
    return zips[-1]


def payload_version(z):
    try:
        for line in z.read('hub_version.py').decode().splitlines():
            if line.startswith('VERSION'):
                return line.split("'")[1]
    except KeyError:
        pass
    return '?'


def default_data_dir():
    if IS_WIN and Path('D:\\').exists():
        return 'D:\\Finance Hub'
    return 'C:\\Finance Hub Data' if IS_WIN else str(Path.home() / 'Finance Hub Data')


def default_program_dir():
    if IS_WIN:
        return str(Path(os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or 'C:\\Program Files') / APP)
    return str(Path.home() / 'Finance Hub')


def installed_location():
    """Program folder of an earlier install (from the uninstall entry), or ''."""
    if not IS_WIN:
        return ''
    import winreg
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, UNINSTALL_KEY) as k:
                return winreg.QueryValueEx(k, 'InstallLocation')[0]
        except OSError:
            continue
    return ''


def is_admin():
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, 'geteuid') else True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def needs_admin(path):
    """True when this process cannot write there (e.g. Program Files)."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        t = p / f'.fh_write_test_{os.getpid()}'
        t.write_text('x')
        t.unlink()
        return False
    except OSError:
        return True


def hub_running(port=None):
    if port is None:
        try:
            port = json.loads((Path(installed_location() or HERE.parent) / 'financehub.json').read_text()).get('port', 5000)
        except (OSError, ValueError):
            port = 5000
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=1.5) as r:
            return r.read(20).startswith(b'FinanceHub')
    except Exception:  # noqa: BLE001
        return False


def find_python_for_venv():
    """The Python that runs this setup is the one the Hub's .venv is made from."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists():
        exe = exe.with_name('python.exe')
    return str(exe)


# ── the installation itself (runs elevated when needed) ─────────────────────
class Log:
    def __init__(self, path=None, echo=None):
        self.path, self.echo = path, echo

    def __call__(self, msg):
        line = f'{time.strftime("%H:%M:%S")}  {msg}'
        if self.path:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        if self.echo:
            self.echo(line)


def install_program(program, data, import_from='', packages=True, log=print, grant_user=''):
    program, data = Path(program), Path(data)
    src = payload()
    z = zipfile.ZipFile(src)
    man = {}
    for line in z.read('MANIFEST.sha256').decode().splitlines():
        h, _, name = line.partition('  ')
        man[name] = h
    bad = [n for n, h in man.items() if hashlib.sha256(z.read(n)).hexdigest() != h]
    if bad:
        raise RuntimeError(f'the release file is damaged ({len(bad)} files do not match) — download it again')
    if any(n.startswith(('/', '\\')) or '..' in Path(n).parts or ':' in n for n in man):
        raise RuntimeError('the release file contains unsafe paths')
    version = payload_version(z)
    log(f'Installing {APP} {version}')
    program.mkdir(parents=True, exist_ok=True)
    old_man = program / 'MANIFEST.sha256'
    old = {l.partition('  ')[2] for l in old_man.read_text().splitlines()} if old_man.exists() else set()
    for n in man:
        t = program / n
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(z.read(n))
    old_man.write_bytes(z.read('MANIFEST.sha256'))
    for n in old - set(man):
        if Path(n).parts[0] not in KEEP:
            try:
                (program / n).unlink()
            except OSError:
                pass
    log(f'Program files: {len(man)} files in {program}')
    for name in ('setup.pyw', 'Setup.cmd'):                      # kept for repair / uninstall
        if (HERE / name).exists() and (HERE / name).resolve() != (program / 'installer' / name).resolve():
            (program / 'installer').mkdir(exist_ok=True)
            shutil.copy2(HERE / name, program / 'installer' / name)
    data.mkdir(parents=True, exist_ok=True)
    cfg_file = program / 'financehub.json'
    try:
        cfg = json.loads(cfg_file.read_text(encoding='utf-8'))      # keep settings such as a custom port when upgrading
    except (OSError, ValueError):
        cfg = {}
    cfg.update(data_dir=str(data))
    cfg.setdefault('port', 5000)
    cfg_file.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    log(f'Data folder: {data}')
    if IS_WIN and grant_user:
        subprocess.run(['icacls', str(data), '/grant', f'{grant_user}:(OI)(CI)M', '/T', '/Q'],
                       capture_output=True, creationflags=0x08000000)   # the user (not only Administrators) may write the data
    if import_from:
        bring_data(Path(import_from), data, log)
    if packages:
        make_venv(program, log)
    if IS_WIN:
        register_uninstall(program, version, log)
    log('Done.')
    return version


def bring_data(src, data, log):
    """Copy users.json and the encrypted databases from an older Finance Hub folder (never overwrites)."""
    cfg = src / 'financehub.json'
    if cfg.exists():
        try:
            src = Path(json.loads(cfg.read_text())['data_dir'])
        except (ValueError, KeyError):
            pass
    if not (src / 'users.json').exists():
        raise RuntimeError(f'no Finance Hub data found in {src} (users.json is missing)')
    if (data / 'users.json').exists():
        log('The data folder already has users — existing data left as it is, nothing imported.')
        return
    (data / 'data').mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / 'users.json', data / 'users.json')
    n = 0
    for f in (src / 'data').iterdir():
        if f.is_file() and (f.suffix in ('.enc', '.prev', '.outbox') or f.name.endswith(('.sent.json', '.enc.prev')) or f.name == '.version'):
            shutil.copy2(f, data / 'data' / f.name)
            n += 1
        elif f.is_dir() and f.name.endswith('_files'):
            shutil.copytree(f, data / 'data' / f.name, dirs_exist_ok=True)
            n += 1
    if (src / 'backups').is_dir():
        shutil.copytree(src / 'backups', data / 'backups', dirs_exist_ok=True)
    log(f'Brought over your data from {src} ({n} items). The old folder was not changed.')


def make_venv(program, log):
    venv = program / '.venv'
    py = find_python_for_venv()
    if not (venv / ('Scripts' if IS_WIN else 'bin')).exists():
        log('Creating the Hub\'s own Python environment …')
        subprocess.run([py, '-m', 'venv', str(venv)], check=True, capture_output=True)
    vpy = venv / ('Scripts/python.exe' if IS_WIN else 'bin/python')
    log('Installing the packages the Hub needs (a few minutes the first time) …')
    flags = {'creationflags': 0x08000000} if IS_WIN else {}      # no console window
    r = subprocess.run([str(vpy), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', str(program / 'requirements.txt')],
                       capture_output=True, text=True, **flags)
    if r.returncode:
        raise RuntimeError('installing packages failed (an internet connection is needed):\n' + (r.stderr or r.stdout)[-800:])
    lock = subprocess.run([str(vpy), '-m', 'pip', 'freeze', '--disable-pip-version-check'], capture_output=True, text=True, **flags)
    (program / 'requirements.lock').write_text(lock.stdout)
    log('Packages installed.')


def register_uninstall(program, version, log):
    import winreg
    root = winreg.HKEY_LOCAL_MACHINE if is_admin() else winreg.HKEY_CURRENT_USER
    pyw = program / '.venv' / 'Scripts' / 'pythonw.exe'
    cmd = f'"{pyw if pyw.exists() else find_python_for_venv()}" "{program / "installer" / "setup.pyw"}" --uninstall'
    with winreg.CreateKey(root, UNINSTALL_KEY) as k:
        for name, val in (('DisplayName', APP), ('DisplayVersion', version), ('Publisher', 'Finance Hub'),
                          ('InstallLocation', str(program)), ('DisplayIcon', str(program / 'static' / 'hub.ico')),
                          ('UninstallString', cmd), ('NoModify', 1), ('NoRepair', 1)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD if isinstance(val, int) else winreg.REG_SZ, val)
    log('Added to Settings › Apps (uninstall).')


# ── per-user parts (shortcuts, start with Windows) ──────────────────────────
def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def make_shortcuts(program, desktop=True, log=print):
    if not IS_WIN:
        return
    target = program / '.venv' / 'Scripts' / 'pythonw.exe'
    dirs = ["[Environment]::GetFolderPath('Programs')"] + (["[Environment]::GetFolderPath('Desktop')"] if desktop else [])
    ps = ('$w = New-Object -ComObject WScript.Shell; foreach ($d in @(' + ', '.join(dirs) + ')) { '
          "$s = $w.CreateShortcut((Join-Path $d 'Finance Hub.lnk')); "
          f'$s.TargetPath = {ps_quote(target)}; $s.Arguments = {ps_quote(chr(34) + str(program / "FinanceHub.pyw") + chr(34))}; '
          f'$s.WorkingDirectory = {ps_quote(program)}; $s.IconLocation = {ps_quote(program / "static" / "hub.ico")}; '
          "$s.Description = 'Finance Hub'; $s.Save() }")
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], capture_output=True,
                   creationflags=0x08000000)
    log('Shortcuts created (Start menu' + (' and Desktop' if desktop else '') + ').')


def set_autostart(program, on, log=print):
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, 'FinanceHub', 0, winreg.REG_SZ,
                              f'"{program / ".venv" / "Scripts" / "pythonw.exe"}" "{program / "FinanceHub.pyw"}" --background')
            log('Starts with Windows.')
        else:
            try:
                winreg.DeleteValue(k, 'FinanceHub')
            except OSError:
                pass


def start_hub(program):
    if IS_WIN:
        subprocess.Popen([str(program / '.venv' / 'Scripts' / 'pythonw.exe'), str(program / 'FinanceHub.pyw')], cwd=str(program),
                         creationflags=0x00000008)          # DETACHED_PROCESS


def base_pythonw():
    """The Python that is NOT inside the program folder's .venv (needed when removing that folder)."""
    base = Path(getattr(sys, '_base_executable', '') or Path(sys.base_prefix) / 'python.exe')
    for cand in (base.with_name('pythonw.exe'), Path(sys.base_prefix) / 'pythonw.exe', base):
        if cand.exists():
            return cand
    return Path(sys.executable)


def run_elevated(args, log_file, script=None, exe=None):
    """Run this setup again with administrator rights for the program-folder part, and wait for it."""
    import ctypes.wintypes as wt

    class SEI(ctypes.Structure):
        _fields_ = [('cbSize', wt.DWORD), ('fMask', ctypes.c_ulong), ('hwnd', wt.HWND), ('lpVerb', wt.LPCWSTR),
                    ('lpFile', wt.LPCWSTR), ('lpParameters', wt.LPCWSTR), ('lpDirectory', wt.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wt.HINSTANCE), ('lpIDList', ctypes.c_void_p), ('lpClass', wt.LPCWSTR), ('hkeyClass', wt.HKEY),
                    ('dwHotKey', wt.DWORD), ('hIcon', wt.HANDLE), ('hProcess', wt.HANDLE)]
    params = subprocess.list2cmdline([str(script or Path(__file__).resolve())] + args + ['--elevated']
                                     + (['--log', str(log_file)] if log_file else []))
    if exe is None:
        exe = Path(sys.executable)
        exe = exe.with_name('pythonw.exe') if exe.with_name('pythonw.exe').exists() else exe
    sei = SEI(cbSize=ctypes.sizeof(SEI), fMask=0x40, lpVerb='runas', lpFile=str(exe), lpParameters=params, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise RuntimeError('administrator permission was not given')
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
    code = wt.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return code.value


def full_install(opts, log):
    """Everything, in the right process: elevated part (if needed) then the per-user part."""
    program, data = Path(opts['program']), Path(opts['data'])
    if hub_running():
        raise RuntimeError('Finance Hub is running — quit it first (tray icon › Quit Finance Hub), then click Install again.')
    args = ['--silent', '--program', str(program), '--data', str(data)]
    if opts.get('import_from'):
        args += ['--import-from', opts['import_from']]
    if not opts.get('packages', True):
        args += ['--no-packages']
    if IS_WIN and (needs_admin(program) or needs_admin(data)) and not is_admin():
        log('Windows will ask for permission to install into the program folder …')
        code = run_elevated(args + ['--grant-user', os.environ.get('USERNAME', '')], log.path)
        if code:
            raise RuntimeError('the installation did not finish — see the messages above')
    else:
        install_program(program, data, opts.get('import_from', ''), packages=opts.get('packages', True), log=log)
    make_shortcuts(program, opts.get('desktop', True), log)
    set_autostart(program, opts.get('autostart', False), log)
    if opts.get('start'):
        start_hub(program)
        log('Finance Hub is starting — your browser will open.')


# ── uninstall ───────────────────────────────────────────────────────────────
def looks_installed(p):
    return (p / 'app.py').exists() and (p / 'MANIFEST.sha256').exists() and (p / 'hub_version.py').exists()


def uninstall(silent=False, elevated=False, program=None):
    program = Path(program or installed_location() or HERE.parent)
    if not looks_installed(program):
        message(f'No Finance Hub installation was found in {program} — nothing was removed.')
        return 1
    cfg = {}
    try:
        cfg = json.loads((program / 'financehub.json').read_text())
    except (OSError, ValueError):
        pass
    me = str(Path(sys.executable).resolve()).lower()
    if not elevated and me.startswith(str(program.resolve()).lower()):
        # started by Settings › Apps with the Python inside the program folder: continue from a copy outside it
        tmp = Path(tempfile.mkdtemp()) / 'setup.pyw'
        shutil.copy2(__file__, tmp)
        subprocess.Popen([str(base_pythonw()), str(tmp), '--uninstall', '--program', str(program)] + (['--silent'] if silent else []))
        return 0
    if not elevated:
        if not silent and not ask_yes_no(f'Remove {APP} from {program}?\n\nYour data in {cfg.get("data_dir", "the data folder")} is kept.'):
            return 1
        if hub_running():
            message(f'{APP} is running — quit it first (tray icon › Quit Finance Hub).')
            return 1
        set_autostart(program, False)
        if IS_WIN:
            for d in ("[Environment]::GetFolderPath('Programs')", "[Environment]::GetFolderPath('Desktop')"):
                subprocess.run(['powershell', '-NoProfile', '-Command', f"Remove-Item -LiteralPath (Join-Path {d} 'Finance Hub.lnk') -ErrorAction SilentlyContinue"],
                               capture_output=True, creationflags=0x08000000)
        if IS_WIN and needs_admin(program) and not is_admin():
            tmp = Path(tempfile.mkdtemp()) / 'setup.pyw'          # run from a copy, with Python outside the folder to remove
            shutil.copy2(__file__, tmp)
            code = run_elevated(['--uninstall', '--silent', '--program', str(program)], None, script=tmp, exe=base_pythonw())
            if not silent:
                message(f'{APP} was removed. Your data is still in {cfg.get("data_dir", "its data folder")} — delete that folder '
                        'yourself if you no longer need it.' if not program.exists() else
                        f'{APP} could not be removed completely from {program}.')
            return code
    shutil.rmtree(program, ignore_errors=True)
    if IS_WIN:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                winreg.DeleteKey(root, UNINSTALL_KEY)
            except OSError:
                pass
    if not silent:
        message(f'{APP} was removed. Your data is still in {cfg.get("data_dir", "its data folder")} — delete that folder yourself if you no longer need it.')
    return 0


def message(text):
    try:
        import tkinter.messagebox as mb
        mb.showinfo(APP, text)
    except Exception:  # noqa: BLE001
        print(text)


def ask_yes_no(text):
    try:
        import tkinter as tk
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        ok = mb.askyesno(APP, text)
        root.destroy()
        return ok
    except Exception:  # noqa: BLE001
        return input(text + ' [y/N] ').strip().lower().startswith('y')


# ── the wizard window ───────────────────────────────────────────────────────
def wizard():
    import tkinter as tk
    from tkinter import ttk, filedialog

    z = zipfile.ZipFile(payload())
    version = payload_version(z)
    prev = installed_location()
    prev_data = ''
    if prev:
        try:
            prev_data = json.loads((Path(prev) / 'financehub.json').read_text()).get('data_dir', '')
        except (OSError, ValueError):
            pass

    root = tk.Tk()
    root.title(f'{APP} {version} — Setup')
    root.geometry('640x470')
    root.resizable(False, False)
    try:
        root.iconbitmap(str(HERE / 'hub.ico'))
    except Exception:  # noqa: BLE001
        pass
    style = ttk.Style()
    try:
        style.theme_use('vista')
    except tk.TclError:
        pass
    v = {'program': tk.StringVar(value=prev or default_program_dir()), 'data': tk.StringVar(value=prev_data or default_data_dir()),
         'do_import': tk.BooleanVar(value=False), 'import_from': tk.StringVar(), 'desktop': tk.BooleanVar(value=True),
         'autostart': tk.BooleanVar(value=False), 'start': tk.BooleanVar(value=True)}
    head = tk.Frame(root, bg='#6366f1', height=64)
    head.pack(fill='x')
    tk.Label(head, text=f'{APP} {version}', bg='#6366f1', fg='white', font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=18, pady=(10, 0))
    sub = tk.Label(head, text='', bg='#6366f1', fg='#e0e7ff', font=('Segoe UI', 9))
    sub.pack(anchor='w', padx=18, pady=(0, 8))
    body = tk.Frame(root, padx=18, pady=12)
    body.pack(fill='both', expand=True)
    foot = tk.Frame(root, padx=18, pady=10)
    foot.pack(fill='x')
    back = ttk.Button(foot, text='< Back')
    nxt = ttk.Button(foot, text='Next >')
    cancel = ttk.Button(foot, text='Cancel', command=root.destroy)
    cancel.pack(side='right')
    nxt.pack(side='right', padx=6)
    back.pack(side='right')
    page = {'i': 0}

    def clear():
        for w in body.winfo_children():
            w.destroy()

    def browse(var):
        d = filedialog.askdirectory(initialdir=var.get() or '/')
        if d:
            var.set(str(Path(d)))

    def row(label, var, note=''):
        tk.Label(body, text=label, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(8, 2))
        f = tk.Frame(body)
        f.pack(fill='x')
        ttk.Entry(f, textvariable=var).pack(side='left', fill='x', expand=True)
        ttk.Button(f, text='Browse…', command=lambda: browse(var)).pack(side='left', padx=(6, 0))
        if note:
            tk.Label(body, text=note, fg='#555', font=('Segoe UI', 8), wraplength=590, justify='left').pack(anchor='w')

    def p_welcome():
        sub['text'] = 'Welcome'
        msg = (f'This installs {APP} {version} — your personal finance hub. It runs on this computer only and keeps your data '
               'encrypted.\n\n'
               + (f'An earlier installation was found in {prev}. It will be upgraded; your data stays where it is.\n\n' if prev else '')
               + f'Python {sys.version.split()[0]} will be used for the Hub\'s own environment. An internet connection is needed '
               'the first time, to download the packages the Hub uses.\n\nClick Next to continue.')
        tk.Label(body, text=msg, justify='left', wraplength=590, font=('Segoe UI', 10)).pack(anchor='w')

    def p_folders():
        sub['text'] = 'Where to install'
        row('Program folder', v['program'], 'The program itself. Installing into Program Files needs administrator permission (Windows asks once).')
        row('Data folder', v['data'], 'Your encrypted data, logs and backups. Keep it on a drive that is backed up. It is never removed '
            'by uninstalling.')
        ttk.Checkbutton(body, text='Bring over the data of an existing Finance Hub folder (an older version)', variable=v['do_import']).pack(anchor='w', pady=(12, 0))
        f = tk.Frame(body)
        f.pack(fill='x')
        ttk.Entry(f, textvariable=v['import_from']).pack(side='left', fill='x', expand=True)
        ttk.Button(f, text='Browse…', command=lambda: (browse(v['import_from']), v['do_import'].set(True))).pack(side='left', padx=(6, 0))
        tk.Label(body, text='Choose the old folder that contains users.json (for example E:\\…\\FinanceHub). It is copied, not moved.',
                 fg='#555', font=('Segoe UI', 8)).pack(anchor='w')

    def p_options():
        sub['text'] = 'Options'
        for key, text in (('desktop', 'Put a Finance Hub shortcut on the Desktop'),
                          ('autostart', 'Start Finance Hub when I log in to Windows (runs in the background)'),
                          ('start', 'Start Finance Hub when setup finishes')):
            ttk.Checkbutton(body, text=text, variable=v[key]).pack(anchor='w', pady=4)
        tk.Label(body, text='\nSummary', font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        tk.Label(body, text=f"Program:  {v['program'].get()}\nData:        {v['data'].get()}"
                 + (f"\nImport:     {v['import_from'].get()}" if v['do_import'].get() else ''), justify='left',
                 font=('Consolas', 9)).pack(anchor='w')

    def p_install():
        sub['text'] = 'Installing'
        txt = tk.Text(body, height=16, font=('Consolas', 9), wrap='word')
        txt.pack(fill='both', expand=True)
        bar = ttk.Progressbar(body, mode='indeterminate')
        bar.pack(fill='x', pady=(6, 0))
        bar.start(12)
        back.state(['disabled'])
        nxt.state(['disabled'])
        cancel.state(['disabled'])
        log_file = Path(tempfile.gettempdir()) / f'FinanceHub_setup_{os.getpid()}.log'
        log = Log(str(log_file))
        seen = {'n': 0}

        def poll():
            try:
                lines = log_file.read_text(encoding='utf-8').splitlines()
            except OSError:
                lines = []
            for ln in lines[seen['n']:]:
                txt.insert('end', ln + '\n')
                txt.see('end')
            seen['n'] = len(lines)
            if worker.is_alive():
                root.after(400, poll)
            else:
                bar.stop()
                bar['mode'] = 'determinate'
                bar['value'] = 100 if not err else 0
                if err:
                    txt.insert('end', f'\nSetup did not finish: {err[0]}\n')
                    cancel.state(['!disabled'])
                    cancel['text'] = 'Close'
                else:
                    nxt.state(['!disabled'])
                    nxt['text'] = 'Finish'
                    nxt['command'] = root.destroy
                    sub['text'] = 'Finished'
        err = []

        def work():
            try:
                full_install({'program': v['program'].get(), 'data': v['data'].get(),
                              'import_from': v['import_from'].get() if v['do_import'].get() else '',
                              'desktop': v['desktop'].get(), 'autostart': v['autostart'].get(), 'start': v['start'].get()}, log)
            except Exception as e:  # noqa: BLE001
                err.append(str(e))
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        root.after(300, poll)

    pages = [p_welcome, p_folders, p_options, p_install]

    def show(i):
        page['i'] = i
        clear()
        pages[i]()
        back.state(['disabled'] if i == 0 else ['!disabled'])
        nxt['text'] = 'Install' if i == 2 else 'Next >'

    def go_next():
        i = page['i']
        if i == 1:
            if not v['program'].get().strip() or not v['data'].get().strip():
                message('Choose both folders.')
                return
            if Path(v['data'].get()).resolve() == Path(v['program'].get()).resolve():
                message('Use a separate data folder (not the program folder).')
                return
            if v['do_import'].get() and not (Path(v['import_from'].get()) / 'users.json').exists() \
                    and not (Path(v['import_from'].get()) / 'financehub.json').exists():
                message('That folder has no Finance Hub data (users.json was not found).')
                return
        if i < len(pages) - 1:
            show(i + 1)

    nxt['command'] = go_next
    back['command'] = lambda: show(max(0, page['i'] - 1))
    show(0)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--silent', action='store_true')
    ap.add_argument('--program')
    ap.add_argument('--data')
    ap.add_argument('--import-from', default='')
    ap.add_argument('--no-packages', action='store_true')
    ap.add_argument('--log')
    ap.add_argument('--elevated', action='store_true')
    ap.add_argument('--grant-user', default='')
    ap.add_argument('--uninstall', action='store_true')
    ap.add_argument('--desktop', action='store_true')
    ap.add_argument('--autostart', action='store_true')
    ap.add_argument('--start', action='store_true')
    a = ap.parse_args()
    if a.uninstall:
        return uninstall(a.silent, a.elevated, a.program)
    if a.silent:
        log = Log(a.log, None if a.log else print)
        try:
            if a.elevated:                         # the administrator part only
                install_program(a.program or default_program_dir(), a.data or default_data_dir(), a.import_from,
                                packages=not a.no_packages, log=log, grant_user=a.grant_user)
            else:
                full_install({'program': a.program or default_program_dir(), 'data': a.data or default_data_dir(),
                              'import_from': a.import_from, 'packages': not a.no_packages, 'desktop': a.desktop,
                              'autostart': a.autostart, 'start': a.start}, log)
            return 0
        except Exception as e:  # noqa: BLE001
            log(f'ERROR: {e}')
            return 1
    try:
        wizard()
    except ImportError:
        print('The setup window needs tkinter (part of the standard Python installer). Run: Setup.cmd /silent')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
