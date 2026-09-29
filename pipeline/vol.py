#!/usr/bin/env python3
"""Implied vs. realized volatility for every constituent.

Reads the files fetch_data.py wrote (stocks.json, history/*.json, options/*.json)
and writes:
  app/data/vol.json         one row per stock: realized vol (20/60/250d), at-the-money
                            implied vol per monthly expiration with liquidity, the
                            front-month premium over realized, and percentile ranks
  app/data/iv_history.json  one front-month ATM IV per stock per run date, kept for
                            ~400 runs, so an IV-rank screen can be added once history accrues

Method: realized vol is the annualised standard deviation of daily log returns.
ATM implied vol is the average of the call and put IVs interpolated to the spot
from the two strikes that bracket it, using only quotes with a live bid.
"""
import glob
import json
import math
import os
import sys
from datetime import date, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WINDOWS = {"rv20": 20, "rv60": 60, "rv250": 250}
MIN_DTE = 5          # skip an expiry inside its last week: pinning noise, not a vol view
HIST_KEEP = 400


def realized(closes, n):
    c = [v for _, v in closes if v][-(n + 1):]
    if len(c) < n + 1:
        return None, None
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    jump = max(x * x for x in r) / max(sum(x * x for x in r), 1e-12)   # share of variance from the single largest day
    return math.sqrt(var * 252) * 100, jump


def atm_iv(exp, spot):
    """(iv%, open interest at the money, relative bid-ask spread) or (None, 0, None)."""
    ivs, ois, sprs = [], 0, []
    for side in ("calls", "puts"):
        rows = [r for r in exp.get(side, []) if r[6] and 0.03 < r[6] < 3 and (r[2] or 0) > 0]
        if len(rows) < 2:
            continue
        below = [r for r in rows if r[0] <= spot]
        above = [r for r in rows if r[0] >= spot]
        if not below or not above:
            continue
        a, b = below[-1], above[0]
        w = 0 if a[0] == b[0] else (spot - a[0]) / (b[0] - a[0])
        ivs.append(a[6] * (1 - w) + b[6] * w)
        for r in (a, b):
            ois += r[5] or 0
            mid = ((r[2] or 0) + (r[3] or 0)) / 2
            if mid > 0 and r[3]:
                sprs.append((r[3] - r[2]) / mid)
    if not ivs:
        return None, 0, None
    return sum(ivs) / len(ivs) * 100, ois, (sum(sprs) / len(sprs) if sprs else None)


def pct_rank(values, v):
    if v is None or not values:
        return None
    return round(sum(1 for x in values if x <= v) / len(values), 3)


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "app", "data")
    uni = json.load(open(os.path.join(data_dir, "stocks.json")))
    hist, opts = {}, {}
    for f in glob.glob(os.path.join(data_dir, "history", "*.json")):
        hist.update(json.load(open(f)))
    for f in glob.glob(os.path.join(data_dir, "options", "*.json")):
        opts.update(json.load(open(f)).get("chains", {}))
    today = datetime.fromisoformat(uni["asOf"]).date()

    rows = {}
    for s in uni["stocks"]:
        t = s["t"]
        closes = hist.get(t, {}).get("d", [])
        chain = opts.get(t) or {}
        spot = chain.get("spot") or s["price"]
        row = {}
        for k, n in WINDOWS.items():
            row[k], j = realized(closes, n)
            if k == "rv60":
                row["jump"] = round(j, 3) if j is not None else None
        ivs = []
        next_er = (s.get("eps") or {}).get("nextQ", {}) or {}
        er_date = date.fromisoformat(next_er["d"]) if next_er.get("d") else None
        for e in chain.get("exps", []):
            d = date.fromisoformat(e["d"])
            dte = (d - today).days
            if dte < MIN_DTE:
                continue
            iv, oi, spr = atm_iv(e, spot)
            if iv is None:
                continue
            ivs.append({"d": e["d"], "dte": dte, "iv": round(iv, 1), "oi": oi,
                        "spr": round(spr, 3) if spr is not None else None,
                        "earn": bool(er_date and today < er_date <= d)})
        row["iv"] = ivs
        for k in WINDOWS:
            if row[k] is not None:
                row[k] = round(row[k], 1)
        if ivs and row["rv60"]:
            row["prem"] = round(ivs[0]["iv"] - row["rv60"], 1)
            row["ratio"] = round(ivs[0]["iv"] / row["rv60"], 2)
        rows[t] = row

    # percentile ranks of the front-month IV/RV60 ratio, across the index and within sector
    sector_of = {s["t"]: s["sector"] for s in uni["stocks"]}
    all_ratios = [r["ratio"] for r in rows.values() if r.get("ratio")]
    by_sector = {}
    for t, r in rows.items():
        if r.get("ratio"):
            by_sector.setdefault(sector_of[t], []).append(r["ratio"])
    for t, r in rows.items():
        r["pctAll"] = pct_rank(all_ratios, r.get("ratio"))
        r["pctSec"] = pct_rank(by_sector.get(sector_of[t], []), r.get("ratio"))

    with open(os.path.join(data_dir, "vol.json"), "w") as fh:
        json.dump({"asOf": uni["asOf"], "rows": rows}, fh, separators=(",", ":"))

    # IV history: one front-month ATM IV per stock per run date
    hp = os.path.join(data_dir, "iv_history.json")
    try:
        ivh = json.load(open(hp))
    except (OSError, ValueError):
        ivh = {"dates": [], "iv": {}}
    day = today.isoformat()
    if day in ivh["dates"]:
        idx = ivh["dates"].index(day)
    else:
        ivh["dates"].append(day)
        idx = len(ivh["dates"]) - 1
        for arr in ivh["iv"].values():
            arr.append(None)
    for t, r in rows.items():
        arr = ivh["iv"].setdefault(t, [None] * len(ivh["dates"]))
        while len(arr) < len(ivh["dates"]):
            arr.append(None)
        arr[idx] = r["iv"][0]["iv"] if r.get("iv") else None
    if len(ivh["dates"]) > HIST_KEEP:
        cut = len(ivh["dates"]) - HIST_KEEP
        ivh["dates"] = ivh["dates"][cut:]
        ivh["iv"] = {t: a[cut:] for t, a in ivh["iv"].items()}
    with open(hp, "w") as fh:
        json.dump(ivh, fh, separators=(",", ":"))

    n = sum(1 for r in rows.values() if r.get("ratio"))
    print(f"vol: {n}/{len(rows)} stocks with front-month IV and 60d realized; median ratio "
          f"{sorted(all_ratios)[len(all_ratios) // 2] if all_ratios else None}")


if __name__ == "__main__":
    main()
