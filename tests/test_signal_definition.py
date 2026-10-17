"""신호 카탈로그를 ★덮는 뷰★ (P1-c)

## 무엇이 문제였나 (실측)

신호·팩터 정의가 **다섯 갈래**로 흩어져 있다:

    engine/filter_ast.FIELD_BY_ID        스크리너 필드(카테고리·단위·방향)
    engine/timing_factors.CATALOG        타이밍 규칙(관측창·공표지연·개정정책까지)
    engine/alpha_lab.FIELDS              알파 DSL 필드
    kis_strategies/factor_tokens         전략 토큰 + 미지원 사유
    data/alpha_registry                  알파 수명주기(draft→…→approved)

그래서 *"이 신호가 어떤 데이터에 기대고 그 데이터가 몇 등급인가"* 를 **한 번에 물을
자리가 없었다**. 증거 등급(`source_registry` 의 `E0~E3`)은 또 따로 있었다.

## ★통합이 아니라 뷰다★

다섯을 합치는 리팩터는 하지 않는다 — 스크리너 3-레이어와 `FIELD_BY_ID` 는
CLAUDE.md §6 이 리팩터 대상이 아니라고 못 박았다. 이 뷰는 **값을 복사하지 않고**
`owner_module` 로 원본을 가리킨다. 복사하면 반드시 갈라진다.
"""
from __future__ import annotations

import dataclasses
import importlib
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.signal_definition import (  # noqa: E402
    KIND_ALPHA_EXPR,
    KIND_SCREENER_FIELD,
    KIND_TIMING_RULE,
    SIGNAL_KINDS,
    SignalDefinition,
    collect_signals,
)


@pytest.fixture(scope="module")
def cat():
    return collect_signals()


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ 다섯 출처를 모은다
# ═══════════════════════════════════════════════════════════════════════════

def test_it_collects_from_several_catalogs(cat):
    kinds = {s.kind for s in cat.signals}
    for must in (KIND_SCREENER_FIELD, KIND_TIMING_RULE, KIND_ALPHA_EXPR):
        assert must in kinds, f"{must} 를 못 모았다 — 모은 것: {kinds}"


def test_every_kind_is_declared(cat):
    for s in cat.signals:
        assert s.kind in SIGNAL_KINDS, s


def test_owner_module_points_at_something_real(cat):
    """★값을 복사하지 않고 원본을 가리킨다★ — 가리키는 곳이 실재해야 한다."""
    for mod in sorted({s.owner_module for s in cat.signals}):
        importlib.import_module(mod)      # 없으면 여기서 터진다


def test_ids_are_unique_within_a_kind(cat):
    seen = set()
    for s in cat.signals:
        key = (s.kind, s.signal_id)
        assert key not in seen, f"중복: {key}"
        seen.add(key)


def test_timing_rules_carry_release_lag_and_revision_policy(cat):
    """타이밍 쪽은 ★공표 지연과 개정 정책★을 이미 들고 있다 — 그것이 소실되면 안 된다."""
    timing = [s for s in cat.signals if s.kind == KIND_TIMING_RULE]
    assert timing, "타이밍 규칙을 하나도 못 모았다"
    assert any(s.release_lag for s in timing), "release_lag 가 전부 비었다"
    assert any(s.revision_policy for s in timing), "revision_policy 가 전부 비었다"


def test_unavailable_factors_keep_their_reason(cat):
    """★카탈로그에 보이되 켤 수 없는 것★ — 사유 없이 사라지면 안 된다."""
    blocked = [s for s in cat.signals if s.unavailable_reason]
    assert blocked, "미지원 사유를 가진 항목이 하나도 안 넘어왔다"
    for s in blocked:
        assert len(s.unavailable_reason) > 5, s


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ ★공허 배제★ — 비면 실패, 부분 실패는 라벨로 남는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_collection_is_not_empty(cat):
    assert len(cat.signals) > 20, len(cat.signals)


def test_a_broken_source_is_reported_not_swallowed(monkeypatch):
    """★출처 하나가 죽어도 나머지는 나오고, 죽었다는 사실이 남는다.★"""
    import src.domain.signal_definition as sd

    def _boom():
        raise RuntimeError("카탈로그 폭발")

    monkeypatch.setitem(sd._ADAPTERS, KIND_TIMING_RULE, _boom)
    c = sd.collect_signals()
    assert c.signals, "한 출처가 죽자 전부 사라졌다"
    assert KIND_TIMING_RULE in c.unavailable_sources
    assert "카탈로그 폭발" in c.unavailable_sources[KIND_TIMING_RULE]
    assert not any(s.kind == KIND_TIMING_RULE for s in c.signals)


def test_nothing_is_unavailable_in_the_normal_case(cat):
    """★짝★ 평소에는 미가용 목록이 비어 있다(항상-실패 구현 배제)."""
    assert cat.unavailable_sources == {}, cat.unavailable_sources


# ═══════════════════════════════════════════════════════════════════════════
# ★증거 축을 섞지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_evidence_grade_uses_the_existing_vocabulary(cat):
    """`E0~E3` 는 `source_registry` 의 어휘다 — `SRC_*` 도 `L0~L3` 도 아니다."""
    from src.data.source_registry import EVIDENCE_GRADES
    for s in cat.signals:
        if s.evidence_grade is not None:
            assert s.evidence_grade in EVIDENCE_GRADES, s


def test_a_signal_is_immutable():
    s = SignalDefinition(signal_id="x", kind=KIND_SCREENER_FIELD, label="X",
                         category="c", owner_module="src.engine.filter_ast")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.label = "Y"                      # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# 소비자 — ★소비자 없는 기능을 만들지 않는다★ (로드맵 규율 ②)
# ═══════════════════════════════════════════════════════════════════════════

def test_the_route_is_registered():
    from src.app_factory import ROUTER_MODULES
    assert "src.api.signal_routes" in ROUTER_MODULES


def test_the_route_serves_the_same_view():
    from src.api.signal_routes import list_signals
    body = list_signals(kind=None)
    assert body["signals"], "라우트가 빈 목록을 돌려줬다"
    assert body["counts_by_kind"], body
    assert body["unavailable_sources"] == {}


def test_the_route_filters_by_kind():
    from src.api.signal_routes import list_signals
    body = list_signals(kind=KIND_TIMING_RULE)
    assert body["signals"]
    assert {s["kind"] for s in body["signals"]} == {KIND_TIMING_RULE}


def test_the_route_passes_through_a_broken_source(monkeypatch):
    """★부분 실패가 200 뒤에 숨지 않는다.★"""
    import src.domain.signal_definition as sd
    from src.api.signal_routes import list_signals

    def _boom():
        raise RuntimeError("어댑터 폭발")

    monkeypatch.setitem(sd._ADAPTERS, KIND_ALPHA_EXPR, _boom)
    body = list_signals(kind=None)
    assert "어댑터 폭발" in body["unavailable_sources"][KIND_ALPHA_EXPR]
