"""1.8 — Outlook (Sign in with Microsoft, device code + XOAUTH2), several mailboxes, clearer Gmail errors.
SYNTHETIC data only; Microsoft's sign-in service and the mail servers are faked."""
import os
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('v18')
import app as A  # noqa: E402
import mailreader as M  # noqa: E402
import notify as N  # noqa: E402
import oauth_ms as O  # noqa: E402

CID = '11111111-2222-3333-4444-555555555555'

# ── oauth_ms against a fake Microsoft endpoint ───────────────────────────────
CALLS, STATE = [], {'polls': 0, 'rt': 0, 'personal_only': False, 'acct': 'hub@outlook.com'}
import base64, json  # noqa: E401,E402
IDT = lambda email: 'h.' + base64.urlsafe_b64encode(json.dumps({'email': email}).encode()).decode().rstrip('=') + '.s'


def fake_post(url, data, timeout=20):
    CALLS.append((url, dict(data)))
    tenant = url.split('/')[3]
    if STATE['personal_only'] and tenant != 'consumers':
        return 400, {'error': 'invalid_request', 'error_description': 'AADSTS9002331: Application is configured for use by Microsoft Account users only.'}
    assert data['client_id'] == CID
    if url.endswith('/devicecode'):
        assert 'IMAP.AccessAsUser.All' in data['scope'] and 'SMTP.Send' in data['scope'] and 'offline_access' in data['scope']
        return 200, {'device_code': 'DEV-1', 'user_code': 'ABCD-1234', 'verification_uri': 'https://microsoft.com/devicelogin',
                     'interval': 5, 'expires_in': 900}
    if data['grant_type'].endswith('device_code'):
        STATE['polls'] += 1
        if STATE['polls'] < 2:
            return 400, {'error': 'authorization_pending'}
        return 200, {'access_token': 'AT-0', 'refresh_token': 'RT-0', 'expires_in': 3600, 'id_token': IDT(STATE['acct'])}
    if data['grant_type'] == 'refresh_token':
        if data['refresh_token'] == 'RT-bad':
            return 400, {'error': 'invalid_grant', 'error_description': 'AADSTS70000: invalid_grant'}
        STATE['rt'] += 1
        return 200, {'access_token': f"AT-{STATE['rt']}", 'refresh_token': f"RT-{STATE['rt']}", 'expires_in': 3600}
    return 400, {'error': 'unsupported'}


O._post = fake_post
p = O.start(CID, 'common')
assert p['user_code'] == 'ABCD-1234' and p['tenant'] == 'common'
assert O.poll(CID, p)[0] == 'pending'
st, j = O.poll(CID, p)
assert st == 'ok' and j['refresh_token'] == 'RT-0' and j['account'] == 'hub@outlook.com'
tok, rt = O.access_token(CID, 'common', 'RT-0', 'hub@outlook.com')
assert tok == 'AT-0' and rt == 'RT-0', 'fresh access token from the sign-in is reused'
O.TOKENS.clear()
tok, rt = O.access_token(CID, 'common', 'RT-0', 'hub@outlook.com')
assert (tok, rt) == ('AT-1', 'RT-1'), 'rotated refresh token handed back to be saved'
assert O.access_token(CID, 'common', 'RT-0', 'hub@outlook.com') == ('AT-1', 'RT-1'), 'cached for the token presented'
assert O.access_token(CID, 'common', 'RT-1', 'hub@outlook.com') == ('AT-1', 'RT-1'), 'and for the new one'
try:
    O.access_token(CID, 'common', '', 'hub@outlook.com')
    raise SystemExit('expected AuthError: no token, no access — nothing is cached by address')
except O.AuthError:
    pass
O.DEVICE[('someone', 1)] = {'x': 1}; O.DEVICE[('other', 2)] = {'x': 1}
O.forget('someone')
assert not O.TOKENS and ('someone', 1) not in O.DEVICE and ('other', 2) in O.DEVICE
O.DEVICE.clear()
try:
    O.access_token(CID, 'common', 'RT-bad', 'x@outlook.com')
    raise SystemExit('expected AuthError')
except O.AuthError as e:
    assert 'Sign in with Microsoft' in str(e)
STATE['personal_only'] = True                      # app registered for personal accounts only → 'consumers' endpoint
p2 = O.start(CID, 'common')
assert p2['tenant'] == 'consumers' and '/consumers/' in CALLS[-1][0]
STATE['personal_only'] = False
assert 'public client' in O.friendly({'error_description': 'AADSTS70002: The client must be marked as public'})
assert 'personal Microsoft accounts' in O.friendly({'error_description': 'AADSTS50059: No tenant-identifying information found in either the request'})
assert O.xoauth2('a@b.c', 'T') == 'user=a@b.c\x01auth=Bearer T\x01\x01'
print('oauth_ms OK')

# ── friendly Gmail errors ────────────────────────────────────────────────────
gm = {'host': 'imap.gmail.com', 'user': 'x@gmail.com'}
assert 'app password' in M.explain(Exception("b'[ALERT] Application-specific password required: https://support.google.com (Failure)'"), gm)
print('explain OK')

# ── app: migration of the 1.7 single mailbox, then several mailboxes ────────
A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})
with A.app.test_request_context():
    con = A.get_db()
    con.executescript(M.SCHEMA)
    for k, v in {'user': 'hub@gmail.com', 'password': 'abcdabcdabcdabcd', 'host': 'imap.gmail.com', 'port': '993',
                 'label': 'FinanceHub', 'last_uid': '7', 'uidvalidity': '777'}.items():     # as 1.7 stored it
        con.execute('INSERT OR REPLACE INTO mail_settings (key, value) VALUES (?,?)', (k, v))
    con.execute("INSERT INTO mail_items (message_id, subject, status, kind, auth, from_domain) VALUES ('<old@x>','old mail','imported','statement','pass','sbi.co.in')")
    con.commit()
    bs = M.boxes(con)
    assert len(bs) == 1 and bs[0]['user'] == 'hub@gmail.com' and bs[0]['password'] == 'abcdabcdabcdabcd' and bs[0]['send_from'] == 1
    assert bs[0]['last_uid'] == '7' and bs[0]['provider'] == 'gmail'
    left = dict(con.execute('SELECT key, value FROM mail_settings').fetchall())
    assert 'password' not in left and 'user' not in left, 'no second copy of the password after migration'
    assert M.settings(con)['user'] == 'hub@gmail.com' and M.configured(M.settings(con))
    M.ensure_schema(con)
    assert 'password' not in dict(con.execute('SELECT key, value FROM mail_settings').fetchall())
G = bs[0]['id']
h = c.get('/mail').get_data(as_text=True)
assert 'hub@gmail.com' in h and 'abcdabcd' not in h and 'Add a mailbox' in h
print('migration OK')

# add an Outlook mailbox
r = c.post('/mail/box/save', data={'box_form': '1', 'provider': 'outlook', 'user': 'hub@outlook.com', 'name': 'Outlook',
                                   'ms_client_id': CID, 'ms_tenant': 'common', 'active': 'on', 'host': '', 'port': '', 'folder': 'INBOX', 'label': ''})
assert r.status_code == 302 and 'box=' in r.headers['Location']
with A.app.test_request_context():
    con = A.get_db()
    ob = [b for b in M.boxes(con) if b['user'] == 'hub@outlook.com'][0]
    OB = ob['id']
    assert ob['host'] == 'outlook.office365.com' and ob['provider'] == 'outlook' and not ob['send_from'] and not ob['password']
    assert not M.configured(M.settings(con, OB)), 'needs the Microsoft sign-in first'
h = c.get(f'/mail?box={OB}').get_data(as_text=True)
assert 'Sign in with Microsoft' in h and CID in h and 'sends reminders' in h
STATE['polls'] = 0
d = c.post(f'/mail/box/{OB}/ms/start', json={}).get_json()
assert d['ok'] and d['user_code'] == 'ABCD-1234'
assert c.post(f'/mail/box/{OB}/ms/poll', json={}).get_json()['state'] == 'pending'
assert c.post(f'/mail/box/{OB}/ms/poll', json={}).get_json()['state'] == 'ok'
assert c.post(f'/mail/box/{OB}/ms/poll', json={}).get_json()['state'] == 'error', 'no sign-in in progress any more'
with A.app.test_request_context():
    con = A.get_db()
    so = M.settings(con, OB)
    assert so['oauth_refresh'] == 'RT-0' and M.configured(so)
h = c.get('/mail').get_data(as_text=True)
assert 'RT-0' not in h and 'Signed in with Microsoft' in h and 'You signed in to Microsoft as' not in h
STATE['polls'], STATE['acct'] = 1, 'someone.else@outlook.com'
assert c.post(f'/mail/box/{OB}/ms/start', json={}).get_json()['ok']
assert c.post(f'/mail/box/{OB}/ms/poll', json={}).get_json()['state'] == 'ok'
assert 'You signed in to Microsoft as someone.else@outlook.com' in c.get('/mail').get_data(as_text=True)
STATE['acct'] = 'hub@outlook.com'
print('outlook sign-in OK')


# ── reading both mailboxes ───────────────────────────────────────────────────
def mail(frm, subject, mid, att=None, outlook=False):
    m = EmailMessage()
    m['From'], m['Subject'], m['Message-ID'], m['Date'] = frm, subject, mid, 'Wed, 07 Oct 2026 10:00:00 +0530'
    d = frm.split('@')[1].rstrip('>')
    m['Authentication-Results'] = (f'spf=pass (sender IP is 192.0.2.1) smtp.mailfrom={d}; dkim=pass (signature was verified) '
                                   f'header.d={d};dmarc=pass action=none header.from={d};compauth=pass reason=100' if outlook else
                                   f'mx.google.com; dkim=pass header.i=@{d} header.s=s1; spf=pass smtp.mailfrom={d}; dmarc=pass (p=REJECT) header.from={d}')
    m.set_content('Synthetic.')
    if att:
        m.add_attachment(b'garbage', maintype='text', subtype='csv', filename=att)
    return m.as_bytes()


BOXES = {'hub@gmail.com': {8: mail('Bank <e@sbi.co.in>', 'G only', '<g8@x>'),
                           9: mail('Bank <e@sbi.co.in>', 'Both boxes', '<both@x>')},
         'hub@outlook.com': {3: mail('Bank <e@sbi.co.in>', 'Both boxes', '<both@x>', outlook=True),
                             4: mail('Bank <e@sbi.co.in>', 'O only', '<o4@x>', outlook=True)}}
SEEN, LABELS = [], []


class Fake:
    def __init__(self, host, port, user, secret):
        SEEN.append((host, user, secret))
        if user == 'hub@gmail.com':
            assert secret == 'abcdabcdabcdabcd'
        else:
            assert host == 'outlook.office365.com' and secret.startswith('AT-'), 'Outlook gets an access token, not a password'
        self.box, self.user = BOXES[user], user

    def select(self, f): return '777'
    def search_since(self, d): return sorted(self.box)
    def headers(self, uids): return {u: (self.box[u].split(b'\n\n')[0], len(self.box[u])) for u in uids if u in self.box}
    def message(self, uid): return self.box[uid]
    def label(self, uid, l): LABELS.append((self.user, l))
    def close(self): pass


O.TOKENS.clear()
with A.app.test_request_context():
    con = A.get_db()
    r = M.check_mail(con, factory=Fake, force=True)
    print('check', r['msg'])
    assert r['ok'] and r['checked'] == 3, r
    rows = {x['message_id']: dict(x) for x in con.execute('SELECT * FROM mail_items')}
    assert rows['<g8@x>']['mailbox_id'] == G and rows['<o4@x>']['mailbox_id'] == OB
    assert rows['<o4@x>']['auth'] == 'pass' and rows['<g8@x>']['auth'] == 'pass', 'Gmail and Outlook sender checks both understood'
    assert con.execute("SELECT COUNT(*) FROM mail_items WHERE message_id='<both@x>'").fetchone()[0] == 1, 'a mail in two mailboxes is read once'
    assert rows['<old@x>']['mailbox_id'] == G, 'mails read before 1.8 belong to the first mailbox'
    assert {u for _h, u, _s in SEEN} == {'hub@gmail.com', 'hub@outlook.com'}
    assert M.settings(con, OB)['oauth_refresh'] == f"RT-{STATE['rt']}" != 'RT-0', 'rotated refresh token saved'
    assert M.settings(con, OB)['last_uid'] == '4' and M.settings(con, G)['last_uid'] == '9'
    assert 'hub@outlook.com' not in M.shared(con).get('user', '')
    assert ('hub@gmail.com', 'FinanceHub') in LABELS and not [x for x in LABELS if x[0] == 'hub@outlook.com' and x[1]], \
        'Outlook mails are left as they are (no folder copies)'
h = c.get('/mail?tab=alerts').get_data(as_text=True)
assert 'G only' in h and 'O only' in h and '<i class="bi bi-inbox"></i> Outlook' in h, 'items show which mailbox they came from'
# pause one mailbox
c.post(f'/mail/box/{G}', data={'action': 'toggle'})
SEEN.clear()
with A.app.test_request_context():
    M.check_mail(A.get_db(), factory=Fake, force=True)
assert {u for _h, u, _s in SEEN} == {'hub@outlook.com'}, SEEN
c.post(f'/mail/box/{G}', data={'action': 'toggle'})
print('several mailboxes OK')

# ── reminders sent from the chosen mailbox (Outlook → XOAUTH2 on 587) ────────
sent = []


class FakeSMTP:
    def __init__(self, smtp): self.smtp, self.authed = smtp, None
    def login(self, u, p): assert p == 'abcdabcdabcdabcd'; self.authed = 'password'
    def ehlo(self): pass
    def auth(self, mech, obj):
        assert mech == 'XOAUTH2' and obj().startswith('user=hub@outlook.com\x01auth=Bearer AT-'); self.authed = 'oauth'
    def send_message(self, m): sent.append((self.smtp['host'], self.smtp['port'], self.authed, m['From']))
    def quit(self): pass


with A.app.test_request_context():
    con = A.get_db()
    smtp = N.smtp_for(M.settings(con), N.settings(con))
    assert smtp['host'] == 'smtp.gmail.com' and N.smtp_ready(smtp)
    N.send_mail(smtp, ['me@example.com'], 'Test', None, 'Synthetic', FakeSMTP)
c.post(f'/mail/box/{OB}', data={'action': 'send_from'})
with A.app.test_request_context():
    con = A.get_db()
    assert M.settings(con)['user'] == 'hub@outlook.com'
    smtp = N.smtp_for(M.settings(con), N.settings(con))
    assert (smtp['host'], smtp['port']) == ('smtp-mail.outlook.com', 587) and smtp['oauth']['refresh'] and N.smtp_ready(smtp)
    N.send_mail(smtp, ['me@example.com'], 'Test', None, 'Synthetic', FakeSMTP)
assert sent[0][2] == 'password' and sent[1][:3] == ('smtp-mail.outlook.com', 587, 'oauth') and 'hub@outlook.com' in sent[1][3]
print('send-from OK')

# ── sign out, edit, remove ───────────────────────────────────────────────────
c.post(f'/mail/box/{OB}', data={'action': 'signout'})
with A.app.test_request_context():
    con = A.get_db()
    assert not M.settings(con, OB)['oauth_refresh']
c.post('/mail/box/save', data={'box_form': '1', 'box_id': str(G), 'provider': 'gmail', 'user': 'hub@gmail.com', 'name': 'Personal',
                               'password': '', 'host': 'imap.gmail.com', 'port': '993', 'folder': 'INBOX', 'label': 'FinanceHub', 'active': 'on'})
with A.app.test_request_context():
    sg = M.settings(A.get_db(), G)
    assert sg['name'] == 'Personal' and sg['password'] == 'abcdabcdabcdabcd', 'empty password field keeps the saved one'
c.post(f'/mail/box/{OB}', data={'action': 'remove'})
with A.app.test_request_context():
    con = A.get_db()
    bs = M.boxes(con)
    assert [b['id'] for b in bs] == [G] and bs[0]['send_from'] == 1, 'the remaining mailbox sends reminders'
    assert con.execute("SELECT COUNT(*) FROM mail_items WHERE message_id='<o4@x>'").fetchone()[0] == 1, 'mails already read stay'
for u in ['/mail', f'/mail?box={G}', '/mail?box=new&kind=outlook', '/mail?box=new&kind=other', '/support', '/reminders']:
    assert c.get(u).status_code == 200, u
assert 'Application (client) ID' in c.get('/mail?box=new&kind=outlook').get_data(as_text=True)
# custom port kept; provider switch away from Outlook forgets the sign-in; 'other' needs a server
c.post('/mail/box/save', data={'box_form': '1', 'provider': 'other', 'user': 'me@example.net', 'password': 'pw', 'host': 'mail.example.net',
                               'port': '1993', 'folder': 'INBOX', 'label': '', 'active': 'on'})
c.post('/mail/box/save', data={'box_form': '1', 'provider': 'outlook', 'user': 'x@outlook.com', 'ms_client_id': CID, 'active': 'on'})
with A.app.test_request_context():
    con = A.get_db()
    by = {b['user']: b for b in M.boxes(con)}
    assert by['me@example.net']['port'] == '1993' and by['me@example.net']['host'] == 'mail.example.net'
    assert not M.configured(dict(M.settings(con, by['me@example.net']['id']), host='')), "'other' without a server is not ready"
    xid = by['x@outlook.com']['id']
    M._set_box(con, xid, oauth_refresh='RT-x'); con.commit()
c.post('/mail/box/save', data={'box_form': '1', 'box_id': str(xid), 'provider': 'gmail', 'user': 'x@outlook.com', 'password': 'apppw',
                               'host': 'imap.gmail.com', 'port': '993', 'folder': 'INBOX', 'label': 'FinanceHub', 'active': 'on'})
with A.app.test_request_context():
    sx = M.settings(A.get_db(), xid)
    assert sx['provider'] == 'gmail' and not sx['oauth_refresh'], 'switching away from Outlook forgets the Microsoft sign-in'

# setup wizard: unknown domains default to Gmail / Google Workspace; Outlook addresses keep no password
import welcome  # noqa: E402,F401
A.app.config['FH_WIZARD'] = True
for user, prov, pw in (('hub@family.in', 'gmail', 'abcdabcdabcdabcd'), ('me@hotmail.com', 'outlook', '')):
    with A.app.test_request_context():
        con = A.get_db()
        for b in M.boxes(con):
            con.execute('DELETE FROM mailboxes WHERE id=?', (b['id'],))
        con.commit()
    c.post('/welcome/mail', data={'user': user, 'password': 'abcd abcd abcd abcd', 'auto': 'on', 'recipients': ''})
    with A.app.test_request_context():
        b = M.settings(A.get_db())
        assert b['user'] == user and b['provider'] == prov and b['password'] == pw and b['host'], (user, b['provider'], b['host'])
print('review fixes OK')
print('ALL 1.8 OK')
