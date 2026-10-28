"""Hub 1.4 demat reconciliation — SYNTHETIC data only."""
import sys, os, shutil, re, io
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from _common import fresh  # noqa: E402
SP = fresh('demat')
import app as A
A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
r = c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
assert r.status_code in (200, 302)
import depository as DP, investments as I
CAS = """NSDL Consolidated Account Statement for the period from 01-Sep-2026 to 30-Sep-2026
NSDL Demat Account
DP Name : ZERODHA BROKING LIMITED DP ID : IN300000 Client ID : 11112222
ISIN Security Face Value No. of Shares Market Price Value
INE000A01011 ALPHA INDUSTRIES LIMITED 10.00 50 2,850.00 1,42,500.00
INE000B01012 BETA BANK LTD 2.00 120 1,500.50 1,80,060.00
CDSL Demat Account
DP Name : RKSV SECURITIES INDIA PRIVATE LIMITED
BO ID : 1208160000001234
ISIN Security Current Bal Frozen Bal Pledge Bal Free Bal Market Price Value
INE000C01013 GAMMA NIFTY 50 ETF 300 0 0 300 250.00 75,000.00
INE000A01011 ALPHA INDUSTRIES LIMITED 10 0 0 10 2,850.00 28,500.00
Mutual Fund Folios
Folio No 12345 INF000X01019 SOME FUND GROWTH 100.000 50.00 5,000.00
"""
pv = DP.parse_text(CAS)
print('as_of', pv['as_of'], 'demats', [(a['depository'], a['dp_name'], a['account_no']) for a in pv['demats']])
for h in pv['holdings']: print('  ', h['acct'], h['isin'], h['name'], h['qty'], h['close'], h['value'])
assert pv['as_of'] == '2026-09-30' and len(pv['demats']) == 2 and len(pv['holdings']) == 4
g = [h for h in pv['holdings'] if h['isin'] == 'INE000C01013'][0]; assert g['qty'] == 300 and 'Nifty 50' in g['name'], g
assert [h for h in pv['holdings'] if h['isin'] == 'INE000B01012'][0]['qty'] == 120
assert I.classify_pdf(CAS)[1] == 'cas'
with A.app.test_request_context():
    con = A.get_db()
    assert not con.execute("SELECT 1 FROM inv_brokers WHERE name LIKE 'CAS%'").fetchone()
    b = {r['name']: r['id'] for r in con.execute('SELECT id, name FROM inv_brokers')}
    def T(br, isin, name, d, side, q, p):
        sid = I.security_id(con, I._symbol_from_name(name), isin, name)
        con.execute('INSERT INTO inv_trades (broker_id, security_id, trade_date, side, qty, price) VALUES (?,?,?,?,?,?)', (b[br], sid, d, side, q, p))
    T('Zerodha', 'INE000A01011', 'Alpha Industries', '2026-08-01', 'buy', 60, 2500)
    T('Zerodha', 'INE000A01011', 'Alpha Industries', '2026-08-20', 'sell', 10, 2700)
    T('Zerodha', 'INE000B01012', 'Beta Bank', '2026-08-05', 'buy', 60, 1400)
    T('Zerodha', 'INE000D01014', 'Delta Motors', '2026-08-07', 'buy', 10, 900)
    T('Zerodha', 'INE000A01011', 'Alpha Industries', '2026-10-05', 'buy', 1, 2900)
    T('Upstox', 'INE000C01013', 'Gamma Nifty 50 ETF', '2026-09-10', 'buy', 300, 240)
    T('Upstox', 'INE000A01011', 'Alpha Industries', '2026-09-29', 'buy', 10, 2800)
    T('Upstox', 'INE000B01012', 'Beta Bank', '2026-09-30', 'buy', 5, 1500)
    con.commit()
    n = DP.commit(con, {'pv': pv, 'file': 'synthetic_cas.pdf', 'hash': 'h1'}); con.commit(); print('committed', n)
    n2 = DP.commit(con, {'pv': pv, 'file': 'synthetic_cas_cdsl.pdf', 'hash': 'h2'}); con.commit()
    assert con.execute('SELECT COUNT(*) FROM inv_holdings WHERE demat_id IS NOT NULL').fetchone()[0] == 4, 'second CAS doubled holdings'
    dm = con.execute('SELECT d.*, b.name bn FROM inv_demats d LEFT JOIN inv_brokers b ON b.id=d.broker_id').fetchall()
    print('demats:', [(d['depository'], d['dp_id'], d['client_id'], d['bn']) for d in dm])
    assert {d['bn'] for d in dm} == {'Zerodha', 'Upstox'}
    acc, brk, _ = DP.reconcile(con)
    for g in acc:
        print('ACCOUNT', g['label'], g['broker'], g['as_of'], g['s'])
        for r in g['rows']: print('    ', r['name'], r['demat'], r['trades'], r['transit'], r['status'], '|', r['hint'])
    st = {(g['broker'], r['isin']): r['status'] for g in acc for r in g['rows']}
    assert st[('Zerodha', 'INE000A01011')] == 'matches'
    assert st[('Zerodha', 'INE000B01012')] == 'quantity differs'
    assert st[('Zerodha', 'INE000D01014')] == 'missing in demat'
    assert st[('Upstox', 'INE000C01013')] == 'matches' and st[('Upstox', 'INE000A01011')] == 'matches'
    assert st[('Upstox', 'INE000B01012')] == 'matches'   # bought on statement day: still settling
    hint = [r['hint'] for g in acc for r in g['rows'] if g['broker'] == 'Zerodha' and r['isin'] == 'INE000B01012'][0]; assert 'bonus' in hint
    hint = [r['hint'] for g in acc for r in g['rows'] if g['broker'] == 'Zerodha' and r['isin'] == 'INE000A01011'][0]; assert 'after the statement' in hint
    print('BROKERS', [(g['name'], g['s']) for g in brk])
    # portfolio still sees depository qty as statement qty
    rows, s, _ = I.build_portfolio(con)
    al = [r for r in rows if r['isin'] == 'INE000A01011'][0]; print('portfolio alpha qty', al['qty'], 'stmt', al['stmt_qty'])
# pages
c.post('/login', data={'username': 'tester', 'password': PW})
for u in ['/investments/demat', '/investments/demat?view=broker', '/investments/demat?view=add', '/investments/demat?edit=1',
          '/investments/import', '/investments', '/investments/brokers', '/report/demat/xlsx', '/report/demat/pdf', '/']:
    r = c.get(u); assert r.status_code == 200, (u, r.status_code); 
h = c.get('/investments/demat').get_data(as_text=True)
assert 'quantity differs' in h and '1234' in h and '1208160000001234' not in h
r = c.post('/investments/demat/save', data={'depository': 'NSDL', 'dp_name': 'Some DP', 'dp_id': 'IN301111', 'client_id': '22223333', 'broker_id': ''}, follow_redirects=True)
assert 'Demat account saved' in r.get_data(as_text=True)
r = c.post('/investments/demat/save', data={'bo_id': '123'}, follow_redirects=True); assert 'Enter the 16-digit' in r.get_data(as_text=True)
r = c.post('/investments/demat/save', data={'id': '1', 'action': 'link', 'broker_id': ''}, follow_redirects=True); assert 'link removed' in r.get_data(as_text=True)
h = c.get('/investments/demat?view=broker').get_data(as_text=True); assert 'No demat account linked to Zerodha' in h
print('pages OK')
# old-CAS migration
with A.app.test_request_context():
    con = A.get_db()
    bid = con.execute("INSERT INTO inv_brokers (name) VALUES ('CAS (CDSL / NSDL)')").lastrowid
    sid = con.execute("SELECT id FROM inv_securities LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO inv_holdings (broker_id, source, as_of, security_id, qty) VALUES (?,?,?,?,?)", (bid, 'x', '2026-01-01', sid, 5))
    con.commit(); DP.ensure_schema(con)
    assert not con.execute("SELECT 1 FROM inv_brokers WHERE name LIKE 'CAS%'").fetchone()
    assert con.execute("SELECT COUNT(*) FROM inv_holdings h JOIN inv_demats d ON d.id=h.demat_id WHERE d.account_no='EARLIER-CAS'").fetchone()[0] == 1
print('migration OK\nALL 1.4 OK')
