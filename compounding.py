"""Finance Hub — Wealth planner: the Compounding Calculator (v1.11) rebuilt inside the Hub.

The maths is the calculator's own tested engine, `static/planner/calculator.js` (unchanged), run in the
browser. This module stores users, plans, goals and year-end records in finance.db and fills the Annual
review from the Hub's own portfolio.

Data
  cc_users    user_id, name, start_year, params (JSON, % as shown on screen), goal (JSON), created/updated
  cc_actuals  user_id, year (plan year 1…60), invested, core_value, sat_value, recorded_at, source
Compatible with the standalone app's database file / export (format 2): import merges (newer updatedAt
wins), export writes the same format so the desktop app can open it.
"""
import json
import re
from datetime import datetime, date

from flask import render_template, request, jsonify, Response

SCHEMA = """
CREATE TABLE IF NOT EXISTS cc_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    start_year INTEGER,
    params     TEXT,
    goal       TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cc_actuals (
    user_id     TEXT NOT NULL,
    year        INTEGER NOT NULL,
    invested    REAL,
    core_value  REAL,
    sat_value   REAL,
    total_value REAL,
    recorded_at TEXT,
    source      TEXT DEFAULT 'manual',
    PRIMARY KEY (user_id, year)
);
"""
APP_VERSION = '1.11'          # engine version (static/planner/calculator.js)
ID_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,31}$')


def default_params():
    return {'selfLump': 100000, 'selfMonthly': 10000, 'selfInclude': True,
            'selfStepUpOn': True, 'selfStepUp': 10, 'selfStepUpMode': 'pct', 'selfStepUpAmt': 1000,
            'selfStepUpStop': 10, 'selfAddStop': 10, 'selfAddStopMonths': 0,
            'coreAlloc': 70, 'coreRet': 15.0, 'satRet': 25.0, 'horizon': 30,
            'spouseInclude': False, 'spouseLump': 0, 'spouseMonthly': 0,
            'spouseStepUpOn': True, 'spouseStepUp': 10, 'spouseStepUpMode': 'pct', 'spouseStepUpAmt': 1000,
            'spouseStepUpStop': 10, 'spouseAddStop': 10, 'spouseAddStopMonths': 0}


def default_goal():
    return {'target': 100000000, 'years': 20, 'assumedReturn': None}


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def slugify(s):
    s = re.sub(r'\s+', '.', str(s or '').lower().strip())
    s = re.sub(r'[^a-z0-9._-]', '', s).strip('._-')
    return s[:32]


def ensure_schema(con):
    con.executescript(SCHEMA)
    if not con.execute('SELECT COUNT(*) FROM cc_users').fetchone()[0]:
        t = now_iso()
        con.execute('INSERT INTO cc_users VALUES (?,?,?,?,?,?,?)',
                    ('me', 'Me', date.today().year, json.dumps(default_params()), json.dumps(default_goal()), t, t))
    con.commit()


def user_dict(con, row):
    acts = {}
    for a in con.execute('SELECT * FROM cc_actuals WHERE user_id=? ORDER BY year', (row['user_id'],)):
        rec = {'invested': a['invested'], 'coreValue': a['core_value'], 'satValue': a['sat_value'],
               'recordedAt': a['recorded_at'], 'source': a['source']}
        if a['total_value'] is not None:
            rec['totalValue'] = a['total_value']
        acts[str(a['year'])] = rec
    params = default_params()
    params.update(json.loads(row['params'] or '{}'))
    goal = default_goal()
    goal.update(json.loads(row['goal'] or '{}'))
    return {'id': row['user_id'], 'userId': row['user_id'], 'name': row['name'], 'startYear': row['start_year'],
            'params': params, 'goal': goal, 'actualsHistory': acts,
            'createdAt': row['created_at'], 'updatedAt': row['updated_at']}


def all_users(con):
    return {r['user_id']: user_dict(con, r) for r in con.execute('SELECT * FROM cc_users ORDER BY name')}


def _touch(con, uid):
    con.execute('UPDATE cc_users SET updated_at=? WHERE user_id=?', (now_iso(), uid))


def save_user(con, u, keep_times=False):
    """Insert or replace a whole user record (params, goal, actuals) — used by import."""
    uid = u['userId']
    t = now_iso()
    con.execute('INSERT OR REPLACE INTO cc_users VALUES (?,?,?,?,?,?,?)',
                (uid, u['name'], int(u.get('startYear') or date.today().year),
                 json.dumps({**default_params(), **(u.get('params') or {})}),
                 json.dumps({**default_goal(), **(u.get('goal') or {})}),
                 (u.get('createdAt') if keep_times else None) or t, (u.get('updatedAt') if keep_times else None) or t))
    con.execute('DELETE FROM cc_actuals WHERE user_id=?', (uid,))
    for y, rec in (u.get('actualsHistory') or {}).items():
        try:
            yr = int(y)
        except ValueError:
            continue
        con.execute('INSERT INTO cc_actuals VALUES (?,?,?,?,?,?,?,?)',
                    (uid, yr, rec.get('invested'), rec.get('coreValue'), rec.get('satValue'), rec.get('totalValue'),
                     rec.get('recordedAt') or t, rec.get('source') or 'manual'))


# ── Fill the Annual review from the Hub ──────────────────────────────────────
def fy_bounds(start_year, plan_year):
    """Plan year y = Indian financial year starting April of (startYear + y − 1)."""
    a = int(start_year) + int(plan_year) - 1
    return f'{a}-04-01', f'{a + 1}-03-31', f'{a}–{str((a + 1) % 100).zfill(2)}'


def hub_figures(con, start_year, plan_year):
    """Amount invested in the year and the year-end Core / Satellite values, from Investments."""
    import investments as inv
    inv.ensure_schema(con)
    start, end, label = fy_bounds(start_year, plan_year)
    today = date.today().isoformat()
    flows = con.execute("SELECT COALESCE(SUM(CASE WHEN side='buy' THEN qty*price+COALESCE(charges,0) "
                        "ELSE -(qty*price-COALESCE(charges,0)) END),0), COUNT(*) FROM inv_trades "
                        "WHERE trade_date BETWEEN ? AND ?", (start, end)).fetchone()
    # holdings at the end of the year (trades up to then; for the current year: today)
    cutoff = min(end, today)
    qty = {}
    for t in con.execute('SELECT security_id, side, qty FROM inv_trades WHERE trade_date<=? ORDER BY trade_date, id', (cutoff,)):
        q = qty.get(t['security_id'], 0.0) + (t['qty'] if t['side'] == 'buy' else -t['qty'])
        qty[t['security_id']] = max(0.0, q)
    if not qty:                               # no trades yet → latest holdings statements
        for sid, h in inv.latest_holdings(con).items():
            qty[sid] = h['qty'] or h['cas_qty'] or 0.0
    core = sat = unset = 0.0
    unset_names, priced_today = [], False
    for sid, q in qty.items():
        if q <= 0:
            continue
        s = con.execute('SELECT symbol, name, bucket, cmp FROM inv_securities WHERE id=?', (sid,)).fetchone()
        if not s:
            continue
        price = s['cmp']
        if not price:
            r = con.execute('SELECT price FROM inv_trades WHERE security_id=? AND trade_date<=? ORDER BY trade_date DESC, id DESC LIMIT 1',
                            (sid, cutoff)).fetchone()
            price = r['price'] if r else 0
        v = q * (price or 0)
        priced_today = True
        if s['bucket'] == 'core':
            core += v
        elif s['bucket'] == 'satellite':
            sat += v
        else:
            unset += v
            unset_names.append(s['name'] or s['symbol'])
    notes = []
    if end < today:
        notes.append('valued at the latest prices in the Hub, not the prices on 31 March — adjust if you have the year-end values')
    elif cutoff == today:
        notes.append(f'year not finished: holdings and prices as of today ({date.today().strftime("%d %b %Y")})')
    if unset:
        notes.append(f'₹{unset:,.0f} in stocks without Core / Satellite is not included ({", ".join(unset_names[:5])}'
                     f'{"…" if len(unset_names) > 5 else ""}) — set it on each stock’s page')
    if not flows[1]:
        notes.append('no trades in this year — amount invested left blank')
    return {'period': label, 'from': start, 'to': end, 'invested': round(flows[0], 2) if flows[1] else None,
            'trades': flows[1], 'coreValue': round(core, 2), 'satValue': round(sat, 2), 'unassigned': round(unset, 2),
            'notes': notes, 'hasHoldings': bool(core or sat or unset)}


def register(app, get_db):

    def con_():
        c = get_db()
        ensure_schema(c)
        return c

    def page():
        con = con_()
        users = all_users(con)
        return render_template('planner.html', users=users, app_version=APP_VERSION)

    def api_users():
        return jsonify(all_users(con_()))

    def api_user_create():
        con = con_()
        d = request.get_json(force=True) or {}
        name = (d.get('name') or '').strip()
        uid = slugify(d.get('userId') or name)
        if not name:
            return jsonify({'ok': False, 'msg': 'Name required'}), 400
        if not ID_RE.match(uid):
            return jsonify({'ok': False, 'msg': 'User ID: 2–32 lowercase letters, digits, dot, dash or underscore'}), 400
        if con.execute('SELECT 1 FROM cc_users WHERE user_id=?', (uid,)).fetchone():
            return jsonify({'ok': False, 'msg': f'User ID “{uid}” is taken'}), 400
        params = d.get('params') or default_params()
        tpl = d.get('template')
        if tpl and tpl != '__default__':
            r = con.execute('SELECT params FROM cc_users WHERE user_id=?', (tpl,)).fetchone()
            if r:
                params = json.loads(r['params'])
        t = now_iso()
        goal = {**default_goal(), **(d.get('goal') or {})}
        con.execute('INSERT INTO cc_users VALUES (?,?,?,?,?,?,?)',
                    (uid, name, int(d.get('startYear') or date.today().year), json.dumps(params), json.dumps(goal), t, t))
        con.commit()
        return jsonify({'ok': True, 'user': user_dict(con, con.execute('SELECT * FROM cc_users WHERE user_id=?', (uid,)).fetchone())})

    def api_user_update(uid):
        con = con_()
        row = con.execute('SELECT * FROM cc_users WHERE user_id=?', (uid,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'msg': 'User not found'}), 404
        d = request.get_json(force=True) or {}
        new_id = slugify(d.get('userId') or uid)
        if new_id != uid:
            if not ID_RE.match(new_id):
                return jsonify({'ok': False, 'msg': 'User ID: 2–32 lowercase letters, digits, dot, dash or underscore'}), 400
            if con.execute('SELECT 1 FROM cc_users WHERE user_id=?', (new_id,)).fetchone():
                return jsonify({'ok': False, 'msg': f'User ID “{new_id}” is taken'}), 400
            con.execute('UPDATE cc_users SET user_id=? WHERE user_id=?', (new_id, uid))
            con.execute('UPDATE cc_actuals SET user_id=? WHERE user_id=?', (new_id, uid))
            uid = new_id
        if 'name' in d and (d['name'] or '').strip():
            con.execute('UPDATE cc_users SET name=? WHERE user_id=?', (d['name'].strip(), uid))
        if 'startYear' in d and d['startYear']:
            con.execute('UPDATE cc_users SET start_year=? WHERE user_id=?', (int(d['startYear']), uid))
        if 'params' in d:
            con.execute('UPDATE cc_users SET params=? WHERE user_id=?', (json.dumps(d['params']), uid))
        if 'goal' in d:
            con.execute('UPDATE cc_users SET goal=? WHERE user_id=?', (json.dumps({**default_goal(), **d['goal']}), uid))
        _touch(con, uid)
        con.commit()
        return jsonify({'ok': True, 'user': user_dict(con, con.execute('SELECT * FROM cc_users WHERE user_id=?', (uid,)).fetchone())})

    def api_user_delete(uid):
        con = con_()
        con.execute('DELETE FROM cc_actuals WHERE user_id=?', (uid,))
        con.execute('DELETE FROM cc_users WHERE user_id=?', (uid,))
        con.commit()
        return jsonify({'ok': True})

    def api_actual_save(uid, year):
        con = con_()
        if not con.execute('SELECT 1 FROM cc_users WHERE user_id=?', (uid,)).fetchone():
            return jsonify({'ok': False, 'msg': 'User not found'}), 404
        d = request.get_json(force=True) or {}

        def num(k):
            v = d.get(k)
            if v in (None, ''):
                return None
            v = float(v)
            if v < 0:
                raise ValueError
            return v
        try:
            inv_, cv, sv = num('invested'), num('coreValue'), num('satValue')
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'msg': 'Values must be numbers of ₹0 or more'}), 400
        if cv is None or sv is None:
            return jsonify({'ok': False, 'msg': f'Enter both the core and the satellite value for year {year}'}), 400
        con.execute('INSERT OR REPLACE INTO cc_actuals VALUES (?,?,?,?,?,?,?,?)',
                    (uid, year, inv_, cv, sv, None, now_iso(), d.get('source') or 'manual'))
        _touch(con, uid)
        con.commit()
        return jsonify({'ok': True})

    def api_actual_delete(uid, year):
        con = con_()
        con.execute('DELETE FROM cc_actuals WHERE user_id=? AND year=?', (uid, year))
        _touch(con, uid)
        con.commit()
        return jsonify({'ok': True})

    def api_actuals_clear(uid):
        con = con_()
        con.execute('DELETE FROM cc_actuals WHERE user_id=?', (uid,))
        _touch(con, uid)
        con.commit()
        return jsonify({'ok': True})

    def api_hub_figures(uid, year):
        con = con_()
        row = con.execute('SELECT start_year FROM cc_users WHERE user_id=?', (uid,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'msg': 'User not found'}), 404
        return jsonify({'ok': True, **hub_figures(con, row['start_year'], year)})

    def api_export():
        con = con_()
        data = {'app': 'Compounding Calculator', 'format': 2, 'appVersion': APP_VERSION, 'savedAt': now_iso(),
                'source': 'Finance Hub', 'users': all_users(con), 'deleted': {}}
        return Response(json.dumps(data, indent=2), mimetype='application/json',
                        headers={'Content-Disposition': f'attachment;filename=compounding-users-{date.today().isoformat()}.json'})

    def api_import():
        con = con_()
        f = request.files.get('file')
        try:
            raw = json.loads(f.read().decode('utf-8-sig')) if f else (request.get_json(force=True) or {})
        except Exception:  # noqa: BLE001
            return jsonify({'ok': False, 'msg': 'Not a JSON file from the Compounding Calculator'}), 400
        src = raw.get('users') if isinstance(raw, dict) and isinstance(raw.get('users'), dict) else raw
        if not isinstance(src, dict):
            return jsonify({'ok': False, 'msg': 'No users found in this file'}), 400
        added = updated = kept = 0
        for key, u in src.items():
            if not isinstance(u, dict) or not u.get('name'):
                continue
            uid = u.get('userId') or slugify(str(key).replace('profile_', '')) or slugify(u['name'])
            if not ID_RE.match(uid):
                uid = slugify(u['name'])
            if not ID_RE.match(uid or ''):
                continue
            u = dict(u, userId=uid)
            if not u.get('startYear'):
                try:
                    u['startYear'] = int(str(u.get('createdAt') or '')[:4])
                except ValueError:
                    u['startYear'] = date.today().year
            row = con.execute('SELECT updated_at FROM cc_users WHERE user_id=?', (uid,)).fetchone()
            if row and (row['updated_at'] or '') >= (u.get('updatedAt') or ''):
                kept += 1
                continue
            save_user(con, u, keep_times=True)
            if row:
                updated += 1
            else:
                added += 1
        con.commit()
        return jsonify({'ok': True, 'msg': f'{added} user(s) added, {updated} updated, {kept} kept (the Hub copy was newer or the same).'})

    routes = [
        ('/planner', 'planner', page, ['GET']),
        ('/api/cc/users', 'cc_users', api_users, ['GET']),
        ('/api/cc/users', 'cc_user_create', api_user_create, ['POST']),
        ('/api/cc/users/<uid>', 'cc_user_update', api_user_update, ['PUT']),
        ('/api/cc/users/<uid>', 'cc_user_delete', api_user_delete, ['DELETE']),
        ('/api/cc/users/<uid>/actuals/<int:year>', 'cc_actual_save', api_actual_save, ['PUT']),
        ('/api/cc/users/<uid>/actuals/<int:year>', 'cc_actual_delete', api_actual_delete, ['DELETE']),
        ('/api/cc/users/<uid>/actuals', 'cc_actuals_clear', api_actuals_clear, ['DELETE']),
        ('/api/cc/users/<uid>/hub/<int:year>', 'cc_hub_figures', api_hub_figures, ['GET']),
        ('/planner/export', 'cc_export', api_export, ['GET']),
        ('/planner/import', 'cc_import', api_import, ['POST']),
    ]
    for rule, ep, fn, methods in routes:
        app.add_url_rule(rule, ep, fn, methods=methods)
