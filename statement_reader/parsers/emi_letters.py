"""Credit-card EMI / loan confirmation letters (not statements).

They contain no account transactions — only the loan terms (and, for Axis, the full
repayment schedule). Output: statement_type 'emi_letter', one EMI entry, and for Axis
the schedule rows in the Transactions sheet marked 'EMI schedule (planned)'.
"""
import re
import sys
import os
from datetime import datetime, date
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry
from statement_reader.utils.pdf_utils import open_pdf


def _d(s):
    s = re.sub(r'\s+', '', s.strip()) if re.match(r'^\d{1,2}-\s*\w{3}-\d{2,4}$', s.strip()) else s.strip()
    for fmt in ('%d-%b-%Y', '%d-%b-%y', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s.title(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _n(s):
    try:
        return round(float(str(s).replace(',', '')), 2)
    except ValueError:
        return 0.0


def _rate_pa(rate: str) -> float:
    """'1.25% p.m.' → 15.0 ; '15% p.a.' → 15.0"""
    m = re.search(r'([\d.]+)\s*%\s*p\.?\s*([ma])', rate or '', re.I)
    if not m:
        return 0.0
    v = float(m.group(1))
    return round(v * 12, 2) if m.group(2).lower() == 'm' else v


def _add_months(iso, n):
    try:
        d = datetime.strptime(iso, '%Y-%m-%d')
        y, m = divmod(d.month - 1 + n, 12)
        return f'{d.year + y}-{m + 1:02d}'
    except ValueError:
        return ''


class HDFCSmartEMILetterParser(BaseParser):
    """'Subject: SmartEMI Loan on your HDFC Bank Credit Card Number: 400000XXXXXX1234'"""

    def can_parse(self, text: str) -> bool:
        return 'SmartEMI' in text and 'HDFC' in text

    def parse(self, filepath: str, password: str = '') -> StatementData:
        with open_pdf(filepath, password) as pdf:
            t = '\n'.join(pg.extract_text() or '' for pg in pdf.pages[:2])
        data = StatementData(bank='HDFC Bank', statement_type='emi_letter',
                             card_name='HDFC SmartEMI loan letter', source_file=Path(filepath).name)
        data.raw_text = t[:2000]
        g = lambda pat: (re.search(pat, t).group(1).strip() if re.search(pat, t) else '')
        m = re.search(r'(\d{1,2})-\s*\n?\s*(\w{3})-(\d{4})', t)
        letter_date = _d(f'{m.group(1)}-{m.group(2)}-{m.group(3)}') if m else ''
        data.statement_date = letter_date
        data.card_number = g(r'Credit Card Number:\s*(\S+)')
        loan = g(r'Loan no\.\s*0*(\d+)')
        data.account_number = loan
        amount = _n(g(r'Amount\s+Rs\.?\s*([\d,]+\.?\d*)'))
        rate = g(r'Interest Rate\s+([\d.]+%\s*p\.?\s*[ma]\.?)')
        tenure = int(g(r'Tenure\s+(\d+)\s*Months') or 0)
        emi = _n(g(r'EMI\s+Rs\.?\s*([\d,]+\.?\d*)'))
        fee = _n(g(r'Processing Fee\s+Rs\.?\s*([\d,]+\.?\d*)'))
        data.emis.append(EMIEntry(
            description=f'HDFC SmartEMI {loan} on card {data.card_number} @ {rate} '
                        f'(processing fee ₹{fee:,.0f} + GST; EMI excl. GST)',
            principal=amount, emi_amount=emi, tenure_months=tenure, months_remaining=tenure,
            start_date=letter_date, end_date=_add_months(letter_date, tenure),
            ref=loan, lender='HDFC Bank', original_amount=amount, outstanding=amount,
            rate_pa=_rate_pa(rate)))
        data.total_due = amount
        return data


class AxisEMILetterParser(BaseParser):
    """'Re: Conversion of Transaction into EMI' + 'Monthly EMI payment Details' schedule."""

    def can_parse(self, text: str) -> bool:
        return 'Conversion of Transaction into' in text and 'AXIS' in text.upper()

    def parse(self, filepath: str, password: str = '') -> StatementData:
        with open_pdf(filepath, password) as pdf:
            t = '\n'.join(pg.extract_text() or '' for pg in pdf.pages)
        data = StatementData(bank='Axis Bank', statement_type='emi_letter',
                             card_name='Axis card EMI letter', source_file=Path(filepath).name)
        data.raw_text = t[:2000]
        g = lambda pat: (re.search(pat, t).group(1).strip() if re.search(pat, t) else '')
        data.statement_date = _d(g(r'Date:\s*(\d{1,2}-\w{3}-\d{4})'))
        data.card_number = g(r'Card number\s*:\s*(\S+)')
        ref = g(r'Ref\. No\.\s*\w*?_?(\d+)') or g(r'Loan no\s*:\s*(\d+)')
        data.account_number = ref
        amount = _n(g(r'Transaction Amount\s*:\s*Rs\.?\s*([\d,.]+)'))
        merchant = g(r'Merchant Name\s*:\s*(.+)')
        txn_date = _d(g(r'Date of Transaction\s*:\s*(\S+)'))
        emi = _n(g(r'Installment Amount\(excluding taxes\)\s*:\s*Rs\.?\s*([\d,.]+)'))
        rate = g(r'Interest Rate\s*:\s*([\d.]+\s*%\s*p\.?m\.?)')
        tenure = int(g(r'Tenure\s*:\s*(\d+)\s*months') or 0)
        last = _d(g(r'Last installment date\s*:\s*(\S+)'))
        cashback = _n(g(r'Cashback Amount\s*:\s*([\d,.]+)'))

        today = date.today().isoformat()
        sched = re.findall(r'^\d+\s+(\d+)\s+(\d{2}-\w{3}-\d{2})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+\S+$', t, re.M)
        total_int = 0.0
        for n, dt, rep, pri, intr, outst in sched:
            iso = _d(dt)
            total_int += _n(intr)
            data.transactions.append(Transaction(
                date=iso, amount=_n(rep), txn_type='debit',
                description=f'Instalment {n}/{tenure or len(sched)}: principal {_n(pri):,.2f} + '
                            f'interest {_n(intr):,.2f} → outstanding {_n(outst):,.2f}',
                category='EMI schedule (paid)' if iso <= today else 'EMI schedule (planned)',
                reference=ref, cardholder=merchant[:30]))
        remaining = sum(1 for x in data.transactions if x.date > today)
        outstanding = next((_n(o) for n, dt, rep, p, i, o in sched if _d(dt) > today), 0.0) if remaining else 0.0
        data.emis.append(EMIEntry(
            description=f'Axis EMI {ref} — {merchant} (txn {txn_date}, ₹{amount:,.2f}, cashback ₹{cashback:,.0f}) @ {rate}',
            principal=amount, interest=round(total_int, 2), emi_amount=emi,
            tenure_months=tenure, months_remaining=remaining,
            start_date=data.transactions[0].date if data.transactions else '', end_date=last,
            ref=ref, lender='Axis Bank', original_amount=amount, outstanding=outstanding,
            rate_pa=_rate_pa(rate)))
        data.total_due = outstanding
        return data
