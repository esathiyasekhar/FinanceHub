"""Finance Hub 1.1 — accounts organised by kind, manual accounts, balances, net worth, dues, Home.

Kinds
  bank      savings / current / salary / NRE-NRO / overdraft         (asset)
  card      credit cards                                             (liability: statement outstanding)
  loan      home / personal / gold / vehicle … loans                 (liability: outstanding)
  emi       EMIs on cards and EMI letters (the `loans` table rows not linked to a loan account)
  deposit   FD / RD / PPF / EPF / NPS / bonds …                      (asset: manual value)
  broker    broker & demat accounts (inv_brokers; value from trades × current price)
  wallet    cash, UPI wallets, prepaid / forex cards                 (asset: manual value)
  asset     property, gold, vehicle, money lent …                    (asset: manual value)

Balances come from the latest statement for the account (closing balance / amount due / loan outstanding)
or from a manual entry (account_balances), whichever is newer.
"""
import json
import re
import sqlite3
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, jsonify

KINDS = [  # key, label, short label, icon, colour token, is_asset
    ('bank', 'Bank accounts', 'Banks', 'bi-bank', 'teal', True),
    ('card', 'Credit cards', 'Cards', 'bi-credit-card-2-front', 'coral', False),
    ('loan', 'Loans', 'Loans', 'bi-house-door', 'amber', False),
    ('emi', 'EMIs', 'EMIs', 'bi-calendar2-check', 'violet', False),
    ('deposit', 'Deposits & schemes', 'Deposits', 'bi-safe2', 'indigo', True),
    ('broker', 'Brokers & demat', 'Brokers', 'bi-graph-up-arrow', 'blue', True),
    ('wallet', 'Wallets & cash', 'Wallets', 'bi-cash-coin', 'green', True),
    ('asset', 'Other assets', 'Assets', 'bi-gem', 'pink', True),
]
KIND = {k[0]: {'key': k[0], 'label': k[1], 'short': k[2], 'icon': k[3], 'tone': k[4], 'asset': k[5]} for k in KINDS}
SUBTYPES = {
    'bank': ['Savings', 'Current', 'Salary', 'NRE / NRO', 'Overdraft'],
    'card': ['Credit card', 'Business card', 'Charge card'],
    'loan': ['Home loan', 'Personal loan', 'Gold loan', 'Vehicle loan', 'Education loan', 'Loan against property',
             'Business loan', 'Overdraft / cash credit', 'Other loan'],
    'emi': ['Card EMI', 'Consumer durable EMI', 'Loan on card', 'Other EMI'],
    'deposit': ['Fixed deposit', 'Recurring deposit', 'PPF', 'EPF', 'NPS', 'Sukanya Samriddhi', 'Post office scheme',
                'Bonds / SGB', 'Mutual fund folio', 'Other'],
    'broker': ['Stock broker', 'Mutual fund platform'],
    'wallet': ['Cash in hand', 'UPI wallet', 'Prepaid card', 'Forex card', 'Gift card'],
    'asset': ['Property', 'Gold / jewellery', 'Vehicle', 'Insurance surrender value', 'Business stake',
              'Money lent (receivable)', 'Other'],
}
COLOURS = ['indigo', 'teal', 'coral', 'amber', 'violet', 'blue', 'green', 'pink', 'slate']

ACC_COLUMNS = [('kind', 'TEXT'), ('subtype', 'TEXT'), ('holder', 'TEXT'), ('entity', 'TEXT'), ('ifsc', 'TEXT'),
               ('opening_balance', 'REAL DEFAULT 0'), ('billing_day', 'INTEGER'), ('due_day', 'INTEGER'),
               ('rate', 'REAL'), ('start_date', 'TEXT'), ('maturity_date', 'TEXT'), ('maturity_amount', 'REAL'),
               ('principal', 'REAL'), ('status', "TEXT DEFAULT 'active'"), ('colour', 'TEXT'),
               ('reward_note', 'TEXT'), ('annual_fee', 'REAL'), ('sort_order', 'INTEGER DEFAULT 0')]
SCHEMA = """
CREATE TABLE IF NOT EXISTS account_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, as_of TEXT NOT NULL,
    balance REAL NOT NULL, source TEXT DEFAULT 'manual', note TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_accbal ON account_balances(account_id, as_of);
CREATE TABLE IF NOT EXISTS networth_snapshots (
    day TEXT PRIMARY KEY, assets REAL, liabilities REAL, net REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS hub_settings (key TEXT PRIMARY KEY, value TEXT);
"""
TYPE_FOR = {'card': 'credit_card', 'loan': 'loan', 'deposit': 'deposit', 'wallet': 'wallet', 'asset': 'asset'}


def ensure_schema(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute('PRAGMA table_info(accounts)')}
    for name, decl in ACC_COLUMNS:
        if name not in have:
            con.execute(f'ALTER TABLE accounts ADD COLUMN {name} {decl}')
    backfill_kinds(con)
    con.commit()


def backfill_kinds(con):
    """Accounts created by the importer (or before 1.1) get a kind from their type."""
    con.execute("UPDATE accounts SET kind = CASE WHEN type='credit_card' THEN 'card' WHEN type='loan' THEN 'loan' "
                "WHEN type IN ('deposit','wallet','asset') THEN type ELSE 'bank' END WHERE kind IS NULL OR kind=''")
    con.execute("UPDATE accounts SET subtype = CASE kind WHEN 'card' THEN 'Credit card' "
                "WHEN 'bank' THEN CASE WHEN type='current' THEN 'Current' ELSE 'Savings' END "
                "WHEN 'loan' THEN CASE WHEN lower(name) LIKE '%home%' THEN 'Home loan' WHEN lower(name) LIKE '%gold%' THEN 'Gold loan' "
                "ELSE 'Loan' END ELSE subtype END "
                "WHERE subtype IS NULL OR subtype=''")
    con.execute("UPDATE accounts SET status='active' WHERE status IS NULL OR status=''")


BANK_TONES = [('hdfc', 'blue'), ('icici', 'coral'), ('sbi', 'indigo'), ('state bank', 'indigo'), ('axis', 'pink'),
              ('american express', 'teal'), ('amex', 'teal'), ('standard chartered', 'green'), ('stanchart', 'green'),
              ('south indian', 'amber'), ('sib', 'amber'), ('kotak', 'red'), ('baroda', 'amber'), ('bob', 'amber'),
              ('bank of india', 'violet'), ('central bank', 'teal'), ('idfc', 'red'), ('indusind', 'violet'), ('yes bank', 'blue')]


def bank_tone(text):
    t = (text or '').lower()
    for key, tone in BANK_TONES:
        if re.search(r'\b' + re.escape(key) + r'\b', t):
            return tone
    return COLOURS[sum(map(ord, t)) % 8] if t else 'indigo'


def type_for(kind, subtype=''):
    if kind == 'bank':
        return 'current' if (subtype or '').lower().startswith(('current', 'overdraft')) else 'savings'
    return TYPE_FOR.get(kind, kind)


def _f(v, default=0.0):
    try:
        return float(str(v).replace(',', '').strip()) if v not in (None, '') else default
    except ValueError:
        return default


def _i(v, default=None):
    try:
        return int(float(v)) if v not in (None, '') else default
    except ValueError:
        return default


def _digits(x):
    return re.sub(r'\D', '', x or '')


def parse_day(text):
    """Dates appear as 2026-09-29, 29/09/2026, 'Jul 2026', '2027-01' — return a date or None."""
    t = (text or '').strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d-%b-%Y', '%b %Y', '%Y-%m', '%B %Y'):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def has_day(text):
    """'2026-09-29' / '29/09/2026' name a day; 'Jul 2026' / '2027-01' do not."""
    t = (text or '').strip()
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{4}', t))


def add_months(d, n, day=None):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day or d.day, monthrange(y, m)[1]))


def next_on_day(day, today=None, after_or_on=True):
    """Next date (≥ today) falling on day-of-month `day`."""
    today = today or date.today()
    cand = date(today.year, today.month, min(day, monthrange(today.year, today.month)[1]))
    if cand < today if after_or_on else cand <= today:
        cand = add_months(cand, 1, day)
    return cand


# ── statement figures ───────────────────────────────────────────────────────
def statement_points(con):
    """{account name: [figures …]} newest first; figures from each statement's balance-check rows."""
    acc_rows = con.execute('SELECT name, card_no, type FROM accounts').fetchall()
    out = defaultdict(list)
    for st in con.execute("SELECT * FROM statements ORDER BY COALESCE(NULLIF(period_to,''), statement_date) DESC, id DESC"):
        names = [n.strip() for n in (st['accounts'] or '').split(';') if n.strip()]
        try:
            checks = json.loads(st['check_detail'] or '[]')
        except ValueError:
            checks = []
        as_of = st['period_to'] or st['statement_date'] or ''
        is_card = st['statement_type'] == 'credit_card'
        for a in acc_rows:
            if a['name'] not in names:
                continue
            last4 = _digits(a['card_no'])[-4:]
            hit = next((c for c in checks if last4 and _digits(str(c.get('Account')))[-4:] == last4), None)
            if hit is None and len(names) == 1 and len(checks) <= 1:
                hit = checks[0] if checks else ({'Closing': st['closing_balance']} if is_card else None)
            if hit is None or hit.get('Closing') is None:
                continue
            out[a['name']].append({
                'stmt_id': st['id'], 'closing': _f(hit.get('Closing')), 'as_of': as_of, 'card': is_card,
                'loan': 'loan' in str(hit.get('Type', '')).lower() or a['type'] == 'loan',
                'statement_date': st['statement_date'] or as_of, 'period_from': st['period_from'] or '',
                'due': st['total_due'] if is_card else None, 'due_date': st['due_date'] if is_card else None,
                'min_due': st['minimum_due'] if is_card else None,
                'limit': st['credit_limit'] if is_card else None,
                'rate': _f(hit.get('ROI %')) or None,
                'check': hit.get('Check') or st['check_status'], 'file': st['file_name']})
    return out


def manual_points(con):
    out = defaultdict(list)
    for r in con.execute('SELECT * FROM account_balances ORDER BY as_of DESC, id DESC'):
        out[r['account_id']].append(dict(r))
    return out


def credits_since(con, account, after):
    """Payments into a card account after its statement date (to see whether the bill is paid)."""
    return con.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account=? AND type='credit' AND date>?",
                       (account, after)).fetchone()[0] or 0


# ── brokers ──────────────────────────────────────────────────────────────────
def broker_rows(con):
    rows = []
    try:
        import investments as inv
        secs = {r['id']: r for r in con.execute('SELECT * FROM inv_securities')}
        hold = inv.latest_holdings(con)
        for b in con.execute('SELECT * FROM inv_brokers ORDER BY name'):
            pos = inv.positions(con, b['id'])
            value = invested = 0.0
            stocks = 0
            for sid, p in pos.items():
                if p['qty'] <= 0.0001:
                    continue
                s = secs.get(sid)
                h = hold.get(sid)
                cmp_ = (s['cmp'] if s and s['cmp'] else None) or (h['close'] if h and h.get('close') else None) or p['avg']
                value += p['qty'] * cmp_
                invested += p['qty'] * p['avg']
                stocks += 1
            n, last = con.execute('SELECT COUNT(*), MAX(trade_date) FROM inv_trades WHERE broker_id=?', (b['id'],)).fetchone()
            rows.append({**dict(b), 'kind': 'broker', 'form': {'id': b['id'], 'kind': 'broker', 'name': b['name'],
                         'client_id': b['client_id'], 'demat_id': b['demat_id'], 'notes': b['notes']}, 'value': value, 'invested': invested, 'pnl': value - invested,
                         'stocks': stocks, 'trades': n, 'last_trade': last or ''})
    except sqlite3.OperationalError:
        pass
    return rows


# ── loans / EMIs ─────────────────────────────────────────────────────────────
def loan_view(r, today=None):
    """Computed figures for a `loans` row."""
    today = today or date.today()
    d = dict(r)
    total, paid = d.get('total_emis') or 0, d.get('emis_paid') or 0
    remaining = max(total - paid, 0)
    out = d.get('outstanding') or 0
    if not out and d.get('status') == 'active':
        out = (d.get('emi_amount') or 0) * remaining
    d['remaining'] = remaining
    d['outstanding_now'] = out if d.get('status') == 'active' else 0
    d['progress'] = round(100 * paid / total) if total else 0
    first = parse_day(d.get('first_emi_date'))
    last = parse_day(d.get('last_emi_date'))
    d['bullet'] = (d.get('repayment') == 'bullet')
    nxt = None
    if d.get('status') == 'active':
        if d['bullet']:
            nxt = last
        elif first and has_day(d.get('first_emi_date')):   # a real day of month is known
            nxt = next_on_day(first.day, today)
            if first > today:
                nxt = first
    d['next_due'] = nxt
    d['end'] = last
    if not last and first and total:
        d['end'] = add_months(first, total - 1)
    d['monthly'] = 0 if d['bullet'] or d.get('status') != 'active' else (d.get('emi_amount') or 0)
    return d


# ── the whole picture ────────────────────────────────────────────────────────
def build(con, fy_start=None, fy_end=None, include_closed=True, ignore_scope=False):
    """Every account with its current figures, grouped by kind, plus totals for net worth."""
    backfill_kinds(con)
    today = date.today()
    spts = statement_points(con)
    mpts = manual_points(con)
    stats = {}
    if fy_start:
        for r in con.execute("SELECT account, SUM(CASE WHEN type='debit' THEN amount ELSE 0 END), "
                             "SUM(CASE WHEN type='credit' THEN amount ELSE 0 END), COUNT(*), MAX(date), "
                             "COALESCE(SUM(reward_pts),0) FROM transactions WHERE date>=? AND date<=? GROUP BY account",
                             (fy_start, fy_end)):
            stats[r[0]] = {'out': r[1] or 0, 'in': r[2] or 0, 'count': r[3], 'last': r[4], 'points': r[5]}
    loans = [loan_view(r, today) for r in con.execute('SELECT * FROM loans ORDER BY status, purchase_date')]
    import scope as SC
    all_accts = [dict(r) for r in con.execute('SELECT * FROM accounts ORDER BY sort_order, name')]
    accts = [a for a in all_accts if SC.account_in_scope(a)] if (SC.active() and not ignore_scope) else all_accts
    kind_by_name = {a['name']: a['kind'] for a in all_accts}
    in_view = {a['name'] for a in accts}
    if SC.active() and not ignore_scope:
        loans = [l for l in loans if l.get('card') in in_view or (not l.get('card') and SC.current()['book'] in ('', 'Personal'))]
    groups = {k: [] for k in KIND}
    for a in accts:
        k = a['kind'] if a['kind'] in KIND else 'bank'
        a['stat'] = stats.get(a['name'], {'out': 0, 'in': 0, 'count': 0, 'last': None, 'points': 0})
        sp = spts.get(a['name'], [])
        mp = mpts.get(a['id'], [])
        a['stmt'] = sp[0] if sp else None
        a['manual'] = mp[0] if mp else None
        a['stmt_count'] = len(sp)
        # current balance: newest of statement / manual entry
        cand = []
        if sp:
            cand.append((sp[0]['as_of'] or '', sp[0]['closing'], 'statement'))
        if mp:
            cand.append((mp[0]['as_of'] or '', mp[0]['balance'], 'manual'))
        cand.sort(reverse=True)
        a['balance'], a['as_of'], a['source'] = (cand[0][1], cand[0][0], cand[0][2]) if cand else (None, '', '')
        a['last4'] = _digits(a['card_no'])[-4:]
        a['tone'] = a['colour'] or (bank_tone(a['bank'] or a['name']) if k in ('card', 'bank') else KIND[k]['tone'])
        a['linked'] = [l for l in loans if l.get('card') == a['name']]
        a['stale_days'] = (today - parse_day(a['as_of'])).days if parse_day(a['as_of']) else None
        if k == 'card':
            st = a['stmt']
            limit = (st['limit'] if st and st['limit'] else 0) or a['credit_limit'] or 0
            a['limit'] = limit
            a['outstanding'] = a['balance'] or 0
            a['util'] = round(100 * a['outstanding'] / limit, 1) if limit else None
            a['available'] = max(limit - a['outstanding'], 0) if limit else None
            a['emi_out'] = sum(l['outstanding_now'] for l in a['linked'])
            sd = parse_day(st['statement_date']) if st else None
            dd = parse_day(st['due_date']) if st and st['due_date'] else None
            a['billing_day_eff'] = a['billing_day'] or (sd.day if sd else None)
            a['grace'] = (dd - sd).days if sd and dd else None
            if a['due_day']:
                a['due_day_eff'] = a['due_day']
            else:
                a['due_day_eff'] = dd.day if dd else None
            a['bill'] = None
            if st and st['due']:
                paid = credits_since(con, a['name'], st['statement_date'] or st['as_of'])
                due_amt = st['due'] or 0
                left = max(due_amt - paid, 0)
                status = 'paid' if left <= 1 else ('part' if paid > 0 else 'due')
                if status != 'paid' and dd and dd < today:
                    # overdue only when the Hub has this card's data beyond the due date; otherwise the payment
                    # simply is not in the Hub yet (next statement not added) → ask to confirm
                    later = con.execute('SELECT MAX(date) FROM transactions WHERE account=?', (a['name'],)).fetchone()[0]
                    status = 'overdue' if later and later > dd.isoformat() else 'check'
                a['bill'] = {'due': due_amt, 'min': st['min_due'] or 0, 'due_date': dd, 'paid': paid, 'left': left,
                             'status': status, 'statement_date': sd}
        elif k == 'loan':
            ln = a['linked'][0] if a['linked'] else None
            a['loan'] = ln
            out = None
            if ln:
                out = ln['outstanding_now']
                if a['balance'] is not None and a['as_of'] >= (ln.get('last_statement_date') or ''):
                    out = abs(a['balance'])
            elif a['balance'] is not None:
                out = abs(a['balance'])
            a['outstanding'] = out or 0
            a['rate_eff'] = a['rate'] or (ln['interest_rate'] if ln else None) or (a['stmt']['rate'] if a['stmt'] else None)
        elif k in ('deposit', 'wallet', 'asset', 'bank'):
            if a['balance'] is None and a['opening_balance']:
                a['balance'], a['source'] = a['opening_balance'], 'opening'
            if k == 'deposit':
                md = parse_day(a['maturity_date'])
                a['maturity'] = md
                a['days_to_maturity'] = (md - today).days if md else None
                if not a['maturity_amount'] and a['principal'] and a['rate'] and md and a['start_date']:
                    sd = parse_day(a['start_date'])
                    if sd and md > sd:   # quarterly compounding (bank FD convention)
                        yrs = (md - sd).days / 365.0
                        a['maturity_est'] = a['principal'] * (1 + a['rate'] / 400) ** (4 * yrs)
        groups[k].append(a)
    for k, xs in groups.items():
        for a in xs:
            a['form'] = account_form(a, k)
    # EMIs = loans rows not attached to a loan account
    emis = [l for l in loans if kind_by_name.get(l.get('card')) != 'loan']
    for l in emis:
        l['on_card'] = kind_by_name.get(l.get('card')) == 'card'
        l['form'] = emi_form(l)
    # loan accounts never linked → still listed; loans rows whose 'card' is a loan account show inside the account
    brokers = broker_rows(con)
    if SC.active() and not ignore_scope:
        c = SC.current()
        brokers = [b for b in brokers if str(b['id']) == c['broker']] if c['broker'] else \
            (brokers if c['book'] in ('Personal',) and not c['account'] else [])

    def active(xs):
        return [x for x in xs if (x.get('status') or 'active') == 'active']

    totals = {
        'bank': sum(a['balance'] or 0 for a in active(groups['bank'])),
        'card': sum(a.get('outstanding') or 0 for a in active(groups['card'])),
        'loan': sum(a.get('outstanding') or 0 for a in active(groups['loan'])),
        'emi': sum(l['outstanding_now'] for l in emis if l.get('status') == 'active'),
        'deposit': sum(a['balance'] or 0 for a in active(groups['deposit'])),
        'broker': sum(b['value'] for b in brokers),
        'wallet': sum(a['balance'] or 0 for a in active(groups['wallet'])),
        'asset': sum(a['balance'] or 0 for a in active(groups['asset'])),
    }
    counts = {k: len(active(groups[k])) for k in KIND}
    counts['emi'] = sum(1 for l in emis if l.get('status') == 'active')
    counts['broker'] = len(brokers)
    assets = sum(totals[k] for k in KIND if KIND[k]['asset'])
    liabilities = sum(totals[k] for k in KIND if not KIND[k]['asset'])
    monthly_emi = sum(l['monthly'] for l in loans)
    return {'groups': groups, 'emis': emis, 'loans': loans, 'brokers': brokers, 'totals': totals, 'counts': counts,
            'assets': assets, 'liabilities': liabilities, 'net': assets - liabilities, 'monthly_emi': monthly_emi,
            'closed': [a for a in accts if (a.get('status') or 'active') != 'active'], 'today': today}


FORM_FIELDS = ('id', 'name', 'subtype', 'bank', 'card_no', 'holder', 'entity', 'ifsc', 'credit_limit', 'billing_day', 'due_day',
               'rate', 'start_date', 'maturity_date', 'maturity_amount', 'principal', 'opening_balance', 'colour',
               'reward_note', 'annual_fee', 'notes')


def account_form(a, kind):
    """Plain values to pre-fill the add / edit form (JSON-safe)."""
    f = {k: a.get(k) for k in FORM_FIELDS}
    f['kind'] = kind
    ln = a['linked'][0] if kind == 'loan' and a.get('linked') else None
    if ln:
        f.update({'emi_amount': ln.get('emi_amount'), 'total_emis': ln.get('total_emis'), 'emis_paid': ln.get('emis_paid'),
                  'first_emi_date': ln.get('first_emi_date'), 'outstanding': ln.get('outstanding'), 'bullet': ln['bullet']})
        if not f['rate']:
            f['rate'] = ln.get('interest_rate')
        if not f['principal']:
            f['principal'] = ln.get('original_amount')
        if not f['maturity_date']:
            f['maturity_date'] = ln.get('last_emi_date')
    return f


def emi_form(l):
    return {'id': l['id'], 'kind': 'emi', 'name': l.get('name'), 'bank': l.get('lender'), 'card': l.get('card'),
            'purchase_desc': l.get('purchase_desc'), 'start_date': l.get('purchase_date'), 'principal': l.get('original_amount'),
            'emi_amount': l.get('emi_amount'), 'total_emis': l.get('total_emis'), 'emis_paid': l.get('emis_paid'),
            'first_emi_date': l.get('first_emi_date'), 'maturity_date': l.get('last_emi_date'), 'rate': l.get('interest_rate'),
            'outstanding': l.get('outstanding'), 'notes': l.get('notes'), 'subtype': 'Card EMI'}


def record_snapshot(con, b, force=False):
    """One net-worth snapshot per day (the latest figure of the day wins)."""
    day = date.today().isoformat()
    detail = json.dumps({k: round(v, 2) for k, v in b['totals'].items()})
    con.execute('INSERT INTO networth_snapshots (day, assets, liabilities, net, detail) VALUES (?,?,?,?,?) '
                'ON CONFLICT(day) DO UPDATE SET assets=excluded.assets, liabilities=excluded.liabilities, '
                'net=excluded.net, detail=excluded.detail', (day, b['assets'], b['liabilities'], b['net'], detail))
    con.commit()


def history(con, limit=400):
    rows = [dict(r) for r in con.execute('SELECT * FROM networth_snapshots ORDER BY day DESC LIMIT ?', (limit,))]
    return list(reversed(rows))


# ── dues ─────────────────────────────────────────────────────────────────────
def dues(con, b=None, start=None, days=30, recurring=None):
    """Money going out (and big inflows) between start and start+days."""
    b = b or build(con)
    today = date.today()
    start = start or today
    end = start + timedelta(days=days)
    ev = []
    for a in b['groups']['card']:
        if (a.get('status') or 'active') != 'active':
            continue
        bill = a.get('bill')
        if bill and bill['due_date'] and (bill['status'] != 'paid' or start <= bill['due_date'] <= end):
            if bill['due_date'] <= end and (bill['due_date'] >= start - timedelta(days=45) or bill['status'] != 'paid'):
                label = {'paid': 'paid', 'due': 'due', 'part': 'part paid', 'overdue': 'overdue',
                         'check': 'payment not seen yet'}[bill['status']]
                ev.append({'date': bill['due_date'], 'title': f"{a['name']} bill", 'amount': bill['left'] if bill['status'] != 'paid' else bill['due'],
                           'full': bill['due'], 'min': bill['min'], 'kind': 'card', 'status': label, 'state': bill['status'],
                           'cash': bill['status'] in ('due', 'part', 'overdue'), 'account_id': a['id'], 'icon': 'bi-credit-card-2-front'})
        # projected next bill when only the billing / due days are known
        if a['due_day_eff'] and (not bill or not bill['due_date'] or bill['due_date'] < start):
            nd = next_on_day(a['due_day_eff'], max(start, today))
            if nd <= end and not (bill and bill['due_date'] and bill['due_date'] >= nd - timedelta(days=10)):
                ev.append({'date': nd, 'title': f"{a['name']} bill (expected)", 'amount': None, 'kind': 'card',
                           'status': 'expected', 'cash': False, 'account_id': a['id'], 'icon': 'bi-credit-card-2-front'})
    for l in b['loans']:
        if l.get('status') != 'active':
            continue
        acct = next((a for a in b['groups']['loan'] if a['name'] == l.get('card')), None)
        on_card = any(a['name'] == l.get('card') for a in b['groups']['card'])
        if l['bullet']:
            if l['next_due'] and start <= l['next_due'] <= end:
                ev.append({'date': l['next_due'], 'title': f"{l['name']} repayment (bullet)", 'amount': l['outstanding_now'],
                           'kind': 'loan', 'status': 'due', 'cash': True, 'account_id': acct['id'] if acct else None,
                           'icon': 'bi-hourglass-split'})
            continue
        if not l['next_due']:
            continue
        first = parse_day(l['first_emi_date'])
        day = first.day if first and has_day(l['first_emi_date']) else l['next_due'].day
        last = l['end']
        d = date(start.year, start.month, min(day, monthrange(start.year, start.month)[1]))   # every EMI date in the window
        if d < start:
            d = add_months(d, 1, day)
        while d <= end:
            if d >= start and (not first or d >= first) and (not last or d <= last + timedelta(days=3)) \
                    and (d >= today or l['remaining'] > 0):
                ev.append({'date': d, 'title': f"{l['name']} EMI", 'amount': l['emi_amount'], 'kind': 'emi' if not acct else 'loan',
                           'status': 'on card bill' if on_card else 'auto-debit', 'cash': not on_card,
                           'account_id': acct['id'] if acct else None, 'loan_id': l['id'], 'icon': 'bi-calendar2-check'})
            d = add_months(d, 1, day)
    for a in b['groups']['deposit']:
        if (a.get('status') or 'active') == 'active' and a.get('maturity') and start <= a['maturity'] <= end:
            ev.append({'date': a['maturity'], 'title': f"{a['name']} matures", 'amount': a['maturity_amount'] or a.get('maturity_est') or a['balance'],
                       'kind': 'deposit', 'status': 'inflow', 'cash': False, 'inflow': True, 'account_id': a['id'], 'icon': 'bi-safe2'})
    for r in (recurring or []):
        d = r.get('next')
        bank_paid = r.get('account_kind') not in ('card',)
        if d and r.get('back'):
            guard = 0
            while d > start and guard < 400:      # step back to the first occurrence in the window
                d = r['back'](d)
                guard += 1
        while d and d <= end:
            if d >= start:
                ev.append({'date': d, 'title': r['name'], 'amount': r['amount'], 'kind': 'recurring',
                           'status': r['freq_label'], 'cash': bank_paid, 'icon': 'bi-arrow-repeat', 'recurring_id': r['id']})
            d = r['step'](d) if r.get('step') else None
    ev.sort(key=lambda e: (e['date'], e['title']))
    return ev


def cash_position(b, ev):
    need = sum((e['amount'] or 0) for e in ev if e.get('cash') and not e.get('inflow'))
    banks = [a for a in b['groups']['bank'] if (a.get('status') or 'active') == 'active' and a['balance'] is not None]
    have = sum(a['balance'] for a in banks)
    oldest = min((a['as_of'] for a in banks if a['as_of']), default='')
    return {'need': need, 'have': have, 'gap': have - need, 'as_of': oldest,
            'pct': min(100, round(100 * need / have)) if have > 0 else 100}


def month_grid(year, month, ev):
    """Weeks (Mon–Sun) of a month with that day's events."""
    by_day = defaultdict(list)
    for e in ev:
        by_day[e['date']].append(e)
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    weeks, d = [], start
    while True:
        week = []
        for _ in range(7):
            week.append({'date': d, 'in_month': d.month == month, 'events': by_day.get(d, [])})
            d += timedelta(days=1)
        weeks.append(week)
        if d.month != month and d > first:
            break
    return weeks


# ── routes ───────────────────────────────────────────────────────────────────
def register(app, get_db):

    def con_():
        return get_db()

    def fy_bounds():
        today = date.today()
        y = today.year if today.month >= 4 else today.year - 1
        p = request.args.get('fy', '')
        m = re.fullmatch(r'(\d{2})-(\d{2})', p)
        if m:
            y = 2000 + int(m.group(1))
        return f'{y}-04-01', f'{y + 1}-03-31', f'FY {str(y)[-2:]}-{str(y + 1)[-2:]}', f'{str(y)[-2:]}-{str(y + 1)[-2:]}'

    def accounts():
        con = con_()
        tab = request.args.get('tab', 'all')
        if tab not in KIND and tab not in ('all', 'closed'):
            tab = 'all'
        fs, fe, fl, fp = fy_bounds()
        b = build(con, fs, fe)
        record_snapshot(con, b)
        cards = [a for a in b['groups']['card'] if a['status'] == 'active']
        fy_opts = []
        today = date.today()
        y0 = today.year if today.month >= 4 else today.year - 1
        for y in range(y0, y0 - 4, -1):
            fy_opts.append((f'FY {str(y)[-2:]}-{str(y + 1)[-2:]}', f'{str(y)[-2:]}-{str(y + 1)[-2:]}'))
        entities = [r[0] for r in con.execute("SELECT name FROM entities WHERE COALESCE(role,'book')='book' ORDER BY name<>'Personal', sort_order, name")]
        people = [r[0] for r in con.execute('SELECT name FROM people ORDER BY name')]
        return render_template('accounts.html', b=b, tab=tab, KINDS=KIND, kinds=[k[0] for k in KINDS],
                               SUBTYPES=SUBTYPES, COLOURS=COLOURS, fy_label=fl, fy_param=fp, fy_opts=fy_opts,
                               sel_start=fs, sel_end=fe, card_names=[a['name'] for a in cards],
                               entities=entities, people=people, today=today)

    def account_detail(acc_id):
        con = con_()
        a = con.execute('SELECT * FROM accounts WHERE id=?', (acc_id,)).fetchone()
        if not a:
            flash('Account not found.', 'warning')
            return redirect(url_for('accounts'))
        fs, fe, fl, fp = fy_bounds()
        b = build(con, fs, fe)
        acc = next(x for k in KIND for x in b['groups'][k] if x['id'] == acc_id)
        pts = [{'as_of': p['as_of'], 'value': p['closing'], 'source': 'statement', 'note': p['file']}
               for p in statement_points(con).get(acc['name'], [])]
        pts += [{'as_of': p['as_of'], 'value': p['balance'], 'source': 'manual', 'note': p['note'] or '', 'id': p['id']}
                for p in manual_points(con).get(acc_id, [])]
        pts.sort(key=lambda p: p['as_of'], reverse=True)
        txns = con.execute('SELECT t.*, c.name AS cat FROM transactions t LEFT JOIN categories c ON c.id=t.category_id '
                           'WHERE t.account=? ORDER BY t.date DESC, t.id DESC LIMIT 25', (acc['name'],)).fetchall()
        monthly = con.execute("SELECT substr(date,1,7) m, SUM(CASE WHEN type='debit' THEN amount ELSE 0 END), "
                              "SUM(CASE WHEN type='credit' THEN amount ELSE 0 END) FROM transactions WHERE account=? "
                              "GROUP BY 1 ORDER BY 1 DESC LIMIT 12", (acc['name'],)).fetchall()
        stmts = con.execute("SELECT id, file_name, period_from, period_to, statement_date, check_status, txn_imported "
                            "FROM statements WHERE ('; ' || accounts || ';') LIKE ? ORDER BY statement_date DESC",
                            (f'%; {acc["name"]};%',)).fetchall()
        entities = [r[0] for r in con.execute("SELECT name FROM entities WHERE COALESCE(role,'book')='book' ORDER BY name<>'Personal', sort_order, name")]
        people = [r[0] for r in con.execute('SELECT name FROM people ORDER BY name')]
        cards = [x['name'] for x in b['groups']['card'] if x['status'] == 'active']
        return render_template('account_detail.html', a=acc, KINDS=KIND, kind=KIND[acc['kind'] if acc['kind'] in KIND else 'bank'],
                               points=pts, txns=txns, monthly=list(reversed(monthly)), stmts=stmts, fy_label=fl,
                               sel_start=fs, sel_end=fe, SUBTYPES=SUBTYPES, COLOURS=COLOURS, kinds=[k[0] for k in KINDS],
                               entities=entities, people=people, card_names=cards, today=date.today(),
                               chart=json.dumps([{'x': p['as_of'], 'y': round(abs(p['value']), 2)} for p in reversed(pts) if p['as_of']]))

    def _back(default_tab):
        nxt = request.form.get('next') or ''
        if nxt.startswith('/'):
            return redirect(nxt)
        return redirect(url_for('accounts', tab=default_tab))

    def account_save():
        con = con_()
        f = request.form
        kind = f.get('kind', 'bank')
        if kind == 'emi':
            return _save_emi(con, f)
        if kind == 'broker':
            return _save_broker(con, f)
        if kind not in KIND:
            kind = 'bank'
        name = re.sub(r'\s+', ' ', f.get('name', '')).strip()
        if not name:
            flash('Give the account a name.', 'warning')
            return _back(kind)
        subtype = f.get('subtype', '')
        vals = {
            'name': name, 'kind': kind, 'subtype': subtype, 'type': type_for(kind, subtype),
            'bank': f.get('bank', '').strip(), 'card_no': f.get('card_no', '').strip(), 'holder': f.get('holder', '').strip(),
            'entity': f.get('entity', '').strip(), 'ifsc': f.get('ifsc', '').strip().upper(),
            'credit_limit': _f(f.get('credit_limit')), 'billing_day': _i(f.get('billing_day')), 'due_day': _i(f.get('due_day')),
            'rate': _f(f.get('rate'), None), 'start_date': f.get('start_date', ''), 'maturity_date': f.get('maturity_date', ''),
            'maturity_amount': _f(f.get('maturity_amount'), None), 'principal': _f(f.get('principal'), None),
            'opening_balance': _f(f.get('opening_balance')), 'colour': f.get('colour', '') or None,
            'reward_note': f.get('reward_note', '').strip(), 'annual_fee': _f(f.get('annual_fee'), None),
            'notes': f.get('notes', '').strip(),
        }
        acc_id = _i(f.get('id'))
        try:
            if acc_id:
                old = con.execute('SELECT * FROM accounts WHERE id=?', (acc_id,)).fetchone()
                if not old:
                    flash('Account not found.', 'warning')
                    return _back(kind)
                con.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in vals)} WHERE id=?", (*vals.values(), acc_id))
                if old['name'] != name:
                    rename_account(con, old['name'], name)
                if (old['entity'] or 'Personal') != (vals['entity'] or 'Personal'):
                    # 1.2: an account moved to another book takes its (not hand-edited) transactions along
                    con.execute("UPDATE transactions SET entity=? WHERE account=? AND COALESCE(manual,0)=0",
                                (vals['entity'] or 'Personal', name))
                msg = f'Saved {name}.'
            else:
                cur = con.execute(f"INSERT INTO accounts ({', '.join(vals)}, status) VALUES ({', '.join('?' * len(vals))}, 'active')",
                                  tuple(vals.values()))
                acc_id = cur.lastrowid
                msg = f'Added {name}.'
            bal = f.get('balance', '').strip()
            if bal:
                con.execute('INSERT INTO account_balances (account_id, as_of, balance, source, note) VALUES (?,?,?,?,?)',
                            (acc_id, f.get('balance_date') or date.today().isoformat(), _f(bal), 'manual', 'entered when saving'))
            if kind == 'loan':
                _save_loan_row(con, f, name)
            con.commit()
            flash(msg, 'success')
        except sqlite3.IntegrityError:
            con.rollback()
            flash(f'An account called “{name}” already exists — choose another name.', 'warning')
        return _back(kind)

    def _save_loan_row(con, f, name):
        """A loan account keeps its EMI schedule in the loans table (shared with statement imports)."""
        row = con.execute('SELECT * FROM loans WHERE card=? ORDER BY id LIMIT 1', (name,)).fetchone()
        emi, total, paid = _f(f.get('emi_amount')), _i(f.get('total_emis'), 0), _i(f.get('emis_paid'), 0)
        out = _f(f.get('outstanding'), None)
        if not (emi or total or out is not None or row):
            return
        data = {'emi_amount': emi, 'total_emis': total, 'emis_paid': paid, 'first_emi_date': f.get('first_emi_date', ''),
                'interest_rate': _f(f.get('rate')), 'original_amount': _f(f.get('principal')),
                'repayment': 'bullet' if f.get('bullet') else 'monthly', 'lender': f.get('bank', ''),
                'last_emi_date': f.get('maturity_date', '')}
        if out is not None:
            data['outstanding'] = out
        if row:
            con.execute(f"UPDATE loans SET {', '.join(k + '=?' for k in data)} WHERE id=?", (*data.values(), row['id']))
        else:
            data.update({'name': name, 'card': name, 'status': 'active', 'source': 'manual',
                         'purchase_date': f.get('start_date', ''), 'purchase_desc': f.get('subtype', '')})
            con.execute(f"INSERT INTO loans ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))

    def _save_emi(con, f):
        lid = _i(f.get('id'))
        data = {'name': f.get('name', '').strip() or 'EMI', 'lender': f.get('bank', '').strip(), 'card': f.get('card', '').strip(),
                'purchase_desc': f.get('purchase_desc', '').strip() or f.get('subtype', ''), 'purchase_date': f.get('start_date', ''),
                'original_amount': _f(f.get('principal')), 'emi_amount': _f(f.get('emi_amount')),
                'total_emis': _i(f.get('total_emis'), 0), 'emis_paid': _i(f.get('emis_paid'), 0),
                'first_emi_date': f.get('first_emi_date', ''), 'last_emi_date': f.get('maturity_date', ''),
                'interest_rate': _f(f.get('rate')), 'notes': f.get('notes', '').strip()}
        out = _f(f.get('outstanding'), None)
        if out is not None:
            data['outstanding'] = out
        if lid:
            con.execute(f"UPDATE loans SET {', '.join(k + '=?' for k in data)} WHERE id=?", (*data.values(), lid))
            flash(f"Saved {data['name']}.", 'success')
        else:
            data.update({'status': 'active', 'source': 'manual', 'repayment': 'monthly'})
            con.execute(f"INSERT INTO loans ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))
            flash(f"Added EMI {data['name']}.", 'success')
        con.execute("UPDATE loans SET status = CASE WHEN total_emis>0 AND emis_paid>=total_emis THEN 'paid' ELSE 'active' END "
                    "WHERE id = COALESCE(?, last_insert_rowid()) AND status IN ('active','paid')", (lid,))
        con.commit()
        return _back('emi')

    def _save_broker(con, f):
        bid = _i(f.get('id'))
        name = f.get('name', '').strip()
        if not name:
            flash('Give the broker a name.', 'warning')
            return _back('broker')
        try:
            if bid:
                con.execute('UPDATE inv_brokers SET name=?, client_id=?, demat_id=?, notes=? WHERE id=?',
                            (name, f.get('client_id', ''), f.get('demat_id', ''), f.get('notes', ''), bid))
            else:
                con.execute('INSERT INTO inv_brokers (name, client_id, demat_id, notes) VALUES (?,?,?,?)',
                            (name, f.get('client_id', ''), f.get('demat_id', ''), f.get('notes', '')))
            con.commit()
            flash(f'Saved broker {name}.', 'success')
        except sqlite3.IntegrityError:
            flash(f'A broker called “{name}” already exists.', 'warning')
        return _back('broker')

    def account_balance(acc_id):
        con = con_()
        bal = request.form.get('balance', '').strip()
        if bal == '':
            flash('Enter a balance.', 'warning')
        else:
            con.execute('INSERT INTO account_balances (account_id, as_of, balance, source, note) VALUES (?,?,?,?,?)',
                        (acc_id, request.form.get('as_of') or date.today().isoformat(), _f(bal), 'manual',
                         request.form.get('note', '').strip()))
            con.commit()
            flash('Balance updated.', 'success')
        return _back('all')

    def balance_delete(bal_id):
        con = con_()
        con.execute('DELETE FROM account_balances WHERE id=?', (bal_id,))
        con.commit()
        flash('Balance entry removed.', 'info')
        return _back('all')

    def account_status(acc_id):
        con = con_()
        st = 'closed' if request.form.get('action') == 'close' else 'active'
        con.execute('UPDATE accounts SET status=? WHERE id=?', (st, acc_id))
        con.commit()
        flash('Account closed — it stays in history and reports.' if st == 'closed' else 'Account re-opened.', 'info')
        return _back('all')

    def account_delete(acc_id):
        con = con_()
        a = con.execute('SELECT name FROM accounts WHERE id=?', (acc_id,)).fetchone()
        if not a:
            return _back('all')
        n = con.execute('SELECT COUNT(*) FROM transactions WHERE account=?', (a['name'],)).fetchone()[0]
        if n:
            flash(f'{a["name"]} has {n} transactions — close it instead of deleting.', 'warning')
            return _back('all')
        con.execute('DELETE FROM account_balances WHERE account_id=?', (acc_id,))
        con.execute('DELETE FROM accounts WHERE id=?', (acc_id,))
        con.commit()
        flash(f'Deleted {a["name"]}.', 'info')
        return redirect(url_for('accounts'))

    def broker_delete(bid):
        con = con_()
        n = con.execute('SELECT COUNT(*) FROM inv_trades WHERE broker_id=?', (bid,)).fetchone()[0]
        if n:
            flash(f'This broker has {n} trades — it cannot be deleted.', 'warning')
        else:
            con.execute('DELETE FROM inv_brokers WHERE id=?', (bid,))
            con.commit()
            flash('Broker removed.', 'info')
        return redirect(url_for('accounts', tab='broker'))

    def networth_page():
        con = con_()
        b = build(con)
        record_snapshot(con, b)
        hist = history(con)
        return render_template('networth.html', b=b, KINDS=KIND, kinds=[k[0] for k in KINDS], hist=hist,
                               hist_json=json.dumps([{'d': h['day'], 'a': round(h['assets']), 'l': round(h['liabilities']),
                                                      'n': round(h['net'])} for h in hist]))

    def dues_page():
        con = con_()
        import planning
        today = date.today()
        ym = request.args.get('m', today.strftime('%Y-%m'))
        try:
            y, m = map(int, ym.split('-'))
            date(y, m, 1)
        except ValueError:
            y, m = today.year, today.month
        b = build(con)
        rec = planning.recurring_for_dues(con, b)
        first = date(y, m, 1)
        last = date(y, m, monthrange(y, m)[1])
        ev = dues(con, b, start=first, days=(last - first).days, recurring=rec)
        upcoming = dues(con, b, start=today, days=30, recurring=rec)
        cash = cash_position(b, upcoming)
        prev_m = (first - timedelta(days=1)).strftime('%Y-%m')
        next_m = (last + timedelta(days=1)).strftime('%Y-%m')
        return render_template('dues.html', weeks=month_grid(y, m, ev), month_label=first.strftime('%B %Y'), ev=ev,
                               upcoming=upcoming, cash=cash, prev_m=prev_m, next_m=next_m, today=today, b=b,
                               this_m=today.strftime('%Y-%m'), sel_m=f'{y}-{m:02d}')

    def home():
        con = con_()
        import planning
        import organise
        today = date.today()
        b = build(con)
        record_snapshot(con, b)
        rec = planning.recurring_for_dues(con, b)
        upcoming = dues(con, b, start=today, days=30, recurring=rec)
        cash = cash_position(b, upcoming)
        hist = history(con, 120)
        prev = next((h for h in reversed(hist) if h['day'] <= (today - timedelta(days=28)).isoformat()), hist[0] if hist else None)
        m_start = today.replace(day=1)
        latest = con.execute("SELECT MAX(date) FROM transactions").fetchone()[0]
        flow_month = m_start
        if latest and latest < m_start.isoformat():
            flow_month = parse_day(latest[:7] + '-01') or m_start
        fm_end = add_months(flow_month, 1, 1)
        d = organise.dashboard_data(con, f"date >= '{flow_month.isoformat()}' AND date < '{fm_end.isoformat()}'",
                                    f"date >= '{add_months(flow_month, -5, 1).isoformat()}' AND date < '{fm_end.isoformat()}'")
        alerts = planning.alerts(con, b, upcoming, cash)
        budgets = planning.budget_rows(con, flow_month)
        close = planning.month_close_status(con, b, add_months(today.replace(day=1), -1, 1))
        util = [a for a in b['groups']['card'] if a['status'] == 'active' and a.get('util') is not None]
        tot_limit = sum(a['limit'] for a in util)
        tot_out = sum(a['outstanding'] for a in util)
        return render_template('home.html', b=b, KINDS=KIND, kinds=[k[0] for k in KINDS], upcoming=upcoming[:12],
                               n_upcoming=len(upcoming), cash=cash, prev=prev, d=d, flow_label=flow_month.strftime('%B %Y'),
                               alerts=alerts, budgets=budgets[:6], close=close, today=today,
                               util_all=round(100 * tot_out / tot_limit, 1) if tot_limit else None,
                               hist_json=json.dumps([{'d': h['day'], 'n': round(h['net']), 'a': round(h['assets']),
                                                      'l': round(h['liabilities'])} for h in hist]),
                               trend_json=json.dumps({'m': [datetime.strptime(x, '%Y-%m').strftime("%b") for x in d['months']],
                                                      'i': [round(d['trend'][x]['income']) for x in d['months']],
                                                      'e': [round(d['trend'][x]['expense']) for x in d['months']]}))

    def snapshot_now():
        con = con_()
        record_snapshot(con, build(con))
        flash('Net worth recorded for today.', 'success')
        return redirect(url_for('networth_page'))

    for rule, ep, fn, methods in [
        ('/', 'home', home, ['GET']),
        ('/accounts', 'accounts', accounts, ['GET']),
        ('/accounts/<int:acc_id>', 'account_detail', account_detail, ['GET']),
        ('/accounts/save', 'account_save', account_save, ['POST']),
        ('/accounts/<int:acc_id>/balance', 'account_balance', account_balance, ['POST']),
        ('/accounts/balance/<int:bal_id>/delete', 'balance_delete', balance_delete, ['POST']),
        ('/accounts/<int:acc_id>/status', 'account_status', account_status, ['POST']),
        ('/accounts/<int:acc_id>/delete', 'account_delete', account_delete, ['POST']),
        ('/accounts/broker/<int:bid>/delete', 'broker_delete', broker_delete, ['POST']),
        ('/networth', 'networth_page', networth_page, ['GET']),
        ('/networth/snapshot', 'snapshot_now', snapshot_now, ['POST']),
        ('/dues', 'dues_page', dues_page, ['GET']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)


def rename_account(con, old, new):
    """Account names are stored on transactions, loans and statements — keep them in step."""
    con.execute('UPDATE transactions SET account=? WHERE account=?', (new, old))
    con.execute('UPDATE loans SET card=? WHERE card=?', (new, old))
    for sid, accs in con.execute('SELECT id, accounts FROM statements').fetchall():
        names = [n.strip() for n in (accs or '').split(';') if n.strip()]
        if old in names:
            con.execute('UPDATE statements SET accounts=? WHERE id=?', ('; '.join(new if n == old else n for n in names), sid))
