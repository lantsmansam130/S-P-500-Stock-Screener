#!/usr/bin/env python3
"""Apply the rules in screener.config.json to stocks.json and write alerts.json.

Each rule: window (1d|1w|1m|3m|6m|1y), threshold_pct (magnitude), direction
(up|down|either). The app also runs these rules live so the thresholds can be
tuned in the UI; this file is the daily record.
"""
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "app", "data")
    cfg = json.load(open(os.path.join(ROOT, "screener.config.json")))
    uni = json.load(open(os.path.join(data_dir, "stocks.json")))
    results = []
    for rule in cfg["rules"]:
        win, thr, direction = rule["window"], abs(float(rule["threshold_pct"])), rule.get("direction", "either")
        hits = []
        for s in uni["stocks"]:
            r = (s.get("ret") or {}).get(win)
            if r is None:
                continue
            ok = (direction == "up" and r >= thr) or (direction == "down" and r <= -thr) or \
                 (direction == "either" and abs(r) >= thr)
            if ok:
                hits.append({"t": s["t"], "n": s["n"], "sector": s["sector"], "ret": r, "price": s["price"]})
        hits.sort(key=lambda h: -abs(h["ret"]))
        results.append({**{k: v for k, v in rule.items() if not k.startswith("_")}, "hits": hits})
    out = {"asOf": uni["asOf"], "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "rules": results}
    with open(os.path.join(data_dir, "alerts.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    for r in results:
        print(f"{r['id']}: {len(r['hits'])} hits")


if __name__ == "__main__":
    main()
