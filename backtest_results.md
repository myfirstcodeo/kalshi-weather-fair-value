# Backtest results: Kalshi daily-high markets vs forecast-error model

Generated 2026-09-23T09:07:05. Window: last 60 days (2026-07-25 to 2026-09-22). 24 cities, 1317 city-days, 7902 settled markets, 6858 of them with a two-sided quote at the day-before close.

**Ground truth** = Kalshi's own `expiration_value` (The Weather Company reading at the station named in the rules). Cross-checked against the NWS CLI product archived by IEM: 1 mismatch(es) of >0.5F across 1317 city-days with a CLI value.

**Forecast** = Open-Meteo Previous Runs API, hourly `temperature_2m_previous_day1` (the model run from one day earlier), max over the local calendar day. Candidates: GFS, ECMWF IFS 0.25, and their average. Selected by lowest pooled sigma: **blend_d1**.

**Market price** = close of the Kalshi 1440-minute candle that ended at least 12h before the market close (i.e. the last full day before the target date), yes_bid / yes_ask; mid used for Brier, ask for buying.

## 1. Forecast error by city (actual minus day-1 forecast, deg F)

| city | n days | bias | sigma | MAE | skew | ex. kurt | within 1sd | within 2sd | normal ok? |
|---|---|---|---|---|---|---|---|---|---|
| NYC | 60 | -1.074 | 2.078 | 1.861 | -0.35 | 0.14 | 0.7 | 0.983 | yes |
| MIA | 60 | 3.657 | 1.916 | 3.667 | 0.11 | -1.18 | 0.583 | 0.983 | yes |
| CHI | 60 | 0.26 | 2.407 | 1.837 | -0.74 | 1.57 | 0.733 | 0.95 | yes |
| AUS | 60 | 2.458 | 1.455 | 2.622 | -1.29 | 4.69 | 0.75 | 0.95 | no |
| HOU | 60 | -0.025 | 2.267 | 1.75 | 0.64 | 1.44 | 0.717 | 0.967 | yes |
| DC | 60 | -0.593 | 2.546 | 2.113 | -0.02 | -0.49 | 0.7 | 0.95 | yes |
| SAN | 35 | -3.354 | 2.543 | 3.669 | 0.51 | -0.18 | 0.657 | 0.971 | yes |
| NOLA | 60 | 1.159 | 2.201 | 1.926 | -0.64 | 2.02 | 0.717 | 0.967 | no |
| MIN | 60 | -0.116 | 2.976 | 2.366 | -0.38 | -0.09 | 0.617 | 0.967 | yes |
| SATX | 60 | 0.526 | 1.592 | 1.204 | -0.39 | 2.06 | 0.8 | 0.933 | no |
| DEN | 60 | 0.624 | 1.946 | 1.641 | -0.52 | 0.32 | 0.733 | 0.917 | yes |
| LAX | 60 | -3.961 | 3.064 | 4.346 | 0.19 | -0.15 | 0.717 | 0.917 | yes |
| BOS | 60 | 0.309 | 2.446 | 1.901 | -0.71 | 0.79 | 0.683 | 0.983 | yes |
| ATL | 60 | 0.326 | 2.128 | 1.647 | 0.4 | -0.5 | 0.7 | 0.967 | yes |
| PHL | 60 | 1.901 | 1.884 | 2.224 | -0.08 | -0.56 | 0.6 | 0.95 | yes |
| OKC | 60 | 1.263 | 2.603 | 2.26 | -0.39 | 2.47 | 0.85 | 0.933 | no |
| PHX | 60 | 0.972 | 1.832 | 1.608 | 0.33 | 0.46 | 0.717 | 0.933 | yes |
| LAS | 60 | 0.616 | 2.232 | 1.587 | -1.4 | 6.02 | 0.85 | 0.933 | no |
| TTN | 28 | 0.546 | 1.651 | 1.425 | -0.72 | -0.18 | 0.679 | 0.964 | yes |
| EWR | 28 | 0.873 | 2.236 | 1.87 | 0.17 | -0.53 | 0.643 | 0.929 | yes |
| SFO | 60 | -1.095 | 3.434 | 2.527 | -1.42 | 2.8 | 0.767 | 0.967 | no |
| SEA | 60 | 0.809 | 2.151 | 1.912 | -0.76 | 0.76 | 0.8 | 0.95 | yes |
| DFW | 60 | 0.45 | 1.926 | 1.527 | -1.49 | 4.11 | 0.733 | 0.967 | no |
| SDF | 26 | -0.285 | 2.465 | 1.573 | -0.76 | 3.81 | 0.846 | 0.923 | no |
| **pooled** | 1317 | 0.321 | 2.755 | 2.136 | -0.72 | 1.57 | 0.733 | 0.948 | yes |

`normal ok?` = |skew| < 1, |excess kurtosis| < 2, and 55-82% of errors inside one sigma (a normal gives 68%). Where it says no, tails are fatter than normal and the model will under-price far-out brackets.

Pooled sigma by forecast candidate: gfs_d1 = 2.819 (bias 0.421), ecm_d1 = 3.917 (bias 0.221), blend_d1 = 2.755 (bias 0.321), blend_d2 = 3.329 (bias -0.803).

## 2. In-sample (parameters fitted on the same days)

*in-sample (fit on all days)*  

Markets priced: 7902; with a two-sided market quote: 6858.

|  | Brier (lower is better) |
|---|---|
| Model (quoted markets) | 0.1345 |
| Market mid (quoted markets) | 0.1184 |
| Base rate (constant) | 0.1533 |
| Model (all markets incl. unquoted) | 0.1187 |

**The market beats the model** on Brier score by 0.0161.

Calibration, model vs market (10% bins of predicted probability):

| bin | model n | model mean p | observed | market n | market mean p | observed |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 2384 | 0.039 | 0.047 | 2895 | 0.04 | 0.029 |
| 0.1-0.2 | 1393 | 0.149 | 0.136 | 1039 | 0.145 | 0.113 |
| 0.2-0.3 | 1563 | 0.25 | 0.26 | 867 | 0.245 | 0.23 |
| 0.3-0.4 | 1173 | 0.344 | 0.362 | 732 | 0.348 | 0.339 |
| 0.4-0.5 | 227 | 0.443 | 0.463 | 818 | 0.449 | 0.401 |
| 0.5-0.6 | 59 | 0.542 | 0.458 | 335 | 0.544 | 0.588 |
| 0.6-0.7 | 31 | 0.649 | 0.419 | 133 | 0.636 | 0.714 |
| 0.7-0.8 | 9 | 0.735 | 0.333 | 32 | 0.725 | 0.688 |
| 0.8-0.9 | 14 | 0.856 | 0.786 | 7 | 0.83 | 1.0 |
| 0.9-1.0 | 5 | 0.928 | 1.0 | 0 |  |  |

Strategy: buy YES when model probability >= market ask + 0.08, $10 stake per trade (floor(stake/ask) contracts), Kalshi fee 0.07 x P x (1-P) per contract rounded up to the cent.

| strategy | trades | wins | staked $ | fees $ | P&L $ | ROI |
|---|---|---|---|---|---|---|
| Buy YES (as specified) | 1299 | 126 | 12924.81 | 809.07 | -3708.88 | -0.287 |
| Buy NO (mirror: model NO prob >= NO ask + 0.08) | 1520 | 862 | 14751.25 | 437.12 | -1118.37 | -0.0758 |

## 3. Out-of-sample (fit on first half of the window, test on the second half)

*out-of-sample (fit before 2026-08-24, test from 2026-08-24)*  

Markets priced: 3780; with a two-sided market quote: 3285.

|  | Brier (lower is better) |
|---|---|
| Model (quoted markets) | 0.1466 |
| Market mid (quoted markets) | 0.1195 |
| Base rate (constant) | 0.1541 |
| Model (all markets incl. unquoted) | 0.1285 |

**The market beats the model** on Brier score by 0.0271.

Calibration, model vs market (10% bins of predicted probability):

| bin | model n | model mean p | observed | market n | market mean p | observed |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 1240 | 0.034 | 0.079 | 1407 | 0.042 | 0.026 |
| 0.1-0.2 | 614 | 0.147 | 0.179 | 498 | 0.143 | 0.131 |
| 0.2-0.3 | 681 | 0.249 | 0.266 | 411 | 0.244 | 0.238 |
| 0.3-0.4 | 491 | 0.345 | 0.263 | 347 | 0.348 | 0.34 |
| 0.4-0.5 | 142 | 0.444 | 0.423 | 384 | 0.447 | 0.427 |
| 0.5-0.6 | 53 | 0.535 | 0.358 | 162 | 0.545 | 0.556 |
| 0.6-0.7 | 24 | 0.641 | 0.25 | 63 | 0.634 | 0.683 |
| 0.7-0.8 | 18 | 0.734 | 0.556 | 10 | 0.736 | 0.7 |
| 0.8-0.9 | 15 | 0.84 | 0.533 | 3 | 0.847 | 1.0 |
| 0.9-1.0 | 7 | 0.945 | 0.571 | 0 |  |  |

Strategy: buy YES when model probability >= market ask + 0.08, $10 stake per trade (floor(stake/ask) contracts), Kalshi fee 0.07 x P x (1-P) per contract rounded up to the cent.

| strategy | trades | wins | staked $ | fees $ | P&L $ | ROI |
|---|---|---|---|---|---|---|
| Buy YES (as specified) | 689 | 74 | 6850.81 | 420.8 | -2583.61 | -0.3771 |
| Buy NO (mirror: model NO prob >= NO ask + 0.08) | 787 | 454 | 7630.54 | 215.34 | -550.88 | -0.0722 |

## 4. Out-of-sample with one pooled bias/sigma for every city

*out-of-sample, pooled params (test from 2026-08-24)*  

Markets priced: 4272; with a two-sided market quote: 3656.

|  | Brier (lower is better) |
|---|---|
| Model (quoted markets) | 0.15 |
| Market mid (quoted markets) | 0.1224 |
| Base rate (constant) | 0.1533 |
| Model (all markets incl. unquoted) | 0.1328 |

**The market beats the model** on Brier score by 0.0276.

Calibration, model vs market (10% bins of predicted probability):

| bin | model n | model mean p | observed | market n | market mean p | observed |
|---|---|---|---|---|---|---|
| 0.0-0.1 | 1051 | 0.046 | 0.08 | 1485 | 0.042 | 0.025 |
| 0.1-0.2 | 957 | 0.152 | 0.171 | 551 | 0.145 | 0.123 |
| 0.2-0.3 | 1420 | 0.249 | 0.274 | 464 | 0.243 | 0.235 |
| 0.3-0.4 | 88 | 0.347 | 0.136 | 375 | 0.348 | 0.339 |
| 0.4-0.5 | 45 | 0.447 | 0.133 | 513 | 0.449 | 0.372 |
| 0.5-0.6 | 42 | 0.55 | 0.19 | 177 | 0.543 | 0.548 |
| 0.6-0.7 | 23 | 0.66 | 0.478 | 72 | 0.633 | 0.681 |
| 0.7-0.8 | 7 | 0.75 | 0.286 | 16 | 0.728 | 0.625 |
| 0.8-0.9 | 12 | 0.835 | 0.583 | 3 | 0.847 | 1.0 |
| 0.9-1.0 | 11 | 0.939 | 0.727 | 0 |  |  |

Strategy: buy YES when model probability >= market ask + 0.08, $10 stake per trade (floor(stake/ask) contracts), Kalshi fee 0.07 x P x (1-P) per contract rounded up to the cent.

| strategy | trades | wins | staked $ | fees $ | P&L $ | ROI |
|---|---|---|---|---|---|---|
| Buy YES (as specified) | 828 | 59 | 8245.53 | 526.65 | -4141.18 | -0.5022 |
| Buy NO (mirror: model NO prob >= NO ask + 0.08) | 945 | 528 | 9168.24 | 267.74 | -758.98 | -0.0828 |

## 5. Sample of out-of-sample YES trades

| date | city | ticker | model | ask | n | fee | P&L |
|---|---|---|---|---|---|---|---|
| 2026-08-24 | NYC | KXHIGHNY-26AUG24-T78 | 0.52 | 0.06 | 166 | 0.66 | -10.62 |
| 2026-08-25 | NYC | KXHIGHNY-26AUG25-T79 | 0.881 | 0.57 | 17 | 0.3 | 7.01 |
| 2026-08-26 | NYC | KXHIGHNY-26AUG26-T80 | 0.378 | 0.08 | 125 | 0.65 | -10.65 |
| 2026-08-27 | NYC | KXHIGHNY-26AUG27-T80 | 0.466 | 0.36 | 27 | 0.44 | 16.84 |
| 2026-08-28 | NYC | KXHIGHNY-26AUG28-T80 | 0.369 | 0.12 | 83 | 0.62 | -10.58 |
| 2026-08-29 | NYC | KXHIGHNY-26AUG29-T79 | 0.89 | 0.52 | 19 | 0.34 | 8.78 |
| 2026-08-31 | NYC | KXHIGHNY-26AUG31-B80.5 | 0.277 | 0.06 | 166 | 0.66 | -10.62 |
| 2026-09-03 | NYC | KXHIGHNY-26SEP03-T83 | 0.6 | 0.22 | 45 | 0.55 | -10.45 |
| 2026-09-04 | NYC | KXHIGHNY-26SEP04-T82 | 0.172 | 0.03 | 333 | 0.68 | -10.67 |
| 2026-09-05 | NYC | KXHIGHNY-26SEP05-T79 | 0.677 | 0.26 | 38 | 0.52 | -10.4 |
| 2026-09-06 | NYC | KXHIGHNY-26SEP06-T73 | 0.272 | 0.07 | 142 | 0.65 | -10.59 |
| 2026-09-07 | NYC | KXHIGHNY-26SEP07-T77 | 0.303 | 0.03 | 333 | 0.68 | -10.67 |
| 2026-09-08 | NYC | KXHIGHNY-26SEP08-T80 | 0.28 | 0.08 | 125 | 0.65 | -10.65 |
| 2026-09-09 | NYC | KXHIGHNY-26SEP09-B88.5 | 0.104 | 0.02 | 500 | 0.69 | -10.69 |
| 2026-09-09 | NYC | KXHIGHNY-26SEP09-B86.5 | 0.277 | 0.14 | 71 | 0.6 | -10.54 |
| 2026-09-10 | NYC | KXHIGHNY-26SEP10-B89.5 | 0.219 | 0.05 | 200 | 0.67 | -10.67 |
| 2026-09-11 | NYC | KXHIGHNY-26SEP11-T79 | 0.311 | 0.23 | 43 | 0.54 | -10.43 |
| 2026-09-14 | NYC | KXHIGHNY-26SEP14-T74 | 0.872 | 0.32 | 31 | 0.48 | -10.4 |
| 2026-09-15 | NYC | KXHIGHNY-26SEP15-T70 | 0.386 | 0.05 | 200 | 0.67 | -10.67 |
| 2026-09-15 | NYC | KXHIGHNY-26SEP15-B70.5 | 0.345 | 0.26 | 38 | 0.52 | -10.4 |
| 2026-09-16 | NYC | KXHIGHNY-26SEP16-B75.5 | 0.248 | 0.1 | 100 | 0.63 | -10.63 |
| 2026-09-17 | NYC | KXHIGHNY-26SEP17-B84.5 | 0.209 | 0.06 | 166 | 0.66 | -10.62 |
| 2026-09-18 | NYC | KXHIGHNY-26SEP18-T80 | 0.336 | 0.11 | 90 | 0.62 | -10.52 |
| 2026-09-19 | NYC | KXHIGHNY-26SEP19-T69 | 0.167 | 0.06 | 166 | 0.66 | -10.62 |
| 2026-09-19 | NYC | KXHIGHNY-26SEP19-B73.5 | 0.159 | 0.04 | 250 | 0.68 | -10.68 |

## 6. Kalshi vs IEM CLI mismatches

| city | date | Kalshi | IEM CLI |
|---|---|---|---|
| MIA | 2026-08-29 | 90.0 | 85.0 |

## How to read this honestly

- The in-sample numbers use parameters fitted on the very days being scored; they are the optimistic bound.
- The out-of-sample numbers are the fair test. A day-before Kalshi close already incorporates the same public forecasts, so the market is a hard benchmark; the base-rate row shows what a no-information forecaster scores.
- The market Brier is scored on the quote mid; you cannot trade at mid. The P&L rows pay the ask plus fees.
- 8-cent-edge trades are concentrated in low-priced brackets where a normal tail is most wrong; treat the P&L as a small sample.
