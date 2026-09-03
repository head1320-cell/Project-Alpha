"""음성 통제 ★보고서 계약★ — 없는 스킬을 주장하지 않는다 (S6)
==============================================================================
하네스: `scripts/company_view_control.py` · 변환: `src/engine/company_view_controls.py`

이 보고서가 저지를 수 있는 가장 나쁜 일은 **답하지 않은 질문에 답한 척**하는 것이다.
그래서 `claims` 를 산문이 아니라 **구조**로 둔다 — 값이 `None` 이고 사유가 붙는 것을
테스트가 건다. 문장을 검사하는 테스트는 문장만 바꾸면 통과한다(이 저장소가 이미
치른 값: `test_last_place_is_not_called_harmless`).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from scripts.company_view_control import (  # noqa: E402
    NULL_STATS,
    _side,
    baseline_block,
    run,
)

import src.engine.company_view_controls as cvc  # noqa: E402

NAMES = ["a", "b", "c", "d"]


def _R(rows: int = 300, cols: int = 4, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.012, size=(rows, cols))


def _views(confs: list[float] | None = None, mock: bool = True) -> list[dict]:
    mags = [9.0, -4.0, 6.0, -2.0]
    cf = confs if confs is not None else [cvc.DEFAULT_CONFIDENCE] * 4
    return [{"assets": [n], "direction": 1 if m >= 0 else -1,
             "magnitude_pct": abs(m), "confidence": c,
             "source": "company_valuation", "is_mock": mock,
             "confidence_saturated": True, "research_usage": "forward_only"}
            for n, m, c in zip(NAMES, mags, cf, strict=True)]


@pytest.fixture(scope="module")
def report():
    return run(NAMES, _R(), _views(), n_perm=200, seed=11)


# ══════════════════════════════════════════════════════════════════════════
# Z11 분위 — ★"얼마나 큰가" 가 아니라 "널 안에서 어디인가"★
# ══════════════════════════════════════════════════════════════════════════
def test_the_percentile_is_computed_against_the_null():
    null = [1.0, 2.0, 3.0, 4.0]
    assert cvc.percentile_of(0.5, null) == 0.0
    assert cvc.percentile_of(2.0, null) == 50.0
    assert cvc.percentile_of(9.0, null) == 100.0


def test_the_percentile_rises_with_the_value():
    """★짝★ 방향이 뒤집힌 구현을 배제한다."""
    null = list(range(10))
    assert cvc.percentile_of(1, null) < cvc.percentile_of(8, null)


def test_an_empty_null_gives_no_percentile():
    """★없는 널에서 분위를 지어내지 않는다★"""
    assert cvc.percentile_of(1.0, []) is None


def test_every_null_statistic_gets_a_percentile(report):
    for stat in NULL_STATS:
        assert stat in report["percentile_of_real"], stat
        assert stat in report["null"]["stats"], stat


# ══════════════════════════════════════════════════════════════════════════
# Z12·Z13 ★무등가 채널을 신고한다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_uniform_confidence_makes_the_evidence_arm_inert_and_it_is_reported(report):
    """S4 가 예고한 포화 — 그때 `evidence-stripped` 는 `company-on` 과 같은 입력이다.

    ★같은 숫자를 조용히 두 번 싣지 않는다★ 보고서가 그 이유를 말해야 한다.
    """
    inert = report["inert_channels"]
    assert [c["arm"] for c in inert] == [cvc.ARM_STRIPPED]
    assert inert[0]["reason"]
    on = report["arms"][cvc.ARM_ON]["weights"]
    st = report["arms"][cvc.ARM_STRIPPED]["weights"]
    assert on == st                      # 무등가의 결과 — 신고했으므로 놀랍지 않다


def test_a_varied_confidence_is_not_inert():
    """★짝★ 항상 무등가라고 적는 구현을 배제한다."""
    rep = run(NAMES, _R(), _views(confs=[10.0, 40.0, 70.0, 95.0]),
              n_perm=50, seed=11)
    assert rep["inert_channels"] == []
    assert (rep["arms"][cvc.ARM_ON]["weights"]
            != rep["arms"][cvc.ARM_STRIPPED]["weights"])


# ══════════════════════════════════════════════════════════════════════════
# Z14 ★퇴화 기준선을 숨기지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_an_equal_weight_baseline_is_flagged_as_degenerate():
    b = baseline_block(np.full(4, 0.25))
    assert b["degenerate"] is True and b["reason"]


def test_a_real_baseline_is_not_flagged():
    """★짝★ 항상 퇴화라고 적으면 신호가 되지 않는다."""
    b = baseline_block(np.array([0.4, 0.3, 0.2, 0.1]))
    assert b["degenerate"] is False and b["reason"] is None


def test_the_report_carries_the_baseline_verdict(report):
    assert "degenerate" in report["baseline"]
    assert "max_dev_from_equal" in report["baseline"]


# ══════════════════════════════════════════════════════════════════════════
# Z15 ★주장은 구조다 — 산문이 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_report_refuses_to_claim_skill_or_economic_value(report):
    c = report["claims"]
    assert c["predictive_skill"] is None
    assert c["economic_value"] is None
    assert c["reason"]
    assert report["question_answered"] == "transmission_stability"


def test_the_evidence_grade_is_derived_from_the_views():
    """★손으로 적지 않는다★ mock 뷰면 E0, 아니면 E3."""
    assert run(NAMES, _R(), _views(mock=True), n_perm=20)["evidence_grade"] == "E0"
    assert run(NAMES, _R(), _views(mock=False), n_perm=20)["evidence_grade"] == "E3"


# ══════════════════════════════════════════════════════════════════════════
# Z16 판정은 ★관례★다
# ══════════════════════════════════════════════════════════════════════════
def test_the_verdict_threshold_is_a_parameter_and_is_labelled_a_convention(report):
    assert report["verdict"]["convention"] is True
    assert report["verdict"]["threshold_pct"] == [5.0, 95.0]

    wide = run(NAMES, _R(), _views(), n_perm=200, seed=11,
               threshold_pct=(0.0, 100.0))
    assert wide["verdict"]["threshold_pct"] == [0.0, 100.0]
    # ★분위는 관측값이라 임계치를 바꿔도 그대로다★ — 뒤집히는 것은 판정뿐이다.
    assert wide["percentile_of_real"] == report["percentile_of_real"]
    assert wide["verdict"]["by_stat"] != report["verdict"]["by_stat"]


# ══════════════════════════════════════════════════════════════════════════
# ★"구분된다" 가 "좋다" 로 읽히지 않게 한다★ (실행해 보고 발견)
# ══════════════════════════════════════════════════════════════════════════
def test_each_verdict_says_which_side_of_the_null_the_real_arm_is_on(report):
    """실측에서 진짜 팔은 셔플 팔들보다 포트폴리오를 **덜** 움직였다(분위 0.0).
    방향을 안 적으면 그 사실이 "통제를 통과했다" 로 둔갑한다."""
    for stat, v in report["verdict"]["by_stat"].items():
        if v is None:
            continue
        assert v["side"] in ("below", "inside", "above"), stat
        if v["distinguishable"]:
            assert v["side"] != "inside", stat
        else:
            assert v["side"] == "inside", stat


def test_the_side_matches_the_percentile_direction(report):
    """★짝★ 방향을 상수로 박은 구현을 배제한다 — 분위와 일관되어야 한다."""
    for stat, v in report["verdict"]["by_stat"].items():
        if v is None:
            continue
        p = report["percentile_of_real"][stat]
        if v["side"] == "below":
            assert p < 50, (stat, p)
        elif v["side"] == "above":
            assert p > 50, (stat, p)


def test_beyond_null_range_is_stronger_than_a_percentile(report):
    """★꼬리에 겨우 걸친 것과 널이 아예 도달하지 못한 것은 증거의 세기가 다르다★

    실측: `corr_q_dw` 는 분위 96.5 로 임계치를 넘지만 널의 **max 보다 작다** —
    셔플 팔 중에 더 강하게 전달한 것이 있다. `w_l1_vs_off` 는 널의 min 보다도
    작아 범위 밖이다. 두 사실이 같은 라벨을 달면 안 된다.
    """
    st = report["null"]["stats"]
    on = report["arms"][cvc.ARM_ON]
    real = {**on["weights"], "turnover_pct": on["decision"]["turnover_pct"]}
    for stat, v in report["verdict"]["by_stat"].items():
        if v is None:
            continue
        outside = real[stat] < st[stat]["min"] or real[stat] > st[stat]["max"]
        assert v["beyond_null_range"] is bool(outside), stat


def test_the_side_classifier_can_return_all_three_answers():
    """★"항상 above" 를 배제한다★

    처음에는 "표본에서 최소 하나는 널 안에 있어야 한다" 고 걸었는데, 그것은
    **코드가 아니라 픽스처의 성질**이다(4자산 픽스처는 다섯 통계가 전부 100분위,
    8종목 mock 유니버스는 `max_weight` 18분위·`enb` 39분위로 널 안에 있다).
    분류기 자체를 직접 건다.
    """
    assert _side(0.0, 5.0, 95.0) == "below"
    assert _side(50.0, 5.0, 95.0) == "inside"
    assert _side(100.0, 5.0, 95.0) == "above"
    # ★임계치를 넓히면 같은 분위가 안으로 들어온다★ — 상수로 박은 구현을 배제한다.
    assert _side(0.0, 0.0, 100.0) == "inside"


# ══════════════════════════════════════════════════════════════════════════
# ★판단도 널에서 센다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_null_counts_decisions_too(report):
    """셔플 팔이 몇 번이나 `trade` 를 냈는지가 결정 계층이 신호에 반응하는지에
    대한 **직접적인** 답이다 — 가중치 거리로는 안 보인다."""
    nd = report["null_decisions"]
    assert sum(nd.values()) == report["null"]["n_permutations"]
    assert set(nd) <= {"trade", "hold", "undetermined", "None"}
    assert report["real_decision"] in ("trade", "hold", "undetermined")


# ══════════════════════════════════════════════════════════════════════════
# Z17 ★판단 층이 실려 있다★ — S1~S5 를 닫는다
# ══════════════════════════════════════════════════════════════════════════
def test_each_arm_reports_a_decision_not_only_weights(report):
    """셔플해도 판단이 같다면 결정 계층이 신호에 무등감하다 — 가중치로는 안 보인다."""
    for arm, blk in report["arms"].items():
        assert blk["decision"]["decision"] in ("trade", "hold", "undetermined"), arm
        assert "turnover_pct" in blk["decision"]
        assert "n_outside_band" in blk["decision"]
    assert set(report["arm_decisions"]) == set(report["arms"])


def test_the_off_arm_really_has_no_views(report):
    assert report["arms"][cvc.ARM_OFF]["n_views"] == 0
    assert report["arms"][cvc.ARM_OFF]["weights"]["w_l1_vs_off"] == 0.0
    assert report["arms"][cvc.ARM_ON]["n_views"] == len(NAMES)


# ══════════════════════════════════════════════════════════════════════════
# 널의 정직성
# ══════════════════════════════════════════════════════════════════════════
def test_the_null_says_how_many_permutations_were_even_possible(report):
    """★5개뿐인 널에서 나온 분위와 40,319개에서 나온 분위는 뜻이 다르다★"""
    n = report["null"]
    assert n["n_distinct_possible"] == 23          # 4! − 1
    assert n["enumerated"] is True                 # 23 ≤ 200 이므로 전수
    assert n["n_permutations"] == 23


def test_a_large_universe_is_sampled_and_the_report_says_so():
    names = [f"n{i}" for i in range(8)]
    views = [{"assets": [n], "direction": 1 if i % 2 else -1,
              "magnitude_pct": 2.0 + i, "confidence": 20.0 + 5 * i,
              "source": "company_valuation", "is_mock": True} for i, n in enumerate(names)]
    rep = run(names, _R(cols=8), views, n_perm=30, seed=2)
    assert rep["null"]["enumerated"] is False
    assert rep["null"]["n_permutations"] == 30
    assert rep["null"]["n_distinct_possible"] == 40319


def test_the_same_seed_reproduces_the_report():
    a = run(NAMES, _R(), _views(), n_perm=200, seed=11)
    b = run(NAMES, _R(), _views(), n_perm=200, seed=11)
    assert a["percentile_of_real"] == b["percentile_of_real"]
    assert a["null"]["stats"] == b["null"]["stats"]
