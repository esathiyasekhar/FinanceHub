"""HDFC Bank credit card statement parser — 2025/26 template.

Used by all current HDFC cards (Biz Power, Tata Neu Infinity/Plus, Regalia, Millennia, ...).

Layout notes:
  * The rupee glyph extracts as the letter 'C'  ->  'C1,12,728.00'
  * Row:  'DD/MM/YYYY| HH:MM  description  [+/- rewards]  [+] C amount  l'
          a '+' immediately before 'C amount' means CREDIT
  * GST rows wrap:  'CGST-... (Ref#' / 'DD/MM/YYYY| 00:00 C 248.13 l' / '0999...)'
  * Header line 'DATE & TIME ...' is followed by the cardholder name (add-on cards repeat this)
  * 'EMI ' prefix on a purchase = eligible for EMI conversion (marker, not merchant name)
  * Smart EMI Loan Summary table lists every active loan
"""
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from statement_reader.parsers.base import StatementData, Transaction, EMIEntry, RewardPoint, account_check

AMT = r'[\d,]+\.\d{2}'
RS = r'(?:C|₹|`|Rs\.?)\s*'
ROW = re.compile(
    rf'^(\d{{2}}/\d{{2}}/\d{{4}})\s*\|\s*(\d{{1,2}}:\d{{2}})\s*(.*?)\s*'
    rf'(?:([+-])\s*(\d[\d,]*)\s+)?(\+\s*)?{RS}({AMT})\s*(?:l)?\s*$')
NAME_LINE = re.compile(r'^[A-Z][A-Z .]{2,40}$')


def _d(s: str) -> str:
    s = s.strip()
    for fmt in ('%d %b, %Y', '%d %b %Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return s


def _a(s) -> float:
    try:
        return round(float(re.sub(r'[^\d.]', '', str(s))), 2)
    except (ValueError, TypeError):
        return 0.0


def _i(s) -> int:
    try:
        return int(re.sub(r'[^\d-]', '', str(s)) or 0)
    except ValueError:
        return 0


def _add_months(iso: str, n: int) -> str:
    try:
        d = datetime.strptime(iso, '%Y-%m-%d')
        y, m = divmod(d.month - 1 + n, 12)
        return f'{d.year + y}-{m + 1:02d}'
    except ValueError:
        return ''


def is_hdfc_cc_template(page1_text: str) -> bool:
    return 'Credit Card No.' in page1_text and 'HDFC Bank Credit Cards' in page1_text


def parse_hdfc_cc(pages: list, filepath: str) -> StatementData:
    text = '\n'.join(pages).replace('(cid:1)', ' ')
    # stop before the long 'Important Information' boilerplate
    body = text.split('Important Information')[0] if 'Important Information' in text else text

    data = StatementData(bank='HDFC Bank', statement_type='credit_card',
                         source_file=Path(filepath).name)
    data.raw_text = body

    first = pages[0].strip().split('\n')[0] if pages else ''
    name = re.sub(r'\s*(HDFC Bank)?\s*Credit Card Statement.*$', '', first, flags=re.I).strip()
    data.card_name = f'HDFC {name}' if name and 'hdfc' not in name.lower() else (name or 'HDFC Credit Card')
    if 'tata neu' in first.lower():
        data.bank = 'HDFC Bank (Tata Neu)'

    _header(body, data)
    _rewards(body, data)
    data.transactions = _transactions(body)
    _emis(body, data)
    m = re.search(rf'{RS}({AMT})\s+{RS}({AMT})\s*\+\s*{RS}({AMT})\s*\+\s*{RS}({AMT})\s*=', body)
    if m:
        data.accounts.append(account_check(
            data.card_number, 'Credit card', _a(m.group(1)), data.total_due, data.transactions,
            is_loan=True, stated_credits=_a(m.group(2)),
            stated_debits=round(_a(m.group(3)) + _a(m.group(4)), 2),
            period=f'{data.from_date} to {data.to_date}', tol=1.0))   # total due is rounded to ₹1
    return data


def _header(t: str, data: StatementData):
    m = re.search(r'Credit Card No\.\s*(\S+)', t)
    if m:
        data.card_number = m.group(1)
    m = re.search(r'Alternate Account Number\s*(\d+)', t)
    if m:
        data.account_number = m.group(1)
    m = re.search(r'Statement Date\s+(\d{1,2} \w{3},? \d{4})', t)
    if m:
        data.statement_date = _d(m.group(1))
    m = re.search(r'Billing Period\s+(\d{1,2} \w{3},? \d{4})\s*-\s*(\d{1,2} \w{3},? \d{4})', t)
    if m:
        data.from_date, data.to_date = _d(m.group(1)), _d(m.group(2))

    m = re.search(rf'TOTAL AMOUNT DUE[\s\S]{{0,120}}?{RS}({AMT})', t)
    if m:
        data.total_due = _a(m.group(1))
    # prev dues, payments/credits, purchases/debits, finance charges
    m = re.search(rf'{RS}({AMT})\s+{RS}({AMT})\s*\+\s*{RS}({AMT})\s*\+\s*{RS}({AMT})\s*=', t)
    if m:
        data.opening_balance = _a(m.group(1))
        data.closing_balance = data.total_due
    m = re.search(rf'MINIMUM DUE\s+DUE DATE\s*\n\s*{RS}({AMT})\s+(\d{{1,2}} \w{{3}},? \d{{4}})', t)
    if m:
        data.minimum_due = _a(m.group(1))
        data.due_date = _d(m.group(2))
    m = re.search(rf'DUE DATE\s*\n[^\n]*\n\s*{RS}([\d,]+(?:\.\d{{2}})?)\s+{RS}([\d,]+(?:\.\d{{2}})?)\s+{RS}([\d,]+(?:\.\d{{2}})?)', t)
    if m:
        data.credit_limit = _a(m.group(1))
        data.available_credit = _a(m.group(2))


def _rewards(t: str, data: StatementData):
    # Biz Power : 'Reward Points Opening Balance ... Adjusted/Lapsed' / '10,402 Points Earned' / '8,841 2,616 0 1,055'
    # Tata Neu  : 'NeuCoins with Bank Opening ... Adjusted/Lapsed' / 'Bank (Base+Bonus) to Tata Neu' / '176 575 176 575 0'
    # Value order on both: closing, opening, earned, redeemed/transferred, adjusted/lapsed
    m = re.search(r'(Reward Points|NeuCoins with Bank)\s+Opening[^\n]*Adjusted/Lapsed\s*\n((?:[^\n]*\n){1,3})', t)
    if m:
        nums = re.findall(r'(?<![\w.])\d[\d,]*(?![\w.%])', m.group(2))
        if len(nums) >= 5:
            closing, opening, earned, redeemed, lapsed = (_i(x) for x in nums[:5])
            data.reward_closing, data.reward_opening = closing, opening
            data.reward_earned, data.reward_redeemed, data.reward_expired = earned, redeemed, lapsed
    unit = 'NeuCoins' if m and 'NeuCoins' in m.group(1) else 'pts'
    # Bonus programme breakdown: '1 Add_BigBasket 71'  /  '1 Biz Power 5X RP Biz Spends R1 1 pts'
    blk = re.search(r'(?:Bonus NeuCoins Summary|Rewards Program Points Summary)\s*\n[^\n]*\n((?:\d+ [^\n]+\n)+)', t)
    if blk:
        for line in blk.group(1).splitlines():
            r = re.match(r'^\d+\s+(.+?)\s+(\d[\d,]*)\s*(?:pts)?$', line.strip())
            if r:
                data.reward_details.append(RewardPoint(description=f'{r.group(1)} ({unit})',
                                                       points_earned=_i(r.group(2)),
                                                       date=data.statement_date))


def _transactions(t: str) -> list:
    lines = [l.strip() for l in t.split('\n')]
    txns, holder, section = [], '', 'Domestic'
    consumed = set()
    prev_nonrow = ''
    for i, line in enumerate(lines):
        if i in consumed or not line:
            continue
        if line.startswith(('Domestic Transactions', 'International Transactions')):
            section = line.split()[0]
            continue
        if line.startswith('DATE & TIME'):
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            if NAME_LINE.match(nxt) and not re.search(r'\d', nxt):
                holder = nxt.title()
                consumed.add(i + 1)
            prev_nonrow = ''
            continue
        m = ROW.match(line)
        if not m:
            prev_nonrow = line
            continue
        date, _time, desc, rsign, rpts, plus, amount = m.groups()
        if not desc:                         # wrapped row: description around the date line
            desc = prev_nonrow
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            if nxt and not ROW.match(nxt) and len(nxt) < 40 and ' ' not in nxt.strip(')'):
                desc = f'{desc} {nxt}'
                consumed.add(i + 1)
        prev_nonrow = ''
        txns.append(_make(date, desc, amount, plus, rsign, rpts, holder, section))
    return txns


def _make(date, desc, amount, plus, rsign, rpts, holder, section) -> Transaction:
    desc = re.sub(r'\s+', ' ', desc).strip()
    ref = ''
    r = re.search(r'\(Ref#\s*([^)]*)\)?', desc)
    if r:
        ref = r.group(1).strip()
        desc = desc[:r.start()].strip()
    is_credit = bool(plus)
    up = desc.upper()
    cat = ''
    if up.startswith('EMI '):
        desc, cat = desc[4:].strip(), 'EMI eligible'
    if 'OFFUS EMI,PRIN' in up or 'OFFUS EMI,INT' in up:
        cat = 'EMI'
    elif re.search(r'CGST|SGST|IGST|FEE|DCC|PROCNG|FINANCE CHARGE|LATE PAY', up):
        cat = 'Fees & Taxes'
    elif is_credit and 'PAYMENT' in up:
        cat = 'Payment'
    elif is_credit and 'EMI' in up:
        cat = 'EMI conversion'
    elif not cat and section == 'International':
        cat = 'International'
    pts = _i(rpts) * (-1 if rsign == '-' else 1) if rpts else 0
    return Transaction(date=_d(date), description=desc, amount=_a(amount),
                       txn_type='credit' if is_credit else 'debit', category=cat,
                       reference=ref, reward_pts=pts, cardholder=holder)


def _emis(t: str, data: StatementData):
    row = re.compile(
        rf'^(\d{{6,}})\s+(\d{{2}}/\d{{2}}/\d{{4}})\s+{RS}({AMT})\s+(\d+)\s+Months\s+([\d.]+)%\s+'
        rf'{RS}({AMT})\s+{RS}({AMT})\s+(\d+)\s+Months', re.M)
    for m in row.finditer(t):
        loan = m.group(1)
        booked = _d(m.group(2))
        amount = _a(m.group(3))
        # this month's instalment = principal + interest rows that carry the loan number
        emi = sum(x.amount for x in data.transactions
                  if x.category == 'EMI' and loan in x.description.replace(' ', ''))
        merchant = next((x.description for x in data.transactions
                         if x.txn_type == 'debit' and abs(x.amount - amount) < 0.01 and x.category != 'EMI'), '')
        desc = f'SmartEMI {loan} @ {m.group(5)}% p.a.' + (f' — {merchant}' if merchant else '')
        data.emis.append(EMIEntry(
            description=desc,
            principal=_a(m.group(6)),            # principal still outstanding
            interest=_a(m.group(7)),             # interest still payable
            emi_amount=round(emi, 2),
            tenure_months=int(m.group(4)),
            months_remaining=int(m.group(8)),
            start_date=booked,
            end_date=_add_months(booked, int(m.group(4))),
            ref=loan, lender='HDFC Bank', original_amount=amount, outstanding=_a(m.group(6)),
            rate_pa=float(m.group(5)),
        ))
