"""AG4 — 결과가 **어떤 실행 가정 위에 섰는지** 스스로 말하는가

판정 규칙은 `src/domain/execution_assumption.py` 에 있고
(`test_execution_assumption.py` 가 건다), 이 파일은 **배선**을 건다:

  · 엔진이 실제로 쓴 `signal_lag`·체결가 유형이 결과까지 오는가
  · ★`perf_label`(Z) 과 다른 키인가★ — 저것은 *"이 수치가 무엇인가"*(백테스트/
    페이퍼/실계좌)이고 이것은 *"어떤 실행 가정 위에 섰나"* 다. 다른 축이다.
  · 저장했다가 되읽으면 그대로 나오는가 (`backtest_runs` 왕복)
  · ★기록 이전 런은 `unrecorded` 인가★ — `0` 으로 읽으면 없는 사실이 생긴다.

★배선했다고 실린 것은 아니다★ 그래서 엔진을 실제로 돌린다 —
`test_price_basis_meta.py` 와 같은 하네스다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
import src.data.ohlcv_loader as L  # noqa: E402
import src.kis_strategies.condition_strategy  # noqa: E402,F401 (전략 레지스트리 등록)
from src.domain.execution_assumption import (  # noqa: E402
    SIGNAL_LAG_DEFAULT,
    STATE_PRECOMPUTABLE,
    STATE_SAME_BAR,
    STATE_UNRECORDED,
    assumption_from_result,
)
from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402

BUY = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
        "op": "lte", "rhs": -3}]
SELL = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 5}]
_TICKERS = ("000000", "000001", "000002", "000003")


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=320)
    c = 10000 * np.exp(np.cumsum(rng.normal(0, .015, len(idx))))
    return pd.DataFrame({"open": c * .995, "high": c * 1.01, "low": c * .99,
                         "close": c, "volume": rng.integers(1e5, 1e6, len(idx))},
                        index=idx)


@pytest.fixture
def frames(monkeypatch):
    made = {tk: _frame(i + 3) for i, tk in enumerate(_TICKERS)}
    for d in made.values():
        d.attrs["source"] = "db"
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": made[tk].copy()
                        if tk in made else pd.DataFrame())
    return made


def _run(**over) -> dict:
    kw = dict(symbols=list(_TICKERS), strategy_name="Condition",
              strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
              start_date="2023-06-01", end_date="2024-03-01", max_positions=2)
    kw.update(over)
    return BacktestEngine(BacktestConfig(**kw)).run()


# ═══════════════════════════════════════════════════════════════════════════
# ⑬ 결과가 가정을 싣는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_result_declares_its_execution_assumption(frames):
    res = _run()
    assert not res.get("error"), res.get("message")
    meta = res.get("execution_assumption")
    assert meta is not None, "결과가 실행 가정을 말하지 않는다"
    assert meta["state"] == STATE_PRECOMPUTABLE
    assert meta["signal_lag"] == SIGNAL_LAG_DEFAULT
    assert meta["precomputable_before_open"] is True
    assert meta["reason"] is None


def test_the_result_carries_the_effective_value_not_the_default(frames):
    """★짝★ 언제나 `precomputable` 을 찍는 배선을 배제한다."""
    meta = _run(signal_lag=0)["execution_assumption"]
    assert meta["state"] == STATE_SAME_BAR
    assert meta["signal_lag"] == 0
    assert meta["precomputable_before_open"] is False
    assert "장 시작 전" in meta["reason"]


def test_the_result_carries_both_fill_types(frames):
    meta = _run(buy_fill_type="prev_close", sell_fill_type="open")["execution_assumption"]
    assert meta["buy_fill_type"] == "prev_close"
    assert meta["sell_fill_type"] == "open"
    # ★체결가 유형은 실리되 판정을 바꾸지 않는다★
    assert meta["state"] == STATE_PRECOMPUTABLE


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ ★축 섞기 배제★ — `perf_label` 안에 들어가지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_assumption_is_not_nested_inside_perf_label(frames):
    res = _run()
    assert "execution_assumption" in res, "최상위 키가 아니다"
    label = res.get("perf_label") or {}
    assert "execution_assumption" not in label, (
        "실행 가정을 perf_label 안에 넣었다 — 다른 축이다")
    assert "signal_lag" not in label


# ═══════════════════════════════════════════════════════════════════════════
# ⑯ ★동작★ — 기본값 변경이 수치를 실제로 바꿨다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_lag_actually_moves_the_numbers(frames):
    """같은 전략·같은 데이터에서 `lag=0` 과 `lag=1` 의 결과가 다르다.

    ★`lag` 를 신호 봉 선택에서 무시하는 변이를 죽인다★ — 라벨만 바뀌고 수치가
    같다면 기록은 장식이다.
    """
    same_bar = _run(signal_lag=0)["result"]["statistics"]
    lagged = _run(signal_lag=1)["result"]["statistics"]
    assert same_bar["total_return_pct"] != lagged["total_return_pct"], (
        "lag 가 수치를 전혀 바꾸지 않는다 — 신호 봉 선택에서 무시되고 있다")


# ═══════════════════════════════════════════════════════════════════════════
# ⑨⑫ 저장 → 되읽기 왕복 (★컬럼이 아니라 `result` JSON 이다★)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def store(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    yield br
    eng.dispose()


def _persist(store, result: dict) -> dict:
    rid = store.create_run("조건식", {"universe": "kospi200"})
    for to in ("validating", "loading_data", "simulating",
               "calculating_metrics", "persisting_results"):
        assert store.transition(rid, to)["ok"], to
    assert store.set_result(rid, result)["ok"]
    return store.get_run(rid)


def test_a_saved_run_keeps_its_assumption(store, frames):
    row = _persist(store, _run())
    got = assumption_from_result(row["result"])
    assert got["state"] == STATE_PRECOMPUTABLE
    assert got["signal_lag"] == SIGNAL_LAG_DEFAULT


def test_a_saved_same_bar_run_keeps_saying_same_bar(store, frames):
    """★짝★ 저장이 상태를 지어내지 않는다."""
    row = _persist(store, _run(signal_lag=0))
    assert assumption_from_result(row["result"])["state"] == STATE_SAME_BAR


def test_a_run_recorded_before_ag_reads_unrecorded(store):
    """★미상 ≠ 0★ AG 이전 런의 `result` 에는 이 블록이 아예 없다."""
    row = _persist(store, {"currency": "KRW", "result": {"statistics": {}}})
    got = assumption_from_result(row["result"])
    assert got["state"] == STATE_UNRECORDED
    assert got["signal_lag"] is None
    assert got["precomputable_before_open"] is None


# ═══════════════════════════════════════════════════════════════════════════
# ⑪⑫ 저장된 런을 **조회할 때** 미상이 미상이라고 나오는가
#
# ★기록 이전 런은 키가 아예 없다★ — 그러면 화면은 "값이 없다" 와 "질문한 적이
# 없다" 를 구별할 수 없다. 라우트가 리더를 통과시켜 사유까지 준다.
# ═══════════════════════════════════════════════════════════════════════════

def test_the_run_detail_route_states_the_assumption(store, frames):
    from src.api.backtest_run_routes import run_full
    rid = store.create_run("조건식", {"universe": "kospi200"})
    for to in ("validating", "loading_data", "simulating",
               "calculating_metrics", "persisting_results"):
        assert store.transition(rid, to)["ok"], to
    assert store.set_result(rid, _run())["ok"]
    out = run_full(rid)
    assert out["execution_assumption"]["state"] == STATE_PRECOMPUTABLE
    # ★다른 축이다★ — `perf_label` 안에 들어가지 않는다.
    assert "execution_assumption" not in out["perf_label"]


def test_the_run_detail_route_says_unrecorded_for_an_old_run(store):
    """★미상 ≠ 0★ AG 이전에 저장된 런은 사유와 함께 미상이라고 나온다."""
    from src.api.backtest_run_routes import run_full
    rid = store.create_run("조건식", {"universe": "kospi200"})
    for to in ("validating", "loading_data", "simulating",
               "calculating_metrics", "persisting_results"):
        assert store.transition(rid, to)["ok"], to
    assert store.set_result(rid, {"result": {"statistics": {}}})["ok"]
    got = run_full(rid)["execution_assumption"]
    assert got["state"] == STATE_UNRECORDED
    assert got["signal_lag"] is None
    assert "알 수 없습니다" in got["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# AH — ★옵트인 누출이 결과에서 보이는가★
#
# `allow_snapshot_fundamentals=True` 로 돌린 실행과 끄고 돌린 실행의 결과가
# **완전히 같았다**(직접 돌려 확인). 오늘의 ROE/PER/PBR 를 과거 전 구간에 방송한
# 실행이 깨끗한 실행과 구별되지 않는다면, 그 수치를 본 사람은 알 방법이 없다.
# ═══════════════════════════════════════════════════════════════════════════

def test_a_snapshot_fundamentals_run_says_so(frames):
    from src.engine.run_evidence import STATUS_VERIFIED
    res = _run(strategy_params={"buy_conditions": BUY, "sell_conditions": SELL,
                                "allow_snapshot_fundamentals": True})
    block = res.get("estimator_leakage")
    assert block is not None, "결과가 추정 누출을 말하지 않는다"
    assert block["status"] != STATUS_VERIFIED
    assert "snapshot_fundamentals" in block["broken_axes"]
    assert "look-ahead" in block["axes"]["snapshot_fundamentals"]["reason"]


def test_a_run_without_the_opt_in_is_measured_as_clean(frames):
    """★짝★ 끄고 돈 실행은 **재봤더니 안 켰다**이지 미상이 아니다."""
    from src.engine.run_evidence import STATUS_VERIFIED
    block = _run()["estimator_leakage"]
    assert block["status"] == STATUS_VERIFIED
    assert "snapshot_fundamentals" in block["applicable"]
    assert block["broken_axes"] == [] and block["unknown_axes"] == []


def test_the_leakage_block_is_not_inside_pit_evidence(frames):
    """★두 축을 안 섞는다★ — `pit_evidence` 는 데이터의 시점 정합을 묻는다."""
    res = _run()
    assert "estimator_leakage" in res
    assert "estimator_leakage" not in (res.get("pit_evidence") or {})
    assert "estimator_leakage" not in (res.get("perf_label") or {})
