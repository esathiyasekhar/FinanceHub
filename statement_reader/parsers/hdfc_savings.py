"""HDFC Bank savings / current account statement (net-banking PDF).

File name: <branch><XXXXXX><last4>_<id>_<DDMonYYYY>_TO_<DDMonYYYY>_<n>.pdf  e.g. 2014XXXXXX1234_…
Page header : Account number, Cust ID, JOINT HOLDERS, 'Statement From : 25/08/26 TO : 24/09/26'
Table       : Date | Narration | Chq./Ref No. | Value Date | Withdrawal Amount | Deposit Amount | Closing Balance
              (narration wraps inside the cell at ~40 characters)
Last page   : STATEMENT SUMMARY — Opening Balance, Dr Count, Cr Count, Debits, Credits, Closing Balance
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, account_check
from statement_reader.utils.pdf_utils import open_pdf

AMT = r'[\d,]+\.\d{2}'


def _d(s):
    for fmt in ('%d/%m/%Y', '%d/%m/%y', '%d-%b-%y', '%d %b %Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s.strip()


def _n(s):
    try:
        return round(float(str(s).replace(',', '').strip() or 0), 2)
    except ValueError:
        return 0.0


def join_wrapped(cell: str, width: int = 38) -> str:
    """Narration cells hard-wrap at a fixed width: glue full-width lines without a space."""
    lines = [l for l in str(cell).split('\n')]
    out = ''
    for i, l in enumerate(lines):
        if i == 0:
            out = l
        elif len(lines[i - 1]) >= width:
            out += l
        else:
            out += ' ' + l
    return out.strip()


def friendly(narr: str) -> str:
    """'UPI-A KUMAR-98765…@PTYES-…' → 'UPI · A KUMAR'."""
    m = re.match(r'^UPI-([^-@]+?)-', narr)
    if m:
        return f'UPI · {m.group(1).strip()}'
    m = re.match(r'^(IMPS|NEFT|RTGS)[- ](?:\w*\d\w*-)?([A-Z][A-Z .&]+?)-', narr)
    if m:
        return f'{m.group(1)} · {m.group(2).strip()}'
    return narr


def category(narr: str, credit: bool) -> str:
    u = narr.upper()
    if 'BILLPAY' in u and re.search(r'\d{6}X+\d{4}', u):
        return 'Credit card payment'
    if re.search(r'ANNUAL FEE|CHARGES|CHGS|GST|FEE-', u):
        return 'Bank charges'
    if 'INTEREST' in u or u.startswith('INT.PD') or 'CREDIT INTEREST' in u:
        return 'Interest'
    if 'ATW' in u or 'NWD' in u or 'ATM' in u:
        return 'Cash withdrawal'
    if 'ACH D' in u or 'NACH' in u or 'EMI' in u:
        return 'EMI / auto-debit'
    if 'SALARY' in u:
        return 'Salary'
    if 'DIV' in u and credit:
        return 'Dividend'
    if u.startswith('UPI'):
        return 'UPI'
    if u.startswith(('IMPS', 'NEFT', 'RTGS')):
        return 'Transfer'
    if u.startswith('POS') or 'DEBIT CARD' in u:
        return 'Card purchase'
    return ''


class HDFCSavingsParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return 'Statement From' in text and 'Withdrawal Amount' in text

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='HDFC Bank', statement_type='savings',
                             source_file=Path(filepath).name)
        txns = []
        with open_pdf(filepath, password) as pdf:
            texts = []
            for pg in pdf.pages:
                texts.append(pg.extract_text() or '')
                for table in pg.extract_tables():
                    for row in table:
                        t = self._row(row)
                        if t:
                            txns.append(t)
        full = '\n'.join(texts)
        data.raw_text = texts[0] if texts else ''
        data.transactions = txns

        g = lambda pat, grp=1: (re.search(pat, full).group(grp) if re.search(pat, full) else '')
        data.account_number = g(r'Account number\s*:\s*(\d+)')
        acct_kind = 'Current' if re.search(r'CURRENT ACCOUNT|\bCA\b-', full) else 'Savings'
        data.statement_type = acct_kind.lower()
        data.card_name = f'HDFC {acct_kind} A/c {data.account_number[-4:]}' if data.account_number else f'HDFC {acct_kind} Account'
        data.card_number = g(r'Cust ID\s*:\s*(\d+)')
        m = re.search(r'Statement From\s*:\s*(\d{2}/\d{2}/\d{2,4})\s*TO\s*:\s*(\d{2}/\d{2}/\d{2,4})', full)
        if m:
            data.from_date, data.to_date = _d(m.group(1)), _d(m.group(2))
            data.statement_date = data.to_date

        m = re.search(rf'STATEMENT SUMMARY[\s\S]*?Closing Balance\s*\n\s*(-?{AMT})\s+(\d+)\s+(\d+)\s+({AMT})\s+({AMT})\s+(-?{AMT})', full)
        stated_cr = stated_dr = None
        if m:
            data.opening_balance, data.closing_balance = _n(m.group(1)), _n(m.group(6))
            stated_dr, stated_cr = _n(m.group(4)), _n(m.group(5))
        label = f'{acct_kind} {data.account_number[-4:]}'
        for t in txns:
            t.cardholder = label

        joint = g(r'JOINT HOLDERS:\s*(.+?)\s+Account number')
        data.accounts.append(account_check(
            data.account_number, acct_kind, data.opening_balance, data.closing_balance, txns,
            stated_credits=stated_cr, stated_debits=stated_dr,
            period=f'{data.from_date} to {data.to_date}', **{'Joint holder': joint}))
        return data

    @staticmethod
    def _row(row):
        if not row or len(row) < 7 or not row[0]:
            return None
        date = str(row[0]).strip()
        if not re.match(r'^\d{2}/\d{2}/\d{2,4}$', date):
            return None
        narr = join_wrapped(row[1] or '')
        wd, dep = _n(row[4]), _n(row[5])
        if wd <= 0 and dep <= 0:
            return None
        credit = dep > 0
        return Transaction(date=_d(date), description=friendly(narr), amount=dep if credit else wd,
                           txn_type='credit' if credit else 'debit', category=category(narr, credit),
                           reference=str(row[2] or '').strip(), narration=narr)
