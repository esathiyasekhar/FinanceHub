"""SBI (State Bank of India) savings, salary, and loan account statement parser.

Handles: Savings, Current, Home Loan, Personal Loan, Auto Loan accounts.
All formats use the same 7-column table structure via pdfplumber table extraction.
Password-protected PDFs are decrypted via pikepdf before parsing.
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, EMIEntry, account_check
from statement_reader.utils.pdf_utils import open_pdf

DATE_FMTS = ['%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %b %y', '%d/%m/%y', '%d %B %Y']


def _parse_date(s: str) -> str:
    s = s.strip()
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _clean_amount(s) -> float:
    if not s or s == '-':
        return 0.0
    # Remove DR/CR suffix, newlines, commas
    s = str(s).split('\n')[0].strip()
    s = re.sub(r'\s*(DR|CR)\s*$', '', s, flags=re.I)
    try:
        return round(float(re.sub(r'[^\d.]', '', s)), 2)
    except (ValueError, TypeError):
        return 0.0


def _clean_desc(s) -> str:
    """Take only the first line of a multi-line Details cell."""
    if not s:
        return ''
    lines = [l.strip() for l in str(s).split('\n') if l.strip()]
    return lines[0] if lines else ''


class SBIParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'state bank of india' in t or ('sbi' in t and 'account' in t)

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(
            bank='State Bank of India',
            source_file=Path(filepath).name,
        )

        try:
            with open_pdf(filepath, password) as pdf:
                pages = pdf.pages

                # --- Page 1: header info ---
                pg1_text = pages[0].extract_text() or ''
                data.raw_text = pg1_text
                self._extract_header(pg1_text, data)

                # --- All pages: table-based transaction extraction ---
                txns = []
                for page in pages:
                    for table in page.extract_tables():
                        txns.extend(self._parse_table(table, data))

                data.transactions = txns
                self._reconcile(data)

        except Exception as e:
            data.raw_text = f'Error: {e}'

        return data

    # ------------------------------------------------------------------
    def _extract_header(self, text: str, data: StatementData):
        """Parse account summary from page 1."""

        # Product type
        m = re.search(r'Product\s*:\s*(.+)', text, re.I)
        if m:
            product = m.group(1).strip()
            p_lower = product.lower()
            if 'home loan' in p_lower:
                data.statement_type = 'home_loan'
                data.card_name = 'SBI Home Loan'
            elif 'personal loan' in p_lower:
                data.statement_type = 'personal_loan'
                data.card_name = 'SBI Personal Loan'
            elif 'auto loan' in p_lower or 'car loan' in p_lower:
                data.statement_type = 'auto_loan'
                data.card_name = 'SBI Auto Loan'
            elif 'savings' in p_lower:
                data.statement_type = 'savings'
                data.card_name = 'SBI Savings Account'
            elif 'current' in p_lower:
                data.statement_type = 'current'
                data.card_name = 'SBI Current Account'
            elif 'education' in p_lower:
                data.statement_type = 'education_loan'
                data.card_name = 'SBI Education Loan'
            elif 'loan' in p_lower or 'od' == p_lower.strip():
                data.statement_type = 'loan'
                data.card_name = f'SBI {product}'
            else:
                data.statement_type = 'savings'
                data.card_name = f'SBI {product}'

        # Account number
        m = re.search(r'Account\s+No\s*:\s*(\d+)', text, re.I)
        if m:
            data.account_number = m.group(1)

        # CIF number (customer ID)
        m = re.search(r'CIF\s+NO\s*:\s*(\d+)', text, re.I)
        if m:
            data.card_number = m.group(1)  # reuse card_number for CIF

        # Statement period: "Statement :01-04-2025 to 31-03-2026"
        m = re.search(r'Statement\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', text, re.I)
        if m:
            data.statement_date = _parse_date(m.group(2))  # end date

        # Outstanding amount
        m = re.search(r'Outstanding\s+Amount\s*:\s*([\d,]+\.\d{2})', text, re.I)
        if m:
            data.closing_balance = _clean_amount(m.group(1))
            data.total_due = _clean_amount(m.group(1))

        # Sanctioned amount (loan)
        m = re.search(r'Sanctioned\s+Amount\s*:\s*([\d,]+\.\d{2})', text, re.I)
        if m:
            amt = _clean_amount(m.group(1))
            if amt > 0:
                data.credit_limit = amt

        # EMI
        m = re.search(r'EMI\s*:\s*([\d,]+\.\d{2})', text, re.I)
        if m:
            emi_amt = _clean_amount(m.group(1))
            if emi_amt > 0:
                data.minimum_due = emi_amt

        # Rate of interest
        m = re.search(r'Rate\s+of\s+Interest\s*:\s*([\d.]+)%', text, re.I)
        interest_rate = float(m.group(1)) if m else 0.0

        # Remaining tenure
        m = re.search(r'Remaining\s+Tenure\s*:\s*(\d+)\s*Months', text, re.I)
        months_remaining = int(m.group(1)) if m else 0

        # Loan term
        m = re.search(r'Loan\s+Term\s*:\s*(\d+)\s*Months', text, re.I)
        loan_term = int(m.group(1)) if m else 0

        # Build EMI entry for loan accounts
        if emi_amt := data.minimum_due:
            if emi_amt > 0 and (months_remaining or loan_term):
                m_name = re.search(r'Product\s*:\s*(.+)', text, re.I)
                prod = m_name.group(1).strip() if m_name else 'Loan'
                mo = re.search(r'Account open Date\s*:\s*(\d{2}-\d{2}-\d{4})', text, re.I)
                data.emis.append(EMIEntry(
                    description=f'SBI {prod} {data.account_number[-4:]} @ {interest_rate}%',
                    emi_amount=emi_amt,
                    tenure_months=loan_term,
                    months_remaining=months_remaining,
                    principal=data.total_due or 0.0,          # outstanding as on header date
                    start_date=_parse_date(mo.group(1)) if mo else '',
                    ref=data.account_number, lender='State Bank of India',
                    original_amount=data.credit_limit or 0.0,
                    outstanding=data.total_due or 0.0, rate_pa=interest_rate,
                ))

    # ------------------------------------------------------------------
    def _parse_table(self, table: list, data: StatementData) -> list:
        """Parse a 7-column SBI transaction table.

        Columns: Post Date | Value Date | Details | Ref No/Cheque | Debit | Credit | Balance
        """
        if not table or len(table) < 2:
            return []

        txns = []
        # Check header row
        header = [str(c or '').lower() for c in table[0]]
        if 'post date' not in ' '.join(header) and 'value date' not in ' '.join(header):
            return []  # Not a transaction table

        for row in table[1:]:
            if not row or len(row) < 7:
                continue

            post_date_cell = row[0]
            # value_date_cell = row[1]  # we use post date
            details_cell = row[2]
            # ref_cell = row[3]
            debit_cell = row[4]
            credit_cell = row[5]
            balance_cell = row[6]

            # Validate date
            if not post_date_cell or not re.match(r'\d{2}/\d{2}/\d{4}', str(post_date_cell).strip()):
                continue

            date_val = _parse_date(str(post_date_cell).strip())
            desc = _clean_desc(details_cell)
            debit = _clean_amount(debit_cell)
            credit = _clean_amount(credit_cell)
            balance = _clean_amount(balance_cell)

            if not desc or desc.lower() in ('details', ''):
                continue

            if debit > 0 or credit > 0:
                t = Transaction(date=date_val, description=desc,
                                amount=debit if debit > 0 else credit,
                                txn_type='debit' if debit > 0 else 'credit',
                                category=_category(desc, data.statement_type, credit > 0),
                                narration=re.sub(r'\s+', ' ', str(details_cell or '')).strip())
                t._balance = balance
                txns.append(t)

        return txns

    # ------------------------------------------------------------------
    @staticmethod
    def _reconcile(data: StatementData):
        """SBI lists newest first. Rebuild opening/closing from the running balance,
        check every row continues from the previous one, and add an Accounts row."""
        tx = data.transactions
        if not tx:
            return
        if tx[0].date > tx[-1].date:
            tx.reverse()                      # chronological order
        is_loan = 'loan' in data.statement_type
        sign = lambda t: (1 if t.txn_type == 'credit' else -1) * (-1 if is_loan else 1)
        first = tx[0]
        opening = round(first._balance - sign(first) * first.amount, 2)
        closing = tx[-1]._balance
        breaks, bal = 0, opening
        for t in tx:
            bal = round(bal + sign(t) * t.amount, 2)
            if abs(bal - t._balance) > 0.01:
                breaks += 1
                bal = t._balance
        data.opening_balance, data.closing_balance = opening, closing
        label = 'Loan' if is_loan else 'Savings'
        for t in tx:
            t.cardholder = f'{label} {data.account_number[-4:]}'
        row = account_check(data.account_number, data.card_name.replace('SBI ', ''), opening, closing,
                            tx, is_loan=is_loan, period=f'{tx[0].date} to {tx[-1].date}')
        if breaks:
            row['Check'] = f'MISMATCH ({breaks} balance breaks)'
        data.accounts.append(row)


def _category(desc: str, stype: str, credit: bool) -> str:
    u = desc.upper()
    if 'loan' in stype:
        if 'INTEREST' in u:
            return 'Loan interest'
        return 'EMI payment' if credit else 'Disbursement / debit'
    if 'INTEREST' in u and credit:
        return 'Interest'
    if 'ATM' in u:
        return 'Cash withdrawal'
    if u.startswith('UPI'):
        return 'UPI'
    if 'NEFT' in u or 'IMPS' in u or 'RTGS' in u or 'TFR' in u:
        return 'Transfer'
    if 'ACHCR' in u or 'ACH CR' in u or 'NACH' in u:
        return 'Dividend / ACH credit' if credit else 'ACH debit'
    if 'CHARGE' in u or 'CHGS' in u or 'GST' in u or 'FEE' in u:
        return 'Bank charges'
    if 'DIRECT DR' in u:
        return 'EMI / loan transfer'
    return ''
