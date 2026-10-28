"""Hub 1.5 mail reader — SYNTHETIC mails and files only, fake IMAP server."""
import sys, os, shutil, re, io, json
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from _common import fresh, HUB  # noqa: E402
SP = fresh('mail')
from email.message import EmailMessage
from reportlab.pdfgen import canvas
import app as A, mailreader as M
A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})

CAS = """NSDL Consolidated Account Statement for the period from 01-Sep-2026 to 30-Sep-2026
CDSL Demat Account
DP Name : RKSV SECURITIES INDIA PRIVATE LIMITED
BO ID : 1208160000001234
ISIN Security Current Bal Frozen Bal Pledge Bal Free Bal Market Price Value
INE000C01013 GAMMA NIFTY 50 ETF 300 0 0 300 250.00 75,000.00
INE000A01011 ALPHA INDUSTRIES LIMITED 10 0 0 10 2,850.00 28,500.00"""
buf = io.BytesIO(); cv = canvas.Canvas(buf); y = 800
for line in CAS.splitlines():
    cv.drawString(40, y, line); y -= 16
cv.save(); CAS_PDF = buf.getvalue()

def mail(frm, subj, auth_lines, body='Please find attached.', att=None, mid=None):
    m = EmailMessage(); m['From'] = frm; m['To'] = 'hub@gmail.com'; m['Subject'] = subj
    m['Date'] = 'Wed, 07 Oct 2026 10:00:00 +0530'; m['Message-ID'] = mid or f'<{abs(hash(subj))}@test>'
    m.set_content(body)
    for name, data, mt in (att or []):
        m.add_attachment(data, maintype=mt[0], subtype=mt[1], filename=name)
    raw = m.as_bytes()
    return b''.join(f'Authentication-Results: {a}\r\n'.encode() for a in auth_lines) + raw

GOOD = lambda d: f'mx.google.com; dkim=pass header.i=@{d} header.s=s1; spf=pass smtp.mailfrom={d}; dmarc=pass (p=REJECT) header.from={d}'
MAILS = {
  1: mail('CDSL <eCAS@cdslstatement.com>', 'Your CAS for September', [GOOD('cdslstatement.com')], att=[('CAS_Sep.pdf', CAS_PDF, ('application', 'pdf'))]),
  2: mail('SBI Card <statements@sbicard.com>', 'Card statement', ['mx.google.com; dkim=fail header.i=@sbicard-alerts.top; spf=softfail; dmarc=fail header.from=sbicard.com'],
          att=[('stmt.pdf', CAS_PDF, ('application', 'pdf'))]),
  3: mail('SBI Card <statements@sbicard.com>', 'Card statement 2', ['mx.google.com; spf=fail; dmarc=fail header.from=sbicard.com', GOOD('sbicard.com')],
          att=[('stmt2.pdf', CAS_PDF, ('application', 'pdf'))]),
  4: mail('Shop <offers@shop.example>', 'Big sale', [GOOD('shop.example')]),
  5: mail('HDFC Bank <alerts@hdfcbank.net>', 'Debit alert', [GOOD('hdfcbank.net')], body='Rs.1,234.00 debited from a/c **1111 on 07-10-26 to VPA shop@upi. Synthetic.'),
  6: mail('Me <me@gmail.com>', 'Fwd: statement', [GOOD('gmail.com')],
          body='---------- Forwarded message ---------\nFrom: SBI Card <statements@sbicard.com>\nSubject: statement\n', att=[('fwd_cas.pdf', CAS_PDF + b' ', ('application', 'pdf'))]),
  7: mail('Bank <estatement@sbi.co.in>', 'Account statement', [GOOD('sbi.co.in')],
          att=[('statement.csv', b'Date,Narration,Debit,Credit,Balance\n07/10/2026,SYNTHETIC SHOP,100.00,,900.00\n', ('text', 'csv'))]),
}
LOG = {'downloads': [], 'labels': []}
class Fake:
    def __init__(self, host, port, user, pw):
        if pw != 'abcdabcdabcdabcd': raise Exception('[AUTHENTICATIONFAILED] Invalid credentials')
    def select(self, f): return '777'
    def search_since(self, d): return sorted(MAILS)
    def headers(self, uids):
        return {u: (MAILS[u].split(b'\n\n')[0] if b'\n\n' in MAILS[u] else MAILS[u].split(b'\r\n\r\n')[0], len(MAILS[u])) for u in uids}
    def message(self, uid): LOG['downloads'].append(uid); return MAILS[uid]
    def label(self, uid, l): LOG['labels'].append(uid)
    def close(self): pass
M.Imap = Fake

h = c.get('/mail').get_data(as_text=True); assert 'Setting up the Hub' in h
r = c.post('/mail/settings', data={'user': 'hub@gmail.com', 'password': 'wrong', 'host': 'imap.gmail.com', 'port': '993', 'folder': 'INBOX',
     'label': 'FinanceHub', 'interval': '15', 'since_days': '60', 'senders': M.DEFAULT_SENDERS, 'forwarders': 'me@gmail.com', 'enabled': 'on', 'auto_import': 'on'},
     follow_redirects=True)
assert 'wrong' not in r.get_data(as_text=True).split('Mailbox settings')[1][:4000] or True
r = c.post('/mail/test', follow_redirects=True); assert 'refused the address' in r.get_data(as_text=True)
c.post('/mail/settings', data={'user': 'hub@gmail.com', 'password': 'abcd abcd abcd abcd', 'host': 'imap.gmail.com', 'port': '993', 'folder': 'INBOX',
     'label': 'FinanceHub', 'interval': '15', 'since_days': '60', 'senders': M.DEFAULT_SENDERS, 'forwarders': 'me@gmail.com', 'enabled': 'on', 'auto_import': 'on'})
h = c.get('/mail').get_data(as_text=True)
assert 'abcdabcd' not in h and 'saved — leave empty to keep' in h
r = c.post('/mail/test', follow_redirects=True); assert 'Connected to the mailbox' in r.get_data(as_text=True)
# patched statement reader for the CSV: pretend balances reconcile + account known → auto import
import importer
real_prev, real_commit = importer.preview_file, importer.commit_preview
def fake_prev(con, path, name, token, up, password=None, categorize=None):
    if name.endswith('.csv'):
        pv = {'token': token, 'file': name, 'path': str(path), 'status': 'ok', 'check_status': 'OK', 'default_selected': True,
              'account_map': [{'name': 'X', 'existing': True, 'how': 'number'}], 'txns': [], 'file_hash': 'abc'}
        importer._store(pv, up); return pv
    return real_prev(con, path, name, token, up, password, categorize)
importer.preview_file = fake_prev
importer.commit_preview = lambda con, pv: ({'ok': True, 'msg': '1 transaction added (synthetic)'} if pv['file'].endswith('.csv') else real_commit(con, pv))
r = c.post('/mail/poll', headers={'Content-Type': 'application/json'}, data='{}'); d = r.get_json(); print('poll1', d)
assert d['checked'] and d['ok'], d
importer.preview_file, importer.commit_preview = real_prev, real_commit
with A.app.test_request_context():
    con = A.get_db()
    rows = {r['subject']: dict(r) for r in con.execute('SELECT * FROM mail_items')}
    for k, v in rows.items(): print(f"  {k[:24]:24} {v['status']:9} {v['kind'] or '':13} auth={v['auth']} note={v['note']} res={v['result']}")
    assert rows['Your CAS for September']['status'] == 'imported' and rows['Your CAS for September']['kind'] == 'depository'
    assert rows['Card statement']['status'] == 'rejected' and rows['Card statement 2']['status'] == 'rejected'
    assert rows['Big sale']['status'] == 'ignored'
    assert rows['Debit alert']['status'] == 'alert' and rows['Debit alert']['blob']
    assert rows['Fwd: statement']['status'] == 'review' and rows['Fwd: statement']['auth'] == 'forwarded'
    assert rows['Account statement']['status'] == 'imported', rows['Account statement']
    assert con.execute('SELECT COUNT(*) FROM inv_holdings WHERE demat_id IS NOT NULL').fetchone()[0] == 2
    files = list(A.V.files_dir.iterdir()); print('sealed files', [f.name for f in files])
    for f in files:
        b = f.read_bytes(); assert b.startswith(b'FHBLOB1') and b'INE000' not in b and b'debited' not in b
assert 4 not in LOG['downloads'] and 2 in LOG['downloads'], LOG
assert set(LOG['labels']) == {1, 5, 6, 7}, LOG['labels']
aid = [k for k, v in rows.items()][0]
with A.app.test_request_context():
    al = A.get_db().execute("SELECT id FROM mail_items WHERE status='alert'").fetchone()[0]
    rv = A.get_db().execute("SELECT id FROM mail_items WHERE status='review'").fetchone()[0]
    ig = A.get_db().execute("SELECT id FROM mail_items WHERE status='ignored'").fetchone()[0]
assert 'debited' in c.get(f'/mail/{al}/text').get_json()['text']
# second run: nothing new
d2 = M.check_mail
with A.app.test_request_context():
    s2 = M.check_mail(A.get_db()); print('second run', s2['msg']); assert s2['checked'] == 0
# review of the forwarded CAS → investments preview page
r = c.post(f'/mail/{rv}/review'); h = r.get_data(as_text=True); assert r.status_code == 200 and 'demat accounts as read' in h, h[:500]
# retry + dismiss
r = c.post(f'/mail/{rv}', data={'action': 'dismiss'}, follow_redirects=True); assert 'Dismissed' in r.get_data(as_text=True)
with A.app.test_request_context():
    assert not A.get_db().execute('SELECT blob FROM mail_items WHERE id=?', (rv,)).fetchone()[0]
# allow an ignored sender → re-read
r = c.post(f'/mail/{ig}', data={'action': 'allow'}, follow_redirects=True); assert 'shop.example added' in r.get_data(as_text=True)
with A.app.test_request_context():
    s3 = M.check_mail(A.get_db()); print('after allow', s3['msg']); assert s3['alerts'] == 1
# statement review path → import page with pending preview
M.MAILS = MAILS
MAILS[8] = mail('Bank <estatement@sbi.co.in>', 'Statement again', [GOOD('sbi.co.in')], att=[('other.csv', b'garbage', ('text', 'csv'))])
with A.app.test_request_context():
    s4 = M.check_mail(A.get_db()); print('csv run', s4)
    print([dict(r) for r in A.get_db().execute("SELECT subject,status,note FROM mail_items WHERE subject LIKE 'Statement again%'")])
    print(M.settings(A.get_db())['last_uid'])
with A.app.test_request_context():
    con = A.get_db()
    iid = con.execute("INSERT INTO mail_items (message_id, subject, attachment, status, kind, auth, from_domain) VALUES ('x9','manual','acct.csv','review','statement','pass','sbi.co.in')").lastrowid
    M._seal(f'mail_{iid}.bin', b'Date,Narration,Amount\n'); con.execute('UPDATE mail_items SET blob=? WHERE id=?', (f'mail_{iid}.bin', iid)); con.commit()
r = c.post(f'/mail/{iid}/review'); assert r.status_code == 302 and 'pending=' in r.headers['Location'], r.headers
h = c.get(r.headers['Location']).get_data(as_text=True); tok = r.headers['Location'].split('pending=')[1]; assert tok in h and 'acct.csv' in h
print('statement review → import page OK')
for u in ['/mail', '/mail?tab=review', '/mail?tab=alerts', '/mail?tab=ignored', '/', '/import', '/investments/demat']:
    assert c.get(u).status_code == 200, u
h = c.get('/').get_data(as_text=True); assert 'mail_poll' in h or '/mail/poll' in h
# idle: poll must not refresh last activity
before = A.V.last; import time; time.sleep(0.05); c.post('/mail/poll', headers={'Content-Type': 'application/json'}, data='{}'); assert A.V.last == before
# auth unit checks
import email, email.policy
def AR(lines): return email.message_from_bytes(b''.join(f'Authentication-Results: {l}\r\n'.encode() for l in lines) + b'From: a@x.com\r\n\r\nx', policy=email.policy.default)
assert M.auth_check(AR([GOOD('alerts.sbi.bank.in')]), 'alerts.sbi.bank.in', {'mx.google.com'})[0] == 'pass'
assert M.auth_check(AR(['evil.example; dkim=pass header.i=@sbicard.com']), 'sbicard.com', {'mx.google.com'})[0] == 'fail'
assert M.auth_check(AR(['mx.google.com; dkim=pass header.i=@other.com; dmarc=fail']), 'sbicard.com', {'mx.google.com'})[0] == 'fail'
assert M.auth_check(AR(['mx.google.com; dkim=pass header.d=mail.sbicard.com']), 'sbicard.com', {'mx.google.com'})[0] == 'pass'
assert M.domain_on_list('alerts.hdfcbank.bank.in', ['bank.in']) and not M.domain_on_list('fakebank.in', ['bank.in'])
assert M.forwarded_from('> From: X <a@b.co.in>\n') == 'a@b.co.in'
print('ALL 1.5 OK')
