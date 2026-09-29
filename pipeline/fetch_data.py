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
import glob
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
FETCH_OPTIONS = True

import threading

class Throttle:
    """Global cap on request rate across worker threads (Yahoo throttles bursts)."""
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next_at:
                time.sleep(self.next_at - now)
                now = time.monotonic()
            self.next_at = max(now, self.next_at) + self.interval


THROTTLE = Throttle(4.0)


def is_rate_limit(err: Exception) -> bool:
    msg = str(err).lower()
    return "too many requests" in msg or "rate limit" in msg or "429" in msg


def with_retry(label: str, fn, attempts: int = 4, default=None):
    """Call fn() through the throttle; back off on rate limits (6s, 12s, 24s)."""
    for attempt in range(attempts):
        THROTTLE.wait()
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if is_rate_limit(e) and attempt < attempts - 1:
                time.sleep(6 * (2 ** attempt))
                continue
            log(label, "failed:", str(e)[:120])
            return default
    return default


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


def since_earnings(closes: pd.Series, report_date: str | None, price) -> float | None:
    """Percent move from the last close strictly before the most recent earnings
    report to the current price, so the earnings-day reaction is included."""
    if not report_date or closes is None or len(closes) == 0 or not price:
        return None
    idx = closes.index.tz_localize(None) if getattr(closes.index, "tz", None) is not None else closes.index
    prior = closes[idx < pd.Timestamp(report_date)]
    if prior.empty or not prior.iloc[-1]:
        return None
    return num((price / float(prior.iloc[-1]) - 1) * 100)


def is_monthly_expiry(date_str: str) -> bool:
    """Standard monthly options expire the third Friday (Thursday when Friday is a holiday)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return 15 <= d.day <= 21 and d.weekday() in (3, 4)


def fetch_options(tk, price, n_expiries=3):
    """Option chains for the next monthly expirations, trimmed to strikes near the spot.

    Rows are [strike, last, bid, ask, volume, openInterest, impliedVol]. Strikes within
    ±20% of spot are kept, widening to ±35% when a side would have fewer than 8 rows.
    """
    out = {"spot": num(price), "exps": []}
    if not price:
        return out
    listed = with_retry(f"options list {tk.ticker}", lambda: tk.options, default=None)
    if listed is None:
        return out
    exps = [e for e in listed if is_monthly_expiry(e)][:n_expiries]
    for exp in exps:
        chain = with_retry(f"option_chain {tk.ticker} {exp}", lambda: tk.option_chain(exp), default=None)
        if chain is None:
            continue
        sides = {}
        for side, df in (("calls", chain.calls), ("puts", chain.puts)):
            rows = []
            if df is not None and len(df):
                for band in (0.20, 0.35):
                    sub = df[(df["strike"] >= price * (1 - band)) & (df["strike"] <= price * (1 + band))]
                    if len(sub) >= 8 or band == 0.35:
                        break
                for r in sub.sort_values("strike").itertuples():
                    rows.append([num(r.strike), num(r.lastPrice), num(r.bid), num(r.ask),
                                 int(r.volume) if r.volume == r.volume else 0,
                                 int(r.openInterest) if r.openInterest == r.openInterest else 0,
                                 num(r.impliedVolatility, 3)])
            sides[side] = rows
        out["exps"].append({"d": exp, **sides})
    return out


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
    info = with_retry(f"info {row.symbol}", lambda: tk.info or {}, default={}) or {}

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
        ed = with_retry(f"earnings_dates {row.symbol}", lambda: tk.get_earnings_dates(limit=28), default=None)
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
        ee = with_retry(f"earnings_estimate {row.symbol}", lambda: tk.earnings_estimate, default=None)
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
        inc = with_retry(f"income_stmt {row.symbol}", lambda: tk.income_stmt, default=None)
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

    # ---- news: latest ticker-scoped headlines ----------------------------------
    news = []
    try:
        found = with_retry(f"news {row.symbol}", lambda: yf.Search(row.yahoo, news_count=8, include_cb=False).news or [], default=[])
        for it in found:
            if not it.get("title") or not it.get("link"):
                continue
            news.append({"t": it["title"].strip(), "u": it["link"], "p": it.get("publisher"),
                         "d": int(it.get("providerPublishTime") or 0)})
        news.sort(key=lambda n: -n["d"])
    except Exception as e:  # noqa: BLE001
        log("news failed", row.symbol, e)
    out["news"] = news[:6]

    # ---- option chains (next monthly expirations) ------------------------------
    out["opt"] = fetch_options(tk, price) if FETCH_OPTIONS else {"spot": num(price), "exps": []}
    return out


def load_previous(out_dir: str) -> dict[str, dict]:
    """Rebuild per-ticker fundamentals from the files a previous run wrote."""
    prev: dict[str, dict] = {}
    try:
        uni = json.load(open(os.path.join(out_dir, "stocks.json")))
    except (OSError, ValueError):
        return prev
    hist: dict[str, dict] = {}
    for fpath in glob.glob(os.path.join(out_dir, "history", "*.json")):
        hist.update(json.load(open(fpath)))
    opts: dict[str, dict] = {}
    for fpath in glob.glob(os.path.join(out_dir, "options", "*.json")):
        opts.update(json.load(open(fpath)).get("chains", {}))
    for s in uni.get("stocks", []):
        t = s["t"]
        prev[t] = {
            "t": t, "price": s.get("price"), "prev": s.get("prev"), "mcap": s.get("mcap"), "ipo": s.get("ipo"),
            "val": s.get("val", {}), "desc": s.get("desc"), "site": s.get("site"), "employees": s.get("employees"),
            "fye": s.get("fye"), "eps": s.get("eps", {}), "news": (hist.get(t) or {}).get("news") or [],
            "opt": opts.get(t) or {"spot": s.get("price"), "exps": []},
        }
    return prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "app", "data"))
    ap.add_argument("--limit", type=int, default=0, help="only first N tickers (testing)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-options", action="store_true", help="skip option chains (faster dev runs)")
    ap.add_argument("--retry-missing", action="store_true",
                    help="refetch only tickers whose previous output lacks news, estimates or option chains")
    ap.add_argument("--rate", type=float, default=4.0, help="max requests per second across workers")
    args = ap.parse_args()
    THROTTLE.interval = 1.0 / args.rate
    global FETCH_OPTIONS
    FETCH_OPTIONS = not args.skip_options
    out_dir = os.path.abspath(args.out)
    os.makedirs(os.path.join(out_dir, "history"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "options"), exist_ok=True)

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

    # previous outputs, reused for tickers that are already complete in --retry-missing mode
    fundamentals: dict[str, dict] = {}
    to_fetch = list(cons.itertuples(index=False))
    if args.retry_missing:
        prev = load_previous(out_dir)
        to_fetch = []
        for r in cons.itertuples(index=False):
            f = prev.get(r.symbol)
            complete = f and f.get("news") and (f.get("eps") or {}).get("nextQ") and (
                not FETCH_OPTIONS or (f.get("opt") or {}).get("exps"))
            if complete:
                fundamentals[r.symbol] = f
            else:
                to_fetch.append(r)
        log(f"retry-missing: {len(to_fetch)} incomplete tickers, {len(fundamentals)} reused")

    log("fetching fundamentals")
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_ticker, r): r.symbol for r in to_fetch}
        for f in as_completed(futs):
            sym = futs[f]
            try:
                fundamentals[sym] = f.result()
            except Exception as e:  # noqa: BLE001
                log("ticker failed", sym, e)
                fundamentals[sym] = {"t": sym}
            done += 1
            if done % 50 == 0:
                log(f"  {done}/{len(to_fetch)}")

    as_of = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stocks = []
    bundles: dict[str, dict] = {}
    opt_bundles: dict[str, dict] = {}
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
        last_q = (f.get("eps") or {}).get("q") or []
        earn_date = last_q[-1]["d"] if last_q else None
        rets["earn"] = since_earnings(d, earn_date, price)
        row = {
            "t": r.symbol, "n": r.name, "sector": r.sector, "group": r.group, "sub": r.sub,
            "hq": r.hq if isinstance(r.hq, str) else None,
            "added": str(r.added)[:10] if pd.notna(r.added) else None,
            "founded": str(r.founded) if pd.notna(r.founded) else None,
            "price": price, "prev": prev,
            "chg": num(price - prev) if price and prev else None,
            "chgPct": rets["1d"],
            "mcap": f.get("mcap"), "ipo": f.get("ipo"),
            "ret": rets, "earnDate": earn_date,
            "spark": closes[-30:],
            "val": f.get("val", {}),
            "eps": f.get("eps", {}),
            "fye": f.get("fye"),
            "desc": f.get("desc"), "site": f.get("site"), "employees": f.get("employees"),
            "news": (f.get("news") or [None])[0],
        }
        stocks.append(row)
        b = bundles.setdefault(slug(r.sector), {})
        b[r.symbol] = {
            "d": [[ts.strftime("%Y-%m-%d"), num(v)] for ts, v in d.items()],
            "w": [[ts.strftime("%Y-%m-%d"), num(v)] for ts, v in w.items()],
            "news": f.get("news") or [],
        }
        opt_bundles.setdefault(slug(r.sector), {})[r.symbol] = f.get("opt") or {"spot": price, "exps": []}

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
    for sec, b in opt_bundles.items():
        with open(os.path.join(out_dir, "options", f"{sec}.json"), "w") as fh:
            json.dump({"asOf": as_of, "chains": b}, fh, separators=(",", ":"))
    missing_price = [s["t"] for s in stocks if s["price"] is None]
    with_opts = sum(1 for b in opt_bundles.values() for v in b.values() if v.get("exps"))
    log(f"wrote {len(stocks)} stocks, {len(bundles)} history bundles, options for {with_opts}; missing price: {missing_price}")


if __name__ == "__main__":
    main()
