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
    EFFECT_COLUMNS,
    AttributionDecomposer,
    _sanitize_for_json,
)

#: ★효과 목록을 여기 다시 적지 않는다★ (AL3 에서 다섯 → 여섯이 되며 이 사본이
#: 낡아 테스트 넷이 깨졌다). 단일 출처를 읽으면 다음 변경에도 안 낡는다.
EFFECTS = EFFECT_COLUMNS


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


# ── ★미상 ≠ 0★ 고쳐진 계약 ────────────────────────────────────────────────
def test_a_missing_macro_row_is_not_counted_as_zero():
    """합은 **알려진 행만의 합**이고, 몇 행을 봤는지가 함께 실린다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"macro_effect": 0.02, "portfolio_return": 0.02, "cumulative_return": 4.0},
        {"macro_effect": np.nan, "portfolio_return": 0.02},
    ]))
    assert cum["macro_effect_pct"] == 2.0
    cov = cum["coverage"]["macro_effect"]
    assert cov["n_known"] == 1 and cov["n_total"] == 2
    assert cov["coverage"] == 0.5


def test_a_fully_observed_effect_reports_full_coverage():
    """★짝★ 항상 부분 커버리지를 주장하는 구현을 배제한다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"macro_effect": 0.02, "portfolio_return": 0.02, "cumulative_return": 4.0},
    ]))
    assert cum["coverage"]["macro_effect"]["coverage"] == 1.0
    assert cum["coverage"]["macro_effect"]["reason"] is None


def test_an_effect_observed_nowhere_is_unknown_not_zero():
    """★미상 ≠ 0★ 한 행도 못 본 효과는 0 이 아니라 미상이다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"macro_effect": np.nan, "portfolio_return": 0.02, "cumulative_return": 4.0},
    ]))
    assert cum["macro_effect_pct"] is None
    assert cum["coverage"]["macro_effect"]["reason"].strip()


def test_an_effect_that_really_is_zero_stays_zero():
    """★짝★ 진짜 0 은 미상이 아니다. 둘을 뭉치면 반대 방향으로 거짓말한다."""
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"macro_effect": 0.0, "portfolio_return": 0.02, "cumulative_return": 4.0},
    ]))
    assert cum["macro_effect_pct"] == 0.0
    assert cum["coverage"]["macro_effect"]["coverage"] == 1.0


def test_the_residual_no_longer_absorbs_the_missing_amount():
    """★이 작업의 핵심★ 세탁 경로를 끊는다.

    구멍이 있는 패널과 없는 패널이 더 이상 같은 리포트를 내지 않는다 — 잔차를
    **복리 효과라고 부르기를 거부한다**. ★BH2★ 부터 구멍의 대상은 수익률 항등식의
    드라이버(동일가중 기준·배분·비용·현금)이고, 닫히는지를 데이터로 검사한다.
    """
    known = daily([{"baseline_effect": 0.02, "portfolio_return": 0.02,
                    "cumulative_return": 2.0}])
    holed = daily([{"baseline_effect": 0.02, "portfolio_return": 0.02,
                    "cumulative_return": 2.0},
                   {"baseline_effect": np.nan, "portfolio_return": 0.0,
                    "cumulative_return": 2.0}])
    a = AttributionDecomposer._cumulative_attribution(known)
    b = AttributionDecomposer._cumulative_attribution(holed)

    assert a["coverage_complete"] is True
    assert b["coverage_complete"] is False
    assert a["interaction_pct"] is not None and a["unexplained_pct"] is None
    # 구멍이 있으면 잔차는 복리가 아니라 **복리와 흡수된 미상의 혼합**이다
    assert b["interaction_pct"] is None
    assert b["unexplained_pct"] is not None
    assert b["unexplained_reason"].strip()


def test_an_incomplete_waterfall_does_not_call_the_residual_compounding():
    """라벨이 바뀌지만 `kind` 는 기존 유니온 값을 유지한다 — 프론트 무변경."""
    holed = daily([{"baseline_effect": 0.02, "portfolio_return": 0.02,
                    "cumulative_return": 5.0},
                   {"baseline_effect": np.nan, "portfolio_return": 0.0,
                    "cumulative_return": 5.0}])
    wf = AttributionDecomposer._build_waterfall(
        AttributionDecomposer._cumulative_attribution(holed))
    resid = [w for w in wf if w["kind"] == "interaction"]
    assert resid and "복리" not in resid[0]["label"]
    assert resid[0]["step"] == "Unexplained"


def test_a_complete_waterfall_still_calls_it_compounding():
    """★짝★ 항상 미설명이라고 부르는 구현을 배제한다 — 이틀이면 복리가 생긴다."""
    known = daily([{"baseline_effect": 0.02, "portfolio_return": 0.02},
                   {"baseline_effect": 0.03, "portfolio_return": 0.03}])
    wf = AttributionDecomposer._build_waterfall(
        AttributionDecomposer._cumulative_attribution(known))
    resid = [w for w in wf if w["kind"] == "interaction"]
    assert resid and resid[0]["label"] == "복리 효과"


def test_no_waterfall_step_ever_carries_a_null_value():
    """★불변식★ 프론트가 `step.value.toFixed(2)` 를 부른다 — `null` 이면 크래시.

    커버리지 0 인 드라이버는 스텝을 **생략**하고 생략 사실을 남긴다.
    """
    cum = AttributionDecomposer._cumulative_attribution(daily([
        {"allocation_effect": np.nan, "baseline_effect": 0.01,
         "portfolio_return": 0.02, "cumulative_return": 5.0},
    ]))
    wf = AttributionDecomposer._build_waterfall(cum)
    assert wf, "워터폴이 비면 이 테스트는 공허하다"
    assert all(isinstance(w["value"], (int, float)) for w in wf)
    assert all(isinstance(w["running_total"], (int, float)) for w in wf)
    assert "allocation_effect" in cum["waterfall_omitted"]
    assert not any(w["step"] == "Allocation Effect" for w in wf)


def test_every_waterfall_step_accumulates_exactly():
    """★잔차를 두 번 세지 않는다★

    예전 `baseline` 은 `actual − Σ효과` 였고 `interaction` 도 **똑같은 식**이라
    같은 미설명분이 두 번 더해졌다 — running_total 이 5.0 → 8.0 으로 실제값을
    넘어섰다가 마지막 "Actual Total" 스텝이 조용히 5.0 으로 되돌려 놓았다
    (실측). 도달이 아니라 **되돌리기**였다.
    """
    wf = AttributionDecomposer._build_waterfall(
        AttributionDecomposer._cumulative_attribution(daily([
            {"macro_effect": 0.02, "portfolio_return": 0.02,
             "cumulative_return": 5.0}])))
    for prev, cur in zip(wf, wf[1:]):
        if cur["kind"] == "total":
            continue
        assert cur["running_total"] == pytest.approx(
            prev["running_total"] + cur["value"], abs=1e-6), cur["step"]
    # 마지막 직전에 **이미** 실제 수익률에 도달해 있어야 한다
    assert wf[-2]["running_total"] == pytest.approx(
        wf[-1]["running_total"], abs=1e-6)


def test_the_waterfall_kinds_stay_inside_the_frontend_union():
    """★프론트 계약★ `COLORS[step.kind]` 라 새 `kind` 는 `undefined` 가 된다."""
    allowed = {"baseline", "positive", "negative", "interaction", "total"}
    for panel in (daily([{"macro_effect": 0.02, "portfolio_return": 0.02,
                          "cumulative_return": 5.0}]),
                  daily([{"macro_effect": np.nan, "allocation_effect": 0.01,
                          "portfolio_return": 0.02, "cumulative_return": 5.0}])):
        wf = AttributionDecomposer._build_waterfall(
            AttributionDecomposer._cumulative_attribution(panel))
        assert {w["kind"] for w in wf} <= allowed


def test_nan_becomes_null_not_zero():
    """★미상을 제조하지 않는다★ NaN 은 0 이 아니라 미상이다. `null` 은 유효 JSON."""
    assert _sanitize_for_json({"x": float("nan")}) == {"x": None}
    assert _sanitize_for_json({"x": float("inf")}) == {"x": None}
    assert _sanitize_for_json([float("nan")]) == [None]


def test_real_numbers_survive_sanitising():
    """★짝★ 전부 `None` 으로 만드는 구현을 배제한다."""
    assert _sanitize_for_json({"x": 1.5, "y": 0.0, "z": "a"}) == {"x": 1.5, "y": 0.0, "z": "a"}


def test_the_result_is_strict_json_with_no_nan():
    """FastAPI 로 나가는 값이 엄격 JSON 이어야 한다 — 이것이 0.0 의 원래 이유였다."""
    import json
    out = AttributionDecomposer(_sqlite_engine()).decompose(1)
    json.dumps(out, allow_nan=False)      # 던지면 실패


def test_zero_volatility_reports_sharpe_as_unknown():
    """변동성이 0 이면 샤프는 0 이 아니라 미상이다(`avg_systemic_risk` 선례)."""
    df = daily([{"portfolio_return": 0.01}, {"portfolio_return": 0.01}])
    row = AttributionDecomposer._regime_breakdown(df)[0]
    assert row["sharpe"] is None
    assert row["sharpe_reason"].strip()


def test_a_real_volatility_still_reports_a_number():
    """★짝★ 항상 미상이라고 답하는 구현을 배제한다."""
    df = daily([{"portfolio_return": 0.01}, {"portfolio_return": -0.02},
                {"portfolio_return": 0.03}])
    row = AttributionDecomposer._regime_breakdown(df)[0]
    assert isinstance(row["sharpe"], float)
    assert row["sharpe_reason"] is None


def test_a_zero_contribution_is_not_treated_as_missing():
    """★값이 0 인 것과 미상인 것을 값으로 구분하지 않는다★ — 커버리지로 가른다."""
    sdf = pd.DataFrame([
        {"strategy_id": 1, "weight": 0.5, "macro_adjustment": 0.0,
         "contribution": 0.0, "strategy_return": 0.04},
    ])
    out = AttributionDecomposer(None)._strategy_contribution(sdf, {1: "A"})
    assert out[0]["cumulative_contribution_pct"] == 0.0


def test_a_missing_contribution_falls_back_and_says_so():
    """★짝★ 진짜 미상이면 대체 계산을 쓰되 **그 사실을 적는다**."""
    sdf = pd.DataFrame([
        {"strategy_id": 1, "weight": 0.5, "macro_adjustment": 0.0,
         "contribution": np.nan, "strategy_return": 0.04},
    ])
    out = AttributionDecomposer(None)._strategy_contribution(sdf, {1: "A"})
    assert out[0]["cumulative_contribution_pct"] == 2.0
    assert out[0]["contribution_source"] == "weight_times_return"


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
        c.execute(_t("INSERT INTO multibacktest_runs VALUES (1, 'r', '2026-01-01',"
                     " '2026-02-01', 'hrp', 5.0, 5.0, 1.0, -2.0)"))
        if with_rows:
            # ★위치 기반 INSERT 를 쓰지 않는다★ — 효과가 다섯에서 여섯이 되자
            # (AL3) 값 개수가 어긋나 테스트 넷이 깨졌다. 칸 이름을 적으면
            # `EFFECTS` 가 늘어도 안 낡는다.
            # 원래 값을 **이름으로** 보존한다(예전 위치 기반 목록과 같은 수).
            _v = {"allocation_effect": 0.01, "selection_effect": 0.0,
                  "macro_effect": 0.02, "netting_effect": 0.0,
                  "cost_effect": 0.0, "cash_effect": 0.0}
            assert set(_v) == set(EFFECTS), "픽스처가 효과 목록과 어긋났습니다"
            names = ", ".join(EFFECTS)
            vals = ", ".join(str(_v[e]) for e in EFFECTS)
            c.execute(_t(f"INSERT INTO multibacktest_daily (run_id, trade_date,"
                         f" portfolio_return, cumulative_return, netting_savings,"
                         f" turnover_pct, num_trades, rebalanced, regime,"
                         f" systemic_risk, {names}) VALUES (1, '2026-01-05',"
                         f" 0.02, 5.0, 0.0, 0.0, 1, 0, 'GOLDILOCKS', 10.0,"
                         f" {vals})"))
            c.execute(_t("INSERT INTO multibacktest_strategy_daily VALUES"
                         " (1, '2026-01-05', 7, 0.5, 0.0, 0.01, 0.02)"))
    if with_strategy_table:
        # ★이름은 전략 레지스트리에서 온다★ (BG5) — 예전 픽스처는 이 저장소에 없는
        # `strategies` 표를 만들어 조회가 성공하는 척을 했다.
        from src.engine.strategy_registry import StrategyRegistry
        StrategyRegistry(eng)
        with eng.begin() as c:
            c.execute(_t("INSERT INTO strategy_registry (id, name, source_run_id,"
                         " is_active) VALUES (7, '실제 전략명', 'bt_fixture', 1)"))
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


def test_a_load_failure_is_not_reported_as_no_data():
    """★없는 것과 못 읽은 것은 다른 사실이다★ 원인이 다르면 다르게 말해야 한다."""
    broke = AttributionDecomposer(_ExplodingEngine()).decompose(1)
    empty = AttributionDecomposer(_sqlite_engine(with_rows=False)).decompose(1)
    assert broke["available"] is False and empty["available"] is False
    assert broke["message"] != empty["message"]
    assert broke["failure"] == "load_failed"
    assert empty["failure"] == "no_rows"
    assert "connection refused" in broke["message"]


def test_both_failure_modes_still_say_something():
    """★짝★ 사유가 비어 있으면 구분해 봐야 소용이 없다."""
    for eng in (_ExplodingEngine(), _sqlite_engine(with_rows=False)):
        out = AttributionDecomposer(eng).decompose(1)
        assert out["message"] and out["message"].strip()


def test_a_name_lookup_failure_does_not_fabricate_a_name():
    """★미상인 이름은 이름이 아니다★ (`stock_master` 의 `"Unknown Corp"` 금지와
    같은 형태). 조회에 실패했으면 실패했다고 말한다."""
    eng = _sqlite_engine(with_strategy_table=False)     # 레지스트리에 id 7 이 없다
    out = AttributionDecomposer(eng).decompose(1)
    row = out["strategy_contribution"][0]
    assert row["strategy_name"] is None
    assert row["strategy_name_reason"].strip()
    assert row["strategy_id"] == 7          # 식별자는 여전히 안다


def test_a_successful_lookup_still_returns_the_real_name():
    """★짝★ 항상 `None` 을 내는 구현을 배제한다."""
    row = AttributionDecomposer(_sqlite_engine()).decompose(1)["strategy_contribution"][0]
    assert row["strategy_name"] == "실제 전략명"
    assert row["strategy_name_reason"] is None
