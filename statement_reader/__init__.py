"""Statement Reader engine (synced from the desktop app by tools/export_engine.py — do not edit here)."""
from .version import APP_VERSION as ENGINE_VERSION
from .parsers import auto_detect_parser
from .utils.excel_export import export_to_excel
from .utils.pdf_utils import needs_password, check_password
