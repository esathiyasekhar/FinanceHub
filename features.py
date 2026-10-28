"""Finance Hub 1.6 — choose the features you use (each user, stored in their encrypted data).

Turning a feature off hides its pages from the menu, search and the Accounts tabs; nothing is deleted, and turning it on
again brings everything back. The first log-in after installing shows this page once ("What do you use?").
The page also lists the kinds of accounts you have, with a quick "Add" for anything missing — at any time.
"""
import json

from flask import render_template, request, redirect, url_for, flash, session, g

# key, label, description, group, icon, pages (endpoints), account kinds
FEATURES = [
    ('bank', 'Savings & current accounts', 'Bank statements, balances, UPI / NEFT transfers.', 'Everyday money', 'bi-bank', [], ['bank']),
    ('cards', 'Credit cards', 'Card statements, bills, due dates, reward points.', 'Everyday money', 'bi-credit-card-2-front', [], ['card']),
    ('loans', 'Loans & EMIs', 'Home / personal / gold loans and EMIs, with their schedules.', 'Everyday money', 'bi-house-door', ['loans'], ['loan', 'emi']),
    ('deposits', 'Deposits & schemes', 'FDs, RDs, PPF, EPF, NPS, bonds — values you update.', 'Everyday money', 'bi-safe2', [], ['deposit']),
    ('wallets', 'Wallets, cash & other assets', 'Wallets, cash in hand, gold, property and other assets.', 'Everyday money', 'bi-cash-coin', [], ['wallet', 'asset']),
    ('budgets', 'Budgets & regular payments', 'Monthly budgets, subscriptions and other recurring payments.', 'Everyday money', 'bi-pie-chart',
     ['budgets_page', 'recurring_page'], []),
    ('refunds', 'Failed payments & refunds', 'Payments that failed and came back; refunds you are waiting for.', 'Everyday money',
     'bi-arrow-counterclockwise', ['refunds_page'], []),
    ('people_loans', 'Loans with people', 'Money lent to or borrowed from friends and family.', 'Everyday money', 'bi-person-lines-fill', ['pl_page'], []),
    ('business', 'My own business (company books)', 'Separate books for your company; director’s account.', 'Business', 'bi-briefcase',
     ['director_page'], []),
    ('reimbursements', 'Expenses a client pays back', 'Travel and other costs you pay for a client and claim back.', 'Business',
     'bi-receipt-cutoff', ['reimb_page'], []),
    ('investments', 'Stocks, ETFs & brokers', 'Contract notes, portfolio and plan, trades, holdings by broker.', 'Investing', 'bi-graph-up-arrow',
     ['inv_portfolio', 'inv_stock', 'inv_trades', 'inv_import', 'inv_brokers_page', 'asset_types_page'], ['broker']),
    ('demat', 'Demat check (CDSL / NSDL)', 'Reconcile CDSL / NSDL statements with each broker.', 'Investing', 'bi-shield-check', ['demat_page'], []),
    ('planning', 'Wealth planner & tools', 'Compounding planner, card and loan calculators.', 'Investing', 'bi-compass', ['planner', 'tools_page'], []),
    ('mail', 'Mail inbox', 'Statements that arrive by mail are read and imported.', 'Automation', 'bi-envelope', ['mail_page'], []),
    ('reminders', 'Reminders & reports by mail', 'A mail the day before a payment is due, and a weekly dues report.', 'Automation', 'bi-bell',
     ['reminders_page'], []),
]
GROUPS = ['Everyday money', 'Business', 'Investing', 'Automation']
BY_KEY = {f[0]: f for f in FEATURES}
REQUIRES = {'demat': 'investments'}


def _get(con, key, default=''):
    try:
        r = con.execute('SELECT value FROM hub_settings WHERE key=?', (key,)).fetchone()
        return r[0] if r else default
    except Exception:  # noqa: BLE001
        return default


def off(con):
    try:
        return set(json.loads(_get(con, 'features_off', '[]')))
    except ValueError:
        return set()


def hidden(con):
    """→ (endpoints hidden, account kinds hidden)"""
    o = off(con)
    for k, need in REQUIRES.items():
        if need in o:
            o.add(k)
    eps, kinds = set(), set()
    for key, *_rest in FEATURES:
        if key in o:
            f = BY_KEY[key]
            eps.update(f[5])
            kinds.update(f[6])
    if not ({'cards', 'loans'} <= o):
        eps.discard('tools_page')               # card & loan tools stay while cards or loans are in use
    return eps, kinds


def register(app, get_db, vault):

    @app.context_processor
    def _features_ctx():
        eps, kinds = set(), set()
        try:
            if vault.unlocked and session.get('user'):
                eps, kinds = hidden(get_db())
        except Exception:  # noqa: BLE001
            pass
        return {'hidden_eps': eps, 'hidden_kinds': kinds}

    @app.before_request
    def _features_guard():
        ep = request.endpoint or ''
        if not vault.unlocked or not session.get('user') or not getattr(g, 'user', None):
            return None
        con = get_db()
        wizard = not app.testing or app.config.get('FH_WIZARD')       # the automated tests skip the welcome step
        if wizard and ep == 'home' and request.method == 'GET':
            import welcome
            if welcome.needed(con):
                return redirect(url_for('welcome_step', name='you'))       # 1.7: the first-start setup wizard
        eps, _ = hidden(con)
        if ep in eps:
            name = next((f[1] for f in FEATURES if ep in f[5]), 'This feature')
            flash(f'“{name}” is turned off. Turn it on here to use that page.', 'info')
            return redirect(url_for('features_page'))
        return None

    def features_page():
        import accounts_hub as AH
        con = get_db()
        o = off(con)
        counts = {k: 0 for k in AH.KIND}
        try:
            for r in con.execute("SELECT COALESCE(kind,'bank') k, COUNT(*) n FROM accounts WHERE COALESCE(status,'active')<>'closed' GROUP BY 1"):
                counts[r['k']] = r['n']
        except Exception:  # noqa: BLE001
            pass
        try:
            counts['broker'] = con.execute('SELECT COUNT(*) FROM inv_brokers WHERE EXISTS (SELECT 1 FROM inv_trades t WHERE t.broker_id=inv_brokers.id) '
                                           'OR client_id IS NOT NULL').fetchone()[0]
        except Exception:  # noqa: BLE001
            pass
        try:
            demats = con.execute('SELECT COUNT(*) FROM inv_demats').fetchone()[0]
        except Exception:  # noqa: BLE001
            demats = 0
        books = [r[0] for r in con.execute("SELECT name FROM entities WHERE name<>'Personal' AND COALESCE(role,'book')='book'")] \
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='entities'").fetchone() else []
        return render_template('features.html', FEATURES=FEATURES, GROUPS=GROUPS, off=o, counts=counts, KIND=AH.KIND,
                               demats=demats, books=books, welcome=request.args.get('welcome') == '1', REQUIRES=REQUIRES)

    def features_save():
        con = get_db()
        on = set(request.form.getlist('on'))
        new_off = sorted(k for k, *_r in FEATURES if k not in on)
        for k, need in REQUIRES.items():
            if need in new_off and k not in new_off:
                new_off.append(k)
        con.execute("INSERT OR REPLACE INTO hub_settings (key, value) VALUES ('features_off', ?)", (json.dumps(sorted(new_off)),))
        con.execute("INSERT OR REPLACE INTO hub_settings (key, value) VALUES ('features_done', '1')")
        con.commit()
        flash('Saved — the menu now shows only what you use. Change it any time on Settings › Features & accounts.', 'success')
        return redirect(url_for('home') if request.form.get('welcome') else url_for('features_page'))

    app.add_url_rule('/features', 'features_page', features_page, methods=['GET'])
    app.add_url_rule('/features/save', 'features_save', features_save, methods=['POST'])
