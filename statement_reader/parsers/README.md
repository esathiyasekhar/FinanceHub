# Bank account & credit card statement parsers

One module per bank / document. `parsers/__init__.py` picks the parser by **scored keywords on page 1**
(`_PARSERS`); a parser can also *require* a word (e.g. the bank's name) so similar layouts don't collide.
Anything unrecognised goes to `generic.py` — the Hub then warns "no dedicated reader" and does not tick it
for import unless its balances reconcile.

## What a parser must deliver
| | Bank account | Credit card |
|---|---|---|
| `statement_type` | `savings` / `current` / `loan` (or `consolidated`) | `credit_card` |
| header | period, opening & closing balance | statement & due date, total due, minimum due, credit / available limit |
| transactions | date, description (+ full narration), debit / credit | date, merchant, debit / credit (`+`/`Cr` = credit), cardholder for add-on cards, reward points |
| balance check | opening − debits + credits = closing (row-by-row if a running balance is printed) | previous balance − payments/credits + purchases + fees = total due (exclude EMI-schedule rows the bank excludes) |
| loans / EMIs | `EMIEntry` per loan (ref, outstanding, rate, EMIs paid / left) | card EMIs / loan-on-card → `EMIEntry`; forex fee + GST split into their own rows |

## Adding a bank or a credit card
1. Put a sample PDF in the statements folder (a month with debits **and** credits is best; for a card, one
   with a payment, a refund and an add-on card if you have them).
2. `python tools/test_statement.py "<file>" <password> --text` — detection scores, page-1 text.
3. Create `parsers/<bank>.py` with a class derived from `BaseParser` (copy the closest existing one:
   `cbi.py` / `hdfc_savings.py` for account statements, `axis.py` / `hdfc_cc.py` / `sbicard.py` for cards
   (`sib.py` when the PDF tables drop rows — it reads words by position),
   `bob.py` for multi-account statements). Fill `StatementData` (bank, card_name, statement_type,
   period, opening / closing or total due, transactions) and **always** add the balance check with
   `account_check(...)` → `data.accounts`, so every statement proves opening ± transactions = closing.
   For loans fill `EMIEntry` (ref, lender, original_amount, outstanding, rate_pa).
4. Register it in `_PARSERS` (distinctive words with weights, required bank word) and add a line to `SUPPORTED`.
5. Re-run the tool until the check is OK; run the other samples to make sure detection didn't change.
6. New version number (version.py + CHANGELOG.md), then `python tools/export_engine.py <FinanceHub folder>`.
