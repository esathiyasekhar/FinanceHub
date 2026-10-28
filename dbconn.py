"""Where database connections come from (1.2: the encrypted vault once the user has logged in)."""
import json
import sqlite3

VAULT = None            # set by app.py


def connect(path=None):
    if VAULT is not None:
        return VAULT.connect()
    return sqlite3.connect(str(path))


def write_sealed(path, obj):
    """Import previews waiting for confirmation are encrypted with the database key."""
    if VAULT is not None and VAULT.unlocked:
        path.write_bytes(VAULT.seal(obj))
    else:
        path.write_text(json.dumps(obj, default=str), encoding='utf-8')


def read_sealed(path):
    blob = path.read_bytes()
    if VAULT is not None and VAULT.unlocked:
        return VAULT.unseal(blob)
    return json.loads(blob.decode('utf-8'))
