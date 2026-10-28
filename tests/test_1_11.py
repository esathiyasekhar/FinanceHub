"""1.11 — card / EMI due dates in full; senders to read as exact addresses or domains, with add / pause / delete.
SYNTHETIC data only; the mailbox is faked."""
import os
import sys
from datetime import date, timedelta
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('v111')
import app as A  # noqa: E402
import accounts_hub as AH  # noqa: E402
import mailreader as M  # noqa: E402

A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})

# ── due dates in full ────────────────────────────────────────────────────────
assert A.full_date('2026-11-15') == 'Sun, 15 Nov 2026' and A.full_date(date(2026, 11, 20)) == 'Fri, 20 Nov 2026'
assert A.full_date('') == '' and A.full_date(None) == ''
t = date.today()
assert A.due_in(t) == 'today' and A.due_in(t + timedelta(days=1)) == 'tomorrow' and A.due_in(t + timedelta(days=5)) == 'in 5 days'
assert A.due_in(t - timedelta(days=1)) == '1 day overdue' and A.due_in(t - timedelta(days=3)) == '3 days overdue'
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO accounts (name, card_no, bank, type, kind, credit_limit, due_day) "
                "VALUES ('Test Card 9999', '4000XXXXXXXX9999', 'Test Bank', 'credit_card', 'card', 100000, 15)")
    con.commit()
nd = AH.next_on_day(15, t)
h = c.get('/accounts?tab=card').get_data(as_text=True)
assert 'Next due' in h and nd.strftime('%a, %d %b %Y') in h, 'card shows its next due date in full'
for u in ['/', '/dues', '/accounts', '/accounts?tab=loan', '/tools', '/recurring', '/alerts', '/people-loans']:
    assert c.get(u).status_code == 200, u
import notify as N  # noqa: E402
from datetime import datetime  # noqa: E402
ev = [{'date': date(2026, 11, 20), 'title': 'Test Card 9999', 'kind': 'card', 'amount': 1000.0, 'min': 100.0, 'status': 'due',
       'icon': 'bi-credit-card', 'account_id': None, 'inflow': False, 'cash': True}]
subj, html_, text_ = N.reminder_mail(date(2026, 11, 20), ev, True, datetime(2026, 11, 19, 9, 0))
assert 'Fri, 20 Nov 2026' in subj and 'Fri, 20 Nov 2026' in html_ and 'Fri, 20 Nov 2026' in text_, (subj, text_)
print('due dates OK')

# ── senders: exact addresses and domains ─────────────────────────────────────
assert M.sender_ok('statements@sbicard.com', ['statements@sbicard.com'])
assert not M.sender_ok('offers@sbicard.com', ['statements@sbicard.com']), 'an exact address does not open the whole domain'
assert M.sender_ok('alerts@mail.hdfcbank.net', ['hdfcbank.net']) and not M.sender_ok('x@fakehdfcbank.net', ['hdfcbank.net'])
assert not M.domain_on_list('sbicard.com', ['statements@sbicard.com'])
good, bad = M.sender_entries('Statements@SBICard.com, <estatement@hdfcbank.net>; @icicibank.com  not-valid  x@y')
assert good == ['statements@sbicard.com', 'estatement@hdfcbank.net', 'icicibank.com'] and bad == ['not-valid', 'x@y'], (good, bad)

GOOD = lambda d: f'mx.google.com; dkim=pass header.i=@{d} header.s=s1; spf=pass smtp.mailfrom={d}; dmarc=pass (p=REJECT) header.from={d}'


def mail(frm, subject, mid):
    m = EmailMessage()
    m['From'], m['Subject'], m['Message-ID'], m['Date'] = frm, subject, mid, 'Wed, 07 Oct 2026 10:00:00 +0530'
    m.set_content('Synthetic alert text.')
    d = frm.split('@')[1].rstrip('>')
    return f'Authentication-Results: {GOOD(d)}\r\n'.encode() + m.as_bytes()


BOX = {1: mail('SBI Card <statements@sbicard.com>', 'Statement mail', '<s1@x>'),
       2: mail('SBI Card <offers@sbicard.com>', 'Offer mail', '<s2@x>'),
       3: mail('HDFC <alerts@hdfcbank.net>', 'HDFC alert', '<s3@x>'),
       4: mail('Shop <deals@shop.example>', 'Shop deal', '<s4@x>')}
DL = []


class Fake:
    def __init__(self, host, port, user, secret): pass
    def select(self, f): return '777'
    def search_since(self, d): return sorted(BOX)
    def headers(self, uids): return {u: (BOX[u].split(b'\n\n')[0], len(BOX[u])) for u in uids}
    def message(self, uid): DL.append(uid); return BOX[uid]
    def label(self, uid, l): pass
    def close(self): pass


with A.app.test_request_context():
    con = A.get_db()
    M.ensure_schema(con)
    M.save_box(con, None, user='hub@gmail.com', password='abcdabcdabcdabcd', host='imap.gmail.com', port='993',
               provider='gmail', label='FinanceHub', name='Gmail')
    con.commit()
h = c.get('/mail').get_data(as_text=True)
assert 'Senders to read' in h and 'sbicard.com' in h and 'Built-in list' in h
# add an exact address; invalid input is reported
r = c.post('/mail/senders', data={'action': 'add', 'new': 'statements@sbicard.com, oops'}, follow_redirects=True)
assert 'Added statements@sbicard.com' in r.get_data(as_text=True) and 'Not valid: oops' in r.get_data(as_text=True)
# read only the exact addresses: every domain entry is paused
r = c.post('/mail/senders', data={'action': 'pause_domains'}, follow_redirects=True)
assert 'only the exact addresses' in r.get_data(as_text=True)
with A.app.test_request_context():
    con = A.get_db()
    s = M.shared(con)
    assert M._lines(s['senders']) == ['statements@sbicard.com'] and 'hdfcbank.net' in M._lines(s['senders_off'])
    res = M.check_mail(con, factory=Fake, force=True)
    st = {r_['subject']: r_['status'] for r_ in con.execute('SELECT subject, status FROM mail_items')}
    assert st['Statement mail'] == 'alert' and st['Offer mail'] == 'ignored' and st['HDFC alert'] == 'ignored', st
    assert DL == [1], 'only the listed address is downloaded'
h = c.get('/mail?tab=ignored').get_data(as_text=True)
assert 'offers@sbicard.com' in h and 'Read this address' in h and 'Whole domain' in h
# "Read this address" from Other senders → that address only, re-read on the next check
with A.app.test_request_context():
    iid = A.get_db().execute("SELECT id FROM mail_items WHERE subject='HDFC alert'").fetchone()[0]
r = c.post(f'/mail/{iid}', data={'action': 'allow_addr'}, follow_redirects=True)
assert 'alerts@hdfcbank.net added' in r.get_data(as_text=True)
with A.app.test_request_context():
    con = A.get_db()
    M.check_mail(con, factory=Fake, force=True)
    st = {r_['subject']: r_['status'] for r_ in con.execute('SELECT subject, status FROM mail_items')}
    assert st['HDFC alert'] == 'alert' and st['Offer mail'] == 'ignored' and sorted(DL) == [1, 3], (st, DL)
# one-row pause, resume (re-reads skipped mails), delete; bulk delete of paused; built-in list back
r = c.post('/mail/senders', data={'one': 'pause|statements@sbicard.com'}, follow_redirects=True)
assert 'Paused: statements@sbicard.com' in r.get_data(as_text=True)
r = c.post('/mail/senders', data={'action': 'resume', 'entry': ['sbicard.com']}, follow_redirects=True)
with A.app.test_request_context():
    con = A.get_db()
    assert 'sbicard.com' in M._lines(M.shared(con)['senders'])
    assert not con.execute("SELECT 1 FROM mail_items WHERE subject='Offer mail'").fetchone(), 'skipped mails of a resumed domain are read again'
    M.check_mail(con, factory=Fake, force=True)
    assert con.execute("SELECT status FROM mail_items WHERE subject='Offer mail'").fetchone()[0] == 'alert'
r = c.post('/mail/senders', data={'one': 'delete|alerts@hdfcbank.net'}, follow_redirects=True)
assert 'Deleted: alerts@hdfcbank.net' in r.get_data(as_text=True)
r = c.post('/mail/senders', data={'action': 'delete_paused'}, follow_redirects=True)
with A.app.test_request_context():
    s = M.shared(A.get_db())
    assert not M._lines(s['senders_off']) and 'hdfcbank.net' not in M._lines(s['senders'])
r = c.post('/mail/senders', data={'action': 'delete', 'entry': M._lines(s['senders'])}, follow_redirects=True)
assert 'No sender is being read now' in r.get_data(as_text=True)
r = c.post('/mail/senders', data={'action': 'defaults'}, follow_redirects=True)
with A.app.test_request_context():
    assert set(M._lines(M.DEFAULT_SENDERS)) <= set(M._lines(M.shared(A.get_db())['senders']))
for u in ['/mail', '/mail?tab=ignored', '/mail?tab=alerts', '/mail?tab=review']:
    assert c.get(u).status_code == 200, u
print('senders OK')
print('ALL 1.11 OK')
