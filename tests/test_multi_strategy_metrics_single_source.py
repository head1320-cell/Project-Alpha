"""멀티전략 요약의 지표 단일 출처 이전 — ★값은 그대로, 출처는 하나로★ (P1 잔여)
==============================================================================
P1 은 `allocation_backtest` 를 `risk_adjusted_ratios` 로 옮겼지만
`multi_strategy_backtest._compute_summary` 는 남겨 뒀다(범위: 매크로→포트폴리오
경로만). 그래서 무위험이 **0.025 vs 0.035**, `ddof` 가 **0 vs 1** 로 갈린 채였다.

★이전이 P1 시점에 불가능했던 이유★ — 이 모듈의 연율수익은 **기하 CAGR** 인데
`risk_adjusted_ratios` 는 산술 고정이었다. 옮기면 calmar 가 −0.470 → −0.515 로
바뀐다(실측). 그래서 먼저 단일 출처가 연율화 관례를 인자로 받게 만들고, 그 다음
이 모듈의 관례(rf 0.025 · ddof 0 · 기하)를 **그대로** 넘긴다.

★이전은 값을 바꾸지 않는다★ 아래 골든이 그것을 못 박는다.
"""

from __future__ import annotations

import os
import pathlib
import re
from types import SimpleNamespace

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.multi_strategy_backtest import MultiStrategyBacktester  # noqa: E402

CAP0 = 1_000_000.0

#: ★골든★ 이전 **전**에 실측한 값. 이전은 값을 바꾸지 않아야 한다.
GOLDEN = {
    "sharpe_ratio": 1.168,
    "calmar_ratio": 2.52,
    "annualized_return_pct": 21.26,
    "max_drawdown_pct": -8.43,
    "total_return_pct": 46.59,
}


def _records():
    """`_compute_summary` 가 읽는 속성만 채운 레코드."""
    src = pathlib.Path("src/engine/multi_strategy_backtest.py").read_text(
        encoding="utf-8")
    i = src.index("def _compute_summary")
    attrs = sorted(set(re.findall(r"\br\.([a-z_]+)", src[i:i + 4000])))
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0005, 0.010, 500)
    eq = CAP0 * np.cumprod(1 + rets)
    out = []
    for r, e in zip(rets, eq, strict=True):
        d = {a: 0.0 for a in attrs}
        d.update(portfolio_return=float(r), portfolio_equity=float(e),
                 regime=None, num_trades=0)
        out.append(SimpleNamespace(**d))
    return out


@pytest.fixture(scope="module")
def summary():
    return MultiStrategyBacktester._compute_summary(
        _records(), SimpleNamespace(initial_capital=CAP0))


@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_the_migration_did_not_change_any_number(summary, key):
    assert summary[key] == GOLDEN[key]


def test_the_summary_declares_the_convention_that_made_it(summary):
    """★그 수를 만든 관례를 달고 다녀야 한다★ — 이것이 없어서 0.025 와 0.035 가
    같은 이름으로 나란히 보고되고 있었다."""
    c = summary["convention"]
    assert c["risk_free"] == 0.025          # ★allocation_backtest 는 0.035 다★
    assert c["ddof"] == 0                   # ★allocation_backtest 는 1 이다★
    assert c["annualization"] == "geometric"
    assert c["starting_equity"] == CAP0
    assert c["periods_per_year"] == 252


def test_the_divergence_from_the_other_engine_is_a_convention_not_a_formula():
    """★P1 이 측정한 사실을 테스트로 남긴다★ 같은 계열·같은 공식인데 관례만
    다르면 값이 얼마나 갈리는가 — 이것이 단일 출처가 필요한 이유다."""
    from src.engine.quant_metrics import risk_adjusted_ratios
    recs = _records()
    rets = np.array([r.portfolio_return for r in recs])
    eq = np.array([r.portfolio_equity for r in recs])
    mine = risk_adjusted_ratios(rets, eq, risk_free=0.025, ddof=0,
                                annualization="geometric", starting_equity=CAP0)
    other = risk_adjusted_ratios(rets, eq, risk_free=0.035, ddof=1)   # 배분 엔진 관례
    assert mine["sharpe_ratio"] != other["sharpe_ratio"]
    assert mine["calmar_ratio"] != other["calmar_ratio"]


def test_the_summary_carries_full_precision_next_to_the_rounded_display(summary):
    """★A3 에서 물린 것★ 표시용 반올림 옆에 전정밀도를 함께 싣는다."""
    full = summary["sharpe_ratio_full"]
    assert full is not None
    assert round(full, 3) == summary["sharpe_ratio"]


def test_the_summary_does_not_recompute_sharpe_inline():
    """★구조★ 값 테스트로는 인라인 복사본을 잡을 수 없다(같은 수를 낸다)."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(
        inspect.getsource(MultiStrategyBacktester._compute_summary))
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "risk_adjusted_ratios" in called
    assert "0.025 / 252" not in src, "무위험을 여기서 다시 정의하고 있다"


# ══════════════════════════════════════════════════════════════════════════
# ★현금 버퍼는 비중으로 표현된다 — 두 번 세지 않는다★ (P4 잔여)
# ══════════════════════════════════════════════════════════════════════════

def test_the_cash_buffer_is_expressed_through_the_weights_not_a_side_variable():
    """★죽은 누산기를 되살리면 현금이 두 번 세어진다★

    `realism_engine` 은 `current_cash_buffer` 를 네 곳에서 대입하고 한 번도 읽지
    않았다. 경제적 효과는 이미 비중에 있다 — `invested_ratio =
    sum(current_weights.values())` 가 현금 이자와 미투자분을 함께 결정한다.
    누군가 "배선이 빠졌네" 하고 연결하면 비중으로 한 번, 버퍼로 또 한 번 세어진다.
    """
    src = pathlib.Path("src/engine/realism_engine.py").read_text(encoding="utf-8")
    assert "invested_ratio = sum(current_weights.values())" in src, \
        "현금 이자의 근거가 비중이 아니게 됐다 — 이 테스트가 낡았다"
    # 대입도 참조도 없어야 한다(주석의 설명은 남는다)
    assert "current_cash_buffer =" not in src
    assert "current_cash_buffer," not in src


def test_the_cash_yield_still_reads_the_invested_ratio():
    """★짝★ 위 테스트가 단순 문자열 부재만 보면 공허하다 — 실제로 그 값이
    현금수익 계산으로 들어가는지 본다."""
    import ast
    import textwrap

    import src.engine.realism_engine as re_mod
    tree = ast.parse(textwrap.dedent(
        pathlib.Path(re_mod.__file__).read_text(encoding="utf-8")))
    # `invested_ratio` 를 **키워드 인자로** 넘기는 호출이 있어야 한다
    passed = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              for k in n.keywords
              if k.arg == "invested_ratio" and isinstance(k.value, ast.Name)
              and k.value.id == "invested_ratio"]
    assert passed, "invested_ratio 가 현금수익 계산으로 넘어가지 않는다"
