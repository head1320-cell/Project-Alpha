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


def test_a_trial_without_a_net_flow_is_counted_but_cannot_be_scored():
    out = v.multiplicity(None, [series(2, 0.0), series(3, 0.0)])
    assert out["n"] == 3 and out["value"] is None and out["psr0"] is None and out["dsr"] is None
    assert out["reason"] == v.REASONS["net_unknown"]


def test_family_trials_without_a_net_flow_still_count_and_only_make_the_correction_stronger():
    current, others = series(1, 300.0), [series(s, 0.0) for s in (2, 3)]
    measured = v.multiplicity(current, others)
    with_blind = v.multiplicity(current, [*others, None, None])
    assert measured["n"] == 3 and with_blind["n"] == 5
    assert with_blind["dsr"] < measured["dsr"]                      # 흐름을 모르는 시행도 '해 본 것'이다 — 빼면 보정이 약해진다
    assert with_blind["unscored"] == 2 and measured["unscored"] == 0


def test_when_only_one_trial_can_be_scored_the_correction_is_unknown_not_skipped():
    out = v.multiplicity(series(1, 300.0), [None])
    assert out["n"] == 2 and out["corrected"] is True and out["value"] is None and out["reason"]
    assert out["psr0"] is not None                                  # 보정 전 확률은 있다 — 그러나 관문이 보는 값은 없다


def test_similarity_is_only_measured_when_every_trial_covers_the_same_days():
    current, others = series(1, 300.0), [series(s, 0.0) for s in (2, 3, 4)]
    same = v.multiplicity(current, others)
    mixed = v.multiplicity(current, others, same_days=False)
    assert same["n_effective"] is not None and same["n_effective_reason"] is None
    assert mixed["n_effective"] is None and mixed["dsr_effective"] is None
    assert mixed["n_effective_reason"] == v.REASONS["different_days"]
    assert mixed["dsr"] == same["dsr"]                              # 시행 횟수로 한 보정은 그대로다


# ── 워크포워드 ────────────────────────────────────────────────────────────────────────
#   여드레를 넷으로: [D0 D1] [D2 D3] [D4 D5] [D6 D7].  칸 A 와 칸 B 의 날마다 손익(원):
#       A   100  100 | −50  −50 | 200  200 | −100 −100
#       B  −100 −100 |  80   80 | −30  −30 |  300  300
#   구간 1 에서 고른다(A 100 > B −100) → 구간 2 에 A: −100 · 구간 2 에서 고른다(B 80 > A −50) → 구간 3 에 B: −60
#   구간 3 에서 고른다(A 200 > B −30) → 구간 4 에 A: −200.   이어 붙이면 −360(여섯 거래).
#   ★적용할 구간을 미리 보고 골랐다면★ B · A · B 로 +160 +400 +600 = +1,160 이 나온다 — 그 값이 나오면 앞을 본 것이다.
WF_DATES = DATES[:8]
CELL_A = [100, 100, -50, -50, 200, 200, -100, -100]
CELL_B = [-100, -100, 80, 80, -30, -30, 300, 300]


def cell(pnl, dates=WF_DATES) -> list[dict]:
    return [f for d, p in zip(dates, pnl) if p is not None for f in day_fills(d, p)]


def wf(cells, folds=4, dates=WF_DATES, commission_bp=0):
    return v.walk_forward(cells, dates, folds, commission_bp=commission_bp)


def test_the_days_are_cut_into_consecutive_folds_as_evenly_as_they_go():
    assert [len(f) for f in v.fold_dates(DATES, 4)] == [3, 3, 2, 2]
    assert v.fold_dates(reversed(WF_DATES), 4) == [WF_DATES[0:2], WF_DATES[2:4], WF_DATES[4:6], WF_DATES[6:8]]
    assert v.fold_dates(DATES[:3], 4) == []                         # 구간보다 날이 적다


def test_walk_forward_chooses_on_one_fold_and_applies_to_the_next():
    out = wf([cell(CELL_A), cell(CELL_B)])
    assert out["reason"] is None and out["folds"] == 4
    assert [s["chosen"] for s in out["steps"]] == [0, 1, 0]
    assert [s["chosen_expectancy"] for s in out["steps"]] == [100.0, 80.0, 200.0]
    assert [s["candidates"] for s in out["steps"]] == [[100.0, -100.0], [-50.0, 80.0], [200.0, -30.0]]
    assert [s["applied"]["net_total"] for s in out["steps"]] == [-100.0, -60.0, -200.0]
    assert out["steps"][0]["choose"] == {"from": WF_DATES[0], "to": WF_DATES[1]}
    assert out["steps"][0]["apply"] == {"from": WF_DATES[2], "to": WF_DATES[3]}
    assert out["stitched"]["net_total"] == -360.0 and out["stitched"]["trades"] == 6
    assert out["stitched"]["net_expectancy"] == pytest.approx(-60.0)


def test_the_choice_never_sees_the_fold_it_is_applied_to():
    base = wf([cell(CELL_A), cell(CELL_B)])
    last_changed = wf([cell([*CELL_A[:6], 9_000, 9_000]), cell([*CELL_B[:6], -9_000, -9_000])])
    assert [s["chosen"] for s in last_changed["steps"]] == [s["chosen"] for s in base["steps"]]
    assert last_changed["steps"][2]["applied"]["net_total"] == 18_000.0      # 적용한 결과만 달라진다
    assert base["stitched"]["net_total"] != 1_160.0                          # 머리말의 '앞을 본' 값이 아니다


def test_the_first_fold_is_only_ever_used_to_choose():
    out = wf([cell(CELL_A), cell(CELL_B)])
    applied_days = {s["apply"]["from"] for s in out["steps"]} | {s["apply"]["to"] for s in out["steps"]}
    assert WF_DATES[0] not in applied_days and WF_DATES[1] not in applied_days
    assert out["stitched"]["trades"] == 6                           # 여덟 거래 가운데 첫 구간의 둘은 이어 붙인 결과에 없다


def test_a_tie_goes_to_the_cell_declared_first_and_a_cell_without_trades_is_not_chosen():
    tie = wf([cell(CELL_B), cell(CELL_B)])
    assert [s["chosen"] for s in tie["steps"]] == [0, 0, 0]
    quiet_first = wf([cell([None, None, *CELL_A[2:]]), cell(CELL_B)])        # 칸 A 는 첫 구간에 거래가 없다
    assert quiet_first["steps"][0]["chosen"] == 1 and quiet_first["steps"][0]["candidates"] == [None, -100.0]


def test_a_fold_where_no_cell_traded_chooses_nothing_and_adds_nothing():
    out = wf([cell([None, None, *CELL_A[2:]]), cell([None, None, *CELL_B[2:]])])
    first = out["steps"][0]
    assert first["chosen"] is None and first["applied"] is None and first["reason"] == "no_choice"
    assert [s["chosen"] for s in out["steps"][1:]] == [1, 0]
    assert out["stitched"]["net_total"] == -260.0 and out["stitched"]["trades"] == 4
    assert v.REASONS["no_choice"].endswith("니다.")


def test_without_a_net_result_walk_forward_does_not_fall_back_to_the_gross_one():
    out = wf([cell(CELL_A), cell(CELL_B)], commission_bp=None)
    assert out["reason"] == "net_unknown" and out["steps"] == [] and out["stitched"] is None


def test_fewer_days_than_folds_gives_no_walk_forward():
    out = wf([cell(CELL_A[:3], WF_DATES[:3]), cell(CELL_B[:3], WF_DATES[:3])], dates=WF_DATES[:3])
    assert out["reason"] == "too_few_days" and out["steps"] == [] and out["stitched"] is None


def test_when_nothing_could_be_chosen_anywhere_there_is_no_stitched_result():
    out = wf([[], []])
    assert out["reason"] is None and all(s["chosen"] is None for s in out["steps"]) and out["stitched"] is None


# ── 시장 구분을 모르는 종목 ───────────────────────────────────────────────────────────
BLIND = [{**f, "market": None, "instrument": None} for f in FILLS]
ASSUME = {"unknown_market": "KOSPI", "unknown_instrument": "etf"}


def test_without_a_market_the_net_side_is_unknown_until_an_assumption_is_declared():
    assert v.out_of_sample(BLIND, DATES, commission_bp=0)["out_of_sample"]["net_total"] is None
    assert v.out_of_sample(BLIND, DATES, commission_bp=0, assume=ASSUME)["out_of_sample"]["net_total"] == 500
    assert v.result(BLIND, commission_bp=0)["net_total"] is None
    assert v.result(BLIND, commission_bp=0, assume=ASSUME)["net_total"] == 750


def test_walk_forward_uses_the_declared_assumption_too():
    cells = [[{**f, "market": None, "instrument": None} for f in cell(c)] for c in (CELL_A, CELL_B)]
    assert v.walk_forward(cells, WF_DATES, 4, commission_bp=0)["reason"] == "net_unknown"
    out = v.walk_forward(cells, WF_DATES, 4, commission_bp=0, assume=ASSUME)
    assert out["reason"] is None and out["stitched"]["net_total"] == -360.0
