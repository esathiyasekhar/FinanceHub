"""Standard Chartered credit card statement parser (India, 2026 format).

Page 1 layout:
  Header  : 'Statement Date : 16 Oct 2026', 'Payment Due Date : 07 Nov 2026',
            'Total Payment Due (INR) : 16,367.65', 'Credit Limit (INR) : 221,500.00 ...'
  Per card: '<Card Name> 400000XXXXXX1234' followed by rows
            'DDMMYY  description  [ref]  rewards  [type]  amount [CR]'
  Rewards : 'REWARDS POINTS SUMMARY' - one row per card
Note: the bank name is only in the logo image, so page-1 text never says
'Standard Chartered' - detection also relies on filename / sc.bank.in / layout.
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry, RewardPoint, account_check
from statement_reader.utils.pdf_utils import extract_text_all_pages, ocr_pages, is_vectorized_pdf

AMT = r'[\d,]+\.\d{2}'
MON = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
CARD_HDR = re.compile(r'^([A-Za-z][A-Za-z &]+?)\s+(\d{6}X{6}\d{4})$')
TXN_START = re.compile(rf'^(\d{{6}}|\d{{2}}/\d{{2}}/\d{{2,4}}|\d{{1,2}} {MON} \d{{2,4}})\s+(.+)$')
AMT_END = re.compile(rf'^(.*?)\s*(-?{AMT}|-?\d+\.\d{{2}})(\s*(?:CR|Cr|C))?$')


def _date(s: str) -> str:
    s = s.strip()
    for fmt in ('%d%m%y', '%d/%m/%Y', '%d/%m/%y', '%d %b %Y', '%d %b %y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _amt(s) -> float:
    try:
        return round(float(re.sub(r'[^\d.]', '', str(s))), 2)
    except (ValueError, TypeError):
        return 0.0


def _num(s) -> float:
    try:
        return float(str(s).replace(',', ''))
    except ValueError:
        return 0.0


class StanChartParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'standard chartered' in t or 'stanchart' in t or 'sc.bank.in' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='Standard Chartered Bank', statement_type='credit_card',
                             source_file=Path(filepath).name)

        if is_vectorized_pdf(filepath, password):
            pages = ocr_pages(filepath, password, pages=[1, 2])
        else:
            pages = extract_text_all_pages(filepath, password, max_pages=3)
        # Statement content is on the pages before the MITC
        stmt_pages = []
        for p in pages:
            if 'Most Important Terms' in p:
                break
            stmt_pages.append(p)
        full = '\n'.join(stmt_pages or pages[:1])
        data.raw_text = full

        self._header(full, data)
        data.transactions = self._transactions(full, data)
        self._rewards(full, data)
        self._emis(full, data)
        if data.closing_balance:
            data.accounts.append(account_check(
                data.account_number, 'Credit card', data.opening_balance, data.closing_balance,
                data.transactions, is_loan=True, period=f'{data.from_date} to {data.to_date}'))
        return data

    # ------------------------------------------------------------------
    def _header(self, t: str, data: StatementData):
        def grab(label, pat=AMT):
            m = re.search(label + r'\s*:\s*(' + pat + ')', t, re.I)
            return m.group(1) if m else ''

        data.account_number = grab(r'Credit Card Account Number', r'\d+')
        data.statement_date = _date(grab(r'Statement Date', rf'\d{{1,2}} {MON} \d{{4}}'))
        data.due_date = _date(grab(r'Payment Due Date', rf'\d{{1,2}} {MON} \d{{4}}'))
        data.total_due = _amt(grab(r'Total Payment Due \(INR\)'))
        data.minimum_due = _amt(grab(r'Minimum Payment Due \(INR\)'))
        data.credit_limit = _amt(grab(r'Credit Limit \(INR\)'))

        m = re.search(rf'Statement Period\s*:\s*(\d{{1,2}} {MON} \d{{4}})\s+To\s+(\d{{1,2}} {MON} \d{{4}})', t, re.I)
        if m:
            data.from_date, data.to_date = _date(m.group(1)), _date(m.group(2))

        # 'Previous Balance (INR) Payments/Credits (INR) Total Payment Due (INR)'
        # '0.17 CR 0.00 16,367.65'
        m = re.search(rf'Previous Balance \(INR\)[^\n]*\n\s*({AMT})(\s*CR)?\s+({AMT})\s+({AMT})', t)
        if m:
            data.opening_balance = -_amt(m.group(1)) if m.group(2) else _amt(m.group(1))
            data.closing_balance = _amt(m.group(4))

        cards = re.findall(CARD_HDR.pattern, t, re.M)
        if cards:
            data.card_name = f'StanChart {cards[0][0].strip()}'
            data.card_number = cards[0][1]
        else:
            data.card_name = 'Standard Chartered Credit Card'

    def _transactions(self, t: str, data: StatementData) -> list:
        txns = []
        card = ''
        in_block = False
        for raw in t.split('\n'):
            line = raw.strip()
            if not line:
                continue
            h = CARD_HDR.match(line)
            if h:
                card = f'{h.group(1).strip()} {h.group(2)[-4:]}'
                in_block = True
                continue
            if line.startswith('REWARDS POINTS SUMMARY') or line.startswith('^Total Payment Due'):
                in_block = False
                continue
            if not in_block:
                continue
            m = TXN_START.match(line)
            if not m:
                continue
            a = AMT_END.match(m.group(2))
            if not a:
                continue
            body, amount, cr = a.group(1), _amt(a.group(2)), bool(a.group(3))
            if amount <= 0:
                continue
            toks = body.split()
            # strip trailing: [type code 3 digits] [rewards int], then [long ref]
            if toks and re.fullmatch(r'\d{3}', toks[-1]) and len(toks) > 1 and re.fullmatch(r'-?\d+', toks[-2]):
                toks.pop()
            rewards = 0
            if toks and re.fullmatch(r'-?\d+', toks[-1]) and len(toks[-1]) < 8:
                rewards = int(toks.pop())
            ref = ''
            if toks and re.fullmatch(r'\d{10,}', toks[-1]):
                ref = toks.pop()
                if set(ref) == {'0'}:
                    ref = ''
            desc = ' '.join(toks).strip()
            if not desc:
                continue
            up = desc.upper()
            if 'PAYMENT' in up and ('RECEIVED' in up or 'THANK' in up):
                cat = 'Payment'
                cr = True
            elif re.search(r'GST|FEE|CHARGE|INTEREST|MARKUP', up):
                cat = 'Fees & Taxes'
            elif re.search(r'\bEMI\b|INSTAL', up):
                cat = 'EMI'
            else:
                cat = ''
            txns.append(Transaction(date=_date(m.group(1)), description=desc, amount=amount,
                                    txn_type='credit' if cr else 'debit', category=cat,
                                    reference=ref, reward_pts=rewards, cardholder=card))
        return txns

    def _rewards(self, t: str, data: StatementData):
        # '400000XXXXXX1234 Ultimate Mastercard points 13752.00 542.00 -1277.00 13017.00 0.00'
        row = re.compile(r'^(\d{6}X{6}\d{4})\s+(.+?)\s+points\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)', re.M)
        for m in row.finditer(t):
            opening, earned, adjusted, closing, expiring = (_num(m.group(i)) for i in range(3, 8))
            data.reward_details.append(RewardPoint(
                description=f'{m.group(2).strip()} ({m.group(1)[-4:]})',
                points_earned=int(earned),
                points_redeemed=int(-adjusted) if adjusted < 0 else 0,
                points_expired=int(expiring),
                balance=int(closing),
                date=data.statement_date,
            ))
            data.reward_opening += int(opening)
            data.reward_earned += int(earned)
            data.reward_redeemed += int(-adjusted) if adjusted < 0 else 0
            data.reward_closing += int(closing)
            data.reward_expired += int(expiring)

    def _emis(self, t: str, data: StatementData):
        """Best effort: 'Instalment Plan Summary' block rows ending in amounts + tenure."""
        m = re.search(r'Instalment (?:Loan|Plan)[^\n]*Summary[^\n]*\n((?:.*\n){0,15})', t, re.I)
        if not m:
            return
        for line in m.group(1).splitlines():
            r = re.search(rf'^(.+?)\s+({AMT})\s+(\d{{1,3}})\s*(?:/\s*(\d{{1,3}}))?\s+({AMT})', line.strip())
            if r:
                paid = int(r.group(3))
                total = int(r.group(4)) if r.group(4) else paid
                data.emis.append(EMIEntry(description=r.group(1).strip(), principal=_amt(r.group(2)),
                                          tenure_months=total, months_remaining=max(total - paid, 0),
                                          emi_amount=_amt(r.group(5))))
