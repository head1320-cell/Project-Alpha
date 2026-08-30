"""매크로 음성 통제 ★리포트 계약★ — 사전등록을 코드가 지킨다 (M3)
==============================================================================
설계·사전등록: `docs/superpowers/specs/2026-08-29-macro-regime-negative-control-design.md`

이 하네스가 저지를 수 있는 가장 나쁜 일은 **결과를 본 뒤 통계를 고르는 것**이다.
사전등록은 문서에 있지만, 문서는 코드를 강제하지 못한다 — 그래서 주 통계·임계·
판정 규칙을 리포트에 **구조로** 싣고 테스트가 그것을 건다.

★판정 함수를 순수 함수로 떼어 놓았다★ 판정은 데이터가 아니라 **규칙**이다.
데이터를 만들어 규칙을 확인하려 하면 픽스처의 우연을 계약으로 착각하게 된다
(S6 에서 "표본에서 최소 하나는 널 안에" 를 걸었다가 버린 그 실수).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from scripts.regime_control import (  # noqa: E402
    COST_LEVELS,
    PRIMARY,
    SECONDARY,
    SPA_ALPHA,
    arm_regime,
    decide_verdict,
    power_curves,
    run,
)

import src.engine.regime_surrogates as rs  # noqa: E402
from src.engine.research_power import power_report  # noqa: E402
from src.engine.research_verdict import (  # noqa: E402
    ALL_VERDICTS,
    VERDICT_EVIDENCE_OF_NO_EFFECT,
    VERDICT_INCONCLUSIVE,
    VERDICT_NO_EVIDENCE,
    VERDICT_POSITIVE,
    VERDICT_UNDERPOWERED,
    require_power_fields,
)

LABELS = (["G"] * 4 + ["R"] * 3 + ["S"] * 2 + ["D"] * 5 + ["G"] * 2
          + ["R"] * 4 + ["S"] * 3 + ["G"] * 1 + ["D"] * 2)
POINTS = [{"t": f"20{18 + i // 12:02d}-{i % 12 + 1:02d}", "growth": 0.1,
           "inflation": -0.2, "regime": g} for i, g in enumerate(LABELS)]


def _cost_map(percentiles):
    """비용 수준별 분위 — ★판정 규칙만 건드리는 합성 입력★

    `decide_verdict` 는 방향을 **분위에서 파생**한다(값과 분위수를 따로 비교하면
    동률에서 어긋난다 — S6 에서 치른 값). 그래서 여기서 넣는 것도 분위뿐이다.
    """
    return {str(c): {"percentile": p}
            for c, p in zip(COST_LEVELS, percentiles, strict=True)}


# ══════════════════════════════════════════════════════════════════════════
# H1·H2 ★사전등록이 코드에 있다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_primary_statistic_is_fixed_to_the_sharpe_difference():
    """★결과를 본 뒤 주 통계를 고를 수 없다★ — 사전등록의 핵심."""
    assert PRIMARY == "sharpe_diff"
    assert PRIMARY not in SECONDARY


def test_every_secondary_statistic_is_marked_non_decisive():
    """부 통계는 **보고만** 한다 — 판정에 쓰면 사전등록이 무의미해진다."""
    rep = run(*_tiny(), n_shift=3, n_markov=0, n_block=0, run_spa=False)
    stats = rep["statistics"]
    assert stats[PRIMARY]["decisive"] is True
    assert SECONDARY, "부 통계가 비면 이 테스트는 아무것도 검사하지 않는다"
    for s in SECONDARY:
        assert stats[s]["decisive"] is False, s


def test_the_report_declares_the_preregistration():
    rep = run(*_tiny(), n_shift=3, n_markov=0, n_block=0, run_spa=False)
    pre = rep["preregistered"]
    assert pre["primary_statistic"] == PRIMARY
    assert pre["threshold_pct"] == list(rep["preregistered"]["threshold_pct"])
    assert pre["convention"] is True          # 임계는 관례이지 측정치가 아니다
    assert pre["cost_levels_bps"] == list(COST_LEVELS)
    assert pre["spa_alpha"] == SPA_ALPHA
    assert pre["decision_rule"]


# ══════════════════════════════════════════════════════════════════════════
# H3·H4·H5 ★판정 규칙 — 순수 함수로 직접 건다★
# ══════════════════════════════════════════════════════════════════════════
def test_one_cost_level_passing_is_not_enough():
    """★비용 은폐를 막는다★ 국면 팔은 더 거래한다 — 한 수준만 보면 비용이 숨는다."""
    v = decide_verdict(_cost_map([0.0, 50.0, 50.0]), spa_p=0.01)
    assert v["passed"] is False
    assert any("비용" in r for r in v["why"]), v["why"]


def test_all_cost_levels_outside_with_a_significant_spa_passes():
    """★짝★ 항상 불통과를 내는 구현을 배제한다."""
    v = decide_verdict(_cost_map([0.0, 0.0, 0.0]), spa_p=0.01)
    assert v["passed"] is True and v["null_outside"] is True and v["spa_ok"] is True


def test_being_outside_the_null_is_not_enough_without_spa():
    """★엇갈리면 보수적으로 불통과★ — 다중비교 보정을 무시하지 않는다."""
    v = decide_verdict(_cost_map([100.0, 100.0, 100.0]), spa_p=0.20)
    assert v["passed"] is False and v["null_outside"] is True and v["spa_ok"] is False
    assert any("SPA" in r for r in v["why"])


def test_a_missing_spa_is_treated_as_not_significant():
    """★미상 ≠ 유의★ SPA 를 못 돌렸으면 통과시키지 않는다."""
    v = decide_verdict(_cost_map([0.0, 0.0, 0.0]), spa_p=None)
    assert v["passed"] is False and v["spa_ok"] is False


def test_a_missing_percentile_cannot_pass():
    """널이 비면 분위가 없다 — 없는 증거로 통과시키지 않는다."""
    m = _cost_map([0.0, 0.0, 0.0])
    m[str(COST_LEVELS[1])] = {"percentile": None}
    assert decide_verdict(m, spa_p=0.01)["passed"] is False


# ══════════════════════════════════════════════════════════════════════════
# ★A2 — 판정에 어휘와 검정력을 싣는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_verdict_carries_the_five_class_label_and_the_power_block():
    """★`passed` 불리언 하나로는 M1~M5 를 설명할 수 없었다★"""
    v = decide_verdict(_cost_map([0.0, 0.0, 0.0]), spa_p=0.01)
    assert v["verdict"] in ALL_VERDICTS
    assert require_power_fields(v) == []      # mde·power·n_eff 가 사유와 함께 실린다


def test_passed_still_means_exactly_what_it_meant_before():
    """★기존 22개 테스트와의 다리★ — 어휘를 더해도 규칙은 그대로다."""
    for pcts, spa in (([0.0, 0.0, 0.0], 0.01), ([0.0, 50.0, 50.0], 0.01),
                      ([100.0, 100.0, 100.0], 0.20), ([0.0, 0.0, 0.0], None)):
        v = decide_verdict(_cost_map(pcts), spa_p=spa)
        assert v["passed"] is (v["null_outside"] and v["spa_ok"])
        assert v["passed"] is (v["verdict"] == VERDICT_POSITIVE)


def test_a_failed_gate_without_a_measured_power_is_no_evidence_not_no_effect():
    """★만다트 §4★ M1~M5 의 실제 형태다 — 널 밖인데 SPA 미달.

    검정력을 재지 않은 채로는 `evidence_of_no_effect` 를 주장할 수 없다.
    """
    v = decide_verdict(_cost_map([100.0, 100.0, 100.0]), spa_p=0.20)
    assert v["verdict"] == VERDICT_INCONCLUSIVE
    both_failed = decide_verdict(_cost_map([50.0, 50.0, 50.0]), spa_p=0.20)
    assert both_failed["verdict"] == VERDICT_NO_EVIDENCE
    assert both_failed["power"] is None
    assert v["reasons"]["power"]


def test_a_supplied_power_block_changes_the_label_not_the_pass_flag():
    """★검정력은 **못 넘은 것**의 뜻을 바꾼다 — 통과 여부를 바꾸지 않는다★"""
    m = _cost_map([50.0, 50.0, 50.0])
    weak = decide_verdict(m, spa_p=0.20, power_block=_power_block(0.40))
    strong = decide_verdict(m, spa_p=0.20, power_block=_power_block(0.95))
    assert weak["verdict"] == VERDICT_UNDERPOWERED
    assert strong["verdict"] == VERDICT_EVIDENCE_OF_NO_EFFECT
    assert weak["passed"] is False and strong["passed"] is False
    assert weak["power"] == pytest.approx(0.40)
    assert weak["n_eff"] == pytest.approx(129.23, abs=0.01)
    assert require_power_fields(weak) == [] and require_power_fields(strong) == []


# ══════════════════════════════════════════════════════════════════════════
# ★A3 — 세 성분의 검정력을 한 번의 격자에서★
# ══════════════════════════════════════════════════════════════════════════
def _runner(table):
    """주입된 시행 — 실제 백테스트를 돌리지 않고 규칙만 검사한다."""
    return lambda scale, seed: table[(scale, seed)]


def test_the_three_curves_come_from_one_sweep():
    """★같은 실행에서 공짜로 나온다★ — 세 번 돌리면 3배 비용이고 시드도 갈라진다."""
    calls = []

    def runner(scale, seed):
        calls.append((scale, seed))
        return {"null_outside": scale >= 1.0, "spa_ok": scale >= 3.0}

    out = power_curves(runner, scales=[1.0, 2.0, 3.0], seeds=[0, 1])
    assert len(calls) == 6                       # 3척도 × 2시드, 한 번씩
    assert set(out) == {"conjunction", "null_only", "spa_only"}
    assert [c["rate"] for c in out["null_only"]] == [1.0, 1.0, 1.0]
    assert [c["rate"] for c in out["spa_only"]] == [0.0, 0.0, 1.0]
    assert [c["rate"] for c in out["conjunction"]] == [0.0, 0.0, 1.0]


def test_the_conjunction_is_the_and_of_the_two_components():
    """★짝★ — 연언을 선언으로 바꾸는 구현을 배제한다."""
    tbl = {(1.0, 0): {"null_outside": True, "spa_ok": False},
           (1.0, 1): {"null_outside": False, "spa_ok": True}}
    out = power_curves(_runner(tbl), scales=[1.0], seeds=[0, 1])
    assert out["null_only"][0]["rate"] == pytest.approx(0.5)
    assert out["spa_only"][0]["rate"] == pytest.approx(0.5)
    assert out["conjunction"][0]["rate"] == pytest.approx(0.0)


def test_an_unknown_component_makes_the_conjunction_unknown_not_false():
    """★미상 ≠ 실패★ 관문을 못 돌린 것을 "못 찾았다" 로 세면 검정력이 낮아 보인다."""
    tbl = {(1.0, 0): {"null_outside": True, "spa_ok": None}}
    out = power_curves(_runner(tbl), scales=[1.0], seeds=[0])
    assert out["conjunction"][0]["n_unknown"] == 1
    assert out["conjunction"][0]["rate"] is None
    assert out["spa_only"][0]["rate"] is None
    assert out["null_only"][0]["rate"] == pytest.approx(1.0)


def test_a_runner_that_raises_is_not_silently_counted_as_a_miss():
    """★침묵 폴백 금지★ 하네스 고장이 음성 결과로 위장되면 안 된다."""
    def boom(scale, seed):
        raise RuntimeError("패널 실패")
    with pytest.raises(RuntimeError):
        power_curves(boom, scales=[1.0], seeds=[0])


def _power_block(power: float) -> dict:
    """검정력 격자를 실제로 돌리지 않고 블록만 만든다 — 판정 규칙만 검사한다."""
    return power_report(
        curve=[{"scale": 1.0, "rate": power, "n": 5, "n_resolved": 5,
                "n_unknown": 0, "n_detected": int(round(power * 5)),
                "ci": (0.0, 1.0), "reason": None},
               {"scale": 2.0, "rate": 1.0, "n": 5, "n_resolved": 5,
                "n_unknown": 0, "n_detected": 5, "ci": (0.0, 1.0), "reason": None}],
        observed_scale=1.0, n_obs=84, n_assets=6, rho_bar=0.58)


def test_the_threshold_is_a_parameter_and_labelled_a_convention():
    """★같은 분위, 다른 관례 → 다른 판정★ 그것이 "측정치가 아니다" 라는 뜻이다.

    분위 92~94 는 사전등록된 (5, 95) 안에 있지만 (10, 90) 밖에 있다. 임계를 결과
    뒤에 고를 수 있다면 이 실험은 아무것도 증명하지 못한다 — 그래서 사전등록한다.
    """
    m = _cost_map([93.0, 92.0, 94.0])
    assert decide_verdict(m, spa_p=0.01)["passed"] is False
    loose = decide_verdict(m, spa_p=0.01, threshold_pct=(10.0, 90.0))
    assert loose["passed"] is True
    assert loose["convention"] is True


# ══════════════════════════════════════════════════════════════════════════
# 팔 구성
# ══════════════════════════════════════════════════════════════════════════
def test_the_off_arm_passes_no_regime_at_all():
    assert arm_regime(POINTS, rs.ARM_OFF) is None


def test_the_on_arm_is_the_production_default_weighting():
    """`hard` 가 프로덕션 기본이다 — 실험이 다른 기본을 쓰면 비교가 성립하지 않는다."""
    assert arm_regime(POINTS, rs.ARM_ON)["weighting"] == "hard"
    assert arm_regime(POINTS, rs.ARM_ON_PROB)["weighting"] == "probabilistic"


def test_the_const_arm_removes_timing_but_keeps_the_regime_machinery():
    """★타이밍만 뺀다★ — 경로는 있고 전환이 없다. 기계는 그대로 돈다."""
    reg = arm_regime(POINTS, rs.ARM_CONST)
    assert reg["weighting"] == "hard"
    assert rs.n_runs(reg["points"]) == 1


def test_an_unknown_arm_is_refused():
    with pytest.raises(ValueError):
        arm_regime(POINTS, "regime-magic")


# ══════════════════════════════════════════════════════════════════════════
# H6~H10 정직 라벨과 널의 정직성
# ══════════════════════════════════════════════════════════════════════════
def _tiny():
    """작지만 진짜인 입력 — 실제 `walk_forward` 를 탄다."""
    rng = np.random.default_rng(11)
    n_days = 26 * len(POINTS)
    R = rng.normal(0.0004, 0.011, size=(n_days, 3))
    import pandas as pd
    dates = list(pd.bdate_range("2018-01-01", periods=n_days).date)
    return ["a", "b", "c"], R, dates, POINTS


def test_the_evidence_grade_is_derived_from_the_panel_source():
    """★손으로 적지 않는다★ mock/합성 패널이면 E0."""
    rep = run(*_tiny(), n_shift=2, n_markov=0, n_block=0, run_spa=False)
    assert rep["evidence_grade"] == "E0"
    real = run(*_tiny(), n_shift=2, n_markov=0, n_block=0, run_spa=False,
               panel_is_synthetic=False)
    assert real["evidence_grade"] == "E3"


def test_the_report_carries_the_revision_bias_and_why_the_null_still_works():
    """★개정 편향이 있어도 널 비교는 성립한다★ — 모든 팔이 같은 편향을 공유한다."""
    rep = run(*_tiny(), n_shift=2, n_markov=0, n_block=0, run_spa=False)
    rb = rep["revision_bias"]
    assert rb["status"] == "unmanaged"
    assert rb["why_null_still_works"]


def test_each_arm_reports_the_regime_contract_disclosure():
    """★하드 팔이 확률 계약을 우회한다는 사실★(`ff5ed4e`)이 결과 옆에 붙어야 한다."""
    rep = run(*_tiny(), n_shift=2, n_markov=0, n_block=0, run_spa=False)
    arms = rep["by_cost"][str(COST_LEVELS[0])]["arms"]
    assert arms[rs.ARM_ON]["prob_source"] == "regime_path_hard_label"
    assert arms[rs.ARM_ON]["prob_usage"] == "persistence_assumption"
    assert arms[rs.ARM_OFF]["prob_source"] is None       # 국면을 안 썼다


def test_the_null_says_whether_it_was_enumerated_and_how_many_were_possible():
    """★5개뿐인 널에서 나온 분위와 81개에서 나온 분위는 뜻이 다르다★"""
    rep = run(*_tiny(), n_shift=3, n_markov=0, n_block=0, run_spa=False)
    n = rep["by_cost"][str(COST_LEVELS[0])]["null"][rs.NULL_SHIFT]
    assert n["n_possible"] == len(POINTS) - 1
    assert n["enumerated"] is False and n["n_draws"] == 3

    full = run(*_tiny(), n_shift=None, n_markov=0, n_block=0, run_spa=False)
    nf = full["by_cost"][str(COST_LEVELS[0])]["null"][rs.NULL_SHIFT]
    assert nf["enumerated"] is True and nf["n_draws"] == len(POINTS) - 1


def test_the_cost_sweep_is_not_vacuous():
    """★사전등록의 "비용 3수준 전부" 절이 실제로 일을 해야 한다★

    처음에는 주 통계를 `summary.sharpe_ratio` 에서 읽었는데 그 값은
    `round(sharpe, 2)` 라 해상도가 0.01 이다 — 실측에서 비용을 5→100bps 로 올려도
    **0.42 로 고정**이었다(전정밀도는 0.6706→0.6087). 통계가 비용을 볼 수 없으면
    그 절은 **아무것도 요구하지 않는 문장**이 된다.

    비용이 오르면 회전율이 있는 팔의 주 통계는 **내려가야** 한다.
    """
    names, R, dates, points = _tiny()
    rep = run(names, R, dates, points, n_shift=1, n_markov=0, n_block=0,
              run_spa=False, cost_levels=(5.0, 200.0))
    lo = rep["by_cost"]["5.0"]["arms"][rs.ARM_ON]
    hi = rep["by_cost"]["200.0"]["arms"][rs.ARM_ON]
    assert lo["avg_turnover_pct"] > 0, "회전율이 0 이면 비용이 일할 수 없다"
    assert hi[PRIMARY] < lo[PRIMARY], (lo[PRIMARY], hi[PRIMARY])
    # ★짝 — 왜 요약값을 안 쓰는지★ 그 값은 같은 구간에서 움직이지 않는다.
    assert lo["sharpe_summary_rounded"] == hi["sharpe_summary_rounded"]


def test_the_off_arm_barely_moves_with_cost():
    """★짝★ 회전율이 낮은 팔은 비용에 덜 민감하다 — 비용이 통계를 통째로
    지배하는 것이 아니라는 확인."""
    names, R, dates, points = _tiny()
    rep = run(names, R, dates, points, n_shift=1, n_markov=0, n_block=0,
              run_spa=False, cost_levels=(5.0, 200.0))
    on_delta = abs(rep["by_cost"]["200.0"]["arms"][rs.ARM_ON]["sharpe"]
                   - rep["by_cost"]["5.0"]["arms"][rs.ARM_ON]["sharpe"])
    off_delta = abs(rep["by_cost"]["200.0"]["arms"][rs.ARM_OFF]["sharpe"]
                    - rep["by_cost"]["5.0"]["arms"][rs.ARM_OFF]["sharpe"])
    assert on_delta > off_delta


def test_the_model_confidence_set_is_reported_but_never_decisive():
    """★보조 관측이다★ "무엇이 최선인가" 가 아니라 "무엇을 버릴 수 없는가" 이고,
    사전등록된 판정 규칙에는 들어가지 않는다."""
    rep = run(*_tiny(), n_shift=1, n_markov=0, n_block=0, run_spa=False)
    m = rep["mcs"]
    assert m["decisive"] is False
    assert ("included" in m) and ("reason" in m)
    # 판정은 널과 SPA 만 본다 — MCS 가 무엇을 말하든 통과 여부를 바꾸지 않는다.
    assert set(rep["verdict"]) >= {"null_outside", "spa_ok", "passed"}
    assert "mcs" not in rep["verdict"]


def test_the_same_seed_reproduces_the_report():
    a = run(*_tiny(), n_shift=3, n_markov=2, n_block=2, run_spa=False, seed=5)
    b = run(*_tiny(), n_shift=3, n_markov=2, n_block=2, run_spa=False, seed=5)
    assert a["by_cost"] == b["by_cost"]


def test_the_primary_percentile_exists_for_every_cost_level():
    rep = run(*_tiny(), n_shift=3, n_markov=0, n_block=0, run_spa=False)
    for c in COST_LEVELS:
        blk = rep["by_cost"][str(c)]
        assert PRIMARY in blk["percentile"]
        assert blk["cost_bps"] == c
