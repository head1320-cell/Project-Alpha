"""ECOS 확장과 **개정 편향** — 정적 공표지연으로는 룩어헤드를 막을 수 없다 (P4-D1).

왜 이 파일이 있는가
------------------------------------------------------------------------------
P4 계획 초안은 "계열마다 공표지연을 선언한다(공표지연이 PIT 의 핵심)" 이라고 적었다.
**틀렸다.** 정적 지연 시프트는 **개정(revision) 편향**을 막지 못한다. 오늘 ECOS 로
2010-05 산업생산을 당기면 2010년 속보치가 아니라 나중에 다듬어진 확정치가 온다.
1개월 시프트해서 백테스트에 넣으면 미래를 훔쳐본다.

외부 리뷰는 "경고를 하드코딩해 프론트에 노출" 하라고 했는데, 라벨은 읽고 무시할 수
있다. 이 저장소엔 **더 강한 장치가 이미 있다** — `pit_macro.derive_usage()` 가
`has_vintage and depth_ok and lag_known` 을 모두 만족해야 `BACKTEST_ELIGIBLE` 이고,
`assert_backtest_eligible()` 이 백테스트 진입을 **예외로 중단**한다.

ECOS 는 빈티지 엔드포인트가 없다 → `has_vintage=False` → **구조적으로 FORWARD_ONLY**.
FRED/ALFRED 는 빈티지가 있다 → `BACKTEST_ELIGIBLE`. **두 소스가 같은 화면에 있으면서
적격성이 다르다**는 것이 이 설계의 요점이고, 아래 테스트는 그 차이를 짝으로 잰다.
새 판정 로직을 만들지 않는다 — 기존 `derive_usage()` 에 태우기만 한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.pit_macro import (  # noqa: E402
    ForwardOnlyError,
    ResearchUsage,
    assert_backtest_eligible,
)
from src.data.source_registry import (  # noqa: E402
    ECOS,
    FRED,
    all_specs,
    get_spec,
    research_usage,
    specs_by_provider,
)


def _ecos_specs():
    return specs_by_provider(ECOS)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 확장이 실제로 일어났다 (공허하지 않은 가드)
# ─────────────────────────────────────────────────────────────────────────────
def test_ecos_coverage_expanded_past_thirty_series():
    """★한국 주식 퀀트 플랫폼인데 한국 매크로가 가장 얕았다★

    착수 실측: ECOS 11계열 vs FRED 18+. 미국 매크로로 한국 자산을 설명하고 있었다.
    이 단언이 없으면 아래 정직성 테스트들은 계열 3개짜리 레지스트리에서도 통과한다.
    """
    n = len(_ecos_specs())
    assert n >= 30, f"ECOS 계열이 {n}개 — 확장이 안 됐다"


def test_the_core_macro_families_are_all_present():
    """짝 — 숫자만 채운 게 아니라 실제 축이 들어왔는지."""
    keys = {s.key for s in _ecos_specs()}
    for expected in ("KR_M2", "KR_GDP", "KR_IP", "KR_UNEMP", "KR_PPI",
                     "KR_CSI", "KR_BSI", "KR_HOUSE_PRICE", "KR_CURRENT_ACCOUNT",
                     "KR_EXPORT_VALUE"):
        assert expected in keys, f"{expected} 가 없다 — 축이 비었다"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 빈티지 선언 — 짝으로 잰다
# ─────────────────────────────────────────────────────────────────────────────
def test_every_ecos_series_declares_no_vintage():
    """ECOS 에는 빈티지 엔드포인트가 없다. 하나라도 True 면 거짓 선언이다."""
    bad = [s.key for s in _ecos_specs() if s.has_vintage]
    assert not bad, f"ECOS 인데 빈티지가 있다고 선언됐다: {bad}"


def test_fred_series_do_declare_vintage():
    """★짝★ 없으면 전부 False 로 선언해도 위 테스트가 통과한다.

    FRED 는 ALFRED 로 빈티지를 준다 — 이 저장소가 Phase 1 에서 이미 구현했다.
    """
    fred = specs_by_provider(FRED)
    assert fred, "FRED 스펙이 하나도 없다 — 대조군이 비었다"
    assert all(s.has_vintage for s in fred), "FRED 가 빈티지 없음으로 선언됐다"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ★구조적 FORWARD_ONLY — 라벨이 아니라 게이트★
# ─────────────────────────────────────────────────────────────────────────────
def test_ecos_is_forward_only_even_when_depth_and_lag_are_satisfied():
    """★이것이 이 파일의 핵심★

    공표지연을 알고(lag_known) 이력이 충분해도(depth_ok) ECOS 는 백테스트 적격이
    **될 수 없다.** 개정 편향은 시프트로 지워지지 않기 때문이다. 정적 지연 선언만
    했다면 이 테스트가 빨개진다.
    """
    assert research_usage("KR_M2", depth_ok=True, lag_known=True) \
        is ResearchUsage.FORWARD_ONLY


def test_fred_is_backtest_eligible_under_the_identical_conditions():
    """★짝★ 같은 조건인데 등급이 갈린다 — 갈리는 이유가 빈티지 하나다.

    이 짝이 없으면 `research_usage` 가 무조건 FORWARD_ONLY 를 돌려줘도 통과한다.
    """
    assert research_usage("CPIAUCSL", depth_ok=True, lag_known=True) \
        is ResearchUsage.BACKTEST_ELIGIBLE


def test_shallow_history_downgrades_even_a_vintage_source():
    """짝 — 빈티지가 있어도 나머지 조건이 어긋나면 내려간다(판정을 우회하지 않는다)."""
    assert research_usage("CPIAUCSL", depth_ok=False, lag_known=True) \
        is ResearchUsage.FORWARD_ONLY


# ─────────────────────────────────────────────────────────────────────────────
# 4. 백테스트 진입 게이트가 실제로 막는다 (1차 방어선)
# ─────────────────────────────────────────────────────────────────────────────
def test_backtest_gate_refuses_a_factor_set_containing_ecos():
    """★라벨은 무시할 수 있지만 게이트는 못 지나간다★

    `assert_backtest_eligible` 은 문제 팩터를 **이름으로** 지목하고 중단한다.
    """
    usage = {k: research_usage(k, depth_ok=True, lag_known=True)
             for k in ("CPIAUCSL", "KR_M2")}
    with pytest.raises(ForwardOnlyError) as e:
        assert_backtest_eligible(usage)
    assert "KR_M2" in str(e.value), "막긴 했는데 어느 팩터 때문인지 안 알려준다"
    assert "CPIAUCSL" not in str(e.value), "멀쩡한 팩터까지 지목됐다"


def test_backtest_gate_passes_a_pure_vintage_set():
    """짝 — 게이트가 무조건 막는 것이 아니다."""
    assert_backtest_eligible(
        {"CPIAUCSL": research_usage("CPIAUCSL", depth_ok=True, lag_known=True)})


# ─────────────────────────────────────────────────────────────────────────────
# 5. 사유 없는 등급 하향은 없다
# ─────────────────────────────────────────────────────────────────────────────
def test_every_forward_only_source_says_why_in_words():
    """화면이 그릴 수 있어야 한다 — 등급만 내리고 이유를 안 적으면 블랙박스다."""
    from src.data.source_registry import revision_bias_note
    for s in _ecos_specs():
        note = revision_bias_note(s.key)
        assert note and "개정" in note, f"{s.key}: 개정 편향 사유가 없다 ({note!r})"


def test_vintage_sources_carry_no_revision_bias_note():
    """짝 — 모든 소스에 경고를 붙이면 경고가 의미를 잃는다."""
    from src.data.source_registry import revision_bias_note
    assert revision_bias_note("CPIAUCSL") is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. 확장이 기존 동작을 깨지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_previously_verified_series_keep_their_mock_fallback():
    """★기존 8개 지표의 mock 폴백은 그대로다★

    레지스트리에 키를 넣으면 `new_source_mock_allowed` 가 mock 을 막는다(M1-I).
    실호출로 검증된 적이 있는 기존 지표까지 막으면 개발 환경 화면이 통째로 빈다.
    """
    from src.data.source_registry import new_source_mock_allowed
    for key in ("KR_BASE_RATE", "KR_3Y", "KR_CPI", "USD_KRW", "KOSPI"):
        assert new_source_mock_allowed(key), f"{key} 의 mock 폴백이 막혔다"


def test_newly_declared_series_still_refuse_mock():
    """짝 — 새로 선언한 미검증 계열은 여전히 mock 으로 안 채운다."""
    from src.data.source_registry import new_source_mock_allowed
    assert not new_source_mock_allowed("KR_PPI")


def test_unregistered_keys_are_unaffected():
    """레지스트리 밖 키는 기존 동작 유지 — 확장이 부작용을 만들지 않는다."""
    from src.data.source_registry import new_source_mock_allowed
    assert new_source_mock_allowed("SOME_UNREGISTERED_KEY")
    assert get_spec("SOME_UNREGISTERED_KEY") is None


def test_no_duplicate_keys_in_the_registry():
    """확장하면서 키가 겹치면 `_BY_KEY` 가 조용히 하나를 덮는다."""
    keys = [s.key for s in all_specs()]
    assert len(keys) == len(set(keys)), \
        f"중복 키: {sorted({k for k in keys if keys.count(k) > 1})}"
