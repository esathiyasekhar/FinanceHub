"""Contract-note readers, one per broker. To add a broker: copy upstox.py, adjust the pieces that differ
(trade date, totals, levies; the trade-line pattern is shared), add the class to READERS, and run
tools/test_contract_note.py on a sample until the check says OK. See README.md."""
from .base import ContractNote, ISIN
from .upstox import Upstox
from .sbicap import SBICap
from .generic import Generic

READERS = [Upstox(), SBICap()]          # dedicated readers; Generic() is the fallback
FALLBACK = Generic()


def brokers_with_reader():
    return [r.broker for r in READERS]


def read(text: str) -> ContractNote:
    t = text.upper()
    best = max(READERS, key=lambda r: r.detect(t))
    reader = best if best.detect(t) > 0 else FALLBACK
    cn = reader.parse(text)
    if reader is FALLBACK:
        cn.warnings.append('No dedicated reader for this broker yet — read with the generic layout; check the rows.')
    return cn
