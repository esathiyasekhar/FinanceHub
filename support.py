"""Finance Hub 1.7 — report a problem.

The form collects what happened, and — only if you leave it ticked — technical details that help find the cause:
version, Windows / Python version, which features are on, and recent error lines from the log. Before anything is sent
you see the exact text. Numbers of 4+ digits, e-mail addresses and file paths are masked, and no statement contents,
amounts, names or passwords are ever included.

Sending: through the Hub's own mailbox (Settings › Mail inbox) to the support address in hub_version.SUPPORT_EMAIL.
Without a mailbox the report opens in your mail program, or can be saved as a text file to attach yourself.
"""
import platform
import re
import sys
import uuid
from datetime import datetime
from urllib.parse import quote

from flask import render_template, request, redirect, url_for, flash, Response, g

MAX_LOG_LINES = 60


def scrub(text):
    """Remove anything personal-looking from log lines / descriptions that go out in a report."""
    t = re.sub(r'[\w.+-]+@[\w-]+\.[\w.]+', '<e-mail>', text or '')
    t = re.sub(r'(?i)\b[A-Z]{5}\d{4}[A-Z]\b', '<PAN>', t)
    t = re.sub(r'(?:[A-Za-z]:\\|/)(?:[^\s"\'<>|]+[\\/])+([^\s"\'<>|\\/]*)', r'<path>/\1', t)
    t = re.sub(r'\d[\d,]{3,}(?:\.\d+)?', '<number>', t)
    return t


def recent_errors(log_dir, ref=None):
    """WARNING / ERROR lines and tracebacks from the newest log, scrubbed."""
    p = log_dir / 'hub.log'
    try:
        lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    keep, in_tb = [], False
    for ln in lines[-3000:]:
        if ' ERROR ' in ln or ' WARNING ' in ln or 'Traceback' in ln:
            keep.append(ln)
            in_tb = 'Traceback' in ln or ' ERROR ' in ln
        elif in_tb and (ln.startswith((' ', '\t')) or re.match(r'^\w+(Error|Exception)\b', ln)):
            keep.append(ln)
        else:
            in_tb = False
    if ref:                                      # the traceback logged just before 'Error reference <ref>'
        idx = max((i for i, l in enumerate(keep) if ref in l), default=None)
        if idx is not None:
            keep = keep[max(0, idx - MAX_LOG_LINES + 1):idx + 1]
    return [scrub(l)[:300] for l in keep[-MAX_LOG_LINES:]]


def diagnostics(con, vault, app):
    import hub_paths
    from hub_version import VERSION
    try:
        from statement_reader import ENGINE_VERSION
    except Exception:  # noqa: BLE001
        ENGINE_VERSION = '?'
    lines = [f'Finance Hub {VERSION} · Statement Reader {ENGINE_VERSION}',
             f'Python {platform.python_version()} · {platform.system()} {platform.release()} ({platform.version()[:40]})',
             f"Installed: {'yes (program and data folders separate)' if hub_paths.INSTALLED else 'portable folder'}",
             f"Server: {(app.config.get('HUB_SERVER') or (lambda: 'command window'))()}"]
    try:
        import features
        off = sorted(features.off(con))
        lines.append('Features off: ' + (', '.join(off) if off else 'none'))
    except Exception:  # noqa: BLE001
        pass
    try:
        n = {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('accounts', 'transactions', 'statements')}
        lines.append('Counts: ' + ', '.join(f'{k} {v}' for k, v in n.items()))
    except Exception:  # noqa: BLE001
        pass
    try:
        import mailreader as MR
        ms = MR.settings(con)
        lines.append(f"Mail inbox: {'set up (' + MR.provider(ms) + ')' if MR.configured(ms) else 'not set up'}"
                     f"{', automatic' if ms.get('enabled') == '1' else ''}")
    except Exception:  # noqa: BLE001
        pass
    return lines


def compose(form, diag, log_lines, user_contact):
    ref = re.sub(r'[^A-Z0-9]', '', form.get('ref', '').upper())[:12]
    t = lambda k: scrub(form.get(k, '').strip())          # what you type is masked the same way as the log
    parts = [f"Summary: {t('summary')}",
             f"Where in the Hub: {t('where') or '-'}",
             f"How bad: {form.get('severity', 'normal')}",
             '', 'What happened:', t('what') or '-',
             '', 'Steps to make it happen again:', t('steps') or '-',
             '', 'What I expected:', t('expected') or '-']
    if ref:
        parts += ['', f'Error reference: {ref}']
    if user_contact:
        parts += ['', f'Reply to: {user_contact}']
    if diag:
        parts += ['', '--- Technical details ---'] + diag
    if log_lines:
        parts += ['', '--- Recent errors from the log (numbers, e-mails and paths masked) ---'] + log_lines
    parts += ['', f'Sent {datetime.now():%Y-%m-%d %H:%M} from Finance Hub.']
    return '\n'.join(parts)


def register(app, get_db, vault):
    import hub_paths
    from hub_version import SUPPORT_EMAIL, VERSION

    def _build():
        con = get_db()
        f = request.form if request.method == 'POST' else request.args
        diag = diagnostics(con, vault, app) if f.get('diag', '1') == '1' else []
        logs = recent_errors(hub_paths.LOG_DIR, f.get('ref')) if f.get('logs', '1') == '1' else []
        contact = (f.get('contact') or '').strip()
        return con, f, compose(f, diag, logs, contact), contact

    def page():
        con, f, text, contact = _build()
        import mailreader as MR
        ms = MR.settings(con)
        return render_template('support.html', text=text, f=f, support=SUPPORT_EMAIL, mail_ready=MR.configured(ms),
                               default_contact=ms.get('user', ''), ref=f.get('ref', ''))

    def send():
        con, f, text, contact = _build()
        if not (f.get('summary') or '').strip():
            flash('Give the problem a short summary first.', 'warning')
            return page()
        subject = f"Finance Hub {VERSION} — problem: {scrub(f.get('summary', '').strip())[:80]}"
        action = f.get('action', 'send')
        if action == 'download':
            return Response(text, mimetype='text/plain', headers={'Content-Disposition': 'attachment; filename="FinanceHub_problem_report.txt"'})
        if action == 'mailto':
            body = text if len(text) < 1800 else text[:1800] + '\n…(shortened — use “Save as a file” in the Hub and attach it for the full text)'
            return redirect(f'mailto:{SUPPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}')
        import mailreader as MR
        import notify
        ms = MR.settings(con)
        smtp = notify.smtp_for(ms, notify.settings(con))
        if not notify.smtp_ready(smtp):
            flash('The Hub mailbox is not set up — use “Open in my mail program” or “Save as a file” instead.', 'warning')
            return page()
        try:
            notify.send_mail(smtp, [SUPPORT_EMAIL], subject, None, text, app.config.get('HUB_SMTP_FACTORY'), reply_to=contact or None)
            app.logger.info('Problem report sent to support')
            flash(f'Thank you — your report was sent to {SUPPORT_EMAIL}.', 'success')
            return redirect(url_for('help_page'))
        except Exception as e:  # noqa: BLE001
            flash(f'Could not send ({str(e)[:120]}). Use “Open in my mail program” or “Save as a file” instead.', 'danger')
            return page()                                # keeps what you typed

    @app.errorhandler(500)
    def _server_error(e):
        ref = uuid.uuid4().hex[:8].upper()
        app.logger.error('Error reference %s on %s %s', ref, request.method, request.path)
        return render_template('auth_error.html', ref=ref), 500

    app.add_url_rule('/support', 'support_page', page, methods=['GET'])
    app.add_url_rule('/support/send', 'support_send', send, methods=['POST'])
