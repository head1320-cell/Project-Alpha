"""Allocation Studio 신규 툴 검증 — /resolve-names, /factor-portfolio, /timing,
/stress(severity), /stress-correlation.

관례: KIS_USE_MOCK=1 + monkeypatch로 팩터 표본/타이밍 헬퍼/수익률을 fake로 대체
(실네트워크·실DB 0). 핵심 주장:
  resolve-names       — 코드→종목명 라벨 (stock_master 단일 소스)
  factor-portfolio    — 방향 인지 z 가중합 랭킹(per=저평가 선호, roe=고수익 선호),
                        equal/factor_tilt 비중, 후보 부족 시 정직 에러
  timing              — 카나리 브레드스 게이트(risk_on/off), k-of-N, 추세 오버레이 현금화
  stress(severity)    — 충격 = base × severity (선형)
  stress-correlation  — 위기 상관 수렴 → 변동성·VaR 상승, intensity=0이면 무변화
"""
import os
from types import SimpleNamespace

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import src.api.allocation_routes as ar  # noqa: E402
from src.api.allocation_routes import (  # noqa: E402
    CanarySpec,
    FactorPortfolioRequest,
    FactorSpec,
    ResolveNamesRequest,
    StressCorrRequest,
    StressRequest,
    TimingRequest,
    allocation_factor_portfolio,
    allocation_resolve_names,
    allocation_stress,
    allocation_stress_correlation,
    allocation_timing,
)

RNG = np.random.default_rng(11)


# ── resolve-names ─────────────────────────────────────────────────────────────
def test_resolve_names(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_stock_name",
                        lambda c: {"005930": "삼성전자", "000660": "SK하이닉스"}.get(c))
    out = allocation_resolve_names(ResolveNamesRequest(codes=["005930", "000660", "999999"]))
    assert out["labels"]["005930"] == "삼성전자"
    assert out["labels"]["000660"] == "SK하이닉스"
    assert out["labels"]["999999"] == "999999"   # 미상은 코드 폴백(정직)


# ── factor-portfolio ──────────────────────────────────────────────────────────
def _fake_rows():
    """20 종목, per(낮을수록 좋음)·roe(높을수록 좋음). 'BEST'가 최우량."""
    rows = []
    for i in range(20):
        rows.append({"stock_code": f"C{i:04d}", "per": 30.0 - i, "roe": 5.0 + i})
    rows.append({"stock_code": "BEST", "per": 3.0, "roe": 40.0})   # 최저 per + 최고 roe
    return rows


def test_factor_portfolio_direction_and_rank(monkeypatch):
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: _fake_rows())
    monkeypatch.setattr("src.data.stock_master.get_stock_name", lambda c: c)
    req = FactorPortfolioRequest(
        factors=[FactorSpec(id="per", weight=1), FactorSpec(id="roe", weight=1)],
        top_k=5, weighting="equal")
    out = allocation_factor_portfolio(req)
    assert out["error"] is False
    # 방향 자동: per=저평가(-1), roe=고수익(+1)
    dirs = {f["id"]: f["direction"] for f in out["factors"]}
    assert dirs["per"] == -1 and dirs["roe"] == 1
    codes = [h["code"] for h in out["holdings"]]
    assert "BEST" in codes                                  # 최우량이 상위 K에 포함
    assert out["holdings"][0]["code"] == "BEST"             # 점수 1위
    assert abs(sum(h["weight"] for h in out["holdings"]) - 100.0) < 0.5


def test_factor_portfolio_tilt_skews_weight(monkeypatch):
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: _fake_rows())
    monkeypatch.setattr("src.data.stock_master.get_stock_name", lambda c: c)
    req = FactorPortfolioRequest(
        factors=[FactorSpec(id="per", weight=1), FactorSpec(id="roe", weight=1)],
        top_k=5, weighting="factor_tilt")
    out = allocation_factor_portfolio(req)
    top = out["holdings"][0]
    assert top["code"] == "BEST"
    assert top["weight"] > 100.0 / 5                        # 틸트가 1위 비중을 키움


def test_factor_portfolio_insufficient(monkeypatch):
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: [{"stock_code": "A", "per": 1}])
    req = FactorPortfolioRequest(factors=[FactorSpec(id="per")], top_k=5)
    out = allocation_factor_portfolio(req)
    assert out["error"] is True                             # 후보 부족 정직 에러


# ── timing ────────────────────────────────────────────────────────────────────
def _patch_timing(monkeypatch, score=1.0, above=True):
    monkeypatch.setattr("src.engine.tactical_allocations._score_13612",
                        lambda t, mk: score)
    monkeypatch.setattr("src.engine.tactical_allocations._abs_mom",
                        lambda t, mk, months=12: score)
    monkeypatch.setattr("src.engine.tactical_allocations._above_ma_d",
                        lambda t, mk, n=200: above)
    monkeypatch.setattr("src.engine.macro_analytics.timing_panel",
                        lambda mk: {"composite": {"score": 55, "label": "중립"},
                                    "components": [], "assets": []})
    monkeypatch.setattr(ar, "_timing_holding", lambda t, mk: (t, f"NM:{t}"))


def test_timing_risk_on(monkeypatch):
    _patch_timing(monkeypatch, score=1.0, above=True)
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612"),
                                  CanarySpec(kind="asset", id="EEM", signal="score_13612")],
                        risk_on_assets=["QQQ", "EFA"], risk_off_assets=["IEF"])
    out = allocation_timing(req)
    assert out["canary"]["signal"] == "risk_on"
    assert out["canary"]["hits"] == 2
    tickers = {h["ticker"] for h in out["holdings"]}
    assert tickers == {"QQQ", "EFA"}                        # 리스크-온 자산군


def test_timing_risk_off(monkeypatch):
    _patch_timing(monkeypatch, score=-1.0, above=True)
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612"),
                                  CanarySpec(kind="asset", id="EEM", signal="score_13612")],
                        risk_on_assets=["QQQ"], risk_off_assets=["IEF", "SHY"])
    out = allocation_timing(req)
    assert out["canary"]["signal"] == "risk_off"
    tickers = {h["ticker"] for h in out["holdings"]}
    assert tickers == {"IEF", "SHY"}


def test_timing_regime_blend_continuous_exposure(monkeypatch):
    """국면-확률 블렌드: 이진 플립 대신 P(위험선호)로 온/오프 바스켓 연속 혼합."""
    _patch_timing(monkeypatch, score=1.0, above=True)
    # 국면확률 고정: 성장+ 국면(Goldilocks+Reflation)=0.3 → p_on 30%
    monkeypatch.setattr(ar, "_timing_regime_probs",
                        lambda mk: {"Goldilocks": 0.2, "Reflation": 0.1, "Stagflation": 0.5, "Disinflation": 0.2})
    req = TimingRequest(market="us", regime_blend=True,
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612")],
                        risk_on_assets=["QQQ"], risk_off_assets=["IEF"])
    out = allocation_timing(req)
    assert out["regime_blend"] is not None
    assert out["regime_blend"]["p_risk_on"] == 30.0
    wmap = {h["ticker"]: h["weight"] for h in out["holdings"]}
    # 온 30%, 오프 70% (이진이면 100/0 이었을 것)
    assert abs(wmap.get("QQQ", 0) - 30.0) < 1.0
    assert abs(wmap.get("IEF", 0) - 70.0) < 1.0


def test_timing_vol_target_scales_exposure(monkeypatch):
    """목표 변동성: 실현 변동성 초과 시 위험자산 노출 축소(잔여 현금)."""
    _patch_timing(monkeypatch, score=1.0, above=True)
    monkeypatch.setattr(ar, "_timing_realized_vol_pct", lambda w, mk: 20.0)  # 실현 20%
    req = TimingRequest(market="us", target_vol_pct=10.0,   # 목표 10% → scale 0.5
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612")],
                        risk_on_assets=["QQQ", "EFA"])
    out = allocation_timing(req)
    assert out["vol_target"] is not None
    assert abs(out["vol_target"]["scale"] - 0.5) < 1e-6
    wmap = {h["ticker"]: h["weight"] for h in out["holdings"]}
    assert abs(wmap.get("QQQ", 0) - 25.0) < 1.0             # 50*0.5
    assert abs(wmap.get("BIL", 0) - 50.0) < 1.0             # 현금 = 100*(1-0.5)


def test_timing_k_of_n_breadth(monkeypatch):
    # 하나만 통과(양수), 하나는 실패(음수) — min_breadth=1이면 risk_on
    def _score(t, mk):
        return 1.0 if t == "SPY" else -1.0
    monkeypatch.setattr("src.engine.tactical_allocations._score_13612", _score)
    monkeypatch.setattr("src.engine.macro_analytics.timing_panel",
                        lambda mk: {"composite": None, "components": [], "assets": []})
    monkeypatch.setattr(ar, "_timing_holding", lambda t, mk: (t, t))
    req = TimingRequest(market="kr", min_breadth=1,
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612"),
                                  CanarySpec(kind="asset", id="EEM", signal="score_13612")],
                        risk_on_assets=["QQQ"])
    out = allocation_timing(req)
    assert out["canary"]["hits"] == 1 and out["canary"]["need"] == 1
    assert out["canary"]["signal"] == "risk_on"


def test_timing_overlay_moves_to_cash(monkeypatch):
    # 추세 이탈(above_ma_d=False) → 전량 현금화
    _patch_timing(monkeypatch, score=1.0, above=False)
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612")],
                        risk_on_assets=["QQQ", "EFA"],
                        overlay={"type": "ma_day", "n": 200})
    out = allocation_timing(req)
    assert out["cash_pct"] == 100.0
    cash = [h for h in out["holdings"] if h.get("is_cash")]
    assert cash and cash[0]["weight"] == 100.0


# ── stress severity ───────────────────────────────────────────────────────────
def _patch_shock(monkeypatch):
    monkeypatch.setattr(ar, "_shock_inputs", lambda code: SimpleNamespace(
        stock_code=code, corp_name=code, debt_ratio_pct=120.0, per=20.0,
        dividend_yield_pct=1.0, roe_pct=10.0, beta_1y=1.2, composite_score=50))


def test_stress_severity_scales_linearly(monkeypatch):
    _patch_shock(monkeypatch)
    base = allocation_stress(StressRequest(holdings={"005930": 50, "000660": 50},
                                           scenario="rate_hike_200bp", severity=1.0))
    dbl = allocation_stress(StressRequest(holdings={"005930": 50, "000660": 50},
                                          scenario="rate_hike_200bp", severity=2.0))
    assert base["mode"] == "hypothetical"
    assert abs(dbl["portfolio_shock_pct"] - 2.0 * base["portfolio_shock_pct"]) < 0.05
    assert dbl["severity"] == 2.0


# ── stress-correlation ────────────────────────────────────────────────────────
def _fake_lowcorr_df(tickers, n=400):
    idx = pd.bdate_range(end="2026-07-15", periods=n)
    return pd.DataFrame({t: RNG.normal(0.0004, 0.012 + 0.002 * i, size=n)
                         for i, t in enumerate(tickers)}, index=idx)


def test_stress_correlation_raises_risk(monkeypatch):
    df = _fake_lowcorr_df(["005930", "000660", "035420", "051910"])
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: df[[t for t in tickers if t in df.columns]])
    monkeypatch.setattr("src.data.stock_master.get_stock_name", lambda c: c)
    out = allocation_stress_correlation(StressCorrRequest(
        tickers=["005930", "000660", "035420", "051910"],
        target_rho=0.9, intensity=1.0, confidence_level=0.95))
    assert out["error"] is False
    assert out["stressed"]["port_vol_pct"] > out["base"]["port_vol_pct"]
    assert out["delta_var_pct"] > 0
    assert abs(out["corr_shift"]["to_avg_rho"] - 0.9) < 1e-6
    assert set(out["stressed"]["component_var"]) == set(out["names"])


def test_stress_correlation_zero_intensity_noop(monkeypatch):
    df = _fake_lowcorr_df(["005930", "000660", "035420"])
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: df[[t for t in tickers if t in df.columns]])
    monkeypatch.setattr("src.data.stock_master.get_stock_name", lambda c: c)
    out = allocation_stress_correlation(StressCorrRequest(
        tickers=["005930", "000660", "035420"], intensity=0.0))
    assert abs(out["delta_vol_pct"]) < 0.6       # 강도 0 → 거의 무변화
