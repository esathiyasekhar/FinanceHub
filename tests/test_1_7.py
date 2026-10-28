"""1.7 — separate data folder, admin password reset / user-ID change, backup & restore, problem reports, setup wizard.
SYNTHETIC data only."""
import io
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('v17')
DATA = tempfile.mkdtemp(prefix='fh_data_')
CLOUD = tempfile.mkdtemp(prefix='fh_cloud_')
os.environ['FINANCEHUB_DATA'] = DATA
os.environ['FINANCEHUB_CLOUD_DIRS'] = CLOUD
import app as A  # noqa: E402
import backup as B  # noqa: E402
import support as S  # noqa: E402
import hub_paths  # noqa: E402

A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Owner', 'username': 'owner', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'owner', 'password': PW})

# ── data folder separate from the program ────────────────────────────────────
assert Path(A.V.base) == Path(DATA) and (Path(DATA) / 'users.json').exists() and any((Path(DATA) / 'data').glob('*.enc'))
assert not (Path(SP) / 'users.json').exists() and not (Path(SP) / 'data').exists(), 'nothing written to the program folder'
assert hub_paths.UPLOAD_DIR == Path(DATA) / 'uploads'
print('data folder OK')

# ── users: escrow, reset, rename, must change ───────────────────────────────
doc = A.V.users_doc()
assert doc.get('escrow') and doc['users']['owner'].get('escrow_key') and doc['users']['owner'].get('escrow_dek')
r = c.post('/users/save', data={'action': 'add', 'username': 'member1', 'full_name': 'Member One', 'password': 'Member pass 77', 'password2': 'Member pass 77', 'role': 'member'}, follow_redirects=True)
assert 'member1 added' in r.get_data(as_text=True)
assert A.V.users_doc()['users']['member1'].get('escrow_dek')
# the member puts something in their data
c.post('/logout')
c.post('/login', data={'username': 'member1', 'password': 'Member pass 77'})
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO accounts (name, bank, type, kind) VALUES ('Member Savings', 'Test Bank', 'savings', 'bank')")
    con.commit()
c.get('/')
c.post('/logout')
c.post('/login', data={'username': 'owner', 'password': PW})
h = c.get('/users').get_data(as_text=True)
assert 'Reset…' in h and 'Change user ID' in h
r = c.post('/users/save', data={'action': 'reset', 'username': 'member1', 'password': 'Temporary pass 11', 'password2': 'Temporary pass 11'}, follow_redirects=True)
assert 'New password set for member1' in r.get_data(as_text=True)
c.post('/logout')
assert c.post('/login', data={'username': 'member1', 'password': 'Member pass 77'}, follow_redirects=True).get_data(as_text=True).count('Wrong user ID') == 1
r = c.post('/login', data={'username': 'member1', 'password': 'Temporary pass 11'})
r = c.get('/')
assert r.status_code == 302 and '/account/password' in r.headers['Location'], 'must choose own password'
r = c.post('/account/password', data={'current': 'Temporary pass 11', 'password': 'Member new pass 9', 'password2': 'Member new pass 9'})
assert r.status_code == 302 and c.get('/').status_code in (200, 302)
with A.app.test_request_context():
    assert A.get_db().execute("SELECT COUNT(*) FROM accounts WHERE name='Member Savings'").fetchone()[0] == 1, 'member data intact after reset'
# member changes own user ID
r = c.post('/users/save', data={'action': 'rename', 'username': 'member1', 'new_username': 'member.one', 'current': 'Member new pass 9'}, follow_redirects=True)
assert 'Your user ID is now member.one' in r.get_data(as_text=True)
c.post('/logout')
assert c.post('/login', data={'username': 'member.one', 'password': 'Member new pass 9'}).status_code == 302
assert A.V.user == 'member.one'
# a member cannot reset others
r = c.post('/users/save', data={'action': 'reset', 'username': 'owner', 'password': 'Hack attempt 999', 'password2': 'Hack attempt 999'}, follow_redirects=True)
assert 'Only an administrator' in r.get_data(as_text=True)
c.post('/logout')
c.post('/login', data={'username': 'owner', 'password': PW})
# admin renames the member together with a temporary password
r = c.post('/users/save', data={'action': 'rename_other', 'username': 'member.one', 'new_username': 'member2', 'password': 'Another temp 222', 'password2': 'Another temp 222'}, follow_redirects=True)
assert 'member.one is now member2' in r.get_data(as_text=True), re.findall(r'alert-\w+[^>]*>\s*([^<]+)', r.get_data(as_text=True))
assert A.V.users_doc()['users']['member2']['must_change']
# promoting gives the reset key
c.post('/users/save', data={'action': 'role', 'username': 'member2', 'role': 'admin'})
assert A.V.users_doc()['users']['member2'].get('escrow_key')
print('users OK')

# ── backup & restore ─────────────────────────────────────────────────────────
assert any(p == CLOUD for _, p in B.cloud_folders())
r = c.post('/backup/save', data={'where': CLOUD, 'every': 'daily', 'keep': '3'}, follow_redirects=True)
assert 'Backup settings saved' in r.get_data(as_text=True)
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO accounts (name, bank, type, kind) VALUES ('Owner Savings', 'Test Bank', 'savings', 'bank')")
    con.commit()
c.get('/')
r = c.post('/backup/now', follow_redirects=True)
assert 'Backed up to' in r.get_data(as_text=True)
files = list((Path(CLOUD) / B.FOLDER_NAME).glob('FinanceHub_owner_*.fhb'))
assert len(files) == 1
raw = files[0].read_bytes()
assert b'Owner Savings' not in raw and b'Test Bank' not in raw, 'backup must be encrypted'
dl = c.get('/backup/download')
assert dl.status_code == 200 and dl.data[:2] == b'PK'
# change data, then restore the backup (same key)
with A.app.test_request_context():
    con = A.get_db()
    con.execute("DELETE FROM accounts WHERE name='Owner Savings'")
    con.commit()
c.get('/')
r = c.post('/backup/restore', data={'path': str(files[0])}, follow_redirects=True)
assert 'Restored the backup' in r.get_data(as_text=True), r.get_data(as_text=True)[-1500:]
with A.app.test_request_context():
    assert A.get_db().execute("SELECT COUNT(*) FROM accounts WHERE name='Owner Savings'").fetchone()[0] == 1
assert c.get('/accounts').status_code == 200, 'still logged in after restore'
assert list(hub_paths.BACKUP_DIR.rglob('FinanceHub_owner_*.fhb')), 'safety copy before restore'
# a damaged file is refused
bad = bytearray(raw)
bad[len(bad) // 2] ^= 0xFF
r = c.post('/backup/restore', data={'file': (io.BytesIO(bytes(bad)), 'x.fhb')}, content_type='multipart/form-data', follow_redirects=True)
assert 'Not restored' in r.get_data(as_text=True)
# automatic backups: due, and only when data changed
import time  # noqa: E402
B.save_settings(A.V, 'owner', last='2000-01-01T00:00:00', last_mtime=0)
assert B.run_due(A.V) >= 1
assert B.run_due(A.V) == 0, 'not again so soon'
# another user's backup cannot be restored into this account
other = B.make_backup(A.V, 'member2', None)
r = c.post('/backup/restore', data={'file': (io.BytesIO(other), 'o.fhb'), 'password': 'Another temp 222'}, content_type='multipart/form-data', follow_redirects=True)
assert 'belongs to another user' in r.get_data(as_text=True)
print('backup OK')

# ── restore on a new computer ────────────────────────────────────────────────
pw_then = PW
c.post('/logout')
import vault as VT  # noqa: E402
NEW = tempfile.mkdtemp(prefix='fh_new_')
V2 = VT.Vault(NEW)
B.restore_fresh(V2, files[0].read_bytes(), pw_then)
ok, msg = V2.login('owner', pw_then)
assert ok, msg
assert V2.connect().execute("SELECT COUNT(*) FROM accounts WHERE name='Owner Savings'").fetchone()[0] == 1
try:
    B.restore_fresh(V2, files[0].read_bytes(), pw_then)
    raise AssertionError('second fresh restore must be refused')
except ValueError:
    pass
V3 = VT.Vault(tempfile.mkdtemp(prefix='fh_new2_'))
try:
    B.restore_fresh(V3, files[0].read_bytes(), 'wrong password 1')
    raise AssertionError('wrong password must be refused')
except ValueError:
    pass
print('fresh restore OK')

# ── problem reports ─────────────────────────────────────────────────────────
s = S.scrub('Failed for 4000123412341234 on 12,34,567.50 at C:\\Users\\someone\\stmt.pdf mail me@mail.example PAN ABCDE1234F')
assert '4000123412341234' not in s and '12,34,567' not in s and 'someone' not in s and 'me@mail' not in s and 'ABCDE1234F' not in s, s
c.post('/login', data={'username': 'owner', 'password': PW})
h = c.get('/support?summary=Test+problem&what=Something+broke').get_data(as_text=True)
from hub_version import VERSION
assert f'Finance Hub {VERSION}' in h and 'amirthamilserve@gmail.com' in h
r = c.post('/support/send', data={'summary': 'Test problem', 'what': 'x', 'action': 'download', 'diag': '1', 'logs': '1'})
assert r.status_code == 200 and b'Summary: Test problem' in r.data and b'Technical details' in r.data
r = c.post('/support/send', data={'summary': 'Test problem', 'action': 'mailto'})
assert r.status_code == 302 and r.headers['Location'].startswith('mailto:amirthamilserve@gmail.com')
sent = []


class FakeSMTP:
    def __init__(self, smtp):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m):
        sent.append(m)

    def quit(self):
        pass


A.app.config['HUB_SMTP_FACTORY'] = FakeSMTP
with A.app.test_request_context():
    con = A.get_db()
    import mailreader as MR
    MR.ensure_schema(con)
    for k, v in {'user': 'hub@gmail.com', 'password': 'abcdabcdabcdabcd'}.items():
        con.execute('INSERT OR REPLACE INTO mail_settings (key, value) VALUES (?,?)', (k, v))
    con.commit()
r = c.post('/support/send', data={'summary': 'Test problem', 'what': 'Card 4000123412341234 failed', 'contact': 'me@example.com', 'action': 'send'},
           follow_redirects=True)
assert 'your report was sent' in r.get_data(as_text=True) and sent and sent[0]['To'] == 'amirthamilserve@gmail.com'
assert sent[0]['Reply-To'] == 'me@example.com'
# a server error page offers a report with a reference
A.app.testing = False
A.app.config['PROPAGATE_EXCEPTIONS'] = False


def _boom(*a, **k):
    raise RuntimeError('boom for test 123456')


A.app.view_functions['dues_page'] = _boom
r = c.get('/dues')
assert r.status_code == 500 and b'Report this problem' in r.data and b'Error reference' in r.data
A.app.testing = True
print('support OK')

# ── setup wizard ────────────────────────────────────────────────────────────
A.app.config['FH_WIZARD'] = True
c.post('/logout')
c.post('/login', data={'username': 'member2', 'password': 'Another temp 222'})
c.post('/account/password', data={'current': 'Another temp 222', 'password': 'M2 own pass 123', 'password2': 'M2 own pass 123'})
r = c.get('/')
assert r.status_code == 302 and '/welcome/you' in r.headers['Location']
c.post('/welcome/you', data={'display_name': 'Member Two', 'company': 'ABC Traders Pvt Ltd', 'company_aliases': 'ABC TRADERS'})
c.post('/welcome/mail', data={'user': 'm2hub@gmail.com', 'password': 'wxyz wxyz wxyz wxyz', 'auto': 'on', 'recipients': 'm2@example.com', 'remind': 'on'})
c.post('/welcome/features', data={'on': ['bank', 'cards', 'business', 'mail', 'reminders']})
c.post('/welcome/accounts', data={})
r = c.post('/welcome/backup', data={'where': CLOUD, 'every': 'weekly', 'then': 'home'})
assert r.status_code == 302 and r.headers['Location'].endswith('/')
with A.app.test_request_context():
    con = A.get_db()
    hs = dict(con.execute('SELECT key, value FROM hub_settings').fetchall())
    assert hs['display_name'] == 'Member Two' and hs['onboarding'] == 'done' and 'investments' in hs['features_off']
    assert con.execute("SELECT 1 FROM entities WHERE name='ABC Traders Pvt Ltd' AND role='book'").fetchone()
    mb = con.execute('SELECT * FROM mailboxes').fetchall()
    assert len(mb) == 1 and mb[0]['password'] == 'wxyzwxyzwxyzwxyz' and mb[0]['send_from'] == 1
    assert 'password' not in dict(con.execute('SELECT key, value FROM mail_settings').fetchall())
    assert 'm2@example.com' in dict(con.execute('SELECT key, value FROM notify_settings').fetchall())['recipients']
assert B.settings_of(A.V, 'member2')['every'] == 'weekly'
assert c.get('/').status_code == 200, 'wizard only once'
for u in ['/welcome/you', '/welcome/mail', '/welcome/features', '/welcome/accounts', '/welcome/backup', '/backup', '/support']:
    assert c.get(u).status_code == 200, u
print('wizard OK')
print('ALL 1.7 OK')
