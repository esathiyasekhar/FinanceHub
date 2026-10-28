"""Tata Neu HDFC Bank credit card parser.
Tata Neu cards (Infinity, Plus) are issued by HDFC Bank — same statement
format as HDFC but with Tata Neu branding.
"""
import sys, os
from statement_reader.parsers.hdfc import HDFCParser
from statement_reader.parsers.base import StatementData
from pathlib import Path


class TataNeuParser(HDFCParser):
    """Inherits HDFC parsing logic; overrides card-name detection."""

    def can_parse(self, text: str) -> bool:
        t = text.lower()
        return 'tata neu' in t or 'tataneu' in t

    def parse(self, filepath: str, password: str = '') -> StatementData:
        data = super().parse(filepath, password)
        data.bank = 'HDFC Bank (Tata Neu)'
        if 'tata neu' in (data.card_name or '').lower():
            return data          # name already read from the statement header
        # Older layouts: derive name from text
        t = data.raw_text.lower()
        if 'infinity' in t:
            data.card_name = 'Tata Neu Infinity HDFC CC'
        elif 'plus' in t:
            data.card_name = 'Tata Neu Plus HDFC CC'
        else:
            data.card_name = 'Tata Neu HDFC CC'
        return data
