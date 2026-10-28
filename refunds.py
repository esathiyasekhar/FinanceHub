"""Finance Hub 1.6 — failed transactions and refund tracking.

Failed & reversed: a debit and a credit for the same amount on the same account a few days apart, where the credit says it
is a reversal (REV / REVERSAL / FAILED / RETURN / DECLINED …) or both carry the same reference number (UPI / IMPS RRN).
Once you confirm, both sides go to Transfers › Failed & reversed, so neither counts as spending or income.

Refunds: a credit that says REFUND / RFND / REVERSAL / CHARGEBACK (or carries the purchase's reference) is matched to the
purchase it pays back — same merchant words, amount not more than the purchase, within 120 days, same account preferred.
Confirming puts the refund in the purchase's category, so that category's spending goes down by the refund.

Awaiting refund: mark any purchase "expecting a refund" (returned order, cancelled booking, failed payment that was not
reversed). The Hub watches new credits for it, shows how long you have been waiting, and flags it after 15 days.
Debits that say FAILED / DECLINED and are not reversed within 3 days are suggested for this list automatically.
"""
import re
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, jsonify

import classifier as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS txn_refunds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- failed / refund / expected
    debit_id INTEGER, credit_id INTEGER,
    status TEXT NOT NULL,               -- suggested / confirmed / rejected / waiting / received / closed
    expected REAL, follow_up_days INTEGER DEFAULT 15, note TEXT, score INTEGER DEFAULT 0, reason TEXT,
    prev_debit_cat INTEGER, prev_credit_cat INTEGER,
    created_at TEXT DEFAULT (datetime('now')), done_at TEXT);
CREATE INDEX IF NOT EXISTS idx_ref_debit ON txn_refunds(debit_id);
CREATE INDEX IF NOT EXISTS idx_ref_credit ON txn_refunds(credit_id);
"""
FAILED_PATH = ('Transfers', 'Failed & reversed', 'Failed payments', 'Reversed by bank')
REV_RE = re.compile(r'\b(REV|REVERSAL|REVERSED|RVSL|FAILED|FAIL|FAILURE|RETURN|RETURNED|RTN|RET|DECLINED?|UNSUCCESSFUL|'
                    r'CHARGEBACK|CHGBK|REJECTED|BOUNCE)\b')
REFUND_RE = re.compile(r'\b(REFUND|RFND|REFUNDED|REVERSAL|REVERSED|CHARGEBACK|CHGBK|MERCHANT CREDIT|RETURN CREDIT|CANCELLATION)\b')
FAILED_DEBIT_RE = re.compile(r'\b(FAILED|DECLINED|UNSUCCESSFUL|TXN FAIL)\b')
REF_RE = re.compile(r'(?<!\d)(\d{12})(?!\d)')          # UPI / IMPS RRN
STOP = {'UPI', 'IMPS', 'NEFT', 'RTGS', 'POS', 'ECOM', 'REV', 'REVERSAL', 'REFUND', 'RFND', 'DR', 'CR', 'TO', 'FROM', 'BY', 'THE',
        'PAYMENT', 'PAY', 'TXN', 'TRANSFER', 'INR', 'RS', 'REF', 'NO', 'FAILED', 'RETURN', 'CREDIT', 'DEBIT', 'PVT', 'LTD',
        'LIMITED', 'PRIVATE', 'INDIA', 'BANK', 'AND', 'FOR', 'WWW', 'COM', 'IN', 'OF', 'ON', 'AT', 'MERCHANT', 'CARD', 'ONLINE'}


def ensure_schema(con):
    con.executescript(SCHEMA)
    con.commit()


def _text(r):
    return f"{r['description'] or ''} {r['narration'] or ''} {r['reference'] or ''}".upper()


def _tokens(r):
    return {t for t in re.findall(r'[A-Z]{3,}', f"{r['description'] or ''} {r['narration'] or ''}".upper()) if t not in STOP}


def _refs(r):
    return set(REF_RE.findall(f"{r['description'] or ''} {r['narration'] or ''} {r['reference'] or ''}"))


def _d(s):
    return datetime.strptime(s[:10], '%Y-%m-%d').date()


def _cols(con):
    have = {r[1] for r in con.execute('PRAGMA table_info(transactions)')}
    sel = ['id', 'date', 'description', 'amount', 'type', 'account', 'category_id']
    sel += [c if c in have else f"'' AS {c}" for c in ('narration', 'reference')]
    return ', '.join(sel)


def _taken(con):
    ids = set()
    for r in con.execute("SELECT debit_id, credit_id FROM txn_refunds WHERE status IN ('suggested','confirmed','received')"):
        ids.update(x for x in r if x)
    try:
        for r in con.execute("SELECT out_id, in_id FROM txn_links WHERE status='confirmed'"):
            ids.update(x for x in r if x)
    except Exception:  # noqa: BLE001
        pass
    return ids


def scan(con, since_days=400):
    """Find failed-and-reversed pairs, refunds for purchases, and failed debits never reversed. → new suggestions"""
    ensure_schema(con)
    since = (date.today() - timedelta(days=since_days)).isoformat()
    rows = con.execute(f'SELECT {_cols(con)} FROM transactions WHERE date>=? ORDER BY date, id', (since,)).fetchall()
    rejected = {(r[0], r[1]) for r in con.execute("SELECT debit_id, credit_id FROM txn_refunds WHERE status='rejected'")}
    taken = _taken(con)
    debits = [r for r in rows if r['type'] == 'debit']
    credits = [r for r in rows if r['type'] == 'credit']
    by_acct_amt = {}
    for d in debits:
        by_acct_amt.setdefault((d['account'], round(d['amount'], 2)), []).append(d)
    added = 0
    # 1) failed & reversed — same account, same amount, credit 0–10 days after, says reversal or shares the reference
    for c in credits:
        if c['id'] in taken:
            continue
        ct, crefs = _text(c), _refs(c)
        best = None
        for d in by_acct_amt.get((c['account'], round(c['amount'], 2)), []):
            if d['id'] in taken or (d['id'], c['id']) in rejected:
                continue
            gap = (_d(c['date']) - _d(d['date'])).days
            if not 0 <= gap <= 10:
                continue
            same_ref = bool(crefs & _refs(d))
            kw = bool(REV_RE.search(ct))
            if not (same_ref or kw):
                continue
            score = (10 if same_ref else 0) + (5 if kw else 0) + (2 if gap <= 1 else 0) + (2 if FAILED_DEBIT_RE.search(_text(d)) else 0) \
                + len(_tokens(c) & _tokens(d))
            if not best or score > best[0]:
                best = (score, d, gap, same_ref, kw)
        if best:
            score, d, gap, same_ref, kw = best
            why = ', '.join(x for x in ('same reference number' if same_ref else '', 'credit says reversal / failed' if kw else '',
                                        f'{gap} day{"s" if gap != 1 else ""} later') if x)
            con.execute("INSERT INTO txn_refunds (kind, debit_id, credit_id, status, score, reason) VALUES ('failed',?,?,'suggested',?,?)",
                        (d['id'], c['id'], score, why))
            taken.update((d['id'], c['id']))
            added += 1
    # 2) refunds — a refund credit matched to an earlier purchase (≤ 120 days, amount ≤ purchase)
    waiting = {r['debit_id']: r for r in con.execute("SELECT * FROM txn_refunds WHERE kind='expected' AND status='waiting'")}
    for c in credits:
        if c['id'] in taken:
            continue
        ct = _text(c)
        is_refund = bool(REFUND_RE.search(ct))
        ctoks, crefs, cd = _tokens(c), _refs(c), _d(c['date'])
        best = None
        for d in debits:
            if d['id'] in taken and d['id'] not in waiting:
                continue
            if (d['id'], c['id']) in rejected:
                continue
            gap = (cd - _d(d['date'])).days
            if not 0 <= gap <= 120 or c['amount'] > d['amount'] + 1:
                continue
            common = ctoks & _tokens(d)
            same_ref = bool(crefs & _refs(d))
            expected = waiting.get(d['id'])
            if not (same_ref or (is_refund and common) or (expected and (common or is_refund))):
                continue
            score = (8 if same_ref else 0) + 3 * len(common) + (3 if c['account'] == d['account'] else 0) + \
                (4 if abs(c['amount'] - d['amount']) < 1 else 0) + (6 if expected else 0) - gap // 30
            if expected and expected['expected'] and abs(expected['expected'] - c['amount']) < 1:
                score += 4
            if not best or score > best[0]:
                best = (score, d, gap, common, same_ref, expected)
        if best and best[0] >= 6:
            score, d, gap, common, same_ref, expected = best
            part = '' if abs(c['amount'] - d['amount']) < 1 else f' (part: {c["amount"]:,.0f} of {d["amount"]:,.0f})'
            why = ', '.join(x for x in ('same reference number' if same_ref else '',
                                        ('same merchant: ' + ' '.join(sorted(common)[:3])) if common else '',
                                        'you were expecting it' if expected else '', f'{gap} days after the purchase') if x) + part
            con.execute("INSERT INTO txn_refunds (kind, debit_id, credit_id, status, score, reason) VALUES ('refund',?,?,'suggested',?,?)",
                        (d['id'], c['id'], score, why))
            taken.update((d['id'], c['id']))
            added += 1
    # 3) failed debits never reversed (3+ days) → suggest "awaiting refund"
    have = {r[0] for r in con.execute('SELECT debit_id FROM txn_refunds')}
    for d in debits:
        if d['id'] in taken or d['id'] in have or not FAILED_DEBIT_RE.search(_text(d)):
            continue
        if (date.today() - _d(d['date'])).days >= 3:
            con.execute("INSERT INTO txn_refunds (kind, debit_id, status, expected, score, reason) VALUES ('expected',?,'suggested',?,3,?)",
                        (d['id'], d['amount'], 'debit says failed / declined and no reversal was found'))
            added += 1
    con.commit()
    return added


def _set_cat(con, tid, cid):
    con.execute('UPDATE transactions SET category_id=?, category=?, manual=1 WHERE id=?', (cid, C.head_name(con, cid), tid))


def confirm(con, rid):
    r = con.execute('SELECT * FROM txn_refunds WHERE id=?', (rid,)).fetchone()
    if not r:
        return
    deb = con.execute('SELECT id, category_id FROM transactions WHERE id=?', (r['debit_id'],)).fetchone() if r['debit_id'] else None
    cre = con.execute('SELECT id, category_id FROM transactions WHERE id=?', (r['credit_id'],)).fetchone() if r['credit_id'] else None
    if r['kind'] == 'failed' and deb and cre:
        fid = C.path_id(con, FAILED_PATH, create=True)
        con.execute('UPDATE txn_refunds SET prev_debit_cat=?, prev_credit_cat=? WHERE id=?', (deb['category_id'], cre['category_id'], rid))
        _set_cat(con, deb['id'], fid)
        _set_cat(con, cre['id'], fid)
        status = 'confirmed'
    elif r['kind'] in ('refund', 'expected') and deb and cre:
        con.execute('UPDATE txn_refunds SET prev_credit_cat=? WHERE id=?', (cre['category_id'], rid))
        if deb['category_id']:
            _set_cat(con, cre['id'], deb['category_id'])
        status = 'confirmed' if r['kind'] == 'refund' else 'received'
        con.execute("UPDATE txn_refunds SET status='received', credit_id=?, done_at=datetime('now') WHERE kind='expected' "
                    "AND debit_id=? AND id<>? AND status='waiting'", (cre['id'], deb['id'], rid))
    elif r['kind'] == 'expected' and deb:
        status = 'waiting'                                   # suggestion "awaiting refund" accepted
    else:
        return
    con.execute("UPDATE txn_refunds SET status=?, done_at=datetime('now') WHERE id=?", (status, rid))
    con.commit()


def undo(con, rid):
    r = con.execute('SELECT * FROM txn_refunds WHERE id=?', (rid,)).fetchone()
    if not r:
        return
    if r['status'] in ('confirmed', 'received'):
        if r['prev_debit_cat'] and r['debit_id']:
            _set_cat(con, r['debit_id'], r['prev_debit_cat'])
        if r['prev_credit_cat'] and r['credit_id']:
            _set_cat(con, r['credit_id'], r['prev_credit_cat'])
    if r['kind'] in ('refund', 'expected') and r['debit_id'] and r['credit_id']:
        # 1.6: a purchase you were waiting on goes back to "Awaiting refund"
        con.execute("UPDATE txn_refunds SET status='waiting', credit_id=NULL, done_at=NULL WHERE kind='expected' AND status='received' "
                    "AND debit_id=? AND credit_id=? AND id<>?", (r['debit_id'], r['credit_id'], rid))
    if r['kind'] == 'expected' and r['status'] == 'received':
        con.execute("UPDATE txn_refunds SET status='waiting', credit_id=NULL, done_at=NULL WHERE id=?", (rid,))
    elif r['kind'] == 'expected' and r['status'] == 'closed':
        con.execute("UPDATE txn_refunds SET status='waiting', done_at=NULL WHERE id=?", (rid,))
    else:
        con.execute("UPDATE txn_refunds SET status='rejected', done_at=datetime('now') WHERE id=?", (rid,))
    con.commit()


def expect(con, tid, amount=None, days=15, note=''):
    t = con.execute('SELECT id, amount FROM transactions WHERE id=? AND type=?', (tid, 'debit')).fetchone()
    if not t:
        return False
    con.execute("DELETE FROM txn_refunds WHERE kind='expected' AND debit_id=? AND status IN ('suggested','waiting')", (tid,))
    con.execute("INSERT INTO txn_refunds (kind, debit_id, status, expected, follow_up_days, note, reason) VALUES ('expected',?,'waiting',?,?,?,?)",
                (tid, amount or t['amount'], days, note[:200], 'marked by you'))
    con.commit()
    return True


def rows(con, where, params=()):
    q = f"""SELECT r.*, d.date d_date, d.description d_desc, d.amount d_amt, d.account d_acct, COALESCE(d.display_name,'') d_name,
                   c.date c_date, c.description c_desc, c.amount c_amt, c.account c_acct, COALESCE(c.display_name,'') c_name
            FROM txn_refunds r LEFT JOIN transactions d ON d.id=r.debit_id LEFT JOIN transactions c ON c.id=r.credit_id
            WHERE {where} ORDER BY COALESCE(d.date, c.date) DESC, r.id DESC LIMIT 300"""
    out = []
    today = date.today()
    for r in con.execute(q, params):
        x = dict(r)
        if r['d_date']:
            x['age'] = (today - _d(r['d_date'])).days
            x['late'] = r['status'] == 'waiting' and x['age'] > (r['follow_up_days'] or 15)
        out.append(x)
    return out


def summary(con):
    ensure_schema(con)
    w = rows(con, "r.kind='expected' AND r.status='waiting'")
    return {'waiting': len(w), 'waiting_amt': sum(x['expected'] or x['d_amt'] or 0 for x in w), 'late': sum(1 for x in w if x.get('late')),
            'suggested': con.execute("SELECT COUNT(*) FROM txn_refunds WHERE status='suggested'").fetchone()[0],
            'refunded': con.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE id IN (SELECT credit_id FROM txn_refunds "
                                    "WHERE kind IN ('refund','expected') AND status IN ('confirmed','received'))").fetchone()[0],
            'failed': con.execute("SELECT COUNT(*) FROM txn_refunds WHERE kind='failed' AND status='confirmed'").fetchone()[0]}


def register(app, get_db):

    def con_():
        c = get_db()
        ensure_schema(c)
        return c

    def page():
        con = con_()
        n = scan(con)
        tab = request.args.get('tab', 'suggested')
        where = {'suggested': "r.status='suggested'", 'waiting': "r.kind='expected' AND r.status='waiting'",
                 'done': "r.status IN ('confirmed','received','closed')", 'rejected': "r.status='rejected'"}.get(tab, "r.status='suggested'")
        return render_template('refunds.html', rows=rows(con, where), tab=tab, s=summary(con), added=n)

    def act(rid):
        con = con_()
        a = request.form.get('action')
        if a == 'confirm':
            confirm(con, rid)
            flash('Confirmed.', 'success')
        elif a in ('reject', 'undo'):
            undo(con, rid)
            flash('Undone.' if a == 'undo' else 'Marked as not a match.', 'info')
        elif a == 'close':
            con.execute("UPDATE txn_refunds SET status='closed', note=COALESCE(note,'') || ? , done_at=datetime('now') WHERE id=?",
                        (' · closed without refund', rid))
            con.commit()
            flash('Closed — no refund expected any more.', 'info')
        elif a == 'match':
            cid = request.form.get('credit_id', type=int)
            if cid:
                con.execute('UPDATE txn_refunds SET credit_id=? WHERE id=?', (cid, rid))
                confirm(con, rid)
                flash('Refund matched.', 'success')
        return redirect(url_for('refunds_page', tab=request.form.get('tab', 'suggested')))

    def expect_route():
        con = con_()
        tid = request.form.get('txn', type=int)
        ok = expect(con, tid, request.form.get('amount', type=float), request.form.get('days', 15, type=int), request.form.get('note', ''))
        if request.is_json or request.headers.get('X-Requested-With'):
            return jsonify({'ok': ok})
        flash('Added to “Awaiting refund”.' if ok else 'Only a debit (money going out) can wait for a refund.', 'success' if ok else 'warning')
        return redirect(url_for('refunds_page', tab='waiting'))

    def candidates(rid):
        """Credits that could be the refund for a waiting purchase (for the 'match by hand' list)."""
        con = con_()
        r = con.execute('SELECT * FROM txn_refunds WHERE id=?', (rid,)).fetchone()
        d = con.execute('SELECT * FROM transactions WHERE id=?', (r['debit_id'],)).fetchone() if r else None
        if not d:
            return jsonify([])
        taken = _taken(con)
        out = [dict(id=c['id'], date=c['date'], desc=c['display_name'] or c['description'], amount=c['amount'], account=c['account'])
               for c in con.execute("SELECT * FROM transactions WHERE type='credit' AND date>=? AND amount<=? ORDER BY "
                                    "(account=?) DESC, ABS(amount-?) LIMIT 40", (d['date'], d['amount'] + 1, d['account'], r['expected'] or d['amount']))
               if c['id'] not in taken]
        return jsonify(out)

    for rule, ep, fn, methods in [('/refunds', 'refunds_page', page, ['GET']), ('/refunds/<int:rid>', 'refund_act', act, ['POST']),
                                  ('/refunds/expect', 'refund_expect', expect_route, ['POST']),
                                  ('/refunds/<int:rid>/candidates', 'refund_candidates', candidates, ['GET'])]:
        app.add_url_rule(rule, ep, fn, methods=methods)
