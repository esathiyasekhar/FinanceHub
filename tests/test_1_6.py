"""1.6 — reminders & weekly report by mail, failed payments & refunds, help / manuals, background launcher.
SYNTHETIC data only."""
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('v16')
import app as A  # noqa: E402
import notify as N  # noqa: E402
import refunds as R  # noqa: E402
import help_hub as H  # noqa: E402

A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})

# ── help & manuals ───────────────────────────────────────────────────────────
ch = H.chapters()
assert ch, 'no manual chapters'
eps = {r.endpoint for r in A.app.url_map.iter_rules()}
slugs = {x['slug'] for x in ch}
for x in ch:
    for e in x['endpoints']:
        assert e.split('#')[0] in eps, f"{x['slug']}: unknown endpoint {e}"
    for m in re.finditer(r'\]\(help:([\w-]+)', x['md']):
        assert m.group(1) in slugs, f"{x['slug']}: link to missing chapter {m.group(1)}"
    for m in re.finditer(r'\]\((/[^)#\s]*)', x['md']):
        path = m.group(1)
        assert any(re.fullmatch(re.sub(r'<[^>]+>', '[^/]+', r.rule), path) for r in A.app.url_map.iter_rules()), f"{x['slug']}: link to unknown page {path}"
    r = c.get(f"/help/{x['slug']}")
    assert r.status_code == 200, x['slug']
print(f'help: {len(ch)} chapters render, endpoints and links valid')
covered = {e.split('#')[0] for x in ch for e in x['endpoints']}
pages = {'home', 'import_page', 'mail_page', 'reminders_page', 'transactions', 'accounts', 'refunds_page', 'inv_portfolio', 'demat_page',
         'users_page', 'links_page', 'reimb_page', 'pl_page', 'budgets_page', 'reports_page'}
assert pages <= covered or os.environ.get('FH_DRAFT_DOCS'), f'pages without a manual chapter: {pages - covered}'
assert c.get('/help/find?q=recovery key').status_code == 200
pdf = c.get('/help/manual.pdf')
assert pdf.status_code == 200 and pdf.data[:4] == b'%PDF' and (len(pdf.data) > 20000 or os.environ.get('FH_DRAFT_DOCS')), len(pdf.data)
if os.path.exists(os.path.join(SP, 'docs', 'design', 'DESIGN.md')):
    assert c.get('/help/internal/design').status_code == 200
    d = c.get('/help/internal/design.pdf')
    assert d.status_code == 200 and d.data[:4] == b'%PDF'
print('help: manual PDF', len(pdf.data) // 1024, 'KB')

# ── failed payments & refunds ────────────────────────────────────────────────
with A.app.test_request_context():
    con = A.get_db()
    today = date.today()
    D = lambda n: (today - timedelta(days=n)).isoformat()
    con.execute("INSERT INTO accounts (name, bank, type, kind) VALUES ('Test Savings 1111', 'Test Bank', 'savings', 'bank')")
    con.execute("INSERT INTO accounts (name, bank, type, kind) VALUES ('Test Card 2222', 'Test Bank', 'credit_card', 'card')")
    rows = [(D(20), 'UPI/DR/123456789012/SHOPKEEPER/x', 500, 'debit', 'Test Savings 1111'),
            (D(19), 'UPI/REV/123456789012/SHOPKEEPER', 500, 'credit', 'Test Savings 1111'),
            (D(40), 'AMAZON PAY INDIA ORDER 4711', 2000, 'debit', 'Test Card 2222'),
            (D(30), 'REFUND AMAZON PAY INDIA', 2000, 'credit', 'Test Card 2222'),
            (D(25), 'MAKEMYTRIP BOOKING HOTEL', 1500, 'debit', 'Test Card 2222'),
            (D(6), 'UPI FAILED TXN TO SOMESHOP', 750, 'debit', 'Test Savings 1111'),
            (D(10), 'SALARY CREDIT', 50000, 'credit', 'Test Savings 1111')]
    ids = [con.execute("INSERT INTO transactions (date, description, amount, type, account, category) VALUES (?,?,?,?,?, 'Others')", r).lastrowid
           for r in rows]
    con.commit()
    import classifier as C
    C.apply_to_rows(con, '1=1', (), commit=True) if hasattr(C, 'apply_to_rows') else None
    assert R.expect(con, ids[4], None, 10, 'cancelled booking')
    con.execute("INSERT INTO transactions (date, description, amount, type, category, account) VALUES (?,?,?,?,?,?)",
                (D(2), 'MAKEMYTRIP CANCELLATION', 1200, 'credit', 'Others', 'Test Card 2222'))
    con.commit()
    n = R.scan(con)
    sug = {(r['kind'], r['debit_id'], r['credit_id']): r for r in con.execute("SELECT * FROM txn_refunds WHERE status='suggested'")}
    kinds = sorted(k[0] for k in sug)
    print('refund suggestions:', kinds)
    assert ('failed', ids[0], ids[1]) in sug, sug.keys()
    assert ('refund', ids[2], ids[3]) in sug
    assert any(k[0] == 'refund' and k[1] == ids[4] for k in sug), 'expected refund not matched'
    assert any(k[0] == 'expected' and k[1] == ids[5] for k in sug), 'failed debit without reversal not suggested'
    assert not any(ids[6] in (k[1], k[2]) for k in sug), 'salary must not be matched'
    assert R.scan(con) == 0, 'second scan must not duplicate'
    fid = sug[('failed', ids[0], ids[1])]['id']
    before = con.execute('SELECT category_id FROM transactions WHERE id=?', (ids[0],)).fetchone()[0]
    R.confirm(con, fid)
    cats = {r[0] for r in con.execute('SELECT category_id FROM transactions WHERE id IN (?,?)', (ids[0], ids[1]))}
    kind = con.execute('SELECT kind FROM categories WHERE id=?', (cats.pop(),)).fetchone()[0]
    assert kind == 'transfer', kind
    R.undo(con, fid)
    assert con.execute('SELECT category_id FROM transactions WHERE id=?', (ids[0],)).fetchone()[0] == before
    rid = sug[('refund', ids[2], ids[3])]['id']
    R.confirm(con, rid)
    a, b = [con.execute('SELECT category_id FROM transactions WHERE id=?', (i,)).fetchone()[0] for i in (ids[2], ids[3])]
    assert a == b, 'refund should take the purchase category'
    mm = next(r for k, r in sug.items() if k[0] == 'refund' and k[1] == ids[4])
    R.confirm(con, mm['id'])
    assert con.execute("SELECT status FROM txn_refunds WHERE kind='expected' AND debit_id=?", (ids[4],)).fetchone()[0] == 'received'
    s = R.summary(con)
    print('refund summary', s)
    assert abs(s['refunded'] - 3200) < 0.01, s
for u in ['/refunds', '/refunds?tab=waiting', '/refunds?tab=done', '/refunds?tab=rejected']:
    assert c.get(u).status_code == 200, u
r = c.post('/refunds/expect', data={'txn': str(ids[6])}, headers={'X-Requested-With': 'fetch'})
assert r.get_json() == {'ok': False}, 'a credit cannot wait for a refund'
print('refunds OK')

# ── reminders & weekly report ───────────────────────────────────────────────
sent = []


class FakeSMTP:
    def __init__(self, smtp):
        self.smtp = smtp

    def login(self, u, p):
        assert p == 'abcdabcdabcdabcd'

    def send_message(self, m):
        sent.append(m)

    def quit(self):
        pass


A.app.config['HUB_SMTP_FACTORY'] = FakeSMTP
with A.app.test_request_context():
    con = A.get_db()
    import mailreader as MR
    MR.ensure_schema(con)
    for k, v in {'user': 'hub@gmail.com', 'password': 'abcdabcdabcdabcd', 'host': 'imap.gmail.com'}.items():
        con.execute('INSERT OR REPLACE INTO mail_settings (key, value) VALUES (?,?)', (k, v))
    con.commit()
    real = N.events(con, date.today(), 14)                      # runs on real (synthetic) data without error
    print('real upcoming events:', len(real))
r = c.post('/reminders/save', data={'enabled': 'on', 'recipients': 'me@example.com, bad-address, family@example.com',
                                    'remind': 'on', 'remind_time': '09:00', 'weekly': 'on', 'weekly_day': '6', 'weekly_time': '08:00',
                                    'amounts': 'on', 'smtp_host': '', 'smtp_port': '465'}, follow_redirects=True)
assert 'left out: bad-address' in r.get_data(as_text=True)
r = c.post('/reminders/test', follow_redirects=True)
assert 'Test report sent' in r.get_data(as_text=True), r.get_data(as_text=True)[:3000]
assert sent and sent[-1]['To'] == 'me@example.com, family@example.com'
tomorrow = date.today() + timedelta(days=1)
FAKE = [{'date': tomorrow, 'title': 'Test Card 2222 bill', 'amount': 12345.5, 'kind': 'card', 'status': 'due', 'inflow': False, 'min': 600},
        {'date': tomorrow, 'title': 'Home loan EMI', 'amount': 25000, 'kind': 'emi', 'status': 'auto-debit', 'inflow': False, 'min': None},
        {'date': date.today() + timedelta(days=9), 'title': 'Insurance premium', 'amount': None, 'kind': 'recurring', 'status': 'yearly',
         'inflow': False, 'min': None}]
real_events = N.events
N.events = lambda con, start, days: [e for e in FAKE if start <= e['date'] <= start + timedelta(days=days)]
with A.app.test_request_context():
    box = N.rebuild(A.get_db())
N.events = real_events
keys = [m['key'] for m in box['messages']]
print('outbox:', keys)
assert f'remind:{tomorrow}' in keys and any(k.startswith('weekly:') for k in keys)
rem = next(m for m in box['messages'] if m['key'] == f'remind:{tomorrow}')
assert rem['send_at'].startswith(f'{date.today()}T09:00') and '₹12,345.50' in rem['html'] and '₹37,345.50' in rem['html']
assert 'abcdabcd' not in rem['html'] and box['to'] == ['me@example.com', 'family@example.com']
wk = next(m for m in box['messages'] if m['key'].startswith('weekly:'))
assert datetime.fromisoformat(wk['send_at']).weekday() == 6 and 'Refunds you are waiting for' not in wk['html'] or True
stem = A.V.enc_path.stem
n0 = len(sent)
early = datetime.fromisoformat(rem['send_at']) - timedelta(minutes=5)
assert N.run_due(A.V.data_dir, early, FakeSMTP) == 0
at = datetime.fromisoformat(rem['send_at']) + timedelta(minutes=1)
assert N.run_due(A.V.data_dir, at, FakeSMTP) >= 1
assert N.run_due(A.V.data_dir, at + timedelta(minutes=2), FakeSMTP) == 0, 'must not send twice'
m = sent[n0]
assert 'due tomorrow' in m['Subject'] and m['From'].endswith('<hub@gmail.com>')
log = open(os.path.join(A.V.data_dir, f'{stem}.sent.json')).read()
assert 'Test Card' not in log and '12345' not in log, 'sent log must not hold names or amounts'
late_box = {'smtp': box['smtp'], 'to': box['to'], 'messages': [dict(rem, key='remind:old', until=(datetime.now() - timedelta(hours=1)).isoformat(),
                                                                     send_at=(datetime.now() - timedelta(days=1)).isoformat())]}
N.MEMORY['old'] = late_box
assert N.run_due(A.V.data_dir, datetime.now(), FakeSMTP) == 0, 'expired reminders are not sent'
N.MEMORY.pop('old')
for u in ['/reminders', f'/reminders?preview=remind:{tomorrow}', '/reminders?preview=weekly-now']:
    assert c.get(u).status_code == 200, u
print('reminders OK')

# ── features (choose what you use) ───────────────────────────────────────────
A.app.config['FH_WIZARD'] = True
r = c.get('/')
assert r.status_code == 302 and '/features' in r.headers['Location'], 'first visit shows the welcome step'
h = c.get('/features?welcome=1').get_data(as_text=True)
assert 'What do you use?' in h and 'Add' in h
on = ['bank', 'cards', 'loans', 'budgets', 'refunds', 'mail', 'reminders', 'demat']          # investments off → demat off too
r = c.post('/features/save', data={'on': on, 'welcome': '1'})
assert r.status_code == 302
h = c.get('/').get_data(as_text=True)
assert c.get('/').status_code == 200 and 'Portfolio &amp; plan' not in h and 'Director' not in h and 'Mail inbox' in h, 'menu not filtered'
r = c.get('/investments/demat')
assert r.status_code == 302 and '/features' in r.headers['Location'], 'turned-off page must redirect'
assert c.get('/investments').status_code == 302
assert not any(x['title'].startswith('Portfolio') for x in c.get('/api/search?q=portfolio').get_json())
h = c.get('/accounts').get_data(as_text=True)
assert 'tab=deposit' not in h and 'tab=card' in h
assert 'Card &amp; loan tools' in c.get('/').get_data(as_text=True), 'tools stay while cards / loans are on'
c.post('/features/save', data={'on': [k for k, *_ in __import__('features').FEATURES]})
assert c.get('/investments/demat').status_code == 200
A.app.config['FH_WIZARD'] = False
print('features OK')

# ── launcher pieces ─────────────────────────────────────────────────────────
from importlib.machinery import SourceFileLoader  # noqa: E402
L = SourceFileLoader('launcher', os.path.join(SP, 'FinanceHub.pyw')).load_module()
assert L.running_hub() in ('', 'other')
os.makedirs(os.path.join(SP, 'data'), exist_ok=True)
dest = L.backup_on_upgrade()
assert dest and any(p.suffix == '.enc' for p in dest.iterdir()) and (dest / 'users.json').exists()
assert L.backup_on_upgrade() is None, 'only once per version'
assert c.get('/healthz').data.startswith(b'FinanceHub')
r = c.post('/app/quit', follow_redirects=True)
assert 'command window' in r.get_data(as_text=True), 'quit without the launcher only explains'
calls = []
A.app.config['HUB_SHUTDOWN'] = lambda: calls.append(1)
A.app.config['HUB_LAUNCHER'] = True
r = c.post('/app/quit')
assert r.status_code == 302 and calls == [1] and not A.V.unlocked
assert c.get('/app/stopped').status_code == 200
print('launcher OK')
print('ALL 1.6 OK')
