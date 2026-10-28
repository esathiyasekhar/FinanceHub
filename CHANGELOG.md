# Finance Hub — Changelog

Every change gets a new version number (shown at the bottom of the sidebar). From 28 Oct 2026 versions run 1.1, 1.2, …
Earlier versions (v2 – v11) and their data were deleted at the owner's request; this log starts with 1.1.

## 1.5 — 2026-10-28
- **Mail inbox** (*Settings › Mail inbox*, and the link under *Add Statements*): the Hub reads its own mailbox over IMAP
  (SSL) while it is unlocked — every 15 minutes (changeable) or on *Check now*.
  - Only senders on your list (bank / card / broker / depository domains; `bank.in` covers every regulated bank) and your
    own forwarding addresses are read; other mails are only listed, never downloaded.
  - A sender is accepted only when your mail server's own check passed (DMARC, or DKIM signed by the sender's domain);
    look-alike mails are rejected and never opened. Mails you forward by hand are read but always wait for you.
  - PDF / CSV / XLSX attachments go through the same readers as the Import pages with your saved statement passwords:
    bank and card statements, broker contract notes, CDSL / NSDL statements. They are imported automatically only when
    every check passes (balances reconcile, account already known, not a duplicate, contract-note totals reconcile, broker /
    demat known); anything else waits under *Waiting for you* with the reason, and *Review* opens the usual import preview.
  - Mails without attachments (instant alerts) are kept, encrypted, for the next step (provisional entries).
  - Mails stay unread in the mailbox and get the label *FinanceHub*. The app password is kept inside your encrypted data;
    files waiting for review are stored encrypted with your key and erased once handled.
- Mail checks in the background do not keep the Hub from locking itself when you are away.

## 1.4 — 2026-10-28
- **CDSL and NSDL are depositories, not brokers.** The fake broker “CAS (CDSL / NSDL)” is gone; holdings imported from it
  earlier are moved to a demat account called “From an earlier CAS” (import the CAS again to split it by account).
- **Demat accounts** (*Investments › Demat check*): one per DP ID + client ID (NSDL) or 16-digit BO ID (CDSL), created
  automatically when a CAS or the DP's holding statement is imported, or added by hand. Each is linked to its broker
  (guessed from the DP name, changeable). Account numbers are shown masked (•••• 1234).
- **CAS reading per demat account**: every demat section of an NSDL or CDSL CAS is read separately (quantity picked so that
  quantity × price = value, which suits both layouts); mutual-fund folios are skipped. Importing both an NSDL and a CDSL CAS
  for the same date does not double the holdings. CSV / XLSX holding exports can also be filed under a demat account.
- **Reconciliation, account-wise and broker-wise**: depository quantity vs the broker's trades settled by the statement
  date (T+1, weekends skipped) vs the broker's own holdings statement. Each holding shows *matches*, *still settling*,
  *quantity differs* (with bonus / split hints), *missing in demat* or *not in broker trades*. Excel and PDF report.
- Import page tables scroll on phones.

## 1.3 — 2026-10-28
- **Your name and your user ID are now separate.** The user ID is only what you type to log in; the Hub greets you by
  your name. Set it on *Settings › Users* (“Your name”) — it is stored only inside your encrypted data. New users get a
  Name field when they are added, and the first-start screen asks for both.
- Log-in, recovery and user screens say “User ID” throughout.

## 1.2 — 2026-10-28
**Security and privacy**
- **Users and passwords.** The first start asks you to create your user; an administrator can add more users.
  Every user has their **own encrypted database** — users never see each other's data, and removing a user erases theirs.
- **Encrypted database.** Data is stored only as `data/<id>.enc`, encrypted with **AES-256-GCM** (any tampering is detected).
  Each user's key is unlocked by their password through **PBKDF2-HMAC-SHA256** (600 000 rounds); passwords are never stored.
  The database is opened only in memory after log-in — copying the folder gives nothing readable.
- **Recovery key** per user, shown once (at setup / first log-in) — resets a forgotten password. Without the password or the
  recovery key nobody can open that user's data.
- Locks after 30 minutes without use (changeable), on **Lock** in the top bar, and when the program is closed.
  The Hub now listens only on this computer (127.0.0.1). Import previews waiting for confirmation are encrypted too, and the
  uploaded copy of a statement is overwritten and deleted once it is imported.
- **No personal data in the program**: card / account numbers, names, statement passwords, family names, company names and
  locally-specific payee rules were removed from the code. Your name variants, family members, companies (books) and clients
  are entered on *Settings › People & entities* and stored only in your encrypted database.
- First start can securely erase old unencrypted databases, backups and uploaded statements found in the folder;
  *Settings › Users & security* lists any that remain.

**Books, transfers and reimbursements**
- **Books**: Personal plus any company you own; a company's bank account (recognised by its registered name) and its
  transactions go into its book. Clients / employers who pay you are *payers* (income), not books.
- **Transfers & links**: transfers between your own accounts are matched automatically — bank → card bill, savings → broker,
  company → you, you → company — by amount and date or because the narration names the other account; you confirm them.
  Confirmed links are categorised as transfers (no double counting). Flow view and Excel / PDF report.
- **Director's account**: company ↔ you movements (capital, drawings, card bills the company paid for you, company expenses you
  paid) with a running balance — who owes whom.
- **Reimbursements**: mark expenses you paid for a client (e.g. travel), group them into claims, apply the client's pay-backs;
  claimed expenses and pay-backs are kept out of your spending and income (and out of the ITR summary).
- **Loans with people**: money lent to / borrowed from people, for any book — mode (cash, UPI, NEFT, IMPS, RTGS, cheque …),
  your account, their bank / account / IFSC / UPI, due date, interest, repayments, write-offs; match each entry with its bank
  transaction; overdue loans flagged.

**Investments**
- **Holdings by broker** and trades **grouped by broker**, with filters for broker, asset type, dates and side.
- **Asset types**: Equity, ETFs, Mutual funds, REITs, InvITs, Bonds & NCDs, Government securities, Sovereign Gold Bonds,
  Preference shares — found from the ISIN and name; anything else gets a suggested new type (e.g. Warrants) to add with one click.
  Change any holding's type; asset mix on the portfolio and broker pages.

**Filter and report anything**
- **Viewing** filter in the top bar: everything, one book, one account / card / loan, or one broker — every page follows it.
- **Report** button on every page: Excel or PDF of what you are viewing (summary, by head, by month, by account, transactions,
  linked transfers), plus trades & holdings, transfers, director's account, reimbursements and loans-with-people reports.

**Statement Reader v13** — reads State Bank of India account statements from internet banking / YONO Business (current or
savings, any period), with row-by-row balance check.

## 1.1 — 2026-10-28
Redesign: accounts by kind with manual add (banks, cards, loans, EMIs, deposits, brokers, wallets, assets), Home page, net worth,
dues calendar, recurring & subscriptions, budgets, card & loan tools, alerts & month close, Ctrl+K search, vibrant light / dark /
auto theme, grouped sidebar, "Add Statements".
