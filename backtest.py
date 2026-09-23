#!/usr/bin/env python3
"""
Backtest for the Kalshi Weather Fair-Value Tool.

For each city and each settled Kalshi daily-high event in the window:
  * day-1 forecast high   : Open-Meteo Previous Runs API, hourly
                            temperature_2m_previous_day1 (GFS + ECMWF), max over
                            the local calendar day
  * actual                : Kalshi's own settlement reading (expiration_value)
                            cross-checked against the NWS CLI product archived
                            by Iowa Environmental Mesonet
  * market price          : Kalshi 1440-min candlestick close of the last full
                            day before the target date (yes_bid / yes_ask)
Then it fits a per-city normal error model (bias, sigma), prices every market,
and compares model vs market: Brier, calibration, and a simple strategy P&L.

Outputs: backtest_results.md, backtest_results.json, params.json
Standard library only.  Raw downloads are cached in ./cache so re-runs are fast.

    python backtest.py [--days 60] [--city NYC --city CHI] [--no-cache]
"""
import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
from collections import defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_edge as we  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
MODELS = ["gfs_seamless", "ecmwf_ifs025"]
EDGE_THRESHOLD = 0.08
STAKE = 10.0


# ---------------------------------------------------------------------------
# cached fetch
# ---------------------------------------------------------------------------
def cached(key, fn, use_cache=True):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, key + ".json")
    if use_cache and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    data = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def fetch_settled(series, use_cache):
    return cached(f"settled_{series}", lambda: we.kalshi_markets(series, "settled", limit=100, max_pages=12), use_cache)


def fetch_prev_runs(city, use_cache, past_days):
    c = we.CITIES[city]
    url = ("https://previous-runs-api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": c["lat"], "longitude": c["lon"],
        "hourly": "temperature_2m,temperature_2m_previous_day1,temperature_2m_previous_day2",
        "temperature_unit": "fahrenheit", "timezone": c["tz"], "past_days": past_days, "forecast_days": 1,
        "models": ",".join(MODELS)}))
    return cached(f"openmeteo_{city}_{past_days}", lambda: we.http_json(url, timeout=90, sleep=0.3), use_cache)


def fetch_cli(city, year, use_cache):
    st = we.CITIES[city]["cli"]
    url = f"https://mesonet.agron.iastate.edu/json/cli.py?station={st}&year={year}&fmt=json"
    return cached(f"cli_{st}_{year}", lambda: we.http_json(url, timeout=90, sleep=0.2), use_cache)


def fetch_candles(event, tickers, close_iso, use_cache):
    close_ts = int(dt.datetime.fromisoformat(close_iso.replace("Z", "+00:00")).timestamp())
    start = close_ts - 10 * 86400
    url = (f"{we.KALSHI}/markets/candlesticks?market_tickers={','.join(tickers)}"
           f"&start_ts={start}&end_ts={close_ts}&period_interval=1440")
    return cached(f"candles_{event}", lambda: we.http_json(url, headers=we.UA_KALSHI, sleep=0.35), use_cache)


# ---------------------------------------------------------------------------
# forecast daily maxima from hourly previous-run series
# ---------------------------------------------------------------------------
def daily_max_from_hourly(om):
    """returns {date: {'gfs_d1':..,'ecm_d1':..,'gfs_d2':..,'ecm_d2':..,'gfs_d0':..}}"""
    h = om["hourly"]
    keymap = {}
    for k in h:
        if k == "time":
            continue
        model = "gfs" if "gfs" in k else ("ecm" if "ecmwf" in k else None)
        if model is None and len(MODELS) == 1:
            model = "gfs" if MODELS[0].startswith("gfs") else "ecm"
        horizon = "d1" if "previous_day1" in k else ("d2" if "previous_day2" in k else "d0")
        keymap[k] = f"{model}_{horizon}"
    out = defaultdict(dict)
    for i, t in enumerate(h["time"]):
        day = t[:10]
        for k, name in keymap.items():
            v = h[k][i]
            if v is None:
                continue
            if v > out[day].get(name, -999.0):
                out[day][name] = v
    return out


# ---------------------------------------------------------------------------
# stats helpers
# ---------------------------------------------------------------------------
def fit_normal(errs):
    n = len(errs)
    if n < 3:
        return None
    mu = statistics.fmean(errs)
    sd = statistics.stdev(errs)
    m3 = sum((e - mu) ** 3 for e in errs) / n
    m4 = sum((e - mu) ** 4 for e in errs) / n
    skew = m3 / (sd ** 3) if sd > 0 else 0.0
    kurt = m4 / (sd ** 4) - 3.0 if sd > 0 else 0.0
    within1 = sum(1 for e in errs if abs(e - mu) <= sd) / n
    within2 = sum(1 for e in errs if abs(e - mu) <= 2 * sd) / n
    mae = statistics.fmean(abs(e) for e in errs)
    return dict(n=n, bias=round(mu, 3), sigma=round(sd, 3), mae=round(mae, 3), skew=round(skew, 2), excess_kurtosis=round(kurt, 2),
                within_1sd=round(within1, 3), within_2sd=round(within2, 3),
                normal_ok=bool(abs(skew) < 1.0 and abs(kurt) < 2.0 and 0.55 <= within1 <= 0.82))


def brier(pairs):
    return statistics.fmean((p - y) ** 2 for p, y in pairs) if pairs else float("nan")


def calibration(pairs, bins=10):
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if sel:
            table.append(dict(bin=f"{lo:.1f}-{hi:.1f}", n=len(sel), mean_pred=round(statistics.fmean(p for p, _ in sel), 3),
                              observed=round(statistics.fmean(y for _, y in sel), 3)))
        else:
            table.append(dict(bin=f"{lo:.1f}-{hi:.1f}", n=0, mean_pred=None, observed=None))
    return table


def day_before_candle(candles, close_iso):
    """Pick the last 1440-min candle that ended at least 12h before close_time."""
    close_ts = int(dt.datetime.fromisoformat(close_iso.replace("Z", "+00:00")).timestamp())
    cutoff = close_ts - 12 * 3600
    best = None
    for c in candles:
        if c["end_period_ts"] <= cutoff and (best is None or c["end_period_ts"] > best["end_period_ts"]):
            best = c
    return best


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_rows(cities, days, use_cache, log):
    """Collect one record per (city, date, market)."""
    today = dt.date.today()
    start_day = today - dt.timedelta(days=days)
    records, day_records, cli_mismatch, notes = [], [], [], []
    for code in cities:
        c = we.CITIES[code]
        t0 = time.time()
        try:
            settled = fetch_settled(c["series"], use_cache)
        except Exception as e:
            notes.append(f"{code}: settled markets fetch failed: {e}")
            continue
        if not settled:
            notes.append(f"{code}: no settled markets")
            continue
        try:
            om = daily_max_from_hourly(fetch_prev_runs(code, use_cache, days + 2))
        except Exception as e:
            notes.append(f"{code}: Open-Meteo previous-runs fetch failed: {e}")
            continue
        cli = {}
        try:
            for r in fetch_cli(code, today.year, use_cache).get("results", []):
                if isinstance(r.get("high"), (int, float)):
                    cli[r["valid"]] = float(r["high"])
        except Exception as e:
            notes.append(f"{code}: IEM CLI fetch failed ({e}); cross-check skipped")

        events = defaultdict(list)
        for m in settled:
            d = we.parse_ticker_date(m["ticker"])
            if d and start_day <= d < today and m.get("result") in ("yes", "no"):
                events[d].append(m)

        station = we.station_from_rules(settled[0].get("rules_primary")) or c["station"]
        n_days = 0
        for d in sorted(events):
            mk = events[d]
            iso = d.isoformat()
            fc = om.get(iso, {})
            if "gfs_d1" not in fc and "ecm_d1" not in fc:
                continue
            # actual settlement value: Kalshi expiration_value (same on every market of the event)
            actual = None
            for m in mk:
                v = we.fnum(m.get("expiration_value"))
                if v is not None:
                    actual = v
                    break
            if actual is None:
                # infer from the bracket that resolved yes
                for m in mk:
                    if m["result"] == "yes" and m.get("strike_type") == "between":
                        lo, hi = we.market_interval(m)
                        actual = (lo + hi) / 2.0
                if actual is None:
                    continue
            # consistency: does the actual reproduce every market's result?
            ok = True
            for m in mk:
                lo, hi = we.market_interval(m)
                inside = (lo is None or actual >= lo) and (hi is None or actual <= hi)
                if inside != (m["result"] == "yes"):
                    ok = False
            if not ok:
                notes.append(f"{code} {iso}: expiration_value {actual} inconsistent with market results; skipped")
                continue
            cli_v = cli.get(iso)
            if cli_v is not None and abs(cli_v - actual) > 0.5:
                cli_mismatch.append(dict(city=code, date=iso, kalshi=actual, iem_cli=cli_v))
            try:
                cd = fetch_candles(f"{c['series']}-{d.strftime('%y%b%d').upper()}", [m["ticker"] for m in mk], mk[0]["close_time"], use_cache)
            except Exception as e:
                notes.append(f"{code} {iso}: candlesticks failed: {e}")
                cd = {"markets": []}
            candle_by_ticker = {}
            for entry in cd.get("markets", []):
                cb = day_before_candle(entry.get("candlesticks", []), mk[0]["close_time"])
                if cb:
                    candle_by_ticker[entry["market_ticker"]] = cb
            fvals = {k: fc.get(k) for k in ("gfs_d1", "ecm_d1", "gfs_d2", "ecm_d2", "gfs_d0", "ecm_d0")}
            blend1 = statistics.fmean([v for v in (fvals["gfs_d1"], fvals["ecm_d1"]) if v is not None])
            blend2 = [v for v in (fvals["gfs_d2"], fvals["ecm_d2"]) if v is not None]
            blend2 = statistics.fmean(blend2) if blend2 else None
            day_records.append(dict(city=code, date=iso, actual=actual, iem_cli=cli_v, gfs_d1=fvals["gfs_d1"], ecm_d1=fvals["ecm_d1"],
                                    blend_d1=blend1, blend_d2=blend2, gfs_d2=fvals["gfs_d2"], ecm_d2=fvals["ecm_d2"]))
            n_days += 1
            for m in mk:
                cb = candle_by_ticker.get(m["ticker"])
                bid = ask = None
                if cb:
                    bid = we.fnum(cb.get("yes_bid", {}).get("close_dollars"))
                    ask = we.fnum(cb.get("yes_ask", {}).get("close_dollars"))
                lo, hi = we.market_interval(m)
                records.append(dict(city=code, date=iso, ticker=m["ticker"], strike_type=m.get("strike_type"), lo=lo, hi=hi,
                                    y=1 if m["result"] == "yes" else 0, actual=actual, blend_d1=blend1, gfs_d1=fvals["gfs_d1"],
                                    ecm_d1=fvals["ecm_d1"], bid=bid, ask=ask, station=station,
                                    volume=we.fnum(m.get("volume_fp"), 0.0)))
        log(f"  {code:5s} {n_days:3d} days, {sum(1 for r in records if r['city']==code):4d} markets, station {station}  ({time.time()-t0:.0f}s)")
    return records, day_records, cli_mismatch, notes


def evaluate(records, day_records, fit_key, params_by_city, label):
    """Price all markets with params_by_city and compare to the market."""
    model_pairs, market_pairs, model_pairs_q, cal_rows = [], [], [], []
    pnl_yes, pnl_no = [], []
    for r in records:
        p = params_by_city.get(r["city"])
        if p is None:
            continue
        f = r[fit_key]
        if f is None:
            continue
        mp = we.prob_interval(r["lo"], r["hi"], f + p["bias"], p["sigma"])
        model_pairs.append((mp, r["y"]))
        quoted = r["bid"] is not None and r["ask"] is not None and r["ask"] < 1.0 and r["bid"] > 0.0 and r["ask"] > r["bid"] - 1e-9
        if quoted:
            mid = (r["bid"] + r["ask"]) / 2.0
            market_pairs.append((mid, r["y"]))
            model_pairs_q.append((mp, r["y"]))
            # strategy: buy YES when model >= ask + threshold
            if mp - r["ask"] >= EDGE_THRESHOLD:
                n = max(1, math.floor(STAKE / r["ask"]))
                fee = we.kalshi_fee(r["ask"], n)
                gain = n * (1.0 - r["ask"]) - fee if r["y"] else -n * r["ask"] - fee
                pnl_yes.append(dict(ticker=r["ticker"], date=r["date"], city=r["city"], model=round(mp, 3), ask=r["ask"], n=n, fee=fee, pnl=round(gain, 2), y=r["y"]))
            no_ask = 1.0 - r["bid"]
            if (1.0 - mp) - no_ask >= EDGE_THRESHOLD:
                n = max(1, math.floor(STAKE / no_ask))
                fee = we.kalshi_fee(no_ask, n)
                gain = n * (1.0 - no_ask) - fee if not r["y"] else -n * no_ask - fee
                pnl_no.append(dict(ticker=r["ticker"], date=r["date"], city=r["city"], model_no=round(1 - mp, 3), no_ask=round(no_ask, 2), n=n, fee=fee, pnl=round(gain, 2), y=r["y"]))

    def pnl_summary(trades):
        if not trades:
            return dict(trades=0, wins=0, staked=0.0, fees=0.0, pnl=0.0, roi=None)
        staked = sum(t["n"] * (t.get("ask") or t.get("no_ask")) for t in trades)
        return dict(trades=len(trades), wins=sum(1 for t in trades if t["pnl"] > 0), staked=round(staked, 2),
                    fees=round(sum(t["fee"] for t in trades), 2), pnl=round(sum(t["pnl"] for t in trades), 2),
                    roi=round(sum(t["pnl"] for t in trades) / staked, 4) if staked else None)

    return dict(
        label=label, n_markets_all=len(model_pairs), n_markets_quoted=len(market_pairs),
        brier_model_all=round(brier(model_pairs), 4),
        brier_model_quoted=round(brier(model_pairs_q), 4), brier_market_quoted=round(brier(market_pairs), 4),
        brier_climatology_quoted=round(brier([(statistics.fmean(y for _, y in market_pairs), y) for _, y in market_pairs]), 4) if market_pairs else None,
        calibration_model=calibration(model_pairs_q), calibration_market=calibration(market_pairs),
        strategy_buy_yes=pnl_summary(pnl_yes), strategy_buy_no=pnl_summary(pnl_no),
        trades_yes=pnl_yes, trades_no=pnl_no,
    )


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--city", action="append")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)
    cities = [c.upper() for c in a.city] if a.city else list(we.CITIES)
    log = lambda s: print(s, file=sys.stderr, flush=True)
    log(f"backtest: {len(cities)} cities, last {a.days} days")
    records, day_records, cli_mismatch, notes = build_rows(cities, a.days, not a.no_cache, log)
    if not day_records:
        log("no data collected; aborting"); return 1

    # ---- error distributions per city, three forecast candidates -------------
    fits = {}
    for key in ("gfs_d1", "ecm_d1", "blend_d1", "blend_d2"):
        fits[key] = {}
        for code in cities:
            errs = [d["actual"] - d[key] for d in day_records if d["city"] == code and d.get(key) is not None]
            f = fit_normal(errs)
            if f:
                fits[key][code] = f
        pooled = [d["actual"] - d[key] for d in day_records if d.get(key) is not None]
        fits[key]["_pooled"] = fit_normal(pooled)

    # choose the day-1 forecast candidate with the lowest pooled sigma
    best_key = min(("gfs_d1", "ecm_d1", "blend_d1"), key=lambda k: fits[k]["_pooled"]["sigma"])
    log(f"pooled sigma: " + ", ".join(f"{k}={fits[k]['_pooled']['sigma']}" for k in ("gfs_d1", "ecm_d1", "blend_d1")) + f" -> using {best_key}")

    def params_from(fit_map, min_n=10):
        pooled = fit_map["_pooled"]
        out = {}
        for code in cities:
            f = fit_map.get(code)
            if f and f["n"] >= min_n:
                out[code] = dict(bias=f["bias"], sigma=f["sigma"])
            elif f:
                # shrink toward pooled when the sample is small
                w = f["n"] / min_n
                out[code] = dict(bias=round(w * f["bias"] + (1 - w) * pooled["bias"], 3), sigma=round(w * f["sigma"] + (1 - w) * pooled["sigma"], 3))
        return out

    # ---- in-sample evaluation (fit on everything) ----------------------------
    in_sample = evaluate(records, day_records, best_key, params_from(fits[best_key]), "in-sample (fit on all days)")

    # ---- out-of-sample: fit on first half of dates, test on second half -------
    dates = sorted({d["date"] for d in day_records})
    split = dates[len(dates) // 2]
    fit_oos = {}
    for code in cities:
        errs = [d["actual"] - d[best_key] for d in day_records if d["city"] == code and d["date"] < split]
        f = fit_normal(errs)
        if f:
            fit_oos[code] = f
    fit_oos["_pooled"] = fit_normal([d["actual"] - d[best_key] for d in day_records if d["date"] < split])
    test_records = [r for r in records if r["date"] >= split]
    out_sample = evaluate(test_records, day_records, best_key, params_from(fit_oos), f"out-of-sample (fit before {split}, test from {split})")
    # pooled-only variant on the same test set (one bias/sigma for every city)
    pooled_params = {code: dict(bias=fit_oos["_pooled"]["bias"], sigma=fit_oos["_pooled"]["sigma"]) for code in cities}
    out_sample_pooled = evaluate(test_records, day_records, best_key, pooled_params, f"out-of-sample, pooled params (test from {split})")

    # ---- params.json ----------------------------------------------------------
    params = dict(fitted_at=dt.date.today().isoformat(), forecast_key=best_key, days=a.days, cities={})
    p1 = params_from(fits[best_key])
    p2 = params_from(fits["blend_d2"])
    for code in cities:
        if code in p1:
            params["cities"][code] = dict(bias=p1[code]["bias"], sigma1=p1[code]["sigma"],
                                          sigma2=p2.get(code, {}).get("sigma", round(p1[code]["sigma"] * 1.2, 3)),
                                          n=fits[best_key][code]["n"], normal_ok=fits[best_key][code]["normal_ok"])
    params["pooled"] = dict(bias=fits[best_key]["_pooled"]["bias"], sigma1=fits[best_key]["_pooled"]["sigma"], sigma2=fits["blend_d2"]["_pooled"]["sigma"])
    params["note"] = ("Error = Kalshi settlement reading minus Open-Meteo day-1 forecast high (" + best_key + "). "
                      "Live tool applies these to the NWS forecast; see README caveat.")
    with open(os.path.join(HERE, "params.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, indent=1)

    # ---- results json ---------------------------------------------------------
    results = dict(generated=dt.datetime.now().isoformat(timespec="seconds"), days=a.days, cities=cities,
                   n_city_days=len(day_records), n_markets=len(records), forecast_key=best_key,
                   fits={k: v for k, v in fits.items()}, cli_mismatches=cli_mismatch, notes=notes,
                   in_sample=in_sample, out_of_sample=out_sample, out_of_sample_pooled=out_sample_pooled,
                   day_records=day_records)
    with open(os.path.join(HERE, "backtest_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)

    # ---- markdown -------------------------------------------------------------
    L = []
    L.append(f"# Backtest results: Kalshi daily-high markets vs forecast-error model\n")
    L.append(f"Generated {results['generated']}. Window: last {a.days} days ({dates[0]} to {dates[-1]}). "
             f"{len(cities)} cities, {len(day_records)} city-days, {len(records)} settled markets, "
             f"{in_sample['n_markets_quoted']} of them with a two-sided quote at the day-before close.\n")
    L.append("**Ground truth** = Kalshi's own `expiration_value` (The Weather Company reading at the station named in the rules). "
             f"Cross-checked against the NWS CLI product archived by IEM: {len(cli_mismatch)} mismatch(es) of >0.5F across "
             f"{sum(1 for d in day_records if d['iem_cli'] is not None)} city-days with a CLI value.\n")
    L.append("**Forecast** = Open-Meteo Previous Runs API, hourly `temperature_2m_previous_day1` (the model run from one day earlier), "
             "max over the local calendar day. Candidates: GFS, ECMWF IFS 0.25, and their average. "
             f"Selected by lowest pooled sigma: **{best_key}**.\n")
    L.append("**Market price** = close of the Kalshi 1440-minute candle that ended at least 12h before the market close "
             "(i.e. the last full day before the target date), yes_bid / yes_ask; mid used for Brier, ask for buying.\n")

    L.append("## 1. Forecast error by city (actual minus day-1 forecast, deg F)\n")
    rows = []
    for code in cities:
        f = fits[best_key].get(code)
        if f:
            rows.append([code, f["n"], f["bias"], f["sigma"], f["mae"], f["skew"], f["excess_kurtosis"], f["within_1sd"], f["within_2sd"], "yes" if f["normal_ok"] else "no"])
    pf = fits[best_key]["_pooled"]
    rows.append(["**pooled**", pf["n"], pf["bias"], pf["sigma"], pf["mae"], pf["skew"], pf["excess_kurtosis"], pf["within_1sd"], pf["within_2sd"], "yes" if pf["normal_ok"] else "no"])
    L.append(md_table(["city", "n days", "bias", "sigma", "MAE", "skew", "ex. kurt", "within 1sd", "within 2sd", "normal ok?"], rows))
    L.append("\n`normal ok?` = |skew| < 1, |excess kurtosis| < 2, and 55-82% of errors inside one sigma (a normal gives 68%). "
             "Where it says no, tails are fatter than normal and the model will under-price far-out brackets.\n")
    L.append("Pooled sigma by forecast candidate: " + ", ".join(f"{k} = {fits[k]['_pooled']['sigma']} (bias {fits[k]['_pooled']['bias']})" for k in ("gfs_d1", "ecm_d1", "blend_d1", "blend_d2")) + ".\n")

    def eval_section(ev, title):
        L.append(f"## {title}\n")
        L.append(f"*{ev['label']}*  \n")
        L.append(f"Markets priced: {ev['n_markets_all']}; with a two-sided market quote: {ev['n_markets_quoted']}.\n")
        L.append(md_table(["", "Brier (lower is better)"], [
            ["Model (quoted markets)", ev["brier_model_quoted"]],
            ["Market mid (quoted markets)", ev["brier_market_quoted"]],
            ["Base rate (constant)", ev["brier_climatology_quoted"]],
            ["Model (all markets incl. unquoted)", ev["brier_model_all"]]]))
        better = ev["brier_model_quoted"] < ev["brier_market_quoted"]
        L.append(f"\n**{'The model beats the market' if better else 'The market beats the model'}** on Brier score by "
                 f"{abs(ev['brier_model_quoted'] - ev['brier_market_quoted']):.4f}.\n")
        L.append("Calibration, model vs market (10% bins of predicted probability):\n")
        rows = []
        for cm, ck in zip(ev["calibration_model"], ev["calibration_market"]):
            rows.append([cm["bin"], cm["n"], cm["mean_pred"], cm["observed"], ck["n"], ck["mean_pred"], ck["observed"]])
        L.append(md_table(["bin", "model n", "model mean p", "observed", "market n", "market mean p", "observed"], rows))
        sy, sn = ev["strategy_buy_yes"], ev["strategy_buy_no"]
        L.append(f"\nStrategy: buy YES when model probability >= market ask + {EDGE_THRESHOLD:.2f}, ${STAKE:.0f} stake per trade "
                 "(floor(stake/ask) contracts), Kalshi fee 0.07 x P x (1-P) per contract rounded up to the cent.\n")
        L.append(md_table(["strategy", "trades", "wins", "staked $", "fees $", "P&L $", "ROI"], [
            ["Buy YES (as specified)", sy["trades"], sy["wins"], sy["staked"], sy["fees"], sy["pnl"], sy["roi"]],
            ["Buy NO (mirror: model NO prob >= NO ask + 0.08)", sn["trades"], sn["wins"], sn["staked"], sn["fees"], sn["pnl"], sn["roi"]]]))
        L.append("")

    eval_section(in_sample, "2. In-sample (parameters fitted on the same days)")
    eval_section(out_sample, "3. Out-of-sample (fit on first half of the window, test on the second half)")
    eval_section(out_sample_pooled, "4. Out-of-sample with one pooled bias/sigma for every city")

    L.append("## 5. Sample of out-of-sample YES trades\n")
    tr = out_sample["trades_yes"][:25]
    L.append(md_table(["date", "city", "ticker", "model", "ask", "n", "fee", "P&L"], [[t["date"], t["city"], t["ticker"], t["model"], t["ask"], t["n"], t["fee"], t["pnl"]] for t in tr]) if tr else "(no trades)")
    if cli_mismatch:
        L.append("\n## 6. Kalshi vs IEM CLI mismatches\n")
        L.append(md_table(["city", "date", "Kalshi", "IEM CLI"], [[m["city"], m["date"], m["kalshi"], m["iem_cli"]] for m in cli_mismatch]))
    if notes:
        L.append("\n## Notes / data gaps\n")
        L += [f"- {n}" for n in notes[:60]]
    L.append("\n## How to read this honestly\n")
    L.append("- The in-sample numbers use parameters fitted on the very days being scored; they are the optimistic bound.\n"
             "- The out-of-sample numbers are the fair test. A day-before Kalshi close already incorporates the same public forecasts, "
             "so the market is a hard benchmark; the base-rate row shows what a no-information forecaster scores.\n"
             "- The market Brier is scored on the quote mid; you cannot trade at mid. The P&L rows pay the ask plus fees.\n"
             "- 8-cent-edge trades are concentrated in low-priced brackets where a normal tail is most wrong; treat the P&L as a small sample.\n")
    with open(os.path.join(HERE, "backtest_results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    log("wrote backtest_results.md, backtest_results.json, params.json")
    log(f"IN-SAMPLE   model Brier {in_sample['brier_model_quoted']} vs market {in_sample['brier_market_quoted']}; YES P&L {in_sample['strategy_buy_yes']['pnl']} on {in_sample['strategy_buy_yes']['trades']} trades")
    log(f"OUT-SAMPLE  model Brier {out_sample['brier_model_quoted']} vs market {out_sample['brier_market_quoted']}; YES P&L {out_sample['strategy_buy_yes']['pnl']} on {out_sample['strategy_buy_yes']['trades']} trades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
