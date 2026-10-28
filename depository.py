"""Finance Hub 1.4 — demat accounts at the depositories (CDSL / NSDL) and their reconciliation with each broker.

CDSL and NSDL are not brokers: they hold the securities. Each demat account (DP ID + client ID, or the 16-digit CDSL BO ID)
is opened through a depository participant — usually the broker — so every broker normally has one demat account.

Reconciliation, per demat account and per broker:
  depository quantity (latest CAS / holding statement of that demat)
  vs quantity from the broker's trades that had SETTLED by the statement date (T+1, weekends skipped)
  vs the broker's own holdings statement (when one was imported).
Differences are explained where possible: trades still settling, sales or purchases not imported, bonus / split,
securities bought elsewhere (IPO, transfer-in) or moved out.
"""
import re
from collections import defaultdict
from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, flash

OLD_CAS_BROKER = 'CAS (CDSL / NSDL)'
DEPOSITORIES = ('CDSL', 'NSDL')
EPS = 0.001

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_demats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    depository TEXT NOT NULL,              -- CDSL / NSDL
    dp_name TEXT, dp_id TEXT, client_id TEXT,
    account_no TEXT UNIQUE NOT NULL,       -- CDSL: 16-digit BO ID; NSDL: IN + 6 digits + 8-digit client ID
    holder TEXT, broker_id INTEGER, notes TEXT, created_at TEXT DEFAULT (datetime('now')));
"""

# DP names → broker names (generic; the user's own brokers are also matched by name)
DP_HINTS = (('zerodha', 'Zerodha'), ('rksv', 'Upstox'), ('upstox', 'Upstox'), ('sbicap', 'SBI Securities'),
            ('sbi securities', 'SBI Securities'))


def ensure_schema(con):
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute('PRAGMA table_info(inv_holdings)')]
    if cols and 'demat_id' not in cols:
        con.execute('ALTER TABLE inv_holdings ADD COLUMN demat_id INTEGER')
    icols = [r[1] for r in con.execute('PRAGMA table_info(inv_imports)')]
    if icols and 'demat_id' not in icols:
        con.execute('ALTER TABLE inv_imports ADD COLUMN demat_id INTEGER')
    _migrate_old_cas_broker(con)
    con.commit()


def _migrate_old_cas_broker(con):
    """Up to 1.3 a CAS was imported as if it came from a broker called 'CAS (CDSL / NSDL)'. Move those holdings to a
    depository account and drop the fake broker."""
    r = con.execute('SELECT id FROM inv_brokers WHERE name=?', (OLD_CAS_BROKER,)).fetchone()
    if not r:
        return
    bid = r[0]
    if con.execute('SELECT 1 FROM inv_holdings WHERE broker_id=?', (bid,)).fetchone():
        did = con.execute("INSERT OR IGNORE INTO inv_demats (depository, dp_name, account_no, notes) VALUES "
                          "('CDSL / NSDL', 'From an earlier CAS', 'EARLIER-CAS', 'Account number was not read in earlier versions — "
                          "import the CAS again to split it by demat account.')").lastrowid or \
            con.execute("SELECT id FROM inv_demats WHERE account_no='EARLIER-CAS'").fetchone()[0]
        con.execute("UPDATE inv_holdings SET demat_id=?, broker_id=NULL, source='depository' WHERE broker_id=?", (did, bid))
    con.execute('UPDATE inv_imports SET broker_id=NULL WHERE broker_id=?', (bid,))
    if not con.execute('SELECT 1 FROM inv_trades WHERE broker_id=?', (bid,)).fetchone():
        con.execute('UPDATE inv_instructions SET broker_id=NULL WHERE broker_id=?', (bid,))
        con.execute('DELETE FROM inv_brokers WHERE id=?', (bid,))


# ── account numbers ──────────────────────────────────────────────────────────
def norm_account(depository='', dp_id='', client_id='', bo_id=''):
    """→ (depository, dp_id, client_id, account_no) or None."""
    d = lambda s: re.sub(r'\D', '', s or '')
    bo = d(bo_id)
    dp = re.sub(r'\s', '', (dp_id or '')).upper()
    cl = d(client_id)
    if len(bo) == 16:
        return 'CDSL', bo[:8], bo[8:], bo
    if re.fullmatch(r'IN\d{6}', dp) and len(cl) == 8:
        return 'NSDL', dp, cl, dp + cl
    if re.fullmatch(r'\d{8}', dp) and len(cl) == 8:
        return 'CDSL', dp, cl, dp + cl
    if (depository or '').upper() in DEPOSITORIES and (dp or cl):
        return depository.upper(), dp, cl, (dp + cl) or None
    return None


def masked(acct):
    acct = acct or ''
    return ('•••• ' + acct[-4:]) if len(acct) > 6 and acct[-4:].isdigit() else acct


def label(d):
    if not d:
        return ''
    dp = (d['dp_name'] or '').strip()
    return f"{d['depository']} · {dp + ' · ' if dp else ''}{masked(d['account_no'])}"


def guess_broker(con, dp_name, account_no=''):
    brokers = con.execute('SELECT id, name, demat_id, client_id FROM inv_brokers').fetchall()
    for b in brokers:                                   # the broker's own demat number, if typed on the broker
        num = re.sub(r'\D', '', b['demat_id'] or '')
        if num and account_no and (account_no.endswith(num) or num.endswith(re.sub(r'\D', '', account_no)[-8:])):
            return b['id']
    low = (dp_name or '').lower()
    for b in brokers:
        if b['name'] and b['name'].lower() in low:
            return b['id']
    for key, name in DP_HINTS:
        if key in low:
            b = next((x for x in brokers if x['name'] == name), None)
            if b:
                return b['id']
    return None


def find_or_create(con, acct):
    n = norm_account(acct.get('depository', ''), acct.get('dp_id', ''), acct.get('client_id', ''), acct.get('bo_id', ''))
    if not n:
        return None
    dep, dp, cl, no = n
    r = con.execute('SELECT * FROM inv_demats WHERE account_no=?', (no,)).fetchone()
    if r:
        if acct.get('dp_name') and not r['dp_name']:
            con.execute('UPDATE inv_demats SET dp_name=? WHERE id=?', (acct['dp_name'][:80], r['id']))
        if r['broker_id'] is None:
            b = guess_broker(con, acct.get('dp_name') or r['dp_name'], no)
            if b:
                con.execute('UPDATE inv_demats SET broker_id=? WHERE id=?', (b, r['id']))
        return r['id']
    return con.execute('INSERT INTO inv_demats (depository, dp_name, dp_id, client_id, account_no, holder, broker_id) '
                       'VALUES (?,?,?,?,?,?,?)', (dep, (acct.get('dp_name') or '')[:80], dp, cl, no, (acct.get('holder') or '')[:80],
                                                   guess_broker(con, acct.get('dp_name'), no))).lastrowid


# ── reading a CAS / depository holding statement ────────────────────────────
ISIN_RE = re.compile(r'\b(IN[EF0-9][A-Z0-9]{8}\d)\b')
BO_RE = re.compile(r'BO\s*ID\s*[:\-.]?\s*(\d{16})', re.I)
DPID_RE = re.compile(r'DP\s*ID\s*[:\-.]?\s*(IN\s?\d{6}|\d{8})', re.I)
CLID_RE = re.compile(r'CLIENT\s*ID\s*[:\-.]?\s*(\d{8})', re.I)
COMBO_RE = re.compile(r'\b(IN\d{6})\s*[-/ ]\s*(\d{8})\b')
DPNAME_RE = re.compile(r'DP\s*NAME\s*[:\-.]?\s*(.+?)(?=\s+(?:DP\s*ID|BO\s*ID|CLIENT\s*ID)\b|$)', re.I)
DATE_RE = r'([0-9]{1,2}[- ][A-Za-z]{3}[- ][0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4}|[0-9]{2}-[0-9]{2}-[0-9]{4})'


def _qty_price_value(nums):
    """CDSL lines: current bal, frozen, pledged …, price, value. NSDL lines: face value, qty, price, value.
    Pick the quantity that makes qty × price ≈ value."""
    if len(nums) >= 3:
        price, value = nums[-2], nums[-1]
        for c in nums[:-2]:
            if c > 0 and abs(c * price - value) <= max(1.0, 0.005 * abs(value)):
                return c, price, value
        return nums[0], price, value
    if len(nums) == 2:
        return nums[0], (nums[1] / nums[0] if nums[0] else 0), nums[1]
    return (nums[0], 0, 0) if nums else (0, 0, 0)


def parse_text(text, num=None, to_date=None, symbol_from_name=None):
    """→ {kind 'depository', as_of, holdings[{… acct}], demats[acct], warnings[]}"""
    import investments as inv
    num = num or inv._num
    to_date = to_date or inv._date
    symbol_from_name = symbol_from_name or inv._symbol_from_name
    as_of = ''
    for pat in (r'for the period.*?to\s*' + DATE_RE, r'(?:as on|as of|as at|holding as on|statement date)\s*[:\-]?\s*' + DATE_RE):
        m = re.search(pat, text, re.I)
        if m:
            as_of = to_date(m.group(1).replace(' ', '-'))
            if as_of:
                break
    holdings, accts, cur, pending_name, since_name = [], {}, None, '', 99
    for line in text.splitlines():
        up = line.upper()
        nm = DPNAME_RE.search(line)
        if nm:
            pending_name, since_name = nm.group(1).strip(' :-')[:80], 0
        else:
            since_name += 1
        bo, dp, cl, combo = BO_RE.search(line), DPID_RE.search(line), CLID_RE.search(line), COMBO_RE.search(line)
        acct = None
        if bo:
            acct = {'bo_id': bo.group(1)}
        elif dp and cl:
            acct = {'dp_id': dp.group(1), 'client_id': cl.group(1)}
        elif combo and ('DP' in up or 'CLIENT' in up or 'ACCOUNT' in up):
            acct = {'dp_id': combo.group(1), 'client_id': combo.group(2)}
        if acct:
            n = norm_account('', acct.get('dp_id', ''), acct.get('client_id', ''), acct.get('bo_id', ''))
            if n:
                acct = {'depository': n[0], 'dp_id': n[1], 'client_id': n[2], 'account_no': n[3],
                        'dp_name': pending_name if since_name <= 4 else ''}
                cur = accts.setdefault(n[3], acct)
                if acct['dp_name'] and not cur['dp_name']:
                    cur['dp_name'] = acct['dp_name']
                continue
        if ('FOLIO NO' in up or 'MUTUAL FUND FOLIO' in up or 'MF FOLIO' in up) and not ISIN_RE.search(line):
            cur = None                                     # units held in folios (not in demat) — not compared here
            continue
        im = ISIN_RE.search(line)
        if not im or not cur:
            continue
        toks = line[im.end():].split()
        isnum = [bool(re.fullmatch(r'-?[\d,]*\d(?:\.\d+)?', t)) for t in toks]
        cut = len(toks)
        while cut > 0 and isnum[cut - 1]:
            cut -= 1                                       # the name ends where the trailing numbers start
        name_part = ' '.join(toks[:cut])
        nums = [num(t) for t in toks[cut:]]
        qty, price, value = _qty_price_value(nums)
        if qty <= 0:
            continue
        name = re.sub(r'\s{2,}', ' ', name_part).strip(' -#*')[:60]
        holdings.append({'symbol': symbol_from_name(name) if name else im.group(1), 'isin': im.group(1), 'name': name.title(),
                         'qty': qty, 'avg_cost': 0, 'close': price, 'value': value, 'sector': '',
                         'acct': cur['account_no'], 'raw': line.strip()[:160]})
    warnings = []
    if not accts:
        warnings.append('No demat account number (DP ID / client ID / BO ID) found — choose the demat account before importing.')
    if holdings:
        warnings.append('Depository statement reading is new — compare a few quantities with the statement before importing.')
    else:
        warnings.append('No holdings with an ISIN found in a demat-account section of this statement.')
    return {'kind': 'depository' if holdings else 'info', 'as_of': as_of or date.today().isoformat(),
            'holdings': holdings, 'demats': list(accts.values()), 'warnings': warnings}


def commit(con, meta, demat_override=None):
    """Store depository holdings. Rows for the same demat and date are replaced (an NSDL and a CDSL CAS both list
    every demat account, so importing both must not count them twice)."""
    import investments as inv
    pv = meta['pv']
    ids = {}
    for a in pv.get('demats', []):
        ids[a['account_no']] = find_or_create(con, a)
    iid = con.execute('INSERT INTO inv_imports (file_name, file_hash, broker_id, kind, as_of, rows, demat_id) VALUES (?,?,?,?,?,?,?)',
                      (meta['file'], meta['hash'], None, 'depository', pv['as_of'], len(pv['holdings']), demat_override)).lastrowid
    rows = defaultdict(list)
    for h in pv['holdings']:
        did = demat_override or ids.get(h.get('acct'))
        if did:
            rows[did].append(h)
    added = 0
    for did, hs in rows.items():
        con.execute("DELETE FROM inv_holdings WHERE demat_id=? AND as_of=?", (did, pv['as_of']))
        for h in hs:
            sid = inv.security_id(con, h['symbol'], h['isin'], h.get('name', ''))
            if h.get('close'):
                con.execute("UPDATE inv_securities SET cmp=?, cmp_date=?, cmp_source='statement' WHERE id=? AND "
                            "(cmp IS NULL OR cmp_source<>'manual' OR COALESCE(cmp_date,'')<=?)", (h['close'], pv['as_of'], sid, pv['as_of']))
            con.execute('INSERT INTO inv_holdings (import_id, broker_id, source, as_of, security_id, qty, avg_cost, close_price, value, demat_id) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?)', (iid, None, 'depository', pv['as_of'], sid, h['qty'], 0, h.get('close') or 0,
                                                         h.get('value') or 0, did))
            added += 1
    con.execute('UPDATE inv_imports SET added=? WHERE id=?', (added, iid))
    return added


# ── reconciliation ───────────────────────────────────────────────────────────
def _next_bday(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def settles_by(trade_date, as_of):
    """Equity settles T+1 (exchange holidays are not known — a trade the day before a holiday may show as in transit)."""
    try:
        return _next_bday(date.fromisoformat(trade_date[:10])) <= date.fromisoformat(as_of[:10])
    except ValueError:
        return True


def demat_holdings(con, did):
    r = con.execute('SELECT MAX(as_of) FROM inv_holdings WHERE demat_id=?', (did,)).fetchone()
    as_of = r[0] if r else None
    out = defaultdict(lambda: {'qty': 0.0, 'close': 0.0})
    if as_of:
        for h in con.execute('SELECT security_id, qty, close_price FROM inv_holdings WHERE demat_id=? AND as_of=?', (did, as_of)):
            o = out[h['security_id']]
            o['qty'] += h['qty'] or 0
            o['close'] = h['close_price'] or o['close']
    return as_of, dict(out)


def broker_trades(con, broker_id, as_of):
    """Net quantity per security: settled by as_of, still settling on as_of, and traded after as_of."""
    settled, transit, after = defaultdict(float), defaultdict(float), defaultdict(int)
    for t in con.execute('SELECT security_id, trade_date, side, qty FROM inv_trades WHERE broker_id=?', (broker_id,)):
        q = t['qty'] if t['side'] == 'buy' else -t['qty']
        if as_of and t['trade_date'] > as_of:
            after[t['security_id']] += 1
        elif not as_of or settles_by(t['trade_date'], as_of):
            settled[t['security_id']] += q
        else:
            transit[t['security_id']] += q
    return settled, transit, after


def broker_statement(con, broker_id):
    r = con.execute('SELECT MAX(as_of) FROM inv_holdings WHERE broker_id=? AND demat_id IS NULL', (broker_id,)).fetchone()
    if not r or not r[0]:
        return None, {}
    out = defaultdict(float)
    for h in con.execute('SELECT security_id, qty FROM inv_holdings WHERE broker_id=? AND demat_id IS NULL AND as_of=?', (broker_id, r[0])):
        out[h['security_id']] += h['qty'] or 0
    return r[0], dict(out)


def _ratio_hint(a, b):
    if a > 0 and b > 0:
        for r, txt in ((2, 'bonus 1:1 or split 1:2'), (3, 'bonus 2:1'), (5, 'split 1:5'), (10, 'split 1:10'),
                       (1.5, 'bonus 1:2'), (4, 'split 1:4')):
            if abs(a / b - r) < 1e-6:
                return f'demat holds {r:g}× — looks like a {txt}; add the extra shares on the Trades page as a buy at price 0'
            if abs(b / a - r) < 1e-6:
                return f'demat holds 1/{r:g} — check for a consolidation, or sales not imported'
    return ''


def compare(con, dep, as_of, broker_id, secs, prices):
    """Rows for one demat (or one broker's demats added together) against that broker."""
    settled, transit, after = broker_trades(con, broker_id, as_of) if broker_id else ({}, {}, {})
    bst_date, bst = broker_statement(con, broker_id) if broker_id else (None, {})
    keys = set(dep) | {k for k, v in settled.items() if abs(v) > EPS} | {k for k, v in transit.items() if abs(v) > EPS} | \
        {k for k, v in bst.items() if v > EPS}
    rows = []
    for sid in keys:
        d = dep.get(sid, {}).get('qty', 0.0) if isinstance(dep.get(sid), dict) else dep.get(sid, 0.0)
        s, tr, b = settled.get(sid, 0.0), transit.get(sid, 0.0), bst.get(sid)
        sec = secs.get(sid)
        price = (dep.get(sid, {}).get('close') if isinstance(dep.get(sid), dict) else 0) or prices.get(sid) or 0
        if not broker_id:
            status, tone, hint = 'no broker linked', 'slate', 'link this demat to its broker to compare'
        elif abs(d - s) < EPS:
            status, tone = 'matches', 'green'
            hint = f'{tr:+g} still settling' if abs(tr) > EPS else ''
        elif abs(tr) > EPS and abs(d - (s + tr)) < EPS:
            status, tone, hint = 'matches', 'green', 'includes trades of the statement day'
        elif s <= EPS and d > EPS:
            status, tone, hint = 'not in broker trades', 'amber', ('bought elsewhere, IPO / rights / transfer-in, or contract notes '
                                                                   'not imported yet')
        elif d <= EPS and s > EPS:
            status, tone, hint = 'missing in demat', 'red', ('sold or moved out (sale not imported?), pledged to another account, '
                                                             'or held in a different demat')
        else:
            status, tone = 'quantity differs', 'red'
            hint = _ratio_hint(d, s) or ('buys not imported' if d > s else 'sales not imported, or shares moved out')
        if b is not None and abs(b - d) > EPS and status == 'matches':
            status, tone, hint = 'broker statement differs', 'amber', f'broker holdings statement ({bst_date}) shows {b:g}'
        if after.get(sid):
            hint = (hint + '; ' if hint else '') + f'{after[sid]} trade(s) after the statement date not counted'
        rows.append({'id': sid, 'name': (sec['name'] or sec['symbol']) if sec else '?', 'isin': sec['isin'] if sec else '',
                     'demat': d, 'trades': s, 'transit': tr, 'bstmt': b, 'diff': d - s if broker_id else 0.0,
                     'price': price, 'value': d * price, 'diff_value': (d - s) * price if broker_id else 0.0,
                     'status': status, 'tone': tone, 'hint': hint})
    order = {'red': 0, 'amber': 1, 'slate': 2, 'green': 3}
    rows.sort(key=lambda r: (order[r['tone']], -abs(r['diff_value']), r['name']))
    return rows, bst_date


def _summary(rows):
    c = defaultdict(int)
    for r in rows:
        c[r['tone']] += 1
    return {'ok': c['green'], 'warn': c['amber'], 'bad': c['red'], 'unlinked': c['slate'], 'n': len(rows),
            'value': sum(r['value'] for r in rows), 'diff_value': sum(abs(r['diff_value']) for r in rows if r['tone'] != 'green')}


def reconcile(con, broker_filter=None):
    secs = {r['id']: r for r in con.execute('SELECT * FROM inv_securities')}
    prices = {k: (v['cmp'] or 0) for k, v in secs.items()}
    brokers = {r['id']: r for r in con.execute('SELECT * FROM inv_brokers ORDER BY name')}
    demats = con.execute('SELECT * FROM inv_demats ORDER BY depository, dp_name, account_no').fetchall()
    by_account = []
    linked = defaultdict(list)
    for d in demats:
        if broker_filter and d['broker_id'] != broker_filter:
            continue
        as_of, dep = demat_holdings(con, d['id'])
        rows, bst = compare(con, dep, as_of, d['broker_id'], secs, prices)
        g = {'id': d['id'], 'demat': d, 'label': label(d), 'masked': masked(d['account_no']), 'as_of': as_of,
             'broker': brokers[d['broker_id']]['name'] if d['broker_id'] in brokers else '', 'broker_id': d['broker_id'],
             'rows': rows, 's': _summary(rows), 'bst_date': bst, 'has_holdings': bool(dep)}
        by_account.append(g)
        if d['broker_id']:
            linked[d['broker_id']].append((d, as_of, dep))
    by_broker = []
    for bid, b in brokers.items():
        if broker_filter and bid != broker_filter:
            continue
        has_trades = con.execute('SELECT 1 FROM inv_trades WHERE broker_id=? LIMIT 1', (bid,)).fetchone()
        ds = linked.get(bid, [])
        if not ds and not has_trades:
            continue
        dep = defaultdict(lambda: {'qty': 0.0, 'close': 0.0})
        dates = [a for _, a, _ in ds if a]
        for _, _, hs in ds:
            for sid, h in hs.items():
                dep[sid]['qty'] += h['qty']
                dep[sid]['close'] = h['close'] or dep[sid]['close']
        as_of = min(dates) if dates else None
        if ds and dates:
            rows, bst = compare(con, dict(dep), as_of, bid, secs, prices)
        else:
            rows, bst = [], None
        by_broker.append({'id': bid, 'name': b['name'], 'demats': [{'id': d['id'], 'label': label(d), 'as_of': a} for d, a, _ in ds],
                          'as_of': as_of, 'mixed_dates': len(set(dates)) > 1, 'rows': rows, 's': _summary(rows),
                          'bst_date': bst, 'no_demat': not ds, 'no_statement': bool(ds) and not dates})
    return by_account, by_broker, list(brokers.values())


# ── pages ────────────────────────────────────────────────────────────────────
def register(app, get_db):

    def con_():
        import investments as inv
        c = get_db()
        inv.ensure_schema(c)
        return c

    def demat_page():
        import scope as SC
        con = con_()
        view = request.args.get('view', 'account')
        acc, brk, brokers = reconcile(con, SC.broker_id())
        tot = {'accounts': len(acc), 'value': sum(g['s']['value'] for g in acc),
               'bad': sum(g['s']['bad'] for g in acc), 'warn': sum(g['s']['warn'] for g in acc),
               'ok': sum(g['s']['ok'] for g in acc), 'unlinked': sum(1 for g in acc if not g['broker_id'])}
        return render_template('demat.html', acc=acc, brk=brk, brokers=brokers, view=view, tot=tot,
                               edit=con.execute('SELECT * FROM inv_demats WHERE id=?', (request.args.get('edit', type=int),)).fetchone())

    def demat_save():
        con = con_()
        f = request.form
        bid = f.get('broker_id', type=int) or None
        did = f.get('id', type=int)
        if did and f.get('action') == 'link':
            con.execute('UPDATE inv_demats SET broker_id=? WHERE id=?', (bid, did))
            con.commit()
            flash('Broker linked.' if bid else 'Broker link removed.', 'success')
            return redirect(url_for('demat_page', view=f.get('view', 'account')))
        n = norm_account(f.get('depository', ''), f.get('dp_id', ''), f.get('client_id', ''), f.get('bo_id', ''))
        if not n or not n[3]:
            flash('Enter the 16-digit BO ID (CDSL), or the DP ID (IN + 6 digits for NSDL, 8 digits for CDSL) and the 8-digit client ID.', 'warning')
            return redirect(url_for('demat_page', edit=did) if did else url_for('demat_page'))
        dep, dp, cl, no = n
        vals = (dep, f.get('dp_name', '').strip()[:80], dp, cl, no, f.get('holder', '').strip()[:80], bid, f.get('notes', '').strip()[:200])
        try:
            if did:
                con.execute('UPDATE inv_demats SET depository=?, dp_name=?, dp_id=?, client_id=?, account_no=?, holder=?, broker_id=?, notes=? '
                            'WHERE id=?', vals + (did,))
            else:
                con.execute('INSERT INTO inv_demats (depository, dp_name, dp_id, client_id, account_no, holder, broker_id, notes) '
                            'VALUES (?,?,?,?,?,?,?,?)', vals)
            con.commit()
            flash('Demat account saved.', 'success')
        except Exception:  # noqa: BLE001
            con.rollback()
            flash('That demat account already exists.', 'warning')
        return redirect(url_for('demat_page'))

    def demat_delete(did):
        con = con_()
        imports = [r[0] for r in con.execute('SELECT DISTINCT import_id FROM inv_holdings WHERE demat_id=? AND import_id IS NOT NULL', (did,))]
        con.execute('DELETE FROM inv_holdings WHERE demat_id=?', (did,))
        con.execute('DELETE FROM inv_demats WHERE id=?', (did,))
        for iid in imports:          # 1.6: so the same statement can be imported again later
            if not con.execute('SELECT 1 FROM inv_holdings WHERE import_id=?', (iid,)).fetchone():
                con.execute('DELETE FROM inv_imports WHERE id=?', (iid,))
        con.commit()
        flash('Demat account and its statement holdings removed.', 'info')
        return redirect(url_for('demat_page'))

    def report_demat(fmt):
        import scope as SC
        import reports_hub as RH
        con = con_()
        acc, brk, _ = reconcile(con, SC.broker_id())
        cols = ['Security', 'ISIN', 'Demat qty', 'Broker trades qty', 'Still settling', 'Broker statement qty', 'Difference',
                'Price', 'Demat value', 'Status', 'Note']

        def rws(g, lead):
            return [lead + (r['name'], r['isin'], r['demat'], r['trades'], r['transit'], '' if r['bstmt'] is None else r['bstmt'],
                            r['diff'], r['price'], r['value'], r['status'], r['hint']) for r in g['rows']]
        rep = {'title': f'Demat reconciliation — {RH.scope_label()}',
               'subtitle': 'depository (CDSL / NSDL) holdings vs broker trades settled by the statement date (T+1)', 'sections': [
            {'title': 'Summary', 'kind': 'table', 'columns': ['Demat account', 'Broker', 'As on', 'Securities', 'Match', 'Check', 'Differ',
                                                               'Demat value', 'Value of differences'],
             'money': ['Demat value', 'Value of differences'],
             'rows': [(g['label'], g['broker'] or 'not linked', g['as_of'] or '—', g['s']['n'], g['s']['ok'], g['s']['warn'], g['s']['bad'],
                       g['s']['value'], g['s']['diff_value']) for g in acc]},
            {'title': 'By demat account', 'kind': 'table', 'columns': ['Demat account', 'Broker', 'As on'] + cols,
             'money': ['Price', 'Demat value'], 'rows': [x for g in acc for x in rws(g, (g['label'], g['broker'] or 'not linked', g['as_of'] or ''))]},
            {'title': 'By broker', 'kind': 'table', 'columns': ['Broker', 'Demat accounts', 'As on'] + cols, 'money': ['Price', 'Demat value'],
             'rows': [x for g in brk for x in rws(g, (g['name'], ', '.join(d['label'] for d in g['demats']) or 'no demat linked', g['as_of'] or ''))]},
        ]}
        return RH.send(rep, fmt, f'demat_reconciliation_{date.today()}')

    for rule, ep, fn, methods in [
        ('/investments/demat', 'demat_page', demat_page, ['GET']),
        ('/investments/demat/save', 'demat_save', demat_save, ['POST']),
        ('/investments/demat/<int:did>/delete', 'demat_delete', demat_delete, ['POST']),
        ('/report/demat/<fmt>', 'report_demat', report_demat, ['GET']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)
