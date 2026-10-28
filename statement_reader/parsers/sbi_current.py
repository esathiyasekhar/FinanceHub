"""State Bank of India — account statement downloaded from internet banking / YONO Business
(current or savings account, any period, e.g. a whole financial year).

Header : 'Account Name : ABC PRIVATE LIMITED', 'Account Number : 00000012345678901',
         'Account Type : Current Account', 'IFS Code : SBIN0000000',
         'Opening Balance as on 1 Apr 2026 : 1,00,000.00', 'Account Statement from 1 Apr 2026 to 26 Oct 2026'
Table  : Txn Date | Value Date | Description | Ref No./Cheque No. | Branch Code | Debit | Credit | Balance
The opening balance is printed, and every row's running balance is checked (row-by-row reconciliation).
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, account_check
from statement_reader.utils.pdf_utils import open_pdf

DATE = re.compile(r'^\d{1,2} [A-Za-z]{3} \d{4}$')


def _d(s):
    try:
        return datetime.strptime(s.strip(), '%d %b %Y').strftime('%Y-%m-%d')
    except ValueError:
        return s.strip()


def _n(s):
    s = re.sub(r'[^\d.\-]', '', str(s or ''))
    try:
        return round(float(s), 2) if s not in ('', '-', '.') else 0.0
    except ValueError:
        return 0.0


def _clean(desc):
    """'TO TRANSFER-\\nINB NEFT UTR NO:\\nSBIN2260…-\\nESSSTANCHAT' → 'NEFT SBIN2260… ESSSTANCHAT'"""
    s = re.sub(r'\s*\n\s*', ' ', desc or '').strip()
    s = re.sub(r'^(BY|TO) TRANSFER-\s*', '', s)
    s = re.sub(r'^INB\s+NEFT UTR NO:\s*', 'NEFT ', s)
    s = re.sub(r'^INB\s+', '', s)
    return re.sub(r'\s+', ' ', s).strip(' -/')


def _cat(desc, credit):
    u = desc.upper()
    if 'INTEREST' in u and credit:
        return 'Interest'
    if any(w in u for w in ('CHARGES', 'GST', 'SMS', 'AMC ', 'FEE')):
        return 'Bank charges'
    if 'SBICARD' in u or 'CREDIT CARD' in u or 'CARD PAYMENT' in u:
        return 'Card bill payment'
    if 'GST' in u or 'TAX' in u or 'CBDT' in u or 'TDS' in u:
        return 'Taxes'
    if 'NEFT' in u or 'IMPS' in u or 'RTGS' in u:
        return 'Transfer'
    if 'UPI' in u:
        return 'UPI'
    if 'CASH' in u or 'ATM' in u:
        return 'Cash'
    return ''


class SBIAccountStatementParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return 'SBIN' in text and 'Account Statement from' in text

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='State Bank of India', statement_type='current', source_file=Path(filepath).name)
        rows, texts = [], []
        with open_pdf(filepath, password) as pdf:
            for pg in pdf.pages:
                texts.append(pg.extract_text() or '')
                for tb in pg.extract_tables():
                    rows.extend(tb)
        t = '\n'.join(texts)
        data.raw_text = texts[0] if texts else ''
        g = lambda pat: (re.search(pat, t).group(1).strip() if re.search(pat, t) else '')
        data.account_number = g(r'Account Number\s*:\s*(\d+)')
        holder = g(r'Account Name\s*:\s*([^\n]+)')
        acct_type = g(r'Account Type\s*:\s*([^\n]+)') or 'Current Account'
        kind = 'Current' if 'current' in acct_type.lower() else ('Savings' if 'saving' in acct_type.lower() else acct_type.split()[0])
        data.statement_type = 'current' if kind == 'Current' else 'savings'
        data.card_name = f'SBI {kind} A/c {data.account_number[-4:]}' + (f' – {holder.title()}' if holder else '')
        m = re.search(r'Account Statement from (\d{1,2} \w{3} \d{4}) to (\d{1,2} \w{3} \d{4})', t)
        if m:
            data.from_date, data.to_date = _d(m.group(1)), _d(m.group(2))
        data.statement_date = _d(g(r'\nDate\s*:\s*(\d{1,2} \w{3} \d{4})')) or data.to_date
        opening = _n(g(r'Opening Balance as on [^:]*:\s*([\d,.\-]+)'))

        txns, bal, breaks = [], opening, 0
        for r in rows:
            cells = [str(c or '').strip() for c in r]
            if len(cells) < 8 or not DATE.match(cells[0]):
                continue
            debit, credit, new_bal = _n(cells[5]), _n(cells[6]), _n(cells[7])
            if debit <= 0 and credit <= 0:
                continue
            is_cr = credit > 0
            raw = re.sub(r'\s*\n\s*', ' ', cells[2]).strip()
            ref = re.sub(r'\s*\n\s*', ' ', cells[3]).strip()
            desc = _clean(cells[2])
            tx = Transaction(date=_d(cells[0]), description=desc, amount=credit if is_cr else debit,
                             txn_type='credit' if is_cr else 'debit', category=_cat(raw + ' ' + ref, is_cr),
                             reference=ref[:120], cardholder=f'{kind} {data.account_number[-4:]}',
                             narration=f'{raw} | {ref}'.strip(' |'))
            bal = round(bal + (credit - debit), 2)
            if abs(bal - new_bal) > 0.01:
                breaks += 1
                bal = new_bal
            txns.append(tx)
        data.transactions = txns
        closing = bal if txns else opening
        data.opening_balance, data.closing_balance = opening, closing
        row = account_check(data.account_number, kind, opening, closing, txns,
                            period=f'{data.from_date} to {data.to_date}', **{'Holder': holder.title(), 'IFSC': g(r'IFS Code\s*:\s*(\S+)')})
        if breaks:
            row['Check'] = f'MISMATCH ({breaks} balance breaks)'
        data.accounts.append(row)
        return data
