"""Where the program and the data live (1.7).

The program folder (e.g. C:\\Program Files\\Finance Hub) holds only the program. Everything that changes — the encrypted
databases (data\\), users.json, uploads, logs and backups — lives in the DATA folder (e.g. D:\\Finance Hub), chosen by
the installer and written to financehub.json beside the program:
    {"data_dir": "D:\\\\Finance Hub", "port": 5000}
Without that file (a portable copy, or the tests) the data stays in the program folder, as in earlier versions.
The environment variables FINANCEHUB_DATA and FINANCEHUB_PORT override the file.
"""
import json
import os
from pathlib import Path

PROGRAM_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROGRAM_DIR / 'financehub.json'


def config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _data_root():
    env = os.environ.get('FINANCEHUB_DATA')
    if env:
        return Path(env)
    d = config().get('data_dir')
    return Path(d) if d else PROGRAM_DIR


DATA_ROOT = _data_root()
try:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
UPLOAD_DIR = DATA_ROOT / 'uploads'
LOG_DIR = DATA_ROOT / 'logs'
BACKUP_DIR = DATA_ROOT / 'backups'
PORT = int(os.environ.get('FINANCEHUB_PORT') or config().get('port') or 5000)
INSTALLED = CONFIG_FILE.exists()
