"""벡터화 → per-bar 폴백을 ★센다★ (⑤)

## 무엇이 문제였나 — 조용한 폴백이 세 겹이었다

전략 신호는 두 경로로 난다: 사전계산(벡터화) 조회, 실패하면 봉마다 재평가하는
per-bar 폴백. 그런데 **어느 쪽이 얼마나 돌았는지 아무도 세지 않았다.**

폴백으로 떨어지는 세 지점이 전부 `logger.debug` 다:
  · `condition_strategy.precompute_signals` — 종목별 예외 격리
  · `kis_backtest_engine` — `precompute_signals` / `prepare_panel` 통째 실패

그리고 디스패치 자체가 아무것도 증가시키지 않았다:

```python
                if self.cfg.vectorize_signals and hasattr(strategy, "signal_at"):
                    signal = strategy.signal_at(ticker, sig_date)
                if signal is None:
                    signal = self._generate_signal_as_of(strategy, ticker, sig_slice)
                if signal is None:
                    continue          # ← 두 경로 모두 실패해도 조용히 넘어간다
```

★마지막 줄이 가장 나쁘다★ — 벡터화도 폴백도 실패한 종목은 **그냥 거래하지
않는다.** 결과 JSON 에서 "조건이 안 맞은 종목" 과 구별되지 않는다.

그리고 이것은 정직성 문제일 뿐 아니라 **속도 문제**다. 폴백은 O(종목×봉)이라
저장소 자신의 실측이 *"종목 1개 예외만으로 5배+ 슬로다운"* 이라고 적어 뒀다
(`condition_strategy.py` `precompute_signals` 독스트링). 사용자가 "백테스팅이
오래 걸린다" 고 할 때, 지금은 그 원인이 이것인지 **물어볼 방법이 없다.**

★관용구는 이미 같은 파일에 있다★ — `self._intraday = {"applied":0,"fallback":0}`
가 `applied_pct` 와 함께 결과에 실린다. 그 모양을 그대로 쓴다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as L  # noqa: E402
import src.kis_strategies.condition_strategy as CS  # noqa: E402
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

N_SYM, N_BAR = 6, 700
BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]


@pytest.fixture
def frames(monkeypatch):
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2023-01-02", periods=N_BAR)
    out = {}
    for i in range(N_SYM):
        c = 10000 * np.exp(np.cumsum(rng.normal(0, .018, N_BAR)))
        out[f"{i:06d}"] = pd.DataFrame(
            {"open": c * .995, "high": c * 1.01, "low": c * .99,
             "close": c, "volume": rng.integers(1e5, 1e6, N_BAR)}, index=idx)
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": out.get(tk, pd.DataFrame()).copy())
    return out


def _run(frames) -> dict:
    return BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date="2023-06-01", end_date="2025-09-01", max_positions=3)).run()


def _meta(out: dict) -> dict:
    m = out.get("signal_path")
    assert m is not None, "결과에 signal_path 가 없다 — 폴백이 여전히 안 보인다"
    return m


# ── 세는가 ──────────────────────────────────────────────────────────────────

def test_a_healthy_run_reports_the_vectorized_path(frames):
    out = _run(frames)
    m = _meta(out)
    assert m["vectorized"] > 0, m
    assert m["per_bar"] == 0 and m["failed"] == 0, f"멀쩡한 실행에 폴백이 잡혔다: {m}"
    assert m["vectorized_pct"] == pytest.approx(100.0), m


def test_a_forced_fallback_is_counted_not_hidden(frames, monkeypatch):
    """★이것이 핵심★ 폴백이 돌았으면 결과가 그렇게 말해야 한다."""
    monkeypatch.setattr(
        CS.ConditionStrategy, "_precompute_ticker",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("강제 폴백")))
    m = _meta(_run(frames))
    assert m["per_bar"] > 0, f"폴백이 돌았는데 0 이다: {m}"
    assert m["vectorized"] == 0, m
    assert m["vectorized_pct"] == pytest.approx(0.0), m


def test_a_signal_that_fails_both_paths_is_counted_not_silently_skipped(frames, monkeypatch):
    """★두 경로 모두 실패한 종목이 '조건 미충족' 과 섞이면 안 된다★

    예전에는 `if signal is None: continue` 로 조용히 넘어가, 그 종목이 왜 한 번도
    거래하지 않았는지 결과 어디에도 없었다.
    """
    monkeypatch.setattr(
        CS.ConditionStrategy, "_precompute_ticker",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("강제 폴백")))
    monkeypatch.setattr(
        CS.ConditionStrategy, "generate_signal",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("폴백도 실패")))
    m = _meta(_run(frames))
    assert m["failed"] > 0, f"두 경로 모두 실패했는데 세어지지 않았다: {m}"


# ── 짝: 지어내지 않는다 ─────────────────────────────────────────────────────

def test_the_counters_are_not_constants(frames, monkeypatch):
    """★상수로 박아도 통과하는 테스트를 막는다★

    앞 테스트들은 "> 0" 만 본다 — 항상 1 을 넣는 구현도 통과한다. 실제 신호 조회
    횟수(종목 × 봉)에 비례해야 한다.
    """
    small = _meta(_run(frames))
    assert small["vectorized"] > N_SYM * 100, (
        f"조회 수가 종목·봉 수에 비례하지 않는다: {small}")


def test_the_percentage_is_absent_rather_than_zero_when_nothing_ran(frames, monkeypatch):
    """★미측정 ≠ 0%★ 신호 조회가 한 번도 없었으면 `0%` 가 아니라 None 이다.

    `0.0` 을 적으면 "벡터화가 한 번도 안 먹혔다" 는 **하지 않은 진술**이 된다.
    """
    from src.kis_backtest_engine import _signal_path_meta
    assert _signal_path_meta({"vectorized": 0, "per_bar": 0, "failed": 0})["vectorized_pct"] is None
