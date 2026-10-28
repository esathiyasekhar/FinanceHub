"""Bank of Baroda — combined account statement (savings + loan accounts in one PDF).

'Statement of transactions in Savings Account 2632… in INR for the period Sep 01, 2026 - Sep 30, 2026'
  DATE NARRATION CHQ.NO. WITHDRAWAL (DR) DEPOSIT (CR) BALANCE
  'dd-mm-yyyy Opening Balance 937.84 Cr' … rows … 'dd-mm-yyyy Closing Balance 1084.84 Cr'
'Statement of transactions in Loan Account 3506… …'
  LOAN DETAIL: sanctioned date, amount, EMI, tenure, ROI, last repayment date, next EMI due date
  rows with balances in 'Dr' (amount owed)
Narrations wrap: the text before and after a 'date amount balance' line belongs to it.
Debit/credit is decided from the running balance, so column alignment never matters.
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry, account_check
from statement_reader.utils.pdf_utils import open_pdf

NUM = r'\d[\d,]*\.\d{2}'
SECTION = re.compile(r'Statement of transactions in (Savings|Current|Loan|Overdraft|Cash Credit) Account (\d+)'
                     r' in INR for the period (\w{3} \d{1,2}, \d{4}) - (\w{3} \d{1,2}, \d{4})', re.I)
ROW = re.compile(rf'^(\d{{2}}-\d{{2}}-\d{{4}})\s*(.*?)\s*({NUM})\s+({NUM})\s*(Cr|Dr)$')


def _d(s):
    for fmt in ('%d-%m-%Y', '%b %d, %Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _n(s):
    return round(float(str(s).replace(',', '')), 2)


def _cat(desc, kind, credit):
    u = desc.upper()
    if kind == 'Loan':
        return 'Loan interest' if 'INT' in u else ('EMI payment' if credit else 'Loan debit')
    if 'REFUND' in u:
        return 'Refund'
    if 'INT' in u and credit:
        return 'Interest'
    if u.startswith('UPI'):
        return 'UPI'
    if u.startswith(('NEFT', 'IMPS', 'RTGS')):
        return 'Transfer'
    if 'ATM' in u:
        return 'Cash withdrawal'
    if 'CHG' in u or 'CHARGE' in u or 'GST' in u:
        return 'Bank charges'
    return ''


class BOBParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return ('bankofbaroda' in t or 'bank of baroda' in t) and 'statement of transactions in' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='Bank of Baroda', card_name='Bank of Baroda — all accounts',
                             statement_type='consolidated', source_file=Path(filepath).name)
        with open_pdf(filepath, password) as pdf:
            full = '\n'.join(pg.extract_text() or '' for pg in pdf.pages)
        data.raw_text = full[:3000]

        m = re.search(r'CUSTOMER ID\s*-\s*(\d+)', full)
        if m:
            data.account_number = m.group(1)
        m = re.search(r'Statement as on (\w{3} \d{1,2}, \d{4})', full)
        if m:
            data.statement_date = _d(m.group(1))
        m = re.search(r'TOTAL \(INR\)\s+(-?[\d.]+)\s+(-?[\d.]+)', full)
        if m:
            data.closing_balance = float(m.group(1))          # total deposits
            data.total_due = abs(float(m.group(2)))           # total loans outstanding

        heads = list(SECTION.finditer(full))
        for i, h in enumerate(heads):
            body = full[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(full)]
            kind = h.group(1).title()
            acct = h.group(2)
            is_loan = kind == 'Loan'
            data.from_date = data.from_date or _d(h.group(3))
            data.to_date = _d(h.group(4))
            txns, opening, closing = self._rows(body, kind, acct, is_loan)
            data.transactions.extend(txns)
            extra = {}
            if is_loan:
                ln = self._loan(body)
                if ln:
                    extra = {'ROI %': ln['roi'], 'EMI': ln['emi']}
                    data.emis.append(EMIEntry(
                        description=(f"BOB Loan {acct} @ {ln['roi']}% — sanctioned ₹{ln['sanctioned']:,.0f} on {ln['sanc_date']}"
                                     f", {ln['tenure']} months, next due {ln['next_due']}"),
                        principal=closing, interest=round(sum(t.amount for t in txns if t.category == 'Loan interest'), 2),
                        emi_amount=ln['emi'], tenure_months=ln['paid'] + ln['left'] or ln['tenure'],
                        months_remaining=ln['left'],
                        start_date=_d(ln['sanc_date']), end_date=_d(ln['last_date']),
                        ref=acct, lender='Bank of Baroda', original_amount=ln['sanctioned'],
                        outstanding=closing, rate_pa=float(ln['roi'] or 0)))
            data.accounts.append(account_check(acct, kind, opening, closing, txns, is_loan=is_loan,
                                               period=f'{_d(h.group(3))} to {_d(h.group(4))}', **extra))
        if not data.statement_date:
            data.statement_date = data.to_date
        return data

    @staticmethod
    def _rows(body, kind, acct, is_loan):
        lines = [l.strip() for l in body.split('\n')]
        txns, opening, closing, prev_bal = [], 0.0, 0.0, None
        label = f'{kind} {acct[-4:]}'
        used = set()
        for i, line in enumerate(lines):
            mo = re.match(rf'^\d{{2}}-\d{{2}}-\d{{4}}\s+Opening Balance\s+({NUM})\s*(Cr|Dr)', line)
            if mo:
                opening = prev_bal = _n(mo.group(1))
                continue
            mc = re.match(rf'^\d{{2}}-\d{{2}}-\d{{4}}\s+Closing Balance\s+({NUM})\s*(Cr|Dr)', line)
            if mc:
                closing = _n(mc.group(1))
                break
            m = ROW.match(line)
            if not m or prev_bal is None:
                continue
            date, desc, amt, bal = m.group(1), m.group(2), _n(m.group(3)), _n(m.group(4))
            if not desc:                       # wrapped narration: line above + line below
                above = lines[i - 1] if i > 0 and (i - 1) not in used else ''
                below = lines[i + 1] if i + 1 < len(lines) else ''
                if below and not re.match(r'^\d{2}-\d{2}-\d{4}', below) and 'Balance' not in below:
                    used.add(i + 1)
                else:
                    below = ''
                desc = f'{above} {below}'.strip()
            up = bal > prev_bal
            credit = (not up) if is_loan else up
            prev_bal = bal
            txns.append(Transaction(date=_d(date), description=re.sub(r'\s+', ' ', desc), amount=amt,
                                    txn_type='credit' if credit else 'debit',
                                    category=_cat(desc, 'Loan' if is_loan else kind, credit),
                                    cardholder=label))
        return txns, opening, closing

    @staticmethod
    def _loan(body):
        m = re.search(rf'(\d{{2}}-\d{{2}}-\d{{4}})\s+({NUM})\s+({NUM})\s+(\d+)\s*M\s+([\d.]+)\s+'
                      rf'(\d{{2}}-\d{{2}}-\d{{4}})\s+(\d{{2}}-\d{{2}}-\d{{4}})', body)
        if not m:
            return None
        k = re.search(r'No\. of EMI left\s*\n\s*([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)', body)
        return {'sanc_date': m.group(1), 'sanctioned': _n(m.group(2)), 'emi': _n(m.group(3)),
                'tenure': int(m.group(4)), 'roi': m.group(5), 'last_date': m.group(6),
                'next_due': m.group(7), 'left': int(k.group(4)) if k else 0,
                'paid': int(k.group(3)) if k else 0}
