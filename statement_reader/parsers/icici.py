"""ICICI Bank credit card statement parser (text + OCR for NORM vectorized PDFs)."""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import BaseParser, StatementData, Transaction, account_check, EMIEntry, RewardPoint
from statement_reader.utils.pdf_utils import (extract_text_all_pages, ocr_pages,
                              is_vectorized_pdf, get_page_count)

DATE_FMTS = ['%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %b %y', '%d/%m/%y']


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


def _clean_desc(desc: str) -> str:
    """Strip OCR artefacts from ICICI transaction description."""
    # Remove leading 10-15 digit serial
    desc = re.sub(r'^\d{10,15}\s+', '', desc)
    # Remove reward pts + optional "IN" at end  e.g. "273 IN" or "10)"
    desc = re.sub(r'\s+\d{1,4}[)\s]*\s*(?:IN\s*)?$', '', desc)
    desc = re.sub(r'\s+\bIN\b\s*$', '', desc)
    # Remove pipe artefacts
    desc = desc.replace('|', '').strip()
    return desc.strip()


class ICICIParser(BaseParser):

    def can_parse(self, text: str) -> bool:
        return 'icici' in text.lower()

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = StatementData(
            bank='ICICI Bank',
            source_file=Path(filepath).name,
            statement_type='credit_card',
        )

        vectorized = is_vectorized_pdf(filepath, password)
        n_pages = get_page_count(filepath, password)

        if vectorized:
            # OCR page 1 (has SPENDS OVERVIEW) and possibly page 2
            pages_to_ocr = [1, 2] if n_pages >= 2 else [1]
            raw_pages = ocr_pages(filepath, password, pages=pages_to_ocr)
        else:
            raw_pages = extract_text_all_pages(filepath, password, max_pages=min(n_pages, 10))

        full_text = '\n'.join(raw_pages)
        data.raw_text = full_text

        # ── Detect card product name ──────────────────────────────────────
        data.card_name = self._detect_card_name(full_text)

        # ── Extract header info ───────────────────────────────────────────
        self._extract_header(full_text, data)

        # ── Extract transactions ──────────────────────────────────────────
        data.transactions = self._extract_transactions(full_text, data.card_name)

        # ── Extract reward points ─────────────────────────────────────────
        self._extract_rewards(full_text, data)

        # ── Extract EMIs ──────────────────────────────────────────────────
        self._extract_emis(full_text, data)

        # ── 2026 layout: summary block, card name, EMI table, reconciliation ──
        self._enrich(full_text, data, filepath)
        return data

    # ------------------------------------------------------------------
    @staticmethod
    def _enrich(t: str, data: StatementData, filepath: str):
        A = r'`?\s*([\d,]+\.\d{2})'
        def dt(s):
            try:
                return datetime.strptime(s.strip(), '%B %d, %Y').strftime('%Y-%m-%d')
            except ValueError:
                return ''
        head = '\n'.join(t.split('\n')[:25])
        dates = re.findall(r'^([A-Z][a-z]+ \d{1,2}, \d{4})\s*$', head, re.M)
        if len(dates) >= 2:
            data.statement_date, data.due_date = dt(dates[0]), dt(dates[1])
        m = re.search(r'Statement period\s*:\s*([A-Z][a-z]+ \d{1,2}, \d{4}) to ([A-Z][a-z]+ \d{1,2}, \d{4})', t)
        if m:
            data.from_date, data.to_date = dt(m.group(1)), dt(m.group(2))
        m = re.search(r'Total Amount due\s*\n\s*' + A, t)
        if m:
            data.total_due = _clean_amount(m.group(1))
        m = re.search(r'Minimum Amount due[^\n]*\n\s*' + A, t)
        if m:
            data.minimum_due = _clean_amount(m.group(1))
        m = re.search(r'total amount due is not paid\s*' + A + r'\s*' + A + r'\s*' + A + r'\s*' + A, t)
        if m:
            data.credit_limit = _clean_amount(m.group(1))
            data.available_credit = _clean_amount(m.group(2))
        m = re.search(r'Previous Balance Purchases / Charges Cash Advances Payments / Credits\s*\n\s*'
                      + A + r'\s*' + A + r'\s*' + A + r'\s*' + A, t)
        stated_cr = stated_dr = None
        if m:
            data.opening_balance = _clean_amount(m.group(1))
            stated_dr = round(_clean_amount(m.group(2)) + _clean_amount(m.group(3)), 2)
            stated_cr = _clean_amount(m.group(4))
            data.closing_balance = data.total_due
        m = re.search(r'Total Points earned\*?\s*(\d[\d,]*)', t)
        if m:
            data.reward_earned = int(m.group(1).replace(',', ''))

        # Card product from the file name (…_Retail_Sapphiro_NORM.pdf) and number
        fn = Path(filepath).name
        m = re.search(r'_Retail_([A-Za-z]+)_', fn)
        if m and m.group(1).lower() not in ('norm',):
            prod = {'amazon': 'Amazon Pay'}.get(m.group(1).lower(), m.group(1).title())
            data.card_name = f'ICICI {prod} Credit Card'
        m = re.match(r'^(\d{4}X{8}\d{4})_', fn)
        if m:
            data.card_number = m.group(1)

        # EMI / PERSONAL LOAN ON CREDIT CARDS table
        for m in re.finditer(r'^(.+?) (\d{2}/\d{2}/\d{4}) (\d{2}/\d{2}/\d{4}) (\d+) ([\d,]+\.\d{2}) (\d+) '
                             r'([\d,]+\.\d{2}) ([\d,]+\.\d{2})\s*$', t, re.M):
            if any(e.description.startswith(m.group(1).strip()) and e.start_date == _parse_date(m.group(2))
                   for e in data.emis):
                continue
            data.emis.append(EMIEntry(
                description=f'{m.group(1).strip()} — ₹{_clean_amount(m.group(5)):,.2f}',
                principal=_clean_amount(m.group(7)), emi_amount=_clean_amount(m.group(8)),
                tenure_months=int(m.group(4)), months_remaining=int(m.group(6)),
                start_date=_parse_date(m.group(2)), end_date=_parse_date(m.group(3)),
                ref=f'{m.group(1).strip()} {_parse_date(m.group(2))}', lender='ICICI Bank',
                original_amount=_clean_amount(m.group(5)), outstanding=_clean_amount(m.group(7))))

        if data.opening_balance or stated_dr is not None:
            data.accounts.append(account_check(
                data.card_number, 'Credit card', data.opening_balance, data.total_due,
                data.transactions, is_loan=True, stated_credits=stated_cr, stated_debits=stated_dr,
                period=f'{data.from_date} to {data.to_date}'))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _detect_card_name(self, text: str) -> str:
        t = text.lower()
        if 'sapphiro' in t:
            return 'ICICI Sapphiro CC'
        if 'amazon' in t:
            return 'ICICI Amazon Pay CC'
        if 'aurum' in t:
            return 'ICICI Aurum CC'
        if 'coral' in t:
            return 'ICICI Coral CC'
        if 'rubyx' in t:
            return 'ICICI Rubyx CC'
        if 'platinum' in t:
            return 'ICICI Platinum CC'
        # Try masked card number
        m = re.search(r'(\d{4}[\s-]?[Xx*O]{4,8}[\s-]?\d{4})', text)
        if m:
            return f'ICICI CC {m.group(1)[-4:]}'
        return 'ICICI CC'

    def _extract_header(self, text: str, data: StatementData):
        # Card number (masked)
        m = re.search(r'(\d{4}[\s-]?[Xx*O]{4,8}[\s-]?\d{4})', text)
        if m:
            data.card_number = m.group(1)

        # Statement / billing date
        for pat in [
            r'(?:statement|billing)\s+date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:statement|billing)\s+date[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                data.statement_date = _parse_date(m.group(1))
                break

        # Payment due date
        for pat in [
            r'(?:payment\s+)?due\s+date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(?:payment\s+)?due\s+date[:\s]+(\d{1,2}\s+\w+\s+\d{2,4})',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                data.due_date = _parse_date(m.group(1))
                break

        # Total amount due
        for pat in [
            r'total\s+amount\s+due[:\s]+([\d,]+\.\d{2})',
            r'total\s+due[:\s]+([\d,]+\.\d{2})',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                data.total_due = _clean_amount(m.group(1))
                break

        # Minimum amount due
        m = re.search(r'minimum\s+(?:amount\s+)?due[:\s]+([\d,]+\.\d{2})', text, re.I)
        if m:
            data.minimum_due = _clean_amount(m.group(1))

        # Credit limit
        m = re.search(r'credit\s+limit[:\s]+([\d,]+)', text, re.I)
        if m:
            data.credit_limit = _clean_amount(m.group(1))

        # Available credit
        m = re.search(r'available\s+credit[:\s]+([\d,]+)', text, re.I)
        if m:
            data.available_credit = _clean_amount(m.group(1))

    def _extract_transactions(self, text: str, card_name: str) -> list:
        txns = []
        current_card_suffix = ''

        # Card section header pattern: OOOOXXXXXXXX1234 or 4000XXXXXXXX5678
        card_hdr_pat = re.compile(
            r'^(?:[O0]{4}|[0-9]{4})[Xx*]{8}(\d{4})\s*$', re.IGNORECASE
        )

        # Transaction line: date  serial  description  [pts]  amount  [CR]
        # Flexible to handle OCR noise before the date
        txn_pat = re.compile(
            r'(\d{2}/\d{2}/20\d{2})'          # date DD/MM/YYYY
            r'\s+(\d{10,15})'                   # serial number
            r'\s+(.+?)'                          # description (lazy)
            r'\s+\d{1,5}[)\s]'                  # reward points (may have OCR ')' artefact)
            r'\s*([\d,]+\.\d{2})'               # amount
            r'(\s+CR)?\s*$',                    # optional CR
            re.IGNORECASE
        )

        # Simpler fallback: date followed by amount on same line
        txn_simple = re.compile(
            r'(\d{2}/\d{2}/20\d{2})'
            r'.*?'
            r'([\d,]+\.\d{2})'
            r'(\s+CR)?\s*$',
            re.IGNORECASE
        )

        lines = text.split('\n')
        for line in lines:
            stripped = line.strip()

            # Check card section header
            m_hdr = card_hdr_pat.match(stripped)
            if m_hdr:
                current_card_suffix = m_hdr.group(1)
                continue

            # Skip non-transaction lines
            if not re.search(r'\d{2}/\d{2}/20\d{2}', stripped):
                continue

            # Try full pattern first
            m = txn_pat.search(stripped)
            if m:
                date_val = _parse_date(m.group(1))
                desc = _clean_desc(m.group(3))
                amount = _clean_amount(m.group(4))
                is_cr = bool(m.group(5))

                # Try to get reward pts from before the amount
                pts_m = re.search(r'\s(\d{1,5})[)\s]+' + re.escape(m.group(4)), stripped)
                pts = int(pts_m.group(1)) if pts_m else 0

                # Infer account
                acct = card_name
                if current_card_suffix:
                    acct = f'{card_name} ({current_card_suffix})'

                if amount > 0 and desc:
                    # Skip balance/summary rows
                    if re.match(r'^(Opening|Closing|Total)\s+Balance', desc, re.I):
                        continue
                    txns.append(Transaction(
                        date=date_val,
                        description=desc,
                        amount=amount,
                        txn_type='credit' if is_cr else 'debit',
                        reward_pts=pts,
                        reference=m.group(2),
                        cardholder=f'Card {current_card_suffix}' if current_card_suffix else '',
                        category=_icici_cat(desc, is_cr),
                    ))
                continue

            # Fallback: simpler pattern (for non-NORM PDFs without serial)
            m2 = re.match(
                r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(.+?)\s+([\d,]+\.\d{2})\s*(Dr|Cr|DR|CR)?\s*$',
                stripped
            )
            if m2:
                date_val = _parse_date(m2.group(1))
                desc = m2.group(2).strip()
                amount = _clean_amount(m2.group(3))
                flag = (m2.group(4) or 'Dr').upper()
                if amount > 0 and desc:
                    txns.append(Transaction(
                        date=date_val,
                        description=desc,
                        amount=amount,
                        txn_type='credit' if flag in ('CR', 'C') else 'debit',
                    ))

        return txns

    def _extract_rewards(self, text: str, data: StatementData):
        # Opening reward points
        m = re.search(r'opening\s+(?:reward\s+)?points?[:\s]+([\d,]+)', text, re.I)
        if m:
            data.reward_opening = int(re.sub(r'[^\d]', '', m.group(1)))

        # Points earned
        m = re.search(r'(?:reward\s+)?points?\s+earned[:\s]+([\d,]+)', text, re.I)
        if m:
            data.reward_earned = int(re.sub(r'[^\d]', '', m.group(1)))

        # Points redeemed
        m = re.search(r'(?:reward\s+)?points?\s+redeemed[:\s]+([\d,]+)', text, re.I)
        if m:
            data.reward_redeemed = int(re.sub(r'[^\d]', '', m.group(1)))

        # Points expired
        m = re.search(r'(?:reward\s+)?points?\s+expir\w+[:\s]+([\d,]+)', text, re.I)
        if m:
            data.reward_expired = int(re.sub(r'[^\d]', '', m.group(1)))

        # Closing / available reward points
        for pat in [
            r'closing\s+(?:reward\s+)?points?[:\s]+([\d,]+)',
            r'available\s+(?:reward\s+)?points?[:\s]+([\d,]+)',
            r'(?:reward\s+)?points?\s+balance[:\s]+([\d,]+)',
        ]:
            m = re.search(pat, text, re.I)
            if m:
                data.reward_closing = int(re.sub(r'[^\d]', '', m.group(1)))
                break

        # Expiry date of reward points
        m = re.search(r'points?\s+(?:valid|expir\w+)\s+(?:till|upto|until)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text, re.I)
        if m:
            data.reward_expiry_date = _parse_date(m.group(1))

    def _extract_emis(self, text: str, data: StatementData):
        """Extract EMI / Insta-loan details if present."""
        # Look for EMI conversion block
        emi_section = re.search(
            r'(?:emi|insta\s*loan|convert\w+\s+to\s+emi)[^\n]*\n((?:.*\n){0,30})',
            text, re.I
        )
        if not emi_section:
            return

        block = emi_section.group(1)
        # Try to find EMI rows: description, amount, tenure, monthly EMI
        for line in block.split('\n'):
            m = re.search(
                r'(.+?)\s+([\d,]+\.\d{2})\s+(\d+)\s+months?\s+([\d,]+\.\d{2})',
                line, re.I
            )
            if m:
                data.emis.append(EMIEntry(
                    description=m.group(1).strip(),
                    principal=_clean_amount(m.group(2)),
                    tenure_months=int(m.group(3)),
                    emi_amount=_clean_amount(m.group(4)),
                ))


def _icici_cat(desc: str, credit: bool) -> str:
    u = desc.upper()
    if credit and ('PAYMENT' in u or 'BBPS' in u):
        return 'Payment'
    if credit and 'SURCHARGE' in u:
        return 'Refund (fuel surcharge)'
    if 'AMORTIZATION' in u or 'EMI' in u:
        return 'EMI'
    if 'IGST' in u or 'CGST' in u or 'SGST' in u or 'FEE' in u or 'HANDLING' in u or 'SURCHARGE' in u:
        return 'Fees & Taxes'
    return ''
