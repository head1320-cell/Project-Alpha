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


def doubled(net, commission_bp=3.0, slippage_ticks=2) -> dict:
    """비용을 두 배로 놓은 계산 — 두 배로 놓은 수수료율과 슬리피지가 함께 온다."""
    return {"double": brief(net=net), "commission_bp": commission_bp, "slippage_ticks": slippage_ticks}


def good(**changes) -> dict:
    """전부 통과하는 입력 — 시험마다 한 군데만 바꾼다."""
    base = dict(
        origin={"grade": "E3", "grade_reason": "쓰인 분봉이 전부 제공자의 실제 응답입니다.", "sessions": {"kis": 60, "synthetic": 0, "unknown": 0}},
        sessions=60, skipped=0, bar_label_known=True, summary=brief(), slippage_ticks=1,
        oos={"reason": None, "split": {"in_sample_days": 42, "out_of_sample_days": 18}, "in_sample": brief(), "out_of_sample": brief(trades=30)},
        oos_views=1, stress=doubled(200.0),
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
    # 가르지 못했으면 본 것도 없다 — '몇 번째 보는지 세지 못했다'는 말은 시행 기록이 실패했을 때의 말이다
    for views in (None, 1):
        facts = gates.build(**good(oos=oos, oos_views=views))["gates"][3]["facts"]
        assert not any("번째" in f or "세지 못했습니다" in f for f in facts) and any("사후" in f for f in facts)


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
@pytest.mark.parametrize("stress, want", [(doubled(1.0), OK), (doubled(0.0), BAD), (doubled(None), UNKNOWN), (None, UNKNOWN)])
def test_cost_robustness_is_the_net_expectancy_under_doubled_costs(stress, want):
    assert states(gates.build(**good(stress=stress)))["cost_robustness"] == want


def robust(stress) -> dict:
    return next(g for g in gates.build(**good(stress=stress))["gates"] if g["key"] == "cost_robustness")


def test_doubling_costs_that_are_both_zero_measures_nothing():
    gate = robust(doubled(200.0, commission_bp=0.0, slippage_ticks=0))
    assert gate["state"] == UNKNOWN and "달라지는 것이 없습니다" in gate["reason"]        # 0 의 두 배는 0 — 통과로 읽히면 공허한 통과다
    assert robust(doubled(200.0, commission_bp=3.0, slippage_ticks=0))["state"] == OK     # 짝: 하나라도 0 이 아니면 잰 것이다
    assert robust(doubled(200.0, commission_bp=0.0, slippage_ticks=2))["state"] == OK


def test_a_zero_assumption_is_named_when_only_the_other_cost_was_doubled():
    assert any("슬리피지" in f and "0틱" in f for f in robust(doubled(200.0, commission_bp=3.0, slippage_ticks=0))["facts"])
    assert any("수수료율" in f and "0" in f for f in robust(doubled(200.0, commission_bp=0.0, slippage_ticks=2))["facts"])
    plain = robust(doubled(200.0))["facts"]
    assert not any("0틱" in f for f in plain) and len(plain) == 1


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


# ── 순차 증거(e-값) — 다중 비교 관문의 ★사실 줄★이다. 관문의 상태는 확률(DSR)이 정한다 (묶음 G · G1) ──────────────
def seq(**changes) -> dict:
    base = {"method": "capped_betting_mixture", "alpha": 0.05, "trials": 3, "threshold": 60.0, "cap": 4_000.0, "days": 80,
            "e_value": 12.3456, "peak": 71.25, "saturated": False, "exceeded_days": 0, "worst": -1_530.4, "passed": True,
            "reason": None, "assumption": "가정입니다.", "loss_limit": 2_000.0, "cap_multiple": 2.0}
    return {**base, **changes}


def mult_gate(sequential, value=0.97):
    m = {"n": 3, "value": value, "threshold": 0.95, "corrected": True, "reason": None if value is not None else "흐름이 짧습니다.",
         "days": 80, "note": "하한입니다.", "sequential": sequential}
    return next(g for g in gates.build(**good(multiplicity=m))["gates"] if g["key"] == "multiplicity")


def seq_facts(gate) -> list[str]:
    return [f for f in gate["facts"] if "순차 증거" in f]


def test_the_sequential_evidence_is_read_out_with_its_peak_its_value_and_its_threshold():
    facts = seq_facts(mult_gate(seq()))
    assert facts[0] == ("순차 증거(e-값)의 최고값이 기준 이상입니다. 최고 71.25 · 현재 12.35 · 기준 60(시행 3회 × 20). "
                        "이 기준은 기간을 늘려 가며 다시 봐도 유효합니다.")
    below = seq_facts(mult_gate(seq(peak=59.99, e_value=3.0, passed=False)))
    assert below[0].startswith("순차 증거(e-값)의 최고값이 기준에 못 미칩니다. 최고 59.99 · 현재 3.00 · 기준 60(시행 3회 × 20).")


def test_the_assumption_is_always_read_out_with_the_cap_and_the_worst_day_seen():
    facts = seq_facts(mult_gate(seq()))
    assert facts[1] == ("순차 증거는 하루 손실이 하루 최대 손실의 2배(4,000원)를 넘지 않는다는 가정 아래의 값입니다. "
                        "배수는 이 도구의 설정값이며 표본에서 가장 큰 하루 손실은 1,530원입니다.")
    never_lost = seq_facts(mult_gate(seq(worst=250.0)))
    assert never_lost[1].endswith("배수는 이 도구의 설정값이며 표본에 손실이 난 날이 없어 이 가정을 표본으로 확인하지 못했습니다.")
    assert len(facts) == len(never_lost) == 2


def test_a_cap_that_was_exceeded_is_said_first_and_the_evidence_is_not_read():
    facts = seq_facts(mult_gate(seq(exceeded_days=3, worst=-9_120.0, passed=False, reason="넘었습니다.")))
    assert facts[0] == ("하루 손실이 가정한 상한을 넘은 날이 3일 있어 순차 증거(e-값)를 증거로 읽지 않습니다. "
                        "상한 4,000원 · 가장 큰 하루 손실 9,120원입니다.")
    assert not any("기준 이상" in f for f in facts)                                    # 숫자가 기준을 넘었어도 그렇게 적지 않는다
    assert any("가정 아래의 값" in f for f in facts)


def test_a_huge_value_is_written_as_a_bound_not_as_a_number():
    facts = seq_facts(mult_gate(seq(peak=1e12, e_value=1e12, saturated=True)))
    assert "최고 1조 이상 · 현재 1조 이상" in facts[0]


def test_without_a_value_the_reason_is_the_fact_and_nothing_is_invented():
    why = "하루 최대 손실을 정하지 않아 순차 증거(e-값)를 계산하지 않았습니다."
    none = seq(e_value=None, peak=None, passed=None, cap=None, days=None, exceeded_days=None, worst=None, saturated=None,
               assumption=None, reason=why, loss_limit=None)
    gate = mult_gate(none)
    assert seq_facts(gate) == [why]
    assert not any("최고" in f or "기준 이상" in f or "못 미칩니다" in f for f in seq_facts(gate))


@pytest.mark.parametrize("value, want", [(0.97, OK), (0.90, BAD), (None, UNKNOWN)])
@pytest.mark.parametrize("sequential", [seq(), seq(passed=False, peak=1.0, e_value=0.2),
                                        seq(exceeded_days=2, passed=False, reason="넘었습니다."), None])
def test_the_state_of_the_gate_is_the_probability_s_alone(value, want, sequential):
    """★e-값은 사실 줄이다★ — 통과해도 미달을 통과로 바꾸지 않고, 못 미쳐도 통과를 미달로 바꾸지 않는다."""
    gate = mult_gate(sequential, value=value)
    assert gate["state"] == want
    assert bool(seq_facts(gate)) == (sequential is not None)
    assert "순차" not in gate["reason"]                                               # 관문의 사유는 확률의 것이다


def test_the_sequential_lines_keep_the_voice_and_the_banned_words_out():
    banned = ("검증됨", "입증", "견고", "프로덕션", "투자 우위", "더 나은 전략")
    for sequential in (seq(), seq(passed=False, peak=1.0, e_value=0.2), seq(exceeded_days=2, passed=False, worst=-9_000.0),
                       seq(worst=10.0), seq(peak=1e12, e_value=1e12, saturated=True),
                       seq(e_value=None, peak=None, passed=None, reason="값이 없습니다.", assumption=None)):
        for text in mult_gate(sequential)["facts"]:
            assert text.endswith("니다.") and "—" not in text and "–" not in text, text
            assert not any(word in text for word in banned), text


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


def test_the_out_of_sample_gate_always_says_the_whole_period_result_already_contained_it():
    for views in (1, 3, None):
        facts = next(g for g in gates.build(**good(oos_views=views))["gates"] if g["key"] == "out_of_sample")["facts"]
        assert any("전체 기간 결과" in f and "이미 들어 있습니다" in f for f in facts)
