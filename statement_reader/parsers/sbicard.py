"""SBI Card (SBI Cards and Payment Services Ltd) credit card statement parser.

Layout (2026 format):
  Page 1  : header (total/min due, limits, dates), account summary, reward summary,
            then transactions:  'DD Mon YY  description  amount  FLAG'
            FLAG: C=credit, D=debit, M=monthly instalment, EN/FP/EMD/BT=conversions, T=temp credit
  Page 2+ : more transactions, grouped under 'TRANSACTIONS FOR <cardholder>'
  Page 3  : 'VALUE ADDED SERVICES' table with active EMI plans
  Later   : schedule of charges (lists ALL card names - must be ignored for detection)
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry, account_check
from statement_reader.utils.pdf_utils import extract_text_all_pages, ocr_pages, is_vectorized_pdf

AMT = r'[\d,]+\.\d{2}'
MON = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
FLAGS = r'(?:C|D|M|EN|FP|EMD|BT|T)'
CREDIT_FLAGS = {'C', 'T'}

TXN_RE = re.compile(rf'^(\d{{1,2}} {MON} \d{{2}})\s+(.+?)\s+({AMT})\s+({FLAGS})$')
CONT_RE = re.compile(rf'^([A-Z][^\n]*?)\s+({AMT})\s+({FLAGS})$')   # undated fee/tax line
HOLDER_RE = re.compile(r'^TRANSACTIONS FOR\s+(.+)$', re.I)
END_MARKERS = ('Transactions highlighted', 'Important Messages', 'SAVINGS AND BENEFITS',
               'C=Credit', 'Schedule of Charges')

CARD_NAMES = [  # (keyword, display name) - most specific first
    ('aurum', 'SBI Card AURUM'), ('elite', 'SBI Card ELITE'), ('prime', 'SBI Card PRIME'),
    ('pulse', 'SBI Card PULSE'), ('cashback', 'SBI Cashback Card'),
    ('simplyclick', 'SBI SimplyCLICK'), ('simply click', 'SBI SimplyCLICK'),
    ('simplysave', 'SBI SimplySAVE'), ('simply save', 'SBI SimplySAVE'),
    ('irctc', 'IRCTC SBI Card'), ('bpcl', 'BPCL SBI Card'), ('krisflyer', 'KrisFlyer SBI Card'),
    ('air india', 'Air India SBI Card'), ('shaurya', 'Shaurya SBI Card'),
]


def _date(s: str) -> str:
    s = s.strip()
    for fmt in ('%d %b %y', '%d %b %Y', '%d/%m/%Y', '%d-%m-%Y'):
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


class SBICardParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'sbi card' in t or 'sbi cards and payment' in t or 'sbicard' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='SBI Card', statement_type='credit_card',
                             source_file=Path(filepath).name)

        if is_vectorized_pdf(filepath, password):
            pages = ocr_pages(filepath, password, pages=[1, 2, 3])
        else:
            pages = extract_text_all_pages(filepath, password, max_pages=12)

        # Drop fee-schedule / MITC pages: they mention every card variant
        useful = [p for p in pages if 'Schedule of Charges' not in p
                  and 'Interest Free Credit Period' not in p]
        full = '\n'.join(useful)
        data.raw_text = full

        data.card_name = self._card_name(pages)
        m = re.search(r'Credit Card Number\s*\n\s*([X\d ]{12,25})', full)
        if m:
            data.card_number = m.group(1).strip()

        self._header(full, data)
        self._rewards(full, data)
        data.transactions = self._transactions(full)
        self._emis(full, data)
        # Balance check. 'M' rows (monthly EMI instalment) move money out of the existing
        # EMI balance and are not part of Purchases or Total Outstanding on SBI Card.
        stated = getattr(self, '_stated', None)
        if stated and data.closing_balance:
            row = account_check(data.card_number, 'Credit card', data.opening_balance, data.closing_balance,
                                [t for t in data.transactions if t.reference != 'M'], is_loan=True,
                                stated_credits=stated[0], stated_debits=stated[1],
                                period=f'{data.from_date} to {data.to_date}', tol=1.0,
                                **{'Note': 'EMI instalment rows (M) excluded; total outstanding rounded to ₹1'})
            data.accounts.append(row)
        return data

    # ------------------------------------------------------------------
    def _card_name(self, pages) -> str:
        # Contact page carries the card-specific mailbox, e.g. 'aurum@sbicard.com'
        for p in pages:
            m = re.search(r'([a-z]+)@sbicard\.com', p, re.I)
            if m and m.group(1).lower() not in ('customercare', 'nodalofficer', 'principalnodalofficer'):
                kw = m.group(1).lower()
                for key, name in CARD_NAMES:
                    if key.replace(' ', '') == kw or key in kw:
                        return name
        first = pages[0].lower() if pages else ''
        for key, name in CARD_NAMES:
            if key in first:
                return name
        return 'SBI Credit Card'

    def _header(self, t: str, data: StatementData):
        m = re.search(rf'Total Amount Due[^\n]*\n\s*({AMT})', t)
        if m:
            data.total_due = _amt(m.group(1))

        # Min due value lands at the end of the CKYC/STMT line after the label
        m = re.search(rf'Minimum Amount Due[^\n]*\n(?:[^\n]*\n){{0,3}}?[^\n]*?({AMT})', t)
        if m:
            data.minimum_due = _amt(m.group(1))

        m = re.search(rf'Credit Limit[^\n]*Statement Date\s*\n\s*({AMT})\s+({AMT})\s+(\d{{1,2}} {MON} \d{{4}})', t)
        if m:
            data.credit_limit = _amt(m.group(1))
            data.statement_date = _date(m.group(3))

        m = re.search(rf'Available Credit Limit[^\n]*Payment Due Date\s*\n\s*({AMT})\s+({AMT})\s+(\d{{1,2}} {MON} \d{{4}})', t)
        if m:
            data.available_credit = _amt(m.group(1))
            data.due_date = _date(m.group(3))

        # Account summary row: prev bal, payments, purchases, fees, total outstanding
        m = re.search(rf'ACCOUNT SUMMARY(?:[^\n]*\n){{1,6}}?\s*({AMT})\s+({AMT})\s+({AMT})\s+({AMT})\s+({AMT})', t)
        if m:
            data.opening_balance = _amt(m.group(1))
            data.closing_balance = _amt(m.group(5))
            # payments/credits, purchases & other debits, fee+taxes+interest (for the balance check)
            self._stated = (_amt(m.group(2)), round(_amt(m.group(3)) + _amt(m.group(4)), 2))

        m = re.search(rf'Statement Period:\s*(\d{{1,2}} {MON} \d{{2}})\s+to\s+(\d{{1,2}} {MON} \d{{2}})', t)
        if m:
            data.from_date = _date(m.group(1))
            data.to_date = _date(m.group(2))
            if not data.statement_date:
                data.statement_date = data.to_date

    def _rewards(self, t: str, data: StatementData):
        # 'Previous Balance Earned Reversed Closing Balance Points Expiry Details'
        # '1200 450 0 1650 NONE'   (opening, earned, redeemed, closing, expiry — example values)
        m = re.search(r'Closing Balance\s+Points Expiry Details\s*\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+)', t)
        if m:
            data.reward_opening = int(m.group(1))
            data.reward_earned = int(m.group(2))
            data.reward_redeemed = int(m.group(3))
            data.reward_closing = int(m.group(4))
            exp = m.group(5).strip()
            if exp.upper() != 'NONE':
                data.reward_expiry_date = exp

    def _transactions(self, t: str) -> list:
        txns = []
        holder = ''
        last_date = ''
        in_block = False
        for raw in t.split('\n'):
            line = raw.strip()
            if not line:
                continue
            if line.startswith('Date Transaction Details') or 'for Statement Period' in line:
                in_block = True
                continue
            if any(line.startswith(mk) for mk in END_MARKERS):
                in_block = False
                continue

            h = HOLDER_RE.match(line)
            if h:
                holder = h.group(1).strip().title()
                in_block = True
                continue

            m = TXN_RE.match(line)
            if m:
                in_block = True
                last_date = _date(m.group(1))
                txns.append(self._make(last_date, m.group(2), m.group(3), m.group(4), holder))
                continue

            # Undated continuation lines (forex markup, GST) belong to the last dated row
            if in_block and last_date:
                c = CONT_RE.match(line)
                if c and not re.match(r'^(Total|Previous|Credit|Available)', c.group(1)):
                    txns.append(self._make(last_date, c.group(1), c.group(2), c.group(3), holder))
        return txns

    @staticmethod
    def _make(date, desc, amount, flag, holder) -> Transaction:
        desc = re.sub(r'\s+', ' ', desc).strip()
        cat = ''
        if flag == 'M' or re.search(r'\bEMI\b', desc):
            cat = 'EMI'
        elif re.search(r'IGST|CGST|SGST|MARKUP|FEE|CHARGE|INTEREST', desc, re.I):
            cat = 'Fees & Taxes'
        elif 'PAYMENT RECEIVED' in desc.upper():
            cat = 'Payment'
        return Transaction(date=date, description=desc, amount=_amt(amount),
                           txn_type='credit' if flag in CREDIT_FLAGS else 'debit',
                           category=cat, reference=flag, cardholder=holder)

    def _emis(self, t: str, data: StatementData):
        # VALUE ADDED SERVICES:
        # 'MERCHANT EMI(6 MONTHS)(Jul.'26) Jan 27 10449.56 3579.41(3435.73+143.68)'
        plan_re = re.compile(
            rf'^(.*?EMI.*?\((\d+) MONTHS\)\S*)\s+({MON} \d{{2}})\s+([\d,]+\.?\d*)\s+'
            rf'([\d,]+\.\d{{2}})\s*\(([\d,.]+)\+([\d,.]+)\)', re.M)
        counters = re.findall(r'EMI (\d{1,3})/(\d{1,3})', t)
        plans = list(plan_re.finditer(t))
        for i, m in enumerate(plans):
            tenure = int(m.group(2))
            outstanding = _amt(m.group(4))
            principal_part = _amt(m.group(6))
            remaining = 0
            if len(counters) == len(plans):
                paid, total = map(int, counters[i])
                remaining = max(total - paid, 0)
            elif principal_part:
                remaining = round(outstanding / principal_part)
            booking = re.search(r"\((\w{3})\.?'(\d{2})\)", m.group(1))
            data.emis.append(EMIEntry(
                description=m.group(1).strip(),
                principal=outstanding,
                interest=_amt(m.group(7)),
                emi_amount=_amt(m.group(5)),
                tenure_months=tenure,
                months_remaining=remaining,
                start_date=f'{booking.group(1)} 20{booking.group(2)}' if booking else '',
                end_date=_date('01 ' + m.group(3))[:7],
                ref=m.group(1).strip(), lender='SBI Card', outstanding=outstanding,
            ))
