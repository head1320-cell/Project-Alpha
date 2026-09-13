"""일별 귀인이 ★미상을 0 으로 접지 않는다★ (AB2)

설계: `docs/plans` AB

## 왜 이 파일이 있나

`attribution_decomposer` 의 **누적** 경로는 `column_coverage`/`sum_known` 으로
*"몇 행을 실제로 봤는가"* 를 재고 한 행도 못 봤으면 `None` 을 낸다. 그 함수의
독스트링이 이유를 적어 두었다 — *"`fillna(0)` 은 '안 본 행' 과 '0 인 행' 을 같은
자리에 쓴다."*

★그런데 **일별** 경로는 그 규율 밖이었다★ — `float(r["allocation_effect"] or 0)`.
한 파일 안에서 한쪽만 미상을 접고 있었다. 소비자는 실측 **0건**이라(백엔드·프런트·
테스트 전부) 아무도 보지 못했는데, 일일 설명 엔진(AB)이 **첫 소비자**가 된다.
0 으로 접힌 값을 문장으로 만들면 *"배분 효과가 0 이었습니다"* 라는 없는 사실을
말하게 되므로, 설명을 세우기 **전에** 재료를 고친다.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pandas as pd

from src.engine.attribution_decomposer import EFFECT_COLUMNS, AttributionDecomposer


def _daily(rows: list[dict]):
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return AttributionDecomposer._daily_attribution(df)


_FULL = {c: 0.001 for c in EFFECT_COLUMNS}


def _row(date: str, **over):
    return {"trade_date": date, "portfolio_return": 0.004,
            "regime": "GOLDILOCKS", **_FULL, **over}


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 골든 — `None` 은 `None` 으로 남는다
# ═══════════════════════════════════════════════════════════════════════════
def test_an_unobserved_effect_stays_none():
    """★미상 ≠ 0★ 관측되지 않은 효과를 0 으로 적으면 "효과가 없었다" 가 된다."""
    out = _daily([_row("2026-09-11", macro_effect=None)])
    assert out[0]["macro_effect"] is None, "미상을 0 으로 접었습니다"
    assert out[0]["allocation_effect"] == 0.1, "관측된 값까지 잃었습니다"


def test_an_observed_zero_is_still_zero():
    """★짝★ 진짜 0 은 0 이다 — 항상-None 구현을 배제한다."""
    out = _daily([_row("2026-09-11", macro_effect=0.0)])
    assert out[0]["macro_effect"] == 0.0


def test_nan_is_treated_as_unobserved():
    """DB 에서 온 `NaN` 도 미상이다 — `None` 만 보면 절반을 놓친다."""
    out = _daily([_row("2026-09-11", netting_effect=float("nan"))])
    assert out[0]["netting_effect"] is None


def test_every_effect_key_is_present_even_when_unknown():
    """★키를 빼지 않는다★ — 빠지면 소비자가 `.get()` 으로 읽다가 0 으로 읽는다."""
    out = _daily([_row("2026-09-11", **{c: None for c in EFFECT_COLUMNS})])
    for col in EFFECT_COLUMNS:
        assert col in out[0], col
        assert out[0][col] is None


def test_the_row_carries_its_coverage():
    """★그 행에서 몇 축을 봤는가★ — 설명이 잔차의 종류를 가르는 근거다."""
    out = _daily([_row("2026-09-11", macro_effect=None, netting_effect=None)])
    cov = out[0]["coverage"]
    assert cov["n_known"] == 3 and cov["n_total"] == len(EFFECT_COLUMNS)
    assert cov["complete"] is False
    assert sorted(cov["missing"]) == ["macro_effect", "netting_effect"]


def test_a_complete_row_says_so():
    out = _daily([_row("2026-09-11")])
    cov = out[0]["coverage"]
    assert cov["complete"] is True and cov["missing"] == []


def test_portfolio_return_is_not_folded_either():
    out = _daily([_row("2026-09-11", portfolio_return=None)])
    assert out[0]["portfolio_return"] is None


# ═══════════════════════════════════════════════════════════════════════════
# ⑨⑩ ★AST 트립와이어★ — `or 0` 이 다시 생기면 잡는다
# ═══════════════════════════════════════════════════════════════════════════
def _or_zero_lines(source: str, func: str) -> list[int]:
    """`x or 0` / `x or 0.0` 꼴이 함수 안에 있으면 그 줄 번호."""
    tree = ast.parse(source)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == func), None)
    if fn is None:
        return []
    bad: list[int] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            for value in node.values[1:]:
                if (isinstance(value, ast.Constant)
                        and isinstance(value.value, (int, float))
                        and not isinstance(value.value, bool)
                        and value.value == 0):
                    bad.append(node.lineno)
    return bad


def test_the_daily_path_has_no_or_zero():
    """⑨ ★미상을 접는 관용구가 다시 들어오면 여기서 멈춘다★"""
    from src.engine import attribution_decomposer
    src = pathlib.Path(inspect.getsourcefile(attribution_decomposer)).read_text(
        encoding="utf-8")
    bad = _or_zero_lines(src, "_daily_attribution")
    assert not bad, f"`or 0` 이 일별 경로에 있습니다(줄): {bad}"


def test_the_or_zero_scanner_actually_scans():
    """⑩ ★테스트의 테스트★ — 가짜 소스에 넣으면 잡는가."""
    fake = '''
def _daily_attribution(df):
    return [{"a": float(r["x"] or 0), "b": float(r["y"] or 0.0)} for r in df]
'''
    assert len(_or_zero_lines(fake, "_daily_attribution")) == 2

    good = '''
def _daily_attribution(df):
    return [{"a": _num(r["x"]), "b": _num(r["y"])} for r in df]
'''
    assert not _or_zero_lines(good, "_daily_attribution"), "짝: 멀쩡한 소스를 잡았습니다"


def test_the_scanner_does_not_flag_a_legitimate_or_default():
    """★`or "unknown"` 같은 문자열 기본값은 미상 접기가 아니다★ — 오탐 배제."""
    fine = '''
def _daily_attribution(df):
    return [{"regime": r["regime"] or "unknown"} for r in df]
'''
    assert not _or_zero_lines(fine, "_daily_attribution")


def test_the_scan_target_exists():
    """★공허 배제★ 함수 이름이 바뀌면 위 검사가 조용히 0건이 된다."""
    from src.engine import attribution_decomposer
    src = pathlib.Path(inspect.getsourcefile(attribution_decomposer)).read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_daily_attribution" in names, "검사 대상 함수가 사라졌습니다"
