"""Finance Hub — Investments: broker statements, portfolio, TF tranching plan, buy / add / sell instructions.

Provision (v7)
  * Brokers: Upstox, Zerodha, SBI Securities (+ any you add); CDSL / NSDL CAS for holdings across demats.
  * Broker files: tradebooks and holdings exports (CSV / XLSX / XLS) are read by column names, so the
    usual Upstox / Zerodha Console / SBI Securities exports work without a per-broker parser; CAS PDFs
    are read for ISIN lines (beta — verify the preview). Contract-note PDFs: to be added once samples
    are uploaded.
  * Portfolio = trades (weighted-average cost; realised P&L on sells). Stocks with no trades use the
    latest holdings file. Holdings files are also used to reconcile quantities.
  * TF Journal tranching rules (editable on the page): up to 8 tranches per stock; stock limit 8 % (Core)
    / 5 % (Satellite) of planned capital; sector cap 8 %; Core 70 % / Satellite 30 %.
  * Suggestions: BUY (first tranche) / ADD (next tranche) / TRIM (over the stock limit) / SELL (exit plan),
    or why it is blocked. Accept a suggestion → open instruction; it is marked done automatically when a
    matching broker trade is imported (or by hand).
"""
import csv
import hashlib
import io
import json
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

from flask import render_template, request, jsonify, redirect, url_for, flash

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_brokers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, client_id TEXT, demat_id TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS inv_securities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, isin TEXT, name TEXT, exchange TEXT DEFAULT 'NSE', sector TEXT,
    bucket TEXT,                         -- core / satellite / NULL (not set yet)
    plan_status TEXT DEFAULT 'active',   -- active / paused / exit / watch
    add_rule TEXT DEFAULT 'any',         -- any / dip / rise / gap
    step_pct REAL DEFAULT 10,            -- for dip / rise
    gap_days INTEGER DEFAULT 30,         -- for gap
    cmp REAL, cmp_date TEXT, cmp_source TEXT, notes TEXT,
    UNIQUE(symbol, exchange));
CREATE UNIQUE INDEX IF NOT EXISTS idx_sec_isin ON inv_securities(isin) WHERE isin IS NOT NULL AND isin <> '';
CREATE TABLE IF NOT EXISTS inv_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT, file_hash TEXT UNIQUE, broker_id INTEGER,
    kind TEXT, as_of TEXT, rows INTEGER, added INTEGER, imported_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS inv_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_id INTEGER NOT NULL, security_id INTEGER NOT NULL, trade_date TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy','sell')), qty REAL NOT NULL, price REAL NOT NULL,
    charges REAL DEFAULT 0, trade_id TEXT, order_id TEXT, exchange TEXT,
    import_id INTEGER, source TEXT DEFAULT 'import', notes TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_trd_sec ON inv_trades(security_id, trade_date);
CREATE TABLE IF NOT EXISTS inv_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, import_id INTEGER, broker_id INTEGER, source TEXT,
    as_of TEXT, security_id INTEGER, qty REAL, avg_cost REAL, close_price REAL, value REAL);
CREATE TABLE IF NOT EXISTS inv_instructions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, security_id INTEGER NOT NULL, broker_id INTEGER,
    action TEXT NOT NULL,                -- BUY / ADD / TRIM / SELL
    tranche TEXT, qty REAL, amount REAL, limit_price REAL, reason TEXT,
    status TEXT DEFAULT 'open',          -- open / done / cancelled
    created_at TEXT DEFAULT (date('now')), done_at TEXT, trade_ids TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS inv_settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {           # TF Journal tranching rules
    'capital': '0',            # planned equity capital (₹); 0 = use current portfolio value
    'max_tranches': '8',
    'core_stock_max': '8',     # % of capital per Core stock
    'sat_stock_max': '5',      # % of capital per Satellite stock
    'sector_cap': '8',         # % of capital per sector (hard cap)
    'core_pct': '70',
    'sat_pct': '30',
    'trim_tolerance': '1',     # percentage points above the stock limit before TRIM is suggested
}
SETTING_LABELS = {
    'capital': 'Planned equity capital (₹) — 0 = current portfolio value',
    'max_tranches': 'Tranches per stock (max)',
    'core_stock_max': 'Core stock limit (% of capital)',
    'sat_stock_max': 'Satellite stock limit (% of capital)',
    'sector_cap': 'Sector cap (% of capital)',
    'core_pct': 'Core share of portfolio (%)',
    'sat_pct': 'Satellite share of portfolio (%)',
    'trim_tolerance': 'Trim when over the limit by (% points)',
}
DEFAULT_BROKERS = ['Upstox', 'Zerodha', 'SBI Securities']
CAS_SOURCE = 'CAS (CDSL / NSDL)'


def ensure_schema(con):
    con.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        con.execute('INSERT OR IGNORE INTO inv_settings (key, value) VALUES (?,?)', (k, v))
    for b in DEFAULT_BROKERS:
        con.execute('INSERT OR IGNORE INTO inv_brokers (name) VALUES (?)', (b,))
    import depository                      # 1.4: CDSL / NSDL demat accounts (not brokers)
    depository.ensure_schema(con)
    con.commit()


def settings(con) -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update({k: v for k, v in con.execute('SELECT key, value FROM inv_settings')})
    return {k: _num(v) for k, v in s.items()}


# ── Reading broker files ─────────────────────────────────────────────────────
ALIASES = {
    'date': ['trade date', 'trade_date', 'date', 'execution date', 'transaction date', 'txn date', 'order date',
             'trade dt', 'order execution time', 'trade time'],
    'symbol': ['symbol', 'tradingsymbol', 'trading symbol', 'scrip', 'scrip name', 'scrip code', 'company',
               'company name', 'stock', 'stock name', 'instrument', 'security', 'security name', 'name', 'script name'],
    'isin': ['isin', 'isin code', 'isin no'],
    'side': ['trade type', 'trade_type', 'side', 'buy/sell', 'b/s', 'transaction type', 'type', 'action',
             'buy / sell', 'order type'],
    'qty': ['quantity', 'qty', 'traded qty', 'trade qty', 'trade quantity', 'quantity available', 'total quantity',
            'net qty', 'free qty', 'current balance', 'balance', 'holding qty', 'qty.'],
    'price': ['price', 'trade price', 'rate', 'traded price', 'net rate', 'market rate', 'trade rate',
              'execution price', 'avg. price', 'average price'],
    'avg': ['average price', 'avg price', 'avg. price', 'avg cost', 'avg. cost', 'average cost', 'buy avg',
            'buy average', 'average buy price', 'avg buy price', 'cost price'],
    'close': ['previous closing price', 'close price', 'closing price', 'ltp', 'last traded price', 'cmp',
              'market price', 'current price', 'last price', 'prev close'],
    'value': ['current value', 'market value', 'value', 'present value', 'valuation'],
    'trade_id': ['trade id', 'trade_id', 'trade num', 'trade no', 'trade no.', 'trade number', 'trade #'],
    'order_id': ['order id', 'order_id', 'order no', 'order no.', 'order number'],
    'exchange': ['exchange', 'exch'],
    'segment': ['segment', 'instrument type', 'series', 'product'],
    'sector': ['sector', 'industry'],
    'charges': ['brokerage', 'charges', 'total charges'],
}
NON_EQUITY = re.compile(r'\b(FO|F&O|FUT|OPT|CE|PE|CDS|MCX|COM|CURRENCY|NFO|BFO)\b', re.I)


def _norm(h):
    return re.sub(r'\s+', ' ', str(h or '').strip().lower().replace('\n', ' '))


def _num(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '').replace('₹', '').replace('Rs.', '').strip()
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()')
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return 0.0


DATE_FMTS = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d-%b-%Y', '%d %b %Y', '%d-%b-%y', '%d/%m/%y', '%Y/%m/%d',
             '%b %d, %Y', '%d.%m.%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S',
             '%d/%m/%Y %H:%M:%S', '%d-%m-%Y %H:%M', '%d/%m/%Y %H:%M', '%d-%b-%Y %H:%M:%S']


def _date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or '').strip()
    if not s:
        return ''
    for f in DATE_FMTS:
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    return m.group(1) if m else ''


def _id(v):
    if v is None or v == '':
        return ''
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _clean_symbol(s):
    s = str(s or '').strip().upper()
    s = re.sub(r'^(NSE|BSE)[:\s-]+', '', s)
    s = re.sub(r'(-EQ|-BE|-BZ|\.NS|\.BO| EQ)$', '', s)
    return s.strip()


def _rows_from_file(path: Path):
    ext = path.suffix.lower()
    if ext == '.csv':
        raw = path.read_bytes().decode('utf-8-sig', errors='replace')
        return list(csv.reader(io.StringIO(raw)))
    if ext == '.xlsx':
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=True)
        rows = []
        for ws in wb.worksheets:                 # all sheets (Zerodha holdings: Equity sheet)
            rows += [list(r) for r in ws.iter_rows(values_only=True)]
            rows.append([])
        return rows
    if ext == '.xls':
        import xlrd
        wb = xlrd.open_workbook(str(path))
        rows = []
        for sh in wb.sheets():
            for i in range(sh.nrows):
                rows.append(sh.row_values(i))
            rows.append([])
        return rows
    raise ValueError('Unsupported file type')


def _find_tables(rows):
    """Yield (header_map, data_rows) for every header row found (≥3 known column names)."""
    i = 0
    while i < len(rows):
        hdr = [_norm(c) for c in rows[i]]
        cols = {}
        for key, names in ALIASES.items():
            for j, h in enumerate(hdr):
                if h in names and key not in cols:
                    cols[key] = j
        if len(cols) >= 3 and ('symbol' in cols or 'isin' in cols) and 'qty' in cols:
            data = []
            k = i + 1
            while k < len(rows) and any(str(c or '').strip() for c in rows[k]):
                data.append(rows[k])
                k += 1
            yield cols, data, hdr
            i = k
        i += 1


def detect_broker(name: str, text: str, brokers: list) -> str:
    t = f'{name} {text}'.lower()
    for key, b in (('zerodha', 'Zerodha'), ('kite', 'Zerodha'), ('console', 'Zerodha'), ('upstox', 'Upstox'),
                   ('rksv', 'Upstox'), ('sbicap', 'SBI Securities'), ('sbi securities', 'SBI Securities'),
                   ('sbisecurities', 'SBI Securities')):
        if key in t and b in brokers:
            return b
    return ''


# ── PDF documents from brokers / exchanges / depositories ────────────────────
class NeedsPassword(PermissionError):
    pass


def open_pdf_text(path: Path, passwords):
    """Text of every page, trying each password (as typed, upper, lower). → (pages, password_used)"""
    import pdfplumber
    tried = []
    for pw in [None] + [x for p in passwords if p for x in (p, p.upper(), p.lower())]:
        if pw in tried:
            continue
        tried.append(pw)
        try:
            with pdfplumber.open(str(path), password=pw) as pdf:
                return [(pg.extract_text() or '') for pg in pdf.pages], pw
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__.lower()
            if 'password' in name or 'encrypt' in str(e).lower() or 'password' in str(e).lower() or not str(e):
                continue
            raise
    raise NeedsPassword('Password-protected — broker and depository statements usually open with your PAN.')


def classify_pdf(text: str) -> tuple:
    """→ (broker, doc_type). doc_type: contract_note / cas / info (+ what it is)."""
    t = text.upper()
    broker = ('Upstox' if ('UPSTOX' in t or 'RKSV' in t) else 'SBI Securities' if ('SBICAP' in t or 'SBI SECURITIES' in t)
              else 'Zerodha' if 'ZERODHA' in t else '')
    if 'CONTRACT NOTE' in t and ISIN_RE.search(text):
        return broker, 'contract_note', 'Contract note'
    if ('CONSOLIDATED ACCOUNT STATEMENT' in t or 'NSDL CAS' in t or 'CDSL CAS' in t) and 'CONTRACT NOTE' not in t:
        return '', 'cas', 'Depository statement (CAS — CDSL / NSDL)'
    if ('TRANSACTION CUM HOLDING' in t or 'HOLDING STATEMENT' in t or 'STATEMENT OF HOLDING' in t) and \
            ('DP ID' in t or 'BO ID' in t) and 'CONTRACT NOTE' not in t:
        return '', 'cas', 'Demat holding statement (from the DP)'
    for key, label in (('STATEMENT OF ACCOUNTS OF FUNDS', 'Funds ledger (weekly statement of accounts)'),
                       ('STATEMENT OF ACCOUNTS OF SECURITIES', 'Securities ledger (weekly statement)'),
                       ('DAILY MARGIN', 'Daily margin statement'),
                       ('SECURITIES BALANCE', 'Exchange balance confirmation (NSE / BSE)'),
                       ('FUNDS BALANCE', 'Exchange balance confirmation (NSE / BSE)')):
        if key in t:
            return broker, 'info', label
    return broker, 'unknown', 'Not recognised'


def _symbol_from_name(name: str) -> str:
    from contract_notes.base import symbol_from_name
    return symbol_from_name(name)


def parse_pdf_document(path: Path, file_name: str, passwords):
    pages, used = open_pdf_text(path, passwords)
    text = '\n'.join(pages)
    broker, doc, label = classify_pdf(text)
    out = {'kind': doc, 'label': label, 'broker_guess': broker, 'as_of': '', 'trades': [], 'holdings': [],
           'warnings': [], 'text_hint': text[:400], 'password_used': bool(used), 'charges': 0.0}
    if doc == 'contract_note':
        import contract_notes
        cn = contract_notes.read(text)
        out.update(trades=cn.trades, charges=cn.charges, warnings=cn.warnings, kind='tradebook',
                   label=f'Contract note {cn.contract_no}'.strip(), reader=cn.reader, check=cn.check,
                   check_detail=cn.check_detail, levies=cn.levies, broker_guess=cn.broker or broker)
        if cn.check == 'MISMATCH':
            out['warnings'].append('Totals do not reconcile — check the rows before importing.')
        out['as_of'] = max((t['date'] for t in out['trades']), default='')
        if not out['trades']:
            out['kind'] = 'info'
            out['warnings'].append('No equity trades found in this contract note.')
    elif doc == 'cas':
        out.update(parse_cas_text(text))
    elif doc == 'info':
        out['warnings'].append('Information only (margin / ledger / exchange balance) — nothing to import. '
                               'Trades come from contract notes; holdings from a CAS or holdings export.')
    else:
        out['warnings'].append('This PDF was not recognised as a contract note or CAS.')
    return out


def parse_broker_file(path: Path, file_name: str, password: str = '', saved_passwords=()):
    """→ dict(kind tradebook|holdings|info|unknown, as_of, trades[], holdings[], warnings[], text_hint)"""
    if path.suffix.lower() == '.pdf':
        return parse_pdf_document(path, file_name, [password] + list(saved_passwords))
    rows = _rows_from_file(path)
    preamble = ' '.join(str(c) for r in rows[:15] for c in r if c)
    trades, holdings, warnings = [], [], []
    as_of = ''
    m = re.search(r'(?:as on|as of|statement date|holdings as on)\D{0,5}([0-9]{1,2}[-/ ][A-Za-z0-9]{2,3}[-/ ][0-9]{2,4}|\d{4}-\d{2}-\d{2})',
                  preamble, re.I)
    if m:
        as_of = _date(m.group(1))
    skipped = 0
    for cols, data, hdr in _find_tables(rows):
        is_trade = 'side' in cols and ('price' in cols or 'avg' in cols)
        for r in data:
            def g(k, default=''):
                j = cols.get(k)
                return r[j] if j is not None and j < len(r) else default
            seg = f"{g('segment')} {g('exchange')}"
            if NON_EQUITY.search(str(seg)):
                skipped += 1
                continue
            sym = _clean_symbol(g('symbol'))
            isin = str(g('isin') or '').strip().upper()
            if not sym and not isin:
                continue
            if sym.lower() in ('total', 'grand total'):
                continue
            if is_trade:
                side_raw = str(g('side')).strip().lower()
                side = 'buy' if side_raw.startswith(('b', 'purchase')) else 'sell' if side_raw.startswith('s') else ''
                qty = abs(_num(g('qty')))
                price = _num(g('price')) or _num(g('avg'))
                d = _date(g('date'))
                if not side or not qty or not price or not d:
                    skipped += 1
                    continue
                trades.append({'date': d, 'symbol': sym, 'isin': isin, 'side': side, 'qty': qty, 'price': price,
                               'trade_id': _id(g('trade_id')), 'order_id': _id(g('order_id')),
                               'exchange': str(g('exchange') or '').strip().upper()[:3] or 'NSE',
                               'charges': _num(g('charges'))})
            else:
                qty = _num(g('qty'))
                if not qty:
                    continue
                holdings.append({'symbol': sym, 'isin': isin, 'qty': qty, 'avg_cost': _num(g('avg')),
                                 'close': _num(g('close')), 'value': _num(g('value')),
                                 'sector': str(g('sector') or '').strip()})
    if skipped:
        warnings.append(f'{skipped} row(s) skipped (F&O / currency / commodity, or missing date, side, quantity or price).')
    kind = 'tradebook' if trades else 'holdings' if holdings else ''
    if not kind:
        raise ValueError('No tradebook or holdings table found — the file needs columns such as Symbol / ISIN, '
                         'Quantity, and Buy/Sell + Price (tradebook) or Average price (holdings).')
    if not as_of:
        as_of = max((t['date'] for t in trades), default='') or date.today().isoformat()
    return {'kind': kind, 'as_of': as_of, 'trades': trades, 'holdings': holdings, 'warnings': warnings,
            'text_hint': preamble[:400]}


ISIN_RE = re.compile(r'\b(IN[EF0-9][A-Z0-9]{8}\d)\b')


def parse_cas_text(text: str):
    """1.4: CDSL / NSDL statements are read per demat account by depository.parse_text."""
    import depository
    return depository.parse_text(text)


def _parse_cas_text_old(text: str):
    """CDSL / NSDL CAS — equity holdings lines that carry an ISIN (beta: check the preview)."""
    holdings, as_of = [], ''
    m = re.search(r'(?:as on|as of|for the period.*?to)\s*([0-9]{1,2}[- ][A-Za-z]{3}[- ][0-9]{4}|[0-9]{2}/[0-9]{2}/[0-9]{4})',
                  text, re.I)
    if m:
        as_of = _date(m.group(1).replace(' ', '-'))
    for line in text.splitlines():
        im = ISIN_RE.search(line)
        if not im or not im.group(1).startswith('INE'):          # equity ISINs only (INE…)
            continue
        rest = line[im.end():]
        nums = [_num(x) for x in re.findall(r'-?[\d,]+\.\d+|-?\d[\d,]*', rest)]
        name = re.sub(r'[\d,.\-]+', ' ', rest).strip()
        name = re.sub(r'\s{2,}', ' ', name)[:60]
        if not nums:
            continue
        qty = nums[0]
        value = nums[-1] if len(nums) > 1 else 0
        price = nums[-2] if len(nums) > 2 else (value / qty if qty else 0)
        holdings.append({'symbol': _symbol_from_name(name) if name else im.group(1), 'isin': im.group(1), 'name': name.title(),
                         'qty': qty, 'avg_cost': 0, 'close': price, 'value': value, 'sector': '', 'raw': line.strip()[:160]})
    warnings = ['CAS reading is in beta — compare the quantities with your CAS before importing.']
    if not holdings:
        warnings = ['No equity holdings (ISIN lines) found in this statement.']
    return {'kind': 'holdings' if holdings else 'info', 'as_of': as_of or date.today().isoformat(),
            'holdings': holdings, 'warnings': warnings}


# ── Securities, trades, portfolio ────────────────────────────────────────────
def security_id(con, symbol, isin='', name='', exchange='NSE', sector='', create=True):
    isin = (isin or '').upper()
    if isin:
        r = con.execute('SELECT id FROM inv_securities WHERE isin=?', (isin,)).fetchone()
        if r:
            return r[0]
    r = con.execute('SELECT id, isin FROM inv_securities WHERE symbol=?', (symbol,)).fetchone()
    if r:
        if isin and not r[1]:
            con.execute('UPDATE inv_securities SET isin=? WHERE id=?', (isin, r[0]))
        return r[0]
    if not create:
        return None
    return con.execute('INSERT INTO inv_securities (symbol, isin, name, exchange, sector) VALUES (?,?,?,?,?)',
                       (symbol or isin, isin or None, name or symbol, exchange or 'NSE', sector or None)).lastrowid


def _dup_key(t):
    return (t['side'], t['date'], round(t['qty'], 4), round(t['price'], 4))


def mark_duplicates(con, broker_id, trades):
    """Trade id when present, otherwise date/side/qty/price with multiplicity."""
    have_ids = {r[0] for r in con.execute("SELECT trade_id FROM inv_trades WHERE broker_id=? AND COALESCE(trade_id,'')<>''",
                                          (broker_id,))}
    existing = defaultdict(int)
    for r in con.execute('SELECT s.symbol, s.isin, t.side, t.trade_date, t.qty, t.price FROM inv_trades t '
                         'JOIN inv_securities s ON s.id=t.security_id WHERE t.broker_id=?', (broker_id,)):
        existing[(r[1] or r[0], r[2], r[3], round(r[4], 4), round(r[5], 4))] += 1
    for t in trades:
        if t['trade_id'] and t['trade_id'] in have_ids:
            t['dup'] = True
            continue
        k = (t['isin'] or t['symbol'],) + _dup_key(t)
        if existing.get(k, 0) > 0:
            existing[k] -= 1
            t['dup'] = True
        else:
            t['dup'] = False


def positions(con, broker_id=None):
    """Per security: qty, avg cost (weighted average), invested, realised P&L, buys, last buy."""
    q = ('SELECT t.*, s.symbol FROM inv_trades t JOIN inv_securities s ON s.id=t.security_id ' +
         ('WHERE t.broker_id=? ' if broker_id else '') + 'ORDER BY t.trade_date, t.id')
    pos = {}
    for t in con.execute(q, (broker_id,) if broker_id else ()):
        p = pos.setdefault(t['security_id'], {'qty': 0.0, 'cost': 0.0, 'realised': 0.0, 'buys': 0, 'last_buy': None,
                                               'last_buy_date': '', 'first_date': t['trade_date'], 'brokers': set(),
                                               'oversold': 0.0, 'sold_value': 0.0})
        p['brokers'].add(t['broker_id'])
        if t['side'] == 'buy':
            p['cost'] += t['qty'] * t['price'] + (t['charges'] or 0)
            p['qty'] += t['qty']
            p['buys'] += 1
            p['last_buy'], p['last_buy_date'] = t['price'], t['trade_date']
        else:
            avg = p['cost'] / p['qty'] if p['qty'] else 0
            q_ = min(t['qty'], p['qty'])
            if t['qty'] > p['qty'] + 1e-9:
                p['oversold'] += t['qty'] - p['qty']
                p['sold_value'] += (t['qty'] - p['qty']) * t['price']
            p['realised'] += (t['price'] - avg) * q_ - (t['charges'] or 0)
            p['cost'] -= avg * q_
            p['qty'] -= q_
        if p['qty'] < 1e-9:
            p['qty'], p['cost'] = 0.0, 0.0
    for p in pos.values():
        p['avg'] = p['cost'] / p['qty'] if p['qty'] else 0
    return pos


def latest_holdings(con):
    """Latest holdings statement per broker and per demat account → {security_id: {qty, cas_qty, avg, close, as_of, sources}}
    qty = broker holdings statements; cas_qty = depository (CDSL / NSDL) statements."""
    key = "CASE WHEN h.demat_id IS NOT NULL THEN 'd' || h.demat_id ELSE 'b' || COALESCE(h.broker_id, 0) END"
    latest = {r[0]: r[1] for r in con.execute(f'SELECT {key}, MAX(as_of) FROM inv_holdings h GROUP BY 1')}
    out = {}
    for r in con.execute(f"SELECT h.*, {key} AS k, COALESCE(b.name, dm.depository || ' ' || COALESCE(dm.dp_name, '')) AS bname "
                         'FROM inv_holdings h LEFT JOIN inv_brokers b ON b.id=h.broker_id LEFT JOIN inv_demats dm ON dm.id=h.demat_id'):
        if r['as_of'] != latest.get(r['k']):
            continue
        is_cas = r['demat_id'] is not None
        o = out.setdefault(r['security_id'], {'qty': 0.0, 'cas_qty': None, 'avg': 0.0, 'close': 0.0, 'as_of': '', 'sources': []})
        if is_cas:
            o['cas_qty'] = (o['cas_qty'] or 0) + r['qty']
        else:
            o['qty'] += r['qty']
            o['avg'] = r['avg_cost'] or o['avg']
        o['close'] = r['close_price'] or o['close']
        o['as_of'] = max(o['as_of'], r['as_of'] or '')
        o['sources'].append(r['bname'] or r['source'])
    return out


def build_portfolio(con, broker_id=None, asset_type=None):
    """Rows for the portfolio page + suggestions, using the TF tranching rules.
    1.2: broker_id limits it to what was bought / sold through one broker; asset_type to one type."""
    st = settings(con)
    pos = positions(con, broker_id)
    hold = latest_holdings(con) if not broker_id else {}
    brokers = {r[0]: r[1] for r in con.execute('SELECT id, name FROM inv_brokers')}
    rows = []
    for s in con.execute('SELECT * FROM inv_securities ORDER BY symbol'):
        sid = s['id']
        p, h = pos.get(sid), hold.get(sid)
        if p:
            qty, avg, realised, src = p['qty'], p['avg'], p['realised'], 'trades'
        elif h:
            qty = h['qty'] if h['qty'] else (h['cas_qty'] or 0)
            avg, realised, src = h['avg'] or h['close'], 0.0, 'holdings file'
        else:
            qty, avg, realised, src = 0.0, 0.0, 0.0, ''
        if qty <= 0 and s['plan_status'] != 'watch':
            continue
        cmp_ = s['cmp'] or (h['close'] if h and h['close'] else 0) or avg
        stmt_qty = None
        if h:
            stmt_qty = h['qty'] if h['qty'] else h['cas_qty']
        rows.append({'id': sid, 'symbol': s['symbol'], 'name': s['name'], 'isin': s['isin'], 'sector': s['sector'] or '',
                     'bucket': s['bucket'] or '', 'plan_status': s['plan_status'] or 'active', 'add_rule': s['add_rule'],
                     'step_pct': s['step_pct'], 'gap_days': s['gap_days'], 'qty': qty, 'avg': avg,
                     'invested': qty * avg, 'cmp': cmp_, 'cmp_date': s['cmp_date'] or (h['as_of'] if h else ''),
                     'value': qty * cmp_, 'pnl': qty * (cmp_ - avg), 'realised': realised, 'source': src,
                     'stmt_qty': stmt_qty, 'mismatch': (stmt_qty is not None and p is not None and abs(stmt_qty - qty) > 0.001),
                     'last_buy': p['last_buy'] if p else None, 'last_buy_date': p['last_buy_date'] if p else '',
                     'brokers': ', '.join(sorted(brokers.get(b, '?') for b in (p['brokers'] if p else []))),
                     'buys': p['buys'] if p else 0,
                     'asset_type': s['asset_type'] if 'asset_type' in s.keys() else None})
    if asset_type:
        rows = [r for r in rows if (r['asset_type'] or '') == (asset_type if asset_type != 'none' else '')]
    total_value = sum(r['value'] for r in rows)
    names = {r[0]: (r[2] or r[1]) for r in con.execute('SELECT id, symbol, name FROM inv_securities')}
    capital = st['capital'] or total_value or 1
    sector_val, bucket_val = defaultdict(float), defaultdict(float)
    for r in rows:
        if r['sector']:
            sector_val[r['sector']] += r['value']
        bucket_val[r['bucket'] or 'unset'] += r['value']
    for r in rows:
        r['weight'] = 100 * r['value'] / capital
        r['suggestion'] = suggest(r, st, capital, sector_val, bucket_val, total_value)
    summary = {'capital': capital, 'capital_is_auto': not st['capital'], 'total_value': total_value,
               'invested': sum(r['invested'] for r in rows), 'pnl': sum(r['pnl'] for r in rows),
               'realised': sum(p['realised'] for p in pos.values()),
               'core_pct': 100 * bucket_val['core'] / total_value if total_value else 0,
               'sat_pct': 100 * bucket_val['satellite'] / total_value if total_value else 0,
               'unset_pct': 100 * bucket_val['unset'] / total_value if total_value else 0,
               'sectors': sorted(((k, 100 * v / capital) for k, v in sector_val.items()), key=lambda x: -x[1]),
               'oversold': [{'id': sid, 'name': names.get(sid, '?'), 'qty': p['oversold'], 'value': p['sold_value']}
                            for sid, p in pos.items() if p['oversold'] > 0]}
    return rows, summary, st


def suggest(r, st, capital, sector_val, bucket_val, total_value):
    """One instruction suggestion for a stock: action, tranche, amount, qty, reason."""
    n = int(st['max_tranches']) or 8
    out = {'action': 'HOLD', 'tranche': '', 'amount': 0, 'qty': 0, 'price': r['cmp'], 'reason': '', 'blocked': False}
    if r['plan_status'] == 'paused':
        out['reason'] = 'Plan paused'
        return out
    if not r['bucket']:
        out.update(action='SET', reason='Set Core or Satellite to get tranche suggestions', blocked=True)
        return out
    if not r['cmp']:
        out.update(action='SET', reason='Price (CMP) needed', blocked=True)
        return out
    limit_pct = st['core_stock_max'] if r['bucket'] == 'core' else st['sat_stock_max']
    max_amt = capital * limit_pct / 100
    tranche_amt = max_amt / n
    used = r['invested'] / tranche_amt if tranche_amt else 0
    r['tranches_used'] = used
    r['tranche_amt'] = tranche_amt
    r['limit_pct'] = limit_pct
    if r['plan_status'] == 'exit':
        if r['qty'] <= 0:
            out['reason'] = 'Exited'
            return out
        sell_q = math.ceil(r['qty'] / max(1, math.ceil(used) or 1))
        out.update(action='SELL', tranche=f'exit · {max(1, math.ceil(used))} tranche(s) left', qty=sell_q,
                   amount=sell_q * r['cmp'], reason='Exit plan — sell one tranche at a time')
        return out
    if r['weight'] > limit_pct + st['trim_tolerance'] and r['qty'] > 0:
        excess = r['value'] - max_amt
        q = math.floor(excess / r['cmp'])
        if q > 0:
            out.update(action='TRIM', qty=q, amount=q * r['cmp'],
                       reason=f"Weight {r['weight']:.1f}% is above the {limit_pct:g}% {r['bucket']} limit")
            return out
    if used >= n - 0.25 or r['invested'] >= max_amt * 0.98:
        out['reason'] = f'Fully invested ({min(used, n):.1f} of {n} tranches)'
        return out
    # trigger rule for the next tranche
    if r['qty'] > 0 and r['last_buy']:
        if r['add_rule'] == 'dip' and r['cmp'] > r['last_buy'] * (1 - (r['step_pct'] or 0) / 100):
            out.update(action='WAIT', reason=f"Next tranche when price ≤ ₹{r['last_buy'] * (1 - r['step_pct'] / 100):,.2f} "
                                             f"({r['step_pct']:g}% below last buy)")
            return out
        if r['add_rule'] == 'rise' and r['cmp'] < r['last_buy'] * (1 + (r['step_pct'] or 0) / 100):
            out.update(action='WAIT', reason=f"Next tranche when price ≥ ₹{r['last_buy'] * (1 + r['step_pct'] / 100):,.2f} "
                                             f"({r['step_pct']:g}% above last buy)")
            return out
        if r['add_rule'] == 'gap' and r['last_buy_date']:
            nxt = datetime.strptime(r['last_buy_date'], '%Y-%m-%d').date() + timedelta(days=int(r['gap_days'] or 0))
            if date.today() < nxt:
                out.update(action='WAIT', reason=f'Next tranche on or after {nxt.strftime("%d %b %Y")}')
                return out
    k = min(n, int(used + 0.25) + 1)                    # a tranche counts as done once 75 % of it is invested
    amount = min(k * tranche_amt - r['invested'], max_amt - r['invested'])   # top up to the k-th rung of the ladder
    reasons = []
    if r['sector']:
        room = capital * st['sector_cap'] / 100 - sector_val[r['sector']]
        if room < amount:
            reasons.append(f"sector {r['sector']} at cap ({st['sector_cap']:g}%)" if room <= 0 else
                           f"sector room ₹{room:,.0f}")
            amount = max(0, room)
    else:
        reasons.append('sector not set — sector cap not checked')
    bucket_target = st['core_pct'] if r['bucket'] == 'core' else st['sat_pct']
    room_b = capital * bucket_target / 100 - bucket_val[r['bucket']]
    if room_b < amount:
        reasons.append(f"{r['bucket']} share at {bucket_target:g}%" if room_b <= 0 else f"{r['bucket']} room ₹{room_b:,.0f}")
        amount = max(0, room_b)
    q = math.floor(amount / r['cmp']) if r['cmp'] else 0
    if q <= 0:
        out.update(action='BLOCKED', blocked=True, reason='; '.join(reasons) or 'Tranche smaller than one share')
        return out
    out.update(action='BUY' if r['qty'] <= 0 else 'ADD', tranche=f'{k} of {n}', qty=q, amount=q * r['cmp'],
               reason='; '.join(reasons))
    return out


def match_instructions(con):
    """Mark open instructions done when matching broker trades exist (same stock & side, on/after the date)."""
    n = 0
    used = set()
    for r in con.execute("SELECT trade_ids FROM inv_instructions WHERE COALESCE(trade_ids,'')<>''"):
        used.update(int(x) for x in r[0].split(',') if x)
    for ins in con.execute("SELECT * FROM inv_instructions WHERE status='open' ORDER BY created_at, id").fetchall():
        side = 'buy' if ins['action'] in ('BUY', 'ADD') else 'sell'
        q = ('SELECT id, qty, trade_date FROM inv_trades WHERE security_id=? AND side=? AND trade_date>=? ' +
             ('AND broker_id=? ' if ins['broker_id'] else '') + 'ORDER BY trade_date, id')
        params = [ins['security_id'], side, ins['created_at']] + ([ins['broker_id']] if ins['broker_id'] else [])
        got, ids, last = 0.0, [], ''
        for t in con.execute(q, params):
            if t['id'] in used:
                continue
            got += t['qty']; ids.append(t['id']); last = t['trade_date']
            if ins['qty'] and got >= ins['qty'] * 0.9:
                break
        if ids and (not ins['qty'] or got >= ins['qty'] * 0.9):
            con.execute("UPDATE inv_instructions SET status='done', done_at=?, trade_ids=? WHERE id=?",
                        (last, ','.join(map(str, ids)), ins['id']))
            used.update(ids)
            n += 1
    con.commit()
    return n


# ── Pages ────────────────────────────────────────────────────────────────────
HOOKS = {}          # 1.5: preview / confirm / render for the mail reader (set by register)


def register(app, get_db, upload_dir: Path):
    pend = upload_dir / '.inv_pending'

    def con_():
        c = get_db()
        ensure_schema(c)
        return c

    def portfolio():
        con = con_()
        match_instructions(con)
        import scope as SC
        import assets as AS
        bid = SC.broker_id() or (int(request.args['broker']) if request.args.get('broker', '').isdigit() else None)
        atype = request.args.get('type') or None
        rows, summary, st = build_portfolio(con, bid, atype)
        tlist = AS.types(con)
        tmap = {t['key']: t for t in tlist}
        all_rows = build_portfolio(con, bid)[0] if atype else rows
        mix = AS.by_type(all_rows, tmap)
        for r in rows:
            t = tmap.get(r['asset_type'])
            r['type_label'], r['type_tone'] = (t['label'], t['tone']) if t else ('Type not set', 'slate')
        broker_rows = []
        for b in con.execute('SELECT * FROM inv_brokers ORDER BY id'):
            p = positions(con, b['id'])
            nh = con.execute('SELECT COUNT(*) FROM inv_holdings WHERE broker_id=?', (b['id'],)).fetchone()[0]
            broker_rows.append({'id': b['id'], 'name': b['name'], 'client_id': b['client_id'] or '',
                                'stocks': sum(1 for x in p.values() if x['qty'] > 0),
                                'trades': con.execute('SELECT COUNT(*) FROM inv_trades WHERE broker_id=?', (b['id'],)).fetchone()[0],
                                'holdings_rows': nh,
                                'last': con.execute('SELECT MAX(trade_date) FROM inv_trades WHERE broker_id=?', (b['id'],)).fetchone()[0] or ''})
        instr = con.execute("SELECT i.*, s.symbol, b.name AS broker FROM inv_instructions i JOIN inv_securities s ON s.id=i.security_id "
                            "LEFT JOIN inv_brokers b ON b.id=i.broker_id ORDER BY (i.status='open') DESC, i.id DESC LIMIT 60").fetchall()
        return render_template('inv_portfolio.html', rows=rows, s=summary, st=st, labels=SETTING_LABELS,
                               brokers=broker_rows, instr=instr, sel_broker=bid, sel_type=atype, types=tlist, mix=mix,
                               view=request.args.get('view', 'stock'),
                               actionable=[r for r in rows if r['suggestion']['action'] in ('BUY', 'ADD', 'TRIM', 'SELL')])

    def save_settings():
        con = con_()
        for k in DEFAULT_SETTINGS:
            if k in request.form:
                con.execute('INSERT OR REPLACE INTO inv_settings (key, value) VALUES (?,?)', (k, str(_num(request.form[k]))))
        con.commit()
        flash('Tranching rules saved.', 'success')
        return redirect(url_for('inv_portfolio') + '#rules')

    def broker_save():
        con = con_()
        name = request.form.get('name', '').strip()
        if name:
            bid = request.form.get('id')
            if bid:
                con.execute('UPDATE inv_brokers SET name=?, client_id=? WHERE id=?',
                            (name, request.form.get('client_id', '').strip(), int(bid)))
            else:
                con.execute('INSERT OR IGNORE INTO inv_brokers (name, client_id) VALUES (?,?)',
                            (name, request.form.get('client_id', '').strip()))
            con.commit()
            flash(f'Broker {name} saved.', 'success')
        return redirect(url_for('inv_portfolio') + '#brokers')

    def stock(sid):
        con = con_()
        s = con.execute('SELECT * FROM inv_securities WHERE id=?', (sid,)).fetchone()
        if not s:
            flash('Stock not found.', 'warning')
            return redirect(url_for('inv_portfolio'))
        rows, summary, st = build_portfolio(con)
        r = next((x for x in rows if x['id'] == sid), None)
        trades = con.execute('SELECT t.*, b.name AS broker FROM inv_trades t JOIN inv_brokers b ON b.id=t.broker_id '
                             'WHERE security_id=? ORDER BY trade_date DESC, t.id DESC', (sid,)).fetchall()
        holds = con.execute("SELECT h.*, COALESCE(b.name, dm.depository || ' demat ' || COALESCE(dm.dp_name, '')) AS broker "
                            'FROM inv_holdings h LEFT JOIN inv_brokers b ON b.id=h.broker_id LEFT JOIN inv_demats dm ON dm.id=h.demat_id '
                            'WHERE security_id=? ORDER BY as_of DESC', (sid,)).fetchall()
        instr = con.execute('SELECT i.*, b.name AS broker FROM inv_instructions i LEFT JOIN inv_brokers b ON b.id=i.broker_id '
                            'WHERE security_id=? ORDER BY id DESC', (sid,)).fetchall()
        brokers = con.execute("SELECT id, name FROM inv_brokers WHERE name<>? ORDER BY id", (CAS_SOURCE,)).fetchall()
        sectors = [x[0] for x in con.execute("SELECT DISTINCT sector FROM inv_securities WHERE COALESCE(sector,'')<>'' ORDER BY 1")]
        import assets as AS
        return render_template('inv_stock.html', sec=s, r=r, st=st, s=summary, trades=trades, holds=holds,
                               instr=instr, brokers=brokers, sectors=sectors, asset_types=AS.types(con))

    def stock_save(sid):
        con = con_()
        f = request.form
        sym = _clean_symbol(f.get('symbol', ''))
        if sym and not con.execute('SELECT 1 FROM inv_securities WHERE symbol=? AND id<>?', (sym, sid)).fetchone():
            con.execute('UPDATE inv_securities SET symbol=? WHERE id=?', (sym, sid))
        con.execute('UPDATE inv_securities SET name=?, sector=?, bucket=?, plan_status=?, add_rule=?, step_pct=?, gap_days=?, '
                    'notes=? WHERE id=?',
                    (f.get('name', '').strip() or None, f.get('sector', '').strip() or None, f.get('bucket') or None,
                     f.get('plan_status', 'active'), f.get('add_rule', 'any'), _num(f.get('step_pct', 10)),
                     int(_num(f.get('gap_days', 30))), f.get('notes', '').strip() or None, sid))
        if f.get('cmp'):
            con.execute("UPDATE inv_securities SET cmp=?, cmp_date=date('now'), cmp_source='manual' WHERE id=?",
                        (_num(f['cmp']), sid))
        con.commit()
        flash('Plan saved.', 'success')
        return redirect(url_for('inv_stock', sid=sid))

    def stock_add():
        con = con_()
        f = request.form
        sym = _clean_symbol(f.get('symbol', ''))
        if not sym:
            flash('Symbol required.', 'warning')
            return redirect(url_for('inv_portfolio'))
        sid = security_id(con, sym, f.get('isin', '').strip(), f.get('name', '').strip(), 'NSE', f.get('sector', '').strip())
        held = con.execute('SELECT 1 FROM inv_trades WHERE security_id=? UNION SELECT 1 FROM inv_holdings WHERE security_id=?',
                           (sid, sid)).fetchone()
        con.execute('UPDATE inv_securities SET bucket=COALESCE(?, bucket) WHERE id=?', (f.get('bucket') or None, sid))
        if not held:
            con.execute("UPDATE inv_securities SET plan_status='watch' WHERE id=?", (sid,))
        if f.get('cmp'):
            con.execute("UPDATE inv_securities SET cmp=?, cmp_date=date('now'), cmp_source='manual' WHERE id=?",
                        (_num(f['cmp']), sid))
        con.commit()
        flash(f'{sym} added to the plan.', 'success')
        return redirect(url_for('inv_stock', sid=sid))

    def instruction_add():
        con = con_()
        f = request.form
        sid = int(f['security_id'])
        con.execute('INSERT INTO inv_instructions (security_id, broker_id, action, tranche, qty, amount, limit_price, reason, notes) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (sid, int(f['broker_id']) if f.get('broker_id') else None, f['action'], f.get('tranche', ''),
                     _num(f.get('qty')), _num(f.get('amount')), _num(f.get('limit_price')) or None,
                     f.get('reason', ''), f.get('notes', '').strip() or None))
        con.commit()
        flash(f"Instruction saved: {f['action']} {f.get('qty')} — it will be marked done when the broker trade is imported.",
              'success')
        return redirect(request.form.get('next') or url_for('inv_portfolio'))

    def instruction_status(iid):
        con = con_()
        st_ = request.form.get('status')
        if st_ in ('done', 'cancelled', 'open'):
            con.execute("UPDATE inv_instructions SET status=?, done_at=CASE WHEN ?='done' THEN date('now') END WHERE id=?",
                        (st_, st_, iid))
            con.commit()
        return redirect(request.form.get('next') or url_for('inv_portfolio'))

    def trades_page():
        con = con_()
        a = request.args
        cond, par = ['1=1'], []
        if a.get('broker'):
            cond.append('t.broker_id=?'); par.append(int(a['broker']))
        if a.get('side'):
            cond.append('t.side=?'); par.append(a['side'])
        if a.get('q'):
            cond.append('(s.symbol LIKE ? OR s.name LIKE ? OR s.isin LIKE ?)'); par += [f"%{a['q']}%"] * 3
        import scope as SC
        if SC.broker_id() and not a.get('broker'):
            cond.append('t.broker_id=?'); par.append(SC.broker_id())
        if a.get('start'):
            cond.append('t.trade_date>=?'); par.append(a['start'])
        if a.get('end'):
            cond.append('t.trade_date<=?'); par.append(a['end'])
        if a.get('type'):
            cond.append("COALESCE(s.asset_type,'')=?"); par.append('' if a['type'] == 'none' else a['type'])
        rows = con.execute(f'SELECT t.*, s.symbol, s.name, s.asset_type, b.name AS broker FROM inv_trades t JOIN inv_securities s ON s.id=t.security_id '
                           f'JOIN inv_brokers b ON b.id=t.broker_id WHERE {" AND ".join(cond)} ORDER BY t.trade_date DESC, t.id DESC LIMIT 2000',
                           par).fetchall()
        brokers = con.execute('SELECT id, name FROM inv_brokers ORDER BY id').fetchall()
        groups = {}
        for r in rows:
            gname = r['broker']
            g = groups.setdefault(gname, {'name': gname, 'id': r['broker_id'], 'rows': [], 'buy': 0.0, 'sell': 0.0, 'charges': 0.0})
            g['rows'].append(r)
            g['buy' if r['side'] == 'buy' else 'sell'] += r['qty'] * r['price']
            g['charges'] += r['charges'] or 0
        import assets as AS
        return render_template('inv_trades.html', rows=rows, brokers=brokers, a=a, groups=sorted(groups.values(), key=lambda g: g['name']),
                               group=a.get('group', 'broker'), types=AS.types(con))

    def trade_add():
        con = con_()
        f = request.form
        sym = _clean_symbol(f.get('symbol', ''))
        price_ok = _num(f.get('price')) > 0 or (f.get('side', 'buy') == 'buy' and str(f.get('price', '')).strip() in ('0', '0.0', '0.00'))
        if not (sym and f.get('date') and _num(f.get('qty')) and price_ok):
            flash('Symbol, date, quantity and price are required (price 0 is allowed for bonus shares).', 'warning')
            return redirect(url_for('inv_trades'))
        sid = security_id(con, sym, f.get('isin', '').strip())
        con.execute("INSERT INTO inv_trades (broker_id, security_id, trade_date, side, qty, price, charges, source, notes) "
                    "VALUES (?,?,?,?,?,?,?,'manual',?)",
                    (int(f['broker_id']), sid, f['date'], f.get('side', 'buy'), _num(f['qty']), _num(f['price']),
                     _num(f.get('charges')), f.get('notes', '').strip() or None))
        con.execute("UPDATE inv_securities SET plan_status='active' WHERE id=? AND plan_status='watch'", (sid,))
        con.commit()
        match_instructions(con)
        flash('Trade added.', 'success')
        return redirect(url_for('inv_trades'))

    def trade_delete(tid):
        con = con_()
        con.execute('DELETE FROM inv_trades WHERE id=?', (tid,))
        con.commit()
        flash('Trade deleted.', 'info')
        return redirect(url_for('inv_trades'))

    # ── import (several files at once: contract notes, holdings exports, CAS) ──
    def _history(con):
        return con.execute("SELECT i.*, COALESCE(b.name, CASE WHEN i.kind='depository' THEN 'CDSL / NSDL' END) AS broker "
                           'FROM inv_imports i LEFT JOIN inv_brokers b ON b.id=i.broker_id ORDER BY i.id DESC LIMIT 100').fetchall()

    def import_page():
        con = con_()
        return render_template('inv_import.html', hist=_history(con), brokers=_brokers(con), previews=[],
                               readers=_readers(), demats=_demats(con))

    def _readers():
        import contract_notes
        return [(r.broker, r.name) for r in contract_notes.READERS]

    def _brokers(con):
        return con.execute('SELECT id, name FROM inv_brokers ORDER BY id').fetchall()

    def _demats(con):
        import depository as DP
        return [{'id': d['id'], 'label': DP.label(d)} for d in con.execute('SELECT * FROM inv_demats ORDER BY depository, dp_name')]

    def _saved_passwords(con):
        try:
            return [r[0] for r in con.execute("SELECT password FROM passwords WHERE COALESCE(password,'')<>''")]
        except Exception:  # noqa: BLE001
            return []

    def _preview_one(con, token, path, fname, typed_pw):
        brokers = _brokers(con)
        bname = {b['id']: b['name'] for b in brokers}
        fhash = hashlib.sha256(path.read_bytes()).hexdigest()
        pv, err, needs_pw = None, '', False
        try:
            pv = parse_broker_file(path, fname, typed_pw, _saved_passwords(con))
        except NeedsPassword as e:
            err, needs_pw = str(e), True
        except Exception as e:  # noqa: BLE001
            err = str(e)
        bid = ''
        if pv:
            guess = pv.get('broker_guess') or detect_broker(fname, pv.get('text_hint', ''), list(bname.values()))
            bid = next((str(k) for k, v in bname.items() if v == guess), '')
            if pv['trades'] and bid:
                mark_duplicates(con, int(bid), pv['trades'])
        dup_file = con.execute('SELECT imported_at FROM inv_imports WHERE file_hash=?', (fhash,)).fetchone()
        meta = {'token': token, 'path': str(path), 'file': fname, 'hash': fhash, 'pv': pv, 'broker_id': bid}
        import dbconn
        dbconn.write_sealed(pend / f'{token}.json', meta)
        if pv and pv['kind'] == 'depository':
            import depository as DP
            for a in pv.get('demats', []):
                a['masked'] = DP.masked(a['account_no'])
                a['n'] = sum(1 for h in pv['holdings'] if h.get('acct') == a['account_no'])
                b = DP.guess_broker(con, a.get('dp_name'), a['account_no'])
                a['broker'] = bname.get(b, '')
        importable = bool(pv and pv['kind'] in ('tradebook', 'holdings', 'depository') and not dup_file
                          and (any(not t.get('dup') for t in pv['trades']) or pv['holdings']))
        tick = importable and pv.get('check') != 'MISMATCH'
        return {'token': token, 'file': fname, 'pv': pv, 'err': err, 'needs_pw': needs_pw, 'broker_id': bid,
                'dup_file': dup_file, 'importable': importable, 'tick': tick,
                'new': sum(1 for t in (pv or {}).get('trades', []) if not t.get('dup')),
                'dups': sum(1 for t in (pv or {}).get('trades', []) if t.get('dup'))}

    def import_preview():
        con = con_()
        pend.mkdir(parents=True, exist_ok=True)
        typed = request.form.get('password', '').strip()
        previews = []
        retry = [t for t in request.form.getlist('retry') if re.fullmatch(r'[0-9a-f]{12}', t)]
        for t in retry:
            mp = pend / f'{t}.json'
            if mp.exists():
                import dbconn
                meta = dbconn.read_sealed(mp)
                previews.append(_preview_one(con, t, Path(meta['path']), meta['file'], typed))
        for f in request.files.getlist('files'):
            if not f or not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in ('.csv', '.xlsx', '.xls', '.pdf'):
                previews.append({'token': '', 'file': f.filename, 'pv': None, 'err': 'Use PDF, CSV, XLSX or XLS.',
                                 'needs_pw': False, 'importable': False})
                continue
            token = uuid.uuid4().hex[:12]
            path = pend / f'{token}{ext}'
            f.save(str(path))
            previews.append(_preview_one(con, token, path, f.filename, typed))
        if typed and request.form.get('save_pw') and any(p.get('pv') and p['pv'].get('password_used') for p in previews):
            if not con.execute('SELECT 1 FROM passwords WHERE password=?', (typed,)).fetchone():
                con.execute("INSERT OR IGNORE INTO passwords (institution, label, password, hint) VALUES (?,?,?,?)",
                            ('broker_pan', 'Broker / depository statements', typed, 'PAN (saved from Investments import)'))
                con.commit()
        if not previews:
            flash('Choose one or more broker files.', 'warning')
            return redirect(url_for('inv_import'))
        return render_template('inv_import.html', hist=_history(con), brokers=_brokers(con), previews=previews,
                               readers=_readers(), demats=_demats(con))

    def _commit(con, meta, bid):
        pv = meta['pv']
        mark_duplicates(con, bid, pv['trades'])
        iid = con.execute('INSERT INTO inv_imports (file_name, file_hash, broker_id, kind, as_of, rows) VALUES (?,?,?,?,?,?)',
                          (meta['file'], meta['hash'], bid, pv['kind'], pv['as_of'],
                           len(pv['trades']) + len(pv['holdings']))).lastrowid
        added = 0
        for t in pv['trades']:
            if t.get('dup'):
                continue
            sid = security_id(con, t['symbol'], t['isin'], t.get('name', ''), exchange=t.get('exchange') or 'NSE')
            con.execute('INSERT INTO inv_trades (broker_id, security_id, trade_date, side, qty, price, charges, trade_id, '
                        'order_id, exchange, import_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (bid, sid, t['date'], t['side'], t['qty'], t['price'], t.get('charges', 0), t['trade_id'] or None,
                         t['order_id'] or None, t.get('exchange'), iid))
            con.execute("UPDATE inv_securities SET plan_status='active' WHERE id=? AND plan_status='watch'", (sid,))
            con.execute("UPDATE inv_securities SET cmp=?, cmp_date=?, cmp_source='last trade' WHERE id=? AND "
                        "(cmp IS NULL OR (cmp_source='last trade' AND COALESCE(cmp_date,'')<=?))",
                        (t['price'], t['date'], sid, t['date']))
            added += 1
        for h in pv['holdings']:
            sid = security_id(con, h['symbol'], h['isin'], h.get('name', ''), sector=h.get('sector', ''))
            if h.get('sector'):
                con.execute('UPDATE inv_securities SET sector=COALESCE(sector, ?) WHERE id=?', (h['sector'], sid))
            if h.get('close'):
                con.execute("UPDATE inv_securities SET cmp=?, cmp_date=?, cmp_source='statement' WHERE id=? AND "
                            "(cmp IS NULL OR cmp_source<>'manual' OR COALESCE(cmp_date,'')<=?)",
                            (h['close'], pv['as_of'], sid, pv['as_of']))
            con.execute('INSERT INTO inv_holdings (import_id, broker_id, source, as_of, security_id, qty, avg_cost, close_price, value) '
                        'VALUES (?,?,?,?,?,?,?,?,?)', (iid, bid, meta['file'], pv['as_of'], sid, h['qty'], h['avg_cost'],
                                                       h['close'], h['value']))
            added += 1
        con.execute('UPDATE inv_imports SET added=? WHERE id=?', (added, iid))
        return added

    def _confirm_one(con, token, sel=None):
        """Import one previewed broker / depository file → (rows added, message). Used by the page and the mail reader."""
        p = pend / f'{token}.json'
        if not re.fullmatch(r'[0-9a-f]{12}', token or '') or not p.exists():
            return 0, 'a preview expired — add that file again'
        import dbconn
        import vault as _vt
        meta = dbconn.read_sealed(p)
        if not meta.get('pv'):
            return 0, f"{meta.get('file', 'file')}: nothing to import"
        sel = sel or str(meta.get('broker_id') or '')
        if con.execute('SELECT 1 FROM inv_imports WHERE file_hash=?', (meta['hash'],)).fetchone():
            return 0, f"{meta['file']}: already imported"
        depo = meta['pv']['kind'] == 'depository' or sel.startswith('d')
        if depo:
            import depository as DP
            override = int(sel[1:]) if sel.startswith('d') and sel[1:].isdigit() else None
            if not override and not meta['pv'].get('demats'):
                return 0, f"{meta['file']}: choose the demat account"
        else:
            bid = int(sel) if sel.isdigit() else 0
            if not bid:
                return 0, f"{meta['file']}: choose the broker"
        try:
            n = DP.commit(con, meta, override) if depo else _commit(con, meta, bid)
            con.commit()
        except Exception as e:  # noqa: BLE001
            con.rollback()
            return 0, f"{meta['file']}: failed, nothing saved ({e})"
        for f in (Path(meta['path']), p):
            if f.exists():
                _vt.secure_delete(f)
        return n, f"{meta['file']}: {n} {'demat holdings' if depo else 'rows'} added"

    def import_confirm():
        con = con_()
        msgs, total = [], 0
        for token in request.form.getlist('token'):
            n, m = _confirm_one(con, token, request.form.get(f'broker_{token}'))
            total += n
            msgs.append(m)
        done = match_instructions(con)
        flash(f'{total} trade / holding rows imported. ' + '; '.join(msgs) +
              (f'. {done} instruction(s) marked done.' if done else ''), 'success' if total else 'warning')
        return redirect(url_for('inv_portfolio'))

    def _render_previews(con, previews):
        return render_template('inv_import.html', hist=_history(con), brokers=_brokers(con), previews=previews,
                               readers=_readers(), demats=_demats(con))

    def _discard(token):
        """Erase a preview that will not be imported (its file and sealed meta)."""
        import dbconn
        import vault as _vt
        p = pend / f'{token}.json'
        if re.fullmatch(r'[0-9a-f]{12}', token or '') and p.exists():
            try:
                meta = dbconn.read_sealed(p)
                if Path(meta['path']).exists():
                    _vt.secure_delete(Path(meta['path']))
            except Exception:  # noqa: BLE001
                pass
            _vt.secure_delete(p)

    def _hook_preview(con, path, fname, pw=''):
        pend.mkdir(parents=True, exist_ok=True)
        return _preview_one(con, uuid.uuid4().hex[:12], path, fname, pw)

    HOOKS.update(preview=_hook_preview,
                 confirm=_confirm_one, render=_render_previews, discard=_discard, pend=lambda: pend)

    def import_delete(iid):
        con = con_()
        con.execute('DELETE FROM inv_trades WHERE import_id=?', (iid,))
        con.execute('DELETE FROM inv_holdings WHERE import_id=?', (iid,))
        con.execute('DELETE FROM inv_imports WHERE id=?', (iid,))
        con.commit()
        flash('Import removed with its trades / holdings.', 'info')
        return redirect(url_for('inv_import'))

    def refresh_prices():
        con = con_()
        try:
            import yfinance as yf  # optional
        except ImportError:
            flash('Live prices need the yfinance package: open a command prompt in the Hub folder and run '
                  '"pip install yfinance", then try again. Until then prices come from holdings files or what you type.',
                  'warning')
            return redirect(url_for('inv_portfolio'))
        n = 0
        for s in con.execute("SELECT id, symbol, exchange, isin FROM inv_securities").fetchall():
            tick = f"{s['symbol']}.{'BO' if (s['exchange'] or '').upper() == 'BSE' else 'NS'}"
            try:
                h = yf.Ticker(tick).history(period='5d')
                if not len(h) and s['isin']:                       # symbol not confirmed yet → look up by ISIN
                    h = yf.Ticker(s['isin']).history(period='5d')
                if len(h):
                    con.execute("UPDATE inv_securities SET cmp=?, cmp_date=?, cmp_source='yfinance' WHERE id=?",
                                (float(h['Close'].iloc[-1]), h.index[-1].date().isoformat(), s['id']))
                    n += 1
            except Exception:  # noqa: BLE001
                pass
        con.commit()
        flash(f'Prices updated for {n} stock(s).', 'success')
        return redirect(url_for('inv_portfolio'))

    routes = [
        ('/investments', 'inv_portfolio', portfolio, ['GET']),
        ('/investments/settings', 'inv_settings', save_settings, ['POST']),
        ('/investments/brokers/save', 'inv_broker_save', broker_save, ['POST']),
        ('/investments/stock/<int:sid>', 'inv_stock', stock, ['GET']),
        ('/investments/stock/<int:sid>/save', 'inv_stock_save', stock_save, ['POST']),
        ('/investments/stock/add', 'inv_stock_add', stock_add, ['POST']),
        ('/investments/instructions/add', 'inv_instruction_add', instruction_add, ['POST']),
        ('/investments/instructions/<int:iid>/status', 'inv_instruction_status', instruction_status, ['POST']),
        ('/investments/trades', 'inv_trades', trades_page, ['GET']),
        ('/investments/trades/add', 'inv_trade_add', trade_add, ['POST']),
        ('/investments/trades/<int:tid>/delete', 'inv_trade_delete', trade_delete, ['POST']),
        ('/investments/import', 'inv_import', import_page, ['GET']),
        ('/investments/import/preview', 'inv_import_preview', import_preview, ['POST']),
        ('/investments/import/confirm', 'inv_import_confirm', import_confirm, ['POST']),
        ('/investments/import/<int:iid>/delete', 'inv_import_delete', import_delete, ['POST']),
        ('/investments/prices', 'inv_prices', refresh_prices, ['POST']),
    ]
    for rule, ep, fn, methods in routes:
        app.add_url_rule(rule, ep, fn, methods=methods)
