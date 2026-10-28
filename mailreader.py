"""Finance Hub 1.5 — the Hub's own mailbox.

A mailbox only for the Hub (for example a new Gmail address) receives statement mails — forwarded by a filter from your
own mail, or sent there directly. While the Hub is unlocked it reads that mailbox over IMAP (SSL) and:

  * keeps only mails from senders on your list (bank / card / broker / depository domains) and from your own forwarding
    addresses; others are listed as "ignored" without being downloaded;
  * accepts a sender only when the mail server's own check passed (DMARC, or DKIM signed by the sender's domain) —
    look-alike mails are "rejected" and never opened;
  * reads PDF / CSV / XLSX attachments with the same readers as the Import pages, using your saved statement passwords;
  * imports automatically only what passes every check (balances reconcile, account already known, not a duplicate,
    contract-note totals reconcile, broker known); everything else waits on the Mail inbox page for you;
  * keeps mails without attachments (instant alerts) for a later version that reads them.

Mails are read with BODY.PEEK (they stay unread) and get the label "FinanceHub" once handled. The mailbox password is kept
inside your encrypted database; attachments waiting for review are stored encrypted with your key and erased once handled.
Nothing is ever clicked, and links in mails are never opened.
"""
import email
import email.policy
import email.utils
import hashlib
import imaplib
import json
import re
from collections import defaultdict
import ssl
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, jsonify

SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS mail_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT, uid TEXT, received TEXT, from_addr TEXT, from_domain TEXT, via TEXT,
    subject TEXT, auth TEXT, auth_note TEXT,
    status TEXT,          -- imported / review / duplicate / ignored / rejected / alert / skipped / error / done
    kind TEXT,            -- statement / contract_note / depository / alert / other
    attachment TEXT, size INTEGER, file_hash TEXT, note TEXT, blob TEXT, result TEXT,
    created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_mail_msg ON mail_items(message_id);
CREATE INDEX IF NOT EXISTS idx_mail_hash ON mail_items(file_hash);
CREATE TABLE IF NOT EXISTS mailboxes (            -- 1.8: the Hub can read several mailboxes (Gmail, Outlook, others)
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, provider TEXT, user TEXT, password TEXT, host TEXT, port TEXT,
    folder TEXT DEFAULT 'INBOX', label TEXT, ms_client_id TEXT, ms_tenant TEXT DEFAULT 'common', oauth_refresh TEXT,
    active INTEGER DEFAULT 1, send_from INTEGER DEFAULT 0, uidvalidity TEXT, last_uid TEXT DEFAULT '0', last_check TEXT,
    last_result TEXT, created_at TEXT DEFAULT (datetime('now')));
"""
_MOVED = ('user', 'password', 'host', 'port', 'folder', 'label', 'ms_client_id', 'ms_tenant', 'oauth_refresh', 'uidvalidity',
          'last_uid', 'provider')
BOX_KEYS = ('name', 'provider', 'user', 'password', 'host', 'port', 'folder', 'label', 'ms_client_id', 'ms_tenant', 'oauth_refresh',
            'active', 'send_from', 'uidvalidity', 'last_uid', 'last_check', 'last_result')

# Generic, public sender domains of Indian banks, card issuers, brokers, depositories and registrars (edit on the page).
# 'bank.in' is the domain reserved for regulated Indian banks.
DEFAULT_SENDERS = """bank.in
sbi.co.in
sbicard.com
hdfcbank.net
hdfcbank.com
icicibank.com
axisbank.com
kotak.com
zerodha.com
zerodha.net
upstox.com
rksv.in
sbisecurities.in
sbicapsec.com
nsdl.co.in
nsdl.com
cdslindia.com
cdslstatement.com
camsonline.com
kfintech.com"""

DEFAULTS = {'host': 'imap.gmail.com', 'port': '993', 'user': '', 'password': '', 'folder': 'INBOX', 'label': 'FinanceHub',
            'interval': '15', 'enabled': '0', 'auto_import': '1', 'since_days': '60', 'senders': DEFAULT_SENDERS,
            'forwarders': '', 'senders_off': '', 'last_check': '', 'last_result': '', 'uidvalidity': '', 'last_uid': '0',
            'provider': '', 'ms_client_id': '', 'ms_tenant': 'common', 'oauth_refresh': ''}     # 1.8: Outlook (Microsoft sign-in)
PROVIDERS = {'gmail': ('Gmail', 'imap.gmail.com', '993', 'FinanceHub'),
             'outlook': ('Outlook.com / Hotmail / Microsoft 365', 'outlook.office365.com', '993', ''),
             'other': ('Another mailbox (IMAP with a password)', '', '993', '')}


def provider(s):
    p = s.get('provider') or ''
    if p in PROVIDERS:
        return p
    h = (s.get('host') or '').lower()
    return 'gmail' if 'gmail' in h or 'google' in h else ('outlook' if 'outlook' in h or 'office365' in h or 'hotmail' in h else 'other')


def configured(s):
    """The mailbox can be used: an address and a password, or (Outlook) a Microsoft sign-in."""
    if not s.get('user'):
        return False
    if provider(s) == 'outlook':
        return bool(s.get('ms_client_id') and s.get('oauth_refresh'))
    return bool(s.get('password') and s.get('host'))


def explain(e, s):
    """A plain-language reason for a failed mailbox connection."""
    msg = str(e)
    low = msg.lower()
    if 'application-specific password' in low or ('gmail' in (s.get('host') or '') and 'web login required' in low):
        return ('Gmail needs an app password, not your normal Gmail password: turn on 2-Step Verification for that Google '
                'account, create an app password at myaccount.google.com/apppasswords and paste it here.')
    if provider(s) == 'outlook' and ('authenticate failed' in low or 'not signed in' in low or 'expired' in low):
        return 'the Microsoft sign-in is missing or has expired — click “Sign in with Microsoft” again.'
    if 'authenticationfailed' in low or 'invalid credentials' in low or 'authentication failed' in low:
        return ('the mailbox refused the address / password' + (' (Gmail needs an app password)' if provider(s) == 'gmail' else '') + '.')
    if 'not enabled for imap' in low or 'imap access is disabled' in low:
        return 'IMAP is turned off for this mailbox — in Gmail: Settings › Forwarding and POP/IMAP › Enable IMAP › Save.'
    if 'logindisabled' in low or 'basicauthblocked' in low or 'basic auth' in low:
        return 'this mailbox does not accept passwords — for Outlook.com choose “Outlook.com” and sign in with Microsoft.'
    return msg
EXTS = ('.pdf', '.csv', '.xlsx', '.xls')
MAX_FILE = 20 * 1024 * 1024
MAX_PER_RUN = 30
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
TWO_LEVEL = {'co.in', 'bank.in', 'net.in', 'org.in', 'gov.in', 'ac.in', 'firm.in', 'gen.in', 'ind.in', 'co.uk', 'org.uk',
             'com.au', 'com.sg'}
STATUS = {'imported': ('Imported', 'green'), 'review': ('Waiting for you', 'amber'), 'duplicate': ('Already in the Hub', 'slate'),
          'ignored': ('Sender not on the list', 'slate'), 'rejected': ('Failed sender check', 'red'),
          'alert': ('Alert — kept for later', 'blue'), 'skipped': ('Not a statement', 'slate'), 'error': ('Could not read', 'red'),
          'done': ('Handled', 'slate')}

UPLOAD_DIR = None
VAULT = None


def ensure_schema(con):
    con.executescript(SCHEMA)
    if 'mailbox_id' not in {r[1] for r in con.execute('PRAGMA table_info(mail_items)')}:
        con.execute('ALTER TABLE mail_items ADD COLUMN mailbox_id INTEGER')
    for k, v in DEFAULTS.items():
        if k not in _MOVED:                     # mailbox fields live in the mailboxes table since 1.8
            con.execute('INSERT OR IGNORE INTO mail_settings (key, value) VALUES (?,?)', (k, v))
    con.commit()


def shared(con):
    """Settings that apply to every mailbox (senders, forwarders, how often, …)."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in con.execute('SELECT key, value FROM mail_settings')})
    return s


def boxes(con, active_only=False):
    """All mailboxes. The single mailbox of 1.5 – 1.7 (kept in mail_settings) becomes the first one."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='mailboxes'").fetchone():
        ensure_schema(con)
    rows = [dict(r) for r in con.execute('SELECT * FROM mailboxes ORDER BY send_from DESC, id')]
    if not rows:
        old = shared(con)
        if old.get('user') and old.get('migrated') != '1':
            prov = provider(old)
            con.execute('INSERT INTO mailboxes (name, provider, user, password, host, port, folder, label, ms_client_id, ms_tenant, '
                        'oauth_refresh, active, send_from, uidvalidity, last_uid, last_check, last_result) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)',
                        (PROVIDERS[prov][0].split(' /')[0], prov, old['user'], old.get('password', ''), old.get('host') or PROVIDERS[prov][1],
                         old.get('port') or '993', old.get('folder') or 'INBOX', old.get('label', ''), old.get('ms_client_id', ''),
                         old.get('ms_tenant') or 'common', old.get('oauth_refresh', ''), old.get('uidvalidity', ''),
                         old.get('last_uid') or '0', old.get('last_check', ''), old.get('last_result', '')))
            con.execute("INSERT OR REPLACE INTO mail_settings (key, value) VALUES ('migrated', '1')")
            con.execute('UPDATE mail_items SET mailbox_id=(SELECT MIN(id) FROM mailboxes) WHERE mailbox_id IS NULL')
            con.execute(f"DELETE FROM mail_settings WHERE key IN ({','.join('?' * len(_MOVED))})", _MOVED)   # no second copy of the password
            con.commit()
            rows = [dict(r) for r in con.execute('SELECT * FROM mailboxes ORDER BY send_from DESC, id')]
    return [r for r in rows if r.get('active')] if active_only else rows


def settings(con, mid=None):
    """Shared settings + one mailbox (by id; default: the one reminders are sent from, else the first)."""
    s = shared(con)
    bs = boxes(con)
    b = next((x for x in bs if x['id'] == mid), None) if mid else (next((x for x in bs if x.get('send_from')), None) or (bs[0] if bs else None))
    for k in BOX_KEYS:
        s[k] = '' if k not in ('active', 'send_from', 'last_uid') else s.get(k, 0)
    s['id'] = None
    if b:
        s.update({k: ('' if v is None else v) for k, v in b.items()})
        s['port'] = str(s['port'] or '993')
        s['last_uid'] = str(s['last_uid'] or '0')
    return s


def _set(con, **kw):
    """Shared settings only (mailbox fields go through _set_box)."""
    for k, v in kw.items():
        con.execute('INSERT OR REPLACE INTO mail_settings (key, value) VALUES (?,?)', (k, str(v)))


def _set_box(con, mid, **kw):
    kw = {k: v for k, v in kw.items() if k in BOX_KEYS}
    if mid and kw:
        con.execute(f"UPDATE mailboxes SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*[str(v) if v is not None else '' for v in kw.values()], mid))


def save_box(con, mid=None, **kw):
    """Create (mid None) or change a mailbox. → id"""
    if not mid:
        mid = con.execute("INSERT INTO mailboxes (name, provider, folder, ms_tenant, active, send_from, last_uid) VALUES ('', 'gmail', 'INBOX', 'common', 1, ?, '0')",
                          (0 if con.execute('SELECT 1 FROM mailboxes').fetchone() else 1,)).lastrowid
    _set_box(con, mid, **kw)
    return mid


def save_box_form(con, mid, f):
    """Add (mid None) or change a mailbox from the page's form fields (also used by the setup wizard). → id"""
    old = settings(con, mid) if mid else {'provider': '', 'user': '', 'ms_client_id': '', 'host': '', 'port': '993', 'label': '',
                                          'folder': 'INBOX', 'ms_tenant': 'common', 'name': ''}
    prov = f.get('provider') if f.get('provider') in PROVIDERS else (provider(old) if mid else 'gmail')
    kw = {k: f.get(k, old.get(k) or '').strip()[:200] for k in ('name', 'user', 'host', 'port', 'folder', 'label', 'ms_client_id', 'ms_tenant')}
    kw['provider'] = prov
    if not mid or prov != provider(old):                # a new mailbox, or a new type: fill in its server
        _n, host, port, label = PROVIDERS[prov]
        kw.update(host=f.get('host', '').strip() or host or kw['host'], port=f.get('port', '').strip() or port,
                  label=label if 'label' not in f else kw['label'])
        if prov == 'outlook':
            kw['password'] = ''
    if prov == 'outlook':
        import oauth_ms
        kw['host'], kw['port'] = kw['host'] or oauth_ms.IMAP_HOST, kw['port'] or str(oauth_ms.IMAP_PORT)
        if mid and (kw['ms_client_id'] != (old.get('ms_client_id') or '') or kw['user'].lower() != (old.get('user') or '').lower()):
            kw['oauth_refresh'] = ''                    # a different app or mailbox needs a new sign-in
    elif mid and old.get('oauth_refresh'):
        kw['oauth_refresh'] = ''                        # no longer an Outlook mailbox: forget the Microsoft sign-in
    kw['ms_tenant'] = kw.get('ms_tenant') if kw.get('ms_tenant') in ('common', 'consumers', 'organizations') else 'common'
    kw['label'] = re.sub(r'[^A-Za-z0-9 _/-]', '', kw.get('label', ''))
    kw['folder'] = kw.get('folder') or 'INBOX'
    kw['name'] = kw.get('name') or (kw['user'].split('@')[-1] if kw.get('user') else PROVIDERS[prov][0].split(' /')[0])
    if 'active' in f or 'box_form' in f:
        kw['active'] = '1' if f.get('active') else '0'
    if f.get('password', '').strip() and prov != 'outlook':
        kw['password'] = f['password'].strip().replace(' ', '')     # Gmail shows app passwords in groups of four
    if mid and (kw.get('user', '').lower() != (old.get('user') or '').lower() or kw.get('folder') != old.get('folder') or kw.get('host') != old.get('host')):
        kw.update(last_uid='0', uidvalidity='')
    return save_box(con, mid, **kw)


def _lines(text):
    return [x.strip().lower() for x in re.split(r'[\s,;]+', text or '') if x.strip()]


# ── sender checks ───────────────────────────────────────────────────────────
def org_domain(d):
    parts = (d or '').lower().strip('.').split('.')
    n = 3 if len(parts) >= 3 and '.'.join(parts[-2:]) in TWO_LEVEL else 2
    return '.'.join(parts[-n:])


def domain_on_list(domain, allowed):
    domain = (domain or '').lower()
    return any(domain == a or domain.endswith('.' + a) for a in allowed if '@' not in a)


ADDR_RE = re.compile(r'^[a-z0-9._%+\-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$')
DOMAIN_RE = re.compile(r'^(?=.{3,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$')


def sender_ok(addr, allowed):
    """1.11: an entry with '@' is one exact sender address; an entry without is a domain (and its sub-domains)."""
    addr = (addr or '').lower().strip()
    if '@' in addr and addr in allowed:
        return True
    return domain_on_list(addr.rsplit('@', 1)[-1], allowed)


def sender_entries(text):
    """Valid, de-duplicated entries (addresses or domains) from typed text. → (entries, rejected)"""
    good, bad = [], []
    for x in _lines(text):
        x = x.strip('<>"\'').lstrip('@').rstrip('.')
        (good if ADDR_RE.match(x) or DOMAIN_RE.match(x) else bad).append(x)
    return list(dict.fromkeys(good)), bad


def auth_check(msg, from_domain, trusted_servers=None):
    """Use the receiving server's own verdict (the TOPMOST Authentication-Results header — the one it added itself).
    → ('pass' | 'fail' | 'none', note)"""
    hdrs = [str(h) for h in (msg.get_all('Authentication-Results') or [])]
    if not hdrs:
        return 'none', 'the mail server added no sender check'
    top = hdrs[0]
    serv = top.split(';', 1)[0].strip().lower()
    if trusted_servers and serv not in trusted_servers:
        return 'fail', f'sender check not added by your mail server ({serv[:40]})'
    t = top.lower()
    m = re.search(r'\bdmarc=(\w+)', t)
    if m and m.group(1) == 'pass':
        hf = re.search(r'dmarc=pass[^;]*header\.from=([\w.-]+)', t)
        if not hf or org_domain(hf.group(1)) == org_domain(from_domain):
            return 'pass', 'DMARC passed'
    for m in re.finditer(r'\bdkim=(\w+)([^;]*)', t):
        if m.group(1) != 'pass':
            continue
        d = re.search(r'header\.(?:i|d)=@?([\w.-]+)', m.group(2))
        if d and org_domain(d.group(1)) == org_domain(from_domain):
            return 'pass', f'DKIM signed by {d.group(1)}'
    v = ', '.join(f'{k}={x}' for k, x in re.findall(r'\b(dkim|spf|dmarc)=(\w+)', t)[:3])
    return 'fail', f'not signed by {from_domain}' + (f' ({v})' if v else '')


def trusted_servers_for(host):
    return {'mx.google.com'} if 'gmail' in (host or '').lower() or 'google' in (host or '').lower() else None


def forwarded_from(text):
    """Original sender inside a mail you forwarded by hand ('From: Bank <alerts@bank.com>')."""
    for m in re.finditer(r'^\s*>?\s*From:\s*(.+)$', text or '', re.I | re.M):
        addr = email.utils.parseaddr(m.group(1))[1]
        if '@' in addr:
            return addr.lower()
    return ''


# ── IMAP ────────────────────────────────────────────────────────────────────
class Imap:
    """Thin, read-mostly IMAP client (SSL only)."""

    def __init__(self, host, port, user, password, timeout=30, oauth_token=None):
        self.m = imaplib.IMAP4_SSL(host, int(port or 993), ssl_context=ssl.create_default_context(), timeout=timeout)
        if oauth_token:                                  # 1.8: Outlook — SASL XOAUTH2 with a Microsoft access token
            import oauth_ms
            self.m.authenticate('XOAUTH2', lambda _challenge: oauth_ms.xoauth2(user, oauth_token).encode())
        else:
            self.m.login(user, password)
        self.caps = {c.upper() for c in self.m.capabilities}

    @staticmethod
    def _q(name):
        return '"' + name.replace('\\', '\\\\').replace('"', '\\"') + '"'

    def select(self, folder):
        typ, _ = self.m.select(self._q(folder))
        if typ != 'OK':
            raise RuntimeError(f'folder "{folder}" not found')
        uv = self.m.response('UIDVALIDITY')[1]
        return (uv[0].decode() if uv and uv[0] else '')

    def search_since(self, d):
        typ, data = self.m.uid('SEARCH', 'SINCE', f'{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}')
        if typ != 'OK':
            raise RuntimeError('search failed')
        return [int(x) for x in (data[0] or b'').split()]

    def headers(self, uids):
        if not uids:
            return {}
        typ, data = self.m.uid('FETCH', ','.join(map(str, uids)),
                               '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] RFC822.SIZE)')
        out = {}
        data = list(data or [])
        for i, part in enumerate(data):
            if isinstance(part, tuple):
                after = data[i + 1] if i + 1 < len(data) and isinstance(data[i + 1], bytes) else b''
                meta = part[0] + b' ' + after                   # UID / size may come before or after the literal
                m = re.search(rb'UID (\d+)', meta)
                sz = re.search(rb'RFC822\.SIZE (\d+)', meta)
                if m:
                    out[int(m.group(1))] = (part[1], int(sz.group(1)) if sz else 0)
        return out

    def message(self, uid):
        typ, data = self.m.uid('FETCH', str(uid), '(BODY.PEEK[])')
        for part in data or []:
            if isinstance(part, tuple):
                return part[1]
        raise RuntimeError('message not found')

    def label(self, uid, label):
        if not label:
            return                                       # no label chosen (e.g. Outlook): mails are left exactly as they are
        try:
            if 'X-GM-EXT-1' in self.caps:
                self.m.uid('STORE', str(uid), '+X-GM-LABELS', f'({self._q(label)})')
            else:
                self.m.create(self._q(label))
                self.m.uid('COPY', str(uid), self._q(label))
        except Exception:  # noqa: BLE001  (labelling is a convenience only)
            pass

    def close(self):
        try:
            self.m.logout()
        except Exception:  # noqa: BLE001
            pass


def connect(s, factory=None, con=None):
    if provider(s) == 'outlook':
        import oauth_ms
        token, newest = oauth_ms.access_token(s['ms_client_id'], s.get('ms_tenant') or 'common', s.get('oauth_refresh'), s['user'])
        if con is not None and newest and newest != s.get('oauth_refresh') and s.get('id'):
            _set_box(con, s['id'], oauth_refresh=newest)     # Microsoft hands out a new refresh token now and then
            con.commit()
        host, port = s.get('host') or oauth_ms.IMAP_HOST, s.get('port') or oauth_ms.IMAP_PORT
        if factory:
            return factory(host, port, s['user'], token)
        return Imap(host, port, s['user'], None, oauth_token=token)
    return (factory or Imap)(s['host'], s['port'], s['user'], s['password'])


# ── reading one mail ────────────────────────────────────────────────────────
def attachments(msg):
    """(filename, bytes) of PDF / CSV / XLSX parts, including those inside forwarded mails."""
    out = []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        fn = part.get_filename() or ''
        if not fn.lower().endswith(EXTS):
            continue
        data = part.get_payload(decode=True) or b''
        if data:
            out.append((fn, data))
    return out


def body_text(msg, limit=20000):
    try:
        b = msg.get_body(preferencelist=('plain', 'html'))
        t = b.get_content() if b else ''
        html = bool(b) and b.get_content_subtype() == 'html'
    except Exception:  # noqa: BLE001
        t, html = '', False
    if html:
        t = re.sub(r'(?is)<(script|style).*?</\1>', ' ', t)
        t = re.sub(r'<br\s*/?>|</p>|</tr>|</div>', '\n', t, flags=re.I)
        t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'&nbsp;', ' ', t)
    t = re.sub(r'[ \t]+', ' ', t)
    return t.strip()[:limit]


def _saved_passwords(con):
    try:
        return [r[0] for r in con.execute("SELECT password FROM passwords WHERE COALESCE(password,'')<>''")]
    except Exception:  # noqa: BLE001
        return []


def _seal(blob_name, data):
    (VAULT.files_dir / blob_name).write_bytes(VAULT.seal_bytes(data))


def _unseal(blob_name):
    return VAULT.unseal_bytes((VAULT.files_dir / blob_name).read_bytes())


def _erase_blob(con, item_id):
    import vault as VT
    r = con.execute('SELECT blob FROM mail_items WHERE id=?', (item_id,)).fetchone()
    if r and r[0]:
        p = VAULT.files_dir / r[0]
        if p.exists():
            VT.secure_delete(p)
        con.execute('UPDATE mail_items SET blob=NULL WHERE id=?', (item_id,))


def _tmp_path(fname):
    from werkzeug.utils import secure_filename
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return Path(UPLOAD_DIR) / f'{uuid.uuid4().hex[:12]}_{secure_filename(fname) or "file"}'


def process_file(con, data, fname, trusted, auto):
    """Read one attachment with the Hub's own readers. → (status, kind, note, result)"""
    import importer
    import investments as I
    import vault as VT
    from parsers.categorizer import categorize
    ext = Path(fname).suffix.lower()
    # 1) broker contract notes / depository statements
    if ext == '.pdf' and I.HOOKS.get('preview'):
        tmp = _tmp_path(fname)
        tmp.write_bytes(data)
        p = I.HOOKS['preview'](con, tmp, fname)
        pv = p.get('pv') or {}
        if pv.get('kind') in ('tradebook', 'depository'):
            kind = 'contract_note' if pv['kind'] == 'tradebook' else 'depository'
            if p.get('dup_file'):
                I.HOOKS['discard'](p['token'])
                return 'duplicate', kind, 'this file was imported before', ''
            sel = p.get('broker_id') or ''
            ready = p.get('importable') and p.get('tick') and (
                (kind == 'contract_note' and sel and pv.get('check') == 'OK') or      # 1.6: totals must reconcile
                (kind == 'depository' and pv.get('demats')))
            if auto and trusted and ready:
                n, msg = I.HOOKS['confirm'](con, p['token'], sel)
                if n:
                    return 'imported', kind, '', msg
            I.HOOKS['discard'](p['token'])
            why = ('forwarded by hand — check it before importing' if not trusted else
                   'broker not recognised' if kind == 'contract_note' and not sel else
                   'totals do not reconcile' if pv.get('check') == 'MISMATCH' else
                   'totals could not be checked' if kind == 'contract_note' and pv.get('check') != 'OK' else
                   'no demat account found' if kind == 'depository' and not pv.get('demats') else
                   'automatic import is off' if not auto else 'check before importing')
            return 'review', kind, why, ''
        I.HOOKS['discard'](p['token'])
        if p.get('needs_pw'):
            pass                                  # may still be a bank / card statement — try that reader below
    # 2) bank and card statements
    tmp = _tmp_path(fname)
    tmp.write_bytes(data)
    token = uuid.uuid4().hex[:12]
    pv = importer.preview_file(con, tmp, fname, token, UPLOAD_DIR, categorize=categorize)
    try:
        if pv['status'] == 'needs_password':
            return 'review', 'statement', 'none of the saved passwords opens it', ''
        if pv['status'] != 'ok':
            if ext != '.pdf' and I.HOOKS.get('preview'):          # 1.6: a broker tradebook / holdings export sent by mail
                tmp2 = _tmp_path(fname)
                tmp2.write_bytes(data)
                p = I.HOOKS['preview'](con, tmp2, fname)
                ipv = p.get('pv') or {}
                I.HOOKS['discard'](p['token'])
                if ipv.get('kind') in ('tradebook', 'holdings'):
                    return 'review', 'contract_note', 'broker file — choose the broker when you review it', ''
            return 'skipped', 'other', (pv.get('msg') or 'not a statement')[:200], ''
        if pv.get('duplicate_statement'):
            return 'duplicate', 'statement', 'this statement is already in the Hub', ''
        new_acct = any(m.get('how') == 'new account' and not m.get('existing') for m in pv.get('account_map', []))
        reasons = [r for r, bad in (('automatic import is off', not auto), ('sender could not be verified', not trusted),
                                    ('balances do not reconcile' if pv.get('check_status') == 'MISMATCH' else
                                     'no balance check in this statement', pv.get('check_status') != 'OK'),
                                    ('new account — confirm it once', new_acct),
                                    ('nothing new in it', not pv.get('default_selected'))) if bad]
        if not reasons:
            res = importer.commit_preview(con, pv)
            if res.get('ok'):
                return 'imported', 'statement', '', res.get('msg', '')
            reasons = [res.get('msg', 'import failed')]
        return 'review', 'statement', '; '.join(reasons)[:200], ''
    finally:
        importer.discard_upload(pv)
        if tmp.exists():
            VT.secure_delete(tmp)


def check_mail(con, factory=None, force=False, mid=None):
    """One pass over every active mailbox (or just one). → summary dict"""
    targets = [b for b in boxes(con, active_only=not mid) if not mid or b['id'] == mid]
    if not targets:
        return {'ok': False, 'msg': 'Add a mailbox first.'}
    total = {'ok': True, 'checked': 0, 'imported': 0, 'review': 0, 'ignored': 0, 'rejected': 0, 'alerts': 0,
             'duplicates': 0, 'errors': 0, 'skipped': 0, 'more': False}
    msgs, oks = [], []
    for b in targets:
        s = settings(con, b['id'])
        if len(targets) > 1 and not configured(s):
            msgs.append(f"{s.get('name') or s['user']}: not set up yet")
            continue
        r = _check_box(con, s, factory)
        con.execute('UPDATE mail_items SET mailbox_id=? WHERE mailbox_id IS NULL', (b['id'],))
        con.commit()
        oks.append(r.get('ok'))
        for k in total:
            if k not in ('ok', 'more') and isinstance(r.get(k), int):
                total[k] += r[k]
        total['more'] = total['more'] or r.get('more', False)
        msgs.append((f"{s.get('name') or s['user']}: " if len(targets) > 1 else '') + r.get('msg', ''))
    total['ok'] = any(oks) if oks else False
    total['msg'] = ' · '.join(msgs)
    _set(con, last_check=datetime.now().isoformat(timespec='seconds'), last_result=total['msg'][:300])
    con.commit()
    return total


def _check_box(con, s, factory=None):
    """One pass over one mailbox (s = settings(con, mailbox id))."""
    if not configured(s):
        return {'ok': False, 'msg': ('Sign in with Microsoft first.' if provider(s) == 'outlook'
                                     else 'Enter the mailbox address and its app password first.')}
    allowed = _lines(s['senders'])
    forwarders = _lines(s['forwarders'])
    auto = s['auto_import'] == '1'
    trusted_srv = trusted_servers_for(s['host'])
    summary = {'ok': True, 'checked': 0, 'imported': 0, 'review': 0, 'ignored': 0, 'rejected': 0, 'alerts': 0,
               'duplicates': 0, 'errors': 0, 'skipped': 0, 'more': False}
    try:
        cli = connect(s, factory, con)
    except Exception as e:  # noqa: BLE001
        msg = explain(e, s)
        _set_box(con, s['id'], last_check=datetime.now().isoformat(timespec='seconds'), last_result=f'Could not connect: {msg}'[:300])
        con.commit()
        return {'ok': False, 'msg': f'Could not connect: {msg}'}
    try:
        uv = cli.select(s['folder'] or 'INBOX')
        last_uid = int(s['last_uid'] or 0) if s['uidvalidity'] == uv else 0
        since = date.today() - timedelta(days=int(s['since_days'] or 60))
        if s['last_check'] and last_uid:
            since = max(since, date.fromisoformat(s['last_check'][:10]) - timedelta(days=2))
        uids = sorted(u for u in cli.search_since(since) if u > last_uid)
        if len(uids) > MAX_PER_RUN * 4:
            uids, summary['more'] = uids[:MAX_PER_RUN * 4], True
        known = {r[0] for r in con.execute('SELECT DISTINCT message_id FROM mail_items')}
        hdrs = cli.headers(uids)
        downloads = 0
        for uid in uids:
            raw, size = hdrs.get(uid, (b'', 0))
            h = email.message_from_bytes(raw or b'', policy=email.policy.default)
            mid = (str(h.get('Message-ID') or '').strip() or f'uid-{uv}-{uid}')[:200]
            if mid in known:
                last_uid = max(last_uid, uid)
                continue
            frm = email.utils.parseaddr(str(h.get('From') or ''))[1].lower()
            dom = frm.split('@')[-1] if '@' in frm else ''
            subj = str(h.get('Subject') or '')[:200]
            try:
                rcv = email.utils.parsedate_to_datetime(str(h.get('Date'))).date().isoformat()
            except Exception:  # noqa: BLE001
                rcv = date.today().isoformat()
            base = (mid, str(uid), rcv, frm, dom, subj)
            summary['checked'] += 1
            is_fwd = frm in forwarders
            if not sender_ok(frm, allowed) and not is_fwd:
                con.execute("INSERT INTO mail_items (message_id, uid, received, from_addr, from_domain, subject, status, kind) "
                            "VALUES (?,?,?,?,?,?, 'ignored', 'other')", base)
                summary['ignored'] += 1
                last_uid = max(last_uid, uid)
                continue
            if downloads >= MAX_PER_RUN:
                summary['more'] = True
                break
            if size > MAX_FILE * 2:
                con.execute("INSERT INTO mail_items (message_id, uid, received, from_addr, from_domain, subject, status, kind, note) "
                            "VALUES (?,?,?,?,?,?, 'error', 'other', 'mail too large')", base)
                last_uid = max(last_uid, uid)
                continue
            downloads += 1
            msg = email.message_from_bytes(cli.message(uid), policy=email.policy.default)
            auth, note = auth_check(msg, dom, trusted_srv)
            via = ''
            if is_fwd:
                orig = forwarded_from(body_text(msg))
                odom = orig.split('@')[-1] if orig else ''
                if auth == 'pass' and sender_ok(orig, allowed):
                    via, frm, dom = frm, orig, odom
                    auth, note = 'forwarded', f'forwarded by you ({via}) — original sender cannot be verified'
                else:
                    auth, note = 'fail', ('forwarded mail from a sender not on the list' if auth == 'pass' else note)
            if auth not in ('pass', 'forwarded'):
                con.execute("INSERT INTO mail_items (message_id, uid, received, from_addr, from_domain, via, subject, auth, auth_note, "
                            "status, kind) VALUES (?,?,?,?,?,?,?,?,?, 'rejected', 'other')",
                            (mid, str(uid), rcv, frm, dom, via, subj, auth, note))
                summary['rejected'] += 1
                last_uid = max(last_uid, uid)
                continue
            files = attachments(msg)
            if not files:
                iid = con.execute("INSERT INTO mail_items (message_id, uid, received, from_addr, from_domain, via, subject, auth, auth_note, "
                                  "status, kind) VALUES (?,?,?,?,?,?,?,?,?, 'alert', 'alert')",
                                  (mid, str(uid), rcv, frm, dom, via, subj, auth, note)).lastrowid
                txt = body_text(msg)
                if txt:
                    name = f'mail_{iid}.txt'
                    _seal(name, txt.encode('utf-8'))
                    con.execute('UPDATE mail_items SET blob=? WHERE id=?', (name, iid))
                summary['alerts'] += 1
            for fname, data in files:
                fh = hashlib.sha256(data).hexdigest()
                iid = con.execute("INSERT INTO mail_items (message_id, uid, received, from_addr, from_domain, via, subject, auth, auth_note, "
                                  "attachment, size, file_hash, status, kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'review', 'other')",
                                  (mid, str(uid), rcv, frm, dom, via, subj, auth, note, fname[:120], len(data), fh)).lastrowid
                if len(data) > MAX_FILE:
                    con.execute("UPDATE mail_items SET status='error', note='attachment larger than 20 MB' WHERE id=?", (iid,))
                    continue
                if con.execute("SELECT 1 FROM mail_items WHERE file_hash=? AND id<>? AND status IN ('imported','duplicate','done')",
                               (fh, iid)).fetchone():
                    con.execute("UPDATE mail_items SET status='duplicate', note='same file came in an earlier mail' WHERE id=?", (iid,))
                    summary['duplicates'] += 1
                    continue
                try:
                    st, kind, why, res = process_file(con, data, fname, auth == 'pass', auto)
                except Exception as e:  # noqa: BLE001
                    con.rollback()
                    st, kind, why, res = 'error', 'other', f'could not read: {e}'[:200], ''
                if st == 'review':
                    name = f'mail_{iid}.bin'
                    _seal(name, data)
                    con.execute('UPDATE mail_items SET blob=? WHERE id=?', (name, iid))
                con.execute('UPDATE mail_items SET status=?, kind=?, note=?, result=? WHERE id=?', (st, kind, why, res[:300], iid))
                key = {'imported': 'imported', 'review': 'review', 'duplicate': 'duplicates', 'error': 'errors',
                       'skipped': 'skipped'}.get(st)
                if key:
                    summary[key] += 1
            con.commit()
            cli.label(uid, s['label'])                 # empty label (Outlook / other): mails stay as they are
            last_uid = max(last_uid, uid)
        parts = [f"{summary[k]} {w}" for k, w in (('imported', 'imported'), ('review', 'waiting for you'), ('alerts', 'alerts kept'),
                                                   ('duplicates', 'already in the Hub'), ('skipped', 'not statements'),
                                                   ('errors', 'could not be read'), ('rejected', 'rejected'),
                                                   ('ignored', 'from other senders')) if summary[k]]
        result = ('New mail: ' + ', '.join(parts)) if parts else 'No new statement mails.'
        if summary['more']:
            result += ' More mails are waiting — they are read on the next check.'
        _set_box(con, s['id'], uidvalidity=uv, last_uid=last_uid, last_check=datetime.now().isoformat(timespec='seconds'), last_result=result)
        con.commit()
        summary['msg'] = result
        return summary
    except Exception as e:  # noqa: BLE001
        con.rollback()
        _set_box(con, s['id'], last_check=datetime.now().isoformat(timespec='seconds'), last_result=f'Mail check failed: {e}'[:300])
        con.commit()
        return {'ok': False, 'msg': f'Mail check failed: {e}'}
    finally:
        cli.close()


def refresh_review(con):
    """Items you imported yourself from the Import pages are marked handled and their stored copy erased."""
    for r in con.execute("SELECT id, file_hash FROM mail_items WHERE status='review' AND file_hash IS NOT NULL").fetchall():
        if con.execute('SELECT 1 FROM statements WHERE file_hash=? UNION SELECT 1 FROM inv_imports WHERE file_hash=?',
                       (r['file_hash'], r['file_hash'])).fetchone():
            _erase_blob(con, r['id'])
            con.execute("UPDATE mail_items SET status='imported', note='imported from the review' WHERE id=?", (r['id'],))
    con.commit()


def due(con):
    s = shared(con)
    if s['enabled'] != '1' or not any(configured(settings(con, b['id'])) for b in boxes(con, active_only=True)):
        return False
    if not s['last_check']:
        return True
    try:
        last = datetime.fromisoformat(s['last_check'])
    except ValueError:
        return True
    return datetime.now() - last >= timedelta(minutes=max(5, int(s['interval'] or 15)))


# ── pages ────────────────────────────────────────────────────────────────────
def register(app, get_db, upload_dir, vault):
    global UPLOAD_DIR, VAULT
    UPLOAD_DIR, VAULT = Path(upload_dir), vault

    def con_():
        c = get_db()
        ensure_schema(c)
        return c

    @app.context_processor
    def _mail_ctx():
        on, waiting = False, 0
        try:
            if VAULT.unlocked:
                c = get_db()
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='mailboxes'").fetchone():
                    on = shared(c)['enabled'] == '1' and any(configured(settings(c, b['id'])) for b in boxes(c, active_only=True))
                    waiting = c.execute("SELECT COUNT(*) FROM mail_items WHERE status='review'").fetchone()[0]
        except Exception:  # noqa: BLE001
            pass
        return {'mail_auto': on, 'mail_waiting': waiting}

    def _add_senders(con, entries):
        """Add (or resume) senders; mails from them that were skipped earlier are read again on the next check."""
        s = shared(con)
        on, off = _lines(s['senders']), _lines(s.get('senders_off', ''))
        for e in entries:
            if e not in on:
                on.append(e)
            if e in off:
                off.remove(e)
            if '@' in e:
                con.execute("DELETE FROM mail_items WHERE lower(from_addr)=? AND status='ignored'", (e,))
            else:
                con.execute("DELETE FROM mail_items WHERE status='ignored' AND (lower(from_domain)=? OR lower(from_domain) LIKE ?)",
                            (e, '%.' + e))
        _set(con, senders='\n'.join(on), senders_off='\n'.join(off))
        if entries:
            con.execute("UPDATE mailboxes SET last_uid='0'")       # look back again (already-read mails are skipped)

    def senders_save():
        """1.11: the list of senders to read — add, pause / resume, delete; exact addresses or whole domains."""
        con = con_()
        f = request.form
        act = f.get('action', '')
        s = shared(con)
        on, off = _lines(s['senders']), _lines(s.get('senders_off', ''))
        picked = [x.lower() for x in f.getlist('entry')]
        if '|' in f.get('one', ''):                               # the pause / resume / delete button on one row
            act, one = f['one'].split('|', 1)
            picked = [one.lower()]
        msg, cat = '', 'success'
        if act == 'add':
            good, bad = sender_entries(f.get('new', ''))
            _add_senders(con, good)
            msg = (f"Added {', '.join(good)}." if good else '') + (f" Not valid: {', '.join(bad)}." if bad else '')
            cat = 'success' if good and not bad else 'warning'
            msg = msg.strip() or 'Type a sender address (e.g. statements@bank.com) or a domain (e.g. bank.com).'
        elif act == 'resume':
            _add_senders(con, [x for x in picked if x in off])
            msg = f"Reading again: {', '.join(picked)}."
        elif act == 'pause':
            on = [x for x in on if x not in picked]
            off = list(dict.fromkeys(off + [x for x in picked if x in _lines(s['senders'])]))
            _set(con, senders='\n'.join(on), senders_off='\n'.join(off))
            msg, cat = f"Paused: {', '.join(picked)} — their mails are skipped.", 'info'
        elif act == 'delete':
            on, off = [x for x in on if x not in picked], [x for x in off if x not in picked]
            _set(con, senders='\n'.join(on), senders_off='\n'.join(off))
            msg, cat = f"Deleted: {', '.join(picked)}.", 'info'
        elif act == 'pause_domains':
            doms = [x for x in on if '@' not in x]
            _set(con, senders='\n'.join(x for x in on if '@' in x), senders_off='\n'.join(dict.fromkeys(off + doms)))
            msg, cat = (f'{len(doms)} domain(s) paused — only the exact addresses on the list are read now.', 'info')
        elif act == 'delete_paused':
            _set(con, senders_off='')
            msg, cat = f'{len(off)} paused sender(s) deleted.', 'info'
        elif act == 'defaults':
            _add_senders(con, [x for x in _lines(DEFAULT_SENDERS) if x not in on])
            msg = 'The built-in bank, card, broker and depository domains are on the list again.'
        if act in ('pause', 'delete', 'pause_domains') and not _lines(shared(con)['senders']):
            msg, cat = msg + ' No sender is being read now — add at least one.', 'warning'
        con.commit()
        if msg:
            flash(msg, cat)
        return redirect(url_for('mail_page', tab=f.get('tab', 'statements')) + '#senders')

    def _sender_rows(con, s):
        seen_a = {r[0]: r[1] for r in con.execute('SELECT lower(from_addr), COUNT(*) FROM mail_items GROUP BY 1')}
        seen_d = defaultdict(int)
        for a, n in seen_a.items():
            if a and '@' in a:
                seen_d[a.rsplit('@', 1)[1]] += n
        def count(e):
            return seen_a.get(e, 0) if '@' in e else sum(n for d, n in seen_d.items() if d == e or d.endswith('.' + e))
        rows = [{'entry': e, 'on': True, 'addr': '@' in e, 'n': count(e)} for e in _lines(s['senders'])]
        rows += [{'entry': e, 'on': False, 'addr': '@' in e, 'n': count(e)} for e in _lines(s.get('senders_off', ''))]
        rows.sort(key=lambda r: (not r['addr'], r['entry'].rsplit('@', 1)[-1], r['entry']))
        return rows

    def mail_page():
        con = con_()
        refresh_review(con)
        s = shared(con)
        bl = []
        for b in boxes(con):
            bs = settings(con, b['id'])
            bl.append(dict(bs, kind=provider(bs), ready=configured(bs), signed_in=bool(bs.get('oauth_refresh')),
                           has_password=bool(bs.get('password'))))
        tab = request.args.get('tab', 'statements')
        where = {'statements': "kind IN ('statement','contract_note','depository','other') AND status NOT IN ('ignored','rejected')",
                 'review': "status='review'", 'alerts': "status='alert'", 'ignored': "status IN ('ignored','rejected')"}.get(tab, '1')
        items = con.execute(f'SELECT i.*, b.name AS box_name, b.user AS box_user FROM mail_items i LEFT JOIN mailboxes b ON b.id=i.mailbox_id '
                            f'WHERE {where} ORDER BY received DESC, i.id DESC LIMIT 300').fetchall()
        counts = {k: con.execute(f'SELECT COUNT(*) FROM mail_items WHERE {w}').fetchone()[0] for k, w in (
            ('review', "status='review'"), ('alerts', "status='alert'"), ('ignored', "status IN ('ignored','rejected')"))}
        edit = request.args.get('box')
        editing = next((b for b in bl if str(b['id']) == edit), None) if edit and edit != 'new' else None
        new_kind = request.args.get('kind') if request.args.get('kind') in PROVIDERS else 'gmail'
        snd = _sender_rows(con, s)
        return render_template('mail.html', s=s, items=items, tab=tab, counts=counts, STATUS=STATUS, PROVIDERS=PROVIDERS, snd=snd,
                               snd_on=sum(1 for r in snd if r['on']), snd_addr=sum(1 for r in snd if r['on'] and r['addr']),
                               boxes=bl, configured=any(b['ready'] for b in bl), editing=editing,
                               adding=(edit == 'new' or not bl), new_kind=new_kind, many=len(bl) > 1)

    def mail_settings_save():
        """Shared reading rules (and, for older forms, the first mailbox's address / password)."""
        con = con_()
        f = request.form
        kw = {}
        for k in ('interval', 'since_days'):
            if k in f:
                kw[k] = f.get(k, '').strip()
        if 'interval' in kw:
            kw['interval'] = str(max(5, min(1440, int(kw['interval'] or 15)))) if kw['interval'].isdigit() else '15'
        if 'since_days' in kw:
            kw['since_days'] = str(max(1, min(400, int(kw['since_days'] or 60)))) if kw['since_days'].isdigit() else '60'
        if 'senders' in f:
            kw['senders'] = '\n'.join(sender_entries(f['senders'])[0])
        if 'forwarders' in f:
            kw['forwarders'] = '\n'.join(dict.fromkeys(a for a in _lines(f['forwarders']) if '@' in a))
        kw['enabled'] = '1' if f.get('enabled') else '0'
        kw['auto_import'] = '1' if f.get('auto_import') else '0'
        _set(con, **kw)
        if f.get('user', '').strip():                       # older single-mailbox form (and the setup wizard)
            bs = boxes(con)
            save_box_form(con, bs[0]['id'] if bs else None, f)
        con.commit()
        flash('Mail settings saved.', 'success')
        return redirect(url_for('mail_page', tab=request.form.get('tab', 'statements')))


    def box_save():
        con = con_()
        mid = request.form.get('box_id', type=int)
        if mid and not con.execute('SELECT 1 FROM mailboxes WHERE id=?', (mid,)).fetchone():
            mid = None
        if not request.form.get('user', '').strip():
            flash('Enter the mailbox address.', 'warning')
            return redirect(url_for('mail_page', box=mid or 'new', kind=request.form.get('provider')))
        mid = save_box_form(con, mid, request.form)
        con.commit()
        s = settings(con, mid)
        flash('Mailbox saved.' + (' Now click “Sign in with Microsoft”.' if provider(s) == 'outlook' and not s.get('oauth_refresh') else ''), 'success')
        return redirect(url_for('mail_page', box=mid) if provider(s) == 'outlook' and not s.get('oauth_refresh') else url_for('mail_page'))

    def box_action(mid):
        con = con_()
        a = request.form.get('action')
        b = con.execute('SELECT * FROM mailboxes WHERE id=?', (mid,)).fetchone()
        if not b:
            return redirect(url_for('mail_page'))
        if a == 'remove':
            con.execute('DELETE FROM mailboxes WHERE id=?', (mid,))
            if b['send_from'] and (first := con.execute('SELECT id FROM mailboxes ORDER BY id LIMIT 1').fetchone()):
                con.execute('UPDATE mailboxes SET send_from=1 WHERE id=?', (first[0],))
            flash(f"Mailbox {b['user']} removed (mails already read stay in the Hub).", 'info')
        elif a == 'send_from':
            con.execute('UPDATE mailboxes SET send_from=CASE WHEN id=? THEN 1 ELSE 0 END', (mid,))
            flash(f"Reminders and problem reports are now sent from {b['user']}.", 'success')
        elif a == 'toggle':
            con.execute('UPDATE mailboxes SET active=1-COALESCE(active,1) WHERE id=?', (mid,))
            flash(f"{b['user']}: {'paused' if b['active'] else 'read again'}.", 'info')
        elif a == 'signout':
            _set_box(con, mid, oauth_refresh='')
            flash('Signed out of Microsoft — the Hub no longer has access to that mailbox.', 'info')
        con.commit()
        return redirect(url_for('mail_page'))

    def mail_test(mid=None):
        con = con_()
        mid = mid or request.form.get('box_id', type=int)
        s = settings(con, mid)
        try:
            cli = connect(s, app.config.get('HUB_IMAP_FACTORY'), con)
            try:
                cli.select(s['folder'] or 'INBOX')
            finally:
                cli.close()
            flash(f"Connected to {s['user']} ✓", 'success')
        except Exception as e:  # noqa: BLE001
            flash(f"Could not connect to {s['user'] or 'the mailbox'}: {explain(e, s)}", 'danger')
        return redirect(url_for('mail_page'))

    # ── 1.8: Sign in with Microsoft (device code), per mailbox ─────────────
    def ms_start(mid):
        import oauth_ms
        con = con_()
        s = settings(con, mid)
        try:
            pending = oauth_ms.start(s.get('ms_client_id', ''), s.get('ms_tenant') or 'common')
        except Exception as e:  # noqa: BLE001
            return jsonify({'ok': False, 'msg': str(e)})
        oauth_ms.DEVICE[(VAULT.user, mid)] = pending
        if pending.get('tenant') and pending['tenant'] != s.get('ms_tenant'):
            _set_box(con, mid, ms_tenant=pending['tenant'])
            con.commit()
        return jsonify({'ok': True, 'user_code': pending['user_code'], 'verification_uri': pending.get('verification_uri'),
                        'interval': int(pending.get('interval', 5)), 'expires_in': int(pending.get('expires_in', 900))})

    def ms_poll(mid):
        import oauth_ms
        con = con_()
        s = settings(con, mid)
        pending = oauth_ms.DEVICE.get((VAULT.user, mid))
        if not pending:
            return jsonify({'state': 'error', 'msg': 'no sign-in in progress — click “Sign in with Microsoft”'})
        try:
            state, payload = oauth_ms.poll(s['ms_client_id'], pending)
        except Exception as e:  # noqa: BLE001
            return jsonify({'state': 'pending', 'msg': f'waiting ({str(e)[:80]})'})
        if state == 'ok':
            oauth_ms.DEVICE.pop((VAULT.user, mid), None)
            fresh_box = not s.get('oauth_refresh')
            _set_box(con, mid, oauth_refresh=payload['refresh_token'], provider='outlook',
                     **({'last_uid': '0', 'uidvalidity': ''} if fresh_box else {}))
            acct = payload.get('account') or ''
            if acct and '@' in acct and acct != (s.get('user') or '').lower():
                flash(f"You signed in to Microsoft as {acct}, but this mailbox is {s['user']}. If reading fails, sign in again "
                      f"with {s['user']} (in the Microsoft page choose “Use another account”), or change the mailbox address.", 'warning')
            con.commit()
            return jsonify({'state': 'ok'})
        if state == 'error':
            oauth_ms.DEVICE.pop((VAULT.user, mid), None)
            return jsonify({'state': 'error', 'msg': payload})
        return jsonify({'state': 'pending'})

    def mail_check():
        con = con_()
        r = check_mail(con, force=True)
        flash(r.get('msg', ''), 'success' if r.get('ok') else 'danger')
        return redirect(url_for('mail_page', tab='review' if r.get('review') else 'statements'))

    def mail_poll():
        con = con_()
        if not due(con):
            return jsonify({'ok': True, 'checked': False})
        r = check_mail(con)
        r['checked'] = True
        r['waiting'] = con.execute("SELECT COUNT(*) FROM mail_items WHERE status='review'").fetchone()[0]
        return jsonify(r)

    def mail_review(iid):
        import importer
        import investments as I
        from parsers.categorizer import categorize
        con = con_()
        it = con.execute('SELECT * FROM mail_items WHERE id=?', (iid,)).fetchone()
        if not it or not it['blob'] or it['status'] != 'review':
            flash('That file is no longer waiting.', 'info')
            return redirect(url_for('mail_page'))
        data = _unseal(it['blob'])
        fname = it['attachment'] or 'statement.pdf'
        tmp = _tmp_path(fname)
        tmp.write_bytes(data)
        if it['kind'] in ('contract_note', 'depository'):
            p = I.HOOKS['preview'](con, tmp, fname)
            return I.HOOKS['render'](con, [p])
        token = uuid.uuid4().hex[:12]
        importer.preview_file(con, tmp, fname, token, UPLOAD_DIR, categorize=categorize)
        return redirect(url_for('import_page', pending=token))

    def mail_item(iid):
        con = con_()
        it = con.execute('SELECT * FROM mail_items WHERE id=?', (iid,)).fetchone()
        act = request.form.get('action')
        if not it:
            return redirect(url_for('mail_page'))
        if act in ('allow', 'allow_addr') and it['from_domain']:
            entry = (it['from_addr'] if act == 'allow_addr' and it['from_addr'] else it['from_domain']).lower().strip()
            if not (ADDR_RE.match(entry) or DOMAIN_RE.match(entry)):
                flash('That sender address cannot be added as it is — add it by hand under Senders to read.', 'warning')
                return redirect(url_for('mail_page', tab=request.form.get('tab', 'statements')))
            _add_senders(con, [entry])
            flash(f'{entry} added to the senders to read — its mails are read on the next check.', 'success')
        elif act == 'dismiss':
            _erase_blob(con, iid)
            con.execute("UPDATE mail_items SET status='done', note='dismissed' WHERE id=?", (iid,))
            flash('Dismissed — its stored copy was erased.', 'info')
        elif act == 'retry' and it['blob'] and it['status'] == 'review':
            data = _unseal(it['blob'])
            st, kind, why, res = process_file(con, data, it['attachment'], it['auth'] == 'pass', True)
            if st != 'review':
                _erase_blob(con, iid)
            con.execute('UPDATE mail_items SET status=?, kind=?, note=?, result=? WHERE id=?', (st, kind, why, res[:300], iid))
            flash(f"{it['attachment']}: {STATUS.get(st, (st,))[0]}{' — ' + why if why else ''}{' — ' + res if res else ''}",
                  'success' if st == 'imported' else 'info')
        con.commit()
        return redirect(url_for('mail_page', tab=request.form.get('tab', 'statements')))

    def mail_alert_text(iid):
        con = con_()
        it = con.execute("SELECT * FROM mail_items WHERE id=? AND status='alert'", (iid,)).fetchone()
        if not it or not it['blob']:
            return jsonify({'text': ''})
        return jsonify({'text': _unseal(it['blob']).decode('utf-8', 'replace')})

    def mail_forget():
        """Erase the list of handled / ignored mails (stored copies included)."""
        con = con_()
        for r in con.execute("SELECT id FROM mail_items WHERE status IN ('imported','duplicate','ignored','rejected','skipped','done','error')").fetchall():
            _erase_blob(con, r['id'])
        con.execute("DELETE FROM mail_items WHERE status IN ('imported','duplicate','ignored','rejected','skipped','done','error')")
        con.commit()
        flash('History cleared. Mails already read are not read again (unless you add one of their senders later).', 'info')
        return redirect(url_for('mail_page'))

    for rule, ep, fn, methods in [
        ('/mail', 'mail_page', mail_page, ['GET']),
        ('/mail/settings', 'mail_settings_save', mail_settings_save, ['POST']),
        ('/mail/test', 'mail_test', mail_test, ['POST']),
        ('/mail/check', 'mail_check', mail_check, ['POST']),
        ('/mail/poll', 'mail_poll', mail_poll, ['POST']),
        ('/mail/<int:iid>/review', 'mail_review', mail_review, ['POST']),
        ('/mail/<int:iid>', 'mail_item', mail_item, ['POST']),
        ('/mail/<int:iid>/text', 'mail_alert_text', mail_alert_text, ['GET']),
        ('/mail/forget', 'mail_forget', mail_forget, ['POST']),
        ('/mail/senders', 'mail_senders', senders_save, ['POST']),
        ('/mail/box/save', 'mail_box_save', box_save, ['POST']),
        ('/mail/box/<int:mid>', 'mail_box_action', box_action, ['POST']),
        ('/mail/box/<int:mid>/test', 'mail_box_test', mail_test, ['POST']),
        ('/mail/box/<int:mid>/ms/start', 'mail_ms_start', ms_start, ['POST']),
        ('/mail/box/<int:mid>/ms/poll', 'mail_ms_poll', ms_poll, ['POST']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)
