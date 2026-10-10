"""§3.2 `TimingFactorDefinition` 구조화 메타 (Phase 12a — 감사 A1·A2).

11a 감사가 잰 것: 정의에 9개 필드가 필요한데 **3개만** 있었고, `provenance` 는 열거형이어야
하는데 자유 텍스트 인용문이었다("Antonacci (Dual Momentum)"). 분류로 필터·그룹할 수 없었다.

★이 파일이 지키는 것은 "필드가 있다" 가 아니라 "필드가 거짓말하지 않는다" 이다★
"""
import pytest

from src.engine import timing_factors as tf
from src.engine.timing_factor_meta import (
    AVAILABILITIES,
    PROVENANCE_CLASSES,
    REQUIRED_DEFINITION_FIELDS,
    USE_MODES,
    classify,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 모든 항목이 정의 필드를 갖는다 — 감사가 잰 그 자리에서
# ═══════════════════════════════════════════════════════════════════════════════
def test_every_catalogue_entry_carries_the_definition_fields():
    """★감사는 `CATALOG_BY_ID` 항목의 키 합집합을 쟀다★ 응답에서만 붙이면 같은 결론이 다시 난다."""
    for c in tf.CATALOG_BY_ID.values():
        missing = [f for f in REQUIRED_DEFINITION_FIELDS if f not in c]
        assert not missing, f"{c['id']} 에 {missing} 가 없습니다"


@pytest.mark.parametrize("field,allowed", [
    ("provenance_class", PROVENANCE_CLASSES),
    ("use_mode", USE_MODES),
    ("availability", AVAILABILITIES),
])
def test_enum_fields_only_hold_enum_values(field, allowed):
    for c in tf.CATALOG_BY_ID.values():
        assert c[field] in allowed, f"{c['id']}.{field} = {c[field]!r} 는 열거형 밖입니다"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 분류는 인용문을 **대체하지 않는다**
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_free_text_citation_survives_classification():
    """★분류가 인용문보다 정보가 적다★ "Keller & Keuning (VAA/DAA)" 를 잃으면 안 된다."""
    vaa = tf.CATALOG_BY_ID["score_13612"]
    assert vaa["provenance"] == "Keller & Keuning (VAA/DAA)"
    assert vaa["provenance_class"] == "systrader_public"


def test_no_catalogue_entry_is_left_unclassified():
    """미분류를 기본값으로 때우면 새 팩터마다 출처가 조용히 틀려진다."""
    unmapped = [c["id"] for c in tf.CATALOG if c["provenance_class"] is None]
    assert not unmapped, f"분류되지 않은 팩터: {unmapped}"


def test_an_unknown_citation_classifies_to_none_not_a_default():
    """★이것이 위 테스트를 의미 있게 만든다★ 기본값이 있으면 위 단언은 언제나 통과한다."""
    assert classify("어떤 새로운 출처 2031") is None
    assert classify("") is None
    assert classify(None) is None


def test_institutional_series_are_not_labelled_generic():
    """FRED/ALFRED 는 공공기관 시계열이다 — '일반 기술 시그널' 로 적으면 출처를 흐린다."""
    for fid in ("financial_conditions", "curve_slope", "vix_term_structure"):
        assert tf.CATALOG_BY_ID[fid]["provenance_class"] == "institutional_public"


def test_generic_technical_families_are_not_claimed_as_authored_strategies():
    """★§6 의 correctness 요구★ 이격도·돌파류를 systrader/유료전략 계열로 적으면 안 된다."""
    for fid in ("disparity", "channel_breakout", "overnight_return"):
        assert tf.CATALOG_BY_ID[fid]["provenance_class"] == "generic_public_technical"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 유도된 값이 실제로 맞는가
# ═══════════════════════════════════════════════════════════════════════════════
def test_allowed_range_is_set_only_where_the_unit_is_really_bounded():
    """★임의의 상한을 씌우면 정상 값이 검증에서 튕긴다★ 수익률·스프레드는 경계가 없다."""
    assert tf.CATALOG_BY_ID["avg_abs_momentum"]["allowed_range"] == [0.0, 1.0]  # weight_0_1
    # 스코어차·퍼센트포인트는 열려 있다 — None 이어야지 [-100, 100] 같은 추측이면 안 된다.
    assert tf.CATALOG_BY_ID["defense_first"]["allowed_range"] is None
    assert tf.CATALOG_BY_ID["curve_slope"]["allowed_range"] is None


def test_the_revised_weekly_series_is_marked_revised():
    """NFCI 가 주간·개정이라는 사실이 ALFRED 빈티지 경로가 존재하는 **이유**다."""
    nfci = tf.CATALOG_BY_ID["financial_conditions"]
    assert nfci["revision_policy"] == "revised"
    assert "주간" in nfci["release_lag"]


def test_vix_is_not_marked_revised():
    """VIX 종가는 개정되지 않는다 — 개정된다고 적으면 없는 위험을 경고하는 셈이다."""
    assert tf.CATALOG_BY_ID["vix_term_structure"]["revision_policy"] == "not_revised"


def test_a_generic_series_factor_admits_it_cannot_answer():
    """★`indicator` 는 임의 시리즈를 받는다★ 하나로 단정하면 그 단정이 대부분 틀린다."""
    ind = tf.CATALOG_BY_ID["indicator"]
    assert ind["revision_policy"] == "series_dependent"
    assert "다름" in ind["release_lag"]


def test_continuous_sizing_factors_are_not_called_gates():
    """평균절대모멘텀은 노출 **크기**를 정한다 — gate 로 적으면 원 규칙을 잘못 말한다."""
    assert tf.CATALOG_BY_ID["avg_abs_momentum"]["use_mode"] == "sizing"
    assert tf.CATALOG_BY_ID["target_vol_size"]["use_mode"] == "sizing"
    assert tf.CATALOG_BY_ID["abs_mom"]["use_mode"] == "gate"


def test_the_failure_mode_states_the_three_state_rule():
    """실패 시 0 으로 대체하지 않는다는 것이 §3.3 의 핵심이고, 정의가 그걸 말해야 한다."""
    fm = tf.CATALOG_BY_ID["abs_mom"]["expected_failure_mode"]
    assert "unavailable" in fm
    assert "0" in fm and "대체하지 않는다" in fm


# ═══════════════════════════════════════════════════════════════════════════════
# 4. §6.1 "소스 없음" 묶음 — 보이되 켤 수 없다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_no_source_group_is_visible_in_the_catalogue():
    """★목록에서 빼면 사용자는 검토한 적조차 없게 된다★ 그건 '안 하기로 했다' 와 다르다."""
    for fid in ("vix_skew", "borrow_short_interest", "option_implied_correlation", "crowding"):
        assert fid in tf.CATALOG_BY_ID, f"{fid} 가 카탈로그에 없습니다"
        assert tf.CATALOG_BY_ID[fid]["availability"] == "unavailable"


def test_every_unavailable_factor_states_a_concrete_reason():
    """§6.1: 'concrete reason shown'. 빈 사유는 사유가 아니다."""
    for c in tf.CATALOG.__iter__():
        if c["availability"] != "unavailable":
            continue
        reason = c["unavailable_reason"]
        assert reason and len(reason) > 10, f"{c['id']} 의 사유가 비어 있습니다: {reason!r}"


def test_available_factors_do_not_carry_a_phantom_reason():
    """쓸 수 있는 팩터에 사유가 붙어 있으면 화면이 못 쓰는 것처럼 보인다."""
    for c in tf.CATALOG:
        if c["availability"] == "available":
            assert c["unavailable_reason"] is None, f"{c['id']} 에 불필요한 사유가 있습니다"


def test_an_unavailable_factor_evaluates_to_none_not_zero():
    """★켤 수 없다는 표시를 UI 가 무시하더라도 엔진이 값을 지어내면 안 된다★ 방어가 두 겹이다."""
    assert tf.evaluate("borrow_short_interest", "SPY", "us") is None
    assert tf.evaluate("vix_skew", "SPY", "us") is None


def test_the_catalogue_response_carries_the_unavailable_group():
    """창이 읽는 것은 `catalog()` 다 — 여기에 없으면 화면에도 없다."""
    got = {f["id"] for g in tf.catalog()["groups"] for f in g["factors"]}
    assert "borrow_short_interest" in got
    assert "crowding" in got


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 기존 계약을 깨지 않았다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_existing_unit_field_is_untouched():
    """★프런트 계약이 `unit` 이다★ 스펙 문구(`units`)에 맞추려고 이름을 바꾸면 화면이 깨진다.

    감사 A1 이 지적한 것은 **이름 불일치**이고, 고칠 쪽은 코드가 아니라 스펙 한 단어다.
    """
    for c in tf.CATALOG:
        assert "unit" in c
        assert "units" not in c, f"{c['id']} 에 중복 키가 생겼습니다 — 진실이 둘이 됩니다"


def test_the_price_derived_factors_still_evaluate(monkeypatch):
    """메타를 덧입히면서 카탈로그 항목이 손상되지 않았는지 — 평가 경로가 여전히 산다."""
    called = {}

    def fake(ticker, market="kr", months=12):
        called["hit"] = True
        return 0.42

    monkeypatch.setattr(tf, "abs_mom_value", fake, raising=False)
    # 카탈로그 항목의 실행에 필요한 키가 남아 있는지가 요점이다.
    entry = tf.CATALOG_BY_ID["abs_mom"]
    assert entry["params"] == {"months": 12}
    assert entry["default_direction"] == "above"
    assert entry["family"] == "momentum"
