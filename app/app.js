/* S&P 500 screener: state, rendering and interaction. Data comes from data/stocks.json
   (the universe) and data/history/<sector>.json (per-sector price history, lazy). */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const WINDOW_LABEL = { "1d": "Today", "1w": "1 week", "1m": "1 month", "3m": "3 months", "6m": "6 months", "1y": "1 year", "earn": "Since last earnings" };
  const WINDOW_SHORT = { "1d": "1D", "1w": "1W", "1m": "1M", "3m": "3M", "6m": "6M", "1y": "1Y", "earn": "Since earnings" };
  const RANGE_DAYS = { "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252 };
  const DEFAULT_RULES = [
    { id: "daily-mover", label: "Moved 4%+ today", window: "1d", threshold_pct: 4, direction: "either" },
    { id: "weekly-breakout", label: "Up 10%+ over the week", window: "1w", threshold_pct: 10, direction: "up" },
    { id: "monthly-slide", label: "Down 15%+ over the month", window: "1m", threshold_pct: 15, direction: "down" },
  ];

  const state = {
    data: null, rules: DEFAULT_RULES, history: {}, options: {}, view: "markets",
    sector: null, group: null, sub: null, query: "", sort: { key: "mcap", dir: -1 },
    screen: { window: "1d", direction: "either", threshold: 4 },
    open: null, range: "1M", earnMode: "q", redraws: [],
  };
  try { Object.assign(state.screen, JSON.parse(localStorage.getItem("sp500.screen") || "{}")); } catch (_) { /* per-viewer convenience only */ }

  // ---------- formatting ----------
  const fmtPrice = (v) => v == null ? "—" : "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtCap = (v) => {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 9.995e11) return "$" + (v / 1e12).toFixed(2) + "T";
    if (a >= 1e9) return "$" + (v / 1e9).toFixed(v >= 1e11 ? 0 : 1) + "B";
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(0) + "M";
    return "$" + v.toLocaleString();
  };
  const fmtPct = (v, signed = true) => v == null ? "—" : (signed && v > 0 ? "+" : "") + v.toFixed(2) + "%";
  const fmtSigned = (v) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
  const fmtX = (v, suf = "×") => v == null ? "—" : (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(1)) + suf;
  const fmtInt = (v) => v == null ? "—" : v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(0) + "K" : String(v);
  const tone = (v) => v == null ? "flat" : v > 0 ? "up" : v < 0 ? "down" : "flat";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d || 1); };
  const fmtDate = (s, long) => { if (!s) return ""; const d = parseISO(s); return long ? `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}` : `${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
  const ago = (unix) => {
    if (!unix) return "";
    const mins = Math.max(0, Math.round((Date.now() / 1000 - unix) / 60));
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60); if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24); if (days < 7) return `${days}d ago`;
    const d = new Date(unix * 1000); return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
  };
  const newsLink = (n, cls) => {
    const a = h("a", cls); a.href = n.u; a.target = "_blank"; a.rel = "noopener";
    a.addEventListener("click", (e) => e.stopPropagation());
    a.addEventListener("keydown", (e) => e.stopPropagation());
    return a;
  };
  const since = (iso) => {
    if (!iso) return null;
    const d = parseISO(iso), now = new Date();
    let months = (now.getFullYear() - d.getFullYear()) * 12 + now.getMonth() - d.getMonth();
    if (now.getDate() < d.getDate()) months -= 1;
    const y = Math.floor(months / 12), m = months % 12;
    return y >= 3 ? `${y} yrs` : y >= 1 ? `${y} yr ${m} mo` : `${m} mo`;
  };

  // ---------- data ----------
  async function load(force) {
    const res = await fetch("data/stocks.json", { cache: force ? "reload" : "no-cache" });
    if (!res.ok) throw new Error("stocks.json " + res.status);
    state.data = await res.json();
    state.bySym = Object.fromEntries(state.data.stocks.map((s) => [s.t, s]));
    state.sectorShort = Object.fromEntries(state.data.sectors.map((s) => [s.name, s.short]));
    for (const sec of state.data.sectors) {
      const rows = state.data.stocks.filter((s) => s.sector === sec.name);
      sec.chg = capWeighted(rows);
      for (const g of sec.groups) g.chg = capWeighted(rows.filter((s) => s.group === g.name));
    }
    try { const r = await fetch("data/alerts.json", { cache: force ? "reload" : "no-cache" }); if (r.ok) { const a = await r.json(); if (a.rules?.length) state.rules = a.rules; } } catch (_) { /* optional */ }
    if (force) { state.history = {}; state.options = {}; }
  }
  function setAsOf() {
    const asOf = new Date(state.data.asOf);
    $("#asof").textContent = `${state.data.count} companies · data as of ${MONTHS[asOf.getMonth()]} ${asOf.getDate()}, ${asOf.getFullYear()} ${asOf.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
  }
  let toastTimer = null;
  function toast(msg, ms = 6000) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, ms);
  }
  /** Re-read every data file, bypassing caches, and redraw. Picks up whatever the
      pipeline last published (the daily job on GitHub Pages, or a republish here). */
  async function refreshAll() {
    const btn = $("#refresh"); if (btn.disabled) return;
    btn.disabled = true; btn.classList.add("spin");
    const before = state.data.asOf;
    let ok = true;
    try { await load(true); } catch (_) { ok = false; }
    setAsOf(); renderAll();
    if (state.open && state.bySym[state.open]) openDetail(state.open);
    const asOf = new Date(state.data.asOf);
    const stamp = `${MONTHS[asOf.getMonth()]} ${asOf.getDate()}, ${asOf.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
    if (!ok) toast("Couldn't reload the data files. Check your connection and try again.", 8000);
    else if (state.data.asOf !== before) toast(`Updated. Data as of ${stamp}.`, 7000);
    else toast(`Already showing the latest data on file (${stamp}). The pipeline refreshes weekdays after the close.`, 8000);
    btn.disabled = false; btn.classList.remove("spin");
  }
  function capWeighted(rows) {
    let num = 0, den = 0;
    for (const s of rows) if (s.chgPct != null && s.mcap) { num += s.chgPct * s.mcap; den += s.mcap; }
    return den ? num / den : null;
  }
  async function historyFor(stock) {
    const slug = stock.sector.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
    if (!state.history[slug]) {
      state.history[slug] = fetch(`data/history/${slug}.json`).then((r) => r.ok ? r.json() : {});
    }
    const bundle = await state.history[slug];
    return bundle[stock.t] || { d: [], w: [] };
  }

  const sectorSlug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  async function optionsFor(stock) {
    const slug = sectorSlug(stock.sector);
    if (!state.options[slug]) state.options[slug] = fetch(`data/options/${slug}.json`).then((r) => r.ok ? r.json() : { chains: {} }).catch(() => ({ chains: {} }));
    const bundle = await state.options[slug];
    return { asOf: bundle.asOf, chain: (bundle.chains || {})[stock.t] || { spot: stock.price, exps: [] } };
  }

  // ---------- filtering / sorting ----------
  function visibleStocks() {
    const q = state.query.trim().toLowerCase();
    let rows = state.data.stocks.filter((s) =>
      (!state.sector || s.sector === state.sector) && (!state.group || s.group === state.group) && (!state.sub || s.sub === state.sub) &&
      (!q || s.t.toLowerCase().includes(q) || s.n.toLowerCase().includes(q)));
    const { key, dir } = state.sort;
    const val = (s) => key === "name" ? s.n : key === "chg" ? s.chgPct : key === "m1" ? s.ret?.["1m"] : key === "fpe" ? s.val?.fpe : key === "pe" ? s.val?.pe : key === "pediff" ? peDiff(s) : s.mcap;
    rows.sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null && vb == null) return 0; if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir;
    });
    return rows;
  }
  function screenStocks() {
    const { window: w, direction, threshold } = state.screen;
    const scope = state.sector ? state.data.stocks.filter((s) => s.sector === state.sector) : state.data.stocks;
    return scope.filter((s) => {
      const r = s.ret?.[w]; if (r == null) return false;
      return direction === "up" ? r >= threshold : direction === "down" ? r <= -threshold : Math.abs(r) >= threshold;
    }).sort((a, b) => Math.abs(b.ret[w]) - Math.abs(a.ret[w]));
  }
  function ruleHits(rule) {
    const thr = Math.abs(rule.threshold_pct);
    return state.data.stocks.filter((s) => {
      const r = s.ret?.[rule.window]; if (r == null) return false;
      return rule.direction === "up" ? r >= thr : rule.direction === "down" ? r <= -thr : Math.abs(r) >= thr;
    }).length;
  }

  // ---------- rendering: rail + chips ----------
  const chgSpan = (v, cls = "chg") => { const e = h("span", `${cls} num ${tone(v)}`, v == null ? "" : fmtPct(v)); return e; };
  function renderRail() {
    const rail = $("#rail"); rail.replaceChildren();
    rail.appendChild(h("h2", null, "Sectors"));
    const all = railItem("All S&P 500", state.data.count, capWeighted(state.data.stocks), !state.sector);
    all.classList.add("all");
    all.addEventListener("click", () => setFilter(null, null, null));
    rail.appendChild(all);
    for (const sec of state.data.sectors) {
      const active = state.sector === sec.name;
      const item = railItem(sec.name, sec.count, sec.chg, active && !state.group);
      item.setAttribute("aria-expanded", String(active));
      const chev = svgIcon("chev"); chev.classList.add("chev"); item.prepend(chev);
      item.addEventListener("click", () => setFilter(active && !state.group ? null : sec.name, null, null));
      rail.appendChild(item);
      if (active) {
        const sub = h("div", "rail-sub");
        for (const g of sec.groups) {
          const gi = railItem(g.name, g.count, g.chg, state.group === g.name);
          gi.prepend(h("i", "dot"));
          gi.title = g.subs.map((x) => x.name).join(", ");
          gi.addEventListener("click", () => setFilter(sec.name, state.group === g.name ? null : g.name, null));
          sub.appendChild(gi);
        }
        rail.appendChild(sub);
      }
    }
  }
  function railItem(name, count, chg, current) {
    const b = h("button", "rail-item"); b.type = "button";
    if (current) b.setAttribute("aria-current", "true");
    b.append(h("span", "name", name), h("span", "cnt num", String(count)), chgSpan(chg));
    return b;
  }
  function renderChips() {
    const wrap = $("#chips"); wrap.replaceChildren();
    const mk = (label, chg, pressed, onClick) => {
      const c = h("button", "chip"); c.type = "button"; c.setAttribute("aria-pressed", String(pressed));
      c.appendChild(h("span", null, label)); if (chg != null) c.appendChild(chgSpan(chg));
      c.addEventListener("click", onClick); return c;
    };
    wrap.appendChild(mk("All", null, !state.sector, () => setFilter(null, null, null)));
    for (const sec of state.data.sectors) wrap.appendChild(mk(sec.short, sec.chg, state.sector === sec.name, () => setFilter(state.sector === sec.name ? null : sec.name, null, null)));
    const subWrap = $("#subchips"); subWrap.replaceChildren();
    const sec = state.data.sectors.find((s) => s.name === state.sector);
    subWrap.hidden = !sec || state.view === "screener";
    if (sec) {
      subWrap.appendChild(mk("All " + sec.short, null, !state.group, () => setFilter(sec.name, null, null)));
      for (const g of sec.groups) subWrap.appendChild(mk(g.name, null, state.group === g.name, () => setFilter(sec.name, state.group === g.name ? null : g.name, null)));
    }
    // keep the active chip in view
    const act = wrap.querySelector('[aria-pressed="true"]'); if (act) act.scrollIntoView({ inline: "center", block: "nearest" });
  }
  function setFilter(sector, group, sub) {
    state.sector = sector; state.group = group; state.sub = sub;
    renderAll();
  }

  // ---------- rendering: list ----------
  function renderRow(s, pctKey) {
    const b = h("div", "row"); b.setAttribute("role", "button"); b.tabIndex = 0; b.dataset.t = s.t;
    b.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(s.t); } });
    const ident = h("div", "ident");
    const tkline = h("div", "tkline"); tkline.append(h("span", "tk", s.t), h("span", "sectag", state.sectorShort[s.sector] || s.sector));
    ident.append(tkline, h("div", "nm", s.n));
    const sec = h("div", "sec", state.group ? s.sub : s.group);
    const spark = Charts.sparkline(s.spark);
    const mcap = h("div", "mcap num", fmtCap(s.mcap));
    const px = h("div", "px num", fmtPrice(s.price));
    const pct = pctKey === "1d" ? s.chgPct : s.ret?.[pctKey];
    const pillwrap = h("div", "pillwrap"); pillwrap.appendChild(pill(pct));
    const mobile = h("div", "mobile-px"); mobile.append(h("span", "px num", fmtPrice(s.price)), pill(pct));
    b.append(ident, sec, spark, mcap, px, pillwrap, mobile);
    b.addEventListener("click", () => openDetail(s.t));
    return b;
  }
  const pill = (v) => h("span", `pill ${tone(v)}`, fmtPct(v));
  function renderList() {
    const list = $("#list"); list.replaceChildren();
    const rows = visibleStocks();
    const crumb = $("#crumb"); crumb.replaceChildren();
    const title = state.group || state.sector || "All S&P 500";
    crumb.append(h("h2", null, title), h("span", "cnt num", `${rows.length}`));
    if (state.group) {
      const sec = state.data.sectors.find((x) => x.name === state.sector);
      const g = sec?.groups.find((x) => x.name === state.group);
      if (g) crumb.appendChild(h("span", "sub", `${sec.name} · ${g.subs.map((x) => `${x.name} (${x.count})`).join(", ")}`));
    } else if (state.sector) {
      const sec = state.data.sectors.find((x) => x.name === state.sector);
      crumb.appendChild(h("span", "sub", `${sec.groups.length} industry groups · cap-weighted today ${fmtPct(sec.chg)}`));
    } else {
      crumb.appendChild(h("span", "sub", `${state.data.sectors.length} GICS sectors · cap-weighted today ${fmtPct(capWeighted(state.data.stocks))}`));
    }
    const cols = h("div", "cols glass");
    ["Company", state.group ? "Sub-industry" : "Industry group", "30 days", "Mkt cap", "Price", "Today"].forEach((c) => cols.appendChild(h("span", null, c)));
    list.appendChild(cols);
    if (!rows.length) { list.appendChild(h("div", "empty", "No companies match.")); return; }
    const frag = document.createDocumentFragment();
    for (const s of rows) frag.appendChild(renderRow(s, "1d"));
    list.appendChild(frag);
    // sort buttons
    $$("#sortseg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === state.sort.key)));
  }

  /** Trailing P/E minus forward P/E: positive when the multiple compresses on next year's earnings. */
  const peDiff = (s) => (s.val?.pe != null && s.val?.fpe != null) ? s.val.pe - s.val.fpe : null;
  const fmtDiff = (d) => d == null ? "—" : (d > 0 ? "+" : "") + d.toFixed(1) + "×";

  // ---------- rendering: table (by sector) ----------
  let tblCollapsed = {};
  try { tblCollapsed = JSON.parse(localStorage.getItem("sp500.tblCollapsed") || "{}"); } catch (_) { /* per-viewer convenience */ }
  function renderTable() {
    const root = $("#table"); root.replaceChildren();
    const rows = visibleStocks();
    const wrap = h("div", "tbl-wrap");
    const table = h("table", "tbl");
    const thead = h("thead"); const hr = h("tr");
    const cols = [["Company", null, ""], ["Price", null, "num"], ["P/E (TTM)", "pe", "num wide"], ["Fwd P/E", "fpe", "num"], ["P/E − Fwd", "pediff", "num"], ["Mkt cap", "mcap", "num wide"]];
    for (const [label, key, cls] of cols) {
      const th = h("th", cls); th.scope = "col";
      if (key) {
        const b = h("button", "th-btn", label); b.type = "button";
        if (key === "pediff") b.title = "Trailing P/E minus forward P/E. Positive means the multiple is lower on next year's expected earnings.";
        if (state.sort.key === key) { b.setAttribute("aria-sort", state.sort.dir < 0 ? "descending" : "ascending"); b.appendChild(h("span", "arrow", state.sort.dir < 0 ? "↓" : "↑")); }
        b.addEventListener("click", () => { if (state.sort.key === key) state.sort.dir *= -1; else state.sort = { key, dir: -1 }; renderTable(); syncSortSeg(); });
        th.appendChild(b);
      } else th.textContent = label;
      hr.appendChild(th);
    }
    thead.appendChild(hr); table.appendChild(thead);
    let shown = 0;
    for (const sec of state.data.sectors) {
      const secRows = rows.filter((s) => s.sector === sec.name);
      if (!secRows.length) continue;
      const tbody = h("tbody");
      const collapsed = !!tblCollapsed[sec.name];
      const sr = h("tr", "sec-row"); const td = h("td"); td.colSpan = cols.length;
      const btn = h("button", "sec-btn"); btn.type = "button"; btn.setAttribute("aria-expanded", String(!collapsed));
      const chev = svgIcon("chev"); chev.classList.add("chev");
      btn.append(chev, h("span", "sec-name", sec.name), h("span", "cnt num", String(secRows.length)), chgSpan(sec.chg));
      btn.addEventListener("click", () => { tblCollapsed[sec.name] = !tblCollapsed[sec.name]; try { localStorage.setItem("sp500.tblCollapsed", JSON.stringify(tblCollapsed)); } catch (_) { /* ignore */ } renderTable(); });
      td.appendChild(btn); sr.appendChild(td); tbody.appendChild(sr);
      if (!collapsed) {
        for (const s of secRows) {
          const tr = h("tr", "stk"); tr.tabIndex = 0; tr.setAttribute("role", "button");
          const c1 = h("td", "co"); const line = h("div", "tkline"); line.append(h("span", "tk", s.t)); c1.append(line, h("div", "nm", s.n));
          const c2 = h("td", "num", fmtPrice(s.price));
          const c3 = h("td", "num wide", fmtX(s.val?.pe));
          const c4 = h("td", "num", fmtX(s.val?.fpe));
          const d = peDiff(s);
          const c5 = h("td", "num"); c5.appendChild(h("span", `pill ${tone(d)}`, fmtDiff(d)));
          const c6 = h("td", "num wide", fmtCap(s.mcap));
          tr.append(c1, c2, c3, c4, c5, c6);
          tr.addEventListener("click", () => openDetail(s.t));
          tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetail(s.t); } });
          tbody.appendChild(tr); shown++;
        }
      }
      table.appendChild(tbody);
    }
    wrap.appendChild(table); root.appendChild(wrap);
    if (!rows.length) root.appendChild(h("div", "empty", "No companies match."));
  }
  function syncSortSeg() { $$("#sortseg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === state.sort.key))); }

  // ---------- rendering: screener ----------
  function renderScreener() {
    const root = $("#screener"); root.replaceChildren();
    const panel = h("section", "panel glass");
    panel.append(h("h3", null, "Price move screen"), h("p", "hint", "Find every S&P 500 member that moved more than a threshold over a time frame. Runs against the latest close."));
    const grid = h("div", "ctrl-grid");
    // window
    const cw = h("div", "ctrl"); cw.appendChild(h("span", "lbl", "Time frame"));
    const segW = h("div", "seg glass small");
    for (const w of Object.keys(WINDOW_SHORT)) {
      const b = h("button", null, WINDOW_SHORT[w]); b.type = "button"; b.setAttribute("aria-pressed", String(state.screen.window === w));
      b.addEventListener("click", () => { state.screen.window = w; saveScreen(); renderScreener(); }); segW.appendChild(b);
    }
    cw.appendChild(segW);
    // direction
    const cd = h("div", "ctrl"); cd.appendChild(h("span", "lbl", "Direction"));
    const segD = h("div", "seg glass small");
    [["up", "Up"], ["down", "Down"], ["either", "Either"]].forEach(([k, l]) => {
      const b = h("button", null, l); b.type = "button"; b.setAttribute("aria-pressed", String(state.screen.direction === k));
      b.addEventListener("click", () => { state.screen.direction = k; saveScreen(); renderScreener(); }); segD.appendChild(b);
    });
    cd.appendChild(segD);
    // threshold
    const ct = h("div", "ctrl"); const lab = h("label", null, "Minimum move"); lab.htmlFor = "thr"; ct.appendChild(lab);
    const sr = h("div", "slider-row");
    const rng = document.createElement("input"); rng.type = "range"; rng.id = "thr"; rng.min = "0.5"; rng.max = "50"; rng.step = "0.5"; rng.value = String(state.screen.threshold);
    const out = h("output", "num", state.screen.threshold + "%"); out.htmlFor = "thr";
    rng.addEventListener("input", () => { state.screen.threshold = parseFloat(rng.value); out.textContent = rng.value + "%"; renderScreenResults(); });
    rng.addEventListener("change", saveScreen);
    sr.append(rng, out); ct.appendChild(sr);
    // presets
    const cp = h("div", "ctrl"); cp.appendChild(h("span", "lbl", "Saved daily screens"));
    const pr = h("div", "presets");
    for (const rule of state.rules) {
      const b = h("button", "preset"); b.type = "button";
      b.append(h("span", null, rule.label || rule.id), h("span", "n num", String(rule.hits ? rule.hits.length : ruleHits(rule))));
      b.addEventListener("click", () => { Object.assign(state.screen, { window: rule.window, direction: rule.direction, threshold: Math.abs(rule.threshold_pct) }); saveScreen(); renderScreener(); });
      pr.appendChild(b);
    }
    cp.appendChild(pr);
    grid.append(cw, cd, ct, cp); panel.appendChild(grid); root.appendChild(panel);
    const head = h("div", "result-head"); head.id = "result-head"; root.appendChild(head);
    const list = h("div", "list"); list.id = "screenlist"; list.style.overflow = "visible"; root.appendChild(list);
    renderScreenResults();
  }
  function renderScreenResults() {
    const rows = screenStocks(); const { window: w, direction, threshold } = state.screen;
    const head = $("#result-head"); head.replaceChildren();
    const dirTxt = direction === "up" ? "up" : direction === "down" ? "down" : "up or down";
    head.appendChild(h("h3", null, `${rows.length} ${rows.length === 1 ? "stock" : "stocks"}`));
    const over = w === "earn" ? "since last earnings" : w === "1d" ? "today" : `over ${WINDOW_LABEL[w].toLowerCase()}`;
    const meta = h("span", "meta"); meta.append(document.createTextNode(`moved ${dirTxt} `), h("b", "num", `${threshold}%+`), document.createTextNode(` ${over}${state.sector ? " · " + state.sector : ""}`));
    head.appendChild(meta);
    if (w === "earn") head.appendChild(h("span", "meta note", "Measured from the last close before each company's most recent earnings report, so the earnings-day reaction is included."));
    const list = $("#screenlist"); list.replaceChildren();
    const cols = h("div", "cols glass");
    ["Company", "Industry group", "30 days", "Mkt cap", "Price", w === "earn" ? "Since ER" : WINDOW_SHORT[w]].forEach((c) => cols.appendChild(h("span", null, c)));
    list.appendChild(cols);
    if (!rows.length) { list.appendChild(h("div", "empty", "Nothing crossed that threshold. Lower the minimum move or widen the time frame.")); return; }
    const frag = document.createDocumentFragment();
    for (const s of rows) {
      const row = renderRow(s, w);
      if (w === "earn" && s.earnDate) row.querySelector(".nm").textContent = `${s.n} · reported ${fmtDate(s.earnDate, true)}`;
      frag.appendChild(row);
    }
    list.appendChild(frag);
  }
  function saveScreen() { try { localStorage.setItem("sp500.screen", JSON.stringify(state.screen)); } catch (_) { /* ignore */ } }

  // ---------- detail sheet ----------
  async function openDetail(t) {
    const s = state.bySym[t]; if (!s) return;
    state.open = t;
    const sheet = $("#sheet"), body = $("#sheet-body");
    $("#sheet-tk").textContent = s.t; $("#sheet-nm").textContent = s.n;
    const path = $("#sheet-path"); path.replaceChildren();
    path.append(tag(s.sector, "tag sector"), tag(s.group), tag(s.sub));
    body.replaceChildren(); body.scrollTop = 0; state.redraws = [];
    // hero
    const hero = h("div", "hero");
    const px = h("div", "px num", fmtPrice(s.price)); hero.appendChild(px);
    const chg = h("div", `chg ${tone(s.chgPct)}`); hero.appendChild(chg);
    const setChg = (delta, pct, when) => { chg.className = `chg ${tone(pct)}`; chg.replaceChildren(h("span", "num", `${fmtSigned(delta)} (${fmtPct(pct)})`), h("span", "when", when)); };
    setChg(s.chg, s.chgPct, "Today");
    body.appendChild(hero);
    const chartWrap = h("div", "chart-wrap"); body.appendChild(chartWrap);
    chartWrap.appendChild(h("div", "loading", "")).appendChild(h("div", "spinner"));
    const ranges = h("div", "ranges");
    const segR = h("div", "seg glass small");
    const rangeRet = h("div", "range-ret"); ranges.append(segR, rangeRet); body.appendChild(ranges);
    body.appendChild(statsSection(s));
    body.appendChild(earningsSection(s));
    const optHost = h("section", "section opt-host"); optHost.appendChild(h("h3", null, "Options"));
    optHost.appendChild(h("div", "loading small")).appendChild(h("div", "spinner"));
    body.appendChild(optHost);
    if (s.desc) {
      const sec = h("section", "section"); sec.appendChild(h("h3", null, "About"));
      sec.appendChild(h("p", "about", s.desc.replace(/\s+\S*$/, "") + (s.desc.length >= 600 ? "…" : "")));
      const links = h("div", "links");
      if (s.site) { const a = h("a", null, s.site.replace(/^https?:\/\/(www\.)?/, "")); a.href = s.site; a.target = "_blank"; a.rel = "noopener"; links.appendChild(a); }
      if (s.hq) links.appendChild(document.createTextNode((s.site ? " · " : "") + s.hq));
      if (s.employees) links.appendChild(document.createTextNode(` · ${Number(s.employees).toLocaleString()} employees`));
      sec.appendChild(links); body.appendChild(sec);
    }
    $("#scrim").classList.add("open"); sheet.classList.add("open"); sheet.setAttribute("aria-hidden", "false");
    try { history.replaceState(null, "", "#" + s.t); } catch (_) { /* ignore */ }
    // chart
    const hist = await historyFor(s);
    if (state.open !== t) return;
    if (hist.news && hist.news.length) body.appendChild(newsSection(hist.news));
    optionsFor(s).then((o) => { if (state.open === t) optionsSection(optHost, s, o); });
    const draw = () => {
      let series;
      if (state.range === "5Y") series = hist.w;
      else series = hist.d.slice(-(RANGE_DAYS[state.range] + 1));
      if (series.length && s.price != null && series[series.length - 1][1] !== s.price) {
        // reflect the live quote at the right edge when the history ends at the prior close
        const last = series[series.length - 1];
        const today = new Date(); const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
        if (last[0] !== iso) series = series.concat([[iso, s.price]]);
      }
      const first = series.length ? series[0][1] : null;
      const rangeWhen = { "1W": "Past week", "1M": "Past month", "3M": "Past 3 months", "6M": "Past 6 months", "1Y": "Past year", "5Y": "Past 5 years" }[state.range];
      const rp = first ? (s.price / first - 1) * 100 : null;
      rangeRet.className = `range-ret ${tone(rp)}`; rangeRet.replaceChildren(h("span", "num", first ? `${fmtSigned(s.price - first)} (${fmtPct(rp)})` : "—"), document.createTextNode(" "), h("span", "when", rangeWhen.toLowerCase()));
      Charts.priceChart(chartWrap, series, {
        fmtValue: fmtPrice,
        fmtDate: (d, long) => state.range === "1W" || state.range === "1M" ? fmtDate(d, true) : (long ? fmtDate(d, true) : fmtDate(d)),
        onHover: (pt) => {
          if (!pt) { px.textContent = fmtPrice(s.price); setChg(s.chg, s.chgPct, "Today"); return; }
          px.textContent = fmtPrice(pt[1]);
          setChg(pt[1] - first, first ? (pt[1] / first - 1) * 100 : null, fmtDate(pt[0], true));
        },
      });
      $$("button", segR).forEach((b) => b.setAttribute("aria-pressed", String(b.textContent === state.range)));
    };
    for (const r of ["1W", "1M", "3M", "6M", "1Y", "5Y"]) {
      const b = h("button", null, r); b.type = "button"; b.addEventListener("click", () => { state.range = r; draw(); }); segR.appendChild(b);
    }
    state.redraws.push(draw);
    draw();
  }
  const tag = (txt, cls = "tag") => h("span", cls, txt);
  function stat(k, v, s) { const d = h("div", "stat"); d.append(h("div", "k", k), h("div", "v", v)); if (s) d.appendChild(h("div", "s", s)); return d; }
  function statsSection(s) {
    const v = s.val || {};
    const sec = h("section", "section");
    const head = h("div", "section-head"); head.appendChild(h("h3", null, "Key stats")); sec.appendChild(head);
    const grid = h("div", "stats");
    grid.append(
      stat("Market cap", fmtCap(s.mcap)),
      stat("P/E (TTM)", fmtX(v.pe), v.epsTtm != null ? `EPS ${fmtSigned(v.epsTtm).replace("+", "")}` : null),
      stat("Fwd P/E", fmtX(v.fpe), v.epsFwd != null ? `Fwd EPS $${v.epsFwd.toFixed(2)}` : null),
    );
    sec.appendChild(grid);
    // the rest lives behind a disclosure so the sheet stays focused
    const more = h("div", "stats more"); more.id = "more-stats";
    more.append(
      stat("P/S", fmtX(v.ps), v.revGrowth != null ? `Rev growth ${fmtPct(v.revGrowth * 100)}` : null),
      stat("P/B", fmtX(v.pb)),
      stat("EV / EBITDA", fmtX(v.evEbitda), v.margin != null ? `Net margin ${(v.margin * 100).toFixed(1)}%` : null),
      stat("Dividend yield", v.divYield != null ? v.divYield.toFixed(2) + "%" : "—"),
      stat("Beta", v.beta != null ? v.beta.toFixed(2) : "—"),
      stat("Volume", fmtInt(v.volume), v.avgVolume ? `avg ${fmtInt(v.avgVolume)}` : null),
      stat("Trading since", s.ipo ? since(s.ipo) : "—", s.ipo ? fmtDate(s.ipo) : "first trade date"),
      stat("Day change", fmtSigned(s.chg), fmtPct(s.chgPct)),
      stat("In S&P 500", s.added ? since(s.added) : "—", s.added ? `added ${fmtDate(s.added)}` : null),
    );
    if (v.lo52 != null && v.hi52 != null && s.price != null) {
      const w = h("div", "stat wide"); w.appendChild(h("div", "k", "52-week range"));
      const rng = h("div", "rng"); const track = h("div", "track"); const knob = h("i");
      const pos = Math.max(0, Math.min(100, ((s.price - v.lo52) / (v.hi52 - v.lo52 || 1)) * 100));
      knob.style.left = pos + "%"; track.appendChild(knob);
      rng.append(h("span", "num", fmtPrice(v.lo52)), track, h("span", "num", fmtPrice(v.hi52)));
      w.appendChild(rng); more.appendChild(w);
    }
    let expanded = false;
    try { expanded = localStorage.getItem("sp500.moreStats") === "1"; } catch (_) { /* ignore */ }
    const toggle = h("button", "disclose"); toggle.type = "button"; toggle.setAttribute("aria-controls", more.id);
    const chev = svgIcon("chev"); chev.classList.add("chev");
    const label = h("span");
    const apply = () => {
      more.hidden = !expanded; toggle.setAttribute("aria-expanded", String(expanded));
      label.textContent = expanded ? "Fewer stats" : `More stats (${more.children.length})`;
    };
    toggle.append(label, chev);
    toggle.addEventListener("click", () => { expanded = !expanded; apply(); try { localStorage.setItem("sp500.moreStats", expanded ? "1" : "0"); } catch (_) { /* ignore */ } });
    apply();
    sec.append(toggle, more);
    return sec;
  }
  function earningsSection(s) {
    const e = s.eps || {};
    const sec = h("section", "section");
    const head = h("div", "section-head"); head.appendChild(h("h3", null, "Earnings per share"));
    const seg = h("div", "seg glass small");
    const wrap = h("div", "earn-chart");
    const legend = h("div", "legend");
    const li1 = h("span"); li1.append(h("i", "est"), document.createTextNode("Expected")); const li2 = h("span"); li2.append(h("i", "act"), document.createTextNode("Actual (green beat, red miss)"));
    legend.append(li1, li2);
    const note = h("div", "earn-note");
    const draw = () => {
      let rows;
      if (state.earnMode === "q") {
        rows = (e.q || []).slice(-4).map((q) => ({ p: q.p, est: q.est, act: q.act, detail: `Reported ${fmtDate(q.d, true)}` }));
        if (e.nextQ && e.nextQ.est != null) rows.push({ p: e.nextQ.p, est: e.nextQ.est, act: null, future: true, when: e.nextQ.d ? fmtDate(e.nextQ.d) : "est.", detail: e.nextQ.d ? `Reports ${fmtDate(e.nextQ.d, true)}${e.nextQ.n ? ` · ${e.nextQ.n} analysts` : ""}` : "Consensus" });
      } else {
        rows = (e.y || []).slice(-4).map((y) => ({ p: y.p.replace("FY", "FY "), est: y.est, act: y.act, detail: y.basis === "gaap" ? "GAAP diluted EPS (no consensus on file)" : "Sum of the four reported quarters" }));
        for (const n of e.nextY || []) rows.push({ p: n.p.replace("FY", "FY "), est: n.est, act: null, future: true, when: n.status === "current" ? "this FY" : "next FY", detail: `Consensus${n.n ? ` · ${n.n} analysts` : ""}${n.low != null ? ` · range $${n.low.toFixed(2)}–$${n.high.toFixed(2)}` : ""}` });
      }
      Charts.earningsChart(wrap, rows);
      $$("button", seg).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.m === state.earnMode)));
      note.replaceChildren();
      if (state.earnMode === "q") {
        const last = (e.q || []).slice(-1)[0];
        if (last && last.est != null && last.act != null) {
          const sp = ((last.act - last.est) / Math.abs(last.est)) * 100;
          const l = h("div"); l.append(document.createTextNode(`${last.p}: reported `), h("b", "num", `$${last.act.toFixed(2)}`), document.createTextNode(` vs `), h("b", "num", `$${last.est.toFixed(2)}`), document.createTextNode(` expected, a ${sp >= 0 ? "beat" : "miss"} of `), h("b", `num ${sp >= 0 ? "up" : "down"}`, fmtPct(sp)));
          note.appendChild(l);
        }
        if (e.nextQ && e.nextQ.est != null) {
          const l = h("div"); l.append(document.createTextNode(`Next: ${e.nextQ.p}${e.nextQ.d ? " on " + fmtDate(e.nextQ.d, true) : ""}, consensus `), h("b", "num", `$${e.nextQ.est.toFixed(2)}`));
          if (e.nextQ.low != null && e.nextQ.high != null) l.append(document.createTextNode(` (range $${e.nextQ.low.toFixed(2)}–$${e.nextQ.high.toFixed(2)})`));
          note.appendChild(l);
        }
        if (!(e.q || []).length) note.appendChild(h("div", null, "No quarterly consensus history on file for this company."));
      } else {
        const ly = (e.y || []).slice(-1)[0];
        if (ly && ly.act != null) { const l = h("div"); l.append(document.createTextNode(`${ly.p.replace("FY", "FY ")} earned `), h("b", "num", `$${ly.act.toFixed(2)}`), document.createTextNode(ly.est != null ? ` against $${ly.est.toFixed(2)} expected.` : ".")); note.appendChild(l); }
        for (const n of e.nextY || []) {
          const prev = n.status === "current" ? ly?.act : (e.nextY || [])[0]?.est;
          const g = prev ? ((n.est / prev) - 1) * 100 : null;
          const l = h("div"); l.append(document.createTextNode(`${n.p.replace("FY", "FY ")} consensus `), h("b", "num", `$${n.est.toFixed(2)}`));
          if (g != null && isFinite(g)) l.append(document.createTextNode(", "), h("b", `num ${tone(g)}`, fmtPct(g)), document.createTextNode(" growth"));
          note.appendChild(l);
        }
        if (!(e.y || []).length) note.appendChild(h("div", null, "No annual EPS history on file."));
      }
    };
    [["q", "Quarterly"], ["y", "Annual"]].forEach(([m, l]) => { const b = h("button", null, l); b.type = "button"; b.dataset.m = m; b.addEventListener("click", () => { state.earnMode = m; draw(); }); seg.appendChild(b); });
    head.appendChild(seg); sec.append(head, legend, wrap, note);
    state.redraws.push(draw);
    requestAnimationFrame(draw); // measure the real width once the section is in the sheet
    return sec;
  }
  // ---------- options ----------
  const optView = { exp: 0, side: "calls" };
  function optionsSection(host, s, data) {
    host.replaceChildren();
    const chain = data.chain || { exps: [] };
    const head = h("div", "section-head"); head.appendChild(h("h3", null, "Options"));
    if (!chain.exps.length) {
      host.append(head, h("p", "about", "No option chain on file for this company."));
      return;
    }
    if (optView.exp >= chain.exps.length) optView.exp = 0;
    const segExp = h("div", "seg glass small");
    chain.exps.forEach((e, i) => {
      const d = parseISO(e.d); const days = Math.max(0, Math.round((d - new Date()) / 864e5));
      const b = h("button"); b.type = "button"; b.append(document.createTextNode(`${MONTHS[d.getMonth()]} ${d.getDate()}`), h("span", "days", ` ${days}d`));
      b.addEventListener("click", () => { optView.exp = i; draw(); }); segExp.appendChild(b);
    });
    head.appendChild(segExp);
    const segSide = h("div", "seg glass small");
    [["calls", "Calls"], ["puts", "Puts"]].forEach(([k, l]) => { const b = h("button", null, l); b.type = "button"; b.dataset.side = k; b.addEventListener("click", () => { optView.side = k; draw(); }); segSide.appendChild(b); });
    const summary = h("div", "opt-summary");
    const wrap = h("div", "opt-wrap");
    const foot = h("div", "opt-foot");
    host.append(head, segSide, summary, wrap, foot);
    const spot = chain.spot || s.price;
    const draw = () => {
      $$("button", segExp).forEach((b, i) => b.setAttribute("aria-pressed", String(i === optView.exp)));
      $$("button", segSide).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.side === optView.side)));
      const exp = chain.exps[optView.exp];
      const rows = exp[optView.side] || [];
      const other = exp[optView.side === "calls" ? "puts" : "calls"] || [];
      const nearest = (arr) => arr.reduce((best, r) => (best == null || Math.abs(r[0] - spot) < Math.abs(best[0] - spot) ? r : best), null);
      const atm = nearest(rows), atmOther = nearest(other);
      summary.replaceChildren();
      summary.append(h("span", null, "Spot "), h("b", "num", fmtPrice(spot)));
      if (atm) summary.append(document.createTextNode(" · ATM "), h("b", "num", `${fmtPrice(atm[0]).replace(".00", "")} ${optView.side === "calls" ? "call" : "put"} ${fmtPrice(atm[1])}`));
      if (atmOther) summary.append(document.createTextNode(` · ${optView.side === "calls" ? "put" : "call"} `), h("b", "num", fmtPrice(atmOther[1])));
      if (atm && atm[6] != null) summary.append(document.createTextNode(" · IV "), h("b", "num", (atm[6] * 100).toFixed(0) + "%"));
      wrap.replaceChildren();
      if (!rows.length) { wrap.appendChild(h("div", "empty", "No strikes on file for this expiration.")); return; }
      const table = h("table", "opt");
      const thead = h("thead"); const hr = h("tr");
      ["Strike", "Last", "Bid", "Ask", "Vol", "OI", "IV"].forEach((c, i) => { const th = h("th", i ? "num" : "strike", c); th.scope = "col"; hr.appendChild(th); });
      thead.appendChild(hr); table.appendChild(thead);
      const tbody = h("tbody");
      for (const r of rows) {
        const itm = optView.side === "calls" ? r[0] < spot : r[0] > spot;
        const tr = h("tr", (r === atm ? "atm " : "") + (itm ? "itm" : ""));
        tr.append(h("td", "strike num", fmtPrice(r[0]).replace(/\.00$/, "")), h("td", "num", fmtPrice(r[1])), h("td", "num", fmtPrice(r[2])), h("td", "num", fmtPrice(r[3])),
          h("td", "num", fmtInt(r[4])), h("td", "num", fmtInt(r[5])), h("td", "num", r[6] != null ? (r[6] * 100).toFixed(0) + "%" : "—"));
        tbody.appendChild(tr);
      }
      table.appendChild(tbody); wrap.appendChild(table);
      const asOf = data.asOf ? new Date(data.asOf) : null;
      foot.textContent = `Standard monthly expirations, strikes near the spot. Snapshot from the last data refresh${asOf ? ` (${MONTHS[asOf.getMonth()]} ${asOf.getDate()}, ${asOf.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })})` : ""}, not live quotes. Shaded rows are in the money.`;
    };
    draw();
  }
  function newsSection(items) {
    const sec = h("section", "section"); sec.appendChild(h("h3", null, "News"));
    const list = h("div", "news-list");
    for (const n of items) {
      if (!n.u) continue;
      const a = newsLink(n, "news-item");
      a.append(h("div", "hl", n.t), h("div", "src", `${n.p ? n.p + " · " : ""}${ago(n.d)}`));
      list.appendChild(a);
    }
    sec.appendChild(list); return sec;
  }
  function closeDetail() {
    state.open = null;
    $("#sheet").classList.remove("open"); $("#sheet").setAttribute("aria-hidden", "true"); $("#scrim").classList.remove("open");
    try { history.replaceState(null, "", location.pathname + location.search); } catch (_) { /* ignore */ }
  }

  // ---------- view switching ----------
  function setView(v) {
    state.view = v;
    $("#list").hidden = v !== "markets"; $("#table").hidden = v !== "table"; $("#screener").hidden = v !== "screener"; $("#list-head").hidden = v === "screener";
    $$("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
    $("#subchips").hidden = v === "screener" || !state.sector;
    if (v === "screener") renderScreener();
    if (v === "table") renderTable();
  }
  function renderAll() {
    renderRail(); renderChips(); renderList();
    if (state.view === "screener") renderScreener();
    if (state.view === "table") renderTable();
  }
  function svgIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", name === "chev" ? "M9 6l6 6-6 6" : "");
    svg.appendChild(p); return svg;
  }

  // ---------- boot ----------
  async function boot() {
    try { await load(); } catch (err) {
      $("#list").replaceChildren(h("div", "loading")).appendChild(h("div", "err", "Could not load data/stocks.json. Run pipeline/fetch_data.py first."));
      console.error(err); return;
    }
    setAsOf();
    $("#refresh").addEventListener("click", refreshAll);
    const search = $("#search");
    const narrow = window.matchMedia("(max-width: 899px)");
    const setPlaceholder = () => { search.placeholder = narrow.matches ? "Search" : "Search ticker or company"; };
    setPlaceholder(); narrow.addEventListener("change", setPlaceholder);
    search.addEventListener("input", () => { state.query = search.value; search.parentElement.classList.toggle("has-value", !!search.value); renderList(); if (state.view === "table") renderTable(); });
    $("#clear").addEventListener("click", () => { search.value = ""; state.query = ""; search.parentElement.classList.remove("has-value"); renderList(); if (state.view === "table") renderTable(); search.focus(); });
    $$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
    $$("#sortseg button").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.key;
      if (state.sort.key === k) state.sort.dir *= -1; else state.sort = { key: k, dir: k === "name" ? 1 : -1 };
      renderList(); if (state.view === "table") renderTable();
    }));
    $("#close").addEventListener("click", closeDetail); $("#scrim").addEventListener("click", closeDetail);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) closeDetail(); });
    let rsz = null;
    window.addEventListener("resize", () => { clearTimeout(rsz); rsz = setTimeout(() => { if (state.open) state.redraws.forEach((f) => f()); }, 150); });
    // swipe down to dismiss on phones
    let y0 = null; const sheet = $("#sheet");
    sheet.addEventListener("touchstart", (e) => { y0 = $("#sheet-body").scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
    sheet.addEventListener("touchmove", (e) => { if (y0 != null && e.touches[0].clientY - y0 > 90 && window.innerWidth < 700) { y0 = null; closeDetail(); } }, { passive: true });
    setView("markets"); renderAll();
    const hash = decodeURIComponent(location.hash.slice(1)).toUpperCase();
    if (hash === "SCREENER") setView("screener"); else if (hash === "TABLE") setView("table"); else if (state.bySym[hash]) openDetail(hash);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", boot) : boot();
})();
