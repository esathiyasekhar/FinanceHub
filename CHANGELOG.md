# Finance Hub — Changelog

Every change gets a new version number (shown at the bottom of the sidebar). From 28 Oct 2026 versions run 1.1, 1.2, …
Earlier versions (v2 – v11) and their data were deleted at the owner's request; this log starts with 1.1.

## 1.12 — 2026-10-28
**Wealth planner (compounding calculator)**
- **Spouse inputs work as expected**: the spouse's (and your own) amounts could not be typed while the person was switched
  off, so changes seemed to have no effect. The boxes stay editable now; typing an amount switches the person on, and a red
  note warns when amounts are filled in but not counted.
- **Include my contributions** now covers your lump sum too (it used to leave the lump sum in the plan).
- **Year-by-year schedule**: the "Self SIP" / "Spouse SIP" columns showed the whole year's amount (e.g. ₹3,00,000 for
  ₹25,000 a month). They are now **₹/month** (after step-ups, "× 6 mo" in a part year) and **added** in the year;
  year 0 shows the lump sums. CSV export has the same columns.
- Annual review: a last SIP year with extra months now counts as planned SIP when working out the SIP needed.
- The spouse comparison says it uses plan figures; the manual explains how each number is worked out, with an example.
- New engine checks (hand-worked example, step-ups, part years, self / spouse symmetry, goal and review solvers).

**Deleting mails** (*Mail inbox*)
- Handled mails are deleted **automatically after 3 days** (Reading rules; 0 = never): imported / already-in-the-Hub /
  not-a-statement mails go to the mailbox's **Trash** and leave the list; alerts go to the Trash but stay in the Hub;
  waiting items are never auto-deleted.
- Automatic deletion applies to mails read from 1.12 on, counts the days from when a mail was handled, and waits until every
  file of a mail is handled. Mails only ever go to the Trash (a mailbox without a Trash folder keeps them).
- **Delete selected** and **Delete all on this tab** (the mails shown; files waiting for you are kept on the Statements tab).
  The Hub checks each mail's Message-ID before deleting, and retries on the next check when the mailbox cannot be reached.
  Deleted mails are never read again.

## 1.11 — 2026-10-28
**Due dates in full** — card and EMI due dates now show weekday, day, month and year, e.g. *Fri, 15 Nov 2026*, with
  "in 5 days" / "2 days overdue" where there is room: Accounts (new **Next due** on every card), account pages, Home, Dues,
  card tools, loans with people, recurring, alerts, and the reminder and weekly mails.

**Senders to read** (*Mail inbox*)
- The list is now its own box: **exact sender addresses** (e.g. statements@sbicard.com — only that address is read) or
  **domains** (every address of that sender). Add several at once; invalid entries are reported.
- **Pause / resume** a sender without deleting it, **delete** single or ticked entries, **Read only the exact addresses**
  (pauses all domains), **Delete paused**, **Built-in list**, search, and a count of mails seen from each sender.
- *Other senders* shows the full sender address with **Read this address** or **Whole domain**; mails skipped earlier are
  read on the next check.

## 1.10 — 2026-10-28
- **Sign in with Microsoft:** the error AADSTS50059 ("No tenant-identifying information found") now says what to do — the
  Azure app registration accepts only its own directory; set its *Supported account types* to "Accounts in any
  organizational directory and personal Microsoft accounts". AADSTS50194 (single-tenant app) gets the same advice.
- Setup picks the newest release zip by version number (1.10 after 1.9).

## 1.9 — 2026-10-28
**Categories** (*Settings › Categories*)
- **Add a category** anywhere: under any category, or as a new top-level group next to Income / Expenses / Transfers /
  Investments (you choose what it counts as). **Delete**, rename and move any category except the four Types.
- **No limit on levels**: sub-categories can go as deep as you like (previously four levels).
- **Search categories** on the page; matches show with the categories above and below them.

**Type-to-search category lists** — the Transactions filter, the edit window, bulk actions and payee rules: click, type any
  part of a name or path ("car fuel"), pick with the keyboard or mouse; "Add “…” under …" creates a missing category on the spot.
  Ctrl+K finds categories at any depth.

**Automatic prices** (*Investments › Portfolio & plan*)
- Daily closing prices for **shares, ETFs, REITs, InvITs, sovereign gold bonds and listed bonds** from the NSE and BSE
  bhavcopies, and **mutual-fund NAVs** from AMFI — downloaded in the background while you use the Hub, matched to your
  holdings by ISIN on your PC (nothing about your holdings is sent anywhere).
- **Update prices automatically** switch (on by default) and **Update prices now** with a per-source result; yfinance is
  still used, if installed, for anything the files do not have. A price you type stays until a newer market price arrives.
  (Before 1.9 prices were updated only by the Refresh button and only with the optional yfinance package.)

## 1.8 — 2026-10-28
**Outlook mailboxes** (*Settings › Mail inbox*)
- **Sign in with Microsoft** for Outlook.com, Hotmail, Live and Microsoft 365 mailboxes — Microsoft no longer accepts
  passwords from programs. You register the Hub once (free) in the Azure portal and paste its *Application (client) ID*;
  then click **Sign in with Microsoft**, type the code shown on microsoft.com/devicelogin and allow access. The Hub never
  sees your Microsoft password; the sign-in is kept in your encrypted data, renewed automatically, and can be signed out.
- Reminders and problem reports can be sent from an Outlook mailbox too (smtp-mail.outlook.com, port 587, same sign-in).

**More than one mailbox**
- Add as many mailboxes as you like (Gmail, Outlook, or another IMAP mailbox); every check reads all of them. A mail that
  reaches two mailboxes is read once, and each mail shows which mailbox it came from.
- Pause, edit, test or remove each mailbox; choose which one **sends reminders**. Senders, forwarding addresses and how
  often to check are shared by all mailboxes (*Reading rules*).
- Your existing mailbox becomes the first one automatically, with nothing read twice.

**Clearer connection errors** — e.g. Gmail's "Application-specific password required" now says to create an
  app password (not your normal Gmail password) and where; IMAP turned off, expired Microsoft sign-in and similar get
  plain advice too.

## 1.7 — 2026-10-28
**Windows installer**
- **Setup** (`Setup.cmd` → setup wizard): choose the **program folder** (default `C:\Program Files\Finance Hub`) and the
  **data folder** (default `D:\Finance Hub`, or `C:\Finance Hub Data` without a D: drive); optionally **bring over the
  data of an older Finance Hub folder**; Desktop shortcut, start with Windows, start now. Windows asks once for
  administrator permission for Program Files. The setup checks every file of the release, creates the Hub's own Python
  environment, the shortcuts and an entry in **Settings › Apps** (uninstall keeps your data). Running a newer Setup upgrades.
  Optional single `.exe`: `build_exe.bat` with Inno Setup 6.
- The program and your data are now **separate**: the data folder holds the encrypted databases, `users.json`, uploads,
  logs and backups (`financehub.json` beside the program says where).

**First-start setup wizard** — after creating your user: about you (and your company as a separate book), the Hub's
  mailbox and where reminders go, the features you use, your accounts, and backup. Every step can be skipped and changed later.

**Users**
- **Change your user ID** (with your password) and your password on *Users & security*.
- **Administrators can reset a user's password** (and user ID): the user logs in with the temporary password and must
  choose their own. This works through a reset key only administrators hold — so an administrator could open another
  user's data; the page says so. Available for a user once they have logged in with 1.7.

**Backup & restore** (*Settings › Backup & restore*)
- Back up to **OneDrive**, **Google Drive** (through their folders on this PC) or any folder — now, automatically every
  day / week (also while the Hub is locked, only when something changed), keeping the newest N. Or download a backup file.
- A backup is one `.fhb` file and stays **encrypted** (opens only with your password or recovery key).
- Restore your data from any backup (your present data is saved first), or **restore on a new computer** from the
  first-start page.

**Report a problem** (*Settings › Report a problem*, the Help page, and every error page with an error reference):
  describe the problem, preview exactly what is sent (versions, settings, recent error lines — numbers, e-mails, PANs and
  paths masked; never your data), and send it to the support address through the Hub's mailbox, your mail program, or
  save it as a file.

**Also:** user manual chapters for installing, the setup wizard, users, backup & restore and problem reports; design
  manual updated; installer, backup, reset and report code covered by new tests.

## 1.6 — 2026-10-28
**Runs in the background, production-grade**
- **No console window.** The *Finance Hub* shortcut (Desktop and Start menu) starts the Hub in the background with a
  **tray icon**: Open · Lock now · Start with Windows · Open logs folder · Quit. A second start just opens the browser.
  The top bar has a **Quit** button too. Runs on **Waitress** (production web server), on this computer only.
- **Install / upgrade:** `install.bat` sets up the Hub's own Python environment (`.venv`), installs the packages, records
  their exact versions (`requirements.lock`) and creates the shortcuts. `run.bat` starts the Hub. `tools\upgrade.py`
  installs a release zip after checking every file against its manifest.
- **Automatic backups:** the first time a new version starts, your encrypted data is copied to `backups\` (newest 10 kept).
- **Logs** in `logs\hub.log` (rotated; never passwords or statement contents); a friendly error page instead of a crash.
- **Version control:** the program is kept in a git repository with a tag per version; `tools\make_release.py` builds a
  release only after the changelog check, a **personal-data scan** of the code and the full test suite (synthetic data).
- **Choose what you use** (*Settings › Features & accounts*): turn savings, cards, loans & EMIs, deposits, wallets,
  budgets, refunds, loans with people, business books, client reimbursements, investments, demat check, planner, mail
  inbox and reminders on or off — the menu, search and Accounts tabs show only what you use (nothing is deleted). The first
  log-in asks once; **Add** buttons let you add any missing account at any time.

**New features**
- **Reminders & reports by mail** (*Settings › Reminders & reports by mail*): a mail the **day before** every payment is due
  (card bills, EMIs, loans, regular payments, money borrowed from people) and a **weekly dues report** (Sunday 08:00 by
  default; next two weeks, overdue items, refunds you are waiting for) to the addresses you choose, sent from the Hub's
  mailbox. Prepared while the Hub is unlocked and kept protected by your Windows login, so they go out on time while the
  Hub is locked. Test mail and preview on the page; amounts can be left out.
- **Failed payments & refunds** (*Money › Failed & refunds*): finds payments that failed and were reversed (same amount,
  same account, reversal or same reference within 10 days) — confirm and neither side counts as spending or income; matches
  **refunds** to the purchases they pay back (the category's spending goes down); **Awaiting refund** list (Transactions ›
  More › *Expecting a refund for this*) with days waiting, follow-up after 15 days, match by hand, close, undo.
- **User manual inside the app** (*Settings › Help & user manual*, or the **?** on any page): 21 chapters, search, PDF.
  **Design manual** for administrators (internal), also as PDF.

**Fixes and hardening (from a full code review)**
- The Hub locks itself after the idle time even when no browser tab is open.
- The login cookie is never sent with requests started by other websites (SameSite=Strict); the recovery key no longer
  passes through the cookie; recovery attempts are throttled; redirects only go to pages inside the Hub.
- Excel report download: parameters are no longer pasted into the database query.
- Removing a user also erases their prepared reminder mails.
- Net-worth history is recorded only from the full (unfiltered) view; an account opens even outside the Viewing filter.
- Re-applying rules with "include hand edits" keeps the categories of confirmed transfers, refunds, reimbursements and loans.
- Reimbursements: **Fee** really returns the credit to income; the "claim" message counts only money going out.
- Mail inbox: contract notes are imported automatically only when their totals reconcile; broker CSV / XLSX files sent by
  mail wait for review; saving the settings keeps fields that are not on the form.
- Demat: removing a demat account lets its statement be imported again; bonus shares can be added at price 0.
- Insights period buttons work again; import error messages point to the log file; small wording fixes.
- Renaming an account also renames it in regular payments and loans with people.
- Privacy: examples taken from real statements (a payee name, a shop name, reward points, an account number, a folder path)
  were removed from the code; Statement Reader is now **v14**.

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
