"""Finance Hub 1.9 — automatic prices for stocks, ETFs, REITs / InvITs, listed bonds, SGBs and mutual funds.

The Hub downloads the exchanges' and AMFI's own public end-of-day files — whole files, the same for everyone — and looks
up your securities in them on your PC. Nothing about your holdings is sent anywhere.

  * NSE  — Capital-market bhavcopy (UDiFF, published every trading day in the evening): every equity share, ETF, REIT,
           InvIT, sovereign gold bond and listed bond / debenture traded that day, with its ISIN and closing price.
  * BSE  — the same for BSE (covers BSE-only securities).
  * AMFI — NAVAll.txt: the latest NAV of every mutual-fund scheme, by ISIN (published every business day at night).

Matching is by ISIN (symbol + exchange for securities without one). An exchange price beats an AMFI NAV for the same ISIN
(ETFs), a newer date beats an older one, and a price you typed yourself is kept until a newer market price arrives.
Downloads run in a background thread and never touch your data; the prices are written into your (encrypted) database on
your next page while you are logged in. The optional yfinance package is still used, on "Update now", for anything the
files do not have.
"""
import csv
import io
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import zipfile
from datetime import date, datetime, timedelta

log = logging.getLogger('financehub.prices')

AMFI_URLS = ('https://portal.amfiindia.com/spages/NAVAll.txt', 'https://www.amfiindia.com/spages/NAVAll.txt')
NSE_URLS = ('https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip',)
BSE_URLS = ('https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV',)
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/126.0 Safari/537.36',
           'Accept': 'text/csv,application/zip,text/plain,*/*', 'Accept-Language': 'en-IN,en;q=0.9'}
REFERER = {'nseindia': 'https://www.nseindia.com/', 'bseindia': 'https://www.bseindia.com/'}
MAX_BYTES = 40 * 1024 * 1024
LOOKBACK_DAYS = 7               # exchange files: go back over weekends / holidays to the latest one published
STALE_SECONDS = 3 * 3600        # download again after 3 hours (files appear in the evening)
RETRY_SECONDS = 30 * 60         # …or after 30 minutes when a source failed
TIMEOUT = 20
SOURCE_LABEL = {'nse': 'NSE close', 'bse': 'BSE close', 'amfi': 'AMFI NAV'}
EQ_SERIES = {'EQ', 'BE', 'BZ', 'SM', 'ST', 'GB', 'RR', 'IV', 'A', 'B', 'T', 'X', 'XT', 'Z', 'M', 'MT', 'F', 'G'}

CACHE = {'data': None, 'at': 0.0, 'running': False, 'status': {}, 'error': ''}
_LOCK = threading.Lock()
ENABLED = os.environ.get('FINANCEHUB_PRICES', '1') != '0'     # tests switch downloads off
WANTED = {'on': False}          # set while a logged-in user has automatic prices on (lets the scheduler pre-download)


# ── downloading ─────────────────────────────────────────────────────────────
def _get(url, timeout=TIMEOUT):
    """→ bytes. Replaced by the tests."""
    hdr = dict(HEADERS)
    for k, ref in REFERER.items():
        if k in url:
            hdr['Referer'] = ref
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('file too large')
    return data


def _num(x):
    try:
        v = float(str(x).replace(',', '').strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _iso(text):
    t = (text or '').strip()
    for fmt in ('%Y-%m-%d', '%d-%b-%Y', '%d-%m-%Y', '%d/%m/%Y', '%d-%b-%y', '%Y%m%d', '%d %b %Y'):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


# ── parsing ─────────────────────────────────────────────────────────────────
def parse_amfi(text):
    """NAVAll.txt → {isin: (nav, date, scheme name)}. Header-driven (AMFI added Plan / Option columns over time)."""
    out, cols = {}, None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(';')]
        if len(parts) < 5:
            continue                                     # blank lines, fund-house and category headings
        if cols is None or parts[0].lower().startswith('scheme code'):
            if parts[0].lower().startswith('scheme code'):
                low = [p.lower() for p in parts]
                find = lambda *keys: next((i for i, c in enumerate(low) if all(k in c for k in keys)), None)  # noqa: E731
                cols = {'isin1': find('isin', 'growth') if find('isin', 'growth') is not None else find('isin', 'payout'),
                        'isin2': find('isin', 'reinvest'), 'nav': find('net asset value'), 'date': find('date'),
                        'name': find('scheme name')}
                continue
            if cols is None:
                continue
        if len(parts) <= max(v for v in cols.values() if v is not None):
            continue
        nav = _num(parts[cols['nav']]) if cols['nav'] is not None else None
        d = _iso(parts[cols['date']]) if cols['date'] is not None else ''
        if not nav or not d:
            continue
        name = parts[cols['name']] if cols['name'] is not None else ''
        for k in ('isin1', 'isin2'):
            i = cols.get(k)
            if i is not None and len(parts[i]) == 12 and parts[i][:2].isalpha():
                out[parts[i].upper()] = (nav, d, name)
    return out


ALIASES = {'isin': ('isin', 'isin_code', 'isin code', 'isin no'),
           'close': ('clspric', 'close', 'close_price', 'close price', 'closing price'),
           'symbol': ('tckrsymb', 'symbol', 'sc_name', 'security id'),
           'series': ('sctysrs', 'series', 'sc_group'),
           'date': ('traddt', 'bizdt', 'timestamp', 'date1', 'trade date', 'trading_date'),
           'segment': ('sgmt',), 'type': ('fininstrmtp',)}


def parse_bhav(data, exchange):
    """A bhavcopy (CSV, or a zip holding one) → ({isin: (close, date, symbol)}, {symbol: (close, date, isin)})."""
    if data[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith('.csv'))
            data = z.read(name)
    text = data.decode('utf-8-sig', errors='replace')
    rows = csv.reader(io.StringIO(text))
    head = next(rows, [])
    low = [h.strip().lower() for h in head]
    col = {k: next((low.index(a) for a in al if a in low), None) for k, al in ALIASES.items()}
    if col['close'] is None or (col['isin'] is None and col['symbol'] is None):
        raise ValueError(f'{exchange}: unexpected file layout ({", ".join(head[:6])}…)')
    by_isin, by_sym = {}, {}
    for r in rows:
        if len(r) <= max(v for v in col.values() if v is not None):
            continue
        g = lambda k: r[col[k]].strip() if col[k] is not None else ''  # noqa: E731
        if g('segment') and g('segment').upper() not in ('CM', 'EQ'):
            continue
        if g('type') and g('type').upper() not in ('STK', 'ETF', 'BND', 'DBT', 'GS', 'INVIT', 'REIT', 'MF', 'SGB', 'TB'):
            pass                                         # unknown instrument types are kept: matching is by ISIN anyway
        close = _num(g('close'))
        if not close:
            continue
        d = _iso(g('date')) or ''
        isin, sym, ser = g('isin').upper(), g('symbol').upper(), g('series').upper()
        pref = ser in EQ_SERIES or not ser
        if isin and len(isin) == 12 and (isin not in by_isin or pref):
            by_isin[isin] = (close, d, sym)
        if sym and (sym not in by_sym or pref):
            by_sym[sym] = (close, d, isin)
    return by_isin, by_sym


# ── fetching all sources ────────────────────────────────────────────────────
def _trading_days(today, n=LOOKBACK_DAYS):
    d = today
    for _ in range(n + 1):
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


def _missing(e):
    """The file for that day does not exist (yet): try the day before. Any other error ends the search."""
    return (isinstance(e, urllib.error.HTTPError) and e.code in (404, 410)) or 'HTTP Error 404' in str(e)


def _fetch_exchange(key, urls, today):
    last_err = ''
    for d in _trading_days(today):
        for u in urls:
            url = u.format(ymd=d.strftime('%Y%m%d'))
            try:
                by_isin, by_sym = parse_bhav(_get(url), key.upper())
                if by_isin or by_sym:
                    for k, v in list(by_isin.items()):
                        by_isin[k] = (v[0], v[1] or d.isoformat(), v[2])
                    for k, v in list(by_sym.items()):
                        by_sym[k] = (v[0], v[1] or d.isoformat(), v[2])
                    return by_isin, by_sym, f'{len(by_isin) or len(by_sym)} prices of {d:%d %b %Y}'
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:120]
                if not _missing(e):                  # network trouble / refused: do not walk back a week of timeouts
                    return {}, {}, f'not available ({last_err})'
    return {}, {}, f'not available ({last_err or "no file in the last week"})'


def _fetch_amfi():
    err = ''
    for u in AMFI_URLS:
        try:
            navs = parse_amfi(_get(u).decode('utf-8-sig', errors='replace'))
            if navs:
                return navs, f"{len(navs)} NAVs, latest {max(v[1] for v in navs.values())}"
            err = 'empty file'
        except Exception as e:  # noqa: BLE001
            err = str(e)[:120]
    return {}, f'not available ({err})'


def fetch(today=None, sources=('nse', 'bse', 'amfi')):
    """Download every source (in parallel). → {'isin': {isin: (price, date, source)},
    'symbol': {(exch, sym): (price, date, source)}, 'status': {source: text}, 'ok': all sources answered, 'at': epoch}"""
    today = today or date.today()
    jobs = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, urls in (('nse', NSE_URLS), ('bse', BSE_URLS)):
            if key in sources:
                jobs[key] = pool.submit(_fetch_exchange, key, urls, today)
        if 'amfi' in sources:
            jobs['amfi'] = pool.submit(_fetch_amfi)
    isin, sym, status, exch = {}, {}, {}, {}
    for key in ('nse', 'bse'):
        if key in jobs:
            bi, bs, status[key] = jobs[key].result()
            exch[key] = bi
            for s_, (p, d, _i) in bs.items():
                sym[(key.upper(), s_)] = (p, d, key)
    for key in ('bse', 'nse'):                      # NSE wins over BSE on the same date (applied last)
        for i, (p, d, _s) in exch.get(key, {}).items():
            old = isin.get(i)
            if not old or d >= old[1]:
                isin[i] = (p, d, key)
    if 'amfi' in jobs:
        navs, status['amfi'] = jobs['amfi'].result()
        for i, (nav, d, _n) in navs.items():
            old = isin.get(i)
            # an ETF's market price beats its NAV unless the NAV is clearly newer
            if not old or (old[2] == 'amfi' and d > old[1]) or (old[2] != 'amfi' and d > _plus(old[1], 4)):
                isin[i] = (nav, d, 'amfi')
    ok = all(not v.startswith('not available') for v in status.values())
    return {'isin': isin, 'symbol': sym, 'status': status, 'ok': ok, 'at': time.time()}


def _plus(iso, days):
    try:
        return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()
    except ValueError:
        return iso


# ── background download ─────────────────────────────────────────────────────
def stale():
    if CACHE['data'] is None:
        return time.time() - CACHE['at'] > RETRY_SECONDS if CACHE['at'] else True
    return time.time() - CACHE['at'] > (STALE_SECONDS if CACHE['data'].get('ok', True) else RETRY_SECONDS)


def _run():
    try:
        data = fetch()
        with _LOCK:
            CACHE.update(data=data, at=data['at'], status=data['status'],
                         error='' if data['isin'] or data['symbol'] else 'no price source could be reached')
        log.info('Prices downloaded: %s', '; '.join(f'{k}: {v}' for k, v in data['status'].items()))
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            CACHE.update(at=time.time(), error=str(e)[:200])
        log.warning('Price download failed: %s', e)
    finally:
        CACHE['running'] = False


def start_background(force=False):
    """Download in a thread when the cached prices are old (never blocks a page). → True when started."""
    if not ENABLED:
        return False
    with _LOCK:
        if CACHE['running'] or not (force or stale()):
            return False
        CACHE['running'] = True
    threading.Thread(target=_run, name='hub-prices', daemon=True).start()
    return True


def update_now(timeout=60):
    """Download now and wait (the Update now button). → cache dict"""
    if not start_background(force=True):
        pass                                         # already running: just wait for it
    t0 = time.time()
    while CACHE['running'] and time.time() - t0 < timeout:
        time.sleep(0.2)
    return CACHE


def tick():
    """Scheduler (every minute, also while locked): keep public prices fresh for the next log-in. No user data involved."""
    if WANTED['on'] and stale():
        start_background()


# ── writing prices into a user's database ───────────────────────────────────
def get_setting(con, key, default=''):
    r = con.execute('SELECT value FROM inv_settings WHERE key=?', (key,)).fetchone()
    return r[0] if r and r[0] is not None else default


def set_setting(con, key, value):
    con.execute('INSERT OR REPLACE INTO inv_settings (key, value) VALUES (?,?)', (key, str(value)))


def apply(con, data):
    """Write the downloaded prices into inv_securities. → number of securities updated"""
    n = 0
    for s in con.execute('SELECT id, symbol, isin, exchange, cmp, cmp_date, cmp_source FROM inv_securities').fetchall():
        hit = data['isin'].get((s['isin'] or '').upper()) if s['isin'] else None
        if not hit:                                      # no ISIN, or an ISIN the files do not know (e.g. changed after a split)
            ex, sy = (s['exchange'] or 'NSE').upper(), (s['symbol'] or '').upper()
            hit = data['symbol'].get((ex, sy))
            if not hit and not s['isin']:
                hit = data['symbol'].get(('BSE' if ex == 'NSE' else 'NSE', sy))
        if not hit:
            continue
        price, d, src = hit
        old_d = s['cmp_date'] or ''
        if old_d and d < old_d:
            continue                                     # never replace a newer price with an older one
        if s['cmp_source'] == 'manual' and old_d and d <= old_d:
            continue                                     # a price you typed stays until a newer market price arrives
        if s['cmp'] == price and old_d == d and s['cmp_source'] == SOURCE_LABEL[src]:
            continue
        con.execute('UPDATE inv_securities SET cmp=?, cmp_date=?, cmp_source=? WHERE id=?', (price, d, SOURCE_LABEL[src], s['id']))
        n += 1
    return n


def auto(con):
    """Called on each page while logged in: write newer downloaded prices, start a download when due. → updated count"""
    try:
        import features
        off = 'investments' in features.off(con)
    except Exception:  # noqa: BLE001
        off = False
    if off or get_setting(con, 'prices_auto', '1') != '1':
        WANTED['on'] = False
        return 0
    WANTED['on'] = True
    n = 0
    data = CACHE['data']
    if data and str(data['at']) != get_setting(con, 'prices_applied'):
        n = apply(con, data)
        set_setting(con, 'prices_applied', data['at'])
        set_setting(con, 'prices_result', summary(data, n))
        con.commit()
    start_background()
    return n


def summary(data, n):
    st = data.get('status', {})
    when = datetime.fromtimestamp(data['at']).strftime('%d %b %Y %H:%M')
    return (f"{when}: {n} price(s) updated · " + ' · '.join(f"{k.upper()}: {v}" for k, v in st.items()))[:400]


def register(app, get_db):
    """Hook the automatic update in after the log-in guard (app.py calls this after auth.register)."""
    from flask import g, request

    @app.before_request
    def _auto_prices():
        if request.method != 'GET' or not getattr(g, 'user', None) or (request.endpoint or '') in ('static', 'healthz') \
                or request.path.startswith('/api/'):
            return None
        try:
            import investments
            con = get_db()
            investments.ensure_schema(con)
            auto(con)
        except Exception:  # noqa: BLE001  (prices must never break a page)
            app.logger.exception('automatic price update')
        return None

    import notify
    if tick not in notify.EXTRA_TICKS:
        notify.EXTRA_TICKS.append(tick)
