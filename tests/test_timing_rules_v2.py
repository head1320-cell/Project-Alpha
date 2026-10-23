"""TimingRuleSetV2 — 3-상태 시그널 + 조합 방식 (AAS Phase 7).

★이 파일의 두 축★
1. **보수적 폴백을 타입으로 강제한다.** 스펙 §3.3: "결측이 참으로 떨어질 수 있는 boolean 이
   있으면 안 된다." 기존 `passes()` 는 bool 을 돌려주며 None→False 로 *동작은* 보수적이지만,
   타입이 그 버그를 허용한다. SignalState 는 risk_on|risk_off|unavailable 3-상태이고
   **조합에서 unavailable 은 risk_off 로 떨어진다.**
2. **defense_first 부호 역전.** 이 팩터는 값이 **음수일 때 위험-온**이고, 그 사실이 함수가
   아니라 **카탈로그 메타데이터(default_direction="below")** 에 들어 있다. direction 을 읽지
   않는 평가기는 신호를 조용히 뒤집는다 — 에러도 안 난다. 이 단계에서 가장 값비싼 테스트다.

네트워크 0: 가격 팩터는 값을 직접 주입, 매크로 팩터는 pit_macro._http_get 을 스텁한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine import timing_rules_v2 as v2  # noqa: E402
from src.engine.timing_rules_v2 import SignalState  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 3-상태 판정 — 임계·방향·결측
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value,threshold,direction,expected", [
    (0.7, 0.5, "above", SignalState.RISK_ON),
    (0.3, 0.5, "above", SignalState.RISK_OFF),
    (0.5, 0.5, "above", SignalState.RISK_OFF),      # 경계는 통과가 아니다(> 비교)
    (-0.2, 0.0, "below", SignalState.RISK_ON),      # ★역방향★
    (0.2, 0.0, "below", SignalState.RISK_OFF),
    (None, 0.5, "above", SignalState.UNAVAILABLE),  # 결측은 risk_off 가 아니라 unavailable
    (None, 0.0, "below", SignalState.UNAVAILABLE),
])
def test_state_from_value(value, threshold, direction, expected):
    assert v2.state_from_value(value, threshold, direction) is expected


def test_unavailable_is_distinct_from_risk_off():
    """결측과 '판정상 위험-오프' 는 다른 사실이다 — 합치면 이유를 알 수 없게 된다."""
    missing = v2.state_from_value(None, 0.5, "above")
    genuine = v2.state_from_value(0.1, 0.5, "above")
    assert missing is SignalState.UNAVAILABLE
    assert genuine is SignalState.RISK_OFF
    assert missing is not genuine


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ★보수적 폴백★ — 어떤 조합에서도 결측이 risk_on 을 만들 수 없다
# ═══════════════════════════════════════════════════════════════════════════════
ALL_METHODS = ["all", "any", "k_of_n", "weighted", "continuous"]


@pytest.mark.parametrize("method", ALL_METHODS)
def test_all_unavailable_never_yields_risk_on(method):
    states = [SignalState.UNAVAILABLE] * 3
    out = v2.combine(states, method=method, k=1)
    assert out.state is not SignalState.RISK_ON, (
        f"{method}: 전부 결측인데 위험-온이 나왔다 — 보수적 폴백 위반"
    )


@pytest.mark.parametrize("method", ALL_METHODS)
def test_unavailable_mixed_in_never_upgrades_the_result(method):
    """결측을 섞었을 때 결과가 **더 좋아지면** 안 된다(결측이 긍정으로 읽힌 것)."""
    base = [SignalState.RISK_ON, SignalState.RISK_OFF]
    with_missing = [*base, SignalState.UNAVAILABLE]
    a = v2.combine(base, method=method, k=1)
    b = v2.combine(with_missing, method=method, k=1)
    if a.state is not SignalState.RISK_ON:
        assert b.state is not SignalState.RISK_ON
    # 연속 노출은 결측이 섞이면 절대 커지지 않아야 한다
    assert b.exposure <= a.exposure + 1e-9


def test_unavailable_resolves_to_risk_off_in_composition():
    """스펙 §3.3: 조합에서 unavailable 은 risk_off 로 떨어진다."""
    out = v2.combine([SignalState.RISK_ON, SignalState.UNAVAILABLE], method="all", k=2)
    assert out.state is SignalState.RISK_OFF
    assert "unavailable" in out.explanation.lower() or "결측" in out.explanation


def test_explanation_names_the_missing_count():
    out = v2.combine([SignalState.UNAVAILABLE, SignalState.RISK_ON], method="k_of_n", k=1)
    assert out.unavailable_count == 1
    assert out.explanation, "설명이 비어 있으면 왜 그 판정인지 알 수 없다"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 조합 방식
# ═══════════════════════════════════════════════════════════════════════════════
def test_all_requires_every_signal():
    on3 = [SignalState.RISK_ON] * 3
    assert v2.combine(on3, method="all").state is SignalState.RISK_ON
    assert v2.combine([*on3[:2], SignalState.RISK_OFF], method="all").state is SignalState.RISK_OFF


def test_any_requires_one():
    assert v2.combine([SignalState.RISK_OFF, SignalState.RISK_ON], method="any").state is SignalState.RISK_ON
    assert v2.combine([SignalState.RISK_OFF] * 2, method="any").state is SignalState.RISK_OFF


@pytest.mark.parametrize("k,on,expected", [
    (2, 2, SignalState.RISK_ON),     # 정확히 k — 통과
    (2, 1, SignalState.RISK_OFF),    # k 미달
    (3, 3, SignalState.RISK_ON),
    (1, 0, SignalState.RISK_OFF),
])
def test_k_of_n_boundaries(k, on, expected):
    states = [SignalState.RISK_ON] * on + [SignalState.RISK_OFF] * (3 - on)
    assert v2.combine(states, method="k_of_n", k=k).state is expected


def test_weighted_uses_weights_not_counts():
    """가중 조합 — 개수가 아니라 무게로 판정한다."""
    states = [SignalState.RISK_ON, SignalState.RISK_OFF, SignalState.RISK_OFF]
    heavy_on = v2.combine(states, method="weighted", weights=[0.8, 0.1, 0.1])
    heavy_off = v2.combine(states, method="weighted", weights=[0.2, 0.4, 0.4])
    assert heavy_on.state is SignalState.RISK_ON
    assert heavy_off.state is SignalState.RISK_OFF


def test_continuous_exposure_is_the_risk_on_fraction():
    out = v2.combine([SignalState.RISK_ON] * 3 + [SignalState.RISK_OFF], method="continuous")
    assert out.exposure == pytest.approx(0.75)
    assert 0.0 <= out.exposure <= 1.0


def test_exposure_is_bounded_for_every_method():
    for m in ALL_METHODS:
        for states in ([SignalState.RISK_ON] * 3, [SignalState.RISK_OFF] * 3,
                       [SignalState.UNAVAILABLE] * 3):
            e = v2.combine(states, method=m, k=1).exposure
            assert 0.0 <= e <= 1.0, f"{m}: 노출 {e} 가 범위를 벗어났다"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. regime_conditioned — Phase 7b 에서 구현됐다. 가드는 걷혔고, 거부 조건이 바뀌었다.
#    (Phase 7 에서는 "7b 에서 온다" 며 거부했다 — 그 테스트를 여기서 함께 갱신한다.
#     능력이 생긴 커밋에서 가드와 그 테스트가 같이 사라져야 기록이 어긋나지 않는다.)
# ═══════════════════════════════════════════════════════════════════════════════
def test_regime_conditioned_is_declared_and_now_implemented():
    assert "regime_conditioned" in v2.COMBINATION_METHODS, "스펙에 있는 방식을 enum 에서 빼면 안 된다"
    assert "regime_conditioned" in v2._IMPLEMENTED


def test_regime_conditioned_still_refuses_without_a_macro_overlay():
    """★매크로 없이 매크로 조건부 조합은 성립하지 않는다★ 다른 방식으로 대치하지 않는다.

    거부 자체는 Phase 7 과 같은 정신이다 — 요청하지 않은 조합으로 판단이 내려지면 안 된다.
    달라진 것은 사유뿐이다: "아직 구현 안 됨" → "오버레이가 없음".
    """
    with pytest.raises(ValueError) as ei:
        v2.combine([SignalState.RISK_ON], method="regime_conditioned")
    assert "오버레이" in str(ei.value)


def test_unknown_method_is_rejected_not_defaulted():
    with pytest.raises(ValueError):
        v2.combine([SignalState.RISK_ON], method="mystery_method")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ★defense_first 부호 역전★ — 카탈로그 direction 을 읽어야 한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_defense_first_negative_value_is_risk_on():
    """방어자산이 현금보다 약하면(음수) 위험-온. 카탈로그가 direction="below" 로 규정한다."""
    st = v2.state_for_factor("defense_first", value=-0.15)
    assert st is SignalState.RISK_ON, (
        "음수 defense_first 를 위험-오프로 읽었다 — 카탈로그 direction 을 무시한 것이다"
    )


def test_defense_first_positive_value_is_risk_off():
    assert v2.state_for_factor("defense_first", value=0.15) is SignalState.RISK_OFF


def test_a_normal_above_factor_keeps_its_direction():
    """역전은 defense_first 에만 적용된다 — 전체를 뒤집으면 안 된다."""
    assert v2.state_for_factor("avg_abs_momentum", value=0.8) is SignalState.RISK_ON
    assert v2.state_for_factor("avg_abs_momentum", value=0.1) is SignalState.RISK_OFF


def test_factor_direction_comes_from_the_catalogue_not_a_hardcoded_list():
    """카탈로그 메타데이터가 단일 진실이어야 한다 — 하드코딩 목록이면 새 팩터에서 어긋난다."""
    from src.engine.timing_factors import CATALOG_BY_ID
    for fid in ("defense_first", "avg_abs_momentum"):
        assert v2.direction_for(fid) == CATALOG_BY_ID[fid]["default_direction"]


def test_unknown_factor_direction_defaults_conservatively():
    """모르는 팩터는 추측하지 않는다 — 값이 있어도 unavailable."""
    assert v2.state_for_factor("no_such_factor", value=0.9) is SignalState.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 히스테리시스 · 쿨다운
# ═══════════════════════════════════════════════════════════════════════════════
def test_hysteresis_holds_the_previous_state_inside_the_band():
    """임계 근방에서 신호가 떨리는 것을 막는다. 밴드 안이면 이전 상태를 유지."""
    # 임계 0.5, 밴드 0.05 → 0.47 은 밴드 안이므로 직전 risk_on 을 유지
    st = v2.state_from_value(0.47, 0.5, "above", hysteresis=0.05, previous=SignalState.RISK_ON)
    assert st is SignalState.RISK_ON
    # 직전이 risk_off 였다면 그대로 risk_off
    st2 = v2.state_from_value(0.47, 0.5, "above", hysteresis=0.05, previous=SignalState.RISK_OFF)
    assert st2 is SignalState.RISK_OFF


def test_hysteresis_does_not_rescue_a_clear_miss():
    """밴드 밖이면 히스테리시스가 개입하지 않는다."""
    st = v2.state_from_value(0.20, 0.5, "above", hysteresis=0.05, previous=SignalState.RISK_ON)
    assert st is SignalState.RISK_OFF


def test_hysteresis_never_rescues_unavailable():
    """★결측은 히스테리시스로도 살아나지 않는다★ — 직전이 risk_on 이어도."""
    st = v2.state_from_value(None, 0.5, "above", hysteresis=0.05, previous=SignalState.RISK_ON)
    assert st is SignalState.UNAVAILABLE


def test_cooldown_blocks_a_flip_that_is_too_soon():
    """전환 직후 재전환을 막는다 — 거래비용을 태우는 휩쏘 방지."""
    # 쿨다운 3일, 전환 후 1일 → 유지
    assert v2.apply_cooldown(SignalState.RISK_OFF, previous=SignalState.RISK_ON,
                             bars_since_flip=1, cooldown=3) is SignalState.RISK_ON
    # 3일 경과 → 전환 허용
    assert v2.apply_cooldown(SignalState.RISK_OFF, previous=SignalState.RISK_ON,
                             bars_since_flip=3, cooldown=3) is SignalState.RISK_OFF


def test_cooldown_is_symmetric_across_signal_flips():
    """쿨다운은 양방향으로 걸린다 — 진입만 늦추면 이탈 쪽 왕복 비용은 그대로 태운다."""
    # 위험-오프 → 위험-온 도 같은 규칙으로 지연된다
    assert v2.apply_cooldown(SignalState.RISK_ON, previous=SignalState.RISK_OFF,
                             bars_since_flip=1, cooldown=3) is SignalState.RISK_OFF
    assert v2.apply_cooldown(SignalState.RISK_ON, previous=SignalState.RISK_OFF,
                             bars_since_flip=3, cooldown=3) is SignalState.RISK_ON


def test_cooldown_never_blocks_a_move_to_risk_off_on_missing_data():
    """★안전 방향으로 가는 전환은 쿨다운이 막지 않는다★ — 데이터가 없어졌으면 즉시 내려간다."""
    out = v2.apply_cooldown(SignalState.UNAVAILABLE, previous=SignalState.RISK_ON,
                            bars_since_flip=0, cooldown=10)
    assert out is not SignalState.RISK_ON, "결측으로의 전환을 쿨다운이 막으면 위험에 노출된 채 남는다"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 빈도 정렬 — 팩터 샘플링이 리밸런싱보다 잦으면 경고 대상
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("factor_freq,rebalance,conflict", [
    ("day", "month_end", True),     # 일간 신호를 월말에만 반영 → 신호 대부분 버려진다
    ("month", "month_end", False),
    ("month", "day", True),         # 월간 신호를 일간 리밸런싱 → 같은 값 반복
    ("day", "day", False),
])
def test_frequency_conflict_detection(factor_freq, rebalance, conflict):
    assert v2.frequency_conflicts(factor_freq, rebalance) is conflict
