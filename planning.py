"""Finance Hub 1.1 — recurring & subscriptions, budgets, card & loan tools, alerts, month close, Ctrl+K search."""
import json
import re
import statistics
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, jsonify

import classifier as C
import accounts_hub as AH
import scope as SC

SCHEMA = """
CREATE TABLE IF NOT EXISTS recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, match_key TEXT, amount REAL DEFAULT 0,
    freq TEXT DEFAULT 'monthly', next_date TEXT, account TEXT, category_id INTEGER,
    rtype TEXT DEFAULT 'subscription',      -- subscription / bill / insurance / sip / income / other
    status TEXT DEFAULT 'active',           -- active / ignored / ended
    source TEXT DEFAULT 'manual', notes TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS budgets (category_id INTEGER PRIMARY KEY, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS alert_state (key TEXT PRIMARY KEY, snoozed_until TEXT);
CREATE TABLE IF NOT EXISTS month_close (month TEXT NOT NULL, item TEXT NOT NULL, done INTEGER DEFAULT 1,
    at TEXT DEFAULT (datetime('now')), note TEXT, PRIMARY KEY (month, item));
"""

FREQS = {  # key: (label, days, months)
    'weekly': ('Weekly', 7, 0), 'monthly': ('Monthly', 0, 1), 'quarterly': ('Quarterly', 0, 3),
    'half-yearly': ('Half-yearly', 0, 6), 'yearly': ('Yearly', 0, 12),
}
PER_MONTH = {'weekly': 52 / 12, 'monthly': 1, 'quarterly': 1 / 3, 'half-yearly': 1 / 6, 'yearly': 1 / 12}
RTYPES = [('subscription', 'Subscription'), ('bill', 'Bill / utility'), ('insurance', 'Insurance'),
          ('sip', 'SIP / investment'), ('rent', 'Rent'), ('income', 'Income'), ('other', 'Other')]
SUBS_WORDS = {
    'subscription': ['NETFLIX', 'SPOTIFY', 'YOUTUBE', 'PRIME VIDEO', 'AMAZON PRIME', 'HOTSTAR', 'JIOCINEMA', 'SONYLIV',
                     'ZEE5', 'APPLE.COM', 'APPLE MEDIA', 'GOOGLE PLAY', 'GOOGLE ONE', 'MICROSOFT', 'ADOBE', 'OPENAI',
                     'CHATGPT', 'ANTHROPIC', 'CLAUDE.AI', 'CANVA', 'NOTION', 'DROPBOX', 'LINKEDIN', 'SWIGGY ONE',
                     'ZOMATO GOLD', 'TIMES PRIME', 'AUDIBLE', 'KINDLE', 'GITHUB', 'ZOOM'],
    'bill': ['AIRTEL', 'JIO', 'VODAFONE', ' VI ', 'BSNL', 'ACT FIBERNET', 'TATA PLAY', 'TATASKY', 'ELECTRICITY', 'TNEB',
             'BESCOM', 'MSEDCL', 'TANGEDCO', 'GAS', 'INDANE', 'WATER', 'BROADBAND', 'DTH', 'FASTAG'],
    'insurance': ['INSURANCE', 'LIC ', 'LIFE INS', 'HDFC LIFE', 'ICICI PRU', 'SBI LIFE', 'NIVA BUPA', 'STAR HEALTH',
                  'CARE HEALTH', 'TATA AIG', 'BAJAJ ALLIANZ', 'POLICY'],
    'sip': ['SIP', 'MUTUAL FUND', 'NACH-MF', 'BSE STAR', 'ZERODHA COIN', 'GROWW', 'KUVERA', 'NPS '],
}
CHARGE_WORDS = re.compile(r'FINANCE CHARGE|LATE (PAYMENT )?FEE|LATE PAY|INTEREST CHARGE|OVERLIMIT|OVER LIMIT|'
                          r'CASH ADVANCE FEE|PENAL|BOUNCE|RETURN CHARGE', re.I)


def ensure_schema(con):
    con.executescript(SCHEMA)
    con.commit()


def step_fn(freq):
    _, days, months = FREQS.get(freq, FREQS['monthly'])
    if days:
        return lambda d: d + timedelta(days=days)
    return lambda d: AH.add_months(d, months)


def back_fn(freq):
    _, days, months = FREQS.get(freq, FREQS['monthly'])
    if days:
        return lambda d: d - timedelta(days=days)
    return lambda d: AH.add_months(d, -months)


def norm_key(text):
    t = re.sub(r'[^A-Z ]', ' ', (text or '').upper())
    words = [w for w in t.split() if len(w) > 1 and w not in {'UPI', 'POS', 'ECOM', 'NEFT', 'IMPS', 'ACH', 'NACH', 'THE',
                                                              'PVT', 'LTD', 'PRIVATE', 'LIMITED', 'INDIA', 'IN', 'COM', 'WWW'}]
    return ' '.join(words[:3])


SUBS_RE = {k: re.compile(r'(?<![A-Z])(?:' + '|'.join(re.escape(w.strip()) for w in words) + r')(?![A-Z])')
           for k, words in SUBS_WORDS.items()}


def guess_rtype(text):
    t = (text or '').upper()
    for k, rx in SUBS_RE.items():
        if rx.search(t):
            return k
    return None


def classify_gap(g):
    if 5 <= g <= 9:
        return 'weekly'
    if 25 <= g <= 36:
        return 'monthly'
    if 80 <= g <= 100:
        return 'quarterly'
    if 170 <= g <= 195:
        return 'half-yearly'
    if 350 <= g <= 380:
        return 'yearly'
    return None


def detect(con):
    """Payments that repeat (same payee, similar amount, regular gap) or look like subscriptions / bills / premiums."""
    rows = con.execute(
        "SELECT t.id, t.date, t.amount, t.type, t.account, t.category_id, t.description, t.payee, t.display_name, c.kind "
        "FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
        f"WHERE t.type='debit' AND COALESCE(c.kind,'expense') IN ('expense','investment') AND {SC.txn_literal('t')} ORDER BY t.date").fetchall()
    known = {r['match_key'] for r in con.execute('SELECT match_key FROM recurring') if r['match_key']}
    groups = defaultdict(list)
    for r in rows:
        shown = r['display_name'] or r['payee'] or r['description']
        k = norm_key(r['payee'] or r['display_name'] or r['description'])
        if k:
            groups[k].append((r, shown))
    out = []
    for k, items in groups.items():
        if k in known:
            continue
        dates = sorted({datetime.strptime(r['date'], '%Y-%m-%d').date() for r, _ in items})
        amts = [r['amount'] for r, _ in items]
        last_r, shown = items[-1]
        rtype = guess_rtype(' '.join(s for _, s in items[-3:]) + ' ' + last_r['description'])
        freq, why = None, ''
        if len(dates) >= 2:
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            freq = classify_gap(statistics.median(gaps))
            similar = max(amts) <= 1.35 * min(amts) if min(amts) > 0 else False
            if freq and (similar or rtype) and (freq != 'weekly' or len(dates) >= 3):
                why = f'{len(dates)} payments, every ~{int(statistics.median(gaps))} days'
            else:
                freq = None
        if not freq and rtype and rtype != 'sip' and statistics.median(amts) >= 20:
            freq, why = ('yearly' if rtype == 'insurance' and last_r['amount'] > 5000 else 'monthly'), \
                        f'looks like a {dict(RTYPES)[rtype].lower()}'
        if not freq:
            continue
        last = dates[-1]
        step = step_fn(freq)
        nxt = step(last)
        out.append({'key': k, 'name': shown[:60], 'amount': round(statistics.median(amts[-3:]), 2), 'freq': freq,
                    'freq_label': FREQS[freq][0], 'last': last, 'next': nxt, 'count': len(dates), 'why': why,
                    'account': last_r['account'], 'category_id': last_r['category_id'], 'rtype': rtype or 'other'})
    out.sort(key=lambda x: -x['amount'] * PER_MONTH[x['freq']])
    return out


def recurring_rows(con, status=('active',)):
    acct_kind = {r['name']: r['kind'] for r in con.execute('SELECT name, kind FROM accounts')}
    today = date.today()
    out = []
    ph = ','.join('?' * len(status))
    acct_book = {r['name']: (r['entity'] or 'Personal') for r in con.execute('SELECT name, entity FROM accounts')}
    for r in con.execute(f'SELECT * FROM recurring WHERE status IN ({ph}) ORDER BY amount DESC', status):
        d = dict(r)
        c = SC.current()
        if (c['account'] and d['account'] != c['account']) or (c['book'] and acct_book.get(d['account'], 'Personal') != c['book']):
            continue
        step = step_fn(d['freq'])
        nxt = AH.parse_day(d['next_date'])
        guard = 0
        while nxt and nxt < today - timedelta(days=3) and guard < 500:
            nxt = step(nxt)
            guard += 1
        d['next'] = nxt
        d['step'] = step
        d['back'] = back_fn(d['freq'])
        d['freq_label'] = FREQS.get(d['freq'], ('Monthly',))[0]
        d['monthly'] = (d['amount'] or 0) * PER_MONTH.get(d['freq'], 1)
        d['account_kind'] = acct_kind.get(d['account'])
        d['due_in'] = (nxt - today).days if nxt else None
        out.append(d)
    return out


def recurring_for_dues(con, b=None):
    return [r for r in recurring_rows(con) if r['rtype'] != 'income']


# ── budgets ──────────────────────────────────────────────────────────────────
def head_spend(con, start, end):
    """Net expense per Head (level-2 category id) between start (incl.) and end (excl.)."""
    _, by_id = C.load_tree(con)

    def head(cid):
        n = by_id.get(cid)
        while n and n['level'] > 2:
            n = by_id.get(n['parent_id'])
        return n['id'] if n and n['level'] == 2 else None

    out = defaultdict(float)
    ssql, spar = SC.txn_sql('t')
    for cid, typ, amt in con.execute(
            "SELECT t.category_id, t.type, SUM(t.amount) FROM transactions t JOIN categories c ON c.id=t.category_id "
            f"WHERE c.kind='expense' AND t.date>=? AND t.date<? AND {ssql} AND COALESCE(t.reimb_payer,'')='' GROUP BY 1,2",
            (start, end, *spar)):
        h = head(cid)
        if h:
            out[h] += amt if typ == 'debit' else -amt
    return out, by_id


def months_with_data(con, start, end):
    return con.execute('SELECT COUNT(DISTINCT substr(date,1,7)) FROM transactions WHERE date>=? AND date<?',
                       (start, end)).fetchone()[0] or 0


def budget_rows(con, month_start=None):
    today = date.today()
    ms = month_start or today.replace(day=1)
    me = AH.add_months(ms, 1, 1)
    spent, by_id = head_spend(con, ms.isoformat(), me.isoformat())
    p3 = AH.add_months(ms, -3, 1).isoformat()
    prev3, _ = head_spend(con, p3, ms.isoformat())
    nm = max(months_with_data(con, p3, ms.isoformat()), 1)
    budgets = {r['category_id']: r['amount'] for r in con.execute('SELECT * FROM budgets')}
    days = monthrange(ms.year, ms.month)[1]
    elapsed = (min(today, me - timedelta(days=1)) - ms).days + 1 if today >= ms else 0
    rows = []
    for cid in set(budgets) | {k for k, v in spent.items() if v > 0}:
        n = by_id.get(cid)
        if not n:
            continue
        s = max(spent.get(cid, 0), 0)
        bud = budgets.get(cid)
        pace = s / elapsed * days if 0 < elapsed < days else s
        rows.append({'id': cid, 'name': n['name'], 'path': n['path'], 'spent': s, 'budget': bud,
                     'avg3': max(prev3.get(cid, 0), 0) / nm, 'pct': round(100 * s / bud) if bud else None,
                     'projected': pace, 'left': (bud - s) if bud else None,
                     'state': (None if not bud else 'over' if s > bud else 'warn' if s > 0.85 * bud or pace > bud else 'ok')})
    rows.sort(key=lambda r: (r['budget'] is None, -(r['pct'] or 0), -r['spent']))
    return rows


# ── alerts ───────────────────────────────────────────────────────────────────
def alerts(con, b, upcoming, cash):
    today = date.today()
    snoozed = {r['key'] for r in con.execute('SELECT key FROM alert_state WHERE snoozed_until >= ?', (today.isoformat(),))}
    out = []

    def add(key, level, icon, title, detail='', link=None, link_label='Open'):
        if key not in snoozed:
            out.append({'key': key, 'level': level, 'icon': icon, 'title': title, 'detail': detail, 'link': link,
                        'link_label': link_label})

    unseen = [a for a in b['groups']['card'] if a['status'] == 'active' and a.get('bill') and a['bill']['status'] == 'check']
    if unseen:
        add('unseen:' + ','.join(f"{a['id']}{a['bill']['due_date']}" for a in unseen), 'warning', 'bi-question-diamond',
            f"{len(unseen)} card bill{'s' if len(unseen) > 1 else ''} past the due date — payment not seen yet",
            '; '.join(f"{a['name']} ₹{a['bill']['left']:,.0f} (due {a['bill']['due_date'].strftime('%a, %d %b %Y')})" for a in unseen[:4])
            + '. Add the next card or bank statement to confirm they were paid.', url_for('import_page'), 'Add Statements')
    for a in b['groups']['card']:
        bill = a.get('bill')
        if a['status'] != 'active' or not bill or bill['status'] in ('paid', 'check') or not bill['due_date']:
            continue
        days = (bill['due_date'] - today).days
        key = f"bill:{a['id']}:{bill['due_date']}"
        if days < 0:
            add(key, 'danger', 'bi-exclamation-octagon', f"{a['name']} bill overdue by {-days} day{'s' if -days != 1 else ''}",
                f"₹{bill['left']:,.0f} still unpaid (minimum ₹{bill['min']:,.0f}). Pay now to avoid interest and late fees.",
                url_for('account_detail', acc_id=a['id']))
        elif days <= 5:
            add(key, 'warning', 'bi-alarm', f"{a['name']} bill due {'today' if days == 0 else f'in {days} days'}",
                f"₹{bill['left']:,.0f} to pay by {bill['due_date'].strftime('%a, %d %b %Y')}.", url_for('account_detail', acc_id=a['id']))
    if cash['need'] > cash['have'] and cash['need'] > 0:
        add(f"cash:{today.strftime('%Y-%m')}", 'danger', 'bi-droplet-half', 'Bank balance short of the next 30 days’ dues',
            f"Dues ₹{cash['need']:,.0f} vs ₹{cash['have']:,.0f} in bank accounts — a gap of ₹{cash['need'] - cash['have']:,.0f}"
            + (f" (bank balances as on {datetime.strptime(cash['as_of'], '%Y-%m-%d').strftime('%d %b')} — add newer statements for a true picture)." if cash.get('as_of') and cash['as_of'] < (today - timedelta(days=7)).isoformat() else '.'),
            url_for('dues_page'), 'See dues')
    hi = [a for a in b['groups']['card'] if a['status'] == 'active' and (a.get('util') or 0) >= 30]
    if hi:
        worst = max(hi, key=lambda a: a['util'])
        add(f"util:{today.strftime('%Y-%m')}", 'danger' if worst['util'] >= 75 else 'warning', 'bi-speedometer',
            f"{len(hi)} card{'s' if len(hi) > 1 else ''} above 30% utilisation",
            f"Highest: {worst['name']} at {worst['util']:.0f}%. Keeping each card under 30% helps your credit score.",
            url_for('tools_page'), 'Card tools')
    stale = [a for k in ('bank', 'card', 'loan') for a in b['groups'][k]
             if a['status'] == 'active' and a['stmt_count'] and a['stale_days'] is not None and a['stale_days'] > 40]
    if stale:
        add(f"stale:{today.isoformat()[:7]}", 'info', 'bi-file-earmark-arrow-up', f"{len(stale)} account{'s' if len(stale) > 1 else ''} need a newer statement",
            ', '.join(a['name'] for a in stale[:4]) + (' …' if len(stale) > 4 else '') + ' — last figures are over 40 days old.',
            url_for('import_page'), 'Add Statements')
    nob = [a for k in ('bank', 'deposit', 'wallet', 'asset') for a in b['groups'][k] if a['status'] == 'active' and a['balance'] is None]
    if nob:
        add('nobalance', 'info', 'bi-question-circle', f"{len(nob)} account{'s' if len(nob) > 1 else ''} without a balance",
            ', '.join(a['name'] for a in nob[:4]) + (' …' if len(nob) > 4 else '') + ' — add a statement or type the balance so net worth is complete.',
            url_for('accounts', tab='bank'), 'Accounts')
    rev = con.execute(f"SELECT COUNT(*) FROM transactions t JOIN categories c ON c.id=t.category_id WHERE c.name='To review' AND {SC.txn_literal('t')}").fetchone()[0]
    if rev:
        add('review', 'info', 'bi-tags', f'{rev} transactions to categorise', 'Categorised spending makes budgets, reports and ITR figures accurate.',
            url_for('transactions', review=1, start='2000-01-01', end='2099-12-31'), 'Categorise')
    for r in budget_rows(con):
        if r['state'] in ('over', 'warn') and r['budget']:
            add(f"budget:{r['id']}:{today.strftime('%Y-%m')}", 'warning' if r['state'] == 'warn' else 'danger', 'bi-pie-chart',
                f"{r['name']}: {'over budget' if r['state'] == 'over' else 'close to budget'}",
                f"Spent ₹{r['spent']:,.0f} of ₹{r['budget']:,.0f} this month (on pace for ₹{r['projected']:,.0f}).",
                url_for('budgets_page'), 'Budgets')
    for l in b['loans']:
        if l.get('status') == 'active' and l['bullet'] and l['next_due'] and (l['next_due'] - today).days < 0:
            add(f"bullet-past:{l['id']}:{l['next_due']}", 'warning', 'bi-hourglass-bottom', f"{l['name']} was due on {l['next_due'].strftime('%a, %d %b %Y')}",
                f"About ₹{l['outstanding_now']:,.0f} outstanding. If it was renewed or closed, update the loan (or add the latest statement).",
                url_for('accounts', tab='loan'), 'Loans')
        if l.get('status') == 'active' and l['bullet'] and l['next_due'] and 0 <= (l['next_due'] - today).days <= 60:
            add(f"bullet:{l['id']}", 'warning', 'bi-hourglass-split', f"{l['name']} falls due on {l['next_due'].strftime('%a, %d %b %Y')}",
                f"Bullet repayment of about ₹{l['outstanding_now']:,.0f}.", url_for('accounts', tab='loan'), 'Loans')
    for a in b['groups']['deposit']:
        if a['status'] == 'active' and a.get('days_to_maturity') is not None and 0 <= a['days_to_maturity'] <= 30:
            add(f"mature:{a['id']}", 'info', 'bi-safe2', f"{a['name']} matures in {a['days_to_maturity']} days",
                'Decide whether to renew or move the money.', url_for('account_detail', acc_id=a['id']))
    charges = con.execute("SELECT date, description, amount, account FROM transactions WHERE type='debit' AND date>=? "
                          "ORDER BY date DESC", ((today - timedelta(days=75)).isoformat(),)).fetchall()
    fees = [c for c in charges if CHARGE_WORDS.search(c['description'] or '')]
    if fees:
        add(f"fees:{fees[0]['date']}", 'warning', 'bi-cash-stack', f"Interest / late-fee charges found ({len(fees)})",
            f"₹{sum(c['amount'] for c in fees):,.0f} in the last 75 days, e.g. {fees[0]['account']}: {fees[0]['description'][:50]}.",
            url_for('transactions', search=re.sub(r'\s+', ' ', CHARGE_WORDS.search(fees[0]['description']).group(0)),
                    start='2000-01-01', end='2099-12-31'), 'See them')
    sug = detect(con)
    if sug:
        add(f"recurring:{len(sug)}", 'info', 'bi-arrow-repeat', f"{len(sug)} possible recurring payment{'s' if len(sug) > 1 else ''} found",
            'Confirm them to see them on the dues calendar and in your monthly fixed costs.', url_for('recurring_page'), 'Review')
    try:
        n = con.execute("SELECT COUNT(*) FROM inv_instructions WHERE status='open'").fetchone()[0]
        if n:
            add('instr', 'info', 'bi-list-check', f'{n} open buy / sell instruction{"s" if n > 1 else ""}',
                'They are marked done when the broker’s contract note is added.', url_for('inv_portfolio'), 'Portfolio')
    except Exception:  # noqa: BLE001
        pass
    last_m = AH.add_months(today.replace(day=1), -1, 1).strftime('%Y-%m')
    if today.day >= 5 and not con.execute("SELECT 1 FROM month_close WHERE month=? AND item='_closed'", (last_m,)).fetchone():
        add(f'close:{last_m}', 'info', 'bi-check2-square', f"Close {datetime.strptime(last_m, '%Y-%m').strftime('%B')}",
            'A 2-minute checklist: statements in, transactions categorised, bills paid, net worth recorded.',
            url_for('month_close_page', m=last_m), 'Checklist')
    order = {'danger': 0, 'warning': 1, 'info': 2}
    out.sort(key=lambda x: order[x['level']])
    return out


# ── month close ──────────────────────────────────────────────────────────────
MANUAL_ITEMS = [('cash', 'Cash in hand and wallets counted / updated'),
                ('invest', 'Contract notes for the month added (Investments)'),
                ('budgets', 'Budgets reviewed for next month'),
                ('docs', 'Bills, receipts and tax documents filed')]


def month_close_status(con, b, month_start):
    ms = month_start
    me = AH.add_months(ms, 1, 1)
    m = ms.strftime('%Y-%m')
    ticks = {r['item']: r for r in con.execute('SELECT * FROM month_close WHERE month=?', (m,))}
    items = []
    missing = [a['name'] for k in ('bank', 'card', 'loan') for a in b['groups'][k]
               if a['status'] == 'active' and a['stmt_count'] and (a['stmt'] is None or (a['stmt']['as_of'] or '') < (me - timedelta(days=12)).isoformat())]
    items.append({'key': 'stmts', 'label': 'Statements added for every account', 'auto': True, 'done': not missing,
                  'detail': ('Missing: ' + ', '.join(missing[:6]) + (' …' if len(missing) > 6 else '')) if missing else 'All accounts have a statement for the month.',
                  'link': url_for('import_page')})
    rev = con.execute("SELECT COUNT(*) FROM transactions t JOIN categories c ON c.id=t.category_id WHERE c.name='To review' "
                      "AND t.date>=? AND t.date<?", (ms.isoformat(), me.isoformat())).fetchone()[0]
    items.append({'key': 'review', 'label': 'Every transaction categorised', 'auto': True, 'done': rev == 0,
                  'detail': f'{rev} still “To review”.' if rev else 'Nothing left to review.',
                  'link': url_for('transactions', review=1, start=ms.isoformat(), end=(me - timedelta(days=1)).isoformat())})
    unpaid = [a['name'] for a in b['groups']['card'] if a.get('bill') and a['bill']['due_date']
              and ms <= a['bill']['due_date'] < me + timedelta(days=25) and a['bill']['status'] in ('due', 'part', 'overdue', 'check')
              and a['bill']['due_date'] < date.today()]
    items.append({'key': 'bills', 'label': 'Card bills paid on time', 'auto': True, 'done': not unpaid,
                  'detail': ('Unpaid: ' + ', '.join(unpaid)) if unpaid else 'No overdue card bills.', 'link': url_for('dues_page')})
    sug = detect(con)
    items.append({'key': 'recurring', 'label': 'Recurring payments reviewed', 'auto': True, 'done': not sug,
                  'detail': f'{len(sug)} suggestions waiting.' if sug else 'No new suggestions.', 'link': url_for('recurring_page')})
    snap = con.execute('SELECT day FROM networth_snapshots WHERE day>=? ORDER BY day LIMIT 1', ((me - timedelta(days=3)).isoformat(),)).fetchone()
    items.append({'key': 'networth', 'label': 'Net worth recorded at month end', 'auto': True, 'done': bool(snap),
                  'detail': f"Snapshot of {snap['day']}." if snap else 'Open Net worth after the month ends to record it.',
                  'link': url_for('networth_page')})
    for k, label in MANUAL_ITEMS:
        items.append({'key': k, 'label': label, 'auto': False, 'done': k in ticks, 'detail': '', 'link': None})
    done = sum(1 for i in items if i['done'])
    return {'month': m, 'label': ms.strftime('%B %Y'), 'items': items, 'done': done, 'total': len(items),
            'pct': round(100 * done / len(items)), 'closed': '_closed' in ticks,
            'closed_at': ticks['_closed']['at'] if '_closed' in ticks else None}


# ── card tools ───────────────────────────────────────────────────────────────
def best_cards(b, today=None):
    today = today or date.today()
    out = []
    for a in b['groups']['card']:
        if a['status'] != 'active' or not a.get('billing_day_eff'):
            continue
        nxt = AH.next_on_day(a['billing_day_eff'], today)
        grace = a.get('grace') or (((a['due_day_eff'] - a['billing_day_eff']) % 31) if a.get('due_day_eff') else 18)
        free = (nxt - today).days + grace
        out.append({'a': a, 'statement': nxt, 'due': nxt + timedelta(days=grace), 'free_days': free, 'grace': grace,
                    'ok': (a.get('util') or 0) < 30 and (a.get('available') or 1) > 0})
    out.sort(key=lambda x: (not x['ok'], -x['free_days']))
    return out


# ── search ───────────────────────────────────────────────────────────────────
PAGES = [  # title, endpoint, icon, keywords
    ('Home', 'home', 'bi-house', 'overview dashboard start'), ('Insights', 'dashboard', 'bi-bar-chart', 'charts spending income trend'),
    ('Alerts & month close', 'alerts_page', 'bi-bell', 'alerts warnings checklist close'),
    ('Dues calendar', 'dues_page', 'bi-calendar3', 'bills due calendar emi payments'),
    ('Accounts', 'accounts', 'bi-wallet2', 'banks cards loans deposits'), ('Net worth', 'networth_page', 'bi-graph-up', 'net worth assets liabilities'),
    ('Transactions', 'transactions', 'bi-list-ul', 'transactions payments spends'), ('Breakdown', 'breakdown', 'bi-diagram-3', 'categories breakdown heads'),
    ('Recurring & subscriptions', 'recurring_page', 'bi-arrow-repeat', 'subscriptions recurring bills'),
    ('Budgets', 'budgets_page', 'bi-pie-chart', 'budget limits'), ('Reports & ITR', 'reports_page', 'bi-file-earmark-spreadsheet', 'reports itr tax excel csv'),
    ('Portfolio & plan', 'inv_portfolio', 'bi-graph-up-arrow', 'stocks portfolio holdings tranches'),
    ('Trades', 'inv_trades', 'bi-arrow-left-right', 'trades buy sell'), ('Import broker files', 'inv_import', 'bi-file-earmark-arrow-up', 'contract notes broker'),
    ('Wealth planner', 'planner', 'bi-rocket-takeoff', 'compounding planner goals'),
    ('Card & loan tools', 'tools_page', 'bi-tools', 'utilisation best card prepayment calculator rewards'),
    ('Transfers & links', 'links_page', 'bi-link-45deg', 'transfers link own accounts card payment broker'),
    ('Loans with people', 'pl_page', 'bi-person-lines-fill', 'lent borrowed friends hand loan'),
    ('Reimbursements', 'reimb_page', 'bi-receipt-cutoff', 'claims reimbursement travel client'),
    ('Director’s account', 'director_page', 'bi-briefcase', 'company director drawings capital'),
    ('Holdings by broker', 'inv_brokers_page', 'bi-diagram-2', 'broker holdings demat'),
    ('Mail inbox', 'mail_page', 'bi-envelope', 'mail email imap inbox statements alerts gmail forward'),
    ('Reminders & reports by mail', 'reminders_page', 'bi-bell', 'reminder email weekly report dues emi sunday notify'),
    ('Failed payments & refunds', 'refunds_page', 'bi-arrow-counterclockwise', 'failed reversal refund reversed chargeback awaiting'),
    ('Help & user manual', 'help_page', 'bi-question-circle', 'help manual guide how to faq support'),
    ('Backup & restore', 'backup_page', 'bi-cloud-arrow-up', 'backup restore onedrive google drive cloud copy'),
    ('Report a problem', 'support_page', 'bi-bug', 'bug report problem error support feedback'),
    ('Setup wizard', 'welcome_step', 'bi-magic', 'welcome setup wizard start onboarding'),
    ('Features & accounts', 'features_page', 'bi-toggles', 'features turn on off modules savings cards demat business add missing account'),
    ('Demat check (CDSL / NSDL)', 'demat_page', 'bi-shield-check', 'demat cdsl nsdl depository cas reconcile reconciliation'),
    ('Asset types', 'asset_types_page', 'bi-tags', 'equity etf reit invit bonds mutual funds'),
    ('Users & security', 'users_page', 'bi-shield-lock', 'users password security lock recovery'),
    ('Add Statements', 'import_page', 'bi-cloud-upload', 'import upload statements pdf'),
    ('Categories', 'categories', 'bi-tags', 'categories heads'), ('Payee rules', 'rules_page', 'bi-magic', 'rules payee rename'),
    ('People & entities', 'people_page', 'bi-people', 'people entities family business'), ('Passwords', 'passwords_page', 'bi-key', 'passwords pdf'),
]


def search(con, q):
    q = (q or '').strip()
    ql = q.lower()
    res = []
    try:
        import features
        hidden_eps = features.hidden(con)[0]
    except Exception:  # noqa: BLE001
        hidden_eps = set()
    for title, ep, icon, kw in PAGES:
        if ep in hidden_eps:
            continue
        if not q or ql in title.lower() or ql in kw:
            res.append({'group': 'Pages', 'title': title, 'sub': '', 'url': url_for(ep), 'icon': icon})
    if not q:
        return res[:8]
    like = f'%{q}%'
    for a in con.execute("SELECT id, name, bank, card_no, kind FROM accounts WHERE name LIKE ? OR bank LIKE ? OR card_no LIKE ? "
                         "OR subtype LIKE ? LIMIT 6", (like, like, like, like)):
        k = AH.KIND.get(a['kind'], AH.KIND['bank'])
        res.append({'group': 'Accounts', 'title': a['name'], 'sub': f"{k['short']} · {a['bank'] or ''}", 'url': url_for('account_detail', acc_id=a['id']), 'icon': k['icon']})
    for l in con.execute('SELECT id, name, lender FROM loans WHERE name LIKE ? OR lender LIKE ? OR purchase_desc LIKE ? LIMIT 4', (like, like, like)):
        res.append({'group': 'Loans & EMIs', 'title': l['name'], 'sub': l['lender'] or '', 'url': url_for('accounts', tab='emi') + f'#loan-{l["id"]}', 'icon': 'bi-calendar2-check'})
    for t in con.execute("SELECT id, date, amount, type, account, COALESCE(NULLIF(display_name,''), description) AS d FROM transactions "
                         "WHERE description LIKE ? OR display_name LIKE ? OR payee LIKE ? OR notes LIKE ? OR CAST(amount AS TEXT) LIKE ? "
                         "ORDER BY date DESC LIMIT 8", (like, like, like, like, f'{q.replace(",", "")}%')):
        res.append({'group': 'Transactions', 'title': t['d'][:60], 'sub': f"{t['date']} · {t['account']} · {'−' if t['type'] == 'debit' else '+'}₹{t['amount']:,.0f}",
                    'url': url_for('transactions', search=q, start='2000-01-01', end='2099-12-31'), 'icon': 'bi-receipt'})
    import classifier as _C
    _paths = None
    for c in con.execute('SELECT id, name, level FROM categories WHERE name LIKE ? AND level >= 2 ORDER BY level LIMIT 6', (like,)):
        _paths = _paths or _C.load_tree(con)[1]
        res.append({'group': 'Categories', 'title': c['name'], 'sub': _paths[c['id']]['short_path'] if c['id'] in _paths else '',
                    'url': url_for('transactions', cat=c['id'], start='2000-01-01', end='2099-12-31'), 'icon': 'bi-tag'})
    try:
        for s in con.execute('SELECT id, symbol, name FROM inv_securities WHERE symbol LIKE ? OR name LIKE ? LIMIT 4', (like, like)):
            res.append({'group': 'Stocks', 'title': s['name'] or s['symbol'], 'sub': s['symbol'], 'url': url_for('inv_stock', sid=s['id']), 'icon': 'bi-graph-up-arrow'})
    except Exception:  # noqa: BLE001
        pass
    for r in con.execute("SELECT name, amount, freq FROM recurring WHERE status='active' AND (name LIKE ? OR notes LIKE ?) LIMIT 4", (like, like)):
        res.append({'group': 'Recurring', 'title': r['name'], 'sub': f"₹{r['amount']:,.0f} {FREQS.get(r['freq'], ('',))[0].lower()}",
                    'url': url_for('recurring_page'), 'icon': 'bi-arrow-repeat'})
    for p in con.execute('SELECT name FROM people WHERE name LIKE ? LIMIT 3', (like,)):
        res.append({'group': 'People', 'title': p['name'], 'sub': 'spending by this person',
                    'url': url_for('transactions', person=p['name'], start='2000-01-01', end='2099-12-31'), 'icon': 'bi-person'})
    return res


# ── routes ───────────────────────────────────────────────────────────────────
def register(app, get_db):

    def recurring_page():
        con = get_db()
        rows = recurring_rows(con, ('active',))
        ended = recurring_rows(con, ('ended',))
        ignored = con.execute("SELECT * FROM recurring WHERE status='ignored' ORDER BY name").fetchall()
        sug = detect(con)
        accts = [r['name'] for r in con.execute("SELECT name FROM accounts WHERE COALESCE(status,'active')='active' ORDER BY name")]
        out_rows = [r for r in rows if r['rtype'] != 'income']
        by_type = defaultdict(float)
        for r in out_rows:
            by_type[dict(RTYPES).get(r['rtype'], 'Other')] += r['monthly']
        return render_template('recurring.html', rows=rows, ended=ended, ignored=ignored, sug=sug, accts=accts,
                               FREQS=FREQS, RTYPES=RTYPES, monthly=sum(r['monthly'] for r in out_rows),
                               income=sum(r['monthly'] for r in rows if r['rtype'] == 'income'),
                               by_type=sorted(by_type.items(), key=lambda x: -x[1]), today=date.today())

    def recurring_save():
        con = get_db()
        f = request.form
        rid = AH._i(f.get('id'))
        data = {'name': f.get('name', '').strip() or 'Payment', 'amount': AH._f(f.get('amount')),
                'freq': f.get('freq') if f.get('freq') in FREQS else 'monthly', 'next_date': f.get('next_date') or date.today().isoformat(),
                'account': f.get('account', ''), 'rtype': f.get('rtype', 'other'), 'notes': f.get('notes', '').strip()}
        if f.get('match_key'):
            data['match_key'] = f.get('match_key')
        if f.get('category_id'):
            data['category_id'] = AH._i(f.get('category_id'))
        if rid:
            con.execute(f"UPDATE recurring SET {', '.join(k + '=?' for k in data)} WHERE id=?", (*data.values(), rid))
        else:
            data['source'] = f.get('source', 'manual')
            data['status'] = 'active'
            con.execute(f"INSERT INTO recurring ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))
        con.commit()
        flash(f"Saved {data['name']}.", 'success')
        return redirect(url_for('recurring_page'))

    def recurring_confirm_all():
        con = get_db()
        keys = request.form.getlist('key')
        n = 0
        for s in detect(con):
            if s['key'] in keys:
                con.execute("INSERT INTO recurring (name, match_key, amount, freq, next_date, account, category_id, rtype, status, source) "
                            "VALUES (?,?,?,?,?,?,?,?, 'active', 'detected')",
                            (s['name'], s['key'], s['amount'], s['freq'], s['next'].isoformat(), s['account'], s['category_id'], s['rtype']))
                n += 1
        con.commit()
        flash(f'{n} recurring payment{"s" if n != 1 else ""} added.', 'success')
        return redirect(url_for('recurring_page'))

    def recurring_ignore():
        con = get_db()
        con.execute("INSERT INTO recurring (name, match_key, status, source) VALUES (?,?, 'ignored', 'detected')",
                    (request.form.get('name', '')[:60], request.form.get('key', '')))
        con.commit()
        flash('Ignored — it will not be suggested again.', 'info')
        return redirect(url_for('recurring_page'))

    def recurring_status(rid):
        con = get_db()
        act = request.form.get('action')
        if act == 'delete':
            con.execute('DELETE FROM recurring WHERE id=?', (rid,))
        else:
            con.execute('UPDATE recurring SET status=? WHERE id=?', ({'end': 'ended', 'restore': 'active'}.get(act, 'active'), rid))
        con.commit()
        return redirect(url_for('recurring_page'))

    def budgets_page():
        con = get_db()
        today = date.today()
        ym = request.args.get('m', today.strftime('%Y-%m'))
        try:
            ms = datetime.strptime(ym + '-01', '%Y-%m-%d').date()
        except ValueError:
            ms = today.replace(day=1)
        rows = budget_rows(con, ms)
        _, by_id = C.load_tree(con)
        heads = sorted((n for n in by_id.values() if n['level'] == 2 and n['kind'] == 'expense'), key=lambda n: n['path'])
        months = [AH.add_months(today.replace(day=1), -i, 1) for i in range(0, 12)]
        tb = sum(r['budget'] or 0 for r in rows)
        ts = sum(r['spent'] for r in rows if r['budget'])
        return render_template('budgets.html', rows=rows, heads=heads, ms=ms, months=months, total_budget=tb,
                               total_spent=ts, unbudgeted=sum(r['spent'] for r in rows if not r['budget']),
                               is_current=ms == today.replace(day=1), today=today,
                               m_end=(AH.add_months(ms, 1, 1) - timedelta(days=1)).isoformat(),
                               days_left=(AH.add_months(ms, 1, 1) - today).days)

    def budgets_save():
        con = get_db()
        for k, v in request.form.items():
            if k.startswith('b_'):
                cid = AH._i(k[2:])
                amt = AH._f(v, None)
                if cid is None:
                    continue
                if amt:
                    con.execute('INSERT INTO budgets (category_id, amount) VALUES (?,?) ON CONFLICT(category_id) DO UPDATE SET amount=excluded.amount', (cid, amt))
                else:
                    con.execute('DELETE FROM budgets WHERE category_id=?', (cid,))
        con.commit()
        flash('Budgets saved.', 'success')
        return redirect(url_for('budgets_page', m=request.form.get('m') or None))

    def budgets_suggest():
        """Set each Head's budget to its 3-month average (rounded up to the next ₹500)."""
        con = get_db()
        ms = date.today().replace(day=1)
        p3 = AH.add_months(ms, -3, 1).isoformat()
        prev3, by_id = head_spend(con, p3, ms.isoformat())
        nm = max(months_with_data(con, p3, ms.isoformat()), 1)
        n = 0
        for cid, v in prev3.items():
            avg = v / nm
            if by_id.get(cid, {}).get('name') in ('Uncategorised',):
                continue
            if avg >= 500 and not con.execute('SELECT 1 FROM budgets WHERE category_id=?', (cid,)).fetchone():
                con.execute('INSERT INTO budgets (category_id, amount) VALUES (?,?)', (cid, -(-avg // 500) * 500))
                n += 1
        con.commit()
        flash(f'{n} budgets suggested from your last 3 months — adjust them as you like.' if n else
              'No new suggestions (needs spending history without a budget).', 'info')
        return redirect(url_for('budgets_page'))

    def tools_page():
        con = get_db()
        b = AH.build(con, *AH_fy())
        cards = [a for a in b['groups']['card'] if a['status'] == 'active']
        today = date.today()
        inc = con.execute("SELECT COALESCE(SUM(CASE WHEN t.type='credit' THEN t.amount ELSE -t.amount END),0) "
                          "FROM transactions t JOIN categories c ON c.id=t.category_id WHERE c.kind='income' AND t.date>=?",
                          ((today - timedelta(days=92)).isoformat(),)).fetchone()[0] or 0
        months_with = con.execute("SELECT COUNT(DISTINCT substr(date,1,7)) FROM transactions WHERE date>=?",
                                  ((today - timedelta(days=92)).isoformat(),)).fetchone()[0] or 1
        loans = [l for l in b['loans'] if l.get('status') == 'active' and l['outstanding_now'] > 0]
        for l in loans:
            l['interest_left'] = est_interest(l)
        loans.sort(key=lambda l: -(l.get('interest_rate') or 0))
        lim = sum(a['limit'] for a in cards if a.get('limit'))
        out = sum(a['outstanding'] for a in cards if a.get('limit'))
        return render_template('tools.html', b=b, cards=cards, best=best_cards(b), loans=loans,
                               util_all=round(100 * out / lim, 1) if lim else None, tot_limit=lim, tot_out=out,
                               income_m=inc / max(months_with, 1), today=today,
                               loans_json=json.dumps([{'id': l['id'], 'name': l['name'], 'out': round(l['outstanding_now'], 2),
                                                       'rate': l.get('interest_rate') or 0, 'emi': l.get('emi_amount') or 0,
                                                       'bullet': l['bullet']} for l in loans]))

    def AH_fy():
        today = date.today()
        y = today.year if today.month >= 4 else today.year - 1
        return f'{y}-04-01', f'{y + 1}-03-31'

    def alerts_page():
        con = get_db()
        b = AH.build(con)
        rec = recurring_for_dues(con, b)
        up = AH.dues(con, b, days=30, recurring=rec)
        cash = AH.cash_position(b, up)
        al = alerts(con, b, up, cash)
        today = date.today()
        last_m = AH.add_months(today.replace(day=1), -1, 1)
        snoozed = con.execute('SELECT * FROM alert_state WHERE snoozed_until >= ? ORDER BY snoozed_until', (today.isoformat(),)).fetchall()
        return render_template('alerts.html', alerts=al, close=month_close_status(con, b, last_m), snoozed=snoozed, today=today)

    def alert_snooze():
        con = get_db()
        days = AH._i(request.form.get('days'), 7)
        until = (date.today() + timedelta(days=days)).isoformat()
        con.execute('INSERT INTO alert_state (key, snoozed_until) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET snoozed_until=excluded.snoozed_until',
                    (request.form.get('key', ''), until))
        con.commit()
        if request.accept_mimetypes.best == 'application/json' or request.is_json:
            return jsonify({'ok': True})
        nxt = request.form.get('next') or ''
        return redirect(nxt if nxt.startswith('/') else url_for('alerts_page'))

    def alert_unsnooze():
        con = get_db()
        con.execute('DELETE FROM alert_state WHERE key=?', (request.form.get('key', ''),))
        con.commit()
        return redirect(url_for('alerts_page'))

    def month_close_page():
        con = get_db()
        today = date.today()
        ym = request.args.get('m') or AH.add_months(today.replace(day=1), -1, 1).strftime('%Y-%m')
        try:
            ms = datetime.strptime(ym + '-01', '%Y-%m-%d').date()
        except ValueError:
            ms = AH.add_months(today.replace(day=1), -1, 1)
        b = AH.build(con)
        st = month_close_status(con, b, ms)
        months = [AH.add_months(today.replace(day=1), -i, 1) for i in range(0, 12)]
        closed = {r['month']: r['at'] for r in con.execute("SELECT month, at FROM month_close WHERE item='_closed'")}
        d = None
        import organise
        me = AH.add_months(ms, 1, 1)
        d = organise.dashboard_data(con, f"date >= '{ms.isoformat()}' AND date < '{me.isoformat()}'",
                                    f"date >= '{ms.isoformat()}' AND date < '{me.isoformat()}'")
        return render_template('month_close.html', st=st, months=months, closed=closed, ms=ms, d=d,
                               budgets=[r for r in budget_rows(con, ms) if r['budget']][:8])

    def month_close_tick():
        con = get_db()
        m, item = request.form.get('month', ''), request.form.get('item', '')
        if request.form.get('done') == '1':
            con.execute('INSERT OR REPLACE INTO month_close (month, item, done, note) VALUES (?,?,1,?)', (m, item, request.form.get('note', '')))
            if item == '_closed':
                AH.record_snapshot(con, AH.build(con))
        else:
            con.execute('DELETE FROM month_close WHERE month=? AND item=?', (m, item))
        con.commit()
        if item == '_closed':
            flash(f"{datetime.strptime(m, '%Y-%m').strftime('%B %Y')} closed." if request.form.get('done') == '1' else 'Month re-opened.', 'success')
        return redirect(url_for('month_close_page', m=m))

    def api_search():
        return jsonify(search(get_db(), request.args.get('q', '')))

    def api_alert_count():
        con = get_db()
        b = AH.build(con)
        up = AH.dues(con, b, days=30, recurring=recurring_for_dues(con, b))
        al = alerts(con, b, up, AH.cash_position(b, up))
        return jsonify({'n': len(al), 'urgent': sum(1 for a in al if a['level'] == 'danger')})

    for rule, ep, fn, methods in [
        ('/recurring', 'recurring_page', recurring_page, ['GET']),
        ('/recurring/save', 'recurring_save', recurring_save, ['POST']),
        ('/recurring/confirm', 'recurring_confirm_all', recurring_confirm_all, ['POST']),
        ('/recurring/ignore', 'recurring_ignore', recurring_ignore, ['POST']),
        ('/recurring/<int:rid>/status', 'recurring_status', recurring_status, ['POST']),
        ('/budgets', 'budgets_page', budgets_page, ['GET']),
        ('/budgets/save', 'budgets_save', budgets_save, ['POST']),
        ('/budgets/suggest', 'budgets_suggest', budgets_suggest, ['POST']),
        ('/tools', 'tools_page', tools_page, ['GET']),
        ('/alerts', 'alerts_page', alerts_page, ['GET']),
        ('/alerts/snooze', 'alert_snooze', alert_snooze, ['POST']),
        ('/alerts/unsnooze', 'alert_unsnooze', alert_unsnooze, ['POST']),
        ('/month-close', 'month_close_page', month_close_page, ['GET']),
        ('/month-close/tick', 'month_close_tick', month_close_tick, ['POST']),
        ('/api/search', 'api_search', api_search, ['GET']),
        ('/api/alerts/count', 'api_alert_count', api_alert_count, ['GET']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)


def est_interest(l):
    """Interest still to pay on a reducing-balance loan at its current EMI (approximate)."""
    p, r, e = l['outstanding_now'] or 0, (l.get('interest_rate') or 0) / 1200, l.get('emi_amount') or 0
    if l['bullet']:
        end = l.get('next_due')
        if end and r:
            months = max((end - date.today()).days / 30.4, 0)
            return p * r * months
        return 0
    if not (p and r and e) or e <= p * r:
        return None
    import math
    n = -math.log(1 - p * r / e) / math.log(1 + r)
    return max(n * e - p, 0)
