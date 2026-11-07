"""BC · 체결 규칙 옵트인 — ★비용이 아니라 체결 가능성이다★
==============================================================================
대상: `src/kis_backtest_engine.py`(`enforce_price_limit`·`round_fills_to_tick`·
`fill_rules` 진단 키) · 규칙 출처 `src/data/market_rules.py`(읽기만) ·
등록 `src/engine/cost_model_registry.UNAPPLIED_RULES`

## 왜

AK 가 `tick_size`·`price_limit_pct` 를 *"비용이 아니라 체결 가능성"* 이라며
`absent` 로 등록했다. 규칙은 `market_rules` 에 이미 있고 백테스트만 안 쓴다.

## ★옵트인이다 — 기본 꺼짐★

CLAUDE.md §5: *"데이터 무결성을 고치기 전에 모델을 키우지 말라 — 금지가 아니라
순서다."* 기본으로 켜면 저장된 모든 백테스트의 뜻이 바뀐다. AK 가 세금·
스프레드·충격에 쓴 **그 선례 그대로**다.

## ★세 가지를 가른다★

- **제한 밖 → 그날 미체결.** 클립해서 체결하면 ★실재하지 않는 체결★ 이다.
- **전일 종가 미상 → 거부하지 않고 센다.** ★미상 ≠ 위반★.
- **호가 반올림은 보수적으로** — 매수 `up`, 매도 `down`. 반대면 낙관 편향이다.
  ★원주가 척도에서만 한다★ — 수정주가에서 호가 단위는 실재하지 않는다.
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from src.kis_backtest_engine import (
    DIAGNOSTIC_KEYS,
    BacktestConfig,
    BacktestEngine,
    run_backtest,
)


def _cfg(**over) -> BacktestConfig:
    base = dict(symbols=["000111"], strategy_name="Condition",
                strategy_params={}, start_date="2024-01-02",
                end_date="2024-06-28")
    base.update(over)
    return BacktestConfig(**base)


def _engine(closes: list[float], basis: str | None = "raw", **over) -> BacktestEngine:
    """규칙 판정만 보려고 프레임을 직접 꽂는다 — ★숫자는 아무것도 말하지 않는다★"""
    eng = BacktestEngine(_cfg(**over))
    idx = pd.bdate_range("2024-01-02", periods=len(closes))
    eng.ohlcv_all = {"000111": pd.DataFrame({"close": closes}, index=idx)}
    eng._price_labels = {"basis": {"000111": basis}, "adj": {}}
    return eng


def _d(i: int) -> str:
    return pd.bdate_range("2024-01-02", periods=i + 1)[-1].strftime("%Y-%m-%d")


# ── ★기본 꺼짐★ ────────────────────────────────────────────────────────

def test_both_rules_are_off_by_default():
    """변이 i — ★저장된 백테스트의 뜻이 바뀐다★"""
    cfg = _cfg()
    assert cfg.enforce_price_limit is False
    assert cfg.round_fills_to_tick is False
    sig = inspect.signature(run_backtest).parameters
    assert sig["enforce_price_limit"].default is False
    assert sig["round_fills_to_tick"].default is False


def test_off_means_the_price_is_untouched():
    eng = _engine([1000.0, 1400.0])
    assert eng._fill_price("000111", 1400.3, _d(1), "buy") == 1400.3
    assert eng._fill_rules_block()["n_rejected_by_limit"] == 0
    assert eng._fill_rules_block()["n_rounded"] == 0


# ── 가격제한 ──────────────────────────────────────────────────────────

def test_a_fill_beyond_the_upper_limit_does_not_happen():
    """변이 j — ★클립해서 체결하면 실재하지 않는 체결이다★"""
    eng = _engine([1000.0, 1400.0], enforce_price_limit=True)
    assert eng._fill_price("000111", 1400.0, _d(1), "buy") is None
    assert eng._fill_rules_block()["n_rejected_by_limit"] == 1


def test_a_fill_below_the_lower_limit_does_not_happen():
    eng = _engine([1000.0, 650.0], enforce_price_limit=True)
    assert eng._fill_price("000111", 650.0, _d(1), "sell") is None


def test_a_fill_inside_the_limit_happens_unchanged():
    """★짝★ — 항상-거부 구현을 배제한다."""
    eng = _engine([1000.0, 1250.0], enforce_price_limit=True)
    assert eng._fill_price("000111", 1250.0, _d(1), "buy") == 1250.0
    assert eng._fill_rules_block()["n_rejected_by_limit"] == 0


def test_the_limit_band_edge_is_inclusive():
    """상한가 **그 가격**에는 체결될 수 있다 — 밖만 막는다."""
    eng = _engine([1000.0, 1300.0], enforce_price_limit=True)
    assert eng._fill_price("000111", 1300.0, _d(1), "buy") == 1300.0


def test_an_unknown_previous_close_is_not_a_violation():
    """변이 k — ★미상 ≠ 위반★ 첫 봉은 전일 종가가 없다. 거부하지 않고 센다."""
    eng = _engine([1000.0], enforce_price_limit=True)
    assert eng._fill_price("000111", 5000.0, _d(0), "buy") == 5000.0
    blk = eng._fill_rules_block()
    assert blk["n_rejected_by_limit"] == 0
    assert blk["n_limit_unknown"] == 1


def test_a_mixed_price_basis_makes_the_limit_unknown():
    """원주가와 수정주가가 섞인 계열에서 전일 대비 비율은 뜻이 없다 — 미상으로 센다."""
    eng = _engine([1000.0, 1400.0], basis="mixed", enforce_price_limit=True)
    assert eng._fill_price("000111", 1400.0, _d(1), "buy") == 1400.0
    assert eng._fill_rules_block()["n_limit_unknown"] == 1


# ── 호가 단위 ─────────────────────────────────────────────────────────

def test_a_buy_rounds_up_and_a_sell_rounds_down():
    """변이 l — ★보수적으로★ 반대면 낙관 편향이다(싸게 사고 비싸게 판다)."""
    eng = _engine([2000.0, 2003.0], round_fills_to_tick=True)
    assert eng._fill_price("000111", 2003.0, _d(1), "buy") == 2005.0
    assert eng._fill_price("000111", 2003.0, _d(1), "sell") == 2000.0
    assert eng._fill_rules_block()["n_rounded"] == 2


def test_a_price_already_on_tick_is_not_counted_as_rounded():
    eng = _engine([2000.0, 2005.0], round_fills_to_tick=True)
    assert eng._fill_price("000111", 2005.0, _d(1), "buy") == 2005.0
    assert eng._fill_rules_block()["n_rounded"] == 0


@pytest.mark.parametrize("basis", ["adjusted", "mixed", None])
def test_ticks_are_not_applied_off_the_raw_price_scale(basis):
    """★수정주가 척도에서 호가 단위는 실재하지 않는다★ — 반올림하지 않고 센다."""
    eng = _engine([2000.0, 2003.0], basis=basis, round_fills_to_tick=True)
    assert eng._fill_price("000111", 2003.0, _d(1), "buy") == 2003.0
    blk = eng._fill_rules_block()
    assert blk["n_rounded"] == 0
    assert blk["n_tick_not_raw"] == 1


def test_the_limit_is_checked_on_the_rounded_price():
    """반올림이 가격을 제한 밖으로 밀면 그 가격으로는 체결할 수 없다."""
    eng = _engine([1000.0, 1299.6], enforce_price_limit=True,
                  round_fills_to_tick=True)
    # 1299.6 → up → 1300 (상한 그 자체) → 체결 가능
    assert eng._fill_price("000111", 1299.6, _d(1), "buy") == 1300.0


# ── ★결과가 말한다 — 비용이 아니다★ ─────────────────────────────────────

def test_fill_rules_is_its_own_diagnostic_not_a_cost():
    """변이 m — ★비용 ≠ 체결 가능성★ (AK 자신의 말)"""
    assert "fill_rules" in DIAGNOSTIC_KEYS
    eng = _engine([1000.0])
    assert "fill_rules" not in eng._cost_model_block()


def test_the_block_names_what_it_does_not_cover():
    """★덮지 않는 경로를 이름으로★ — 래더 매수 단계와 ETF 슬리브는 이 규칙을 안 탄다."""
    blk = _engine([1000.0])._fill_rules_block()
    assert blk["enforce_price_limit"] is False
    assert blk["round_fills_to_tick"] is False
    assert set(blk["not_covered"]) >= {"ladder_buy", "etf_sleeve"}
    assert blk["price_limit_pct"] is None      # 꺼졌으면 요율을 싣지 않는다


def test_the_block_carries_the_rule_values_it_used_when_on():
    blk = _engine([1000.0], enforce_price_limit=True)._fill_rules_block()
    from src.data import market_rules as mr
    assert blk["price_limit_pct"] == mr.price_limit_pct()


# ── ★짝 — 실제 실행에서 켜면 일어나고 끄면 안 일어난다★ ──────────────────

def _frames(monkeypatch):
    import src.data.ohlcv_loader as L
    import src.kis_strategies.condition_strategy  # noqa: F401

    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2023-01-02", periods=320)
    # ★평탄한 계열에 +45% 하루★ — 매수 신호(전일 대비 +2% 이상)는 그날 하루뿐이다.
    # 합성이다: 실제 일봉 종가는 가격제한을 넘지 않는다(넘는다면 수정주가 불연속).
    c = 3003.0 * (1 + rng.normal(0, .002, len(idx)))
    c[200:] = c[200:] * 1.45
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * .99,
                       "close": c, "volume": 1_000_000}, index=idx)
    df.attrs["price_basis"] = "raw"

    def _load(tk, s, e, prefer="auto"):
        out = df.copy()
        out.attrs["price_basis"] = "raw"
        return out
    monkeypatch.setattr(L, "load_ohlcv_unified", _load)


def _run(**over):
    return BacktestEngine(BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={
            "buy_conditions": [{"factor_token": "종가", "function_id": "pct",
                                "params": {"n": 1}, "op": "gte", "rhs": 2}],
            "sell_conditions": [{"factor_token": "종가", "function_id": "pct",
                                 "params": {"n": 1}, "op": "lte", "rhs": -2}]},
        start_date="2023-06-01", end_date="2024-03-01", **over)).run()


def test_turning_the_rules_on_really_rejects_and_rounds(monkeypatch):
    """변이 o — ★항상-꺼짐 구현을 배제한다★"""
    _frames(monkeypatch)
    # ★`signal_lag=0` 이라야 +45% 봉 **그 자체**에서 체결을 시도한다★ — 기본
    # (`signal_lag=1`)은 다음 봉에서 체결하고, 그 봉의 전일 종가는 이미 뛴 값이라
    # 제한 안이다(실측). 일봉 종가끼리는 제한을 넘기 어렵다는 뜻이기도 하다.
    on = _run(enforce_price_limit=True, round_fills_to_tick=True, signal_lag=0)
    assert not on.get("error"), on.get("message")
    blk = on["fill_rules"]
    assert blk["n_rejected_by_limit"] > 0, blk
    assert blk["n_rounded"] > 0, blk


def test_leaving_them_off_changes_nothing(monkeypatch):
    """변이 p — ★짝★ 꺼진 실행은 규칙을 모르는 실행과 거래가 같다."""
    _frames(monkeypatch)
    default = _run(signal_lag=0)
    off = _run(enforce_price_limit=False, round_fills_to_tick=False, signal_lag=0)
    assert default["fill_rules"]["n_rejected_by_limit"] == 0
    assert default["fill_rules"]["n_rounded"] == 0
    assert default["result"]["trades"] == off["result"]["trades"]
    assert default["result"]["trades"], "거래가 없으면 위 동치는 공허하다"


# ── 등록·텔레메트리·프런트 계약 ────────────────────────────────────────

def test_the_registry_now_says_opt_in_for_the_two_rules():
    """BC4 — AK 가 세금 등에 한 그대로 `absent` → `opt_in`."""
    from src.engine.cost_model_registry import UNAPPLIED_RULES
    status = {r["rule"]: r["status"] for r in UNAPPLIED_RULES}
    assert status["tick_size / is_on_tick / round_to_tick"] == "opt_in"
    assert status["price_limit_pct"] == "opt_in"
    # ★안 한 것은 여전히 안 했다고 말한다★ (짝)
    assert status["board_lot"] == "absent"
    assert status["shortable"] == "absent"


def test_telemetry_can_count_runs_that_turned_the_rules_on():
    """★행만 봐도 체결 규칙을 켜고 돈 런을 셀 수 있어야 한다★"""
    from src.api.backtest_run_routes import _diagnostic_telemetry
    blk = _engine([1000.0], enforce_price_limit=True)._fill_rules_block()
    got = _diagnostic_telemetry({"fill_rules": blk})["fill_rules"]
    assert got["enforce_price_limit"] is True
    assert got["n_rejected_by_limit"] == 0
    assert "note" not in got      # 사유 원문은 결과에 있고 행에는 수치만


def test_the_frontend_type_declares_the_block():
    """★진단 키를 더하면 프런트 타입도 같은 커밋에서★ (passthrough 스냅샷의 약속)."""
    import pathlib
    ts = pathlib.Path("frontend/src/entities/backtest/bridgeModel.ts").read_text(
        encoding="utf-8")
    assert "fill_rules?:" in ts
    for k in ("n_rejected_by_limit", "n_limit_unknown", "n_rounded", "n_tick_not_raw"):
        assert k in ts, k


# ── ★매도·분할매수도 같은 규칙을 탄다★ (변이 r 이 살아남아서 더했다) ─────

def _shaped(monkeypatch, shape):
    """평탄한 계열 + `shape(c)` 로 만든 사건. 원주가 라벨을 단다(합성)."""
    import src.data.ohlcv_loader as L
    import src.kis_strategies.condition_strategy  # noqa: F401

    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2023-01-02", periods=320)
    c = 3003.0 * (1 + rng.normal(0, .002, len(idx)))
    shape(c)
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * .99,
                       "close": c, "volume": 1_000_000}, index=idx)

    def _load(tk, s, e, prefer="auto"):
        out = df.copy()
        out.attrs["price_basis"] = "raw"
        return out
    monkeypatch.setattr(L, "load_ohlcv_unified", _load)
    return idx


def _run_with(conds_buy, conds_sell, **over):
    return BacktestEngine(BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": conds_buy,
                         "sell_conditions": conds_sell},
        start_date="2023-06-01", end_date="2024-03-01", signal_lag=0,
        **over)).run()


_UP = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 1},
        "op": "gte", "rhs": 2}]
_DOWN = [{"factor_token": "종가", "function_id": "pct", "params": {"n": 1},
          "op": "lte", "rhs": -2}]


def _crash(c):
    c[150:] *= 1.03          # 매수 신호 하루
    c[200:] *= 0.55          # ★하한가를 넘는 하루★ — 매도 신호


def test_a_sell_below_the_lower_limit_does_not_happen_that_day(monkeypatch):
    """★하한가 잠김이 실재한다★ — 그날 팔 수 없다."""
    idx = _shaped(monkeypatch, _crash)
    crash_day = idx[200].strftime("%Y-%m-%d")
    on = _run_with(_UP, _DOWN, enforce_price_limit=True)
    off = _run_with(_UP, _DOWN)
    sells_on = [t for t in on["result"]["trades"] if t["side"] == "sell"]
    sells_off = [t for t in off["result"]["trades"] if t["side"] == "sell"]
    # ★짝★ 끄면 그날 판다 — 켜면 그날 안 판다.
    assert any(t["date"] == crash_day for t in sells_off), sells_off
    assert not any(t["date"] == crash_day for t in sells_on), sells_on
    assert on["fill_rules"]["n_rejected_by_limit"] >= 1


def _surge_twice(c):
    c[150:] *= 1.03          # 첫 매수
    c[200:] *= 1.45          # ★상한가를 넘는 하루★ — 분할매수 시도


def test_an_add_on_buy_beyond_the_upper_limit_does_not_happen(monkeypatch):
    idx = _shaped(monkeypatch, _surge_twice)
    surge_day = idx[200].strftime("%Y-%m-%d")
    kw = dict(max_buy_count=3, buy_divide_pct=50.0)
    on = _run_with(_UP, [], enforce_price_limit=True, **kw)
    off = _run_with(_UP, [], **kw)
    buys_on = [t for t in on["result"]["trades"] if t["side"] == "buy"]
    buys_off = [t for t in off["result"]["trades"] if t["side"] == "buy"]
    assert any(t["date"] == surge_day for t in buys_off), buys_off
    assert not any(t["date"] == surge_day for t in buys_on), buys_on
