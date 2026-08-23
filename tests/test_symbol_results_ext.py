"""종목별 성과 확장 — 라운드트립 기반 실현손익/평균수익률/평균보유일/기여도."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.kis_backtest_engine import Trade, _compute_symbol_results  # noqa: E402

TRADES = [
    Trade("2024-01-02", "A", "buy", 100.0, 10, 1000, 1, 0),
    Trade("2024-01-12", "A", "sell", 120.0, 10, 1200, 1, 0, pnl=200.0),
    Trade("2024-02-01", "A", "buy", 110.0, 10, 1100, 1, 0),
    Trade("2024-02-11", "A", "sell", 99.0, 10, 990, 1, 0, pnl=-110.0),
    Trade("2024-01-02", "B", "buy", 200.0, 5, 1000, 1, 0),
    Trade("2024-03-02", "B", "sell", 220.0, 5, 1100, 1, 0, pnl=100.0),
]


def test_extended_fields():
    rs = {r["symbol"]: r for r in _compute_symbol_results(TRADES, ["A", "B"])}
    a, b = rs["A"], rs["B"]
    assert a["realized_pnl"] == 90.0            # 200 - 110
    assert a["round_trips"] == 2 and a["win_rate"] == 50.0
    assert abs(a["avg_hold_days"] - 10.0) < 0.01
    assert abs(a["avg_return_pct"] - ((20.0 + -10.0) / 2)) < 0.2   # +20%, -10%
    assert b["avg_hold_days"] == 60.0
    total = 90.0 + 100.0
    assert abs(a["contribution_pct"] - 90.0 / total * 100) < 0.1
    assert "corp_name" in a


def test_no_trades_symbol_zeroes():
    rs = {r["symbol"]: r for r in _compute_symbol_results([], ["C"])}
    assert rs["C"]["realized_pnl"] == 0.0 and rs["C"]["round_trips"] == 0
