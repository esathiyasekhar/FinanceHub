from .base import StatementData
from .icici import ICICIParser
from .hdfc import HDFCParser
from .sbi import SBIParser
from .sbicard import SBICardParser
from .stanch import StanChartParser
from .tataneu import TataNeuParser
from .sib import SIBParser
from .sbi_consolidated import SBIConsolidatedParser
from .hdfc_savings import HDFCSavingsParser
from .axis import AxisCCParser, AxisSavingsParser
from .bob import BOBParser
from .emi_letters import HDFCSmartEMILetterParser, AxisEMILetterParser
from .cbi import CBIParser
from .sbi_current import SBIAccountStatementParser
from .generic import GenericParser

# Score-based detection — higher = more confident match
# Checked against page 1 text only to avoid false matches from transaction descriptions
_PARSERS = [
    (TataNeuParser,   [('tata neu', 30), ('tataneu', 30)]),
    (SBICardParser,   [('sbi card', 12), ('sbi cards and payment', 20),
                       ('sbicard', 15), ('sbicards', 15)]),
    (SIBParser,       [('sib one credit card', 20), ('sib one', 15),
                       ('south indian bank', 10), ('sib credit card', 18),
                       # some months print only 'One Credit Card Statement' (SIB logo is an image)
                       ('one credit card statement', 12), ('summary statement illustration', 12),
                       ('getonecard', 10)]),
    (ICICIParser,     [('icici bank', 8), ('icicibank', 8),
                       ('icici bank credit card', 12)]),
    (HDFCParser,      [('hdfc bank', 8), ('hdfc credit card', 12),
                       ('hdfc bank credit card statement', 18),
                       ('hdfc bank ltd', 10)]),
    # Account statements carry table headings a card statement never has
    (HDFCSavingsParser, [('withdrawal amount', 12), ('deposit amount', 8),
                         ('statement from', 8), ('cust id', 6), ('a/c open date', 6)],
                        ('hdfc',)),
    (AxisCCParser,      [('credit card statement', 10), ('payment summary', 8),
                         ('total payment due', 6), ('edge reward', 6)], ('axis',)),
    (AxisSavingsParser, [('statement for account no', 14), ('savings account(s)', 8),
                         ('scheme name', 6), ('opening balance', 4)], ('axis',)),
    (BOBParser,         [('statement of transactions in', 14), ('summary of your relationship', 10),
                         ('customer id', 4)], ('bankofbaroda', 'bank of baroda')),
    # Loan / EMI confirmation letters — not statements
    (HDFCSmartEMILetterParser, [('smartemi loan on your hdfc bank credit card', 40),
                                ('we are pleased to grant you smartemi', 20)], ('hdfc',)),
    (AxisEMILetterParser,      [('conversion of transaction into', 40),
                                ('installment amount', 8)], ('axis',)),
    (CBIParser,         [('central bank of india', 20), ('cbin0', 10), ('statement of account from', 8)],
                        ('central bank of india', 'cbin0')),
    (StanChartParser, [('standard chartered', 12), ('stanchart', 10),
                       ('standardchartered', 12), ('sc.bank.in', 12),
                       ('retail interest rate', 6), ('ultimate mastercard', 6),
                       ('super value titanium', 6), ('smart credit card', 4)]),
    # SBI internet-banking / YONO Business account statement (current or savings, any period)
    (SBIAccountStatementParser, [('account statement from', 12), ('drawing power', 15), ('mod balance', 15),
                                 ('txn date value date description', 20), ('opening balance as on', 8)], ('sbin',)),
    (SBIParser,       [('state bank of india', 8), ('sbi account', 10)]),
    (SBIConsolidatedParser, [('my home branch information', 25), ('my accounts', 8),
                             ('loan accounts', 4), ('customercare@sbi.co.in', 4)]),
]


# What each reader covers — shown on the Hub's Import page and in tools/test_statement.py.
# Add a line here when a new bank parser is added (see parsers/README.md).
SUPPORTED = [
    ('South Indian Bank', 'SIB One credit card', 'SIBParser'),
    ('HDFC Bank', 'Credit cards (Biz Power, Tata Neu Infinity, Regalia …)', 'HDFCParser / TataNeuParser'),
    ('HDFC Bank', 'Savings account statement', 'HDFCSavingsParser'),
    ('HDFC Bank', 'SmartEMI letter', 'HDFCSmartEMILetterParser'),
    ('State Bank of India', 'Savings / loan account statements; consolidated statement (all accounts)',
     'SBIParser / SBIConsolidatedParser'),
    ('State Bank of India', 'Current / savings account statement from internet banking or YONO Business (any period)',
     'SBIAccountStatementParser'),
    ('SBI Card', 'Credit card (Aurum …)', 'SBICardParser'),
    ('Axis Bank', 'Credit card; savings account; EMI conversion letter', 'AxisCCParser / AxisSavingsParser / AxisEMILetterParser'),
    ('ICICI Bank', 'Credit cards (Sapphiro, Amazon Pay)', 'ICICIParser'),
    ('Standard Chartered', 'Credit card (Ultimate …)', 'StanChartParser'),
    ('Bank of Baroda', 'Combined statement (savings + loans)', 'BOBParser'),
    ('Central Bank of India', 'Savings account (internet banking PDF)', 'CBIParser'),
]


def detect_scores(text: str) -> list:
    """[(score, parser name)] for a page-1 text, best first — used by tools/test_statement.py."""
    t = text.replace('(cid:9)', ' ').lower()
    out = []
    for entry in _PARSERS:
        parser_cls, patterns = entry[0], entry[1]
        required = entry[2] if len(entry) > 2 else ()
        if required and not any(r in t for r in required):
            continue
        score = sum(w for pat, w in patterns if pat in t)
        if score:
            out.append((score, parser_cls.__name__))
    return sorted(out, reverse=True)


def auto_detect_parser(filepath: str, password: str = ''):
    """Auto-detect the right parser using scored keyword matching on page 1 only."""
    from statement_reader.utils.pdf_utils import extract_text_all_pages, ocr_pages, is_vectorized_pdf
    import re

    # Get page 1 text only — bank letterhead is always there
    pages = extract_text_all_pages(filepath, password, max_pages=1)
    text = pages[0] if pages else ''

    # If page 1 is vectorized, OCR it
    if len(text.strip()) < 80:
        ocr = ocr_pages(filepath, password, pages=[1])
        text = ocr[0] if ocr else ''

    def _best(t):
        t = t.replace('(cid:9)', ' ').lower()
        best_score, best_parser = 0, None
        for entry in _PARSERS:
            parser_cls, patterns = entry[0], entry[1]
            required = entry[2] if len(entry) > 2 else ()
            if required and not any(r in t for r in required):
                continue
            score = sum(w for pat, w in patterns if pat in t)
            if score > best_score:
                best_score, best_parser = score, parser_cls
        return best_parser

    # 1) page 1 letterhead
    best_parser = _best(text)

    # 2) some banks (StanChart) print their name only as a logo image —
    #    fall back to page 2 + filename
    if not best_parser:
        import os
        more = extract_text_all_pages(filepath, password, max_pages=2)
        fname = os.path.basename(filepath).replace('_', ' ')
        best_parser = _best('\n'.join(more) + '\n' + fname)

    if best_parser:
        return best_parser()
    return GenericParser()
