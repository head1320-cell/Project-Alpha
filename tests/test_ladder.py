"""분할 래더 (가격변동%·비중% 단계, 신호 당일 유효) — 매수·매도·만기.

① 매수 래더: 도달 단계만 단계별 가격으로 체결 (0%=기준가, -2%=저가 도달 시)
② 일부 단계 미도달 → 그 비중은 소멸 (보수적)
③ 매도 래더: 단계 비중은 신호 시점 보유수량 기준
④ 만기 래더: 미체결 잔량은 종가 강제 청산 (반드시 종결)
⑤ 검증: 비중 합 >100% → 400(ValueError)
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401

START = "2024-06-03"
BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]
SELL = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
         "op": "lte", "rhs": -5}]


def make_df(rows, warmup=60):
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=warmup)
    idx = idx.append(pd.bdate_range(start=START, periods=len(rows)))
    base = [(100.0, 100.5, 99.5, 100.0)] * warmup + [tuple(map(float, r)) for r in rows]
    df = pd.DataFrame(base, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 50_000.0
    return df


def run(monkeypatch, rows, **kw):
    df = make_df(rows)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    # ★이 파일의 픽스처는 "신호 봉 = 체결 봉" 을 전제로 손으로 짜였다★ — 점프봉
    # 하나에 신호와 래더 도달을 같이 넣어 두었다. 그 전제는 예전 기본값
    # (`signal_lag=0`)에서 **암묵적**이었고, 기본값이 1로 바뀌자 드러났다(AG).
    # ★단언을 느슨하게 하는 대신 전제를 명시한다★ — 여기 주제는 래더 산식이지
    # 신호 시차가 아니다. 그리고 그 전제가 가렸던 사각지대(래더가 `lag>=1` 에서도
    # 도는가)는 아래 `test_a_ladder_fills_the_bar_after_the_signal` 이 덮는다.
    kw.setdefault("signal_lag", 0)
    cfg = BacktestConfig(symbols=["000111"], strategy_name="Condition",
                         strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
                         start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
                         commission_rate=0.0, slippage_rate=0.0, max_positions=1,
                         initial_capital=10_000_000, **kw)
    e = BacktestEngine(cfg)
    r = e.run()
    assert not r.get("error", False)
    return e


LADDER = [{"move_pct": 0.0, "weight_pct": 50.0}, {"move_pct": -2.0, "weight_pct": 50.0}]


def test_buy_ladder_fills_reached_steps(monkeypatch):
    # 점프봉: 전일종가 100 기준 — 0%(100)와 -2%(98) 모두 저가 97.9로 도달
    rows = [(100, 100.5, 99.5, 100), (99, 111, 97.9, 110), (110, 111, 109, 110)]
    e = run(monkeypatch, rows, buy_fill_type="prev_close", buy_ladder=LADDER)
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 2
    assert abs(buys[0].price - 99.0) < 1e-9      # 0% 단계: min(100, 시가99)=99
    assert abs(buys[1].price - 98.0) < 1e-9      # -2% 단계: min(98, 99)=98
    assert "래더 1/2" in buys[0].reason and "래더 2/2" in buys[1].reason
    pos_qty = sum(b.quantity for b in buys)
    assert e.positions["000111"].quantity == pos_qty   # 단일 포지션으로 합산


def test_buy_ladder_skips_unreached(monkeypatch):
    # 저가 99.5 → -2%(98) 미도달: 1단계만 체결, 비중 50%만 진입
    rows = [(100, 100.5, 99.5, 100), (109, 111, 99.5, 110), (110, 111, 109, 110)]
    e = run(monkeypatch, rows, buy_fill_type="prev_close", buy_ladder=LADDER)
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 1 and abs(buys[0].price - 100.0) < 1e-9   # min(100, 시가109)=100
    # 배분의 절반만 사용됐는지 (잔여 절반 소멸 — 당일만 유효)
    assert buys[0].value <= 10_000_000 * 0.95 * 0.5 + buys[0].price


def test_sell_ladder_partial_then_keep(monkeypatch):
    # 매수 후 급락(매도 신호). 매도 래더 0%/+2% — 고가가 +2% 미도달이면 절반만 매도
    rows = [(100, 100.5, 99.5, 100), (109, 111, 108, 110),
            (104, 104.5, 100, 100.5),     # -8.6% 신호, 고가 104.5
            (100, 101, 99, 100.5)]
    ladder = [{"move_pct": 0.0, "weight_pct": 50.0}, {"move_pct": 5.0, "weight_pct": 50.0}]
    e = run(monkeypatch, rows, sell_fill_type="prev_close", sell_ladder=ladder)
    sells = [t for t in e.trades if t.side == "sell"]
    # 기준가 110: 0%→110 도달(고가 104.5? 110 > 104.5 → 미도달!) … 기준가가 전일종가 110이므로
    # 0% 단계도 미도달 → 매도 0. 잔량 유지 검증으로 의미 확정
    assert sells == [] and "000111" in e.positions


def test_sell_ladder_steps_fill(monkeypatch):
    rows = [(100, 100.5, 99.5, 100), (109, 111, 108, 110),
            (104, 113, 100, 100.5),       # 고가 113 — 110(0%)·112.2(+2%) 모두 도달
            (100, 101, 99, 100.5)]
    ladder = [{"move_pct": 0.0, "weight_pct": 50.0}, {"move_pct": 2.0, "weight_pct": 50.0}]
    e = run(monkeypatch, rows, sell_fill_type="prev_close", sell_ladder=ladder)
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 2
    assert abs(sells[0].price - 110.0) < 1e-9          # max(110, 시가104)=110
    assert abs(sells[1].price - 110 * 1.02) < 1e-9
    assert "000111" not in e.positions                 # 50+50 = 전량


def test_expiry_ladder_force_closes_rest(monkeypatch):
    # 만기일 고가가 +5% 단계 미도달 → 도달분만 래더, 잔량은 종가 강제 청산
    rows = [(100, 100.5, 99.5, 100), (109, 111, 108, 110),
            (110, 111.5, 109, 111), (111, 112, 110, 111.5)]
    ladder = [{"move_pct": 0.0, "weight_pct": 50.0}, {"move_pct": 5.0, "weight_pct": 50.0}]
    e = run(monkeypatch, rows, max_hold_days=1, sell_ladder=ladder,
            expiry_sell_method="ladder", expiry_fill_type="prev_close")
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 2
    assert "래더 1/1" in sells[0].reason               # 0% 단계 도달분
    assert "잔량 종가" in sells[1].reason              # 미체결 잔량 종가 청산
    assert "000111" not in e.positions                 # 만기는 반드시 종결


def test_ladder_weight_validation(monkeypatch):
    bad = [{"move_pct": 0.0, "weight_pct": 80.0}, {"move_pct": -1.0, "weight_pct": 40.0}]
    with pytest.raises(ValueError, match="비중 합"):
        run(monkeypatch, [(100, 100.5, 99.5, 100)], buy_ladder=bad)


# ═══════════════════════════════════════════════════════════════════════════
# ★사각지대★ — 래더가 **기본 시차**(`signal_lag=1`)에서도 도는가
#
# 위 넷은 전부 신호 봉에서 바로 체결하는 전제로 짜여 있었다. 그래서 운영 기본값
# (신호는 전일 봉, 체결은 당일)에서 래더가 도는지는 **아무도 테스트하지 않았다**.
# 기본값 변경이 그 구멍을 드러냈으니 구멍을 메운다.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_ladder_fills_the_bar_after_the_signal(monkeypatch):
    """신호는 06-04 봉에서 나고 래더는 **06-05 봉**에서 체결된다.

    기준가는 그 전일(=신호 봉) 종가 110 이고, 단계는 110(0%)·107.8(-2%) 다.
    ★체결일이 신호일이면 죽는다★ — 그게 기본값이 막으려던 룩어헤드다.
    """
    rows = [(100, 100.5, 99.5, 100),      # 06-03 — 무신호
            (99, 111, 97.9, 110),          # 06-04 — +10% ★신호 봉★
            (109, 111, 107.0, 110)]        # 06-05 — 래더 도달 봉
    e = run(monkeypatch, rows, buy_fill_type="prev_close", buy_ladder=LADDER,
            signal_lag=1)
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 2, [t.reason for t in buys]
    assert {t.date for t in buys} == {"2024-06-05"}, "신호 봉에서 체결했다 — 룩어헤드"
    assert abs(buys[0].price - 109.0) < 1e-9      # 0% 단계: min(110, 시가109)=109
    assert abs(buys[1].price - 107.8) < 1e-9      # -2% 단계: min(107.8, 109)=107.8
