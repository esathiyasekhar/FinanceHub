# Statement Reader — Changelog

Every change gets a new version number. The zip is named `StatementReader_<version>.zip`
and the version shows in the app's title bar.

## v14 — 2026-10-28
- Privacy: examples in the code comments and this changelog that came from real statements (reward points in the SBI
  Card reader, a payee name in the HDFC savings reader) were replaced with made-up values. Reading is unchanged.

## v13 — 2026-10-28
- New reader: **State Bank of India account statement** from internet banking / YONO Business — current or savings
  account, any period (e.g. a whole financial year). Reads the account name, number, type and IFSC, the printed
  opening balance, and checks every row's running balance. Tested on three full-year statements: all reconcile. Other statements are detected exactly as before.

## v12 — 2026-10-27
Provision for adding more banks and credit cards (no change to how existing statements are read):
- `tools/test_statement.py <pdf> [password] [--text]` — detection scores of every parser, parser chosen,
  header figures, balance check per account, first transactions (and page-1 text) — the starting point
  for a new bank parser
- `parsers/README.md` — what a bank-account and a credit-card parser must deliver, step-by-step for adding one; `SUPPORTED` list of banks / documents
  (shown on the Finance Hub Import page); `detect_scores()` helper
- Generic fallback is now flagged by the Hub ("no dedicated reader") and not pre-ticked unless it reconciles

## v11 — 2026-10-26
Engine changes needed for Finance Hub integration (loan tracking):
- Every EMI / loan now carries consistent fields: loan / reference number, lender, original amount,
  outstanding principal, annual interest rate — EMI Details sheet has these 5 new columns
- SBI single-account loans: interest *rate* was being written into the interest *amount* column — fixed;
  start date = account open date; outstanding = header Outstanding Amount
- BOB bullet loans: instalments shown as the bank prints them (0 paid / 1 left), not 11/12
- EMI letters: monthly rate converted to annual (1.25% p.m. → 15% p.a.)
- Verification re-run: 16/16 statements still PASS

## v10 — 2026-10-26
- NEW Central Bank of India savings statement (internet-banking PDF): table rows, running-balance
  check row by row, opening balance derived from the first row (CBI does not print it),
  matches the printed Cleared Balance
- SBI Card: automatic balance check added — opening − credits + purchases + fees = Total
  Outstanding (EMI instalment rows 'M' excluded, as SBI Card excludes them; ₹1 rounding)
- Excel Summary labels follow the document: combined statements show "Total Loans Outstanding" /
  "Total Deposit Balance", EMI letters "Loan Outstanding" / "Letter Date", loan accounts
  "EMI" / "Sanctioned Amount" (values unchanged — only the labels were misleading)
- Verified: all 16 statements in FinanceHub_v2\statements — see _Verification_Report.xlsx

## v9 — 2026-10-26
Audit of every statement in the folders — each one now goes to the right parser and,
wherever the statement prints balances, reconciles exactly (Accounts sheet = OK).
- NEW Axis Bank credit card (SELECT): matches Previous Balance − Payments + Purchases + Other = Total Due;
  merchant category column, card EMI instalments (REF#) → EMI sheet, eDGE reward points
- NEW Axis Bank savings (Liberty): opening/closing and withdrawal/deposit totals checked
- NEW Bank of Baroda combined statement: savings + 2 loans, all reconcile; loan terms → EMI sheet
- NEW EMI letters: HDFC SmartEMI letter and Axis "Conversion of Transaction into EMI" letter
  (Axis: full 12-month schedule, each instalment marked paid / planned)
- SBI single-account statements: Other Loans / Education Loan no longer labelled "savings";
  row-by-row running-balance check; closing balance now from the newest row (was the oldest)
- ICICI (Sapphiro, Amazon Pay): statement & due date, total/minimum due, limits, card name,
  two card sections, Loan-on-Card EMI table; reconciles with the printed summary
  (minimum due was wrongly read from an example in the terms pages)
- HDFC credit cards & StanChart: balance check added
- SIB: months whose header says only "One Credit Card Statement" are detected again (v8 missed them)
- App status bar now says whether the balances reconcile after each parse

## v8 — 2026-10-26
- SIB One Credit Card: parser rewritten (layout-based) — **was missing most rows**
  - Oct 2026 statement: 10 → 30 transactions; all 13 SIB statements now reconcile exactly
    (opening − repayments/refunds + spends + fees = Total Amount Due)
  - reads words by column position instead of pdfplumber tables (which dropped rows)
  - rows split across page breaks are re-joined (merchant / amount / forex fee)
  - add-on cardholders from the section titles
  - refunds detected: Repayments, negative reward points (reversals), fuel-surcharge
    refunds — checked against the printed "Repayments & Refunds" total
  - forex fee + GST split out of the printed amount into a separate "Fees & Taxes" row
  - older statements: Total Amount Due no longer read as 0.00; Dec→Jan year handled
- NEW: HDFC savings account statement (was being read as an HDFC credit card)
  - matches the bank's STATEMENT SUMMARY (opening, debits, credits, closing) exactly
  - short description (e.g. "UPI · A KUMAR") + "Full narration" column
- Every statement with a balance check now gets an **Accounts** sheet row (OK / MISMATCH)
- Detection: a parser can now require the bank's name, so account-statement column
  headings can't pull another bank's file into the wrong parser

## v7 — 2026-10-26
- NEW: SBI consolidated account statement (internet-banking download, e.g. <CIF><DDMMYYYY>.pdf)
  - all accounts in one PDF: 3 savings + 5 loan accounts, 56 transactions (Sep 2026)
  - every account reconciles: opening ± transactions = closing (shown in new **Accounts** sheet)
  - each loan → EMI sheet: EMI amount, outstanding, ROI, interest charged this month,
    months remaining / original term, sanction date & amount
  - categories: Transfer, UPI, Cash withdrawal, Interest, Dividend, Bank charges, EMI payment, …
- Excel: new "Accounts" sheet for multi-account statements (with OK / MISMATCH check)
- App window: Transactions tab now shows "Card / Account" and "Category" columns
- Generic parser: bank name taken from web domain (sbi.co.in etc.) instead of the first bank
  name mentioned in a transaction (was mislabelling this SBI file as "HDFC Bank")

## v6 — 2026-10-26
- Password box: type the password and press **Enter** to process (same as clicking Process PDF)
  - after selecting a file the cursor jumps to the password box; if the PDF is protected
    it says "Password required — type it and press Enter"
  - wrong password: box turns red, text is selected for re-typing, status bar says
    "Wrong password" — no pop-up; typing again clears the red
  - Enter on a non-protected file processes it straight away
  - clear (×) button inside the password box; double-Enter while processing is ignored

## v5 — 2026-10-26
- UI: input box renamed **"Select PDF Statement"**, made compact (one line, 54 px high)
  and moved into the top bar right next to the title
  - still click-to-browse or drag & drop; long file names shortened with full name on hover
  - "Input" group box removed — password + Process PDF row sits directly below the top bar,
    giving more room to the Extracted Data tabs
  - fixed dashed border being drawn around the labels inside the box

## v4 — 2026-10-26
- HDFC credit cards: new parser for the 2025/26 template (parsers/hdfc_cc.py)
  - Biz Power and Tata Neu Infinity verified; same template covers Regalia/Millennia etc.
  - ₹ glyph read as 'C'; '+' before amount = credit; reward points / NeuCoins per transaction
  - wrapped GST rows rebuilt, Ref# moved to Reference column
  - cardholder per section, 'EMI' marker → category "EMI eligible"
  - Smart EMI Loan Summary → EMI sheet (principal & interest outstanding, months left,
    this month's instalment = PRIN + INT rows, merchant matched by booked amount)
  - reward / NeuCoins summary + bonus programme breakdown
- Detection: Tata Neu weight raised so it wins over the generic HDFC header

## v3 — 2026-10-26
- SBI Card: parser rewritten for the 2026 format (`DD Mon YY … amount C/D/M`)
  - header: total/min due, credit & available limit, statement & due date, account summary
  - add-on cardholder sections (TRANSACTIONS FOR …) → new "Cardholder" column
  - undated forex markup / GST lines attached to the right date
  - EMI plans from the VALUE ADDED SERVICES table (instalment n/N → months remaining)
  - reward points (previous / earned / redeemed / closing)
  - card name from the card-specific mailbox (e.g. AURUM), not the fee schedule
- Standard Chartered: parser rewritten (`DDMMYY` dates, per-card sections, rewards per card)
- Detection: falls back to page 2 + filename when page 1 has no bank name (StanChart logo-only)
- Excel: Transactions sheet now has Cardholder and Category columns

## v2 — 2026-10-26 (released 3 times under the same name; superseded by v3)
- SIB One Credit Card parser (table extraction, forex-fee rows)
- SBI Savings / Home Loan parser (7-column tables, EMI from header)
- Score-based bank detection on page 1, Tata Neu & SBI Card parsers added

## v1
- First release: ICICI (OCR for NORM PDFs), HDFC, SBI, StanChart, generic fallback
