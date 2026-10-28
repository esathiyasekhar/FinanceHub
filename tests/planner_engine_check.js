/* 1.12 — checks of the Wealth planner engine (static/planner/calculator.js). Run by test_1_12.py with node. */
const CE = require(require('path').resolve(process.argv[2]));
let fails = 0;
const ok = (c, m) => { if (!c) { fails++; console.log('FAIL', m); } };
const near = (a, b, tol = 0.5) => Math.abs(a - b) <= tol;
const base = { coreAlloc: .7, satAlloc: .3, coreReturn: .1, satReturn: .1, maxYears: 60 };

// hand-worked: ₹1 L lump + ₹10,000/mo for 1 year at 10% — lump earns 10,000; SIPs earn 1,20,000 × 10% × ½ = 6,000
let r = CE.calculateSchedule(Object.assign({}, base, { selfLump: 1e5, selfMonthly: 1e4, selfInclude: true, selfStepUp: 0, selfAddStop: 1, horizon: 1 }));
ok(near(r.totalCorpus, 236000), 'hand-worked year 1: ' + r.totalCorpus);
ok(r.yearlyRows[1].selfMonthly === 10000 && r.yearlyRows[1].selfMonths === 12 && r.yearlyRows[1].selfContrib === 120000, 'monthly vs yearly figures');
ok(r.yearlyRows[0].selfLump === 100000 && r.yearlyRows[0].selfContrib === 100000, 'lump sum in year 0');

// step-up 10 % until year 3, SIP 3 years 6 months: 10,000 · 11,000 · 12,100 · 12,100 × 6
r = CE.calculateSchedule(Object.assign({}, base, { selfLump: 0, selfMonthly: 1e4, selfInclude: true, selfStepUp: .1, selfStepUpStop: 3, selfAddStop: 3, selfAddStopMonths: 6, horizon: 6 }));
const m = r.yearlyRows.slice(1, 6).map(x => [Math.round(x.selfMonthly), x.selfMonths]);
ok(JSON.stringify(m) === JSON.stringify([[10000, 12], [11000, 12], [12100, 12], [12100, 6], [0, 0]]), 'step-up and part year ' + JSON.stringify(m));
ok(near(r.totalInvested, 120000 + 132000 + 145200 + 72600), 'invested ' + r.totalInvested);

// ₹ step-up: +1,000 a month each year
r = CE.calculateSchedule(Object.assign({}, base, { selfMonthly: 5000, selfInclude: true, selfStepUpMode: 'amt', selfStepUpAmt: 1000, selfStepUpStop: 10, selfAddStop: 3, horizon: 3 }));
ok(r.yearlyRows[3].selfMonthly === 7000, '₹ step-up');

// spouse: counted only when included; identical inputs give identical results for self and spouse
const sp = { spouseLump: 2e5, spouseMonthly: 15000, spouseStepUp: .1, spouseStepUpStop: 10, spouseAddStop: 10 };
const self = { selfLump: 2e5, selfMonthly: 15000, selfStepUp: .1, selfStepUpStop: 10, selfAddStop: 10 };
const a = CE.calculateSchedule(Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: true }, self, { spouseInclude: false }, sp));
const b = CE.calculateSchedule(Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: false, selfLump: 9e9, selfMonthly: 9e9, spouseInclude: true }, sp));
ok(near(a.totalCorpus, b.totalCorpus, 1), 'self and spouse symmetric (and an excluded self counts nothing): ' + a.totalCorpus + ' vs ' + b.totalCorpus);
const both = CE.calculateSchedule(Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: true, spouseInclude: true }, self, sp));
ok(near(both.totalInvested, a.totalInvested * 2, 1), 'both = twice one');
const sa = CE.analyzeSpouseImpact(Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: true, spouseInclude: true }, self, sp));
ok(near(sa.spouseTotalInvested, a.totalInvested, 1) && near(sa.combinedCorpus, both.totalCorpus, 1), 'spouse impact');
const off = CE.calculateSchedule(Object.assign({}, base, { horizon: 20, selfInclude: true, selfMonthly: 1e4, selfAddStop: 20, spouseInclude: false, spouseLump: 5e5, spouseMonthly: 5e4 }));
ok(off.yearlyRows.every(x => x.spouseContrib === 0), 'excluded spouse adds nothing');

// goal: the SIP and the return it reports really reach the target
const plan = Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: true, selfLump: 1e5, selfMonthly: 1e4, selfStepUp: .1, selfStepUpStop: 10, selfAddStop: 10, spouseInclude: true, spouseMonthly: 5000, spouseAddStop: 10, spouseStepUpStop: 10 });
const g = CE.solveGoal(5e7, 20, plan);
ok(Math.abs(CE.calculateSchedule(Object.assign({}, plan, { selfMonthly: g.requiredMonthlySIP })).totalCorpus - 5e7) / 5e7 < 0.002, 'goal SIP');
ok(Math.abs(CE.calculateSchedule(Object.assign({}, plan, CE.ratesForBlended(g.requiredBlendedReturn, plan))).totalCorpus - 5e7) / 5e7 < 0.001, 'goal return');

// review: year-end values equal to the plan change nothing; a part-year last SIP year still counts as planned SIP
const p0 = CE.calculateSchedule(plan), act = {};
for (let y = 1; y <= 3; y++) act[y] = { invested: p0.yearlyRows[y].totalContrib, coreValue: p0.yearlyRows[y].coreClose, satValue: p0.yearlyRows[y].satClose };
ok(near(CE.reviewActualsAndCorrect(plan, act, 5e7).revisedCorpus, p0.totalCorpus, 1), 'review unchanged');
const plan2 = Object.assign({}, plan, { selfAddStop: 3, selfAddStopMonths: 6 });
const p2 = CE.calculateSchedule(plan2), act2 = {};
for (let y = 1; y <= 3; y++) act2[y] = { invested: p2.yearlyRows[y].totalContrib, coreValue: p2.yearlyRows[y].coreClose, satValue: p2.yearlyRows[y].satClose };
const rv2 = CE.reviewActualsAndCorrect(plan2, act2, 5e7);
ok(rv2.sipMode === 'scale' && rv2.plannedFutureMonthly > 0, 'review part year: ' + rv2.sipMode);
// goal with self switched off: the left-out lump sum must not come back when the solver adds a self SIP
const offPlan = Object.assign({}, base, { coreReturn: .15, satReturn: .25, horizon: 20, selfInclude: false, selfLump: 5e6, selfMonthly: 0,
  selfAddStop: 20, spouseInclude: true, spouseMonthly: 20000, spouseAddStop: 20, spouseStepUpStop: 1 });
const g2 = CE.solveGoal(5e7, 20, offPlan);
ok(g2.currentCorpusAtHorizon < 5e7 && g2.requiredMonthlySIP > 0, 'goal with self off needs a SIP: ' + g2.requiredMonthlySIP);
ok(Math.abs(CE.calculateSchedule(Object.assign({}, offPlan, { selfInclude: true, selfLump: 0, selfMonthly: g2.requiredMonthlySIP })).totalCorpus - 5e7) / 5e7 < 0.002, 'goal SIP with self off reaches the target');
const nobody = CE.solveGoal(5e7, 20, Object.assign({}, offPlan, { spouseInclude: false }));
ok(nobody.requiredBlendedReturn === null && nobody.rateOutOfRange === null, 'nobody included: no rate to solve');
console.log(fails ? `${fails} FAILED` : 'planner engine OK');
process.exit(fails ? 1 : 0);
