"""판정의 계산부 — 표본외 분할 · 손익분기 비용 · 일별 흐름 · 다중 비교 (분봉 백테스트 설계 §8 · W4d d2).

체결 줄은 손으로 만든다: 날마다 한 번, 1,000원에 10주 사서 (1,000 + 손익/10)원에 판다. ETF(매도세 0) · 수수료율 0 으로 두어
비용 뒤 손익이 비용 전과 같다 — 그래야 여기서 보는 것이 비용 계산(매매일지 시험이 건다)이 아니라 ★나누고 세는 일★이 된다.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine.intraday import validate as v
from src.engine.trade_journal import analyze

DATES = [f"2026-03-{d:02d}" for d in range(2, 12)]                 # 열흘
PNL = [100, -50, 200, -100, 300, 0, -200, 400, -150, 250]          # 날마다의 손익(원) — 합 750


def day_fills(date: str, pnl: float, instrument="etf") -> list[dict]:
    base = {"symbol": "069500", "quantity": 10, "market": "KOSPI", "instrument": instrument, "name": None}
    return [{**base, "executed_at": f"{date} 09:01:00", "side": "buy", "price": 1_000.0},
            {**base, "executed_at": f"{date} 09:05:00", "side": "sell", "price": 1_000.0 + pnl / 10}]


FILLS = [f for d, p in zip(DATES, PNL) for f in day_fills(d, p)]


# ── 표본내 / 표본외 ───────────────────────────────────────────────────────────────────
def test_the_split_is_chronological_seventy_thirty_and_never_shuffled():
    out = v.split_dates(reversed(DATES))                           # 순서를 뒤집어 줘도 시간순으로 가른다
    assert out["in_sample"] == DATES[:7] and out["out_of_sample"] == DATES[7:] and out["reason"] is None


@pytest.mark.parametrize("n, sizes", [(2, (1, 1)), (3, (2, 1)), (4, (2, 2)), (5, (3, 2)), (10, (7, 3))])
def test_both_sides_of_the_split_always_have_a_day(n, sizes):
    out = v.split_dates(DATES[:n])
    assert (len(out["in_sample"]), len(out["out_of_sample"])) == sizes


def test_one_day_cannot_be_split():
    out = v.split_dates(DATES[:1])
    assert out["in_sample"] == [] and out["out_of_sample"] == [] and out["reason"] == "too_few_days"
    assert v.REASONS["too_few_days"].endswith("니다.")


def test_out_of_sample_reads_the_same_fills_on_the_later_days_only():
    out = v.out_of_sample(FILLS, DATES, commission_bp=0)
    assert out["in_sample"]["trades"] == 7 and out["out_of_sample"]["trades"] == 3
    assert out["in_sample"]["gross_total"] == sum(PNL[:7]) == 250
    assert out["out_of_sample"]["gross_total"] == sum(PNL[7:]) == 500
    assert out["out_of_sample"]["net_total"] == 500 and out["out_of_sample"]["net_expectancy"] == pytest.approx(500 / 3)
    assert out["split"] == {"in_sample_days": 7, "out_of_sample_days": 3, "in_sample_from": DATES[0], "in_sample_to": DATES[6],
                            "out_of_sample_from": DATES[7], "out_of_sample_to": DATES[9], "fraction": 0.7}


def test_without_a_commission_rate_the_net_side_is_unknown_not_zero():
    out = v.out_of_sample(FILLS, DATES, commission_bp=None)
    assert out["out_of_sample"]["gross_total"] == 500
    assert out["out_of_sample"]["net_total"] is None and out["out_of_sample"]["net_expectancy"] is None


def test_too_few_days_gives_no_split_and_says_why():
    out = v.out_of_sample(day_fills(DATES[0], 100), DATES[:1], commission_bp=0)
    assert out["in_sample"] is None and out["out_of_sample"] is None and out["reason"] == "too_few_days"


def test_days_without_trades_still_count_as_days():
    quiet = [d for d in DATES]                                    # 열흘 가운데 거래는 이틀뿐
    out = v.out_of_sample(day_fills(DATES[0], 100) + day_fills(DATES[9], 50), quiet, commission_bp=0)
    assert out["split"]["in_sample_days"] == 7 and out["in_sample"]["trades"] == 1 and out["out_of_sample"]["trades"] == 1


# ── 일별 흐름 ─────────────────────────────────────────────────────────────────────────
def test_the_daily_series_has_every_day_and_zero_on_days_without_trades():
    journal = analyze(day_fills(DATES[0], 100) + day_fills(DATES[2], -40), {"commission_bp": 0})
    out = v.daily_values(journal, DATES[:4])
    assert out == {"basis": "net", "values": [100.0, 0.0, -40.0, 0.0]}


def test_the_daily_series_says_when_it_is_before_costs():
    journal = analyze(day_fills(DATES[0], 100), {"commission_bp": None})
    assert v.daily_values(journal, DATES[:2]) == {"basis": "gross", "values": [100.0, 0.0]}


# ── 손익분기 비용 ─────────────────────────────────────────────────────────────────────
def test_breakeven_cost_is_gross_profit_over_turnover_in_bp_per_side():
    # 하루: 매수 10,000 + 매도 10,100 = 대금 20,100 · 손익 +100 → 100 ÷ 20,100 × 10,000 = 49.75bp
    journal = analyze(day_fills(DATES[0], 100), {"commission_bp": 0})
    out = v.breakeven_cost(journal)
    assert out["bp"] == pytest.approx(100 / 20_100 * 10_000) and out["reason"] is None
    assert out["turnover"] == 20_100 and out["spent_bp"] == pytest.approx(0.0)


def test_a_rule_that_loses_before_costs_has_no_breakeven_cost():
    out = v.breakeven_cost(analyze(day_fills(DATES[0], -100), {"commission_bp": 0}))
    assert out["bp"] is None and out["reason"] == "loses_before_costs"


def test_no_trades_means_no_breakeven_cost():
    out = v.breakeven_cost(analyze([], {"commission_bp": 0}))
    assert out["bp"] is None and out["reason"] == "no_trades"


def test_the_spent_cost_is_unknown_when_the_costs_are():
    out = v.breakeven_cost(analyze(day_fills(DATES[0], 100), {"commission_bp": None}))
    assert out["bp"] == pytest.approx(100 / 20_100 * 10_000) and out["spent_bp"] is None


# ── 다중 비교 ─────────────────────────────────────────────────────────────────────────
def series(seed: int, drift: float, n: int = 80) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(rng.normal(drift, 1_000.0, n))


def test_a_short_series_gives_no_probability_and_says_why():
    out = v.multiplicity(series(1, 300.0, n=40), [])
    assert out["psr0"] is None and out["dsr"] is None and out["days"] == 40 and out["reason"]


def test_a_single_trial_has_a_probability_but_nothing_to_correct_for():
    out = v.multiplicity(series(1, 300.0), [])
    assert out["n"] == 1 and 0 < out["psr0"] <= 1 and out["dsr"] is None
    assert out["value"] == out["psr0"] and out["corrected"] is False


def test_more_trials_lower_the_corrected_probability():
    current = series(1, 300.0)
    family = [series(s, 0.0) for s in (2, 3, 4, 5)]
    out = v.multiplicity(current, family)
    assert out["n"] == 5 and out["corrected"] is True
    assert out["dsr"] is not None and out["dsr"] < out["psr0"]         # 시도가 늘면 운으로 기대되는 최대가 올라간다
    assert out["value"] == out["dsr"]
    fewer = v.multiplicity(current, family[:1])
    assert fewer["n"] == 2 and fewer["dsr"] is not None


def test_a_flat_series_cannot_be_scored():
    out = v.multiplicity([0.0] * 80, [])
    assert out["psr0"] is None and out["reason"]


def test_the_trial_count_is_reported_as_a_lower_bound():
    assert "하한" in v.multiplicity(series(1, 300.0), [])["note"]
    assert math.isclose(v.DSR_THRESHOLD, 0.95)
