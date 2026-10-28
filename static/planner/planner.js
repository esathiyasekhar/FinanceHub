/* Finance Hub — Wealth planner page (Compounding Calculator v1.11 rebuilt in Hub style).
   All numbers come from window.CompoundingEngine (calculator.js, unchanged). This file only reads the
   inputs, calls the engine and draws cards, tables and Chart.js charts. Users are saved through /api/cc. */
(function () {
  'use strict';
  const CE = window.CompoundingEngine;
  const $ = (id) => document.getElementById(id);
  const num = (id, d = 0) => { const v = parseFloat($(id).value); return isFinite(v) ? v : d; };
  const int = (id, d = 0) => { const v = parseInt($(id).value, 10); return isFinite(v) ? v : d; };
  const set = (id, t) => { const e = $(id); if (e) e.textContent = t; };
  const html = (id, h) => { const e = $(id); if (e) e.innerHTML = h; };
  const cr = (v, d = 2) => CE.formatINR(v, { compact: true, decimals: d });
  const full = (v) => CE.formatINR(Math.round(v), { decimals: 0 });
  const fmtPct = (x, d = 1) => `${(x * 100).toFixed(d).replace(/\.0+$/, '')}%`;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const C = { gold: '#F2B544', growth: '#3ED6A0', core: '#7E9CFF', sat: '#2BC3D8', rose: '#FF7A8A', inv: '#8193AE', muted: '#94a3b8', line: 'rgba(148,163,184,.15)' };

  const DEFAULTS = {
    selfLump: 100000, selfMonthly: 10000, selfInclude: true, selfStepUpOn: true, selfStepUp: 10, selfStepUpMode: 'pct',
    selfStepUpAmt: 1000, selfStepUpStop: 10, selfAddStop: 10, selfAddStopMonths: 0, coreAlloc: 70, coreRet: 15, satRet: 25,
    horizon: 30, spouseInclude: false, spouseLump: 0, spouseMonthly: 0, spouseStepUpOn: true, spouseStepUp: 10,
    spouseStepUpMode: 'pct', spouseStepUpAmt: 1000, spouseStepUpStop: 10, spouseAddStop: 10, spouseAddStopMonths: 0
  };
  const Y_DEFAULTS = { age: 21, monthly: 10000, on: true, mode: 'pct', pct: 5, amt: 500, stop: 10, add: 10, addMonths: 0, alloc: 70, core: 17, sat: 27 };

  const state = {
    users: window.PLANNER_USERS || {}, activeId: null, actuals: {}, goalTouched: false, log: false,
    pending: {}, mode: { self: 'pct', spouse: 'pct', y: 'pct' }, tab: 'core', charts: {}
  };

  // ── API ────────────────────────────────────────────────────────────────
  async function api(method, url, body) {
    const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json().catch(() => ({ ok: false, msg: 'Server error' }));
    if (!r.ok || j.ok === false) throw new Error(j.msg || 'Request failed');
    return j;
  }
  function toast(msg, ok = true) {
    let box = $('plToast');
    if (!box) { box = document.createElement('div'); box.id = 'plToast'; box.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:2000;max-width:420px'; document.body.appendChild(box); }
    const d = document.createElement('div');
    d.className = `alert alert-${ok ? 'success' : 'warning'} py-2 px-3 mb-2 shadow`; d.style.fontSize = '.82rem'; d.textContent = msg;
    box.appendChild(d); setTimeout(() => d.remove(), 4200);
  }
  async function reloadUsers(selectId) {
    state.users = await fetch('/api/cc/users').then(r => r.json());
    const sel = $('userSel');
    sel.innerHTML = Object.values(state.users).sort((a, b) => a.name.localeCompare(b.name))
      .map(u => `<option value="${esc(u.userId)}">${esc(u.name)} (${esc(u.userId)})</option>`).join('');
    if (selectId && state.users[selectId]) sel.value = selectId;
  }

  // ── Inputs ⇄ stored params (stored as shown on screen: % values) ─────────
  function setMode(who, mode, convert) {
    const pctId = who === 'y' ? 'yStep' : `${who}Step`, amtId = who === 'y' ? 'yStepAmt' : `${who}StepAmt`;
    const baseId = who === 'y' ? 'yMonthly' : `${who}Monthly`;
    if (convert && state.mode[who] !== mode) {
      const base = num(baseId, 0);
      if (base > 0 && mode === 'amt') $(amtId).value = Math.round(base * num(pctId, 0) / 100 / 100) * 100;
      if (base > 0 && mode === 'pct') $(pctId).value = Math.min(25, Math.max(0, Math.round(num(amtId, 0) / base * 200) / 2));
    }
    state.mode[who] = mode;
    document.querySelectorAll(`[data-mode-for="${who}"] button`).forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    const box = $(who === 'y' ? 'yStepBox' : `${who}StepBox`);
    box.querySelector('.step-pct').style.display = mode === 'pct' ? '' : 'none';
    box.querySelector('.step-amt').style.display = mode === 'amt' ? '' : 'none';
  }
  function applyParams(p) {
    p = Object.assign({}, DEFAULTS, p || {});
    ['coreAlloc', 'coreRet', 'satRet', 'horizon'].forEach(k => { $(k).value = p[k]; });
    ['self', 'spouse'].forEach(w => {
      $(`${w}Include`).checked = !!p[`${w}Include`];
      $(`${w}Lump`).value = p[`${w}Lump`]; $(`${w}Monthly`).value = p[`${w}Monthly`];
      $(`${w}StepOn`).checked = p[`${w}StepUpOn`] !== false;
      $(`${w}Step`).value = p[`${w}StepUp`]; $(`${w}StepAmt`).value = p[`${w}StepUpAmt`];
      $(`${w}StepStop`).value = p[`${w}StepUpStop`]; $(`${w}AddStop`).value = p[`${w}AddStop`];
      $(`${w}AddStopMonths`).value = p[`${w}AddStopMonths`] || 0;
      setMode(w, p[`${w}StepUpMode`] === 'amt' ? 'amt' : 'pct', false);
    });
  }
  function readParams() {
    const p = { coreAlloc: num('coreAlloc', 70), coreRet: num('coreRet', 15), satRet: num('satRet', 25), horizon: int('horizon', 30) };
    ['self', 'spouse'].forEach(w => Object.assign(p, {
      [`${w}Include`]: $(`${w}Include`).checked, [`${w}Lump`]: num(`${w}Lump`, 0), [`${w}Monthly`]: num(`${w}Monthly`, 0),
      [`${w}StepUpOn`]: $(`${w}StepOn`).checked, [`${w}StepUp`]: num(`${w}Step`, 0), [`${w}StepUpMode`]: state.mode[w],
      [`${w}StepUpAmt`]: num(`${w}StepAmt`, 0), [`${w}StepUpStop`]: int(`${w}StepStop`, 10), [`${w}AddStop`]: int(`${w}AddStop`, 10),
      [`${w}AddStopMonths`]: int(`${w}AddStopMonths`, 0)
    }));
    return p;
  }
  /** Stored params → engine params (fractions), exactly as the calculator's getCurrentParams(). */
  function engineParams(sp) {
    const p = sp || readParams();
    const e = { coreAlloc: p.coreAlloc / 100, satAlloc: 1 - p.coreAlloc / 100, coreReturn: p.coreRet / 100, satReturn: p.satRet / 100, horizon: p.horizon, maxYears: 60 };
    ['self', 'spouse'].forEach(w => {
      const on = p[`${w}StepUpOn`];
      Object.assign(e, {
        [`${w}Lump`]: Math.max(0, p[`${w}Lump`]), [`${w}Monthly`]: Math.max(0, p[`${w}Monthly`]), [`${w}Include`]: p[`${w}Include`],
        [`${w}StepUpOn`]: on, [`${w}StepUp`]: on ? p[`${w}StepUp`] / 100 : 0, [`${w}StepUpMode`]: p[`${w}StepUpMode`] === 'amt' ? 'amt' : 'pct',
        [`${w}StepUpAmt`]: on ? Math.max(0, p[`${w}StepUpAmt`]) : 0, [`${w}StepUpStop`]: Math.max(1, p[`${w}StepUpStop`]),
        [`${w}AddStop`]: Math.max(0, p[`${w}AddStop`]), [`${w}AddStopMonths`]: Math.max(0, Math.min(11, p[`${w}AddStopMonths`]))
      });
    });
    return e;
  }
  function readGoal() {
    return { target: Math.max(0, num('goalTarget', 1e8)), years: Math.max(1, int('goalYears', 20)), assumedReturn: state.goalTouched ? num('goalRet', null) : null };
  }
  function applyGoal(g) {
    g = Object.assign({ target: 1e8, years: 20, assumedReturn: null }, g || {});
    $('goalTarget').value = g.target; $('goalYears').value = g.years;
    state.goalTouched = g.assumedReturn !== null && g.assumedReturn !== undefined;
    if (state.goalTouched) $('goalRet').value = g.assumedReturn;
  }
  function activeUser() { return state.users[state.activeId] || null; }
  function loadUser(id) {
    const u = state.users[id];
    if (!u) return;
    state.activeId = id; $('userSel').value = id;
    applyParams(u.params); applyGoal(u.goal);
    state.actuals = JSON.parse(JSON.stringify(u.actualsHistory || {}));
    state.pending = {};
    try { localStorage.setItem('planner_active_user', id); } catch (e) { /* ignore */ }
    updateAll();
  }
  function refreshDirty() {
    const u = activeUser();
    if (!u) return;
    const sameP = JSON.stringify(Object.assign({}, DEFAULTS, u.params)) === JSON.stringify(Object.assign({}, DEFAULTS, readParams()));
    const g = readGoal();
    const sameG = Number(u.goal.target) === g.target && Number(u.goal.years) === g.years && (u.goal.assumedReturn ?? null) === (g.assumedReturn ?? null);
    const dirty = !(sameP && sameG);
    $('btnSave').classList.toggle('dirty', dirty);
    $('dirtyNote').style.display = dirty ? '' : 'none';
  }

  // ── Core engine ─────────────────────────────────────────────────────────
  function stepEquiv(base, mode, pct, amt, stopYr, addStop, word = 'year') {
    const last = Math.min(stopYr, addStop);
    if (last < 2) return 'No step-up: the SIP stops or stops rising after year 1.';
    const y2 = CE.steppedMonthly(base, 2, stopYr, mode, pct, amt), yl = CE.steppedMonthly(base, last, stopYr, mode, pct, amt);
    if (mode === 'amt') {
      if (amt <= 0) return 'No step-up.';
      if (base <= 0) return `SIP starts at ₹0 and grows by <b>${full(amt)}/mo</b> each ${word}; ${full(yl)}/mo by ${word} ${last}.`;
      const lastPct = amt / CE.steppedMonthly(base, last - 1, stopYr, mode, pct, amt);
      return `= <b>${fmtPct(amt / base)}</b> of the ${word}-1 SIP${last > 2 ? `, easing to ${fmtPct(lastPct)} by ${word} ${last}` : ''}. SIP reaches ${full(yl)}/mo.`;
    }
    if (pct <= 0) return 'No step-up.';
    if (base <= 0) return 'Enter a monthly SIP to see the rupee step-up.';
    return `= <b>+${full(y2 - base)}/mo</b> in ${word} 2 (${full((y2 - base) * 12)} more a year). SIP reaches ${full(yl)}/mo by ${word} ${last}.`;
  }

  function updateAll() {
    const sp = readParams(), p = engineParams(sp);
    set('dCoreAlloc', `${sp.coreAlloc}%`); set('lblCore', `Core ${sp.coreAlloc}%`); set('lblSat', `Satellite ${100 - sp.coreAlloc}%`);
    $('barCore').style.width = `${sp.coreAlloc}%`; $('barSat').style.width = `${100 - sp.coreAlloc}%`;
    set('dCoreRet', `${sp.coreRet.toFixed(1)}%`); set('dSatRet', `${sp.satRet.toFixed(1)}%`); set('dHorizon', `${sp.horizon} yrs`); set('kHorizon', sp.horizon);
    ['self', 'spouse'].forEach(w => {
      set(`d${w}Step`, fmtPct(sp[`${w}StepUp`] / 100));
      $(`${w}StepBox`).classList.toggle('is-off', !sp[`${w}StepUpOn`]);
      $(`${w}Box`).classList.toggle('is-off', !sp[`${w}Include`] && w === 'spouse');
      if (w === 'self') { $('selfMonthly').closest('.col-6').classList.toggle('is-off', !sp.selfInclude); }
      html(`${w}Equiv`, sp[`${w}StepUpOn`] ? stepEquiv(p[`${w}Monthly`], p[`${w}StepUpMode`], p[`${w}StepUp`], p[`${w}StepUpAmt`], p[`${w}StepUpStop`], p[`${w}AddStop`]) : 'Step-up is off: the SIP stays flat.');
    });
    set('chipSelf', sp.selfInclude && sp.selfMonthly > 0 ? `${cr(sp.selfMonthly, 0)}/mo` : sp.selfLump > 0 ? 'lump' : (sp.selfInclude ? '₹0' : 'off'));
    set('chipSpouse', !sp.spouseInclude ? 'off' : sp.spouseMonthly > 0 ? `${cr(sp.spouseMonthly, 0)}/mo` : sp.spouseLump > 0 ? 'lump' : '₹0');

    const r = CE.calculateSchedule(p, state.actuals);
    state.last = r;
    const has = r.totalInvested > 0;
    set('kCorpus', cr(r.totalCorpus)); set('kCorpusExact', CE.formatINR(r.totalCorpus, { decimals: 0 }));
    set('kMultiple', has ? `${r.multiple.toFixed(1)}× what you invested` : 'Nothing invested yet');
    set('kInvested', cr(r.totalInvested)); set('kInvestedExact', CE.formatINR(r.totalInvested, { decimals: 0 }));
    set('kGain', cr(r.wealthGain)); set('kGainShare', r.totalCorpus > 0 ? `${(r.wealthGain / r.totalCorpus * 100).toFixed(1)}% of the corpus` : '');
    const invShare = r.totalCorpus > 0 ? Math.min(100, r.totalInvested / r.totalCorpus * 100) : 100;
    $('segInv').style.width = `${invShare}%`; $('segGain').style.width = `${100 - invShare}%`;
    set('kIrr', has && r.portfolioIRR > 0 ? CE.formatPercent(r.portfolioIRR, 2) : '—');
    set('kCagr', CE.formatPercent(r.weightedStartingReturn, 2));
    const d = (r.portfolioIRR - r.weightedStartingReturn) * 100, satFinal = r.totalCorpus > 0 ? r.satCorpus / r.totalCorpus * 100 : 0;
    set('kGapNote', !has ? 'Blended CAGR is the mix-weighted return of core and satellite.'
      : Math.abs(d) < 0.1 ? 'IRR matches the blended CAGR — your money compounds at the planned rate.'
      : d > 0 ? `IRR is ${d.toFixed(2)} pts above the CAGR: the faster satellite grows from ${100 - sp.coreAlloc}% to ${satFinal.toFixed(0)}% of the money (no rebalancing).`
      : `IRR is ${(-d).toFixed(2)} pts below the CAGR${Object.keys(state.actuals).length ? ': your recorded years earned less than planned.' : '.'}`);
    set('kDbl', has && r.doublingTimeAtIRR > 0 ? CE.formatYears(r.doublingTimeAtIRR, 2) : '—');
    set('kNext2x', !has ? '—' : (typeof r.nextDoublingAfterHorizon === 'number' ? CE.formatYears(r.nextDoublingAfterHorizon, 2) : r.nextDoublingAfterHorizon));
    const cs = r.totalCorpus > 0 ? r.coreCorpus / r.totalCorpus * 100 : sp.coreAlloc, ss = r.totalCorpus > 0 ? r.satCorpus / r.totalCorpus * 100 : 100 - sp.coreAlloc;
    set('kCoreC', cr(r.coreCorpus)); set('kCoreSub', `${CE.formatINR(r.coreCorpus, { decimals: 0 })} · ${cs.toFixed(1)}%`);
    set('kSatC', cr(r.satCorpus)); set('kSatSub', `${CE.formatINR(r.satCorpus, { decimals: 0 })} · ${ss.toFixed(1)}%`);
    $('splitCore').style.width = `${cs}%`; $('splitSat').style.width = `${ss}%`;
    set('splitCaption', r.totalCorpus > 0 ? `Satellite is ${100 - sp.coreAlloc}% of every rupee invested, and ${ss.toFixed(0)}% of the corpus by year ${r.horizon}` : 'Enter a lump sum or SIP to see how the corpus splits');

    const sa = updateSpouse(p);
    drawGrowth(r, sa ? sa.selfOnlyResult.yearlyRows : null);
    updateGoal(p, sp);
    renderLadder(r, p);
    renderSchedule(r.yearlyRows, r.horizon);
    updateReview(p);
    refreshDirty();
  }

  function updateSpouse(p) {
    if (!p.spouseInclude) { $('spouseStrip').style.display = 'none'; return null; }
    $('spouseStrip').style.display = '';
    const sa = CE.analyzeSpouseImpact(p);
    set('spSaved', sa.timeSavedYears > 0.05 ? `${sa.timeSavedYears.toFixed(1)} years` : '—');
    set('spReach', sa.yearsWithSpouseToReachSelfTarget !== null ? sa.yearsWithSpouseToReachSelfTarget.toFixed(1) : '—');
    set('spH', sa.combinedResult.horizon);
    set('spSolo', cr(sa.selfCorpus)); set('spSoloInv', cr(sa.selfTotalInvested, 1));
    set('spTeam', cr(sa.combinedCorpus)); set('spTeamInv', cr(sa.combinedTotalInvested, 1));
    set('spExtra', sa.extraCorpusAtHorizon > 0 ? `+${cr(sa.extraCorpusAtHorizon)}` : '₹0');
    set('spMult', sa.spouseWealthMultiplier > 0 ? `${sa.spouseWealthMultiplier.toFixed(1)}× the ${cr(sa.spouseTotalInvested, 1)} the spouse invests` : 'Enter the spouse’s lump sum or SIP');
    return sa;
  }

  // markers plugin: vertical dashed lines at fractional years (25 / 50 / 75 % of the horizon corpus)
  const markerPlugin = {
    id: 'plMarkers',
    afterDatasetsDraw(chart, _a, opts) {
      const ms = (opts && opts.marks) || [];
      const { ctx, chartArea: a, scales: { x } } = chart;
      ctx.save();
      ms.forEach(m => {
        const px = x.getPixelForValue(m.x);
        if (px < a.left || px > a.right) return;
        ctx.strokeStyle = m.color || C.gold; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(px, a.top + 14); ctx.lineTo(px, a.bottom); ctx.stroke();
        ctx.setLineDash([]); ctx.fillStyle = m.color || C.gold; ctx.font = '600 11px Inter,system-ui,sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(m.label, px, a.top + 10);
      });
      ctx.restore();
    }
  };
  const moneyTick = (v) => v === 0 ? '₹0' : CE.formatINR(v, { compact: true, decimals: v >= 1e7 ? 0 : 1 }).replace('.0 ', ' ');

  function drawGrowth(r, soloRows) {
    const H = r.horizon, rows = r.yearlyRows.filter(x => x.year <= H), final = rows[rows.length - 1].totalCorpus;
    const pts = (k) => rows.map(x => ({ x: x.year, y: state.log ? Math.max(1, x[k]) : x[k] }));
    const ds = [
      { label: 'Core', data: pts('coreClose'), stack: 'pots', fill: 'origin', borderColor: C.core, backgroundColor: 'rgba(126,156,255,.25)', pointRadius: 0, borderWidth: 1.5 },
      { label: 'Satellite', data: pts('satClose'), stack: 'pots', fill: '-1', borderColor: C.sat, backgroundColor: 'rgba(43,195,216,.25)', pointRadius: 0, borderWidth: 1.5 },
      { label: 'Invested', data: pts('totalInvested'), stack: 'inv', borderColor: C.inv, borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5, fill: false }
    ];
    if (soloRows) ds.push({ label: 'Self only', data: soloRows.filter(x => x.year <= H).map(x => ({ x: x.year, y: Math.max(state.log ? 1 : 0, x.totalCorpus) })), stack: 'solo', borderColor: C.rose, borderDash: [3, 3], pointRadius: 0, borderWidth: 1.5, fill: false });
    const marks = [];
    if (final > 0) [0.25, 0.5, 0.75].forEach(f => { const y = CE.yearReaching(r.yearlyRows, f * final, 60); if (y !== null && y <= H) marks.push({ x: y, label: `${f * 100}%` }); });
    const half = marks.find(m => m.label === '50%');
    set('shareNote', final > 0 && half ? `Half of the year-${H} corpus arrives in the last ${(H - half.x).toFixed(1)} years` : '');
    const cfg = {
      type: 'line', data: { datasets: ds }, plugins: [markerPlugin],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: true,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
          plMarkers: { marks }, legend: { position: 'top', labels: { boxWidth: 12 } },
          tooltip: {
            callbacks: {
              title: (it) => `Year ${it[0].parsed.x}`,
              label: (it) => `${it.dataset.label}: ${cr(it.raw.y)}`,
              footer: (it) => {
                const row = rows[Math.round(it[0].parsed.x)];
                return row ? [`Corpus: ${cr(row.totalCorpus)}`, `${(row.totalCorpus / final * 100).toFixed(1)}% of the year-${H} corpus`] : '';
              }
            }
          }
        },
        scales: {
          x: { type: 'linear', min: 0, max: H, ticks: { stepSize: H <= 12 ? 2 : H <= 30 ? 5 : 10 }, grid: { color: C.line } },
          y: { type: state.log ? 'logarithmic' : 'linear', stacked: true, ticks: { callback: moneyTick }, grid: { color: C.line } }
        }
      }
    };
    if (state.charts.growth) state.charts.growth.destroy();
    state.charts.growth = new Chart($('growthChart'), cfg);
  }

  // ── Goal & schedule ─────────────────────────────────────────────────────
  function updateGoal(p, sp) {
    const g = readGoal(), planned = CE.weightedReturnOf(p);
    if (!state.goalTouched) $('goalRet').value = (planned * 100).toFixed(1);
    const assumed = state.goalTouched ? num('goalRet', planned * 100) / 100 : planned;
    set('dGoalRet', fmtPct(assumed));
    const dd = (assumed - planned) * 100;
    set('goalRetNote', Math.abs(dd) < 0.05 ? 'Your blended CAGR' : `${Math.abs(dd).toFixed(1)} pts ${dd > 0 ? 'above' : 'below'} your blended CAGR of ${fmtPct(planned)}`);
    const showBtns = state.goalTouched && Math.abs(assumed - planned) >= 0.0005;
    $('goalRetReset').style.display = showBtns ? '' : 'none';
    $('goalRetApply').style.display = showBtns ? '' : 'none';
    set('goalRetApply', `Use ${fmtPct(assumed)} in my plan`);
    set('gSipTitle', `Monthly SIP to hit it on time at ${fmtPct(assumed)}`);
    document.querySelectorAll('.goal-chip').forEach(c => c.classList.toggle('active', Number(c.dataset.goal) === g.target));
    const res = CE.solveGoal(g.target, g.years, p, { assumedBlendedReturn: assumed });
    html('goalCurrent', `Your current plan at year ${g.years}: <b>${cr(res.currentCorpusAtHorizon)}</b>`);
    if (g.target <= 0) { set('gTime', 'Now'); set('gTimeSub', 'A target of ₹0 is already met.'); set('gSip', '₹0 / mo'); set('gSipSub', ''); set('gRate', '—'); html('sensBody', ''); return; }
    if (res.timeToGoalYears !== null) {
      set('gTime', `Year ${res.timeToGoalYears.toFixed(1)}`);
      const df = g.years - res.timeToGoalYears;
      html('gTimeSub', df >= 0 ? `<span class="good">${df.toFixed(1)} years before your deadline.</span>` : `<span class="bad">${(-df).toFixed(1)} years after your deadline</span> at your current SIP and returns.`);
    } else { set('gTime', 'Not in 60 yrs'); set('gTimeSub', 'Your current plan never reaches this within 60 years. Raise the SIP or the return.'); }
    set('gSip', res.sipUnreachable ? 'Not reachable' : `${full(res.requiredMonthlySIP)} / mo`);
    const lastSip = Math.min(p.selfAddStop, g.years), lastStep = Math.min(p.selfStepUpStop, lastSip);
    const stepTxt = lastStep < 2 ? 'no step-up' : (p.selfStepUpMode === 'amt' ? (p.selfStepUpAmt > 0 ? `rising ${full(p.selfStepUpAmt)}/mo each year to year ${lastStep}` : 'no step-up')
      : (p.selfStepUp > 0 ? `stepped up ${fmtPct(p.selfStepUp)} a year to year ${lastStep}` : 'no step-up'));
    const lumpTxt = (p.selfLump + (p.spouseInclude ? p.spouseLump : 0)) > 0 ? 'your lump sum' : 'no lump sum';
    const spTxt = p.spouseInclude ? ' and your spouse’s plan' : '';
    set('gSipSub', res.sipUnreachable ? `Your SIP stops after year ${p.selfAddStop}, so no amount gets there. Raise “SIP runs for” in the Core engine.`
      : res.requiredMonthlySIP === 0 ? `${lumpTxt[0].toUpperCase() + lumpTxt.slice(1)}${spTxt} already get there at ${fmtPct(assumed)} — no SIP needed.`
      : `Starting SIP, ${stepTxt}, paid until year ${lastSip}, with ${lumpTxt}${spTxt}. Your SIP today: ${full(p.selfInclude ? p.selfMonthly : 0)}.`);
    if (res.requiredBlendedReturn !== null) {
      set('gRate', CE.formatPercent(res.requiredBlendedReturn, 1));
      const rates = CE.ratesForBlended(res.requiredBlendedReturn, p);
      set('gRateSub', `Blended CAGR over ${g.years} years — about ${(rates.coreReturn * 100).toFixed(1)}% core and ${(rates.satReturn * 100).toFixed(1)}% satellite. Yours is ${(planned * 100).toFixed(1)}%.`);
    } else {
      set('gRate', res.rateOutOfRange === 'high' ? 'Over 150%' : '—');
      set('gRateSub', res.rateOutOfRange === 'high' ? 'No realistic return gets there with your current lump sum and SIP.' : 'Add a lump sum or SIP in the Core engine first.');
    }
    // sensitivity
    const ks = new Set([0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30].map(x => Math.round(x * 1000)));
    ks.add(Math.round(planned * 1000)); ks.add(Math.round(assumed * 1000));
    const today = p.selfInclude ? p.selfMonthly : 0;
    set('sensCorpusTh', `Corpus at year ${p.horizon}`);
    html('sensBody', Array.from(ks).sort((a, b) => a - b).map(k => {
      const rr = k / 1000, rates = CE.ratesForBlended(rr, p);
      const s = CE.calculateSchedule(Object.assign({}, p, rates), state.actuals);
      const reach = CE.yearReaching(s.yearlyRows, g.target, 60), sip = CE.requiredSIPAtReturn(g.target, g.years, p, rr);
      const chosen = Math.abs(rr - assumed) < 0.0006, mine = Math.abs(rr - planned) < 0.0006, ok = s.totalInvested > 0;
      let reachCell = '<span class="bad">Not in 60 yrs</span>';
      if (reach !== null) { const dy = g.years - reach; reachCell = `Year ${reach.toFixed(1)} <span class="${dy >= 0 ? 'good' : 'bad'}">${dy >= 0 ? '✓' : '+' + (-dy).toFixed(1) + ' yrs'}</span>`; }
      let sipCell = '<span class="muted">Not reachable</span>';
      if (!sip.unreachable) { const v = Math.round(sip.sip), df = v - today;
        sipCell = v === 0 ? '<span class="good">No SIP needed</span>' : `<b>${full(v)}</b> <span class="${Math.abs(df) < 50 ? 'muted' : df > 0 ? 'bad' : 'good'}">${Math.abs(df) < 50 ? 'same' : (df > 0 ? '+' : '−') + full(Math.abs(df))}</span>`; }
      return `<tr class="${chosen ? 'hl' : ''}" data-ret="${(rr * 100).toFixed(1)}" style="cursor:pointer">
        <td><b>${fmtPct(rr)}</b>${mine ? ' <span class="badge bg-secondary">yours</span>' : ''}${chosen && !mine ? ' <span class="badge bg-warning text-dark">selected</span>' : ''}</td>
        <td>${fmtPct(rates.coreReturn)} / ${fmtPct(rates.satReturn)}</td>
        <td class="c-growth">${ok && s.portfolioIRR > 0 ? fmtPct(s.portfolioIRR) : '—'}</td>
        <td>${ok && s.doublingTimeAtIRR > 0 ? s.doublingTimeAtIRR.toFixed(1) + ' yrs' : '—'}</td>
        <td>${ok ? `<b>${cr(s.totalCorpus)}</b> <span class="muted">${s.multiple.toFixed(0)}×</span>` : '—'}</td>
        <td>${reachCell}</td><td>${sipCell}</td></tr>`;
    }).join(''));
  }

  function renderLadder(r, p) {
    const ms = r.milestones.filter(m => typeof m.yearReached === 'number').slice(0, 14);
    const base = p.selfLump + (p.spouseInclude ? p.spouseLump : 0);
    if (!ms.length) { html('ladder', '<span class="muted small">Enter a lump sum or SIP in the Core engine to see the ladder.</span>'); set('ladderNote', ''); return; }
    const baseAmt = base > 0 ? base : ms[0].target / 2;
    set('ladderNote', `— multiples of ${base > 0 ? 'your ' + full(baseAmt) + ' starting capital' : 'the first year’s SIP (' + full(baseAmt) + ')'}, SIPs included.` +
      (r.portfolioIRR > 0 ? ` At ${fmtPct(r.portfolioIRR)} IRR money doubles every ${r.doublingTimeAtIRR.toFixed(2)} yrs (Rule of 72: ${(72 / (r.portfolioIRR * 100)).toFixed(2)}) — about ${(r.horizon / r.doublingTimeAtIRR).toFixed(1)} doublings in ${r.horizon} years.` : ''));
    html('ladder', ms.map(m => `<span class="rung ${m.isWithinHorizon ? 'in' : 'out'}" title="${m.isWithinHorizon ? 'Within your horizon' : 'After your horizon'}">
      <b>${m.multiple.toLocaleString('en-IN')}×</b><span>${cr(m.target)}</span><span class="muted">Year ${m.yearReached.toFixed(1)}${typeof m.gap === 'number' && m.multiple > 2 ? ` · +${m.gap.toFixed(1)}` : ''}</span></span>`).join(''));
  }

  function renderSchedule(rows, H) {
    const f = (v) => CE.formatINR(v, { decimals: 0 }), dash = '<span class="muted">—</span>', fin = rows[H] ? rows[H].totalCorpus : 0;
    set('thShare', `% of yr-${H}`);
    html('schedBody', rows.map(x => `<tr class="${x.year === H ? 'hl' : ''}"><td><b>${x.year}</b>${x.isActual ? ' <span class="badge bg-warning text-dark">actual</span>' : ''}</td>
      <td>${x.selfContrib > 0 ? f(x.selfContrib) : dash}</td><td>${x.spouseContrib > 0 ? f(x.spouseContrib) : dash}</td>
      <td>${f(x.coreOpen)}</td><td>${x.coreAdd > 0 ? f(x.coreAdd) : dash}</td><td>${f(x.coreRet)}</td><td><b>${f(x.coreClose)}</b></td>
      <td>${f(x.satOpen)}</td><td>${x.satAdd > 0 ? f(x.satAdd) : dash}</td><td>${f(x.satRet)}</td><td><b>${f(x.satClose)}</b></td>
      <td class="c-growth">${f(x.totalCorpus)}</td><td>${f(x.totalInvested)}</td><td class="c-gold">${x.multiple.toFixed(2)}×</td>
      <td>${fin > 0 ? (x.totalCorpus / fin * 100).toFixed(x.totalCorpus / fin >= 0.1 ? 0 : 1) + '%' : '—'}</td>
      <td>${typeof x.yrsTo2x === 'number' ? x.yrsTo2x.toFixed(2) : '<span class="muted">' + x.yrsTo2x + '</span>'}</td></tr>`).join(''));
  }
  function scheduleCsv() {
    const rows = state.last.yearlyRows, head = ['Year', 'Self SIP', 'Spouse SIP', 'Core open', 'Core added', 'Core growth', 'Core close', 'Sat open', 'Sat added', 'Sat growth', 'Sat close', 'Corpus', 'Invested', 'Multiple', 'Years to 2x', 'Actual'];
    return [head.join(',')].concat(rows.map(x => [x.year, x.selfContrib, x.spouseContrib, x.coreOpen, x.coreAdd, x.coreRet, x.coreClose, x.satOpen, x.satAdd, x.satRet, x.satClose, x.totalCorpus, x.totalInvested]
      .map(v => Math.round(v)).concat([x.multiple.toFixed(2), typeof x.yrsTo2x === 'number' ? x.yrsTo2x.toFixed(2) : x.yrsTo2x, x.isActual ? 'yes' : '']).join(','))).join('\n');
  }

  // ── Annual review ───────────────────────────────────────────────────────
  const periodLabel = (start, y) => { const a = (start || new Date().getFullYear()) + y - 1; return `${a}–${String((a + 1) % 100).padStart(2, '0')}`; };
  function updateReview(p) {
    const u = activeUser(), start = u ? u.startYear : new Date().getFullYear(), g = readGoal();
    const gp = Object.assign({}, p, { horizon: Math.min(60, Math.max(1, g.years)) });
    const review = CE.reviewActualsAndCorrect(gp, state.actuals, g.target), base = CE.calculateSchedule(gp), rev = review.revisedSchedule;
    if (u) {
      set('rvName', u.name); set('rvId', `User ID: ${u.userId}`); set('rvStart', start);
      set('rvGoal', `${cr(g.target)} in ${g.years} yrs (by ${periodLabel(start, g.years)})`);
      const n = Object.keys(state.actuals).length;
      set('rvLogged', n ? `${n} (latest: year ${review.latestActualYear})` : 'none yet');
      set('rvSaved', u.updatedAt ? new Date(u.updatedAt).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
    }
    set('ccRevTitle', `Projected at year ${g.years} (${periodLabel(start, g.years)})`);
    set('ccRev', cr(review.revisedCorpus));
    const gap = review.revisedCorpus - g.target;
    html('ccVar', Math.abs(gap) < Math.max(1000, g.target * 0.0005) ? '<span class="good">right on the goal</span>'
      : gap > 0 ? `<span class="good">${cr(gap)} above the goal</span>` : `<span class="bad">${cr(-gap)} short of the goal</span>`);
    if (review.revisedTimeToGoal === null) { set('ccTime', 'Not in 60 yrs'); set('ccTimeSub', 'At the planned SIP and returns the goal is never reached.'); }
    else { const df = g.years - review.revisedTimeToGoal; set('ccTime', `Year ${review.revisedTimeToGoal.toFixed(1)}`);
      html('ccTimeSub', df >= 0 ? `<span class="good">${df.toFixed(1)} years before the deadline</span>, with the planned SIP and returns from here.` : `<span class="bad">${(-df).toFixed(1)} years after the deadline</span>, with the planned SIP and returns from here.`); }
    const planned = (review.plannedWeightedRate * 100).toFixed(1);
    if (review.latestActualYear >= g.years) { set('ccRate', '—'); set('ccRateSub', 'Every year up to the goal year is already recorded.'); }
    else if (review.requiredFutureRate !== null) {
      set('ccRate', CE.formatPercent(review.requiredFutureRate, 1));
      const dd = (review.requiredFutureRate - review.plannedWeightedRate) * 100, left = g.years - review.latestActualYear;
      html('ccRateSub', Math.abs(dd) <= 0.05 ? `Blended CAGR for the remaining ${left} years — the same as your ${planned}%.`
        : `Blended CAGR for the remaining ${left} years: <span class="${dd > 0 ? 'bad' : 'good'}">${Math.abs(dd).toFixed(1)} pts ${dd > 0 ? 'above' : 'below'}</span> your ${planned}%.`);
    } else { set('ccRate', review.rateOutOfRange === 'high' ? 'Over 150%' : '—');
      set('ccRateSub', review.rateOutOfRange === 'high' ? 'Returns alone cannot close this gap — more money is needed (see SIP).' : 'Already ahead of the goal even at very low returns.'); }
    set('ccSipTitle', `Monthly SIP needed from year ${review.sipFromYear}`);
    if (review.latestActualYear >= g.years) { set('ccSip', '—'); set('ccSipSub', ''); }
    else if (review.sipUnreachable) { set('ccSip', 'Not reachable'); set('ccSipSub', 'No SIP closes the gap in the time left at the planned returns.'); }
    else {
      set('ccSip', `${full(review.requiredFutureSIP)} / mo`);
      const pm = full(review.plannedFutureMonthly), dl = review.sipAdjustmentNeeded;
      html('ccSipSub', review.sipMode === 'restart' ? (review.requiredFutureSIP > 0 ? `The planned SIP has ended by year ${review.sipFromYear}. A flat SIP like this until year ${g.years}, at planned returns, reaches the goal.` : '<span class="good">No more SIP needed</span> — the goal is reached anyway.')
        : dl > 100 ? `The plan has ${pm} for year ${review.sipFromYear}. <span class="bad">Add ${full(dl)} a month</span>, keeping the step-up, at planned returns.`
        : dl < -100 ? `The plan has ${pm} for year ${review.sipFromYear}. <span class="good">${full(-dl)} a month less</span> still reaches the goal.`
        : `The planned SIP (${pm} in year ${review.sipFromYear}) is enough.`);
    }
    // records table
    const last = Math.min(60, Math.max(review.latestActualYear + 1, 1));
    let h = '';
    for (let yr = 1; yr <= last; yr++) {
      const rec = state.actuals[yr], b = base.yearlyRows[yr], r = rev.yearlyRows[yr], prev = rev.yearlyRows[yr - 1], pd = state.pending[yr] || {};
      const val = (k) => pd[k] !== undefined ? pd[k] : (rec && rec[k] != null ? rec[k] : '');
      const edited = Object.keys(pd).length > 0;
      let ret = '<span class="muted">—</span>', diff = ret, tot = ret;
      if (rec) {
        const add = r.selfContrib + r.spouseContrib, open = prev.totalCorpus, bse = open + add / 2;
        const t = bse > 0 ? (r.totalCorpus - open - add) / bse : null, pc = (x) => x == null ? '—' : `${(x * 100).toFixed(1)}%`;
        ret = `<b class="${t !== null && t < 0 ? 'c-rose' : ''}">${pc(t)}</b><div class="muted" style="font-size:.68rem">core ${pc(r.actualCoreRate)} · sat ${pc(r.actualSatRate)}</div>`;
        const dv = r.totalCorpus - b.totalCorpus;
        diff = `<span class="${dv >= 0 ? 'c-growth' : 'c-rose'}">${dv >= 0 ? '+' : '−'}${cr(Math.abs(dv))}</span>`;
        tot = `<b>${full(r.totalCorpus)}</b>`;
      }
      h += `<tr data-yr="${yr}" class="${edited ? 'pending' : ''}">
        <td><b>Year ${yr}</b><div class="muted" style="font-size:.68rem">${periodLabel(start, yr)}${rec && rec.source === 'hub' ? ' · from Hub' : ''}</div></td>
        <td>${full(b.selfContrib + b.spouseContrib)}</td>
        <td><input type="number" class="form-control form-control-sm" min="0" step="1000" data-k="invested" value="${val('invested')}" placeholder="${Math.round(b.selfContrib + b.spouseContrib)}"></td>
        <td>${full(b.totalCorpus)}</td>
        <td><input type="number" class="form-control form-control-sm" min="0" step="1000" data-k="coreValue" value="${val('coreValue')}" placeholder="${Math.round(r.coreClose)}"></td>
        <td><input type="number" class="form-control form-control-sm" min="0" step="1000" data-k="satValue" value="${val('satValue')}" placeholder="${Math.round(r.satClose)}"></td>
        <td>${tot}</td><td>${ret}</td><td>${diff}</td>
        <td class="text-nowrap"><button class="btn btn-sm btn-outline-info py-0" data-act="hub" title="Fill from the Hub's Investments">Fill from Hub</button>
          <button class="btn btn-sm btn-primary py-0" data-act="save" ${edited ? '' : 'disabled'}>Save</button>
          ${rec ? '<button class="btn btn-sm btn-outline-danger py-0" data-act="del">×</button>' : ''}</td></tr>`;
    }
    html('actBody', u ? h : '<tr><td colspan="10" class="muted text-center py-3">Open or create a user to record year-end values.</td></tr>');
    drawReview(base.yearlyRows, rev.yearlyRows, review.latestActualYear, g);
  }

  function drawReview(planRows, revRows, latest, g) {
    const H = Math.max(1, Math.min(60, g.years)), plan = planRows.filter(r => r.year <= H), rev = revRows.filter(r => r.year <= H), cut = Math.min(latest, H);
    const ds = [
      { label: 'Original plan', data: plan.map(r => ({ x: r.year, y: r.totalCorpus })), borderColor: C.muted, borderDash: [4, 4], pointRadius: 0, borderWidth: 1.6 },
      { label: 'Actual + revised', data: rev.map(r => ({ x: r.year, y: r.totalCorpus })), borderColor: C.growth, borderWidth: 2.4,
        pointRadius: rev.map(r => (r.year >= 1 && r.year <= cut && state.actuals[r.year]) ? 4 : 0), pointBackgroundColor: C.growth,
        segment: { borderDash: (ctx) => ctx.p0.parsed.x >= cut && cut > 0 ? [7, 4] : undefined } },
      { label: `Goal ${cr(g.target)}`, data: [{ x: 0, y: g.target }, { x: H, y: g.target }], borderColor: C.gold, borderDash: [6, 4], pointRadius: [0, 5], pointBackgroundColor: C.gold, borderWidth: 1.4 }
    ];
    if (state.charts.review) state.charts.review.destroy();
    state.charts.review = new Chart($('reviewChart'), {
      type: 'line', data: { datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: { legend: { position: 'top', labels: { boxWidth: 12 } }, tooltip: { callbacks: { title: (it) => `Year ${it[0].parsed.x}`, label: (it) => `${it.dataset.label.split(' ₹')[0]}: ${cr(it.raw.y)}` } } },
        scales: { x: { type: 'linear', min: 0, max: H, grid: { color: C.line } }, y: { beginAtZero: true, ticks: { callback: moneyTick }, grid: { color: C.line } } } }
    });
  }

  async function saveRow(yr, source) {
    const u = activeUser(); if (!u) return;
    const tr = document.querySelector(`#actBody tr[data-yr="${yr}"]`);
    const rd = (k) => tr.querySelector(`input[data-k="${k}"]`).value.trim();
    const body = { invested: rd('invested'), coreValue: rd('coreValue'), satValue: rd('satValue'), source: source || (state.pending[yr] && state.pending[yr]._source) || 'manual' };
    if (body.coreValue === '' || body.satValue === '') { toast(`Enter both the core and the satellite value for year ${yr}`, false); return; }
    try {
      await api('PUT', `/api/cc/users/${encodeURIComponent(u.userId)}/actuals/${yr}`, body);
      state.actuals[yr] = { invested: body.invested === '' ? null : Number(body.invested), coreValue: Number(body.coreValue), satValue: Number(body.satValue), recordedAt: new Date().toISOString(), source: body.source };
      u.actualsHistory = JSON.parse(JSON.stringify(state.actuals)); u.updatedAt = new Date().toISOString();
      delete state.pending[yr];
      updateAll();
      toast(`Year ${yr} saved for ${u.name}${body.invested === '' ? ' (invested taken as planned)' : ''}`);
    } catch (e) { toast(e.message, false); }
  }

  async function fillFromHub(yr) {
    const u = activeUser(); if (!u) return;
    try {
      const f = await api('GET', `/api/cc/users/${encodeURIComponent(u.userId)}/hub/${yr}`);
      if (!f.hasHoldings && f.invested === null) { toast(`No investments found in the Hub for ${f.period}`, false); html('hubNote', ''); return; }
      state.pending[yr] = Object.assign(state.pending[yr] || {}, { invested: f.invested !== null ? Math.round(f.invested) : '', coreValue: Math.round(f.coreValue), satValue: Math.round(f.satValue), _source: 'hub' });
      updateReview(engineParams());
      html('hubNote', `Year ${yr} (${esc(f.period)}) filled from the Hub — ${f.trades} trade(s); check and press Save.` + (f.notes.length ? '<br>• ' + f.notes.map(esc).join('<br>• ') : ''));
    } catch (e) { toast(e.message, false); }
  }

  // ── Youngster lab ───────────────────────────────────────────────────────
  function syncYearSlider(id, H) {
    const el = $(id), oldMax = parseInt(el.max, 10) || H, atMax = (parseInt(el.value, 10) || 0) >= oldMax;
    el.max = Math.max(1, H); if (atMax || parseInt(el.value, 10) > H) el.value = H;
  }
  function applyYoung(v) {
    $('yAge').value = v.age; updateYoung();
    $('yMonthly').value = v.monthly; $('yStepOn').checked = v.on; setMode('y', v.mode, false);
    $('yStep').value = v.pct; $('yStepAmt').value = v.amt; $('yStepStop').value = v.stop; $('yAddStop').value = Math.min(v.add, parseInt($('yAddStop').max, 10));
    $('yAddStopMonths').value = v.addMonths; $('yAlloc').value = v.alloc; $('yCore').value = v.core; $('ySat').value = v.sat;
    updateYoung();
  }
  function updateYoung() {
    const age = int('yAge', 21), target = 70, H = Math.max(1, target - age);
    syncYearSlider('yStepStop', H); syncYearSlider('yAddStop', H);
    const monthly = Math.max(0, num('yMonthly', 10000)), on = $('yStepOn').checked, mode = state.mode.y;
    const pct = on ? num('yStep', 5) : 0, amt = Math.max(0, num('yStepAmt', 0));
    const stopRaw = int('yStepStop', 10), addRaw = int('yAddStop', H);
    const stopY = stopRaw >= H ? 999 : stopRaw, addY = addRaw >= H ? 999 : addRaw;
    $('yAddStopMonths').disabled = addY >= H;
    const addM = addY >= H ? 0 : Math.max(0, Math.min(11, int('yAddStopMonths', 0)));
    const alloc = Math.max(0, Math.min(100, num('yAlloc', 70))), yc = num('yCore', 17), ys = num('ySat', 27), rate = (alloc * yc + (100 - alloc) * ys) / 100;
    set('dyAge', `${age} yrs`); set('yHorizon', `${H} years to 70`); set('dyStep', fmtPct(pct / 100));
    $('yStepBox').classList.toggle('is-off', !on);
    html('yEquiv', on ? stepEquiv(monthly, mode, pct / 100, amt, Math.min(stopY, H), Math.min(addY, H)) : 'Step-up is off: the SIP stays flat.');
    set('dyAlloc', `${alloc}% / ${100 - alloc}%`); set('dyCore', `${yc.toFixed(1)}%`); set('dySat', `${ys.toFixed(1)}%`);
    $('yBarCore').style.width = `${alloc}%`; $('yBarSat').style.width = `${100 - alloc}%`;
    set('hyReturn', `Core ${alloc}% / Satellite ${100 - alloc}% · blend ${rate.toFixed(1)}%`);
    set('yAgeNow', age); set('yAgeStart', age);
    const yrs = (n) => `${n} yr${n === 1 ? '' : 's'}`;
    set('dyStepStop', !on ? '—' : stopY >= H ? 'Never' : yrs(stopRaw));
    set('hyStepStop', !on ? 'Step-up is off' : stopY >= H ? 'Keeps rising every year to 70' : `Rises until year ${stopRaw} (age ${age + stopRaw}), then stays flat`);
    set('dyAddStop', addY >= H ? 'Until 70' : yrs(addRaw) + (addM ? ` ${addM} mo` : ''));
    set('hyAddStop', addY >= H ? 'Investing every year to 70' : `SIPs end after ${yrs(addRaw)}${addM ? ' ' + addM + ' months' : ''} (age ${age + addRaw}); the corpus keeps compounding to 70`);
    document.querySelectorAll('.y-chip').forEach(c => c.classList.toggle('active', Number(c.dataset.val) === monthly));

    const r = CE.calculateYoungsterWealth({ currentAge: age, targetAge: target, monthly, stepUpEnabled: on, stepUpPct: pct, stepUpMode: mode, stepUpAmt: amt,
      stepUpStopYears: stopY, additionsStopYears: addY, additionsStopMonths: addM, rate, coreRate: yc, satRate: ys, coreAlloc: alloc, delayYearsList: [3, 6, 9] });
    const ageKpi = (k, c, m, lbl) => {
      if (c !== null && c !== undefined) { set(k, cr(c)); set(k + 'x', CE.formatINR(c, { decimals: 0 })); set(k + 'm', m > 0 ? `${m.toFixed(0)}× invested` : ''); }
      else { set(k, '—'); set(k + 'x', lbl); set(k + 'm', ''); }
    };
    ageKpi('y50', r.corpusAt50, r.multipleAt50, 'You start after 50'); ageKpi('y60', r.corpusAt60, r.multipleAt60, 'You start after 60'); ageKpi('y70', r.corpusAt70, r.multipleAt70, '');
    set('yInv', cr(r.totalInvested));
    const active = Math.min(H, addY);
    set('yInvSub', active >= H ? `Over ${H} years, age ${age} to 70` : `For ${active} yrs${addM ? ' ' + addM + ' mo' : ''}, age ${age} to ${age + active}`);
    set('yGain', cr(r.wealthGain)); set('yGainShare', `${r.corpus > 0 ? (r.wealthGain / r.corpus * 100).toFixed(1) : '0'}% of wealth`);
    set('yMult', r.totalInvested > 0 ? `${r.multiple.toFixed(0)}× invested` : '—');
    const d3 = r.delayScenarios.find(s => s.delayYears === 3);
    set('yDelay', d3 ? `−${d3.pctLost.toFixed(1)}%` : 'n/a'); set('yDelayLoss', d3 ? `${cr(d3.wealthLost, 1)} less at 70` : 'Too close to 70');
    // doubling table
    const cw = alloc / 100, rc = yc / 100, rs = ys / 100, mix = (t) => cw * Math.pow(1 + rc, t) + (1 - cw) * Math.pow(1 + rs, t);
    let lo = 0, hi = 200; for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (mix(m) >= 2) hi = m; else lo = m; }
    const mixD = mix(200) >= 2 ? (lo + hi) / 2 : null;
    html('yDblBody', [
      { n: 'Fixed deposit', r: '6.5%', d: Math.log(2) / Math.log(1.065), v: 1e5 * Math.pow(1.065, 30) },
      { n: 'Nifty 50 index', r: '13%', d: Math.log(2) / Math.log(1.13), v: 1e5 * Math.pow(1.13, 30) },
      { n: 'Core+SAT', r: `${rate.toFixed(1)}%`, d: mixD, v: 1e5 * mix(30), me: true }
    ].map(x => `<tr class="${x.me ? 'hl' : ''}"><td>${x.me ? '<b>' + x.n + '</b>' : x.n}</td><td>${x.r}</td><td>${x.d ? x.d.toFixed(1) + ' yrs' : '—'}</td><td>${cr(x.v)}</td></tr>`).join(''));
    set('yDblNote', mixD ? `Core+SAT = ${alloc}% core at ${yc.toFixed(1)}% and ${100 - alloc}% satellite at ${ys.toFixed(1)}% (blend ${rate.toFixed(1)}%). It first doubles in ${mixD.toFixed(2)} years, and a lump sum doubles about ${Math.log2(mix(H)).toFixed(1)} times between age ${age} and 70.` : 'Choose returns above zero.');
    // delay cards
    const rowsH = (a, b) => `<div class="d-flex justify-content-between"><span class="muted">At 50</span><b>${a !== null ? cr(a) : '—'}</b></div><div class="d-flex justify-content-between"><span class="muted">At 60</span><b>${b !== null ? cr(b) : '—'}</b></div>`;
    let ch = `<div class="col-6 col-lg-3"><div class="yc best"><div class="d-flex justify-content-between"><b>Start today, age ${r.currentAge}</b><span class="badge bg-success">Best</span></div>${rowsH(r.corpusAt50, r.corpusAt60)}
      <div class="d-flex justify-content-between mt-1"><span>At 70</span><b class="c-growth">${cr(r.corpus)}</b></div><div class="bar2 my-1"><div style="width:100%;background:var(--growth)"></div></div>
      <div class="muted" style="font-size:.72rem">Invested ${cr(r.totalInvested)} · ${r.multiple.toFixed(0)}× back</div></div></div>`;
    r.delayScenarios.forEach(dl => {
      const keep = Math.max(0, 100 - dl.pctLost);
      ch += `<div class="col-6 col-lg-3"><div class="yc"><div class="d-flex justify-content-between"><b>Wait ${dl.delayYears} yr${dl.delayYears > 1 ? 's' : ''}, age ${dl.startAge}</b><span class="badge bg-danger">−${dl.pctLost.toFixed(0)}%</span></div>${rowsH(dl.corpusAt50, dl.corpusAt60)}
        <div class="d-flex justify-content-between mt-1"><span>At 70</span><b>${cr(dl.corpus)}</b></div><div class="bar2 my-1"><div style="width:${keep}%;background:var(--muted)"></div></div>
        <div style="font-size:.72rem"><span class="c-rose">${cr(dl.wealthLost, 1)} less</span> <span class="muted">· invested ${cr(dl.totalInvested)}</span></div></div></div>`;
    });
    html('yCards', ch);
    html('yTimeline', r.yearlyRows.map(x => {
      const sp = x.age === 50 || x.age === 60 || x.age === target;
      return `<tr class="${sp ? 'hl' : ''}"><td><b>${x.age}</b>${sp ? ` <span class="badge bg-secondary">Age ${x.age}</span>` : ''}</td><td>${x.year}</td>
        <td>${x.monthly > 0 && x.months > 0 ? CE.formatINR(x.monthly, { decimals: 0 }) + (x.months < 12 ? ` <span class="muted">× ${x.months} mo</span>` : '') : '<span class="muted">—</span>'}</td>
        <td>${x.annualAdd > 0 ? cr(x.annualAdd) : '<span class="muted">—</span>'}</td>
        <td class="${x.annualInterest > x.annualAdd ? 'c-gold' : ''}">${cr(x.annualInterest)}</td><td>${cr(x.totalInvested)}</td>
        <td class="c-growth">${cr(x.corpus)}</td><td>${x.totalInvested > 0 ? (x.corpus / x.totalInvested).toFixed(1) : '0.0'}×</td></tr>`;
    }).join(''));
  }

  // ── Users ───────────────────────────────────────────────────────────────
  const userModal = new bootstrap.Modal($('userModal')), usersModal = new bootstrap.Modal($('usersModal'));
  let editing = null;
  function slug(s) { return String(s || '').toLowerCase().trim().replace(/\s+/g, '.').replace(/[^a-z0-9._-]/g, '').replace(/^[._-]+|[._-]+$/g, '').slice(0, 32); }
  function openUserModal(id) {
    editing = id || null;
    const u = id ? state.users[id] : null;
    set('umTitle', u ? `Edit ${u.name}` : 'New user');
    $('umName').value = u ? u.name : ''; $('umId').value = u ? u.userId : '';
    $('umTarget').value = u ? u.goal.target : 1e8; $('umYears').value = u ? u.goal.years : 20; $('umStart').value = u ? u.startYear : new Date().getFullYear();
    $('umTplBox').style.display = u ? 'none' : '';
    $('umTpl').innerHTML = '<option value="__default__">Standard plan</option>' + (state.activeId ? `<option value="__current__" selected>Current Core engine inputs</option>` : '') +
      Object.values(state.users).map(x => `<option value="${esc(x.userId)}">${esc(x.name)}’s plan</option>`).join('');
    set('umMsg', ''); userModal.show();
  }
  $('umName').addEventListener('input', () => { if (!editing && !$('umId').dataset.touched) $('umId').value = slug($('umName').value); });
  $('umId').addEventListener('input', () => { $('umId').dataset.touched = '1'; });
  document.querySelectorAll('.um-chip').forEach(c => c.addEventListener('click', () => { $('umTarget').value = c.dataset.goal; }));
  $('umSave').addEventListener('click', async () => {
    const body = { name: $('umName').value.trim(), userId: slug($('umId').value || $('umName').value), startYear: int('umStart', new Date().getFullYear()) };
    const goal = { target: num('umTarget', 1e8), years: int('umYears', 20) };
    try {
      if (editing) {
        const cur = state.users[editing];
        const j = await api('PUT', `/api/cc/users/${encodeURIComponent(editing)}`, Object.assign(body, { goal: Object.assign({}, cur.goal, goal) }));
        await reloadUsers(j.user.userId); userModal.hide(); loadUser(j.user.userId); toast(`Saved ${j.user.name}`);
      } else {
        const tpl = $('umTpl').value;
        Object.assign(body, { goal, template: tpl === '__current__' ? null : tpl, params: tpl === '__current__' ? readParams() : null });
        const j = await api('POST', '/api/cc/users', body);
        await reloadUsers(j.user.userId); userModal.hide(); loadUser(j.user.userId); toast(`Created ${j.user.name} (${j.user.userId})`);
      }
    } catch (e) { set('umMsg', e.message); }
  });
  function renderUsersList() {
    html('usersBody', Object.values(state.users).map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.userId)}</td><td>${cr(u.goal.target)} in ${u.goal.years} yrs</td>
      <td>${Object.keys(u.actualsHistory || {}).length}</td><td>${u.updatedAt ? u.updatedAt.slice(0, 10) : ''}</td>
      <td><button class="btn btn-sm btn-outline-primary py-0" data-open="${esc(u.userId)}">Open</button>
          <button class="btn btn-sm btn-outline-danger py-0" data-del="${esc(u.userId)}">Delete</button></td></tr>`).join(''));
  }
  $('usersBody').addEventListener('click', async (e) => {
    const o = e.target.closest('[data-open]'), d = e.target.closest('[data-del]');
    if (o) { usersModal.hide(); loadUser(o.dataset.open); }
    if (d) {
      const u = state.users[d.dataset.del];
      if (Object.keys(state.users).length < 2) { toast('Keep at least one user', false); return; }
      if (!confirm(`Delete ${u.name} (${u.userId}) with all year-end records?`)) return;
      await api('DELETE', `/api/cc/users/${encodeURIComponent(u.userId)}`);
      await reloadUsers(); renderUsersList();
      if (state.activeId === u.userId) loadUser(Object.keys(state.users)[0]);
      toast(`Deleted ${u.name}`);
    }
  });
  $('importFile').addEventListener('change', async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    const j = await fetch('/planner/import', { method: 'POST', body: fd }).then(r => r.json());
    set('importMsg', j.msg || ''); e.target.value = '';
    if (j.ok) { await reloadUsers(state.activeId); renderUsersList(); if (state.activeId) loadUser(state.activeId); }
  });

  // ── Wire up ─────────────────────────────────────────────────────────────
  function showTab(t) {
    state.tab = t;
    document.querySelectorAll('#plTabs .nav-link').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    document.querySelectorAll('.pl-tab').forEach(p => { p.style.display = p.id === `tab-${t}` ? '' : 'none'; });
    try { localStorage.setItem('planner_tab', t); } catch (e) { /* ignore */ }
    if (t === 'young') updateYoung(); else updateAll();
  }
  document.querySelectorAll('#plTabs .nav-link').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  document.querySelectorAll('#tab-core input, #tab-core select').forEach(el => el.addEventListener('input', updateAll));
  document.querySelectorAll('[data-who-tab]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-who-tab]').forEach(x => x.classList.toggle('active', x === b));
    document.querySelectorAll('.who-pane').forEach(p => { p.style.display = p.dataset.who === b.dataset.whoTab ? '' : 'none'; });
  }));
  document.querySelectorAll('[data-mode-for] button').forEach(b => b.addEventListener('click', () => {
    const who = b.parentElement.dataset.modeFor; setMode(who, b.dataset.mode, true);
    if (who === 'y') updateYoung(); else updateAll();
  }));
  $('scaleLin').addEventListener('click', () => { state.log = false; $('scaleLin').classList.add('active'); $('scaleLog').classList.remove('active'); updateAll(); });
  $('scaleLog').addEventListener('click', () => { state.log = true; $('scaleLog').classList.add('active'); $('scaleLin').classList.remove('active'); updateAll(); });
  ['goalTarget', 'goalYears'].forEach(id => $(id).addEventListener('input', updateAll));
  $('goalRet').addEventListener('input', () => { state.goalTouched = true; updateAll(); });
  document.querySelectorAll('.goal-chip').forEach(c => c.addEventListener('click', () => { $('goalTarget').value = c.dataset.goal; updateAll(); }));
  $('goalRetReset').addEventListener('click', () => { state.goalTouched = false; updateAll(); });
  $('goalRetApply').addEventListener('click', () => {
    const p = engineParams(), rates = CE.ratesForBlended(num('goalRet') / 100, p);
    $('coreRet').value = Math.min(32, Math.max(8, (rates.coreReturn * 100).toFixed(1))); $('satRet').value = Math.min(45, Math.max(15, (rates.satReturn * 100).toFixed(1)));
    state.goalTouched = false; updateAll(); toast('Core and satellite CAGR changed in the Core engine — press Save plan to keep it');
  });
  $('sensBody').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-ret]'); if (!tr) return; $('goalRet').value = tr.dataset.ret; state.goalTouched = true; updateAll(); });
  $('btnSchedCsv').addEventListener('click', () => {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([scheduleCsv()], { type: 'text/csv' }));
    a.download = `schedule-${state.activeId || 'plan'}.csv`; a.click();
  });
  $('btnSchedCopy').addEventListener('click', async () => { try { await navigator.clipboard.writeText(scheduleCsv().replace(/,/g, '\t')); toast('Schedule copied — paste into Excel'); } catch (e) { toast('Copy not allowed by the browser', false); } });

  $('actBody').addEventListener('input', (e) => {
    const inp = e.target.closest('input[data-k]'); if (!inp) return;
    const tr = inp.closest('tr'), yr = parseInt(tr.dataset.yr, 10);
    state.pending[yr] = state.pending[yr] || {}; state.pending[yr][inp.dataset.k] = inp.value;
    tr.classList.add('pending'); tr.querySelector('[data-act="save"]').disabled = false;
  });
  $('actBody').addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.closest('input[data-k]')) { e.preventDefault(); saveRow(parseInt(e.target.closest('tr').dataset.yr, 10)); } });
  $('actBody').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-act]'); if (!b) return;
    const yr = parseInt(b.closest('tr').dataset.yr, 10), u = activeUser();
    if (b.dataset.act === 'save') saveRow(yr);
    if (b.dataset.act === 'hub') fillFromHub(yr);
    if (b.dataset.act === 'del') {
      if (!confirm(`Delete the year ${yr} record for ${u.name}?`)) return;
      await api('DELETE', `/api/cc/users/${encodeURIComponent(u.userId)}/actuals/${yr}`);
      delete state.actuals[yr]; delete state.pending[yr]; u.actualsHistory = JSON.parse(JSON.stringify(state.actuals));
      updateAll(); toast(`Year ${yr} record deleted`);
    }
  });
  $('btnClearActuals').addEventListener('click', async () => {
    const u = activeUser(); if (!u || !confirm(`Delete ALL year-end records for ${u.name}?`)) return;
    await api('DELETE', `/api/cc/users/${encodeURIComponent(u.userId)}/actuals`);
    state.actuals = {}; state.pending = {}; u.actualsHistory = {}; updateAll(); toast('All records deleted');
  });

  document.querySelectorAll('#tab-young input, #tab-young select').forEach(el => el.addEventListener('input', updateYoung));
  document.querySelectorAll('.y-chip').forEach(c => c.addEventListener('click', () => { $('yMonthly').value = c.dataset.val; updateYoung(); }));

  $('userSel').addEventListener('change', () => {
    if ($('btnSave').classList.contains('dirty') && !confirm('Leave this user without saving the plan changes?')) { $('userSel').value = state.activeId; return; }
    loadUser($('userSel').value);
  });
  $('btnSave').addEventListener('click', async () => {
    const u = activeUser(); if (!u) return;
    try {
      const j = await api('PUT', `/api/cc/users/${encodeURIComponent(u.userId)}`, { params: readParams(), goal: readGoal() });
      state.users[u.userId] = j.user; refreshDirty(); updateAll(); toast(`Saved ${u.name}’s plan and goal`);
    } catch (e) { toast(e.message, false); }
  });
  $('btnNewUser').addEventListener('click', () => openUserModal(null));
  $('btnEditUser').addEventListener('click', () => state.activeId && openUserModal(state.activeId));
  $('btnUsers').addEventListener('click', () => { renderUsersList(); set('importMsg', ''); usersModal.show(); });
  $('btnReset').addEventListener('click', () => {
    if (state.tab === 'core') { if (confirm('Put the Core engine back to the standard plan? (Save plan keeps it for this user.)')) { applyParams(DEFAULTS); updateAll(); } }
    else if (state.tab === 'goal') { const u = activeUser(); applyGoal(u ? u.goal : null); updateAll(); toast('Goal back to the saved goal'); }
    else if (state.tab === 'review') { state.pending = {}; html('hubNote', ''); updateAll(); toast('Unsaved entries discarded — saved records untouched'); }
    else { applyYoung(Y_DEFAULTS); }
  });
  window.addEventListener('beforeunload', (e) => { if ($('btnSave').classList.contains('dirty')) { e.preventDefault(); e.returnValue = ''; } });

  // start
  applyYoung(Y_DEFAULTS);
  let start = null, tab = 'core';
  try { start = localStorage.getItem('planner_active_user'); tab = localStorage.getItem('planner_tab') || 'core'; } catch (e) { /* ignore */ }
  const firstId = state.users[start] ? start : Object.keys(state.users)[0];
  if (firstId) loadUser(firstId); else { applyParams(DEFAULTS); applyGoal(null); }
  const q = new URLSearchParams(location.search).get('tab');
  showTab(['core', 'goal', 'review', 'young'].includes(q) ? q : (['core', 'goal', 'review', 'young'].includes(tab) ? tab : 'core'));
})();
