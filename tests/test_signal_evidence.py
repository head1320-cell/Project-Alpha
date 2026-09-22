"""AV · ★신호가 어디서 왔는가★ — 출처 등급 규칙
==============================================================================
대상: `src/domain/signal_evidence.py` · 카탈로그 `src/domain/signal_definition.py`

## 왜 이 모듈이 생겼나

`SignalDefinition.evidence_grade` 는 선언만 되고 저장소 전체에서 **대입 0건**
이었다 — 같은 dataclass 의 `availability`·`unavailable_reason` 은 채워지는데
그 하나만 빠져 있었다. `GET /signals` 는 그 칸을 이미 내보내고 있으니, 화면은
지금까지 언제나 `null` 을 받았다. 갭 분석 §1 이 지목한 균열이고, 그것을 닫으려
만든 모듈에서 아직 안 닫혔다.

## ★같은 글자, 다른 축★

`E0~E3` 이라는 글자가 저장소에서 **두 척도**로 쓰인다:

    CLAUDE.md §2                      출처   E2 = 제공자 파생
    source_registry.EVIDENCE_GRADES   확신도 E2 = 메타 API 응답에서 관측

그리고 빈 필드의 주석은 ★확신도 쪽★을 가리키고 있었다. CLAUDE.md 가
`capability.py` 의 `L0~L3` 에 대해 *"방향이 정반대니 절대 섞지 마세요"* 라고
적어 둔 바로 그 위험이다. 신호에는 **출처 척도**를 쓴다.

## ★아는 것에서만 파생한다★

실측(2026-09-21, 신호 215개):

| 종류 | 개수 | 저장소가 출처를 말할 수 있나 |
|---|---|---|
| `strategy_token` | 8 | ✔ `BASE_TOKENS` 가 전부 가격·거래량이다 |
| `alpha_expr` | 17 | ✔ 카테고리가 `price`/`fund` 로 갈려 있다 |
| `screener_field` | 157 | ✘ ★`filter_ast` 병합이 `FactorMeta.source` 를 버린다★ |
| `timing_rule` | 33 | ✔ 24 `etf_prices` · ✘ 5 키 없음 · ✘ 4 소스 없음 (AX) |

★157개(73%)가 미상이고, 그 사유가 구체적인 결함을 가리킨다★ — 그 목록이 이
프로그램의 산출물이다. 미상을 `E0`(합성)으로 접지 않는다: 미상과 합성은 다른
사실이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.signal_definition import (
    KIND_ALPHA_EXPR,
    KIND_SCREENER_FIELD,
    KIND_STRATEGY_TOKEN,
    KIND_TIMING_RULE,
    SignalCatalog,
    SignalDefinition,
)
from src.domain.signal_evidence import (
    PROV_E0,
    PROV_E2,
    PROVENANCE_GRADES,
    grade_catalog,
    signal_grade,
)

_MODULE = pathlib.Path("src/domain/signal_evidence.py")


def _sig(kind, *, signal_id="s1", category="price", **over):
    fields = {"signal_id": signal_id, "kind": kind, "label": "L",
              "category": category, "owner_module": "src.engine.x"}
    fields.update(over)
    return SignalDefinition(**fields)


# ── ★어휘 — 출처 척도지 확신도 척도가 아니다★ ─────────────────────────

def test_the_scale_is_the_provenance_one():
    """CLAUDE.md §2 의 여섯 중 이 모듈이 쓰는 다섯."""
    assert PROVENANCE_GRADES == ("E0", "E1", "E2", "E3", "E4")


def test_the_module_does_not_import_the_confidence_scale():
    """변이 a — ★같은 글자, 다른 축★

    `source_registry.EVIDENCE_GRADES` 는 *ECOS 메타를 얼마나 확신하는가* 의
    척도다. 섞으면 `E2` 하나가 두 가지를 뜻하게 된다.
    ★어휘가 아니라 구조로 건다★ — docstring 이 그것을 **설명**하는 것은
    의존이 아니다(AU 에서 원문 grep 이 설명까지 잡은 적이 있다).
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "source_registry" not in node.module, ast.dump(node)


# ── ★말할 수 있는 종류★ ───────────────────────────────────────────────

def test_a_price_token_is_synthetic_under_the_mock_gate(monkeypatch):
    """★mock 에서 가격은 합성이다★ — `MockKISClient` 가 값을 지어낸다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_STRATEGY_TOKEN, category="token"))
    assert out["grade"] == PROV_E0
    assert out["reason"]


def test_the_same_token_is_not_synthetic_outside_the_mock_gate(monkeypatch):
    """★짝★ — 게이트가 실제로 판정을 움직인다(공허한 분기가 아니다)."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    out = signal_grade(_sig(KIND_STRATEGY_TOKEN, category="token"))
    assert out["grade"] != PROV_E0


def test_an_alpha_price_field_follows_the_same_path(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert signal_grade(_sig(KIND_ALPHA_EXPR, category="price"))["grade"] == PROV_E0


def test_a_real_mode_price_signal_is_provider_derived(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    out = signal_grade(_sig(KIND_ALPHA_EXPR, category="price"))
    assert out["grade"] == PROV_E2


def test_every_grade_carries_what_it_looked_at(monkeypatch):
    """★등급만 내면 다음 사람이 그 등급을 검증할 수 없다★"""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_STRATEGY_TOKEN, category="token"))
    assert out["basis"], out


# ── ★말할 수 없는 종류 — 미상 + 사유★ ────────────────────────────────

def test_a_screener_field_without_an_origin_is_unknown():
    """★AW 이후 이 사유가 바뀌었다★

    AV 때는 *"filter_ast 의 병합이 출처를 버린다"* 가 사유였다. AW 가 그것을
    되살렸으므로 ★그 문장은 이제 거짓이다★ — 지금 미상인 이유는 신호가
    출처를 실어 나르지 않아서다.
    """
    out = signal_grade(_sig(KIND_SCREENER_FIELD, category="valuation"))
    assert out["grade"] is None
    assert out["reason"]
    assert "버립니다" not in out["reason"], "낡은 사유가 남아 있다"


def test_a_screener_field_with_a_backed_origin_is_graded(monkeypatch):
    """★AW 가 되살린 것이 실제로 등급이 된다★"""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_SCREENER_FIELD, category="valuation",
                            origin="fundamentals_store"))
    assert out["grade"] == PROV_E0
    assert "fundamentals_store" in out["basis"]


def test_a_store_backed_reason_does_not_claim_it_is_price(monkeypatch):
    """★재무 필드에 "가격이 mock 에서 온다" 는 거짓을 붙이지 않는다★

    구현 중에 실제로 그 거짓을 만들었다가 잡았다 — 출처 기반 필드를 가격으로
    뭉뚱그리면 사유가 틀린 것을 말한다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_SCREENER_FIELD, category="quality",
                            origin="fundamentals_store"))
    assert "가격" not in out["reason"]


def test_a_base_field_is_unknown_because_nothing_declares_its_source():
    """★스토어로 옮겼다고 출처를 아는 것이 아니다★ — 14개는 여전히 미상."""
    out = signal_grade(_sig(KIND_SCREENER_FIELD, category="valuation",
                            origin="base_fields_store"))
    assert out["grade"] is None
    assert out["reason"]


def test_a_timing_rule_without_an_origin_is_unknown():
    """★AX 이후 — 출처를 안 싣는 것만 미상으로 남는다★

    AX 이전에는 33개 **전부**가 미상이었고 사유가 *"개정 정책은 아는데 출처는
    안 실어 나른다"* 였다. 이제 24개가 `etf_prices` 를 싣는다. 남는 것은
    ★평가 함수가 아예 없는 §6.1 묶음 4개★다.
    """
    out = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                            revision_policy="revised", origin=None))
    assert out["grade"] is None
    assert out["reason"]


def test_the_revision_axis_still_does_not_decide_the_origin():
    """★개정 정책 ⟂ 출처★ — 두 축은 여전히 갈려 있다(짝).

    같은 `origin` 에 `revision_policy` 만 달리해도 판정이 움직이지 않는다.
    """
    a = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                          origin="etf_prices", revision_policy="revised"))
    b = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                          origin="etf_prices", revision_policy="not_revised"))
    assert a["grade"] == b["grade"]
    assert a["reason"] == b["reason"]


# ── ★AX — 두 로더가 다른 것에 지배된다★ ─────────────────────────────────

def test_a_price_timing_factor_is_graded_by_the_mock_gate(monkeypatch):
    """`etf_prices` 는 `load_ohlcv_unified` 를 재사용한다 — 게이트가 지배한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_TIMING_RULE, category="momentum",
                            origin="etf_prices"))
    assert out["grade"] == PROV_E0
    assert out["basis"]


def test_the_same_price_timing_factor_is_not_synthetic_outside_the_gate(
        monkeypatch):
    """★짝★ — 게이트가 실제로 판정을 움직인다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    out = signal_grade(_sig(KIND_TIMING_RULE, category="momentum",
                            origin="etf_prices"))
    assert out["grade"] == PROV_E2


def test_a_macro_factor_is_unknown_without_the_fred_key(monkeypatch):
    """변이 e — ★키가 없으면 아무 값도 안 나온다. 등급을 붙이면 거짓이다★"""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                            origin="pit_macro"))
    assert out["grade"] is None
    assert "FRED_API_KEY" in out["reason"]


def test_a_macro_factor_is_graded_with_the_fred_key(monkeypatch):
    """변이 m ★짝★ — 항상-거부가 아니다. 환경이 판정을 움직인다."""
    monkeypatch.setenv("FRED_API_KEY", "x" * 8)
    out = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                            origin="pit_macro"))
    assert out["grade"] == PROV_E2
    assert out["basis"]


def test_the_mock_gate_does_not_move_the_macro_verdict(monkeypatch):
    """변이 d — ★mock 게이트는 FRED 경로를 지배하지 않는다★

    AW 에서 `BACKING_PRICE` 를 재사용했다가 재무 필드에 *"가격이 mock 에서
    옵니다"* 라는 거짓을 붙인 적이 있다. 같은 실수를 여기서 반복하면 죽는다.
    """
    monkeypatch.setenv("FRED_API_KEY", "x" * 8)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    opened = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                               origin="pit_macro"))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    closed = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                               origin="pit_macro"))
    assert opened["grade"] == closed["grade"]
    assert opened["reason"] == closed["reason"]


def test_a_macro_reason_never_claims_the_mock_gate_decided_it(monkeypatch):
    """변이 d 의 문장 쪽 — ★등급이 맞아도 사유가 틀리면 거짓이다★"""
    monkeypatch.setenv("FRED_API_KEY", "x" * 8)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                            origin="pit_macro"))
    assert "지어낸 것입니다" not in out["reason"]
    assert "MockKISClient" not in out["reason"]


def test_a_macro_factor_is_never_raised_to_the_vintage_grade(monkeypatch):
    """★빈티지 리더를 지나는 것 ≠ 빈티지가 고정됐음을 확인한 것★

    `E4`(시점 고정)는 강한 주장이고 순수 규칙은 그것을 확인할 수 없다.
    """
    monkeypatch.setenv("FRED_API_KEY", "x" * 8)
    out = signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                            origin="pit_macro"))
    assert out["grade"] != "E4"


def test_the_stale_timing_reason_is_gone(monkeypatch):
    """변이 l — ★거짓이 된 문장이 남아 있으면 죽는다★

    AV 가 적은 *"무엇에서 계산되는지는 실어 나르지 않습니다"* 는 이제
    24개에 대해 거짓이다.

    ★처음 쓴 이 테스트는 등급이 **붙는** 팩터를 겨눴고, 그래서 변이가
    살아남았다★ — 낡은 문구는 **미상 경로**에서만 나온다. 미상으로 남는
    두 묶음 **전부**를 본다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    reasons = [
        signal_grade(_sig(KIND_TIMING_RULE, category="regime", origin=None)),
        signal_grade(_sig(KIND_TIMING_RULE, category="regime",
                          origin="pit_macro")),
        signal_grade(_sig(KIND_TIMING_RULE, category="momentum",
                          origin="etf_prices")),
    ]
    for out in reasons:
        assert "실어 나르지 않습니다" not in (out["reason"] or ""), out["reason"]
    # ★공허 방지★ — 실제로 미상이 섞여 있어야 이 검사가 의미를 갖는다.
    assert any(o["grade"] is None for o in reasons)
    assert any(o["grade"] is not None for o in reasons)


def test_an_unknown_grade_is_never_folded_into_synthetic():
    """변이 c — ★미상 ≠ 합성★ (E0 은 '합성이라고 안다' 는 주장이다)."""
    for kind in (KIND_SCREENER_FIELD, KIND_TIMING_RULE):
        out = signal_grade(_sig(kind, category="x"))
        assert out["grade"] is not PROV_E0
        assert out["grade"] is None


def test_an_unregistered_kind_is_unknown_with_a_reason():
    """변이 f·j — 모르는 종류를 낙관적으로 분류하면 죽는다."""
    out = signal_grade(_sig("망가진종류"))
    assert out["grade"] is None
    assert out["reason"]


@pytest.mark.parametrize("category", ["", None, "듣보잡"])
def test_an_alpha_expr_with_an_unmapped_category_is_unknown(category):
    """`alpha_lab` 이 새 그룹을 더하면 ★조용히 통과하지 않는다★."""
    out = signal_grade(_sig(KIND_ALPHA_EXPR, category=category))
    assert out["grade"] is None


def test_no_grade_is_ever_returned_without_a_reason(monkeypatch):
    """변이 e — ★사유 없는 미상은 금지★ (CLAUDE.md §4)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    for kind in (KIND_SCREENER_FIELD, KIND_TIMING_RULE, KIND_ALPHA_EXPR,
                 KIND_STRATEGY_TOKEN, "듣보잡"):
        out = signal_grade(_sig(kind))
        assert out["reason"], kind


def test_the_grade_is_always_in_the_vocabulary_or_none(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    for kind in (KIND_SCREENER_FIELD, KIND_TIMING_RULE, KIND_ALPHA_EXPR,
                 KIND_STRATEGY_TOKEN, "듣보잡"):
        g = signal_grade(_sig(kind))["grade"]
        assert g is None or g in PROVENANCE_GRADES


# ── ★상수가 관측 행세를 하지 않는다★ ─────────────────────────────────

def test_the_kind_actually_changes_the_answer(monkeypatch):
    """변이 h — 모든 신호에 같은 등급을 찍으면 죽는다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    grades = {signal_grade(_sig(k, category=c))["grade"]
              for k, c in ((KIND_STRATEGY_TOKEN, "token"),
                           (KIND_SCREENER_FIELD, "valuation"))}
    assert len(grades) == 2


def test_the_availability_axis_is_not_mixed_in(monkeypatch):
    """변이 k — ★쓸 수 있는가 ⟂ 어디서 왔는가★

    `availability` 가 무엇이든 출처 등급은 달라지지 않는다. 섞으면 "못 쓰는
    신호" 와 "출처를 모르는 신호" 가 한 칸에 접힌다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    base = signal_grade(_sig(KIND_STRATEGY_TOKEN, category="token"))
    for avail in ("available", "unavailable", None):
        out = signal_grade(_sig(KIND_STRATEGY_TOKEN, category="token",
                                availability=avail))
        assert out["grade"] == base["grade"], avail


# ── ★카탈로그 판정 — 빈틈 목록이 산출물이다★ ────────────────────────

def _catalog(*signals):
    return SignalCatalog(signals=tuple(signals))


def test_the_rollup_separates_graded_from_ungraded(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = grade_catalog(_catalog(
        _sig(KIND_STRATEGY_TOKEN, signal_id="t1", category="token"),
        _sig(KIND_SCREENER_FIELD, signal_id="f1", category="valuation"),
    ))
    assert out["n_graded"] == 1
    assert [u["signal_id"] for u in out["ungraded"]] == ["f1"]


def test_an_empty_catalog_does_not_claim_everything_is_graded():
    """변이 g — ★공허한 전칭★ 금지. 파이썬에서 `all([])` 은 `True` 다."""
    out = grade_catalog(_catalog())
    assert out["n_graded"] == 0
    assert out["complete"] is False


def test_a_fully_graded_catalog_says_so(monkeypatch):
    """★짝★ — `complete` 가 실제로 True 가 될 수 있다(항상-거짓이 아니다)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = grade_catalog(_catalog(
        _sig(KIND_STRATEGY_TOKEN, signal_id="t1", category="token")))
    assert out["complete"] is True


def test_the_ungraded_list_actually_filters(monkeypatch):
    """변이 i — ★공허한 분기★ 금지. 필터가 무언가를 거른다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = grade_catalog(_catalog(
        _sig(KIND_STRATEGY_TOKEN, signal_id="t1", category="token"),
        _sig(KIND_STRATEGY_TOKEN, signal_id="t2", category="token"),
    ))
    assert out["ungraded"] == []


def test_the_rollup_counts_by_grade(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = grade_catalog(_catalog(
        _sig(KIND_STRATEGY_TOKEN, signal_id="t1", category="token"),
        _sig(KIND_ALPHA_EXPR, signal_id="a1", category="price"),
    ))
    assert out["by_grade"][PROV_E0] == 2


def test_every_ungraded_entry_carries_its_reason():
    out = grade_catalog(_catalog(
        _sig(KIND_SCREENER_FIELD, signal_id="f1", category="valuation")))
    assert out["ungraded"][0]["reason"]


# ── ★실물 — 진짜 카탈로그로 잰다★ ────────────────────────────────────

def test_the_real_catalog_has_signals_the_repo_cannot_place(monkeypatch):
    """★목록이 비면 그것도 거짓이다★

    규칙이 모든 신호에 등급을 찍는다면 지어내고 있는 것이다 — 실측으로
    `screener_field` 157개는 출처가 카탈로그에 도달하지 않는다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.domain.signal_definition import collect_signals

    out = grade_catalog(collect_signals())
    assert out["n_ungraded"] > 0
    assert out["complete"] is False


def test_the_real_catalog_also_has_signals_it_can_place(monkeypatch):
    """★짝★ — 전부 미상이면 규칙이 아무 일도 안 하는 것이다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.domain.signal_definition import collect_signals

    assert grade_catalog(collect_signals())["n_graded"] > 0


# ── ★순수★ ───────────────────────────────────────────────────────────

def test_the_module_imports_no_database_or_network():
    """변이 l — 계층 경계(CLAUDE.md §3)."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned
