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
    base = dict(regime="Goldilocks", recommended_mode="NORMAL", confidence=0.9,
                stress_score=10.0, data_status=DataStatus.REAL,
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
    for mode in ("NORMAL", "CAUTIOUS", "DEFENSIVE"):
        withm = v2.combine([ON, OFF], method="continuous",
                           overlay=overlay(recommended_mode=mode))
        assert withm.exposure <= timing_only.exposure + 1e-9, (
            f"매크로({mode})가 노출을 올렸다 — 오버레이는 줄이기만 해야 한다")


def test_macro_risk_off_forces_risk_off():
    out = v2.combine([ON, ON], method="all", overlay=overlay(recommended_mode="DEFENSIVE"))
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0


def test_low_confidence_shrinks_exposure_but_does_not_flip_to_on():
    hi = v2.combine([ON, ON], method="continuous", overlay=overlay(confidence=1.0))
    lo = v2.combine([ON, ON], method="continuous", overlay=overlay(confidence=0.2))
    assert lo.exposure < hi.exposure
    assert lo.exposure >= 0.0


def test_high_stress_shrinks_exposure():
    calm = v2.combine([ON, ON], method="continuous", overlay=overlay(stress_score=0.0))
    hot = v2.combine([ON, ON], method="continuous", overlay=overlay(stress_score=95.0))
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
    out = v2.combine([OFF, OFF], method="all", overlay=overlay(recommended_mode="NORMAL"))
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 끌 수 있어야 한다 — "조용한 오버라이드" 가 아니라는 것의 실질
# ═══════════════════════════════════════════════════════════════════════════════
def test_disabled_overlay_equals_timing_only():
    timing_only = v2.combine([ON, OFF], method="continuous")
    off = v2.combine([ON, OFF], method="continuous",
                     overlay=overlay(recommended_mode="DEFENSIVE", enabled=False))
    assert off.exposure == timing_only.exposure
    assert off.state is timing_only.state


def test_disabling_the_overlay_visibly_changes_the_result():
    """게이트 문구 그대로 — 끄면 결과가 눈에 보이게 달라져야 의미가 있다."""
    on = v2.combine([ON, ON], method="continuous", overlay=overlay(recommended_mode="DEFENSIVE"))
    off = v2.combine([ON, ON], method="continuous",
                     overlay=overlay(recommended_mode="DEFENSIVE", enabled=False))
    assert on.state is not off.state or on.exposure != off.exposure


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 3자 비교 — 기준 vs 타이밍만 vs 타이밍+매크로
# ═══════════════════════════════════════════════════════════════════════════════
def test_three_way_returns_all_three_legs():
    r = mo.three_way([ON, OFF], method="continuous", overlay=overlay())
    assert set(r) == {"baseline", "timing_only", "timing_macro"}


def test_baseline_is_always_fully_invested():
    """기준은 '타이밍을 하지 않았다면' 이다 — 항상 노출 100%."""
    r = mo.three_way([OFF, OFF], method="all", overlay=overlay(recommended_mode="DEFENSIVE"))
    assert r["baseline"].exposure == 1.0
    assert r["baseline"].state is SignalState.RISK_ON


def test_three_way_legs_are_ordered_by_conservatism():
    """기준 ≥ 타이밍만 ≥ 타이밍+매크로 — 오버레이가 one-way 이므로 항상 성립한다."""
    r = mo.three_way([ON, OFF], method="continuous",
                     overlay=overlay(recommended_mode="CAUTIOUS", confidence=0.5))
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
                                   overlay(recommended_mode="DEFENSIVE", stress_score=80.0))
    assert text, "충돌인데 설명이 비어 있다"
    assert "위험-온" in text and ("매크로" in text or "국면" in text)


def test_no_conflict_when_both_agree():
    assert mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(recommended_mode="NORMAL")) is None


def test_explanation_names_the_regime_and_numbers():
    text = mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(regime="Stagflation", recommended_mode="DEFENSIVE",
                                           confidence=0.3, stress_score=77.0))
    assert "Stagflation" in text
    assert "0.3" in text or "30" in text          # 신뢰도를 숫자로 밝힌다
    assert "0.77" in text or "77" in text         # 스트레스도 숫자로


def test_disabled_overlay_reports_no_conflict():
    """꺼진 오버레이는 판단에 관여하지 않으므로 충돌도 없다."""
    assert mo.conflict_explanation(
        v2.combine([ON, ON], method="all"),
        overlay(recommended_mode="DEFENSIVE", enabled=False)) is None


def test_composite_explanation_mentions_the_overlay_when_applied():
    out = v2.combine([ON, ON], method="continuous", overlay=overlay(recommended_mode="CAUTIOUS"))
    assert "매크로" in out.explanation, "오버레이가 적용됐는데 설명에 흔적이 없다"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ★어휘와 단위 — 실제 생산자에 맞는가★ (Phase 7b 배선에서 드러난 결함의 회귀 테스트)
#
# 위의 테스트 20개는 전부 통과하고 있었다. 그런데 `MacroOverlay` 가 기대하던 어휘
# (`risk_on`/`neutral`/`risk_off`)와 단위(스트레스 0~1)는 **이 코드베이스에 없었다.**
# 테스트가 내가 지어낸 단위를 그대로 먹여 줬기 때문에 자기 일관적으로 통과했고, 실제
# 스냅샷이 처음 흘러든 순간(3자 비교 HTTP 배선) 상한이 0.0 이 되어 모든 포트폴리오가
# 조용히 전액 위험-오프로 떨어졌다. 아래는 그 결함들을 고정한다.
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mode,expected", [
    ("NORMAL", 1.0), ("CAUTIOUS", 0.6), ("DEFENSIVE", 0.0),
    ("normal", 1.0), ("Cautious", 0.6),          # 대소문자 무관
])
def test_the_real_regime_vocabulary_is_recognized(mode, expected):
    """`regime_analyzer.RegimeState.recommended_mode` 의 실제 값들(`regime_analyzer.py:65`)."""
    assert mo.MacroOverlay(regime="X", recommended_mode=mode, confidence=1.0,
                           stress_score=0.0).mode_cap == expected


def test_stress_score_is_a_zero_to_hundred_score_not_a_fraction():
    """★실제 스냅샷의 스트레스는 51.8 같은 값이다★ 0~1 분수로 읽으면 1.0 으로 클램프되어
    상한이 0 이 되고, 매크로가 언제나 전액 방어를 지시하게 된다(실제로 그랬다)."""
    ov = overlay(recommended_mode="NORMAL", confidence=1.0, stress_score=51.8)
    assert ov.exposure_cap() == pytest.approx(1.0 - 0.518, abs=1e-9)
    assert ov.exposure_cap() > 0.0, "현실적인 스트레스 값이 노출을 0 으로 만들었다"


def test_a_calm_real_snapshot_barely_trims_exposure():
    assert overlay(recommended_mode="NORMAL", confidence=1.0,
                   stress_score=5.0).exposure_cap() == pytest.approx(0.95)


def test_an_unrecognized_mode_does_not_silently_mean_full_defense():
    """★모르는 라벨은 '전액 방어하라' 는 지식이 아니다★

    `MODE_CAP.get(mode, 0.0)` 이면 어휘가 하나 바뀌는 순간 조용히 가장 강한 판단
    (노출 0)으로 번역된다 — mock 게이트 원칙과 같은 이유로 모르면 조정하지 않는다.
    """
    ov = overlay(recommended_mode="TELEPATHY")
    assert ov.mode_cap is None
    assert ov.usable is False
    assert ov.exposure_cap() == 1.0
    timing_only = v2.combine([ON, OFF], method="continuous")
    withm = v2.combine([ON, OFF], method="continuous", overlay=ov)
    assert withm.exposure == timing_only.exposure


def test_an_empty_mode_is_unusable_rather_than_defensive():
    """열이 degraded 인 DB 는 `recommended_mode` 를 None 으로 준다 → 빈 문자열로 도착한다."""
    ov = overlay(recommended_mode="")
    assert ov.usable is False and ov.exposure_cap() == 1.0


def test_normal_mode_is_not_reported_as_a_conflict():
    """`NORMAL` 은 아무 제약도 걸지 않는다 — 충돌로 보고하면 사용자가 없는 갈등을 본다.

    기준을 "라벨이 risk_on 이 아니다" 로 적었을 때 정확히 이게 깨졌다.
    """
    assert mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(recommended_mode="NORMAL")) is None


def test_unrecognized_mode_is_not_reported_as_a_conflict_either():
    assert mo.conflict_explanation(v2.combine([ON, ON], method="all"),
                                   overlay(recommended_mode="???")) is None


def test_to_dict_publishes_usable_so_consumers_can_tell_missing_from_neutral():
    """`usable` 이 빠져 있으면 소비자는 '매크로를 못 읽었다' 와 '매크로가 중립이다' 를
    구별할 수 없다 — 그리고 그 상태에서 정직성 테스트가 조용히 통과했다."""
    assert overlay().to_dict()["usable"] is True
    assert overlay(recommended_mode="???").to_dict()["usable"] is False
