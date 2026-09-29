#!/usr/bin/env python3
"""Build the static data set the screener app reads.

Outputs (relative to --out, default app/data):
  stocks.json            universe: one row per constituent with quote, valuation,
                         returns over several windows, a 30-day sparkline and EPS history
  history/<sector>.json  per-sector bundles of 1y daily closes and 5y weekly closes,
                         lazy-loaded by the app when a stock is opened
Run screen.py afterwards to produce alerts.json.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from gics import industry_group, SECTOR_ORDER, SECTOR_SHORT  # noqa: E402

warnings.filterwarnings("ignore")
WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = {"User-Agent": "Mozilla/5.0 (compatible; sp500-screener/1.0)"}
WINDOWS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "6m": 126, "1y": 252}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def num(x, nd=2):
    """Finite float rounded to nd places, else None."""
    try:
        if x is None:
            return None
        f = float(x)
        if not math.isfinite(f):
            return None
        return round(f, nd)
    except (TypeError, ValueError):
        return None


def constituents() -> pd.DataFrame:
    html = requests.get(WIKI, headers=UA, timeout=60).text
    t = pd.read_html(io.StringIO(html))[0]
    t = t.rename(columns={
        "Symbol": "symbol", "Security": "name", "GICS Sector": "sector",
        "GICS Sub-Industry": "sub", "Date added": "added", "Founded": "founded",
        "Headquarters Location": "hq",
    })
    t["yahoo"] = t["symbol"].str.replace(".", "-", regex=False)
    t["group"] = [industry_group(s, u) for s, u in zip(t["sector"], t["sub"])]
    return t[["symbol", "yahoo", "name", "sector", "group", "sub", "added", "founded", "hq"]]


def download_closes(tickers, days, interval) -> pd.DataFrame:
    """Wide frame of closes (split-adjusted, not dividend-adjusted), one column per ticker."""
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    for attempt in range(3):
        try:
            df = yf.download(tickers, start=start, interval=interval, group_by="column",
                             auto_adjust=False, threads=True, progress=False)
            closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
            closes = closes.dropna(how="all")
            if len(closes.columns) >= len(tickers) * 0.9:
                return closes
            log(f"download returned {len(closes.columns)}/{len(tickers)} tickers, retrying")
        except Exception as e:  # noqa: BLE001
            log("download error", e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("price download failed")


def fiscal_quarter_label(report_dt: pd.Timestamp, fye_month: int | None) -> tuple[str, str]:
    """Return (label, quarter_end 'YYYY-MM') for the quarter a report covers.

    A report lands 2-8 weeks after its quarter closes, so step back 35 days to land
    inside the period, then snap to the fiscal quarter relative to the fiscal year end.
    """
    approx = report_dt - timedelta(days=35)
    m, y = approx.month, approx.year
    F = fye_month or 12
    k = (m - F - 1) % 12                 # months elapsed since the fiscal year began (0..11)
    q = k // 3 + 1                       # fiscal quarter 1..4
    fy = y if m <= F else y + 1          # calendar year in which this fiscal year ends
    qe_month = (F + 3 * q - 1) % 12 + 1  # calendar month the quarter ends in
    qe_year = fy if qe_month <= F else fy - 1
    label = f"Q{q} {fy}" if F == 12 else f"Q{q} FY{str(fy)[2:]}"
    return label, f"{qe_year:04d}-{qe_month:02d}"


def fetch_ticker(row) -> dict:
    """Per-ticker fundamentals: quote, valuation, EPS history and estimates."""
    tk = yf.Ticker(row.yahoo)
    out: dict = {"t": row.symbol}
    last_err = None
    for attempt in range(4):
        try:
            info = tk.info or {}
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 ** attempt)
    else:
        log("info failed", row.symbol, last_err)
        info = {}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
    out["price"] = num(price)
    out["prev"] = num(prev)
    out["mcap"] = num(info.get("marketCap"), 0)
    ipo_ms = info.get("firstTradeDateMilliseconds") or info.get("firstTradeDateEpochUtc")
    if ipo_ms:
        ts = ipo_ms / 1000 if abs(ipo_ms) > 1e11 else ipo_ms
        out["ipo"] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    out["val"] = {
        "pe": num(info.get("trailingPE")),
        "fpe": num(info.get("forwardPE")),
        "ps": num(info.get("priceToSalesTrailing12Months")),
        "pb": num(info.get("priceToBook")),
        "evEbitda": num(info.get("enterpriseToEbitda")),
        "evRev": num(info.get("enterpriseToRevenue")),
        "peg": num(info.get("trailingPegRatio")),
        "divYield": num(info.get("dividendYield")),  # already in percent in recent yfinance
        "beta": num(info.get("beta")),
        "hi52": num(info.get("fiftyTwoWeekHigh")),
        "lo52": num(info.get("fiftyTwoWeekLow")),
        "epsTtm": num(info.get("trailingEps")),
        "epsFwd": num(info.get("forwardEps")),
        "revGrowth": num(info.get("revenueGrowth"), 4),
        "margin": num(info.get("profitMargins"), 4),
        "volume": num(info.get("regularMarketVolume"), 0),
        "avgVolume": num(info.get("averageVolume"), 0),
    }
    out["desc"] = (info.get("longBusinessSummary") or "")[:600]
    out["site"] = info.get("website")
    out["employees"] = info.get("fullTimeEmployees")
    fye_month = None
    if info.get("lastFiscalYearEnd"):
        fye_month = datetime.fromtimestamp(info["lastFiscalYearEnd"], tz=timezone.utc).month
    out["fye"] = fye_month

    # ---- quarterly EPS: estimate vs reported -------------------------------
    quarters = []
    try:
        ed = tk.get_earnings_dates(limit=28)
        if ed is not None and len(ed):
            ed = ed.sort_index()
            for dt, r in ed.iterrows():
                est, act = num(r.get("EPS Estimate")), num(r.get("Reported EPS"))
                if est is None and act is None:
                    continue
                label, pend = fiscal_quarter_label(dt, fye_month)
                quarters.append({"d": dt.strftime("%Y-%m-%d"), "p": label, "pe": pend,
                                 "est": est, "act": act})
    except Exception as e:  # noqa: BLE001
        log("earnings_dates failed", row.symbol, e)

    # Keep past reported quarters (with an actual) and the next upcoming one.
    now = pd.Timestamp.now(tz="UTC")
    past = [q for q in quarters if q["act"] is not None]
    upcoming = [q for q in quarters if q["act"] is None and pd.Timestamp(q["d"], tz="UTC") >= now - pd.Timedelta(days=3)]
    # dedupe by period label, keeping the latest row
    seen = {}
    for q in past:
        seen[q["p"]] = q
    past = sorted(seen.values(), key=lambda q: q["d"])

    # ---- forward estimates -------------------------------------------------
    est = {}
    try:
        ee = tk.earnings_estimate
        if ee is not None and len(ee):
            for per in ("0q", "+1q", "0y", "+1y"):
                if per in ee.index:
                    r = ee.loc[per]
                    est[per] = {"avg": num(r.get("avg")), "low": num(r.get("low")),
                                "high": num(r.get("high")), "n": num(r.get("numberOfAnalysts"), 0),
                                "yearAgo": num(r.get("yearAgoEps")), "growth": num(r.get("growth"), 4)}
    except Exception as e:  # noqa: BLE001
        log("earnings_estimate failed", row.symbol, e)

    next_q = None
    if upcoming:
        u = upcoming[0]
        next_q = {"d": u["d"], "p": u["p"], "est": u["est"] if u["est"] is not None else (est.get("0q") or {}).get("avg")}
        if est.get("0q"):
            next_q.update({"low": est["0q"]["low"], "high": est["0q"]["high"], "n": est["0q"]["n"]})
    elif est.get("0q"):
        next_q = {"d": None, "p": "Next Q", "est": est["0q"]["avg"], "low": est["0q"]["low"],
                  "high": est["0q"]["high"], "n": est["0q"]["n"]}

    # ---- annual EPS ----------------------------------------------------------
    # Consensus and "reported" EPS are on an adjusted basis, so a fiscal year's
    # estimate and actual are the sums of its four quarters. Years without four
    # reported quarters fall back to GAAP diluted EPS from the income statement.
    F = fye_month or 12
    by_fy: dict[int, list] = {}
    for q in past:
        qe = pd.Timestamp(q["pe"] + "-01")
        fy = qe.year if qe.month <= F else qe.year + 1
        by_fy.setdefault(fy, []).append(q)
    gaap: dict[int, float] = {}
    try:
        inc = tk.income_stmt
        if inc is not None and "Diluted EPS" in inc.index:
            for col, v in inc.loc["Diluted EPS"].dropna().items():
                if num(v) is not None:
                    gaap[pd.Timestamp(col).year] = num(v)
    except Exception as e:  # noqa: BLE001
        log("income_stmt failed", row.symbol, e)
    years = []
    for fy in sorted(set(by_fy) | set(gaap)):
        qs = by_fy.get(fy, [])
        if len(qs) == 4:
            est_sum = round(sum(q["est"] for q in qs), 2) if all(q["est"] is not None for q in qs) else None
            years.append({"p": f"FY{fy}", "est": est_sum, "act": round(sum(q["act"] for q in qs), 2), "basis": "adj"})
        elif fy in gaap and (not qs or fy < max(by_fy, default=fy)):
            years.append({"p": f"FY{fy}", "est": None, "act": gaap[fy], "basis": "gaap"})

    fy_next = []
    if est.get("0y") and est["0y"]["avg"] is not None:
        base_year = int(years[-1]["p"][2:]) if years else (now.year if now.month <= F else now.year + 1) - 1
        fy_next.append({"p": f"FY{base_year + 1}", "est": est["0y"]["avg"], "low": est["0y"]["low"],
                        "high": est["0y"]["high"], "n": est["0y"]["n"], "status": "current"})
        if est.get("+1y") and est["+1y"]["avg"] is not None:
            fy_next.append({"p": f"FY{base_year + 2}", "est": est["+1y"]["avg"], "low": est["+1y"]["low"],
                            "high": est["+1y"]["high"], "n": est["+1y"]["n"], "status": "next"})

    out["eps"] = {"q": past[-8:], "nextQ": next_q, "y": years[-5:], "nextY": fy_next}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "app", "data"))
    ap.add_argument("--limit", type=int, default=0, help="only first N tickers (testing)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(os.path.join(out_dir, "history"), exist_ok=True)

    log("fetching constituents")
    cons = constituents()
    if args.limit:
        cons = cons.head(args.limit)
    tickers = cons["yahoo"].tolist()
    log(f"{len(tickers)} tickers")

    log("downloading 1y daily closes")
    daily = download_closes(tickers, 400, "1d")
    log("downloading 5y weekly closes")
    weekly = download_closes(tickers, 5 * 366, "1wk")

    log("fetching fundamentals")
    fundamentals: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_ticker, r): r.symbol for r in cons.itertuples(index=False)}
        for f in as_completed(futs):
            sym = futs[f]
            try:
                fundamentals[sym] = f.result()
            except Exception as e:  # noqa: BLE001
                log("ticker failed", sym, e)
                fundamentals[sym] = {"t": sym}
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(tickers)}")

    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stocks = []
    bundles: dict[str, dict] = {}
    for r in cons.itertuples(index=False):
        f = fundamentals.get(r.symbol, {})
        d = daily[r.yahoo].dropna() if r.yahoo in daily else pd.Series(dtype=float)
        w = weekly[r.yahoo].dropna() if r.yahoo in weekly else pd.Series(dtype=float)
        closes = [num(v) for v in d.values]
        price = f.get("price") or (closes[-1] if closes else None)
        prev = f.get("prev") or (closes[-2] if len(closes) > 1 else None)
        rets = {}
        for k, n in WINDOWS.items():
            if k == "1d":
                rets[k] = num((price / prev - 1) * 100) if price and prev else None
            elif len(closes) > n and closes[-1 - n]:
                rets[k] = num((price / closes[-1 - n] - 1) * 100) if price else None
            else:
                rets[k] = None
        row = {
            "t": r.symbol, "n": r.name, "sector": r.sector, "group": r.group, "sub": r.sub,
            "hq": r.hq if isinstance(r.hq, str) else None,
            "added": str(r.added)[:10] if pd.notna(r.added) else None,
            "founded": str(r.founded) if pd.notna(r.founded) else None,
            "price": price, "prev": prev,
            "chg": num(price - prev) if price and prev else None,
            "chgPct": rets["1d"],
            "mcap": f.get("mcap"), "ipo": f.get("ipo"),
            "ret": rets,
            "spark": closes[-30:],
            "val": f.get("val", {}),
            "eps": f.get("eps", {}),
            "fye": f.get("fye"),
            "desc": f.get("desc"), "site": f.get("site"), "employees": f.get("employees"),
        }
        stocks.append(row)
        b = bundles.setdefault(slug(r.sector), {})
        b[r.symbol] = {
            "d": [[ts.strftime("%Y-%m-%d"), num(v)] for ts, v in d.items()],
            "w": [[ts.strftime("%Y-%m-%d"), num(v)] for ts, v in w.items()],
        }

    # sector tree: sector -> groups -> sub-industries, with counts
    tree = []
    for sec in SECTOR_ORDER:
        rows = [s for s in stocks if s["sector"] == sec]
        if not rows:
            continue
        groups = {}
        for s in rows:
            g = groups.setdefault(s["group"], {"name": s["group"], "subs": {}, "count": 0})
            g["count"] += 1
            g["subs"][s["sub"]] = g["subs"].get(s["sub"], 0) + 1
        tree.append({
            "name": sec, "short": SECTOR_SHORT.get(sec, sec), "slug": slug(sec), "count": len(rows),
            "mcap": sum(s["mcap"] or 0 for s in rows),
            "groups": sorted(
                [{"name": g["name"], "count": g["count"],
                  "subs": [{"name": k, "count": v} for k, v in sorted(g["subs"].items())]}
                 for g in groups.values()], key=lambda g: -g["count"]),
        })

    with open(os.path.join(out_dir, "stocks.json"), "w") as fh:
        json.dump({"asOf": as_of, "count": len(stocks), "sectors": tree, "stocks": stocks},
                  fh, separators=(",", ":"))
    for sec, b in bundles.items():
        with open(os.path.join(out_dir, "history", f"{sec}.json"), "w") as fh:
            json.dump(b, fh, separators=(",", ":"))
    missing_price = [s["t"] for s in stocks if s["price"] is None]
    log(f"wrote {len(stocks)} stocks, {len(bundles)} history bundles; missing price: {missing_price}")


if __name__ == "__main__":
    main()
