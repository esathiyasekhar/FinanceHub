"""Finance Hub v4 — organise money: 4-level categories, rename, rules, people, entities, breakdown.

Pages
  /transactions        list + filters + edit (rename / re-categorise / entity / person / notes) + bulk edit
  /breakdown           Type › Head › Sub-head › Item totals, by entity / person / month, drill-down, Excel export
  /categories          add / rename / move / delete headings
  /rules               the 'all from this payee' rules — edit, delete, re-apply
  /people              people (with name variants on statements) and entities (Personal, your companies, clients)
"""
import io
import re
from collections import defaultdict
from datetime import datetime, date

from flask import render_template, request, jsonify, redirect, url_for, flash, send_file, Response

import classifier as C

KIND_LABEL = {'income': 'Income', 'expense': 'Expenses', 'transfer': 'Transfers', 'investment': 'Investments'}
KIND_COLOR = {'income': '#4ade80', 'expense': '#f87171', 'transfer': '#94a3b8', 'investment': '#60a5fa'}


def _fy(today=None):
    today = today or date.today()
    y = today.year if today.month >= 4 else today.year - 1
    return f'{y}-04-01', f'{y + 1}-03-31', f'FY {str(y)[-2:]}-{str(y + 1)[-2:]}'


def period_presets(con):
    """Quick period buttons: this FY, last FY, all time, last 3 months with data."""
    s, e, lbl = _fy()
    ls, le, llbl = _fy(date(int(s[:4]) - 1, 6, 1))
    lo, hi = con.execute('SELECT MIN(date), MAX(date) FROM transactions').fetchone()
    out = [(lbl, s, e), (llbl, ls, le)]
    if lo:
        out.append(('All time', lo, hi))
        for (m,) in con.execute("SELECT DISTINCT substr(date,1,7) m FROM transactions ORDER BY m DESC LIMIT 4"):
            y, mo = int(m[:4]), int(m[5:7])
            end = f'{y + (mo == 12)}-{(mo % 12) + 1:02d}-01'
            last = (datetime.strptime(end, '%Y-%m-%d').date().toordinal() - 1)
            out.append((datetime.strptime(m, '%Y-%m').strftime('%b %Y'), f'{m}-01',
                        date.fromordinal(last).isoformat()))
    return out


def net_value(kind, debit, credit):
    """Expense / investment: money out (refunds reduce it). Income: money in. Transfers: in − out."""
    if kind in ('expense', 'investment'):
        return debit - credit
    return credit - debit


class Filters:
    """Query-string filters shared by Transactions, Breakdown and the exports (all parameterised)."""

    def __init__(self, args, con, by_id, default_all=False):
        fs, fe, _ = _fy()
        if default_all:
            lo, hi = con.execute('SELECT MIN(date), MAX(date) FROM transactions').fetchone()
            fs, fe = lo or fs, hi or fe
        self.start = args.get('start') or fs
        self.end = args.get('end') or fe
        self.account = args.get('account', '')
        self.cat = args.get('cat', '')
        self.kind = args.get('kind', '')
        self.entity = args.get('entity', '')
        self.person = args.get('person', '')
        self.type = args.get('type', '')
        self.search = args.get('search', '').strip()
        self.review = args.get('review', '')
        self.payee = args.get('payee', '')
        self.by_id = by_id
        conds, params = ['t.date >= ?', 't.date <= ?'], [self.start, self.end]
        if self.account:
            conds.append('t.account = ?'); params.append(self.account)
        if self.cat and self.cat.isdigit() and int(self.cat) in by_id:
            ids = C.descendants(by_id, int(self.cat))
            conds.append(f"t.category_id IN ({','.join('?' * len(ids))})"); params += ids
        if self.kind:
            conds.append('c.kind = ?'); params.append(self.kind)
        if self.entity:
            conds.append("COALESCE(t.entity,'Personal') = ?"); params.append(self.entity)
        if self.person:
            conds.append("COALESCE(t.person,'Self') = ?"); params.append(self.person)
        if self.type:
            conds.append('t.type = ?'); params.append(self.type)
        if self.payee:
            conds.append('t.payee = ?'); params.append(self.payee)
        if self.review:
            conds.append("c.name = 'To review'")
        if self.search:
            like = f'%{self.search}%'
            conds.append("(t.description LIKE ? OR t.display_name LIKE ? OR t.payee LIKE ? OR t.narration LIKE ? "
                         "OR t.notes LIKE ? OR t.account LIKE ? OR CAST(t.amount AS TEXT) LIKE ?)")
            params += [like] * 7
        import scope as SC                       # 1.2: the top-bar "Viewing" filter (book / account)
        ssql, spar = SC.txn_sql('t')
        if spar:
            conds.append(ssql); params += spar
        self.where, self.params = ' AND '.join(conds), params

    def qs(self, **override):
        d = {k: getattr(self, k) for k in ('start', 'end', 'account', 'cat', 'kind', 'entity', 'person', 'type',
                                           'search', 'review', 'payee')}
        d.update(override)
        return {k: v for k, v in d.items() if v not in ('', None)}


FROM = 'FROM transactions t LEFT JOIN categories c ON c.id = t.category_id'


def _shown_name(r):
    return r['display_name'] or r['payee'] or r['description']


def _people(con):
    return [r[0] for r in con.execute('SELECT name FROM people ORDER BY (name<>"Self"), name')]


def _entities(con):
    return [r[0] for r in con.execute('SELECT name FROM entities ORDER BY sort_order, name')]


def register(app, get_db):
    """Attach all v4 routes to the Flask app (endpoint names are plain, e.g. url_for('breakdown'))."""

    def tree():
        roots, by_id = C.load_tree(get_db())
        return roots, by_id

    # ── Transactions ──────────────────────────────────────────────────────────
    def transactions():
        con = get_db()
        roots, by_id = tree()
        f = Filters(request.args, con, by_id)
        page = max(1, int(request.args.get('page', 1) or 1))
        per_page = 100
        total, s_debit, s_credit = con.execute(
            f"SELECT COUNT(*), COALESCE(SUM(CASE WHEN t.type='debit' THEN t.amount END),0), "
            f"COALESCE(SUM(CASE WHEN t.type='credit' THEN t.amount END),0) {FROM} WHERE {f.where}", f.params).fetchone()
        rows = con.execute(
            f"SELECT t.*, c.kind AS kind {FROM} WHERE {f.where} ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?",
            f.params + [per_page, (page - 1) * per_page]).fetchall()
        items = []
        for r in rows:
            node = by_id.get(r['category_id'])
            path = node['path'].split(' › ') if node else ['—']
            items.append({'id': r['id'], 'date': r['date'], 'name': _shown_name(r), 'description': r['description'],
                          'renamed': bool(r['display_name']), 'path': path, 'kind': r['kind'] or 'expense',
                          'entity': r['entity'] or 'Personal', 'person': r['person'] or 'Self',
                          'account': r['account'], 'amount': r['amount'], 'type': r['type'], 'notes': r['notes'] or '',
                          'manual': r['manual'], 'rule_id': r['rule_id'], 'review': bool(node and node['name'] == 'To review'),
                          'cardholder': r['cardholder'] or ''})
        accounts = [r[0] for r in con.execute('SELECT DISTINCT account FROM transactions ORDER BY account')]
        review_count = con.execute(f"SELECT COUNT(*) {FROM} WHERE c.name='To review'").fetchone()[0]
        pages = max(1, (total + per_page - 1) // per_page)
        return render_template('transactions.html', items=items, total=total, page=page, pages=pages,
                               s_debit=s_debit, s_credit=s_credit, f=f, qs=f.qs(), accounts=accounts,
                               cat_options=C.flat_options(roots), entities=_entities(con), people=_people(con),
                               review_count=review_count, presets=period_presets(con),
                               cat_name=(by_id[int(f.cat)]['path'] if f.cat.isdigit() and int(f.cat) in by_id else ''),
                               kind_label=KIND_LABEL, kind_color=KIND_COLOR)

    def export_csv():
        con = get_db()
        _, by_id = tree()
        f = Filters(request.args, con, by_id)
        rows = con.execute(f"SELECT t.* {FROM} WHERE {f.where} ORDER BY t.date DESC, t.id DESC", f.params).fetchall()

        def esc(v):
            v = '' if v is None else str(v)
            return '"' + v.replace('"', '""') + '"'

        def gen():
            yield '﻿Date,Name,Original description,Type,Head,Sub-head,Item,Entity,Person,Account,Debit,Credit,Notes\n'
            for r in rows:
                node = by_id.get(r['category_id'])
                p = (node['path'].split(' › ') if node else []) + ['', '', '', '']
                yield ','.join([r['date'], esc(_shown_name(r)), esc(r['description']), esc(p[0]), esc(p[1]), esc(p[2]),
                                esc(p[3]), esc(r['entity'] or 'Personal'), esc(r['person'] or 'Self'), esc(r['account']),
                                f"{r['amount']:.2f}" if r['type'] == 'debit' else '',
                                f"{r['amount']:.2f}" if r['type'] == 'credit' else '', esc(r['notes'])]) + '\n'
        return Response(gen(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment;filename=transactions.csv'})

    def api_txn(tid):
        con = get_db()
        _, by_id = tree()
        r = con.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'msg': 'not found'}), 404
        key = C.payee_key(r['description'])
        rule = con.execute('SELECT * FROM rules WHERE id=?', (r['rule_id'],)).fetchone() if r['rule_id'] else None
        node = by_id.get(r['category_id'])
        return jsonify({'ok': True, 'id': r['id'], 'date': r['date'], 'description': r['description'],
                        'narration': r['narration'] or '', 'amount': r['amount'], 'type': r['type'],
                        'account': r['account'], 'cardholder': r['cardholder'] or '',
                        'name': _shown_name(r), 'display_name': r['display_name'] or '', 'payee': r['payee'] or '',
                        'category_id': r['category_id'], 'path': node['path'] if node else '',
                        'entity': r['entity'] or 'Personal', 'person': r['person'] or 'Self', 'notes': r['notes'] or '',
                        'manual': r['manual'] or 0, 'payee_key': key,
                        'rule': dict(rule) if rule else None,
                        'payee_count': _count_matches(con, 'payee', key)})

    def _count_matches(con, match_type, pattern):
        pattern = (pattern or '').strip().upper()
        if not pattern:
            return 0
        rule = {'match_type': match_type, 'pattern': pattern}
        clf_match = C.Classifier.rule_matches
        n = 0
        for d, nar in con.execute('SELECT description, narration FROM transactions'):
            text = f"{d} {nar or ''}".upper().strip()
            if clf_match(None, rule, text, C.payee_key(d)):
                n += 1
        return n

    def api_rule_count():
        con = get_db()
        return jsonify({'count': _count_matches(con, request.args.get('match_type', 'contains'),
                                                request.args.get('pattern', ''))})

    def _ensure_person(con, name):
        name = (name or '').strip()
        if name and not con.execute('SELECT 1 FROM people WHERE name=?', (name,)).fetchone():
            con.execute('INSERT INTO people (name, aliases) VALUES (?, "")', (name,))
        return name

    def _ensure_entity(con, name):
        name = (name or '').strip()
        if name and not con.execute('SELECT 1 FROM entities WHERE name=?', (name,)).fetchone():
            con.execute('INSERT INTO entities (name, sort_order) VALUES (?, 50)', (name,))
        return name

    def _new_child(con, parent_id, name):
        p = con.execute('SELECT id, level, kind FROM categories WHERE id=?', (parent_id,)).fetchone()
        if not p:
            raise ValueError('choose a heading first')
        if p['level'] >= 4:
            raise ValueError('an Item cannot have children (4 levels maximum) — pick its Sub-head instead')
        return C._ins(con, p['id'], name.strip(), p['level'] + 1, p['kind'], 99)

    def api_txn_save(tid):
        con = get_db()
        d = request.get_json(force=True) or {}
        r = con.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'msg': 'transaction not found'}), 404
        scope = d.get('scope')
        if scope not in ('one', 'payee'):
            return jsonify({'ok': False, 'msg': 'Choose: only this transaction, or all from this payee'}), 400
        try:
            cid = int(d.get('category_id') or r['category_id'])
            if (d.get('new_item') or '').strip():
                cid = _new_child(con, cid, d['new_item'])
        except ValueError as e:
            return jsonify({'ok': False, 'msg': str(e)}), 400
        name = (d.get('display_name') or '').strip()
        if name and name == (r['payee'] or ''):
            name = ''                      # unchanged automatic name — don't store as a rename
        entity = _ensure_entity(con, d.get('entity') or 'Personal')
        person = _ensure_person(con, d.get('person') or 'Self')
        notes = (d.get('notes') or '').strip()
        head = C.head_name(con, cid)
        if scope == 'one':
            con.execute('UPDATE transactions SET display_name=?, category_id=?, category=?, entity=?, person=?, '
                        'notes=?, manual=1, rule_id=NULL WHERE id=?',
                        (name or None, cid, head, entity, person, notes or None, tid))
            con.commit()
            return jsonify({'ok': True, 'msg': 'Saved (this transaction only).', 'updated': 1})
        # all from this payee — a rule, applied to past rows now and to future imports
        match_type = 'payee' if d.get('match_type') == 'payee' else 'contains'
        pattern = (d.get('pattern') or '').strip().upper()
        if match_type == 'payee' and not pattern:
            pattern = C.payee_key(r['description'])
        if len(pattern) < 3:
            return jsonify({'ok': False, 'msg': 'The text to match is too short (3 letters minimum).'}), 400
        row = con.execute('SELECT id FROM rules WHERE pattern=? AND match_type=?', (pattern, match_type)).fetchone()
        vals = (name or None, cid, entity, person if d.get('set_person') else None)
        if row:
            rid = row['id']
            con.execute('UPDATE rules SET display_name=?, category_id=?, entity=?, person=? WHERE id=?', (*vals, rid))
        else:
            rid = con.execute('INSERT INTO rules (pattern, match_type, display_name, category_id, entity, person) '
                              'VALUES (?,?,?,?,?,?)', (pattern, match_type, *vals)).lastrowid
        con.execute('UPDATE transactions SET manual=0, notes=? WHERE id=?', (notes or None, tid))
        if d.get('override_manual'):
            clf = C.Classifier(con)
            rule = next(x for x in clf.rules if x['id'] == rid)
            for t in con.execute('SELECT id, description, narration FROM transactions WHERE manual=1').fetchall():
                if clf.rule_matches(rule, f"{t['description']} {t['narration'] or ''}".upper().strip(),
                                    C.payee_key(t['description'])):
                    con.execute('UPDATE transactions SET manual=0 WHERE id=?', (t['id'],))
        C.apply_to_rows(con, commit=False)
        con.commit()
        n = con.execute('SELECT COUNT(*) FROM transactions WHERE rule_id=?', (rid,)).fetchone()[0]
        return jsonify({'ok': True, 'updated': n,
                        'msg': f'Rule saved — {n} transaction(s) updated; future imports from this payee will follow it.'})

    def api_bulk():
        con = get_db()
        d = request.get_json(force=True) or {}
        ids = [int(i) for i in d.get('ids', []) if str(i).isdigit()]
        if not ids:
            return jsonify({'ok': False, 'msg': 'nothing selected'}), 400
        sets, vals = ['manual=1'], []
        if d.get('category_id'):
            cid = int(d['category_id'])
            sets += ['category_id=?', 'category=?', 'rule_id=NULL']; vals += [cid, C.head_name(con, cid)]
        if d.get('entity'):
            sets.append('entity=?'); vals.append(_ensure_entity(con, d['entity']))
        if d.get('person'):
            sets.append('person=?'); vals.append(_ensure_person(con, d['person']))
        if len(sets) == 1:
            return jsonify({'ok': False, 'msg': 'choose a category, entity or person to set'}), 400
        con.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id IN ({','.join('?' * len(ids))})", vals + ids)
        con.commit()
        return jsonify({'ok': True, 'msg': f'{len(ids)} transactions updated.'})

    def api_txn_reset(tid):
        """Undo hand edits on one row: back to automatic (rules)."""
        con = get_db()
        con.execute('UPDATE transactions SET manual=0, display_name=NULL WHERE id=?', (tid,))
        C.apply_to_rows(con, 'id=?', (tid,))
        return jsonify({'ok': True, 'msg': 'Back to automatic.'})

    # ── Breakdown ─────────────────────────────────────────────────────────────
    def _aggregate(con, f, by_id):
        rows = con.execute(f"SELECT t.category_id, t.type, t.amount, substr(t.date,1,7) AS m, "
                           f"COALESCE(t.entity,'Personal') AS entity, COALESCE(t.person,'Self') AS person, t.account "
                           f"{FROM} WHERE {f.where}", f.params).fetchall()
        node = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0, 'n': 0})
        month = defaultdict(lambda: defaultdict(lambda: {'debit': 0.0, 'credit': 0.0}))
        dims = {k: defaultdict(lambda: defaultdict(lambda: {'debit': 0.0, 'credit': 0.0}))
                for k in ('entity', 'person', 'account')}
        months = set()
        for r in rows:
            cid = r['category_id']
            if cid not in by_id:
                continue
            kind = by_id[cid]['kind']
            months.add(r['m'])
            for dim in dims:
                dims[dim][r[dim]][kind][r['type']] += r['amount']
            c = cid
            while c:
                a = node[c]
                a[r['type']] += r['amount']; a['n'] += 1
                month[c][r['m']][r['type']] += r['amount']
                c = by_id[c]['parent_id']
        return node, month, dims, sorted(months)

    def breakdown():
        con = get_db()
        roots, by_id = tree()
        f = Filters(request.args, con, by_id)
        node, month, dims, months = _aggregate(con, f, by_id)
        lines = []

        def walk(n):
            a = node.get(n['id'])
            if not a:
                return
            lines.append({'id': n['id'], 'name': n['name'], 'level': n['level'], 'parent_id': n['parent_id'],
                          'kind': n['kind'], 'n': a['n'], 'debit': a['debit'], 'credit': a['credit'],
                          'net': net_value(n['kind'], a['debit'], a['credit']),
                          'has_children': any(node.get(ch['id']) for ch in n['children'])})
            for ch in sorted(n['children'], key=lambda x: -abs(net_value(x['kind'], node[x['id']]['debit'],
                                                                         node[x['id']]['credit']))
                             if node.get(x['id']) else 0):
                walk(ch)
        for r in roots:
            walk(r)
        totals = {k: 0.0 for k in KIND_LABEL}
        for r in roots:
            if node.get(r['id']):
                totals[r['kind']] = net_value(r['kind'], node[r['id']]['debit'], node[r['id']]['credit'])
        type_total = {r['id']: abs(totals[r['kind']]) or 1 for r in roots}
        root_of = {}
        for ln in lines:
            root_of[ln['id']] = ln['id'] if ln['level'] == 1 else root_of.get(ln['parent_id'])
            ln['pct'] = 100 * ln['net'] / type_total.get(root_of[ln['id']], 1) if ln['level'] > 1 else 100

        def dim_table(dim):
            out = []
            for name, kinds in dims[dim].items():
                inc = net_value('income', kinds['income']['debit'], kinds['income']['credit'])
                exp = net_value('expense', kinds['expense']['debit'], kinds['expense']['credit'])
                inv = net_value('investment', kinds['investment']['debit'], kinds['investment']['credit'])
                out.append({'name': name, 'income': inc, 'expense': exp, 'investment': inv})
            return sorted(out, key=lambda x: -(x['expense'] + x['income']))

        # monthly matrix
        mkind = request.args.get('mkind', 'expense')
        mlevel = int(request.args.get('mlevel', 2) or 2)
        matrix = []
        for nid, n in by_id.items():
            if n['kind'] == mkind and n['level'] == mlevel and node.get(nid):
                vals = [net_value(mkind, month[nid][m]['debit'], month[nid][m]['credit']) for m in months]
                matrix.append({'id': nid, 'name': n['name'], 'path': n['short_path'], 'vals': vals, 'total': sum(vals)})
        matrix.sort(key=lambda x: -x['total'])
        mtot = [sum(r['vals'][i] for r in matrix) for i in range(len(months))]
        review = con.execute(f"SELECT COUNT(*), COALESCE(SUM(t.amount),0) {FROM} WHERE {f.where} AND c.name='To review'",
                             f.params).fetchone()
        accounts = [r[0] for r in con.execute('SELECT DISTINCT account FROM transactions ORDER BY account')]
        return render_template('breakdown.html', f=f, qs=f.qs(), lines=lines, totals=totals,
                               depth=int(request.args.get('depth', 2) or 2),
                               entities_t=dim_table('entity'), people_t=dim_table('person'),
                               accounts_t=dim_table('account'), months=months, matrix=matrix, mtot=mtot,
                               mkind=mkind, mlevel=mlevel, review=review, presets=period_presets(con),
                               entities=_entities(con), people=_people(con), accounts=accounts,
                               kind_label=KIND_LABEL, kind_color=KIND_COLOR,
                               cat_name=(by_id[int(f.cat)]['path'] if f.cat.isdigit() and int(f.cat) in by_id else ''))

    def breakdown_export():
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        con = get_db()
        roots, by_id = tree()
        f = Filters(request.args, con, by_id)
        node, month, dims, months = _aggregate(con, f, by_id)
        wb = Workbook()
        hdr_fill, hdr_font = PatternFill('solid', fgColor='1E293B'), Font(bold=True, color='FFFFFF')
        lvl_font = {1: Font(bold=True, size=12), 2: Font(bold=True), 3: Font(italic=True), 4: Font()}
        money = '#,##0.00;[Red]-#,##0.00'

        def header(ws, cols, widths):
            ws.append(cols)
            for i, w in enumerate(widths, 1):
                ws.cell(1, i).fill, ws.cell(1, i).font = hdr_fill, hdr_font
                ws.column_dimensions[get_column_letter(i)].width = w
            ws.freeze_panes = 'A2'

        ws = wb.active
        ws.title = 'Breakdown'
        header(ws, ['Type', 'Head', 'Sub-head', 'Item', 'Transactions', 'Money out', 'Money in', 'Net'],
               [14, 26, 28, 30, 13, 15, 15, 15])

        def walk(n):
            a = node.get(n['id'])
            if not a:
                return
            p = n['path'].split(' › ')
            ws.append([*(p + [''] * 4)[:4], a['n'], round(a['debit'], 2), round(a['credit'], 2),
                       round(net_value(n['kind'], a['debit'], a['credit']), 2)])
            for c in ws[ws.max_row]:
                c.font = lvl_font[n['level']]
            for col in (6, 7, 8):
                ws.cell(ws.max_row, col).number_format = money
            for ch in n['children']:
                walk(ch)
        for r in roots:
            walk(r)
        ws.append([])
        ws.append([f'Period {f.start} to {f.end}' + (f' · entity {f.entity}' if f.entity else '') +
                   (f' · person {f.person}' if f.person else '') + (f' · {f.account}' if f.account else '')])
        ws.append(['Net: expenses & investments = money out − refunds; income = money in − reversals; '
                   'transfers (card bills, own accounts, loan principal, ATM) are not income or expense.'])

        for kind in ('expense', 'income'):
            wm = wb.create_sheet(f'Monthly {KIND_LABEL[kind]}')
            header(wm, ['Head', 'Sub-head'] + [datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in months] + ['Total'],
                   [26, 28] + [12] * len(months) + [14])
            for nid, n in sorted(by_id.items(), key=lambda x: x[1]['path']):
                if n['kind'] == kind and n['level'] in (2, 3) and node.get(nid):
                    vals = [round(net_value(kind, month[nid][m]['debit'], month[nid][m]['credit']), 2) for m in months]
                    p = n['path'].split(' › ')
                    wm.append([p[1], p[2] if n['level'] == 3 else ''] + vals + [round(sum(vals), 2)])
                    for c in wm[wm.max_row]:
                        if n['level'] == 2:
                            c.font = Font(bold=True)
                        if isinstance(c.value, float):
                            c.number_format = money

        wd = wb.create_sheet('By entity & person')
        header(wd, ['Group', 'Name', 'Income', 'Expenses', 'Investments'], [12, 28, 15, 15, 15])
        for dim in ('entity', 'person', 'account'):
            for name, kinds in sorted(dims[dim].items()):
                wd.append([dim.title(), name,
                           round(net_value('income', kinds['income']['debit'], kinds['income']['credit']), 2),
                           round(net_value('expense', kinds['expense']['debit'], kinds['expense']['credit']), 2),
                           round(net_value('investment', kinds['investment']['debit'], kinds['investment']['credit']), 2)])
                for col in (3, 4, 5):
                    wd.cell(wd.max_row, col).number_format = money

        wt = wb.create_sheet('Transactions')
        header(wt, ['Date', 'Name', 'Original description', 'Type', 'Head', 'Sub-head', 'Item', 'Entity', 'Person',
                    'Account', 'Money out', 'Money in', 'Notes'], [11, 32, 46, 12, 22, 24, 26, 13, 13, 22, 13, 13, 30])
        for r in con.execute(f"SELECT t.* {FROM} WHERE {f.where} ORDER BY t.date, t.id", f.params):
            n = by_id.get(r['category_id'])
            p = (n['path'].split(' › ') if n else []) + [''] * 4
            wt.append([r['date'], _shown_name(r), r['description'], *p[:4], r['entity'] or 'Personal',
                       r['person'] or 'Self', r['account'], r['amount'] if r['type'] == 'debit' else None,
                       r['amount'] if r['type'] == 'credit' else None, r['notes'] or ''])
            for col in (11, 12):
                wt.cell(wt.max_row, col).number_format = money
        wt.auto_filter.ref = wt.dimensions
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=f'Breakdown_{f.start}_to_{f.end}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── Categories ────────────────────────────────────────────────────────────
    def categories():
        con = get_db()
        roots, by_id = tree()
        import scope as SC
        ssql, spar = SC.txn_sql('t')
        direct = dict(con.execute(f'SELECT category_id, COUNT(*) FROM transactions t WHERE {ssql} GROUP BY category_id', spar).fetchall())
        rules = dict(con.execute('SELECT category_id, COUNT(*) FROM rules GROUP BY category_id').fetchall())
        total = {}

        def count(n):
            total[n['id']] = direct.get(n['id'], 0) + sum(count(ch) for ch in n['children'])
            return total[n['id']]
        for r in roots:
            count(r)
        flat = C.flat_options(roots)
        for o in flat:
            o['n'], o['direct'], o['rules'] = total.get(o['id'], 0), direct.get(o['id'], 0), rules.get(o['id'], 0)
            o['name'] = by_id[o['id']]['name']
            o['parent_id'] = by_id[o['id']]['parent_id']
            o['has_children'] = bool(by_id[o['id']]['children'])
        return render_template('categories.html', flat=flat, kind_label=KIND_LABEL, kind_color=KIND_COLOR)

    def cat_add():
        con = get_db()
        try:
            _new_child(con, int(request.form['parent_id']), request.form['name'])
            con.commit()
            flash(f"Added “{request.form['name'].strip()}”.", 'success')
        except (ValueError, KeyError) as e:
            flash(f'Not added: {e}', 'warning')
        return redirect(url_for('categories') + f"#c{request.form.get('parent_id', '')}")

    def cat_rename(cid):
        con = get_db()
        name = request.form.get('name', '').strip()
        n = con.execute('SELECT parent_id, level FROM categories WHERE id=?', (cid,)).fetchone()
        if not name or not n:
            flash('Name required.', 'warning')
        elif n['level'] == 1:
            flash('The four Types (Income, Expenses, Transfers, Investments) cannot be renamed.', 'warning')
        elif con.execute('SELECT 1 FROM categories WHERE parent_id IS ? AND name=? AND id<>?',
                         (n['parent_id'], name, cid)).fetchone():
            flash('A heading with that name already exists at this place.', 'warning')
        else:
            con.execute('UPDATE categories SET name=? WHERE id=?', (name, cid))
            _refresh_heads(con)
            con.commit()
            flash(f'Renamed to “{name}”.', 'success')
        return redirect(url_for('categories') + f'#c{cid}')

    def _refresh_heads(con):
        _, by_id = C.load_tree(con)
        for cid, n in by_id.items():
            p = n['path'].split(' › ')
            if len(p) >= 2:
                con.execute('UPDATE transactions SET category=? WHERE category_id=?', (p[1], cid))

    def cat_move(cid):
        con = get_db()
        _, by_id = C.load_tree(con)
        try:
            new_parent = int(request.form['parent_id'])
        except (KeyError, ValueError):
            flash('Choose where to move it.', 'warning')
            return redirect(url_for('categories'))
        n, p = by_id.get(cid), by_id.get(new_parent)
        if not n or not p or n['level'] == 1:
            flash('Cannot move that.', 'warning')
            return redirect(url_for('categories'))
        sub = C.descendants(by_id, cid)
        depth = max(by_id[s]['level'] for s in sub) - n['level']
        if new_parent in sub:
            flash('Cannot move a heading inside itself.', 'warning')
        elif p['level'] + 1 + depth > 4:
            flash('That would make more than 4 levels — move it higher up, or move its children first.', 'warning')
        elif con.execute('SELECT 1 FROM categories WHERE parent_id=? AND name=?', (new_parent, n['name'])).fetchone():
            flash(f"“{p['name']}” already has a “{n['name']}”.", 'warning')
        else:
            shift = p['level'] + 1 - n['level']
            con.execute('UPDATE categories SET parent_id=? WHERE id=?', (new_parent, cid))
            con.execute(f"UPDATE categories SET level=level+?, kind=? WHERE id IN ({','.join('?' * len(sub))})",
                        (shift, p['kind'], *sub))
            _refresh_heads(con)
            con.commit()
            flash(f"Moved “{n['name']}” under {p['path']}.", 'success')
        return redirect(url_for('categories') + f'#c{cid}')

    def cat_delete(cid):
        con = get_db()
        _, by_id = C.load_tree(con)
        n = by_id.get(cid)
        try:
            target = int(request.form.get('target_id') or 0)
        except ValueError:
            target = 0
        sub = C.descendants(by_id, cid) if n else []
        if not n or n['level'] == 1:
            flash('The four Types cannot be deleted.', 'warning')
        elif target in sub or target not in by_id:
            flash('Choose where its transactions should go (outside the heading being deleted).', 'warning')
        else:
            ph = ','.join('?' * len(sub))
            moved = con.execute(f'UPDATE transactions SET category_id=? WHERE category_id IN ({ph})', (target, *sub)).rowcount
            con.execute(f'UPDATE rules SET category_id=? WHERE category_id IN ({ph})', (target, *sub))
            con.execute(f'DELETE FROM categories WHERE id IN ({ph})', sub)
            _refresh_heads(con)
            con.commit()
            flash(f"Deleted “{n['name']}”" + (f' and {len(sub) - 1} sub-heading(s)' if len(sub) > 1 else '') +
                  f"; {moved} transaction(s) moved to {by_id[target]['path']}.", 'success')
        return redirect(url_for('categories'))

    # ── Rules ─────────────────────────────────────────────────────────────────
    def rules_page():
        con = get_db()
        roots, by_id = tree()
        counts = dict(con.execute('SELECT rule_id, COUNT(*) FROM transactions WHERE rule_id IS NOT NULL GROUP BY rule_id'))
        rules = []
        for r in con.execute('SELECT * FROM rules ORDER BY created_at DESC, id DESC'):
            d = dict(r)
            d['path'] = by_id[r['category_id']]['path'] if r['category_id'] in by_id else '—'
            d['n'] = counts.get(r['id'], 0)
            rules.append(d)
        manual = con.execute('SELECT COUNT(*) FROM transactions WHERE manual=1').fetchone()[0]
        return render_template('rules.html', rules=rules, cat_options=C.flat_options(roots),
                               entities=_entities(con), people=_people(con), manual=manual)

    def rule_update(rid):
        con = get_db()
        fm = request.form
        pattern = fm.get('pattern', '').strip().upper()
        if len(pattern) < 3:
            flash('Match text must be at least 3 letters.', 'warning')
            return redirect(url_for('rules_page'))
        try:
            con.execute('UPDATE rules SET pattern=?, match_type=?, display_name=?, category_id=?, entity=?, person=? '
                        'WHERE id=?', (pattern, 'payee' if fm.get('match_type') == 'payee' else 'contains',
                                       fm.get('display_name', '').strip() or None, int(fm['category_id']),
                                       _ensure_entity(con, fm.get('entity')) or None,
                                       _ensure_person(con, fm.get('person')) or None, rid))
        except Exception as e:  # noqa: BLE001 — e.g. duplicate pattern
            flash(f'Not saved: {e}', 'warning')
            return redirect(url_for('rules_page'))
        C.apply_to_rows(con)
        flash('Rule saved and re-applied.', 'success')
        return redirect(url_for('rules_page'))

    def rule_delete(rid):
        con = get_db()
        con.execute('DELETE FROM rules WHERE id=?', (rid,))
        con.execute('UPDATE transactions SET rule_id=NULL WHERE rule_id=?', (rid,))
        C.apply_to_rows(con)
        flash('Rule deleted — those transactions are back to automatic categories.', 'success')
        return redirect(url_for('rules_page'))

    def rules_reapply():
        con = get_db()
        if request.form.get('include_manual'):
            # 1.6: rows owned by confirmed transfers, refunds, reimbursements and loans with people keep their categories
            keep = []
            for q in ("SELECT out_id FROM txn_links WHERE status='confirmed' UNION SELECT in_id FROM txn_links WHERE status='confirmed'",
                      "SELECT debit_id FROM txn_refunds WHERE status IN ('confirmed','received') UNION "
                      "SELECT credit_id FROM txn_refunds WHERE status IN ('confirmed','received')",
                      'SELECT id FROM transactions WHERE reimb_payer IS NOT NULL', 'SELECT txn_id FROM pl_moves'):
                try:
                    keep += [r[0] for r in con.execute(q) if r[0]]
                except Exception:  # noqa: BLE001  (feature tables not created yet)
                    pass
            con.execute('CREATE TEMP TABLE IF NOT EXISTS _keep (id INTEGER PRIMARY KEY)')
            con.execute('DELETE FROM _keep')
            con.executemany('INSERT OR IGNORE INTO _keep VALUES (?)', [(i,) for i in keep])
            con.execute('UPDATE transactions SET manual=0 WHERE id NOT IN (SELECT id FROM _keep)')
        n = C.apply_to_rows(con)
        flash(f'Re-applied rules to {n} transactions' +
              (' (hand edits were reset).' if request.form.get('include_manual') else ' (hand-edited ones kept).'),
              'success')
        return redirect(url_for('rules_page'))

    # ── People & entities ─────────────────────────────────────────────────────
    def people_page():
        con = get_db()
        pc = dict(con.execute("SELECT COALESCE(person,'Self'), COUNT(*) FROM transactions GROUP BY 1"))
        ec = dict(con.execute("SELECT COALESCE(entity,'Personal'), COUNT(*) FROM transactions GROUP BY 1"))
        people = [dict(r, n=pc.get(r['name'], 0)) for r in con.execute('SELECT * FROM people ORDER BY (name<>"Self"), name')]
        entities = [dict(r, n=ec.get(r['name'], 0)) for r in con.execute('SELECT * FROM entities ORDER BY sort_order, name')]
        holders = con.execute("SELECT cardholder, COUNT(*) n, MIN(COALESCE(person,'')) p FROM transactions "
                              "WHERE COALESCE(cardholder,'')<>'' GROUP BY cardholder ORDER BY n DESC").fetchall()
        return render_template('people.html', people=people, entities=entities, holders=holders)

    def person_save(pid=None):
        con = get_db()
        name = request.form.get('name', '').strip()
        aliases = ', '.join(a.strip() for a in request.form.get('aliases', '').split(',') if a.strip())
        if not name:
            flash('Name required.', 'warning')
            return redirect(url_for('people_page'))
        try:
            if pid:
                old = con.execute('SELECT name FROM people WHERE id=?', (pid,)).fetchone()['name']
                con.execute('UPDATE people SET name=?, aliases=? WHERE id=?', (name, aliases, pid))
                con.execute('UPDATE transactions SET person=? WHERE person=?', (name, old))
                con.execute('UPDATE rules SET person=? WHERE person=?', (name, old))
            else:
                con.execute('INSERT INTO people (name, aliases) VALUES (?,?)', (name, aliases))
        except Exception as e:  # noqa: BLE001
            flash(f'Not saved: {e}', 'warning')
            return redirect(url_for('people_page'))
        C.apply_to_rows(con)     # statement name variants → person
        flash(f'Saved {name}.', 'success')
        return redirect(url_for('people_page'))

    def person_delete(pid):
        con = get_db()
        r = con.execute('SELECT name FROM people WHERE id=?', (pid,)).fetchone()
        if r and r['name'] != 'Self':
            con.execute('DELETE FROM people WHERE id=?', (pid,))
            con.execute("UPDATE transactions SET person='Self' WHERE person=?", (r['name'],))
            con.execute('UPDATE rules SET person=NULL WHERE person=?', (r['name'],))
            C.apply_to_rows(con)
            flash(f"Removed {r['name']}; their transactions now show as Self (unless a statement name matches someone).",
                  'success')
        return redirect(url_for('people_page'))

    def entity_save(eid=None):
        con = get_db()
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name required.', 'warning')
            return redirect(url_for('people_page'))
        try:
            role = request.form.get('role') if request.form.get('role') in ('book', 'payer', 'other') else 'book'
            aliases = ', '.join(a.strip() for a in request.form.get('aliases', '').split(',') if a.strip())
            if eid:
                old = con.execute('SELECT name FROM entities WHERE id=?', (eid,)).fetchone()['name']
                con.execute('UPDATE entities SET name=?, role=?, aliases=? WHERE id=?', (name, role, aliases, eid))
                con.execute('UPDATE transactions SET entity=? WHERE entity=?', (name, old))
                con.execute('UPDATE rules SET entity=? WHERE entity=?', (name, old))
                con.execute('UPDATE accounts SET entity=? WHERE entity=?', (name, old))
            else:
                con.execute('INSERT INTO entities (name, sort_order, role, aliases) VALUES (?, 50, ?, ?)', (name, role, aliases))
            C.apply_to_rows(con, commit=False)      # names on statements → transfers / income recognised
            con.commit()
            flash(f'Saved {name}.', 'success')
        except Exception as e:  # noqa: BLE001
            flash(f'Not saved: {e}', 'warning')
        return redirect(url_for('people_page'))

    def entity_delete(eid):
        con = get_db()
        r = con.execute('SELECT name FROM entities WHERE id=?', (eid,)).fetchone()
        if r and r['name'] != 'Personal':
            con.execute('DELETE FROM entities WHERE id=?', (eid,))
            con.execute("UPDATE transactions SET entity='Personal' WHERE entity=?", (r['name'],))
            con.execute("UPDATE accounts SET entity=NULL WHERE entity=?", (r['name'],))
            con.execute('UPDATE rules SET entity=NULL WHERE entity=?', (r['name'],))
            con.commit()
            flash(f"Removed {r['name']}; its transactions are now Personal.", 'success')
        return redirect(url_for('people_page'))

    routes = [
        ('/transactions', 'transactions', transactions, ['GET']),
        ('/transactions/export', 'export_csv', export_csv, ['GET']),
        ('/api/txn/<int:tid>', 'api_txn', api_txn, ['GET']),
        ('/api/txn/<int:tid>/save', 'api_txn_save', api_txn_save, ['POST']),
        ('/api/txn/<int:tid>/reset', 'api_txn_reset', api_txn_reset, ['POST']),
        ('/api/txn/bulk', 'api_bulk', api_bulk, ['POST']),
        ('/api/rules/count', 'api_rule_count', api_rule_count, ['GET']),
        ('/breakdown', 'breakdown', breakdown, ['GET']),
        ('/breakdown/export', 'breakdown_export', breakdown_export, ['GET']),
        ('/categories', 'categories', categories, ['GET']),
        ('/categories/add', 'cat_add', cat_add, ['POST']),
        ('/categories/<int:cid>/rename', 'cat_rename', cat_rename, ['POST']),
        ('/categories/<int:cid>/move', 'cat_move', cat_move, ['POST']),
        ('/categories/<int:cid>/delete', 'cat_delete', cat_delete, ['POST']),
        ('/rules', 'rules_page', rules_page, ['GET']),
        ('/rules/<int:rid>/update', 'rule_update', rule_update, ['POST']),
        ('/rules/<int:rid>/delete', 'rule_delete', rule_delete, ['POST']),
        ('/rules/reapply', 'rules_reapply', rules_reapply, ['POST']),
        ('/people', 'people_page', people_page, ['GET']),
        ('/people/add', 'person_add', person_save, ['POST']),
        ('/people/<int:pid>/update', 'person_update', person_save, ['POST']),
        ('/people/<int:pid>/delete', 'person_delete', person_delete, ['POST']),
        ('/entities/add', 'entity_add', entity_save, ['POST']),
        ('/entities/<int:eid>/update', 'entity_update', entity_save, ['POST']),
        ('/entities/<int:eid>/delete', 'entity_delete', entity_delete, ['POST']),
    ]
    for rule, endpoint, fn, methods in routes:
        app.add_url_rule(rule, endpoint, fn, methods=methods)


# ── Dashboard numbers (used by app.dashboard) ───────────────────────────────
def dashboard_data(con, period_where: str, fy_where: str):
    """Real income / expense (transfers excluded), by Head, by account, top payees, monthly trend."""
    roots, by_id = C.load_tree(con)

    def head(cid):
        n = by_id.get(cid)
        while n and n['level'] > 2:
            n = by_id.get(n['parent_id'])
        return n['name'] if n else 'Uncategorised'

    import scope as SC
    sc = SC.txn_literal('t')
    rows = con.execute(f"SELECT t.*, c.kind AS kind {FROM} WHERE {period_where.replace('date', 't.date')} AND {sc} "
                       f"AND COALESCE(t.reimb_payer,'')=''").fetchall()
    tot = {k: 0.0 for k in KIND_LABEL}
    by_head, by_acct, by_payee = defaultdict(float), defaultdict(lambda: [0.0, 0]), defaultdict(float)
    review = 0
    for r in rows:
        k = r['kind'] or 'expense'
        sign = 1 if r['type'] == 'debit' else -1
        v = r['amount'] * (sign if k in ('expense', 'investment') else -sign)
        tot[k] += v
        if by_id.get(r['category_id'], {}).get('name') == 'To review':
            review += 1
        if k == 'expense':
            by_head[head(r['category_id'])] += v
            by_acct[r['account']][0] += v; by_acct[r['account']][1] += 1
            by_payee[_shown_name(r)] += v
    trend = defaultdict(lambda: {'income': 0.0, 'expense': 0.0})
    for m, kind, typ, amt in con.execute(
            f"SELECT substr(t.date,1,7), c.kind, t.type, SUM(t.amount) {FROM} "
            f"WHERE {fy_where.replace('date', 't.date')} AND {sc} AND COALESCE(t.reimb_payer,'')='' "
            f"AND c.kind IN ('income','expense') GROUP BY 1,2,3"):
        trend[m][kind] += net_value(kind, amt if typ == 'debit' else 0, amt if typ == 'credit' else 0)
    heads = sorted(((h, v) for h, v in by_head.items() if v > 0), key=lambda x: -x[1])
    if len(heads) > 9:
        heads = heads[:9] + [('Other heads', sum(v for _, v in heads[9:]))]
    recent = []
    for r in sorted(rows, key=lambda r: (r['date'], r['id']), reverse=True)[:15]:
        n = by_id.get(r['category_id'])
        recent.append((r['date'], _shown_name(r), r['amount'], r['type'],
                       ' › '.join(n['path'].split(' › ')[1:3]) if n else '', r['account'], r['kind'] or 'expense'))
    portfolio = None
    try:
        import investments as inv
        prow, psum, _ = inv.build_portfolio(con)
        if prow:
            portfolio = {'value': psum['total_value'], 'pnl': psum['pnl'], 'stocks': len(prow)}
    except Exception:  # noqa: BLE001 — Investments not used yet
        portfolio = None
    return {
        'portfolio': portfolio,
        'income': tot['income'], 'expense': tot['expense'], 'investment': tot['investment'],
        'saved': tot['income'] - tot['expense'], 'review': review, 'txn_count': len(rows),
        'heads': heads,
        'accounts': sorted(((a, v[0], v[1]) for a, v in by_acct.items()), key=lambda x: -x[1]),
        'payees': sorted(((p, v) for p, v in by_payee.items() if v > 0), key=lambda x: -x[1])[:8],
        'months': sorted(trend), 'trend': trend, 'recent': recent,
    }
