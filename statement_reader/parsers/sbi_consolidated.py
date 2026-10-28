"""SBI consolidated account statement (all accounts of one customer in one PDF).

Downloaded from SBI internet banking: file name is the CIF + date, e.g. <CIF><DDMMYYYY>.pdf.
Page 1 : MY ACCOUNTS — deposit and loan totals (no 'State Bank of India' text; logo only)
Page 2 : SAVINGS ACCOUNTS table (holding, mode, account, status, balances)
Page 3 : LOAN / OD ACCOUNTS table + LOAN ACCOUNTS ADDITIONAL DETAILS (EMI, recovered, term)
Page 4+: one TRANSACTION DETAILS section per account:
         'TRANSACTION DETAILS' / 'SAVING ACCOUNT' / 'XXXXXXX1234'
         table: Date | Transaction Reference | Ref.No./Chq.No. | Credit | Debit | Balance
         'Opening Balance on 01-09-26: n'  …  'Your Closing Balance on 30-09-26: n'
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry
from statement_reader.utils.pdf_utils import open_pdf

DATE = re.compile(r'^\d{2}-\d{2}-\d{2}$')
NUM = r'-?[\d,]+(?:\.\d+)?'
ACCT_HDR = re.compile(r'TRANSACTION DETAILS\s*\n\s*([A-Z/ ]*ACCOUNT)\s*\n\s*(X+\d{4})')
TYPE_LABEL = {'SAVING ACCOUNT': 'Savings', 'CURRENT ACCOUNT': 'Current',
              'DL/TL ACCOUNT': 'Loan', 'OD ACCOUNT': 'Overdraft', 'CC ACCOUNT': 'Cash Credit'}


def _d(s: str) -> str:
    for fmt in ('%d-%m-%y', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s.strip()


def _n(s) -> float:
    try:
        return round(float(str(s).replace(',', '').strip()), 2)
    except (ValueError, TypeError):
        return 0.0


def _category(desc: str, acct_type: str, is_credit: bool) -> str:
    u = desc.upper()
    if acct_type == 'Loan':
        return 'Loan interest' if 'INTEREST' in u else ('EMI payment' if is_credit else 'Loan debit')
    if 'INTEREST CREDIT' in u:
        return 'Interest'
    if re.search(r'\bDIV|DIVIDEND|FIN\.DIV|FINL DIV', u):
        return 'Dividend'
    if 'ATM CASH' in u:
        return 'Cash withdrawal'
    if re.search(r'CHARGE|COMMISSION|^SERVICE$|MCC ISSUE|SMS CHG', u):
        return 'Bank charges'
    if 'DIRECT DR' in u:
        return 'EMI / loan transfer'
    if u.startswith('UPI'):
        return 'UPI'
    if 'NEFT' in u or 'IMPS' in u or 'RTGS' in u or u.startswith('INB'):
        return 'Transfer'
    if 'BILL PAYMENT' in u or 'BILL_' in u:
        return 'Bill payment'
    if 'DEPOSIT OR INVESTMENT' in u or 'LOAN REPAYMENT' in u:
        return 'Own-account transfer'
    if 'USD' in u or 'EUR' in u or 'GBP' in u:
        return 'Forex'
    return ''


class SBIConsolidatedParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'my home branch information' in t or ('my accounts' in t and 'sbi.co.in' in t)

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='State Bank of India', card_name='SBI Consolidated Statement',
                             statement_type='consolidated', source_file=Path(filepath).name)
        with open_pdf(filepath, password) as pdf:
            pages = [(pg.extract_text() or '', pg) for pg in pdf.pages]
            texts = [t for t, _ in pages]
            full = '\n'.join(texts)
            data.raw_text = texts[0] if texts else ''

            self._summary(full, data)
            savings = self._savings_table(full)
            loans = self._loan_tables(full)

            # Walk pages, remembering the current account across continuation pages
            accounts, order, current = {}, [], None
            for text, pg in pages:
                h = ACCT_HDR.search(text)
                if h:
                    acct = h.group(2)
                    atype = TYPE_LABEL.get(h.group(1).strip(), h.group(1).title())
                    current = acct
                    if acct not in accounts:
                        accounts[acct] = {'type': atype, 'txns': [], 'opening': None, 'closing': None,
                                          'from': '', 'to': ''}
                        order.append(acct)
                if current is None:
                    continue
                a = accounts[current]
                m = re.search(rf'Opening\s*\S*\s*Balance on (\d{{2}}-\d{{2}}-\d{{2}}):\s*({NUM})|'
                              rf'on (\d{{2}}-\d{{2}}-\d{{2}}):\s*({NUM})\s+null', text.replace('nBualllance', 'Balance'))
                if m and a['opening'] is None:
                    a['from'] = _d(m.group(1) or m.group(3))
                    a['opening'] = _n(m.group(2) or m.group(4))
                m = re.search(rf'Closing Balance on (\d{{2}}-\d{{2}}-\d{{2}}):\s*({NUM})', text)
                if m:
                    a['to'], a['closing'] = _d(m.group(1)), _n(m.group(2))
                for table in pg.extract_tables():
                    for row in table:
                        t = self._row(row, a['type'], current)
                        if t:
                            a['txns'].append(t)

        # Build output
        for acct in order:
            a = accounts[acct]
            data.transactions.extend(a['txns'])
            cr = round(sum(t.amount for t in a['txns'] if t.txn_type == 'credit'), 2)
            dr = round(sum(t.amount for t in a['txns'] if t.txn_type == 'debit'), 2)
            op, cl = a['opening'] or 0.0, a['closing'] or 0.0
            # savings: balance = opening + credit - debit ; loans: outstanding = opening - credit + debit
            expected = round(op - cr + dr, 2) if a['type'] == 'Loan' else round(op + cr - dr, 2)
            extra = savings.get(acct, {}) if a['type'] != 'Loan' else loans.get(acct, {})
            data.accounts.append({
                'Account': acct, 'Type': a['type'],
                'Holding': extra.get('holding', ''), 'Mode': extra.get('mode', ''),
                'Period': f"{a['from']} to {a['to']}",
                'Opening': op, 'Credits': cr, 'Debits': dr, 'Closing': cl,
                'Transactions': len(a['txns']),
                'Check': 'OK' if abs(expected - cl) < 0.02 else f'MISMATCH (calc {expected:,.2f})',
            })
            if a['from'] and (not data.from_date or a['from'] < data.from_date):
                data.from_date = a['from']
            if a['to'] and a['to'] > (data.to_date or ''):
                data.to_date = a['to']

        # EMIs: one per loan account
        for acct, ln in loans.items():
            interest_now = sum(t.amount for t in accounts.get(acct, {}).get('txns', [])
                               if t.category == 'Loan interest')
            data.emis.append(EMIEntry(
                description=(f"SBI Loan {acct} @ {ln['roi']}% — sanctioned ₹{ln['sanctioned']:,.0f} "
                             f"on {ln['sanc_date']}"),
                principal=abs(ln['outstanding']),
                interest=round(interest_now, 2),
                emi_amount=ln.get('emi', 0.0),
                tenure_months=ln.get('term', 0),
                months_remaining=ln['residual_months'],
                start_date=_d(ln['sanc_date']),
                end_date='',
                ref=acct, lender='State Bank of India', original_amount=ln['sanctioned'],
                outstanding=abs(ln['outstanding']), rate_pa=float(ln['roi'] or 0),
            ))
        if not data.statement_date:
            data.statement_date = data.to_date
        return data

    # ------------------------------------------------------------------
    @staticmethod
    def _row(row, acct_type, acct):
        if not row or not row[0] or not DATE.match(str(row[0]).strip()):
            return None
        cells = [str(c).replace('\n', ' ').strip() if c is not None else '' for c in row]
        if len(cells) < 5:
            return None
        credit, debit, balance = _n(cells[-3]), _n(cells[-2]), cells[-1]
        ref = cells[-4] if cells[-4] not in ('-', 'null') else ''
        desc = ' '.join(c for c in cells[1:-4] if c).strip()
        desc = re.sub(r'\s+', ' ', desc)
        if credit <= 0 and debit <= 0:
            return None
        is_credit = credit > 0
        label = f'{acct_type} {acct[-4:]}'
        return Transaction(date=_d(cells[0]), description=desc, amount=credit if is_credit else debit,
                           txn_type='credit' if is_credit else 'debit',
                           category=_category(desc, acct_type, is_credit),
                           reference=ref, cardholder=label)

    @staticmethod
    def _summary(t: str, data: StatementData):
        m = re.search(r'Customer\s+(X+\d+)', t)
        if m:
            data.account_number = m.group(1)
        m = re.search(r'As on (\d{2}-\d{2}-\d{2})', t)
        if m:
            data.statement_date = _d(m.group(1))
        m = re.search(rf'MY ACCOUNTS[\s\S]*?Total INR:\s*Rs\.\s*({NUM})', t)
        if m:
            data.closing_balance = _n(m.group(1))          # total deposit balance
        m = re.search(rf'LOAN ACCOUNTS\s*\n[\s\S]*?Total INR:\s*Rs\.\s*({NUM})', t)
        if m:
            data.total_due = abs(_n(m.group(1)))           # total loan outstanding

    @staticmethod
    def _savings_table(t: str) -> dict:
        out = {}
        for m in re.finditer(rf'^(P|S)\s+(.+?)\s+(X+\d{{4}})\s+(\w+)\s+INR\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})',
                             t, re.M):
            out[m.group(3)] = {'holding': 'Primary' if m.group(1) == 'P' else 'Secondary',
                               'mode': m.group(2).title(), 'status': m.group(4),
                               'available': _n(m.group(8))}
        return out

    @staticmethod
    def _loan_tables(t: str) -> dict:
        out = {}
        # '08 Years 01' / 'DL/TL ACCOUNT XXXXXXX5678 INR 01-01-20 1000000.00 800000.00 Months 00 8.20 0.0000 -500000.00 0.00'
        pat = re.compile(
            rf'(?:(\d{{1,2}}) Years (\d{{1,2}})\s*\n)?[A-Z/ ]*ACCOUNT (X+\d{{4}}) INR (\d{{2}}-\d{{2}}-\d{{2}}) '
            rf'({NUM}) ({NUM}) Months \d{{1,2}} ({NUM}) ({NUM}) ({NUM}) ({NUM})')
        for m in pat.finditer(t):
            yrs, mons = int(m.group(1) or 0), int(m.group(2) or 0)
            out[m.group(3)] = {'sanc_date': m.group(4), 'sanctioned': _n(m.group(5)),
                               'drawing_power': _n(m.group(6)), 'roi': m.group(7),
                               'outstanding': _n(m.group(9)), 'arrear': _n(m.group(10)),
                               'residual_months': yrs * 12 + mons}
        # 'XXXXXXX5678 10000.00 300000.00 200000.000 120'  (EMI, interest recovered, principal recovered, term)
        add = re.search(r'LOAN ACCOUNTS ADDITIONAL DETAILS([\s\S]*?)(?:Visithttps|\Z)', t)
        if add:
            for m in re.finditer(rf'^(X+\d{{4}})\s+({NUM})\s+({NUM})\s+({NUM})\s+(\d+)\s*$', add.group(1), re.M):
                if m.group(1) in out:
                    out[m.group(1)].update({'emi': _n(m.group(2)), 'interest_recovered': _n(m.group(3)),
                                            'principal_recovered': _n(m.group(4)), 'term': int(m.group(5))})
        return out
