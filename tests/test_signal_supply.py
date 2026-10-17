"""AY · ★못 붙이는 이유를 검증되는 관측으로★ — 공급 모듈 규칙
==============================================================================
대상: `src/domain/signal_supply.py` · `src/engine/alpha_lab.py`(관측만) ·
앞 프로그램 `tests/test_field_provenance.py`(AW) · `tests/test_timing_origin.py`(AX)

## 적히지 않은 규칙이 하나 있었다

AW·AX 가 `origin` 을 세 번 쓰도록 **한 번도 적히지 않은 규칙**이 있다:
★`origin` 은 실재하는 `src/data/` **공급 모듈** 이름이다.★ 여섯 값 모두
그러한데(실측) 아무도 그것을 걸지 않았다. 이 파일이 소급으로 건다.

## 그 규칙이 처음으로 부딪힌 자리

`alpha_expr`(fund) 7개의 값은 `alpha_lab._load_fundamentals` 가
`financials_history` 를 **직접 SELECT** 해서 온다 — 어느 `src/data/` 모듈도
지나지 않는다. ★`financials_history` 는 모듈이 아니라 테이블이라 어휘에
넣을 수 없다★(한 칸에 두 종류를 넣으면 다음 사람이 구별할 수 없다).

## ★그래서 등급 대신 관측을 만든다★

*"모른다"* 가 아니라 *"공급 모듈이 없다 — 이것이 참인 동안은 못 붙인다"* 라고
말하고, **그것이 참인지를 이 파일이 확인한다.** 누군가 고치면 ★테스트가 red 로
승급을 알린다★ — `version_registry.MISSING_AXES` 가 세운 선례 그대로다.
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

from src.domain.signal_supply import (
    SUPPLY_PACKAGE,
    UNSUPPLIED,
    UnsuppliedSignal,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_ALPHA_LAB = "src/engine/alpha_lab.py"
_MODULE = pathlib.Path("src/domain/signal_supply.py")


# ── AST 도구 ─────────────────────────────────────────────────────────────

def _fn(rel: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{rel} 에 {name} 이 없다")


def _imports_inside(fn: ast.FunctionDef) -> set[str]:
    out = {n.module for n in ast.walk(fn)
           if isinstance(n, ast.ImportFrom) and n.module}
    for n in ast.walk(fn):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


def _goes_through_supply(fn: ast.FunctionDef) -> bool:
    """이 함수가 ★`src/data/` 공급 모듈★ 을 지나는가."""
    return any(m.startswith(SUPPLY_PACKAGE + ".") or m == SUPPLY_PACKAGE
               for m in _imports_inside(fn))


# ── ★규칙 — `origin` 은 실재하는 공급 모듈이다★ ──────────────────────────

def _all_declared_origins() -> set[str]:
    from src.engine.filter_ast import ORIGINS
    from src.engine.timing_factor_meta import TIMING_ORIGINS

    return set(ORIGINS) | set(TIMING_ORIGINS)


def test_the_supply_package_is_the_data_layer():
    assert SUPPLY_PACKAGE == "src.data"


def test_every_declared_origin_is_a_real_supply_module():
    """변이 a·b — ★오타도 테이블 이름도 여기서 죽는다★

    AW·AX 가 세 번 쓰도록 아무도 이것을 걸지 않았다. 소급으로 건다.
    """
    declared = _all_declared_origins()
    for name in declared:
        importlib.import_module(f"{SUPPLY_PACKAGE}.{name}")


def test_the_origin_vocabulary_is_not_empty():
    """★공허한 전칭 금지★ — 0개면 위 테스트가 아무것도 안 본 것이다."""
    assert len(_all_declared_origins()) >= 6


def test_the_origin_names_carry_no_dots():
    """★모듈 이름이지 경로가 아니다★ — `src.data.x` 나 테이블명이 섞이면 죽는다."""
    for name in _all_declared_origins():
        assert "." not in name, name


# ── ★alpha_lab 의 비대칭 — 이것이 이 프로그램의 발견★ ────────────────────

def test_the_price_loader_goes_through_the_data_layer():
    """10개는 `ohlcv_loader` 를 지난다 — 그래서 출처를 말할 수 있다."""
    fn = _fn(_ALPHA_LAB, "_load_price_series")
    assert _goes_through_supply(fn), _imports_inside(fn)
    assert any("ohlcv_loader" in m for m in _imports_inside(fn))


def test_the_fundamentals_loader_does_not_go_through_the_data_layer():
    """변이 e·f — ★이 주장이 살아 있는지 확인한다★

    7개는 `src/data/` 를 지나지 않고 `src.database` 로 표를 직접 읽는다.
    ★누군가 이것을 고치면 이 테스트가 red 가 되고, 그것이 곧 승급 신호다.★
    실패하면 `signal_supply.UNSUPPLIED` 에서 이 항목을 빼고 등급을 붙여라.
    """
    fn = _fn(_ALPHA_LAB, "_load_fundamentals")
    mods = _imports_inside(fn)
    assert not _goes_through_supply(fn), (
        f"★승급 조건이 충족됐다★ — 이제 공급 모듈을 지난다: {sorted(mods)}")
    assert "src.database" in mods, mods


def test_the_two_loaders_actually_differ():
    """★짝★ — 둘 다 지나거나 둘 다 안 지나면 이 프로그램의 전제가 무너진 것이다.

    *"비대칭이다"* 가 이 프로그램의 주장인데, 한쪽만 보면 그 주장을 증명한
    것이 아니다.
    """
    price = _goes_through_supply(_fn(_ALPHA_LAB, "_load_price_series"))
    fund = _goes_through_supply(_fn(_ALPHA_LAB, "_load_fundamentals"))
    assert price != fund, (price, fund)


# ── ★레지스트리 — "없다" 를 사유·막는 질문·승급 조건과 함께★ ─────────────

def test_the_registry_is_not_empty():
    assert UNSUPPLIED


def test_every_entry_says_why_and_what_it_blocks_and_when_it_promotes():
    """`version_registry.MissingAxis` 선례 — ★사유 없이 '없다' 고만 적으면
    갚을 수 없는 부채다★. 여기에 ★승급 조건★ 한 칸을 더했다."""
    for e in UNSUPPLIED:
        assert isinstance(e, UnsuppliedSignal)
        assert e.key and e.label
        assert len(e.reason) > 40, e.key
        assert len(e.blocks) > 20, e.key
        assert len(e.promotes_when) > 20, e.key


def test_the_alpha_fund_group_is_registered():
    keys = {e.key for e in UNSUPPLIED}
    assert "alpha_expr.fund" in keys, keys


def test_the_reason_names_the_table_it_actually_reads():
    """★실측한 것만 적는다★ — 표 이름이 사유에 있고, 그 표를 코드가 실제로 읽는다."""
    entry = next(e for e in UNSUPPLIED if e.key == "alpha_expr.fund")
    assert "financials_history" in entry.reason
    src = (_ROOT / _ALPHA_LAB).read_text(encoding="utf-8")
    assert "financials_history" in src


def test_the_reason_does_not_claim_an_origin():
    """변이 c·d — ★공급 모듈이 없다는 것과 테이블 이름을 출처라 부르는 것은 다르다★"""
    from src.engine.filter_ast import ORIGINS

    entry = next(e for e in UNSUPPLIED if e.key == "alpha_expr.fund")
    for name in ORIGINS:
        assert name not in entry.reason, name


def test_the_registry_does_not_mix_in_the_revision_axis():
    """변이 h — ★출처 축 ⟂ 개정 축★

    *"정정이 원본을 덮는다"* 는 사실이지만 **다른 축**이고 제 칸
    (`SignalDefinition.revision_policy`)이 있다. 출처 사유에 섞으면
    AV 가 `E2` 두 척도에서, AW 가 `source` 에서 겪은 것과 같은 모양이 된다.
    """
    entry = next(e for e in UNSUPPLIED if e.key == "alpha_expr.fund")
    for word in ("정정", "revised", "빈티지"):
        assert word not in entry.reason, word


# ── ★순수★ ───────────────────────────────────────────────────────────────

def test_the_module_imports_no_database_or_network():
    """계층 경계(CLAUDE.md §3) — 앞 세 프로그램과 같은 가드."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned


@pytest.mark.parametrize("attr", ["SUPPLY_PACKAGE", "UNSUPPLIED"])
def test_the_public_names_exist(attr):
    import src.domain.signal_supply as mod

    assert hasattr(mod, attr)
