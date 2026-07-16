"""시뮬레이션 루프 진행률 emit 검증 (SSE 무음 구간 수정).

배경: BacktestEngine의 일별 시뮬레이션 루프가 루프 시작 시 "simulating" 이벤트를
1회만 emit하고 그 이후로는 전혀 emit하지 않았음 — 가장 오래 걸리는 구간이 정확히
SSE 무음 구간이 되어 인프라 비활성 타임아웃으로 커넥션이 끊길 위험이 있었음. 루프
내부에 screener.py:504와 동일한 throttle 관용구(step = max(1, total // 100))로
구간별 emit을 추가한 수정을 고정한다.
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리 자기등록

START = "2024-01-02"
WARMUP = 90
N_DAYS = 150  # step = max(1, 150 // 100) = 1 → throttle 상한(1)을 넘겨도 매일 emit 가능한 크기


def _df(warmup_len: int, n_days: int) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=warmup_len)
    idx = idx.append(pd.bdate_range(start=START, periods=n_days))
    close = pd.Series([100.0 + 0.01 * i for i in range(len(idx))], index=idx)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 50_000.0}, index=idx)


def _mock_loader(dfs: dict):
    def loader(ticker, *_a, **_k):
        return dfs[ticker].copy()
    return loader


def test_simulating_phase_emits_more_than_once(monkeypatch):
    dfs = {"000001": _df(WARMUP, N_DAYS), "000002": _df(WARMUP, N_DAYS)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", _mock_loader(dfs))

    events = []
    cfg = BacktestConfig(
        symbols=["000001", "000002"], strategy_name="Condition",
        strategy_params={"buy_conditions": [], "sell_conditions": []},
        start_date=START, end_date=dfs["000001"].index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=2,
    )
    engine = BacktestEngine(cfg, progress_cb=lambda e: events.append(e))
    result = engine.run()
    assert not result.get("error", False)

    sim_events = [e for e in events if e.get("phase") == "simulating"]
    # 수정 전: 루프 시작 시 done=0 이벤트 1개뿐. 수정 후: 루프 진행에 따라 추가 emit.
    assert len(sim_events) >= 2, sim_events
    assert sim_events[0]["done"] == 0
    assert sim_events[-1]["done"] == sim_events[-1]["total"]
    # done이 단조 증가(스레드 없이 메인 루프에서 순차 emit이므로 순서 보장)
    dones = [e["done"] for e in sim_events]
    assert dones == sorted(dones)


def test_simulating_phase_no_progress_cb_still_completes(monkeypatch):
    # progress_cb=None(unary 경로) — 새 emit 호출이 무해하게 no-op되고 결과는 불변인지 확인
    dfs = {"000001": _df(WARMUP, N_DAYS)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", _mock_loader(dfs))

    cfg = BacktestConfig(
        symbols=["000001"], strategy_name="Condition",
        strategy_params={"buy_conditions": [], "sell_conditions": []},
        start_date=START, end_date=dfs["000001"].index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1,
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
