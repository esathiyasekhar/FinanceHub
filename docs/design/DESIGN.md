# Finance Hub — Design manual

Version 1.9 · 28 October 2026 · Statement Reader engine v14 · internal, for maintainers

This manual explains how Finance Hub is built and why. It is written for developers and for an AI assistant continuing the work, and describes the 1.9 code in this repository. When code and manual disagree, the code wins and the manual is corrected in the same change. The user manual (docs/user/) covers the same features from the user's side.

> **Note:** Names of modules, functions, tables and columns are written exactly as in the code. Examples use made-up values.

## 1. Purpose and scope

Finance Hub is a personal-finance web app for one person or one family. It reads bank, card and broker statements, puts every transaction into a four-level category tree, keeps accounts, loans, investments and dues, and produces reports. It runs as a local web server on the owner's Windows PC and is used through a browser on that PC.

### 1.1 Goals

- All data stays on the PC, encrypted at rest, readable only after log-in.
- Import exactly what was previewed (parse, show, confirm). Only the mail reader imports on its own, and only when every check passes.
- Prove the numbers: balance checks for statements, totals checks for contract notes, depository-versus-broker reconciliation.
- Organise money by Type › Head › sub-categories of any depth, by book (personal or the owner's company), person and account, counting each transfer once.
- Run in the background (tray, start with Windows) and mail due-date reminders.
- Install like a Windows program: program in Program Files, data in a separate folder; upgrade by running the newer setup; uninstall without touching the data (1.7).
- Encrypted backups the user can keep off the PC (OneDrive, Google Drive or any folder) and restore on the same or a new PC (1.7).
- Let an administrator help a user who lost both password and recovery key, with the trade-off disclosed to every user (key escrow, 1.7).
- No personal data in the program: names, numbers, companies and personal payee rules live only in the encrypted database.

### 1.2 Non-goals

- No cloud service of its own, no sync, no mobile app, no aggregation APIs. Backups are files written into a local folder; when that folder belongs to OneDrive or Google Drive, their desktop app uploads it. The Hub never calls a cloud API. It connects only to the user's own mailbox (IMAP/SMTP over TLS; problem reports also go out through that SMTP account) to Microsoft's sign-in service for Outlook mailboxes (8.5), to the public price files of NSE, BSE and AMFI (whole files, nothing about holdings is sent; 8.6) and, on Update now, to Yahoo Finance through the optional yfinance package. The browser loads UI libraries from CDNs (11.4).
- No multi-tenant server: several users may exist, but one database is open at a time.
- No payments, no writes to banks or brokers, no opening of links in mails, no tax filing (itr.py is a reference summary).

## 2. Architecture overview

### 2.1 Process model

```
FinanceHub.pyw  (pythonw.exe, no console)
 |-- hub_paths: PROGRAM_DIR, DATA_ROOT, LOG_DIR, BACKUP_DIR, PORT (section 3.2)
 |-- running_hub(): does http://127.0.0.1:<PORT>/healthz answer "FinanceHub"?
 |-- backup_on_upgrade(): copy <data>/data to <data>/backups when the version changed
 |-- import app                Flask app + Vault(DATA_ROOT), all modules registered
 |-- Server.start()            thread "hub-server"
 |      Waitress create_server(host=127.0.0.1, port=PORT, threads=1)
 |      or Werkzeug make_server(threaded=False) if waitress is missing
 |-- notify.start_scheduler()  thread "hub-reminders": tick() every 60 s
 |-- webbrowser.open(URL)      skipped with --background (autostart)
 '-- pystray.Icon.run()        main thread until Quit
        Open | Lock now | Start with Windows | Open logs folder | Quit
```

The launcher logs to <data folder>/logs/hub.log (hub_paths.LOG_DIR; rotating, 1 MB × 5; stdout and stderr redirected under pythonw). running_hub() returns 'hub' (open the browser and exit, so a second start only opens the page), 'other' (port taken: message box; FINANCEHUB_PORT or the port in financehub.json changes it) or '' (start). It passes hooks through app.config: HUB_LAUNCHER, HUB_SHUTDOWN, HUB_AUTOSTART_GET and HUB_AUTOSTART_SET (HKCU Run value FinanceHub with --background) and HUB_SERVER. Quit, from the tray or the Hub's power button, calls V.lock_now(), stops server and tray and ends with os._exit(0). Without a tray the main thread waits for the Hub's Quit button. `python app.py` runs Werkzeug (threaded=False) on hub_paths.PORT plus the scheduler; app_quit then only explains how to stop it.

Why one worker thread: the database is a single in-memory SQLite connection (section 4). Serving one request at a time means no request ever shares it with another, so there is no per-request locking and no pool. The cost: a slow request (IMAP check, big PDF) blocks the UI.

### 2.2 Threads

| Thread | Work | Database access |
|---|---|---|
| hub-server | all HTTP requests, one at a time | shared connection via Conn |
| main (tray) | menu actions | lock_now() only, under Vault.lock |
| hub-reminders | notify.tick(): EXTRA_TICKS (auth.idle_watch, backup.run_due), then maybe_rebuild(), run_due() | private copy from notify.snapshot_con(); idle_watch calls lock_now() and backup.make_backup calls V.persist(), both under V.lock on the shared connection |
| timers | delayed browser open and quit | none |

### 2.3 Request flow

1. Waitress hands the request to Flask.
2. auth._guard, the only before_request hook, passes open endpoints and checks setup, idle lock, session and role for the rest (section 5).
3. The view calls get_db() (app.py): a Conn proxy with row_factory sqlite3.Row, cached in g._database. Modules receive get_db in register(); some helpers call dbconn.connect(), which returns the same kind of proxy.
4. Templates extend base.html. Context processors add versions and FY label (inject_fy), user and display name (auth), Viewing-filter lists (scope), mail badge (mailreader), payers (ledger), help topic (help_hub) and launcher state (_runtime_ctx).
5. teardown_appcontext close_db rolls back if the request raised, calls V.persist() and, if something was written, notify.mark_dirty().
6. An unhandled exception reaches support's errorhandler(500): Flask has already logged the traceback; the handler logs "Error reference <ref>" and renders auth_error.html with the reference and a Report this problem link (12.2).

### 2.4 Module map

| Module | Responsibility | Main tables | Routes |
|---|---|---|---|
| FinanceHub.pyw | launcher: single instance, upgrade backup, server, scheduler, tray, autostart; paths and port from hub_paths | — | calls /healthz |
| hub_paths.py | program folder vs data folder: PROGRAM_DIR, CONFIG_FILE (financehub.json), DATA_ROOT, UPLOAD_DIR, LOG_DIR, BACKUP_DIR, PORT, INSTALLED (3.2) | financehub.json | — |
| app.py | Flask app, Vault(DATA_ROOT), get_db, close_db, prepare_db; Insights, statement import, passwords, EMI actions, Reports page, launcher routes; registers backup, support and welcome | transactions, accounts, passwords, loans | /insights, /import…, /passwords…, /loans/…, /reports…, /api/summary, /api/category_data, /healthz, /app/quit, /app/stopped, /app/autostart |
| vault.py | users, key wrapping, encrypted file, in-memory SQLite, sealing, secure delete; key escrow, admin reset, rename_user, check_password (4.9) | users.json, data/<hex>.enc | — |
| auth.py | guard (incl. must_change), setup, log-in, recovery, users (password, user-ID change, admin reset), forced password change, profile | hub_settings | /setup, /setup/recovery-key, /login, /logout, /recover, /users…, /account/password, /profile/save |
| welcome.py | first-start setup wizard: about you, mail, features, accounts, backup; needed() (11.5) | hub_settings, entities, mail_settings, notify_settings; users.json backup | /welcome, /welcome/<name> |
| backup.py | .fhb backup and restore, cloud-folder detection, automatic backups through notify.EXTRA_TICKS, first-start restore (4.10, 4.11) | users.json backup | /backup, /backup/save, /backup/now, /backup/download, /backup/restore, /setup/restore |
| support.py | Report a problem: diagnostics, scrubbed log lines, preview, send by SMTP / mailto / file; errorhandler(500) with error reference (12.2) | reads mail_settings, notify_settings, counts | /support, /support/send |
| installer/ | Windows setup: setup.pyw (tkinter wizard and command line), Setup.cmd, optional Inno Setup wrapper (14.5) | — | — |
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
| prices.py | automatic prices (1.9): NSE / BSE bhavcopy and AMFI NAV download in a thread, apply by ISIN / symbol, before_request hook after the log-in guard, scheduler tick (8.6) | inv_securities.cmp / cmp_date / cmp_source; inv_settings prices_auto, prices_applied, prices_result | — (POST /investments/prices) |
| investments.py | broker files, trades, holdings, portfolio, tranching, instructions, HOOKS | inv_brokers, inv_securities, inv_imports, inv_trades, inv_holdings, inv_instructions, inv_settings | /investments and /investments/… |
| contract_notes/ | contract-note readers and totals check | — | — |
| depository.py | demat accounts, CAS reading, reconciliation | inv_demats | /investments/demat…, /report/demat/<fmt> |
| mailreader.py | the Hub's mailboxes: IMAP (password or XOAUTH2), sender checks, auto-import, review; several mailboxes (1.8) | mail_settings, mailboxes, mail_items | /mail, /mail/… (settings, test, check, poll, forget, <iid>, review, text), /mail/box/save, /mail/box/<mid> (remove, send_from, toggle, signout), /mail/box/<mid>/test, /mail/box/<mid>/ms/start, …/ms/poll |
| oauth_ms.py | Sign in with Microsoft (1.8): OAuth 2.0 device-code flow, refresh-token rotation, XOAUTH2 string (8.5) | — (refresh token stored in mailboxes.oauth_refresh) | — |
| notify.py | reminder and weekly mails, outbox, scheduler | notify_settings | /reminders, /reminders/save, /reminders/test |
| refunds.py | failed payments, refunds, awaiting refund | txn_refunds | /refunds, /refunds/<rid>, /refunds/expect, /refunds/<rid>/candidates |
| reports_hub.py | section model to xlsx and pdf | (reads all) | /report/view/<fmt> and trades, transfers, director, reimbursements, people-loans |
| itr.py | FY options, ITR summary, FIFO capital gains | (reads) | used by /reports |
| compounding.py | Wealth planner storage and Hub figures | cc_users, cc_actuals | /planner, /api/cc/… |
| help_hub.py | user and design manuals, Markdown subset, PDF | docs/ files | /help, /help/<topic>, /help/find, /help/manual.pdf, /help/internal/design(.pdf) |
| hub_version.py | APP_NAME, VERSION, RELEASE_DATE, SUPPORT_EMAIL | — | — |
| features.py | per-user feature switches (hub_settings.features_off / features_done), Home redirect to the setup wizard, nav / search / route hiding, "add a missing account" | hub_settings | /features, /features/save |
| webutil.py | safe_next(): only local redirect targets | — | — |
| parsers/ | CSV, XLSX, XLS bank exports (auto_parse), legacy categorize() | — | — |

reports/generator.py (legacy monthly workbook) serves /reports/download.

## 3. Repository layout and runtime folders

### 3.1 Repository

```
FinanceHub.pyw  app.py auth.py vault.py dbconn.py hub_version.py hub_paths.py
importer.py classifier.py organise.py scope.py accounts_hub.py planning.py
ledger.py refunds.py investments.py assets.py depository.py compounding.py
mailreader.py notify.py reports_hub.py itr.py help_hub.py features.py
welcome.py backup.py support.py webutil.py
statement_reader/   engine copy (parsers/, utils/, tools/, version.py)
contract_notes/     parsers/     reports/
templates/          base.html + one template per page
static/             hub.ico, hub.png, planner/ (calculator.js, planner.js)
installer/          setup.pyw Setup.cmd FinanceHub_Setup.iss build_exe.bat
                    README.txt hub.ico
docs/user/          manual chapters NN-slug.md     docs/design/  DESIGN.md
tests/              synthetic-data tests, _tkstub/ (not shipped)
tools/              make_release.py upgrade.py shortcuts.py test_contract_note.py
install.bat run.bat requirements.txt CHANGELOG.md .gitignore
```

installer/ is part of the release zip (it is not in SKIP_DIRS), so an installed program folder also holds it; setup copies its own setup.pyw and Setup.cmd there as well, for repair and uninstall.

### 3.2 Program folder and data folder (hub_paths.py)

Since 1.7 the program and the data live in separate folders. hub_paths is imported first by app.py, FinanceHub.pyw and tools/upgrade.py and resolves:

| Name | Resolution |
|---|---|
| PROGRAM_DIR | the folder of hub_paths.py |
| CONFIG_FILE | PROGRAM_DIR/financehub.json, written by setup: {"data_dir": "<folder>", "port": 5000} |
| DATA_ROOT | env FINANCEHUB_DATA, else config data_dir, else PROGRAM_DIR (portable copy, tests); created at import (errors ignored) |
| UPLOAD_DIR, LOG_DIR, BACKUP_DIR | DATA_ROOT/uploads, /logs, /backups |
| PORT | env FINANCEHUB_PORT, else config port, else 5000 |
| INSTALLED | CONFIG_FILE exists (reported in problem reports) |

Users: app.py (Vault(DATA_ROOT); DB_PATH and STMT_DIR under DATA_ROOT; UPLOAD_DIR; BACKUP_DIR for the Running card; PORT for `python app.py`), FinanceHub.pyw (PORT, LOG_DIR, BACKUP_DIR, DATA_ROOT/data for the upgrade backup), tools/upgrade.py (DATA, port; falls back to the program folder when hub_paths cannot be imported), backup.py (BACKUP_DIR for safety copies) and support.py (LOG_DIR, INSTALLED). BASE_DIR in app.py is PROGRAM_DIR: templates, static files and docs/ are read from the program folder. app._statement_folders() reads DATA_ROOT/statements, PROGRAM_DIR/statements and the statements folder next to the program folder.

Program folder (installed, e.g. C:\Program Files\Finance Hub; the whole repository folder for a portable copy):

| Path | Contents | git |
|---|---|---|
| program files | written by setup or upgrade.py from the release zip | tracked |
| MANIFEST.sha256 | the release's manifest, used to find stale files at the next upgrade | only in releases and installs |
| financehub.json | data_dir and port (installed copies only) | ignored, excluded from releases |
| .venv/ | the Hub's Python environment (setup or install.bat) | ignored |
| requirements.lock | pip freeze of .venv | ignored |
| installer/ | setup.pyw, Setup.cmd (for Settings › Apps uninstall), README, .iss | tracked |
| dist/ | release zip, Setup zip and .sha256 files (development only) | ignored |

Data folder (DATA_ROOT; e.g. D:\Finance Hub, or the program folder for a portable copy):

| Runtime path | Contents | git |
|---|---|---|
| data/ | <hex>.enc, .enc.prev, .enc.tmp (while saving), <hex>_files/ (sealed mail files), <hex>.outbox, <hex>.sent.json, .version (launcher marker) | ignored |
| users.json | user records, escrow, backup settings (4.2) | ignored |
| uploads/ | files being previewed, .pending/ (sealed statement previews), .inv_pending/ (broker files, sealed previews), mail temp files | ignored |
| backups/ | <date>_before_<version>/ encrypted copies; Finance Hub backups/ (safety .fhb files written before a restore) | ignored |
| logs/ | hub.log and rotations | ignored |
| statements/ | optional statement folder read by Reset and reload | ignored |

The user's own backups (.fhb) go to a folder they choose, normally outside both (4.10).

.gitignore also excludes .enc and .enc.prev files, finance.db and other .db or .sqlite files, __pycache__, .pyc files, requirements.lock and financehub.json.

## 4. Storage and encryption (vault.py)

### 4.1 Files and keys

| File | Format | Key |
|---|---|---|
| data/<hex>.enc (+ .prev) | b'FHUBENC1' + 12-byte nonce + AES-256-GCM(zlib level 6 of SQLite serialize()), AAD = magic | user's DEK |
| uploads/.pending/<token>.json, uploads/.inv_pending/<token>.json | b'FHSEAL1' + nonce + AES-GCM(JSON), AAD 'seal' | DEK |
| data/<hex>_files/mail_<id>.bin or .txt | b'FHBLOB1' + nonce + AES-GCM(zlib bytes), AAD 'blob' | DEK |
| data/<hex>.outbox | b'FHOUTBOX1' + DPAPI blob | Windows account |
| data/<hex>.sent.json | plain JSON, hashed keys only | none |
| users.json escrow_dek | b64 RSA-OAEP(SHA-256, MGF1-SHA-256, label b'FinanceHub') of the DEK | escrow private key |
| users.json escrow_key | b64(nonce + AES-GCM(admin's DEK, PKCS8 PEM of the escrow private key)), AAD b'escrow' | that admin's DEK |
| <chosen folder>/Finance Hub backups/*.fhb | zip of manifest.json, user.json (plain), db.enc and files/ copied as on disk (4.10) | DEK, reached via the wrapped keys in user.json |

<hex> is secrets.token_hex(8), so file names say nothing about users.

```
password  --PBKDF2-HMAC-SHA256(16-byte salt, 600000 rounds)-->  KEK
recovery key (normalised)  --PBKDF2-HMAC-SHA256(own salt)-->     RKEK
DEK = 32 random bytes per user
users.json key      = b64(nonce + AES-GCM(KEK,  DEK, aad = user ID))
users.json recovery = b64(nonce + AES-GCM(RKEK, DEK, aad = b"recovery"))
escrow pair         = RSA-3072, one per installation; public PEM in users.json
users.json escrow_dek = b64(RSA-OAEP-SHA256(public, DEK, label = b"FinanceHub"))
users.json escrow_key = b64(nonce + AES-GCM(admin DEK, private PEM, aad = b"escrow"))
```

Password change and recovery only rewrap the DEK (_rewrap); the database is not re-encrypted. Iterations are stored per entry and _rewrap writes the current ITERATIONS, so the cost can be raised later. For unknown user IDs a PBKDF2 still runs (equal timing). The user ID is the AAD of the password-wrapped key, so rename_user rewraps the DEK under the new ID (5.2); the recovery wrap (AAD b"recovery"), escrow_dek and escrow_key do not depend on the ID. The DEK itself never changes: password change, recovery, admin reset and rename only rewrap it, so every past backup of a user stays decryptable with that user's DEK.

### 4.2 users.json

```
{"version": 2, "settings": {"idle_minutes": 30},
 "escrow": {"public": "<PEM>", "created": "<iso>"},
 "users": {"<user ID>": {"salt": "<b64>", "iterations": 600000, "role": "admin",
   "db": "<16 hex>.enc", "key": "<b64>",
   "recovery": {"salt": "<b64>", "iterations": 600000, "key": "<b64>",
                "created": "<iso>"},
   "created": "<iso>", "last_login": "<iso>",
   "escrow_dek": "<b64>", "escrow_key": "<b64>   (administrators only)",
   "must_change": true,                       (after an admin reset)
   "backup": {"dir": "<folder>", "every": "off|daily|weekly", "keep": 10,
              "last": "<iso>", "last_mtime": 0.0, "last_error": ""}}}}
```

No passwords, names or financial data. Visible: user IDs, roles, creation and log-in times, the escrow public key, and each user's backup folder, schedule, last backup time and last error (a OneDrive path usually contains the Windows user name). idle_minutes is global. Saved atomically (.json.tmp, os.replace). Writers re-read the file and write it back under V.lock (the mutating Vault methods are @_locked; log-in, the Users-page grant and backup.save_settings take the lock too), so request and scheduler writes cannot overwrite each other.

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

plaintext_copies(base) skips .venv, .git, backups, logs and other program folders and lists every unsealed file under uploads/ (sealed previews starting FHSEAL1 / FHBLOB1 are skipped) plus finance.db-style files (.db, .sqlite, .sqlite3, -wal, -shm) with an SQLite header. secure_delete overwrites with random bytes, fsyncs and unlinks — best effort on SSDs. Setup offers erasure; the Users page lists remaining copies and plain_cleanup (admin) erases them; prepare_db erases uploads older than 24 hours at each log-in. Since 1.7 base is V.base = DATA_ROOT, so an installed Hub scans its data folder, not the program folder (the card is still titled "Unencrypted copies in the app folder"). An old portable folder whose data was brought over by setup is not scanned.

### 4.9 Key escrow: administrator reset (1.7)

Purpose: an administrator can give a user a new password without knowing the old one or the recovery key. Cost: every administrator can obtain every user's DEK (13).

- _escrow_init(doc, admin, dek): generates RSA-3072 (e = 65537); doc['escrow'] = {public PEM, created}; the admin gets escrow_key (the PKCS8 PEM wrapped with their DEK, AAD b'escrow') and escrow_dek; any old escrow_dek entries are dropped. Called by V.setup on a fresh install, and by _escrow_on_login at the first administrator log-in when users.json has no escrow (upgrade from 1.6, or after restore_fresh, which removes it).
- _escrow_on_login(doc, user, dek), run in V.login with every exception swallowed (a log-in is never blocked): creates the escrow as above for an admin; otherwise adds escrow_dek when missing and removes escrow_key from non-admins.
- add_user: with an escrow, the new user gets escrow_dek at once; a new admin also gets escrow_key through grant_reset_key (only if the acting admin holds escrow_key).
- set_role: promotion calls grant_reset_key (needs the target's escrow_dek and the acting admin's escrow_key; failures ignored); demotion removes escrow_key. users_page: an admin who holds escrow_key grants it to every admin that has escrow_dek but no escrow_key, then saves.
- _escrow_private(doc): only for the logged-in, unlocked admin with escrow_key; unwraps the PEM with V.dek. _escrow_dek_of(doc, user) RSA-decrypts that user's escrow_dek; without one: "<user> has not logged in since password reset was turned on".
- admin_reset_password(user, new): refuses self; rewraps the DEK with the new password (_rewrap), sets must_change, clears the failed-attempts counter. can_reset(user) = escrow exists, the current user has escrow_key, the target has escrow_dek; the Users page shows Reset… or "reset after their next log-in" from it.
- must_change is cleared by set_password and by recover().

Users of a 1.6 install become resettable one by one, at their next log-in after the upgrade; users added under 1.7 at once.

### 4.10 Backup files and settings (backup.py)

A backup is one zip per user:

```
FinanceHub_<user ID>_<YYYY-mm-dd_HHMMSS>.fhb   (ZIP_DEFLATED; [^A-Za-z0-9._-] -> _)
  manifest.json  {"app": "Finance Hub", "format": 1, "version", "created", "user",
                  "sha256": {"db.enc": <hex>}, "files": {<name>: <hex>}}
  user.json      the users.json entry, only: salt, iterations, role, db, key,
                 recovery, created
  db.enc         data/<hex>.enc exactly as on disk (FHUBENC1, DEK)
  files/<name>   data/<hex>_files/* as on disk (sealed blobs, DEK)
```

Not included: escrow_dek, escrow_key, must_change, last_login, backup settings, .enc.prev, the outbox and sent log, other users. Downloads are named FinanceHub_<user ID>_<YYYY-mm-dd_HHMM>.fhb (the ID is not sanitised there).

- make_backup(vault, user, dest_dir=None, keep=None): under V.lock, persist() first when that user is the one unlocked; read the entry, db and files; build the zip in memory. dest_dir None returns bytes (download). Otherwise target_dir(dest_dir) appends "Finance Hub backups" (unless the folder already has that name) and creates it; the file is written as .tmp and renamed; keep deletes the oldest FinanceHub_<user>_*.fhb beyond keep (names sort by time).
- cloud_folders(): the OneDriveConsumer, OneDriveCommercial and OneDrive environment variables, ~/OneDrive, <letter>:\My Drive for every drive letter on Windows (Google Drive for desktop), ~/Google Drive, ~/My Drive, ~/Dropbox, and FINANCEHUB_CLOUD_DIRS (os.pathsep-separated, used by the tests). Only existing folders, de-duplicated case-insensitively.
- Settings live in users.json users.<id>.backup, not in the database, because automatic backups run while locked: dir, every ('off', 'daily', 'weekly'; EVERY), keep (1–100, default 10), last (ISO time), last_mtime (database file mtime at that backup), last_error (up to 200 characters). settings_of() fills defaults; save_settings() merges under V.lock. backup_save validates the folder with target_dir first. The wizard's backup step saves dir, every (default weekly) and keep 10.
- run_due(vault, now) is appended to notify.EXTRA_TICKS in register(), so it runs every 60 s on hub-reminders, locked or not, for every user: skip unless every is daily/weekly and dir is set; skip until 20 h (daily) or 6 d 12 h (weekly) after last; skip when the database mtime is not newer than last_mtime; else make_backup(keep) and record last and last_mtime, or record last_error ("<dd Mon HH:MM>: <error>").
- backup_now does the same for the logged-in user (button disabled without dir); backup_download returns the bytes and changes no settings.

### 4.11 Restore and the backup threat model

- read_backup(src): requires manifest.json, user.json and db.enc; checks the sha256 of db.enc and of every file listed in the manifest; refuses file names containing a slash or backslash, or starting with a dot. Error texts: "this is not a Finance Hub backup file", "the backup file is damaged (…)".
- _backup_dek(vault, m, entry, db, password): (1) while unlocked, the current DEK if it decrypts db.enc; (2) PBKDF2(password, entry salt, entry iterations) unwrapping entry key with AAD = manifest user; (3) the normalised recovery key unwrapping entry recovery with AAD b'recovery'; else "that password (or recovery key) does not open this backup". Because the DEK never changes, (1) opens every backup of the logged-in user, whatever their password was then; (2) and (3) matter only when the DEK differs (another or re-created user, or a fresh install).
- restore_mine(vault, src, password) (POST /backup/restore with a path inside the user's backup folder, or an uploaded file): decrypts db.enc as proof; refuses a backup of another database unless the user ID is the same; writes a safety backup of the current data with make_backup(…, hub_paths.BACKUP_DIR / 'before-restore', keep=10); then under V.lock re-encrypts the plaintext with the current DEK (.enc.tmp, os.replace), replaces the _files folder (re-sealing each blob under the current DEK when the keys differ: magic 7 bytes, nonce 12, AES-GCM with AAD b'blob'), closes the connection and _open()s it again. users.json is untouched, so the present password and recovery key stay valid. The view stores the new V.nonce in the session, so the user stays logged in.
- restore_fresh(vault, src, password) (/setup/restore, an open endpoint, GET and POST, only while is_setup() is false; linked from auth_setup.html): finds the DEK with the password or recovery key of the backup, decrypts as proof, writes db.enc under entry['db'] and the files, then users.json = {manifest user: entry + role admin + last_login ''} without escrow. The user logs in with the password of the backup; the escrow is re-created at that log-in.

Threat model of backups:

- Confidentiality: db.enc and blobs are AES-256-GCM under the DEK; user.json holds the DEK wrapped by the password and recovery key of that time, so an attacker with the file can guess passwords offline at the PBKDF2 cost (600 000 rounds), as with users.json. manifest.json and the file name reveal the user ID, version, times and sizes.
- Old secrets: an old backup opens with the password or recovery key valid when it was made. Since the DEK is never rotated, anyone who once learnt it (or an administrator through the escrow) can decrypt every past and future backup of that user.
- Integrity: the sha256 values detect damage, not tampering (the manifest is not authenticated); tampering with db.enc or blobs is caught by the AES-GCM tags. user.json is not authenticated: a crafted backup can bring its own wrapped key, which only lets someone restore data they encrypted themselves.
- restore_fresh is reachable by anyone on this PC before the first user exists, the same exposure as /setup. It accepts only a db name of 16 hex digits + .enc and a valid user ID.
- Cloud: the Hub only writes into a local folder; the sync client, the cloud account and its 2-step verification are outside the Hub.
- Automatic backups need no key while locked (they copy ciphertext); they never touch the shared connection (persist=False): every request has already saved its changes.

## 5. Authentication and request lifecycle (auth.py)

### 5.1 The guard

OPEN_ENDPOINTS: login, setup, recover, static, logout, healthz, app_stopped, setup_restore. For all other endpoints _guard does:

1. No user yet: redirect to /setup.
2. Idle time exceeded: lock_now(), clear session, flash.
3. Locked, or session['vault'] differs from V.nonce, or no session['user']: 401 JSON for /api/ paths and JSON requests, else redirect to /login with next (GET only).
4. V.last = now, except for mail_poll.
5. g.user, g.role.
6. must_change set for this user (an administrator reset the password): redirect to change_password, except for change_password, logout, static and healthz.
7. Admin only: user_remove, security_settings, plain_cleanup, user_save with action add, role, reset or rename_other. (app_autostart checks the role in the view.)
8. No recovery key yet, on a GET: create one, put it in session['show_recovery'], redirect to recovery_show.

The nonce binds a browser session to one unlock; another log-in changes it and older sessions return to the log-in page.

### 5.2 Roles and flows

- admin: add users, change roles, remove users (their .enc, .enc.prev and _files are secure-deleted), reset another user's password or user ID, idle setting, plaintext clean-up, Start with Windows from the Users page, design manual. member: their own database, own password and own user ID. One admin must remain; nobody removes themselves. Through the escrow (4.9) every admin holding escrow_key can reach every other user's DEK; the Users page tells all users so ("Administrators can reset another user's password (and so could open that user's data)") whenever an escrow exists.
- Setup: _check_new requires a user ID of 3+ characters (letters, digits, . _ -) and a password of 10+ characters using three of lower, upper, digits, symbols/space. V.setup creates the admin and database, prepare_db() builds the schema, the recovery key is shown once.
- Log-in: V.login unwraps the DEK, prepare_db() upgrades the schema, the session gets user and nonce; next only if it starts with a single slash. From the third failure per user ID the wait is 5 s, doubling to 300 s (in memory).
- Users added by an admin get their recovery key at their first GET. recovery_new replaces it.
- /recover: user ID + recovery key (case, spaces, dashes ignored) + new password rewraps the DEK and clears must_change; the key stays valid.
- user_save actions (POST /users/save):
  - add, role: as before; add and role also hand out escrow material (4.9).
  - password: own account only; the current password is checked with V.check_password (no second log-in, so the session nonce is unchanged); V.set_password rewraps and clears must_change.
  - rename: own user ID; V.rename_user(session user, new_username, current password). The new ID must match `[A-Za-z0-9._-]{3,40}` and be unused; the DEK comes from the password; the entry moves to the new key and is rewrapped with the new ID as AAD; V.user and session['user'] become the new ID. Recovery wrap, escrow_dek, escrow_key and backup settings move with the entry.
  - reset (admin): _check_new on the temporary password, then V.admin_reset_password.
  - rename_other (admin): _check_new(new ID, temporary password); V.rename_user(old, new, temporary password) takes the DEK from the escrow, rewraps it with the temporary password under the new ID and sets must_change. The Users page form submits reset, switched to rename_other by script when a new ID is typed.
- /account/password (change_password, GET and POST, logged in): auth_change.html "Choose your password"; checks the temporary password with check_password and the new one with _check_new, then set_password and redirect to Home.
- Recovery key: 28 characters from a 32-letter alphabet without I, O, 0, 1, in seven groups of four (about 140 bits).

### 5.3 Display name and user ID

The user ID is typed at log-in, keys users.json and is the AAD of the wrapped DEK. Since 1.7 it can be changed (rename_user, 5.2); the database and its random file name stay the same. Backups carry the ID they were made under (4.10). The person's name is hub_settings.display_name inside the encrypted database (max 60 characters; set at setup or user creation, changed with /profile/save). auth._inject_user gives it to templates; the Hub greets with display_name, or the user ID when empty. Reason: users.json is readable by anyone with the folder, so it must hold no names (1.3).

### 5.4 mail_poll, healthz, app_quit, app_stopped

- mail_poll is a background POST every 60 s. If it refreshed V.last an open tab would keep the Hub unlocked for ever, so _guard skips the activity update for it while the idle check still applies (tested in test_mail_inbox.py).
- /healthz (open) returns "FinanceHub <version>" only; used by the launcher, tools/upgrade.py and installer/setup.pyw (to refuse while the Hub runs).
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
| accounts_hub | account_balances, networth_snapshots, hub_settings | manual balances (account_id, as_of); one snapshot per day; key/value: display_name, features_off, features_done (features), onboarding = 'done' (welcome) |
| classifier, scope | categories, rules, entities, people | categories (parent_id, name, level 1 = Type, 2 = Head, 3… any depth since 1.9, kind); rules (pattern, match_type contains/payee, category_id, display_name, entity, person); entities (name, role book/payer/other, aliases); people (name, aliases; 'Self' = owner's name variants) |
| planning | recurring, budgets, alert_state, month_close | recurring (name, match_key, amount, freq, next_date, account, rtype, status); monthly budget per category_id; snoozes; checklist per month and item |
| ledger | txn_links, reimb_claims, reimb_receipts, contacts, pl_loans, pl_moves | links (out_id, in_id, counter_kind, counter_ref, kind, status suggested/confirmed/rejected, score, reason); claims and receipts per payer; loans with people (book, person, direction given/taken, due_date, status) and their moves (kind principal/repayment/interest/waived, mode, our_account, txn_id) |
| refunds | txn_refunds | kind failed/refund/expected, debit_id, credit_id, status suggested/confirmed/rejected/waiting/received/closed, expected, follow_up_days, prev_debit_cat, prev_credit_cat |
| investments, assets | inv_brokers, inv_securities, inv_imports, inv_trades, inv_holdings, inv_instructions, inv_settings, inv_asset_types | securities (symbol+exchange unique, isin, bucket core/satellite, plan_status, cmp, asset_type); imports (file_hash unique); trades (broker_id, security_id, trade_date, side, qty, price, charges, trade_id); holdings (broker_id or demat_id, as_of, qty, close_price); instructions BUY/ADD/TRIM/SELL |
| depository | inv_demats | depository CDSL/NSDL, dp_name, dp_id, client_id, account_no (unique), broker_id; adds demat_id to inv_holdings and inv_imports |
| mailreader, notify | mail_settings, mailboxes, mail_items, notify_settings | mail_settings: key/value rules shared by every mailbox (senders, forwarders, interval, since_days, enabled, auto_import, last_check/result, migrated); mailboxes (1.8): one row per mailbox (name, provider gmail/outlook/other, user, password, host, port, folder, label, ms_client_id, ms_tenant, oauth_refresh, active, send_from, uidvalidity, last_uid, last_check, last_result); mail_items (message_id, mailbox_id, from_domain, auth, status, kind, file_hash, blob, note, result); notify_settings: reminder options |
| compounding | cc_users, cc_actuals | planner users (params, goal JSON) and year-end records |

## 7. Classification

### 7.1 Tree and kinds

classifier.TREE seeds four Types: Income (kind income), Expenses (expense), Transfers (transfer), Investments (investment). Levels: 1 Type › 2 Head › 3 Sub-head › 4 Item. Each node stores its kind; cat_move moves a subtree and gives it the new parent's kind; the four built-in Types (a root whose name is in classifier.KINDS) cannot be renamed, moved or deleted. Since 1.9 there is no depth limit (_new_child, cat_move), names are unique per parent (case-insensitive on add), and users may add their own top-level groups with a chosen kind (_new_root, parent_id 'top'); such groups can be renamed, moved under another category and deleted. Code that reads levels treats 2 as Head and 3 as Sub-head; amounts in deeper categories roll up into their ancestors (_aggregate walks parent_id; budgets and planning climb to the Head); breakdown totals add up every root of a kind; the Excel breakdown fonts default for deep levels. Names: runs of spaces collapse, '›' becomes '-' (it separates levels in paths), at most 80 characters, unique per parent ignoring case (add, rename and move). Exports keep Type, Head, Sub-head and join deeper levels into Item (organise._levels). The ITR summary keys heads under a user's own top-level group as '<group> › <head>' so they never mix with built-in heads. _refresh_heads sets transactions.category to the Head, or to the Type for rows sitting on a Type. POST /categories/add also accepts JSON ({parent_id, name, next: 'json'} → {ok, id, path, level, kind}) for the picker. path_id() finds or creates a path. transactions.category holds the Head name (head_name, refreshed by _refresh_heads). Modules create nodes on demand (ledger EXTRA_NODES and PL_PATHS, refunds FAILED_PATH, Transfers › Reimbursable › <payer>).

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

check_mail() loops over the active mailboxes (boxes(con, active_only=True); with more than one, a mailbox that is not configured is skipped with "not set up yet") and calls _check_box() for each with settings(con, id) = the shared rules + that mailbox's row. Message-IDs are deduplicated across all mailboxes, so a mail in two mailboxes is read once; new mail_items rows get that mailbox's id. Per-mailbox state (uidvalidity, last_uid, last_check, last_result) is written with _set_box; the overall last_check / last_result go to mail_settings.

**Migration (1.8).** boxes() turns the single mailbox of 1.5–1.7 (user, password, host … in mail_settings) into mailboxes row 1 with send_from=1, keeping last_uid / uidvalidity, sets mail_settings.migrated=1 and deletes the moved keys (_MOVED) so no second copy of the password remains; ensure_schema no longer seeds those keys. The same migration gives items read before 1.8 (mailbox_id NULL) the migrated mailbox's id.

1. IMAP4_SSL (port 993) with a default SSL context; LOGIN with the address and app password (Gmail / other), or for Outlook AUTHENTICATE XOAUTH2 with a Microsoft access token (connect(); 8.5).
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

auth_check() trusts the receiving server's verdict and reads only the topmost Authentication-Results header, the one that server added last; lower headers may be forged by the sender. For a Gmail mailbox (trusted_servers_for) its authserv-id must be mx.google.com; other hosts are not restricted. Microsoft (Outlook.com / Exchange Online) writes no authserv-id — its topmost header starts with spf=… and holds dmarc=pass action=none header.from=…, which the same rules read. pass = dmarc=pass with a matching header.from organisational domain, or dkim=pass whose header.d/header.i has the From address's organisational domain (aligned DKIM; org_domain knows co.in, bank.in, co.uk…). Otherwise fail or none, both rejected.

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
- explain(e, s) turns server errors into advice: Gmail "Application-specific password required" → make an app password; Outlook sign-in missing or expired; AUTHENTICATIONFAILED; IMAP not enabled; LOGINDISABLED / basic auth blocked → use Sign in with Microsoft; anything else is shown as the server said it.

#### Mailbox page

/mail lists the mailboxes (kind, ready, signed_in, has_password — never the secret), an add/edit form (?box=<id>|new&kind=gmail|outlook|other; the provider radios reload with the right fields), and the shared Reading rules form. _save_box_form() validates the provider, fills server defaults for a new mailbox or a new provider, keeps the saved password when the field is empty, and clears oauth_refresh when the client ID or address changes. Actions: remove (send_from moves to the first remaining mailbox), send_from (exactly one), toggle (active), signout (clears oauth_refresh). save_box_form() (module level, also used by the wizard) keeps a typed port, clears oauth_refresh when a mailbox stops being Outlook, and resets uidvalidity / last_uid when the address, folder or server changes. configured() needs a password and a server for Gmail / other, a client ID and a sign-in for Outlook. Each handled mail is labelled with the mailbox's own label; an empty label (the Outlook / other default) leaves mails untouched. The older POST /mail/settings with a user field still saves the first mailbox (kept for old forms).

### 8.5 Sign in with Microsoft (oauth_ms.py)

Outlook.com stopped accepting passwords and app passwords for IMAP/SMTP (basic authentication) in 2024, so Outlook mailboxes use OAuth 2.0.

- **Registration.** The user registers a public client in Microsoft Entra: supported account types "any organizational directory and personal Microsoft accounts", "Allow public client flows" = Yes, no redirect URI, no secret. The Hub stores only the Application (client) ID (mailboxes.ms_client_id). No client ID ships with the Hub, so nothing about the user's sign-ins passes through a third party's app.
- **Device code.** ms_start posts to https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode with scope "offline_access openid email https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send" and returns user_code / verification_uri to the page; the pending response is kept in oauth_ms.DEVICE[(user ID, mailbox id)], in memory only. The page polls ms_poll every interval seconds; poll() posts grant_type device_code to /token: authorization_pending / slow_down → pending; success → the refresh token goes into mailboxes.oauth_refresh (inside the encrypted database), and last_uid resets only for a first sign-in. signed_in_as() reads the email / preferred_username claim of the returned id_token (no signature check — it only compares); if it differs from the mailbox address the page warns that reading may fail.
- **Tenant.** tenant 'common'; when Microsoft answers AADSTS9002331 (app for personal accounts only) _call retries on 'consumers' and the mailbox remembers it.
- **Tokens.** access_token(client, tenant, refresh) returns a cached access token or redeems the refresh token. TOKENS is keyed only by a SHA-256 of the refresh token presented (and of the new one), valid until 2 minutes before expiry, so a cached token is reachable only by someone who holds that refresh token — never by mailbox address or across Hub users. Microsoft may return a new refresh token: access_token hands it back and connect() saves it to the mailbox (older ones stay valid until they expire). forget(user) clears TOKENS and that user's pending DEVICE entries; Vault.lock_now calls it. Errors pass through friendly() (AADSTS70002 public client flows, 700016 unknown client ID, 50020 account type, 65001 consent, invalid_grant expired / withdrawn).
- **IMAP / SMTP.** IMAP outlook.office365.com:993, AUTHENTICATE XOAUTH2 with "user=<addr>^Aauth=Bearer <token>^A^A". SMTP smtp-mail.outlook.com:587 STARTTLS, EHLO, AUTH XOAUTH2 (notify.send_mail; smtp_for adds an 'oauth' dict with client_id, tenant, refresh). The outbox (10.2) therefore holds the refresh token instead of a password, under the same DPAPI protection.
- **Not logged.** Codes, tokens and the client ID are never written to the log; the page shows only "Signed in with Microsoft ✓".

### 8.6 Automatic prices (prices.py, 1.9)

- **Sources.** NSE capital-market bhavcopy in UDiFF format (nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip), the BSE equivalent (www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_<YYYYMMDD>_F_0000.CSV) and AMFI NAVAll.txt (portal.amfiindia.com, then www.amfiindia.com). Browser-like User-Agent and the exchange's Referer; 40 MB cap; _get is replaced by the tests. Exchange files are tried for today and back over up to 7 calendar days (weekdays only) until one exists — 404 before publication and holidays are normal; any other error (timeout, refused) ends that source at once. The three sources are fetched in parallel (20 s per request).
- **Parsing.** parse_bhav reads the header and finds columns by name (ISIN, ClsPric / CLOSE…, TckrSymb / SYMBOL, SctySrs / SERIES, TradDt…), so the older CSV layouts still parse; zip or plain CSV; rows of other segments are skipped; for an ISIN with several series the regular-market series (EQ, BE, GB, RR, IV, BSE A/B/T/X/Z…) wins. parse_amfi is header-driven too (AMFI added Plan and Option columns) and takes both the growth / payout and the reinvestment ISIN; "N.A." NAVs are skipped.
- **Merging (fetch).** Per ISIN the newest date wins; on the same date NSE beats BSE. An AMFI NAV replaces an exchange price only when it is more than 4 days newer, so ETFs keep their market price. A symbol index (exchange, symbol) serves securities without an ISIN.
- **Applying (apply).** Matched by ISIN; else by symbol on the security's own exchange; a security without an ISIN may also match the other exchange. A price is written only if its date is not older than cmp_date, and a manual price is replaced only by a strictly newer date. cmp_source becomes "NSE close", "BSE close" or "AMFI NAV". Returns the number of rows changed; unchanged prices are not rewritten (no needless re-encryption).
- **When.** prices.register adds a before_request hook after auth's guard (it needs g.user), for GET pages outside /api/. auto(con): if inv_settings.prices_auto is not '0' and the investments feature is on, write CACHE['data'] once per download (inv_settings.prices_applied = its timestamp, prices_result = a summary line) and call start_background(), which starts a daemon thread when the cache is older than 3 hours (30 minutes when a source failed last time). The thread only downloads and parses public files; it never touches a database. notify's scheduler calls tick() every minute: while WANTED (set by auto for the last logged-in user with prices on) it refreshes stale prices even while locked, so they are ready at the next log-in. FINANCEHUB_PRICES=0 (set by tests/_common) disables all downloads.
- **Update now** (POST /investments/prices) waits up to 60 s for a forced download, applies it, then tries yfinance (if installed) for securities whose price is missing or older than 7 days, and flashes each source's status. The same route with auto=0/1 sets the switch.
- Securities with no market data (unlisted bonds, deposits, schemes) keep prices from holdings files or the user.

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

- EXTRA_TICKS first, each in its own try: auth.idle_watch (4.5) and, since 1.7, backup.run_due (4.10).
- maybe_rebuild(): only while unlocked, when mark_dirty() was called (by close_db after a save, by prepare_db), after an hour, or after midnight.
- run_due(): for every outbox (MEMORY plus DPAPI files of all users, locked or not), send each unsent message inside its window; retry failures after 15 minutes (_FAILS); record success in the sent log (late if over an hour after send_at).

maybe_rebuild never touches the shared connection: snapshot_con() serialises V.con under V.lock into a private in-memory copy, and rebuild() runs build_outbox inside APP.test_request_context('/'), so no Viewing filter applies. Why: the shared connection belongs to the request thread (cursors, transactions, row factories), sqlite3 objects must not be used concurrently, and reminders must cover all accounts whatever the user views.

### 10.4 DPAPI and SMTP

_dpapi() wraps CryptProtectData/CryptUnprotectData via ctypes, binding the outbox to the Windows account so reminders can be sent while locked or after a restart. Off Windows only MEMORY is used. smtp_for() takes user and app password from the mailbox marked send_from (MR.settings(con) without an id) — or, for Outlook, smtp-mail.outlook.com:587 with an 'oauth' dict (8.5); the host is notify_settings.smtp_host or derived from the IMAP host (Gmail → smtp.gmail.com, imap.x → smtp.x); port 465 uses SMTP_SSL, others STARTTLS. /reminders/test sends a test report; HUB_SMTP_FACTORY lets tests replace the client.

## 11. Viewing filter, reports and UI conventions

### 11.1 scope.py

The Viewing filter is session['scope']: book, account or broker (+ label), set by /scope (next must be local). txn_sql(alias) returns SQL and parameters: Personal = entity not a company book; another book = that entity; account = account name; broker alone = transactions linked to it in txn_links; nothing = '1=1'. txn_literal() inlines parameters for helpers that take only a WHERE string (dashboard_data, planning.detect, alerts). account_in_scope() filters accounts in accounts_hub.build; broker_id() serves investments, assets and depository pages. Code that must see everything uses ignore_scope=True or a fresh request context (notify).

### 11.2 Reports (reports_hub.py)

A report is {title, subtitle, sections}; a section is 'kv' (label/value rows) or 'table' (columns, rows, money columns, totals columns). to_xlsx makes one sheet per section (Indian grouping '#,##,##0.00', red negatives, totals row, frozen header, autofilter); to_pdf makes landscape A4 with reportlab and a dated, numbered footer; send(rep, fmt, stem) returns the file. Builders: view_report (summary, heads, months, accounts, transactions, linked transfers), trades, transfers, director, reimbursements, people loans; depository.report_demat uses the same model.

### 11.3 base.html

- nav_groups: (id, label, icon, tone, items), items = (label, endpoint, args, icon, active test); groups Home, Accounts, Money, Investments, Plan, Settings; open state remembered in localStorage.
- Tones: CSS variables --indigo, --teal, --coral, --amber, --violet, --blue, --green, --pink, --slate, --red; class tone-<name> sets --tone for cards, chips, pills, bars, icons (t-tone, bg-tone-soft). Light/dark via data-bs-theme; choice in localStorage hub_theme.
- Cards and pieces: stat-card, chart-card, card-head, kpi, chip, pill-tabs, list-row, soft-box, bar, num, muted.
- Settings group (1.7): Categories, Payee rules, Features & accounts, People & entities, Statement passwords, Mail inbox, Reminders & reports by mail, Backup & restore, Help & user manual, Report a problem, Users & security. planning.PAGES adds Backup & restore, Report a problem and Setup wizard (welcome_step) to Ctrl+K.
- Top bar: Viewing filter, Ctrl+K palette (/api/search over planning.PAGES and data), alerts bell (/api/alerts/count), theme, Report menu (block report_menu), help "?" (help_page with topic = request.endpoint), Lock, Quit (only if hub_launcher).
- Mail badge: review count from mailreader._mail_ctx; with mail_auto the poll script (8.4) updates it and shows a toast.
- Feature switches (features.py): the context processor gives hidden_eps and hidden_kinds; the nav loop builds a visible item list per group (a group with no visible items is not drawn), accounts tabs drop hidden kinds, planning.search drops hidden pages, and features._features_guard redirects a hidden page to /features. The first GET of Home for which welcome.needed(con) is true (hub_settings.onboarding is not 'done' and features_done is not '1') goes to /welcome/you (skipped when app.testing unless FH_WIZARD is set); users who chose features in 1.6 never see the wizard. Nothing is deleted when a feature is off; demat requires investments; card & loan tools stay while cards or loans are on.
- Blocks: title, head, page_title, report_menu, content, scripts.

> **Important:** A top-level `{% set %}` in base.html overrides a view variable of the same name, even inside the child template's blocks. That is why base.html uses nav_groups, _ep and _tab instead of groups, ep or tab (accounts.html relies on its own tab). Never add a top-level set with a common name to base.html.

### 11.4 External assets

base.html and auth_base.html load Bootstrap 5.3.2, Bootstrap Icons, Chart.js 4.4.1, jQuery 3.7.1 and DataTables from cdnjs, and the Inter font from Google Fonts, without integrity attributes. static/js/picker.js (1.9) is the Hub's own.

### 11.4a Searchable pickers (static/js/picker.js, 1.9)

Any `<select data-picker>` is wrapped: the select stays (hidden, with its name, value and change event) and a button opens a panel with a search box. Every typed word must occur in the option's data-path (built from the indentation of the label when missing); matches are highlighted; ↑ ↓ Enter Esc work; disabled options show but cannot be chosen (the Categories move / delete dialogs disable them before opening). The select's value property is redefined on the element so that code setting select.value also updates the button. data-picker-add="1" offers "Add “…” under <current choice>" when nothing matches by name; it POSTs JSON to /categories/add and inserts the new option into every picker on the page that lists categories. Used on Transactions (filter, edit window, bulk), Payee rules and Categories (Under, move / delete target). The Categories page also has its own row search (catSearch) that keeps ancestors and descendants of matches visible.

### 11.5 First-start setup wizard (welcome.py)

STEPS = you, mail, features, accounts, backup (label and icon each). Endpoint welcome_step serves /welcome and /welcome/<name> (GET and POST; an unknown name redirects to you). The page (welcome.html) shows the steps as chips that link to each other; every step has Save and continue and Skip this step (skip=1); the last has Finish and add my first statements (then=import) and Finish.

POST without skip writes:

| Step | Writes |
|---|---|
| you | hub_settings.display_name (60 chars); a company name other than "personal" becomes an entities row (role 'book', aliases, sort_order 5) with INSERT OR IGNORE |
| mail | only when an address is given: saved into the first mailbox with MR.save_box_form (provider: Outlook for outlook.com / hotmail / live / msn domains, otherwise Gmail — also Google Workspace — unless the address is unchanged; password spaces removed, kept if empty, never stored for Outlook, which finishes with Sign in with Microsoft on /mail), mail_settings enabled (automatic reading); recipients validated by notify.EMAIL_RE go to notify_settings recipients with enabled (reminders) |
| features | features_off from the ticked keys, closed over features.REQUIRES |
| accounts | nothing (Add links open accounts?tab=<kind>&add=<kind> in a new tab) |
| backup | backup.target_dir check, then backup.save_settings(dir, every, keep=10) in users.json; an unusable folder flashes a warning and stays on the step |

The features step sets features_done = '1' even when skipped (everything stays on). After the last step onboarding = 'done' and features_done = '1', then redirect to import_page (then=import) or Home. Every step can be reopened later, for example from Ctrl+K "Setup wizard".

## 12. Help and support

### 12.1 Manuals (help_hub.py)

- Chapters: docs/user/NN-slug.md (slug without the number), optional endpoints and icon comments; chapters() caches by file names and modification times.
- Markdown subset: headings # to ####, paragraphs, - / * / 1. lists (two-space nesting, three levels, indented continuation lines), tables, fenced code, > callouts (Important and Warning shown as warnings; Tip, Note, Good to know as tips), --- rules; inline bold, italics, code and links to help:slug#anchor, /path, #anchor or https://. HTML is escaped; repeated heading ids get -2, -3.
- Mapping: "?" opens /help/<endpoint>; chapter_for matches a slug, then a chapter listing the endpoint, and redirects to /help/<slug>#<anchor>; unknown topics go to the index.
- Search: every word must occur in a section; score = occurrences + 5 per word in its title; top 20 with snippets.
- PDF: reportlab, cover with contents, a page per chapter, footer. Text is mapped to Helvetica's character set (rupee sign → Rs, arrows and dashes replaced); code blocks print verbatim in Courier, so keep them ASCII and under about 95 characters. /help/manual.pdf holds all chapters; design_pdf splits DESIGN.md at level-1 and level-2 headings.
- Design manual: /help/internal/design and its PDF are admin-only (403 otherwise, 404 if missing).
- The help sidebar also has a Report a problem button (support_page).

### 12.2 Report a problem (support.py)

The support address is hub_version.SUPPORT_EMAIL (a gmail.com address, which the release privacy scan allows).

```
GET  /support         page(): preview built from request.args ("Update preview" is a
                      GET of the same form), ref from ?ref=
POST /support/send    send(): summary required; action = download | mailto | send
_build(): diagnostics() if diag == '1'      (default on)
          recent_errors(LOG_DIR, ref) if logs == '1'   (default on)
          compose(form, diag, logs, contact) -> plain text
```

- compose: Summary, Where in the Hub, How bad (minor / normal / blocking), What happened, Steps, What I expected, Error reference, Reply to, "--- Technical details ---", "--- Recent errors from the log (numbers, e-mails and paths masked) ---", "Sent <time> from Finance Hub."
- diagnostics(con, vault, app): Finance Hub VERSION and Statement Reader ENGINE_VERSION; Python, platform.system/release/version; installed (hub_paths.INSTALLED) or portable; HUB_SERVER; features.off; COUNT(*) of accounts, transactions and statements; mail inbox set up and automatic. Each part in its own try.
- recent_errors(log_dir, ref): the last 3000 lines of hub.log; keeps lines containing " ERROR ", " WARNING " or "Traceback", plus continuation lines (indented, or starting "<Name>Error" / "<Name>Exception") after a traceback or ERROR line. With ref, the list is cut after the last line containing ref and keeps up to 60 lines before it, so it ends with that error's traceback. Each line is scrubbed and cut to 300 characters; at most 60 lines (MAX_LOG_LINES).
- scrub(text), in this order: e-mail addresses `[\w.+-]+@[\w-]+\.[\w.]+` become <e-mail>; PAN `[A-Z]{5}\d{4}[A-Z]` (any case) becomes <PAN>; rooted paths (drive letter or /, at least one separator) become <path>/<last part>; numbers `\d[\d,]{3,}(?:\.\d+)?` become <number>. Side effects: dates and times in log prefixes are also masked; names, numbers under four digits and file names are not.
- scrub is applied to the log lines and to every typed field (summary, where, what, steps, expected) and to the mail subject.
- Sending: download returns text/plain FinanceHub_problem_report.txt; mailto redirects to mailto:SUPPORT_EMAIL with subject and body (body cut at 1800 characters); send uses notify.smtp_for(mail_settings, notify_settings) and needs host, user and password: EmailMessage From "Finance Hub <hub mailbox>", To SUPPORT_EMAIL, Reply-To the contact, Subject "Finance Hub <VERSION> — problem: <summary[:80]>"; SMTP_SSL on 465, else STARTTLS; app.config HUB_SMTP_FACTORY replaces the client in tests. Success logs "Problem report sent to support" and redirects to help_page; failure flashes the error (120 characters).
- errorhandler(500), registered by support.register (it replaced the plain handler in app.py): ref = uuid4().hex[:8].upper(); app.logger.error("Error reference %s on %s %s"); renders auth_error.html with the reference and a link to support_page?ref=<ref>. Flask logs the traceback just before, which is why recent_errors(ref) can find it.

## 13. Security model

1.7 changes the model in one deliberate way: key escrow (4.9) trades "nobody but the user can open their data" for "a forgotten password and lost recovery key can be repaired by an administrator". Within one Hub, users are protected from each other only if they are not administrators.

| Threat | Mitigations | Residual risk |
|---|---|---|
| Copied data folder or stolen disk | AES-256-GCM files; DEK wrapped by PBKDF2 (600 000) of password or recovery key; sealed previews and mail files; uploads erased after import and after a day; DPAPI outbox | guessing weak passwords offline (limited by rules and PBKDF2 cost); users.json reveals IDs, roles, log-in times and backup folders and times; secure delete is best effort on SSDs; logs may hold error texts |
| Another Windows user | data folder: setup grants the installing user Modify, other access is inherited from the parent folder; server on 127.0.0.1 and every guarded request needs a cookie signed with a per-start secret plus the vault nonce; outbox bound to the Hub's Windows account | a data folder on another drive may be readable by other local accounts (files stay encrypted); other users reach the port's open endpoints, including /setup/restore before the first user exists; a PC administrator can read memory while unlocked |
| Administrator reading another user's data (escrow) | the escrow private key exists only wrapped with each admin's DEK; non-admins hold no escrow_key and demotion removes it; a reset sets must_change and the old password stops working; disclosed on the Users page | any admin can decrypt any user's escrow_dek offline, from users.json alone, without a trace, and with that DEK every past and future backup of the user; the DEK is never rotated |
| Malicious mail | allowlist, header-first fetch, type and size limits, own parsers only, no links followed, HTML never rendered (alerts kept as stripped text), auto-import only when every check passes | bugs in pdfplumber, pikepdf, openpyxl, xlrd; a hostile but validly signed mail from an allowed domain |
| Look-alike senders | exact or subdomain match; DMARC or aligned DKIM from the topmost Authentication-Results; mx.google.com required for Gmail; forwarded mails never auto-import | non-Gmail hosts: any topmost header is trusted; broad entries such as bank.in |
| Stolen app password or Microsoft refresh token | kept only in the encrypted database and the DPAPI outbox; dedicated mailbox advised; Outlook uses OAuth with only IMAP / SMTP / offline scopes and can be signed out (8.5); Hub reads (BODY.PEEK), labels, sends to set recipients | an app password gives full mailbox access until revoked; a refresh token until it expires or is withdrawn |
| Localhost server | binds 127.0.0.1; Waitress clears untrusted proxy headers; next checked at log-in and profile | no CSRF tokens (SameSite=Strict cookie instead); /logout and /scope change state on GET; CDN assets without integrity |
| Forgotten password | recovery key wraps the same DEK; an admin can reset through the escrow (only for users who logged in once under 1.7, and not for oneself) | losing both, with no other admin holding escrow_key, loses the data |
| Backups in a cloud folder | .fhb holds only ciphertext plus the wrapped keys of its time; written to a local folder, uploaded by the sync app; sha256 per part and AES-GCM tags checked on restore; a safety backup precedes every restore | offline guessing against the wrapped key; old passwords and recovery keys open old backups; manifest and file name show user ID and times; the cloud account's own security is out of scope |
| Price downloads (1.9) | whole public files fetched over HTTPS from fixed NSE, BSE and AMFI URLs, nothing about holdings in the request; size cap 40 MB; parsed as CSV / text only, numbers validated; a source that fails is reported and skipped; only cmp, cmp_date, cmp_source are written | a wrong or spoofed file (e.g. a compromised exchange site or TLS interception by local software) would show wrong prices until the next file; NSE may refuse non-browser downloads (BSE / yfinance then fill in) |
| Problem reports | sent only on a click, after a preview of the exact text; diagnostics are versions, switches and counts; log lines scrubbed (12.2); no files attached; sent through the user's own mailbox or mail program | names, short numbers and file names pass the scrub |
| Installer | release zip checked against MANIFEST.sha256; absolute, drive and .. paths refused; only the program-folder part runs elevated, and it is waited for; shortcuts and the Run key are written unelevated | the manifest is not signed (it detects damage, not a replaced setup package); Setup.cmd runs whichever py / python is first on PATH; the elevated part runs setup.pyw from the user-writable setup folder |

Out of scope: malware running as the same Windows user (memory, keystrokes, DPAPI); someone using an unlocked Hub at the PC (idle lock and Lock limit it); copies of backups/ and .fhb files taken elsewhere (they stay encrypted); the OneDrive or Google Drive account; isolation between Hub users beyond separate keys (one process, one open database) and, since 1.7, isolation from administrators.

## 14. Versioning, release and upgrade

### 14.1 Versions and git

- Every change gets a new version: hub_version.VERSION and RELEASE_DATE, plus a "## <version> — <date>" entry on top of CHANGELOG.md, written for the user. Versions run 1.1, 1.2…; earlier history was deleted at the owner's request. The version shows in the sidebar, /healthz and the release name.
- The Statement Reader engine has its own version, statement_reader/version.py APP_VERSION (v14), and statement_reader/CHANGELOG.md; it changes only with a new export. compounding.APP_VERSION is the planner engine's version.
- git: one annotated tag per version (v1.5, v1.6…) on the commit the zip was built from; make_release prints git describe --tags --dirty. Commit subject "Finance Hub <version> — <summary>", body with what and why (user-facing list in CHANGELOG.md), attribution trailers last, as in the 1.5 baseline. Never commit runtime folders, statements or real samples.

### 14.2 tools/make_release.py

1. CHANGELOG.md must have a "## <VERSION>" heading.
2. Privacy scan of text files (.py .pyw .html .md .bat .txt .json .js .css .cfg .toml) for PAN, card and account numbers, Aadhaar, IFSC, mobile numbers and e-mail addresses, with allow-lists for synthetic values; findings stop the build unless --allow-findings. It cannot detect names — review diffs for them.
3. tests/run_all.py unless --skip-tests; failures stop the build.
4. dist/FinanceHub_<VERSION>.zip without data, uploads, backups, logs, .venv, .git, dist, __pycache__, tests, statements, users.json, requirements.lock, financehub.json, finance.db and .enc, .prev or .pyc files; MANIFEST.sha256 inside; FinanceHub_<VERSION>.zip.sha256 beside it. installer/ is included.
5. dist/FinanceHub_<VERSION>_Setup.zip (1.7): one folder FinanceHub_<VERSION>_Setup/ with installer/setup.pyw, Setup.cmd, hub.ico, README.txt, FinanceHub_Setup.iss, build_exe.bat and the release zip; FinanceHub_<VERSION>_Setup.zip.sha256 beside it. This is what users receive.

### 14.3 tools/upgrade.py

1. Verify every file against the zip's MANIFEST.sha256; refuse damaged zips and zips containing data folders or users.json.
2. Refuse while /healthz answers on 127.0.0.1 at FINANCEHUB_PORT or hub_paths.PORT.
3. Back up the .enc and .enc.prev files, the _files folders and users.json from DATA (hub_paths.DATA_ROOT; the program folder when hub_paths cannot be imported) to DATA/backups/<date>_before_<version>/, write data/.version, keep the newest 10.
4. Write the program files and the new MANIFEST.sha256.
5. Delete .py, .pyw, .html, .md and .bat files of the old manifest that the new one lacks.
6. pip install -r requirements.txt into .venv (or advise install.bat).

It writes into the program folder without elevation, so it suits portable copies; an installed copy is upgraded by running the newer setup (14.5).

### 14.4 Launcher backup and installation

- backup_on_upgrade(): when DATA_ROOT/data/.version differs from VERSION and encrypted data exists, copy .enc, .enc.prev, the _files folders and users.json to BACKUP_DIR/<YYYY-mm-dd_HHMMSS>_before_<VERSION>/ with FROM_VERSION.txt, write the marker, keep the newest 10 folders. Backups stay encrypted; outbox and sent log are not copied. Only folders named like that count as version backups (Running card, pruning in the launcher and upgrade.py); restore safety copies live in backups/before-restore/.
- Portable copies (no financehub.json): install.bat finds Python 3.10+, creates .venv, installs requirements.txt, writes requirements.lock, runs tools/shortcuts.py and starts the launcher; safe to repeat, never touches data. run.bat starts .venv pythonw with FinanceHub.pyw, or install.bat if .venv is missing.
- tools/shortcuts.py creates "Finance Hub" shortcuts on the Desktop and Start menu via PowerShell (Windows only). Start with Windows is an HKCU Run value FinanceHub with --background, written by the tray, the Users page and setup alike.

### 14.5 Installation (installer/, 1.7)

| File | Role |
|---|---|
| Setup.cmd | entry point: finds Python 3.10+ (`py -3`, run as `pyw -3`; else `python`, run as `pythonw`), else explains and opens python.org/downloads/windows and exits 1; `start /wait` setup.pyw; /uninstall → --uninstall, /silent → --silent --desktop --start |
| setup.pyw | tkinter wizard, command line, install, upgrade, uninstall |
| FinanceHub_Setup.iss, build_exe.bat | optional single .exe with Inno Setup 6 |
| README.txt, hub.ico | short instructions; window icon |

```
setup.pyw (no arguments) -> wizard(): Welcome | Folders | Options | Install
  full_install(opts, log)                         (worker thread)
    hub_running() on 127.0.0.1:5000? -> refuse ("quit it first")
    program or data not writable and not admin?
      yes: run_elevated(--silent --program P --data D [--import-from X]
                        --grant-user %USERNAME% --elevated --log FILE)   UAC
      no:  install_program(...) in this process
    make_shortcuts(), set_autostart(), start_hub()   (always as the user)

install_program(program, data, import_from, packages, log, grant_user)
  verify every file of FinanceHub_<v>.zip against its MANIFEST.sha256
  refuse names starting with / or \, containing .. or a drive colon
  write files and MANIFEST.sha256; delete files of the old manifest that
    the new one lacks (never KEEP: data uploads backups logs .venv users.json
    financehub.json requirements.lock)
  copy setup.pyw and Setup.cmd to <program>/installer
  mkdir data; write financehub.json {"data_dir": D, "port": 5000}
  icacls D /grant <user>:(OI)(CI)M /T /Q          (elevated run only)
  bring_data(X, D)   make_venv(program)   register_uninstall()
```

- Defaults: default_program_dir() = ProgramW6432 (or ProgramFiles)\Finance Hub; default_data_dir() = D:\Finance Hub when D:\ exists, else C:\Finance Hub Data (~/Finance Hub Data off Windows). installed_location() reads InstallLocation from the uninstall key (HKLM, then HKCU); when found, the Welcome page announces an upgrade and the folders default to that program folder and its financehub.json data_dir.
- Wizard pages: Welcome (version, Python used, earlier install); Folders (program, data, "Bring over the data of an existing Finance Hub folder" with a path; go_next requires both folders, refuses data = program, and requires users.json or financehub.json in the import folder); Options (Desktop shortcut on, start with Windows off, start now on, summary; Next becomes Install); Install (log text, indeterminate progress bar, buttons disabled). The worker runs full_install; the Log object appends to %TEMP%\FinanceHub_setup_<pid>.log, the elevated process writes the same file (--log), and the page polls it every 400 ms. An exception shows "Setup did not finish: <error>" and a Close button; success shows Finish.
- Elevation: needs_admin(path) tries to create a test file in the nearest existing parent. run_elevated() re-runs setup.pyw through ShellExecuteExW (verb runas, hidden window, SEE_MASK_NOCLOSEPROCESS), waits for it and returns its exit code; a refused UAC prompt raises "administrator permission was not given". Only install_program runs elevated, so shortcuts (Programs and Desktop of the user) and the HKCU Run value land in the installing user's profile.
- ACL: an elevated run creates the data folder as administrator, so --grant-user grants the installing user (USERNAME of the unelevated process) Modify with object and container inheritance, recursively. The Hub, running as that user, can then write there.
- bring_data(src, data): follows src/financehub.json to its data_dir; requires users.json; if data/users.json already exists it only logs "The data folder already has users …" and copies nothing; otherwise copies users.json, data/*.enc, *.enc.prev, *.outbox, *.sent.json, .version and *_files/, and backups/. The source is never changed. Because .version comes along, the launcher's first start backs the data up for the new version.
- make_venv: the Python running setup (python.exe beside pythonw.exe) creates <program>/.venv if missing, then pip install -r requirements.txt without a console window and pip freeze to requirements.lock; a pip failure raises with the tail of its output (internet needed).
- register_uninstall: HKLM when running as admin, else HKCU, key Software\Microsoft\Windows\CurrentVersion\Uninstall\FinanceHub: DisplayName, DisplayVersion, Publisher, InstallLocation, DisplayIcon (static\hub.ico), UninstallString ("<.venv pythonw.exe>" "<program>\installer\setup.pyw" --uninstall), NoModify, NoRepair.
- Shortcuts: PowerShell with WScript.Shell creates "Finance Hub.lnk" in Programs (and Desktop when chosen), target .venv\Scripts\pythonw.exe with "FinanceHub.pyw", working folder the program folder, icon static\hub.ico. set_autostart writes or deletes HKCU Run FinanceHub = pythonw FinanceHub.pyw --background, so setup also turns autostart off when unticked. start_hub starts the launcher detached.
- Upgrade = the same flow over the existing folders. The program folder is rewritten, stale files go, the data folder is untouched; the launcher makes the version backup at the first start.
- Uninstall (--uninstall [--program DIR]): the program folder is --program, else InstallLocation, else the folder above setup.pyw — and it must look like an installation (app.py, hub_version.py, MANIFEST.sha256) or nothing is removed. When started with the Python inside that folder (Settings › Apps runs the .venv pythonw), it first restarts itself from a temp copy with the base Python (base_pythonw). A yes/no question names the data folder that is kept (skipped with --silent); refuses while the Hub runs; removes the HKCU Run value and both shortcuts; if the program folder needs elevation, runs the temp copy elevated (run_elevated with script/exe, waited for) with --uninstall --silent --program, then reports the result; otherwise rmtree(program) and deletes the uninstall key under HKLM and HKCU. The data folder is never touched.
- Command line: --silent --program --data --import-from --no-packages (also passed to the elevated part) --log --elevated --grant-user --uninstall --desktop --autostart --start. install_program keeps the keys of an existing financehub.json (e.g. a custom port) and only sets data_dir. --silent with --elevated runs install_program only; --silent alone runs full_install. Without tkinter the wizard raises ImportError and main() prints a hint to use /silent.
- Inno option: FinanceHub_Setup.iss (Inno Setup 6) takes AppVersion from the FH_VERSION environment variable (default 1.7) and builds FinanceHub_<v>_Setup.exe with CreateAppDir=no, Uninstallable=no, PrivilegesRequired=lowest. It unpacks setup.pyw, Setup.cmd, hub.ico and FinanceHub_*.zip to {tmp} and runs `cmd /c Setup.cmd`, waiting until it ends. build_exe.bat finds ISCC.exe under Program Files (x86) or Program Files, derives FH_VERSION from the zip name and compiles. The .exe is only a self-extracting wrapper: Python must already be installed, and the Hub's own uninstall entry, not Inno's, removes the program.

## 15. Testing

- tests/_common.fresh(name) copies the program (without .git, .venv, data, users.json, uploads, backups, logs, dist, databases, tests) to a temp folder, changes into it and puts it first on sys.path: tests never touch real data.
- tests/run_all.py runs each tests/test_*.py in its own process, prints PASS/FAIL with the output tail, and exits 0 only if all pass.
- Synthetic data only: invented names, accounts such as "Test Savings 1111", made-up ISINs, fake IMAP and SMTP.
- Environment hooks: FINANCEHUB_DATA (data folder), FINANCEHUB_CLOUD_DIRS (extra "cloud" folders for cloud_folders), app.config FH_WIZARD (show the setup wizard although app.testing is set), HUB_SMTP_FACTORY.
- tests/_tkstub/tkinter is a minimal stand-in for tkinter (Tk and widgets that record their options in ALL, after() callbacks queued in AFTER, StringVar / BooleanVar, ttk, filedialog, messagebox). tests/_tkstub/drive_wizard.py loads setup.pyw from the unpacked Setup package with that stub first on sys.path, replaces full_install with a recorder, presses Next three times, drains AFTER and checks the options passed. It needs no display. UAC, the registry, shortcuts, icacls and pip are Windows- or network-only and are not exercised; test_installer runs on Linux with --no-packages.

| Test | Covers |
|---|---|
| test_core.py | setup and weak passwords, recovery key, books, classification, links, director, reimbursements, people loans, asset types, broker views, Viewing filter, reports, search, encryption at rest, second user, recovery, restart, display name, open-redirect check |
| test_demat.py | CAS reading per demat, commit, reconciliation statuses, portfolio statement quantities, old CAS broker migration |
| test_imap_client.py | mailreader.Imap against a scripted IMAP server (capabilities, UIDVALIDITY, SEARCH SINCE, header parsing, BODY.PEEK, labels; AUTHENTICATE XOAUTH2 instead of LOGIN) |
| test_mail_inbox.py | allowlist, rejected look-alikes, sealed alerts, forwarded mail to review, auto-import of CAS and statements, duplicates, allow sender, review, poll not counted as activity, auth_check units |
| test_1_6.py | help chapters (endpoints, links, PDF, design pages if DESIGN.md exists), refunds, reminder outbox, timing, no double send, sent-log privacy, Home redirect to /welcome, features, launcher pieces |
| test_1_7.py | separate data folder via FINANCEHUB_DATA (nothing written to the program folder); escrow fields; admin reset, must_change and /account/password; own rename; a member cannot reset; rename_other; promotion grants escrow_key; backup save, now and download (no plaintext in the file), restore with the same key, safety copy, still logged in, damaged file refused, run_due due and not again; restore_fresh on a new Vault, refused a second time and with a wrong password; scrub; support page, download, mailto and send with a fake SMTP; 500 page with error reference; the setup wizard's five steps, what they write, shown once |
| test_1_8.py | oauth_ms against a fake Microsoft endpoint (device code, pending → ok, cached and rotated tokens keyed by the token presented, no token → no access, forget(), invalid_grant, consumers fallback, friendly texts, XOAUTH2 string, id_token account); Gmail app-password advice; migration of the 1.7 mailbox (no password left in mail_settings); adding an Outlook mailbox and signing in through the routes; check_mail over two mailboxes with Gmail- and Microsoft-style Authentication-Results, mailbox_id tagging, a mail in both read once, rotated refresh token saved; pause; SMTP with password vs XOAUTH2 on 587 after send_from; sign-out, edit keeps the password, remove moves send_from; signed in as another account → warning; empty label leaves Outlook mails untouched; custom port kept; switching away from Outlook forgets the sign-in; wizard defaults unknown domains to Gmail and stores no Outlook password |
| test_1_9.py | categories seven and eight levels deep, duplicate names refused, JSON add, own top-level group with a kind, move a deep branch under it (kind and Head refreshed), move into itself refused, delete with transactions moved, Types fixed; transactions, breakdown (screen and Excel), rules, budgets and Ctrl+K with deep categories; pickers on the pages and picker.js served; prices from fake NSE (zip) / BSE (csv) / AMFI files: lookback over unpublished days, NSE over BSE, EQ over block series, ETF market price over NAV, SGB and bond, symbol match without ISIN, manual and newer prices kept, nothing rewritten; background download after a page and applied on the next; switch off, scheduler idle, Update now, feature off, offline sources |
| test_installer.py | make_release (--skip-tests --allow-findings) builds the Setup zip; silent install with --no-packages into temporary program and data folders, bringing over an old portable Vault; financehub.json; a subprocess in the installed folder finds its data and logs in; upgrade removes a stale file and keeps data; import into a folder with users is refused; a tampered release is refused; uninstall keeps data; the wizard's page flow through tests/_tkstub |

To add a test: create tests/test_<topic>.py; call `SP = fresh('<topic>')` before importing app; drive A.app.test_client() after posting /setup and /login, or use A.app.test_request_context() with A.get_db(); fake external services by replacing mailreader.Imap or oauth_ms._post, passing a factory to check_mail or notify.run_due, or setting app.config HUB_SMTP_FACTORY; assert, then run tests/run_all.py.

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
- Intraday prices (today's files are end of day only); prices for unlisted bonds.
- Google sign-in (OAuth) for Gmail too, instead of app passwords: Outlook uses OAuth since 1.8 (8.5); Gmail's IMAP scope needs a Google-verified app, so app passwords stay for now.
- More bank, card and broker readers as samples arrive.
- A compiled installer: today the .exe (Inno Setup) is optional and still needs Python; bundling a Python runtime would remove that step.
- DEK rotation (re-encrypt with a new key) so that old backups and an escrow copy stop opening new data after a compromise.

### 17.2 Limitations

- Single worker thread: IMAP checks, large PDFs and big reports block the UI; mail is read only while a page is open.
- One open database at a time; another user's log-in locks the first.
- Windows-only DPAPI outbox, tray, autostart and shortcuts; elsewhere reminders need a running, unlocked-once process.
- Whole-database re-encryption on each writing request; account names as keys; UI libraries from CDNs.
- Installation needs Python 3.10+ installed first (Setup.cmd only finds it or opens python.org). No real .exe is compiled in the build environment: FinanceHub_Setup.iss and build_exe.bat need Inno Setup 6 on a Windows PC, and the resulting .exe is a wrapper around Setup.cmd.
- The tkinter wizard is tested only with the stub (15); UAC elevation, icacls, registry entries, shortcuts and pip are not covered by automated tests and must be checked by hand on Windows.
- Automatic backups need the Hub running (Start with Windows); uploading to the cloud depends on the sync app.
- Key escrow: administrators can read every user's data (13).
- Outlook needs the user's own Microsoft app registration (no client ID ships with the Hub); mailboxes are read one after another in the request that checks mail.

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

### 17.4 Review findings (1.7)

Found while writing the 1.7 manuals and fixed before release:

| Finding | Fix |
|---|---|
| uninstall could fall back to the folder above setup.pyw | uninstall() refuses unless the folder looks like an installation (app.py, hub_version.py, MANIFEST.sha256) |
| elevated uninstall ran the .venv Python inside the folder being removed; no final message | uninstall continues from a temp copy with the base Python (base_pythonw), waits for the elevated part and reports the result |
| financehub.json port reset to 5000; hub_running() checked 5000 only | existing financehub.json keys are kept; hub_running() reads the configured port |
| --no-packages not passed to the elevated run | passed |
| restore safety copies counted as version backups | version backups are only folders named YYYY-MM-DD_HHMMSS_before_<v> (app, launcher, upgrade.py); safety copies go to backups/before-restore (newest 10) |
| make_backup persisted from the scheduler thread | run_due passes persist=False (every request already saved its changes) |
| users.json read-modify-write without a lock | the mutating Vault methods run under V.lock (@_locked), as do log-in, the admin grant on the Users page and backup.save_settings |
| restore_mine accepted another user's backup | only the same database (manifest/entry db) or the same user ID |
| restore_fresh trusted names from the file | db must match [0-9a-f]{16}.enc and the user ID the user-ID rule |
| backups not listed / pruned after a user-ID change | manifest records db; listing and pruning go by db |
| restore form asked for "password of then" | asks only for a backup from another installation |
| typed report text was not scrubbed | scrub() applies to every typed field and the subject; the page says so |
| mailto text promised a saved file; a failed send lost the form | wording fixed; send re-renders the form with its values and the error reference |
| error page / Users card wording | "data folder" |
| tests/_common copied financehub.json | excluded |


### 17.5 Review findings (1.8)

Found by an independent review of the 1.8 change and fixed before release:

| Finding | Fix |
|---|---|
| handled mails were labelled 'FinanceHub' even with an empty label, so Outlook / other servers got a new folder and a copy of every mail | the mailbox's own label is used; empty leaves mails untouched |
| the wizard made unknown domains an 'other' mailbox without a server (a 1.7 regression for Google Workspace); it stored a password for Outlook addresses | unknown domains default to Gmail; Outlook gets no password; the wizard goes through save_box_form; configured() needs a server |
| switching a mailbox away from Outlook kept its refresh token | cleared |
| a typed IMAP port was replaced by the provider default | kept |
| the access-token cache was keyed by client ID + address and preferred over the stored token, so another Hub user adding the same address could use it | TOKENS is keyed only by the refresh token presented; forget() on lock |
| mails read before 1.8 could be credited to whichever mailbox was checked first | the migration assigns them to the migrated mailbox |
| signing in with a different Microsoft account than the mailbox address failed later with a misleading message | the id_token's account is compared and the page warns |

### 17.6 Review findings (1.9)

Found by an independent review of the 1.9 change and fixed before release:

| Finding | Fix |
|---|---|
| deleting a category offered the Type, not its parent, as the default target; rows moved onto a Type kept the deleted head's name | the longest ancestor (its parent) is chosen; _refresh_heads also covers rows on a Type |
| Update now could time out: each source walked back a week of 30 s timeouts, one source after another | only a 404 walks back a day; sources run in parallel; 20 s per request; retry after 30 minutes when a source failed |
| exports cut the path at four levels, so deeper rows repeated their parent | deeper levels are joined into the Item column |
| search highlighting replaced inside already-highlighted HTML | one pass over the plain text (HubPicker.hl), then escaped |
| rename / move compared names case-sensitively; names could contain the path separator '›' | case-insensitive everywhere; '›' replaced by '-' |
| ITR summary mixed a head under the user's own income group with a built-in head of the same name | user groups are keyed '<group> › <head>' |
| a holding whose ISIN changed was never priced | symbol match on its own exchange as a fallback |
| AMFI file with a byte-order mark would parse as empty | decoded as utf-8-sig |
