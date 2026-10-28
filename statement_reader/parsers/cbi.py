"""Central Bank of India — savings / current account statement (internet-banking PDF).

Header : 'Account Number: 1234567890', 'Product Type: HSS-GEN-PUB-IND-RURAL-INR',
         'Cleared Balance: 1345.370', 'STATEMENT OF ACCOUNT from 01/04/2026 to 01/10/2026'
Table  : Post Date | Value Date | Branch Code | Cheque Number | Transaction Description |
         Debit | Credit | Balance ('5,038.94 CR')
No opening balance is printed: it is rebuilt from the first row, and every following row
must continue the running balance (row-by-row check).
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, account_check
from statement_reader.utils.pdf_utils import open_pdf


def _d(s):
    try:
        return datetime.strptime(s.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')
    except ValueError:
        return s.strip()


def _n(s):
    s = str(s or '').replace(',', '').strip()
    neg = s.upper().endswith('DR')
    s = re.sub(r'[^\d.]', '', s)
    try:
        v = round(float(s), 2) if s else 0.0
    except ValueError:
        v = 0.0
    return -v if neg else v


def _cat(desc, credit):
    u = desc.upper()
    if 'INTEREST' in u and credit:
        return 'Interest'
    if 'SMS' in u or 'CHARGES' in u or 'GST' in u or 'ISSUANCE' in u:
        return 'Bank charges (reversal)' if credit else 'Bank charges'
    if 'PMSBY' in u or 'PMJJBY' in u or 'APY' in u:
        return 'Insurance / pension scheme'
    if 'NEFT' in u or 'IMPS' in u or 'RTGS' in u:
        return 'Transfer'
    if u.startswith('UPI'):
        return 'UPI'
    if 'ATM' in u or 'CASH' in u:
        return 'Cash withdrawal'
    return ''


class CBIParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return 'Central Bank of India' in text

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='Central Bank of India', statement_type='savings',
                             source_file=Path(filepath).name)
        rows, texts = [], []
        with open_pdf(filepath, password) as pdf:
            for pg in pdf.pages:
                texts.append(pg.extract_text() or '')
                for tb in pg.extract_tables():
                    rows.extend(tb)
        t = '\n'.join(texts)
        data.raw_text = texts[0] if texts else ''
        g = lambda pat: (re.search(pat, t).group(1).strip() if re.search(pat, t) else '')
        data.account_number = g(r'Account Number:\s*(\d+)')
        product = g(r'Product Type:\s*(\S+)')
        kind = 'Current' if product.upper().startswith(('CA', 'CUR')) else 'Savings'
        data.statement_type = kind.lower()
        data.card_name = f'Central Bank {kind} A/c {data.account_number[-4:]}'
        m = re.search(r'from (\d{2}/\d{2}/\d{4}) to (\d{2}/\d{2}/\d{4})', t)
        if m:
            data.from_date, data.to_date = _d(m.group(1)), _d(m.group(2))
        m = re.search(r'Statement Date\s*:\s*\w{3} (\w{3}) (\d{1,2}) [\d:]+ \w+ (\d{4})', t)
        if m:
            data.statement_date = datetime.strptime(f'{m.group(2)} {m.group(1)} {m.group(3)}', '%d %b %Y').strftime('%Y-%m-%d')
        cleared = _n(g(r'Cleared Balance:\s*([\d,.]+)'))

        txns = []
        for r in rows:
            cells = [str(c or '').strip() for c in r]
            if len(cells) < 8 or not re.match(r'^\d{2}/\d{2}/\d{4}$', cells[0]):
                continue
            debit, credit, bal = _n(cells[-3]), _n(cells[-2]), _n(cells[-1])
            if debit <= 0 and credit <= 0:
                continue
            narr = re.sub(r'\s*\n\s*', ' ', cells[4]).strip()
            is_cr = credit > 0
            tx = Transaction(date=_d(cells[0]), description=narr, amount=credit if is_cr else debit,
                             txn_type='credit' if is_cr else 'debit', category=_cat(narr, is_cr),
                             reference=cells[3], cardholder=f'{kind} {data.account_number[-4:]}',
                             narration=narr)
            tx._balance = bal
            txns.append(tx)
        data.transactions = txns

        if txns:
            f = txns[0]
            opening = round(f._balance - (f.amount if f.txn_type == 'credit' else -f.amount), 2)
            closing = txns[-1]._balance
            breaks, bal = 0, opening
            for x in txns:
                bal = round(bal + (x.amount if x.txn_type == 'credit' else -x.amount), 2)
                if abs(bal - x._balance) > 0.01:
                    breaks += 1
                    bal = x._balance
            data.opening_balance, data.closing_balance = opening, closing
            row = account_check(data.account_number, kind, opening, closing, txns,
                                period=f'{data.from_date} to {data.to_date}',
                                **{'Product': product})
            if breaks:
                row['Check'] = f'MISMATCH ({breaks} balance breaks)'
            elif cleared and abs(cleared - closing) > 0.01:
                row['Check'] = f'MISMATCH (cleared balance {cleared:,.2f})'
            data.accounts.append(row)
        return data
