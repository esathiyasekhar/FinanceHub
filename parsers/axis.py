"""Parser for Axis Bank Credit Card XLSX statements."""
import re
from datetime import datetime
from pathlib import Path
import openpyxl
from .categorizer import categorize

ACCOUNT = 'Axis Select CC'


def normalize_date(raw) -> str:
    """Handle multiple date formats including Axis's "DD Mon 'YY" style."""
    if hasattr(raw, 'strftime'):
        return raw.strftime('%Y-%m-%d')
    s = str(raw).strip()
    # Remove right single quote before 2-digit year: "17 Mar '26" → "17 Mar 26"
    s_clean = s.replace("'", "").strip()
    for fmt in ('%d %b %y', '%d %b %Y', '%d-%b-%y', '%d-%b-%Y',
                '%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s_clean, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def clean_amount(raw) -> float:
    """Strip ₹, commas, spaces from amount strings like '₹ 1,025.40'."""
    if raw is None:
        return 0.0
    s = str(raw).replace('₹', '').replace(',', '').strip()
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def parse_axis_xlsx(filepath: str) -> list[dict]:
    """Parse a single Axis CC XLSX file and return list of transaction dicts."""
    transactions = []
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active

        header_row = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            row_str = ' '.join(str(c) for c in row if c)
            # Axis format: header has 'Date', 'Transaction Details', 'Amount', 'Debit/Credit'
            if 'Date' in row_str and ('Debit/Credit' in row_str or 'Amount' in row_str):
                header_row = i
                break

        if header_row is None:
            return transactions

        # Map columns from header
        header = list(ws.iter_rows(min_row=header_row + 1, max_row=header_row + 1,
                                   values_only=True))[0]
        col_map = {}
        for i, h in enumerate(header):
            if h is None:
                continue
            hl = str(h).lower()
            if 'date' in hl and 'date' not in col_map:
                col_map['date'] = i
            elif 'detail' in hl or ('transaction' in hl and 'date' not in hl):
                col_map['desc'] = i
            elif 'amount' in hl:
                col_map['amount'] = i
            elif 'debit' in hl and 'credit' in hl:
                col_map['type'] = i

        # Fallback column positions for known Axis layout
        # Row: Date | Transaction Details | (empty) | Amount (INR) | Debit/Credit | (empty)
        date_col = col_map.get('date', 0)
        desc_col = col_map.get('desc', 1)
        amt_col = col_map.get('amount', 3)
        type_col = col_map.get('type', 4)

        for row in ws.iter_rows(min_row=header_row + 2, values_only=True):
            if not row or all(c is None for c in row):
                continue
            cells = list(row)
            try:
                date_val = cells[date_col] if date_col < len(cells) else None
                if not date_val:
                    continue

                # Multi-line cells: Transaction Details may contain newlines
                desc_raw = cells[desc_col] if desc_col < len(cells) else ''
                desc = str(desc_raw).replace('\n', ' ').strip() if desc_raw else ''

                amount = clean_amount(cells[amt_col] if amt_col < len(cells) else None)
                if amount == 0 or not desc:
                    continue

                # Type: "Debit" or "Credit"
                type_raw = str(cells[type_col]).strip() if type_col < len(cells) and cells[type_col] else 'Debit'
                txn_type = 'credit' if 'credit' in type_raw.lower() else 'debit'

                date_str = normalize_date(date_val)
                transactions.append({
                    'date': date_str,
                    'description': desc,
                    'amount': amount,
                    'type': txn_type,
                    'category': categorize(desc),
                    'account': ACCOUNT,
                    'source_file': Path(filepath).name,
                })
            except Exception:
                continue
    except Exception:
        pass
    return transactions


def load_all_axis(folder: str) -> list[dict]:
    """Load all Axis XLSX files from a folder."""
    all_txns = []
    p = Path(folder)
    for f in sorted(p.glob('*.xlsx')):
        all_txns.extend(parse_axis_xlsx(str(f)))
    # Deduplicate by (date, description, amount, type)
    seen = set()
    unique = []
    for t in all_txns:
        key = (t['date'], t['description'][:50], t['amount'], t['type'])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique
