"""Finance Hub 1.2 — asset types for holdings (equity, ETF, MF, REIT, InvIT, bonds …) and broker-wise views.

Types are found automatically from the ISIN and the name; anything that fits no type gets a suggestion for a new
type (e.g. Warrants, Rights entitlement) that you can add with one click. You can always change a holding's type.
"""
import re
from collections import defaultdict

from flask import render_template, request, redirect, url_for, flash

import scope as SC

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_asset_types (
    key TEXT PRIMARY KEY, label TEXT NOT NULL, tone TEXT DEFAULT 'slate', sort_order INTEGER DEFAULT 50,
    builtin INTEGER DEFAULT 0, keywords TEXT DEFAULT '');
"""
BUILTIN = [  # key, label, tone, order
    ('equity', 'Equity shares', 'indigo', 1), ('etf', 'ETFs', 'teal', 2), ('mf', 'Mutual funds', 'violet', 3),
    ('reit', 'REITs', 'coral', 4), ('invit', 'InvITs', 'amber', 5), ('bond', 'Bonds & NCDs', 'blue', 6),
    ('gsec', 'Govt. securities (G-Sec / SDL / T-Bill)', 'green', 7), ('sgb', 'Sovereign Gold Bonds', 'amber', 8),
    ('pref', 'Preference shares', 'pink', 9), ('other', 'Other', 'slate', 99),
]
REIT_NAMES = r'EMBASSY OFFICE|MINDSPACE|BROOKFIELD INDIA|NEXUS SELECT|KNOWLEDGE REALTY|\bREIT\b|REAL ESTATE INV'
INVIT_NAMES = r'INDIGRID|INDIA GRID|POWERGRID INFRA|PGINVIT|IRB INVIT|INDUS INFRA|CUBE HIGHWAYS|NHAI INVIT|\bINVIT\b|INFRASTRUCTURE INV|ENERGY INFRA'
ETF_NAMES = r'\bETF\b|BEES\b|BEES$|\bIETF\b|ETF$|GOLDBEES|NIFTYBEES|BANKBEES|LIQUIDBEES|SILVERBEES|MON100|MAFANG|ICICIB22|CPSEETF'
SUGGEST_NEW = [  # pattern, suggested key, label
    (r'\bWARRANT', 'warrant', 'Warrants'), (r'\bRE\b|RIGHTS? ENTITLE|-RE$|RIGHTS', 'rights', 'Rights entitlements'),
    (r'PARTLY PAID|PARTLYPAID|\bPP\b', 'partly', 'Partly-paid shares'), (r'\bADR\b|\bGDR\b|\bNASDAQ\b|\bNYSE\b|US STOCK', 'foreign', 'Foreign stocks'),
    (r'\bAIF\b|ALTERNATIVE INVESTMENT', 'aif', 'AIFs'), (r'\bPMS\b|PORTFOLIO MANAGEMENT', 'pms', 'PMS'),
    (r'\bCP\b|COMMERCIAL PAPER', 'cp', 'Commercial paper'), (r'\bFD\b|FIXED DEPOSIT', 'fd', 'Corporate FDs'),
]


def ensure_schema(con):
    con.executescript(SCHEMA)
    for key, label, tone, order in BUILTIN:
        con.execute('INSERT OR IGNORE INTO inv_asset_types (key, label, tone, sort_order, builtin) VALUES (?,?,?,?,1)',
                    (key, label, tone, order))
    have = {r[1] for r in con.execute('PRAGMA table_info(inv_securities)')}
    for col, decl in (('asset_type', 'TEXT'), ('asset_type_manual', 'INTEGER DEFAULT 0')):
        if col not in have:
            con.execute(f'ALTER TABLE inv_securities ADD COLUMN {col} {decl}')
    classify_all(con)
    con.commit()


def classify(isin, name, symbol, custom=()):
    """→ (type key or None, reason, suggestion (key, label) or None)."""
    isin = (isin or '').upper().strip()
    text = f'{name or ""} {symbol or ""}'.upper()
    for key, kws in custom:                 # your own types first (keywords you gave them)
        if kws and re.search(kws, text):
            return key, 'matches your keywords', None
    if re.search(r'\bSGB\b|SOVEREIGN GOLD|GOLDBOND|SGBMAR|SGBAUG|SGBJUN|SGBDEC|SGBSEP|SGBFEB|SGBNOV|SGBJAN|SGBOCT|SGBJUL|SGBMAY|SGBAPR', text):
        return 'sgb', 'Sovereign Gold Bond', None
    if isin.startswith('IN00') or isin.startswith(('IN1', 'IN2', 'IN3')) or re.search(r'\bGOI\b|\bG-?SEC\b|\bSDL\b|T-?BILL|\bTB\d', text):
        return 'gsec', 'government security ISIN / name', None
    if re.search(REIT_NAMES, text) or (isin.startswith('INE') and isin[7:9] == '25'):
        return 'reit', 'REIT units (ISIN type 25 / name)', None
    if re.search(INVIT_NAMES, text) or (isin.startswith('INE') and isin[7:9] == '23'):
        return 'invit', 'InvIT units (ISIN type 23 / name)', None
    if re.search(ETF_NAMES, text):
        return 'etf', 'ETF in the name', None
    if isin.startswith('INF'):
        return ('etf', 'fund ISIN with ETF name', None) if 'ETF' in text else ('mf', 'mutual fund ISIN (INF…)', None)
    for pat, k, label in SUGGEST_NEW:
        if re.search(pat, text):
            return None, f'looks like {label.lower()}', (k, label)
    if isin.startswith('INE'):
        code = isin[7:9]
        if code == '01':
            return 'equity', 'equity share ISIN (type 01)', None
        if code == '04':
            return 'pref', 'preference share ISIN (type 04)', None
        if code in ('07', '08', '09', '11', '12', '13'):
            return 'bond', f'debt ISIN (type {code})', None
        if re.search(r'NCD|BOND|DEBENTURE|\d+(\.\d+)?%', text):
            return 'bond', 'NCD / bond in the name', None
        return None, f'unknown ISIN security type {code}', None
    if re.search(r'NCD|BOND|DEBENTURE', text):
        return 'bond', 'NCD / bond in the name', None
    if not isin:
        return 'equity', 'no ISIN — assumed a listed share', None
    return None, 'no rule matched', None


def custom_types(con):
    return [(r['key'], r['keywords']) for r in con.execute("SELECT key, keywords FROM inv_asset_types WHERE builtin=0 AND keywords<>''")]


def classify_all(con, force=False):
    cust = custom_types(con)
    for s in con.execute('SELECT id, isin, name, symbol, asset_type, asset_type_manual FROM inv_securities').fetchall():
        if s['asset_type_manual'] and not force:
            continue
        key, _, _ = classify(s['isin'], s['name'], s['symbol'], cust)
        if key != s['asset_type']:
            con.execute('UPDATE inv_securities SET asset_type=? WHERE id=?', (key, s['id']))


def types(con):
    return [dict(r) for r in con.execute('SELECT * FROM inv_asset_types ORDER BY sort_order, label')]


def suggestions(con):
    """Holdings without a type and the new types the Hub suggests for them."""
    out = defaultdict(list)
    unknown = []
    have = {r['key'] for r in con.execute('SELECT key FROM inv_asset_types')}
    for s in con.execute('SELECT id, isin, name, symbol FROM inv_securities WHERE asset_type IS NULL OR asset_type=""').fetchall():
        key, why, sug = classify(s['isin'], s['name'], s['symbol'])
        if sug and sug[0] not in have:
            out[sug].append(dict(s))
        else:
            unknown.append({**dict(s), 'why': why})
    return [{'key': k, 'label': l, 'items': v} for (k, l), v in out.items()], unknown


def broker_groups(con, broker=None):
    """Holdings per broker (quantity bought − sold through that broker) valued at the latest price."""
    import investments as inv
    secs = {r['id']: r for r in con.execute('SELECT * FROM inv_securities')}
    tmap = {t['key']: t for t in types(con)}
    hold = inv.latest_holdings(con)
    groups = []
    q = 'SELECT * FROM inv_brokers' + (' WHERE id=?' if broker else '') + ' ORDER BY name'
    for b in con.execute(q, (broker,) if broker else ()):
        pos = inv.positions(con, b['id'])
        rows = []
        for sid, p in pos.items():
            if p['qty'] <= 0.0001:
                continue
            s = secs.get(sid)
            h = hold.get(sid)
            cmp_ = (s['cmp'] if s and s['cmp'] else None) or (h['close'] if h and h.get('close') else None) or p['avg']
            t = tmap.get(s['asset_type'] if s else None)
            rows.append({'id': sid, 'name': (s['name'] or s['symbol']) if s else '?', 'symbol': s['symbol'] if s else '',
                         'type': s['asset_type'] if s else None, 'type_label': t['label'] if t else 'Not set',
                         'tone': t['tone'] if t else 'slate', 'qty': p['qty'], 'avg': p['avg'], 'cmp': cmp_,
                         'invested': p['qty'] * p['avg'], 'value': p['qty'] * cmp_, 'pnl': p['qty'] * (cmp_ - p['avg']),
                         'realised': p['realised']})
        trades = con.execute("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN side='buy' THEN qty*price END),0) buys, "
                             "COALESCE(SUM(CASE WHEN side='sell' THEN qty*price END),0) sells, COALESCE(SUM(charges),0) ch, "
                             "MIN(trade_date) first, MAX(trade_date) last FROM inv_trades WHERE broker_id=?", (b['id'],)).fetchone()
        rows.sort(key=lambda r: -r['value'])
        groups.append({'id': b['id'], 'name': b['name'], 'client_id': b['client_id'], 'rows': rows,
                       'value': sum(r['value'] for r in rows), 'invested': sum(r['invested'] for r in rows),
                       'pnl': sum(r['pnl'] for r in rows), 'realised': sum(p['realised'] for p in pos.values()),
                       'trades': trades['n'], 'buys': trades['buys'], 'sells': trades['sells'], 'charges': trades['ch'],
                       'first': trades['first'], 'last': trades['last']})
    return groups


def by_type(rows, tmap):
    agg = defaultdict(lambda: {'value': 0.0, 'invested': 0.0, 'n': 0})
    for r in rows:
        a = agg[r.get('asset_type') or r.get('type') or '']
        a['value'] += r['value']; a['invested'] += r['invested']; a['n'] += 1
    total = sum(a['value'] for a in agg.values()) or 1
    out = []
    for k, a in agg.items():
        t = tmap.get(k)
        out.append({'key': k, 'label': t['label'] if t else 'Not set', 'tone': t['tone'] if t else 'slate',
                    'value': a['value'], 'invested': a['invested'], 'n': a['n'], 'pct': 100 * a['value'] / total})
    return sorted(out, key=lambda x: -x['value'])


def register(app, get_db):

    def asset_types_page():
        con = get_db()
        classify_all(con)
        con.commit()
        sug, unknown = suggestions(con)
        counts = dict(con.execute('SELECT asset_type, COUNT(*) FROM inv_securities GROUP BY asset_type').fetchall())
        secs = con.execute('SELECT id, symbol, name, isin, asset_type, asset_type_manual FROM inv_securities ORDER BY name').fetchall()
        cust = custom_types(con)
        why = {s['id']: classify(s['isin'], s['name'], s['symbol'], cust)[1] for s in secs}
        return render_template('asset_types.html', types=types(con), sug=sug, unknown=unknown, counts=counts, secs=secs, why=why)

    def asset_type_save():
        con = get_db()
        f = request.form
        key = re.sub(r'[^a-z0-9_]', '', (f.get('key') or f.get('label', '')).lower().replace(' ', '_'))[:24]
        if not key or not f.get('label'):
            flash('Give the type a name.', 'warning')
            return redirect(url_for('asset_types_page'))
        kws = f.get('keywords', '').strip()
        if kws:
            try:
                re.compile(kws)
            except re.error:
                kws = '|'.join(re.escape(w.strip().upper()) for w in kws.split(',') if w.strip())
        con.execute('INSERT INTO inv_asset_types (key, label, tone, sort_order, builtin, keywords) VALUES (?,?,?,?,0,?) '
                    'ON CONFLICT(key) DO UPDATE SET label=excluded.label, tone=excluded.tone, keywords=excluded.keywords',
                    (key, f.get('label').strip(), f.get('tone') or 'slate', 60, kws.upper()))
        for sid in f.getlist('ids'):
            con.execute('UPDATE inv_securities SET asset_type=?, asset_type_manual=1 WHERE id=?', (key, int(sid)))
        classify_all(con)
        con.commit()
        flash(f"Asset type “{f.get('label').strip()}” saved.", 'success')
        return redirect(url_for('asset_types_page'))

    def asset_type_delete():
        con = get_db()
        key = request.form.get('key')
        row = con.execute('SELECT builtin FROM inv_asset_types WHERE key=?', (key,)).fetchone()
        if not row:
            flash('That asset type no longer exists.', 'info')
        elif row[0]:
            flash('Built-in types cannot be removed.', 'warning')
        else:
            con.execute('UPDATE inv_securities SET asset_type=NULL, asset_type_manual=0 WHERE asset_type=?', (key,))
            con.execute('DELETE FROM inv_asset_types WHERE key=?', (key,))
            classify_all(con)
            con.commit()
        return redirect(url_for('asset_types_page'))

    def asset_set():
        con = get_db()
        sid, key = int(request.form['sid']), request.form.get('asset_type') or None
        if key == '__auto__':
            con.execute('UPDATE inv_securities SET asset_type_manual=0 WHERE id=?', (sid,))
            classify_all(con)
        else:
            con.execute('UPDATE inv_securities SET asset_type=?, asset_type_manual=1 WHERE id=?', (key, sid))
        con.commit()
        from webutil import safe_next
        return redirect(safe_next(request.form.get('next'), url_for('asset_types_page')))

    def brokers_page():
        con = get_db()
        bid = SC.broker_id() or (int(request.args['broker']) if request.args.get('broker', '').isdigit() else None)
        groups = broker_groups(con, bid)
        tmap = {t['key']: t for t in types(con)}
        allrows = [dict(r, asset_type=r['type']) for g in groups for r in g['rows']]
        return render_template('inv_brokers.html', groups=groups, mix=by_type(allrows, tmap), sel=bid,
                               brokers=con.execute('SELECT id, name FROM inv_brokers ORDER BY name').fetchall(),
                               total=sum(g['value'] for g in groups))

    for rule, ep, fn, methods in [
        ('/investments/types', 'asset_types_page', asset_types_page, ['GET']),
        ('/investments/types/save', 'asset_type_save', asset_type_save, ['POST']),
        ('/investments/types/delete', 'asset_type_delete', asset_type_delete, ['POST']),
        ('/investments/types/set', 'asset_set', asset_set, ['POST']),
        ('/investments/brokers', 'inv_brokers_page', brokers_page, ['GET']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)
