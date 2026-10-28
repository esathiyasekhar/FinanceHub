"""Finance Hub 1.7 — the first-start setup wizard.

Right after a new user is created (name, user ID, password, recovery key) the Hub walks through:
  1. About you      — your name, and your company if you have one (it becomes a separate book)
  2. Mail           — the Hub's own mailbox (optional) and where reminders / reports go
  3. Features       — what you use (changeable later on Settings › Features & accounts)
  4. Accounts       — add the accounts you have (or let statements create them)
  5. Backup         — OneDrive / Google Drive / a folder, and how often
Every step can be skipped; everything can be changed later in Settings.
"""
import json
import re

from flask import render_template, request, redirect, url_for, flash, session

STEPS = [('you', 'About you', 'bi-person'), ('mail', 'Mail', 'bi-envelope'), ('features', 'Features', 'bi-toggles'),
         ('accounts', 'Accounts', 'bi-wallet2'), ('backup', 'Backup', 'bi-cloud-arrow-up')]
KEYS = [s[0] for s in STEPS]


def _get(con, key, default=''):
    try:
        r = con.execute('SELECT value FROM hub_settings WHERE key=?', (key,)).fetchone()
        return r[0] if r else default
    except Exception:  # noqa: BLE001
        return default


def _set(con, key, value):
    con.execute('INSERT OR REPLACE INTO hub_settings (key, value) VALUES (?,?)', (key, value))


def needed(con):
    """New users (no feature choice yet and not finished) see the wizard once."""
    return _get(con, 'onboarding') != 'done' and _get(con, 'features_done') != '1'


def register(app, get_db, vault):

    def step(name='you'):
        import features as F
        import mailreader as MR
        import notify as N
        import backup as B
        import accounts_hub as AH
        if name not in KEYS:
            return redirect(url_for('welcome_step', name='you'))
        con = get_db()
        MR.ensure_schema(con)
        N.ensure_schema(con)
        i = KEYS.index(name)
        nxt = KEYS[i + 1] if i + 1 < len(KEYS) else None
        if request.method == 'POST':
            f = request.form
            if f.get('skip') != '1':
                if name == 'you':
                    _set(con, 'display_name', f.get('display_name', '').strip()[:60])
                    company = f.get('company', '').strip()[:60]
                    if company and company.lower() != 'personal':
                        con.execute("INSERT OR IGNORE INTO entities (name, role, aliases, sort_order) VALUES (?, 'book', ?, 5)",
                                    (company, f.get('company_aliases', '').strip()[:200]))
                elif name == 'mail':
                    if f.get('user', '').strip():
                        con.execute("INSERT OR REPLACE INTO mail_settings (key, value) VALUES ('user', ?)", (f['user'].strip(),))
                        if f.get('password', '').strip():
                            con.execute("INSERT OR REPLACE INTO mail_settings (key, value) VALUES ('password', ?)",
                                        (f['password'].strip().replace(' ', ''),))
                        con.execute("INSERT OR REPLACE INTO mail_settings (key, value) VALUES ('enabled', ?)", ('1' if f.get('auto') else '0',))
                    rcpt = [x for x in re.split(r'[\s,;]+', f.get('recipients', '')) if N.EMAIL_RE.match(x.strip())]
                    if rcpt:
                        con.execute("INSERT OR REPLACE INTO notify_settings (key, value) VALUES ('recipients', ?)", ('\n'.join(rcpt),))
                        con.execute("INSERT OR REPLACE INTO notify_settings (key, value) VALUES ('enabled', ?)", ('1' if f.get('remind') else '0',))
                elif name == 'features':
                    on = set(f.getlist('on'))
                    off = sorted(k for k, *_r in F.FEATURES if k not in on)
                    for k, need in F.REQUIRES.items():
                        if need in off and k not in off:
                            off.append(k)
                    _set(con, 'features_off', json.dumps(sorted(off)))
                    _set(con, 'features_done', '1')
                elif name == 'backup':
                    d = (f.get('custom') or '').strip() if f.get('where') == 'custom' else (f.get('where') or '').strip()
                    if d:
                        try:
                            B.target_dir(d)
                            B.save_settings(vault, vault.user, dir=d, every=f.get('every') if f.get('every') in B.EVERY else 'weekly', keep=10)
                        except OSError as e:
                            flash(f'That backup folder cannot be used: {e}', 'warning')
                            return redirect(url_for('welcome_step', name='backup'))
            if name == 'features':
                _set(con, 'features_done', '1')
            con.commit()
            if nxt:
                return redirect(url_for('welcome_step', name=nxt))
            _set(con, 'onboarding', 'done')
            _set(con, 'features_done', '1')
            con.commit()
            flash('All set! You can change any of this later in Settings.', 'success')
            return redirect(url_for('import_page') if request.form.get('then') == 'import' else url_for('home'))
        ms, ns = MR.settings(con), N.settings(con)
        counts = {k: 0 for k in AH.KIND}
        for r in con.execute("SELECT COALESCE(kind,'bank') k, COUNT(*) n FROM accounts GROUP BY 1"):
            counts[r['k']] = r['n']
        books = [r[0] for r in con.execute("SELECT name FROM entities WHERE name<>'Personal' AND COALESCE(role,'book')='book'")]
        return render_template('welcome.html', step=name, STEPS=STEPS, i=i, nxt=nxt, display_name=_get(con, 'display_name'),
                               ms=ms, ns=ns, FEATURES=F.FEATURES, GROUPS=F.GROUPS, off=F.off(con), REQUIRES=F.REQUIRES,
                               counts=counts, KIND=AH.KIND, hidden_kinds=F.hidden(con)[1], books=books,
                               clouds=B.cloud_folders(), bs=B.settings_of(vault, vault.user), EVERY=B.EVERY)

    app.add_url_rule('/welcome', 'welcome_step', step, methods=['GET', 'POST'])
    app.add_url_rule('/welcome/<name>', 'welcome_step', step, methods=['GET', 'POST'])
