"""Parser for HDFC Bank savings account XLS statements.

Format (after LibreOffice XLS→XLSX conversion):
  Header at row 21: Date | Narration | Chq./Ref.No. | Value Dt | Withdrawal Amt. | Deposit Amt. | Closing Balance
  Date format: DD/MM/YY (e.g., '01/04/25')
  Withdrawal Amt = debit, Deposit Amt = credit
"""
import subprocess
import tempfile
import os
import re
from datetime import datetime
from pathlib import Path
import openpyxl
from .categorizer import categorize

ACCOUNT = 'HDFC Savings'


def convert_xls_to_xlsx(xls_path: str) -> str | None:
    out_dir = tempfile.mkdtemp()
    try:
        subprocess.run(
            ['libreoffice', '--headless', '--convert-to', 'xlsx', '--outdir', out_dir, xls_path],
            capture_output=True, text=True, timeout=60
        )
        stem = Path(xls_path).stem
        out_file = os.path.join(out_dir, stem + '.xlsx')
        if os.path.exists(out_file):
            return out_file
    except Exception:
        pass
    return None


def normalize_date(raw) -> str:
    if hasattr(raw, 'strftime'):
        return raw.strftime('%Y-%m-%d')
    s = str(raw).strip()
    for fmt in ('%d/%m/%y', '%d/%m/%Y', '%d-%m-%y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def clean_amount(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).replace(',', '').replace('*', '').strip()
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def parse_hdfc_savings_xlsx(xlsx_path: str, source_filename: str) -> list[dict]:
    transactions = []
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active

        # Find header row: look for 'Narration' or 'Withdrawal Amt'
        header_row = None
        col_map = {}
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            row_str = ' '.join(str(c) for c in row if c)
            if 'Narration' in row_str and ('Withdrawal' in row_str or 'Deposit' in row_str):
                header_row = i
                for j, h in enumerate(row):
                    if h is None:
                        continue
                    hl = str(h).strip().lower()
                    if hl == 'date' and 'date' not in col_map:
                        col_map['date'] = j
                    elif 'narration' in hl or 'description' in hl:
                        col_map['desc'] = j
                    elif 'withdrawal' in hl or 'debit' in hl:
                        col_map['withdrawal'] = j
                    elif 'deposit' in hl or 'credit' in hl:
                        col_map['deposit'] = j
                break

        if header_row is None or 'date' not in col_map:
            return transactions

        date_col = col_map['date']
        desc_col = col_map.get('desc', 1)
        wd_col = col_map.get('withdrawal', 4)
        dep_col = col_map.get('deposit', 5)

        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            cells = list(row)
            if not cells or all(c is None for c in cells):
                continue

            date_val = cells[date_col] if date_col < len(cells) else None
            if not date_val:
                continue
            date_str = normalize_date(date_val)
            if not re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                continue

            desc = str(cells[desc_col]).strip() if desc_col < len(cells) and cells[desc_col] else ''
            if not desc or desc.startswith('*') or desc in ('-', 'nan', 'None'):
                continue

            wd = clean_amount(cells[wd_col] if wd_col < len(cells) else None)
            dep = clean_amount(cells[dep_col] if dep_col < len(cells) else None)

            if wd > 0:
                amount, txn_type = wd, 'debit'
            elif dep > 0:
                amount, txn_type = dep, 'credit'
            else:
                continue

            transactions.append({
                'date': date_str,
                'description': desc,
                'amount': amount,
                'type': txn_type,
                'category': categorize(desc),
                'account': ACCOUNT,
                'source_file': source_filename,
            })
    except Exception:
        pass
    return transactions


def parse_hdfc_savings_file(filepath: str) -> list[dict]:
    fpath = Path(filepath)
    if fpath.suffix.lower() == '.xls':
        xlsx = convert_xls_to_xlsx(str(filepath))
        if not xlsx:
            return []
        try:
            return parse_hdfc_savings_xlsx(xlsx, fpath.name)
        finally:
            try:
                os.unlink(xlsx)
                os.rmdir(os.path.dirname(xlsx))
            except Exception:
                pass
    else:
        return parse_hdfc_savings_xlsx(str(filepath), fpath.name)


def load_all_hdfc_savings(folder: str) -> list[dict]:
    all_txns = []
    p = Path(folder)
    if not p.exists():
        return all_txns
    for f in sorted(p.glob('*.xls')) + sorted(p.glob('*.xlsx')) + sorted(p.glob('*.XLS')):
        all_txns.extend(parse_hdfc_savings_file(str(f)))
    # Deduplicate
    seen = set()
    unique = []
    for t in all_txns:
        key = (t['date'], t['description'][:50], t['amount'], t['type'])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique
