"""Finance Hub — spreadsheet / CSV importers.

PDF statements are NOT parsed here any more: every PDF goes through the
Statement Reader engine (package `statement_reader`, see importer.py).
This package keeps the CSV / XLSX / XLS importers.
"""
from pathlib import Path

from .axis import load_all_axis
from .icici import load_all_icici
from .cbi import load_all_cbi
from .boi import load_all_boi, parse_boi_csv
from .hdfc_cc import load_all_hdfc_cc
from .axis_savings import load_all_axis_savings
from .hdfc_savings import load_all_hdfc_savings
from .categorizer import categorize


def auto_parse(filepath: str, password: str = '') -> list[dict]:
    """Parse a CSV / XLSX / XLS statement into a list of transaction dicts."""
    p = Path(filepath)
    ext = p.suffix.lower()
    name = p.name.lower()

    if ext == '.pdf':
        raise ValueError('PDF statements are handled by the Statement Reader engine (importer.py)')

    if ext == '.csv':
        if 'icici' in name or 'amazon' in name or 'sapphiro' in name or 'credit' in name.replace('creditcard', ''):
            from .icici import parse_icici_csv
            return parse_icici_csv(filepath)
        return parse_boi_csv(filepath)

    if ext == '.xlsx':
        if 'axis' in name or 'select' in name:
            from .axis import parse_axis_xlsx
            return parse_axis_xlsx(filepath)
        if 'accountstatement' in name.replace(' ', ''):
            from .cbi import parse_cbi_xlsx
            return parse_cbi_xlsx(filepath)
        from .axis import parse_axis_xlsx
        result = parse_axis_xlsx(filepath)
        if result:
            return result
        from .cbi import parse_cbi_xlsx
        return parse_cbi_xlsx(filepath)

    if ext == '.xls':
        # Old-format Excel exports: try the HDFC / Axis readers in turn
        from .hdfc_savings import parse_hdfc_savings_file
        from .axis_savings import parse_axis_savings_file
        from .hdfc_cc import parse_hdfc_xls
        for fn in (parse_hdfc_xls, parse_hdfc_savings_file, parse_axis_savings_file):
            try:
                rows = fn(filepath)
                if rows:
                    return rows
            except Exception:
                continue
        return []

    return []


def load_all_statements(base_folder: str, passwords: dict = None) -> list[dict]:
    """Load CSV / XLSX / XLS statements from the standard sub-folders.
    (PDFs in the folder are imported by importer.import_folder via the engine.)"""
    base = Path(base_folder)
    all_txns = []
    if (base / 'Axis_Card').exists():
        all_txns.extend(load_all_axis(str(base / 'Axis_Card')))
    if (base / 'ICICI_Cards').exists():
        all_txns.extend(load_all_icici(str(base / 'ICICI_Cards')))
    hdfc_biz, hdfc_neu = base / 'HDFC_BizPower', base / 'HDFC_TataNeu'
    if hdfc_biz.exists() or hdfc_neu.exists():
        all_txns.extend(load_all_hdfc_cc(str(hdfc_biz), str(hdfc_neu)))
    if (base / 'Savings_Accounts').exists():
        all_txns.extend(load_all_cbi(str(base / 'Savings_Accounts')))
        all_txns.extend(load_all_boi(str(base / 'Savings_Accounts')))
    if (base / 'Axis_Savings').exists():
        all_txns.extend(load_all_axis_savings(str(base / 'Axis_Savings')))
    if (base / 'HDFC_Savings').exists():
        all_txns.extend(load_all_hdfc_savings(str(base / 'HDFC_Savings')))
    return all_txns
