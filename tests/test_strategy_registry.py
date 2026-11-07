"""BG1 · 전략 레지스트리 — ★저장된 실행을 전략으로, 다시 돌려 같은지 확인한 뒤에만★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-24-multistrategy-restore-r1-r3-design.md` §4.1 ·
대상 `src/engine/strategy_registry.py` · 재실행 경로 `screener_routes._backtest_kwargs` ·
엔진 훅 `kis_backtest_engine.run_backtest(on_engine=...)`

## 무엇을 거는가

- completed 실행만 받는다.
- ★다시 스크리닝하지 않는다★ — 스크리닝은 현재 데이터로 돌아 유니버스가 바뀔 수 있다.
  저장된 `screened_tickers` 로 재실행한다.
- ★재현 검증★ — 재실행 자산곡선이 저장본과 **전부 같아야** 등록한다. 다르면 거절하고
  첫 불일치 날짜를 말한다(*"같은 전략이라고 말할 수 없다"*).
- 저장되지 않은 재료(재편입 풀 > 평가 상한 · tactical 전략)는 **미리** 거절한다.
- 원천 실행의 mock·PIT 표시를 그대로 넘긴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.data.backtest_runs as br
from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core

_AST = {"logic": "AND", "conditions": [], "groups": []}
CODES = ["100001", "100002", "100003"]


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    yield eng
    eng.dispose()


class _Item:
    def __init__(self, code, score):
        self.stock_code = code
        self.corp_name = f"종목{code}"
        self.composite_score = score


class _Screener:
    """가짜 스크리너 — ★몇 번 불렸는지 센다★ (재등록이 스크리닝을 다시 하면 안 된다)."""

    def __init__(self):
        self.calls = 0

    def run(self, **kw):
        self.calls += 1
        items = [_Item(c, 50.0 + i) for i, c in enumerate(CODES)]
        extra = [_Item(f"2000{i:02d}", 10.0) for i in range(10)]
        return type("R", (), {"items": (items + extra)[: kw.get("limit", 13)]})()


@pytest.fixture
def market(monkeypatch):
    """종목마다 시드가 다른 결정적 합성 계열 — ★숫자는 아무것도 말하지 않는다★"""
    import src.data.ohlcv_loader as L
    import src.kis_strategies.condition_strategy  # noqa: F401

    idx = pd.bdate_range("2023-01-02", periods=320)
    frames = {}
    for k, c in enumerate(CODES + [f"2000{i:02d}" for i in range(10)]):
        rng = np.random.default_rng(100 + k)
        px = 10000 * np.exp(np.cumsum(rng.normal(0, .02, len(idx))))
        frames[c] = pd.DataFrame({"open": px, "high": px * 1.01, "low": px * .99,
                                  "close": px, "volume": 1_000_000}, index=idx)
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": frames.get(tk, pd.DataFrame()).copy())
    scr = _Screener()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: scr)
    return scr


def _req(**over) -> ScreenToBacktestRequest:
    base = dict(
        filter_ast=_AST, universe="kospi200", universe_eval_cap=3,
        replenishment_pool_cap=0, strategy_name="Condition",
        buy_conditions=[{"factor_token": "종가", "function_id": "pct",
                         "params": {"n": 5}, "op": "lte", "rhs": -3}],
        sell_conditions=[{"factor_token": "종가", "function_id": "pct",
                          "params": {"n": 5}, "op": "gte", "rhs": 5}],
        start_date="2023-06-01", end_date="2024-03-01", max_positions=3)
    base.update(over)
    return ScreenToBacktestRequest(**base)


def _stored_run(req, *, mutate=None, mock=True, pit=False) -> str:
    """원래 경로로 돌려 `backtest_runs` 에 completed 로 저장한다."""
    result = _screen_to_backtest_core(req)
    assert not result.get("error"), result.get("message")
    if mutate:
        mutate(result)
    rid = br.create_run("조건식", req.model_dump(), is_mock_data=mock,
                        is_pit_verified=pit)
    for to in ("validating", "loading_data", "simulating",
               "calculating_metrics", "persisting_results"):
        assert br.transition(rid, to)["ok"], to
    assert br.set_result(rid, result, is_mock_data=mock, is_pit_verified=pit)["ok"]
    return rid


def _registry(db):
    from src.engine.strategy_registry import StrategyRegistry
    return StrategyRegistry(db)


# ── 등록 · 재현 ──────────────────────────────────────────────────────

def test_a_reproducible_run_registers_with_an_integer_id(db, market):
    rid = _stored_run(_req())
    s = _registry(db).register(rid, "역추세 A")
    assert isinstance(s["id"], int)
    assert s["name"] == "역추세 A" and s["source_run_id"] == rid
    assert s["repro"]["equal"] is True and s["repro"]["compared_points"] > 100


def test_a_run_whose_curve_no_longer_reproduces_is_refused(db, market):
    """변이 — 재현 검증을 빼면 여기서 등록돼 버린다.

    ★짝★ 위 테스트가 같은 실행이 **통과**함을 보인다(항상-거부 배제).
    """
    from src.engine.strategy_registry import RegistrationRefused

    def _tamper(result):
        curve = result["backtest"]["equity_curve"]
        curve[150] = curve[150] + 1.0

    rid = _stored_run(_req(), mutate=_tamper)
    with pytest.raises(RegistrationRefused) as e:
        _registry(db).register(rid, "변조")
    d = e.value.detail
    assert d["first_mismatch"]["index"] == 150
    assert d["first_mismatch"]["date"]
    assert d["first_mismatch"]["stored"] != d["first_mismatch"]["rerun"]


def test_registration_does_not_screen_again(db, market):
    """★스크리닝은 현재 데이터로 돈다★ — 재등록이 스크리너를 부르면 유니버스가 바뀐다."""
    rid = _stored_run(_req())
    before = market.calls
    _registry(db).register(rid, "A")
    assert market.calls == before


def test_only_completed_runs_can_be_registered(db, market):
    from src.engine.strategy_registry import RegistrationRefused
    rid = br.create_run("조건식", _req().model_dump())
    with pytest.raises(RegistrationRefused) as e:
        _registry(db).register(rid, "대기 중")
    assert "completed" in e.value.reason


def test_an_unknown_run_is_refused(db, market):
    from src.engine.strategy_registry import RegistrationRefused
    with pytest.raises(RegistrationRefused):
        _registry(db).register("bt_does_not_exist", "없음")


def test_a_pool_that_was_never_stored_is_refused_up_front(db, market):
    """재편입 풀이 평가 상한보다 크면 그 풀은 저장되지 않았다 — 재현할 재료가 없다."""
    from src.engine.strategy_registry import RegistrationRefused
    rid = _stored_run(_req(replenishment_pool_cap=10))
    with pytest.raises(RegistrationRefused) as e:
        _registry(db).register(rid, "풀")
    assert "replenishment_pool_cap" in e.value.reason


def test_a_pool_equal_to_the_evaluated_set_is_reproducible(db, market):
    """★짝★ — 풀 ≤ 평가 상한이면 풀 == 평가 종목이라 재구성할 수 있다."""
    rid = _stored_run(_req(replenishment_pool_cap=3))
    assert _registry(db).register(rid, "풀=평가")["repro"]["equal"] is True


def test_the_same_run_cannot_be_registered_twice(db, market):
    from src.engine.strategy_registry import RegistrationRefused
    rid = _stored_run(_req())
    reg = _registry(db)
    reg.register(rid, "A")
    with pytest.raises(RegistrationRefused):
        reg.register(rid, "A 다시")


def test_the_source_labels_are_carried(db, market):
    rid = _stored_run(_req(), mock=True, pit=False)
    s = _registry(db).register(rid, "A")
    assert s["is_mock_data"] is True and s["is_pit_verified"] is False


# ── 엔진이 쓰는 인터페이스 ───────────────────────────────────────────

def test_get_and_list(db, market):
    reg = _registry(db)
    sid = reg.register(_stored_run(_req()), "A")["id"]
    assert reg.get(sid)["name"] == "A"
    assert reg.get(sid + 999) is None
    assert [s["id"] for s in reg.list()] == [sid]
    assert reg.deactivate(sid) is True
    assert reg.list() == [] and len(reg.list(active_only=False)) == 1


def test_the_returns_matrix_has_integer_columns_and_real_returns(db, market):
    reg = _registry(db)
    a = reg.register(_stored_run(_req()), "A")["id"]
    b = reg.register(_stored_run(_req(sell_conditions=[
        {"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 3}])), "B")["id"]
    m = reg.load_returns_matrix([a, b], "2023-06-01", "2024-03-01")
    assert list(m.columns) == [a, b]
    assert isinstance(m.index, pd.DatetimeIndex) and len(m) > 100
    assert not m.isna().any().any()
    assert (m.abs().sum() > 0).all(), "수익률이 전부 0 이면 원천이 비어 있다"


def test_holdings_are_snapshotted_from_the_complete_trades(db, market):
    """★보유 합 ≤ 1 · 거래가 있는 날엔 비어 있지 않다★ — 완전한 거래로 복원한다."""
    reg = _registry(db)
    sid = reg.register(_stored_run(_req()), "A")["id"]
    h = reg.load_holdings([sid], "2023-06-01", "2024-03-01")[sid]
    days = [d for d, w in h.items() if w]
    assert days, "보유가 있는 날이 하나도 없다 — 복원이 공허하다"
    for d in days:
        tot = sum(h[d].values())
        assert 0 < tot <= 1.0 + 1e-6, (d, tot)
        assert set(h[d]) <= set(CODES)


def test_the_engine_hook_does_not_change_the_result(market):
    """★`on_engine` 은 관측 전용★ — 넘겨도 안 넘겨도 결과가 같다."""
    from src.kis_backtest_engine import run_backtest
    kw = dict(symbols=CODES, strategy_name="Condition",
              strategy_params={"buy_conditions": _req().buy_conditions,
                               "sell_conditions": _req().sell_conditions},
              start_date="2023-06-01", end_date="2024-03-01", max_positions=3)
    seen = []
    a = run_backtest(**kw)
    # ★불린 **그 순간** 의 거래 수를 적는다★ — 엔진 객체만 모아 두면 실행 전에 불러도
    # 나중에 보면 거래가 차 있어 통과한다(변이 d 가 그렇게 살아남았다).
    b = run_backtest(**kw, on_engine=lambda e: seen.append(len(e.trades)))
    assert a["result"]["equity_curve"] == b["result"]["equity_curve"]
    assert len(seen) == 1 and seen[0] > 0


def test_a_factor_weighted_run_reproduces_with_its_stored_scores(db, market):
    """★팩터가중은 스크리닝 점수에서 온다★ — 저장된 `composite_score` 로 재구성해야
    재현된다(변이 i: 가중을 빼면 곡선이 갈라져 거절된다).
    """
    rid = _stored_run(_req(buy_weight_mode="factor"))
    assert _registry(db).register(rid, "팩터")["repro"]["equal"] is True
