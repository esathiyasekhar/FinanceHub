# Finance Hub — notes for Claude Code

Personal-finance web app (Flask + SQLite, runs on the owner's Windows PC at http://127.0.0.1:5000), with the
Statement Reader engine (`statement_reader/`) and a Core + Satellite wealth planner. Current version: see
`hub_version.py` (1.12 when this file was written, 29 Oct 2026). Full history: `CHANGELOG.md`.

**The authoritative technical description is `docs/design/DESIGN.md`** (architecture, every module, tables, flows,
security model, tests, review findings). Read the relevant section before changing a module, and update it in the same
change. The user manual is `docs/user/*.md` (shown inside the app under Help).

## Owner's standing rules — always follow
1. **Every change gets a new version number**: 1.12 → 1.13 → … (1.10 follows 1.9; compare numerically). Bump
   `hub_version.VERSION`, add a `CHANGELOG.md` entry, commit, and tag `v1.N`.
2. **Never print, log or echo passwords**, recovery keys, app passwords or OAuth tokens.
3. **No personal data in code, docs, tests, packages or git history** — synthetic data only (names like "Test Person",
   accounts like "Test Savings 1111", made-up ISINs, `example.com` addresses). `tools/make_release.py` runs a privacy scan;
   never add `--allow-findings` to get past it.
4. **Each user's data is linked to their login and stays encrypted** (`vault.py`: AES-256-GCM per-user database, kept in
   memory while unlocked). Never write plaintext copies of user data to disk.
5. **Standalone app on the owner's PC** — not hosted in the cloud. Remote access, when built, goes through a private
   tunnel (e.g. Tailscale) with 127.0.0.1 kept as the default.
6. Ask the owner when a request is ambiguous (he answers multiple-choice questions quickly); explain results in plain words.

## Development setup (Windows, this folder)
```bat
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
rem run a DEV copy without touching the real data or the installed Hub (port 5000):
set FINANCEHUB_DATA=%TEMP%\fh-dev
set FINANCEHUB_PORT=5050
.venv\Scripts\python app.py
```
The installed Hub lives in `C:\Program Files\Finance Hub` with its data in the data folder chosen at setup
(default `D:\Finance Hub`). Do **not** point a dev run at that data folder.

## Tests and release
- `python tests\run_all.py` — every `tests/test_*.py` in its own process, on a fresh temp copy (`tests/_common.fresh`),
  synthetic data, fake IMAP/SMTP/Microsoft/price sources. `FINANCEHUB_PRICES=0` is set by the tests (no downloads).
  `tests/planner_engine_check.js` (planner maths) needs `node`; skipped if node is missing.
- New feature → new `tests/test_<version>.py` (pattern: `SP = fresh('vNNN')`, then import `app`, post `/setup` and `/login`).
- `python tools\make_release.py` → `dist\FinanceHub_<v>.zip` and `dist\FinanceHub_<v>_Setup.zip` (checks CHANGELOG entry,
  privacy scan, runs the tests, writes MANIFEST.sha256). The owner installs/upgrades by unzipping the Setup zip and running
  `Setup.cmd` (data is kept). Optional single .exe: `installer\build_exe.bat` with Inno Setup 6.
- Release checklist: version bump · CHANGELOG · user manual chapter · DESIGN.md (module map, section, test table) · tests ·
  `run_all` green · `make_release` · commit (`Finance Hub 1.N — summary`) · `git tag -a v1.N`.

## Layout (details in DESIGN.md §2.4)
`app.py` (Flask app, registers every module; order matters — see below) · `vault.py` / `auth.py` / `dbconn.py`
(encryption, login, per-request DB) · `importer.py` + `statement_reader/` (bank/card statements) · `classifier.py` /
`organise.py` (category tree of any depth, rules, transactions, breakdown) · `accounts_hub.py` (accounts, dues, net worth) ·
`investments.py` / `depository.py` / `assets.py` / `prices.py` (brokers, CDSL/NSDL, asset types, automatic prices) ·
`mailreader.py` / `oauth_ms.py` (mail inbox: several mailboxes, Gmail app password or Outlook OAuth, senders list, deletion) ·
`notify.py` (reminder mails, scheduler `EXTRA_TICKS`) · `compounding.py` + `static/planner/` (wealth planner) ·
`backup.py`, `welcome.py`, `features.py`, `support.py`, `help_hub.py` · `installer/` · `tools/` · `templates/` · `static/`.

## Gotchas
- `statement_reader/` is copied from the separate **StatementReader** repo (`..\StatementReader-source`) by its
  `tools/export_engine.py`. Never edit it here — change the reader there, bump its version, re-export.
- `app.py` registration order: hooks needing `g.user` (e.g. `prices.register`) must come **after** `auth.register`.
- In `templates/base.html` never add a top-level `{% set %}` with a common name (it overrides view variables).
- One request at a time (Waitress threads=1); background threads (scheduler, price downloads) must never touch a user's
  database — only public data or the DPAPI outbox.
- UI libraries load from cdnjs; `static/js/picker.js` (searchable selects) and `static/planner/*.js` are our own.
- Mail deletion only ever moves mails to the mailbox's Trash after verifying the Message-ID (DESIGN.md "Deleting mails").

## Open items (Oct 2026)
- Owner to confirm on the real PC: Hotmail "Sign in with Microsoft"; first real run of "Update prices now" (NSE / BSE /
  AMFI file formats were only tested on synthetic files); planner spouse tab after 1.12.
- The separate `E:\Finance Organiser\Compounding Calculator` app shares `calculator.js` but lacks the 1.12 fixes.
- Planned: private remote access (Tailscale); alert mails → provisional transactions; maybe Google OAuth for Gmail.
