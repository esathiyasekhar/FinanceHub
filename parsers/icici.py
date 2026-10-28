"""Parser for ICICI Bank Credit Card CSV statements."""
import csv
import re
from datetime import datetime
from pathlib import Path
from .categorizer import categorize

ACCOUNT_MAP = {
    'amazon': 'ICICI Amazon Pay CC',
    'sapphiro': 'ICICI Sapphiro CC',
}


def detect_account(filename: str, card_line: str = '') -> str:
    fn = filename.lower()
    for key, name in ACCOUNT_MAP.items():
        if key in fn:
            return name
    # Try to detect from masked card number line (e.g. "4000 XXXX XXXX 1234")
    # Amazon Pay ICICI: ends in 1009
    if '1009' in card_line:
        return 'ICICI Amazon Pay CC'
    # Sapphiro: ends in 2007 or account 31356892
    if '2007' in card_line or '6892' in card_line or '31356892' in card_line:
        return 'ICICI Sapphiro CC'
    return 'ICICI CC'


def normalize_date(raw: str) -> str:
    # Handles DD-Mon-YY (ICICI uses 05-Apr-25), DD-Mon-YYYY, DD/MM/YYYY, DD-MM-YYYY
    for fmt in ('%d-%b-%y', '%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return raw.strip()


def parse_icici_csv(filepath: str) -> list[dict]:
    """Parse ICICI CC CSV statement. Handles quoted fields for amounts with commas."""
    transactions = []

    # Pre-scan file to find account number / masked card line for account detection
    card_line = ''
    try:
        with open(filepath, encoding='utf-8-sig', errors='replace') as fh:
            for line in fh:
                stripped = line.strip()
                if re.match(r'^\d{4}[\s-]', stripped) or re.match(r'^0000[\s-]', stripped):
                    card_line = stripped
                    break
                # Also check Accountno line
                if 'accountno' in stripped.lower():
                    acc_match = re.search(r'(\d{8,})', stripped)
                    if acc_match:
                        card_line = acc_match.group(1)
    except Exception:
        pass
    account = detect_account(Path(filepath).name, card_line)

    with open(filepath, encoding='utf-8-sig', errors='replace') as f:
        reader = csv.reader(f)
        header_row = None
        header_idx = {}

        for row in reader:
            if not row or all(c.strip() == '' for c in row):
                continue
            # Capture masked card number rows like "4000 XXXX XXXX 1234,,,,,,"
            if re.match(r'^\d{4}[\s-][Xx0]{4}', row[0].strip()):
                card_line = row[0].strip()
                continue
            # Find header row
            row_join = ' '.join(row).lower()
            if 'date' in row_join and ('debit' in row_join or 'amount' in row_join or 'transaction' in row_join):
                header_row = [c.strip().lower() for c in row]
                # Map column names — ICICI format:
                # Date, Sr.No., Transaction Details, Reward Point Header, Intl.Amount, Amount(in Rs), BillingAmountSign
                for i, h in enumerate(header_row):
                    if h == 'date':
                        header_idx['date'] = i
                    elif 'transaction' in h and 'detail' in h:
                        header_idx['desc'] = i
                    elif 'debit' in h and 'credit' not in h and 'amount' not in h:
                        header_idx['debit'] = i
                    elif 'credit' in h and 'debit' not in h and 'amount' not in h:
                        header_idx['credit'] = i
                    elif 'amount' in h and 'billing' not in h and 'intl' not in h:
                        header_idx['amount'] = i
                # Now that we may have seen the card line, detect account
                account = detect_account(Path(filepath).name, card_line)
                continue

            if header_row is None:
                continue

            try:
                date_str = normalize_date(row[header_idx.get('date', 0)])
                desc = row[header_idx.get('desc', 2)].strip() if len(row) > header_idx.get('desc', 2) else ''

                if not desc or date_str == '':
                    continue

                # Parse amount
                debit_idx = header_idx.get('debit')
                credit_idx = header_idx.get('credit')
                amount_idx = header_idx.get('amount')

                amount = 0.0
                txn_type = 'debit'

                if debit_idx is not None and credit_idx is not None:
                    debit_str = row[debit_idx].strip() if len(row) > debit_idx else ''
                    credit_str = row[credit_idx].strip() if len(row) > credit_idx else ''
                    if debit_str and debit_str != '0' and debit_str != '0.00':
                        amount = float(debit_str.replace(',', ''))
                        txn_type = 'debit'
                    elif credit_str and credit_str != '0' and credit_str != '0.00':
                        amount = float(credit_str.replace(',', ''))
                        txn_type = 'credit'
                elif amount_idx is not None and len(row) > amount_idx:
                    raw_amt = row[amount_idx].strip()
                    if raw_amt:
                        amount = abs(float(raw_amt.replace(',', '')))
                        txn_type = 'credit' if float(raw_amt.replace(',', '')) < 0 else 'debit'

                if amount == 0:
                    continue

                transactions.append({
                    'date': date_str,
                    'description': desc,
                    'amount': amount,
                    'type': txn_type,
                    'category': categorize(desc),
                    'account': account,
                    'source_file': Path(filepath).name,
                })
            except (IndexError, ValueError):
                continue

    return transactions


def load_all_icici(folder: str) -> list[dict]:
    all_txns = []
    p = Path(folder)
    for f in sorted(p.glob('*.csv')):
        all_txns.extend(parse_icici_csv(str(f)))
    for f in sorted(p.glob('*.CSV')):
        all_txns.extend(parse_icici_csv(str(f)))
    # Deduplicate by (date, description, amount, account)
    seen = set()
    unique = []
    for t in all_txns:
        key = (t['date'], t['description'][:50], t['amount'], t['account'])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique
