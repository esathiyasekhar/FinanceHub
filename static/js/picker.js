/* Finance Hub 1.9 — type-to-search dropdown for long lists (categories).
   Any <select data-picker> becomes a button that opens a search box with the options below it.
   - type any part of a name or path ("fuel", "car fuel", "expenses transport") — every word must match;
   - ↑ ↓ to move, Enter to choose, Esc to close;
   - the original <select> stays in the page (hidden), keeps its name and value, and still fires "change";
   - setting select.value from code updates the button too;
   - data-picker-add="1": offers "Add “…” under <current choice>" when nothing matches (POST /categories/add). */
(function () {
  const css = `
  .pk{position:relative}
  .pk-btn{display:flex;align-items:center;gap:.4rem;width:100%;text-align:left;cursor:pointer;overflow:hidden}
  .pk-btn .pk-txt{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .pk-btn .pk-sub{color:var(--muted,#8a94a6);font-size:.72em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:45%}
  .pk-pan{position:absolute;z-index:1080;left:0;top:calc(100% + 2px);min-width:100%;width:max(100%,340px);max-width:min(520px,92vw);
    background:var(--navy2,var(--card,#fff));border:1px solid var(--border,#d0d5dd);border-radius:.6rem;box-shadow:0 10px 30px rgba(0,0,0,.25);padding:.4rem}
  .pk-list{max-height:300px;overflow:auto;margin-top:.35rem}
  .pk-it{padding:.28rem .5rem;border-radius:.4rem;cursor:pointer;font-size:.82rem;line-height:1.25}
  .pk-it .pk-p{display:block;color:var(--muted,#8a94a6);font-size:.7rem}
  .pk-it.on{background:var(--tint,rgba(99,102,241,.14))}
  .pk-it.dis{opacity:.4;cursor:not-allowed}
  .pk-it mark{padding:0;background:rgba(250,204,21,.45);color:inherit;border-radius:2px}
  .pk-none{padding:.4rem .5rem;font-size:.8rem;color:var(--muted,#8a94a6)}
  .pk-add{margin-top:.3rem;border-top:1px solid var(--border,#d0d5dd);padding-top:.3rem}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const esc = t => String(t).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const proto = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  // highlight on the plain text in one pass, then escape each piece (no tags inside tags, no broken entities)
  function hl(text, words) {
    const ws = [...new Set(words)].filter(Boolean).sort((a, b) => b.length - a.length);
    if (!ws.length) return esc(text);
    const re = new RegExp(ws.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'ig');
    let out = '', last = 0, m;
    while ((m = re.exec(text)) !== null) {
      if (!m[0]) { re.lastIndex++; continue; }
      out += esc(text.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>'; last = m.index + m[0].length;
    }
    return out + esc(text.slice(last));
  }

  function info(o) {
    const path = o.dataset.path || o.textContent.trim();
    const parts = path.split(' › ');
    return {value: o.value, name: parts[parts.length - 1] || o.textContent.trim(), path, under: parts.slice(0, -1).join(' › '),
            disabled: o.disabled, hay: (path + ' ' + o.textContent).toLowerCase()};
  }

  function enhance(sel) {
    if (sel.dataset.pkDone) return;
    sel.dataset.pkDone = '1';
    // paths for options that do not carry data-path: rebuild them from the indentation of the labels
    const stack = [];
    [...sel.options].forEach(o => {
      if (o.dataset.path || !o.value) return;
      const raw = o.textContent, depth = (raw.match(/^\s*/)[0].length / 3) | 0, name = raw.trim();
      stack.length = depth; stack[depth] = name; o.dataset.path = stack.filter(Boolean).join(' › ');
    });
    const wrap = document.createElement('div'); wrap.className = 'pk';
    const btn = document.createElement('button'); btn.type = 'button';
    btn.className = sel.className.replace('form-select', 'form-select pk-btn');
    sel.parentNode.insertBefore(wrap, sel); wrap.appendChild(btn); wrap.appendChild(sel);
    sel.style.display = 'none'; sel.tabIndex = -1;
    const pan = document.createElement('div'); pan.className = 'pk-pan'; pan.hidden = true;
    pan.innerHTML = '<input class="form-control form-control-sm" placeholder="Search…" autocomplete="off"><div class="pk-list"></div><div class="pk-addbox"></div>';
    wrap.appendChild(pan);
    const q = pan.querySelector('input'), list = pan.querySelector('.pk-list'), addBox = pan.querySelector('.pk-addbox');
    let items = [], hi = 0;

    function show() {
      const o = sel.selectedOptions[0];
      if (!o) { btn.innerHTML = '<span class="pk-txt">—</span>'; return; }
      const i = info(o);
      btn.innerHTML = `<span class="pk-txt">${esc(o.value ? i.name : o.textContent.trim())}</span>` +
        (i.under ? `<span class="pk-sub">${esc(i.under)}</span>` : '');
      btn.title = o.value ? i.path : '';
    }
    Object.defineProperty(sel, 'value', {configurable: true, get() { return proto.get.call(this); },
      set(v) { proto.set.call(this, v); show(); }});

    function render() {
      const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      items = [...sel.options].map(info).filter(i => words.every(w => i.hay.includes(w)));
      const mark = t => hl(t, words);
      list.innerHTML = items.length ? items.slice(0, 300).map((i, k) =>
        `<div class="pk-it${i.disabled ? ' dis' : ''}" data-k="${k}">${mark(i.value ? i.name : i.path)}` +
        (i.under ? `<span class="pk-p">${mark(i.under)}</span>` : '') + '</div>').join('')
        : '<div class="pk-none">Nothing matches.</div>';
      hi = Math.max(0, items.findIndex(i => !i.disabled && i.value === sel.value));
      if (words.length) hi = Math.max(0, items.findIndex(i => !i.disabled));
      light();
      addBox.innerHTML = '';
      if (sel.dataset.pickerAdd && q.value.trim() && !items.some(i => i.name.toLowerCase() === q.value.trim().toLowerCase())) {
        const cur = sel.selectedOptions[0];
        if (cur && cur.value) addBox.innerHTML = `<div class="pk-it pk-add" data-add="1"><i class="bi bi-plus-lg me-1"></i>Add “${esc(q.value.trim())}” under <b>${esc(info(cur).path)}</b></div>`;
      }
    }
    function light() {
      list.querySelectorAll('.pk-it').forEach(e => e.classList.toggle('on', +e.dataset.k === hi));
      const e = list.querySelector(`.pk-it[data-k="${hi}"]`); if (e) e.scrollIntoView({block: 'nearest'});
    }
    function choose(i) {
      if (!i || i.disabled) return;
      proto.set.call(sel, i.value); show(); close();
      sel.dispatchEvent(new Event('change', {bubbles: true}));
    }
    function open() { pan.hidden = false; q.value = ''; render(); q.focus(); }
    function close() { pan.hidden = true; }
    function addNew() {
      const cur = sel.selectedOptions[0], name = q.value.trim();
      fetch('/categories/add', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({parent_id: cur.value, name, next: 'json'})}).then(r => r.json()).then(d => {
        if (!d.ok) { addBox.innerHTML = `<div class="pk-none text-danger">${esc(d.msg || 'Not added')}</div>`; return; }
        document.querySelectorAll('select[data-picker]').forEach(s => {     // every category list on the page learns it
          if (![...s.options].some(o => o.dataset.path === cur.dataset.path)) return;
          const o = new Option('   '.repeat(d.level - 1) + name, d.id); o.dataset.path = d.path; o.dataset.level = d.level;
          const after = [...s.options].find(x => x.value === cur.value);
          after ? after.after(o) : s.add(o);
        });
        choose(info([...sel.options].find(o => o.value == d.id)));
      }).catch(() => { addBox.innerHTML = '<div class="pk-none text-danger">Could not reach the Hub.</div>'; });
    }
    btn.addEventListener('click', () => pan.hidden ? open() : close());
    q.addEventListener('input', render);
    q.addEventListener('keydown', e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); const d = e.key === 'ArrowDown' ? 1 : -1; let k = hi;
        do { k += d; } while (items[k] && items[k].disabled);
        if (items[k]) { hi = k; light(); }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items[hi] && !items[hi].disabled) choose(items[hi]); else if (addBox.firstChild) addNew();
      } else if (e.key === 'Escape') { e.stopPropagation(); close(); btn.focus(); }
    });
    list.addEventListener('mousedown', e => { const t = e.target.closest('.pk-it'); if (t) { e.preventDefault(); choose(items[+t.dataset.k]); } });
    addBox.addEventListener('mousedown', e => { if (e.target.closest('[data-add]')) { e.preventDefault(); addNew(); } });
    document.addEventListener('mousedown', e => { if (!wrap.contains(e.target)) close(); });
    sel.addEventListener('change', show);
    show();
  }
  window.HubPicker = {enhance, hl, all: () => document.querySelectorAll('select[data-picker]').forEach(enhance)};
  document.addEventListener('DOMContentLoaded', window.HubPicker.all);
})();
