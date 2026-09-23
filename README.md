# Kalshi Weather Fair-Value Tool

A small command-line tool that prices every open Kalshi daily high-temperature
market (NYC, Chicago, Miami, Austin, Houston, DC, and 18 more US cities) from
the National Weather Service forecast plus a per-city forecast-error model, then
shows you where the Kalshi price disagrees with the forecast and by how much.

It runs on your own machine against public, keyless APIs. No account, no API
key, no data feed from us. Python 3.9+ and nothing else to install.

```
python weather_edge.py --min-edge 0.08
```

```
city  date       bracket           fc side  model price   edge qKelly  EV/ct ticker
-----------------------------------------------------------------------------------
DEN   2026-09-24 72 or above       66 NO     0.99  0.51  +0.48  0.100 +0.464 KXHIGHDEN-26SEP24-T71
ATL   2026-09-24 73 or below       75 NO     0.80  0.33  +0.47  0.100 +0.455 KXHIGHTATL-26SEP24-T74
LAX   2026-09-24 77 or below       81 YES    0.56  0.11  +0.45  0.100 +0.440 KXHIGHLAX-26SEP24-T78
AUS   2026-09-24 100 to 101        98 YES    0.51  0.12  +0.39  0.100 +0.378 KXHIGHAUS-26SEP24-B100.5
```
(real output from 2026-09-23; a 24-city scan takes about a minute)

Read the backtest section before you trade anything. **The model does not beat
the day-before Kalshi price on average.** What it is good for is spotting
individual brackets that are mispriced relative to the forecast, and giving you
a disciplined size for them.

## What is in the box

| file | what it does |
|---|---|
| `weather_edge.py` | the scanner. Standard library only. |
| `params.json` | fitted per-city bias and sigma of the day-1 forecast error, produced by `backtest.py` |
| `backtest.py` | rebuilds `params.json` from the last 60 days of settled markets and reruns the full evaluation (`python weather_edge.py --refit` calls it) |
| `backtest_results.md` / `.json` | the evaluation this README quotes |
| `test_smoke.py` | offline checks that the pricing math is right (`python test_smoke.py`) |

## How it works

1. **Markets.** For each city series (`KXHIGHNY`, `KXHIGHCHI`, ...) it pulls the
   open markets from Kalshi's public API. Each day has a ladder of brackets
   ("67 to 68") plus two tails ("64 or below", "71 or above").
2. **Forecast.** It reads the settlement station's coordinates (Central Park for
   NYC, Midway for Chicago, and so on) and asks the NWS API for the forecast
   daily maximum at that point. `--source openmeteo` uses Open-Meteo's GFS +
   ECMWF blend instead.
3. **Error model.** A forecast is not the answer; it is the centre of a
   distribution. `backtest.py` measured, for each city, how far the actual
   settlement reading landed from the day-1 forecast over the last 60 days:
   a mean bias and a standard deviation. The tool assumes the high is normally
   distributed around forecast + bias with that sigma (wider for two days out).
4. **Pricing.** Each bracket's probability is the mass of that distribution
   inside the bracket, with a half-degree continuity correction because
   Kalshi settles on a whole-degree reading.
5. **Edge.** Compares the model probability to the Kalshi yes-ask (or the
   no-ask for the NO side) and prints the better side, the edge, a
   quarter-Kelly fraction (capped at 10% of bankroll) and the fee-adjusted
   expected value per contract using Kalshi's fee of 0.07 x P x (1 - P) per
   contract rounded up to the cent.

By default the tool prices **tomorrow onwards**. Today's markets are skipped
because by mid-morning the running high is already public and the market knows
it; a static forecast cannot compete. `--include-today` prices them anyway.

## The settlement caveat, in plain words

Kalshi settles these markets on **The Weather Company's reading at the station
named in the rules** (for NYC: "New York City (CLINYC)", the Central Park
climate station). The tool parses that station code from every market's rules
text and warns if it differs from its table.

Two things follow:

* The **forecast source is the NWS**, not The Weather Company. The two can
  disagree systematically. The backtest measures the actual settlement value
  against a public model forecast for the station point, so the bias and sigma
  in `params.json` already include the "forecast point vs station reading"
  mismatch for that city. It does not measure NWS specifically: the backtest
  uses Open-Meteo's archived GFS + ECMWF runs because the NWS API keeps no
  forecast history. Expect the live NWS forecast to be a little better than
  the archived model runs (it is human-edited), but do not assume it.
* **Ground truth in the backtest is Kalshi's own settlement value**
  (`expiration_value` on every settled market). It was cross-checked against
  the NWS daily climate report (CLI product) archived by Iowa Environmental
  Mesonet; see the mismatch count below. Note that IEM's plain ASOS daily
  summary (`daily.py`) runs about 1F low against both because METAR rounds to
  whole degrees Celsius; do not use it as truth.

## Backtest summary (real numbers)

Run on 2026-09-23 over the last 60 days (2026-07-25 to 2026-09-22), 24 US
cities, 1,317 city-days, 7,902 settled markets, 6,858 of which had a two-sided
Kalshi quote at the close of the day before. Full tables in
`backtest_results.md`.

**Ground truth check.** Kalshi's settlement value agreed with the NWS CLI
report on 1,316 of 1,317 city-days (the one exception: Miami 2026-08-29,
Kalshi 90 vs CLI 85).

**Forecast error, day-1 (actual minus forecast, deg F).** Pooled across cities:
bias +0.3, sigma 2.76, MAE 2.1. The GFS + ECMWF average had the lowest sigma
(GFS alone 2.82, ECMWF alone 3.92) and is what the parameters are fitted on.
Per-city sigma ranges from 1.5 (Austin) to 3.4 (San Francisco). Bias is large
and stable in a few cities and worth knowing on its own: Miami +3.7, Austin
+2.5, Philadelphia +1.9 (station runs hotter than the forecast point);
Los Angeles -4.0, San Diego -3.4, NYC -1.1 (station runs cooler). A normal
fit is reasonable in 16 of 24 cities; Austin, Las Vegas, Dallas, San Francisco,
Louisville, Oklahoma City, San Antonio and New Orleans have fatter tails than
normal.

**Model vs market, Brier score (lower is better; 0.25 is a coin flip).**

| | in-sample | out-of-sample (fit on first 30 days, test on last 30) |
|---|---|---|
| Model | 0.1345 | 0.1466 |
| Kalshi market mid, day-before close | 0.1184 | 0.1195 |
| Constant base rate | 0.1533 | 0.1541 |

**The market beats the model.** Out of sample, by 0.027 Brier. The model is a
clear improvement over knowing nothing (base rate), but the day-before Kalshi
price is better still, in every city and in every probability bin.

**Calibration (out-of-sample, 10% bins).** Both are reasonably calibrated
below 30%. Where they disagree the market is right more often: when the model
said 50-70% and the market disagreed by 8+ cents, the event happened only
25-36% of the time. The market's 0-10% bin resolved YES 2.6% of the time; the
model's 0-10% bin resolved YES 7.9% of the time, which is the fat-tail problem.

**Strategy P&L (out-of-sample, $10 flat stakes, fees included).**

| rule | trades | wins | staked | fees | P&L | ROI |
|---|---|---|---|---|---|---|
| Buy YES when model >= ask + 8c (as specified) | 689 | 74 | $6,851 | $421 | **-$2,584** | -38% |
| Buy NO when model NO >= NO ask + 8c | 787 | 454 | $7,631 | $215 | **-$551** | -7% |

Every price band loses. The YES rule is worst in cheap tail brackets (ask
under 10 cents: 341 trades, -$1,555), exactly where a normal distribution is
most wrong. The NO rule loses roughly the fee plus spread, which is what you
would expect if the market is fair and the model adds nothing.

**What this means for you.** Do not run this as a mechanical strategy; it
loses. Use it as a fair-value reference: the bias table tells you which
stations run hot or cold against the forecast, the sigma tells you how wide a
ladder should be, and the edge column tells you when a Kalshi price has
drifted far from the forecast so you can look at why (a front timing change, a
marine layer, an overnight model update) before anyone else does.

## Honest limits

* **The market is a strong benchmark.** By the night before, the Kalshi price
  already reflects the same public forecasts plus whatever traders know. On
  Brier score the market beats this model out of sample. The value of the tool
  is the *disagreement list*, not blanket trading of every edge.
* **Normal tails are thin.** Errors of 5F+ happen more often than a normal
  distribution says in some cities (see the "normal ok?" column in
  `backtest_results.md`). Far-out tail brackets at 1-3 cents are systematically
  the model's weakest spot; the buy-YES strategy loses money there. Prefer the
  brackets near the centre of the ladder, and the NO side of over-priced
  brackets.
* **Sixty days is a small sample** and all summer. Sigma will be larger in
  spring and autumn frontal seasons. Re-run `python backtest.py` monthly.
* **Prices move.** The tool prints the ask at scan time; fills at that price
  are not guaranteed, and liquidity in the tails is thin.
* **Rate limits.** Kalshi returns 429 if you hammer it; the tool retries with
  backoff. A full 24-city scan takes about a minute.
* **Coordinates.** Station coordinates are hard-coded from public station
  metadata. If Kalshi changes a series' station, the tool warns; fix the table
  in `CITIES` at the top of `weather_edge.py`.

## Usage

```
python weather_edge.py                          # scan all cities, tomorrow onwards
python weather_edge.py --min-edge 0.08          # only rows with 8+ cents of edge
python weather_edge.py --city NYC --city CHI    # subset
python weather_edge.py --json scan.json --html scan.html
python weather_edge.py --source openmeteo       # alternative forecast source
python weather_edge.py --include-today          # also price today's ladder
python weather_edge.py --refit                  # rebuild params.json (about 15 minutes, cached)
python test_smoke.py                            # offline math checks
```

Columns: `fc` forecast high, `model` model probability of the printed side,
`price` what you would pay for that side, `edge` model minus price, `qKelly`
quarter-Kelly fraction of bankroll, `EV/ct` expected profit per $1 contract
after fees.

## Not financial advice

This is a statistics tool, not a recommendation. Weather markets can and do
settle against the forecast. Only stake what you can lose. Nothing here is
investment advice and the author is not a licensed advisor.


## Free, and why

This tool is free (MIT license) because its own backtest says the Kalshi market prices these brackets better than a forecast-plus-error model does. What it is good for is the per-station bias table, a disciplined fair-value reference, and a starting point for your own model. If you want the cross-venue tooling that does pay for itself, the paid Kalshi vs Polymarket divergence scanner and the trader toolkit are at https://instaverb.gumroad.com (bundle link with $10 off: https://instaverb.gumroad.com/l/pm-toolkit/LAUNCH49).

Not financial advice. Read the market rules before trading anything.
