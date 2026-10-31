"""AH4 — ★주석을 트립와이어로★ 재무 스냅샷 방송이 조용히 늘어나지 않게.

## 무엇이 문제였나

`score_factors.py:151,156` 은 재무값을 이렇게 깐다:

    pd.Series(np.full(n, v, dtype=f32), index=idx)

★오늘의 ROE/PER/PBR 를 과거 전 구간에 방송한다.★ 그러면 그 조건은 창 전체에서
값이 변하지 않아 항상 참이거나 항상 거짓이 되고, 그것이 look-ahead 의 관측 가능한
형태다(`thesis_backtest` 가 이미 그렇게 적어 뒀다).

엔진은 이것을 피한다 — `kis_backtest_engine.py:837` 이 `build_score_panels(ohlcv_map)`
을 **재무 없이** 부른다. 그런데 ★그 회피는 주석이지 가드가 아니었다.★ 그리고
`condition_strategy.py:568` 은 옵트인 플래그가 켜지면 실제로 재무를 넘긴다.

이 파일이 거는 것:
  · 엔진의 재편입 패널 호출은 **재무를 넘기지 않는다**(현재 계약을 못 박음)
  · 재무를 넘기는 호출은 **옵트인 플래그 뒤에 있어야 한다**
  · 그렇게 돈 실행은 결과가 **그렇다고 말한다**(배선은 별도 파일이 건다)
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★백테스트 루프에서 도달하는 모듈★ — 여기서 재무를 넘기면 방송이 백테스트에 든다.
_ENGINE_MODULES = ("src/kis_backtest_engine.py",)

#: 옵트인 뒤에서만 재무를 넘겨도 되는 모듈.
_OPT_IN_MODULES = ("src/kis_strategies/condition_strategy.py",)

_FUNC = "build_score_panels"
_OPT_IN_FLAG = "allow_snapshot_fundamentals"


def _calls_with_fundamentals(source: str) -> list[int]:
    """`build_score_panels(...)` 에 **두 번째 인자**(재무)를 넘기는 호출의 줄 번호."""
    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != _FUNC:
            continue
        passes_funds = len(node.args) >= 2 or any(
            kw.arg == "fundamentals_map" for kw in node.keywords)
        if passes_funds:
            out.append(node.lineno)
    return out


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# ① ★엔진은 재무를 넘기지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rel", _ENGINE_MODULES)
def test_the_engine_never_broadcasts_fundamentals(rel):
    offenders = _calls_with_fundamentals(_read(rel))
    assert not offenders, (
        f"{rel}:{offenders} 이 `{_FUNC}` 에 재무를 넘긴다 — 오늘의 ROE/PER/PBR 가 "
        f"과거 전 구간에 방송된다. 이 호출은 지금까지 주석으로만 막혀 있었다.")


@pytest.mark.parametrize("rel", _ENGINE_MODULES)
def test_the_engine_really_calls_it(rel):
    """★짝★ 호출이 아예 없으면 ①은 언제나 통과한다 — 공허한 검사 배제."""
    assert _FUNC in _read(rel), f"{rel} 이 `{_FUNC}` 을 안 부른다 — ①이 공허하다"


# ═══════════════════════════════════════════════════════════════════════════
# ② 재무를 넘기는 호출은 ★옵트인 뒤에★
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rel", _OPT_IN_MODULES)
def test_a_broadcasting_call_sits_behind_the_opt_in(rel):
    source = _read(rel)
    calls = _calls_with_fundamentals(source)
    assert calls, f"{rel} 이 재무를 안 넘긴다 — 이 검사가 공허하다"
    assert _OPT_IN_FLAG in source, (
        f"{rel} 이 재무를 넘기면서 `{_OPT_IN_FLAG}` 옵트인을 갖지 않는다")


def test_the_opt_in_defaults_to_off():
    """★기본값이 켜져 있으면 옵트인이 아니다★"""
    tree = ast.parse(_read("src/kis_strategies/condition_strategy.py"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args.args + node.args.kwonlyargs
        defaults = list(node.args.defaults) + list(node.args.kw_defaults)
        for a, d in zip(args[-len(defaults):] if defaults else [], defaults):
            if a.arg == _OPT_IN_FLAG and isinstance(d, ast.Constant):
                found.append(d.value)
    assert found, "옵트인 인자를 못 찾았다 — 검출기가 낡았다"
    assert all(v is False for v in found), f"옵트인 기본값이 켜져 있다: {found}"


# ═══════════════════════════════════════════════════════════════════════════
# ③ ★테스트의 테스트★ — 검출기가 실제로 검출하는가
# ═══════════════════════════════════════════════════════════════════════════

def test_the_detector_catches_a_positional_call():
    assert _calls_with_fundamentals("build_score_panels(ohlcv_map, fund_map)") == [1]


def test_the_detector_catches_a_keyword_call():
    assert _calls_with_fundamentals(
        "build_score_panels(ohlcv_map, fundamentals_map=f)") == [1]


def test_the_detector_catches_an_attribute_call():
    assert _calls_with_fundamentals("sf.build_score_panels(m, f)") == [1]


def test_the_detector_does_not_cry_wolf():
    """★짝★ 재무 없는 호출을 잡으면 엔진이 영영 빨개진다."""
    assert _calls_with_fundamentals("build_score_panels(ohlcv_map)") == []
    assert _calls_with_fundamentals("other_function(a, b)") == []


def test_the_module_lists_are_not_empty():
    """★공허한 하네스는 증거가 아니다★ (AG 변이 `i` 의 교훈)"""
    assert _ENGINE_MODULES and _OPT_IN_MODULES
    for rel in _ENGINE_MODULES + _OPT_IN_MODULES:
        assert (_ROOT / rel).exists(), f"{rel} 이 없다 — 목록이 낡았다"
