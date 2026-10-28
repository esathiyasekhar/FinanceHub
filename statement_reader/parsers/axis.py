"""Axis Bank — credit card (SELECT, Flipkart, ACE, …) and savings account statements."""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry, account_check
from statement_reader.utils.pdf_utils import open_pdf

AMT = r'[\d,]+\.\d{2}'


def _clean(s) -> str:
    return re.sub(r'[ \t]+', ' ', str(s or '').replace('(cid:9)', ' ')).strip()


def _d(s):
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d-%b-%y', '%d-%b-%Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s.strip()


def _n(s):
    try:
        return round(float(re.sub(r'[^\d.\-]', '', str(s)) or 0), 2)
    except ValueError:
        return 0.0


def _signed(amount: str, flag: str) -> float:
    """Card balances: 'Dr' = owed (+), 'Cr' = in credit (−)."""
    v = _n(amount)
    return -v if (flag or '').strip().upper() == 'CR' else v


# ════════════════════════════════════════════════════════════════════════════
class AxisCCParser(BaseParser):
    """Layout: PAYMENT SUMMARY block, then table
       DATE | TRANSACTION DETAILS | MERCHANT CATEGORY | AMOUNT (Rs.) 'n Dr/Cr'"""

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'axis' in t and 'credit card statement' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='Axis Bank', statement_type='credit_card',
                             source_file=Path(filepath).name)
        rows, texts = [], []
        with open_pdf(filepath, password) as pdf:
            for pg in pdf.pages:
                texts.append(_clean(pg.extract_text()))
                for tb in pg.extract_tables():
                    rows.extend(tb)
        full = '\n'.join(texts)
        data.raw_text = texts[0] if texts else ''
        first = texts[0].split('\n')[0] if texts else ''
        m = re.match(r'^(.+?)\s+credit card statement', first, re.I)
        data.card_name = f'Axis {m.group(1).strip().title()} Credit Card' if m else 'Axis Bank Credit Card'

        m = re.search(rf'({AMT})\s*(Dr|Cr)?\s+({AMT})\s*(Dr|Cr)?\s+(\d{{2}}/\d{{2}}/\d{{4}})\s*-\s*(\d{{2}}/\d{{2}}/\d{{4}})\s+(\d{{2}}/\d{{2}}/\d{{4}})\s+(\d{{2}}/\d{{2}}/\d{{4}})', full)
        if m:
            data.total_due = _signed(m.group(1), m.group(2))
            data.minimum_due = _n(m.group(3))
            data.from_date, data.to_date = _d(m.group(5)), _d(m.group(6))
            data.due_date, data.statement_date = _d(m.group(7)), _d(m.group(8))
        m = re.search(rf'(\d{{4,6}}\*+\d{{4}})\s+({AMT})\s+({AMT})\s+({AMT})', full)
        if m:
            data.card_number = m.group(1)
            data.credit_limit, data.available_credit = _n(m.group(2)), _n(m.group(3))
        # Previous Balance - Payments - Credits + Purchase + Cash Advance + Other Debit&Charges = Total
        m = re.search(rf'({AMT})\s*(Dr|Cr)?\s+({AMT})\s+({AMT})\s+({AMT})\s+({AMT})\s+({AMT})\s+({AMT})\s*(Dr|Cr)?', full)
        stated_cr = stated_dr = None
        if m:
            data.opening_balance = _signed(m.group(1), m.group(2))
            stated_cr = round(_n(m.group(3)) + _n(m.group(4)), 2)
            stated_dr = round(_n(m.group(5)) + _n(m.group(6)) + _n(m.group(7)), 2)
            data.closing_balance = _signed(m.group(8), m.group(9))
        m = re.search(r'eDGE REWARD[\s\S]{0,400}?\n\s*(\d[\d,]*)\s+(\d{2}-\d{2}-\d{4})\s+(\d{6,})', full)
        if m:
            data.reward_closing = int(m.group(1).replace(',', ''))
            data.reward_expiry_date = ''

        data.transactions = self._txns(rows) or self._txns_text(full)
        self._emis(data)
        data.accounts.append(account_check(
            data.card_number, 'Credit card', data.opening_balance, data.closing_balance,
            data.transactions, is_loan=True, stated_credits=stated_cr, stated_debits=stated_dr,
            period=f'{data.from_date} to {data.to_date}'))
        return data

    @staticmethod
    def _txns(rows):
        out, holder = [], ''
        for row in rows:
            cells = [_clean(c) for c in row]
            if not cells:
                continue
            if 'Card No:' in cells and 'Name' in cells:
                holder = cells[cells.index('Name') + 1].title() if cells.index('Name') + 1 < len(cells) else ''
                continue
            if not re.match(r'^\d{2}/\d{2}/\d{4}$', cells[0] or ''):
                continue
            vals = [c for c in cells[1:] if c]
            if len(vals) < 2:
                continue
            m = re.match(rf'^({AMT})\s*(Dr|Cr)$', vals[-1])
            if not m:
                continue
            desc = vals[0]
            cat = vals[-2] if len(vals) >= 3 else ''
            out.append(AxisCCParser._make(cells[0], desc, m.group(1), m.group(2), cat, holder))
        return out

    @staticmethod
    def _txns_text(full):
        out = []
        for line in full.split('\n'):
            m = re.match(rf'^(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+({AMT})\s*(Dr|Cr)$', line.strip())
            if m:
                out.append(AxisCCParser._make(m.group(1), m.group(2), m.group(3), m.group(4), '', ''))
        return out

    @staticmethod
    def _make(date, desc, amount, flag, cat, holder):
        up = desc.upper()
        if 'PAYMENT' in up and flag == 'Cr':
            cat = 'Payment'
        elif up.startswith('EMI '):
            cat = 'EMI'
        elif up in ('GST', 'IGST', 'CGST', 'SGST') or 'FEE' in up or 'CHARGE' in up:
            cat = 'Fees & Taxes'
        else:
            cat = cat.title()
        ref = ''
        r = re.search(r'REF#\s*(\w+)', desc)
        if r:
            ref = r.group(1)
        return Transaction(date=_d(date), description=desc, amount=_n(amount),
                           txn_type='credit' if flag == 'Cr' else 'debit',
                           category=cat, reference=ref, cardholder=holder)

    @staticmethod
    def _emis(data):
        """'EMI PRINCIPAL - 12/12, REF# 63443420' + 'EMI INTEREST - 12/12, REF# …' → one EMI per REF."""
        plans = {}
        for t in data.transactions:
            m = re.match(r'EMI (PRINCIPAL|INTEREST)\s*-\s*(\d+)/(\d+),?\s*REF#\s*(\w+)', t.description, re.I)
            if m:
                p = plans.setdefault(m.group(4), {'paid': int(m.group(2)), 'total': int(m.group(3)),
                                                  'principal': 0.0, 'interest': 0.0})
                p[m.group(1).lower()] += t.amount
        for ref, p in plans.items():
            data.emis.append(EMIEntry(
                description=f'Axis card EMI REF# {ref} — instalment {p["paid"]}/{p["total"]}',
                principal=round(p['principal'], 2), interest=round(p['interest'], 2),
                emi_amount=round(p['principal'] + p['interest'], 2),
                tenure_months=p['total'], months_remaining=p['total'] - p['paid'],
                ref=ref, lender='Axis Bank'))


# ════════════════════════════════════════════════════════════════════════════
class AxisSavingsParser(BaseParser):
    """'Statement for Account No. 91201XXXXX01234 for the period from 01-09-2026 to 30-09-2026'
       Date | Transaction Details | Chq No. | Withdrawal | Deposits | Balance"""

    def can_parse(self, text: str) -> bool:
        t = _clean(text).lower()
        return 'axis' in t and 'statement for account no' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(bank='Axis Bank', statement_type='savings', source_file=Path(filepath).name)
        rows, texts = [], []
        with open_pdf(filepath, password) as pdf:
            for pg in pdf.pages:
                texts.append(_clean(pg.extract_text()))
                for tb in pg.extract_tables():
                    rows.extend(tb)
        full = '\n'.join(texts)
        data.raw_text = texts[0] if texts else ''

        m = re.search(r'Statement for Account No\.?\s*(\S+)\s+for the period from\s+(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})', full)
        if m:
            data.account_number = m.group(1)
            data.from_date, data.to_date = _d(m.group(2)), _d(m.group(3))
            data.statement_date = data.to_date
        m = re.search(r'Scheme Name:\s*(.+?)\s+Joint Holder:\s*(.*)', full)
        scheme = m.group(1).strip().title() if m else 'Savings Account'
        joint = m.group(2).strip() if m else ''
        data.card_name = f'Axis {scheme} {data.account_number[-4:]}'
        m = re.search(r'Cust ID:\s*(\S+)', full)
        if m:
            data.card_number = m.group(1)
        m = re.search(rf'Opening Balance\s+(-?{AMT})', full)
        if m:
            data.opening_balance = _n(m.group(1))
        m = re.search(rf'Closing Balance\s+(-?{AMT})', full)
        if m:
            data.closing_balance = _n(m.group(1))
        m = re.search(rf'Closing Balance\s+-?{AMT}\s*\n\s*Total\s+({AMT})\s+({AMT})', full)
        stated_dr, stated_cr = (_n(m.group(1)), _n(m.group(2))) if m else (None, None)

        txns = []
        for row in rows:
            cells = [_clean(c).replace('\n', ' ') for c in row]
            if len(cells) < 6 or not re.match(r'^\d{2}-\d{2}-\d{4}$', cells[0]):
                continue
            wd, dep = _n(cells[-3]), _n(cells[-2])
            if wd <= 0 and dep <= 0:
                continue
            desc = ' '.join(c for c in cells[1:-4] if c) or cells[1]
            credit = dep > 0
            txns.append(Transaction(date=_d(cells[0]), description=desc, amount=dep if credit else wd,
                                    txn_type='credit' if credit else 'debit', category=_sav_cat(desc, credit),
                                    reference=cells[-4] if len(cells) >= 6 else '',
                                    cardholder=f'Savings {data.account_number[-4:]}'))
        data.transactions = txns
        data.accounts.append(account_check(
            data.account_number, 'Savings', data.opening_balance, data.closing_balance, txns,
            stated_credits=stated_cr, stated_debits=stated_dr,
            period=f'{data.from_date} to {data.to_date}', **{'Scheme': scheme, 'Joint holder': joint}))
        return data


def _sav_cat(desc, credit):
    u = desc.upper()
    if 'INT.PD' in u or 'INTEREST' in u:
        return 'Interest'
    if u.startswith('UPI'):
        return 'UPI'
    if 'ATM' in u or 'CWDR' in u:
        return 'Cash withdrawal'
    if 'NEFT' in u or 'IMPS' in u or 'RTGS' in u or 'TRANSFER' in u:
        return 'Transfer'
    if 'CHRG' in u or 'CHARGE' in u or 'FEE' in u or 'GST' in u:
        return 'Bank charges'
    if 'ACH' in u or 'NACH' in u or 'SI ' in u:
        return 'EMI / auto-debit'
    if 'PUR' in u or 'POS' in u:
        return 'Card purchase'
    return ''
