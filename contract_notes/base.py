"""Shared pieces for contract-note readers (one module per broker).

A reader turns the text of an equity contract note into a ContractNote:
  trades      one dict per trade line (date, isin, name, side, qty, price, trade_id, order_id, exchange)
  obligation  pay-in / (pay-out) obligation before levies, as printed (buys − sells)
  net         net amount payable by (+) / receivable by (−) the client, as printed
  levies      {'Brokerage': .., 'STT': .., 'GST': .., 'Stamp duty': .., 'Exchange charges': .., 'SEBI fees': .., ...}
Then check() reconciles: Σ buys − Σ sells = obligation, and obligation + charges = net.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

ISIN = r'IN[EF][A-Z0-9]{8}\d'
# SEBI common format, Annexure A: Order no, Order time, Trade no, Trade time, Security (with ISIN), B/S, Qty, Price …
TRADE_LINE = re.compile(
    r'^(?P<order>\d{6,20})\s+(?P<otime>\d\d:\d\d:\d\d)\s+(?P<trade>\d{3,20})\s+(?P<ttime>\d\d:\d\d:\d\d)\s+(?P<desc>.+?)'
    r'(?:\s*\[|-Cash-|/|\s)(?P<isin>' + ISIN + r')\]?\s+(?P<side>[BS])\s+(?P<qty>-?[\d,]+(?:\.\d+)?)\s+'
    r'(?P<price>[\d,]+\.\d+)(?P<rest>.*)$')
FNO = re.compile(r'\b(FUT|OPT|FUTSTK|OPTSTK|FUTIDX|OPTIDX|CE|PE)\b')


def num(s):
    s = str(s or '').replace(',', '').strip()
    neg = s.startswith('(') and s.endswith(')')
    try:
        v = float(s.strip('()'))
    except ValueError:
        return 0.0
    return -v if neg else v


def parse_date(s):
    s = (s or '').strip()
    for f in ('%d/%m/%Y', '%d-%m-%Y', '%d-%b-%y', '%d-%b-%Y', '%d/%m/%y', '%d %b %Y', '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(s.title() if any(c.isalpha() for c in s) else s, f).date().isoformat()
        except ValueError:
            pass
    return ''


def symbol_from_name(name):
    n = re.sub(r'\(.*?\)', '', name.upper())
    n = re.sub(r'\b(LIMITED|LTD|LTD\.|INDIA|CO|CORPORATION|CORP|INDUSTRIES|IND|THE|OF|AND|&)\b\.?', ' ', n)
    words = [w for w in re.split(r'[^A-Z0-9]+', n) if w]
    return ''.join(words)[:16] or name.upper()[:16]


def first(rx, text, flags=re.I | re.M, group=1):
    m = re.search(rx, text, flags)
    return m.group(group) if m else None


@dataclass
class ContractNote:
    broker: str = ''
    reader: str = ''
    contract_no: str = ''
    trade_date: str = ''
    trades: list = field(default_factory=list)
    obligation: float = None       # buys − sells, before levies (as printed)
    net: float = None              # payable (+) / receivable (−) after levies (as printed)
    levies: dict = field(default_factory=dict)
    skipped_fno: int = 0
    warnings: list = field(default_factory=list)
    check: str = 'n/a'             # OK / MISMATCH / n/a
    check_detail: str = ''

    @property
    def buys(self):
        return sum(t['qty'] * t['price'] for t in self.trades if t['side'] == 'buy')

    @property
    def sells(self):
        return sum(t['qty'] * t['price'] for t in self.trades if t['side'] == 'sell')

    @property
    def charges(self):
        if self.levies:
            return round(sum(self.levies.values()), 2)
        if self.net is not None:
            return round(abs(self.net - (self.buys - self.sells)), 2)
        return 0.0

    def reconcile(self, tol=1.0):
        """Σ trades vs printed obligation; obligation + levies vs printed net amount."""
        gross = self.buys - self.sells
        notes, ok = [], True
        if self.obligation is not None:
            if abs(abs(gross) - abs(self.obligation)) <= tol:
                notes.append(f'trades ₹{gross:,.2f} = obligation')
            else:
                ok = False
                notes.append(f'trades ₹{gross:,.2f} ≠ printed obligation ₹{self.obligation:,.2f}')
        if self.net is not None and self.levies:
            exp = gross + sum(self.levies.values())
            if abs(exp - self.net) <= tol or abs(exp + self.net) <= tol and gross < 0:
                notes.append(f'+ charges ₹{self.charges:,.2f} = net ₹{self.net:,.2f}')
            else:
                ok = False
                notes.append(f'trades + charges ₹{exp:,.2f} ≠ printed net ₹{self.net:,.2f}')
        if not notes:
            self.check, self.check_detail = 'n/a', 'no totals printed to check against'
        else:
            self.check, self.check_detail = ('OK' if ok else 'MISMATCH'), '; '.join(notes)
        return self.check

    def spread_charges(self):
        """Charges shared over trades by value, so the cost of each lot includes them."""
        turnover = self.buys + self.sells
        for t in self.trades:
            t['charges'] = round(self.charges * t['qty'] * t['price'] / turnover, 4) if turnover else 0.0


class Reader:
    """Subclass per broker: set name / keywords, override parse() pieces when the layout differs."""
    name = 'Generic'
    broker = ''
    keywords = ()                 # upper-case words that identify the broker in the text

    def detect(self, text_upper: str) -> int:
        return sum(10 for k in self.keywords if k in text_upper)

    # --- pieces a broker module usually overrides ------------------------
    def trade_date(self, text):
        d = first(r'TRADE DATE\s*:?\s*(\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4})', text)
        return parse_date(d) if d else ''

    def contract_no(self, text):
        return first(r'CONTRACT NOTE NO\.?\s*:?\s*([A-Z0-9/-]+)', text) or ''

    def obligation(self, text):
        v = first(r'PAY\s*IN\s*/\s*\(?\s*PAY\s*OUT\s*\)?\s*OBLIGATION\s+(-?[\d,]+\.\d+)', text)
        return num(v) if v is not None else None

    def net(self, text):
        v = first(r'Net amount[^\n]*?\(Rs\.?\)\s*(-?[\d,]+\.\d+)', text)
        return num(v) if v is not None else None

    def levies(self, text):
        return {}

    # --- common ---------------------------------------------------------
    def trades(self, text, trade_date):
        out, skipped, exch = [], 0, 'NSE'
        for line in text.splitlines():
            line = line.strip()
            if line in ('NSEM', 'NSEZ', 'NSE'):
                exch = 'NSE'
            elif line in ('BSEM', 'BSEZ', 'BSE'):
                exch = 'BSE'
            m = TRADE_LINE.match(line)
            if not m:
                continue
            desc = m.group('desc')
            if FNO.search(desc):
                skipped += 1
                continue
            rest = m.group('rest')
            ex = 'BSE' if re.search(r'\bBSE\b', rest) else 'NSE' if re.search(r'\bNSE\b', rest) else exch
            name = re.sub(r'\s+', ' ', desc).strip(' -[')
            out.append({'date': trade_date, 'symbol': symbol_from_name(name), 'name': name.title(),
                        'isin': m.group('isin'), 'side': 'buy' if m.group('side') == 'B' else 'sell',
                        'qty': abs(num(m.group('qty'))), 'price': num(m.group('price')),
                        'trade_id': m.group('trade'), 'order_id': m.group('order'), 'exchange': ex, 'charges': 0.0})
        return out, skipped

    def parse(self, text) -> ContractNote:
        cn = ContractNote(broker=self.broker, reader=self.name)
        cn.trade_date = self.trade_date(text)
        cn.contract_no = self.contract_no(text)
        cn.trades, cn.skipped_fno = self.trades(text, cn.trade_date)
        cn.obligation = self.obligation(text)
        cn.net = self.net(text)
        cn.levies = {k: v for k, v in self.levies(text).items() if v}
        if not cn.trade_date:
            cn.warnings.append('Trade date not found — check the dates.')
        if cn.skipped_fno:
            cn.warnings.append(f'{cn.skipped_fno} F&O trade(s) skipped (only equity delivery is tracked).')
        cn.reconcile()
        cn.spread_charges()
        return cn
