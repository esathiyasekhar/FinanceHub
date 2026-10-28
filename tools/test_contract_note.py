"""Check how the Hub reads a contract note — use this when adding a broker.

    python tools/test_contract_note.py "<file.pdf>" [password]

Prints the broker / reader chosen, every trade, the levies, and the reconciliation check
(trades = printed obligation; obligation + charges = printed net amount). Nothing is saved."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import investments as I          # noqa: E402
import contract_notes as CN      # noqa: E402


def main(path, password=''):
    pages, _ = I.open_pdf_text(Path(path), [password])
    text = '\n'.join(pages)
    cn = CN.read(text)
    print(f'Reader : {cn.reader}   Broker: {cn.broker or "?"}   Contract no: {cn.contract_no}   Trade date: {cn.trade_date}')
    for t in cn.trades:
        print(f"  {t['side'].upper():4} {t['qty']:>8g} @ {t['price']:>10,.2f}  {t['isin']}  {t['name'][:34]:34} {t['exchange']}  #{t['trade_id']}")
    print(f'Buys ₹{cn.buys:,.2f}  Sells ₹{cn.sells:,.2f}  Obligation ₹{cn.obligation}  Net ₹{cn.net}')
    print('Levies :', ', '.join(f'{k} {v:,.2f}' for k, v in cn.levies.items()) or '—', f'  (charges ₹{cn.charges:,.2f})')
    print(f'Check  : {cn.check} — {cn.check_detail}')
    for w in cn.warnings:
        print('  !', w)
    if '--text' in sys.argv:
        print('\n----- text -----\n' + text)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--text']
    main(args[0], args[1] if len(args) > 1 else '')
