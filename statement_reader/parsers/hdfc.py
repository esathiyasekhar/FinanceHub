"""HDFC Bank credit card and savings account statement parser."""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry
from statement_reader.utils.pdf_utils import extract_text_all_pages, ocr_pages, is_vectorized_pdf

DATE_FMTS = ['%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %b %y', '%d/%m/%y', '%d %B %Y']


def _parse_date(s: str) -> str:
    s = s.strip()
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _clean_amount(s: str) -> float:
    try:
        return round(float(re.sub(r'[^\d.]', '', s)), 2)
    except (ValueError, TypeError):
        return 0.0


class HDFCParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return 'hdfc' in text.lower()

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(
            bank='HDFC Bank',
            source_file=Path(filepath).name,
        )

        vectorized = is_vectorized_pdf(filepath, password)
        if vectorized:
            raw_pages = ocr_pages(filepath, password, pages=[1, 2, 3])
        else:
            raw_pages = extract_text_all_pages(filepath, password, max_pages=15)

        # Current HDFC credit card template (Biz Power, Tata Neu, Regalia, ...)
        from statement_reader.parsers.hdfc_cc import is_hdfc_cc_template, parse_hdfc_cc
        if raw_pages and is_hdfc_cc_template(raw_pages[0]):
            return parse_hdfc_cc(raw_pages, filepath)

        full_text = '\n'.join(raw_pages)
        data.raw_text = full_text

        # Detect type
        t = full_text.lower()
        if 'credit card' in t or 'credit limit' in t:
            data.statement_type = 'credit_card'
        elif 'savings' in t or 'current account' in t:
            data.statement_type = 'savings'
        else:
            data.statement_type = 'credit_card'

        # Card/account name
        data.card_name = self._detect_card_name(full_text)

        # Card number
        m = re.search(r'(\d{4}[\s-]?[Xx*]{4}[\s-]?[Xx*]{4}[\s-]?\d{4})', full_text)
        if m:
            data.card_number = m.group(1)

        self._extract_header(full_text, data)
        data.transactions = self._extract_transactions(full_text)
        self._extract_emis(full_text, data)

        return data

    def _detect_card_name(self, text: str) -> str:
        t = text.lower()
        if 'regalia' in t:
            return 'HDFC Regalia CC'
        if 'millennia' in t:
            return 'HDFC Millennia CC'
        if 'moneyback' in t:
            return 'HDFC MoneyBack CC'
        if 'infinia' in t:
            return 'HDFC Infinia CC'
        if 'diners' in t:
            return 'HDFC Diners CC'
        if 'bizpower' in t or 'biz power' in t:
            return 'HDFC BizPower CC'
        if 'savings' in t:
            return 'HDFC Savings'
        if 'current' in t:
            return 'HDFC Current'
        return 'HDFC CC'

    def _extract_header(self, text: str, data: StatementData):
        # Statement date
        m = re.search(r'(?:statement\s+date|billing\s+date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text, re.I)
        if m:
            data.statement_date = _parse_date(m.group(1))

        # Due date
        m = re.search(r'(?:payment\s+)?due\s+date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text, re.I)
        if m:
            data.due_date = _parse_date(m.group(1))

        # Total due
        for pat in [
            r'total\s+amount\s+due[:\s]+([\d,]+\.\d{2})',
            r'total\s+dues?[:\s]+([\d,]+\.\d{2})',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                data.total_due = _clean_amount(m.group(1))
                break

        # Min due
        m = re.search(r'minimum\s+(?:amount\s+)?due[:\s]+([\d,]+\.\d{2})', text, re.I)
        if m:
            data.minimum_due = _clean_amount(m.group(1))

        # Credit limit
        m = re.search(r'credit\s+limit[:\s]+([\d,]+)', text, re.I)
        if m:
            data.credit_limit = _clean_amount(m.group(1))

        # Opening/closing balance (savings)
        m = re.search(r'opening\s+balance[:\s]+([\d,]+\.\d{2})', text, re.I)
        if m:
            data.opening_balance = _clean_amount(m.group(1))

        m = re.search(r'closing\s+balance[:\s]+([\d,]+\.\d{2})', text, re.I)
        if m:
            data.closing_balance = _clean_amount(m.group(1))

    def _extract_transactions(self, text: str) -> list:
        txns = []

        # HDFC CC pattern: DD/MM/YYYY  description  amount  Dr/Cr
        # HDFC savings:    DD/MM/YYYY  description  debit_amt  credit_amt  balance
        lines = text.split('\n')
        for line in lines:
            line = line.strip()

            # CC transaction: date desc amount [Dr/Cr]
            m = re.match(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(.+?)\s+([\d,]+\.\d{2})\s*(Dr|Cr|DR|CR)?\s*$',
                line
            )
            if m:
                date_val = _parse_date(m.group(1))
                if not re.match(r'\d{4}-\d{2}-\d{2}', date_val):
                    continue
                desc = m.group(2).strip()
                amount = _clean_amount(m.group(3))
                flag = (m.group(4) or 'Dr').upper()
                if re.match(r'^(Opening|Closing|Total|Previous|Brought)', desc, re.I):
                    continue
                if re.match(r'^[\d,]+\.\d{2}$', desc):
                    continue
                if amount > 0 and len(desc) >= 3:
                    txns.append(Transaction(
                        date=date_val,
                        description=desc,
                        amount=amount,
                        txn_type='credit' if flag in ('CR', 'C') else 'debit',
                    ))
                continue

            # Savings: date desc ref debit credit balance
            m = re.match(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(.+?)\s+([\d,]*\.\d{2})?\s+([\d,]*\.\d{2})?\s+([\d,]+\.\d{2})\s*$',
                line
            )
            if m:
                date_val = _parse_date(m.group(1))
                desc = m.group(2).strip()
                debit = _clean_amount(m.group(3) or '0')
                credit = _clean_amount(m.group(4) or '0')
                if debit > 0:
                    txns.append(Transaction(date=date_val, description=desc,
                                            amount=debit, txn_type='debit'))
                elif credit > 0:
                    txns.append(Transaction(date=date_val, description=desc,
                                            amount=credit, txn_type='credit'))

        return txns

    def _extract_emis(self, text: str, data: StatementData):
        # HDFC uses: EasyEMI, Dial-an-EMI, SmartEMI, Balance Transfer on EMI
        emi_block = re.search(
            r'(?:emi\s+details?|easy\s*emi|dial.an.emi|smart\s*emi|'
            r'balance\s+transfer.*emi|loan\s+on\s+phone|'
            r'insta\s+loan)[^\n]*\n((?:.*\n){0,30})',
            text, re.I
        )
        if not emi_block:
            return
        block = emi_block.group(1)
        for line in block.split('\n'):
            # Description  principal  interest  emi_amount  tenure
            m = re.search(
                r'(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+(\d+)',
                line
            )
            if m:
                data.emis.append(EMIEntry(
                    description=m.group(1).strip(),
                    principal=_clean_amount(m.group(2)),
                    interest=_clean_amount(m.group(3)),
                    emi_amount=_clean_amount(m.group(4)),
                    tenure_months=int(m.group(5)),
                ))
                continue
            # Simpler: description  amount  tenure  emi
            m2 = re.search(
                r'(.+?)\s+([\d,]+\.\d{2})\s+(\d+)\s+([\d,]+\.\d{2})',
                line
            )
            if m2:
                data.emis.append(EMIEntry(
                    description=m2.group(1).strip(),
                    principal=_clean_amount(m2.group(2)),
                    tenure_months=int(m2.group(3)),
                    emi_amount=_clean_amount(m2.group(4)),
                ))
