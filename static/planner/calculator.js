/**
 * Core + Satellite Compounding Calculator Engine
 * Faithfully replicates Sheet 4 of "R - Compounding Final.xlsx"
 * Plus advanced Goal-Seeking, Actuals Course-Correction, and Spouse Acceleration Analytics.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.CompoundingEngine = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {

  /**
   * Currency & Number Formatting Helpers
   */
  function formatINR(value, options = {}) {
    if (value === null || value === undefined || isNaN(value)) return '₹0';
    const num = Number(value);
    const sign = num < 0 ? '-' : '';
    const abs = Math.abs(num);

    if (options.compact) {
      if (abs >= 1e7) {
        const crVal = abs / 1e7;
        const crFixed = crVal.toFixed(options.decimals !== undefined ? options.decimals : 2);
        const parts = crFixed.split('.');
        let crInt = parts[0];
        const crDec = parts.length > 1 ? '.' + parts[1] : '';
        if (crInt.length > 3) {
          const lastThree = crInt.substring(crInt.length - 3);
          const others = crInt.substring(0, crInt.length - 3);
          crInt = others.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + lastThree;
        }
        return `${sign}₹${crInt}${crDec} Cr`;
      }
      if (abs >= 1e5) {
        return `${sign}₹${(abs / 1e5).toFixed(options.decimals !== undefined ? options.decimals : 2)} L`;
      }
      if (abs >= 1e3) {
        return `${sign}₹${(abs / 1e3).toFixed(options.decimals !== undefined ? options.decimals : 1)} k`;
      }
      return `${sign}₹${abs.toFixed(options.decimals || 0)}`;
    }

    // Standard Indian number format (e.g. 1,00,00,000)
    const fixed = abs.toFixed(options.decimals || 0);
    const parts = fixed.split('.');
    let integerPart = parts[0];
    const decimalPart = parts.length > 1 ? '.' + parts[1] : '';

    if (integerPart.length > 3) {
      const lastThree = integerPart.substring(integerPart.length - 3);
      const otherNumbers = integerPart.substring(0, integerPart.length - 3);
      integerPart = otherNumbers.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + lastThree;
    }

    return `${sign}₹${integerPart}${decimalPart}`;
  }

  function formatPercent(value, decimals = 1) {
    if (value === null || value === undefined || isNaN(value)) return '0.0%';
    return (Number(value) * 100).toFixed(decimals) + '%';
  }

  function formatYears(value, decimals = 2) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'string') return value;
    if (isNaN(value)) return '-';
    return `${Number(value).toFixed(decimals)} yrs`;
  }

  /**
   * Monthly SIP in a given year after step-ups.
   *  mode 'pct': base × (1 + pct)^(steps)        — compounding % step-up
   *  mode 'amt': base + amt × steps              — fixed ₹ added to the monthly SIP each year
   * steps = min(year, stopYear) − 1, so year 1 is the base SIP and the last step-up is in stopYear.
   */
  function steppedMonthly(base, year, stopYear, mode, pct, amt) {
    const steps = Math.max(0, Math.min(year, stopYear) - 1);
    if (mode === 'amt') return Number(base || 0) + Number(amt || 0) * steps;
    return Number(base || 0) * Math.pow(1.0 + Number(pct || 0), steps);
  }

  /**
   * Solve Semi-Annual IRR using Newton-Raphson (Exact match to Sheet 4 formula)
   * Formula:
   * cf[0] = -TotalLumpSum
   * cf[2*y - 1] = -AnnualAdditions[y] (mid-year addition at month 6 of year y)
   * cf[2*y] = 0
   * cf[2*horizon] += TerminalCorpus
   * Solves sum(cf[k] / (1 + r)^k) = 0 for r (semi-annual rate)
   * Annual IRR = (1 + r)^2 - 1
   */
  /**
   * Annual IRR for cash flows at arbitrary times (in years): sum cf·(1+R)^(−t) = 0.
   * With contributions at mid-year (t = y − 0.5) this equals the sheet's semi-annual IRR exactly.
   */
  function solveIRR(flows) {
    const f = flows.filter(x => x.cf !== 0);
    if (!f.some(x => x.cf < 0) || !f.some(x => x.cf > 0)) return 0;
    const npv = (R) => f.reduce((s, x) => s + x.cf * Math.pow(1 + R, -x.t), 0);
    let R = 0.15, ok = false;
    for (let i = 0; i < 100; i++) {
      let v = 0, d = 0;
      for (const x of f) {
        const disc = Math.pow(1 + R, -x.t);
        v += x.cf * disc;
        d -= x.t * x.cf * disc / (1 + R);
      }
      if (Math.abs(d) < 1e-13) break;
      const step = v / d;
      R -= step;
      if (!isFinite(R) || R <= -0.99) break;
      if (Math.abs(step) < 1e-11) { ok = true; break; }
    }
    if (!ok || !isFinite(R) || R <= -0.99 || R > 20) {
      let lo = -0.95, hi = 20;
      for (let i = 0; i < 200; i++) {
        const mid = (lo + hi) / 2;
        if (npv(mid) > 0) lo = mid; else hi = mid;
      }
      R = (lo + hi) / 2;
    }
    return isFinite(R) ? R : 0;
  }

  function solveSemiAnnualIRR(lumpSum, annualAdditions, terminalCorpus, horizonYears) {
    if (lumpSum <= 0 && (!annualAdditions || annualAdditions.every(v => v <= 0))) {
      return 0;
    }
    const n = 2 * horizonYears;
    const cfs = new Float64Array(n + 1);
    cfs[0] = -lumpSum;
    for (let y = 1; y <= horizonYears; y++) {
      if (annualAdditions && annualAdditions[y - 1]) {
        cfs[2 * y - 1] = -annualAdditions[y - 1];
      }
    }
    cfs[n] += terminalCorpus;

    // Fast Newton-Raphson solver
    let r = 0.10; // initial guess for 6-month rate
    let converged = false;
    for (let iter = 0; iter < 100; iter++) {
      let fVal = 0.0;
      let fPrime = 0.0;
      for (let k = 0; k <= n; k++) {
        if (cfs[k] !== 0) {
          const disc = Math.pow(1.0 + r, -k);
          fVal += cfs[k] * disc;
          if (k > 0) {
            fPrime -= k * cfs[k] * disc / (1.0 + r);
          }
        }
      }
      if (Math.abs(fPrime) < 1e-13) break;
      const step = fVal / fPrime;
      r -= step;
      if (Math.abs(step) < 1e-10) {
        converged = true;
        break;
      }
    }

    // Robust bisection fallback if Newton-Raphson diverges or produces invalid rate
    if (!converged || isNaN(r) || r <= -0.5 || r > 5.0) {
      let low = -0.49;
      let high = 5.0;
      for (let iter = 0; iter < 60; iter++) {
        const mid = (low + high) / 2.0;
        let npv = 0.0;
        for (let k = 0; k <= n; k++) {
          if (cfs[k] !== 0) npv += cfs[k] * Math.pow(1.0 + mid, -k);
        }
        if (Math.abs(npv) < 1e-4) { r = mid; break; }
        if (npv > 0) low = mid; else high = mid;
        r = mid;
      }
    }

    if (isNaN(r) || r <= -1) return 0;
    return Math.pow(1.0 + r, 2) - 1.0;
  }

  /**
   * Main Compounding Engine: Replicates Sheet 4 calculations exactly
   * Supports custom past actual returns for each year.
   */
  function calculateSchedule(params = {}, actuals = {}) {
    const defaultParams = {
      selfLump: 500000,
      spouseLump: 0,
      coreAlloc: 0.70,
      satAlloc: 0.30,
      coreReturn: 0.20,
      satReturn: 0.30,
      selfMonthly: 25000,
      spouseMonthly: 0,
      selfInclude: true,
      spouseInclude: false,
      horizon: 30,
      selfStepUp: 0.10,
      spouseStepUp: 0.10,
      selfStepUpMode: 'pct', // 'pct' or 'amt'
      spouseStepUpMode: 'pct',
      selfStepUpAmt: 0,      // ₹ added to monthly SIP each year (amt mode)
      spouseStepUpAmt: 0,
      selfStepUpStop: 7,   // Excel Sheet 4 C13 default: 7 yrs
      spouseStepUpStop: 30, // Excel Sheet 4 D13 default: 30 yrs
      selfAddStop: 7,      // Excel Sheet 4 C14 default: 7 yrs
      selfAddStopMonths: 0,   // extra months of SIP after selfAddStop full years (0–11)
      spouseAddStopMonths: 0,
      spouseAddStop: 30,   // Excel Sheet 4 D14 default: 30 yrs
      maxYears: 60
    };

    const p = Object.assign({}, defaultParams, params);

    // Normalize allocations to sum to 1
    const totalAlloc = p.coreAlloc + p.satAlloc;
    const coreAlloc = totalAlloc > 0 ? p.coreAlloc / totalAlloc : 0.7;
    const satAlloc = totalAlloc > 0 ? p.satAlloc / totalAlloc : 0.3;

    const maxYears = p.maxYears || 60;
    const selfInitialLump = p.selfInclude ? Number(p.selfLump || 0) : 0;   // "Include my contributions" covers the lump sum too (1.12)
    const spouseInitialLump = p.spouseInclude ? Number(p.spouseLump || 0) : 0;
    const totalLump = selfInitialLump + spouseInitialLump;

    const coreOpen = new Float64Array(maxYears + 1);
    const coreAdd = new Float64Array(maxYears + 1);
    const coreRet = new Float64Array(maxYears + 1);
    const coreClose = new Float64Array(maxYears + 1);

    const satOpen = new Float64Array(maxYears + 1);
    const satAdd = new Float64Array(maxYears + 1);
    const satRet = new Float64Array(maxYears + 1);
    const satClose = new Float64Array(maxYears + 1);

    const totalCorpus = new Float64Array(maxYears + 1);
    const totalInvested = new Float64Array(maxYears + 1);
    const multipleInvested = new Float64Array(maxYears + 1);
    const selfContrib = new Float64Array(maxYears + 1);
    const spouseContrib = new Float64Array(maxYears + 1);
    const selfMonthlyAmt = new Float64Array(maxYears + 1), spouseMonthlyAmt = new Float64Array(maxYears + 1);
    const selfMonthsIn = new Array(maxYears + 1).fill(0), spouseMonthsIn = new Array(maxYears + 1).fill(0);
    const annualReturnsEarned = new Float64Array(maxYears + 1);
    const isActualYear = new Array(maxYears + 1).fill(false);
    const actualCoreRates = new Array(maxYears + 1).fill(null);
    const actualSatRates = new Array(maxYears + 1).fill(null);

    // Year 0
    selfContrib[0] = selfInitialLump;
    spouseContrib[0] = spouseInitialLump;
    totalInvested[0] = totalLump;
    coreClose[0] = totalLump * coreAlloc;
    satClose[0] = totalLump * satAlloc;
    totalCorpus[0] = coreClose[0] + satClose[0];
    multipleInvested[0] = totalInvested[0] > 0 ? totalCorpus[0] / totalInvested[0] : 0.0;

    const contribFlows = [];

    // Years 1 to maxYears
    for (let yr = 1; yr <= maxYears; yr++) {
      // Self Annual Contribution
      // Months of SIP in this year: 12 while running, a part-year in the stop year, 0 after
      const monthsIn = (stopYrs, stopMonths) => {
        if (yr <= stopYrs) return 12;
        const m = Math.max(0, Math.min(11, Math.round(Number(stopMonths) || 0)));
        return (yr === stopYrs + 1) ? m : 0;
      };
      // Average share of the year a contribution is invested: 1/2 for a full year of SIPs,
      // 1 − m/24 for m months at the start of the year (consistent with the sheet's r/2 rule)
      const weightFor = (m) => (m > 0 ? 1 - m / 24 : 0.5);

      let sCon = 0.0;
      let sMonths = 0;
      if (p.selfInclude) {
        sMonths = monthsIn(p.selfAddStop, p.selfAddStopMonths);
        if (sMonths > 0) {
          selfMonthlyAmt[yr] = steppedMonthly(p.selfMonthly, yr, p.selfStepUpStop, p.selfStepUpMode, p.selfStepUp, p.selfStepUpAmt);
          sCon = selfMonthlyAmt[yr] * sMonths;
        }
      }
      // Course-correction override: change ONLY future years' self SIP (past years already happened)
      if (p.selfFutureFromYear && yr >= p.selfFutureFromYear) {
        if (p.selfFutureMonthly !== undefined && p.selfFutureMonthly !== null) {
          // Restart mode: flat monthly SIP from fromYear through the horizon
          sCon = yr <= p.horizon ? Number(p.selfFutureMonthly) * 12.0 : 0.0;
          sMonths = sCon > 0 ? 12 : 0;
          selfMonthlyAmt[yr] = sCon > 0 ? Number(p.selfFutureMonthly) : 0;
        } else if (p.selfFutureFactor !== undefined && p.selfFutureFactor !== null) {
          // Scale mode: keep the planned step-up path, scaled by a factor
          sCon = sCon * Number(p.selfFutureFactor);
          selfMonthlyAmt[yr] = selfMonthlyAmt[yr] * Number(p.selfFutureFactor);
        }
      }
      selfContrib[yr] = sCon;

      // Spouse Annual Contribution
      let spCon = 0.0;
      let spMonths = 0;
      if (p.spouseInclude) {
        spMonths = monthsIn(p.spouseAddStop, p.spouseAddStopMonths);
        if (spMonths > 0) {
          spouseMonthlyAmt[yr] = steppedMonthly(p.spouseMonthly, yr, p.spouseStepUpStop, p.spouseStepUpMode, p.spouseStepUp, p.spouseStepUpAmt);
          spCon = spouseMonthlyAmt[yr] * spMonths;
        }
      }
      selfMonthsIn[yr] = sCon > 0 ? sMonths : 0; spouseMonthsIn[yr] = spCon > 0 ? spMonths : 0;
      let sW = weightFor(sMonths), spW = weightFor(spMonths);

      const act = actuals ? actuals[yr] : null;
      // Actual amount invested this year replaces the planned SIPs (split self/spouse pro rata)
      if (act && act.invested !== undefined && act.invested !== null && act.invested !== '') {
        const inv = Math.max(0, Number(act.invested) || 0);
        const planned = sCon + spCon;
        if (planned > 0) { sCon = inv * (sCon / planned); spCon = inv * (spCon / planned); }
        else { sCon = inv; spCon = 0; }
        selfMonthlyAmt[yr] = selfMonthsIn[yr] ? sCon / selfMonthsIn[yr] : 0; spouseMonthlyAmt[yr] = spouseMonthsIn[yr] ? spCon / spouseMonthsIn[yr] : 0;
        sW = 0.5; spW = 0.5;
      }
      selfContrib[yr] = sCon;
      spouseContrib[yr] = spCon;

      const totalAnnualAdd = sCon + spCon;
      const weightedAdd = sCon * sW + spCon * spW;   // contributions × share of year invested
      contribFlows.push({ t: yr - sW, cf: sCon, yr: yr }, { t: yr - spW, cf: spCon, yr: yr });

      // Check if actual performance rates are provided for this year
      let yrCoreReturn = Number(p.coreReturn);
      let yrSatReturn = Number(p.satReturn);

      if (act && (act.coreReturn != null || act.satReturn != null || act.blendedReturn != null)) {
        isActualYear[yr] = true;
        if (actuals[yr].coreReturn !== undefined && actuals[yr].coreReturn !== null) {
          yrCoreReturn = Number(actuals[yr].coreReturn);
          actualCoreRates[yr] = yrCoreReturn;
        }
        if (actuals[yr].satReturn !== undefined && actuals[yr].satReturn !== null) {
          yrSatReturn = Number(actuals[yr].satReturn);
          actualSatRates[yr] = yrSatReturn;
        }
        // If blended actual is passed:
        if (actuals[yr].blendedReturn !== undefined && actuals[yr].blendedReturn !== null) {
          // distribute proportionally or apply equally
          const blend = Number(actuals[yr].blendedReturn);
          yrCoreReturn = blend;
          yrSatReturn = blend;
          actualCoreRates[yr] = blend;
          actualSatRates[yr] = blend;
        }
      }

      // Core Portfolio
      coreOpen[yr] = coreClose[yr - 1];
      coreAdd[yr] = totalAnnualAdd * coreAlloc;
      coreRet[yr] = (coreOpen[yr] * yrCoreReturn) + (weightedAdd * coreAlloc * yrCoreReturn);
      coreClose[yr] = coreOpen[yr] + coreAdd[yr] + coreRet[yr];

      // Satellite Portfolio
      satOpen[yr] = satClose[yr - 1];
      satAdd[yr] = totalAnnualAdd * satAlloc;
      satRet[yr] = (satOpen[yr] * yrSatReturn) + (weightedAdd * satAlloc * yrSatReturn);
      satClose[yr] = satOpen[yr] + satAdd[yr] + satRet[yr];

      // Actual year-end values: the books win. Growth = close − open − added;
      // the return shown is the Modified Dietz return, consistent with the model's timing.
      if (act && ((act.coreValue ?? null) !== null || (act.satValue ?? null) !== null || (act.totalValue ?? null) !== null)) {
        let cv = act.coreValue, sv = act.satValue;
        if ((cv === undefined || cv === null || cv === '') && (sv === undefined || sv === null || sv === '') && act.totalValue != null) {
          const modelTotal = coreClose[yr] + satClose[yr];
          const share = modelTotal > 0 ? coreClose[yr] / modelTotal : coreAlloc;
          cv = Number(act.totalValue) * share; sv = Number(act.totalValue) - cv;
        }
        if (cv !== undefined && cv !== null && cv !== '') {
          coreClose[yr] = Math.max(0, Number(cv));
          coreRet[yr] = coreClose[yr] - coreOpen[yr] - coreAdd[yr];
          const base = coreOpen[yr] + weightedAdd * coreAlloc;
          actualCoreRates[yr] = base > 0 ? coreRet[yr] / base : null;
        }
        if (sv !== undefined && sv !== null && sv !== '') {
          satClose[yr] = Math.max(0, Number(sv));
          satRet[yr] = satClose[yr] - satOpen[yr] - satAdd[yr];
          const base = satOpen[yr] + weightedAdd * satAlloc;
          actualSatRates[yr] = base > 0 ? satRet[yr] / base : null;
        }
        isActualYear[yr] = true;
      }

      totalCorpus[yr] = coreClose[yr] + satClose[yr];
      totalInvested[yr] = totalInvested[yr - 1] + coreAdd[yr] + satAdd[yr];
      multipleInvested[yr] = totalInvested[yr] > 0 ? totalCorpus[yr] / totalInvested[yr] : 0.0;
      annualReturnsEarned[yr] = coreRet[yr] + satRet[yr];
    }

    // Years to next 2x (Logarithmic interpolation)
    const yrsToNext2x = new Array(maxYears + 1);
    for (let yr = 0; yr <= maxYears; yr++) {
      if (totalCorpus[yr] <= 0) {
        yrsToNext2x[yr] = '-';
        continue;
      }
      const target = 2.0 * totalCorpus[yr];
      let matchIdx = -1;
      for (let m = yr + 1; m <= maxYears; m++) {
        if (totalCorpus[m] >= target) {
          matchIdx = m;
          break;
        }
      }
      if (matchIdx !== -1) {
        const lo = totalCorpus[matchIdx - 1];
        const hi = totalCorpus[matchIdx];
        if (hi > lo && lo > 0) {
          const interpYr = (matchIdx - 1) + Math.log(target / lo) / Math.log(hi / lo);
          yrsToNext2x[yr] = interpYr - yr;
        } else {
          yrsToNext2x[yr] = matchIdx - yr;
        }
      } else {
        yrsToNext2x[yr] = `Beyond yr ${maxYears}`;
      }
    }

    // Doubling Milestones vs Combined Initial Lump Sum (2x, 4x, 8x, ..., up to 60-year scale)
    // If lump sum is 0, base against Year 1 total additions if positive, else 0
    const year1Additions = selfContrib[1] + spouseContrib[1];
    const milestoneBase = totalLump > 0 
      ? totalLump 
      : (year1Additions > 0 ? year1Additions : 0);

    const milestones = [];
    if (milestoneBase > 0) {
      let currentMult = 2;
      while (currentMult <= 131072) {
        const target = milestoneBase * currentMult;
        let matchIdx = -1;
        for (let m = 0; m <= maxYears; m++) {
          if (totalCorpus[m] >= target) {
            matchIdx = m;
            break;
          }
        }
        let yearReached = null;
        if (matchIdx > 0) {
          const lo = totalCorpus[matchIdx - 1];
          const hi = totalCorpus[matchIdx];
          if (hi > lo && lo > 0) {
            yearReached = (matchIdx - 1) + Math.log(target / lo) / Math.log(hi / lo);
          } else {
            yearReached = matchIdx;
          }
        } else if (matchIdx === 0 && totalCorpus[0] >= target) {
          yearReached = 0;
        } else {
          yearReached = `Beyond yr ${maxYears}`;
        }

        milestones.push({
          multiple: currentMult,
          target: target,
          yearReached: yearReached,
          isWithinHorizon: typeof yearReached === 'number' && yearReached <= p.horizon
        });

        currentMult *= 2;
      }
    }

    // Calculate gap from previous milestone
    for (let i = 0; i < milestones.length; i++) {
      if (i === 0) {
        milestones[i].gap = typeof milestones[i].yearReached === 'number' ? milestones[i].yearReached : '-';
      } else {
        const prev = milestones[i - 1].yearReached;
        const curr = milestones[i].yearReached;
        if (typeof curr === 'number' && typeof prev === 'number') {
          milestones[i].gap = curr - prev;
        } else {
          milestones[i].gap = '-';
        }
      }
    }

    // Summary at selected horizon
    const h = Math.min(Math.max(1, Math.round(p.horizon)), maxYears);
    const horizonAdditions = [];
    for (let y = 1; y <= h; y++) {
      horizonAdditions.push(coreAdd[y] + satAdd[y]);
    }

    // IRR on the actual cash-flow timing (mid-year for full-year SIPs, earlier for part-years)
    const irrFlows = [{ t: 0, cf: -totalLump }];
    contribFlows.forEach(f => { if (f.yr <= h && f.cf > 0) irrFlows.push({ t: f.t, cf: -f.cf }); });
    irrFlows.push({ t: h, cf: totalCorpus[h] });
    const portfolioIRR = (totalInvested[h] > 0 && totalCorpus[h] > 0) ? solveIRR(irrFlows) : 0;
    const doublingTimeAtIRR = (portfolioIRR > 0 && totalCorpus[h] > 0) ? Math.log(2) / Math.log(1 + portfolioIRR) : 0;
    const weightedStartingReturn = (coreAlloc * Number(p.coreReturn)) + (satAlloc * Number(p.satReturn));

    // Construct yearly array
    const yearlyRows = [];
    for (let yr = 0; yr <= maxYears; yr++) {
      yearlyRows.push({
        year: yr,
        selfContrib: selfContrib[yr],
        spouseContrib: spouseContrib[yr],
        selfMonthly: selfMonthlyAmt[yr], selfMonths: selfMonthsIn[yr],       // 1.12: the monthly SIP behind each year's total
        spouseMonthly: spouseMonthlyAmt[yr], spouseMonths: spouseMonthsIn[yr],
        selfLump: yr === 0 ? selfInitialLump : 0, spouseLump: yr === 0 ? spouseInitialLump : 0,
        totalContrib: selfContrib[yr] + spouseContrib[yr],
        coreOpen: coreOpen[yr],
        coreAdd: coreAdd[yr],
        coreRet: coreRet[yr],
        coreClose: coreClose[yr],
        satOpen: satOpen[yr],
        satAdd: satAdd[yr],
        satRet: satRet[yr],
        satClose: satClose[yr],
        totalCorpus: totalCorpus[yr],
        totalInvested: totalInvested[yr],
        wealthGain: totalCorpus[yr] - totalInvested[yr],
        multiple: multipleInvested[yr],
        yrsTo2x: yrsToNext2x[yr],
        annualReturnsEarned: annualReturnsEarned[yr],
        isActual: isActualYear[yr],
        actualCoreRate: actualCoreRates[yr],
        actualSatRate: actualSatRates[yr],
        isHorizon: yr === h
      });
    }

    return {
      params: p,
      horizon: h,
      coreCorpus: coreClose[h],
      satCorpus: satClose[h],
      totalCorpus: totalCorpus[h],
      totalInvested: totalInvested[h],
      wealthGain: totalCorpus[h] - totalInvested[h],
      multiple: multipleInvested[h],
      weightedStartingReturn: weightedStartingReturn,
      portfolioIRR: portfolioIRR,
      doublingTimeAtIRR: doublingTimeAtIRR,
      yrsToFirstDoubling: yrsToNext2x[0],
      nextDoublingAfterHorizon: yrsToNext2x[h],
      yearNextDoublingAchieved: typeof yrsToNext2x[h] === 'number' ? h + yrsToNext2x[h] : `Beyond yr ${maxYears}`,
      milestones: milestones,
      yearlyRows: yearlyRows
    };
  }

  /**
   * Analyze the power of Spouse Contributions
   * Compares Self-Only vs Self+Spouse
   */
  function analyzeSpouseImpact(params) {
    // 1. Self only plan
    const selfOnlyParams = Object.assign({}, params, {
      spouseLump: 0,
      spouseMonthly: 0,
      spouseInclude: false
    });
    const selfOnlyResult = calculateSchedule(selfOnlyParams);

    // 2. Combined plan (with spouse)
    const combinedParams = Object.assign({}, params, {
      spouseInclude: true
    });
    const combinedResult = calculateSchedule(combinedParams);

    const h = combinedResult.horizon;

    // Time to reach Self-Only's 30-year corpus with Spouse!
    const targetCorpus = selfOnlyResult.totalCorpus;
    let yearsWithSpouseToReachSelfTarget = null;
    if (targetCorpus > 0) {
      for (let yr = 1; yr <= (combinedParams.maxYears || 60); yr++) {
        if (combinedResult.yearlyRows[yr].totalCorpus >= targetCorpus) {
          const lo = combinedResult.yearlyRows[yr - 1].totalCorpus;
          const hi = combinedResult.yearlyRows[yr].totalCorpus;
          if (hi > lo && lo > 0) {
            yearsWithSpouseToReachSelfTarget = (yr - 1) + Math.log(targetCorpus / lo) / Math.log(hi / lo);
          } else {
            yearsWithSpouseToReachSelfTarget = yr;
          }
          break;
        }
      }
    }

    const timeSavedYears = (yearsWithSpouseToReachSelfTarget !== null && targetCorpus > 0)
      ? Math.max(0, h - yearsWithSpouseToReachSelfTarget)
      : 0;
    const extraCorpusAtHorizon = Math.max(0, combinedResult.totalCorpus - selfOnlyResult.totalCorpus);

    // Spouse total contribution
    let spouseTotalInvested = combinedParams.spouseInclude ? Number(params.spouseLump || 0) : 0;
    for (let yr = 1; yr <= h; yr++) {
      spouseTotalInvested += combinedResult.yearlyRows[yr].spouseContrib;
    }

    // Terminal wealth multiplier on spouse's capital alone
    const spouseWealthMultiplier = spouseTotalInvested > 0 ? extraCorpusAtHorizon / spouseTotalInvested : 0;

    return {
      selfOnlyResult: selfOnlyResult,
      combinedResult: combinedResult,
      timeSavedYears: timeSavedYears,
      yearsWithSpouseToReachSelfTarget: yearsWithSpouseToReachSelfTarget,
      extraCorpusAtHorizon: extraCorpusAtHorizon,
      selfCorpus: selfOnlyResult.totalCorpus,
      combinedCorpus: combinedResult.totalCorpus,
      spouseTotalInvested: spouseTotalInvested,
      selfTotalInvested: selfOnlyResult.totalInvested,
      combinedTotalInvested: combinedResult.totalInvested,
      spouseWealthMultiplier: spouseWealthMultiplier,
      percentageCorpusBoost: selfOnlyResult.totalCorpus > 0 ? (extraCorpusAtHorizon / selfOnlyResult.totalCorpus) * 100 : 0
    };
  }

  /**
   * Shared helper: fractional year at which a corpus series first reaches `target`
   * (log-interpolated between year-ends, as used throughout the sheet). Returns null if never.
   */
  function yearReaching(rows, target, maxYears) {
    for (let yr = 0; yr <= maxYears; yr++) {
      if (rows[yr].totalCorpus >= target) {
        if (yr === 0) return 0;
        const lo = rows[yr - 1].totalCorpus;
        const hi = rows[yr].totalCorpus;
        if (hi > lo && lo > 0) return (yr - 1) + Math.log(target / lo) / Math.log(hi / lo);
        return yr;
      }
    }
    return null;
  }

  /**
   * Core & satellite returns for a given blended (weighted) return, keeping the
   * user's alpha spread (satellite minus core) unchanged.
   *   weighted = coreW*core + satW*sat = blended  (exactly)
   */
  function ratesForBlended(blended, p) {
    const coreReturn = Number(p.coreReturn ?? 0.20);
    const satReturn = Number(p.satReturn ?? 0.30);
    const spread = satReturn - coreReturn;
    const cw = Number(p.coreAlloc ?? 0.70);
    const sw = Number(p.satAlloc ?? 0.30);
    const tw = (cw + sw) > 0 ? (cw + sw) : 1.0;
    return {
      coreReturn: blended - (sw / tw) * spread,
      satReturn: blended + (cw / tw) * spread
    };
  }

  /** Weighted (blended) planned return of a parameter set */
  function weightedReturnOf(p) {
    const cw = Number(p.coreAlloc ?? 0.70), sw = Number(p.satAlloc ?? 0.30);
    const tw = (cw + sw) > 0 ? (cw + sw) : 1.0;
    return (cw / tw) * Number(p.coreReturn ?? 0.20) + (sw / tw) * Number(p.satReturn ?? 0.30);
  }

  /** Generic monotone bisection: finds x in [lo, hi] where f(x) = 0 (f increasing). */
  function bisect(f, lo, hi, iters = 60) {
    let mid = lo;
    for (let i = 0; i < iters; i++) {
      mid = (lo + hi) / 2.0;
      if (f(mid) > 0) hi = mid; else lo = mid;
    }
    return (lo + hi) / 2.0;
  }

  /**
   * Goal Solver / Reverse Engineer for Adults
   * Given Target Goal (e.g. ₹10 Cr) & Horizon (e.g. 20 yrs):
   * 1. Time (years) to hit the goal with the current plan
   * 2. Required starting monthly self SIP (same step-up / stop settings, spouse unchanged)
   * 3. Required blended return (current SIP kept, core–satellite spread kept)
   */
  /**
   * Starting monthly self SIP that makes `plan` reach `target` at plan.horizon.
   * Keeps the plan's step-up mode/amount, stop years, lump sums and spouse plan.
   * Returns { sip, unreachable }.
   */
  function solveRequiredSIP(target, plan) {
    // switching self on for the SIP must not bring back a lump sum the user left out
    const selfLump = plan.selfInclude === false ? 0 : plan.selfLump;
    const corpusWithSIP = (m) => calculateSchedule(Object.assign({}, plan, {
      selfInclude: true, selfMonthly: m, selfLump: selfLump
    })).totalCorpus;
    if (corpusWithSIP(0) >= target) return { sip: 0, unreachable: false };
    let hi = Math.max(10000, target / (Math.max(1, plan.horizon) * 12));
    while (corpusWithSIP(hi) < target && hi < 1e10) hi *= 2;
    if (corpusWithSIP(hi) < target) return { sip: null, unreachable: true };
    return { sip: bisect((m) => corpusWithSIP(m) - target, 0, hi, 50), unreachable: false };
  }

  /**
   * Required starting SIP if the portfolio earns `blended` (weighted) return,
   * keeping the user's core–satellite spread.
   */
  function requiredSIPAtReturn(targetCorpus, targetHorizonYears, baseParams, blended) {
    const plan = Object.assign({}, baseParams,
      { horizon: Math.max(1, Math.round(Number(targetHorizonYears) || 1)) },
      ratesForBlended(blended, baseParams));
    return solveRequiredSIP(Number(targetCorpus), plan);
  }

  function solveGoal(targetCorpus, targetHorizonYears, baseParams, options = {}) {
    const target = Number(targetCorpus);
    const horizon = Math.max(1, Math.round(Number(targetHorizonYears) || 1));
    const maxYears = baseParams.maxYears || 60;
    const planAtGoalHorizon = Object.assign({}, baseParams, { horizon: horizon });

    // 1. Current plan outcome, measured at the GOAL horizon
    const currentSchedule = calculateSchedule(planAtGoalHorizon);

    if (target <= 0) {
      return {
        targetCorpus: 0,
        targetHorizonYears: horizon,
        currentCorpusAtHorizon: currentSchedule.totalCorpus,
        currentShortfallOrSurplus: currentSchedule.totalCorpus,
        timeToGoalYears: 0,
        requiredMonthlySIP: 0,
        sipUnreachable: false,
        requiredBlendedReturn: 0,
        rateOutOfRange: null,
        isGoalAchievedOnTime: true
      };
    }

    const timeToGoal = yearReaching(currentSchedule.yearlyRows, target, maxYears);

    // 2. Required starting monthly self SIP — at the plan's returns, or at a return the user picks
    const plannedBlended = weightedReturnOf(baseParams);
    const assumed = (options.assumedBlendedReturn !== undefined && options.assumedBlendedReturn !== null && !isNaN(options.assumedBlendedReturn))
      ? Number(options.assumedBlendedReturn) : plannedBlended;
    const sipPlan = Object.assign({}, planAtGoalHorizon, ratesForBlended(assumed, baseParams));
    const sipRes = solveRequiredSIP(target, sipPlan);
    const requiredSIP = sipRes.sip || 0;
    const sipUnreachable = sipRes.unreachable;

    // 3. Required blended return (keeping SIP & alpha spread)
    const baseInitialLump = (baseParams.selfInclude !== false ? Number(baseParams.selfLump || 0) : 0) +
                            (baseParams.spouseInclude ? Number(baseParams.spouseLump || 0) : 0);
    const baseMonthly = (baseParams.selfInclude ? Number(baseParams.selfMonthly || 0) : 0) +
                        (baseParams.spouseInclude ? Number(baseParams.spouseMonthly || 0) : 0);

    let solvedRate = null;
    let rateOutOfRange = null; // 'high' if > 150%, 'low' if < -50%
    if (baseInitialLump > 0 || baseMonthly > 0) {
      const corpusAtRate = (b) => calculateSchedule(Object.assign({}, planAtGoalHorizon,
        ratesForBlended(b, baseParams))).totalCorpus;
      const LO = -0.50, HI = 1.50;
      if (corpusAtRate(HI) < target) rateOutOfRange = 'high';
      else if (corpusAtRate(LO) > target) rateOutOfRange = 'low';
      else solvedRate = bisect((b) => corpusAtRate(b) - target, LO, HI, 50);
    }

    return {
      targetCorpus: target,
      targetHorizonYears: horizon,
      currentCorpusAtHorizon: currentSchedule.totalCorpus,
      currentShortfallOrSurplus: currentSchedule.totalCorpus - target,
      timeToGoalYears: timeToGoal,
      requiredMonthlySIP: Math.max(0, Math.round(requiredSIP)),
      sipUnreachable: sipUnreachable,
      sipAssumedReturn: assumed,
      plannedBlendedReturn: plannedBlended,
      requiredBlendedReturn: solvedRate,
      rateOutOfRange: rateOutOfRange,
      isGoalAchievedOnTime: timeToGoal !== null && timeToGoal <= horizon
    };
  }

  /**
   * Actuals Review & Course Correction
   * Recalculates after real market returns have happened.
   * 1. Revised projected corpus at horizon (actual returns for logged years, plan thereafter)
   * 2. Required blended return from next year onward to still reach the target
   * 3. Required monthly SIP from next year onward (past contributions are NOT changed)
   */
  function reviewActualsAndCorrect(baseParams, actualsHistory, originalTargetCorpus) {
    const maxYears = baseParams.maxYears || 60;
    let latestActualYear = 0;
    if (actualsHistory) {
      for (const yrStr of Object.keys(actualsHistory)) {
        const yr = parseInt(yrStr, 10);
        if (yr > latestActualYear) latestActualYear = yr;
      }
    }

    const baseline = calculateSchedule(baseParams);
    const targetCorpus = originalTargetCorpus || baseline.totalCorpus;
    const revised = calculateSchedule(baseParams, actualsHistory);
    const revisedCorpusAtHorizon = revised.totalCorpus;
    const gap = revisedCorpusAtHorizon - targetCorpus;
    const horizon = revised.horizon;
    const remainingYears = Math.max(0, horizon - latestActualYear);
    const fromYear = latestActualYear + 1;

    // Planned self monthly SIP in year y (before any correction)
    const plannedSelfMonthlyIn = (y) => {
      const extraMonths = Math.max(0, Math.min(11, Math.round(Number(baseParams.selfAddStopMonths) || 0)));
      if (!baseParams.selfInclude) return 0;
      if (y > baseParams.selfAddStop && !(y === baseParams.selfAddStop + 1 && extraMonths > 0)) return 0;
      return steppedMonthly(baseParams.selfMonthly, y, baseParams.selfStepUpStop,
        baseParams.selfStepUpMode, baseParams.selfStepUp, baseParams.selfStepUpAmt);
    };
    const plannedFutureMonthly = plannedSelfMonthlyIn(fromYear);

    const out = {
      latestActualYear: latestActualYear,
      baselineCorpus: baseline.totalCorpus,
      revisedCorpus: revisedCorpusAtHorizon,
      gap: gap,
      percentageChange: baseline.totalCorpus > 0 ? ((revisedCorpusAtHorizon - baseline.totalCorpus) / baseline.totalCorpus) * 100 : 0,
      targetCorpus: targetCorpus,
      remainingYears: remainingYears,
      sipFromYear: fromYear,
      plannedWeightedRate: baseline.weightedStartingReturn,
      requiredFutureRate: null,
      rateOutOfRange: null,
      rateAdjustmentNeeded: null,
      sipMode: 'none',              // 'scale' | 'restart' | 'none'
      plannedFutureMonthly: plannedFutureMonthly,
      requiredFutureSIP: Math.round(plannedFutureMonthly),
      sipAdjustmentNeeded: 0,
      sipUnreachable: false,
      revisedTimeToGoal: null,
      timeShiftYears: null,
      revisedSchedule: revised
    };

    if (targetCorpus <= 0) {
      out.baselineCorpus = 0; out.revisedCorpus = 0; out.gap = 0; out.targetCorpus = 0;
      return out;
    }

    if (latestActualYear === 0) {
      out.requiredFutureRate = baseline.weightedStartingReturn;
      out.rateAdjustmentNeeded = 0;
      out.sipMode = plannedFutureMonthly > 0 ? 'scale' : 'none';
    } else if (latestActualYear < horizon) {
      // 1. Required blended return for remaining years (logged years keep their actuals)
      const corpusAtRate = (b) => calculateSchedule(Object.assign({}, baseParams,
        ratesForBlended(b, baseParams)), actualsHistory).totalCorpus;
      const LO = -0.50, HI = 1.50;
      if (corpusAtRate(HI) < targetCorpus) out.rateOutOfRange = 'high';
      else if (corpusAtRate(LO) > targetCorpus) out.rateOutOfRange = 'low';
      else out.requiredFutureRate = bisect((b) => corpusAtRate(b) - targetCorpus, LO, HI, 50);
      if (out.requiredFutureRate !== null) {
        out.rateAdjustmentNeeded = out.requiredFutureRate - baseline.weightedStartingReturn;
      }

      // 2. Required SIP from next year onward, at planned returns
      let plannedFutureTotal = 0;
      for (let y = fromYear; y <= horizon; y++) plannedFutureTotal += plannedSelfMonthlyIn(y);

      if (plannedFutureTotal > 0) {
        // Scale the remaining planned SIP path (keeps step-up & stop year)
        out.sipMode = 'scale';
        const corpusAtFactor = (k) => calculateSchedule(Object.assign({}, baseParams, {
          selfFutureFromYear: fromYear, selfFutureFactor: k
        }), actualsHistory).totalCorpus;
        let k = 0;
        if (corpusAtFactor(0) < targetCorpus) {
          let hi = 2;
          while (corpusAtFactor(hi) < targetCorpus && hi < 1e6) hi *= 2;
          if (corpusAtFactor(hi) < targetCorpus) out.sipUnreachable = true;
          else k = bisect((x) => corpusAtFactor(x) - targetCorpus, 0, hi, 50);
        }
        out.requiredFutureSIP = Math.round(k * plannedFutureMonthly);
      } else {
        // Additions already stopped (or never planned): flat SIP restarted from next year to horizon
        out.sipMode = 'restart';
        const corpusAtMonthly = (m) => calculateSchedule(Object.assign({}, baseParams, {
          selfFutureFromYear: fromYear, selfFutureMonthly: m
        }), actualsHistory).totalCorpus;
        let m = 0;
        if (corpusAtMonthly(0) < targetCorpus) {
          let hi = Math.max(10000, targetCorpus / (Math.max(1, remainingYears) * 12));
          while (corpusAtMonthly(hi) < targetCorpus && hi < 1e10) hi *= 2;
          if (corpusAtMonthly(hi) < targetCorpus) out.sipUnreachable = true;
          else m = bisect((x) => corpusAtMonthly(x) - targetCorpus, 0, hi, 50);
        }
        out.requiredFutureSIP = Math.round(m);
      }
      out.sipAdjustmentNeeded = out.requiredFutureSIP - Math.round(plannedFutureMonthly);
    }

    // 3. Revised time to reach the target
    out.revisedTimeToGoal = yearReaching(revised.yearlyRows, targetCorpus, maxYears);
    out.timeShiftYears = out.revisedTimeToGoal !== null ? out.revisedTimeToGoal - horizon : null;
    return out;
  }

  /**
   * Youngster Wealth & Cost of Delay Calculator Engine
   * Takes current age, monthly amount, annual step-up (on/off/stop years),
   * additions stop years, and projects wealth to age 70 with cost-of-delay analytics.
   */
  function calculateYoungsterWealth(options = {}) {
    const currentAge = Math.max(10, Math.min(65, parseInt(options.currentAge, 10) || 21));
    const targetAge = Math.max(currentAge + 1, Math.min(90, parseInt(options.targetAge, 10) || 70));
    const monthly = options.monthly !== undefined && !isNaN(parseFloat(options.monthly)) ? Math.max(0, parseFloat(options.monthly)) : 10000;
    const stepUpEnabled = options.stepUpEnabled !== false;
    const stepUpPct = stepUpEnabled ? (options.stepUpPct !== undefined && !isNaN(parseFloat(options.stepUpPct)) ? parseFloat(options.stepUpPct) / 100.0 : 0.10) : 0.0;
    const stepUpStopYears = Math.max(1, parseInt(options.stepUpStopYears, 10) || 10);
    const stepUpMode = options.stepUpMode === 'amt' ? 'amt' : 'pct';
    const stepUpAmt = stepUpEnabled && stepUpMode === 'amt' ? Math.max(0, parseFloat(options.stepUpAmt) || 0) : 0;
    const horizon = targetAge - currentAge;
    const additionsStopYears = options.additionsStopYears ? Math.min(horizon, parseInt(options.additionsStopYears, 10)) : horizon;
    const additionsStopMonths = additionsStopYears < horizon ? Math.max(0, Math.min(11, parseInt(options.additionsStopMonths, 10) || 0)) : 0;
    const delayYearsList = Array.isArray(options.delayYearsList) ? options.delayYearsList : [3, 6, 9];
    const rate = options.rate !== undefined && !isNaN(parseFloat(options.rate)) ? parseFloat(options.rate) / 100.0 : 0.20;
    // Optional core + satellite split (as in the Core engine): two pots growing at their own rates.
    // Without it, everything grows at the single `rate`.
    const hasSplit = options.coreRate !== undefined && options.satRate !== undefined;
    const coreW = hasSplit ? Math.max(0, Math.min(1, (parseFloat(options.coreAlloc) || 0) / 100.0)) : 1;
    const coreRate = hasSplit ? parseFloat(options.coreRate) / 100.0 : rate;
    const satRate = hasSplit ? parseFloat(options.satRate) / 100.0 : rate;
    const computeDelays = options.computeDelays !== false;

    let corpus = 0.0;
    let corePot = 0.0, satPot = 0.0;
    let totalInvested = 0.0;
    const yearlyRows = [];

    for (let yr = 1; yr <= horizon; yr++) {
      const age = currentAge + yr;
      let curMonthly = 0.0;
      const months = yr <= additionsStopYears ? 12 : (yr === additionsStopYears + 1 ? additionsStopMonths : 0);
      if (months > 0) {
        if (stepUpEnabled) {
          curMonthly = steppedMonthly(monthly, yr, stepUpStopYears, stepUpMode, stepUpPct, stepUpAmt);
        } else {
          curMonthly = monthly;
        }
      }
      const annualAdd = curMonthly * months;
      // Return on additions: half a year for a full year of SIPs, (1 − m/24) for m months
      const w = months > 0 && months < 12 ? 1 - months / 24 : 0.5;
      const coreAdd = annualAdd * coreW, satAdd = annualAdd - coreAdd;
      const coreInt = corePot * coreRate + coreAdd * coreRate * w;
      const satInt = satPot * satRate + satAdd * satRate * w;
      corePot += coreAdd + coreInt;
      satPot += satAdd + satInt;
      const interest = coreInt + satInt;
      corpus = corePot + satPot;
      totalInvested += annualAdd;

      yearlyRows.push({
        year: yr,
        age: age,
        months: months,
        monthly: curMonthly,
        annualAdd: annualAdd,
        annualInterest: interest,
        totalInvested: totalInvested,
        corpus: corpus,
        coreCorpus: corePot,
        satCorpus: satPot
      });
    }

    // Extract key milestone checkpoints at ages 50, 60, and 70
    const row50 = yearlyRows.find(r => r.age === 50);
    const row60 = yearlyRows.find(r => r.age === 60);
    const row70 = yearlyRows.find(r => r.age === 70) || (yearlyRows.length ? yearlyRows[yearlyRows.length - 1] : null);

    const corpusAt50 = row50 ? row50.corpus : null;
    const investedAt50 = row50 ? row50.totalInvested : null;
    const multipleAt50 = (row50 && row50.totalInvested > 0) ? row50.corpus / row50.totalInvested : 0;

    const corpusAt60 = row60 ? row60.corpus : null;
    const investedAt60 = row60 ? row60.totalInvested : null;
    const multipleAt60 = (row60 && row60.totalInvested > 0) ? row60.corpus / row60.totalInvested : 0;

    const corpusAt70 = row70 ? row70.corpus : corpus;
    const investedAt70 = row70 ? row70.totalInvested : totalInvested;
    const multipleAt70 = investedAt70 > 0 ? corpusAt70 / investedAt70 : 0;

    // Cost of Delay Analysis: ONLY compute at top-level (prevent recursive explosion)
    let delayScenarios = [];
    if (computeDelays) {
      delayScenarios = delayYearsList
        .filter(d => currentAge + d < targetAge)
        .map(d => {
          const delayedRes = calculateYoungsterWealth({
            currentAge: currentAge + d,
            targetAge: targetAge,
            monthly: monthly,
            stepUpEnabled: stepUpEnabled,
            stepUpPct: stepUpPct * 100,
            stepUpMode: stepUpMode,
            stepUpAmt: stepUpAmt,
            stepUpStopYears: stepUpStopYears,
            additionsStopYears: additionsStopYears,
            additionsStopMonths: additionsStopMonths,
            delayYearsList: delayYearsList,
            rate: rate * 100,
            coreRate: hasSplit ? coreRate * 100 : undefined,
            satRate: hasSplit ? satRate * 100 : undefined,
            coreAlloc: hasSplit ? coreW * 100 : undefined,
            computeDelays: false // CRITICAL: Stop recursion here
          });
          const row50d = delayedRes.yearlyRows.find(r => r.age === 50);
          const row60d = delayedRes.yearlyRows.find(r => r.age === 60);
          const row70d = delayedRes.yearlyRows.find(r => r.age === 70) || (delayedRes.yearlyRows.length ? delayedRes.yearlyRows[delayedRes.yearlyRows.length - 1] : null);
          const wealthLost = Math.max(0, corpus - delayedRes.corpus);
          const pctLost = corpus > 0 ? (wealthLost / corpus) * 100.0 : 0.0;
          return {
            delayYears: d,
            startAge: currentAge + d,
            label: `Wait ${d} Year${d > 1 ? 's' : ''} (Start at Age ${currentAge + d})`,
            corpus: delayedRes.corpus,
            corpusAt50: row50d ? row50d.corpus : null,
            corpusAt60: row60d ? row60d.corpus : null,
            corpusAt70: row70d ? row70d.corpus : delayedRes.corpus,
            totalInvested: delayedRes.totalInvested,
            wealthLost: wealthLost,
            pctLost: pctLost,
            multiple: delayedRes.multiple
          };
        });
    }

    return {
      currentAge: currentAge,
      targetAge: targetAge,
      horizon: horizon,
      monthly: monthly,
      stepUpEnabled: stepUpEnabled,
      stepUpPct: stepUpPct,
      stepUpMode: stepUpMode,
      stepUpAmt: stepUpAmt,
      stepUpStopYears: stepUpStopYears,
      additionsStopYears: additionsStopYears,
      additionsStopMonths: additionsStopMonths,
      rate: rate,
      totalInvested: totalInvested,
      corpus: corpus,
      corpusAt50: corpusAt50,
      investedAt50: investedAt50,
      multipleAt50: multipleAt50,
      corpusAt60: corpusAt60,
      investedAt60: investedAt60,
      multipleAt60: multipleAt60,
      corpusAt70: corpusAt70,
      investedAt70: investedAt70,
      multipleAt70: multipleAt70,
      wealthGain: corpus - totalInvested,
      multiple: totalInvested > 0 ? corpus / totalInvested : 0,
      delayScenarios: delayScenarios,
      yearlyRows: yearlyRows
    };
  }

  /**
   * Youngster Cost of Delay Analysis
   * Compares starting early vs delaying 5 or 10 years
   */
  function analyzeCostOfDelay(monthlyInvestment = 10000, startAge = 20, retirementAge = 60, rate = 0.20) {
    const horizons = [0, 5, 10, 15]
      .filter(d => startAge + d < retirementAge)
      .map(d => ({
        label: d === 0 ? `Start at ${startAge}` : `Start at ${startAge + d} (${d}-yr delay)`,
        delay: d,
        yrs: retirementAge - (startAge + d)
      }));

    const results = horizons.map(h => {
      const p = {
        selfLump: 0,
        spouseLump: 0,
        coreAlloc: 0.7,
        satAlloc: 0.3,
        // 70/30 mix with a 10-pt alpha spread whose weighted average equals `rate` exactly
        coreReturn: rate - 0.03,
        satReturn: rate + 0.07,
        selfMonthly: monthlyInvestment,
        selfInclude: true,
        spouseInclude: false,
        horizon: h.yrs,
        selfStepUp: 0.10,
        selfStepUpStop: 10,
        selfAddStop: h.yrs,
        maxYears: 60
      };
      const res = calculateSchedule(p);
      return {
        label: h.label,
        delayYears: h.delay,
        investingYears: h.yrs,
        totalInvested: res.totalInvested,
        totalCorpus: res.totalCorpus,
        wealthGain: res.wealthGain,
        multiple: res.multiple
      };
    });

    const baseline = results[0].totalCorpus;
    results.forEach(r => {
      r.lossVsStartToday = baseline - r.totalCorpus;
      r.percentageLoss = baseline > 0 ? ((baseline - r.totalCorpus) / baseline) * 100 : 0;
    });

    return results;
  }

  // Export all functions
  return {
    formatINR: formatINR,
    formatPercent: formatPercent,
    formatYears: formatYears,
    calculateSchedule: calculateSchedule,
    analyzeSpouseImpact: analyzeSpouseImpact,
    solveGoal: solveGoal,
    reviewActualsAndCorrect: reviewActualsAndCorrect,
    calculateYoungsterWealth: calculateYoungsterWealth,
    analyzeCostOfDelay: analyzeCostOfDelay,
    solveSemiAnnualIRR: solveSemiAnnualIRR,
    solveIRR: solveIRR,
    steppedMonthly: steppedMonthly,
    requiredSIPAtReturn: requiredSIPAtReturn,
    weightedReturnOf: weightedReturnOf,
    yearReaching: yearReaching,
    ratesForBlended: ratesForBlended
  };
});
