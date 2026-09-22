"""AX · ★인용문이 아니라 로더가 안다★ — 타이밍 팩터의 데이터 출처
==============================================================================
대상: `src/engine/timing_factor_meta.py` 의 `_ORIGIN_OVERRIDES`·`enrich()` ·
`src/engine/timing_factors.CATALOG` · 앞 프로그램 `tests/test_field_provenance.py`

## 왜 `provenance` 에서 뽑지 않았나 (실측)

`provenance` 칸에 ★세 가지가 섞여 있다★:

    데이터 제공자   5  'FRED/ALFRED (NFCI)'
    ETF 대용물      3  'ETF proxy (KODEX 229200 / 069500)'
    문헌 근거       7  'Keller & Keuning (VAA/DAA)'
    ★출처가 아님   17  'generic (realized volatility)'  ← 기법의 종류다
    명시적 없음     4  'spec §6.1 (no source)'

`classify()` 가 이미 이 문자열을 패턴 매칭해 `provenance_class` 를 만들지만,
그것은 *"누가 공개했나"* 라서 인용문에서 읽힌다. ★*"값이 어디서 오는가"* 는
읽히지 않는다★ — 17개가 아무것도 말하지 않는다. AW 이 `FactorMeta.source` 에서
만난 것과 같은 함정이다.

## 이 파일이 지키는 것

손으로 적은 선언이 ★실제 호출과 일치하는지★를 코드에서 읽어 대조한다.
**선언만 있고 검증이 없으면 그것은 증거가 아니라 주장이다.**
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.engine.timing_factor_meta import (
    ORIGIN_ETF_PRICES,
    ORIGIN_PIT_MACRO,
    TIMING_ORIGINS,
)
from src.engine.timing_factors import CATALOG

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TIMING_FACTORS = "src/engine/timing_factors.py"
_TACTICAL = "src/engine/tactical_allocations.py"
_RULES_V2 = "src/engine/timing_rules_v2.py"


# ── AST 도구 — ★소스 텍스트가 아니라 구조를 읽는다★ ──────────────────────

def _tree(rel: str) -> ast.Module:
    return ast.parse((_ROOT / rel).read_text(encoding="utf-8"))


def _module_imports(rel: str) -> set[str]:
    """모듈 **최상위** 임포트만. 함수 안의 지연 임포트는 세지 않는다."""
    return {n.module for n in _tree(rel).body
            if isinstance(n, ast.ImportFrom) and n.module}


def _functions(rel: str) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in _tree(rel).body if isinstance(n, ast.FunctionDef)}


def _imports_inside(fn: ast.FunctionDef) -> set[str]:
    return {n.module for n in ast.walk(fn)
            if isinstance(n, ast.ImportFrom) and n.module}


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.add(n.func.attr)
    return out


def _str_constants(rel: str) -> dict[str, str]:
    """모듈 최상위의 `NAME = "문자열"` — ★분기가 상수로 비교한다★(실측).

    처음 쓴 이 파일은 문자열 리터럴만 찾았고, 그래서 `read_factor` 가
    `CURVE_SLOPE_FACTOR_ID` 로 비교하는 네 팩터를 **통째로 놓쳤다**.
    ★어휘로 걸면 이렇게 샌다★ — 이름을 값으로 풀어서 본다.
    """
    out: dict[str, str] = {}
    for n in _tree(rel).body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def _dispatch(rel: str, fn_name: str) -> dict[str, set[str]]:
    """`if factor_id == X: ... FN(...)` 를 읽어 **id → 불리는 함수 이름들**.

    `X` 는 문자열 리터럴일 수도 모듈 상수일 수도 있다(둘 다 실재한다).
    """
    fn = _functions(rel)[fn_name]
    consts = _str_constants(rel)
    out: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        ids: set[str] = set()
        for cmp_ in (n for n in ast.walk(node.test) if isinstance(n, ast.Compare)):
            left = cmp_.left
            if isinstance(left, ast.Name) and left.id == "factor_id":
                for c in cmp_.comparators:
                    ids |= _as_ids(c, consts)
        if not ids:
            continue
        called = {n for b in node.body for n in _called_names(b)}
        for fid in ids:
            out.setdefault(fid, set()).update(called)
    return out


def _as_ids(node: ast.AST, consts: dict[str, str]) -> set[str]:
    """비교 대상 하나 → 팩터 id 들. 리터럴·상수 이름·튜플을 모두 푼다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name) and node.id in consts:
        return {consts[node.id]}
    if isinstance(node, (ast.Tuple, ast.List)):
        out: set[str] = set()
        for e in node.elts:
            out |= _as_ids(e, consts)
        return out
    return set()


def _reaches_etf_prices(fn_name: str) -> bool:
    """★모듈 내 1홉 + 모듈 간 1홉★ — 실측으로 확인된 경로만 따라간다.

    `target_vol_size` 는 스스로 임포트하지 않고 `realized_vol` 을 부르며,
    `_score_13612` 등은 `tactical_allocations` 에 있고 그 모듈이 **최상위**
    에서 `etf_prices` 를 임포트한다.
    """
    local = _functions(_TIMING_FACTORS)
    if fn_name in local:
        fn = local[fn_name]
        mods = _imports_inside(fn)
        if "src.data.etf_prices" in mods:
            return True
        if "src.engine.tactical_allocations" in mods:
            return "src.data.etf_prices" in _module_imports(_TACTICAL)
        # 모듈 내 1홉 — 같은 파일의 다른 팩터 함수에 위임한다.
        for callee in _called_names(fn) & set(local):
            if callee != fn_name and _reaches_etf_prices(callee):
                return True
        return False
    # `tactical_allocations` 의 프리미티브 — 그 모듈의 최상위 임포트를 본다.
    if fn_name in _functions(_TACTICAL):
        return "src.data.etf_prices" in _module_imports(_TACTICAL)
    return False


# ── 픽스처 대신 모듈 상수 (순수 읽기) ────────────────────────────────────

_BY_ORIGIN: dict[object, list[dict]] = {}
for _c in CATALOG:
    _BY_ORIGIN.setdefault(_c.get("origin"), []).append(_c)


# ── ★모든 팩터가 출처 칸을 갖는다★ ───────────────────────────────────────

def test_every_factor_declares_an_origin_key():
    """★칸이 없는 것과 값이 없는 것은 다르다★ — 키는 전부 있어야 한다."""
    missing = [c["id"] for c in CATALOG if "origin" not in c]
    assert missing == [], missing


def test_the_origin_vocabulary_is_closed():
    for c in CATALOG:
        assert c["origin"] in TIMING_ORIGINS or c["origin"] is None, (
            c["id"], c["origin"])


def test_the_origin_is_not_a_constant():
    """변이 j — ★상수가 관측 행세를 하면 죽는다★"""
    assert len({c["origin"] for c in CATALOG}) >= 3   # etf · pit_macro · None


def test_the_catalog_lost_no_key():
    """변이 k — ★응답에서 키가 사라지는 것은 파괴다★"""
    from src.engine.timing_factor_meta import REQUIRED_DEFINITION_FIELDS

    for c in CATALOG:
        for k in REQUIRED_DEFINITION_FIELDS:
            assert k in c, (c["id"], k)


# ── ★선언이 실제 호출과 일치한다 — 이것이 트립와이어다★ ─────────────────

def test_every_price_factor_actually_reaches_etf_prices():
    """변이 c — ★선언만 하고 다른 로더를 부르면 죽는다★"""
    dispatch = _dispatch(_TIMING_FACTORS, "evaluate")
    checked = 0
    for c in _BY_ORIGIN.get(ORIGIN_ETF_PRICES, []):
        fid = c["id"]
        assert fid in dispatch, f"{fid} 는 evaluate() 분기에 없다"
        assert any(_reaches_etf_prices(fn) for fn in dispatch[fid]), (
            f"{fid} 가 etf_prices 를 선언했지만 그 경로가 코드에 없다: "
            f"{sorted(dispatch[fid])}")
        checked += 1
    # ★공허한 전칭 금지★ — 한 건도 안 봤으면 통과가 아니다.
    assert checked >= 20, checked


def test_every_macro_factor_actually_reaches_pit_macro():
    """변이 c 의 짝 — 매크로 쪽도 선언대로 간다."""
    dispatch = _dispatch(_RULES_V2, "read_factor")
    mods = _module_imports(_RULES_V2)
    assert "src.data.pit_macro" in mods, mods
    checked = 0
    for c in _BY_ORIGIN.get(ORIGIN_PIT_MACRO, []):
        assert c["id"] in dispatch, f"{c['id']} 는 read_factor() 분기에 없다"
        checked += 1
    assert checked >= 5, checked


def test_the_sourceless_factors_declare_nothing_and_say_so():
    """변이 f — ★확인한 적 없는 출처를 적으면 죽는다★ + 짝.

    평가 함수가 아예 없는 4개는 `origin` 이 비어 있어야 하고, ★동시에★
    스스로 `unavailable` 이라고 광고해야 한다 — 비어 있는데 "쓸 수 있다"
    고 말하면 그것이 거짓 광고다.
    """
    evaluate_ids = set(_dispatch(_TIMING_FACTORS, "evaluate"))
    read_ids = set(_dispatch(_RULES_V2, "read_factor"))
    none_group = _BY_ORIGIN.get(None, [])
    assert len(none_group) >= 4, len(none_group)
    for c in none_group:
        assert c["id"] not in evaluate_ids, c["id"]
        assert c["id"] not in read_ids, c["id"]
        assert c["availability"] == "unavailable", c["id"]
        assert c["unavailable_reason"], c["id"]


def test_a_factor_with_an_origin_is_not_advertised_as_unavailable():
    """★짝★ — 출처가 있는 것은 unavailable 이 아니다(축이 실제로 갈린다)."""
    for c in CATALOG:
        if c["origin"] is not None:
            assert c["availability"] != "unavailable", c["id"]


# ── ★출처를 인용문에서 뽑지 않는다★ ─────────────────────────────────────

def test_the_origin_is_not_derivable_from_the_provenance_text():
    """변이 a — ★17개가 `generic (...)` 이라 인용문은 출처를 모른다★

    이 테스트는 구현이 아니라 **사실**을 못 박는다: 같은 `origin` 을 가진
    팩터들이 전혀 다른 인용문을 달고 있고, `'generic'` 을 단 것들이 그
    중 큰 덩어리다. 그러니 `provenance` 로 갈랐다면 틀렸을 것이다.
    """
    price = _BY_ORIGIN.get(ORIGIN_ETF_PRICES, [])
    assert len({c["provenance"] for c in price}) > 5
    generic = [c for c in price if str(c["provenance"]).startswith("generic")]
    assert len(generic) >= 10, len(generic)


def test_nothing_reads_the_provenance_to_decide_the_origin():
    """변이 a 의 구조적 짝 — ★인용문을 보고 출처를 정하면 죽는다★"""
    fn = _functions("src/engine/timing_factor_meta.py")["enrich"]
    for node in ast.walk(fn):
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == "origin":
                continue
        if isinstance(node, ast.Assign):
            tgt = node.targets[0]
            is_origin = (isinstance(tgt, ast.Subscript)
                         and isinstance(tgt.slice, ast.Constant)
                         and tgt.slice.value == "origin")
            if is_origin:
                names = {n.value for n in ast.walk(node.value)
                         if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                assert "provenance" not in names, names
                assert "classify" not in _called_names(node.value)


def test_the_availability_axis_does_not_decide_the_origin():
    """변이 g — ★쓸 수 있는가 ⟂ 어디서 오는가★"""
    fn = _functions("src/engine/timing_factor_meta.py")["enrich"]
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            tgt = node.targets[0]
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == "origin"):
                names = {n.value for n in ast.walk(node.value)
                         if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                assert "availability" not in names, names


# ── ★개수는 세지 않고 하한만 건다★ (CLAUDE.md — 개수를 적으면 낡는다) ──

@pytest.mark.parametrize("origin,minimum", [
    (ORIGIN_ETF_PRICES, 20), (ORIGIN_PIT_MACRO, 5), (None, 4),
])
def test_each_origin_group_actually_has_members(origin, minimum):
    """변이 b — ★한 값으로 뭉치면 다른 묶음이 비어 죽는다★"""
    assert len(_BY_ORIGIN.get(origin, [])) >= minimum, (
        origin, len(_BY_ORIGIN.get(origin, [])))
