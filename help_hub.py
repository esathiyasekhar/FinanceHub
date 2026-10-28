"""Finance Hub 1.6 — the user manual inside the app, and the design manual for administrators.

Manual chapters are Markdown files in docs/user/ (NN-slug.md). A chapter can say which pages it explains:
    <!-- endpoints: import_page, mail_page -->
so the "?" button in the top bar opens the right chapter. The design manual is docs/design/DESIGN.md (administrators only).

A small Markdown reader is built in (headings, paragraphs, lists, tables, code, quotes, bold / italic / code / links) so the
manual needs no extra package; the same blocks are turned into HTML for the screen and into a PDF with reportlab.
Links of the form help:slug or help:slug#section point to another chapter.
"""
import html
import io
import re
from datetime import date
from pathlib import Path

from flask import render_template, request, redirect, url_for, send_file, abort, g

BASE = Path(__file__).resolve().parent
USER_DIR = BASE / 'docs' / 'user'
DESIGN = BASE / 'docs' / 'design' / 'DESIGN.md'


# ── Markdown → blocks ───────────────────────────────────────────────────────
def slugify(text):
    s = re.sub(r'[^\w\s-]', '', text.lower()).strip()
    return re.sub(r'[\s_]+', '-', s)[:60] or 'section'


def parse(md):
    """→ list of blocks: (kind, data). kinds: h (level, text, id) · p · ul / ol (items: [(level, text)]) · table (head, rows)
    · code · quote · hr"""
    lines = md.replace('\r\n', '\n').split('\n')
    blocks, i, seen = [], 0, {}
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if not st or (st.startswith('<!--') and st.endswith('-->')):
            i += 1
            continue
        if st.startswith('```'):
            j, buf = i + 1, []
            while j < len(lines) and not lines[j].strip().startswith('```'):
                buf.append(lines[j])
                j += 1
            blocks.append(('code', '\n'.join(buf)))
            i = j + 1
            continue
        m = re.match(r'^(#{1,4})\s+(.*)$', st)
        if m:
            text = m.group(2).strip()
            sid = slugify(text)
            seen[sid] = seen.get(sid, 0) + 1
            if seen[sid] > 1:
                sid = f'{sid}-{seen[sid]}'
            blocks.append(('h', (len(m.group(1)), text, sid)))
            i += 1
            continue
        if re.match(r'^(-{3,}|\*{3,})$', st):
            blocks.append(('hr', None))
            i += 1
            continue
        if st.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                    rows.append(cells)
                i += 1
            blocks.append(('table', (rows[0], rows[1:]) if rows else ([], [])))
            continue
        if st.startswith('>'):
            buf = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(('quote', ' '.join(buf)))
            continue
        lm = re.match(r'^(\s*)([-*]|\d+[.)])\s+(.*)$', ln)
        if lm:
            kind = 'ol' if lm.group(2)[0].isdigit() else 'ul'
            items = []
            while i < len(lines):
                m2 = re.match(r'^(\s*)([-*]|\d+[.)])\s+(.*)$', lines[i])
                if m2:
                    items.append([min(2, len(m2.group(1).replace('\t', '  ')) // 2), m2.group(3).strip()])
                elif lines[i].strip() and lines[i].startswith('  ') and items:
                    items[-1][1] += ' ' + lines[i].strip()          # continuation line
                else:
                    break
                i += 1
            blocks.append((kind, [tuple(x) for x in items]))
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,4}\s|```|\||>|\s*([-*]|\d+[.)])\s)', lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(('p', ' '.join(buf)))
    return blocks


def _link(url):
    if url.startswith('help:'):
        slug, _, anchor = url[5:].partition('#')
        return f'/help/{slug}' + (f'#{anchor}' if anchor else '')
    if url.startswith(('/', '#', 'https://')):
        return url
    return '#'


def inline(text):
    t = html.escape(text, quote=False)
    codes = []
    t = re.sub(r'`([^`]+)`', lambda m: codes.append(m.group(1)) or f'\x00{len(codes) - 1}\x00', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', lambda m: f'<a href="{html.escape(_link(m.group(2)))}">{m.group(1)}</a>', t)
    t = re.sub(r'\x00(\d+)\x00', lambda m: f'<code>{codes[int(m.group(1))]}</code>', t)
    return t


def to_html(blocks):
    out = []
    for kind, d in blocks:
        if kind == 'h':
            lvl, text, sid = d
            out.append(f'<h{lvl + 1} id="{sid}">{inline(text)}</h{lvl + 1}>' if lvl > 1 else '')
        elif kind == 'p':
            out.append(f'<p>{inline(d)}</p>')
        elif kind in ('ul', 'ol'):
            out.append(_list_html(kind, d))
        elif kind == 'table':
            head, rows = d
            out.append('<div class="table-responsive"><table class="table table-sm help-table"><thead><tr>' +
                       ''.join(f'<th>{inline(c)}</th>' for c in head) + '</tr></thead><tbody>' +
                       ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>' for r in rows) + '</tbody></table></div>')
        elif kind == 'code':
            out.append(f'<pre class="help-code">{html.escape(d)}</pre>')
        elif kind == 'quote':
            tip = re.match(r'^\*\*(Tip|Note|Important|Good to know|Warning)[:.]?\*\*\s*', d, re.I)
            cls = 'warn' if tip and tip.group(1).lower() in ('important', 'warning') else 'tip'
            out.append(f'<div class="help-callout {cls}">{inline(d)}</div>')
        elif kind == 'hr':
            out.append('<hr>')
    return '\n'.join(out)


def _list_html(kind, items):
    out, depth = [], -1
    for lvl, text in items:
        while depth < lvl:
            out.append(f'<{kind}>')
            depth += 1
        while depth > lvl:
            out.append(f'</{kind}>')
            depth -= 1
        out.append(f'<li>{inline(text)}</li>')
    while depth >= 0:
        out.append(f'</{kind}>')
        depth -= 1
    return ''.join(out)


def plain(text):
    t = re.sub(r'`([^`]+)`', r'\1', text)
    t = re.sub(r'\*\*(.+?)\*\*|\*(.+?)\*', lambda m: m.group(1) or m.group(2), t)
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)


# ── chapters ────────────────────────────────────────────────────────────────
_CACHE = {}


def chapters():
    files = sorted(USER_DIR.glob('*.md')) if USER_DIR.is_dir() else []
    key = tuple((f.name, f.stat().st_mtime) for f in files)
    if _CACHE.get('key') == key:
        return _CACHE['chapters']
    out = []
    for f in files:
        md = f.read_text(encoding='utf-8')
        slug = re.sub(r'^\d+[-_]', '', f.stem)
        eps = re.search(r'<!--\s*endpoints:\s*(.*?)-->', md, re.S)
        icon = re.search(r'<!--\s*icon:\s*(bi-[\w-]+)\s*-->', md)
        blocks = parse(md)
        title = next((d[1] for k, d in blocks if k == 'h' and d[0] == 1), slug.replace('-', ' ').title())
        intro = next((plain(d) for k, d in blocks if k == 'p'), '')
        sections = [(d[1], d[2]) for k, d in blocks if k == 'h' and d[0] == 2]
        out.append({'slug': slug, 'title': title, 'intro': intro, 'icon': icon.group(1) if icon else 'bi-book',
                    'endpoints': [e.strip() for e in (eps.group(1) if eps else '').split(',') if e.strip()],
                    'blocks': blocks, 'sections': sections, 'md': md})
    _CACHE.update(key=key, chapters=out)
    return out


def chapter_for(topic):
    ch = chapters()
    for c in ch:
        if c['slug'] == topic:
            return c, ''
    for c in ch:
        for e in c['endpoints']:
            ep, _, anchor = e.partition('#')
            if ep == topic:
                return c, anchor
    return None, ''


def search(q, limit=20):
    words = [w for w in re.findall(r'\w+', (q or '').lower()) if len(w) > 1]
    if not words:
        return []
    hits = []
    for c in chapters():
        cur_title, cur_id, buf = c['title'], '', []

        def flush():
            text = plain(' '.join(buf))
            low = (cur_title + ' ' + text).lower()
            score = sum(low.count(w) for w in words) + 5 * sum(w in cur_title.lower() for w in words)
            if score and all(w in low for w in words):
                pos = min((text.lower().find(w) for w in words if w in text.lower()), default=0)
                snippet = text[max(0, pos - 60): pos + 160]
                hits.append({'chapter': c['title'], 'slug': c['slug'], 'section': cur_title, 'id': cur_id,
                             'snippet': ('…' if pos > 60 else '') + snippet + '…', 'score': score})
        for kind, d in c['blocks']:
            if kind == 'h' and d[0] >= 2:
                flush()
                cur_title, cur_id, buf = d[1], d[2], []
            elif kind in ('p', 'quote', 'code'):
                buf.append(d)
            elif kind in ('ul', 'ol'):
                buf.extend(t for _, t in d)
            elif kind == 'table':
                buf.extend(' '.join(r) for r in [d[0]] + d[1])
        flush()
    hits.sort(key=lambda h: -h['score'])
    return hits[:limit]


# ── PDF ─────────────────────────────────────────────────────────────────────
def to_pdf(docs, title, subtitle):
    """docs: [(chapter title, blocks)] → BytesIO (A4 portrait, contents page, page numbers)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted,
                                    ListFlowable, ListItem, KeepTogether)
    ss = getSampleStyleSheet()
    base = ParagraphStyle('b', parent=ss['BodyText'], fontName='Helvetica', fontSize=9.5, leading=13.5, alignment=TA_LEFT,
                          spaceAfter=5)
    hs = {1: ParagraphStyle('h1', parent=base, fontName='Helvetica-Bold', fontSize=17, leading=21, spaceBefore=4, spaceAfter=10,
                            textColor=colors.HexColor('#3730a3')),
          2: ParagraphStyle('h2', parent=base, fontName='Helvetica-Bold', fontSize=12.5, leading=16, spaceBefore=10, spaceAfter=5,
                            textColor=colors.HexColor('#1e1b4b')),
          3: ParagraphStyle('h3', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=14, spaceBefore=7, spaceAfter=3),
          4: ParagraphStyle('h4', parent=base, fontName='Helvetica-BoldOblique', fontSize=9.5, leading=13, spaceBefore=5)}
    cell = ParagraphStyle('c', parent=base, fontSize=8.3, leading=10.5, spaceAfter=0)
    quote = ParagraphStyle('q', parent=base, backColor=colors.HexColor('#eef2ff'), borderPadding=6, leftIndent=6, rightIndent=6,
                           spaceBefore=4, spaceAfter=8)

    def rl(text):
        t = html.escape(plain_keep(text), quote=False)
        t = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', t)
        t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
        t = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', t)
        return t.replace('₹', 'Rs ').replace('→', '-&gt;').replace('›', '&gt;').replace('·', '-').replace('—', '-') \
            .replace('–', '-').replace('…', '...').replace('“', '"').replace('”', '"').replace('’', "'").replace('✓', 'ok')

    story = [Spacer(1, 50 * mm), Paragraph(title, ParagraphStyle('t', parent=hs[1], fontSize=26, leading=30)),
             Paragraph(subtitle, base), Spacer(1, 8 * mm), Paragraph('Contents', hs[2])]
    for n, (ct, _) in enumerate(docs, 1):
        story.append(Paragraph(f'{n}. {rl(ct)}', base))
    for ct, blocks in docs:
        story.append(PageBreak())
        for kind, d in blocks:
            if kind == 'h':
                story.append(Paragraph(rl(d[1]), hs[min(d[0], 4)]))
            elif kind == 'p':
                story.append(Paragraph(rl(d), base))
            elif kind in ('ul', 'ol'):
                items = [ListItem(Paragraph(rl(t), base), leftIndent=12 + 12 * lvl, value=None) for lvl, t in d]
                story.append(ListFlowable(items, bulletType='1' if kind == 'ol' else 'bullet', start='1' if kind == 'ol' else None,
                                          leftIndent=14, bulletFontSize=8))
            elif kind == 'table' and d[0]:
                head, rows = d
                n = len(head)
                data = [[Paragraph(f'<b>{rl(c)}</b>', cell) for c in head]] + \
                       [[Paragraph(rl(c), cell) for c in (r + [''] * n)[:n]] for r in rows]
                tb = Table(data, colWidths=[(170 * mm) / n] * n, repeatRows=1)
                tb.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#c7cbe0')),
                                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2ff')),
                                        ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
                story += [tb, Spacer(1, 6)]
            elif kind == 'code':
                story.append(Preformatted(d, ParagraphStyle('pre', parent=base, fontName='Courier', fontSize=7.8, leading=9.5,
                                                            backColor=colors.HexColor('#f4f5fa'), borderPadding=5)))
            elif kind == 'quote':
                story.append(Paragraph(rl(d), quote))

    def page(cv, doc):
        cv.saveState()
        cv.setFont('Helvetica', 7.5)
        cv.setFillColor(colors.HexColor('#69728f'))
        cv.drawString(20 * mm, 10 * mm, title)
        cv.drawRightString(190 * mm, 10 * mm, f'page {doc.page}')
        cv.restoreState()
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                      title=title, author='Finance Hub').build(story, onFirstPage=page, onLaterPages=page)
    buf.seek(0)
    return buf


def plain_keep(text):
    """Links → their text (PDF has no app links)."""
    return re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)


def manual_pdf(version):
    return to_pdf([(c['title'], c['blocks']) for c in chapters()], 'Finance Hub — User manual',
                  f'Version {version} · {date.today():%d %b %Y}')


def design_pdf(version):
    blocks = parse(DESIGN.read_text(encoding='utf-8')) if DESIGN.exists() else []
    parts, cur = [], None
    for b in blocks:                                  # one "chapter" per level-1 or level-2 heading for the contents page
        if b[0] == 'h' and b[1][0] <= 2:
            cur = (b[1][1], [b])
            parts.append(cur)
        elif cur:
            cur[1].append(b)
    return to_pdf(parts or [('Design manual', blocks)], 'Finance Hub — Design manual (internal)',
                  f'Version {version} · {date.today():%d %b %Y} · for maintainers only')


# ── pages ────────────────────────────────────────────────────────────────────
def register(app):
    from hub_version import VERSION

    @app.context_processor
    def _help_ctx():
        return {'help_topic': request.endpoint or 'index'}

    def _admin():
        return getattr(g, 'role', None) == 'admin'

    def help_page(topic='index'):
        ch = chapters()
        if topic in ('index', '', None):
            return render_template('help.html', ch=ch, c=None, body='', hits=None, q='', is_admin=_admin())
        c, anchor = chapter_for(topic)
        if not c:
            return redirect(url_for('help_page', topic='index'))
        if c['slug'] != topic:
            return redirect(url_for('help_page', topic=c['slug']) + (f'#{anchor}' if anchor else ''))
        i = ch.index(c)
        return render_template('help.html', ch=ch, c=c, body=to_html(c['blocks']), hits=None, q='', is_admin=_admin(),
                               prev=ch[i - 1] if i else None, nxt=ch[i + 1] if i + 1 < len(ch) else None)

    def help_search():
        q = request.args.get('q', '')
        return render_template('help.html', ch=chapters(), c=None, body='', hits=search(q), q=q, is_admin=_admin())

    def help_pdf():
        return send_file(manual_pdf(VERSION), mimetype='application/pdf', as_attachment=True,
                         download_name=f'FinanceHub_{VERSION}_User_manual.pdf')

    def help_design():
        if not _admin():
            abort(403)
        if not DESIGN.exists():
            abort(404)
        blocks = parse(DESIGN.read_text(encoding='utf-8'))
        toc = [(d[1], d[2]) for k, d in blocks if k == 'h' and d[0] == 2]
        title = next((d[1] for k, d in blocks if k == 'h' and d[0] == 1), 'Design manual')
        return render_template('help.html', ch=chapters(), c={'slug': 'design', 'title': title, 'sections': toc, 'icon': 'bi-diagram-3'},
                               body=to_html(blocks), hits=None, q='', is_admin=True, design=True)

    def help_design_pdf():
        if not _admin():
            abort(403)
        return send_file(design_pdf(VERSION), mimetype='application/pdf', as_attachment=True,
                         download_name=f'FinanceHub_{VERSION}_Design_manual.pdf')

    for rule, ep, fn in [('/help', 'help_page', help_page), ('/help/<topic>', 'help_page', help_page),
                         ('/help/find', 'help_search', help_search), ('/help/manual.pdf', 'help_pdf', help_pdf),
                         ('/help/internal/design', 'help_design', help_design),
                         ('/help/internal/design.pdf', 'help_design_pdf', help_design_pdf)]:
        app.add_url_rule(rule, ep, fn, methods=['GET'])
