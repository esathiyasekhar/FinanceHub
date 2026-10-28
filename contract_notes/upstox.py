"""Upstox (Upstox Securities Pvt Ltd, formerly RKSV) — 'Contract Note cum Tax Invoice' (CW_T_<ucc>_<date>_*.pdf).
Trade lines:  <order> <time> <trade> <time> NAME [ISIN] B|S ±qty gross_rate net_rate net_total NSE|BSE
Totals:       PAY IN / ( PAY OUT ) OBLIGATION 2786.31 … ; levies as '[STT-DEL.] 64.81'; 'Brokerage Charges 270.00';
              'Net amount (-) receivable by Client / (+) payable by Client (Rs.) 3248.18'
"""
import re
from .base import Reader, first, num, parse_date


class Upstox(Reader):
    name = 'Upstox contract note'
    broker = 'Upstox'
    keywords = ('UPSTOX', 'RKSV')

    def trade_date(self, text):
        d = first(r'Trade Date\s*:\s*(\d{2}/\d{2}/\d{4})', text)
        return parse_date(d) if d else super().trade_date(text)

    def contract_no(self, text):
        return first(r'Contract Note No\.?\s*:\s*(\d+)', text) or ''

    def net(self, text):
        v = first(r'Net amount \(-\) receivable by Client / \(\+\) payable by Client \(Rs\.\)\s*(-?[\d,]+\.\d+)', text)
        return num(v) if v is not None else super().net(text)

    def levies(self, text):
        out = {}
        b = first(r'^Brokerage Charges\s+(-?[\d,]+\.\d+)', text)
        if b:
            out['Brokerage'] = num(b)
        names = {'STT': 'STT', 'IGST': 'GST', 'CGST': 'GST', 'SGST': 'GST', 'UTT': 'GST', 'STAMP': 'Stamp duty',
                 'TURNOVER': 'Exchange charges', 'SEBI': 'SEBI fees', 'DEMAT': 'Demat charges', 'CLEARING': 'Clearing charges'}
        for m in re.finditer(r'^\[([^\]]+)\]\s+(-?[\d,]+\.\d+)', text, re.M):
            label = m.group(1).upper()
            key = next((v for k, v in names.items() if k in label), m.group(1).title())
            out[key] = round(out.get(key, 0) + num(m.group(2)), 2)
        return out
