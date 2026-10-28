"""Finance Hub 1.6 — payment reminders and the weekly dues report, by e-mail.

* A reminder goes out the day before a payment is due (card bills, EMIs, loan repayments, regular payments, money you
  borrowed from people), one mail per due date, at the time you choose.
* The weekly report (Sunday morning by default) lists everything due in the next two weeks, plus anything overdue.
* Mails go to the addresses you choose, sent through the Hub's own mailbox (Settings › Mail inbox; Gmail: smtp.gmail.com).

How it works while the Hub is locked: the mails for the coming days are prepared whenever the Hub is unlocked (and again
whenever your data changes). They are kept in memory and — on Windows — in data/<id>.outbox, protected by your Windows
login (DPAPI), so the background server can send them on time even when the Hub is locked or after a restart. The file is
useless on another computer or another Windows account. data/<id>.sent.json records only which mails went out
(hashed keys and times — no names or amounts).
"""
import hashlib
import json
import logging
import re
import smtplib
import ssl
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash

log = logging.getLogger('financehub.notify')

SCHEMA = """CREATE TABLE IF NOT EXISTS notify_settings (key TEXT PRIMARY KEY, value TEXT);"""
DEFAULTS = {'enabled': '0', 'recipients': '', 'remind': '1', 'remind_time': '09:00', 'weekly': '1', 'weekly_day': '6',
            'weekly_time': '08:00', 'amounts': '1', 'smtp_host': '', 'smtp_port': '465'}
DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
KIND_LABEL = {'card': 'Card bill', 'emi': 'EMI', 'loan': 'Loan', 'recurring': 'Regular payment', 'person': 'Borrowed',
              'deposit': 'Deposit matures'}
EMAIL_RE = re.compile(r'^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$')

APP = None
VAULT = None
MEMORY = {}            # db stem → outbox dict (survives a lock, not a restart)
_DIRTY = threading.Event()
_LAST_BUILD = {}
_FAILS = {}


# ── settings ────────────────────────────────────────────────────────────────
def ensure_schema(con):
    con.executescript(SCHEMA)
    for k, v in DEFAULTS.items():
        con.execute('INSERT OR IGNORE INTO notify_settings (key, value) VALUES (?,?)', (k, v))
    con.commit()


def settings(con):
    s = dict(DEFAULTS)
    try:
        s.update({k: v for k, v in con.execute('SELECT key, value FROM notify_settings')})
    except Exception:  # noqa: BLE001
        pass
    return s


def recipients(s):
    return [a for a in dict.fromkeys(x.strip().lower() for x in re.split(r'[\s,;]+', s.get('recipients', '')) if x.strip())
            if EMAIL_RE.match(a)]


def smtp_for(mail_s, s):
    host = (s.get('smtp_host') or '').strip()
    if not host:
        ih = (mail_s.get('host') or '').lower()
        host = 'smtp.gmail.com' if 'gmail' in ih or 'google' in ih else (ih.replace('imap.', 'smtp.', 1) if ih.startswith('imap.') else '')
    return {'host': host, 'port': int(s.get('smtp_port') or 465), 'user': mail_s.get('user', ''), 'password': mail_s.get('password', '')}


def _hm(text, default):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', (text or '').strip())
    return (int(m.group(1)) % 24, int(m.group(2)) % 60) if m else default


# ── what is due ─────────────────────────────────────────────────────────────
def events(con, start, days):
    """Payments due in [start, start+days]: card bills (not yet paid), EMIs, loans, regular payments, money borrowed
    from people; deposits maturing are listed as money coming in."""
    import accounts_hub as AH
    import planning as PL
    b = AH.build(con, ignore_scope=True)
    out = []
    for e in AH.dues(con, b, start=start, days=days, recurring=PL.recurring_for_dues(con, b)):
        if e.get('state') == 'paid' or e.get('status') == 'paid':
            continue
        out.append({'date': e['date'], 'title': e['title'], 'amount': e.get('amount'), 'kind': e.get('kind', ''),
                    'status': e.get('status', ''), 'inflow': bool(e.get('inflow')), 'min': e.get('min')})
    try:
        import ledger as L
        end = start + timedelta(days=days)
        for l in L.pl_rows(con):
            if l['direction'] == 'taken' and l['status'] == 'open' and l['outstanding'] > 0.5 and l['due'] and l['due'] <= end:
                out.append({'date': max(l['due'], start) if l['due'] < start else l['due'], 'title': f"Repay {l['person']}",
                            'amount': l['outstanding'], 'kind': 'person', 'status': 'overdue' if l['due'] < start else 'due',
                            'inflow': False, 'min': None})
    except Exception as e:  # noqa: BLE001
        log.warning('people loans skipped: %s', e)
    out.sort(key=lambda x: (x['date'], x['title']))
    return out


def overdue(con, today):
    return [e for e in events(con, today - timedelta(days=45), 45) if e['status'] in ('overdue', 'payment not seen yet')
            and e['date'] < today and not e['inflow']]


# ── mail content ────────────────────────────────────────────────────────────
def _money(v):
    if v is None:
        return 'amount not known yet'
    v = float(v)
    whole, frac = f'{abs(v):.2f}'.split('.')
    if len(whole) > 3:
        whole = re.sub(r'(\d)(?=(\d{2})+$)', r'\1,', whole[:-3]) + ',' + whole[-3:]
    return f"{'-' if v < 0 else ''}₹{whole}" + ('' if frac == '00' else f'.{frac}')


def _rows_html(items, amounts):
    tr = []
    for e in items:
        amt = _money(e['amount']) if amounts else ('—' if e['amount'] is None else 'see the Hub')
        extra = f"<div style='color:#69728f;font-size:12px'>minimum {_money(e['min'])}</div>" if amounts and e.get('min') else ''
        tr.append(f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e2e6f2;white-space:nowrap'>{e['date']:%a %d %b}</td>"
                  f"<td style='padding:6px 8px;border-bottom:1px solid #e2e6f2'>{escape(e['title'])}"
                  f"<div style='color:#69728f;font-size:12px'>{escape(KIND_LABEL.get(e['kind'], e['kind']))}"
                  f"{' · ' + escape(e['status']) if e['status'] and e['status'] not in ('due',) else ''}</div></td>"
                  f"<td style='padding:6px 8px;border-bottom:1px solid #e2e6f2;text-align:right;white-space:nowrap'>{escape(amt)}{extra}</td></tr>")
    return ("<table style='border-collapse:collapse;width:100%;font-size:14px'>"
            "<tr style='background:#eef2ff'><th style='text-align:left;padding:6px 8px'>Due</th><th style='text-align:left;padding:6px 8px'>What</th>"
            "<th style='text-align:right;padding:6px 8px'>Amount</th></tr>" + ''.join(tr) + '</table>')


def _rows_text(items, amounts):
    return '\n'.join(f"  {e['date']:%a %d %b}  {e['title']}  ({KIND_LABEL.get(e['kind'], e['kind'])})"
                     + (f"  {_money(e['amount'])}" if amounts else '') for e in items)


def _total(items):
    known = [e['amount'] for e in items if e['amount'] is not None and not e['inflow']]
    return sum(known), len(items) - len(known)


def _wrap(title, inner, built):
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:auto;color:#1a2138'>"
            f"<div style='background:linear-gradient(135deg,#6366f1,#8b5cf6 55%,#ec4899);color:#fff;padding:14px 18px;border-radius:12px 12px 0 0'>"
            f"<div style='font-size:12px;opacity:.85'>Finance Hub</div><div style='font-size:19px;font-weight:700'>{escape(title)}</div></div>"
            f"<div style='border:1px solid #e2e6f2;border-top:0;padding:16px 18px;border-radius:0 0 12px 12px'>{inner}"
            f"<p style='color:#69728f;font-size:12px;margin-top:18px'>Based on your Finance Hub data as of {built:%d %b %Y, %H:%M}. "
            f"Payments made after that, or not yet in an imported statement, are not reflected. Open the Hub's Dues calendar for the latest.</p>"
            f"</div></div>")


def reminder_mail(due, items, amounts, built):
    pay = [e for e in items if not e['inflow']]
    total, unknown = _total(pay)
    title = f"Due tomorrow — {due:%A %d %b}"
    lead = (f"<p>{len(pay)} payment{'s' if len(pay) != 1 else ''} fall{'s' if len(pay) == 1 else ''} due tomorrow"
            + (f", <b>{_money(total)}</b> in all" + (' (plus amounts not known yet)' if unknown else '') if amounts else '') + '.</p>')
    html = _wrap(title, lead + _rows_html(pay, amounts), built)
    text = f"Finance Hub — {title}\n\n{_rows_text(pay, amounts)}\n" + (f"\nTotal: {_money(total)}\n" if amounts else '')
    return f"Finance Hub: payments due tomorrow ({due:%d %b})", html, text


def weekly_mail(sunday, this_week, next_week, late, amounts, built, waiting=()):
    parts, text = [], [f"Finance Hub — week of {sunday:%d %b %Y}"]
    t1, _ = _total(this_week)
    t2, _ = _total(next_week)
    if amounts:
        parts.append(f"<p>Due in the next 7 days: <b>{_money(t1)}</b> · the 7 days after: <b>{_money(t2)}</b>"
                     + (f" · <span style='color:#dc2626'>overdue: <b>{len(late)}</b></span>" if late else '') + '</p>')
    for head, items in (('Overdue', late), ('Next 7 days', this_week), ('The week after', next_week)):
        if items:
            parts.append(f"<h3 style='font-size:15px;margin:16px 0 6px'>{head}</h3>" + _rows_html(items, amounts))
            text.append(f"\n{head}:\n{_rows_text(items, amounts)}")
    if waiting:
        rows = ''.join(f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e2e6f2'>{escape(w['d_name'] or w['d_desc'] or '')[:60]}"
                       f"<div style='color:#69728f;font-size:12px'>paid {w['d_date']} · waiting {w.get('age', 0)} days"
                       f"{' — follow up' if w.get('late') else ''}</div></td><td style='padding:6px 8px;border-bottom:1px solid #e2e6f2;text-align:right'>"
                       f"{escape(_money(w['expected'] or w['d_amt'])) if amounts else ''}</td></tr>" for w in waiting)
        parts.append("<h3 style='font-size:15px;margin:16px 0 6px'>Refunds you are waiting for</h3>"
                     f"<table style='border-collapse:collapse;width:100%;font-size:14px'>{rows}</table>")
        text.append('\nRefunds you are waiting for:\n' + '\n'.join(f"  {w['d_date']}  {(w['d_name'] or w['d_desc'] or '')[:50]}"
                                                                   f"  waiting {w.get('age', 0)} days" for w in waiting))
    if not (late or this_week or next_week):
        parts.append('<p>Nothing is due in the next two weeks.</p>')
        text.append('\nNothing is due in the next two weeks.')
    return (f"Finance Hub: weekly dues report ({sunday:%d %b})", _wrap(f"Your dues — week of {sunday:%d %b}", ''.join(parts), built),
            '\n'.join(text))


# ── outbox ──────────────────────────────────────────────────────────────────
def waiting_refunds(con):
    try:
        import refunds as RF
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='txn_refunds'").fetchone():
            return RF.rows(con, "r.kind='expected' AND r.status='waiting'")
    except Exception:  # noqa: BLE001
        pass
    return []


def weekly_now(con, amounts):
    """This week's report as it would be sent now (for the preview and the test mail)."""
    today = date.today()
    with (APP.test_request_context('/') if APP is not None else _nullctx()):     # no Viewing filter
        ev = events(con, today, 13)
        late = overdue(con, today)
        waiting = waiting_refunds(con)
    return weekly_mail(today, [e for e in ev if e['date'] < today + timedelta(days=7) and not e['inflow']],
                       [e for e in ev if e['date'] >= today + timedelta(days=7) and not e['inflow']], late, amounts, datetime.now(), waiting)


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def build_outbox(con, now=None):
    """Mails for the next 15 days, prepared from the (unlocked) data. → outbox dict or None"""
    import mailreader as MR
    now = now or datetime.now()
    s = settings(con)
    ms = MR.settings(con) if con.execute("SELECT 1 FROM sqlite_master WHERE name='mail_settings'").fetchone() else {}
    to = recipients(s)
    smtp = smtp_for(ms, s)
    if s['enabled'] != '1' or not to or not smtp['host'] or not smtp['user'] or not smtp['password']:
        return None
    amounts = s['amounts'] == '1'
    today = now.date()
    msgs = []
    if s['remind'] == '1':
        hh, mm = _hm(s['remind_time'], (9, 0))
        by_day = {}
        for e in events(con, today, 16):
            if not e['inflow']:
                by_day.setdefault(e['date'], []).append(e)
        for due, items in by_day.items():
            send_at = datetime.combine(due - timedelta(days=1), datetime.min.time()).replace(hour=hh, minute=mm)
            until = datetime.combine(due, datetime.min.time()).replace(hour=12)
            if until <= now:
                continue
            subj, html, text = reminder_mail(due, items, amounts, now)
            msgs.append({'key': f'remind:{due}', 'kind': 'reminder', 'send_at': send_at.isoformat(), 'until': until.isoformat(),
                         'subject': subj, 'html': html, 'text': text})
    if s['weekly'] == '1':
        hh, mm = _hm(s['weekly_time'], (8, 0))
        wd = int(s['weekly_day'] or 6) % 7
        d = today + timedelta(days=(wd - today.weekday()) % 7)
        late = overdue(con, today)
        waiting = waiting_refunds(con)
        for k in range(2):
            day = d + timedelta(days=7 * k)
            send_at = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
            until = datetime.combine(day, datetime.min.time()).replace(hour=23, minute=59)
            if until <= now:
                continue
            ev = events(con, day, 13)
            this_w = [e for e in ev if e['date'] < day + timedelta(days=7) and not e['inflow']]
            next_w = [e for e in ev if e['date'] >= day + timedelta(days=7) and not e['inflow']]
            subj, html, text = weekly_mail(day, this_w, next_w, late if k == 0 else [], amounts, now, waiting)
            msgs.append({'key': f'weekly:{day}', 'kind': 'weekly', 'send_at': send_at.isoformat(), 'until': until.isoformat(),
                         'subject': subj, 'html': html, 'text': text})
    return {'v': 1, 'built': now.isoformat(timespec='seconds'), 'smtp': smtp, 'to': to, 'messages': msgs}


# ── Windows DPAPI (protects the outbox with the Windows login) ─────────────
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes as wt

    class BLOB(ctypes.Structure):
        _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def mk(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                   ctypes.POINTER(BLOB)]
    fn.restype = wt.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    src, _k1 = mk(data)
    ent, _k2 = mk(b'FinanceHub outbox v1')
    out = BLOB()
    if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x01, ctypes.byref(out)):   # 0x01 = no UI
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def dpapi_available():
    try:
        import ctypes
        return hasattr(ctypes, 'windll')
    except Exception:  # noqa: BLE001
        return False


def save_outbox(data_dir, stem, box):
    p = Path(data_dir) / f'{stem}.outbox'
    if box is None:
        MEMORY.pop(stem, None)
        if p.exists():
            import vault as VT
            VT.secure_delete(p)
        return
    MEMORY[stem] = box
    if dpapi_available():
        try:
            p.write_bytes(b'FHOUTBOX1' + _dpapi(json.dumps(box).encode(), True))
        except Exception as e:  # noqa: BLE001
            log.warning('outbox not saved to disk (sent only while the Hub runs): %s', e)


def load_outboxes(data_dir):
    boxes = dict(MEMORY)
    if dpapi_available():
        for p in Path(data_dir).glob('*.outbox'):
            stem = p.stem
            if stem in boxes:
                continue
            try:
                blob = p.read_bytes()
                if blob.startswith(b'FHOUTBOX1'):
                    boxes[stem] = json.loads(_dpapi(blob[9:], False))
            except Exception as e:  # noqa: BLE001
                log.warning('outbox %s unreadable: %s', stem, e)
    return boxes


def _sent_path(data_dir, stem):
    return Path(data_dir) / f'{stem}.sent.json'


def sent_log(data_dir, stem):
    p = _sent_path(data_dir, stem)
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _h(key):
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _mark_sent(data_dir, stem, key, kind, late=False):
    log_ = sent_log(data_dir, stem)
    cutoff = (datetime.now() - timedelta(days=120)).isoformat()
    log_ = {k: v for k, v in log_.items() if v.get('at', '') >= cutoff}
    log_[_h(key)] = {'at': datetime.now().isoformat(timespec='seconds'), 'kind': kind, 'late': late}
    _sent_path(data_dir, stem).write_text(json.dumps(log_))


# ── sending ─────────────────────────────────────────────────────────────────
def send_mail(smtp, to, subject, html, text, factory=None):
    msg = EmailMessage()
    msg['From'] = formataddr(('Finance Hub', smtp['user']))
    msg['To'] = ', '.join(to)
    msg['Subject'] = subject
    msg['Message-ID'] = make_msgid(domain='financehub.local')
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')
    ctx = ssl.create_default_context()
    if factory:
        cli = factory(smtp)
    elif int(smtp['port']) == 465:
        cli = smtplib.SMTP_SSL(smtp['host'], 465, context=ctx, timeout=30)
    else:
        cli = smtplib.SMTP(smtp['host'], int(smtp['port']), timeout=30)
        cli.starttls(context=ctx)
    try:
        cli.login(smtp['user'], smtp['password'])
        cli.send_message(msg)
    finally:
        try:
            cli.quit()
        except Exception:  # noqa: BLE001
            pass


def run_due(data_dir, now=None, factory=None):
    """Send every prepared mail whose time has come (called every minute by the background scheduler). → sent count"""
    now = now or datetime.now()
    sent = 0
    for stem, box in load_outboxes(data_dir).items():
        done = sent_log(data_dir, stem)
        for m in box.get('messages', []):
            if _h(m['key']) in done:
                continue
            at, until = datetime.fromisoformat(m['send_at']), datetime.fromisoformat(m['until'])
            if not (at <= now <= until):
                continue
            f = _FAILS.get((stem, m['key']))
            if f and now < f:
                continue
            try:
                send_mail(box['smtp'], box['to'], m['subject'], m['html'], m['text'], factory)
                _mark_sent(data_dir, stem, m['key'], m['kind'], late=(now - at) > timedelta(hours=1))
                _FAILS.pop((stem, m['key']), None)
                sent += 1
                log.info('sent %s mail (%s)', m['kind'], m['key'].split(':')[1])
            except Exception as e:  # noqa: BLE001
                _FAILS[(stem, m['key'])] = now + timedelta(minutes=15)
                log.warning('could not send %s mail: %s — retrying in 15 minutes', m['kind'], str(e)[:160])
    return sent


def snapshot_con(vault):
    """A private copy of the unlocked database for reading from the scheduler thread."""
    import sqlite3
    with vault.lock:
        if not vault.unlocked:
            return None
        data = vault.con.serialize()
    c = sqlite3.connect(':memory:')
    c.deserialize(data)
    c.row_factory = sqlite3.Row
    return c


def rebuild(con, stem=None):
    stem = stem or VAULT.enc_path.stem
    if APP is not None:
        with APP.test_request_context('/'):            # no Viewing filter: everything counts
            box = build_outbox(con)
    else:
        box = build_outbox(con)
    save_outbox(VAULT.data_dir, stem, box)
    _LAST_BUILD[stem] = time.time()
    return box


def maybe_rebuild(force=False):
    """While unlocked: prepare the mails again when data changed, every hour, and after midnight."""
    if VAULT is None or not VAULT.unlocked:
        return None
    stem = VAULT.enc_path.stem
    last = _LAST_BUILD.get(stem, 0)
    stale = time.time() - last > 3600 or date.fromtimestamp(last) != date.today()
    if not (force or _DIRTY.is_set() or stale):
        return None
    _DIRTY.clear()
    con = snapshot_con(VAULT)
    if con is None:
        return None
    try:
        return rebuild(con, stem)
    finally:
        con.close()


def mark_dirty():
    _DIRTY.set()


def scheduler_loop(stop_event, every=60):
    while not stop_event.wait(every):
        tick()


EXTRA_TICKS = []       # other once-a-minute jobs (the idle lock) — added by other modules


def tick():
    for job in list(EXTRA_TICKS):
        try:
            job()
        except Exception as e:  # noqa: BLE001
            log.warning('background job failed: %s', e)
    try:
        maybe_rebuild()
    except Exception as e:  # noqa: BLE001
        log.warning('preparing reminders failed: %s', e)
    try:
        run_due(VAULT.data_dir)
    except Exception as e:  # noqa: BLE001
        log.warning('sending reminders failed: %s', e)


def start_scheduler(every=60):
    ev = threading.Event()
    threading.Thread(target=scheduler_loop, args=(ev, every), name='hub-reminders', daemon=True).start()
    return ev


# ── page ────────────────────────────────────────────────────────────────────
def register(app, get_db, vault):
    global APP, VAULT
    APP, VAULT = app, vault

    def con_():
        c = get_db()
        ensure_schema(c)
        return c

    def page():
        import mailreader as MR
        con = con_()
        MR.ensure_schema(con)
        s, ms = settings(con), MR.settings(con)
        with app.test_request_context('/'):                  # what will really be sent: no Viewing filter
            box = build_outbox(con)
        stem = VAULT.enc_path.stem
        done = sent_log(VAULT.data_dir, stem)
        upcoming = [m for m in (box or {}).get('messages', []) if _h(m['key']) not in done]
        upcoming.sort(key=lambda m: m['send_at'])
        history = sorted(done.values(), key=lambda v: v.get('at', ''), reverse=True)[:20]
        preview = request.args.get('preview')
        pv = next((m for m in upcoming if m['key'] == preview), None) if preview else None
        if preview == 'weekly-now':
            pv = dict(zip(('subject', 'html', 'text'), weekly_now(con, s['amounts'] == '1')))
        return render_template('reminders.html', s=s, to=recipients(s), smtp=smtp_for(ms, s), mail_ready=bool(ms.get('user') and ms.get('password')),
                               upcoming=upcoming, history=history, pv=pv, DAYS=DAYS, dpapi=dpapi_available(),
                               launcher=bool(app.config.get('HUB_LAUNCHER')))

    def save():
        con = con_()
        f = request.form
        bad = [x for x in re.split(r'[\s,;]+', f.get('recipients', '')) if x.strip() and not EMAIL_RE.match(x.strip())]
        kw = {'recipients': '\n'.join(dict.fromkeys(x.strip().lower() for x in re.split(r'[\s,;]+', f.get('recipients', ''))
                                                     if EMAIL_RE.match(x.strip()))),
              'enabled': '1' if f.get('enabled') else '0', 'remind': '1' if f.get('remind') else '0',
              'weekly': '1' if f.get('weekly') else '0', 'amounts': '1' if f.get('amounts') else '0',
              'remind_time': '%02d:%02d' % _hm(f.get('remind_time'), (9, 0)), 'weekly_time': '%02d:%02d' % _hm(f.get('weekly_time'), (8, 0)),
              'weekly_day': str(int(f.get('weekly_day', '6')) % 7) if f.get('weekly_day', '6').isdigit() else '6',
              'smtp_host': f.get('smtp_host', '').strip()[:100],
              'smtp_port': f.get('smtp_port', '465').strip() if f.get('smtp_port', '465').strip().isdigit() else '465'}
        for k, v in kw.items():
            con.execute('INSERT OR REPLACE INTO notify_settings (key, value) VALUES (?,?)', (k, v))
        con.commit()
        rebuild(con)
        flash('Reminder settings saved.' + (f" Not valid, left out: {', '.join(bad[:3])}." if bad else ''), 'warning' if bad else 'success')
        return redirect(url_for('reminders_page'))

    def test():
        import mailreader as MR
        con = con_()
        s, ms = settings(con), MR.settings(con)
        to = recipients(s)
        smtp = smtp_for(ms, s)
        if not to or not smtp['user'] or not smtp['password'] or not smtp['host']:
            flash('Add at least one address, and set up the Hub mailbox (Settings › Mail inbox) — mails are sent from it.', 'warning')
            return redirect(url_for('reminders_page'))
        subj, html, text = weekly_now(con, s['amounts'] == '1')
        try:
            send_mail(smtp, to, subj.replace('weekly dues report', 'test — dues report'), html, text,
                      app.config.get('HUB_SMTP_FACTORY'))
            flash(f"Test report sent to {', '.join(to)}.", 'success')
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if '535' in msg or 'auth' in msg.lower():
                msg = 'the mail server refused the mailbox address / app password'
            flash(f'Could not send: {msg[:200]}', 'danger')
        return redirect(url_for('reminders_page'))

    for rule, ep, fn, methods in [('/reminders', 'reminders_page', page, ['GET']),
                                  ('/reminders/save', 'reminders_save', save, ['POST']),
                                  ('/reminders/test', 'reminders_test', test, ['POST'])]:
        app.add_url_rule(rule, ep, fn, methods=methods)
