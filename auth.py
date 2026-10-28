"""Finance Hub 1.2 — first-run setup, login / logout, recovery, user management, idle lock."""
import time
from pathlib import Path

from flask import render_template, request, redirect, url_for, flash, session, jsonify, g

import vault as VT

_RK = {}            # recovery keys waiting to be shown once — kept in memory, never in the (unencrypted) session cookie


def _hold_key(rk):
    import secrets
    _RK.clear()
    t = secrets.token_urlsafe(16)
    _RK[t] = rk
    return t


OPEN_ENDPOINTS = {'login', 'setup', 'recover', 'static', 'logout', 'healthz', 'app_stopped', 'setup_restore'}


def register(app, V, prepare_db):

    @app.before_request
    def _guard():
        ep = request.endpoint or ''
        if ep in OPEN_ENDPOINTS:
            return None
        if not V.is_setup():
            return redirect(url_for('setup'))
        idle = V.idle_minutes()
        if V.unlocked and idle and time.time() - V.last > idle * 60:
            V.lock_now()
            session.clear()
            flash(f'Locked after {idle} minutes without use — log in again.', 'info')
        if not V.unlocked or session.get('vault') != V.nonce or not session.get('user'):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'ok': False, 'msg': 'locked — log in again'}), 401
            return redirect(url_for('login', next=request.full_path if request.method == 'GET' else None))
        if ep != 'mail_poll':                 # background mail checks do not count as use (idle lock still applies)
            V.last = time.time()
        g.user = session['user']
        g.role = V.role(session['user'])
        if V.must_change(session['user']) and ep not in ('change_password', 'logout', 'static', 'healthz'):
            return redirect(url_for('change_password'))          # 1.7: an administrator reset this password
        if ep in ('user_remove', 'security_settings', 'plain_cleanup') or \
                (ep == 'user_save' and request.form.get('action') in ('add', 'role', 'reset', 'rename_other')):
            if g.role != 'admin':
                flash('Only an administrator can add or remove users.', 'warning')
                return redirect(url_for('users_page'))
        if V.needs_recovery_key() and ep not in ('recovery_show',) and request.method == 'GET':
            session['show_recovery'] = _hold_key(V.new_recovery())
            return redirect(url_for('recovery_show'))
        return None

    def idle_watch():
        """1.6: lock after the idle time even when no browser tab is open (runs every minute in the background)."""
        idle = V.idle_minutes()
        if V.unlocked and idle and time.time() - V.last > idle * 60:
            V.lock_now()
            app.logger.info('Locked after %s idle minutes', idle)
    import notify
    notify.EXTRA_TICKS.append(idle_watch)

    @app.context_processor
    def _inject_user():
        name = ''
        if V.unlocked and session.get('user'):
            try:
                r = V.connect().execute("SELECT value FROM hub_settings WHERE key='display_name'").fetchone()
                name = r[0] if r else ''
            except Exception:  # noqa: BLE001
                name = ''
        return {'current_user': session.get('user'), 'current_role': getattr(g, 'role', None), 'display_name': name}

    def setup():
        if V.is_setup():
            return redirect(url_for('login'))
        copies = VT.plaintext_copies(V.base)
        if request.method == 'POST':
            u, p1, p2 = request.form.get('username', '').strip(), request.form.get('password', ''), request.form.get('password2', '')
            err = _check_new(u, p1, p2)
            if err:
                flash(err, 'warning')
                return render_template('auth_setup.html', copies=copies)
            erased = []
            if request.form.get('erase'):          # 1.2: start clean — old unencrypted data is overwritten and removed
                for f in copies:
                    if VT.secure_delete(f):
                        erased.append(str(f.relative_to(V.base)))
            rk = V.setup(u, p1, request.form.get('full_name', '').strip())
            prepare_db()
            session.clear()
            session['user'], session['vault'] = u, V.nonce
            session['show_recovery'] = _hold_key(rk)
            return redirect(url_for('recovery_show', removed=len(erased)))
        return render_template('auth_setup.html', copies=copies)

    def recovery_show():
        rk = _RK.pop(session.pop('show_recovery', None) or '', None)
        if not rk:
            return redirect(url_for('home'))
        return render_template('auth_recovery.html', rk=rk, removed=request.args.get('removed', ''), user=V.user,
                               copies=[str(p.relative_to(V.base)) for p in VT.plaintext_copies(V.base)])

    def login():
        if not V.is_setup():
            return redirect(url_for('setup'))
        if request.method == 'POST':
            ok, msg = V.login(request.form.get('username', ''), request.form.get('password', ''))
            if ok:
                prepare_db()                       # upgrades the tables when a new version is installed
                session.clear()
                session['user'], session['vault'] = request.form['username'].strip(), V.nonce
                from webutil import safe_next
                return redirect(safe_next(request.form.get('next'), url_for('home')))
            flash(msg, 'danger')
        return render_template('auth_login.html', next=request.args.get('next', ''))

    def logout():
        V.lock_now()
        session.clear()
        flash('Locked. The database is encrypted again.', 'info')
        return redirect(url_for('login'))

    def recover():
        if request.method == 'POST':
            f = request.form
            err = _check_new(f.get('username', 'x'), f.get('password', ''), f.get('password2', ''))
            if err:
                flash(err, 'warning')
            else:
                ok, msg = V.recover(f.get('username', '').strip(), f.get('recovery', ''), f.get('password', ''))
                if ok:
                    flash('Password reset — log in with the new password.', 'success')
                    return redirect(url_for('login'))
                flash(msg, 'danger')
        return render_template('auth_recover.html')

    def users_page():
        doc = V.users_doc()
        if g.role == 'admin' and doc.get('escrow') and doc['users'][V.user].get('escrow_key'):
            with V.lock:                         # 1.7: other administrators get the password-reset key too
                doc = V.users_doc()
                changed = False
                for name, u in doc['users'].items():
                    if u.get('role') == 'admin' and not u.get('escrow_key') and u.get('escrow_dek'):
                        try:
                            V.grant_reset_key(doc, name)
                            changed = True
                        except Exception:  # noqa: BLE001
                            pass
                if changed:
                    V.save_users(doc)
        can_reset = {name: V.can_reset(name) for name in doc['users']} if g.role == 'admin' else {}
        return render_template('users.html', users=doc['users'], ROLES=VT.ROLES, recovery=doc['users'][V.user].get('recovery'),
                               idle=V.idle_minutes(), copies=[str(p.relative_to(V.base)) for p in VT.plaintext_copies(V.base)],
                               enc_size=V.enc_path.stat().st_size if V.enc_path.exists() else 0, is_admin=g.role == 'admin',
                               can_reset=can_reset, escrow=bool(doc.get('escrow')))

    def user_save():
        f = request.form
        u, act = f.get('username', '').strip(), f.get('action', 'add')
        try:
            if act == 'add':
                err = _check_new(u, f.get('password', ''), f.get('password2', ''))
                if err:
                    raise ValueError(err)
                V.add_user(u, f['password'], f.get('role', 'member'), f.get('full_name', '').strip())
                flash(f'User {u} added.', 'success')
            elif act == 'password':
                err = _check_new(u, f.get('password', ''), f.get('password2', ''))
                if err:
                    raise ValueError(err)
                if u != session.get('user'):
                    raise ValueError('each user changes their own password (an administrator can reset it)')
                if not V.check_password(u, f.get('current', '')):
                    raise ValueError('current password is wrong')
                V.set_password(u, f['password'])
                flash(f'Password changed for {u}.', 'success')
            elif act == 'rename':                                  # 1.7: change your own user ID
                new = V.rename_user(session.get('user'), f.get('new_username', ''), f.get('current', ''))
                session['user'] = new
                flash(f'Your user ID is now {new} — use it the next time you log in.', 'success')
            elif act == 'reset':                                   # 1.7: administrator sets a temporary password
                err = _check_new(u, f.get('password', ''), f.get('password2', ''))
                if err:
                    raise ValueError(err)
                V.admin_reset_password(u, f['password'])
                flash(f'New password set for {u}. Give it to them; they must choose their own at the next log-in.', 'success')
            elif act == 'rename_other':
                err = _check_new(f.get('new_username', ''), f.get('password', ''), f.get('password2', ''))
                if err:
                    raise ValueError(err)
                new = V.rename_user(u, f.get('new_username', ''), f['password'])
                flash(f'{u} is now {new}, with the new password you gave. They choose their own at the next log-in.', 'success')
            elif act == 'role':
                V.set_role(u, f.get('role'))
                flash(f'{u} is now: {VT.ROLES[f.get("role")]}.', 'success')
        except (ValueError, KeyError) as e:
            flash(f'Not saved: {e}', 'warning')
        return redirect(url_for('users_page'))

    def user_remove():
        u = request.form.get('username', '')
        try:
            if u == session.get('user'):
                raise ValueError('you cannot remove yourself')
            V.remove_user(u)
            flash(f'User {u} removed.', 'info')
        except ValueError as e:
            flash(f'Not removed: {e}', 'warning')
        return redirect(url_for('users_page'))

    def change_password():
        """1.7: after an administrator reset — the user chooses their own password before anything else."""
        if request.method == 'POST':
            u = session.get('user')
            err = _check_new(u, request.form.get('password', ''), request.form.get('password2', ''))
            if not err and not V.check_password(u, request.form.get('current', '')):
                err = 'The temporary password is wrong.'
            if err:
                flash(err, 'warning')
            else:
                V.set_password(u, request.form['password'])
                flash('Password changed.', 'success')
                return redirect(url_for('home'))
        return render_template('auth_change.html', user=session.get('user'))

    def recovery_new():
        session['show_recovery'] = _hold_key(V.new_recovery())
        return redirect(url_for('recovery_show'))

    def security_settings():
        try:
            V.set_idle(int(request.form.get('idle_minutes', 30)))
            flash('Saved.', 'success')
        except ValueError:
            flash('Enter minutes as a number.', 'warning')
        return redirect(url_for('users_page'))

    def plain_cleanup():
        chosen = set(request.form.getlist('files'))
        done = []
        for p in VT.plaintext_copies(V.base):
            rel = str(p.relative_to(V.base))
            if rel in chosen and VT.secure_delete(p):
                done.append(rel)
        flash(f'Removed {len(done)} unencrypted cop{"ies" if len(done) != 1 else "y"}.' if done else 'Nothing removed.', 'success' if done else 'info')
        return redirect(url_for('users_page'))

    def profile_save():
        con = V.connect()
        con.execute("INSERT OR REPLACE INTO hub_settings (key, value) VALUES ('display_name', ?)", (request.form.get('display_name', '').strip()[:60],))
        con.commit()
        flash('Saved.', 'success')
        from webutil import safe_next
        return redirect(safe_next(request.form.get('next'), url_for('people_page')))

    for rule, ep, fn, methods in [
        ('/account/password', 'change_password', change_password, ['GET', 'POST']),
        ('/setup', 'setup', setup, ['GET', 'POST']),
        ('/setup/recovery-key', 'recovery_show', recovery_show, ['GET']),
        ('/login', 'login', login, ['GET', 'POST']),
        ('/logout', 'logout', logout, ['GET', 'POST']),
        ('/recover', 'recover', recover, ['GET', 'POST']),
        ('/users', 'users_page', users_page, ['GET']),
        ('/users/save', 'user_save', user_save, ['POST']),
        ('/users/remove', 'user_remove', user_remove, ['POST']),
        ('/users/recovery', 'recovery_new', recovery_new, ['POST']),
        ('/users/security', 'security_settings', security_settings, ['POST']),
        ('/users/cleanup', 'plain_cleanup', plain_cleanup, ['POST']),
        ('/profile/save', 'profile_save', profile_save, ['POST']),
    ]:
        app.add_url_rule(rule, ep, fn, methods=methods)


def _check_new(user, p1, p2):
    if not user or len(user) < 3 or not user.replace('.', '').replace('_', '').replace('-', '').isalnum():
        return 'User ID: at least 3 letters / numbers (. _ - allowed).'
    if len(p1) < 10:
        return 'Password: at least 10 characters (a short sentence is easiest to remember).'
    if sum(bool(set(p1) & set(s)) for s in ('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '0123456789',
                                             '!@#$%^&*()-_=+[]{};:,.<>/?|~ ')) < 3:
        return 'Password: mix at least three of — lower case, upper case, numbers, symbols / spaces.'
    if p1 != p2:
        return 'The two passwords do not match.'
    return ''
