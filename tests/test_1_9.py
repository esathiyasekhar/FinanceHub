"""1.9 — categories without level limits (add / delete anywhere, new top-level groups), searchable category pickers,
automatic prices from NSE / BSE bhavcopies and AMFI NAVs. SYNTHETIC data only; the price files are faked."""
import io
import os
import sys
import time
import zipfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fresh  # noqa: E402

SP = fresh('v19')
import app as A  # noqa: E402
import classifier as C  # noqa: E402
import investments as I  # noqa: E402
import prices as P  # noqa: E402

A.app.testing = True
c = A.app.test_client()
PW = 'Synthetic pass 42'
c.post('/setup', data={'full_name': 'Test Person', 'username': 'tester', 'password': PW, 'password2': PW, 'erase': '1'})
c.post('/login', data={'username': 'tester', 'password': PW})


def cid(path):
    with A.app.test_request_context():
        return C.path_id(A.get_db(), tuple(path.split(' › ')), create=False)


# ── 1 + 2: categories at any depth, add / rename / move / delete ─────────────
h = c.get('/categories').get_data(as_text=True)
assert 'Add a category' in h and 'catSearch' in h and 'data-picker' in h
exp = cid('Expenses')
r = c.post('/categories/add', data={'parent_id': str(exp), 'name': 'Hobbies'}, follow_redirects=True)
assert 'Added “Hobbies”' in r.get_data(as_text=True)
parent = cid('Expenses › Hobbies')
for lvl, name in enumerate(['Music', 'Guitar', 'Strings', 'Nylon', 'Brand X'], 3):     # 7 levels deep
    r = c.post('/categories/add', data={'parent_id': str(parent), 'name': name}, follow_redirects=True)
    assert f'Added “{name}”' in r.get_data(as_text=True), name
    parent = cid('Expenses › Hobbies › ' + ' › '.join(['Music', 'Guitar', 'Strings', 'Nylon', 'Brand X'][:lvl - 2]))
    assert parent, name
deep = parent
with A.app.test_request_context():
    _, by_id = C.load_tree(A.get_db())
    assert by_id[deep]['level'] == 7 and by_id[deep]['path'] == 'Expenses › Hobbies › Music › Guitar › Strings › Nylon › Brand X'
r = c.post('/categories/add', data={'parent_id': str(cid('Expenses › Hobbies')), 'name': 'music'}, follow_redirects=True)
assert 'already has' in r.get_data(as_text=True), 'duplicate names under one parent are refused'
# JSON add (used by the searchable picker's "Add … under …")
j = c.post('/categories/add', json={'parent_id': str(deep), 'name': 'Spare set', 'next': 'json'}).get_json()
assert j['ok'] and j['level'] == 8 and j['path'].endswith('Brand X › Spare set')
assert c.post('/categories/add', json={'parent_id': str(deep), 'name': '', 'next': 'json'}).status_code == 400
# a new top-level group with its own kind
r = c.post('/categories/add', data={'parent_id': 'top', 'name': 'Side business', 'kind': 'income'}, follow_redirects=True)
assert 'Added “Side business”' in r.get_data(as_text=True)
sb = cid('Side business')
assert c.post('/categories/add', data={'parent_id': 'top', 'name': 'side BUSINESS', 'kind': 'income'}, follow_redirects=True) \
    .get_data(as_text=True).count('already exists') == 1
c.post('/categories/add', data={'parent_id': str(sb), 'name': 'Workshops'})
with A.app.test_request_context():
    con = A.get_db()
    assert con.execute('SELECT kind, level FROM categories WHERE id=?', (cid('Side business › Workshops'),)).fetchone()[:] == ('income', 2)
# a transaction in the deep category, then move a deep branch under the new group (no depth limit), then delete
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO transactions (date, description, amount, type, category, account, category_id, manual) "
                "VALUES ('2026-10-01', 'SYNTHETIC GUITAR SHOP', 450, 'debit', 'Hobbies', 'Test Savings 1111', ?, 1)", (deep,))
    con.commit()
music = cid('Expenses › Hobbies › Music')
r = c.post(f'/categories/{music}/move', data={'parent_id': str(cid('Side business › Workshops'))}, follow_redirects=True)
assert 'Moved “Music”' in r.get_data(as_text=True)
with A.app.test_request_context():
    con = A.get_db()
    _, by_id = C.load_tree(con)
    assert by_id[deep]['level'] == 7 and by_id[deep]['kind'] == 'income' and by_id[deep]['path'].startswith('Side business › Workshops › Music')
    assert con.execute("SELECT category FROM transactions WHERE category_id=?", (deep,)).fetchone()[0] == 'Workshops'
r = c.post(f'/categories/{music}/move', data={'parent_id': str(deep)}, follow_redirects=True)
assert 'inside itself' in r.get_data(as_text=True)
r = c.post(f'/categories/{music}/delete', data={'target_id': str(cid('Expenses › Hobbies'))}, follow_redirects=True)
assert 'Deleted “Music”' in r.get_data(as_text=True) and '1 transaction(s) moved' in r.get_data(as_text=True)
r = c.post(f'/categories/{sb}/rename', data={'name': 'Side gigs'}, follow_redirects=True)
assert 'Renamed to “Side gigs”' in r.get_data(as_text=True), 'own top-level groups can be renamed'
r = c.post(f'/categories/{exp}/rename', data={'name': 'Spending'}, follow_redirects=True)
assert 'cannot be renamed' in r.get_data(as_text=True), 'the four Types stay fixed'
r = c.post(f'/categories/{exp}/delete', data={'target_id': str(sb)}, follow_redirects=True)
assert 'cannot be deleted' in r.get_data(as_text=True)
r = c.post(f'/categories/{sb}/delete', data={'target_id': str(cid('Income'))}, follow_redirects=True)
assert 'Deleted “Side gigs”' in r.get_data(as_text=True)
# pages that walk the tree still work with deep categories
c.post('/categories/add', data={'parent_id': str(cid('Expenses › Hobbies')), 'name': 'Deep'})
d1 = cid('Expenses › Hobbies › Deep')
for n in ('L5', 'L6'):
    c.post('/categories/add', data={'parent_id': str(d1), 'name': n})
    d1 = cid('Expenses › Hobbies › Deep › L5' + (' › L6' if n == 'L6' else ''))
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO transactions (date, description, amount, type, category, account, category_id, manual) "
                "VALUES ('2026-10-02', 'SYNTHETIC DEEP', 99, 'debit', 'Hobbies', 'Test Savings 1111', ?, 1)", (d1,))
    con.commit()
for u in ['/categories', '/transactions?start=2026-10-01&end=2026-10-31', f'/transactions?cat={exp}&start=2026-10-01&end=2026-10-31',
          '/breakdown?start=2026-10-01&end=2026-10-31', '/rules', '/budgets', '/']:
    assert c.get(u).status_code == 200, u
x = c.get('/breakdown/export?start=2026-10-01&end=2026-10-31')
assert x.status_code == 200 and x.data[:2] == b'PK', 'Excel breakdown with deep levels'
sr = c.get('/api/search?q=L6').get_json()
assert any(g['title'] == 'L6' and 'Deep › L5' in g['sub'] for g in sr), sr
# review fixes: export keeps deep paths, names cannot hold '›', case-insensitive clashes, rows moved onto a Type
x = c.get('/transactions/export?start=2026-10-01&end=2026-10-31').get_data(as_text=True)
assert '"Expenses","Hobbies","Deep","L5 › L6"' in x, 'CSV keeps levels below Item'
import organise as O  # noqa: E402
assert O._levels('Expenses › Hobbies › Deep › L5 › L6') == ['Expenses', 'Hobbies', 'Deep', 'L5 › L6']
assert O._levels('Income') == ['Income', '', '', '']
c.post('/categories/add', data={'parent_id': str(exp), 'name': 'Transport › Car'})
assert cid('Expenses › Transport - Car'), "'›' in a typed name becomes '-'"
r = c.post('/categories/add', data={'parent_id': 'top', 'name': 'Mine', 'kind': 'expense'}, follow_redirects=True)
r = c.post(f"/categories/{cid('Mine')}/rename", data={'name': 'EXPENSES'}, follow_redirects=True)
assert 'already exists' in r.get_data(as_text=True), 'no second “Expenses” next to the built-in one'
c.post('/categories/add', data={'parent_id': str(cid('Mine')), 'name': 'Thing'})
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO transactions (date, description, amount, type, category, account, category_id, manual) "
                "VALUES ('2026-10-03', 'SYNTHETIC THING', 10, 'debit', 'Thing', 'Test Savings 1111', ?, 1)", (cid('Mine › Thing'),))
    con.commit()
r = c.post(f"/categories/{cid('Mine')}/delete", data={'target_id': str(exp)}, follow_redirects=True)
with A.app.test_request_context():
    assert A.get_db().execute("SELECT category FROM transactions WHERE description='SYNTHETIC THING'").fetchone()[0] == 'Expenses', \
        'rows moved onto a Type no longer show the deleted head'
# ITR: a head under the user's own income group is not mixed with a built-in head of the same name
import itr  # noqa: E402
c.post('/categories/add', data={'parent_id': 'top', 'name': 'Side work', 'kind': 'income'})
c.post('/categories/add', data={'parent_id': str(cid('Side work')), 'name': 'Salary & Remuneration'})
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO transactions (date, description, amount, type, category, account, category_id, manual) "
                "VALUES ('2026-10-04', 'SYNTHETIC GIG', 500, 'credit', 'x', 'Test Savings 1111', ?, 1)",
                (cid('Side work › Salary & Remuneration'),))
    con.commit()
    _, by_id = C.load_tree(con)
    sums = itr._sum_by_path(con, '2026-04-01', '2027-03-31', by_id, 'income')
    assert sums.get(('Side work › Salary & Remuneration', '', '')) == 500 and not sums.get(('Salary & Remuneration', '', ''))
print('categories OK')

# ── 3: searchable pickers are on every category list ─────────────────────────
h = c.get('/transactions?start=2026-10-01&end=2026-10-31').get_data(as_text=True)
assert h.count('data-picker') >= 3 and 'js/picker.js' in h and 'data-path="Expenses › Hobbies › Deep › L5 › L6"' in h
assert 'data-picker' in c.get('/rules').get_data(as_text=True) or 'No rules' in c.get('/rules').get_data(as_text=True)
js = c.get('/static/js/picker.js')
assert js.status_code == 200 and b'HubPicker' in js.data
print('pickers OK')

# ── 4: automatic prices ──────────────────────────────────────────────────────
HDR = ('TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,'
       'FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,'
       'TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n')


def bhav(day, rows, exch):
    lines = [f"{day},{day},CM,{exch},{tp},1,{isin},{sym},{ser},,,,,{sym} SYNTHETIC,1,1,1,{px},{px},1,,,,,10,10,1,F1,1,,,,,"
             for isin, sym, ser, tp, px in rows]
    csv_ = (HDR + '\n'.join(lines) + '\n').encode()
    if exch == 'BSE':
        return csv_
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr(f'BhavCopy_NSE_CM_0_0_0_{day.replace("-", "")}_F_0000.csv', csv_)
    return b.getvalue()


TODAY = date(2026, 10, 28)                  # a Wednesday
LAST = '2026-10-27'
AMFI = ('Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\n\n'
        'Open Ended Schemes(Equity Scheme - Large Cap Fund)\n\nTest Mutual Fund\n\n'
        '100001;INF000T01AB1;-;Test Large Cap Fund;Direct Plan;Growth Option;123.4567;27-Oct-2026\n'
        '100002;INF000T01AC9;INF000T01AD7;Test Large Cap Fund;Direct Plan;IDCW Option;23.10;27-Oct-2026\n'
        '100003;INF000T01ET0;-;Test Nifty ETF;-;-;250.10;27-Oct-2026\n'
        '100004;INF000T01AE5;-;Test Closed Fund;Direct;Growth;N.A.;27-Oct-2026\n')
CALLS = []


def fake_get(url, timeout=30):
    CALLS.append(url)
    if 'amfiindia' in url:
        return AMFI.encode()
    if '20261027' not in url:
        raise OSError('HTTP Error 404: Not Found')                       # today's file not published yet
    if 'nseindia' in url:
        return bhav(LAST, [('INE000A01011', 'TESTCO', 'EQ', 'STK', '105.50'), ('INF000T01ET0', 'TESTETF', 'EQ', 'ETF', '251.25'),
                           ('IN0020000001', 'SGBTEST', 'GB', 'STK', '6100'), ('INE000B07019', 'TESTNCD', 'N1', 'BND', '1012.40'),
                           ('INE000A01011', 'TESTCO', 'BL', 'STK', '99.00')], 'NSE')
    if 'bseindia' in url:
        return bhav(LAST, [('INE000A01011', 'TESTCO', 'A', 'STK', '105.40'), ('INE000C01015', 'BSEONLY', 'X', 'STK', '42.00')], 'BSE')
    raise OSError('unexpected ' + url)


P._get = fake_get
data = P.fetch(TODAY)
assert data['isin']['INE000A01011'] == (105.5, LAST, 'nse'), 'NSE (EQ series) wins over BSE and block-deal rows'
assert data['isin']['INE000C01015'][2] == 'bse' and data['isin']['INF000T01AB1'] == (123.4567, LAST, 'amfi')
assert data['isin']['INF000T01ET0'] == (251.25, LAST, 'nse'), 'an ETF uses its market price, not its NAV'
assert data['isin']['IN0020000001'][0] == 6100 and data['isin']['INE000B07019'][0] == 1012.4, 'SGBs and listed bonds'
assert 'INF000T01AE5' not in data['isin'] and data['isin']['INF000T01AD7'][0] == 23.1
assert any('20261026' in u for u in CALLS) is False and any('20261028' in u for u in CALLS)
assert data['symbol'][('BSE', 'BSEONLY')][0] == 42.0
print('fetch:', data['status'])

with A.app.test_request_context():
    con = A.get_db()
    I.ensure_schema(con)
    secs = [('TESTCO', 'INE000A01011', 'NSE'), ('LCF', 'INF000T01AB1', 'NSE'), ('TESTETF', 'INF000T01ET0', 'NSE'),
            ('SGBTEST', 'IN0020000001', 'NSE'), ('TESTNCD', 'INE000B07019', 'NSE'), ('BSEONLY', None, 'BSE'),
            ('MANUAL', 'INE000D01013', 'NSE'), ('UNKNOWN', 'INE999Z01019', 'NSE')]
    for sym, isin, ex in secs:
        con.execute('INSERT INTO inv_securities (symbol, isin, exchange) VALUES (?,?,?)', (sym, isin, ex))
    con.execute("UPDATE inv_securities SET cmp=77, cmp_date='2026-10-28', cmp_source='manual' WHERE symbol='MANUAL'")
    con.execute("UPDATE inv_securities SET cmp=1, cmp_date='2026-10-28', cmp_source='statement' WHERE symbol='TESTNCD'")
    con.commit()
    data['isin']['INE000D01013'] = (80.0, LAST, 'nse')
    n = P.apply(con, data)
    rows = {r['symbol']: dict(r) for r in con.execute('SELECT symbol, cmp, cmp_date, cmp_source FROM inv_securities')}
    assert rows['TESTCO']['cmp'] == 105.5 and rows['TESTCO']['cmp_source'] == 'NSE close' and rows['TESTCO']['cmp_date'] == LAST
    assert rows['LCF']['cmp'] == 123.4567 and rows['LCF']['cmp_source'] == 'AMFI NAV'
    assert rows['BSEONLY']['cmp'] == 42.0 and rows['BSEONLY']['cmp_source'] == 'BSE close', 'no ISIN: matched by symbol'
    assert rows['MANUAL']['cmp'] == 77, 'a price typed today is not replaced by an older close'
    assert rows['TESTNCD']['cmp'] == 1, 'never an older price over a newer one'
    assert rows['UNKNOWN']['cmp'] is None and n == 5, n
    assert P.apply(con, data) == 0, 'nothing written twice'
    con.commit()
print('apply OK')

# automatic: background download after a page view, prices written on the next page
P.ENABLED = True
P.CACHE.update(data=None, at=0.0, running=False)
with A.app.test_request_context():
    con = A.get_db()
    con.execute("UPDATE inv_securities SET cmp=NULL, cmp_date=NULL, cmp_source=NULL WHERE symbol='TESTCO'")
    con.commit()
real_fetch = P.fetch
P.fetch = lambda today=None, sources=('nse', 'bse', 'amfi'): real_fetch(TODAY, sources)
assert c.get('/').status_code == 200
for _ in range(50):
    if P.CACHE['data'] and not P.CACHE['running']:
        break
    time.sleep(0.1)
assert P.CACHE['data'], 'downloaded in the background'
assert P.WANTED['on']
c.get('/investments')
with A.app.test_request_context():
    con = A.get_db()
    assert con.execute("SELECT cmp FROM inv_securities WHERE symbol='TESTCO'").fetchone()[0] == 105.5
    assert 'price(s) updated' in P.get_setting(con, 'prices_result')
h = c.get('/investments').get_data(as_text=True)
assert 'Update prices automatically' in h and 'Update prices now' in h and 'NSE:' in h
n_calls = len(CALLS)
c.get('/investments')
time.sleep(0.3)
assert len(CALLS) == n_calls, 'no new download while the prices are fresh'
# switch off → no downloads; Update now still works
r = c.post('/investments/prices', data={'auto': '0'}, follow_redirects=True)
assert 'Automatic price updates are off' in r.get_data(as_text=True)
P.CACHE.update(at=0.0)
c.get('/investments'); time.sleep(0.3)
assert len(CALLS) == n_calls and not P.WANTED['on']
P.tick(); time.sleep(0.2)
assert len(CALLS) == n_calls, 'the scheduler does not download when nobody wants prices'
r = c.post('/investments/prices', follow_redirects=True)
assert 'Prices updated for' in r.get_data(as_text=True) and len(CALLS) > n_calls
c.post('/investments/prices', data={'auto': '1'})
# investments feature off → no automatic downloads
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT OR REPLACE INTO hub_settings (key, value) VALUES ('features_off', '[\"investments\"]')")
    con.commit()
    assert P.auto(con) == 0 and not P.WANTED['on']
# a broken source never breaks a page
P._get = lambda url, timeout=30: (_ for _ in ()).throw(OSError('offline'))
P.CACHE.update(data=None, at=0.0)
with A.app.test_request_context():
    con = A.get_db()
    con.execute("DELETE FROM hub_settings WHERE key='features_off'"); con.commit()
assert c.get('/investments').status_code == 200
for _ in range(50):
    if not P.CACHE['running']:
        break
    time.sleep(0.1)
assert P.CACHE['data'] is not None and 'not available' in P.CACHE['data']['status']['nse']
assert c.get('/investments').status_code == 200
# a network error does not walk back a week of timeouts, and the sources are tried side by side
CALLS.clear()
P._get = lambda url, timeout=30: (CALLS.append(url), (_ for _ in ()).throw(OSError('timed out')))[1]
d2 = P.fetch(TODAY)
assert len([u for u in CALLS if 'nseindia' in u]) == 1 and len([u for u in CALLS if 'bseindia' in u]) == 1 and not d2['ok']
P.CACHE.update(data=d2, at=time.time() - P.RETRY_SECONDS - 5)
assert P.stale(), 'a failed download is retried after 30 minutes, not 3 hours'
P.CACHE.update(data=dict(d2, ok=True), at=time.time() - P.RETRY_SECONDS - 5)
assert not P.stale()
# a holding whose ISIN the files do not know is matched by symbol on its own exchange
with A.app.test_request_context():
    con = A.get_db()
    con.execute("INSERT INTO inv_securities (symbol, isin, exchange) VALUES ('BSEONLY2', 'INE111X01011', 'BSE')")
    n = P.apply(con, {'isin': {}, 'symbol': {('BSE', 'BSEONLY2'): (9.5, LAST, 'bse'), ('NSE', 'UNKNOWN'): (5.0, LAST, 'nse')}})
    assert con.execute("SELECT cmp FROM inv_securities WHERE symbol='BSEONLY2'").fetchone()[0] == 9.5
    con.rollback()
print('automatic prices OK')
print('ALL 1.9 OK')
