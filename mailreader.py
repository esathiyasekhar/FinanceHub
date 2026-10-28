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
"""

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
            'forwarders': '', 'last_check': '', 'last_result': '', 'uidvalidity': '', 'last_uid': '0'}
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
    for k, v in DEFAULTS.items():
        con.execute('INSERT OR IGNORE INTO mail_settings (key, value) VALUES (?,?)', (k, v))
    con.commit()


def settings(con):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in con.execute('SELECT key, value FROM mail_settings')})
    return s


def _set(con, **kw):
    for k, v in kw.items():
        con.execute('INSERT OR REPLACE INTO mail_settings (key, value) VALUES (?,?)', (k, str(v)))


def _lines(text):
    return [x.strip().lower() for x in re.split(r'[\s,;]+', text or '') if x.strip()]


# ── sender checks ───────────────────────────────────────────────────────────
def org_domain(d):
    parts = (d or '').lower().strip('.').split('.')
    n = 3 if len(parts) >= 3 and '.'.join(parts[-2:]) in TWO_LEVEL else 2
    return '.'.join(parts[-n:])


def domain_on_list(domain, allowed):
    domain = (domain or '').lower()
    return any(domain == a or domain.endswith('.' + a) for a in allowed)


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

    def __init__(self, host, port, user, password, timeout=30):
        self.m = imaplib.IMAP4_SSL(host, int(port or 993), ssl_context=ssl.create_default_context(), timeout=timeout)
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


def connect(s, factory=None):
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


def check_mail(con, factory=None, force=False):
    """One pass over the mailbox. → summary dict"""
    s = settings(con)
    if not s['user'] or not s['password']:
        return {'ok': False, 'msg': 'Enter the mailbox address and its app password first.'}
    allowed = _lines(s['senders'])
    forwarders = _lines(s['forwarders'])
    auto = s['auto_import'] == '1'
    trusted_srv = trusted_servers_for(s['host'])
    summary = {'ok': True, 'checked': 0, 'imported': 0, 'review': 0, 'ignored': 0, 'rejected': 0, 'alerts': 0,
               'duplicates': 0, 'errors': 0, 'skipped': 0, 'more': False}
    try:
        cli = connect(s, factory)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if 'AUTHENTICATIONFAILED' in msg.upper() or 'invalid credentials' in msg.lower():
            msg = 'the mailbox refused the address / app password'
        _set(con, last_check=datetime.now().isoformat(timespec='seconds'), last_result=f'Could not connect: {msg}'[:300])
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
            if not domain_on_list(dom, allowed) and not is_fwd:
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
                if auth == 'pass' and domain_on_list(odom, allowed):
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
            cli.label(uid, s['label'] or 'FinanceHub')
            last_uid = max(last_uid, uid)
        parts = [f"{summary[k]} {w}" for k, w in (('imported', 'imported'), ('review', 'waiting for you'), ('alerts', 'alerts kept'),
                                                   ('duplicates', 'already in the Hub'), ('skipped', 'not statements'),
                                                   ('errors', 'could not be read'), ('rejected', 'rejected'),
                                                   ('ignored', 'from other senders')) if summary[k]]
        result = ('New mail: ' + ', '.join(parts)) if parts else 'No new statement mails.'
        if summary['more']:
            result += ' More mails are waiting — they are read on the next check.'
        _set(con, uidvalidity=uv, last_uid=last_uid, last_check=datetime.now().isoformat(timespec='seconds'), last_result=result)
        con.commit()
        summary['msg'] = result
        return summary
    except Exception as e:  # noqa: BLE001
        con.rollback()
        _set(con, last_check=datetime.now().isoformat(timespec='seconds'), last_result=f'Mail check failed: {e}'[:300])
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
    s = settings(con)
    if s['enabled'] != '1' or not s['user'] or not s['password']:
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
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='mail_settings'").fetchone():
                    s = settings(c)
                    on = s['enabled'] == '1' and bool(s['user']) and bool(s['password'])
                    waiting = c.execute("SELECT COUNT(*) FROM mail_items WHERE status='review'").fetchone()[0]
        except Exception:  # noqa: BLE001
            pass
        return {'mail_auto': on, 'mail_waiting': waiting}

    def mail_page():
        con = con_()
        refresh_review(con)
        s = settings(con)
        tab = request.args.get('tab', 'statements')
        where = {'statements': "kind IN ('statement','contract_note','depository','other') AND status NOT IN ('ignored','rejected')",
                 'review': "status='review'", 'alerts': "status='alert'", 'ignored': "status IN ('ignored','rejected')"}.get(tab, '1')
        items = con.execute(f'SELECT * FROM mail_items WHERE {where} ORDER BY received DESC, id DESC LIMIT 300').fetchall()
        counts = {k: con.execute(f'SELECT COUNT(*) FROM mail_items WHERE {w}').fetchone()[0] for k, w in (
            ('review', "status='review'"), ('alerts', "status='alert'"), ('ignored', "status IN ('ignored','rejected')"))}
        return render_template('mail.html', s=s, items=items, tab=tab, counts=counts, STATUS=STATUS,
                               has_password=bool(s['password']), configured=bool(s['user'] and s['password']))

    def mail_settings_save():
        con = con_()
        f = request.form
        old = settings(con)
        kw = {}
        for k in ('host', 'port', 'user', 'folder', 'label', 'interval', 'since_days'):
            kw[k] = f.get(k, old[k]).strip()[:200]                  # 1.6: fields not on the form keep their value
        kw['label'] = re.sub(r'[^A-Za-z0-9 _/-]', '', kw.get('label', 'FinanceHub')) or 'FinanceHub'
        kw['interval'] = str(max(5, min(1440, int(kw.get('interval') or 15)))) if (kw.get('interval') or '15').isdigit() else '15'
        kw['since_days'] = str(max(1, min(400, int(kw.get('since_days') or 60)))) if (kw.get('since_days') or '60').isdigit() else '60'
        if 'senders' in f:
            kw['senders'] = '\n'.join(dict.fromkeys(_lines(f['senders'])))
        if 'forwarders' in f:
            kw['forwarders'] = '\n'.join(dict.fromkeys(a for a in _lines(f['forwarders']) if '@' in a))
        kw['enabled'] = '1' if f.get('enabled') else '0'
        kw['auto_import'] = '1' if f.get('auto_import') else '0'
        if f.get('password', '').strip():
            kw['password'] = f['password'].strip().replace(' ', '')       # Gmail shows app passwords in groups of four
        if kw.get('user') != old['user'] or kw.get('folder') != old['folder'] or kw.get('host') != old['host']:
            kw.update(last_uid='0', uidvalidity='')
        _set(con, **kw)
        con.commit()
        flash('Mailbox settings saved.', 'success')
        return redirect(url_for('mail_page', tab=request.form.get('tab', 'statements')))

    def mail_test():
        con = con_()
        s = settings(con)
        try:
            cli = connect(s)
            try:
                cli.select(s['folder'] or 'INBOX')
            finally:
                cli.close()
            flash('Connected to the mailbox ✓', 'success')
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if 'AUTHENTICATIONFAILED' in msg.upper() or 'invalid credentials' in msg.lower():
                msg = 'the mailbox refused the address / app password'
            flash(f'Could not connect: {msg}', 'danger')
        return redirect(url_for('mail_page'))

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
        if act == 'allow' and it['from_domain']:
            s = settings(con)
            _set(con, senders='\n'.join(dict.fromkeys(_lines(s['senders']) + [it['from_domain']])))
            con.execute("DELETE FROM mail_items WHERE from_domain=? AND status='ignored'", (it['from_domain'],))
            _set(con, last_uid='0')                 # read those mails again on the next check
            flash(f'{it["from_domain"]} added to the sender list — its mails are read on the next check.', 'success')
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
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)
