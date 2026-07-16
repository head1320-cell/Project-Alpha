"""Allocation Studio API 검증 — /analyze, /factor-xray, /stress.

관례: KIS_USE_MOCK=1 + monkeypatch로 load_returns/팩터 스토어를 fake로 대체
(실네트워크·실DB 0). 핵심 주장:
  /analyze  — 응답 형태(frontier 곡선+클라우드, flow 3열, 지표, MC 분포),
              시계열 부족 자산 excluded 보고, 2자산 미만 정직 에러
  /factor-xray — 가중 z 집계 + 커버리지(미커버 자산 재정규화)
  /stress   — 가중합 = Σw·shock, 미보유 역사 윈도우 available=false
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import src.api.allocation_routes as ar  # noqa: E402
from src.api.allocation_routes import (  # noqa: E402
    AnalyzeRequest,
    StressRequest,
    XrayRequest,
    allocation_analyze,
    allocation_factor_xray,
    allocation_stress,
)

RNG = np.random.default_rng(7)
T3 = ["005930", "000660", "035420"]


def _fake_returns_df(tickers, n=300, include_bench=True):
    idx = pd.bdate_range(end="2026-07-15", periods=n)
    cols = {}
    for i, t in enumerate(tickers):
        cols[t] = RNG.normal(0.0004 + 0.0001 * i, 0.012 + 0.002 * i, size=n)
    if include_bench:
        cols["KOSPI"] = RNG.normal(0.0003, 0.008, size=n)
    return pd.DataFrame(cols, index=idx)


def _patch_returns(monkeypatch, df):
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: df)


def _patch_caps(monkeypatch, cap=100000.0):
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: cap)


# ── /analyze ─────────────────────────────────────────────────────────────────

def test_analyze_response_shape(monkeypatch):
    _patch_returns(monkeypatch, _fake_returns_df(T3))
    _patch_caps(monkeypatch)
    out = allocation_analyze(AnalyzeRequest(tickers=T3, model="mvo"))
    assert out["error"] is False
    assert out["names"] == T3
    # 프론티어 곡선 — 각 점에 자산별 가중치(w_*) 포함
    assert len(out["frontier"]["curve"]) >= 10
    assert any(k.startswith("w_") for k in out["frontier"]["curve"][0])
    # MC 클라우드
    assert len(out["frontier"]["cloud"]["returns"]) == 1500
    # flow 3열 — 각 열 합 ≈ 100
    for stage in ("market", "view_applied", "optimized"):
        assert abs(sum(out["flow"][stage].values()) - 100.0) < 1.0
    # 지표·리스크 기여·MC 분포
    assert "sharpe" in out["summary"]["portfolio"]
    assert out["summary"]["benchmark"] is not None  # KOSPI 포함
    assert set(out["risk_contributions"]) == set(T3)
    assert len(out["mc"]["bins"]) == 40
    assert out["mc"]["var95_pct"] is not None


def test_analyze_views_shift_weights(monkeypatch):
    df = _fake_returns_df(T3)
    _patch_returns(monkeypatch, df)
    _patch_caps(monkeypatch)
    base = allocation_analyze(AnalyzeRequest(tickers=T3, model="bl"))
    viewed = allocation_analyze(AnalyzeRequest(
        tickers=T3, model="bl",
        views=[{"assets": ["035420"], "direction": 1,
                "magnitude_pct": 15.0, "confidence": 90}]))
    assert viewed["views_applied"] is True
    # 강한 긍정 뷰 대상의 비중이 무뷰 대비 증가
    assert viewed["weights"]["optimized"].get("035420", 0) >= \
        base["weights"]["optimized"].get("035420", 0)


def test_analyze_excludes_short_history(monkeypatch):
    df = _fake_returns_df(T3)
    df.iloc[:-10, df.columns.get_loc("000660")] = np.nan  # 10일만 존재
    _patch_returns(monkeypatch, df)
    _patch_caps(monkeypatch)
    out = allocation_analyze(AnalyzeRequest(tickers=T3))
    assert out["error"] is False
    assert "000660" not in out["names"]
    assert any(e["ticker"] == "000660" for e in out["excluded"])


def test_analyze_honest_error_below_two_assets(monkeypatch):
    _patch_returns(monkeypatch, pd.DataFrame())
    out = allocation_analyze(AnalyzeRequest(tickers=["005930", "000660"]))
    assert out["error"] is True
    assert len(out["excluded"]) == 2


# ── /factor-xray ─────────────────────────────────────────────────────────────

class _FakeFundStore:
    def get_factors(self, code, item=None):
        # ETF(069500)는 펀더멘털 없음 — 커버리지 재정규화 검증용
        if code == "069500":
            return {}
        return {"book_to_market": 1.0 if code == "005930" else 0.5,
                "gp_to_assets": 0.4, "revenue_growth_yoy": 10.0,
                "dividend_yield": 2.0}


class _FakePriceStore:
    def get_factors(self, code, item=None):
        return {"beta_1y": 1.2 if code == "005930" else 0.9,
                "momentum_12_1": 15.0, "volatility_60d": 25.0,
                "amount_20d_avg": 500.0}


def _patch_xray(monkeypatch):
    monkeypatch.setattr("src.data.fundamentals_store.FundamentalsStore.get_default",
                        classmethod(lambda cls: _FakeFundStore()))
    monkeypatch.setattr("src.data.price_factors_store.PriceFactorsStore.get_default",
                        classmethod(lambda cls: _FakePriceStore()))
    # 유니버스 표본 60종목 (분포)
    sample = []
    rng = np.random.default_rng(3)
    for i in range(60):
        sample.append({"stock_code": f"{100000 + i}",
                       "book_to_market": float(rng.normal(0.7, 0.3)),
                       "gp_to_assets": float(rng.normal(0.35, 0.15)),
                       "revenue_growth_yoy": float(rng.normal(8, 12)),
                       "dividend_yield": float(rng.normal(2.2, 1.5)),
                       "beta_1y": float(rng.normal(1.0, 0.3)),
                       "momentum_12_1": float(rng.normal(8, 20)),
                       "volatility_60d": float(rng.normal(28, 9)),
                       "amount_20d_avg": float(abs(rng.normal(300, 250)) + 10)})
    monkeypatch.setattr("src.data.snapshot_db.sample_factors", lambda limit=500: sample)
    monkeypatch.setattr("src.data.stock_master.load_master_flags", lambda: {})
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: None)


def test_xray_weighted_and_coverage(monkeypatch):
    _patch_xray(monkeypatch)
    out = allocation_factor_xray(XrayRequest(
        holdings={"005930": 50, "000660": 30, "069500": 20}))
    assert out["error"] is False
    by_id = {f["id"]: f for f in out["factors"]}
    # 가치 팩터: ETF(20%)가 미커버 → 커버리지 80%
    assert "value" in by_id
    assert abs(by_id["value"]["coverage_pct"] - 80.0) < 0.5
    # 가격 팩터(베타)는 전 자산 커버 → 100%
    assert abs(by_id["equity_beta"]["coverage_pct"] - 100.0) < 0.5
    # 가중 z 부호: 005930 베타 1.2 > 유니버스 평균 1.0 근방 → 양수 방향 우세
    assert by_id["equity_beta"]["portfolio_z"] > -0.5


def test_xray_size_omitted_without_caps(monkeypatch):
    # get_market_cap가 None(마스터 미적재 샌드박스) → size 팩터는 정직 생략
    _patch_xray(monkeypatch)
    out = allocation_factor_xray(XrayRequest(holdings={"005930": 100}))
    assert all(f["id"] != "size" for f in out["factors"])


# ── /stress ──────────────────────────────────────────────────────────────────

def test_stress_hypothetical_weighted_sum(monkeypatch):
    monkeypatch.setattr(ar, "_shock_inputs", lambda code: __import__("types").SimpleNamespace(
        stock_code=code, corp_name=code, debt_ratio_pct=100, per=15,
        dividend_yield_pct=2, roe_pct=8, beta_1y=None, composite_score=50))
    from src.engine.stress_test_analyzer import _stock_shock
    ns = ar._shock_inputs("005930")
    unit_shock = _stock_shock(ns, "rate_hike_200bp")
    out = allocation_stress(StressRequest(
        holdings={"005930": 60, "000660": 40}, scenario="rate_hike_200bp"))
    assert out["available"] is True
    # 두 종목 동일 입력 → 포트폴리오 충격 == 개별 충격
    assert abs(out["portfolio_shock_pct"] - unit_shock) < 0.05
    assert len(out["rows"]) == 2


def test_stress_historical_unavailable_when_no_data(monkeypatch):
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: pd.DataFrame())
    out = allocation_stress(StressRequest(
        holdings={"005930": 100}, scenario="hist_2008_gfc"))
    assert out["mode"] == "historical"
    assert out["available"] is False
    assert "미보유" in out["reason"]


def test_stress_historical_replay(monkeypatch):
    df = _fake_returns_df(["005930", "000660"], n=120)
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: df)
    out = allocation_stress(StressRequest(
        holdings={"005930": 50, "000660": 50}, scenario="hist_2020_covid"))
    assert out["available"] is True
    assert len(out["portfolio_dd"]) == len(out["dates"])
    assert out["max_dd_pct"] <= 0
    assert "benchmark_dd" in out  # KOSPI 포함 fake
