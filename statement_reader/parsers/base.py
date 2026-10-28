"""Base data classes and parser interface."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Transaction:
    date: str = ''
    description: str = ''
    amount: float = 0.0
    txn_type: str = 'debit'   # 'debit' or 'credit'
    category: str = ''
    reference: str = ''       # serial / cheque no
    reward_pts: int = 0
    cardholder: str = ''      # add-on card holder name, if statement groups by holder
    narration: str = ''       # full bank narration when description is shortened


@dataclass
class EMIEntry:
    description: str = ''
    principal: float = 0.0
    interest: float = 0.0
    emi_amount: float = 0.0
    tenure_months: int = 0
    months_remaining: int = 0
    start_date: str = ''
    end_date: str = ''
    # consistent fields for loan tracking (Finance Hub):
    ref: str = ''               # loan / account / EMI reference number (stable across statements)
    lender: str = ''
    original_amount: float = 0.0
    outstanding: float = 0.0    # principal still owed as of the statement
    rate_pa: float = 0.0        # annual interest rate, %


@dataclass
class RewardPoint:
    description: str = ''
    points_earned: int = 0
    points_redeemed: int = 0
    points_expired: int = 0
    balance: int = 0
    date: str = ''


@dataclass
class StatementData:
    # Source
    bank: str = ''
    card_name: str = ''
    card_number: str = ''       # masked
    account_number: str = ''
    statement_type: str = ''    # 'credit_card', 'savings', 'loan', 'emi'
    source_file: str = ''

    # Dates & amounts
    statement_date: str = ''
    due_date: str = ''
    from_date: str = ''
    to_date: str = ''
    total_due: float = 0.0
    minimum_due: float = 0.0
    credit_limit: float = 0.0
    available_credit: float = 0.0
    opening_balance: float = 0.0
    closing_balance: float = 0.0
    total_spends: float = 0.0
    total_payments: float = 0.0

    # Reward points
    reward_opening: int = 0
    reward_earned: int = 0
    reward_redeemed: int = 0
    reward_expired: int = 0
    reward_closing: int = 0
    reward_expiry_date: str = ''

    # Collections
    transactions: list = field(default_factory=list)   # list[Transaction]
    emis: list = field(default_factory=list)           # list[EMIEntry]
    reward_details: list = field(default_factory=list) # list[RewardPoint]
    accounts: list = field(default_factory=list)       # list[dict] — multi-account statements

    # Raw text for debugging
    raw_text: str = ''


class BaseParser:
    """Abstract parser interface."""

    def can_parse(self, text: str) -> bool:
        """Return True if this parser recognises the statement."""
        raise NotImplementedError

    def parse(self, filepath: str, password: str = '') -> StatementData:
        """Parse the PDF and return StatementData."""
        raise NotImplementedError


def account_check(account: str, acct_type: str, opening: float, closing: float, txns: list,
                  is_loan: bool = False, stated_credits: float = None, stated_debits: float = None,
                  period: str = '', tol: float = 0.02, **extra) -> dict:
    """Reconcile one account: opening ± transactions must equal closing.

    Savings/current: closing = opening + credits - debits
    Loan (balance = amount owed): closing = opening - credits + debits
    If the statement prints its own debit/credit totals, those are compared too.
    """
    cr = round(sum(t.amount for t in txns if t.txn_type == 'credit'), 2)
    dr = round(sum(t.amount for t in txns if t.txn_type == 'debit'), 2)
    opening, closing = round(opening or 0.0, 2), round(closing or 0.0, 2)
    calc = round(opening - cr + dr, 2) if is_loan else round(opening + cr - dr, 2)
    problems = []
    if abs(calc - closing) >= tol:
        problems.append(f'calc closing {calc:,.2f}')
    if stated_credits is not None and abs(stated_credits - cr) >= 0.02:
        problems.append(f'stmt credits {stated_credits:,.2f}')
    if stated_debits is not None and abs(stated_debits - dr) >= 0.02:
        problems.append(f'stmt debits {stated_debits:,.2f}')
    row = {'Account': account, 'Type': acct_type}
    row.update(extra)
    row.update({'Period': period, 'Opening': opening, 'Credits': cr, 'Debits': dr,
                'Closing': closing, 'Transactions': len(txns),
                'Check': 'OK' if not problems else 'MISMATCH (' + '; '.join(problems) + ')'})
    return row
