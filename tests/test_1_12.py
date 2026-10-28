"""1.12 — Wealth planner fixes (spouse inputs, monthly vs yearly figures, include switches) and mail deletion
(automatic after N days, Delete selected / Delete all → mailbox Trash). SYNTHETIC data only; the mailbox is faked."""
import os
import shutil
import subprocess
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh, HUB  # noqa: E402

SP = fresh('v112')
import app as A  # noqa: E402
import mailreader as M  # noqa: E402

# ── planner engine (node, when installed) ────────────────────────────────────
node = shutil.which('node')
if node:
    out = subprocess.run([node, str(HUB / 'tests' / 'planner_engine_check.js'), os.path.join(SP, 'static', 'planner', 'calculator.js')],
                         capture_output=True, text=True, timeout=120)
    print(out.stdout.strip())
    assert out.returncode == 0, out.stdout + out.stderr
else:
    print('node not installed — engine checks skipped')

A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})
h = c.get('/planner').get_data(as_text=True)
assert 'Self ₹/month' in h and 'Spouse added' in h and 'spouseOffNote' in h and 'lump sum and SIP' in h
js = open(os.path.join(SP, 'static', 'planner', 'planner.js'), encoding='utf-8').read()
assert "classList.toggle('is-dim'" in js and 'Spouse included in the plan' in js
print('planner page OK')

# ── mail deletion ────────────────────────────────────────────────────────────
GOOD = lambda d: f'mx.google.com; dkim=pass header.i=@{d} header.s=s1; spf=pass smtp.mailfrom={d}; dmarc=pass (p=REJECT) header.from={d}'


def mail(frm, subject, mid, att=None):
    m = EmailMessage()
    m['From'], m['Subject'], m['Message-ID'], m['Date'] = frm, subject, mid, 'Wed, 07 Oct 2026 10:00:00 +0530'
    m.set_content('Synthetic text.')
    if att:
        m.add_attachment(att[1], maintype='text', subtype='csv', filename=att[0])
    d = frm.split('@')[1].rstrip('>')
    return f'Authentication-Results: {GOOD(d)}\r\n'.encode() + m.as_bytes()


BOX = {1: mail('Bank <e@sbi.co.in>', 'Alert one', '<a1@x>'),
       2: mail('Bank <e@sbi.co.in>', 'Not a statement', '<a2@x>', ('junk.csv', b'nothing,here\n')),
       3: mail('Shop <s@shop.example>', 'Shop offer', '<a3@x>'),
       4: mail('Bank <e@sbi.co.in>', 'Alert two', '<a4@x>'),
       5: mail('Bank <e@sbi.co.in>', 'Alert three', '<a5@x>')}
TRASHED, STATE = [], {'down': False, 'swap': None}


class Fake:
    def __init__(self, host, port, user, secret):
        if STATE['down']:
            raise OSError('timed out')
    def select(self, f): return '777'
    def search_since(self, d): return sorted(BOX)
    def headers(self, uids): return {u: (BOX[u].split(b'\n\n')[0], len(BOX[u])) for u in uids if u in BOX}
    def message(self, uid): return BOX[uid]
    def label(self, uid, l): pass
    def message_id_of(self, uid):
        uid = int(uid)
        if STATE['swap'] == uid:
            return '<someone-else@x>'
        return {1: '<a1@x>', 2: '<a2@x>', 3: '<a3@x>', 4: '<a4@x>', 5: '<a5@x>'}.get(uid) if uid in BOX else None
    def trash(self, uid): TRASHED.append(int(uid)); BOX.pop(int(uid), None); return True
    def close(self): pass


A.app.config['HUB_IMAP_FACTORY'] = Fake
with A.app.test_request_context():
    con = A.get_db()
    M.ensure_schema(con)
    M.save_box(con, None, user='hub@gmail.com', password='abcdabcdabcdabcd', host='imap.gmail.com', port='993', provider='gmail',
               label='FinanceHub', name='Gmail')
    con.commit()
    assert M.shared(con)['delete_after'] == '3', 'automatic deletion after 3 days by default'
    M.check_mail(con, factory=Fake, force=True)
    st = {r['subject']: r['status'] for r in con.execute('SELECT subject, status FROM mail_items')}
    print('read:', st)
    assert st['Alert one'] == 'alert' and st['Shop offer'] == 'ignored' and st['Not a statement'] in ('skipped', 'error', 'review')
    assert not TRASHED, 'nothing deleted on the day it was read'
    # mails read before automatic deletion existed (the upgrade) are never deleted automatically
    assert M.shared(con)['delete_since']
    con.execute("UPDATE mail_items SET created_at=datetime('now', '-4 day'), handled_at=NULL")
    con.commit()
    M.check_mail(con, factory=Fake, force=True)
    assert not TRASHED, 'mails read before the upgrade stay'
    con.execute("UPDATE mail_settings SET value=datetime('now', '-30 day') WHERE key='delete_since'")
    # four days later
    STATE['swap'] = 4                                          # mail 4's UID now holds a different mail
    # a second file of mail 5 still waits → mail 5 stays in the mailbox
    con.execute("INSERT INTO mail_items (message_id, uid, received, from_domain, subject, status, kind, mailbox_id, created_at) "
                "VALUES ('<a5@x>', '5', '2026-10-07', 'sbi.co.in', 'Alert three (2nd file)', 'review', 'statement', 1, datetime('now', '-4 day'))")
    con.execute("UPDATE mail_items SET status='imported' WHERE subject='Not a statement'")     # its data was imported just now
    assert con.execute("SELECT handled_at FROM mail_items WHERE subject='Not a statement'").fetchone()[0], 'status change stamps handled_at'
    con.commit()
    M.check_mail(con, factory=Fake, force=True)
    assert 2 not in TRASHED, 'imported just now (after waiting) — not deleted yet'
    con.execute("UPDATE mail_items SET handled_at=datetime('now', '-4 day')")
    con.commit()
    M.check_mail(con, factory=Fake, force=True)
    rows = {r['message_id']: dict(r) for r in con.execute("SELECT * FROM mail_items WHERE subject IS NULL OR subject NOT LIKE '%2nd file%'")}
    assert rows['<a2@x>']['status'] == 'deleted' and rows['<a2@x>']['trash'] == 'done' and rows['<a2@x>']['subject'] is None
    assert rows['<a1@x>']['status'] == 'alert' and rows['<a1@x>']['trash'] == 'done', 'alerts move to the Trash but stay in the Hub'
    assert rows['<a4@x>']['trash'] == 'kept', 'a UID that now holds another mail is left alone'
    assert rows['<a3@x>']['status'] == 'ignored' and not rows['<a3@x>']['trash'], 'other senders are not deleted automatically'
    assert sorted(TRASHED) == [1, 2], TRASHED
    assert rows['<a5@x>']['status'] == 'alert' and not rows['<a5@x>']['trash'], 'another file of the same mail still waits'
    assert '<a2@x>' in {r[0] for r in con.execute('SELECT message_id FROM mail_items')}, 'the Message-ID stays: never read again'
STATE['swap'] = None
h = c.get('/mail?tab=statements').get_data(as_text=True)
assert 'Not a statement' not in h and 'Delete selected' in h and 'deleted automatically after 3 days' in h
assert 'deleted from the mailbox' in c.get('/mail?tab=alerts').get_data(as_text=True)
# manual: Delete selected while the mailbox is unreachable → retried on the next check
with A.app.test_request_context():
    iid = A.get_db().execute("SELECT id FROM mail_items WHERE message_id='<a3@x>'").fetchone()[0]
STATE['down'] = True
r = c.post('/mail/delete', data={'tab': 'ignored', 'item': [str(iid)]}, follow_redirects=True)
assert 'removed from the list' in r.get_data(as_text=True) and 'tries again on the next check' in r.get_data(as_text=True)
with A.app.test_request_context():
    row = A.get_db().execute('SELECT status, trash, trash_note FROM mail_items WHERE id=?', (iid,)).fetchone()
    assert row['status'] == 'deleted' and row['trash'] == 'pending' and 'will retry' in row['trash_note']
STATE['down'] = False
with A.app.test_request_context():
    M.check_mail(A.get_db(), factory=Fake, force=True)
    assert A.get_db().execute('SELECT trash FROM mail_items WHERE id=?', (iid,)).fetchone()[0] == 'done' and 3 in TRASHED
# Delete all on the Statements tab keeps files waiting for you
r = c.post('/mail/delete', data={'tab': 'statements', 'scope': 'all'}, follow_redirects=True)
with A.app.test_request_context():
    assert A.get_db().execute("SELECT status FROM mail_items WHERE subject='Alert three (2nd file)'").fetchone()[0] == 'review'
# Delete all on the Alerts tab
r = c.post('/mail/delete', data={'tab': 'alerts', 'scope': 'all'}, follow_redirects=True)
assert 'removed from the list' in r.get_data(as_text=True)
with A.app.test_request_context():
    assert not A.get_db().execute("SELECT COUNT(*) FROM mail_items WHERE status='alert'").fetchone()[0]
r = c.post('/mail/delete', data={'tab': 'alerts'}, follow_redirects=True)
assert 'Tick the mails to delete first' in r.get_data(as_text=True)
# switch automatic deletion off
c.post('/mail/settings', data={'interval': '15', 'since_days': '60', 'delete_after': '0', 'enabled': 'on', 'forwarders': ''})
with A.app.test_request_context():
    con = A.get_db()
    assert M.shared(con)['delete_after'] == '0'
    assert M.mark_old_for_deletion(con) == 0
for u in ['/mail', '/mail?tab=review', '/mail?tab=alerts', '/mail?tab=ignored']:
    assert c.get(u).status_code == 200, u
# Imap.trash never deletes for good: no Trash folder → error; without UIDPLUS no EXPUNGE
class FakeM:
    def __init__(self, folders, caps): self.folders, self.calls = folders, []
    def list(self): return 'OK', [f'(\\HasNoChildren{" " + fl if fl else ""}) "/" "{n}"'.encode() for n, fl in self.folders]
    def uid(self, *a): self.calls.append(a); return 'OK', [None]
    def expunge(self): self.calls.append(('EXPUNGE-ALL',)); return 'OK', [None]
im = M.Imap.__new__(M.Imap)
im.m, im.caps = FakeM([('INBOX', ''), ('Archive', '')], set()), {'IMAP4REV1'}
try:
    im.trash(9)
    raise SystemExit('expected an error without a Trash folder')
except RuntimeError as e:
    assert 'no Trash folder' in str(e) and not any(c[0] in ('STORE', 'EXPUNGE') for c in im.m.calls)
im = M.Imap.__new__(M.Imap)
im.m, im.caps = FakeM([('INBOX', ''), ('Deleted Items', '\\Trash')], set()), {'IMAP4REV1'}
assert im.trash(9) and im.m.calls[0][:2] == ('COPY', '9') and ('EXPUNGE-ALL',) not in im.m.calls
assert not any(c[0] == 'EXPUNGE' for c in im.m.calls), 'no expunge without UIDPLUS'
print('mail deletion OK')
print('ALL 1.12 OK')
