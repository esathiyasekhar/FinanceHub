"""Generic fallback parser — works on any bank PDF via OCR + heuristic extraction."""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction
from statement_reader.utils.pdf_utils import extract_text_all_pages, ocr_pages, is_vectorized_pdf, get_page_count

DATE_FMTS = ['%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %b %y', '%d/%m/%y',
             '%d %B %Y', '%d/%m/%y']


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


def _detect_bank(text: str) -> str:
    t = text.lower()
    # Bank web domains / letterhead are reliable; a bank name inside a transaction
    # description (e.g. 'IMPS ... HDFC') is not — so score domains first.
    domains = [('sbi.co.in', 'State Bank of India'), ('sbicard.com', 'SBI Card'),
               ('hdfcbank', 'HDFC Bank'), ('icicibank', 'ICICI Bank'), ('axisbank', 'Axis Bank'),
               ('sc.com', 'Standard Chartered Bank'), ('sc.bank.in', 'Standard Chartered Bank'),
               ('kotak.com', 'Kotak Mahindra Bank'), ('southindianbank', 'South Indian Bank'),
               ('bankofbaroda', 'Bank of Baroda'), ('bankofindia', 'Bank of India')]
    for dom, name in domains:
        if dom in t:
            return name
    if 'icici' in t:
        return 'ICICI Bank'
    if 'hdfc' in t:
        return 'HDFC Bank'
    if 'state bank of india' in t or 'sbi' in t:
        return 'State Bank of India'
    if 'standard chartered' in t:
        return 'Standard Chartered Bank'
    if 'axis' in t:
        return 'Axis Bank'
    if 'kotak' in t:
        return 'Kotak Mahindra Bank'
    if 'yes bank' in t:
        return 'Yes Bank'
    if 'indusind' in t:
        return 'IndusInd Bank'
    if 'idfc' in t:
        return 'IDFC First Bank'
    if 'rbl' in t:
        return 'RBL Bank'
    if 'amex' in t or 'american express' in t:
        return 'American Express'
    return 'Unknown Bank'


class GenericParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return True  # Always fallback

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(source_file=Path(filepath).name)

        vectorized = is_vectorized_pdf(filepath, password)
        n_pages = get_page_count(filepath, password)

        if vectorized:
            pages_to_ocr = list(range(1, min(n_pages + 1, 6)))
            raw_pages = ocr_pages(filepath, password, pages=pages_to_ocr)
        else:
            raw_pages = extract_text_all_pages(filepath, password, max_pages=20)

        full_text = '\n'.join(raw_pages)
        data.raw_text = full_text

        data.bank = _detect_bank(full_text)
        data.card_name = data.bank

        # Detect type
        t = full_text.lower()
        if 'credit card' in t or 'credit limit' in t:
            data.statement_type = 'credit_card'
        elif 'loan' in t and 'emi' in t:
            data.statement_type = 'loan'
        else:
            data.statement_type = 'savings'

        # Card/account number
        m = re.search(r'(\d{4}[\s-]?[Xx*]{4}[\s-]?[Xx*]{4}[\s-]?\d{4})', full_text)
        if m:
            data.card_number = m.group(1)
        m = re.search(r'(?:account\s+(?:no|number))[.:\s]+(\d{9,18})', full_text, re.I)
        if m:
            data.account_number = m.group(1)

        # Dates
        m = re.search(r'(?:statement|billing)\s+date[:\s]+(\d{1,2}[/ -]\d{1,2}[/ -]\d{2,4})', full_text, re.I)
        if m:
            data.statement_date = _parse_date(m.group(1))
        m = re.search(r'(?:payment\s+)?due\s+date[:\s]+(\d{1,2}[/ -]\d{1,2}[/ -]\d{2,4})', full_text, re.I)
        if m:
            data.due_date = _parse_date(m.group(1))

        # Amounts
        m = re.search(r'total\s+(?:amount\s+)?due[:\s]+([\d,]+\.\d{2})', full_text, re.I)
        if m:
            data.total_due = _clean_amount(m.group(1))
        m = re.search(r'minimum\s+(?:amount\s+)?due[:\s]+([\d,]+\.\d{2})', full_text, re.I)
        if m:
            data.minimum_due = _clean_amount(m.group(1))
        m = re.search(r'credit\s+limit[:\s]+([\d,]+)', full_text, re.I)
        if m:
            data.credit_limit = _clean_amount(m.group(1))

        data.transactions = self._extract_transactions(full_text)
        return data

    def _extract_transactions(self, text: str) -> list:
        """
        Heuristic extraction: find any line with a date and amount.
        Tries multiple patterns in decreasing specificity.
        """
        txns = []
        seen = set()

        patterns = [
            # date  serial  description  amount  [CR/DR]
            re.compile(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+'
                r'\d{6,15}\s+'
                r'(.+?)\s+'
                r'([\d,]+\.\d{2})\s*'
                r'(CR|DR|Cr|Dr)?\s*$'
            ),
            # date  description  amount  [CR/DR]
            re.compile(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+'
                r'(.+?)\s+'
                r'([\d,]+\.\d{2})\s*'
                r'(CR|DR|Cr|Dr)?\s*$'
            ),
            # date  description  debit  credit  balance
            re.compile(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+'
                r'(.+?)\s+'
                r'([\d,]+\.\d{2})\s+'
                r'([\d,]+\.\d{2})\s+'
                r'([\d,]+\.\d{2})\s*$'
            ),
        ]

        for line in text.split('\n'):
            line = line.strip()
            if not re.search(r'\d{2}[/-]\d{2}[/-]\d{2,4}', line):
                continue

            for i, pat in enumerate(patterns):
                m = pat.match(line)
                if not m:
                    continue
                date_val = _parse_date(m.group(1))
                if not re.match(r'\d{4}-\d{2}-\d{2}', date_val):
                    break  # Try next pattern

                desc = m.group(2).strip()
                if re.match(r'^(Opening|Closing|Total|Previous|Brought)', desc, re.I):
                    break

                if i < 2:
                    # Single amount + DR/CR flag
                    amount = _clean_amount(m.group(3))
                    flag = (m.group(4) or 'Dr').upper()
                    txn_type = 'credit' if flag in ('CR', 'C') else 'debit'
                else:
                    # Debit + credit columns
                    debit = _clean_amount(m.group(3))
                    credit = _clean_amount(m.group(4))
                    if debit > 0:
                        amount, txn_type = debit, 'debit'
                    elif credit > 0:
                        amount, txn_type = credit, 'credit'
                    else:
                        break

                if amount > 0 and desc:
                    key = (date_val, desc[:30], amount)
                    if key not in seen:
                        seen.add(key)
                        txns.append(Transaction(
                            date=date_val,
                            description=desc,
                            amount=amount,
                            txn_type=txn_type,
                        ))
                break  # Used a pattern, don't try others

        return txns
