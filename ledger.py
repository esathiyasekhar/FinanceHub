"""Finance Hub 1.2 — interlinked transfers, company ↔ director account, reimbursements from clients, loans with people.

Transfers between your own accounts (bank → card bill, savings → broker, your company → you, you → your company …) are found
automatically (same amount, a few days apart, or the narration names the other account) and shown as
suggestions; once you confirm, both sides are categorised as a transfer so they are not counted as
income or expense, and company ↔ you movements build the director's account.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, jsonify

import classifier as C
import scope as SC

SCHEMA = """
CREATE TABLE IF NOT EXISTS txn_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    out_id INTEGER, in_id INTEGER,          -- money-out and money-in transactions (one may be missing)
    counter_kind TEXT, counter_ref TEXT,    -- other side outside the Hub: account / broker / person
    kind TEXT NOT NULL, status TEXT DEFAULT 'suggested',   -- suggested / confirmed / rejected
    score REAL DEFAULT 0, reason TEXT, amount REAL, note TEXT,
    created_at TEXT DEFAULT (datetime('now')), confirmed_at TEXT);
CREATE INDEX IF NOT EXISTS idx_link_out ON txn_links(out_id);
CREATE INDEX IF NOT EXISTS idx_link_in ON txn_links(in_id);
CREATE TABLE IF NOT EXISTS reimb_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT, payer TEXT NOT NULL, title TEXT, claim_date TEXT,
    status TEXT DEFAULT 'open', note TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS reimb_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id INTEGER NOT NULL, txn_id INTEGER NOT NULL, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, phone TEXT, bank TEXT, account_no TEXT,
    ifsc TEXT, upi TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS pl_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT DEFAULT 'Personal', person TEXT NOT NULL,
    direction TEXT NOT NULL,                -- given (you lent) / taken (you borrowed)
    start_date TEXT, amount REAL DEFAULT 0, interest_rate REAL DEFAULT 0, due_date TEXT, purpose TEXT,
    status TEXT DEFAULT 'open', notes TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS pl_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT, loan_id INTEGER NOT NULL, date TEXT NOT NULL, amount REAL NOT NULL,
    kind TEXT NOT NULL,                     -- principal (money handed over) / repayment / interest / waived
    mode TEXT,                              -- Cash / UPI / NEFT / IMPS / RTGS / Cheque / Other
    our_account TEXT, their_name TEXT, their_bank TEXT, their_account TEXT, their_ifsc TEXT, their_upi TEXT,
    reference TEXT, txn_id INTEGER, note TEXT);
"""
TXN_COLUMNS = [('reimb_payer', 'TEXT'), ('reimb_claim', 'INTEGER')]

T, E, I, INV = 'Transfers', 'Expenses', 'Income', 'Investments'
LINK_KINDS = {  # key: label, out-side category path, in-side category path, director-account sign (+ = the company owes you)
    'card_payment': ('Card bill payment', (T, 'Card bill payments', 'Paid to cards', 'From bank account'),
                     (T, 'Card bill payments', 'Received on cards', 'Card payment received'), 0),
    'self_transfer': ('Between own accounts', (T, 'Own accounts', 'Between own accounts', 'Self transfer'),
                      (T, 'Own accounts', 'Between own accounts', 'Self transfer'), 0),
    'loan_payment': ('Loan repayment', (T, 'Loan repayments', 'Principal', 'Other loans'),
                     (T, 'Loan repayments', 'Principal', 'Other loans'), 0),
    'broker_funding': ('Money to broker', (INV, 'Market', 'Stocks & mutual funds', 'Broker'), None, 0),
    'broker_withdrawal': ('Money from broker', None, (INV, 'Market', 'Stocks & mutual funds', 'Broker'), 0),
    'owner_capital': ('You → your company (capital / loan)', (INV, 'Own business', 'Capital & loans to business', 'Transfers to business'),
                      (T, 'Owner & director', 'Director account', 'Received from director'), 1),
    'owner_drawings': ('Company → you (drawings / paid for you)', (T, 'Owner & director', 'Director account', 'Paid to / for director'),
                       (T, 'Owner & director', 'Director account', 'Received from company'), -1),
    'owner_repay': ('Company repays you (loan / expenses you paid)', (T, 'Owner & director', 'Director account', 'Repaid to director'),
                    (T, 'Owner & director', 'Director account', 'Received from company'), -1),
    'owner_salary': ('Company → you (remuneration)', (E, 'Business Expenses', 'Salaries & remuneration', 'Director remuneration'),
                     (I, 'Business Income', 'Own business', 'Director remuneration'), 0),
}
EXTRA_NODES = [  # 1.2 additions to the category tree (created if missing)
    (T, 'Owner & director', 'Director account', 'Paid to / for director'),
    (T, 'Owner & director', 'Director account', 'Received from company'),
    (T, 'Owner & director', 'Director account', 'Received from director'),
    (T, 'Owner & director', 'Director account', 'Repaid to director'),
    (T, 'Loans with people', 'Lent', 'Money lent'), (T, 'Loans with people', 'Lent', 'Repaid to you'),
    (T, 'Loans with people', 'Borrowed', 'Money borrowed'), (T, 'Loans with people', 'Borrowed', 'Repaid by you'),
    (E, 'Business Expenses', 'Salaries & remuneration', 'Director remuneration'),
    (E, 'Business Expenses', 'Salaries & remuneration', 'Staff salaries'),
    (E, 'Business Expenses', 'Office & rent', 'Rent'), (E, 'Business Expenses', 'Office & rent', 'Office expenses'),
    (E, 'Business Expenses', 'Professional fees', 'Accounting & legal'),
    (E, 'Business Expenses', 'Statutory & GST', 'GST & TDS payments'),
    (I, 'Business Income', 'Own business', 'Director remuneration'), (I, 'Business Income', 'Customers', 'Sales & service receipts'),
    (I, 'Salary & Remuneration', 'Employers & clients', 'Consultancy fees'),
]
PL_PATHS = {('given', 'principal'): (T, 'Loans with people', 'Lent', 'Money lent'),
            ('given', 'repayment'): (T, 'Loans with people', 'Lent', 'Repaid to you'),
            ('taken', 'principal'): (T, 'Loans with people', 'Borrowed', 'Money borrowed'),
            ('taken', 'repayment'): (T, 'Loans with people', 'Borrowed', 'Repaid by you'),
            ('given', 'interest'): (I, 'Investment Income', 'Interest', 'Interest from people'),
            ('taken', 'interest'): (E, 'Loans & EMI', 'Interest', 'Interest to people')}
MODES = ['Cash', 'UPI', 'NEFT', 'IMPS', 'RTGS', 'Cheque', 'Bank transfer (other)', 'Card', 'Other']

CARD_HINTS = [(r'SBI\s?CARD|SBICARD|SBICPSL', 'sbi'),
              (r'HDFC\s?(BANK\s?)?(CREDIT\s?CARD|CC\b)|HDFCBIZ|BIZPWR|BIZPOWER|ESSHDFC|TATANEU|HDFC\s?CARD', 'hdfc'),
              (r'ICICI\s?(BANK\s?)?(CREDIT\s?CARD|CC\b)|ICICICC|ESSICICI|AMAZON PAY CC', 'icici'),
              (r'AXIS\s?(BANK\s?)?(CREDIT\s?CARD|CC\b)|AXISCC|ESSAXIS|FLIPKART AXIS', 'axis'),
              (r'STANCHA|STAN\s?CHART|STANDARD CHARTERED|ESSSCB', 'sc'),
              (r'SIB\s?ONE|ONECARD|ONE\s?CARD|FPL\s?TECH', 'sib')]
BROKER_HINTS = [(r'ZERODHA', 'zerodha'), (r'UPSTOX|RKSV', 'upstox'), (r'SBICAP|SBI\s?CAP|SBI\s?SECURITIES', 'sbi securities'),
                (r'GROWW|NEXTBILLION', 'groww'), (r'ANGEL\s?(ONE|BROKING)', 'angel'), (r'ICICI\s?SEC', 'icici sec'),
                (r'KOTAK\s?SEC', 'kotak sec'), (r'ICCL|INDIAN CLEARING|NSE CLEARING|NSCCL|CLEARING CORP', '')]


def ensure_schema(con):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute('PRAGMA table_info(transactions)')}
    for name, decl in TXN_COLUMNS:
        if name not in have:
            con.execute(f'ALTER TABLE transactions ADD COLUMN {name} {decl}')
    for p in EXTRA_NODES + list(PL_PATHS.values()):
        C.path_id(con, p, create=True)
    con.commit()


def setting(con, key, default=''):
    r = con.execute('SELECT value FROM hub_settings WHERE key=?', (key,)).fetchone()
    return r[0] if r and r[0] is not None else default


def skel(s):
    """Consonant skeleton: 'BizPower' → 'BZPWR' (bank narrations drop vowels: 'BIZPWR')."""
    return re.sub(r'[AEIOU\W\d_]', '', (s or '').upper())


def _acct_info(con):
    import importer as IM
    out = {}
    for a in con.execute("SELECT name, kind, card_no, bank, COALESCE(NULLIF(entity,''),'Personal') AS book FROM accounts"):
        d = dict(a)
        d['code'] = IM.bank_code((a['bank'] or '') + ' ' + a['name'])
        d['digits'] = re.sub(r'\D', '', a['card_no'] or '')
        words = [w for w in re.findall(r'[A-Za-z]+', a['name']) if w.lower() not in IM.STOP | IM.BANK_WORDS | {'savings', 'current', 'loan'}]
        d['skels'] = [skel(w) for w in words if len(skel(w)) >= 4]
        out[a['name']] = d
    return out


def _text(r):
    return f"{r['description'] or ''} {r['narration'] or ''} {r['reference'] or ''}".upper()


def card_from_text(text, accts, exclude=''):
    hits = []
    for pat, code in CARD_HINTS:
        if re.search(pat, text):
            hits = [a for a in accts.values() if a['kind'] == 'card' and a['code'] == code and a['name'] != exclude]
            break
    if len(hits) > 1:
        st = skel(text)
        narrowed = [a for a in hits if any(s in st for s in a['skels'])]
        hits = narrowed or hits
    return hits[0]['name'] if len(hits) == 1 else ''


def account_from_digits(text, accts, exclude=''):
    """'TRANSFER TO 00000012343842' → the own account whose number ends with …3842."""
    cands = set()
    for num in re.findall(r'\d{8,18}', text):
        for a in accts.values():
            if a['name'] != exclude and len(a['digits']) >= 4 and a['kind'] in ('bank', 'card', 'loan') \
                    and (num.endswith(a['digits'][-6:]) if len(a['digits']) >= 6 else num.endswith(a['digits'][-4:])):
                cands.add(a['name'])
    return next(iter(cands)) if len(cands) == 1 else ''


def broker_from_text(text, con):
    for pat, key in BROKER_HINTS:
        if re.search(pat, text):
            if not key:
                return 'clearing'
            row = con.execute('SELECT id, name FROM inv_brokers WHERE lower(name) LIKE ?', (f'%{key}%',)).fetchone()
            return str(row['id']) if row else key.title()
    return ''


def decide_kind(out_acct, in_acct):
    ok, ik = out_acct['kind'], in_acct['kind']
    ob, ib = out_acct['book'], in_acct['book']
    if ob != ib:
        if ob != 'Personal' and ib == 'Personal':
            return 'owner_drawings'
        if ob == 'Personal' and ib != 'Personal':
            return 'owner_capital'
    if ik == 'card':
        return 'card_payment'
    if ik == 'loan':
        return 'loan_payment'
    return 'self_transfer'


def linked_ids(con, include_rejected=False):
    q = 'SELECT out_id, in_id FROM txn_links' + ('' if include_rejected else " WHERE status<>'rejected'")
    s = set()
    for o, i in con.execute(q):
        s.update(x for x in (o, i) if x)
    return s


def suggest(con):
    """Add new suggestions for unlinked transactions; returns how many were added."""
    accts = _acct_info(con)
    taken = linked_ids(con)
    rejected = {(o, i) for o, i in con.execute("SELECT out_id, in_id FROM txn_links WHERE status='rejected'")}
    rows = con.execute("SELECT t.*, c.kind AS ckind FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
                       "WHERE t.amount >= 1 ORDER BY t.date").fetchall()
    rows = [r for r in rows if r['id'] not in taken and r['account'] in accts]
    credits = defaultdict(list)
    for r in rows:
        if r['type'] == 'credit':
            credits[round(r['amount'])].append(r)
    pairs = []
    for d in rows:
        if d['type'] != 'debit' or d['ckind'] in ('income',):
            continue
        dd = datetime.strptime(d['date'], '%Y-%m-%d').date()
        dt = _text(d)
        named_card = card_from_text(dt, accts, d['account'])
        named_acct = account_from_digits(dt, accts, d['account'])
        for key in (round(d['amount']) - 1, round(d['amount']), round(d['amount']) + 1):
            for c in credits.get(key, []):
                if c['account'] == d['account'] or abs(c['amount'] - d['amount']) > 1 or (d['id'], c['id']) in rejected:
                    continue
                gap = (datetime.strptime(c['date'], '%Y-%m-%d').date() - dd).days
                if gap < -2 or gap > 6:
                    continue
                score = 10 - abs(gap)
                why = [f'same amount, {abs(gap)} day{"s" if abs(gap) != 1 else ""} apart' if gap else 'same amount, same day']
                if c['account'] in (named_card, named_acct):
                    score += 8; why.append('narration names the account')
                ca, da = accts[c['account']], accts[d['account']]
                if ca['kind'] == 'card' and re.search(r'PAYMENT|THANK YOU|RECEIVED|NEFT|IMPS|UPI|AUTOPAY|BBPS', _text(c)):
                    score += 3
                if da['kind'] == 'card' and ca['kind'] == 'bank':
                    score -= 4          # a card paying into a bank account is unusual (refund / cash-back)
                pairs.append((score, d, c, '; '.join(why)))
    pairs.sort(key=lambda x: -x[0])
    used, n = set(), 0
    for score, d, c, why in pairs:
        if d['id'] in used or c['id'] in used or score < 6:
            continue
        used.update((d['id'], c['id']))
        kind = decide_kind(accts[d['account']], accts[c['account']])
        con.execute('INSERT INTO txn_links (out_id, in_id, kind, status, score, reason, amount) VALUES (?,?,?,?,?,?,?)',
                    (d['id'], c['id'], kind, 'suggested', score, why, d['amount']))
        n += 1
    # one-sided: the narration names an own account / card / broker whose side is not in the Hub
    owner_words = [w.strip().upper() for n, al in con.execute("SELECT name, aliases FROM people WHERE name='Self'")
                   for w in (al or '').split(',') if len(w.strip()) >= 5 and w.strip().lower() != 'primary']
    for r in rows:
        if r['id'] in used:
            continue
        txt = _text(r)
        a = accts[r['account']]
        counter, ck, kind, why = '', '', '', ''
        if r['type'] == 'debit':
            cname = card_from_text(txt, accts, r['account']) or account_from_digits(txt, accts, r['account'])
            if cname:
                counter, ck = cname, 'account'
                kind, why = decide_kind(a, accts[cname]), f'narration names {cname}'
            else:
                b = broker_from_text(txt, con)
                if b:
                    counter, ck, kind, why = b, 'broker', 'broker_funding', 'payment to a broker / clearing house'
                elif a['book'] != 'Personal' and any(w in txt for w in owner_words):
                    counter, ck, kind, why = 'Owner', 'person', 'owner_drawings', 'paid to you (your name in the narration)'
        else:
            b = broker_from_text(txt, con)
            if b:
                counter, ck, kind, why = b, 'broker', 'broker_withdrawal', 'money from a broker'
            elif a['book'] == 'Personal' and company_from_text(con, txt):
                cname = company_from_text(con, txt)
                counter, ck, kind, why = cname, 'book', 'owner_drawings', f'received from {cname}'
            elif a['book'] != 'Personal' and any(w in txt for w in owner_words):
                counter, ck, kind, why = 'Owner', 'person', 'owner_capital', 'received from you (your name in the narration)'
        if not kind:
            continue
        if con.execute("SELECT 1 FROM txn_links WHERE status='rejected' AND (out_id=? OR in_id=?) AND in_id IS NULL OR "
                       "status='rejected' AND out_id IS NULL AND in_id=?", (r['id'], r['id'], r['id'])).fetchone():
            continue
        out_id, in_id = (r['id'], None) if r['type'] == 'debit' else (None, r['id'])
        con.execute('INSERT INTO txn_links (out_id, in_id, counter_kind, counter_ref, kind, status, score, reason, amount) '
                    'VALUES (?,?,?,?,?,?,?,?,?)', (out_id, in_id, ck, counter, kind, 'suggested', 5, why, r['amount']))
        n += 1
    con.commit()
    return n


def _set_cat(con, tid, path):
    if not tid or not path:
        return
    cid = C.path_id(con, path, create=True)
    con.execute('UPDATE transactions SET category_id=?, category=?, manual=1 WHERE id=?', (cid, C.head_name(con, cid), tid))


def confirm(con, lid, kind=None):
    l = con.execute('SELECT * FROM txn_links WHERE id=?', (lid,)).fetchone()
    if not l:
        return
    kind = kind if kind in LINK_KINDS else l['kind']
    label, out_p, in_p, _ = LINK_KINDS[kind]
    _set_cat(con, l['out_id'], out_p)
    _set_cat(con, l['in_id'], in_p)
    con.execute("UPDATE txn_links SET status='confirmed', kind=?, confirmed_at=datetime('now') WHERE id=?", (kind, lid))


def undo(con, lid, reject=True):
    l = con.execute('SELECT * FROM txn_links WHERE id=?', (lid,)).fetchone()
    if not l:
        return
    if l['status'] == 'confirmed':
        ids = [x for x in (l['out_id'], l['in_id']) if x]
        if ids:
            con.execute(f"UPDATE transactions SET manual=0 WHERE id IN ({','.join('?' * len(ids))})", ids)
            C.apply_to_rows(con, f"id IN ({','.join('?' * len(ids))})", ids, commit=False)
    if reject:
        con.execute("UPDATE txn_links SET status='rejected' WHERE id=?", (lid,))
    else:
        con.execute('DELETE FROM txn_links WHERE id=?', (lid,))


def link_rows(con, status, limit=500):
    sql, par = SC.txn_sql('x')
    rows = con.execute(
        f"""SELECT l.*, o.date AS o_date, o.account AS o_acct, COALESCE(NULLIF(o.display_name,''), o.description) AS o_desc,
                   o.amount AS o_amt, i.date AS i_date, i.account AS i_acct, COALESCE(NULLIF(i.display_name,''), i.description) AS i_desc,
                   i.amount AS i_amt
            FROM txn_links l LEFT JOIN transactions o ON o.id=l.out_id LEFT JOIN transactions i ON i.id=l.in_id
            WHERE l.status=? AND EXISTS (SELECT 1 FROM transactions x WHERE x.id IN (l.out_id, l.in_id) AND {sql})
            ORDER BY COALESCE(o.date, i.date) DESC LIMIT ?""", (status, *par, limit)).fetchall()
    brokers = {str(r['id']): r['name'] for r in con.execute('SELECT id, name FROM inv_brokers')}
    out = []
    for r in rows:
        d = dict(r)
        d['label'] = LINK_KINDS.get(r['kind'], (r['kind'],))[0]
        d['counter'] = brokers.get(r['counter_ref'], r['counter_ref']) if r['counter_kind'] == 'broker' else r['counter_ref']
        if d['counter'] == 'clearing':
            d['counter'] = 'Clearing corporation (broker funds)'
        d['date'] = r['o_date'] or r['i_date']
        out.append(d)
    return out


def director_ledger(con, book, start=None, end=None):
    """Movements between a company book and you, from the company's side: + = the company owes you more."""
    accts = _acct_info(con)
    rows = []
    for l in con.execute("SELECT l.*, o.date od, o.account oa, o.description odesc, i.date idt, i.account ia, i.description idesc "
                         "FROM txn_links l LEFT JOIN transactions o ON o.id=l.out_id LEFT JOIN transactions i ON i.id=l.in_id "
                         "WHERE l.status='confirmed' AND l.kind IN ('owner_capital','owner_drawings','owner_repay','owner_salary')"):
        books = {accts.get(l['oa'] or '', {}).get('book'), accts.get(l['ia'] or '', {}).get('book'), l['counter_ref']}
        if book not in books and not (l['counter_ref'] == 'Owner' and accts.get(l['oa'] or l['ia'] or '', {}).get('book') == book):
            continue
        sign = LINK_KINDS[l['kind']][3]
        d = l['od'] or l['idt']
        rows.append({'date': d, 'what': LINK_KINDS[l['kind']][0], 'detail': (l['odesc'] or l['idesc'] or '')[:70],
                     'from': l['oa'] or l['counter_ref'] or '', 'to': l['ia'] or l['counter_ref'] or '',
                     'amount': l['amount'], 'effect': sign * (l['amount'] or 0), 'kind': l['kind']})
    # company expenses you paid from your own accounts (rows tagged with the book but in a Personal account)
    for t in con.execute("SELECT t.date, t.description, t.display_name, t.amount, t.type, t.account FROM transactions t "
                         "JOIN categories c ON c.id=t.category_id WHERE t.entity=? AND c.kind='expense'", (book,)):
        if accts.get(t['account'], {}).get('book', 'Personal') != 'Personal':
            continue
        eff = t['amount'] if t['type'] == 'debit' else -t['amount']
        rows.append({'date': t['date'], 'what': f'{book} expense paid by you', 'detail': (t['display_name'] or t['description'])[:70],
                     'from': t['account'], 'to': book, 'amount': t['amount'], 'effect': eff, 'kind': 'paid_for_company'})
    rows.sort(key=lambda r: r['date'] or '')
    bal = 0.0
    for r in rows:
        bal += r['effect']
        r['balance'] = bal
    if start:
        opening = sum(r['effect'] for r in rows if r['date'] < start)
        rows = [r for r in rows if start <= r['date'] <= (end or '9999')]
    else:
        opening = 0.0
    return rows, opening


# ── reimbursements (expenses a client / employer pays back) ───────────────────────────────────────────────────
def payers(con):
    return [r[0] for r in con.execute("SELECT name FROM entities WHERE role='payer' ORDER BY name")]


def payer_regex(con, name):
    row = con.execute('SELECT aliases FROM entities WHERE name=?', (name,)).fetchone()
    words = [name] + [a for a in ((row[0] if row else '') or '').split(',')]
    first = [re.sub(r'[^A-Za-z ]', '', w).split()[0] for w in words if re.sub(r'[^A-Za-z ]', '', w).split()]
    return re.compile(r'\b(' + '|'.join(re.escape(w.upper()) for w in first if len(w) >= 3) + ')', re.I) if first else re.compile(r'$^')


def company_from_text(con, text):
    for n, al in con.execute("SELECT name, COALESCE(aliases,'') FROM entities WHERE name<>'Personal' AND COALESCE(role,'book')='book'"):
        for w in [n] + al.split(','):
            w = w.strip().upper()
            if len(w) >= 4 and re.search(r'(?<![A-Z])' + re.escape(w) + r'(?![A-Z])', text):
                return n
    return ''


def reimb_state(con, payer):
    items = con.execute("SELECT t.*, c.name AS cat FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
                        "WHERE t.reimb_payer=? AND t.type='debit' ORDER BY t.date", (payer,)).fetchall()
    claims = []
    for cl in con.execute('SELECT * FROM reimb_claims WHERE payer=? ORDER BY id DESC', (payer,)):
        its = [i for i in items if i['reimb_claim'] == cl['id']]
        rec = con.execute('SELECT r.*, t.date, t.account, t.description FROM reimb_receipts r JOIN transactions t ON t.id=r.txn_id '
                          'WHERE r.claim_id=? ORDER BY t.date', (cl['id'],)).fetchall()
        total, got = sum(i['amount'] for i in its), sum(r['amount'] for r in rec)
        claims.append({**dict(cl), 'items': its, 'receipts': rec, 'total': total, 'received': got, 'balance': total - got,
                       'state': 'paid' if its and got >= total - 1 else ('part paid' if got > 0 else cl['status'])})
    open_items = [i for i in items if not i['reimb_claim']]
    rx = payer_regex(con, payer)
    applied = {r[0] for r in con.execute('SELECT txn_id FROM reimb_receipts')}
    credits = [t for t in con.execute("SELECT t.*, c.name AS cat FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
                                      "WHERE t.type='credit' ORDER BY t.date DESC LIMIT 2000")
               if rx.search(_text(t)) and t['id'] not in applied]
    fees = [t for t in credits if t['reimb_payer'] != payer]
    pending_receipts = [t for t in credits if t['reimb_payer'] == payer]
    sugg = {}
    for t in pending_receipts:
        best = next((c for c in sorted(claims, key=lambda c: c['id']) if c['balance'] > 1 and abs(c['balance'] - t['amount']) <= 1), None) \
            or next((c for c in sorted(claims, key=lambda c: c['id']) if c['balance'] > 1), None)
        sugg[t['id']] = best['id'] if best else None
    return {'claims': claims, 'open_items': open_items, 'fee_credits': fees[:12], 'pending_receipts': pending_receipts,
            'suggest': sugg, 'open_total': sum(i['amount'] for i in open_items),
            'outstanding': sum(max(c['balance'], 0) for c in claims) + sum(i['amount'] for i in open_items),
            'received_total': sum(c['received'] for c in claims)}


# ── loans with people ───────────────────────────────────────────────────────
def pl_rows(con, book=None):
    q = 'SELECT * FROM pl_loans' + (' WHERE book=?' if book else '') + ' ORDER BY status, start_date DESC'
    out = []
    for l in con.execute(q, (book,) if book else ()):
        moves = con.execute('SELECT m.*, t.account AS t_acct, t.date AS t_date FROM pl_moves m LEFT JOIN transactions t ON t.id=m.txn_id '
                            'WHERE loan_id=? ORDER BY date, id', (l['id'],)).fetchall()
        principal = sum(m['amount'] for m in moves if m['kind'] == 'principal')
        repaid = sum(m['amount'] for m in moves if m['kind'] == 'repayment')
        waived = sum(m['amount'] for m in moves if m['kind'] == 'waived')
        interest = sum(m['amount'] for m in moves if m['kind'] == 'interest')
        out_ = principal - repaid - waived
        due = datetime.strptime(l['due_date'], '%Y-%m-%d').date() if l['due_date'] else None
        out.append({**dict(l), 'moves': moves, 'principal': principal, 'repaid': repaid, 'waived': waived, 'interest': interest,
                    'outstanding': out_, 'overdue': bool(due and due < date.today() and out_ > 0.5 and l['status'] == 'open'),
                    'due': due})
    return out


def pl_candidates(con, amount, on, direction, kind, book):
    """Bank / wallet transactions that could be this loan movement (same amount, ±7 days, money flowing the right way)."""
    money_out = (direction == 'given') == (kind == 'principal')
    d = datetime.strptime(on, '%Y-%m-%d').date()
    used = {r[0] for r in con.execute('SELECT txn_id FROM pl_moves WHERE txn_id IS NOT NULL')}
    rows = con.execute("SELECT t.* FROM transactions t JOIN accounts a ON a.name=t.account WHERE t.type=? AND ABS(t.amount-?)<=1 "
                       "AND t.date BETWEEN ? AND ? AND COALESCE(NULLIF(a.entity,''),'Personal')=? ORDER BY ABS(julianday(t.date)-julianday(?))",
                       ('debit' if money_out else 'credit', amount, (d - timedelta(days=7)).isoformat(),
                        (d + timedelta(days=7)).isoformat(), book, on)).fetchall()
    return [r for r in rows if r['id'] not in used]


def _mode_from(txn):
    t = _text(txn)
    for m in ('UPI', 'NEFT', 'IMPS', 'RTGS'):
        if m in t:
            return m
    if 'CHQ' in t or 'CHEQUE' in t or 'CLG' in t:
        return 'Cheque'
    if 'CASH' in t or 'ATM' in t:
        return 'Cash'
    return 'Bank transfer (other)'


# ── routes ───────────────────────────────────────────────────────────────────
def register(app, get_db):

    @app.context_processor
    def _inject_payers():
        try:
            return {'reimb_payers': payers(get_db())}
        except Exception:  # noqa: BLE001
            return {'reimb_payers': []}

    def _back(default):
        nxt = request.form.get('next') or ''
        return redirect(nxt if nxt.startswith('/') else default)

    def links_page():
        con = get_db()
        added = suggest(con)
        tab = request.args.get('tab', 'suggested')
        rows = link_rows(con, {'suggested': 'suggested', 'confirmed': 'confirmed', 'rejected': 'rejected'}.get(tab, 'suggested'))
        counts = dict(con.execute('SELECT status, COUNT(*) FROM txn_links GROUP BY status').fetchall())
        taken = linked_ids(con)
        sql, par = SC.txn_sql('t')
        unl = [r for r in con.execute(f"SELECT t.*, c.name AS cat FROM transactions t JOIN categories c ON c.id=t.category_id "
                                      f"WHERE c.kind='transfer' AND {sql} ORDER BY t.date DESC LIMIT 400", par) if r['id'] not in taken]
        # inter-account flow matrix of confirmed links
        flows = defaultdict(float)
        for r in link_rows(con, 'confirmed', 5000):
            flows[(r['o_acct'] or r['counter'] or '?', r['i_acct'] or r['counter'] or '?')] += r['amount'] or 0
        return render_template('links.html', rows=rows, tab=tab, counts=counts, added=added, unlinked=unl,
                               KINDS={k: v[0] for k, v in LINK_KINDS.items()},
                               flows=sorted(((a, b, v) for (a, b), v in flows.items()), key=lambda x: -x[2])[:40])

    def link_confirm(lid):
        con = get_db()
        confirm(con, lid, request.form.get('kind'))
        con.commit()
        return _back(url_for('links_page'))

    def link_confirm_many():
        con = get_db()
        ids = [int(x) for x in request.form.getlist('ids') if x.isdigit()]
        for lid in ids:
            confirm(con, lid, request.form.get(f'kind_{lid}'))
        con.commit()
        flash(f'{len(ids)} link{"s" if len(ids) != 1 else ""} confirmed.', 'success')
        return _back(url_for('links_page'))

    def link_reject(lid):
        con = get_db()
        undo(con, lid, reject=request.form.get('action') != 'delete')
        con.commit()
        return _back(url_for('links_page'))

    def link_manual():
        con = get_db()
        if request.method == 'POST':
            f = request.form
            a = con.execute('SELECT * FROM transactions WHERE id=?', (int(f['txn']),)).fetchone()
            other = int(f['other']) if f.get('other', '').isdigit() else None
            out_id, in_id = (a['id'], other) if a['type'] == 'debit' else (other, a['id'])
            kind = f.get('kind') if f.get('kind') in LINK_KINDS else 'self_transfer'
            con.execute('INSERT INTO txn_links (out_id, in_id, counter_kind, counter_ref, kind, status, reason, amount) '
                        'VALUES (?,?,?,?,?,?,?,?)', (out_id, in_id, None if other else 'account', None if other else f.get('counter', ''),
                                                     kind, 'suggested', 'linked by you', a['amount']))
            lid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
            confirm(con, lid, kind)
            con.commit()
            flash('Linked.', 'success')
            return _back(url_for('links_page', tab='confirmed'))
        tid = int(request.args.get('txn', 0) or 0)
        a = con.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
        if not a:
            flash('Transaction not found.', 'warning')
            return redirect(url_for('links_page'))
        taken = linked_ids(con)
        d = datetime.strptime(a['date'], '%Y-%m-%d').date()
        cands = [r for r in con.execute('SELECT * FROM transactions WHERE type<>? AND account<>? AND ABS(amount-?)<=1 AND date BETWEEN ? AND ? '
                                        'ORDER BY ABS(julianday(date)-julianday(?))',
                                        (a['type'], a['account'], a['amount'], (d - timedelta(days=15)).isoformat(),
                                         (d + timedelta(days=15)).isoformat(), a['date'])) if r['id'] not in taken]
        accts = [r[0] for r in con.execute("SELECT name FROM accounts ORDER BY name")]
        return render_template('link_manual.html', a=a, cands=cands, accts=accts,
                               KINDS={k: v[0] for k, v in LINK_KINDS.items()})

    def director_page():
        con = get_db()
        bks = [b for b in SC.books(con) if b != 'Personal']
        if not bks:
            flash('Add your company as a book on People & entities first.', 'info')
            return redirect(url_for('people_page'))
        book = request.args.get('book') or (SC.current()['book'] if SC.current()['book'] in bks else bks[0])
        start, end = request.args.get('start', ''), request.args.get('end', '')
        rows, opening = director_ledger(con, book, start or None, end or None)
        closing = opening + sum(r['effect'] for r in rows)
        return render_template('director.html', rows=rows, opening=opening, closing=closing, book=book, books=bks,
                               start=start, end=end, KINDS={k: v[0] for k, v in LINK_KINDS.items()})

    # reimbursements
    def reimb_page():
        con = get_db()
        ps = payers(con)
        if not ps:
            flash('Add the client / employer who pays you back as a “payer” on People & entities first.', 'info')
            return redirect(url_for('people_page'))
        payer = request.args.get('payer') or ps[0]
        st = reimb_state(con, payer)
        return render_template('reimbursements.html', st=st, payer=payer, payers=ps, today=date.today())

    def reimb_mark():
        """Mark transactions as 'claim from payer' (or clear it)."""
        con = get_db()
        d = request.get_json(silent=True) or request.form
        ids = [int(x) for x in (d.get('ids') if isinstance(d.get('ids'), list) else request.form.getlist('ids')) if str(x).isdigit()]
        payer = d.get('payer') or (payers(con) or ['Client'])[0]
        clear = str(d.get('clear', '')) in ('1', 'true', 'True')
        if not ids:
            return jsonify({'ok': False, 'msg': 'nothing selected'}), 400
        ph = ','.join('?' * len(ids))
        if clear:
            con.execute(f'UPDATE transactions SET reimb_payer=NULL, reimb_claim=NULL, manual=0 WHERE id IN ({ph})', ids)
            C.apply_to_rows(con, f'id IN ({ph})', ids, commit=False)
        else:
            path = (T, 'Reimbursable', payer, 'Expense to claim')
            cid = C.path_id(con, path, create=True)
            con.execute(f"UPDATE transactions SET reimb_payer=?, manual=1, category_id=?, category=? WHERE type='debit' AND id IN ({ph})",
                        (payer, cid, C.head_name(con, cid), *ids))
        con.commit()
        msg = f"{len(ids)} transaction{'s' if len(ids) != 1 else ''} {'cleared' if clear else 'marked to claim from ' + payer}."
        if request.is_json:
            return jsonify({'ok': True, 'msg': msg})
        flash(msg, 'success')
        return _back(url_for('reimb_page', payer=payer))

    def reimb_claim_new():
        con = get_db()
        f = request.form
        ids = [int(x) for x in f.getlist('ids') if x.isdigit()]
        if not ids:
            flash('Tick the expenses to put in the claim.', 'warning')
            return redirect(url_for('reimb_page', payer=f.get('payer')))
        cur = con.execute('INSERT INTO reimb_claims (payer, title, claim_date, status, note) VALUES (?,?,?,?,?)',
                          (f.get('payer'), f.get('title') or 'Travel claim', f.get('claim_date') or date.today().isoformat(), 'submitted', f.get('note', '')))
        con.execute(f"UPDATE transactions SET reimb_claim=? WHERE id IN ({','.join('?' * len(ids))})", (cur.lastrowid, *ids))
        con.commit()
        flash(f"Claim “{f.get('title') or 'Travel claim'}” created with {len(ids)} expenses.", 'success')
        return redirect(url_for('reimb_page', payer=f.get('payer')))

    def reimb_receipt():
        """A credit from the payer: apply it to a claim, or call it a fee (normal income)."""
        con = get_db()
        f = request.form
        tid = int(f.get('txn'))
        payer = f.get('payer')
        if f.get('action') == 'fee':
            con.execute('UPDATE transactions SET reimb_payer=NULL WHERE id=?', (tid,))
        elif f.get('action') == 'receipt':
            path = (T, 'Reimbursable', payer, 'Reimbursement received')
            cid = C.path_id(con, path, create=True)
            con.execute('UPDATE transactions SET reimb_payer=?, manual=1, category_id=?, category=? WHERE id=?',
                        (payer, cid, C.head_name(con, cid), tid))
        elif f.get('action') == 'apply' and f.get('claim'):
            t = con.execute('SELECT amount FROM transactions WHERE id=?', (tid,)).fetchone()
            path = (T, 'Reimbursable', payer, 'Reimbursement received')
            cid = C.path_id(con, path, create=True)
            con.execute('UPDATE transactions SET reimb_payer=?, manual=1, category_id=?, category=? WHERE id=?',
                        (payer, cid, C.head_name(con, cid), tid))
            con.execute('INSERT INTO reimb_receipts (claim_id, txn_id, amount) VALUES (?,?,?)',
                        (int(f['claim']), tid, float(f.get('amount') or t['amount'])))
        elif f.get('action') == 'unapply':
            con.execute('DELETE FROM reimb_receipts WHERE txn_id=?', (tid,))
        con.commit()
        return redirect(url_for('reimb_page', payer=payer))

    def reimb_claim_edit(cid):
        con = get_db()
        f = request.form
        if f.get('action') == 'delete':
            con.execute('UPDATE transactions SET reimb_claim=NULL WHERE reimb_claim=?', (cid,))
            con.execute('DELETE FROM reimb_receipts WHERE claim_id=?', (cid,))
            con.execute('DELETE FROM reimb_claims WHERE id=?', (cid,))
        elif f.get('action') == 'remove_item':
            con.execute('UPDATE transactions SET reimb_claim=NULL WHERE id=?', (int(f['txn']),))
        else:
            con.execute('UPDATE reimb_claims SET title=?, claim_date=?, note=? WHERE id=?',
                        (f.get('title'), f.get('claim_date'), f.get('note', ''), cid))
        con.commit()
        return redirect(url_for('reimb_page', payer=f.get('payer')))

    # loans with people
    def pl_page():
        con = get_db()
        book = SC.current()['book'] or request.args.get('book') or None
        loans = pl_rows(con, book)
        contacts = con.execute('SELECT * FROM contacts ORDER BY name').fetchall()
        by_person = defaultdict(lambda: {'given': 0.0, 'taken': 0.0})
        for l in loans:
            if l['status'] == 'open':
                by_person[(l['person'], l['book'])][l['direction']] += l['outstanding']
        accts = con.execute("SELECT name, COALESCE(NULLIF(entity,''),'Personal') AS book FROM accounts "
                            "WHERE kind IN ('bank','wallet','card') AND COALESCE(status,'active')='active' ORDER BY name").fetchall()
        return render_template('people_loans.html', loans=loans, contacts=contacts, books=SC.books(con), MODES=MODES,
                               accts=accts, by_person=sorted(by_person.items()), today=date.today(),
                               lent=sum(l['outstanding'] for l in loans if l['direction'] == 'given' and l['status'] == 'open'),
                               borrowed=sum(l['outstanding'] for l in loans if l['direction'] == 'taken' and l['status'] == 'open'),
                               from_txn=con.execute('SELECT * FROM transactions WHERE id=?', (request.args.get('txn', 0),)).fetchone())

    def _contact(con, f):
        name = (f.get('person') or '').strip()
        if not name:
            return ''
        row = con.execute('SELECT * FROM contacts WHERE name=?', (name,)).fetchone()
        vals = {k: (f.get(k) or '').strip() for k in ('phone', 'their_bank', 'their_account', 'their_ifsc', 'their_upi')}
        if not row:
            con.execute('INSERT INTO contacts (name, phone, bank, account_no, ifsc, upi) VALUES (?,?,?,?,?,?)',
                        (name, vals['phone'], vals['their_bank'], vals['their_account'], vals['their_ifsc'].upper(), vals['their_upi']))
        else:   # keep the details the first time they are given
            con.execute("UPDATE contacts SET phone=COALESCE(NULLIF(phone,''),?), bank=COALESCE(NULLIF(bank,''),?), "
                        "account_no=COALESCE(NULLIF(account_no,''),?), ifsc=COALESCE(NULLIF(ifsc,''),?), upi=COALESCE(NULLIF(upi,''),?) WHERE name=?",
                        (vals['phone'], vals['their_bank'], vals['their_account'], vals['their_ifsc'].upper(), vals['their_upi'], name))
        return name

    def _add_move(con, loan, f, kind, amount, on):
        txn_id = int(f['txn_id']) if str(f.get('txn_id', '')).isdigit() else None
        txn = con.execute('SELECT * FROM transactions WHERE id=?', (txn_id,)).fetchone() if txn_id else None
        mode = f.get('mode') or (_mode_from(txn) if txn else 'Cash')
        cur = con.execute('INSERT INTO pl_moves (loan_id, date, amount, kind, mode, our_account, their_name, their_bank, their_account, '
                          'their_ifsc, their_upi, reference, txn_id, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (loan['id'], on, amount, kind, mode, f.get('our_account') or (txn['account'] if txn else ''),
                           loan['person'], f.get('their_bank', ''), f.get('their_account', ''), (f.get('their_ifsc') or '').upper(),
                           f.get('their_upi', ''), f.get('reference') or (txn['reference'] if txn else ''), txn_id, f.get('note', '')))
        if txn:
            path = PL_PATHS.get((loan['direction'], kind))
            if path:
                _set_cat(con, txn_id, path)
            con.execute('UPDATE transactions SET person=COALESCE(person, ?) WHERE id=?', (loan['person'], txn_id))
        return cur.lastrowid

    def pl_save():
        con = get_db()
        f = request.form
        person = _contact(con, f)
        if not person or not f.get('amount'):
            flash('Person and amount are needed.', 'warning')
            return redirect(url_for('pl_page'))
        lid = int(f['id']) if str(f.get('id', '')).isdigit() else None
        vals = (f.get('book') or 'Personal', person, f.get('direction', 'given'), f.get('start_date') or date.today().isoformat(),
                float(f.get('amount') or 0), float(f.get('interest_rate') or 0), f.get('due_date') or None, f.get('purpose', ''), f.get('notes', ''))
        if lid:
            con.execute('UPDATE pl_loans SET book=?, person=?, direction=?, start_date=?, amount=?, interest_rate=?, due_date=?, purpose=?, notes=? '
                        'WHERE id=?', (*vals, lid))
            flash('Loan updated.', 'success')
        else:
            cur = con.execute('INSERT INTO pl_loans (book, person, direction, start_date, amount, interest_rate, due_date, purpose, notes) '
                              'VALUES (?,?,?,?,?,?,?,?,?)', vals)
            loan = con.execute('SELECT * FROM pl_loans WHERE id=?', (cur.lastrowid,)).fetchone()
            _add_move(con, loan, f, 'principal', vals[4], vals[3])
            flash(f"Recorded: {'lent to' if vals[2] == 'given' else 'borrowed from'} {person} ₹{vals[4]:,.0f}.", 'success')
        con.commit()
        return redirect(url_for('pl_page'))

    def pl_move(lid):
        con = get_db()
        f = request.form
        loan = con.execute('SELECT * FROM pl_loans WHERE id=?', (lid,)).fetchone()
        if f.get('action') == 'delete_move':
            m = con.execute('SELECT * FROM pl_moves WHERE id=?', (int(f['move']),)).fetchone()
            if m and m['txn_id']:
                con.execute('UPDATE transactions SET manual=0 WHERE id=?', (m['txn_id'],))
                C.apply_to_rows(con, 'id=?', (m['txn_id'],), commit=False)
            con.execute('DELETE FROM pl_moves WHERE id=?', (int(f['move']),))
        elif f.get('action') == 'link':
            m = con.execute('SELECT * FROM pl_moves WHERE id=?', (int(f['move']),)).fetchone()
            txn = con.execute('SELECT * FROM transactions WHERE id=?', (int(f['txn_id']),)).fetchone()
            con.execute('UPDATE pl_moves SET txn_id=?, our_account=?, mode=COALESCE(NULLIF(mode,\'Cash\'), ?), '
                        'reference=COALESCE(NULLIF(reference,\'\'), ?) WHERE id=?',
                        (txn['id'], txn['account'], _mode_from(txn), txn['reference'], m['id']))
            path = PL_PATHS.get((loan['direction'], m['kind']))
            _set_cat(con, txn['id'], path)
        elif f.get('action') in ('close', 'reopen'):
            con.execute('UPDATE pl_loans SET status=? WHERE id=?', ('closed' if f['action'] == 'close' else 'open', lid))
        elif f.get('action') == 'delete_loan':
            for m in con.execute('SELECT txn_id FROM pl_moves WHERE loan_id=? AND txn_id IS NOT NULL', (lid,)).fetchall():
                con.execute('UPDATE transactions SET manual=0 WHERE id=?', (m[0],))
                C.apply_to_rows(con, 'id=?', (m[0],), commit=False)
            con.execute('DELETE FROM pl_moves WHERE loan_id=?', (lid,))
            con.execute('DELETE FROM pl_loans WHERE id=?', (lid,))
        else:
            amt = float(f.get('amount') or 0)
            if amt > 0:
                _add_move(con, loan, f, f.get('kind', 'repayment'), amt, f.get('date') or date.today().isoformat())
                rows = pl_rows(con)
                me = next((r for r in rows if r['id'] == lid), None)
                if me and me['outstanding'] <= 0.5:
                    con.execute("UPDATE pl_loans SET status='closed' WHERE id=?", (lid,))
                    flash(f"{loan['person']}'s loan is fully settled — closed.", 'success')
        con.commit()
        return redirect(url_for('pl_page') + f'#loan-{lid}')

    def pl_candidates_api():
        con = get_db()
        a = request.args
        rows = pl_candidates(con, float(a.get('amount') or 0), a.get('date') or date.today().isoformat(),
                             a.get('direction', 'given'), a.get('kind', 'principal'), a.get('book', 'Personal'))
        return jsonify([{'id': r['id'], 'date': r['date'], 'account': r['account'], 'amount': r['amount'],
                         'desc': (r['display_name'] or r['description'])[:60], 'mode': _mode_from(r)} for r in rows[:10]])

    def contact_save():
        con = get_db()
        f = request.form
        cid = int(f['id']) if str(f.get('id', '')).isdigit() else None
        vals = tuple((f.get(k) or '').strip() for k in ('name', 'phone', 'bank', 'account_no', 'ifsc', 'upi', 'notes'))
        try:
            if cid:
                old = con.execute('SELECT name FROM contacts WHERE id=?', (cid,)).fetchone()[0]
                con.execute('UPDATE contacts SET name=?, phone=?, bank=?, account_no=?, ifsc=upper(?), upi=?, notes=? WHERE id=?', (*vals, cid))
                con.execute('UPDATE pl_loans SET person=? WHERE person=?', (vals[0], old))
            else:
                con.execute('INSERT INTO contacts (name, phone, bank, account_no, ifsc, upi, notes) VALUES (?,?,?,?,upper(?),?,?)', vals)
            con.commit()
            flash(f'Saved {vals[0]}.', 'success')
        except Exception as e:  # noqa: BLE001
            flash(f'Not saved: {e}', 'warning')
        return redirect(url_for('pl_page') + '#contacts')

    for rule, ep, fn, methods in [
        ('/links', 'links_page', links_page, ['GET']),
        ('/links/<int:lid>/confirm', 'link_confirm', link_confirm, ['POST']),
        ('/links/confirm', 'link_confirm_many', link_confirm_many, ['POST']),
        ('/links/<int:lid>/reject', 'link_reject', link_reject, ['POST']),
        ('/links/manual', 'link_manual', link_manual, ['GET', 'POST']),
        ('/director', 'director_page', director_page, ['GET']),
        ('/reimbursements', 'reimb_page', reimb_page, ['GET']),
        ('/reimbursements/mark', 'reimb_mark', reimb_mark, ['POST']),
        ('/reimbursements/claim', 'reimb_claim_new', reimb_claim_new, ['POST']),
        ('/reimbursements/claim/<int:cid>', 'reimb_claim_edit', reimb_claim_edit, ['POST']),
        ('/reimbursements/receipt', 'reimb_receipt', reimb_receipt, ['POST']),
        ('/people-loans', 'pl_page', pl_page, ['GET']),
        ('/people-loans/save', 'pl_save', pl_save, ['POST']),
        ('/people-loans/<int:lid>/move', 'pl_move', pl_move, ['POST']),
        ('/api/people-loans/candidates', 'pl_candidates_api', pl_candidates_api, ['GET']),
        ('/contacts/save', 'contact_save', contact_save, ['POST']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)
