"""AAS TIMING 통합 팩터 — 신규 시그널 패밀리 + TimingRule 공통 스키마.

정직성 회귀: 이격도·돌파·오버나이트는 공개 일반 기법의 파라미터화 구현으로 provenance가
"generic"이어야 한다(유료 컨텐츠 조건식 재현 주장 금지). systrader79 계열만 출처를 명시.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine import timing_factors as tf  # noqa: E402

TK = "SPY"


# ── 카탈로그 · 스키마 ────────────────────────────────────────────────────────
def test_catalog_groups_cover_all_families():
    cat = tf.catalog()
    fams = {g["family"] for g in cat["groups"]}
    assert fams == set(tf.SIGNAL_FAMILIES)
    # 사용자 제안 TimingRule 스키마 필드가 전부 노출
    for f in ("universe", "signal_family", "observation_window", "entry_condition",
              "exit_condition", "risk_off_asset", "rebalance_or_holding_period",
              "position_sizing", "leverage_cap", "transaction_cost_and_slippage",
              "point_in_time_data_timestamp"):
        assert f in cat["schema"], f"스키마 누락: {f}"


def test_generic_signals_are_labeled_generic_not_paywalled_replication():
    """이격도·돌파·오버나이트는 특정 유료 전략 재현이 아니라 일반 기법임을 provenance로 고정."""
    for fid in ("disparity", "vol_breakout", "channel_breakout", "overnight_return"):
        prov = tf.CATALOG_BY_ID[fid]["provenance"]
        assert "generic" in prov.lower(), f"{fid} provenance는 generic이어야 함(현재 {prov})"


def test_systrader79_signals_cite_source():
    for fid in ("avg_abs_momentum", "accel_momentum", "defense_first"):
        assert "systrader79" in tf.CATALOG_BY_ID[fid]["provenance"]


# ── 신규 시그널 동작 ─────────────────────────────────────────────────────────
def test_avg_abs_momentum_is_continuous_weight_0_1():
    v = tf.avg_abs_momentum(TK, "us", 12)
    assert v is None or (0.0 <= v <= 1.0), f"0~1 연속 비중이어야 함: {v}"


def test_avg_abs_momentum_all_positive_series(monkeypatch):
    """단조 상승 시계열 → 모든 개월 수익률 양수 → 비중 1.0."""
    monkeypatch.setattr("src.data.etf_prices.monthly_closes",
                        lambda t, m="kr", n=14: [100 + i * 5 for i in range(20)])
    assert tf.avg_abs_momentum(TK, "us", 12) == pytest.approx(1.0)


def test_avg_abs_momentum_all_negative_series(monkeypatch):
    monkeypatch.setattr("src.data.etf_prices.monthly_closes",
                        lambda t, m="kr", n=14: [200 - i * 5 for i in range(20)])
    assert tf.avg_abs_momentum(TK, "us", 12) == pytest.approx(0.0)


def test_disparity_100_when_flat(monkeypatch):
    """가격이 평평하면 이격도 = 100 (이평선과 동일)."""
    monkeypatch.setattr("src.data.etf_prices.daily_closes",
                        lambda t, m="kr", d=300: [100.0] * 60)
    assert tf.disparity(TK, "us", 20) == pytest.approx(100.0)


def test_disparity_above_100_when_rising(monkeypatch):
    monkeypatch.setattr("src.data.etf_prices.daily_closes",
                        lambda t, m="kr", d=300: [100 + i for i in range(60)])
    assert tf.disparity(TK, "us", 20) > 100.0


def test_channel_breakout_excludes_current_bar(monkeypatch):
    """당일 봉은 채널 산정에서 제외 — 자기참조면 항상 <=0이 되어 신호가 죽는다."""
    bars = [{"open": 100, "high": 100, "low": 99, "close": 100} for _ in range(30)]
    bars[-1] = {"open": 100, "high": 120, "low": 99, "close": 118}   # 당일 급등
    monkeypatch.setattr("src.data.etf_prices.daily_ohlc", lambda t, m="kr", d=300: bars)
    v = tf.channel_breakout(TK, "us", 20)
    assert v is not None and v > 0, "직전 채널(100) 대비 118 종가는 상단 돌파여야 함"


def test_vol_breakout_sign(monkeypatch):
    prev = {"open": 100, "high": 110, "low": 100, "close": 105}   # range 10
    cur = {"open": 100, "high": 120, "low": 99, "close": 118}     # trigger = 100 + .5*10 = 105
    monkeypatch.setattr("src.data.etf_prices.daily_ohlc", lambda t, m="kr", d=300: [prev, cur])
    assert tf.vol_breakout(TK, "us", 0.5) == pytest.approx((118 - 105) / 105 * 100)


def test_overnight_return_uses_open_over_prev_close(monkeypatch):
    bars = [{"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 102, "high": 103, "low": 101, "close": 102}]   # gap +2%
    monkeypatch.setattr("src.data.etf_prices.daily_ohlc", lambda t, m="kr", d=300: bars)
    assert tf.overnight_return(TK, "us", 20) == pytest.approx(2.0)


def test_defense_first_is_contrarian(monkeypatch):
    """방어자산이 현금보다 강하면 양수 → (역발상) 위험-오프. 부호 방향 고정."""
    monkeypatch.setattr("src.engine.tactical_allocations._score_13612",
                        lambda t, m: 5.0 if t != "BIL" else 1.0)
    v = tf.defense_first(None, "us")
    assert v == pytest.approx(4.0)
    # 카탈로그 기본 통과 방향이 below(= 음수일 때 위험-온)임을 고정
    assert tf.CATALOG_BY_ID["defense_first"]["default_direction"] == "below"


# ── 판정 · 스펙 변환 ─────────────────────────────────────────────────────────
def test_passes_direction_and_none_is_conservative():
    assert tf.passes(1.0, 0.0, "above") is True
    assert tf.passes(-1.0, 0.0, "above") is False
    assert tf.passes(-1.0, 0.0, "below") is True
    assert tf.passes(None, 0.0, "above") is False   # 데이터 없음 = 통과 실패(보수적)


def test_rule_from_spec_fills_defaults_and_observation_window():
    r = tf.rule_from_spec({"factor_id": "disparity", "params": {"ma_days": 60}})
    assert r.signal_family == "deviation"
    assert r.params["ma_days"] == 60
    assert r.observation_window.get("ma_days") == 60
    assert r.leverage_cap == 1.0
    assert r.transaction_cost_and_slippage["cost_bps"] == 10.0


def test_stamp_pit_records_timestamp():
    r = tf.stamp_pit(tf.rule_from_spec({"factor_id": "abs_mom"}))
    assert r.point_in_time_data_timestamp and "T" in r.point_in_time_data_timestamp


def test_evaluate_dispatches_all_catalog_ids():
    """카탈로그의 모든 팩터가 evaluate에서 라우팅된다(미구현 id로 조용히 None 금지)."""
    for c in tf.CATALOG:
        if c["id"] == "indicator":
            continue    # 매크로 시리즈는 별도 경로(_canary_eval)
        tf.evaluate(c["id"], TK, "us", c.get("params"))   # 예외 없이 값 또는 None
