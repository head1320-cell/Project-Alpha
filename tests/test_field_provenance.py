"""AW · ★병합이 떨어뜨린 것을 되살린다 — 둘이었다★
==============================================================================
대상: `src/engine/filter_ast.py` 의 `FieldMeta`·세 병합 · 골든 스냅샷
`tests/test_filter_ast_golden.py`

## 무엇이 떨어지고 있었나

AV 가 신호 157개(73%)의 출처를 저장소가 말할 수 없다고 이름 붙였고, 원인을
`filter_ast` 의 병합이 `FactorMeta.source` 를 버리는 것으로 지목했다.
★그런데 실측하니 떨어진 것이 **둘**이었고, 둘은 다른 축이다.★

## ★실측 ① — `source` 는 문헌 근거가 아니다(적어도 균일하게는)★

    FUNDAMENTAL_FACTORS  '기본' 29 · 'DuPont' 3 · 'Piotroski (2000)' 1 …
                         → 전부 문헌·파생 근거
    EXTENDED_FACTORS     'DART' 26 · 'DART 파생' 14 · 'KIS' 4 …
                         → 전부 데이터 제공자
    PRICE_FACTORS        '기본' 16 · 'KIS 투자자동향' 6 · 'Wilder' 1 …
                         → ★한 칸에 둘이 섞여 있다★

그래서 이 칸을 `literature` 로 옮기면 `'DART'` 를 문헌 인용이라고 부르게
된다. ★해석하지 않고 원문 그대로 나르고, 섞여 있다는 사실을 기록한다★ —
문자열을 패턴으로 가르는 것은 AR 이 `msg1` 에서 거부한 바로 그 일이다.

## ★실측 ② — 데이터 출처는 병합 자리가 안다★

어느 스토어에서 병합됐는지는 **해석이 필요 없는 구조적 사실**이다. 그것이
`signal_evidence` 가 필요로 하는 데이터 출처이고, 이 프로그램이 되살리는 것이다.

## ★이 파일이 지키는 것★

- 새 칸은 **늘기만** 한다 — 기존 일곱 칸은 골든 스냅샷이 지킨다.
- `origin` 은 스토어마다 **다르다**(상수가 관측 행세를 하지 않는다).
- `source_declared` 는 ★해석하지 않은 원문★이고 등급은 그것을 읽지 않는다.
"""
from __future__ import annotations

import pytest

import src.engine.filter_ast as fa
from src.engine.filter_ast import (
    ORIGIN_BASE,
    ORIGIN_EXTENDED,
    ORIGIN_FUNDAMENTAL,
    ORIGIN_PRICE,
    ORIGINS,
)

# ── ★새 칸은 늘기만 한다★ ──────────────────────────────────────────────

def test_the_new_columns_exist_with_defaults():
    """★기본값이 없으면 위치인자 생성 17곳이 깨진다★ (실측)."""
    from dataclasses import fields as dfields

    by_name = {f.name: f for f in dfields(fa.FieldMeta)}
    for name in ("origin", "source_declared"):
        assert name in by_name, name
        assert by_name[name].default is None, f"{name} 에 기본값이 없다"


def test_the_new_columns_come_last():
    """앞에 끼어들면 위치인자가 조용히 어긋난다."""
    from dataclasses import fields as dfields

    names = [f.name for f in dfields(fa.FieldMeta)]
    assert names[-2:] == ["origin", "source_declared"]


def test_a_positional_construction_still_works():
    """★17곳이 쓰는 모양★ — 일곱 개만 줘도 만들어져야 한다."""
    m = fa.FieldMeta("x", "X", "valuation", "배", False, 0, 50)
    assert m.origin is None and m.source_declared is None


# ── ★데이터 출처 — 병합 자리가 아는 구조적 사실★ ─────────────────────

def test_every_field_has_an_origin():
    """★157개 전부★ — 리터럴도 스토어로 옮겼으니 미상이 없어야 한다."""
    missing = [f.id for f in fa.FIELD_CATALOG if f.origin is None]
    assert missing == [], missing


def test_every_origin_is_in_the_vocabulary():
    for f in fa.FIELD_CATALOG:
        assert f.origin in ORIGINS, (f.id, f.origin)


def test_the_origin_is_not_a_constant():
    """변이 h — ★상수가 관측 행세를 하면 죽는다★"""
    assert len({f.origin for f in fa.FIELD_CATALOG}) >= 3


@pytest.mark.parametrize("origin,expected_min", [
    (ORIGIN_FUNDAMENTAL, 60), (ORIGIN_PRICE, 30),
    (ORIGIN_EXTENDED, 45), (ORIGIN_BASE, 10),
])
def test_each_origin_actually_has_members(origin, expected_min):
    """★실측한 개수(64·31·50·12)에 근거한 하한★ — 한 쪽이 비면 병합이 깨진 것이다."""
    n = sum(1 for f in fa.FIELD_CATALOG if f.origin == origin)
    assert n >= expected_min, (origin, n)


def test_a_known_fundamental_field_says_so():
    assert fa.FIELD_BY_ID["gp_to_assets"].origin == ORIGIN_FUNDAMENTAL


def test_a_known_base_field_says_so():
    """옮긴 리터럴이 제 출처를 갖는다."""
    assert fa.FIELD_BY_ID["per"].origin == ORIGIN_BASE


# ── ★선언된 출처 — 해석하지 않은 원문★ ───────────────────────────────

def test_the_declared_source_is_carried_verbatim():
    """★스토어가 적어 둔 문자열 그대로★ — 고쳐 쓰지 않는다."""
    from src.data.fundamentals_store import FACTOR_BY_ID

    fid = "gp_to_assets"
    assert fa.FIELD_BY_ID[fid].source_declared == FACTOR_BY_ID[fid].source


@pytest.mark.parametrize("origin,module,attr", [
    (ORIGIN_FUNDAMENTAL, "src.data.fundamentals_store", "FACTOR_BY_ID"),
    (ORIGIN_PRICE, "src.data.price_factors_store", "PRICE_FACTOR_BY_ID"),
    (ORIGIN_EXTENDED, "src.data.extended_factors_store", "EXT_FACTOR_BY_ID"),
])
def test_every_declared_source_matches_its_store_verbatim(origin, module, attr):
    """변이 e — ★한 칸이라도 지어내면 죽는다★

    처음 쓴 검증은 *"어딘가에 `'DART'` 가 보이면 된다"* 였고, 그래서 50개를
    전부 상수 `'DART'` 로 바꾸는 변이가 **살아남았다**(`'DART 파생'` 14개와
    `'KIS'` 4개가 조용히 뭉개진다). ★느슨한 전칭은 증거가 아니다★ —
    필드마다 스토어 원문과 글자 단위로 대조한다.
    """
    import importlib

    by_id = getattr(importlib.import_module(module), attr)
    checked = 0
    for f in fa.FIELD_CATALOG:
        if f.origin != origin:
            continue
        fac = by_id.get(f.id)
        if fac is None:
            continue
        assert f.source_declared == getattr(fac, "source", None), f.id
        checked += 1
    # ★공허한 전칭 금지★ — 한 건도 안 봤으면 통과가 아니다.
    assert checked >= 10, (origin, checked)


def test_the_declared_source_is_not_a_constant():
    """변이 e — ★스토어가 여러 값을 적어 뒀는데 하나로 접으면 죽는다★"""
    for origin, n_min in ((ORIGIN_EXTENDED, 5), (ORIGIN_FUNDAMENTAL, 10),
                          (ORIGIN_PRICE, 5)):
        distinct = {f.source_declared for f in fa.FIELD_CATALOG
                    if f.origin == origin}
        assert len(distinct) >= n_min, (origin, distinct)


def test_the_declared_source_keeps_a_literature_value_unchanged():
    """★짝★ — 문헌 쪽도 그대로 살아 온다."""
    declared = {f.source_declared for f in fa.FIELD_CATALOG
                if f.origin == ORIGIN_FUNDAMENTAL}
    assert any(d and "(" in d and ")" in d for d in declared), declared


def test_the_base_fields_declare_nothing():
    """변이 f — ★확인한 적 없는 근거를 적으면 죽는다★

    맨손 리터럴 12개는 어느 스토어에도 없었고 근거를 확인한 적이 없다.
    적는 것이 곧 지어내기다.
    """
    for f in fa.FIELD_CATALOG:
        if f.origin == ORIGIN_BASE:
            assert f.source_declared is None, f.id


def test_the_two_columns_are_not_the_same_thing():
    """★한 칸에 두 질문을 넣지 않는다★ (AV 가 방금 고친 실수).

    실측: `EXTENDED_FACTORS.source` 는 제공자(`DART`)이고
    `FUNDAMENTAL_FACTORS.source` 는 문헌(`Piotroski (2000)`)이다 — 같은 칸
    이름이 스토어마다 다른 것을 담고 있다. 그래서 `origin` 과 분리한다.
    """
    pairs = {(f.origin, f.source_declared) for f in fa.FIELD_CATALOG}
    by_origin: dict[str, set] = {}
    for origin, declared in pairs:
        by_origin.setdefault(origin, set()).add(declared)
    assert len(by_origin[ORIGIN_FUNDAMENTAL]) > 1
    assert by_origin[ORIGIN_FUNDAMENTAL] != by_origin[ORIGIN_EXTENDED]


def test_nothing_interprets_the_declared_source():
    """변이 — ★문자열을 패턴으로 가르지 않는다★ (AR 이 `msg1` 에서 거부한 것).

    `'기본'`·`'DART'`·`'Wilder'` 를 코드가 분류하기 시작하면, 저장소가
    확인한 적 없는 것을 주장하게 된다.
    """
    import ast
    import pathlib

    src = pathlib.Path("src/engine/filter_ast.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.Eq)) for op in node.ops):
            for side in (node.left, *node.comparators):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    assert "DART" not in side.value and "기본" not in side.value, (
                        f"선언된 출처를 해석하고 있다: {side.value!r}")


# ── ★API 카탈로그가 둘을 낸다★ ───────────────────────────────────────

def test_the_api_catalog_carries_both_columns():
    """`fields_catalog()` 는 `asdict` 라 자동으로 나온다 — 키가 늘기만 한다."""
    cats = fa.fields_catalog()["categories"]
    one = next(f for c in cats for f in c["fields"])
    assert "origin" in one and "source_declared" in one


def test_the_api_catalog_lost_no_key():
    """변이 k — ★응답에서 키가 사라지는 것은 파괴다★"""
    cats = fa.fields_catalog()["categories"]
    one = next(f for c in cats for f in c["fields"])
    for old in ("id", "label", "category", "unit", "higher_better",
                "typical_min", "typical_max"):
        assert old in one, old


# ── ★등급은 선언된 원문을 읽지 않는다 — 구조로 건다★ ─────────────────

def test_the_grade_rule_never_mentions_the_declared_source():
    """변이 b — ★등급 규칙이 `source_declared` 를 읽으면 죽는다★

    변이 배터리에서 `signal_grade` 가 `getattr(signal, "source_declared")` 를
    읽게 만들어 봤더니 **테스트가 아무것도 잡지 못했다**. 잡을 것이 없었기
    때문이다 — `SignalDefinition` 에 그 칸이 없어 언제나 `None` 이다.
    ★등가 변이는 통과한 변이가 아니다★ — 그래서 그 구조적 사실을 못 박는다.
    """
    import pathlib

    src = pathlib.Path("src/domain/signal_evidence.py").read_text(encoding="utf-8")
    assert "source_declared" not in src, "등급 규칙이 선언된 원문을 알고 있다"


def test_the_signal_deliberately_does_not_carry_the_declared_source():
    """★짝★ — 칸이 `filter_ast` 에서 멈추는 것이 설계다.

    `origin` 은 신호까지 간다(등급이 읽는다). `source_declared` 는 스크리너
    카탈로그까지만 간다(사람이 읽는다). ★둘이 같은 곳까지 가면 축이 하나로
    무너진다.★
    """
    from dataclasses import fields as dfields

    from src.domain.signal_definition import SignalDefinition

    names = {f.name for f in dfields(SignalDefinition)}
    assert "origin" in names
    assert "source_declared" not in names
