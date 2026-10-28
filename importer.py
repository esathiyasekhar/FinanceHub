"""Finance Hub ⇄ Statement Reader engine: preview → confirm import.

preview_file()  – find the password, parse with the engine (PDF) or the Hub's own
                  CSV/XLSX importers, map to Hub accounts, flag duplicates, plan loan
                  updates. Nothing is written to the database. The preview is saved to
                  uploads/.pending/<token>.json so that *exactly* what the user saw is
                  what gets imported.
commit_preview() – write statement, accounts, transactions and loans in one transaction.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import classifier
from statement_reader import auto_detect_parser, needs_password, check_password, ENGINE_VERSION

# ── Schema additions (idempotent) ────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,
    file_hash       TEXT,
    bank            TEXT,
    document        TEXT,
    statement_type  TEXT,
    accounts        TEXT,            -- Hub account names, '; ' separated
    period_from     TEXT,
    period_to       TEXT,
    statement_date  TEXT,
    due_date        TEXT,
    total_due       REAL DEFAULT 0,
    minimum_due     REAL DEFAULT 0,
    opening_balance REAL DEFAULT 0,
    closing_balance REAL DEFAULT 0,
    credit_limit    REAL DEFAULT 0,
    txn_count       INTEGER DEFAULT 0,
    txn_imported    INTEGER DEFAULT 0,
    check_status    TEXT,            -- OK / MISMATCH / n/a
    check_detail    TEXT,            -- JSON (Accounts sheet rows)
    reader_version  TEXT,
    imported_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stmt_hash ON statements(file_hash);
"""
NEW_COLUMNS = {
    'transactions': [('statement_id', 'INTEGER'), ('reference', 'TEXT'), ('narration', 'TEXT'),
                     ('reward_pts', 'REAL')],
    'loans': [('loan_ref', 'TEXT'), ('outstanding', 'REAL DEFAULT 0'), ('last_statement_date', 'TEXT'),
              ('source', "TEXT DEFAULT 'manual'"), ('repayment', "TEXT DEFAULT 'monthly'")],
}


def ensure_schema(db_path):
    import dbconn
    with dbconn.connect(db_path) as con:
        con.executescript(SCHEMA)
        for table, cols in NEW_COLUMNS.items():
            have = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
            for name, decl in cols:
                if name not in have:
                    con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
        con.execute('CREATE INDEX IF NOT EXISTS idx_txn_stmt ON transactions(statement_id)')
        con.commit()
        classifier.ensure_schema(con)
        if con.execute('SELECT COUNT(*) FROM transactions WHERE category_id IS NULL').fetchone()[0]:
            classifier.apply_to_rows(con, only_unclassified=True)


# ── Helpers ──────────────────────────────────────────────────────────────────
BANK_CODES = [  # order matters: 'state bank of india' contains 'bank of india'
    ('sbi card', 'sbi'), ('state bank', 'sbi'), ('sbi', 'sbi'), ('hdfc', 'hdfc'), ('icici', 'icici'),
    ('axis', 'axis'), ('south indian', 'sib'), ('sib', 'sib'), ('standard chartered', 'sc'),
    ('stanchart', 'sc'), ('baroda', 'bob'), ('bob', 'bob'), ('central bank', 'cbi'), ('cbi', 'cbi'),
    ('bank of india', 'boi'), ('boi', 'boi'),
]
BANK_SHORT = {'sbi': 'SBI', 'hdfc': 'HDFC', 'icici': 'ICICI', 'axis': 'Axis', 'sib': 'SIB',
              'sc': 'StanChart', 'bob': 'BOB', 'cbi': 'CBI', 'boi': 'BOI'}
STOP = {'credit', 'card', 'cc', 'bank', 'account', 'a', 'c', 'ac', 'statement', 'of', 'the', 'ltd',
        'mastercard', 'visa', 'retail', 'india', 'limited', 'all', 'accounts', 'consolidated'}
BANK_WORDS = {'hdfc', 'sbi', 'icici', 'axis', 'sib', 'stanchart', 'standard', 'chartered', 'bob',
              'baroda', 'cbi', 'central', 'boi', 'state', 'south', 'indian', 'one'}


def bank_code(text: str) -> str:
    t = (text or '').lower()
    for k, v in BANK_CODES:
        if k in t:
            return v
    return ''


def _digits(s):
    return re.sub(r'\D', '', str(s or ''))


def _last4(s):
    d = _digits(s)
    return d[-4:] if len(d) >= 4 else ''


def _tokens(name: str) -> set:
    words = [w for w in re.findall(r'[a-z0-9]+', (name or '').lower())]
    toks = {w for w in words if w not in STOP and not w.isdigit()}
    toks |= {a + b for a, b in zip(words, words[1:])}          # 'biz power' → 'bizpower'
    return toks


def hub_type(statement_type: str, acct_type: str = '') -> str:
    t = (acct_type or statement_type or '').lower()
    if 'loan' in t or t == 'overdraft':
        return 'loan'
    if 'savings' in t or 'current' in t or 'consolidated' in t:
        return 'savings'
    return 'credit_card'


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def find_password(path: str, saved: list) -> tuple:
    """→ (password, label) ; ('', 'not protected') ; (None, None) when nothing works."""
    if not needs_password(path):
        return '', 'not protected'
    for label, pw in saved:
        if pw and check_password(path, pw):
            return pw, label
    return None, None


# Engine categories → Hub categories (Hub's own rules are tried first for merchants)
ENGINE_TO_HUB = {
    'payment': 'Payment/Reward', 'refund': 'Payment/Reward', 'refund (fuel surcharge)': 'Payment/Reward',
    'refund (surcharge/reversal)': 'Payment/Reward', 'repayments': 'Payment/Reward', 'interest': 'Payment/Reward',
    'emi': 'EMI/Loan', 'emi payment': 'EMI/Loan', 'loan interest': 'EMI/Loan', 'emi / loan transfer': 'EMI/Loan',
    'emi / auto-debit': 'EMI/Loan', 'emi schedule (paid)': 'EMI/Loan', 'emi schedule (planned)': 'EMI/Loan',
    'disbursement / debit': 'EMI/Loan', 'credit card payment': 'Fund Transfer',
    'fees & taxes': 'Charges & Tax', 'bank charges': 'Charges & Tax', 'bank charges (reversal)': 'Charges & Tax',
    'cash withdrawal': 'Cash', 'upi': 'Fund Transfer', 'transfer': 'Fund Transfer', 'own-account transfer': 'Fund Transfer',
    'dividend': 'Investment', 'dividend / ach credit': 'Investment', 'insurance / pension scheme': 'Insurance',
    'insurance': 'Insurance', 'medical': 'Healthcare', 'health & wellness': 'Healthcare', 'travel': 'Travel',
    'food & dining': 'Food & Dining', 'groceries': 'Food & Dining', 'fuel': 'Transport', 'transport': 'Transport',
    'entertainment': 'Subscriptions', 'shopping': 'Shopping', 'cloth stores': 'Shopping', 'dept stores': 'Shopping',
    'retail stores': 'Shopping', 'electronics': 'Shopping', 'bills and utilities': 'Utilities', 'education': 'Education',
    'transfers': 'Fund Transfer',
}
STRUCTURAL = {'payment', 'refund', 'refund (fuel surcharge)', 'refund (surcharge/reversal)', 'repayments', 'emi',
              'emi payment', 'loan interest', 'fees & taxes', 'bank charges', 'bank charges (reversal)',
              'cash withdrawal', 'interest', 'credit card payment', 'emi / loan transfer', 'dividend',
              'emi schedule (paid)', 'emi schedule (planned)', 'disbursement / debit'}


def book_for_holder(con, text: str) -> str:
    """'ABC PRIVATE LIMITED' → 'ABC' when that book lists the name among its aliases."""
    t = re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower())
    try:
        rows = con.execute("SELECT name, COALESCE(aliases,'') FROM entities WHERE COALESCE(role,'book')='book' "
                           "AND name<>'Personal'").fetchall()
    except Exception:  # noqa: BLE001
        return ''
    for name, aliases in rows:
        for al in [name] + [x.strip() for x in aliases.split(',') if x.strip()]:
            a = re.sub(r'[^a-z0-9 ]', ' ', al.lower()).strip()
            if len(a) >= 4 and re.search(r'\b' + re.escape(a) + r'\b', t):
                return name
    return ''


def hub_category(engine_cat: str, desc: str, categorize) -> str:
    c = (engine_cat or '').strip().lower()
    if c in STRUCTURAL:
        return ENGINE_TO_HUB.get(c, 'Others')
    hub = categorize(desc)
    if hub != 'Others':
        return hub
    return ENGINE_TO_HUB.get(c, 'Others')


# ── Account matching ─────────────────────────────────────────────────────────
def resolve_account(accounts: list, bank: str, a_type: str, numbers: list, hint: str) -> dict:
    """accounts: rows (id, name, card_no, bank, type). Returns {'name', 'existing', 'how', ...}."""
    code = bank_code(bank) or bank_code(hint)
    l4s = {x for x in (_last4(n) for n in numbers) if x}
    # 1) last 4 digits of card / account number
    hits = [a for a in accounts if _last4(a['card_no']) and _last4(a['card_no']) in l4s
            and (not code or bank_code(a['bank'] + ' ' + a['name']) in (code, ''))]
    if len(hits) == 1:
        return {'name': hits[0]['name'], 'existing': True, 'how': f"number …{_last4(hits[0]['card_no'])}"}
    # 2) distinctive name words (e.g. 'aurum', 'bizpower', 'tataneu', 'sapphiro')
    ht = _tokens(hint)
    best, best_score = None, 0
    for a in accounts:
        if code and bank_code(a['bank'] + ' ' + a['name']) != code:
            continue
        if a['type'] and hub_type(a['type']) != a_type:
            continue
        common = ht & _tokens(a['name'])
        distinctive = {w for w in common if w not in BANK_WORDS and w not in {'savings', 'loan', 'home'}}
        score = len(common) + 2 * len(distinctive)
        if distinctive and score > best_score:
            best, best_score = a, score
    if best:
        return {'name': best['name'], 'existing': True, 'how': 'name'}
    # 3) the only account of this bank and type
    same = [a for a in accounts if code and bank_code(a['bank'] + ' ' + a['name']) == code
            and hub_type(a['type']) == a_type
            # a different, known card/account number means it is a different account
            and not (_last4(a['card_no']) and l4s and _last4(a['card_no']) not in l4s)]
    if len(same) == 1 and (a_type != 'loan'):
        return {'name': same[0]['name'], 'existing': True, 'how': 'only account of this bank & type',
                'fill_number': next(iter(l4s), '') if not _digits(same[0]['card_no']) else ''}
    # 4) new account
    short = BANK_SHORT.get(code, bank.split()[0] if bank else 'Bank')
    label = {'credit_card': 'Card', 'savings': 'Savings', 'loan': 'Loan'}[a_type]
    clean_hint = re.sub(r'\s+', ' ', hint or '').strip()
    if clean_hint and a_type == 'credit_card' and not clean_hint.lower().startswith('statement'):
        name = clean_hint
    else:
        name = f'{short} {label}'
    l4 = next(iter(sorted(l4s)), '')
    if l4 and l4 not in name:
        name = f'{name} {l4}'
    return {'name': name, 'existing': False, 'how': 'new account',
            'card_no': next((n for n in numbers if _digits(n)), ''), 'bank': bank, 'type': a_type}


# ── Loans ────────────────────────────────────────────────────────────────────
def loan_key(lender: str, ref: str) -> str:
    code = bank_code(lender) or 'x'
    ref = (ref or '').strip()
    if re.fullmatch(r'[Xx*\d\s-]+', ref) and _last4(ref):
        return f'{code}:{_last4(ref)}'
    return f'{code}:{ref.lower()}'


# ── Preview ──────────────────────────────────────────────────────────────────
def _pending_dir(upload_dir: Path) -> Path:
    d = Path(upload_dir) / '.pending'
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(fileobj, filename: str, upload_dir: Path) -> tuple:
    from werkzeug.utils import secure_filename
    token = uuid.uuid4().hex[:12]
    path = Path(upload_dir) / f'{token}_{secure_filename(filename) or "statement"}'
    fileobj.save(str(path))
    return token, path


def preview_file(con, path: Path, original_name: str, token: str, upload_dir: Path,
                 password: str = None, categorize=None) -> dict:
    """Parse and build a preview. `con` is a sqlite3 connection with row_factory=Row."""
    ext = path.suffix.lower()
    pv = {'token': token, 'file': original_name, 'path': str(path), 'ext': ext,
          'engine_version': ENGINE_VERSION, 'status': 'ok', 'warnings': []}
    pv['file_hash'] = file_sha256(path)

    # ---- duplicate statement by file content
    dup = con.execute('SELECT id, file_name, imported_at FROM statements WHERE file_hash=?',
                      (pv['file_hash'],)).fetchone()

    if ext == '.pdf':
        if password is None:
            saved = [(r['label'], r['password']) for r in con.execute('SELECT label, password FROM passwords')]
            pw, label = find_password(str(path), saved)
            if pw is None:
                pv.update(status='needs_password', msg='None of the saved passwords opens this PDF.')
                _store(pv, upload_dir)
                return pv
        else:
            if needs_password(str(path)) and not check_password(str(path), password):
                pv.update(status='needs_password', msg='That password did not open the file.')
                _store(pv, upload_dir)
                return pv
            pw, label = password, 'typed'
        pv['password_label'] = label
        pv['_password'] = pw
        try:
            parser = auto_detect_parser(str(path), pw)
            data = parser.parse(str(path), pw)
        except Exception as e:  # noqa: BLE001
            pv.update(status='error', msg=f'Could not read this PDF: {e}')
            _store(pv, upload_dir)
            return pv
        pv['parser'] = type(parser).__name__.replace('Parser', '')
        pv['generic'] = type(parser).__name__ == 'GenericParser'
        if label != 'typed' and pw:
            same = [r['label'] for r in con.execute('SELECT label, password FROM passwords') if r['password'] == pw]
            want = _tokens(f'{data.bank} {data.card_name} {data.statement_type}')
            if same:
                pv['password_label'] = max(same, key=lambda lb: len(_tokens(lb) & want))
        _from_engine(con, pv, data, categorize)
    else:
        from parsers import auto_parse
        try:
            rows = auto_parse(str(path))
        except Exception as e:  # noqa: BLE001
            pv.update(status='error', msg=f'Could not read this file: {e}')
            _store(pv, upload_dir)
            return pv
        _from_tabular(con, pv, rows, categorize)

    if not pv.get('txns') and not pv.get('loans'):
        pv.update(status='error', msg='No transactions or loan details were found in this file.')

    if dup:
        pv['duplicate_statement'] = {'id': dup['id'], 'file': dup['file_name'], 'imported_at': dup['imported_at']}
    else:
        # same accounts + same period already imported (e.g. the same statement downloaded twice)
        if pv.get('period_from') and pv.get('accounts_key'):
            d2 = con.execute('SELECT id, file_name, imported_at FROM statements WHERE accounts=? AND period_from=? '
                             'AND period_to=? AND COALESCE(statement_date,"")=?',
                             (pv['accounts_key'], pv['period_from'], pv['period_to'],
                              pv.get('statement_date') or '')).fetchone()
            if d2:
                pv['duplicate_statement'] = {'id': d2['id'], 'file': d2['file_name'], 'imported_at': d2['imported_at']}
    # rows imported earlier from this same file by the old (pre-engine) reader → replaced on import
    from werkzeug.utils import secure_filename
    names = {original_name, secure_filename(original_name)}
    old = [r[0] for r in con.execute(
        f"SELECT id FROM transactions WHERE statement_id IS NULL AND source_file IN ({','.join('?' * len(names))})",
        tuple(names))]
    pv['replace_old_ids'] = old
    if old:
        pv['warnings'].append(f'{len(old)} rows imported earlier from this file by the old reader '
                              f'will be replaced by the verified rows.')
    _mark_duplicate_txns(con, pv)
    if pv.get('generic') and pv['status'] == 'ok':
        pv['warnings'].append('No dedicated reader for this bank / card yet — read with the generic reader. Check the rows '
                              'and balances; to add this bank see statement_reader\\parsers\\README.md.')
    pv['default_selected'] = (pv['status'] == 'ok' and not pv.get('duplicate_statement')
                              and (not pv.get('generic') or pv.get('check_status') == 'OK')
                              and pv.get('check_status') != 'MISMATCH'
                              and (pv['counts']['new'] > 0 or any(l['action'] != 'none' for l in pv.get('loans', []))))
    _store(pv, upload_dir)
    return pv


def _from_engine(con, pv, data, categorize):
    accounts = [dict(r) for r in con.execute("SELECT id, name, card_no, bank, type FROM accounts "
                                          "WHERE COALESCE(type,'') IN ('', 'credit_card', 'savings', 'current', 'loan')")]
    multi = len(data.accounts) > 1
    pv.update({
        'bank': data.bank, 'document': data.card_name, 'statement_type': data.statement_type,
        'period_from': data.from_date or '', 'period_to': data.to_date or '',
        'statement_date': data.statement_date or '', 'due_date': data.due_date or '',
        'total_due': data.total_due or 0, 'minimum_due': data.minimum_due or 0,
        'opening_balance': data.opening_balance or 0, 'closing_balance': data.closing_balance or 0,
        'credit_limit': data.credit_limit or 0,
        'checks': data.accounts,
    })
    checks = [a.get('Check') for a in data.accounts]
    pv['check_status'] = ('n/a' if not checks else ('OK' if all(c == 'OK' for c in checks) else 'MISMATCH'))
    if pv['check_status'] == 'MISMATCH':
        pv['warnings'].append('Balances do not reconcile — review before importing.')

    # ---- map statement accounts → Hub accounts
    mapping = {}            # txn label (or '') → resolution
    if multi:
        for a in data.accounts:
            a_type = hub_type('', a.get('Type', ''))
            label = f"{a.get('Type')} {str(a.get('Account'))[-4:]}"
            hint = f"{data.bank} {a.get('Type')}"
            mapping[label] = resolve_account(accounts, data.bank, a_type, [a.get('Account')], hint)
    elif data.statement_type == 'emi_letter':
        numbers = [data.card_number]
        res = resolve_account(accounts, data.bank, 'credit_card', numbers, data.card_name)
        if not res['existing']:
            # a loan letter must not create an account: keep the card number on the loan;
            # the card's own statement links it to the right account later
            res = {'name': f"{BANK_SHORT.get(bank_code(data.bank), data.bank)} card …{_last4(data.card_number)}",
                   'existing': False, 'how': 'loan letter — card not linked yet', 'no_account': True}
        mapping[''] = res
    else:
        a_type = hub_type(data.statement_type)
        numbers = [data.card_number, data.account_number]
        numbers += [t.cardholder for t in data.transactions if re.search(r'\d{4}$', t.cardholder or '')]
        if data.accounts:
            numbers.append(data.accounts[0].get('Account'))
        mapping[''] = resolve_account(accounts, data.bank, a_type, numbers, data.card_name)
    # 1.2: current accounts keep their type; a company account holder puts the account in that company's book
    book = book_for_holder(con, ' '.join(str(a.get('Holder', '')) for a in data.accounts) + ' ' + (data.card_name or ''))
    for v in mapping.values():
        if not v.get('existing') and v.get('how') == 'new account':
            if data.statement_type == 'current':
                v['type'] = 'current'
                v['name'] = v['name'].replace(' Savings', ' Current')
            if book:
                v['book'] = book
                if not v['name'].startswith(book):
                    v['name'] = f"{book} {v['name']}"
    if book:
        pv['book'] = book
    pv['account_map'] = [{'label': k or data.card_name, **v} for k, v in mapping.items()]
    pv['accounts_key'] = '; '.join(sorted({v['name'] for v in mapping.values()}))

    txns = []
    for t in data.transactions:
        label = (t.cardholder or '') if multi else ''
        res = mapping.get(label) or next(iter(mapping.values()))
        holder = '' if multi or re.fullmatch(r'(Savings|Current|Loan|Card|Credit card) \d{4}', t.cardholder or '') \
            else (t.cardholder or '')
        planned = (t.category or '').lower() == 'emi schedule (planned)'
        txns.append({'date': t.date, 'description': t.description, 'amount': round(t.amount, 2),
                     'type': t.txn_type, 'category': hub_category(t.category, t.description, categorize),
                     'engine_category': t.category, 'account': res['name'], 'cardholder': holder,
                     'reference': t.reference or '', 'narration': getattr(t, 'narration', '') or '',
                     'reward_pts': t.reward_pts or 0, 'skip': planned,
                     'skip_reason': 'future EMI instalment (schedule)' if planned else ''})
    if data.statement_type == 'emi_letter':
        # an EMI letter's schedule is not account activity — the card statement carries the real rows
        for x in txns:
            x['skip'], x['skip_reason'] = True, 'EMI schedule from a letter (not a transaction)'
    pv['txns'] = txns

    # ---- loans plan
    loans = []
    card_account = next(iter(mapping.values()))['name']
    for e in data.emis:
        key = loan_key(e.lender or data.bank, e.ref)
        if not e.ref:
            continue
        row = con.execute('SELECT * FROM loans WHERE loan_ref=?', (key,)).fetchone()
        paid = max((e.tenure_months or 0) - (e.months_remaining or 0), 0)
        bullet = 'BOB Loan' in e.description or (e.tenure_months == 1)
        acct = card_account
        if multi:
            l4 = _last4(e.ref)
            acct = next((v['name'] for k, v in mapping.items() if k.endswith(l4)), card_account)
        plan = {'key': key, 'ref': e.ref, 'lender': e.lender or data.bank, 'description': e.description,
                'account': acct, 'emi_amount': round(e.emi_amount or 0, 2), 'total_emis': e.tenure_months or 0,
                'emis_paid': paid, 'remaining': e.months_remaining or 0,
                'original_amount': round(e.original_amount or 0, 2), 'outstanding': round(e.outstanding or 0, 2),
                'rate_pa': e.rate_pa or 0, 'start_date': e.start_date or '', 'end_date': e.end_date or '',
                'repayment': 'bullet' if bullet else 'monthly',
                'as_of': data.statement_date or data.to_date or ''}
        if row is None:
            plan['action'] = 'create'
        else:
            newer = not row['last_statement_date'] or plan['as_of'] >= (row['last_statement_date'] or '')
            changes = []
            if newer and row['emis_paid'] != paid:
                changes.append(f"EMIs paid {row['emis_paid']} → {paid}")
            if newer and plan['outstanding'] and abs((row['outstanding'] or 0) - plan['outstanding']) > 0.5:
                changes.append(f"outstanding {row['outstanding'] or 0:,.0f} → {plan['outstanding']:,.0f}")
            fills = [f for f, v in (('original_amount', plan['original_amount']), ('interest_rate', plan['rate_pa']))
                     if v and not row[f]]
            if fills:
                changes.append('fills ' + ', '.join(fills))
            plan['action'] = 'update' if changes else 'none'
            plan['changes'] = changes
            plan['loan_id'] = row['id']
            plan['newer'] = newer
        loans.append(plan)
    pv['loans'] = loans


def _from_tabular(con, pv, rows, categorize):
    accounts = [dict(r) for r in con.execute("SELECT id, name, card_no, bank, type FROM accounts "
                                          "WHERE COALESCE(type,'') IN ('', 'credit_card', 'savings', 'current', 'loan')")]
    names = {a['name'] for a in accounts}
    txns = []
    for t in rows:
        acct = t.get('account', '') or 'Unassigned'
        txns.append({'date': t.get('date', ''), 'description': t.get('description', ''),
                     'amount': round(float(t.get('amount', 0) or 0), 2), 'type': t.get('type', 'debit'),
                     'category': t.get('category') or categorize(t.get('description', '')),
                     'engine_category': '', 'account': acct, 'cardholder': t.get('cardholder', ''),
                     'reference': '', 'narration': '', 'reward_pts': 0, 'skip': False, 'skip_reason': ''})
    dates = sorted(x['date'] for x in txns if x['date'])
    accts = sorted({x['account'] for x in txns})
    pv.update({'parser': 'Spreadsheet/CSV importer', 'bank': '', 'document': ', '.join(accts),
               'statement_type': 'spreadsheet', 'period_from': dates[0] if dates else '',
               'period_to': dates[-1] if dates else '', 'statement_date': dates[-1] if dates else '',
               'check_status': 'n/a', 'checks': [], 'txns': txns, 'loans': [],
               'account_map': [{'label': a, 'name': a, 'existing': a in names, 'how': 'from file'} for a in accts],
               'accounts_key': '; '.join(accts)})
    pv['warnings'].append('Spreadsheet/CSV files carry no printed balances, so no balance check is possible.')


def _mark_duplicate_txns(con, pv):
    """Rows already in the Hub (same account, date, amount, type) are flagged, counting
    multiplicity — two identical ₹231 rows in the file vs one in the Hub → one is new."""
    txns = pv.get('txns', [])
    by_acct = defaultdict(list)
    for x in txns:
        if not x['skip']:
            by_acct[x['account']].append(x)
    for acct, rows in by_acct.items():
        skip_ids = set(pv.get('replace_old_ids') or [])
        have = Counter((r['date'], round(r['amount'], 2), r['type']) for r in con.execute(
            'SELECT id, date, amount, type FROM transactions WHERE account=?', (acct,)) if r['id'] not in skip_ids)
        for x in rows:
            k = (x['date'], round(x['amount'], 2), x['type'])
            if have[k] > 0:
                have[k] -= 1
                x['skip'], x['skip_reason'] = True, 'already in Hub'
    new = [x for x in txns if not x['skip']]
    pv['counts'] = {'rows': len(txns), 'new': len(new), 'replaced': len(pv.get('replace_old_ids') or []),
                    'already': sum(1 for x in txns if x['skip_reason'] == 'already in Hub'),
                    'schedule': sum(1 for x in txns if x['skip'] and x['skip_reason'] != 'already in Hub'),
                    'debits': round(sum(x['amount'] for x in txns if x['type'] == 'debit' and not x['skip_reason'].startswith(('EMI sched', 'future'))), 2),
                    'credits': round(sum(x['amount'] for x in txns if x['type'] == 'credit' and not x['skip_reason'].startswith(('EMI sched', 'future'))), 2)}


def _store(pv, upload_dir):
    import dbconn
    dbconn.write_sealed(_pending_dir(upload_dir) / f"{pv['token']}.json", pv)


def load_pending(token: str, upload_dir: Path) -> dict:
    if not re.fullmatch(r'[0-9a-f]{12}', token or ''):
        return None
    p = _pending_dir(upload_dir) / f'{token}.json'
    import dbconn
    return dbconn.read_sealed(p) if p.exists() else None


def public_view(pv: dict, max_rows: int = 400) -> dict:
    """What the browser receives (no file path, no password)."""
    out = {k: v for k, v in pv.items() if k not in ('path', '_password')}
    out['txns'] = pv.get('txns', [])[:max_rows]
    out['txns_truncated'] = max(0, len(pv.get('txns', [])) - max_rows)
    return out


# ── Commit ───────────────────────────────────────────────────────────────────
def commit_preview(con, pv: dict) -> dict:
    """Write one previewed statement. Re-checks duplicates at commit time."""
    if pv.get('status') != 'ok':
        return {'file': pv['file'], 'ok': False, 'msg': pv.get('msg', 'not importable')}
    if con.execute('SELECT 1 FROM statements WHERE file_hash=?', (pv['file_hash'],)).fetchone():
        return {'file': pv['file'], 'ok': False, 'msg': 'already imported (same file)'}
    _mark_duplicate_txns(con, pv)          # someone may have imported overlapping rows meanwhile
    cur = con.cursor()
    try:
        # accounts
        created = []
        for m in pv.get('account_map', []):
            if m.get('no_account'):
                continue
            if not m.get('existing') and m.get('how') == 'new account':
                cur.execute('INSERT OR IGNORE INTO accounts (name, card_no, bank, type, credit_limit, notes, entity) '
                            'VALUES (?,?,?,?,?,?,?)',
                            (m['name'], m.get('card_no', ''), m.get('bank', pv.get('bank', '')), m.get('type', 'savings'),
                             pv.get('credit_limit', 0) if m.get('type') == 'credit_card' else 0,
                             f"Created from {pv['file']}", m.get('book') or None))
                if cur.rowcount:
                    created.append(m['name'])
            elif m.get('fill_number'):
                cur.execute("UPDATE accounts SET card_no=? WHERE name=? AND COALESCE(card_no,'')=''",
                            (m['fill_number'], m['name']))
        # remove rows the old reader imported from this file
        old_ids = pv.get('replace_old_ids') or []
        if old_ids:
            cur.execute(f"DELETE FROM transactions WHERE statement_id IS NULL AND id IN ({','.join('?' * len(old_ids))})",
                        tuple(old_ids))
        # statement
        new_rows = [x for x in pv.get('txns', []) if not x['skip']]
        cur.execute('''INSERT INTO statements (file_name, file_hash, bank, document, statement_type, accounts,
                       period_from, period_to, statement_date, due_date, total_due, minimum_due, opening_balance,
                       closing_balance, credit_limit, txn_count, txn_imported, check_status, check_detail,
                       reader_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (pv['file'], pv['file_hash'], pv.get('bank', ''), pv.get('document', ''),
                     pv.get('statement_type', ''), pv.get('accounts_key', ''), pv.get('period_from', ''),
                     pv.get('period_to', ''), pv.get('statement_date', ''), pv.get('due_date', ''),
                     pv.get('total_due', 0), pv.get('minimum_due', 0), pv.get('opening_balance', 0),
                     pv.get('closing_balance', 0), pv.get('credit_limit', 0), len(pv.get('txns', [])),
                     len(new_rows), pv.get('check_status', 'n/a'), json.dumps(pv.get('checks', []), default=str),
                     pv.get('engine_version', '')))
        sid = cur.lastrowid
        cur.executemany('''INSERT INTO transactions (date, description, amount, type, category, account,
                           cardholder, source_file, statement_id, reference, narration, reward_pts)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                        [(x['date'], x['description'], x['amount'], x['type'], x['category'], x['account'],
                          x['cardholder'], pv['file'], sid, x['reference'], x['narration'], x['reward_pts'])
                         for x in new_rows])
        classifier.apply_to_rows(con, 'statement_id=? AND COALESCE(manual,0)=0', (sid,), commit=False)
        # 1.2: rows of a business account belong to that book (entity), whatever the payee rule says
        cur.execute("UPDATE transactions SET entity=(SELECT a.entity FROM accounts a WHERE a.name=transactions.account) "
                    "WHERE statement_id=? AND COALESCE(manual,0)=0 AND EXISTS (SELECT 1 FROM accounts a WHERE "
                    "a.name=transactions.account AND COALESCE(a.entity,'') NOT IN ('', 'Personal'))", (sid,))
        # loans
        loan_msgs = []
        for l in pv.get('loans', []):
            row = cur.execute('SELECT * FROM loans WHERE loan_ref=?', (l['key'],)).fetchone()
            status = 'paid' if l['remaining'] == 0 and not l['outstanding'] else 'active'
            if row is None:
                name = _loan_name(l)
                cur.execute('''INSERT INTO loans (name, lender, card, purchase_desc, purchase_date, original_amount,
                               emi_amount, total_emis, emis_paid, first_emi_date, last_emi_date, interest_rate,
                               status, notes, loan_ref, outstanding, last_statement_date, source, repayment)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (name, l['lender'], l['account'], l['description'], l['start_date'],
                             l['original_amount'], l['emi_amount'], l['total_emis'], l['emis_paid'], l['start_date'],
                             l['end_date'], l['rate_pa'], status, f"From {pv['file']}", l['key'], l['outstanding'],
                             l['as_of'], 'statement', l['repayment']))
                loan_msgs.append(f'created {name}')
            else:
                newer = not row['last_statement_date'] or l['as_of'] >= row['last_statement_date']
                sets, vals = [], []
                if newer:
                    sets += ['emis_paid=?', 'total_emis=?', 'last_statement_date=?', 'status=?']
                    vals += [l['emis_paid'], l['total_emis'] or row['total_emis'], l['as_of'], status]
                    if l['outstanding'] or status == 'paid':
                        sets.append('outstanding=?'); vals.append(l['outstanding'])
                    if l['emi_amount']:
                        sets.append('emi_amount=?'); vals.append(l['emi_amount'])
                if l['account'] and (not row['card'] or ' card …' in (row['card'] or '')) and ' card …' not in l['account']:
                    sets.append('card=?'); vals.append(l['account'])
                for col, v in (('original_amount', l['original_amount']), ('interest_rate', l['rate_pa']),
                               ('purchase_date', l['start_date']), ('first_emi_date', l['start_date']),
                               ('last_emi_date', l['end_date'])):
                    if v and not row[col]:
                        sets.append(f'{col}=?'); vals.append(v)
                if sets:
                    cur.execute(f"UPDATE loans SET {', '.join(sets)} WHERE id=?", (*vals, row['id']))
                    loan_msgs.append(f"updated {row['name']}")
        con.commit()
    except Exception as e:  # noqa: BLE001
        con.rollback()
        return {'file': pv['file'], 'ok': False, 'msg': f'import failed, nothing saved: {e}'}
    msg = f"{len(new_rows)} transactions imported"
    skipped = len(pv.get('txns', [])) - len(new_rows)
    if skipped:
        msg += f", {skipped} skipped (already in Hub / EMI schedule)"
    if old_ids:
        msg += f"; replaced {len(old_ids)} rows from the old reader"
    if created:
        msg += f"; new account: {', '.join(created)}"
    if loan_msgs:
        msg += '; loans: ' + ', '.join(loan_msgs)
    discard_upload(pv)          # 1.2: the uploaded copy of the statement is erased once its data is in the encrypted DB
    return {'file': pv['file'], 'ok': True, 'msg': msg, 'statement_id': sid, 'imported': len(new_rows)}


def discard_upload(pv):
    import vault
    for f in (pv.get('path'), Path(pv['path']).parent / '.pending' / f"{pv.get('token', '')}.json" if pv.get('path') else None):
        try:
            if f and Path(f).exists():
                vault.secure_delete(Path(f))
        except Exception:  # noqa: BLE001
            pass


def _loan_name(l: dict) -> str:
    acct = l.get('account') or ''
    if 'loan' in acct.lower() and not re.search(r'\bloan \d{4}$', acct.lower()):
        return acct                                   # e.g. existing 'SBI Home Loan'
    code = bank_code(l['lender'])
    short = BANK_SHORT.get(code, l['lender'].split()[0] if l['lender'] else '')
    desc = l['description']
    m = re.search(r'—\s*(.+?)(?:\s*\(|$)', desc)
    merchant = m.group(1).strip() if m and not m.group(1).startswith(('sanctioned', 'instalment', '₹')) else ''
    ref = l['ref']
    tail = _last4(ref) if re.fullmatch(r'[Xx*\d\s-]+', ref or '') else ''
    if 'smartemi' in desc.lower():
        kind = 'SmartEMI'
    elif 'loan on card' in desc.lower():
        kind = 'Loan on Card'
    elif 'merchant emi' in desc.lower():
        kind = 'Merchant EMI'
    elif re.search(r'home loan', desc, re.I):
        kind = 'Home Loan'
    elif re.search(r'auto loan|car loan', desc, re.I):
        kind = 'Auto Loan'
    elif re.search(r'education', desc, re.I):
        kind = 'Education Loan'
    elif re.search(r'card emi|emi ref', desc, re.I) or l['account'].lower().endswith(('cc', 'card')):
        kind = 'Card EMI'
    else:
        kind = 'Loan'
    name = f'{short} {kind}'
    if tail:
        name += f' {tail}'
    if merchant:
        name += f' – {merchant[:28]}'
    return name


# ── Folder import (Reset & Reload) ───────────────────────────────────────────
def import_folder(db_path, folders: list, upload_dir: Path, categorize) -> dict:
    """Import every PDF / CSV / XLSX in the folders. Files that need a password nobody saved,
    don't reconcile, or are duplicates are skipped and listed."""
    import shutil
    res = {'imported': [], 'skipped': []}
    import dbconn
    con = dbconn.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        files = []
        for folder in folders:
            for p in sorted(Path(folder).rglob('*')):
                rel = p.relative_to(folder).parts[:-1]          # sub-folders below the statements folder
                if p.suffix.lower() in ('.pdf', '.csv', '.xlsx', '.xls') \
                        and not any(d.startswith(('_', '~', '.')) or d.lower() in ('output', 'backup') for d in rel):
                    files.append(p)                             # skips _to_delete, ~BROMIUM, output …
        for p in files:
            token = uuid.uuid4().hex[:12]
            dst = Path(upload_dir) / f'{token}_{p.name}'
            shutil.copy(p, dst)
            pv = preview_file(con, dst, p.name, token, upload_dir, categorize=categorize)
            if pv['status'] != 'ok' or pv.get('duplicate_statement') or pv.get('check_status') == 'MISMATCH':
                discard_upload({'path': str(dst), 'token': token})
            if pv['status'] != 'ok':
                res['skipped'].append({'file': p.name, 'why': pv.get('msg', pv['status'])})
            elif pv.get('duplicate_statement'):
                res['skipped'].append({'file': p.name, 'why': 'already imported'})
            elif pv.get('check_status') == 'MISMATCH':
                res['skipped'].append({'file': p.name, 'why': 'balances do not reconcile — import it from the Import page after review'})
            else:
                r = commit_preview(con, pv)
                (res['imported'] if r['ok'] else res['skipped']).append(
                    {'file': p.name, 'why': r['msg']} if not r['ok'] else r)
    finally:
        con.close()
    return res
