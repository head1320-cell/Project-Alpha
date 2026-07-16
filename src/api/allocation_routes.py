"""Allocation Studio API — 포트폴리오 구축·최적화·분석 (Two Sigma Venn 벤치마킹).

POST /api/v1/allocation/analyze      — 프론티어+클라우드+최적화+흐름+리스크+지표+MC (1콜)
POST /api/v1/allocation/factor-xray  — 포트폴리오 가중 팩터 노출 vs 유니버스/벤치마크
POST /api/v1/allocation/stress       — 가상 시나리오(M8) + 역사 리플레이
GET  /api/v1/allocation/stress-catalog — 시나리오 목록(가상 4 + 역사, 가용성 포함)

전부 기존 엔진 조립: kis_portfolio_analyzer(프론티어·리스크기여) ·
portfolio_optimizer(MC 클라우드) · allocation_studio(사용자 뷰 BL·모델 스위치) ·
quant_metrics(지표) · stress_test_analyzer(M8 충격) · 팩터 스토어(X-ray).
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.allocation")

router = APIRouter(prefix="/api/v1/allocation", tags=["allocation-studio"])

_MIN_OBS = 30          # 자산별 최소 관측일 (kis_portfolio_analyzer 관례와 동일)
_RF = 0.035            # 무위험수익률 (quant_metrics 기본과 동일)

# 역사 리플레이 카탈로그 — DB 커버리지 밖 윈도우는 정직하게 unavailable
_HIST_WINDOWS = {
    "hist_2008_gfc": {"label": "2008 금융위기", "start": "2007-10-01", "end": "2009-03-31"},
    "hist_2018_trade": {"label": "2018 미중 무역분쟁", "start": "2018-01-01", "end": "2019-01-31"},
    "hist_2020_covid": {"label": "2020 코로나 급락", "start": "2020-01-20", "end": "2020-08-31"},
    "hist_2022_rates": {"label": "2022 금리 충격", "start": "2022-01-01", "end": "2022-10-31"},
}


# ── 요청 모델 ─────────────────────────────────────────────────────────────────
class AllocationView(BaseModel):
    assets: list[str] = Field(..., min_length=1)
    direction: int = 1                      # +1 상회 / -1 하회
    magnitude_pct: float = Field(2.0, ge=0, le=50)   # 연간 기대수익 크기(%)
    confidence: float = Field(50, ge=0, le=100)
    label: str | None = None                # 테제 문장 (표시용, 계산 미사용)


class AnalyzeRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=30)
    weights: dict[str, float] | None = None          # 없으면 균등
    views: list[AllocationView] | None = None
    model: str = "mvo"                                # mvo|bl|risk_parity|hrp|min_var
    delta: float = Field(2.5, ge=0.5, le=10)          # 위험회피 λ (π 스케일)
    tau: float = Field(0.05, ge=0.001, le=1.0)
    lookback_days: int = Field(756, ge=90, le=3650)   # 거래일 기준 ~3년
    benchmark: str = "KOSPI"
    mc_paths: int = Field(500, ge=100, le=2000)


class XrayRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)   # {code: weight_pct}


class StressRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    scenario: str = "rate_hike_200bp"
    benchmark: str = "KOSPI"


# ── 공용 헬퍼 ─────────────────────────────────────────────────────────────────
def _mock_returns_fallback(want: list[str], start: str, end: str):
    """DB 무(빈 결과)일 때 mock 모드 한정 합성 수익률 — 기존 로더 체인 재사용.

    mock_gate 원칙: KIS_USE_MOCK=1(개발 기본)에서만 합성 허용, 운영에선 빈
    결과를 그대로 정직 반환(상위에서 excluded/에러로 보고).
    """
    from src.data.mock_gate import mock_allowed
    if not mock_allowed():
        return None
    import pandas as pd

    from src.data.ohlcv_loader import load_ohlcv_unified
    cols = {}
    for t in want:
        try:
            df = load_ohlcv_unified(t, start, end, prefer="mock")
            if df is not None and len(df) > _MIN_OBS:
                cols[t] = df["close"].pct_change()
        except Exception:
            continue
    if not cols:
        return None
    return pd.DataFrame(cols).dropna(how="all")


def _load_clean_returns(tickers: list[str], benchmark: str | None, lookback_days: int):
    """load_returns → (returns_df[keep], bench_series|None, excluded, coverage)."""
    from src.kis_portfolio_analyzer import load_returns
    end = date.today()
    start = end - timedelta(days=int(lookback_days * 1.6) + 30)  # 캘린더 여유
    want = list(dict.fromkeys(tickers + ([benchmark] if benchmark else [])))
    df = load_returns(want, start.isoformat(), end.isoformat())
    src_mock = False
    if df is None or df.empty:
        mock_df = _mock_returns_fallback(want, start.isoformat(), end.isoformat())
        if mock_df is not None:
            df = mock_df
            src_mock = True

    excluded = []
    bench = None
    if benchmark is not None and benchmark in getattr(df, "columns", []):
        bench = df[benchmark]
    keep = []
    for t in tickers:
        if df.empty or t not in df.columns:
            excluded.append({"ticker": t, "reason": "시세 데이터 없음"})
        elif int(df[t].dropna().shape[0]) < _MIN_OBS:
            excluded.append({"ticker": t, "reason": f"시계열 {_MIN_OBS}일 미만"})
        else:
            keep.append(t)
    if not keep:
        return None, None, excluded, {}
    returns = df[keep].dropna()
    if len(returns) > lookback_days:
        returns = returns.iloc[-lookback_days:]
    if bench is not None:
        bench = bench.reindex(returns.index).dropna()
    coverage = {
        "start": str(returns.index.min().date()) if len(returns) else None,
        "end": str(returns.index.max().date()) if len(returns) else None,
        "n_obs": int(len(returns)),
        "benchmark_available": bench is not None and len(bench) >= _MIN_OBS,
        "source": "mock" if src_mock else "db",
    }
    return returns, bench, excluded, coverage


def _series_stats(ret: np.ndarray, ppy: int = 252) -> dict:
    """일별 수익률 시리즈 → 헤드라인 지표 (연수익·변동성·Sharpe·MDD·Sortino·Calmar)."""
    r = np.asarray(ret, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return {}
    ann = float(r.mean() * ppy)
    vol = float(r.std(ddof=1) * math.sqrt(ppy))
    sharpe = (ann - _RF) / vol if vol > 0 else 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    mdd = float(dd.min())
    downside = r[r < 0]
    dvol = float(downside.std(ddof=1) * math.sqrt(ppy)) if downside.size > 1 else 0.0
    sortino = (ann - _RF) / dvol if dvol > 0 else 0.0
    calmar = ann / abs(mdd) if mdd < 0 else 0.0
    return {
        "expected_return_pct": round(ann * 100, 2),
        "volatility_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(mdd * 100, 2),
        "sortino": round(sortino, 2),
        "calmar": round(calmar, 2),
    }


def _labels(codes: list[str]) -> dict[str, str]:
    from src.data.stock_master import get_stock_name
    return {c: (get_stock_name(c) or c) for c in codes}


def _w_dict(names: list[str], w: np.ndarray) -> dict[str, float]:
    return {names[i]: round(float(w[i]) * 100, 2) for i in range(len(names))
            if w[i] > 0.0005}


# ── /analyze ─────────────────────────────────────────────────────────────────
@router.post("/analyze")
def allocation_analyze(req: AnalyzeRequest):
    """포트폴리오 종합 분석 — 하나의 수익률 행렬에서 전 패널 파생 (추가 DB 조회 0)."""
    try:
        returns, bench, excluded, coverage = _load_clean_returns(
            req.tickers, req.benchmark, req.lookback_days)
        if returns is None or len(returns.columns) < 2:
            return {"error": True,
                    "message": "분석 가능한 자산이 2개 미만입니다. 시세가 적재된 자산을 추가하세요.",
                    "excluded": excluded}

        names = list(returns.columns)
        R = returns.values

        # 1) 뷰+모델 최적화 (allocation_studio 엔진)
        from src.engine.allocation_studio import optimize
        views = [v.model_dump() for v in (req.views or [])]
        opt = optimize(req.model, names, R, views=views or None,
                       delta=req.delta, tau=req.tau)

        # 2) 현재(사용자) 가중치 분석 — 리스크 기여·상관 (기존 PortfolioAnalyzer)
        from src.kis_portfolio_analyzer import PortfolioAnalyzer
        user_w = None
        if req.weights:
            user_w = {t: max(float(req.weights.get(t, 0.0)), 0.0) for t in names}
            if sum(user_w.values()) <= 0:
                user_w = None
        analyzer = PortfolioAnalyzer(returns=returns, weights=user_w)
        metrics = analyzer.analyze()

        # 3) 효율적 프론티어 곡선(SLSQP 30점, 각 점 자산별 가중치 포함)
        frontier_records = []
        try:
            ef = analyzer.efficient_frontier(n_points=30)
            if ef is not None and not ef.empty:
                frontier_records = ef.round(4).to_dict("records")
        except Exception as e:
            logger.warning(f"frontier 실패: {e}")

        # 4) MC Dirichlet 클라우드 (기존 portfolio_optimizer — 가중치 배열은 미포함)
        cloud = {"returns": [], "volatilities": [], "sharpes": []}
        try:
            from src.models.portfolio_optimizer import efficient_frontier as mc_frontier
            mc = mc_frontier(returns, n_portfolios=1500, risk_free_rate=_RF)
            f = mc.get("frontier", {}) if isinstance(mc, dict) else {}
            cloud = {"returns": f.get("returns", []),
                     "volatilities": f.get("volatilities", []),
                     "sharpes": f.get("sharpe_ratios", [])}
        except Exception as e:
            logger.warning(f"MC cloud 실패: {e}")

        # 5) 마커 포인트들 (연율 좌표: x=vol%, y=ret%)
        mu_a = opt["mu_annual"]
        S_a = opt["sigma_annual"]

        def _pt(w: np.ndarray) -> dict:
            r = float(w @ mu_a)
            v = float(np.sqrt(w @ S_a @ w))
            return {"return_pct": round(r * 100, 2), "volatility_pct": round(v * 100, 2)}

        w_cur = metrics.weights.reindex(names).fillna(0).values
        points = {
            "current": _pt(w_cur),
            "market": _pt(opt["flow"]["market"]),
            "optimal": _pt(opt["weights"]),
        }

        # 6) Sankey 3단계 흐름
        flow = {stage: _w_dict(names, w) for stage, w in opt["flow"].items()}

        # 7) 요약 지표 — 최적화 포트폴리오 vs 벤치마크 vs Active
        port_ret = returns.values @ opt["weights"]
        pf_stats = _series_stats(port_ret)
        bench_stats = {}
        active = {}
        if bench is not None and len(bench) >= _MIN_OBS:
            bench_stats = _series_stats(bench.values)
            active = {k: round(pf_stats[k] - bench_stats[k], 2)
                      for k in pf_stats if k in bench_stats}

        # quant_metrics 보강 지표 (VaR/CVaR 등 — 히스토리컬)
        from src.engine.quant_metrics import compute_metrics
        eq = np.cumprod(1.0 + port_ret)
        extra = compute_metrics(port_ret, eq, benchmark_returns=(
            bench.values if bench is not None and len(bench) == len(port_ret) else None))

        # 8) MC 1년 수익 분포 (GBM 정규근사, 시드 고정 — 결정론)
        mu_d = float(np.mean(port_ret))
        sd_d = float(np.std(port_ret, ddof=1)) if len(port_ret) > 1 else 0.0
        rng = np.random.default_rng(42)
        z = rng.standard_normal(req.mc_paths)
        term = np.exp((mu_d - 0.5 * sd_d * sd_d) * 252 + sd_d * math.sqrt(252) * z) - 1.0
        lo, hi = np.percentile(term, [0.5, 99.5])
        edges = np.linspace(lo, hi, 41)
        counts, _ = np.histogram(term, bins=edges)
        mc_dist = {
            "bins": [{"x0": round(float(edges[i]) * 100, 2),
                      "x1": round(float(edges[i + 1]) * 100, 2),
                      "count": int(counts[i])} for i in range(len(counts))],
            "expected_pct": round(float(term.mean()) * 100, 2),
            "var95_pct": round(float(-np.percentile(term, 5)) * 100, 2),
            "cvar95_pct": round(float(-term[term <= np.percentile(term, 5)].mean()) * 100, 2),
            "note": "GBM 정규근사 1년 시뮬레이션 (히스토리컬 μ·σ 기반)",
        }

        return {
            "error": False,
            "names": names,
            "labels": _labels(names),
            "excluded": excluded,
            "coverage": coverage,
            "model": req.model,
            "params": {"delta": req.delta, "tau": req.tau,
                       "lookback_days": req.lookback_days},
            "views_applied": opt["views_applied"],
            "skipped_views": opt["skipped_views"],
            "cap_missing": opt["cap_missing"],
            "weights": {"current": _w_dict(names, w_cur),
                        "optimized": _w_dict(names, opt["weights"])},
            "flow": flow,
            "frontier": {"curve": frontier_records, "cloud": cloud},
            "points": points,
            "risk_contributions": {k: round(float(v) * 100, 2)
                                   for k, v in metrics.risk_contributions.items()},
            "correlation": metrics.correlation_matrix.round(3).to_dict(),
            "summary": {"portfolio": pf_stats, "benchmark": bench_stats or None,
                        "active": active or None,
                        "benchmark_label": req.benchmark if bench_stats else None,
                        "extra": {"var_pct": extra.get("var_pct"),
                                  "cvar_pct": extra.get("cvar_pct"),
                                  "information_ratio": extra.get("information_ratio")}},
            "mc": mc_dist,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("allocation analyze 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /factor-xray ─────────────────────────────────────────────────────────────
# (표시라벨, 팩터 id, 소스, 변환, 부호반전) — 커버 불가 팩터는 응답에서 정직 생략
_XRAY_SPEC = [
    ("equity_beta", "시장 베타", "beta_1y", "price", None, False),
    ("momentum", "모멘텀", "momentum_12_1", "price", None, False),
    ("low_vol", "저변동성", "volatility_60d", "price", None, True),
    ("value", "가치", "book_to_market", "fund", None, False),
    ("quality", "퀄리티", "gp_to_assets", "fund", None, False),
    ("growth", "성장", "revenue_growth_yoy", "fund", None, False),
    ("dividend", "배당", "dividend_yield", "fund", None, False),
    ("size", "규모", "__market_cap__", "master", "log", False),
    ("liquidity", "유동성", "amount_20d_avg", "price", "log", False),
]


def _xf(v, transform):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if transform == "log":
        return math.log10(f) if f > 0 else None
    return f


def _factor_value(code: str, fid: str, source: str, fund_cache: dict, price_cache: dict):
    if source == "master":
        from src.data.stock_master import get_market_cap
        return get_market_cap(code)
    cache = fund_cache if source == "fund" else price_cache
    if code not in cache:
        try:
            if source == "fund":
                from src.data.fundamentals_store import FundamentalsStore
                cache[code] = FundamentalsStore.get_default().get_factors(code, None) or {}
            else:
                from src.data.price_factors_store import PriceFactorsStore
                cache[code] = PriceFactorsStore.get_default().get_factors(code, None) or {}
        except Exception:
            cache[code] = {}
    return cache[code].get(fid)


@router.post("/factor-xray")
def allocation_factor_xray(req: XrayRequest):
    """포트폴리오 가중 팩터 노출(z-score) vs 유니버스 분포·KOSPI200 벤치마크.

    커버리지 정직 규칙: 팩터 값이 없는 자산(예: ETF의 펀더멘털)은 그 팩터에서
    가중 재정규화하고 커버리지 %로 표기 — 조용한 0 처리 금지.
    """
    try:
        from src.data.snapshot_db import sample_factors
        from src.data.stock_master import get_market_cap, load_master_flags

        holdings = {c: max(float(w), 0.0) for c, w in req.holdings.items()}
        tot = sum(holdings.values())
        if tot <= 0:
            return {"error": True, "message": "보유 비중 합이 0입니다."}
        holdings = {c: w / tot for c, w in holdings.items()}

        sample = sample_factors(500) or []
        if not sample:
            # DB 무 → mock 모드 한정 합성 유니버스 표본 (mock 스토어는 종목별 결정론)
            from src.data.mock_gate import mock_allowed
            if mock_allowed():
                from src.data.fundamentals_store import FundamentalsStore
                from src.data.price_factors_store import PriceFactorsStore
                fs = FundamentalsStore.get_default()
                ps = PriceFactorsStore.get_default()
                for i in range(60):
                    code = f"{100 + i * 137 % 900:03d}{i * 41 % 1000:03d}"
                    row = {"stock_code": code}
                    try:
                        row.update(fs.get_factors(code, None) or {})
                        row.update(ps.get_factors(code, None) or {})
                    except Exception:
                        continue
                    sample.append(row)
        flags = load_master_flags() or {}
        k200 = {c for c, f in flags.items() if f.get("is_kospi200")}

        fund_cache: dict = {}
        price_cache: dict = {}
        out_factors = []
        for key, label, fid, source, transform, invert in _XRAY_SPEC:
            # 유니버스 분포 (표본 + master 시총)
            if source == "master":
                uni_pairs = [(r.get("stock_code"), get_market_cap(r.get("stock_code")))
                             for r in sample]
            else:
                uni_pairs = [(r.get("stock_code"), r.get(fid)) for r in sample]
            uni = [( c, _xf(v, transform)) for c, v in uni_pairs]
            uni_vals = np.array([v for _, v in uni if v is not None], dtype=float)
            if uni_vals.size < 20:
                continue  # 분포 부족 — 팩터 자체를 정직 생략
            mean, std = float(uni_vals.mean()), float(uni_vals.std(ddof=1))
            if std <= 1e-12:
                continue

            def _z(v):
                z = (v - mean) / std
                return float(np.clip(-z if invert else z, -3.0, 3.0))

            # 포트폴리오 가중 z (커버 자산만 재정규화)
            acc, cov_w = 0.0, 0.0
            for code, w in holdings.items():
                v = _xf(_factor_value(code, fid, source, fund_cache, price_cache), transform)
                if v is None:
                    continue
                acc += w * _z(v)
                cov_w += w
            pf_z = acc / cov_w if cov_w > 0 else None

            # 벤치마크: 표본 내 KOSPI200 캡가중 (플래그 없으면 유니버스 평균=0 근방)
            bz_acc, bz_w = 0.0, 0.0
            for code, v in uni:
                if v is None or (k200 and code not in k200):
                    continue
                cap = get_market_cap(code) or 1.0
                bz_acc += cap * _z(v)
                bz_w += cap
            bench_z = bz_acc / bz_w if bz_w > 0 else 0.0

            if pf_z is None:
                continue  # 포트폴리오 전체가 미커버 — 표기 불가, 정직 생략
            out_factors.append({
                "id": key, "label": label,
                "portfolio_z": round(pf_z, 2),
                "benchmark_z": round(bench_z, 2),
                "coverage_pct": round(cov_w * 100, 1),
                "n_universe": int(uni_vals.size),
            })

        return {"error": False, "factors": out_factors,
                "benchmark_label": "KOSPI200(표본 캡가중)" if k200 else "유니버스 평균",
                "note": "유니버스 표본 z-score 기준. 커버리지 <100%는 해당 팩터 데이터가 없는 자산(예: ETF 펀더멘털)을 재정규화한 것."}
    except Exception:
        logger.exception("factor-xray 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /stress ──────────────────────────────────────────────────────────────────
def _shock_inputs(code: str):
    """M8 _stock_shock 입력 — item: 스냅샷 우선, 없으면 팩터 스토어 폴백(정직 매핑)."""
    from types import SimpleNamespace

    from src.data.snapshot_db import bulk_read
    snap = bulk_read([f"item:{code}"], max_age_sec=86400 * 30) or {}
    d = snap.get(f"item:{code}")
    if isinstance(d, dict) and d.get("stock_code"):
        return SimpleNamespace(
            stock_code=code, corp_name=d.get("corp_name") or code,
            debt_ratio_pct=d.get("debt_ratio_pct"), per=d.get("per"),
            dividend_yield_pct=d.get("dividend_yield_pct"), roe_pct=d.get("roe_pct"),
            beta_1y=d.get("beta_1y"), composite_score=d.get("composite_score") or 50)
    try:
        from src.data.fundamentals_store import FundamentalsStore
        from src.data.price_factors_store import PriceFactorsStore
        f = FundamentalsStore.get_default().get_factors(code, None) or {}
        p = PriceFactorsStore.get_default().get_factors(code, None) or {}
        d2e = f.get("debt_to_equity")
        return SimpleNamespace(
            stock_code=code, corp_name=code,
            debt_ratio_pct=(float(d2e) * 100 if d2e is not None else None),
            per=f.get("per"), dividend_yield_pct=f.get("dividend_yield"),
            roe_pct=f.get("roe"), beta_1y=p.get("beta_1y"), composite_score=50)
    except Exception:
        return SimpleNamespace(stock_code=code, corp_name=code, debt_ratio_pct=None,
                               per=None, dividend_yield_pct=None, roe_pct=None,
                               beta_1y=None, composite_score=50)


@router.post("/stress")
def allocation_stress(req: StressRequest):
    """가상 시나리오(M8 펀더멘털 충격 가중합) 또는 역사 윈도우 리플레이."""
    try:
        holdings = {c: max(float(w), 0.0) for c, w in req.holdings.items()}
        tot = sum(holdings.values())
        if tot <= 0:
            return {"error": True, "message": "보유 비중 합이 0입니다."}
        holdings = {c: w / tot for c, w in holdings.items()}

        # ── 역사 리플레이 ──
        if req.scenario in _HIST_WINDOWS:
            win = _HIST_WINDOWS[req.scenario]
            from src.kis_portfolio_analyzer import load_returns
            df = load_returns(list(holdings) + [req.benchmark], win["start"], win["end"])
            if df is None or df.empty:
                mock_df = _mock_returns_fallback(list(holdings) + [req.benchmark],
                                                 win["start"], win["end"])
                if mock_df is not None:
                    df = mock_df
            avail = [c for c in holdings if not df.empty and c in df.columns
                     and int(df[c].dropna().shape[0]) >= _MIN_OBS]
            if not avail:
                return {"error": False, "mode": "historical", "available": False,
                        "scenario": req.scenario, "label": win["label"],
                        "reason": "해당 기간 시세 데이터 미보유 (KRX 백필 범위 밖)"}
            dropped = [c for c in holdings if c not in avail]
            sub = df[avail].dropna()
            w = np.array([holdings[c] for c in avail])
            w = w / w.sum()
            port = sub.values @ w
            eq = np.cumprod(1.0 + port)
            dd = eq / np.maximum.accumulate(eq) - 1.0
            out = {
                "error": False, "mode": "historical", "available": True,
                "scenario": req.scenario, "label": win["label"],
                "dates": [str(d.date()) for d in sub.index],
                "portfolio_dd": [round(float(x) * 100, 2) for x in dd],
                "max_dd_pct": round(float(dd.min()) * 100, 2),
                "total_return_pct": round(float(eq[-1] - 1.0) * 100, 2),
                "dropped": dropped,
            }
            if req.benchmark in df.columns:
                b = df[req.benchmark].reindex(sub.index).ffill().dropna()
                if len(b) >= _MIN_OBS:
                    beq = np.cumprod(1.0 + b.values)
                    bdd = beq / np.maximum.accumulate(beq) - 1.0
                    out["benchmark_dd"] = [round(float(x) * 100, 2) for x in bdd]
                    out["benchmark_max_dd_pct"] = round(float(bdd.min()) * 100, 2)
                    out["benchmark_label"] = req.benchmark
            return out

        # ── 가상 시나리오 (M8) ──
        from src.engine.stress_test_analyzer import STRESS_SCENARIOS, _stock_shock
        if req.scenario not in STRESS_SCENARIOS:
            return {"error": True, "message": f"미지원 시나리오: {req.scenario}"}
        rows = []
        port_shock = 0.0
        for code, w in holdings.items():
            item = _shock_inputs(code)
            shock = _stock_shock(item, req.scenario)
            port_shock += w * shock
            rows.append({"stock_code": code, "corp_name": item.corp_name,
                         "weight_pct": round(w * 100, 2), "shock_pct": shock,
                         "contribution_pct": round(w * shock, 2)})
        rows.sort(key=lambda x: x["shock_pct"])
        return {
            "error": False, "mode": "hypothetical", "available": True,
            "scenario": req.scenario,
            "label": STRESS_SCENARIOS[req.scenario]["label"],
            "portfolio_shock_pct": round(port_shock, 2),
            "rows": rows,
            "note": "종목 펀더멘털(부채·PER·배당·ROE·베타) 기반 M8 충격 추정의 가중합.",
        }
    except Exception:
        logger.exception("stress 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/stress-catalog")
def allocation_stress_catalog():
    """시나리오 카탈로그 — 가상 4종(M8) + 역사 윈도우(가용성 1쿼리 판정)."""
    try:
        from src.engine.stress_test_analyzer import STRESS_SCENARIOS
        hypo = [{"id": k, "label": v["label"], "description": v["description"],
                 "mode": "hypothetical", "available": True}
                for k, v in STRESS_SCENARIOS.items()]

        # DB 최소일자 1회 조회 → 그보다 전부 이른 윈도우는 미보유 처리
        min_date = None
        try:
            from sqlalchemy import text

            from src.database import get_engine
            with get_engine().connect() as c:
                row = c.execute(text(
                    "SELECT MIN(trade_date) FROM daily_prices")).fetchone()
                if row and row[0]:
                    min_date = str(row[0])
        except Exception:
            pass
        from src.data.mock_gate import mock_allowed
        hist = []
        for k, v in _HIST_WINDOWS.items():
            available = True
            reason = None
            if min_date is None:
                # mock 모드는 합성 리플레이 가능(개발), 운영은 정직 unavailable
                available = mock_allowed()
                reason = "mock 합성 리플레이" if available else "시세 DB 미적재"
            elif v["end"] < min_date:
                available = False
                reason = f"데이터 미보유 (DB 시작 {min_date})"
            hist.append({"id": k, "label": v["label"],
                         "description": f"{v['start']} ~ {v['end']} 실제 시세 리플레이",
                         "mode": "historical", "available": available,
                         **({"reason": reason} if reason else {})})
        return {"scenarios": hypo + hist}
    except Exception:
        logger.exception("stress-catalog 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
