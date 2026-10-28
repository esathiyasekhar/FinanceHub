"""Finance Hub — background launcher (1.6).

Started with pythonw.exe (no console window) from the Start-menu / Desktop shortcut or run.bat. It:
  * makes sure only one Finance Hub runs (a second start just opens the browser);
  * copies the encrypted data to backups/ the first time a new version starts;
  * runs the web server in the background — Waitress (production server) when installed, otherwise Werkzeug —
    on 127.0.0.1 only, one request at a time;
  * shows a tray icon (Open · Lock now · Start with Windows · Open logs folder · Quit), when pystray is installed;
  * writes logs to logs/hub.log (rotated, no passwords or statement contents are logged).
"""
import logging
import logging.handlers
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from hub_version import APP_NAME, VERSION  # noqa: E402

import hub_paths  # noqa: E402
HOST = '127.0.0.1'
PORT = hub_paths.PORT
URL = f'http://{HOST}:{PORT}/'
DATA_ROOT = hub_paths.DATA_ROOT
LOG_DIR = hub_paths.LOG_DIR
BACKUP_DIR = hub_paths.BACKUP_DIR
KEEP_BACKUPS = 10
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'FinanceHub'
log = logging.getLogger('financehub')


# ── logging ─────────────────────────────────────────────────────────────────
def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(LOG_DIR / 'hub.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    for noisy in ('werkzeug', 'waitress.queue', 'pdfminer', 'PIL'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    class _ToLog:                                   # pythonw has no console: print() / tracebacks go to the log
        def __init__(self, level):
            self.level = level

        def write(self, s):
            s = s.strip()
            if s:
                logging.getLogger('console').log(self.level, s)

        def flush(self):
            pass
    if sys.stdout is None or 'pythonw' in Path(sys.executable).name.lower():
        sys.stdout, sys.stderr = _ToLog(logging.INFO), _ToLog(logging.ERROR)


def message_box(text, title=APP_NAME):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:  # noqa: BLE001  (not Windows)
        print(text)


# ── single instance ─────────────────────────────────────────────────────────
def running_hub():
    """'hub' when a Finance Hub already answers on the port, 'other' when another program uses it, '' when free."""
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            pass
    except OSError:
        return ''
    try:
        with urllib.request.urlopen(URL + 'healthz', timeout=2) as r:
            return 'hub' if r.read(40).startswith(b'FinanceHub') else 'other'
    except Exception:  # noqa: BLE001
        return 'other'


# ── backups when the version changes ────────────────────────────────────────
def backup_on_upgrade():
    data = DATA_ROOT / 'data'
    marker = data / '.version'
    if not data.is_dir() or not any(data.glob('*.enc')):
        data.mkdir(exist_ok=True)               # fresh install: remember the version so the next start makes no backup
        marker.write_text(VERSION)
        return None
    last = marker.read_text().strip() if marker.exists() else ''
    if last == VERSION:
        return None
    dest = BACKUP_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_before_{VERSION}"
    dest.mkdir(parents=True)
    for f in list(data.glob('*.enc')) + list(data.glob('*.enc.prev')):
        shutil.copy2(f, dest / f.name)
    for d in data.glob('*_files'):              # encrypted mail attachments waiting for review
        if d.is_dir():
            shutil.copytree(d, dest / d.name)
    if (DATA_ROOT / 'users.json').exists():
        shutil.copy2(DATA_ROOT / 'users.json', dest / 'users.json')
    (dest / 'FROM_VERSION.txt').write_text(f'Data as used by Finance Hub {last or "an earlier version"} — still encrypted.\n')
    marker.write_text(VERSION)
    import re
    olds = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}_\d{6}_before_', p.name))
    for p in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(p, ignore_errors=True)
    log.info('Encrypted data backed up to %s (version %s → %s)', dest.name, last or '?', VERSION)
    return dest


# ── start with Windows (current user only, no admin rights needed) ─────────
def _pythonw():
    exe = Path(sys.executable)
    w = exe.with_name('pythonw.exe')
    return w if w.exists() else exe


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:  # noqa: BLE001
        return False


def set_autostart(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{_pythonw()}" "{BASE / "FinanceHub.pyw"}" --background')
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        log.info('Start with Windows: %s', 'on' if on else 'off')
        return True
    except Exception as e:  # noqa: BLE001
        log.warning('Start with Windows could not be changed: %s', e)
        return False


# ── server ──────────────────────────────────────────────────────────────────
class Server:
    def __init__(self, app):
        self.app, self.srv, self.kind = app, None, ''

    def start(self):
        try:
            from waitress import create_server
            self.srv = create_server(self.app, host=HOST, port=PORT, threads=1, ident='FinanceHub',
                                     clear_untrusted_proxy_headers=True)
            self.kind = 'waitress'
            run = self.srv.run
        except ImportError:
            from werkzeug.serving import make_server
            self.srv = make_server(HOST, PORT, self.app, threaded=False)
            self.kind = 'werkzeug'
            run = self.srv.serve_forever
        t = threading.Thread(target=run, name='hub-server', daemon=True)
        t.start()
        log.info('%s %s serving on %s (%s)', APP_NAME, VERSION, URL, self.kind)
        return t

    def stop(self):
        try:
            if self.kind == 'waitress':
                self.srv.close()
            elif self.srv:
                self.srv.shutdown()
        except Exception:  # noqa: BLE001
            pass


def tray_image():
    from PIL import Image, ImageDraw
    png = BASE / 'static' / 'hub.png'
    if png.exists():
        return Image.open(png)
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), 14, fill=(99, 102, 241))
    d.text((22, 18), 'F', fill='white')
    return img


def main():
    setup_logging()
    background = '--background' in sys.argv
    state = running_hub()
    if state == 'hub':
        webbrowser.open(URL)
        return
    if state == 'other':
        message_box(f'Port {PORT} is used by another program, so {APP_NAME} cannot start.\n'
                    f'Close that program, or set FINANCEHUB_PORT to another number.')
        return
    try:
        backup_on_upgrade()
    except Exception as e:  # noqa: BLE001
        log.warning('Backup before upgrade failed: %s', e)
    import app as hub
    stop_event = threading.Event()
    server = Server(hub.app)
    icon_box = {}

    def quit_hub():
        log.info('Quit requested')
        try:
            hub.V.lock_now()                     # writes the encrypted database and forgets the key
        except Exception as e:  # noqa: BLE001
            log.warning('lock on quit: %s', e)
        server.stop()
        if icon_box.get('icon'):
            try:
                icon_box['icon'].stop()
            except Exception:  # noqa: BLE001
                pass
        stop_event.set()

    def lock_hub():
        try:
            hub.V.lock_now()
            log.info('Locked from the tray')
        except Exception as e:  # noqa: BLE001
            log.warning('lock: %s', e)

    hub.app.config.update(HUB_LAUNCHER=True, HUB_SHUTDOWN=lambda: threading.Timer(0.6, quit_hub).start(),
                          HUB_AUTOSTART_GET=autostart_enabled, HUB_AUTOSTART_SET=set_autostart,
                          HUB_SERVER=lambda: server.kind)
    server.start()
    import notify
    notify.start_scheduler()                     # payment reminders / weekly report by mail
    if not background:
        threading.Timer(1.2, lambda: webbrowser.open(URL)).start()
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem('Open Finance Hub', lambda icon, item: webbrowser.open(URL), default=True),
            pystray.MenuItem('Lock now', lambda icon, item: lock_hub()),
            pystray.MenuItem('Start with Windows', lambda icon, item: set_autostart(not autostart_enabled()),
                             checked=lambda item: autostart_enabled()),
            pystray.MenuItem('Open logs folder', lambda icon, item: os.startfile(str(LOG_DIR)) if hasattr(os, 'startfile') else None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit Finance Hub', lambda icon, item: quit_hub()))
        icon = pystray.Icon('FinanceHub', tray_image(), f'{APP_NAME} {VERSION}', menu)
        icon_box['icon'] = icon
        icon.run()                                # blocks until Quit
    except Exception as e:  # noqa: BLE001  (no tray available: keep running until Quit from the Hub's menu)
        log.info('Tray icon not available (%s) — use Quit in the Hub', e)
        while not stop_event.wait(1):
            pass
    stop_event.wait(5)
    log.info('%s stopped', APP_NAME)
    logging.shutdown()
    os._exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception:  # noqa: BLE001
        logging.getLogger('financehub').exception('Finance Hub could not start')
        message_box(f'{APP_NAME} could not start — see logs\\hub.log in the Finance Hub folder.')
        raise
