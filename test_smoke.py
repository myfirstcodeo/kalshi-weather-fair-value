#!/usr/bin/env python3
"""Offline smoke tests for the pricing function.  No network.  Run: python test_smoke.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_edge as we  # noqa: E402


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_bracket_ladder_sums_to_one():
    # A Kalshi-style ladder for a forecast of 68F: <63, 63-64, 65-66, 67-68, 69-70, >70
    ladder = [
        dict(ticker="X-26SEP22-T63", strike_type="less", cap_strike=63),
        dict(ticker="X-26SEP22-B63.5", strike_type="between", floor_strike=63, cap_strike=64),
        dict(ticker="X-26SEP22-B65.5", strike_type="between", floor_strike=65, cap_strike=66),
        dict(ticker="X-26SEP22-B67.5", strike_type="between", floor_strike=67, cap_strike=68),
        dict(ticker="X-26SEP22-B69.5", strike_type="between", floor_strike=69, cap_strike=70),
        dict(ticker="X-26SEP22-T70", strike_type="greater", floor_strike=70),
    ]
    params = dict(bias=0.0, sigma1=2.0, sigma2=2.5)
    probs = [we.price_market(m, 68.0, params, horizon=1) for m in ladder]
    total = sum(probs)
    assert approx(total, 1.0, 1e-9), f"ladder probabilities sum to {total}, expected 1"
    assert probs[3] == max(probs), "the bracket containing the forecast should be the most likely"


def test_hand_computed_value():
    # forecast 68, bias 0, sigma 2: P(67 <= T <= 68) = Phi((68.5-68)/2) - Phi((66.5-68)/2)
    #                                               = Phi(0.25) - Phi(-0.75)
    m = dict(ticker="X-26SEP22-B67.5", strike_type="between", floor_strike=67, cap_strike=68)
    p = we.price_market(m, 68.0, dict(bias=0.0, sigma1=2.0), horizon=1)
    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    expected = phi(0.25) - phi(-0.75)      # = 0.59871 - 0.22663 = 0.37208
    assert approx(p, expected, 1e-9), f"{p} != {expected}"
    assert approx(p, 0.37208, 5e-5)

    # threshold ">70" means 71 or above: P(T >= 71) = 1 - Phi((70.5-68)/2) = 1 - Phi(1.25)
    t = dict(ticker="X-26SEP22-T70", strike_type="greater", floor_strike=70)
    p2 = we.price_market(t, 68.0, dict(bias=0.0, sigma1=2.0), horizon=1)
    assert approx(p2, 1 - phi(1.25), 1e-9)
    assert approx(p2, 0.10565, 5e-5)

    # "<63" means 62 or below: P(T <= 62) = Phi((62.5-68)/2) = Phi(-2.75)
    l = dict(ticker="X-26SEP22-T63", strike_type="less", cap_strike=63)
    p3 = we.price_market(l, 68.0, dict(bias=0.0, sigma1=2.0), horizon=1)
    assert approx(p3, phi(-2.75), 1e-9)


def test_bias_shifts_distribution():
    m = dict(ticker="X-26SEP22-B69.5", strike_type="between", floor_strike=69, cap_strike=70)
    p_nobias = we.price_market(m, 68.0, dict(bias=0.0, sigma1=2.0), 1)
    p_bias = we.price_market(m, 68.0, dict(bias=1.5, sigma1=2.0), 1)
    assert p_bias > p_nobias


def test_horizon_widens():
    m = dict(ticker="X-26SEP22-B67.5", strike_type="between", floor_strike=67, cap_strike=68)
    p1 = we.price_market(m, 68.0, dict(bias=0.0, sigma1=2.0, sigma2=3.0), 1)
    p2 = we.price_market(m, 68.0, dict(bias=0.0, sigma1=2.0, sigma2=3.0), 2)
    p3 = we.price_market(m, 68.0, dict(bias=0.0, sigma1=2.0, sigma2=3.0), 3)
    assert p1 > p2 > p3


def test_ticker_fallback_and_date():
    # no strike_type fields: parse from the ticker suffix / sub title
    b = dict(ticker="KXHIGHNY-26SEP22-B67.5")
    assert we.market_interval(b) == (67, 68)
    t = dict(ticker="KXHIGHNY-26SEP22-T70", yes_sub_title="71° or above")
    assert we.market_interval(t) == (71, None)
    lo = dict(ticker="KXHIGHNY-26SEP22-T63", yes_sub_title="62° or below")
    assert we.market_interval(lo) == (None, 62)
    assert we.parse_ticker_date("KXHIGHNY-26SEP22-T70").isoformat() == "2026-09-22"


def test_fee_and_kelly():
    assert we.kalshi_fee(0.50) == 0.02          # 0.07*0.25 = 0.0175 -> 0.02
    assert we.kalshi_fee(0.10) == 0.01          # 0.0063 -> 0.01
    assert we.kalshi_fee(0.50, 10) == 0.18      # 0.175 -> 0.18
    assert approx(we.kelly_fraction(0.60, 0.50), 0.2)
    assert we.kelly_fraction(0.40, 0.50) == 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
