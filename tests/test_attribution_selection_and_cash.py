"""AL2·AL3 — ★상수 0 을 걷어내고, 현금이자를 비용에서 떼어낸다★

## AL2 ★재료를 먼저 고친다★ (AB2 와 같은 모양)

`selection_effect=0` 이 두 생산자에 하드코딩돼 있었다. `column_coverage` 는
`pd.notna` 로 세므로 ★상수 0 도 "관측됨"★ 이 되고, `coverage_complete` 가
**거짓으로 참**이 되어 잔차가 `unexplained_pct` 대신 `interaction_pct`(복리 효과)
로 이름 붙었다. 저장소가 *"커버리지가 불완전하면 잔차를 복리라고 부르기를
거부한다"* 며 만든 바로 그 가드를, 하드코딩된 0 이 무력화하고 있었다.

★새 가드를 만들지 않는다★ — 재료가 `None` 이 되면 기존 기계가 제대로 작동한다.

## AL3 ★현금이자는 비용이 아니다★

`realism_engine:412` 이 `cost_effect + cash_yield` 를 한 칸에 넣고 화면이
"거래 비용" 이라 불렀다 — 부호도 성격도 반대다. 그리고 `multi_strategy_backtest`
는 현금 모델이 **아예 없어** 같은 칸을 다른 뜻으로 썼다.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.attribution_decomposer import (  # noqa: E402
    EFFECT_COLUMNS,
    AttributionDecomposer,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def daily(rows: list[dict]) -> pd.DataFrame:
    """일별 프레임 — 안 준 칸은 0.0(관측된 0)."""
    base = {**{e: 0.0 for e in EFFECT_COLUMNS}, "portfolio_return": 0.0,
            "netting_savings": 0.0, "turnover_pct": 0.0, "num_trades": 1,
            "rebalanced": 0, "regime": "GOLDILOCKS", "systemic_risk": 10.0}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["trade_date"] = pd.to_datetime(
        pd.date_range("2026-01-05", periods=len(df), freq="B"))
    return df


# ═══════════════════════════════════════════════════════════════════════════
# ①② ★거짓 완결성★ — 상수 0 이 사라지면 잔차의 이름이 바뀐다
# ═══════════════════════════════════════════════════════════════════════════

def test_an_unmeasured_selection_makes_the_coverage_incomplete():
    """★핵심★ 미측정이 `None` 이면 가드가 비로소 작동한다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "selection_effect": np.nan,
         "portfolio_return": 0.03, "cumulative_return": 3.0},
    ]))
    assert cum["coverage_complete"] is False
    assert cum["selection_effect_pct"] is None
    assert cum["interaction_pct"] is None, "복리라고 부르면 안 된다"
    assert cum["unexplained_pct"] is not None
    assert "selection_effect" in cum["unexplained_reason"]


def test_a_fully_measured_book_still_calls_the_residual_interaction():
    """★짝★ 언제나 불완전인 구현을 배제한다 — 여섯이 다 관측되면 복리다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "portfolio_return": 0.03,
         "cumulative_return": 3.0},
    ]))
    assert cum["coverage_complete"] is True
    assert cum["interaction_pct"] is not None
    assert cum["unexplained_pct"] is None


def test_a_constant_zero_would_have_faked_completeness():
    """★이 작업이 고친 사고를 그대로 재현한다★

    `0.0` 은 `notna` 라 커버리지가 1.0 으로 잡힌다 — 그래서 상수 0 을 싣던
    시절에는 `coverage_complete` 가 **거짓으로 참**이었다. 이 테스트는 그 메커니즘이
    여전히 그렇게 동작함을 못 박는다(그래서 **생산자가** 0 을 실으면 안 된다).
    """
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"selection_effect": 0.0, "portfolio_return": 0.03,
         "cumulative_return": 3.0},
    ]))
    assert cum["coverage_complete"] is True, "0 은 관측으로 세어진다 — 그것이 함정이었다"


# ═══════════════════════════════════════════════════════════════════════════
# ④ ★수치 불변★ — 0 을 빼도 합은 같다
# ═══════════════════════════════════════════════════════════════════════════

def test_dropping_the_constant_zero_does_not_move_the_decomposed_total():
    zeroed = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "selection_effect": 0.0,
         "portfolio_return": 0.03, "cumulative_return": 3.0}]))
    unmeasured = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "selection_effect": np.nan,
         "portfolio_return": 0.03, "cumulative_return": 3.0}]))
    assert (zeroed["total_decomposed_pct"]
            == pytest.approx(unmeasured["total_decomposed_pct"]))
    assert zeroed["actual_return_pct"] == unmeasured["actual_return_pct"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑤⑥⑩ ★현금이자는 제 칸을 갖는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_cash_effect_is_one_of_the_effect_columns():
    assert "cash_effect" in EFFECT_COLUMNS
    assert len(EFFECT_COLUMNS) == 6


def test_the_effect_columns_still_match_the_sentence_drivers():
    """★같은 것을 두 이름으로 부르지 않는다★ (기존 대조가 여섯으로 통과해야 한다)"""
    from src.domain.daily_explanation import STRATEGY_DRIVERS
    assert tuple(STRATEGY_DRIVERS) == tuple(EFFECT_COLUMNS)


def test_the_cash_effect_has_a_korean_label():
    from src.domain.daily_explanation import DRIVER_LABELS
    assert DRIVER_LABELS["cash_effect"] == "현금 이자"


def test_a_cash_effect_column_is_summed_like_the_others():
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"cash_effect": 0.0002, "portfolio_return": 0.0002,
         "cumulative_return": 0.02},
    ]))
    assert cum["cash_effect_pct"] == pytest.approx(0.02)


def test_an_unmeasured_cash_effect_is_none_not_zero():
    """`multi_strategy_backtest` 는 현금 모델이 없다 — ★0 이 아니라 미측정★."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"cash_effect": np.nan, "portfolio_return": 0.01,
         "cumulative_return": 1.0},
    ]))
    assert cum["cash_effect_pct"] is None
    assert cum["coverage_complete"] is False


# ═══════════════════════════════════════════════════════════════════════════
# ★생산자 트립와이어★ — 변이 a·g·h·i 를 잡는다
# ═══════════════════════════════════════════════════════════════════════════

def _tree(rel: str) -> ast.Module:
    return ast.parse((_ROOT / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel", [
    "src/engine/realism_engine.py",
    "src/engine/multi_strategy_backtest.py",
])
def test_no_producer_hardcodes_selection_effect_to_zero(rel):
    """★상수가 관측 행세를 하지 못하게★ — 변이 a 를 잡는다."""
    for node in ast.walk(_tree(rel)):
        if (isinstance(node, ast.keyword) and node.arg == "selection_effect"
                and isinstance(node.value, ast.Constant)
                and node.value.value in (0, 0.0)):
            raise AssertionError(f"{rel} 이 selection_effect 에 상수 0 을 싣는다")


def test_the_realism_engine_does_not_fold_cash_into_cost():
    """★현금이자가 비용 칸으로 되돌아가지 못하게★ — 변이 g 를 잡는다."""
    src = (_ROOT / "src/engine/realism_engine.py").read_text(encoding="utf-8")
    assert "cost_effect=cost_effect + cash_yield" not in src
    assert "cost_effect=cost_effect," in src, "비용 칸이 순수 비용이어야 한다"
    assert "cash_effect=cash_yield," in src, "현금이자가 제 칸에 실려야 한다"


def test_the_realism_net_return_still_includes_both():
    """★수치 불변★ — 분리는 표시를 가르는 것이지 수익률을 바꾸는 것이 아니다.

    변이 i(`net_return` 에서 `cash_yield` 를 뺀다)를 잡는다.
    """
    src = (_ROOT / "src/engine/realism_engine.py").read_text(encoding="utf-8")
    assert "net_return = portfolio_ret + cost_effect + cash_yield" in src


def test_the_multi_strategy_engine_declares_cash_as_unmeasured():
    """★그 엔진엔 현금 모델이 없다★ — 0 을 실으면 '이자가 0 이었다' 가 된다."""
    src = (_ROOT / "src/engine/multi_strategy_backtest.py").read_text(encoding="utf-8")
    assert "cash_effect=None" in src


def test_this_guard_is_not_vacuous():
    """★검사의 검사★ — 두 생산자가 실제로 레코드를 만들어야 뜻이 있다."""
    for rel in ("src/engine/realism_engine.py",
                "src/engine/multi_strategy_backtest.py"):
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert "selection_effect=" in src and "cost_effect=" in src, rel


# ═══════════════════════════════════════════════════════════════════════════
# ⑪ ★DB 쓰기가 DEFAULT 0 에 기대지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_daily_insert_names_every_effect_column():
    """DDL 의 `DEFAULT 0` 은 ★그 자체가 거짓 생성기★ 다 — 명시적으로 실어야 한다."""
    src = (_ROOT / "src/engine/multi_strategy_backtest.py").read_text(encoding="utf-8")
    i = src.index("INSERT INTO multibacktest_daily")
    stmt = src[i:i + 900]
    for col in EFFECT_COLUMNS:
        assert col in stmt, f"{col} 을 INSERT 가 안 싣는다 — DEFAULT 에 기대고 있다"


# ═══════════════════════════════════════════════════════════════════════════
# ★네 번째 자리★ — 월간/분기 표가 미상을 다시 0 으로 만들고 있었다
#
# 누적만 고치면 두 화면이 서로 다른 말을 한다: 누적은 "재지 않았다", 월간 표는
# `0.0`. `_aggregate_period` 의 `.fillna(0)` 과 `_safe` 의 `return 0.0` 이
# 그 자리였다 — ★미상 ≠ 0★ 을 세 번째로 어긴 곳이다.
# ═══════════════════════════════════════════════════════════════════════════

def test_the_monthly_table_keeps_an_unmeasured_effect_unmeasured():
    rows = AttributionDecomposer._aggregate_period(daily([
        {"selection_effect": np.nan, "portfolio_return": 0.01,
         "cumulative_return": 1.0},
        {"selection_effect": np.nan, "portfolio_return": 0.01},
    ]), "ME")
    assert rows, "집계가 비었다 — 이 검사가 공허하다"
    assert rows[0]["selection_effect_pct"] is None, "미상이 다시 0 이 됐다"


def test_the_monthly_table_still_reports_a_measured_zero_as_zero():
    """★짝★ 관측된 0 은 0 으로 남아야 한다 — 전부 `None` 인 구현을 배제한다."""
    rows = AttributionDecomposer._aggregate_period(daily([
        {"netting_effect": 0.0, "portfolio_return": 0.01,
         "cumulative_return": 1.0},
    ]), "ME")
    assert rows[0]["netting_effect_pct"] == 0.0


def test_the_monthly_table_carries_the_cash_effect():
    rows = AttributionDecomposer._aggregate_period(daily([
        {"cash_effect": 0.0002, "portfolio_return": 0.0002,
         "cumulative_return": 0.02},
    ]), "ME")
    assert rows[0]["cash_effect_pct"] == pytest.approx(0.02)


# ═══════════════════════════════════════════════════════════════════════════
# ★세 번째 상수★ — DB 행 빌더가 레코드를 무시하고 0 을 썼다
#
# 레코드를 고쳐도 이 빌더가 `"se": 0` 으로 덮어써서 DB 에는 여전히 거짓 관측이
# 들어갔다. ★손으로 찾았지만 테스트로 못 박지 않아 변이 `m` 이 살아남았다.★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_daily_row_builder_reads_the_record_not_a_constant():
    """빌더가 효과 칸에 **상수**를 쓰지 않는다."""
    src = (_ROOT / "src/engine/multi_strategy_backtest.py").read_text(encoding="utf-8")
    i = src.index("daily_rows.append({")
    block = src[i:src.index("})", i)]
    for key in ('"se"', '"ae"', '"me"', '"ne"', '"ce"', '"cash"'):
        assert key in block, f"{key} 가 행 빌더에 없다"
    tree = ast.parse("x = {" + block.split("daily_rows.append({", 1)[-1] + "}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and k.value in ("se", "ce", "cash")
                    and isinstance(v, ast.Constant)):
                raise AssertionError(
                    f'행 빌더가 "{k.value}" 에 상수 {v.value!r} 을 쓴다 — '
                    "레코드가 말하는 것을 실어야 한다")


def test_that_row_builder_guard_is_not_vacuous():
    """★검사의 검사★ — 빌더 블록을 실제로 찾았는지."""
    src = (_ROOT / "src/engine/multi_strategy_backtest.py").read_text(encoding="utf-8")
    assert "daily_rows.append({" in src
