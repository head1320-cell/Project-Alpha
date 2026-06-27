"""라운드트립 매칭 — 매수/매도 leg을 FIFO로 묶어 체결 쌍 생성 검증."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.kis_backtest_engine import Trade, _round_trips  # noqa: E402


def test_round_trips_basic_matching():
    trades = [
        Trade("2024-01-02", "000660", "buy", 100.0, 10, 1000, 0, 0),
        Trade("2024-01-10", "000660", "sell", 120.0, 10, 1200, 0, 0, pnl=200.0),
    ]
    rts = _round_trips(trades)
    assert len(rts) == 1
    rt = rts[0]
    assert rt["stock_code"] == "000660"
    assert rt["entry_date"] == "2024-01-02" and rt["exit_date"] == "2024-01-10"
    assert rt["entry_price"] == 100.0 and rt["exit_price"] == 120.0
    assert abs(rt["return_pct"] - 20.0) < 1e-6
    assert rt["corp_name"]  # 종목명 채워짐(빈 문자열 아님)
    assert rt["pnl"] == 200.0


def test_round_trips_partial_and_fifo():
    trades = [
        Trade("2024-01-02", "A", "buy", 100.0, 10, 1000, 0, 0),
        Trade("2024-01-03", "A", "buy", 110.0, 10, 1100, 0, 0),
        Trade("2024-01-10", "A", "sell", 120.0, 15, 1800, 0, 0, pnl=250.0),
    ]
    rts = _round_trips(trades)
    assert len(rts) == 1
    rt = rts[0]
    # 가중 진입가 = (10*100 + 5*110)/15 = 1550/15 ≈ 103.33, 진입일은 가장 이른 lot
    assert abs(rt["entry_price"] - 103.33) < 0.1
    assert rt["entry_date"] == "2024-01-02"
    assert rt["quantity"] == 15


def test_round_trips_loss_sign():
    trades = [
        Trade("2024-01-02", "A", "buy", 100.0, 10, 1000, 0, 0),
        Trade("2024-01-10", "A", "sell", 80.0, 10, 800, 0, 0, pnl=-200.0),
    ]
    rts = _round_trips(trades)
    assert abs(rts[0]["return_pct"] - (-20.0)) < 1e-6


def test_round_trips_multi_ticker_independent():
    trades = [
        Trade("2024-01-02", "A", "buy", 100.0, 10, 1000, 0, 0),
        Trade("2024-01-02", "B", "buy", 200.0, 5, 1000, 0, 0),
        Trade("2024-01-09", "B", "sell", 220.0, 5, 1100, 0, 0, pnl=100.0),
        Trade("2024-01-10", "A", "sell", 90.0, 10, 900, 0, 0, pnl=-100.0),
    ]
    rts = _round_trips(trades)
    assert len(rts) == 2
    by_code = {rt["stock_code"]: rt for rt in rts}
    assert abs(by_code["B"]["return_pct"] - 10.0) < 1e-6
    assert abs(by_code["A"]["return_pct"] - (-10.0)) < 1e-6


def test_round_trips_empty():
    assert _round_trips([]) == []
