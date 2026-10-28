# Finance Hub — Design manual

Version 1.6 · 28 October 2026 · Statement Reader engine v14 · internal, for maintainers

This manual explains how Finance Hub is built and why. It is written for developers and for an AI assistant continuing the work, and describes the 1.6 code in this repository. When code and manual disagree, the code wins and the manual is corrected in the same change. The user manual (docs/user/) covers the same features from the user's side.

> **Note:** Names of modules, functions, tables and columns are written exactly as in the code. Examples use made-up values.

## 1. Purpose and scope

Finance Hub is a personal-finance web app for one person or one family. It reads bank, card and broker statements, puts every transaction into a four-level category tree, keeps accounts, loans, investments and dues, and produces reports. It runs as a local web server on the owner's Windows PC and is used through a browser on that PC.

### 1.1 Goals

- All data stays on the PC, encrypted at rest, readable only after log-in.
- Import exactly what was previewed (parse, show, confirm). Only the mail reader imports on its own, and only when every check passes.
- Prove the numbers: balance checks for statements, totals checks for contract notes, depository-versus-broker reconciliation.
- Organise money by Type › Head › Sub-head › Item, by book (personal or the owner's company), person and account, counting each transfer once.
- Run in the background (tray, start with Windows) and mail due-date reminders.
- No personal data in the program: names, numbers, companies and personal payee rules live only in the encrypted database.

### 1.2 Non-goals

- No cloud, no sync, no mobile app, no aggregation APIs. The Hub connects only to the user's own mailbox (IMAP/SMTP over TLS) and, on request, to Yahoo Finance through the optional yfinance package. The browser loads UI libraries from CDNs (11.4).
- No multi-tenant server: several users may exist, but one database is open at a time.
- No payments, no writes to banks or brokers, no opening of links in mails, no tax filing (itr.py is a reference summary).

## 2. Architecture overview

### 2.1 Process model

```
FinanceHub.pyw  (pythonw.exe, no console)
 |-- running_hub(): does http://127.0.0.1:<port>/healthz answer "FinanceHub"?
 |-- backup_on_upgrade(): copy data/ to backups/ when the version changed
 |-- import app                Flask app + Vault, all modules registered
 |-- Server.start()            thread "hub-server"
 |      Waitress create_server(host=127.0.0.1, port=5000, threads=1)
 |      or Werkzeug make_server(threaded=False) if waitress is missing
 |-- notify.start_scheduler()  thread "hub-reminders": tick() every 60 s
 |-- webbrowser.open(URL)      skipped with --background (autostart)
 '-- pystray.Icon.run()        main thread until Quit
        Open | Lock now | Start with Windows | Open logs folder | Quit
```

The launcher logs to logs/hub.log (rotating, 1 MB × 5; stdout and stderr redirected under pythonw). running_hub() returns 'hub' (open the browser and exit, so a second start only opens the page), 'other' (port taken: message box; FINANCEHUB_PORT changes the port) or '' (start). It passes hooks through app.config: HUB_LAUNCHER, HUB_SHUTDOWN, HUB_AUTOSTART_GET and HUB_AUTOSTART_SET (HKCU Run value FinanceHub with --background) and HUB_SERVER. Quit, from the tray or the Hub's power button, calls V.lock_now(), stops server and tray and ends with os._exit(0). Without a tray the main thread waits for the Hub's Quit button. `python app.py` runs Werkzeug (threaded=False) plus the scheduler; app_quit then only explains how to stop it.

Why one worker thread: the database is a single in-memory SQLite connection (section 4). Serving one request at a time means no request ever shares it with another, so there is no per-request locking and no pool. The cost: a slow request (IMAP check, big PDF) blocks the UI.

### 2.2 Threads

| Thread | Work | Database access |
|---|---|---|
| hub-server | all HTTP requests, one at a time | shared connection via Conn |
| main (tray) | menu actions | lock_now() only, under Vault.lock |
| hub-reminders | notify.tick(): maybe_rebuild(), run_due() | private copy from notify.snapshot_con() |
| timers | delayed browser open and quit | none |

### 2.3 Request flow

1. Waitress hands the request to Flask.
2. auth._guard, the only before_request hook, passes open endpoints and checks setup, idle lock, session and role for the rest (section 5).
3. The view calls get_db() (app.py): a Conn proxy with row_factory sqlite3.Row, cached in g._database. Modules receive get_db in register(); some helpers call dbconn.connect(), which returns the same kind of proxy.
4. Templates extend base.html. Context processors add versions and FY label (inject_fy), user and display name (auth), Viewing-filter lists (scope), mail badge (mailreader), payers (ledger), help topic (help_hub) and launcher state (_runtime_ctx).
5. teardown_appcontext close_db rolls back if the request raised, calls V.persist() and, if something was written, notify.mark_dirty().

### 2.4 Module map

| Module | Responsibility | Main tables | Routes |
|---|---|---|---|
| FinanceHub.pyw | launcher: single instance, upgrade backup, server, scheduler, tray, autostart | — | calls /healthz |
| app.py | Flask app, Vault, get_db, close_db, prepare_db; Insights, statement import, passwords, EMI actions, Reports page, launcher routes | transactions, accounts, passwords, loans | /insights, /import…, /passwords…, /loans/…, /reports…, /api/summary, /api/category_data, /healthz, /app/quit, /app/stopped, /app/autostart |
| vault.py | users, key wrapping, encrypted file, in-memory SQLite, sealing, secure delete | users.json, data/<hex>.enc | — |
| auth.py | guard, setup, log-in, recovery, users, profile | hub_settings | /setup…, /login, /logout, /recover, /users…, /profile/save |
| dbconn.py | connection source; sealed JSON files | — | — |
| importer.py | bank and card statements: preview, confirm, accounts, loans | statements | via /import/preview, /import/password, /import/confirm |
| statement_reader/ | PDF statement engine. Exported from the separate Statement Reader desktop app by its tools/export_engine.py; never edited in the Hub | — | — |
| classifier.py | category tree, rules, payee names, apply_to_rows | categories, rules, entities, people | — |
| organise.py | transactions, payee rules, Breakdown, categories, people and entities, Insights numbers | (classifier's) | /transactions…, /api/txn/…, /breakdown…, /categories/…, /rules…, /people…, /entities/… |
| accounts_hub.py | accounts by kind, balances, net worth, dues, Home | account_balances, networth_snapshots | /, /accounts…, /networth…, /dues |
| planning.py | recurring, budgets, tools, alerts, month close, Ctrl+K search (PAGES) | recurring, budgets, alert_state, month_close | /recurring…, /budgets…, /tools, /alerts…, /month-close…, /api/search, /api/alerts/count |
| scope.py | Viewing filter in the session | entities.role, aliases | /scope |
| ledger.py | transfer links, director's account, reimbursements, loans with people | txn_links, reimb_claims, reimb_receipts, contacts, pl_loans, pl_moves | /links…, /director, /reimbursements…, /people-loans…, /contacts/save |
| assets.py | asset types, holdings by broker | inv_asset_types | /investments/types…, /investments/brokers |
| investments.py | broker files, trades, holdings, portfolio, tranching, instructions, HOOKS | inv_brokers, inv_securities, inv_imports, inv_trades, inv_holdings, inv_instructions, inv_settings | /investments and /investments/… |
| contract_notes/ | contract-note readers and totals check | — | — |
| depository.py | demat accounts, CAS reading, reconciliation | inv_demats | /investments/demat…, /report/demat/<fmt> |
| mailreader.py | the Hub's mailbox: IMAP, sender checks, auto-import, review | mail_settings, mail_items | /mail, /mail/… (settings, test, check, poll, forget, <iid>, review, text) |
| notify.py | reminder and weekly mails, outbox, scheduler | notify_settings | /reminders, /reminders/save, /reminders/test |
| refunds.py | failed payments, refunds, awaiting refund | txn_refunds | /refunds, /refunds/<rid>, /refunds/expect, /refunds/<rid>/candidates |
| reports_hub.py | section model to xlsx and pdf | (reads all) | /report/view/<fmt> and trades, transfers, director, reimbursements, people-loans |
| itr.py | FY options, ITR summary, FIFO capital gains | (reads) | used by /reports |
| compounding.py | Wealth planner storage and Hub figures | cc_users, cc_actuals | /planner, /api/cc/… |
| help_hub.py | user and design manuals, Markdown subset, PDF | docs/ files | /help, /help/<topic>, /help/find, /help/manual.pdf, /help/internal/design(.pdf) |
| hub_version.py | APP_NAME, VERSION, RELEASE_DATE | — | — |
| features.py | per-user feature switches (hub_settings.features_off / features_done), welcome step, nav / search / route hiding, "add a missing account" | hub_settings | /features, /features/save |
| webutil.py | safe_next(): only local redirect targets | — | — |
| parsers/ | CSV, XLSX, XLS bank exports (auto_parse), legacy categorize() | — | — |

reports/generator.py (legacy monthly workbook) serves /reports/download.

## 3. Repository layout and runtime folders

```
FinanceHub.pyw  app.py auth.py vault.py dbconn.py hub_version.py
importer.py classifier.py organise.py scope.py accounts_hub.py planning.py
ledger.py refunds.py investments.py assets.py depository.py compounding.py
mailreader.py notify.py reports_hub.py itr.py help_hub.py
statement_reader/   engine copy (parsers/, utils/, tools/, version.py)
contract_notes/     parsers/     reports/
templates/          base.html + one template per page
static/             hub.ico, hub.png, planner/ (calculator.js, planner.js)
docs/user/          manual chapters NN-slug.md     docs/design/  DESIGN.md
tests/              synthetic-data tests (not shipped)
tools/              make_release.py upgrade.py shortcuts.py test_contract_note.py
install.bat run.bat requirements.txt CHANGELOG.md .gitignore
```

| Runtime path | Contents | git |
|---|---|---|
| data/ | <hex>.enc, .enc.prev, .enc.tmp (while saving), <hex>_files/ (sealed mail files), <hex>.outbox, <hex>.sent.json, .version (launcher marker) | ignored |
| users.json | user records (4.3) | ignored |
| uploads/ | files being previewed, .pending/ (sealed statement previews), .inv_pending/ (broker files, sealed previews), mail temp files | ignored |
| backups/ | <date>_before_<version>/ encrypted copies | ignored |
| logs/ | hub.log and rotations | ignored |
| .venv/ | the Hub's Python environment (install.bat) | ignored |
| dist/ | release zip and .sha256 | ignored |
| statements/ | optional statement folder read by Reset and reload | ignored |

.gitignore also excludes .enc and .enc.prev files, finance.db and other .db or .sqlite files, __pycache__, .pyc files and requirements.lock.

## 4. Storage and encryption (vault.py)

### 4.1 Files and keys

| File | Format | Key |
|---|---|---|
| data/<hex>.enc (+ .prev) | b'FHUBENC1' + 12-byte nonce + AES-256-GCM(zlib level 6 of SQLite serialize()), AAD = magic | user's DEK |
| uploads/.pending/<token>.json, uploads/.inv_pending/<token>.json | b'FHSEAL1' + nonce + AES-GCM(JSON), AAD 'seal' | DEK |
| data/<hex>_files/mail_<id>.bin or .txt | b'FHBLOB1' + nonce + AES-GCM(zlib bytes), AAD 'blob' | DEK |
| data/<hex>.outbox | b'FHOUTBOX1' + DPAPI blob | Windows account |
| data/<hex>.sent.json | plain JSON, hashed keys only | none |

<hex> is secrets.token_hex(8), so file names say nothing about users.

```
password  --PBKDF2-HMAC-SHA256(16-byte salt, 600000 rounds)-->  KEK
recovery key (normalised)  --PBKDF2-HMAC-SHA256(own salt)-->     RKEK
DEK = 32 random bytes per user
users.json key      = b64(nonce + AES-GCM(KEK,  DEK, aad = user ID))
users.json recovery = b64(nonce + AES-GCM(RKEK, DEK, aad = b"recovery"))
```

Password change and recovery only rewrap the DEK (_rewrap); the database is not re-encrypted. Iterations are stored per entry and _rewrap writes the current ITERATIONS, so the cost can be raised later. For unknown user IDs a PBKDF2 still runs (equal timing). The user ID is the AAD, so it cannot be renamed without rewrapping; no rename exists.

### 4.2 users.json

```
{"version": 2, "settings": {"idle_minutes": 30},
 "users": {"<user ID>": {"salt": "<b64>", "iterations": 600000, "role": "admin",
   "db": "<16 hex>.enc", "key": "<b64>",
   "recovery": {"salt": "<b64>", "iterations": 600000, "key": "<b64>", "created": "<iso>"},
   "created": "<iso>", "last_login": "<iso>"}}}
```

No passwords, names or financial data; user IDs, roles and log-in times are visible. idle_minutes is global. Saved atomically (.json.tmp, os.replace).

### 4.3 The in-memory database

- _open() decrypts, opens sqlite3.connect(':memory:', check_same_thread=False), calls deserialize() and sets a new random V.nonce for this unlock.
- _load() falls back to .enc.prev when the main file is missing or fails to decrypt or decompress (power cut during a save).
- persist(force=False), under V.lock: commits an open transaction; if con.total_changes differs from saved_changes (or force), serializes, encrypts, writes .enc.tmp, renames .enc to .enc.prev and .tmp to .enc.
- Called by close_db after every request, by prepare_db (force) and by lock_now.

Why: SQLite cannot open an encrypted file without an extension such as SQLCipher, which is awkward on Windows. serialize/deserialize keep plaintext in process memory only; the price is re-encrypting the whole file per writing request, acceptable for one household. total_changes skips read-only requests, but any UPDATE counts even with equal values, so record_snapshot makes every view of Home, Accounts and Net worth save the file; ledger.suggest and refunds.scan do so when they add suggestions.

### 4.4 Conn proxy, lock and threads

- V.connect() returns Conn, a connection-like view of the single V.con. Each Conn has its own row_factory for its cursors; close() does nothing (module code may call it freely); with-blocks commit or roll back; other attributes are forwarded (in_transaction, total_changes, serialize…). Used while locked it raises OperationalError('Finance Hub is locked — log in first.').
- check_same_thread=False: the connection is created in the log-in request but also used by the tray thread (lock_now) and the scheduler (serialize).
- V.lock (RLock) guards persist, lock_now, user switching in login and snapshot_con. Request handlers do not take it; they rely on the single server thread.

### 4.5 Locking

lock_now() persists, closes and forgets con, dek, user and nonce. Callers: log-out, app_quit, tray Lock/Quit, log-in as another user, idle check. The idle check in auth._guard locks when time since V.last exceeds idle_minutes (default 30; 0 = never). It runs on the next guarded request and, since the 1.6 review, also once a minute in the background: auth.idle_watch is added to notify.EXTRA_TICKS, so the data is locked on time even with no browser tab open. app.secret_key is random per start, so a restart logs everyone out.

### 4.6 Sealed previews and blobs

dbconn.write_sealed/read_sealed seal JSON with V.seal when unlocked, otherwise write plain JSON (unseal also reads old plain files); importer._store and investments _preview_one use them. V.seal_bytes/unseal_bytes store mail attachments awaiting review and alert texts in V.files_dir (data/<stem>_files/). Sealed files are erased with secure_delete when handled (importer.discard_upload, investments _discard, mailreader._erase_blob) and when the user is removed.

### 4.7 Outbox and sent log

notify.save_outbox writes data/<stem>.outbox: CryptProtectData of the outbox JSON (entropy b'FinanceHub outbox v1', CRYPTPROTECT_UI_FORBIDDEN). It holds prepared mails (due items, amounts if enabled), recipients and SMTP settings including the app password — the only such data outside the encrypted database, hence DPAPI: only the same Windows account on the same PC can read it, yet reminders go out while locked or after a restart. Off Windows the outbox lives only in notify.MEMORY. data/<stem>.sent.json maps sha256(key)[:24] to {at, kind, late} for keys remind:<date> and weekly:<date>, pruned after 120 days.

### 4.8 Plaintext copies

plaintext_copies(base) skips .venv, .git, backups, logs and other program folders and lists every unsealed file under uploads/ (sealed previews starting FHSEAL1 / FHBLOB1 are skipped) plus finance.db-style files (.db, .sqlite, .sqlite3, -wal, -shm) with an SQLite header. secure_delete overwrites with random bytes, fsyncs and unlinks — best effort on SSDs. Setup offers erasure; the Users page lists remaining copies and plain_cleanup (admin) erases them; prepare_db erases uploads older than 24 hours at each log-in.

## 5. Authentication and request lifecycle (auth.py)

### 5.1 The guard

OPEN_ENDPOINTS: login, setup, recover, static, logout, healthz, app_stopped. For all other endpoints _guard does:

1. No user yet: redirect to /setup.
2. Idle time exceeded: lock_now(), clear session, flash.
3. Locked, or session['vault'] differs from V.nonce, or no session['user']: 401 JSON for /api/ paths and JSON requests, else redirect to /login with next (GET only).
4. V.last = now, except for mail_poll.
5. g.user, g.role.
6. Admin only: user_remove, security_settings, plain_cleanup, user_save with action add or role.
7. No recovery key yet, on a GET: create one, put it in session['show_recovery'], redirect to recovery_show.

The nonce binds a browser session to one unlock; another log-in changes it and older sessions return to the log-in page.

### 5.2 Roles and flows

- admin: add users, change roles, remove users (their .enc, .enc.prev and _files are secure-deleted), idle setting, plaintext clean-up, design manual. member: their own database. One admin must remain; nobody removes themselves. No admin can read or reset another user's data, because the DEK is reachable only via that user's password or recovery key.
- Setup: _check_new requires a user ID of 3+ characters (letters, digits, . _ -) and a password of 10+ characters using three of lower, upper, digits, symbols/space. V.setup creates the admin and database, prepare_db() builds the schema, the recovery key is shown once.
- Log-in: V.login unwraps the DEK, prepare_db() upgrades the schema, the session gets user and nonce; next only if it starts with a single slash. From the third failure per user ID the wait is 5 s, doubling to 300 s (in memory).
- Users added by an admin get their recovery key at their first GET. recovery_new replaces it.
- /recover: user ID + recovery key (case, spaces, dashes ignored) + new password rewraps the DEK; the key stays valid. Password change: own account only, current password checked via V.login.
- Recovery key: 28 characters from a 32-letter alphabet without I, O, 0, 1, in seven groups of four (about 140 bits).

### 5.3 Display name and user ID

The user ID is typed at log-in, keys users.json and is the AAD of the wrapped DEK. The person's name is hub_settings.display_name inside the encrypted database (max 60 characters; set at setup or user creation, changed with /profile/save). auth._inject_user gives it to templates; the Hub greets with display_name, or the user ID when empty. Reason: users.json is readable by anyone with the folder, so it must hold no names (1.3).

### 5.4 mail_poll, healthz, app_quit, app_stopped

- mail_poll is a background POST every 60 s. If it refreshed V.last an open tab would keep the Hub unlocked for ever, so _guard skips the activity update for it while the idle check still applies (tested in test_mail_inbox.py).
- /healthz (open) returns "FinanceHub <version>" only; used by the launcher and tools/upgrade.py.
- /app/quit (POST, logged in): with the launcher (HUB_SHUTDOWN) locks the vault, schedules shutdown after 0.6 s and redirects to /app/stopped (open, static page); otherwise explains how to stop the command-window server.
- /app/autostart (POST) toggles Start with Windows through the launcher hook.

## 6. Data model

### 6.1 Migration approach

app.prepare_db() runs right after every unlock (setup and each log-in), and every step is idempotent:

```
init_db()                     transactions, accounts, passwords, loans
importer.ensure_schema()      statements, new columns, classifier.ensure_schema(),
                              classify rows with category_id NULL
investments.ensure_schema()   inv_ tables, settings, default brokers,
                              depository.ensure_schema() + old CAS broker migration
compounding, accounts_hub, planning, scope, ledger, assets,
mailreader, notify, refunds:  ensure_schema()
seed_passwords(); seed_data() empty since 1.2
V.persist(force=True); notify.mark_dirty(); erase uploads older than a day
```

Rules: CREATE TABLE IF NOT EXISTS; new columns via PRAGMA table_info + ALTER TABLE ADD COLUMN with a default; seeds with INSERT OR IGNORE; data migrations guarded and repeatable (depository._migrate_old_cas_broker, accounts_hub.backfill_kinds); never drop or rename columns (transactions.category and accounts.type are kept in step). investments, depository, mailreader, notify and refunds also call ensure_schema from con_() per request. Classification runs before scope adds entities.role/aliases and accounts_hub adds accounts.entity, so classifier catches sqlite3.OperationalError for them — mind this when reordering.

### 6.2 Relations

Account names are keys: transactions.account = accounts.name, also loans.card, statements.accounts ('; '-separated), recurring.account, pl_moves.our_account. accounts_hub.rename_account updates transactions, loans and statements. Books and payers are entity names (transactions.entity, accounts.entity, rules.entity, pl_loans.book, transactions.reimb_payer). Everything else uses ids. Foreign keys are not enforced; deletes clean up dependants in code.

### 6.3 Tables by module

| Module | Table | Key columns and notes |
|---|---|---|
| app, importer, classifier, ledger | transactions | date, description, amount (always positive), type debit/credit, account, cardholder, statement_id, reference, narration, category_id, payee, display_name, entity, person, manual, rule_id, notes, reimb_payer, reimb_claim; category = Head name (legacy) |
| app, accounts_hub | accounts | name (unique), card_no, bank, type (importer: credit_card, savings, current, loan…), kind (bank, card, loan, emi, deposit, broker, wallet, asset), subtype, entity (book), billing_day, due_day, rate, maturity fields, status |
| app, importer | loans | lender, card (account), emi_amount, total_emis, emis_paid, first/last_emi_date, interest_rate, status, loan_ref, outstanding, last_statement_date, source, repayment (monthly/bullet) |
| app | passwords | institution (unique), label, password, hint — statement passwords |
| importer | statements | file_name, file_hash, bank, statement_type, accounts, period, statement and due dates, totals, check_status OK/MISMATCH/n/a, check_detail (JSON balance rows), reader_version |
| accounts_hub | account_balances, networth_snapshots, hub_settings | manual balances (account_id, as_of); one snapshot per day; key/value (display_name) |
| classifier, scope | categories, rules, entities, people | categories (parent_id, name, level 1–4, kind); rules (pattern, match_type contains/payee, category_id, display_name, entity, person); entities (name, role book/payer/other, aliases); people (name, aliases; 'Self' = owner's name variants) |
| planning | recurring, budgets, alert_state, month_close | recurring (name, match_key, amount, freq, next_date, account, rtype, status); monthly budget per category_id; snoozes; checklist per month and item |
| ledger | txn_links, reimb_claims, reimb_receipts, contacts, pl_loans, pl_moves | links (out_id, in_id, counter_kind, counter_ref, kind, status suggested/confirmed/rejected, score, reason); claims and receipts per payer; loans with people (book, person, direction given/taken, due_date, status) and their moves (kind principal/repayment/interest/waived, mode, our_account, txn_id) |
| refunds | txn_refunds | kind failed/refund/expected, debit_id, credit_id, status suggested/confirmed/rejected/waiting/received/closed, expected, follow_up_days, prev_debit_cat, prev_credit_cat |
| investments, assets | inv_brokers, inv_securities, inv_imports, inv_trades, inv_holdings, inv_instructions, inv_settings, inv_asset_types | securities (symbol+exchange unique, isin, bucket core/satellite, plan_status, cmp, asset_type); imports (file_hash unique); trades (broker_id, security_id, trade_date, side, qty, price, charges, trade_id); holdings (broker_id or demat_id, as_of, qty, close_price); instructions BUY/ADD/TRIM/SELL |
| depository | inv_demats | depository CDSL/NSDL, dp_name, dp_id, client_id, account_no (unique), broker_id; adds demat_id to inv_holdings and inv_imports |
| mailreader, notify | mail_settings, mail_items, notify_settings | key/value settings (mailbox, allowlist, last_uid; reminder options); mail_items (message_id, from_domain, auth, status, kind, file_hash, blob, note, result) |
| compounding | cc_users, cc_actuals | planner users (params, goal JSON) and year-end records |

## 7. Classification

### 7.1 Tree and kinds

classifier.TREE seeds four Types: Income (kind income), Expenses (expense), Transfers (transfer), Investments (investment). Levels: 1 Type › 2 Head › 3 Sub-head › 4 Item. Each node stores its kind; cat_move moves a subtree and gives it the new parent's kind; Types cannot be renamed, moved or deleted; nothing goes deeper than level 4. path_id() finds or creates a path. transactions.category holds the Head name (head_name, refreshed by _refresh_heads). Modules create nodes on demand (ledger EXTRA_NODES and PL_PATHS, refunds FAILED_PATH, Transfers › Reimbursable › <payer>).

### 7.2 Rule order

Classifier(con) loads everything once per batch; classify(t) decides:

1. User rules (rules table), longest pattern first: payee = payee_key(description) equals the pattern; contains = pattern found in "DESCRIPTION NARRATION" upper-cased. A rule may set display_name, entity, person, and ends the search only with a category_id. Charge lines (CHARGE_ROW) never match user rules, so a merchant rule cannot swallow its fee.
2. Built-in rules, first part RULES[:_SPLIT]: card bill payments, card EMI conversion/interest/principal, processing fees, bank and card charges, loan-account rules and loan EMIs.
3. Profile rules (classifier.profile_rules), inserted at _SPLIT (the 'Pension credit' rule): Self aliases → Transfers › Own accounts; other people → Expenses › Family & Personal › Transfers to family (debits, sets person); payers → Income › Salary & Remuneration › … › Consultancy fees (credits); books → Income › Business Income (credits) and Investments › Own business (debits), skipped for the book's own accounts (not_book).
4. Built-in rules, rest: income, own accounts and cash, investments, business expenses ('__company__' = first non-Personal book), merchants by area, refunds, then person-to-person UPI/IMPS/NEFT.
5. Fallback: a credit on a card → Income › Refunds & Rewards › Refunds › Merchant refunds; else To review (Expenses › Uncategorised for debits, Income › Other Income for credits).

Built-in options: type, acct (credit_card/savings/loan from _acct_kind), acct_name, max amount, entity, person, name ('__dividend__' and '__remittance__' compute it). Why profile rules sit in the middle: structural rules must beat a name (a card bill paid "to" your own name is still a card bill), and names must beat generic merchant and UPI rules (a UPI payment to family is not a stranger). person_for() maps card holders to people.

### 7.3 Manual rows

apply_to_rows(con, where, params, only_unclassified, commit) re-classifies rows matching where, by default COALESCE(manual,0)=0: rows with manual = 1 are never changed. manual = 1 is set by a one-transaction edit or bulk edit, and by features that own a row's category: confirmed links, reimbursement marks and receipts, people-loan moves, refund confirmations. Saving a payee rule clears manual on the edited row (and with override_manual on all matching manual rows) and re-applies rules. api_txn_reset and the undo paths (ledger.undo, clearing a reimbursement, deleting a loan move) set manual = 0 and re-classify. Rules › Re-apply with include_manual clears manual everywhere except on rows owned by those features (since 1.6).

### 7.4 Netting and transfers

organise.net_value: expense and investment = debits - credits (a refund in the same category lowers spending); income and transfer = credits - debits. Insights (dashboard_data), Breakdown, reports_hub.view_report and itr.summary group by kind and show Transfers separately or not at all; an uncategorised row counts as expense; dashboard_data and itr skip rows with reimb_payer. Transfers are excluded because their other side is already counted or is not consumption: a card bill paid from the bank would count every card purchase twice, and own-account moves, loan principal, ATM cash and broker funding are not spending. Loan interest stays an expense.

## 8. Import pipelines

### 8.1 Bank and card statements (importer.py)

```
POST /import/preview -> save_upload -> uploads/<token>_<name>
  preview_file(): PDF -> find_password -> auto_detect_parser -> parse -> _from_engine
                  CSV/XLSX/XLS -> parsers.auto_parse -> _from_tabular
                  duplicates, old-reader rows, _mark_duplicate_txns, default_selected
  _store() -> sealed uploads/.pending/<token>.json ; browser gets public_view()
POST /import/password  -> preview again with a typed password (optionally saved)
POST /import/confirm   -> load_pending -> commit_preview -> discard_upload
```

- Passwords: saved passwords are tried; else status needs_password. The password stays in the sealed preview (_password); public_view drops it and the file path.
- Balance check: check_status OK when every engine accounts row says Check OK, MISMATCH otherwise (warning, not ticked), n/a with no rows (always for spreadsheets).
- Account resolution, resolve_account(): (1) last four digits at the same bank; (2) distinctive card-name words in an account name; (3) the only account of that bank and type (not loans, not with a different known number), filling a missing number; (4) a new account named from bank, type and last four digits. Multi-account statements map each balance row; EMI letters never create accounts.
- book_for_holder(): when the holder or card name contains a book name or alias (4+ characters, whole words), the new account belongs to that book and is prefixed with its name.
- Duplicates: same file hash (statements.file_hash); same accounts, period and statement date; per account, rows equal on date, amount and type counted with multiplicity ('already in Hub'); rows of the pre-engine reader for the same file (statement_id NULL) are replaced. EMI-schedule rows are skipped.
- default_selected: ok, not a duplicate statement, not MISMATCH, generic reader only with check OK, something new.
- commit_preview re-checks hash and rows, then in one transaction creates accounts, inserts the statement and new rows, classifies them, sets entity from a company account's book and creates or updates loans; on error it rolls back. discard_upload secure-deletes the upload and the sealed preview. The preview's legacy category (hub_category) is replaced at commit by the classifier.
- Loans: loan_key(lender, ref) = '<bank code>:<last 4>' for masked numbers, else the lower-case reference. New keys create a loan (_loan_name); known keys update paid count, outstanding, status and EMI only if this statement is not older than last_statement_date, and fill empty fields.
- Also: delete a statement with its rows, clear a date range (import_clear_fy), delete all, Reset and reload from statements/ (import_folder skips unknown passwords, duplicates and MISMATCH).

### 8.2 Investments: contract notes and broker files

- Upload: /investments/import/preview stores uploads/.inv_pending/<token><ext> and a sealed <token>.json (path, hash, parsed result, broker guess).
- PDFs: open_pdf_text tries no password, then each typed or saved password as typed, upper and lower case. classify_pdf: 'CONTRACT NOTE' + ISIN = contract note; CAS or holding statement with DP ID or BO ID = depository (8.3); ledgers, margin and exchange-balance statements = information only.
- contract_notes.read() picks the reader with the highest keyword score (Upstox, SBICap) or falls back to Generic (SEBI common format) with a warning. Reader.parse reads trade date, contract number, trade lines (TRADE_LINE; F&O skipped and counted), printed obligation, net amount and levies.
- Reconciliation (ContractNote.reconcile, tolerance ₹1): sum of buys - sum of sells = printed obligation, and obligation + levies = printed net; result OK, MISMATCH or n/a (nothing printed). spread_charges spreads charges over trades by value.
- CSV/XLSX/XLS tradebooks and holdings: header rows found through ALIASES; side + price columns = tradebook, otherwise holdings; NON_EQUITY segments skipped.
- Duplicates: inv_imports.file_hash is unique; trades are dup by trade_id, else by (ISIN or symbol, side, date, qty, price) with multiplicity per broker. Flags: importable (something new, not a duplicate file) and tick (importable, not MISMATCH).
- _confirm_one/_commit insert trades and holdings, update cmp, then match_instructions closes open instructions with matching trades (same stock and side, on or after the date, 90 % of the quantity). Files are secure-deleted.
- investments.HOOKS (set in register()): preview, confirm, render, discard, pend. The mail reader uses them so it shares the Import page's exact code.
- Portfolio: positions() replays trades at weighted-average cost; securities without trades use holdings statements; suggest() applies the TF tranching settings (tranche = stock limit ÷ max tranches, TRIM above limit + tolerance, dip/rise/gap add rules, sector cap, Core/Satellite shares).

### 8.3 Depository CAS (depository.py)

CDSL and NSDL hold securities; they are not brokers. Each demat account is an inv_demats row keyed by account_no: the 16-digit BO ID (CDSL) or DP ID + 8-digit client ID (NSDL DP IDs are IN + 6 digits). masked() shows the last four digits.

parse_text() reads line by line: as_of from "for the period … to" or "as on/as of/statement date"; a line with a BO ID, or DP ID + client ID, starts a demat section, named by a DP NAME up to four lines before; a folio line without an ISIN ends it (mutual-fund folios are skipped); each ISIN line in a section is a holding, the name running until the trailing numbers.

Heuristic _qty_price_value: price and value are the last two numbers; quantity is the first earlier number c > 0 with c × price within max(₹1, 0.5 % of value) of value, else the first number. Why: CDSL prints free, frozen and pledged balances before price and value, NSDL prints face value before quantity; the product test fits both without layout code.

commit(): find_or_create each demat (broker guessed by guess_broker: the broker's demat number, its name in the DP name, DP_HINTS); one inv_imports row; per demat, DELETE inv_holdings for (demat_id, as_of) then insert (broker_id NULL). Replace-on-same-date: an NSDL and a CDSL CAS of the same month both list every demat, so importing both must not double the holdings. A demat can be chosen by hand (sel 'd<id>').

reconcile(con, broker_filter) compares each demat's latest holdings with its linked broker's trades:

```
settled  = net qty of the broker's trades with settles_by(trade_date, as_of)
transit  = net qty of trades up to as_of that settle after it
after    = count of trades after as_of (noted in the hint)
settles_by: next business day after the trade (Sat/Sun skipped) <= as_of   (T+1)
```

| Condition (first match) | Status | Tone |
|---|---|---|
| no linked broker | no broker linked | slate |
| demat = settled | matches (transit noted) | green |
| demat = settled + transit | matches (statement-day trades) | green |
| settled is zero, demat holds some | not in broker trades | amber |
| demat holds none, settled positive | missing in demat | red |
| anything else | quantity differs (+ bonus or split hint) | red |
| matches, but broker holdings statement differs | broker statement differs | amber |

Equality uses EPS 0.001. The by-broker view sums linked demats at the earliest of their dates (mixed_dates flag). Rows sort red, amber, slate, green. investments.latest_holdings keeps broker quantities (qty) and depository quantities (cas_qty) apart.

### 8.4 Mail reader (mailreader.py)

#### IMAP flow

1. IMAP4_SSL (port 993) with a default SSL context; LOGIN with the address and app password from mail_settings.
2. SELECT the folder; a new UIDVALIDITY resets last_uid.
3. UID SEARCH SINCE today - since_days (default 60), narrowed to last_check - 2 days once last_uid is known; UIDs above last_uid, at most 120 per run.
4. Header first: UID FETCH BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)] RFC822.SIZE; known Message-IDs skipped.
5. Sender neither allowed nor a forwarder: 'ignored', body never downloaded.
6. At most 30 downloads per run; over 40 MB: 'error'. BODY.PEEK[] keeps mails unread.
7. auth_check; failures are 'rejected' and go no further.
8. No PDF/CSV/XLSX/XLS attachment: 'alert'; stripped body text (20 000 characters) sealed as mail_<id>.txt.
9. Attachments: over 20 MB 'error'; hash already handled 'duplicate'; else process_file; review files sealed as mail_<id>.bin.
10. Commit, then label: Gmail X-GM-LABELS via UID STORE, elsewhere UID COPY into a folder of that name; errors ignored.
11. Save last_uid, uidvalidity, last_check, last_result.

#### Allowlist and trust model

mail_settings.senders lists domains (DEFAULT_SENDERS: generic public domains of Indian banks, card issuers, brokers, depositories, registrars; bank.in is reserved for regulated banks). domain_on_list accepts the domain or its subdomains, never look-alikes (fakebank.in does not match bank.in). Allow on an ignored mail adds its domain, deletes its ignored rows and resets last_uid.

auth_check() trusts the receiving server's verdict and reads only the topmost Authentication-Results header, the one that server added last; lower headers may be forged by the sender. For a Gmail mailbox (trusted_servers_for) its authserv-id must be mx.google.com; other hosts are not restricted. pass = dmarc=pass with a matching header.from organisational domain, or dkim=pass whose header.d/header.i has the From address's organisational domain (aligned DKIM; org_domain knows co.in, bank.in, co.uk…). Otherwise fail or none, both rejected.

#### Forwarded mails

Mails from mail_settings.forwarders must pass auth_check for the forwarder's domain; the original sender, the first "From:" line in the body (forwarded_from), must be on the allowlist. They get auth 'forwarded' and always wait for review, because the original sender cannot be verified.

#### Auto-import criteria (process_file)

- PDFs first go to investments HOOKS['preview']. A contract note or depository statement is confirmed only if automatic import is on, the sender passed, the preview is importable and ticked, and the broker is known (or demat accounts were found). Otherwise review, with the reason.
- Then importer.preview_file. needs_password: review; not ok: skipped; duplicate: duplicate. commit_preview only when automatic import is on, the sender passed, check_status is OK (spreadsheets always wait), no new account is needed and something is new.
- Temporary plaintext files in uploads/ are secure-deleted on every path.

#### Review and limits

- /mail calls refresh_review: items whose hash now appears in statements or inv_imports become imported and their sealed copy is erased.
- Review unseals to a temp file and opens the normal preview (Import page with pending=<token>, or the investments preview). Dismiss erases the copy; retry re-runs process_file with automatic import; forget clears handled history.
- Checks run only while unlocked and a Hub page is open: base.html posts /mail/poll after 4 s and every 60 s while visible; due() checks enabled, credentials and interval; Check now forces a run. The scheduler never reads mail.
- Limits: MAX_FILE 20 MB, MAX_PER_RUN 30, interval 5–1440 minutes (default 15), since_days 1–400.

## 9. Ledger features

### 9.1 Transfer links

ledger.suggest() runs when Transfers & links opens, over unlinked transactions of ₹1 or more in known accounts. Two-sided pairs: a debit (not income kind) and a credit in another account, same amount within ₹1, 2 days before to 6 days after. Score: 10 - gap in days; +8 when the narration names the credit's account (card_from_text via CARD_HINTS and consonant skeletons, or account_from_digits); +3 for a card credit saying PAYMENT, THANK YOU, AUTOPAY…; -4 for card-to-bank. Pairs are taken greedily, each transaction once, from score 6; rejected pairs never return. decide_kind: different books → owner_capital (personal to company) or owner_drawings (company to personal); else card_payment, loan_payment or self_transfer by the receiving account. One-sided links (score 5) cover a named own account, broker or clearing payments (BROKER_HINTS → broker_funding / broker_withdrawal), and owner-company movements found by the owner's name or a company name.

confirm() sets both categories (manual = 1):

| kind | money-out side | money-in side | director sign |
|---|---|---|---|
| card_payment | Transfers › Card bill payments › Paid to cards | Transfers › Card bill payments › Received on cards | 0 |
| self_transfer | Transfers › Own accounts › Self transfer | same | 0 |
| loan_payment | Transfers › Loan repayments › Principal | same | 0 |
| broker_funding | Investments › Market › Broker | — | 0 |
| broker_withdrawal | — | Investments › Market › Broker | 0 |
| owner_capital | Investments › Own business › Transfers to business | Transfers › Owner & director › Received from director | +1 |
| owner_drawings | Transfers › Owner & director › Paid to / for director | Transfers › Owner & director › Received from company | -1 |
| owner_repay | Transfers › Owner & director › Repaid to director | Received from company | -1 |
| owner_salary | Expenses › Business Expenses › Director remuneration | Income › Business Income › Director remuneration | 0 |

(Paths shortened; LINK_KINDS holds all four levels.) owner_repay and owner_salary are chosen by the user, never suggested. Reject restores automatic classification and keeps the link 'rejected'; delete removes it. link_manual offers opposite-type candidates within ₹1 and 15 days.

### 9.2 Director's account

director_ledger(con, book): confirmed owner links touching the book, with effect = sign × amount, plus company expenses paid from personal accounts (entity = book, expense kind, Personal account) as positive. A positive balance means the company owes the owner; owner_salary (sign 0) is income/expense, not balance. A start date turns earlier rows into the opening balance.

### 9.3 Reimbursements

For expenses paid for a payer entity: reimb_mark sets reimb_payer, manual = 1 and Transfers › Reimbursable › <payer> › Expense to claim; reimb_claims group them (transactions.reimb_claim). reimb_state finds credits matching payer_regex (first word of name and aliases): each becomes a fee (normal income), a receipt (… › Reimbursement received) or is applied to a claim (reimb_receipts; suggested claim = equal open balance, else oldest open). A claim is paid when receipts reach its total (₹1 tolerance). Both sides are Transfers, so spending and income stay clean; dashboard_data and itr also skip reimb_payer rows.

### 9.4 Loans with people

pl_loans (book, person, direction given/taken, due date) and pl_moves (principal, repayment, interest, waived; mode from MODES; our_account; their bank details) with contacts keeping each person's first-given details. pl_rows: outstanding = principal - repaid - waived; overdue when the due date passed, open, over ₹0.50. pl_candidates links a move to a transaction (same amount within ₹1, ±7 days, right direction, same book, unused); the transaction gets the PL_PATHS category (Transfers › Loans with people, or the interest heads), manual = 1 and the person. A loan closes at ₹0.50 or less; deleting moves or loans restores automatic classification. Borrowed loans with a due date feed the reminders.

### 9.5 Failed payments and refunds (refunds.py)

scan(con, since_days=400) runs when the page opens, over rows not in an active refund row or confirmed link:

1. Failed & reversed: credit and debit in the same account, same amount, credit 0–10 days later, credit matching REV_RE (REV, REVERSAL, FAILED, RETURN, DECLINED, CHARGEBACK…) or both sharing a 12-digit UPI/IMPS reference. Score: reference 10, keyword 5, within a day 2, debit says failed 2, plus shared words.
2. Refunds: a credit up to 120 days after a purchase, not above it (+₹1), sharing the reference, or saying REFUND/RFND/REVERSAL/CHARGEBACK with shared merchant words, or the purchase is awaited. Score: reference 8, 3 per shared word, same account 3, equal amount 4, awaited 6 (+4 if expected amount matches), -1 per 30 days; 6 or more.
3. Debits saying FAILED/DECLINED/UNSUCCESSFUL, 3+ days old, are suggested as awaiting refund.

Confirm: failed → both rows to Transfers › Failed & reversed › Failed payments › Reversed by bank (previous categories saved), so neither counts. refund (or expected with a credit) → the credit takes the purchase's category; since expense nets debits - credits, that category's spending falls by the refund; waiting expectations for the purchase become received. expected without a credit → waiting. Undo restores saved categories; a received expectation returns to waiting, anything else becomes rejected (not suggested again). Refund categories carry manual = 1. Waiting rows older than follow_up_days (15) are late and listed in the weekly mail.

## 10. Notifications (notify.py)

### 10.1 Events

events(con, start, days) = accounts_hub.dues(con, b, …) with b = AH.build(con, ignore_scope=True) and recurring = planning.recurring_for_dues (all types but income): unpaid card bills, expected bills from billing/due days, EMI and loan instalments, bullet repayments, deposits maturing (inflows), recurring items — minus paid ones — plus money borrowed from people (ledger.pl_rows: taken, open, due within the window). overdue() = events of the last 45 days marked overdue or "payment not seen yet".

### 10.2 Outbox

build_outbox() returns None unless enabled, with a valid recipient and SMTP host, user and password. Reminders: events of the next 16 days grouped by date, one mail per date, send_at the day before at remind_time (09:00), until noon on the due day. Weekly report: weekly_day (6 = Sunday) at weekly_time (08:00) until 23:59, prepared for this and next week; lists the next 7 days, the following 7, overdue items (first mail) and awaited refunds. amounts = 0 hides amounts. Keys: remind:<date>, weekly:<date>.

### 10.3 Scheduler and snapshot connection

start_scheduler() runs tick() every 60 s in a daemon thread:

- maybe_rebuild(): only while unlocked, when mark_dirty() was called (by close_db after a save, by prepare_db), after an hour, or after midnight.
- run_due(): for every outbox (MEMORY plus DPAPI files of all users, locked or not), send each unsent message inside its window; retry failures after 15 minutes (_FAILS); record success in the sent log (late if over an hour after send_at).

maybe_rebuild never touches the shared connection: snapshot_con() serialises V.con under V.lock into a private in-memory copy, and rebuild() runs build_outbox inside APP.test_request_context('/'), so no Viewing filter applies. Why: the shared connection belongs to the request thread (cursors, transactions, row factories), sqlite3 objects must not be used concurrently, and reminders must cover all accounts whatever the user views.

### 10.4 DPAPI and SMTP

_dpapi() wraps CryptProtectData/CryptUnprotectData via ctypes, binding the outbox to the Windows account so reminders can be sent while locked or after a restart. Off Windows only MEMORY is used. smtp_for() takes user and app password from mail_settings; the host is notify_settings.smtp_host or derived from the IMAP host (Gmail → smtp.gmail.com, imap.x → smtp.x); port 465 uses SMTP_SSL, others STARTTLS. /reminders/test sends a test report; HUB_SMTP_FACTORY lets tests replace the client.

## 11. Viewing filter, reports and UI conventions

### 11.1 scope.py

The Viewing filter is session['scope']: book, account or broker (+ label), set by /scope (next must be local). txn_sql(alias) returns SQL and parameters: Personal = entity not a company book; another book = that entity; account = account name; broker alone = transactions linked to it in txn_links; nothing = '1=1'. txn_literal() inlines parameters for helpers that take only a WHERE string (dashboard_data, planning.detect, alerts). account_in_scope() filters accounts in accounts_hub.build; broker_id() serves investments, assets and depository pages. Code that must see everything uses ignore_scope=True or a fresh request context (notify).

### 11.2 Reports (reports_hub.py)

A report is {title, subtitle, sections}; a section is 'kv' (label/value rows) or 'table' (columns, rows, money columns, totals columns). to_xlsx makes one sheet per section (Indian grouping '#,##,##0.00', red negatives, totals row, frozen header, autofilter); to_pdf makes landscape A4 with reportlab and a dated, numbered footer; send(rep, fmt, stem) returns the file. Builders: view_report (summary, heads, months, accounts, transactions, linked transfers), trades, transfers, director, reimbursements, people loans; depository.report_demat uses the same model.

### 11.3 base.html

- nav_groups: (id, label, icon, tone, items), items = (label, endpoint, args, icon, active test); groups Home, Accounts, Money, Investments, Plan, Settings; open state remembered in localStorage.
- Tones: CSS variables --indigo, --teal, --coral, --amber, --violet, --blue, --green, --pink, --slate, --red; class tone-<name> sets --tone for cards, chips, pills, bars, icons (t-tone, bg-tone-soft). Light/dark via data-bs-theme; choice in localStorage hub_theme.
- Cards and pieces: stat-card, chart-card, card-head, kpi, chip, pill-tabs, list-row, soft-box, bar, num, muted.
- Top bar: Viewing filter, Ctrl+K palette (/api/search over planning.PAGES and data), alerts bell (/api/alerts/count), theme, Report menu (block report_menu), help "?" (help_page with topic = request.endpoint), Lock, Quit (only if hub_launcher).
- Mail badge: review count from mailreader._mail_ctx; with mail_auto the poll script (8.4) updates it and shows a toast.
- Feature switches (features.py): the context processor gives hidden_eps and hidden_kinds; the nav loop builds a visible item list per group (a group with no visible items is not drawn), accounts tabs drop hidden kinds, planning.search drops hidden pages, and features._features_guard redirects a hidden page to /features. The first GET of Home for a user without hub_settings.features_done goes to /features?welcome=1 (skipped when app.testing unless FH_WIZARD is set). Nothing is deleted when a feature is off; demat requires investments; card & loan tools stay while cards or loans are on.
- Blocks: title, head, page_title, report_menu, content, scripts.

> **Important:** A top-level `{% set %}` in base.html overrides a view variable of the same name, even inside the child template's blocks. That is why base.html uses nav_groups, _ep and _tab instead of groups, ep or tab (accounts.html relies on its own tab). Never add a top-level set with a common name to base.html.

### 11.4 External assets

base.html and auth_base.html load Bootstrap 5.3.2, Bootstrap Icons, Chart.js 4.4.1, jQuery 3.7.1 and DataTables from cdnjs, and the Inter font from Google Fonts, without integrity attributes.

## 12. Help system (help_hub.py)

- Chapters: docs/user/NN-slug.md (slug without the number), optional endpoints and icon comments; chapters() caches by file names and modification times.
- Markdown subset: headings # to ####, paragraphs, - / * / 1. lists (two-space nesting, three levels, indented continuation lines), tables, fenced code, > callouts (Important and Warning shown as warnings; Tip, Note, Good to know as tips), --- rules; inline bold, italics, code and links to help:slug#anchor, /path, #anchor or https://. HTML is escaped; repeated heading ids get -2, -3.
- Mapping: "?" opens /help/<endpoint>; chapter_for matches a slug, then a chapter listing the endpoint, and redirects to /help/<slug>#<anchor>; unknown topics go to the index.
- Search: every word must occur in a section; score = occurrences + 5 per word in its title; top 20 with snippets.
- PDF: reportlab, cover with contents, a page per chapter, footer. Text is mapped to Helvetica's character set (rupee sign → Rs, arrows and dashes replaced); code blocks print verbatim in Courier, so keep them ASCII and under about 95 characters. /help/manual.pdf holds all chapters; design_pdf splits DESIGN.md at level-1 and level-2 headings.
- Design manual: /help/internal/design and its PDF are admin-only (403 otherwise, 404 if missing).

## 13. Security model

| Threat | Mitigations | Residual risk |
|---|---|---|
| Copied folder or stolen disk | AES-256-GCM files; DEK wrapped by PBKDF2 (600 000) of password or recovery key; sealed previews and mail files; uploads erased after import and after a day; DPAPI outbox | guessing weak passwords offline (limited by rules and PBKDF2 cost); users.json reveals IDs, roles, log-in times; secure delete is best effort on SSDs; logs may hold error texts |
| Another Windows user | profile-folder permissions; server on 127.0.0.1 and every guarded request needs a cookie signed with a per-start secret plus the vault nonce; outbox bound to the Hub's Windows account | other users reach the port's open endpoints; a PC administrator can read memory while unlocked |
| Malicious mail | allowlist, header-first fetch, type and size limits, own parsers only, no links followed, HTML never rendered (alerts kept as stripped text), auto-import only when every check passes | bugs in pdfplumber, pikepdf, openpyxl, xlrd; a hostile but validly signed mail from an allowed domain |
| Look-alike senders | exact or subdomain match; DMARC or aligned DKIM from the topmost Authentication-Results; mx.google.com required for Gmail; forwarded mails never auto-import | non-Gmail hosts: any topmost header is trusted; broad entries such as bank.in |
| Stolen app password | kept only in the encrypted database and the DPAPI outbox; dedicated mailbox advised; Hub reads (BODY.PEEK), labels, sends to set recipients | an app password gives full mailbox access until revoked; no OAuth |
| Localhost server | binds 127.0.0.1; Waitress clears untrusted proxy headers; next checked at log-in and profile | no CSRF tokens or SameSite cookie; /logout and /scope change state on GET; CDN assets without integrity |
| Forgotten password | recovery key wraps the same DEK | losing both loses the data — by design, no back door |

Out of scope: malware running as the same Windows user (memory, keystrokes, DPAPI); someone using an unlocked Hub at the PC (idle lock and Lock limit it); copies of backups/ taken elsewhere (they stay encrypted); isolation between Hub users beyond separate keys (one process, one open database).

## 14. Versioning, release and upgrade

### 14.1 Versions and git

- Every change gets a new version: hub_version.VERSION and RELEASE_DATE, plus a "## <version> — <date>" entry on top of CHANGELOG.md, written for the user. Versions run 1.1, 1.2…; earlier history was deleted at the owner's request. The version shows in the sidebar, /healthz and the release name.
- The Statement Reader engine has its own version, statement_reader/version.py APP_VERSION (v14), and statement_reader/CHANGELOG.md; it changes only with a new export. compounding.APP_VERSION is the planner engine's version.
- git: one annotated tag per version (v1.5, v1.6…) on the commit the zip was built from; make_release prints git describe --tags --dirty. Commit subject "Finance Hub <version> — <summary>", body with what and why (user-facing list in CHANGELOG.md), attribution trailers last, as in the 1.5 baseline. Never commit runtime folders, statements or real samples.

### 14.2 tools/make_release.py

1. CHANGELOG.md must have a "## <VERSION>" heading.
2. Privacy scan of text files (.py .pyw .html .md .bat .txt .json .js .css .cfg .toml) for PAN, card and account numbers, Aadhaar, IFSC, mobile numbers and e-mail addresses, with allow-lists for synthetic values; findings stop the build unless --allow-findings. It cannot detect names — review diffs for them.
3. tests/run_all.py unless --skip-tests; failures stop the build.
4. dist/FinanceHub_<VERSION>.zip without data, uploads, backups, logs, .venv, .git, dist, __pycache__, tests, statements, users.json, requirements.lock, finance.db and .enc, .prev or .pyc files; MANIFEST.sha256 inside; FinanceHub_<VERSION>.zip.sha256 beside it.

### 14.3 tools/upgrade.py

1. Verify every file against the zip's MANIFEST.sha256; refuse damaged zips and zips containing data folders or users.json.
2. Refuse while /healthz answers on 127.0.0.1:5000.
3. Back up the .enc and .enc.prev files and users.json to backups/<date>_before_<version>/.
4. Write the program files and the new MANIFEST.sha256.
5. Delete .py, .pyw, .html, .md and .bat files of the old manifest that the new one lacks.
6. pip install -r requirements.txt into .venv (or advise install.bat).

### 14.4 Launcher backup and installation

- backup_on_upgrade(): when data/.version differs from VERSION and encrypted data exists, copy .enc, .enc.prev and users.json to backups/<YYYY-mm-dd_HHMMSS>_before_<VERSION>/ with FROM_VERSION.txt, write the marker, keep the newest 10 folders. Backups stay encrypted; sealed mail files, outbox and sent log are not copied.
- install.bat: finds Python 3.10+, creates .venv, installs requirements.txt, writes requirements.lock, runs tools/shortcuts.py and starts the launcher; safe to repeat, never touches data. run.bat starts .venv pythonw with FinanceHub.pyw, or install.bat if .venv is missing.
- tools/shortcuts.py creates "Finance Hub" shortcuts on the Desktop and Start menu via PowerShell (Windows only). Start with Windows is an HKCU Run value with --background.

## 15. Testing

- tests/_common.fresh(name) copies the program (without .git, .venv, data, users.json, uploads, backups, logs, dist, databases, tests) to a temp folder, changes into it and puts it first on sys.path: tests never touch real data.
- tests/run_all.py runs each tests/test_*.py in its own process, prints PASS/FAIL with the output tail, and exits 0 only if all pass.
- Synthetic data only: invented names, accounts such as "Test Savings 1111", made-up ISINs, fake IMAP and SMTP.

| Test | Covers |
|---|---|
| test_core.py | setup and weak passwords, recovery key, books, classification, links, director, reimbursements, people loans, asset types, broker views, Viewing filter, reports, search, encryption at rest, second user, recovery, restart, display name, open-redirect check |
| test_demat.py | CAS reading per demat, commit, reconciliation statuses, portfolio statement quantities, old CAS broker migration |
| test_imap_client.py | mailreader.Imap against a scripted IMAP server (capabilities, UIDVALIDITY, SEARCH SINCE, header parsing, BODY.PEEK, labels) |
| test_mail_inbox.py | allowlist, rejected look-alikes, sealed alerts, forwarded mail to review, auto-import of CAS and statements, duplicates, allow sender, review, poll not counted as activity, auth_check units |
| test_1_6.py | help chapters (endpoints, links, PDF, design pages if DESIGN.md exists), refunds, reminder outbox, timing, no double send, sent-log privacy, launcher pieces |

To add a test: create tests/test_<topic>.py; call `SP = fresh('<topic>')` before importing app; drive A.app.test_client() after posting /setup and /login, or use A.app.test_request_context() with A.get_db(); fake external services by replacing mailreader.Imap, passing a factory to check_mail or notify.run_due, or setting app.config HUB_SMTP_FACTORY; assert, then run tests/run_all.py.

## 16. Extending the Hub

### 16.1 New bank or card reader

1. Work in the Statement Reader desktop app, never in the Hub's statement_reader/.
2. Follow statement_reader/parsers/README.md: sample PDF, tools/test_statement.py with --text, a BaseParser subclass filling StatementData, account_check(...) rows in data.accounts, EMIEntry for loans, registration in _PARSERS and SUPPORTED.
3. New engine version, then the desktop app's tools/export_engine.py into the Hub folder.
4. In the Hub: new version; add the bank to importer.BANK_CODES (longer names first) and BANK_SHORT, and to ledger.CARD_HINTS if card payments name it.

### 16.2 New broker contract-note reader

1. Run tools/test_contract_note.py on a sample with --text.
2. Copy contract_notes/upstox.py; set name, broker (equal to the inv_brokers name) and keywords; override only what differs (trade_date, contract_no, obligation, net, levies, trades).
3. Add it to READERS and repeat until Check: OK.
4. Add the name where brokers are recognised: investments.detect_broker and classify_pdf, depository.DP_HINTS, ledger.BROKER_HINTS, mailreader.DEFAULT_SENDERS, investments.DEFAULT_BROKERS.

### 16.3 New page

1. A module with register(app, get_db) adding routes via app.add_url_rule (unique endpoint names) and a con_() helper; call it from app.py.
2. Template extending base.html with page_title, tones and cards; override report_menu if needed.
3. Nav item in nav_groups (base.html); search entry (title, endpoint, icon, keywords) in planning.PAGES.
4. Manual chapter listing the endpoint in its endpoints comment.
5. If it belongs to an optional feature, add the endpoint (and any account kind) to that entry in features.FEATURES.
6. Respect the Viewing filter; add admin-only endpoints to auth._guard; redirect only through webutil.safe_next.

### 16.4 New table

Add CREATE TABLE IF NOT EXISTS to the module SCHEMA, later columns via PRAGMA table_info + ALTER TABLE ADD COLUMN, seeds via INSERT OR IGNORE, all in ensure_schema(con) called from app.prepare_db (and con_() if needed). Never drop or rename columns. If the table stores account names, extend accounts_hub.rename_account. No personal seeds.

### 16.5 New manual chapter

Create docs/user/NN-slug.md with "# Title", endpoints and icon comments, the Markdown subset and help:slug#section links; run tests/test_1_6.py and check /help/manual.pdf. For this manual, keep the numbering and check /help/internal/design and its PDF.

## 17. Known limitations and roadmap

### 17.1 Roadmap

- Alert mails into provisional entries: attachment-less mails are already kept (status alert, sealed text) for a reader that will create provisional transactions, later matched with statement rows.
- Exchange holidays for T+1: settles_by skips only weekends, so trades before a holiday look in transit a day too long.
- OAuth instead of Gmail app passwords, for narrower, separately revocable access.
- More bank, card and broker readers as samples arrive.

### 17.2 Limitations

- Single worker thread: IMAP checks, large PDFs and big reports block the UI; mail is read only while a page is open.
- One open database at a time; another user's log-in locks the first.
- Windows-only DPAPI outbox, tray, autostart and shortcuts; elsewhere reminders need a running, unlocked-once process.
- Whole-database re-encryption on each writing request; account names as keys; UI libraries from CDNs.

### 17.3 Review findings (1.6)

Writing this manual and the user manual surfaced the issues below; all were fixed before 1.6 was released:

| Finding | Fix |
|---|---|
| remove_user left .outbox, .sent.json and the in-memory outbox | vault.remove_user erases them and drops notify.MEMORY[stem] |
| idle lock only on the next request | auth.idle_watch runs every minute through notify.EXTRA_TICKS |
| no CSRF protection | SESSION_COOKIE_SAMESITE='Strict' and HttpOnly: the login cookie never goes with requests started by other sites |
| download_report built SQL with an f-string | parameters bound with ? |
| net-worth snapshot taken from filtered views | record_snapshot only when scope.active() is false |
| rules_reapply with include_manual reset feature-owned rows | rows owned by confirmed links, refunds, reimbursements and loan moves keep manual = 1 |
| refunds.undo did not reopen a received expectation; closed items invisible | undo reopens it; closed items show on "Confirmed & closed" and can be reopened |
| reminders preview / test followed the Viewing filter and lacked waiting refunds | notify.weekly_now runs inside an empty test_request_context and adds waiting refunds |
| recovery key in the session cookie | kept in auth._RK (process memory); the cookie holds only a random token |
| mail: unverified contract notes auto-imported; broker CSV/XLSX misread | auto-import needs check == 'OK'; tabular broker files go to review |
| upgrade.py: paths, outer .sha256, port, stale files, backups | paths validated, .sha256 checked, FINANCEHUB_PORT honoured, all old program files removed, backups trimmed to 10 incl. _files |
| close_db swallowed persist errors | logged with app.logger.exception |
| scope.txn_literal broke on '?' in values | placeholders filled left to right |
| rename_account missed recurring and pl_moves | both updated |
| open redirects via // in next / referrer | webutil.safe_next everywhere |
| recover() had no throttling | same back-off as login |
| account detail crashed outside the Viewing filter | built with ignore_scope=True |
| Fee button left the credit in Transfers | clears the marks and re-applies the rules |
| demat delete kept its import record | the import is removed when no holdings remain |
| bonus shares could not be added at price 0 | buys at price 0 are accepted |
| personal-looking examples in comments (a payee name, a shop name, reward points, a drive path) | replaced; the release privacy scan now also covers statement_reader/ |

Still open (low risk, by design for a local single-user app):

- State-changing GET routes (/logout, /scope) — protected by the SameSite cookie, not by tokens.
- No subresource integrity on CDN assets; the CDN must be trusted, or the assets vendored later.
- For non-Gmail mailboxes the topmost Authentication-Results header is trusted whatever its authserv-id.
- Automatic mail checks need an open Hub tab (the scheduler only prepares and sends reminder mails; it never writes the database).
