"""Finance Hub 1.2 — the global “Viewing” filter (book / account / card / broker) shown in the top bar.

Every page reads the same choice (kept in the browser session):
  book    : '' (all books) / 'Personal' / your company …   — entities whose role is 'book'
  account : one Hub account (bank, card, loan …) by name
  broker  : one inv_brokers id
Transactions belong to a book through their entity (set from the account's book when imported).
"""
from flask import session, request, redirect, url_for

ROLES = [('book', 'Book (keeps its own accounts)'), ('payer', 'Client / payer'), ('other', 'Other')]


def ensure_schema(con):
    have = {r[1] for r in con.execute('PRAGMA table_info(entities)')}
    if 'role' not in have:
        con.execute("ALTER TABLE entities ADD COLUMN role TEXT DEFAULT 'book'")
    if 'aliases' not in have:
        con.execute("ALTER TABLE entities ADD COLUMN aliases TEXT DEFAULT ''")
    con.execute("INSERT OR IGNORE INTO entities (name, role) VALUES ('Personal', 'book')")
    con.commit()


def books(con):
    return [r[0] for r in con.execute("SELECT name FROM entities WHERE COALESCE(role,'book')='book' "
                                      "ORDER BY name<>'Personal', sort_order, name")]


def current():
    s = session.get('scope') or {}
    return {'book': s.get('book', ''), 'account': s.get('account', ''), 'broker': s.get('broker', ''),
            'broker_name': s.get('broker_name', ''), 'label': s.get('label', '')}


def active():
    c = current()
    return bool(c['book'] or c['account'] or c['broker'])


def txn_sql(alias='t'):
    """(sql, params) restricting transactions to the current view."""
    c = current()
    conds, params = [], []
    if c['book'] == 'Personal':
        others = _companies()
        if others:
            conds.append(f"COALESCE(NULLIF({alias}.entity,''),'Personal') NOT IN ({','.join('?' * len(others))})")
            params += others
    elif c['book']:
        conds.append(f"COALESCE(NULLIF({alias}.entity,''),'Personal') = ?"); params.append(c['book'])
    if c['account']:
        conds.append(f'{alias}.account = ?'); params.append(c['account'])
    if c['broker'] and not c['account'] and not c['book']:
        # money moved to / from this broker (confirmed or suggested links that name it)
        conds.append(f"{alias}.id IN (SELECT COALESCE(out_id, in_id) FROM txn_links WHERE counter_kind='broker' "
                     f"AND counter_ref=? AND status<>'rejected')")
        params.append(c['broker'])
    return (' AND '.join(conds) or '1=1'), params


def _companies():
    try:
        import dbconn
        con = dbconn.connect()
        return [r[0] for r in con.execute("SELECT name FROM entities WHERE name<>'Personal' AND COALESCE(role,'book')='book'")]
    except Exception:  # noqa: BLE001
        return []


def txn_literal(alias='t'):
    """Same filter as plain SQL text (for older helpers that take a WHERE string)."""
    sql, params = txn_sql(alias)
    for p in params:
        sql = sql.replace('?', "'" + str(p).replace("'", "''") + "'", 1)
    return sql


def account_in_scope(a):
    """a: dict/Row with name and entity."""
    c = current()
    if c['account'] and a['name'] != c['account']:
        return False
    if c['broker'] and not c['account'] and not c['book']:
        return False
    if c['book'] and ((a['entity'] or 'Personal') if (a['entity'] or 'Personal') in _companies() + ['Personal'] else 'Personal') != c['book']:
        return False
    return True


def broker_id():
    try:
        return int(current()['broker'] or 0) or None
    except ValueError:
        return None


def register(app, get_db):

    @app.context_processor
    def _inject_scope():
        try:
            con = get_db()
            accts = con.execute("SELECT name, kind, COALESCE(NULLIF(entity,''),'Personal') AS entity FROM accounts "
                                "WHERE COALESCE(status,'active')='active' ORDER BY kind, name").fetchall()
            brokers = con.execute("SELECT id, name FROM inv_brokers ORDER BY name").fetchall()
            bks = books(con)
        except Exception:  # noqa: BLE001 — very first start, tables not there yet
            accts, brokers, bks = [], [], []
        return {'scope': current(), 'scope_active': active(), 'scope_books': bks,
                'scope_accounts': accts, 'scope_brokers': brokers}

    def set_scope():
        v = request.values
        kind, val = v.get('kind', ''), v.get('value', '')
        s = {}
        if kind == 'book' and val:
            s = {'book': val, 'label': f'{val} book'}
        elif kind == 'account' and val:
            row = get_db().execute("SELECT name FROM accounts WHERE name=?", (val,)).fetchone()
            if row:
                s = {'account': val, 'label': val}
        elif kind == 'broker' and val:
            row = get_db().execute('SELECT id, name FROM inv_brokers WHERE id=?', (val,)).fetchone()
            if row:
                s = {'broker': str(row['id']), 'broker_name': row['name'], 'label': f"{row['name']} (broker)"}
        session['scope'] = s
        nxt = v.get('next') or request.referrer or url_for('home')
        if not str(nxt).startswith(('/', 'http://127.0.0.1', 'http://localhost')):
            nxt = url_for('home')
        return redirect(nxt)

    app.add_url_rule('/scope', 'set_scope', set_scope, methods=['GET', 'POST'])
