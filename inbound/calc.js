/* Calculator maths for the "Reuse OK Please" page. Plain script: works in the browser (window.IBCalc) and in node (tests).
   Every number it produces comes from the visitor's own inputs and the editable placeholder prices below. It never invents savings. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(); else root.IBCalc = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  // ---- assumptions: every value is shown on the page and can be edited by the visitor ----
  var ITEMS = [
    { id: 'plate', name: 'Paper plates',     icon: 'i-paper-plate',   costRs: 3,   litres: 0.25, color: '#D63D27' },
    { id: 'cup',   name: 'Cups',             icon: 'i-plastic-cup',   costRs: 1.5, litres: 0.2,  color: '#0B7A8A' },
    { id: 'cut',   name: 'Spoons and forks', icon: 'i-plastic-spoon', costRs: 1,   litres: 0.02, color: '#3FAE3A' },
    { id: 'box',   name: 'Takeaway boxes',   icon: 'i-takeaway-box',  costRs: 8,   litres: 0.6,  color: '#D7266F' }
  ];
  var BIN_LITRES = 120;

  function compute(o) {
    var meals = Math.max(0, +o.meals || 0), days = Math.max(0, +o.days || 0);
    var parts = ITEMS.map(function (it) {
      var perMeal = Math.max(0, +((o.counts || {})[it.id]) || 0);
      var cost = o.costs && o.costs[it.id] != null && o.costs[it.id] !== '' ? Math.max(0, +o.costs[it.id]) : it.costRs;
      var units = meals * perMeal * days;
      return { id: it.id, name: it.name, icon: it.icon, color: it.color, perMeal: perMeal, units: units, rs: units * cost, litres: units * it.litres };
    });
    var sum = function (k) { return parts.reduce(function (a, p) { return a + p[k]; }, 0); };
    return { parts: parts, units: sum('units'), rs: sum('rs'), bins: sum('litres') / BIN_LITRES };
  }

  // share of each item, by units or by rupees (the Units / Rs toggle)
  function shares(res, mode) {
    var key = mode === 'rs' ? 'rs' : 'units', tot = mode === 'rs' ? res.rs : res.units;
    return res.parts.map(function (p) { return { id: p.id, color: p.color, name: p.name, value: p[key], frac: tot ? p[key] / tot : 0 }; });
  }

  var nf = function (n) { return Math.round(n).toLocaleString('en-IN'); };
  function inr(n) {  // Indian wording: Rs 45,000 / Rs 1.9 lakh / Rs 2.3 crore
    if (n >= 1e7) return 'Rs ' + (n / 1e7).toFixed(1).replace(/\.0$/, '') + ' crore';
    if (n >= 1e5) return 'Rs ' + (n / 1e5).toFixed(1).replace(/\.0$/, '') + ' lakh';
    return 'Rs ' + nf(n);
  }

  var QUEUE = { corporate: 'warewashing', institution: 'warewashing', fitout: 'kitchen design', caterer: 'partner' };
  return { ITEMS: ITEMS, BIN_LITRES: BIN_LITRES, compute: compute, shares: shares, nf: nf, inr: inr, queueFor: function (s) { return QUEUE[s] || 'unrouted'; } };
});
