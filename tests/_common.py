"""Every test runs on a fresh copy of the program in a temporary folder, with SYNTHETIC data only."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns('__pycache__', '.git', '.venv', 'data', 'users.json', 'uploads', 'backups', 'logs', 'dist',
                                'finance.db*', 'tests', 'financehub.json')


os.environ.setdefault('FINANCEHUB_PRICES', '0')      # no price downloads from the tests (test_1_9 fakes them)


def fresh(name):
    """Copy the program to a new temp folder, make it the working folder and import path. → folder (str)"""
    root = Path(tempfile.mkdtemp(prefix=f'fh_{name}_'))
    dest = root / 'hub'
    shutil.copytree(HUB, dest, ignore=IGNORE)
    os.chdir(dest)
    sys.path.insert(0, str(dest))
    return str(dest)
