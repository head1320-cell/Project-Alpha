"""Phase 7b — 매크로 오버레이 시맨틱 (스펙 §8) + `regime_conditioned`.

스펙이 요구하는 세 가지의 백엔드 절반:
  · **선택적 오버레이** — 매크로는 룰셋을 조정할 뿐, 조용히 대체하지 않는다. 끌 수 있다.
  · **3자 비교** — 기준(타이밍 없음) vs 타이밍만 vs 타이밍+매크로.
  · **평문 충돌 설명** — 모든 위험-온/오프 판단이 이유를 갖는다.

★오버레이는 위험을 **키우지 못한다**★
이 파일에서 가장 중요한 불변식이다. 매크로가 좋아 보인다고 노출을 올려 주면, 매크로 모델이
틀렸을 때 손실이 증폭된다. 오버레이는 줄이기만 한다(one-way). 그래서 "오버레이를 켜면
노출이 늘어난다" 는 테스트는 없고, 늘어나지 않는지를 검증한다.
"""
import pytest

from src.data.pit_macro import DataStatus, ResearchUsage
from src.engine import macro_overlay as mo
from src.engine import timing_rules_v2 as v2
from src.engine.timing_rules_v2 import SignalState

ON, OFF, NA = SignalState.RISK_ON, SignalState.RISK_OFF, SignalState.UNAVAILABLE


def overlay(**kw):
    base = dict(regime="Goldilocks", recommended_mode="risk_on", confidence=0.9,
                stress_score=0.1, data_status=DataStatus.REAL,
                research_usage=ResearchUsage.BACKTEST_ELIGIBLE)
    base.update(kw)
    return mo.MacroOverlay(**base)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. regime_conditioned — Phase 7 의 거부 가드를 걷어낸다
# ═══════════════════════════════════════════════════════════════════════════════
def test_regime_conditioned_now_works_with_an_overlay():
    out = v2.combine([ON, ON], method="regime_conditioned", overlay=overlay())
    assert out.state is SignalState.RISK_ON
    assert out.method == "regime_conditioned"


def test_regime_conditioned_without_an_overlay_is_refused():
    """★매크로 없이 매크로 조건부 조합을 하면 안 된다★ 조용히 다른 방식으로 대치하지 않는다."""
    with pytest.raises(ValueError) as e:
        v2.combine([ON, ON], method="regime_conditioned")
    assert "오버레이" in str(e.value) or "overlay" in str(e.value)


def test_regime_conditioned_is_still_in_the_declared_methods():
    assert "regime_conditioned" in v2.COMBINATION_METHODS


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ★오버레이는 위험을 키우지 못한다★ (one-way)
# ═══════════════════════════════════════════════════════════════════════════════
def test_overlay_never_raises_exposure():
    timing_only = v2.combine([ON, OFF], method="continuous")           # 0.5
    for mode in ("risk_on", "neutral", "risk_off"):
        withm = v2.combine([ON, OFF], method="continuous",
                           overlay=overlay(recommended_mode=mode))
        assert withm.exposure <= timing_only.exposure + 1e-9, (
            f"매크로({mode})가 노출을 올렸다 — 오버레이는 줄이기만 해야 한다")


def test_macro_risk_off_forces_risk_off():
    out = v2.combine([ON, ON], method="all", overlay=overlay(recommended_mode="risk_off"))
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0


def test_low_confidence_shrinks_exposure_but_does_not_flip_to_on():
    hi = v2.combine([ON, ON], method="continuous", overlay=overlay(confidence=1.0))
    lo = v2.combine([ON, ON], method="continuous", overlay=overlay(confidence=0.2))
    assert lo.exposure < hi.exposure
    assert lo.exposure >= 0.0


def test_high_stress_shrinks_exposure():
    calm = v2.combine([ON, ON], method="continuous", overlay=overlay(stress_score=0.0))
    hot = v2.combine([ON, ON], method="continuous", overlay=overlay(stress_score=0.95))
    assert hot.exposure < calm.exposure


def test_unavailable_macro_does_not_upgrade_anything():
    """매크로가 결측이면 아무것도 좋게 만들지 않는다 — 타이밍 결과를 그대로 두거나 줄인다."""
    timing_only = v2.combine([ON, OFF], method="continuous")
    out = v2.combine([ON, OFF], method="continuous",
                     overlay=overlay(data_status=DataStatus.UNAVAILABLE,
                                     research_usage=ResearchUsage.UNAVAILABLE))
    assert out.exposure <= timing_only.exposure + 1e-9
    assert out.state is not SignalState.RISK_ON or timing_only.state is SignalState.RISK_ON


def test_timing_risk_off_stays_off_even_with_a_rosy_macro():
    """★매크로가 좋아도 타이밍이 오프면 오프다★ 오버레이는 대체가 아니다."""
    out = v2.combine([OFF, OFF], method="all", overlay=overlay(recommended_mode="risk_on"))
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 끌 수 있어야 한다 — "조용한 오버라이드" 가 아니라는 것의 실질
# ═══════════════════════════════════════════════════════════════════════════════
def test_disabled_overlay_equals_timing_only():
    timing_only = v2.combine([ON, OFF], method="continuous")
    off = v2.combine([ON, OFF], method="continuous",
                     overlay=overlay(recommended_mode="risk_off", enabled=False))
    assert off.exposure == timing_only.exposure
    assert off.state is timing_only.state


def test_disabling_the_overlay_visibly_changes_the_result():
    """게이트 문구 그대로 — 끄면 결과가 눈에 보이게 달라져야 의미가 있다."""
    on = v2.combine([ON, ON], method="continuous", overlay=overlay(recommended_mode="risk_off"))
    off = v2.combine([ON, ON], method="continuous",
                     overlay=overlay(recommended_mode="risk_off", enabled=False))
    assert on.state is not off.state or on.exposure != off.exposure


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 3자 비교 — 기준 vs 타이밍만 vs 타이밍+매크로
# ═══════════════════════════════════════════════════════════════════════════════
def test_three_way_returns_all_three_legs():
    r = mo.three_way([ON, OFF], method="continuous", overlay=overlay())
    assert set(r) == {"baseline", "timing_only", "timing_macro"}


def test_baseline_is_always_fully_invested():
    """기준은 '타이밍을 하지 않았다면' 이다 — 항상 노출 100%."""
    r = mo.three_way([OFF, OFF], method="all", overlay=overlay(recommended_mode="risk_off"))
    assert r["baseline"].exposure == 1.0
    assert r["baseline"].state is SignalState.RISK_ON


def test_three_way_legs_are_ordered_by_conservatism():
    """기준 ≥ 타이밍만 ≥ 타이밍+매크로 — 오버레이가 one-way 이므로 항상 성립한다."""
    r = mo.three_way([ON, OFF], method="continuous",
                     overlay=overlay(recommended_mode="neutral", confidence=0.5))
    assert r["baseline"].exposure >= r["timing_only"].exposure >= r["timing_macro"].exposure


def test_three_way_without_overlay_marks_macro_leg_unavailable():
    """매크로가 없으면 세 번째 다리를 지어내지 않는다."""
    r = mo.three_way([ON, OFF], method="continuous", overlay=None)
    assert r["timing_macro"].state is SignalState.UNAVAILABLE
    assert "매크로" in r["timing_macro"].explanation


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 평문 충돌 설명 — 모든 판단이 이유를 갖는다
# ═══════════════════════════════════════════════════════════════════════════════
def test_conflict_is_explained_when_timing_and_macro_disagree():
    text = mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(recommended_mode="risk_off", stress_score=0.8))
    assert text, "충돌인데 설명이 비어 있다"
    assert "위험-온" in text and ("매크로" in text or "국면" in text)


def test_no_conflict_when_both_agree():
    assert mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(recommended_mode="risk_on")) is None


def test_explanation_names_the_regime_and_numbers():
    text = mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(regime="Stagflation", recommended_mode="risk_off",
                                           confidence=0.3, stress_score=0.77))
    assert "Stagflation" in text
    assert "0.3" in text or "30" in text          # 신뢰도를 숫자로 밝힌다
    assert "0.77" in text or "77" in text         # 스트레스도 숫자로


def test_disabled_overlay_reports_no_conflict():
    """꺼진 오버레이는 판단에 관여하지 않으므로 충돌도 없다."""
    assert mo.conflict_explanation(
        v2.combine([ON, ON], method="all"),
        overlay(recommended_mode="risk_off", enabled=False)) is None


def test_composite_explanation_mentions_the_overlay_when_applied():
    out = v2.combine([ON, ON], method="continuous", overlay=overlay(recommended_mode="neutral"))
    assert "매크로" in out.explanation, "오버레이가 적용됐는데 설명에 흔적이 없다"
