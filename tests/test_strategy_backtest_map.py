"""전략 → 백테스터 셋업 매핑 + 최적화 전략 충실 백테스트 어댑터 (mock, 결정론적)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.strategy_backtest_map import (  # noqa: E402
    _ENGINE,
    _MOMENTUM,
    _STATIC,
    backtest_config,
    run_tactical_backtest,
)
from src.engine.tactical_allocations import ALL_STRATEGIES  # noqa: E402
from src.kis_strategies.factor_expr import parse_expr  # noqa: E402

ALL_IDS = {s[0] for s in ALL_STRATEGIES}
_STAT_KEYS = {"total_return_pct", "cagr", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
              "max_drawdown_pct", "num_trades", "win_rate", "profit_factor"}


def test_partition_covers_all_22():
    covered = set(_MOMENTUM) | _STATIC | _ENGINE
    assert covered == ALL_IDS
    assert len(_MOMENTUM) == 12 and len(_STATIC) == 2 and len(_ENGINE) == 8


def test_config_modes():
    for sid in ALL_IDS:
        c = backtest_config(sid, "us")
        assert c is not None, sid
        assert c["mode"] in ("conditions", "asset_alloc", "engine")
        assert c["id"] == sid
        if sid in _MOMENTUM:
            assert c["mode"] == "conditions"
        elif sid in _STATIC:
            assert c["mode"] == "asset_alloc"
        else:
            assert c["mode"] == "engine"


def test_config_unknown_is_none():
    assert backtest_config("__nope__", "us") is None


def test_momentum_conditions_parse_and_universe():
    for sid in _MOMENTUM:
        c = backtest_config(sid, "kr")
        assert c["universe_codes"], f"{sid} 유니버스 비어있음"
        assert c["buy_conditions"], f"{sid} 매수조건 없음"
        assert c["max_tickers"] >= 1
        for cond in c["buy_conditions"]:
            parse_expr(cond["expr"])  # 유효 산술식 (예외 시 실패)
        if c.get("sort_expr"):
            parse_expr(c["sort_expr"])


def test_static_asset_alloc_basket():
    for sid in _STATIC:
        c = backtest_config(sid, "kr")
        assert c["mode"] == "asset_alloc"
        assert c["basket"], f"{sid} 바스켓 없음"
        total = round(sum(b["weight_pct"] for b in c["basket"]), 1)
        assert abs(total - 100.0) <= 1.0, f"{sid} 바스켓 합 {total}"
        for b in c["basket"]:
            assert b["ticker"] and b["weight_pct"] > 0


def test_optimizer_engine_mode():
    for sid in _ENGINE:
        c = backtest_config(sid, "kr")
        assert c["mode"] == "engine"
        assert c["engine_strategy"] == sid
        assert c["universe_codes"]


def test_run_tactical_backtest_shape():
    r = run_tactical_backtest("hrp", "kr", "2021-01-01", "2025-01-01", 10_000_000)
    assert r["error"] is False
    bt = r["backtest"]
    assert _STAT_KEYS <= set(bt["statistics"].keys())
    assert bt["equity_curve"] and len(bt["equity_curve"]) == len(bt["equity_dates"])
    assert len(bt["drawdown_curve"]) == len(bt["equity_curve"])
    assert bt["trades"] == []
    assert r["screened_tickers"]
    # 통계 수치 유한
    s = bt["statistics"]
    assert isinstance(s["total_return_pct"], (int, float))
    assert 0 <= s["win_rate"] <= 100


def test_run_tactical_unknown_safe():
    r = run_tactical_backtest("__nope__", "kr", "2021-01-01", "2025-01-01", 1_000_000)
    assert r["error"] is True


def test_run_tactical_deterministic():
    a = run_tactical_backtest("risk_parity", "kr", "2021-01-01", "2025-01-01", 1_000_000)
    b = run_tactical_backtest("risk_parity", "kr", "2021-01-01", "2025-01-01", 1_000_000)
    assert a["backtest"]["statistics"] == b["backtest"]["statistics"]
