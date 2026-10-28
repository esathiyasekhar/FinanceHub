"""South Indian Bank (SIB) One Credit Card statement parser — layout based.

Why layout-based: pdfplumber's table detector silently drops many rows on these
statements, and the plain text interleaves columns. Instead every word is placed
into a column by its x-position and attached to the nearest transaction date.

Columns (x, points):  date <80 | merchant 80-235 | category 235-325 | type 325-400 |
                      location 400-485 | reward pts 485-560 | amount >=560
Forex rows: merchant name sits ~13pt ABOVE the date, amount ~5pt above,
            'Forex Fee = x' on the date row, 'GST @ 18% = y   null z' ~14pt below.
Sections:   'Your Transactions' (primary) / "<Name>'s Transactions" (add-on cards).

Credits are not marked visually. They are:
  * category Repayments / Refunds
  * negative reward points (a reversed purchase)
  * any remaining gap to the printed 'Repayments & Refunds' total is matched to
    an exact-amount debit row (e.g. fuel-surcharge refund) — verified by reconciliation.
"""
import re
import sys
import os
from itertools import combinations
from datetime import datetime, date
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, account_check
from statement_reader.utils.pdf_utils import open_pdf

MONTHS = {m: i for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
                                      'Sep', 'Oct', 'Nov', 'Dec'], 1)}
AMT_RE = re.compile(r'^-?[\d,]+\.\d{2}$')
CREDIT_CATEGORIES = {'repayments', 'refunds', 'refund', 'cashback'}
COL = {'merchant': (78, 235), 'category': (235, 325), 'type': (325, 400),
       'location': (400, 485), 'reward': (485, 560), 'amount': (560, 9999)}


def _n(s) -> float:
    try:
        return round(float(str(s).replace(',', '')), 2)
    except (ValueError, TypeError):
        return 0.0


def _full_date(s):
    for fmt in ('%d %b %Y', '%d %b %y'):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


class SIBParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'sib one' in t or 'south indian bank' in t or 'sib credit card' in t

    # ------------------------------------------------------------------
    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='South Indian Bank', statement_type='credit_card',
                             source_file=Path(filepath).name, card_name='SIB One Credit Card')
        with open_pdf(filepath, password) as pdf:
            pg1 = pdf.pages[0].extract_text() or ''
            data.raw_text = pg1
            summ = self._header(pg1, data)
            blocks = self._blocks(pdf.pages)

        end = datetime.strptime(data.to_date, '%Y-%m-%d').date() if data.to_date else date.today()
        txns = []
        for b in blocks:
            day, mon = b['date']
            yr = end.year
            d = date(yr, MONTHS[mon], day)
            if d > end and (d - end).days > 20:           # Dec txn on a Jan statement
                d = date(yr - 1, MONTHS[mon], day)
            iso = d.isoformat()
            cat = b['category']
            credit = cat.lower() in CREDIT_CATEGORIES or (b['reward'] is not None and b['reward'] < 0)
            desc = b['merchant'] + (f" ({b['location']})" if b['location'] else '')
            # printed amount already includes forex fee + GST → split them apart
            base = round(b['amount'] - b['fee'], 2) if 0 < b['fee'] < b['amount'] else b['amount']
            txns.append(Transaction(date=iso, description=desc, amount=base,
                                    txn_type='credit' if credit else 'debit',
                                    category=('Refund' if credit and cat.lower() not in CREDIT_CATEGORIES else cat),
                                    reference=b['type'], cardholder=b['holder'],
                                    reward_pts=b['reward'] or 0))
            if b['fee'] > 0:
                txns.append(Transaction(date=iso, description=f"Forex fee + GST on {b['merchant']}",
                                        amount=round(b['fee'], 2), txn_type='debit',
                                        category='Fees & Taxes', cardholder=b['holder']))
        self._resolve_unmarked_refunds(txns, summ)
        data.transactions = txns

        stated_cr = summ.get('repayments')
        stated_dr = None
        if 'spends' in summ:
            stated_dr = round(summ['spends'] + summ.get('interest', 0) + summ.get('fees', 0), 2)
        # New EMI / paid-via-points reduce the due without being transactions here
        adj = round(summ.get('new_emi', 0) + summ.get('points', 0), 2)
        row = account_check(data.card_number, 'Credit card', data.opening_balance,
                            round(data.total_due + adj, 2), txns, is_loan=True,
                            stated_credits=stated_cr, stated_debits=stated_dr,
                            period=f'{data.from_date} to {data.to_date}')
        data.accounts.append(row)
        return data

    # ------------------------------------------------------------------
    @staticmethod
    def _header(t: str, data: StatementData) -> dict:
        m = re.search(r'Statement\s*\((\d{1,2} \w{3} \d{4})\s*-\s*(\d{1,2} \w{3} \d{4})\)', t)
        if m:
            data.from_date = _full_date(m.group(1)).isoformat()
            data.to_date = _full_date(m.group(2)).isoformat()
            data.statement_date = data.to_date
        m = re.search(r'Statement Date[^\n]*\n(?:[^\n]*\n)?\s*(\d{1,2} \w{3} \d{4})', t)
        if m and _full_date(m.group(1)):
            data.statement_date = _full_date(m.group(1)).isoformat()
        m = re.search(r'Payment\s+Due\s+Date\s*\n\s*(\d{1,2}\s+\w{3}\s+\d{4})', t)
        if m:
            data.due_date = _full_date(m.group(1)).isoformat()
        cn = re.search(r'(\d{4}-\d{2}[Xx*]{2}-[Xx*]{4}-\d{4})', t)
        if cn:
            data.card_number = cn.group(1)

        A = r'([\d,]+\.\d{2})'
        grab = lambda pat: _n(re.search(pat, t).group(1)) if re.search(pat, t) else None
        summ = {
            'opening': grab(A + r'\s*\n\s*Full Name Opening Balance'),
            'spends': grab(A + r'\s*\n\s*Spends \+'),
            'interest': grab(r'Interest Charges \+\s*' + A),
            'fees': grab(r'Fees & Charges \+\s*' + A),
            'repayments': grab(A + r'\s*\n\s*Repayments & Refunds'),
            'new_emi': grab(A + r'\s*\n\s*New EMI'),
            'points': grab(A + r'\s*\n\s*Paid via points'),
        }
        totals = [_n(x) for x in re.findall(r'Total Amount Due\s+' + A, t)]
        if totals:
            summ['total'] = totals[-1]          # label appears twice; the last one is the real due
        summ = {k: v for k, v in summ.items() if v is not None}
        data.opening_balance = summ.get('opening', 0.0)
        data.total_due = summ.get('total', 0.0)
        data.closing_balance = data.total_due
        m = re.search(r'Minimum Amount Due\s+' + A, t)
        if m:
            data.minimum_due = _n(m.group(1))
        if 'Credit Limit' in t:
            m = re.search(r'Paid via points -\s*\n\s*' + A, t)
            if m:
                data.credit_limit = _n(m.group(1))
        return summ

    # ------------------------------------------------------------------
    def _blocks(self, pages) -> list:
        out, holder, orphan = [], 'Primary', None
        started = False
        for pg in pages:
            words = pg.extract_words(extra_attrs=['size'])
            text = pg.extract_text() or ''
            stop_y = None
            if 'IMPORTANT INFORMATION' in text:
                hit = [w for w in words if w['text'] == 'IMPORTANT']
                stop_y = hit[0]['top'] if hit else 0
            start_y = 0
            if not started:
                hit = [w for w in words if w['text'] == 'HISTORY']
                th = [w for w in words if w['text'] == 'Transactions']
                if hit:
                    start_y, started = hit[0]['top'], True
                elif th:
                    start_y, started = th[0]['top'] - 5, True
                else:
                    continue
            words = [w for w in words if w['top'] >= start_y and (stop_y is None or w['top'] < stop_y)]
            if not words:
                if stop_y is not None:
                    break
                continue

            # section titles
            sections = []
            rows = {}
            for w in words:
                rows.setdefault(round(w['top']), []).append(w)
            for y, ws in sorted(rows.items()):
                line = ' '.join(x['text'] for x in sorted(ws, key=lambda x: x['x0']))
                m = re.match(r"^(?:(Your)|(.+?)'s) Transactions$", line)
                if m:
                    sections.append((y, 'Primary' if m.group(1) else m.group(2).strip()))

            # anchors: 'DD Mon' at the left edge
            anchors = []
            for w in words:
                if w['x0'] < 60 and re.fullmatch(r'\d{1,2}', w['text']):
                    nxt = [v for v in words if abs(v['top'] - w['top']) < 2 and 50 < v['x0'] < 80
                           and v['text'] in MONTHS]
                    if nxt:
                        anchors.append((w['top'], int(w['text']), nxt[0]['text']))
            anchors.sort()

            # Drop table-header rows and section titles (there can be several per page)
            HDR = {'Merchant', 'Points', 'Reward', '(Rs.)', 'HISTORY'}
            skip_rows = {y for y, ws in rows.items() if HDR & {x['text'] for x in ws}}
            skip_rows |= {y for y, _ in sections}
            skip_rows |= {y for y, ws in rows.items()
                          if ' '.join(x['text'] for x in sorted(ws, key=lambda x: x['x0'])) == 'Type Points'}
            near_skip = lambda w: any(abs(round(w['top']) - y) <= 1 for y in skip_rows)

            blocks = {a: [] for a in anchors}
            tail = []
            for w in words:
                if w['x0'] < 78 or near_skip(w):
                    continue
                if not anchors:
                    tail.append(w)
                    continue
                a = min(anchors, key=lambda a: abs(a[0] - w['top']))
                if abs(a[0] - w['top']) <= 22:
                    blocks[a].append(w)
                elif w['top'] > anchors[-1][0]:
                    tail.append(w)

            for i, a in enumerate(anchors):
                for y, h in sections:
                    if y < a[0]:
                        holder = h
                ws = blocks[a]
                if i == 0 and orphan:
                    # rows stranded at the foot of the previous page come first
                    ws = [dict(w, top=w['top'] - 10000) for w in orphan] + ws
                    orphan = None
                b = self._decode(ws)
                if b['amount'] <= 0:
                    continue
                b.update(date=(a[1], a[2]), holder=holder)
                out.append(b)
            # words below the last row of a page (merchant name, amount, forex fee)
            # belong to the first row on the next page
            orphan = tail or None
            for y, h in sections:          # carry section into next page
                if not anchors or y > anchors[-1][0]:
                    holder = h
            if stop_y is not None:
                break
        return out

    @staticmethod
    def _decode(ws) -> dict:
        def col(name, items):
            lo, hi = COL[name]
            return [w for w in items if lo <= w['x0'] < hi]

        rows = {}
        for w in ws:
            rows.setdefault(round(w['top']), []).append(w)
        merchant, fee = [], 0.0
        amount, reward = 0.0, None
        cat, typ, loc = [], [], []
        for y in sorted(rows):
            r = sorted(rows[y], key=lambda w: w['x0'])
            mtxt = ' '.join(w['text'] for w in col('merchant', r))
            fm = re.match(r'^(?:Forex Fee|GST @ [\d.]+%)\s*=\s*([\d.]+)', mtxt)
            if fm:
                fee += _n(fm.group(1))
            elif mtxt:
                merchant.append(mtxt)
            cat += [w['text'] for w in col('category', r)]
            typ += [w['text'] for w in col('type', r)]
            loc += [w['text'] for w in col('location', r)]
            for w in col('reward', r):
                if AMT_RE.match(w['text']):
                    reward = _n(w['text'])
            amt_words = [w['text'] for w in col('amount', r)]
            if 'null' in amt_words:
                continue                      # 'null 21.00' — informational, not the amount
            for a in amt_words:
                if AMT_RE.match(a) and amount == 0.0:
                    amount = abs(_n(a))
        return {'merchant': ' '.join(merchant).strip(), 'category': ' '.join(cat).strip(),
                'type': ' '.join(typ).strip(), 'location': ' '.join(loc).strip(),
                'reward': reward, 'amount': amount, 'fee': round(fee, 2)}

    @staticmethod
    def _resolve_unmarked_refunds(txns, summ):
        """Some refunds (e.g. fuel surcharge) carry no marker. Use the printed
        'Repayments & Refunds' total to find them: an exact-amount debit (or pair)."""
        target = summ.get('repayments')
        if target is None:
            return
        gap = round(target - sum(t.amount for t in txns if t.txn_type == 'credit'), 2)
        if gap <= 0.009:
            return
        cands = [t for t in txns if t.txn_type == 'debit' and t.category != 'Fees & Taxes'
                 and not t.reward_pts and t.amount <= gap + 0.01]
        # Fuel-surcharge refunds: 'Fuel' rows printed without a city
        fuel = [t for t in cands if t.category == 'Fuel' and '(' not in t.description]
        if fuel and abs(sum(t.amount for t in fuel) - gap) < 0.01:
            for t in fuel:
                t.txn_type, t.category = 'credit', 'Refund (fuel surcharge)'
            return
        cands.sort(key=lambda t: (t.category != 'Fuel', t.amount))
        cands = cands[:40]
        for k in (1, 2, 3, 4):
            for combo in combinations(cands, k):
                if abs(sum(t.amount for t in combo) - gap) < 0.01:
                    for t in combo:
                        t.txn_type = 'credit'
                        t.category = 'Refund (surcharge/reversal)'
                    return
