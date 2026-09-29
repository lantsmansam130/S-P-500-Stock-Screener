/* Hand-built SVG charts: sparkline, price line with crosshair, earnings dots.
   No library; every mark is placed with one linear scale per axis. */
(function (global) {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const scale = (d0, d1, r0, r1) => {
    const span = d1 - d0 || 1;
    return (v) => r0 + ((v - d0) / span) * (r1 - r0);
  };
  const toneOf = (a, b) => (b > a ? "up" : b < a ? "down" : "flat");
  /** Draw at the container's real width so nothing is stretched; 600 when not yet laid out. */
  const widthOf = (container) => Math.max(280, Math.round(container.getBoundingClientRect().width) || 600);
  const COLOR = { up: "var(--up)", down: "var(--down)", flat: "var(--fg-2)", accent: "var(--accent)" };

  /** Sparkline: closes[] -> <svg>. Colored by the direction over the whole span. */
  function sparkline(closes, w = 110, h = 34) {
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", class: "spark", "aria-hidden": "true" });
    const pts = (closes || []).filter((v) => v != null);
    if (pts.length < 2) return svg;
    const tone = toneOf(pts[0], pts[pts.length - 1]);
    const min = Math.min(...pts), max = Math.max(...pts);
    const x = scale(0, pts.length - 1, 1, w - 1), y = scale(min, max, h - 2, 2);
    const d = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const gid = "g" + Math.random().toString(36).slice(2, 8);
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: "0", "stop-color": COLOR[tone], "stop-opacity": ".28" }, grad);
    el("stop", { offset: "1", "stop-color": COLOR[tone], "stop-opacity": "0" }, grad);
    el("path", { d: `${d}L${x(pts.length - 1).toFixed(1)},${h}L${x(0).toFixed(1)},${h}Z`, fill: `url(#${gid})` }, svg);
    el("path", { d, fill: "none", stroke: COLOR[tone], "stroke-width": 1.6, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }, svg);
    return svg;
  }

  /** Price chart. series: [[dateISO, close], ...]. onHover(point|null) reports the hovered point. */
  function priceChart(container, series, opts = {}) {
    container.replaceChildren();
    const W = widthOf(container), H = 220, padL = 6, padR = 6, padT = 14, padB = 22;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img" }, container);
    const tip = document.createElement("div"); tip.className = "tip"; container.appendChild(tip);
    const pts = (series || []).filter((p) => p[1] != null);
    if (pts.length < 2) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "var(--fg-3)", "font-size": 13 }, svg).textContent = "No price history"; return; }
    const vals = pts.map((p) => p[1]);
    const min = Math.min(...vals), max = Math.max(...vals);
    const tone = toneOf(vals[0], vals[vals.length - 1]);
    const x = scale(0, pts.length - 1, padL, W - padR), y = scale(min, max, H - padB, padT);
    // reference line at the first close (Robinhood convention) + min/max labels
    const y0 = y(vals[0]);
    el("line", { x1: padL, x2: W - padR, y1: y0, y2: y0, stroke: "var(--fg-3)", "stroke-width": 1, "stroke-dasharray": "2 4", opacity: .6, "vector-effect": "non-scaling-stroke" }, svg);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(p[1]).toFixed(2)}`).join("");
    const gid = "pg" + Math.random().toString(36).slice(2, 8);
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: "0", "stop-color": COLOR[tone], "stop-opacity": ".22" }, grad);
    el("stop", { offset: "1", "stop-color": COLOR[tone], "stop-opacity": "0" }, grad);
    el("path", { d: `${d}L${x(pts.length - 1).toFixed(2)},${H - padB}L${padL},${H - padB}Z`, fill: `url(#${gid})` }, svg);
    const line = el("path", { d, fill: "none", stroke: COLOR[tone], "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }, svg);
    // end dot with surface ring
    const lx = x(pts.length - 1), ly = y(vals[vals.length - 1]);
    el("circle", { cx: lx, cy: ly, r: 5.5, fill: "var(--bg)" }, svg);
    el("circle", { cx: lx, cy: ly, r: 3.5, fill: COLOR[tone] }, svg);
    // x labels: first, middle, last dates
    const fmtD = opts.fmtDate || ((s) => s);
    [0, Math.floor((pts.length - 1) / 2), pts.length - 1].forEach((i, k) => {
      el("text", { x: x(i), y: H - 6, "text-anchor": k === 0 ? "start" : k === 1 ? "middle" : "end", fill: "var(--fg-3)", "font-size": 11, "font-family": "inherit" }, svg).textContent = fmtD(pts[i][0]);
    });
    // crosshair
    const cross = el("g", { style: "display:none" }, svg);
    const vline = el("line", { y1: padT, y2: H - padB, stroke: "var(--fg-2)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, cross);
    el("circle", { r: 6, fill: "var(--bg)" }, cross);
    const dot = el("circle", { r: 4, fill: COLOR[tone] }, cross);
    const ring = cross.children[1];
    const fmtV = opts.fmtValue || ((v) => v);
    const move = (clientX) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(pts.length - 1, Math.round(((clientX - r.left) / r.width) * (pts.length - 1))));
      const px = x(i), py = y(pts[i][1]);
      cross.style.display = "";
      vline.setAttribute("x1", px); vline.setAttribute("x2", px);
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); ring.setAttribute("cx", px); ring.setAttribute("cy", py);
      line.setAttribute("opacity", ".85");
      tip.style.display = "block";
      const leftPx = (px / W) * r.width;
      tip.style.left = Math.max(60, Math.min(r.width - 60, leftPx)) + "px";
      tip.replaceChildren();
      const b = document.createElement("b"); b.textContent = fmtV(pts[i][1]);
      const dd = document.createElement("span"); dd.className = "d"; dd.textContent = fmtD(pts[i][0], true);
      tip.append(b, dd);
      opts.onHover && opts.onHover(pts[i], i);
    };
    const leave = () => { cross.style.display = "none"; tip.style.display = "none"; line.removeAttribute("opacity"); opts.onHover && opts.onHover(null); };
    svg.addEventListener("pointermove", (e) => move(e.clientX));
    svg.addEventListener("pointerdown", (e) => move(e.clientX));
    svg.addEventListener("pointerleave", leave);
    svg.addEventListener("pointerup", leave);
    svg.addEventListener("pointercancel", leave);
  }

  /** Earnings dots. rows: [{p, est, act, future}] in time order.
      Estimate = lightly shaded dot; actual = solid dot colored by beat/miss. */
  function earningsChart(container, rows, opts = {}) {
    container.replaceChildren();
    const W = widthOf(container), H = 230, small = W < 440, padL = small ? 38 : 44, padR = small ? 10 : 16, padT = 18, padB = 44;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img" }, container);
    const tip = document.createElement("div"); tip.className = "tip"; container.appendChild(tip);
    if (!rows || !rows.length) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "var(--fg-3)", "font-size": 13 }, svg).textContent = "No earnings data"; return; }
    const vals = rows.flatMap((r) => [r.est, r.act]).filter((v) => v != null);
    let min = Math.min(0, ...vals), max = Math.max(0, ...vals);
    if (min === max) { max = min + 1; }
    const pad = (max - min) * 0.12; min -= pad; max += pad;
    const inset = small ? 22 : 30;
    const x = scale(0, rows.length - 1, padL + inset, W - padR - inset), y = scale(min, max, H - padB, padT);
    // gridlines: 4 clean ticks
    const step = niceStep((max - min) / 4);
    for (let t = Math.ceil(min / step) * step; t <= max; t += step) {
      const yy = y(t);
      el("line", { x1: padL, x2: W - padR, y1: yy, y2: yy, stroke: "var(--hairline)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, svg);
      el("text", { x: padL - 8, y: yy + 4, "text-anchor": "end", fill: "var(--fg-3)", "font-size": 11, "font-family": "inherit" }, svg).textContent = fmtEps(t);
    }
    if (min < 0 && max > 0) el("line", { x1: padL, x2: W - padR, y1: y(0), y2: y(0), stroke: "var(--fg-3)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, svg);
    // divider between reported and future periods
    const firstFuture = rows.findIndex((r) => r.future);
    if (firstFuture > 0) {
      const xx = (x(firstFuture - 1) + x(firstFuture)) / 2;
      el("line", { x1: xx, x2: xx, y1: padT, y2: H - padB + 6, stroke: "var(--fg-3)", "stroke-width": 1, "stroke-dasharray": "3 4", opacity: .7, "vector-effect": "non-scaling-stroke" }, svg);
    }
    rows.forEach((r, i) => {
      const cx = x(i);
      const g = el("g", { class: "ep", tabindex: 0, role: "img" }, svg);
      // hit area
      const half = Math.min(28, (x(1) - x(0)) / 2 || 28);
      el("rect", { x: cx - half, y: padT - 6, width: half * 2, height: H - padT - padB + 12, fill: "transparent" }, g);
      if (r.est != null) {
        const cy = y(r.est);
        el("circle", { cx, cy, r: 8, fill: "var(--bg)" }, g);
        el("circle", { cx, cy, r: 6, fill: "var(--fg-2)", opacity: r.future ? .55 : .35 }, g);
      }
      if (r.act != null) {
        const cy = y(r.act);
        const tone = r.est == null ? "accent" : r.act >= r.est ? "up" : "down";
        if (r.est != null) el("line", { x1: cx, x2: cx, y1: y(r.est), y2: cy, stroke: COLOR[tone], "stroke-width": 1.5, opacity: .5, "vector-effect": "non-scaling-stroke" }, g);
        el("circle", { cx, cy, r: 8, fill: "var(--bg)" }, g);
        el("circle", { cx, cy, r: 6, fill: COLOR[tone] }, g);
      }
      el("text", { x: cx, y: H - padB + 18, "text-anchor": "middle", fill: r.future ? "var(--fg-3)" : "var(--fg-2)", "font-size": small ? 10.5 : 11.5, "font-weight": 600, "font-family": "inherit" }, g).textContent = r.p;
      const sub = el("text", { x: cx, y: H - padB + 33, "text-anchor": "middle", "font-size": small ? 10 : 11, "font-family": "inherit" }, g);
      if (r.act != null && r.est != null && r.est !== 0) {
        const sp = ((r.act - r.est) / Math.abs(r.est)) * 100;
        sub.setAttribute("fill", sp >= 0 ? "var(--up)" : "var(--down)");
        sub.textContent = (sp >= 0 ? "+" : "") + sp.toFixed(1) + "%";
      } else if (r.future) { sub.setAttribute("fill", "var(--fg-3)"); sub.textContent = r.when || "est."; }
      const show = () => {
        tip.style.display = "block";
        const rect = svg.getBoundingClientRect();
        tip.style.left = Math.max(70, Math.min(rect.width - 70, (cx / W) * rect.width)) + "px";
        tip.replaceChildren();
        const l1 = document.createElement("div");
        const b = document.createElement("b"); b.textContent = r.act != null ? "Actual " + fmtEps(r.act) : "Expected " + fmtEps(r.est);
        l1.appendChild(b);
        if (r.act != null && r.est != null) { const s = document.createElement("span"); s.className = "d"; s.textContent = "est. " + fmtEps(r.est); l1.appendChild(s); }
        const l2 = document.createElement("div"); l2.className = "d"; l2.style.marginLeft = 0; l2.textContent = r.detail || r.p;
        tip.append(l1, l2);
        g.querySelectorAll("circle:nth-of-type(even)").forEach((c) => c.setAttribute("r", 7));
      };
      const hide = () => { tip.style.display = "none"; g.querySelectorAll("circle:nth-of-type(even)").forEach((c) => c.setAttribute("r", 6)); };
      g.addEventListener("pointerenter", show); g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", show); g.addEventListener("blur", hide);
      g.addEventListener("pointerdown", show);
    });
  }
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function fmtEps(v) { return (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2); }

  /** Rolling realized vol line with dashed horizontal implied-vol levels.
      series: [[dateISO, vol%]], levels: [{label, value}]. */
  function volChart(container, series, levels, opts = {}) {
    container.replaceChildren();
    const W = widthOf(container), H = 200, small = W < 440, padL = 34, padR = small ? 48 : 64, padT = 12, padB = 22;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img" }, container);
    const tip = document.createElement("div"); tip.className = "tip"; container.appendChild(tip);
    const pts = (series || []).filter((p) => p[1] != null);
    if (pts.length < 2) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: "var(--fg-3)", "font-size": 13 }, svg).textContent = "Not enough history"; return; }
    const vals = pts.map((p) => p[1]).concat(levels.map((l) => l.value).filter((v) => v != null));
    let min = 0, max = Math.max(...vals) * 1.12 || 10;
    const x = scale(0, pts.length - 1, padL, W - padR), y = scale(min, max, H - padB, padT);
    const step = niceStep((max - min) / 4);
    for (let t = 0; t <= max; t += step) {
      el("line", { x1: padL, x2: W - padR, y1: y(t), y2: y(t), stroke: "var(--hairline)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, svg);
      el("text", { x: padL - 6, y: y(t) + 4, "text-anchor": "end", fill: "var(--fg-3)", "font-size": 10.5, "font-family": "inherit" }, svg).textContent = t.toFixed(0) + "%";
    }
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(p[1]).toFixed(2)}`).join("");
    el("path", { d, fill: "none", stroke: "var(--fg-2)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }, svg);
    // implied levels, labels stacked apart if they collide
    const placed = [];
    levels.filter((l) => l.value != null).sort((a, b) => b.value - a.value).forEach((l) => {
      const yy = y(l.value);
      el("line", { x1: padL, x2: W - padR, y1: yy, y2: yy, stroke: "var(--accent)", "stroke-width": 1.5, "stroke-dasharray": "4 4", "vector-effect": "non-scaling-stroke" }, svg);
      let ly = yy + 4; while (placed.some((p) => Math.abs(p - ly) < 12)) ly += 12; placed.push(ly);
      el("text", { x: W - padR + 6, y: ly, fill: "var(--accent)", "font-size": 10.5, "font-weight": 600, "font-family": "inherit" }, svg).textContent = l.label;
    });
    const fmtD = opts.fmtDate || ((s) => s);
    [0, Math.floor((pts.length - 1) / 2), pts.length - 1].forEach((i, k) => {
      el("text", { x: x(i), y: H - 6, "text-anchor": k === 0 ? "start" : k === 1 ? "middle" : "end", fill: "var(--fg-3)", "font-size": 10.5, "font-family": "inherit" }, svg).textContent = fmtD(pts[i][0]);
    });
    const cross = el("g", { style: "display:none" }, svg);
    const vline = el("line", { y1: padT, y2: H - padB, stroke: "var(--fg-2)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, cross);
    el("circle", { r: 6, fill: "var(--bg)" }, cross); const dot = el("circle", { r: 4, fill: "var(--fg)" }, cross); const ring = cross.children[1];
    const move = (clientX) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(pts.length - 1, Math.round(((clientX - r.left) / r.width) * (pts.length - 1))));
      const px = x(i), py = y(pts[i][1]);
      cross.style.display = ""; vline.setAttribute("x1", px); vline.setAttribute("x2", px);
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); ring.setAttribute("cx", px); ring.setAttribute("cy", py);
      tip.style.display = "block"; tip.style.left = Math.max(60, Math.min(r.width - 60, (px / W) * r.width)) + "px";
      tip.replaceChildren(); const b = document.createElement("b"); b.textContent = pts[i][1].toFixed(1) + "% realized"; const dd = document.createElement("span"); dd.className = "d"; dd.textContent = fmtD(pts[i][0], true); tip.append(b, dd);
    };
    const leave = () => { cross.style.display = "none"; tip.style.display = "none"; };
    svg.addEventListener("pointermove", (e) => move(e.clientX)); svg.addEventListener("pointerdown", (e) => move(e.clientX));
    svg.addEventListener("pointerleave", leave); svg.addEventListener("pointerup", leave); svg.addEventListener("pointercancel", leave);
  }

  global.Charts = { sparkline, priceChart, earningsChart, volChart };
})(window);
