"""Check how a bank / card statement is read — use this when adding a bank.

    python tools/test_statement.py "<file.pdf>" [password] [--text]

Shows the detection scores of every parser, the parser chosen, the header figures, the balance check
per account (opening ± transactions = closing) and the first transactions. Nothing is saved."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))     # Finance Hub: <hub>/statement_reader/tools → <hub>
try:                                     # inside Finance Hub the engine is the package 'statement_reader'
    from statement_reader.parsers import auto_detect_parser, detect_scores
    from statement_reader.utils.pdf_utils import extract_text_all_pages
except ImportError:                      # desktop Statement Reader
    from parsers import auto_detect_parser, detect_scores
    from utils.pdf_utils import extract_text_all_pages


def main(path, password=''):
    page1 = (extract_text_all_pages(path, password, max_pages=1) or [''])[0]
    print('Detection scores (page 1):', ', '.join(f'{n} {s}' for s, n in detect_scores(page1)) or 'none')
    parser = auto_detect_parser(path, password)
    print('Parser chosen:', type(parser).__name__,
          '  ← no dedicated parser: add one (parsers/README.md)' if type(parser).__name__ == 'GenericParser' else '')
    d = parser.parse(path, password)
    print(f'Bank: {d.bank} | Document: {d.card_name} | Type: {d.statement_type} | Period: {d.from_date} – {d.to_date}')
    print(f'Opening {d.opening_balance} | Closing {d.closing_balance} | Total due {d.total_due} | Transactions {len(d.transactions)}')
    for a in (d.accounts or []):
        print(f"  Account {a.get('Account')}: {a.get('Check')}  {a.get('Note', '')}")
    if not d.accounts:
        print('  No balance check (add account_check() to the parser so every statement is verified)')
    for t in d.transactions[:15]:
        print(f'  {t.date}  {t.txn_type:6} {t.amount:>12,.2f}  {t.description[:60]}')
    if len(d.transactions) > 15:
        print(f'  … {len(d.transactions) - 15} more')
    if '--text' in sys.argv:
        print('\n----- page 1 text -----\n' + page1)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--text']
    main(args[0], args[1] if len(args) > 1 else '')
