# Contract-note readers

Trades come from the brokers' **contract notes** (one PDF per trading day). Each broker has a small
module here; `generic.py` covers any broker that follows the SEBI common layout until it gets its own.

| Broker | Module | Sample file name | Verified |
|---|---|---|---|
| Upstox | `upstox.py` | `CW_T_<ucc>_<yyyymmdd>_NSE_<no>.pdf` | 2 notes, checks OK |
| SBI Securities | `sbicap.py` | `CNB_11_COMMON_CONTRACT_<ddmmyyyy>_<ucc>_<no>.pdf` | 1 note, check OK |
| others | `generic.py` | — | rows only; totals not checked |

## Adding a broker
1. Keep a sample contract note in any folder on your computer (with a buy and, if possible, a sell).
2. `python tools/test_contract_note.py "<file>" <password> --text` — shows what the generic reader gets and the raw text.
3. Copy `upstox.py` to `<broker>.py`; set `broker`, `keywords` (words only that broker prints) and override
   only what differs: `trade_date`, `contract_no`, `obligation`, `net`, `levies`, or `trades` if the trade
   lines are not `order time trade time NAME … ISIN B/S qty price`.
4. Add the class to `READERS` in `__init__.py`; re-run the tool until **Check: OK**
   (Σ buys − Σ sells = pay-in obligation, and obligation + levies = net amount payable).
5. Bump the Hub version and note the broker in CHANGELOG.md.

Only equity delivery trades are kept; F&O lines are skipped and counted in the warnings.
