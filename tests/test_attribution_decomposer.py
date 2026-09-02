"""귀속 분해기 ★특성화★ — 프로덕션인데 테스트가 0개였다 (P4-a)
==============================================================================
`src/engine/attribution_decomposer.py` 는 `src/api/stage11_routes.py:139` 에서
호출되는 **프로덕션 경로**인데 이 모듈을 import 하는 테스트가 하나도 없었다.
이름이 비슷한 `test_attribution*.py` 5개는 전부 `attribution.py` ·
`backtest_attribution.py` · `attribution_routes.py` 를 본다 — 있는 것처럼
보였을 뿐이다.

★이 파일은 먼저 **현행 동작을 그대로** 못 박는다★ — 침묵 폴백까지 포함해서다.
고치기 전에 고정해 두지 않으면 무엇이 왜 바뀌었는지 나중에 구분할 수 없다
(B1 국면 적응형 배분기에서 쓴 것과 같은 순서 — `0d2eac3`).

현행 동작을 **승인**한다는 뜻이 아니다. `★결함★` 이 붙은 테스트는 다음 커밋에서
의도적으로 뒤집힌다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.attribution_decomposer import (  # noqa: E402
    AttributionDecomposer,
    _sanitize_for_json,
)

EFFECTS = ("allocation_effect", "selection_effect", "macro_effect",
           "netting_effect", "cost_effect")


def daily(rows: list[dict]) -> pd.DataFrame:
    """일별 프레임 — 안 준 칸은 0.0, `trade_date` 는 연속 영업일."""
    base = {**{e: 0.0 for e in EFFECTS}, "portfolio_return": 0.0,
            "netting_savings": 0.0, "turnover_pct": 0.0, "num_trades": 1,
            "rebalanced": 0, "regime": "GOLDILOCKS", "systemic_risk": 10.0}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["trade_date"] = pd.to_datetime(
        pd.date_range("2026-01-05", periods=len(df), freq="B"))
    return df


# ── 정상 경로 — 이건 바뀌면 안 된다 ───────────────────────────────────────
def test_the_effects_are_summed_and_scaled_to_percent():
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "macro_effect": 0.02,
         "portfolio_return": 0.03, "cumulative_return": 3.0},
    ]))
    assert cum["allocation_effect_pct"] == 1.0
    assert cum["macro_effect_pct"] == 2.0
    assert cum["actual_return_pct"] == 3.0


def test_the_waterfall_closes_on_the_actual_return():
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": 0.01, "macro_effect": 0.02,
         "portfolio_return": 0.03, "cumulative_return": 3.5},
    ]))
    wf = AttributionDecomposer._build_waterfall(cum)
    assert wf[-1]["step"] == "Actual Total"
    assert wf[-1]["running_total"] == pytest.approx(cum["actual_return_pct"], abs=1e-9)


def test_an_empty_frame_yields_nothing_rather_than_a_fabricated_row():
    assert AttributionDecomposer._cumulative_attribution(pd.DataFrame()) == {}
    assert AttributionDecomposer._build_waterfall({}) == []
    assert AttributionDecomposer._aggregate_period(pd.DataFrame(), "ME") == []
    assert AttributionDecomposer._regime_breakdown(pd.DataFrame()) == []


def test_the_regime_breakdown_already_reports_unknown_systemic_risk_as_none():
    """★모듈 안에 정답의 선례가 이미 있다★ — `avg_systemic_risk` 는 NaN 이면
    `None` 을 낸다. 바로 아래 `sharpe` 는 그렇지 않다(다음 테스트)."""
    df = daily([{"portfolio_return": 0.01, "systemic_risk": np.nan},
                {"portfolio_return": -0.01, "systemic_risk": np.nan}])
    assert AttributionDecomposer._regime_breakdown(df)[0]["avg_systemic_risk"] is None


# ── ★결함★ 현행 동작 — 다음 커밋에서 뒤집힌다 ────────────────────────────
def test_a_missing_macro_row_is_currently_counted_as_zero():
    """★결함★ 미상이 0 으로 둔갑한다 — "매크로 기여 미상" 이 "기여 0" 이 된다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"macro_effect": 0.02, "portfolio_return": 0.02, "cumulative_return": 4.0},
        {"macro_effect": np.nan, "portfolio_return": 0.02},
    ]))
    assert cum["macro_effect_pct"] == 2.0          # 관측된 한 행만의 합인데
    assert "macro_effect_coverage" not in cum      # 몇 행을 봤는지는 안 적힌다


def test_the_residual_currently_absorbs_the_missing_amount():
    """★가장 깊은 결함★ 잔차가 미상을 세탁한다.

    `interaction = actual − sum_factors` 이므로 NaN→0 으로 줄어든 만큼을 잔차가
    **정확히** 흡수한다. 워터폴은 여전히 완벽하게 닫힌다 — ★리포트는 틀렸을 때
    오히려 자기일관적이다.★ 그래서 값만 `None` 으로 바꾸면 안 고쳐진다.
    """
    known = daily([{"macro_effect": 0.02, "portfolio_return": 0.02,
                    "cumulative_return": 5.0}])
    holed = daily([{"macro_effect": 0.02, "portfolio_return": 0.02,
                    "cumulative_return": 5.0},
                   {"macro_effect": np.nan, "portfolio_return": 0.0,
                    "cumulative_return": 5.0}])
    a = AttributionDecomposer._cumulative_attribution(known)
    b = AttributionDecomposer._cumulative_attribution(holed)

    # ★두 리포트가 완전히 같다★ — 관측되지 않은 하루가 있었다는 사실이 리포트
    # 어디에도 남지 않는다. "그날은 데이터가 없었다" 와 "그날 기여가 정확히 0
    # 이었다" 를 소비자가 구분할 방법이 없다.
    assert a["macro_effect_pct"] == b["macro_effect_pct"]
    assert a["interaction_pct"] == b["interaction_pct"]
    # 그리고 워터폴은 구멍이 있든 없든 똑같이 완벽하게 닫힌다 — 이것이 세탁이다
    for cum in (a, b):
        wf = AttributionDecomposer._build_waterfall(cum)
        assert wf[-1]["running_total"] == pytest.approx(
            cum["actual_return_pct"], abs=1e-9)
    assert "unexplained_pct" not in b


def test_nan_is_currently_turned_into_zero_not_null():
    """★결함★ 미상을 제조한다. NaN 은 0 이 아니라 미상이다."""
    assert _sanitize_for_json({"x": float("nan")}) == {"x": 0.0}
    assert _sanitize_for_json({"x": float("inf")}) == {"x": 0.0}
    assert _sanitize_for_json([float("nan")]) == [0.0]


def test_zero_volatility_currently_reports_sharpe_zero():
    """★결함★ 변동성이 0 이면 샤프는 0 이 아니라 미상이다."""
    df = daily([{"portfolio_return": 0.01}, {"portfolio_return": 0.01}])
    assert AttributionDecomposer._regime_breakdown(df)[0]["sharpe"] == 0


def test_a_zero_contribution_currently_triggers_a_silent_recompute():
    """★결함★ "기여가 0" 과 "기여가 미상" 을 값으로 구분하고 있다."""
    sdf = pd.DataFrame([
        {"strategy_id": 1, "weight": 0.5, "macro_adjustment": 0.0,
         "contribution": 0.0, "strategy_return": 0.04},
    ])
    out = AttributionDecomposer(None)._strategy_contribution(sdf, {1: "A"})
    # 기여가 진짜 0 인데도 strategy_return 으로 재계산해 2.0 을 만들어 낸다
    assert out[0]["cumulative_contribution_pct"] == 2.0


# ── 적재 경로 — sqlite 로 진짜 SQL 을 태운다 ──────────────────────────────
def _sqlite_engine(with_rows: bool = True, with_strategy_table: bool = True):
    from sqlalchemy import create_engine
    from sqlalchemy import text as _t
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(_t("CREATE TABLE multibacktest_runs (id INTEGER, run_name TEXT,"
                     " start_date TEXT, end_date TEXT, allocation_method TEXT,"
                     " total_return_pct REAL, annualized_return_pct REAL,"
                     " sharpe_ratio REAL, max_drawdown_pct REAL)"))
        cols = ", ".join(f"{e} REAL" for e in EFFECTS)
        c.execute(_t(f"CREATE TABLE multibacktest_daily (run_id INTEGER,"
                     f" trade_date TEXT, portfolio_return REAL,"
                     f" cumulative_return REAL, netting_savings REAL,"
                     f" turnover_pct REAL, num_trades INTEGER,"
                     f" rebalanced INTEGER, regime TEXT, systemic_risk REAL,"
                     f" {cols})"))
        c.execute(_t("CREATE TABLE multibacktest_strategy_daily (run_id INTEGER,"
                     " trade_date TEXT, strategy_id INTEGER, weight REAL,"
                     " macro_adjustment REAL, contribution REAL,"
                     " strategy_return REAL)"))
        if with_strategy_table:
            c.execute(_t("CREATE TABLE strategies (id INTEGER, name TEXT)"))
            c.execute(_t("INSERT INTO strategies VALUES (7, '실제 전략명')"))
        c.execute(_t("INSERT INTO multibacktest_runs VALUES (1, 'r', '2026-01-01',"
                     " '2026-02-01', 'hrp', 5.0, 5.0, 1.0, -2.0)"))
        if with_rows:
            c.execute(_t("INSERT INTO multibacktest_daily VALUES (1, '2026-01-05',"
                         " 0.02, 5.0, 0.0, 0.0, 1, 0, 'GOLDILOCKS', 10.0,"
                         " 0.01, 0.0, 0.02, 0.0, 0.0)"))
            c.execute(_t("INSERT INTO multibacktest_strategy_daily VALUES"
                         " (1, '2026-01-05', 7, 0.5, 0.0, 0.01, 0.02)"))
    return eng


class _ExplodingEngine:
    """연결 자체가 실패하는 엔진 — 적재 실패를 흉내낸다."""

    def connect(self):
        raise RuntimeError("connection refused")


def test_a_run_with_rows_decomposes():
    out = AttributionDecomposer(_sqlite_engine()).decompose(1)
    assert out["available"] is True
    assert out["cumulative"]["macro_effect_pct"] == 2.0
    assert out["strategy_contribution"][0]["strategy_name"] == "실제 전략명"


def test_a_load_failure_is_currently_indistinguishable_from_no_rows():
    """★결함★ 적재가 **실패**했는데 리포트는 "데이터 없음" 이라고 말한다.

    원인이 다르면 다르게 말해야 한다 — 없는 것과 못 읽은 것은 다른 사실이다.
    """
    broke = AttributionDecomposer(_ExplodingEngine()).decompose(1)
    empty = AttributionDecomposer(_sqlite_engine(with_rows=False)).decompose(1)
    assert broke["available"] is False and empty["available"] is False
    assert broke["message"] == empty["message"]     # 구분이 안 된다
    assert "없음" in broke["message"]                # 실패인데 "없음" 이라 한다


def test_a_name_lookup_failure_currently_fabricates_a_name():
    """★결함★ 이름 조회가 실패했는데 이름을 지어낸다.

    `stock_master` 에서 `"Unknown Corp"` 를 금지한 것과 같은 형태다 — 미상인
    이름은 이름이 아니다.
    """
    eng = _sqlite_engine(with_strategy_table=False)     # strategies 테이블 없음
    out = AttributionDecomposer(eng).decompose(1)
    assert out["strategy_contribution"][0]["strategy_name"] == "Strategy #7"
