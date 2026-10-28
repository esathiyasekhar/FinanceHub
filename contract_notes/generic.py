"""Fallback for brokers without their own module — the SEBI common contract-note layout
(Annexure A trade lines with ISIN). Totals are looked for under the usual labels; if they are not
found the note is imported with a 'not checked' status. Add a broker module when a new layout appears."""
import re
from .base import Reader, first, num


class Generic(Reader):
    name = 'Generic contract note (SEBI common format)'

    def detect(self, text_upper):
        return 1 if 'CONTRACT NOTE' in text_upper else 0

    def net(self, text):
        for rx in (r'Net amount[^\n]*?payable by (?:the )?Client[^\n]*?(-?[\d,]+\.\d+)',
                   r'NET AMOUNT RECEIVABLE[^\n]*?(-?[\d,]+\.\d+)', r'^Total\s+(-?[\d,]+\.\d+)'):
            v = first(rx, text)
            if v is not None:
                return num(v)
        return None
