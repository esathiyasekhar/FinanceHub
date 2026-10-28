"""Parser for Bank of India Savings Account CSV statements."""
import csv
from datetime import datetime
from pathlib import Path
from .categorizer import categorize

ACCOUNT = 'BOI Savings Account'


def normalize_date(raw: str) -> str:
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return raw.strip()


def parse_boi_csv(filepath: str) -> list[dict]:
    """Parse Bank of India CSV statement.

    Header: 6–8 metadata lines, blank line, then:
    Sr No, Date, Remarks, Debit, Credit, Balance Amount
    """
    transactions = []
    try:
        with open(filepath, encoding='utf-8-sig', errors='replace') as f:
            reader = csv.reader(f)
            header_found = False
            col = {}

            for row in reader:
                if not row or all(c.strip() == '' for c in row):
                    continue

                row_lower = [c.strip().lower() for c in row]
                join = ' '.join(row_lower)

                # Find data header row
                if not header_found and 'date' in join and ('debit' in join or 'credit' in join):
                    header_found = True
                    for i, h in enumerate(row_lower):
                        if 'date' in h:
                            col['date'] = i
                        elif 'remark' in h or 'narration' in h or 'description' in h:
                            col['desc'] = i
                        elif 'debit' in h:
                            col['debit'] = i
                        elif 'credit' in h:
                            col['credit'] = i
                    continue

                if not header_found:
                    continue

                try:
                    date_val = row[col.get('date', 1)].strip()
                    desc = row[col.get('desc', 2)].strip()
                    if not desc or not date_val:
                        continue

                    date_str = normalize_date(date_val)

                    debit_val = row[col.get('debit', 3)].strip() if col.get('debit') is not None else ''
                    credit_val = row[col.get('credit', 4)].strip() if col.get('credit') is not None else ''

                    amount = 0.0
                    txn_type = 'debit'

                    if debit_val and debit_val != '0' and debit_val != '0.00' and debit_val != '':
                        amount = float(debit_val.replace(',', ''))
                        txn_type = 'debit'
                    elif credit_val and credit_val != '0' and credit_val != '0.00' and credit_val != '':
                        amount = float(credit_val.replace(',', ''))
                        txn_type = 'credit'

                    if amount == 0:
                        continue

                    transactions.append({
                        'date': date_str,
                        'description': desc,
                        'amount': amount,
                        'type': txn_type,
                        'category': categorize(desc),
                        'account': ACCOUNT,
                        'source_file': Path(filepath).name,
                    })
                except (IndexError, ValueError):
                    continue

    except Exception as e:
        print(f'[BOI] Error: {e}')

    return transactions


def load_all_boi(folder: str) -> list[dict]:
    all_txns = []
    p = Path(folder)
    for f in sorted(p.glob('*.csv')):
        all_txns.extend(parse_boi_csv(str(f)))
    return all_txns
