"""ITR-relevant summary for one financial year, built from the Hub's classified data.

For reference only — figures come from the statements and contract notes imported into the Hub;
always check them against Form 16, Form 26AS / AIS and the broker's capital-gains statement.
"""
from collections import defaultdict
from datetime import date, datetime


def fy_options(con):
    """[(label, start, end)] for the current FY and every FY that has data (newest first)."""
    today = date.today()
    y = today.year if today.month >= 4 else today.year - 1
    years = {y}
    for (d,) in con.execute("SELECT date FROM transactions UNION SELECT trade_date FROM inv_trades"):
        try:
            dd = datetime.strptime(d[:10], '%Y-%m-%d').date()
        except (TypeError, ValueError):
            continue
        years.add(dd.year if dd.month >= 4 else dd.year - 1)
    return [(f'FY {str(a)[-2:]}-{str(a + 1)[-2:]}', f'{a}-04-01', f'{a + 1}-03-31') for a in sorted(years, reverse=True)]


def _paths(con):
    import classifier as C
    _, by_id = C.load_tree(con)
    return by_id


def _sum_by_path(con, start, end, by_id, kind):
    """{(Head, Sub-head, Item): net} for one kind (income: in − out; expense / transfer debits)."""
    out = defaultdict(float)
    try:
        companies = [r[0] for r in con.execute("SELECT name FROM entities WHERE name<>'Personal' AND COALESCE(role,'book')='book'")]
    except Exception:  # noqa: BLE001
        companies = []
    ph = ','.join('?' * len(companies)) or "''"
    for r in con.execute('SELECT t.category_id, t.type, t.amount FROM transactions t JOIN categories c ON c.id=t.category_id '
                         f"WHERE c.kind=? AND t.date BETWEEN ? AND ? AND COALESCE(NULLIF(t.entity,''),'Personal') NOT IN ({ph}) "
                         "AND COALESCE(t.reimb_payer,'')=''", (kind, start, end, *companies)):
        n = by_id.get(r['category_id'])
        if not n:
            continue
        full = n['path'].split(' › ')
        p = full[1:] + ['', '', '']
        if full[0] not in ('Income', 'Expenses', 'Transfers', 'Investments'):    # 1.9: the user's own top-level group
            p[0] = f"{full[0]} › {p[0]}" if p[0] else full[0]                       # never mixed with a built-in head
        sign = 1 if (r['type'] == 'credit') == (kind == 'income') else -1
        out[tuple(p[:3])] += sign * r['amount']
    return out


def capital_gains(con, start, end):
    """FIFO over all broker trades; gains on sells inside the FY split short / long term (> 12 months).
    Charges are added to the cost of buys and taken off the proceeds of sells."""
    lots = defaultdict(list)            # security_id → [[qty, unit_cost, date]]
    res = {'stcg': 0.0, 'ltcg': 0.0, 'sell_value': 0.0, 'unmatched_qty': 0.0, 'unmatched_value': 0.0, 'rows': []}
    names = {r[0]: (r[2] or r[1]) for r in con.execute('SELECT id, symbol, name FROM inv_securities')}
    for t in con.execute('SELECT * FROM inv_trades ORDER BY trade_date, id'):
        sid, q = t['security_id'], t['qty']
        if t['side'] == 'buy':
            lots[sid].append([q, (q * t['price'] + (t['charges'] or 0)) / q, t['trade_date']])
            continue
        unit_proceeds = (q * t['price'] - (t['charges'] or 0)) / q
        in_fy = start <= t['trade_date'] <= end
        remaining = q
        while remaining > 1e-9 and lots[sid]:
            lot = lots[sid][0]
            take = min(remaining, lot[0])
            gain = take * (unit_proceeds - lot[1])
            held = (datetime.strptime(t['trade_date'], '%Y-%m-%d') - datetime.strptime(lot[2], '%Y-%m-%d')).days
            if in_fy:
                res['ltcg' if held > 365 else 'stcg'] += gain
                res['rows'].append({'name': names.get(sid, '?'), 'date': t['trade_date'], 'qty': take, 'bought': lot[2],
                                    'gain': round(gain, 2), 'term': 'Long' if held > 365 else 'Short'})
            lot[0] -= take
            remaining -= take
            if lot[0] <= 1e-9:
                lots[sid].pop(0)
        if in_fy:
            res['sell_value'] += q * unit_proceeds
            if remaining > 1e-9:
                res['unmatched_qty'] += remaining
                res['unmatched_value'] += remaining * unit_proceeds
                res['rows'].append({'name': names.get(sid, '?'), 'date': t['trade_date'], 'qty': remaining, 'bought': None,
                                    'gain': None, 'term': 'No buy in the Hub'})
    for k in ('stcg', 'ltcg', 'sell_value', 'unmatched_value'):
        res[k] = round(res[k], 2)
    return res


def summary(con, start, end):
    by_id = _paths(con)
    inc = _sum_by_path(con, start, end, by_id, 'income')
    exp = _sum_by_path(con, start, end, by_id, 'expense')
    trf = _sum_by_path(con, start, end, by_id, 'transfer')

    def pick(d, head=None, sub=None, item=None):
        return round(sum(v for (h, s, i), v in d.items()
                         if (head is None or h == head) and (sub is None or s == sub) and (item is None or i == item)), 2)

    income = [
        ('Salary / consultancy fees (employers & clients)', pick(inc, 'Salary & Remuneration')),
        ('Pension', pick(inc, 'Pension & Government')),
        ('From your own business', pick(inc, 'Business Income')),
        ('Savings / FD interest', pick(inc, 'Investment Income', 'Interest')),
        ('Dividends', pick(inc, 'Investment Income', 'Dividends')),
        ('Receipts from people', pick(inc, 'Receipts from People')),
        ('Other income (to review)', pick(inc, 'Other Income')),
    ]
    deductions = [
        ('Life insurance premium (80C)', pick(exp, 'Insurance', 'Life insurance')),
        ('Health insurance premium (80D)', pick(exp, 'Insurance', 'Health insurance')),
        ('PMSBY / PMJJBY', pick(exp, 'Insurance', 'Government schemes')),
        ('Tuition / education fees (80C)', pick(exp, 'Education', 'Fees')),
        ('Home loan interest (24b)', pick(exp, 'Loans & EMI', 'Interest', 'Home loan interest')),
        ('Home loan principal (80C) — EMIs paid less interest',
         round(max(0.0, -pick(trf, 'Loan repayments', 'Principal', 'Home loan') - pick(exp, 'Loans & EMI', 'Interest', 'Home loan interest')), 2)),
        ('Donations (80G — check eligibility)', pick(exp, 'Family & Personal', 'Gifts & donations', 'Donations')),
    ]
    taxes = [('Income tax paid (advance / self-assessment)', pick(exp, 'Taxes', 'Income tax'))]
    try:
        cg = capital_gains(con, start, end)
    except Exception:  # noqa: BLE001 — no investments tables yet
        cg = {'stcg': 0, 'ltcg': 0, 'sell_value': 0, 'unmatched_qty': 0, 'unmatched_value': 0, 'rows': []}
    review = con.execute("SELECT COUNT(*) FROM transactions t JOIN categories c ON c.id=t.category_id "
                         "WHERE c.name='To review' AND t.date BETWEEN ? AND ?", (start, end)).fetchone()[0]
    return {'income': income, 'deductions': deductions, 'taxes': taxes, 'cg': cg, 'to_review': review}
