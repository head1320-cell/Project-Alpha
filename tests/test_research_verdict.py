"""판정 어휘 5분류 ★"유의하지 않다" ≠ "효과가 없다"★ (A2)
==============================================================================
M1~M5 가 정확히 이 구멍에 빠졌다. `verdict.passed` 가 불리언 하나뿐이라
"SPA p=0.094 로 불통과" 가 리포트에서 "효과가 없다" 와 **구별되지 않았다**.
양성 통제에서 심은 효과 1× 의 검출률이 40% 였다는 사실 — 즉 관문이 애초에
찾을 힘이 없었다는 사실 — 을 담을 자리가 없었다.

★만다트 §4 의 계약★ `p > 0.05` 만으로는 결코 `evidence_of_no_effect` 가 되지
않는다. **입증된 검정력**이 있어야 한다. 아래 짝 테스트가 그것을 건다.

★판정은 규칙이지 데이터가 아니다★ 그래서 순수 함수를 직접 검사한다 — 데이터를
만들어 규칙을 확인하면 픽스처의 우연을 계약으로 착각한다(S6 에서 치른 값).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.research_verdict import (  # noqa: E402
    ALL_VERDICTS,
    DEFAULT_TARGET_POWER,
    VERDICT_EVIDENCE_OF_NO_EFFECT,
    VERDICT_INCONCLUSIVE,
    VERDICT_NO_EVIDENCE,
    VERDICT_POSITIVE,
    VERDICT_UNDERPOWERED,
    classify,
    require_power_fields,
)


# ══════════════════════════════════════════════════════════════════════════
# 어휘 자체
# ══════════════════════════════════════════════════════════════════════════
def test_the_vocabulary_has_exactly_five_classes():
    """★다섯이다★ — 불리언 하나로 되돌아가는 것을 막는다."""
    assert set(ALL_VERDICTS) == {
        VERDICT_NO_EVIDENCE, VERDICT_UNDERPOWERED, VERDICT_INCONCLUSIVE,
        VERDICT_EVIDENCE_OF_NO_EFFECT, VERDICT_POSITIVE,
    }
    assert len(ALL_VERDICTS) == 5


def test_every_classification_returns_a_known_verdict():
    for null_outside in (True, False, None):
        for spa_ok in (True, False, None):
            for power in (None, 0.0, 0.5, 1.0):
                v = classify(null_outside=null_outside, spa_ok=spa_ok, power=power)
                assert v["verdict"] in ALL_VERDICTS
                assert v["why"], v


# ══════════════════════════════════════════════════════════════════════════
# ★§4 — 불유의는 효과 없음이 아니다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("power", [None, 0.0, 0.10, 0.40, 0.79])
def test_a_non_significant_result_is_not_evidence_of_no_effect_without_power(power):
    """★만다트 §4 의 계약★

    관문을 못 넘었다는 것과 효과가 없다는 것은 다른 진술이다. 검정력이 모자라면
    **찾을 힘이 없었다**는 뜻이지 없다는 뜻이 아니다.
    """
    v = classify(null_outside=False, spa_ok=False, power=power)
    assert v["verdict"] != VERDICT_EVIDENCE_OF_NO_EFFECT
    assert v["verdict"] in (VERDICT_UNDERPOWERED, VERDICT_NO_EVIDENCE)


def test_a_non_significant_result_with_demonstrated_power_is_evidence_of_no_effect():
    """★짝★ — 언제나 `underpowered` 를 내는 구현을 배제한다."""
    v = classify(null_outside=False, spa_ok=False, power=0.95)
    assert v["verdict"] == VERDICT_EVIDENCE_OF_NO_EFFECT


def test_the_target_power_is_a_declared_convention_not_a_measurement():
    """★같은 검정력, 다른 목표 → 다른 판정★ 그것이 "관례" 라는 뜻이다."""
    strict = classify(null_outside=False, spa_ok=False, power=0.85)
    loose = classify(null_outside=False, spa_ok=False, power=0.85,
                     target_power=0.99)
    assert strict["verdict"] == VERDICT_EVIDENCE_OF_NO_EFFECT
    assert loose["verdict"] == VERDICT_UNDERPOWERED
    assert strict["convention"] is True
    assert DEFAULT_TARGET_POWER == 0.80


def test_the_boundary_is_inclusive_at_the_target():
    """★경계를 못 박는다★ — 목표에 **도달**하면 충분하다."""
    assert classify(null_outside=False, spa_ok=False,
                    power=0.80)["verdict"] == VERDICT_EVIDENCE_OF_NO_EFFECT
    assert classify(null_outside=False, spa_ok=False,
                    power=0.7999)["verdict"] == VERDICT_UNDERPOWERED


# ══════════════════════════════════════════════════════════════════════════
# 나머지 네 분류
# ══════════════════════════════════════════════════════════════════════════
def test_both_gates_passed_is_positive():
    v = classify(null_outside=True, spa_ok=True, power=0.40)
    assert v["verdict"] == VERDICT_POSITIVE
    assert v["passed"] is True


def test_a_positive_does_not_need_power_to_stand():
    """★검정력은 **못 찾은 것**을 읽을 때 필요하다★ — 찾았으면 찾은 것이다."""
    v = classify(null_outside=True, spa_ok=True, power=None)
    assert v["verdict"] == VERDICT_POSITIVE


@pytest.mark.parametrize("null_outside,spa_ok", [(True, False), (False, True)])
def test_exactly_one_gate_is_inconclusive(null_outside, spa_ok):
    """★엇갈리면 결론이 아니다★ M1~M5 가 정확히 이랬다(널 밖 · SPA 미달)."""
    v = classify(null_outside=null_outside, spa_ok=spa_ok, power=0.95)
    assert v["verdict"] == VERDICT_INCONCLUSIVE
    assert v["passed"] is False


@pytest.mark.parametrize("null_outside,spa_ok", [
    (None, True), (True, None), (None, None), (None, False), (False, None)])
def test_an_unrun_gate_is_no_evidence(null_outside, spa_ok):
    """★미상 ≠ 아니오★ 관문을 못 돌린 것은 판정이 아니다."""
    v = classify(null_outside=null_outside, spa_ok=spa_ok, power=0.95)
    assert v["verdict"] == VERDICT_NO_EVIDENCE
    assert v["passed"] is False


def test_unknown_power_on_a_failed_gate_is_no_evidence_not_underpowered():
    """★모르는 검정력은 '낮은 검정력' 이 아니다★ — 둘은 다른 진술이다."""
    assert classify(null_outside=False, spa_ok=False,
                    power=None)["verdict"] == VERDICT_NO_EVIDENCE
    assert classify(null_outside=False, spa_ok=False,
                    power=0.10)["verdict"] == VERDICT_UNDERPOWERED


def test_passed_is_true_only_for_positive():
    """★기존 불리언과의 다리★ — `passed` 는 `positive` 와 동치다."""
    for null_outside in (True, False, None):
        for spa_ok in (True, False, None):
            v = classify(null_outside=null_outside, spa_ok=spa_ok, power=0.95)
            assert v["passed"] is (v["verdict"] == VERDICT_POSITIVE)


# ══════════════════════════════════════════════════════════════════════════
# ★리포트에 검정력이 없으면 그 리포트는 불완전하다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_report_without_the_power_fields_is_incomplete():
    missing = require_power_fields({"mde": 2.0})
    assert any("power" in m for m in missing)
    assert any("n_eff" in m for m in missing)


def test_a_complete_report_reports_nothing_missing():
    """★짝★ — 언제나 불평하는 구현을 배제한다."""
    assert require_power_fields({"mde": 2.0, "power": 0.4, "n_eff": 129.2}) == []


def test_an_unknown_field_needs_a_reason():
    """★`None` 은 사유와 함께 적는다★ — 사유 없는 미상은 침묵 폴백이다."""
    assert require_power_fields({"mde": None, "power": 0.4, "n_eff": 1.0})
    assert require_power_fields(
        {"mde": None, "mde_reason": "탐색 범위에서 목표에 도달하지 못했습니다",
         "power": 0.4, "n_eff": 1.0}) == []
    assert require_power_fields(
        {"mde": None, "power": 0.4, "n_eff": 1.0,
         "reasons": {"mde": "널 표본이 없습니다"}}) == []


def test_an_empty_reason_does_not_count():
    """★빈 문자열은 사유가 아니다★ `{}` 나 `""` 로 관문을 통과시키지 않는다."""
    assert require_power_fields(
        {"mde": None, "mde_reason": "   ", "power": 0.4, "n_eff": 1.0})
