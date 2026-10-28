"""SBI Securities (SBICAP Securities Ltd) — common contract note (CNB_11_COMMON_CONTRACT_<date>_<ucc>_*.pdf).
Trade lines (Annexure A, after an NSEM / BSEM heading):
              <order> <time> <trade> <time> NAME-Cash-ISIN B|S qty price
Totals:       'PAY IN/ PAY OUT OBLIGATION 19753.70 0.00 … 19753.70' (last column = total);
              levy rows (STT, CGST/SGST/IGST/UTT Amount, Exchange Transaction Charges, SEBI fees, Stamp Duty, Brokerage)
              and 'Total 19824.29 … 19824.29' = net payable.
"""
import re
from .base import Reader, first, num, parse_date


class SBICap(Reader):
    name = 'SBI Securities contract note'
    broker = 'SBI Securities'
    keywords = ('SBICAP', 'SBI SECURITIES', 'SBISECURITIES')

    def trade_date(self, text):
        d = first(r'TRADE DATE\s+(\d{1,2}-[A-Z]{3}-\d{2,4})', text)
        return parse_date(d) if d else super().trade_date(text)

    @staticmethod
    def _last(text, label_rx):
        m = re.search(r'^' + label_rx + r'[^\n]*?((?:\s+-?[\d,]+\.\d+)+)\s*$', text, re.I | re.M)
        if not m:
            return None
        return num(m.group(1).split()[-1])          # last column = Total

    def obligation(self, text):
        return self._last(text, r'PAY IN/?\s*PAY OUT OBLIGATION')

    def net(self, text):
        return self._last(text, r'Total(?=\s+-?[\d,]+\.\d+)')

    def levies(self, text):
        rows = {'STT': r'Security Transaction Tax', 'Exchange charges': r'Exchange\s*Transaction Charges',
                'SEBI fees': r'SEBI Turnover Fees', 'Stamp duty': r'Stamp Duty', 'Brokerage': r'Brokerage(?=\s+-?[\d,]+\.\d+)',
                'Commodity tax': r'Commodities Transaction Tax'}
        out = {k: self._last(text, rx) or 0.0 for k, rx in rows.items()}
        gst = 0.0
        for m in re.finditer(r'^Amount(?:\(Rs\.\))?((?:\s+-?[\d,]+\.\d+)+)\s*$', text, re.M):   # CGST / SGST / IGST / UTT amounts
            gst += num(m.group(1).split()[-1])
        out['GST'] = round(gst, 2)
        return out
