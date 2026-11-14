"""관문 표 — 한 규칙의 결과를 일곱 관문으로 읽는다 (분봉 백테스트 설계 §8.3 · W4d d3).

상태 어휘는 `run_evidence` 의 셋(`ok · degraded · unknown`)이다. ★미상은 통과가 아니고, 재지 않은 관문은 늘 미상으로 남는다★ —
그래서 어떤 규칙도 일곱을 전부 통과할 수 없다(경제적 가치와 모의·실계좌는 이 도구가 재지 않는다).
"""
from __future__ import annotations

import pytest

from src.engine import run_evidence
from src.engine.intraday import gates

OK, BAD, UNKNOWN = run_evidence.AXIS_OK, run_evidence.AXIS_DEGRADED, run_evidence.AXIS_UNKNOWN


def brief(trades=40, net=1_000.0, gross=2_000.0):
    return {"trades": trades, "gross_total": gross * trades, "gross_expectancy": gross,
            "net_total": None if net is None else net * trades, "net_expectancy": net, "win_rate": 0.5,
            "basis": "gross" if net is None else "net"}


def good(**changes) -> dict:
    """전부 통과하는 입력 — 시험마다 한 군데만 바꾼다."""
    base = dict(
        origin={"grade": "E3", "grade_reason": "쓰인 분봉이 전부 제공자의 실제 응답입니다.", "sessions": {"kis": 60, "synthetic": 0, "unknown": 0}},
        sessions=60, skipped=0, bar_label_known=True, summary=brief(), slippage_ticks=1,
        oos={"reason": None, "split": {"in_sample_days": 42, "out_of_sample_days": 18}, "in_sample": brief(), "out_of_sample": brief(trades=30)},
        oos_views=1, stress={"double": brief(net=200.0)},
        multiplicity={"n": 3, "value": 0.97, "threshold": 0.95, "corrected": True, "reason": None, "days": 60, "note": "하한입니다."},
        trial_error=None)
    return {**base, **changes}


def states(result) -> dict:
    return {g["key"]: g["state"] for g in result["gates"]}


def test_there_are_seven_gates_in_the_order_of_the_evidence_ladder():
    out = gates.build(**good())
    assert [g["key"] for g in out["gates"]] == list(gates.GATES) == [
        "data_integrity", "point_in_time", "costs", "out_of_sample", "cost_robustness", "multiplicity", "economic_value"]
    assert all(g["label"] and g["reason"].endswith("니다.") for g in out["gates"])


def test_even_the_best_case_cannot_pass_all_seven():
    out = gates.build(**good())
    assert states(out) == {"data_integrity": OK, "point_in_time": OK, "costs": OK, "out_of_sample": OK,
                           "cost_robustness": OK, "multiplicity": OK, "economic_value": UNKNOWN}
    assert out["counts"] == {"ok": 6, "degraded": 0, "unknown": 1}
    assert out["sentence"] == "관문 일곱 가운데 통과 6 · 미달 0 · 미상 1 입니다."
    assert out["on_synthetic"] is False


# ── 데이터 무결성 ─────────────────────────────────────────────────────────────────────
def test_synthetic_bars_degrade_the_data_gate_and_mark_everything_below():
    out = gates.build(**good(origin={"grade": "E0", "grade_reason": "모의 모드에서 만든 합성 분봉이 섞여 있습니다.", "sessions": {}}))
    assert states(out)["data_integrity"] == BAD and out["on_synthetic"] is True
    assert out["sentence"].endswith("합성 분봉 위의 숫자이며 예측력이나 수익의 증거가 아닙니다.")


def test_unknown_origin_is_unknown_not_degraded():
    out = gates.build(**good(origin={"grade": None, "grade_reason": "출처를 알 수 없는 분봉이 섞여 있어 등급을 매기지 않았습니다.", "sessions": {}}))
    assert states(out)["data_integrity"] == UNKNOWN and out["on_synthetic"] is False


def test_skipped_sessions_degrade_the_data_gate_and_the_count_is_shown():
    out = gates.build(**good(skipped=3))
    gate = out["gates"][0]
    assert gate["state"] == BAD and "3" in gate["reason"]


def test_no_sessions_at_all_is_unknown():
    assert states(gates.build(**good(sessions=0, summary=brief(trades=0))))["data_integrity"] == UNKNOWN


# ── 시점 정합 ─────────────────────────────────────────────────────────────────────────
def test_an_unverified_bar_label_keeps_point_in_time_unknown():
    gate = gates.build(**good(bar_label_known=False))["gates"][1]
    assert gate["state"] == UNKNOWN and "1분" in gate["reason"]


# ── 거래비용 ─────────────────────────────────────────────────────────────────────────
def test_without_a_net_result_the_cost_gate_is_unknown():
    assert states(gates.build(**good(summary=brief(net=None))))["costs"] == UNKNOWN


def test_the_cost_gate_always_lists_what_was_not_measured():
    gate = gates.build(**good())["gates"][2]
    assert any("시장충격" in f for f in gate["facts"]) and any("가정" in f for f in gate["facts"])


# ── 표본외 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("trades, net, want", [(30, 100.0, OK), (30, 0.0, BAD), (30, -5.0, BAD), (29, 100.0, UNKNOWN), (30, None, UNKNOWN)])
def test_out_of_sample_needs_thirty_trades_and_a_positive_net_expectancy(trades, net, want):
    oos = {"reason": None, "split": {"in_sample_days": 42, "out_of_sample_days": 18}, "in_sample": brief(),
           "out_of_sample": brief(trades=trades, net=net)}
    assert states(gates.build(**good(oos=oos)))["out_of_sample"] == want


def test_a_period_too_short_to_split_is_unknown():
    oos = {"reason": "too_few_days", "split": None, "in_sample": None, "out_of_sample": None}
    assert states(gates.build(**good(oos=oos)))["out_of_sample"] == UNKNOWN


def test_looking_again_at_the_same_out_of_sample_is_said_out_loud():
    first = gates.build(**good(oos_views=1))["gates"][3]
    third = gates.build(**good(oos_views=3))["gates"][3]
    assert not any("3번째" in f for f in first["facts"]) and any("3번째" in f for f in third["facts"])
    assert any("사후" in f for f in first["facts"])                # 종목을 지금 골랐다는 것은 늘 적는다
    assert third["state"] == first["state"]                       # 사실을 붙일 뿐 상태를 지어 바꾸지 않는다


def test_an_unrecorded_trial_cannot_say_how_many_times_it_was_looked_at():
    gate = gates.build(**good(oos_views=None))["gates"][3]
    assert any("세지 못" in f for f in gate["facts"])


# ── 비용 강건성 ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("stress, want", [({"double": brief(net=1.0)}, OK), ({"double": brief(net=0.0)}, BAD),
                                           ({"double": brief(net=None)}, UNKNOWN), (None, UNKNOWN)])
def test_cost_robustness_is_the_net_expectancy_under_doubled_costs(stress, want):
    assert states(gates.build(**good(stress=stress)))["cost_robustness"] == want


# ── 다중 비교 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value, want", [(0.95, OK), (0.9499, BAD), (None, UNKNOWN)])
def test_multiplicity_compares_the_probability_with_the_conventional_threshold(value, want):
    m = {"n": 4, "value": value, "threshold": 0.95, "corrected": True, "reason": None if value is not None else "흐름이 짧습니다.",
         "days": 60, "note": "하한입니다."}
    gate = [g for g in gates.build(**good(multiplicity=m))["gates"] if g["key"] == "multiplicity"][0]
    assert gate["state"] == want
    assert any("관례" in f for f in gate["facts"]) and any("4" in f for f in gate["facts"])


def test_a_trial_that_could_not_be_recorded_leaves_multiplicity_unknown_and_never_counts_as_one():
    out = gates.build(**good(multiplicity=None, trial_error="시행 기록을 남기지 못했습니다."))
    gate = [g for g in out["gates"] if g["key"] == "multiplicity"][0]
    assert gate["state"] == UNKNOWN and gate["reason"] == "시행 기록을 남기지 못했습니다."


# ── 경제적 가치 ───────────────────────────────────────────────────────────────────────
def test_economic_value_is_never_measured_here():
    for changes in ({}, {"summary": brief(net=1e9)}, {"multiplicity": {"n": 1, "value": 1.0, "threshold": 0.95, "corrected": False, "reason": None, "days": 250, "note": ""}}):
        gate = gates.build(**good(**changes))["gates"][-1]
        assert gate["state"] == UNKNOWN and "재지 않습니다" in gate["reason"]


def test_the_vocabulary_is_the_repository_s_and_nothing_else():
    worst = gates.build(**good(origin={"grade": "E0", "grade_reason": "합성입니다.", "sessions": {}}, skipped=2, bar_label_known=False,
                               summary=brief(net=None), oos=None, stress=None, multiplicity=None, trial_error=None, oos_views=None))
    assert {g["state"] for g in worst["gates"]} <= {OK, BAD, UNKNOWN}
    assert worst["counts"]["ok"] == 0
    for g in worst["gates"]:
        for text in (g["reason"], *g["facts"]):
            assert text.endswith("니다.") and "—" not in text and "–" not in text, text
    banned = ("검증됨", "입증", "견고", "프로덕션", "투자 우위", "더 나은 전략")
    best = gates.build(**good())
    assert not any(word in text for g in best["gates"] for text in (g["reason"], *g["facts"], best["sentence"]) for word in banned)
