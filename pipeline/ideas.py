#!/usr/bin/env python3
"""Top-10 opportunities for the next session, horizon up to a year.

Three rule-based playbooks score every constituent from the data on disk
(stocks.json, vol.json, options/*.json); each stock keeps its best playbook, and
the top ten are chosen with diversity constraints (at least two per playbook when
available, at most two per sector). Every score is built from percentile ranks so
the weights are transparent and no factor can dominate through scale.

Playbooks
  buy      own the shares: cheap vs. sector on forward P/E, earnings expected to
           grow, a record of beating estimates, a positive medium-term trend,
           and calm options (no crisis pricing).
  cc       covered call: shares you would hold anyway plus rich option premium
           (implied vol well above realized) and a liquid chain; the suggested
           contract is the nearest monthly call about 5% out of the money.
  put      buy puts: earnings expected to fall, a negative trend, misses on
           recent reports, and cheap puts (implied vol at or below realized);
           the suggested contract is the longest monthly put about 5% out of
           the money.
Writes app/data/ideas.json.
"""
import glob
import json
import os
import statistics
import sys
from datetime import date, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOP_N = 10
MAX_PER_SECTOR = 2
MIN_PER_PLAYBOOK = 2


def pct_rank(values, v, higher_is_better=True):
    vals = [x for x in values if x is not None]
    if v is None or not vals:
        return None
    r = sum(1 for x in vals if x <= v) / len(vals)
    return r if higher_is_better else 1 - r


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def pick_strike(rows, spot, side, otm=0.05, min_oi=25):
    """Nearest strike about `otm` out of the money with a live quote. Returns (strike, mid, oi)."""
    cands = []
    for r in rows:
        k, last, bid, ask, vol, oi, iv = r
        if (oi or 0) < min_oi:
            continue
        mid = (bid + ask) / 2 if bid and ask else (last or 0)   # pre-market chains carry no bids
        if mid <= 0:
            continue
        if side == "call" and k >= spot * (1 + otm):
            cands.append((k, mid, oi))
        if side == "put" and k <= spot * (1 - otm):
            cands.append((k, mid, oi))
    if not cands:
        return None
    cands.sort(key=lambda c: abs(c[0] - spot))
    return cands[0]


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "app", "data")
    uni = json.load(open(os.path.join(data_dir, "stocks.json")))
    try:
        vol = json.load(open(os.path.join(data_dir, "vol.json")))["rows"]
    except (OSError, ValueError):
        vol = {}
    chains = {}
    for f in glob.glob(os.path.join(data_dir, "options", "*.json")):
        chains.update(json.load(open(f)).get("chains", {}))
    today = datetime.fromisoformat(uni["asOf"]).date()
    stocks = uni["stocks"]

    # ---- raw factors --------------------------------------------------------
    sector_fpe = {}
    for s in stocks:
        f = (s.get("val") or {}).get("fpe")
        if f and f > 0:
            sector_fpe.setdefault(s["sector"], []).append(f)
    sector_med = {k: statistics.median(v) for k, v in sector_fpe.items()}

    raw = {}
    for s in stocks:
        v = s.get("val") or {}
        eps = s.get("eps") or {}
        q = eps.get("q") or []
        last4 = q[-4:]
        beats = [x for x in last4 if x.get("est") is not None and x.get("act") is not None]
        beat_n = sum(1 for x in beats if x["act"] >= x["est"])
        surprises = [(x["act"] - x["est"]) / abs(x["est"]) * 100 for x in beats if x["est"]]
        ny = eps.get("nextY") or []
        ly = (eps.get("y") or [{}])[-1] if eps.get("y") else {}
        growth = None
        if ny and ny[0].get("est") and ly.get("act"):
            growth = (ny[0]["est"] / ly["act"] - 1) * 100 if ly["act"] > 0 else None
        fpe, pe = v.get("fpe"), v.get("pe")
        rel_val = (sector_med.get(s["sector"], 0) / fpe) if fpe and fpe > 0 and sector_med.get(s["sector"]) else None
        rng = None
        if v.get("lo52") is not None and v.get("hi52") is not None and s.get("price") and v["hi52"] > v["lo52"]:
            rng = (s["price"] - v["lo52"]) / (v["hi52"] - v["lo52"])
        vr = vol.get(s["t"]) or {}
        iv0 = (vr.get("iv") or [None])[0]
        raw[s["t"]] = {
            "rel_val": rel_val, "growth": growth, "pe_gap": (pe - fpe) if pe and fpe else None,
            "beat_n": beat_n, "n_q": len(beats), "avg_surp": (sum(surprises) / len(surprises)) if surprises else None,
            "r3": (s.get("ret") or {}).get("3m"), "r6": (s.get("ret") or {}).get("6m"), "r1y": (s.get("ret") or {}).get("1y"),
            "rng": rng, "ratio": vr.get("ratio"), "prem": vr.get("prem"), "iv0": iv0, "rv60": vr.get("rv60"),
            "jump": vr.get("jump"), "liquid": bool(iv0 and iv0["oi"] >= 100 and (iv0["spr"] is None or iv0["spr"] <= 0.2)),
        }

    col = lambda k: [r[k] for r in raw.values()]
    ranks = {}
    for t, r in raw.items():
        ranks[t] = {
            "val": pct_rank(col("rel_val"), r["rel_val"]),
            "growth": pct_rank(col("growth"), r["growth"]),
            "gap": pct_rank(col("pe_gap"), r["pe_gap"]),
            "trend": pct_rank(col("r6"), r["r6"]),
            "trend3": pct_rank(col("r3"), r["r3"]),
            "volp": pct_rank(col("ratio"), r["ratio"]),
            "beats": (r["beat_n"] / r["n_q"]) if r["n_q"] else None,
        }

    by_sym = {s["t"]: s for s in stocks}

    def fmt_pct(x, signed=True):
        return "—" if x is None else f"{'+' if signed and x > 0 else ''}{x:.0f}%"

    ideas = []
    for s in stocks:
        t = s["t"]; r = raw[t]; k = ranks[t]; sec_med = sector_med.get(s["sector"])
        chain = chains.get(t) or {}
        spot = chain.get("spot") or s["price"]
        exps = [e for e in chain.get("exps", []) if (date.fromisoformat(e["d"]) - today).days >= 5]
        next_er = ((s.get("eps") or {}).get("nextQ") or {}).get("d")
        cands = []

        # ---- buy the shares -------------------------------------------------
        if all(k[x] is not None for x in ("val", "growth", "trend")) and k["beats"] is not None and r["n_q"] >= 3 \
                and (r["r3"] is None or r["r3"] > -12) and (r["growth"] or 0) > 0:
            calm = 1 - (k["volp"] or 0.5)
            score = 0.30 * k["val"] + 0.25 * k["growth"] + 0.20 * k["beats"] + 0.15 * k["trend"] + 0.10 * calm
            reasons = [
                {"label": "Valuation", "text": f"{s['val']['fpe']:.1f}× forward P/E vs {sec_med:.1f}× sector median", "score": k["val"]},
                {"label": "Growth", "text": f"EPS expected {fmt_pct(r['growth'])} next fiscal year", "score": k["growth"]},
                {"label": "Earnings record", "text": f"Beat {r['beat_n']} of last {r['n_q']}" + (f", avg surprise {fmt_pct(r['avg_surp'])}" if r["avg_surp"] is not None else ""), "score": k["beats"]},
                {"label": "Trend", "text": f"{fmt_pct(r['r6'])} over 6 months, {fmt_pct(r['r1y'])} over a year", "score": k["trend"]},
                {"label": "Options calm", "text": f"Implied {r['iv0']['iv']:.0f}% vs realized {r['rv60']:.0f}% (no crisis pricing)" if r["iv0"] and r["rv60"] else "No option data", "score": calm},
            ]
            plan = "Buy shares. Hold up to 12 months; review at each earnings report" + (f" (next {datetime.fromisoformat(next_er).strftime('%b %-d')})" if next_er else "") + ". Consider selling calls against the position once implied vol rises."
            cands.append(("buy", score, reasons, plan, None))

        # ---- covered call ---------------------------------------------------
        if r["liquid"] and exps and k["volp"] is not None and (r["ratio"] or 0) >= 1.15 and k["val"] is not None and k["beats"] is not None:
            e = exps[0] if (date.fromisoformat(exps[0]["d"]) - today).days >= 14 or len(exps) == 1 else exps[1]
            pk = pick_strike(e.get("calls", []), spot, "call", 0.05)
            if pk:
                strike, mid, oi = pk
                dte = (date.fromisoformat(e["d"]) - today).days
                yld = mid / spot * 100
                ann = yld * 365 / dte
                er_in = bool(e.get("earn")) or (next_er and today < date.fromisoformat(next_er) <= date.fromisoformat(e["d"]))
                hold = 0.5 * k["val"] + 0.5 * k["beats"]
                mid_trend = 1 - clamp(abs((k["trend"] or 0.5) - 0.6) * 2)
                score = 0.40 * k["volp"] + 0.20 * hold + 0.15 * mid_trend + 0.15 * clamp(ann / 40) + 0.10 * (0.0 if er_in else 1.0)
                reasons = [
                    {"label": "Premium richness", "text": f"Implied {r['iv0']['iv']:.0f}% vs realized {r['rv60']:.0f}% ({r['ratio']:.2f}×)", "score": k["volp"]},
                    {"label": "Income", "text": f"{e['d'][5:]} ${strike:g} call ≈ ${mid:.2f}: {yld:.1f}% in {dte} days ({ann:.0f}% annualized)", "score": clamp(ann / 40)},
                    {"label": "Happy to hold", "text": f"{s['val']['fpe']:.1f}× forward vs {sec_med:.1f}× sector; beat {r['beat_n']} of {r['n_q']}", "score": hold},
                    {"label": "Trend fit", "text": f"{fmt_pct(r['r6'])} over 6 months (steady, not parabolic, suits call writing)", "score": mid_trend},
                    {"label": "Event risk", "text": "Earnings inside the expiration: cap could be tested" if er_in else "No earnings before expiration", "score": 0.2 if er_in else 1.0},
                ]
                plan = f"Own the shares and sell the {datetime.fromisoformat(e['d']).strftime('%b %-d')} ${strike:g} call (≈${mid:.2f}, {yld:.1f}%). Upside capped at ${strike:g} ({(strike / spot - 1) * 100:.0f}% above spot); roll or let shares go at expiry."
                cands.append(("cc", score, reasons, plan, {"type": "call", "exp": e["d"], "strike": strike, "mid": round(mid, 2), "yieldPct": round(yld, 2), "annPct": round(ann, 1), "dte": dte, "oi": oi}))

        # ---- buy puts --------------------------------------------------------
        if r["liquid"] and exps and k["growth"] is not None and k["trend"] is not None and r["ratio"] is not None and r["ratio"] <= 1.15 \
                and ((r["r3"] or 0) < 0 or (r["growth"] or 0) < 0):
            e = exps[-1]
            pk = pick_strike(e.get("puts", []), spot, "put", 0.05)
            if pk:
                strike, mid, oi = pk
                dte = (date.fromisoformat(e["d"]) - today).days
                cost = mid / spot * 100
                miss_rate = 1 - k["beats"] if k["beats"] is not None else 0.5
                cheap = 1 - k["volp"]
                score = 0.30 * (1 - k["growth"]) + 0.25 * (1 - k["trend"]) + 0.20 * cheap + 0.15 * miss_rate + 0.10 * (1 - (k["val"] or 0.5))
                reasons = [
                    {"label": "Estimates falling", "text": f"EPS expected {fmt_pct(r['growth'])} next fiscal year", "score": 1 - k["growth"]},
                    {"label": "Downtrend", "text": f"{fmt_pct(r['r3'])} over 3 months, {fmt_pct(r['r6'])} over 6", "score": 1 - k["trend"]},
                    {"label": "Puts cheap", "text": f"Implied {r['iv0']['iv']:.0f}% vs realized {r['rv60']:.0f}% ({r['ratio']:.2f}×)", "score": cheap},
                    {"label": "Earnings record", "text": f"Missed {r['n_q'] - r['beat_n']} of last {r['n_q']}", "score": miss_rate},
                    {"label": "Still expensive", "text": f"{s['val']['fpe']:.1f}× forward vs {sec_med:.1f}× sector median" if s["val"].get("fpe") and sec_med else "No forward P/E", "score": 1 - (k["val"] or 0.5)},
                ]
                plan = f"Buy the {datetime.fromisoformat(e['d']).strftime('%b %-d')} ${strike:g} put (≈${mid:.2f}, {cost:.1f}% of spot). Breakeven ${strike - mid:.2f}; risk limited to the premium. Roll out if the thesis holds at expiry."
                cands.append(("put", score, reasons, plan, {"type": "put", "exp": e["d"], "strike": strike, "mid": round(mid, 2), "costPct": round(cost, 2), "breakeven": round(strike - mid, 2), "dte": dte, "oi": oi}))

        for pb, score, reasons, plan, contract in cands:
            er_days = (date.fromisoformat(next_er) - today).days if next_er else None
            ideas.append({"t": t, "n": s["n"], "sector": s["sector"], "playbook": pb, "score": round(score * 100, 1),
                          "reasons": [{**x, "score": round(clamp(x["score"] or 0), 3)} for x in reasons],
                          "plan": plan, "contract": contract, "nextEarnings": next_er, "erDays": er_days,
                          "price": s["price"], "chgPct": s.get("chgPct")})

    # one idea per stock (its best playbook), then diversified top ten
    best = {}
    for i in ideas:
        if i["t"] not in best or i["score"] > best[i["t"]]["score"]:
            best[i["t"]] = i
    pool = sorted(best.values(), key=lambda i: -i["score"])
    picked, sector_n = [], {}

    def take(i):
        picked.append(i); sector_n[i["sector"]] = sector_n.get(i["sector"], 0) + 1

    for pb in ("buy", "cc", "put"):
        for i in [x for x in pool if x["playbook"] == pb]:
            if sum(1 for p in picked if p["playbook"] == pb) >= MIN_PER_PLAYBOOK:
                break
            if sector_n.get(i["sector"], 0) < MAX_PER_SECTOR:
                take(i)
    for i in pool:
        if len(picked) >= TOP_N:
            break
        if i in picked or sector_n.get(i["sector"], 0) >= MAX_PER_SECTOR:
            continue
        take(i)
    picked.sort(key=lambda i: -i["score"])
    for n, i in enumerate(picked, 1):
        i["rank"] = n

    out = {"asOf": uni["asOf"], "forSession": None, "count": len(picked), "ideas": picked,
           "method": {"buy": "cheap vs sector, growing EPS, beats, positive trend, calm options",
                      "cc": "rich premium, liquid chain, shares worth holding, steady trend, no earnings in the window",
                      "put": "falling estimates, downtrend, cheap puts, recent misses, still expensive"}}
    with open(os.path.join(data_dir, "ideas.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"ideas: {len(pool)} candidates, picked {len(picked)}: " + ", ".join(f"{i['t']}({i['playbook']} {i['score']})" for i in picked))


if __name__ == "__main__":
    main()
