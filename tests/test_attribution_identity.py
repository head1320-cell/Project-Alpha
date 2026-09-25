"""BH2 · 귀인 항등식 — ★분해는 수익률 항등식을 데이터로 검증한다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-bh-safety-attribution-regime-design.md` §4.2 ·
대상 `src/engine/attribution_decomposer.py` · `multi_strategy_backtest.py`(기록·저장) ·
`src/domain/daily_explanation.py` · `src/engine/daily_explain_backtest.py`

## 항등식 (엔진 실측)

    net_t = EW_t + alloc_t + cost_t (+ cash_t, realism)
    EW_t    = 그날 전략 수익률의 단순평균           (동일가중 기준)
    alloc_t = Σ (w_i − 1/n) · r_i                  (배분 효과)

## 무엇이 틀렸었나

- 기준을 0 으로 하드코딩해 **EW 수익 전체를 잔차가 흡수**했다.
- 수익률에 없는 **네팅을 '청산 효과' 스텝으로 더했다**(잔차가 정확히 그만큼 줄어 차트는
  닫혔다 — 틀렸을 때 오히려 자기일관적이었다).
- 매크로 조정(이미 가중 안)을 따로 더할 자리였고, 현금 스텝이 없었다.
- 저장이 `strategy_return`·`contribution`·`macro_adjustment` 에 **상수 0** 을 썼다.

## 거는 것

- 항등식이 성립하면 워터폴은 `동일가중 기준 → 배분 → 비용 → (현금) → 복리(계산값) → 실제`
  로 **닫힌다**(잔차 ≈ 0). 복리는 `∏(1+r) − 1 − Σr` 로 **계산된** 값이다.
- 네팅은 값이 있어도 스텝이 아니다(보고 전용) — ★짝★ 네팅이 수익률에 들어간 데이터면
  항등식이 깨졌다고 말한다.
- 기준이 없는 옛 실행은 "미설명" + 사유.
- 현금이 None 이고 항등식이 현금 없이 닫히면 현금은 **이 엔진에 없는 축**(미상 아님).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.attribution_decomposer import (  # noqa: E402
    IDENTITY_DRIVERS,
    AttributionDecomposer,
)
from tests.test_strategy_registry import _registry, _req, _stored_run, db, market  # noqa: E402,F401


def frame(rows: list[dict], *, with_baseline: bool = True) -> pd.DataFrame:
    """항등식을 지키는 일별 프레임 — ★`portfolio_return` 을 드라이버 합으로 만든다★

    `net` 을 따로 주면 그 값이 그대로 쓰인다(항등식을 일부러 깨는 짝 테스트용).
    """
    out = []
    for r in rows:
        ew = r.get("baseline_effect", 0.0)
        alloc = r.get("allocation_effect", 0.0)
        cost = r.get("cost_effect", 0.0)
        cash = r.get("cash_effect")
        net = r.get("net", ew + alloc + cost + (cash or 0.0))
        row = {"portfolio_return": net, "allocation_effect": alloc,
               "cost_effect": cost, "cash_effect": cash,
               "selection_effect": None, "macro_effect": r.get("macro_effect", 0.0),
               "netting_effect": r.get("netting_effect", 0.0),
               "netting_savings": r.get("netting_savings", 0.0),
               "turnover_pct": 0.0, "num_trades": 0, "rebalanced": 0,
               "regime": None, "systemic_risk": None}
        if with_baseline:
            row["baseline_effect"] = ew
        out.append(row)
    df = pd.DataFrame(out)
    eq = np.cumprod(1 + df["portfolio_return"].astype(float))
    df["cumulative_return"] = (eq - 1) * 100
    df["trade_date"] = pd.to_datetime(pd.date_range("2026-01-05", periods=len(df), freq="B"))
    return df


_ROWS = [
    {"baseline_effect": 0.010, "allocation_effect": 0.002, "cost_effect": -0.0005},
    {"baseline_effect": -0.004, "allocation_effect": 0.001},
    {"baseline_effect": 0.006, "allocation_effect": -0.003, "cost_effect": -0.0002},
]


def _cum(df):
    return AttributionDecomposer._cumulative_attribution(df)


# ── 항등식이 닫힌다 ──────────────────────────────────────────────────────

def test_the_identity_holds_and_the_waterfall_closes_on_the_actual_return():
    df = frame(_ROWS)
    cum = _cum(df)
    assert cum["identity"]["holds"] is True
    assert cum["identity"]["max_abs_gap"] < 1e-12
    wf = AttributionDecomposer._build_waterfall(cum)
    steps = [w["step"] for w in wf]
    assert steps == ["Baseline", "Allocation Effect", "Transaction Cost",
                     "Compounding", "Actual Total"], steps
    base = wf[0]
    assert base["label"] == "동일가중 기준"
    assert base["value"] == pytest.approx(sum(r["baseline_effect"] for r in _ROWS) * 100,
                                          abs=1e-3)
    for prev, cur in zip(wf, wf[1:-1]):
        assert cur["running_total"] == pytest.approx(prev["running_total"] + cur["value"],
                                                     abs=1e-6)
    assert wf[-2]["running_total"] == pytest.approx(wf[-1]["running_total"], abs=1e-6)


def test_compounding_is_computed_not_absorbed():
    """복리 스텝 = `∏(1+r) − 1 − Σr` (%) — ★잔차가 아니라 계산값★."""
    df = frame(_ROWS)
    r = df["portfolio_return"].astype(float)
    expect = (math.prod(1 + x for x in r) - 1 - r.sum()) * 100
    cum = _cum(df)
    assert cum["compounding_pct"] == pytest.approx(expect, abs=1e-9)
    assert cum["interaction_pct"] == pytest.approx(expect, abs=1e-6)
    assert cum["unexplained_pct"] is None


# ── 네팅은 스텝이 아니다 ─────────────────────────────────────────────────

def test_netting_is_reported_but_never_a_step():
    rows = [{**r, "netting_effect": 0.0007, "netting_savings": 700.0} for r in _ROWS]
    cum = _cum(frame(rows))
    assert cum["identity"]["holds"] is True
    wf = AttributionDecomposer._build_waterfall(cum)
    assert not any("Netting" in w["step"] or "청산" in w["label"] for w in wf)
    ro = cum["report_only"]["netting_effect"]
    assert ro["value_pct"] == pytest.approx(0.21, abs=1e-6) and ro["reason"]
    assert cum["netting_savings_value"] == pytest.approx(2100.0)


def test_a_return_that_secretly_contains_netting_breaks_the_identity():
    """★짝★ — 네팅이 수익률에 들어간 데이터면 "닫힌다" 고 말하지 않는다."""
    rows = [{**r, "netting_effect": 0.0007,
             "net": (r.get("baseline_effect", 0) + r.get("allocation_effect", 0)
                     + r.get("cost_effect", 0) + 0.0007)} for r in _ROWS]
    cum = _cum(frame(rows))
    assert cum["identity"]["holds"] is False
    assert cum["identity"]["max_abs_gap"] == pytest.approx(0.0007, abs=1e-9)
    assert cum["interaction_pct"] is None and cum["unexplained_pct"] is not None
    wf = AttributionDecomposer._build_waterfall(cum)
    assert any(w["step"] == "Unexplained" for w in wf)


def test_macro_and_selection_are_report_only_too():
    cum = _cum(frame([{**r, "macro_effect": 0.001} for r in _ROWS]))
    assert set(cum["report_only"]) == {"netting_effect", "macro_effect", "selection_effect"}
    assert cum["report_only"]["selection_effect"]["value_pct"] is None
    assert cum["identity"]["holds"] is True, "매크로를 더하면 이중 계산이다"


# ── 기준이 없는 옛 실행 · 현금 ───────────────────────────────────────────

def test_a_legacy_run_without_a_baseline_is_unexplained_with_a_reason():
    cum = _cum(frame(_ROWS, with_baseline=False))
    assert cum["identity"]["holds"] is False
    assert "동일가중" in cum["identity"]["reason"]
    assert cum["interaction_pct"] is None
    wf = AttributionDecomposer._build_waterfall(cum)
    assert wf[0]["step"] == "Baseline" and wf[0]["value"] == 0.0
    assert "미상" in wf[0]["label"]


def test_cash_without_a_model_is_not_modeled_not_unknown():
    cum = _cum(frame(_ROWS))                        # cash_effect 전부 None
    assert cum["identity"]["holds"] is True
    assert "cash_effect" in cum["identity"]["not_modeled"]
    assert not any(w["step"] == "Cash Yield" for w in
                   AttributionDecomposer._build_waterfall(cum))


def test_a_modeled_cash_yield_is_a_step():
    """★짝★ realism 처럼 현금이자가 수익률에 있으면 제 스텝을 갖는다."""
    rows = [{**r, "cash_effect": 0.0001} for r in _ROWS]
    cum = _cum(frame(rows))
    assert cum["identity"]["holds"] is True
    assert cum["identity"]["not_modeled"] == []
    wf = AttributionDecomposer._build_waterfall(cum)
    cash = [w for w in wf if w["step"] == "Cash Yield"]
    assert cash and cash[0]["value"] == pytest.approx(0.03, abs=1e-6)


def test_the_identity_drivers_exclude_report_only_effects():
    assert IDENTITY_DRIVERS == ("baseline_effect", "allocation_effect",
                                "cost_effect", "cash_effect")


# ── 하루 설명 ────────────────────────────────────────────────────────────

def test_a_closed_day_is_not_called_compounding():
    """하루에는 복리가 없다 — 항등식이 닫히면 잔차는 "닫힘" 이다."""
    from src.domain.daily_explanation import RESIDUAL_CLOSED
    from src.engine.daily_explain_backtest import explain_backtest_day
    rows = AttributionDecomposer._daily_attribution(frame(_ROWS))
    exp = explain_backtest_day(rows[0], run_id=1)
    assert exp.residual_kind == RESIDUAL_CLOSED
    assert abs(exp.residual_pct) < 1e-6
    assert "복리" not in exp.summary_ko
    assert "현금 이자" in exp.summary_ko and "모델링하지 않" in exp.summary_ko


def test_a_day_that_does_not_close_says_so():
    """★짝★"""
    from src.domain.daily_explanation import RESIDUAL_UNEXPLAINED
    from src.engine.daily_explain_backtest import explain_backtest_day
    bad = [{**_ROWS[0], "net": 0.02}]
    rows = AttributionDecomposer._daily_attribution(frame(bad))
    exp = explain_backtest_day(rows[0], run_id=1)
    assert exp.residual_kind == RESIDUAL_UNEXPLAINED and exp.residual_reason


# ── 실물 — 엔진이 싣고 저장하고 분해가 닫힌다 ─────────────────────────────

def _run_saved(db):
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    reg = _registry(db)
    a = reg.register(_stored_run(_req()), "A")["id"]
    b = reg.register(_stored_run(_req(sell_conditions=[
        {"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 3}])), "B")["id"]
    bt = MultiStrategyBacktester(db)
    out = bt.run_and_save(BacktestConfig(
        strategy_ids=[a, b], start_date="2023-06-01", end_date="2024-03-01",
        allocation_method="hrp", macro_overlay_enabled=False, lookback_days=60,
        max_weight=0.8, min_weight=0.0))
    assert out["success"], out.get("message")
    return out, (a, b), reg


def test_the_engine_records_the_equal_weight_baseline(db, market):
    out, sids, reg = _run_saved(db)
    m = reg.load_returns_matrix(list(sids), "2023-06-01", "2024-03-01")
    rec = out["daily_records"][5]
    day = m.loc[pd.Timestamp(rec["date"])]
    assert rec["baseline_effect"] == pytest.approx(float(day.mean()), abs=1e-12)


def test_the_saved_strategy_rows_carry_real_values_not_constants(db, market):
    from sqlalchemy import text
    out, sids, reg = _run_saved(db)
    with db.connect() as c:
        rows = c.execute(text(
            "SELECT trade_date, strategy_id, weight, strategy_return, contribution "
            "FROM multibacktest_strategy_daily WHERE run_id = :r"),
            {"r": out["run_id"]}).fetchall()
    assert rows
    m = reg.load_returns_matrix(list(sids), "2023-06-01", "2024-03-01")
    nonzero = 0
    for td, sid, w, sr, contrib in rows:
        r = float(m.loc[pd.Timestamp(str(td)[:10]), int(sid)])
        assert sr == pytest.approx(r, abs=1e-12)
        assert contrib == pytest.approx(w * r, abs=1e-12)
        nonzero += abs(sr) > 0
    assert nonzero > 10, "전부 0 이면 저장이 여전히 상수를 쓰고 있다"


def test_a_saved_run_decomposes_with_the_identity_holding(db, market):
    out, _sids, _reg = _run_saved(db)
    res = AttributionDecomposer(db).decompose(out["run_id"])
    assert res["available"] is True
    ident = res["cumulative"]["identity"]
    assert ident["holds"] is True, ident
    assert ident["n_rows_checked"] == out["n_trading_days"]
    wf = res["waterfall"]
    assert wf[0]["label"] == "동일가중 기준"
    assert wf[-2]["running_total"] == pytest.approx(wf[-1]["running_total"], abs=1e-3)
    contrib = sum(s["cumulative_contribution_pct"] for s in res["strategy_contribution"])
    ew_plus_alloc = (res["cumulative"]["baseline_effect_pct"]
                     + res["cumulative"]["allocation_effect_pct"])
    # 전략별 기여는 소수 3자리로 표시된다 — 전략 둘의 반올림 합 오차 ≤ 1e-3.
    assert contrib == pytest.approx(ew_plus_alloc, abs=1e-3), \
        "전략 기여의 합 = Σ w·r = 동일가중 기준 + 배분 효과"


def test_the_postgres_ddl_uses_double_precision():
    """★PG 의 REAL 은 4바이트★ — 항등식 검사(1e-9)가 반올림에 깨진다."""
    from src.engine.multibacktest_schema import schema_ddls
    pg = " ".join(schema_ddls("postgresql"))
    assert " REAL" not in pg and "DOUBLE PRECISION" in pg


def test_the_regime_breakdown_keeps_an_unknown_effect_unknown():
    """예전 `fillna(0).sum()` — 국면별 표만 안 잰 것을 0 으로 뒀다."""
    df = frame(_ROWS)
    df["regime"] = "Goldilocks"
    df["macro_effect"] = np.nan
    row = AttributionDecomposer._regime_breakdown(df.assign(regime="GOLDILOCKS"))[0]
    assert row["macro_effect_pct"] is None
    assert row["baseline_effect_pct"] == pytest.approx(
        sum(r["baseline_effect"] for r in _ROWS) * 100, abs=1e-3)       # ★짝★


def test_an_old_table_gains_the_late_columns():
    """★키워드 버그★ — `add_columns(..., logger=)` 가 TypeError 로 삼켜져 기존 표에
    뒤늦은 칸이 한 번도 붙지 않았다. 옛 모양의 표에 초기화를 돌리면 칸이 생겨야 한다."""
    from sqlalchemy import create_engine, inspect, text

    from src.engine.multibacktest_schema import init_multibacktest_schema
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE multibacktest_daily (run_id INTEGER, "
                       "trade_date DATE, portfolio_return REAL)"))
    init_multibacktest_schema(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("multibacktest_daily")}
    assert {"baseline_effect", "cash_effect"} <= cols
