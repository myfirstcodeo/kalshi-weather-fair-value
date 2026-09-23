#!/usr/bin/env python3
"""
Kalshi Weather Fair-Value Tool  (pm-weather-edge)

Scans every open Kalshi US daily high-temperature series, pulls the NWS
forecast for each city's settlement station, prices every bracket / threshold
market with a per-city forecast-error model fitted by backtest.py, pulls live
Kalshi prices and prints edge, quarter-Kelly and fee-adjusted EV.

Standard library only.  All data sources are public and keyless.

Usage:
    python weather_edge.py                   # scan everything
    python weather_edge.py --city NYC --city CHI
    python weather_edge.py --min-edge 0.05 --json out.json --html out.html
    python weather_edge.py --source openmeteo   # use Open-Meteo instead of NWS
    python weather_edge.py --refit           # re-run the backtest and rewrite params.json

Not financial advice.  See README.md.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS_PATH = os.path.join(HERE, "params.json")

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA_KALSHI = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) pm-weather-edge/1.0"}
UA_NWS = {"User-Agent": "pm-weather-edge/1.0 (contact: owner)", "Accept": "application/geo+json"}
UA_PLAIN = {"User-Agent": "pm-weather-edge/1.0 (contact: owner)"}

# ---------------------------------------------------------------------------
# City table.  key = short city code used by --city.
# station  = the station code Kalshi names in rules_primary ("CLINYC" etc.).
#            Parsed live from the rules text too; this table is the fallback
#            and the coordinate source.
# lat/lon  = the settlement station's coordinates (ASOS / climate site).
# cli      = IEM CLI-product station id used to cross-check settlement values.
# ---------------------------------------------------------------------------
CITIES = {
    "NYC":  dict(series="KXHIGHNY",    name="New York City", station="CLINYC", lat=40.779, lon=-73.969,  tz="America/New_York",    cli="KNYC"),
    "MIA":  dict(series="KXHIGHMIA",   name="Miami",         station="CLIMIA", lat=25.788, lon=-80.317,  tz="America/New_York",    cli="KMIA"),
    "CHI":  dict(series="KXHIGHCHI",   name="Chicago",       station="CLIMDW", lat=41.786, lon=-87.752,  tz="America/Chicago",     cli="KMDW"),
    "AUS":  dict(series="KXHIGHAUS",   name="Austin",        station="CLIAUS", lat=30.183, lon=-97.680,  tz="America/Chicago",     cli="KAUS"),
    "HOU":  dict(series="KXHIGHTHOU",  name="Houston",       station="CLIHOU", lat=29.638, lon=-95.282,  tz="America/Chicago",     cli="KHOU"),
    "DC":   dict(series="KXHIGHTDC",   name="Washington DC", station="CLIDCA", lat=38.848, lon=-77.034,  tz="America/New_York",    cli="KDCA"),
    "SAN":  dict(series="KXHIGHTSAN",  name="San Diego",     station="CLISAN", lat=32.734, lon=-117.183, tz="America/Los_Angeles", cli="KSAN"),
    "NOLA": dict(series="KXHIGHTNOLA", name="New Orleans",   station="CLIMSY", lat=29.993, lon=-90.251,  tz="America/Chicago",     cli="KMSY"),
    "MIN":  dict(series="KXHIGHTMIN",  name="Minneapolis",   station="CLIMSP", lat=44.883, lon=-93.229,  tz="America/Chicago",     cli="KMSP"),
    "SATX": dict(series="KXHIGHTSATX", name="San Antonio",   station="CLISAT", lat=29.544, lon=-98.484,  tz="America/Chicago",     cli="KSAT"),
    "DEN":  dict(series="KXHIGHDEN",   name="Denver",        station="CLIDEN", lat=39.847, lon=-104.656, tz="America/Denver",      cli="KDEN"),
    "LAX":  dict(series="KXHIGHLAX",   name="Los Angeles",   station="CLILAX", lat=33.938, lon=-118.389, tz="America/Los_Angeles", cli="KLAX"),
    "BOS":  dict(series="KXHIGHTBOS",  name="Boston",        station="CLIBOS", lat=42.361, lon=-71.010,  tz="America/New_York",    cli="KBOS"),
    "ATL":  dict(series="KXHIGHTATL",  name="Atlanta",       station="CLIATL", lat=33.630, lon=-84.442,  tz="America/New_York",    cli="KATL"),
    "PHL":  dict(series="KXHIGHPHIL",  name="Philadelphia",  station="CLIPHL", lat=39.873, lon=-75.227,  tz="America/New_York",    cli="KPHL"),
    "OKC":  dict(series="KXHIGHTOKC",  name="Oklahoma City", station="CLIOKC", lat=35.389, lon=-97.600,  tz="America/Chicago",     cli="KOKC"),
    "PHX":  dict(series="KXHIGHTPHX",  name="Phoenix",       station="CLIPHX", lat=33.428, lon=-112.004, tz="America/Phoenix",     cli="KPHX"),
    "LAS":  dict(series="KXHIGHTLV",   name="Las Vegas",     station="CLILAS", lat=36.072, lon=-115.163, tz="America/Los_Angeles", cli="KLAS"),
    "TTN":  dict(series="KXHIGHTTTN",  name="Trenton",       station="CLITTN", lat=40.277, lon=-74.816,  tz="America/New_York",    cli="KTTN"),
    "EWR":  dict(series="KXHIGHTEWR",  name="Newark",        station="CLIEWR", lat=40.683, lon=-74.169,  tz="America/New_York",    cli="KEWR"),
    "SFO":  dict(series="KXHIGHTSFO",  name="San Francisco", station="CLISFO", lat=37.620, lon=-122.375, tz="America/Los_Angeles", cli="KSFO"),
    "SEA":  dict(series="KXHIGHTSEA",  name="Seattle",       station="CLISEA", lat=47.445, lon=-122.314, tz="America/Los_Angeles", cli="KSEA"),
    "DFW":  dict(series="KXHIGHTDAL",  name="Dallas",        station="CLIDFW", lat=32.898, lon=-97.019,  tz="America/Chicago",     cli="KDFW"),
    "SDF":  dict(series="KXHIGHTSDF",  name="Louisville",    station="CLISDF", lat=38.181, lon=-85.739,  tz="America/New_York",    cli="KSDF"),
}
SERIES_TO_CITY = {v["series"]: k for k, v in CITIES.items()}

MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

# Default error model used for a city with no fitted parameters.
DEFAULT_PARAMS = {"bias": 0.0, "sigma1": 3.0, "sigma2": 3.6, "n": 0}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def http_json(url, headers=None, timeout=30, retries=4, sleep=0.25):
    """GET JSON with simple retry/backoff (handles Kalshi 429s)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or UA_PLAIN)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                data = json.loads(f.read().decode("utf-8"))
            if sleep:
                time.sleep(sleep)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def parse_ticker_date(ticker):
    """'KXHIGHNY-26SEP22-T70' -> datetime.date(2026, 9, 22)"""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})-", ticker)
    if not m:
        return None
    yy, mon, dd = m.groups()
    return dt.date(2000 + int(yy), MONTHS[mon], int(dd))


def market_interval(mkt):
    """
    Return (lo, hi) integer-degree inclusive interval the market pays YES on,
    using None for open ends.  Kalshi settles on a whole-degree reading.
      strike_type 'between' floor=67 cap=68 -> 67..68 inclusive
      strike_type 'greater' floor=70       -> 71..inf  (strictly greater than 70)
      strike_type 'less'    cap=63         -> -inf..62 (strictly less than 63)
    """
    st = mkt.get("strike_type")
    if st == "between":
        return (int(round(float(mkt["floor_strike"]))), int(round(float(mkt["cap_strike"]))))
    if st == "greater":
        return (int(round(float(mkt["floor_strike"]))) + 1, None)
    if st == "less":
        return (None, int(round(float(mkt["cap_strike"]))) - 1)
    # Fallback: parse the ticker suffix
    suf = mkt.get("ticker", "").split("-")[-1]
    if suf.startswith("B"):
        c = float(suf[1:])
        return (int(math.floor(c)), int(math.ceil(c)))
    if suf.startswith("T"):
        k = int(float(suf[1:]))
        sub = (mkt.get("yes_sub_title") or "").lower()
        if "below" in sub or "less" in sub:
            return (None, k - 1)
        return (k + 1, None)
    return (None, None)


def prob_interval(lo, hi, mean, sigma):
    """P(lo <= T <= hi) for integer-valued T ~ round(Normal(mean, sigma)),
    via continuity correction (lo-0.5, hi+0.5)."""
    sigma = max(sigma, 0.05)
    a = -math.inf if lo is None else (lo - 0.5 - mean) / sigma
    b = math.inf if hi is None else (hi + 0.5 - mean) / sigma
    pa = 0.0 if a == -math.inf else norm_cdf(a)
    pb = 1.0 if b == math.inf else norm_cdf(b)
    return max(0.0, min(1.0, pb - pa))


def price_market(mkt, forecast_high, params, horizon=1):
    """
    Model probability that market resolves YES given a forecast high (deg F),
    fitted params {bias, sigma1, sigma2} and horizon in days (1 = tomorrow /
    today, 2 = day after).  Horizons >2 scale sigma2 by 1.15^(h-2).
    """
    lo, hi = market_interval(mkt)
    if lo is None and hi is None:
        return None
    mean = forecast_high + params.get("bias", 0.0)
    if horizon <= 1:
        sigma = params.get("sigma1", DEFAULT_PARAMS["sigma1"])
    elif horizon == 2:
        sigma = params.get("sigma2", params.get("sigma1", DEFAULT_PARAMS["sigma1"]) * 1.2)
    else:
        sigma = params.get("sigma2", params.get("sigma1", DEFAULT_PARAMS["sigma1"]) * 1.2) * (1.15 ** (horizon - 2))
    return prob_interval(lo, hi, mean, sigma)


def kalshi_fee(price, contracts=1):
    """Kalshi taker fee: 0.07 * P * (1-P) per contract, rounded UP to the cent."""
    raw = 0.07 * price * (1.0 - price) * contracts
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def kelly_fraction(p, ask):
    """Full Kelly for a binary YES contract bought at `ask`: (p - ask) / (1 - ask)."""
    if ask >= 1.0 or ask <= 0.0:
        return 0.0
    return max(0.0, (p - ask) / (1.0 - ask))


def load_params(path=PARAMS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"cities": {}, "note": "params.json missing; using defaults"}


def city_params(params, city):
    p = dict(DEFAULT_PARAMS)
    p.update((params.get("cities") or {}).get(city, {}))
    if "sigma2" not in (params.get("cities") or {}).get(city, {}):
        p["sigma2"] = p["sigma1"] * 1.2
    return p


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------
def iso_duration_hours(s):
    """'PT13H' -> 13, 'P1D' -> 24, 'P1DT6H' -> 30; unknown -> 6."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s or "")
    if not m or not any(m.groups()):
        return 6.0
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return d * 24.0 + h + mi / 60.0


def nws_daily_highs(lat, lon, tz):
    """
    Returns {date: high_F} from the NWS gridpoint maxTemperature series, with
    the 12-hour daytime forecast periods as fallback.  Raises on total failure.
    """
    pts = http_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=UA_NWS, sleep=0)["properties"]
    out = {}
    z = ZoneInfo(tz)
    try:
        grid = http_json(pts["forecastGridData"], headers=UA_NWS, sleep=0)["properties"]
        best_len = {}
        for v in grid.get("maxTemperature", {}).get("values", []):
            if v.get("value") is None:
                continue
            start_s, _, dur_s = v["validTime"].partition("/")
            start = dt.datetime.fromisoformat(start_s.replace("Z", "+00:00"))
            hours = iso_duration_hours(dur_s)
            # maxTemperature periods normally run 12Z for 13h; the local date of
            # the period midpoint is the day the max applies to.  Keep the
            # longest period seen for each day (short leftovers are stubs).
            day = (start + dt.timedelta(hours=hours / 2.0)).astimezone(z).date()
            if hours > best_len.get(day, 0):
                best_len[day] = hours
                out[day] = v["value"] * 9.0 / 5.0 + 32.0
    except Exception:
        pass
    try:
        per = http_json(pts["forecast"], headers=UA_NWS, sleep=0)["properties"]["periods"]
        for p in per:
            if not p.get("isDaytime"):
                continue
            day = dt.datetime.fromisoformat(p["startTime"]).astimezone(z).date()
            t = float(p["temperature"])
            if p.get("temperatureUnit") == "C":
                t = t * 9.0 / 5.0 + 32.0
            out.setdefault(day, t)
    except Exception:
        pass
    if not out:
        raise RuntimeError("NWS returned no usable daily highs")
    return out


def openmeteo_daily_highs(lat, lon, tz, models="gfs_seamless,ecmwf_ifs025"):
    """{date: high_F} from the Open-Meteo forecast API (average of models)."""
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit", "timezone": tz, "forecast_days": 5, "models": models}))
    d = http_json(url, sleep=0)
    h = d["hourly"]
    keys = [k for k in h if k.startswith("temperature_2m")]
    daymax = {}
    for i, t in enumerate(h["time"]):
        day = dt.date.fromisoformat(t[:10])
        vals = [h[k][i] for k in keys if h[k][i] is not None]
        if not vals:
            continue
        v = sum(vals) / len(vals)
        daymax[day] = max(daymax.get(day, -999.0), v)
    return daymax


# ---------------------------------------------------------------------------
# Kalshi
# ---------------------------------------------------------------------------
def kalshi_markets(series, status="open", limit=200, max_pages=10):
    out, cursor = [], None
    for _ in range(max_pages):
        url = f"{KALSHI}/markets?series_ticker={series}&status={status}&limit={limit}"
        if cursor:
            url += f"&cursor={cursor}"
        d = http_json(url, headers=UA_KALSHI)
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    return out


def station_from_rules(text):
    m = re.search(r"\(([A-Z]{3,8}[0-9]*)\)", text or "")
    return m.group(1) if m else None


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def clean_label(s):
    """Console-safe bracket label: '67° to 68°' -> '67 to 68'."""
    return (s or "").replace("°", "").replace("–", "-").strip()


def scan(cities=None, source="nws", min_edge=0.0, params=None, verbose=True, include_today=False):
    params = params or load_params()
    rows, warnings, today_skipped = [], [], []
    todo = [c for c in CITIES if (not cities or c in cities)]
    for code in todo:
        c = CITIES[code]
        z = ZoneInfo(c["tz"])
        today_local = dt.datetime.now(z).date()
        try:
            mkts = kalshi_markets(c["series"], "open")
        except Exception as e:
            warnings.append(f"{code}: Kalshi markets failed ({e})")
            continue
        if not mkts:
            continue
        # settlement station check
        rules_station = station_from_rules(mkts[0].get("rules_primary"))
        if rules_station and rules_station != c["station"]:
            warnings.append(f"{code}: rules name station {rules_station}, table says {c['station']}; check coordinates")
        try:
            if source == "openmeteo":
                fc = openmeteo_daily_highs(c["lat"], c["lon"], c["tz"])
            else:
                fc = nws_daily_highs(c["lat"], c["lon"], c["tz"])
        except Exception as e:
            warnings.append(f"{code}: {source.upper()} forecast failed ({e}); trying Open-Meteo")
            try:
                fc = openmeteo_daily_highs(c["lat"], c["lon"], c["tz"])
            except Exception as e2:
                warnings.append(f"{code}: Open-Meteo also failed ({e2}); skipped")
                continue
        cp = city_params(params, code)
        skipped_today = False
        for m in mkts:
            day = parse_ticker_date(m["ticker"])
            if day is None or day not in fc:
                continue
            days_ahead = (day - today_local).days
            if days_ahead < 0:
                continue
            if days_ahead == 0 and not include_today:
                skipped_today = True
                continue
            horizon = max(1, days_ahead)
            p = price_market(m, fc[day], cp, horizon)
            if p is None:
                continue
            ask = fnum(m.get("yes_ask_dollars"), 1.0)
            bid = fnum(m.get("yes_bid_dollars"), 0.0)
            no_ask = 1.0 - bid
            edge_yes = p - ask
            edge_no = (1.0 - p) - no_ask
            side, edge, px, prob = ("YES", edge_yes, ask, p) if edge_yes >= edge_no else ("NO", edge_no, no_ask, 1.0 - p)
            fee = kalshi_fee(px)
            ev = prob * (1.0 - px) - (1.0 - prob) * px - fee   # per contract, $
            # quarter-Kelly, capped at 10% of bankroll, zero when fees eat the edge
            kq = min(0.10, kelly_fraction(prob, px) / 4.0) if ev >= 0.01 else 0.0
            row = dict(
                city=code, series=c["series"], station=rules_station or c["station"], date=day.isoformat(),
                days_ahead=days_ahead, ticker=m["ticker"], bracket=clean_label(m.get("yes_sub_title")) or m["ticker"].split("-")[-1],
                forecast_high=round(fc[day], 1), model_yes=round(p, 4),
                yes_bid=bid, yes_ask=ask, side=side, price=round(px, 2), edge=round(edge, 4),
                kelly_q=round(kq, 4), ev_per_contract=round(ev, 4),
                sigma=cp["sigma1"] if horizon <= 1 else cp["sigma2"], bias=cp["bias"], n_fit=cp.get("n", 0),
                volume=fnum(m.get("volume_fp"), 0.0),
            )
            if edge >= min_edge:
                rows.append(row)
        if skipped_today:
            today_skipped.append(code)
        if verbose:
            print(f"  {code:5s} {len(mkts):3d} open markets, forecast days: "
                  + ", ".join(f"{d.isoformat()[5:]}={fc[d]:.0f}" for d in sorted(fc)[:4]), file=sys.stderr)
    if today_skipped:
        warnings.append(f"today's markets skipped for {len(today_skipped)} cities (the running high is already partly known; "
                        "use --include-today to price them anyway)")
    rows.sort(key=lambda r: -r["edge"])
    return rows, warnings


def fmt_table(rows):
    if not rows:
        return "(no markets matched)"
    hdr = f"{'city':5s} {'date':10s} {'bracket':14s} {'fc':>5s} {'side':4s} {'model':>6s} {'price':>5s} {'edge':>6s} {'qKelly':>6s} {'EV/ct':>6s} {'ticker'}"
    lines = [hdr, "-" * len(hdr)]
    for r in rows:
        mp = r["model_yes"] if r["side"] == "YES" else 1 - r["model_yes"]
        lines.append(f"{r['city']:5s} {r['date']:10s} {r['bracket'][:14]:14s} {r['forecast_high']:5.0f} {r['side']:4s} "
                     f"{mp:6.2f} {r['price']:5.2f} {r['edge']:+6.2f} {r['kelly_q']:6.3f} {r['ev_per_contract']:+6.3f} {r['ticker']}")
    return "\n".join(lines)


def write_html(rows, warnings, path, min_edge):
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    trs = []
    for r in rows:
        mp = r["model_yes"] if r["side"] == "YES" else 1 - r["model_yes"]
        cls = "pos" if r["edge"] >= 0.08 else ""
        trs.append(f"<tr class='{cls}'><td>{esc(r['city'])}</td><td>{r['date']}</td><td>{esc(r['bracket'])}</td>"
                   f"<td>{r['forecast_high']:.0f}</td><td>{r['side']}</td><td>{mp:.2f}</td><td>{r['price']:.2f}</td>"
                   f"<td>{r['edge']:+.2f}</td><td>{r['kelly_q']:.3f}</td><td>{r['ev_per_contract']:+.3f}</td><td>{esc(r['ticker'])}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Weather Edge</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#fff;color:#111}}table{{border-collapse:collapse;font-size:14px}}
td,th{{padding:4px 8px;border-bottom:1px solid #ddd;text-align:right}}td:first-child,td:nth-child(2),td:nth-child(3),td:nth-child(5),td:last-child,th{{text-align:left}}
tr.pos{{background:#eaf7ea}}.warn{{color:#a33;font-size:13px}}</style></head><body>
<h2>Kalshi Weather Fair-Value scan</h2><p>Generated {dt.datetime.now().isoformat(timespec='minutes')} · min edge {min_edge:.2f} · {len(rows)} rows · not financial advice</p>
<table><tr><th>city</th><th>date</th><th>bracket</th><th>fc</th><th>side</th><th>model</th><th>price</th><th>edge</th><th>¼Kelly</th><th>EV/ct</th><th>ticker</th></tr>
{''.join(trs)}</table>
{'<h3>Warnings</h3><ul class=warn>' + ''.join('<li>' + esc(w) + '</li>' for w in warnings) + '</ul>' if warnings else ''}
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kalshi Weather Fair-Value Tool")
    ap.add_argument("--min-edge", type=float, default=0.0, help="only show rows with edge >= this (e.g. 0.08)")
    ap.add_argument("--city", action="append", help="city code (NYC, MIA, CHI, ...); repeatable")
    ap.add_argument("--source", choices=["nws", "openmeteo"], default="nws", help="forecast source (default nws)")
    ap.add_argument("--json", metavar="PATH", help="write rows as JSON")
    ap.add_argument("--html", metavar="PATH", help="write an HTML report")
    ap.add_argument("--refit", action="store_true", help="re-run backtest.py to refresh params.json first")
    ap.add_argument("--include-today", action="store_true", help="also price markets for today's date (default: tomorrow onwards)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.refit:
        import backtest
        backtest.main([])

    cities = [c.upper() for c in a.city] if a.city else None
    bad = [c for c in (cities or []) if c not in CITIES]
    if bad:
        print("unknown city code(s): " + ", ".join(bad) + "\nknown: " + ", ".join(CITIES), file=sys.stderr)
        return 2
    params = load_params()
    if not a.quiet:
        fitted = len(params.get("cities") or {})
        print(f"params.json: {fitted} fitted cities" + (f" (fitted {params.get('fitted_at','?')})" if fitted else " -- using defaults"), file=sys.stderr)
    rows, warnings = scan(cities, a.source, a.min_edge, params, verbose=not a.quiet, include_today=a.include_today)
    print(fmt_table(rows))
    for w in warnings:
        print("WARN " + w, file=sys.stderr)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"generated": dt.datetime.now().isoformat(), "source": a.source, "rows": rows, "warnings": warnings}, f, indent=1)
    if a.html:
        write_html(rows, warnings, a.html, a.min_edge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
