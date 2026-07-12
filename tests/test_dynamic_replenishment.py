"""동적 재편입(Dynamic Replenishment, 젠포트화 Phase 6) 검증.

핵심 주장: symbols(초기 후보 리스트)에 없는 종목도 replenishment_pool을 통해 매도로 슬롯이
열린 그날 즉시 편입될 수 있어야 한다 — 이전 엔진은 self.cfg.symbols 밖 종목을 절대 편입할
수 없었다(메인루프가 `for ticker in self.cfg.symbols`만 순회).

세 시나리오:
  1) replenishment_pool 미지정 시 dynamic_replenishment 플래그 값과 무관하게 완전히 비활성
     — pool을 넘기지 않는 기존 호출자(레거시 경로)는 새 기본값(True)의 영향을 전혀 받지 않음.
  2) pool 지정 + 손절로 슬롯이 열리면, symbols 밖 종목(CCC)이 같은 날 즉시 편입됨.
  3) rebalance_period 설정 시, 그 주기 첫 거래일에 순위 이탈 보유종목만 정리되고 빈자리가
     같은 날 재편입으로 자동 채워짐(상위권 보유종목은 그대로 유지).
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리 자기등록

START = "2024-06-03"
WARMUP = 90

BUY_JUMP = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
             "op": "gte", "rhs": 5}]
SELL_DROP = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
              "op": "lte", "rhs": -5}]


def _df(warmup_closes: list[float], test_closes: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=len(warmup_closes))
    idx = idx.append(pd.bdate_range(start=START, periods=len(test_closes)))
    close = pd.Series([float(c) for c in warmup_closes + test_closes], index=idx)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 50_000.0}, index=idx)


def _linspace(start: float, end: float, n: int) -> list[float]:
    if n <= 1:
        return [end] * max(n, 0)
    step = (end - start) / (n - 1)
    return [start + step * i for i in range(n)]


def _mock_loader(dfs: dict):
    def loader(ticker, *_a, **_k):
        return dfs[ticker].copy()
    return loader


# ── 시나리오 1: pool 미지정 → dynamic_replenishment 값과 무관하게 완전 비활성 ──────────

WARMUP_FLAT = [100.0] * WARMUP
AAA_T1 = [100, 100, 100, 110, 110, 110, 110, 110, 99, 99, 99, 99]      # day3 +10%매수, day8 -10%매도
BBB_T1 = [100, 100, 100, 110, 110, 110, 110, 110, 110, 110, 110, 110]  # day3 +10%매수, 이후 보유 유지


def _run_scenario1(dynamic_replenishment: bool, monkeypatch) -> list[tuple]:
    dfs = {"000001": _df(WARMUP_FLAT, AAA_T1), "000002": _df(WARMUP_FLAT, BBB_T1)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", _mock_loader(dfs))
    cfg = BacktestConfig(
        symbols=["000001", "000002"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY_JUMP, "sell_conditions": SELL_DROP},
        start_date=START, end_date=dfs["000001"].index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=2,
        dynamic_replenishment=dynamic_replenishment, replenishment_pool=None,
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return [(t.ticker, t.side, t.reason) for t in engine.trades]


def test_no_pool_inert_when_default_true(monkeypatch):
    trades = _run_scenario1(True, monkeypatch)
    assert [(tk, side) for tk, side, _ in trades] == [
        ("000001", "buy"), ("000002", "buy"), ("000001", "sell"),
    ]
    assert all("재편입" not in r and "순위이탈" not in r for _, _, r in trades)


def test_no_pool_inert_when_explicit_false(monkeypatch):
    trades = _run_scenario1(False, monkeypatch)
    assert [(tk, side) for tk, side, _ in trades] == [
        ("000001", "buy"), ("000002", "buy"), ("000001", "sell"),
    ]


# ── 시나리오 2: 손절로 슬롯이 열리면 symbols 밖 종목(CCC)이 같은 날 즉시 편입 ─────────

AAA_WARM2 = _linspace(90, 118, WARMUP)   # 강한 상승 — 초기 재편입에서 채택됨
BBB_WARM2 = _linspace(92, 116, WARMUP)   # 강한 상승 — 초기 재편입에서 채택됨
CCC_WARM2 = [100.0] * WARMUP             # 워밍업 중엔 평탄 — 초기 재편입에서 제외됨

AAA_T2 = [118, 118, 118, 118, 118, 90, 90, 90, 90, 90, 90, 90]         # day5 -24% 폭락 → 5%손절
BBB_T2 = [116] * 12                                                    # 트리거 없음, 보유 유지
CCC_T2 = [102, 105, 108, 111, 114, 117, 120, 123, 126, 129, 132, 135]  # 지속 강세로 전환


def test_replenish_fills_slot_with_off_list_ticker(monkeypatch):
    dfs = {"000101": _df(AAA_WARM2, AAA_T2), "000102": _df(BBB_WARM2, BBB_T2),
           "000103": _df(CCC_WARM2, CCC_T2)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", _mock_loader(dfs))
    cfg = BacktestConfig(
        symbols=["000101", "000102"], strategy_name="Condition",
        strategy_params={"buy_conditions": [], "sell_conditions": []},
        start_date=START, end_date=dfs["000101"].index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=2,
        stop_loss_pct=5.0, rebuy_block_days=30,
        dynamic_replenishment=True, replenishment_pool=["000101", "000102", "000103"],
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    trades = [(t.ticker, t.side, t.reason) for t in engine.trades]

    # 초기 재편입(day0): AAA·BBB가 모멘텀 상위라 채워짐 — CCC는 아직 아님
    initial = [(tk, side, r) for tk, side, r in trades if r.startswith("동적 재편입")]
    assert {tk for tk, _, _ in initial[:2]} == {"000101", "000102"}

    # 핵심 주장: CCC(원래 symbols 밖 종목)가 손절로 열린 슬롯에 재편입으로 편입됨
    ccc_buys = [(tk, side, r) for tk, side, r in trades if tk == "000103" and side == "buy"]
    assert ccc_buys, "CCC가 재편입으로 매수되어야 함(symbols 밖 종목 편입 증명)"
    assert all(r.startswith("동적 재편입") for _, _, r in ccc_buys)

    # AAA는 손절로 청산됨 (재매수방지 30일로 재편입 후보에서도 배제됨)
    aaa_sells = [(tk, side, r) for tk, side, r in trades if tk == "000101" and side == "sell"]
    assert aaa_sells and all(r == "Stop-loss triggered" for _, _, r in aaa_sells)
    aaa_buys = [t for t in trades if t[0] == "000101" and t[1] == "buy"]
    assert len(aaa_buys) == 1  # 초기 재편입 1회만 — 손절 후 재매수방지로 재편입되지 않음


# ── 시나리오 3: rebalance_period 첫 거래일에 순위이탈 보유종목만 정리 + 즉시 재편입 ─────

AAA_WARM3 = _linspace(90, 118, WARMUP)   # 강한 상승 — 초기 재편입에서 채택
BBB_WARM3 = _linspace(95, 128, WARMUP)   # 더 강한 상승 — 항상 최상위권 유지
CCC_WARM3 = [100.0] * WARMUP             # 워밍업 중엔 평탄 — 초기 재편입에서 제외

# 약 25거래일 — 2024-06-03(월)에서 다음달(7월) 첫 거래일까지 포함하도록 충분히 길게
N_T3 = 25
AAA_T3 = [118.0] * N_T3                                    # 평탄 전환 — 모멘텀 감속(순위 하락)
BBB_T3 = _linspace(128.0, 140.0, N_T3)                     # 지속 상승 — 항상 최상위 유지
CCC_T3 = _linspace(100.0, 160.0, N_T3)                     # 급등 전환 — AAA를 역전


def test_rebalance_prune_replaces_out_of_rank_holding(monkeypatch):
    dfs = {"000101": _df(AAA_WARM3, AAA_T3), "000102": _df(BBB_WARM3, BBB_T3),
           "000103": _df(CCC_WARM3, CCC_T3)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", _mock_loader(dfs))
    cfg = BacktestConfig(
        symbols=["000101", "000102"], strategy_name="Condition",
        strategy_params={"buy_conditions": [], "sell_conditions": []},
        start_date=START, end_date=dfs["000101"].index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=2,
        rebalance_period="monthly",
        dynamic_replenishment=True, replenishment_pool=["000101", "000102", "000103"],
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    trades = [(t.ticker, t.side, t.reason) for t in engine.trades]

    # BBB는 항상 최상위권 — 순위이탈로 정리되면 안 됨
    assert not any(tk == "000102" and r == "리밸런싱 순위이탈 매도" for tk, _, r in trades)

    # AAA는 모멘텀 감속으로 순위 이탈 → 리밸런싱 시 정리됨
    prune_sells = [(tk, side, r) for tk, side, r in trades if r == "리밸런싱 순위이탈 매도"]
    assert prune_sells and prune_sells[0][0] == "000101"

    # CCC(원래 symbols 밖 종목)가 그 빈자리에 재편입으로 편입됨
    ccc_buys = [(tk, side, r) for tk, side, r in trades if tk == "000103" and side == "buy"]
    assert ccc_buys, "CCC가 순위이탈로 열린 슬롯에 재편입으로 편입돼야 함"
    assert all(r.startswith("동적 재편입") for _, _, r in ccc_buys)
