"""Parser for Axis Bank savings account XLS/XLSX statements.

Format (after LibreOffice XLS→XLSX conversion):
  Header at row 17: SRL NO | Tran Date | CHQNO | PARTICULARS | DR | CR | BAL | SOL
  Date format: DD-MM-YYYY
  DR column = debit amount, CR column = credit amount
"""
import subprocess
import tempfile
import os
import re
from datetime import datetime
from pathlib import Path
import openpyxl
from .categorizer import categorize

ACCOUNT = 'Axis Savings'


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
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def clean_amount(raw) -> float:
    if raw is None:
        return 0.0
    s = str(raw).replace(',', '').strip()
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def parse_axis_savings_xlsx(xlsx_path: str, source_filename: str) -> list[dict]:
    transactions = []
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active

        # Find header row: look for 'Tran Date' or 'CHQNO'
        header_row = None
        col_map = {}
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            row_str = ' '.join(str(c) for c in row if c)
            if 'Tran Date' in row_str or 'PARTICULARS' in row_str:
                header_row = i
                for j, h in enumerate(row):
                    if h is None:
                        continue
                    hl = str(h).strip().lower()
                    if 'tran date' in hl or hl == 'date':
                        col_map['date'] = j
                    elif 'particular' in hl or 'narration' in hl or 'description' in hl:
                        col_map['desc'] = j
                    elif hl == 'dr' or 'withdraw' in hl or hl == 'debit':
                        col_map['dr'] = j
                    elif hl == 'cr' or 'deposit' in hl or hl == 'credit':
                        col_map['cr'] = j
                break

        if header_row is None or 'date' not in col_map:
            return transactions

        date_col = col_map['date']
        desc_col = col_map.get('desc', 3)
        dr_col = col_map.get('dr', 4)
        cr_col = col_map.get('cr', 5)

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
            if not desc or desc in ('-', 'nan', 'None'):
                continue

            dr = clean_amount(cells[dr_col] if dr_col < len(cells) else None)
            cr = clean_amount(cells[cr_col] if cr_col < len(cells) else None)

            if dr > 0:
                amount, txn_type = dr, 'debit'
            elif cr > 0:
                amount, txn_type = cr, 'credit'
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


def parse_axis_savings_file(filepath: str) -> list[dict]:
    fpath = Path(filepath)
    if fpath.suffix.lower() == '.xls':
        xlsx = convert_xls_to_xlsx(str(filepath))
        if not xlsx:
            return []
        try:
            return parse_axis_savings_xlsx(xlsx, fpath.name)
        finally:
            try:
                os.unlink(xlsx)
                os.rmdir(os.path.dirname(xlsx))
            except Exception:
                pass
    else:
        return parse_axis_savings_xlsx(str(filepath), fpath.name)


def load_all_axis_savings(folder: str) -> list[dict]:
    all_txns = []
    p = Path(folder)
    if not p.exists():
        return all_txns
    for f in sorted(p.glob('*.xls')) + sorted(p.glob('*.xlsx')) + sorted(p.glob('*.XLS')):
        all_txns.extend(parse_axis_savings_file(str(f)))
    # Deduplicate
    seen = set()
    unique = []
    for t in all_txns:
        key = (t['date'], t['description'][:50], t['amount'], t['type'])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique
