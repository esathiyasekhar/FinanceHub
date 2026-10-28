"""Finance Hub v2 – Flask application."""
import os
import io
import re
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

from flask import (Flask, render_template, request, jsonify, g, redirect,
                   url_for, flash, send_file, Response)
from werkzeug.utils import secure_filename

# ── App setup ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / 'finance.db'
STMT_DIR = BASE_DIR / 'statements'
UPLOAD_DIR = BASE_DIR / 'uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTS = {'.pdf', '.xlsx', '.xls', '.csv'}

HUB_VERSION = '1.5'          # bump on every change: 1.1, 1.2, … (see CHANGELOG.md)

app = Flask(__name__)
import secrets as _secrets  # noqa: E402
app.secret_key = _secrets.token_hex(32)      # new every start → everyone logs in again after a restart

# 1.2: the database is encrypted on disk (finance.db.enc) and opened in memory after login — see vault.py
import vault as _vault  # noqa: E402
import dbconn  # noqa: E402
V = _vault.Vault(BASE_DIR)
dbconn.VAULT = V

def _current_fy():
    """Return (fy_start, fy_end, fy_label) for the current Indian financial year."""
    today = date.today()
    if today.month >= 4:
        yr_start, yr_end = today.year, today.year + 1
    else:
        yr_start, yr_end = today.year - 1, today.year
    return (
        f'{yr_start}-04-01',
        f'{yr_end}-03-31',
        f'FY {str(yr_start)[-2:]}-{str(yr_end)[-2:]}',
    )

FY_START, FY_END, FY_LABEL = _current_fy()


# ── Context processor: inject current FY into every template ─────────────────
@app.context_processor
def inject_fy():
    """Inject current financial year into all templates (recomputed per request)."""
    _, _, label = _current_fy()
    from statement_reader import ENGINE_VERSION
    return {'fy_label': label, 'hub_version': HUB_VERSION, 'engine_version': ENGINE_VERSION}


# ── Jinja2 filters ────────────────────────────────────────────────────────────
@app.template_filter('inr')
def inr_filter(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '₹0'
    if abs(v) >= 1e7:
        return f'₹{v/1e7:.2f} Cr'
    if abs(v) >= 1e5:
        return f'₹{v/1e5:.2f} L'
    return f'₹{v:,.0f}'


@app.template_filter('short_date')
def short_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%d %b %y')
    except Exception:
        return value


@app.template_filter('month_name')
def month_name(value):
    try:
        return datetime.strptime(value, '%Y-%m').strftime('%b %Y')
    except Exception:
        return value


# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = V.connect()
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    """Save the (encrypted) database after every request that changed something."""
    if V.unlocked:
        try:
            if exc is not None and V.con.in_transaction:
                V.con.rollback()
            V.persist()
        except Exception:  # noqa: BLE001
            pass


def init_db():
    with dbconn.connect(DB_PATH) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            description TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            type        TEXT    NOT NULL CHECK(type IN ('debit','credit')),
            category    TEXT    NOT NULL DEFAULT 'Others',
            account     TEXT    NOT NULL,
            cardholder  TEXT,
            source_file TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_txn_date    ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account);
        CREATE INDEX IF NOT EXISTS idx_txn_cat     ON transactions(category);
        CREATE INDEX IF NOT EXISTS idx_txn_type    ON transactions(type);

        CREATE TABLE IF NOT EXISTS accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT UNIQUE NOT NULL,
            card_no      TEXT,
            bank         TEXT,
            type         TEXT DEFAULT 'credit_card',
            credit_limit REAL DEFAULT 0,
            notes        TEXT
        );

        CREATE TABLE IF NOT EXISTS passwords (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT    UNIQUE NOT NULL,
            label       TEXT    NOT NULL,
            password    TEXT    NOT NULL DEFAULT '',
            hint        TEXT    DEFAULT '',
            updated_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS loans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            lender          TEXT,
            card            TEXT,
            purchase_desc   TEXT,
            purchase_date   TEXT,
            original_amount REAL    DEFAULT 0,
            emi_amount      REAL    DEFAULT 0,
            total_emis      INTEGER DEFAULT 0,
            emis_paid       INTEGER DEFAULT 0,
            first_emi_date  TEXT,
            last_emi_date   TEXT,
            interest_rate   REAL    DEFAULT 0,
            status          TEXT    DEFAULT 'active',
            notes           TEXT
        );
        """)
        con.commit()


def seed_passwords():
    """Seed default passwords for password-protected statements."""
    with dbconn.connect(DB_PATH) as con:
        passwords = []   # 1.2: no passwords in the source code — they are kept in the encrypted database
        for institution, label, password, hint in passwords:
            con.execute(
                '''INSERT OR IGNORE INTO passwords (institution, label, password, hint)
                   VALUES (?, ?, ?, ?)''',
                (institution, label, password, hint)
            )
        con.commit()


def get_passwords() -> dict:
    """Return all passwords as a dict keyed by institution."""
    with dbconn.connect(DB_PATH) as con:
        rows = con.execute('SELECT institution, password FROM passwords').fetchall()
    return {row[0]: row[1] for row in rows}


def seed_data():
    """1.2: nothing is pre-filled — every user adds their own accounts (or Add Statements creates them)."""
    return


def load_statements():
    """Parse all statements and insert into DB (idempotent)."""
    with dbconn.connect(DB_PATH) as con:
        count = con.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
        if count > 0:
            return count  # Already loaded

    from parsers import load_all_statements
    passwords = get_passwords()
    txns = load_all_statements(str(STMT_DIR), passwords=passwords)

    inserted = 0
    with dbconn.connect(DB_PATH) as con:
        for t in txns:
            try:
                con.execute(
                    '''INSERT OR IGNORE INTO transactions
                       (date,description,amount,type,category,account,cardholder,source_file)
                       VALUES (?,?,?,?,?,?,?,?)''',
                    (t.get('date',''), t.get('description',''), t.get('amount',0),
                     t.get('type','debit'), t.get('category','Others'),
                     t.get('account',''), t.get('cardholder',''),
                     t.get('source_file',''))
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        con.commit()
    return inserted


# ── Helper queries ────────────────────────────────────────────────────────────
def q(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def q1(sql, params=()):
    row = get_db().execute(sql, params).fetchone()
    return row[0] if row else 0


def fy_where(start=FY_START, end=FY_END):
    return f"date >= '{start}' AND date <= '{end}'"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/insights')
def dashboard():
    # Period: default to current month; user can switch to full FY via ?period=fy
    period = request.args.get('period', 'month')
    today  = date.today()

    # Find the latest month that actually has data (in case current month is empty)
    latest_data_month = q1("SELECT MAX(strftime('%Y-%m', date)) FROM transactions")

    if period == 'month':
        cur_month = today.strftime('%Y-%m')
        # Allow month picker override via ?m=YYYY-MM
        m_param = request.args.get('m', '')
        if m_param and re.fullmatch(r'\d{4}-\d{2}', m_param):
            view_month = m_param
            has_cur = q1(f"SELECT COUNT(*) FROM transactions WHERE date LIKE '{view_month}%'")
        else:
            # Use current month if it has data, else fall back to latest month with data
            has_cur = q1(f"SELECT COUNT(*) FROM transactions WHERE date LIKE '{cur_month}%'")
            view_month = cur_month if has_cur else (latest_data_month or cur_month)
        view_start = view_month + '-01'
        # Last day of month
        if view_month:
            ym = datetime.strptime(view_month, '%Y-%m')
            if ym.month == 12:
                view_end = f'{ym.year + 1}-01-01'
            else:
                view_end = f'{ym.year}-{ym.month + 1:02d}-01'
            # Exclusive end — use < view_end in queries
        else:
            view_end = view_start
        period_where  = f"date >= '{view_start}' AND date < '{view_end}'"
        period_label  = datetime.strptime(view_month, '%Y-%m').strftime('%B %Y')
        # Only show "no data" note when current real month has no data AND we're not on a selected month
        if not m_param and not has_cur and view_month != cur_month:
            period_label += ' (No data yet — showing latest available)'
    else:
        period_where = fy_where()
        period_label = FY_LABEL

    import organise
    d = organise.dashboard_data(get_db(), period_where, fy_where())
    chart_labels = [datetime.strptime(m, '%Y-%m').strftime("%b '%y") for m in d['months']]
    avail_months = [r[0] for r in q(
        "SELECT DISTINCT strftime('%Y-%m', date) mon FROM transactions ORDER BY mon DESC LIMIT 24"
    )]
    return render_template('dashboard.html', d=d,
        txn_count=d['txn_count'],
        chart_labels=json.dumps(chart_labels),
        chart_expense=json.dumps([round(d['trend'][m]['expense'], 2) for m in d['months']]),
        chart_income=json.dumps([round(d['trend'][m]['income'], 2) for m in d['months']]),
        cat_labels=json.dumps([h for h, _ in d['heads']]),
        cat_values=json.dumps([round(v, 2) for _, v in d['heads']]),
        fy_label=FY_LABEL,
        period=period,
        period_label=period_label,
        avail_months=avail_months,
        cur_month=today.strftime('%Y-%m'),
        latest_data_month=latest_data_month or today.strftime('%Y-%m'),
    )


@app.route('/loans')
def loans():
    """1.1: loans and EMIs live on the Accounts page (Loans / EMIs tabs)."""
    return redirect(url_for('accounts', tab='emi'))


def _loans_back():
    nxt = request.form.get('next') or ''
    return redirect(nxt if nxt.startswith('/') else url_for('accounts', tab='emi'))


@app.route('/loans/add', methods=['POST'])
def add_loan():
    data = request.form
    get_db().execute('''
        INSERT INTO loans (name,lender,card,purchase_desc,purchase_date,
                           original_amount,emi_amount,total_emis,emis_paid,
                           first_emi_date,last_emi_date,interest_rate,status,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        data.get('name',''), data.get('lender',''), data.get('card',''),
        data.get('purchase_desc',''), data.get('purchase_date',''),
        float(data.get('original_amount',0) or 0),
        float(data.get('emi_amount',0) or 0),
        int(data.get('total_emis',0) or 0),
        int(data.get('emis_paid',0) or 0),
        data.get('first_emi_date',''), data.get('last_emi_date',''),
        float(data.get('interest_rate',0) or 0),
        'active', data.get('notes',''),
    ))
    get_db().commit()
    flash('EMI added successfully!', 'success')
    return _loans_back()


@app.route('/loans/<int:loan_id>/pay', methods=['POST'])
def mark_emi_paid(loan_id):
    db = get_db()
    db.execute('UPDATE loans SET emis_paid = emis_paid + 1 WHERE id = ?', (loan_id,))
    # Check if fully paid
    row = db.execute('SELECT emis_paid, total_emis FROM loans WHERE id = ?', (loan_id,)).fetchone()
    if row and row[0] >= row[1]:
        db.execute("UPDATE loans SET status = 'paid' WHERE id = ?", (loan_id,))
    db.commit()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'ok': True})
    flash('EMI marked as paid.', 'success')
    return _loans_back()


@app.route('/loans/<int:loan_id>/delete', methods=['POST'])
def delete_loan(loan_id):
    get_db().execute('DELETE FROM loans WHERE id = ?', (loan_id,))
    get_db().commit()
    flash('EMI record deleted.', 'info')
    return _loans_back()


@app.route('/reports')
def reports_page():
    import itr
    con = get_db()
    opts = itr.fy_options(con)
    sel = request.args.get('fy') or opts[0][0]
    label, start, end = next((o for o in opts if o[0] == sel), opts[0])
    return render_template('reports.html', fy_opts=opts, fy_sel=label, fy_start=start, fy_end=end,
                           s=itr.summary(con, start, end))


@app.route('/reports/download')
def download_report():
    from reports.generator import generate_monthly_report
    start = request.args.get('start', FY_START)
    end   = request.args.get('end',   FY_END)

    txns = [dict(r) for r in q(
        f"SELECT * FROM transactions WHERE date >= '{start}' AND date <= '{end}'"
    )]
    data = generate_monthly_report(txns, start, end)
    if not data:
        flash('Report generation failed (openpyxl missing?)', 'danger')
        return redirect(url_for('reports_page'))

    fname = f'FinanceReport_{start[:7]}_to_{end[:7]}.xlsx'
    return send_file(io.BytesIO(data), download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True)


@app.route('/import', methods=['GET'])
def import_page():
    stmts = q("""SELECT id, file_name, bank, document, period_from, period_to, statement_date,
                        txn_count, txn_imported, check_status, imported_at, reader_version, accounts
                 FROM statements ORDER BY imported_at DESC, id DESC LIMIT 200""")
    from statement_reader.parsers import SUPPORTED
    import itr
    import importer
    pending = []                       # 1.5: statements from the mail inbox waiting for review
    for t in (request.args.get('pending') or '').split(','):
        pv = importer.load_pending(t.strip(), UPLOAD_DIR) if t.strip() else None
        if pv:
            pending.append(importer.public_view(pv))
    return render_template('import.html', statements=stmts, stmt_folders=[str(p) for p in _statement_folders()],
                           supported=SUPPORTED, fy_opts=itr.fy_options(get_db()), pending=pending)


def _db_con():
    con = dbconn.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


@app.route('/import/preview', methods=['POST'])
def import_preview():
    """Step 1: upload → parse → preview. Nothing is written to the database."""
    import importer
    from parsers.categorizer import categorize
    out = []
    con = _db_con()
    try:
        for f in request.files.getlist('files'):
            if not f or not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_EXTS:
                out.append({'file': f.filename, 'status': 'error', 'msg': 'Unsupported format', 'token': ''})
                continue
            token, path = importer.save_upload(f, f.filename, UPLOAD_DIR)
            pv = importer.preview_file(con, path, f.filename, token, UPLOAD_DIR, categorize=categorize)
            out.append(importer.public_view(pv))
    finally:
        con.close()
    return jsonify(out)


@app.route('/import/password', methods=['POST'])
def import_password():
    """Retry a preview with a typed password; optionally save it on the Passwords page."""
    import importer
    from parsers.categorizer import categorize
    data = request.get_json(force=True)
    pv = importer.load_pending(data.get('token', ''), UPLOAD_DIR)
    if not pv:
        return jsonify({'status': 'error', 'msg': 'Upload expired — please add the file again.'}), 404
    con = _db_con()
    try:
        new = importer.preview_file(con, Path(pv['path']), pv['file'], pv['token'], UPLOAD_DIR,
                                    password=data.get('password', ''), categorize=categorize)
        if new['status'] != 'needs_password' and data.get('save'):
            code = importer.bank_code(new.get('bank', '')) or 'pdf'
            n = con.execute("SELECT COUNT(*) FROM passwords WHERE institution LIKE ?", (f'auto_{code}%',)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO passwords (institution, label, password, hint) VALUES (?,?,?,?)",
                        (f'auto_{code}_{n + 1}', f"{new.get('bank') or 'Statement'} – {new.get('document', '')}"[:80],
                         data.get('password', ''), f"saved from Import ({pv['file']})"))
            con.commit()
            new['password_saved'] = True
    finally:
        con.close()
    return jsonify(importer.public_view(new))


@app.route('/import/confirm', methods=['POST'])
def import_confirm():
    """Step 2: import exactly what was previewed."""
    import importer
    tokens = (request.get_json(force=True) or {}).get('tokens', [])
    results = []
    con = _db_con()
    try:
        for t in tokens:
            pv = importer.load_pending(t, UPLOAD_DIR)
            if not pv:
                results.append({'file': t, 'ok': False, 'msg': 'preview expired — add the file again'})
                continue
            results.append(importer.commit_preview(con, pv))
    finally:
        con.close()
    return jsonify(results)


@app.route('/import/statements/<int:sid>/delete', methods=['POST'])
def delete_statement(sid):
    """Remove one imported statement and the transactions it added."""
    db = get_db()
    row = db.execute('SELECT file_name FROM statements WHERE id=?', (sid,)).fetchone()
    n = db.execute('DELETE FROM transactions WHERE statement_id=?', (sid,)).rowcount
    db.execute('DELETE FROM statements WHERE id=?', (sid,))
    db.commit()
    flash(f"Removed {row[0] if row else 'statement'} and its {n} transactions.", 'info')
    return redirect(url_for('import_page'))


def _statement_folders():
    """The app's own statements/ folder and the one next to it (FinanceHub_v2\\statements)."""
    cands = [STMT_DIR, BASE_DIR.parent / 'statements']
    return [p for p in cands if p.exists() and any(p.rglob('*.*'))]


@app.route('/passwords', methods=['GET'])
def passwords_page():
    rows = q('SELECT institution, label, password, hint, updated_at FROM passwords ORDER BY label')
    return render_template('passwords.html', passwords=rows)


@app.route('/passwords/update', methods=['POST'])
def update_password():
    data = request.get_json()
    institution = data.get('institution', '').strip()
    new_pw = data.get('password', '').strip()
    if not institution or not new_pw:
        return jsonify({'ok': False, 'msg': 'institution and password required'}), 400
    db = get_db()
    db.execute(
        "UPDATE passwords SET password=?, updated_at=datetime('now') WHERE institution=?",
        (new_pw, institution)
    )
    if db.execute('SELECT changes()').fetchone()[0] == 0:
        # Insert new entry if not found
        db.execute(
            "INSERT INTO passwords (institution, label, password) VALUES (?, ?, ?)",
            (institution, institution, new_pw)
        )
    db.commit()
    return jsonify({'ok': True, 'msg': 'Password updated'})


@app.route('/import/reset', methods=['POST'])
def import_reset():
    """Delete all transactions + statement history, then import every file in the statements folder(s)."""
    import importer
    from parsers.categorizer import categorize
    db = get_db()
    db.execute('DELETE FROM transactions')
    db.execute('DELETE FROM statements')
    db.commit()
    folders = _statement_folders()
    res = importer.import_folder(DB_PATH, folders, UPLOAD_DIR, categorize)
    n = sum(r.get('imported', 0) for r in res['imported'])
    msg = f"Database reset. {len(res['imported'])} statements, {n} transactions imported from {', '.join(map(str, folders)) or 'no folder'}."
    if res['skipped']:
        msg += ' Skipped: ' + '; '.join(f"{s['file']} ({s['why']})" for s in res['skipped'][:8])
    flash(msg, 'success' if not res['skipped'] else 'warning')
    return redirect(url_for('import_page'))


@app.route('/import/delete-all', methods=['POST'])
def import_delete_all():
    """Delete ALL transactions and the statement history (AJAX — returns JSON)."""
    db = get_db()
    result = db.execute('DELETE FROM transactions')
    db.execute('DELETE FROM statements')
    db.commit()
    return jsonify({'ok': True, 'msg': f'All {result.rowcount} transactions deleted. Database is now empty.'})


@app.route('/import/clear-fy', methods=['POST'])
def import_clear_fy():
    """Delete all transactions for a specific financial year."""
    fy_start = request.form.get('fy_start', FY_START)
    fy_end   = request.form.get('fy_end',   FY_END)
    if not (re.fullmatch(r'\d{4}-\d{2}-\d{2}', fy_start) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', fy_end)):
        flash('Invalid dates.', 'warning')
        return redirect(url_for('import_page'))
    db = get_db()
    result = db.execute(
        "DELETE FROM transactions WHERE date >= ? AND date <= ?",
        (fy_start, fy_end)
    )
    deleted = result.rowcount
    # statements left without rows are removed too, so the same files can be imported again
    gone = db.execute("DELETE FROM statements WHERE id NOT IN (SELECT DISTINCT statement_id FROM transactions "
                      "WHERE statement_id IS NOT NULL) AND COALESCE(NULLIF(period_to,''), statement_date, '') BETWEEN ? AND ?",
                      (fy_start, fy_end)).rowcount
    db.commit()
    flash(f'Removed {deleted} transactions from {fy_start} to {fy_end}'
          + (f' and {gone} statement record(s), so those files can be imported again.' if gone else '.'), 'success')
    return redirect(url_for('import_page'))


# ── API endpoints ─────────────────────────────────────────────────────────────
@app.route('/api/summary')
def api_summary():
    fy = fy_where()
    return jsonify({
        'total_debit':  q1(f'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="debit" AND {fy}'),
        'total_credit': q1(f'SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type="credit" AND {fy}'),
        'txn_count':    q1(f'SELECT COUNT(*) FROM transactions WHERE {fy}'),
        'acc_count':    q1('SELECT COUNT(*) FROM accounts'),
    })


@app.route('/api/category_data')
def api_category_data():
    start = request.args.get('start', FY_START)
    end   = request.args.get('end',   FY_END)
    # real spending by Head (transfers excluded, refunds deducted)
    rows = q('''
        SELECT t.category, SUM(CASE WHEN t.type='debit' THEN t.amount ELSE -t.amount END) AS total
        FROM transactions t JOIN categories c ON c.id = t.category_id
        WHERE c.kind = 'expense' AND t.date >= ? AND t.date <= ?
        GROUP BY t.category HAVING total > 0 ORDER BY total DESC
    ''', (start, end))
    return jsonify({'labels': [r[0] for r in rows], 'values': [round(r[1], 2) for r in rows]})


# ── v4: transactions, breakdown, categories, rules, people (organise.py) ─────
import organise  # noqa: E402
organise.register(app, get_db)
import investments  # noqa: E402
investments.register(app, get_db, UPLOAD_DIR)
import compounding  # noqa: E402
compounding.register(app, get_db)
import accounts_hub  # noqa: E402  (1.1: accounts by kind, net worth, dues, Home)
accounts_hub.register(app, get_db)
import planning  # noqa: E402      (1.1: recurring, budgets, tools, alerts, month close, search)
planning.register(app, get_db)


# ── Startup ───────────────────────────────────────────────────────────────────
def prepare_db():
    """Create / upgrade every table — runs right after the database is unlocked."""
    init_db()
    import importer
    importer.ensure_schema(DB_PATH)
    with dbconn.connect(DB_PATH) as _c:
        _c.row_factory = sqlite3.Row
        investments.ensure_schema(_c)
        compounding.ensure_schema(_c)
        accounts_hub.ensure_schema(_c)
        planning.ensure_schema(_c)
        scope.ensure_schema(_c)
        ledger.ensure_schema(_c)
        assets.ensure_schema(_c)
        import mailreader as _mr
        _mr.ensure_schema(_c)
    seed_passwords()
    seed_data()
    V.persist(force=True)
    # statement copies left in uploads/ by unfinished imports are erased after a day
    import time as _t
    for f in UPLOAD_DIR.rglob('*'):
        try:
            if f.is_file() and _t.time() - f.stat().st_mtime > 86400:
                _vault.secure_delete(f)
        except OSError:
            pass


import scope  # noqa: E402        (1.2: global Viewing filter — book / account / card / broker)
scope.register(app, get_db)
import ledger  # noqa: E402       (1.2: transfers, director account, reimbursements, loans with people)
ledger.register(app, get_db)
import assets  # noqa: E402       (1.2: asset types, broker-wise views)
assets.register(app, get_db)
import reports_hub  # noqa: E402  (1.2: Excel / PDF reports for any view)
reports_hub.register(app, get_db)
import depository  # noqa: E402     (1.4: CDSL / NSDL demat accounts and reconciliation)
depository.register(app, get_db)
import mailreader  # noqa: E402     (1.5: the Hub's own mailbox — IMAP)
mailreader.register(app, get_db, UPLOAD_DIR, V)
import auth  # noqa: E402         (1.2: users, login, lock)
auth.register(app, V, prepare_db)


def create_app():
    """Kept for the test tools: with no users yet, set up an encrypted database from finance.db."""
    return app


if __name__ == '__main__':
    print('Finance Hub ' + HUB_VERSION + ' — open http://127.0.0.1:5000 in your browser (this computer only).')
    app.run(debug=False, host='127.0.0.1', port=5000, threaded=False)
