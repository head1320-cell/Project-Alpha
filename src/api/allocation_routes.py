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


class ConstraintsInput(BaseModel):
    """전부 선택 — 지정된 것만 적용 (P3 제약 엔진). 퍼센트 단위."""
    max_weight_pct: float | None = Field(None, ge=1, le=100)
    min_weight_pct: float = Field(0.0, ge=0, le=50)
    group_caps_pct: dict[str, float] = Field(default_factory=dict)
    turnover_cap_pct: float | None = Field(None, ge=0, le=200)
    beta_min: float | None = Field(None, ge=-2, le=3)
    beta_max: float | None = Field(None, ge=-2, le=3)
    cash_min_pct: float = Field(0.0, ge=0, le=90)
    cash_max_pct: float = Field(0.0, ge=0, le=90)


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
    constraints: ConstraintsInput | None = None       # P3 — 없으면 기존 무제약 동작 불변
    # ── ResearchRun 기록 (opt-in) — 슬라이더 드래그마다 DB에 쓰지 않도록 명시 요청 시에만 ──
    record_run: bool = False
    run_name: str | None = Field(None, max_length=200)


class BacktestRequest(BaseModel):
    """정책 walk-forward 백테스트 — /analyze 와 동일 정책(모델·뷰·제약)을 OOS로 재현."""
    tickers: list[str] = Field(..., min_length=2, max_length=30)
    model: str = "mvo"                                # mvo|bl|risk_parity|hrp|min_var
    views: list[AllocationView] | None = None
    constraints: ConstraintsInput | None = None
    benchmark: str = "KOSPI"
    rebalance: str = Field("M", pattern="^[MQ]$")     # M=월 · Q=분기
    window_days: int | None = Field(None, ge=63, le=1260)   # None=expanding, 값=rolling
    cost_bps: float = Field(10.0, ge=0, le=100)       # 편도 회전율 비용(bp)
    lookback_days: int = Field(1008, ge=252, le=3650)  # 기본 ~4년(리밸런싱 충분)
    delta: float = Field(2.5, ge=0.5, le=10)
    tau: float = Field(0.05, ge=0.001, le=1.0)


class XrayRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)   # {code: weight_pct}


class SensitivityRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=2, max_length=30)
    views: list[AllocationView] | None = None
    delta: float = Field(2.5, ge=0.5, le=10)
    tau: float = Field(0.05, ge=0.001, le=1.0)
    bump_pct: float = Field(2.0, ge=0.5, le=10)   # μ 충격 크기 (연 %p)
    lookback_days: int = Field(756, ge=90, le=3650)


class StressRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    scenario: str = "rate_hike_200bp"
    benchmark: str = "KOSPI"
    severity: float = Field(1.0, ge=0.25, le=3.0)   # 가상 시나리오 충격 배율(0.25~3×)


# ── 팩터 기반 포트폴리오 ──────────────────────────────────────────────────────
class FactorSpec(BaseModel):
    id: str                                  # 팩터 필드 id (fundamentals/price 스토어)
    weight: float = Field(1.0, ge=0, le=10)  # 상대 가중치
    direction: int = 0                       # 0=자동(higher_better) · 1=상위선호 · -1=하위선호


class FactorPortfolioRequest(BaseModel):
    factors: list[FactorSpec] = Field(..., min_length=1, max_length=12)
    tickers: list[str] | None = None         # 후보 풀(명시) — 없으면 유니버스 표본
    top_k: int = Field(10, ge=2, le=30)
    weighting: str = "equal"                 # equal|factor_tilt|inverse_vol|risk_parity|min_var|hrp
    lookback_days: int = Field(756, ge=90, le=3650)
    sample_size: int = Field(400, ge=50, le=1500)


# ── 카나리·마켓타이밍 ────────────────────────────────────────────────────────
class CanarySpec(BaseModel):
    kind: str = "asset"                      # asset|indicator
    id: str                                  # 자산 티커 또는 매크로 시리즈 id(VIXCLS 등)
    signal: str = "score_13612"              # abs_mom|score_13612|ma_month|ma_day|threshold
    lookback: int = Field(12, ge=1, le=252)
    threshold: float = 0.0
    direction: str = "above"                 # above|below (threshold/indicator 통과 방향)


class TimingRequest(BaseModel):
    market: str = "kr"                       # kr|us
    canaries: list[CanarySpec] = Field(..., min_length=1, max_length=8)
    min_breadth: int = Field(0, ge=0, le=8)  # 0 = 전부 통과 · k = k-of-N
    risk_on_assets: list[str] = Field(default_factory=list)
    risk_off_assets: list[str] = Field(default_factory=list)
    holdings: dict[str, float] | None = None  # 현재 포트폴리오(리스크-온 유지 + 오버레이 대상)
    overlay: dict | None = None              # {"type":"ma_day"|"abs_mom"|"none","n":200,"lookback":12}


# ── 상관-국면 스트레스 ───────────────────────────────────────────────────────
class StressCorrRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=2, max_length=30)
    weights: dict[str, float] | None = None
    lookback_days: int = Field(756, ge=90, le=3650)
    target_rho: float = Field(0.9, ge=0.0, le=0.99)     # 위기 시 수렴 상관
    intensity: float = Field(1.0, ge=0.0, le=1.0)        # 충격 강도(0=무·1=완전)
    confidence_level: float = Field(0.95, ge=0.8, le=0.999)
    portfolio_value: float = Field(1e8, gt=0)


class ResolveNamesRequest(BaseModel):
    codes: list[str] = Field(..., min_length=1, max_length=300)


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

        # 1b) P3 제약 엔진 (opt-in) — 최종 optimized 가중치를 제약 해로 교체.
        #     infeasible이면 무제약 해를 유지하되 정직 사유를 함께 반환(조용한 무시 금지).
        constraints_report = None
        if req.constraints is not None:
            from src.engine.constrained_opt import Constraints, constrained_solve, sector_groups_for
            cobj = Constraints(**req.constraints.model_dump())
            if cobj.any_active():
                sol = constrained_solve(
                    req.model, names, R,
                    mu=np.asarray(opt["mu_used"], dtype=float),
                    S=np.asarray(opt["sigma_annual"], dtype=float),
                    constraints=cobj,
                    w_current=req.weights,
                    groups_of=sector_groups_for(names),
                    bench_returns=(bench.values if bench is not None
                                   and len(bench) == R.shape[0] else None),
                )
                constraints_report = {k: sol.get(k) for k in
                                      ("status", "violations", "binding", "relaxed",
                                       "notes", "reason", "projected")}
                if sol["status"] != "infeasible" and sol.get("weights") is not None:
                    opt["weights"] = np.asarray(sol["weights"], dtype=float)
                    opt["flow"]["optimized"] = opt["weights"]

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

        payload = {
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
            "constraints_report": constraints_report,
        }

        # ── ResearchRun 기록 (opt-in) — 서버가 계산한 결과를 서버가 스탬프.
        #    outputs는 재계산 가능한 대형 산출물(프론티어 클라우드·MC bins) 제외 요약만.
        if req.record_run:
            from src.data.research_runs import KIND_ANALYZE, record_run
            rid = record_run(
                KIND_ANALYZE,
                inputs=req.model_dump(exclude={"record_run", "run_name"}),
                outputs={"weights": payload["weights"], "flow": payload["flow"],
                         "summary": payload["summary"], "labels": payload["labels"],
                         "views_applied": payload["views_applied"]},
                snapshot={"coverage": coverage, "excluded": excluded,
                          "cap_missing": opt["cap_missing"]},
                name=req.run_name,
            )
            payload["run_id"] = rid              # None이면 DB 미가용 — 정직 보고
            payload["run_recorded"] = rid is not None

        return payload
    except HTTPException:
        raise
    except Exception:
        logger.exception("allocation analyze 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /backtest — 정책 walk-forward(OOS) ────────────────────────────────────────
@router.post("/backtest")
def allocation_backtest(req: BacktestRequest):
    """정책(모델+뷰+제약+리밸런싱+비용)을 시점 밖으로 재현 — 각 리밸런싱 가중치는
    과거 데이터로만 산출(look-ahead 없음). OOS 자산곡선 + compute_metrics 지표 반환."""
    try:
        returns, bench, excluded, coverage = _load_clean_returns(
            req.tickers, req.benchmark, req.lookback_days)
        if returns is None or len(returns.columns) < 2:
            return {"error": True, "excluded": excluded,
                    "message": "백테스트 가능한 자산이 2개 미만입니다. 시세가 적재된 자산을 추가하세요."}

        names = list(returns.columns)
        from src.engine.allocation_backtest import walk_forward
        cobj = None
        if req.constraints is not None:
            from src.engine.constrained_opt import Constraints
            cobj = Constraints(**req.constraints.model_dump())
        views = [v.model_dump() for v in (req.views or [])]
        bench_arr = (bench.reindex(returns.index).fillna(0.0).values
                     if bench is not None else None)

        out = walk_forward(
            names, returns.values, list(returns.index),
            model=req.model, views=views or None, constraints=cobj,
            rebalance=req.rebalance, window_days=req.window_days,
            cost_bps=req.cost_bps, bench=bench_arr, delta=req.delta, tau=req.tau)

        out["excluded"] = excluded
        if not out.get("error"):
            out["labels"] = _labels(names)
            out["coverage"] = coverage
            out["benchmark_label"] = req.benchmark if out.get("bench_curve") else None
        return out
    except Exception:
        logger.exception("allocation backtest 실패")
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
        sev = float(req.severity)
        rows = []
        port_shock = 0.0
        for code, w in holdings.items():
            item = _shock_inputs(code)
            shock = round(_stock_shock(item, req.scenario) * sev, 2)
            port_shock += w * shock
            rows.append({"stock_code": code, "corp_name": item.corp_name,
                         "weight_pct": round(w * 100, 2), "shock_pct": shock,
                         "contribution_pct": round(w * shock, 2)})
        rows.sort(key=lambda x: x["shock_pct"])
        return {
            "error": False, "mode": "hypothetical", "available": True,
            "scenario": req.scenario, "severity": sev,
            "label": STRESS_SCENARIOS[req.scenario]["label"],
            "portfolio_shock_pct": round(port_shock, 2),
            "rows": rows,
            "note": f"종목 펀더멘털(부채·PER·배당·ROE·베타) 기반 M8 충격 추정의 가중합 (배율 {sev:g}×).",
        }
    except Exception:
        logger.exception("stress 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/sensitivity")
def allocation_sensitivity(req: SensitivityRequest):
    """Sensitivity Heatmap — 자산별 기대수익 +bump 충격 → 최적 비중 변화 N×N.

    Robustness 재정의(Research OS): 결과 산점이 아니라 "입력(μ) 변동에 대한
    가중치 안정성"을 검증. base μ는 /analyze와 동일(뷰 있으면 BL posterior).
    """
    try:
        returns, _bench, excluded, coverage = _load_clean_returns(
            req.tickers, None, req.lookback_days)
        if returns is None or len(returns.columns) < 2:
            return {"error": True,
                    "message": "분석 가능한 자산이 2개 미만입니다.",
                    "excluded": excluded}
        names = list(returns.columns)
        from src.engine.allocation_studio import sensitivity_matrix
        views = [v.model_dump() for v in (req.views or [])]
        out = sensitivity_matrix(names, returns.values, views=views or None,
                                 delta=req.delta, tau=req.tau,
                                 bump_pct=req.bump_pct)
        out.update({"error": False, "labels": _labels(names),
                    "excluded": excluded, "coverage": coverage})
        return out
    except Exception:
        logger.exception("sensitivity 실패")
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


# ── 국내 시나리오팩 (P3-b) ────────────────────────────────────────────────────
class KrScenarioRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    scenario: str = "semi_selloff"
    severity: float = Field(1.0, ge=0.25, le=3.0)
    sleeves: dict[str, str] | None = None    # code → 슬리브명 (있으면 취약 슬리브 귀속)


@router.get("/kr-scenario-catalog")
def allocation_kr_scenario_catalog():
    """국내 7종 시나리오 목록 — 라벨·설명·충격 출처."""
    try:
        from src.engine.kr_scenario_pack import catalog
        return {"scenarios": catalog()}
    except Exception:
        logger.exception("kr-scenario-catalog 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/kr-scenario")
def allocation_kr_scenario(req: KrScenarioRequest):
    """국내 시나리오 팩터 충격 — 종목·팩터·슬리브별 P&L + VaR/CVaR 프록시 + 실행 가능성."""
    try:
        from src.engine.kr_scenario_pack import run_scenario
        holdings = {str(c): max(float(w), 0.0) for c, w in req.holdings.items()}
        return run_scenario(list(holdings), holdings, req.scenario,
                            severity=req.severity, sleeves=req.sleeves)
    except Exception:
        logger.exception("kr-scenario 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /resolve-names ───────────────────────────────────────────────────────────
@router.post("/resolve-names")
def allocation_resolve_names(req: ResolveNamesRequest):
    """코드 목록 → 종목명 라벨(단일 진실 공급원 stock_master). 초기 포트폴리오 구성 시
    종목코드 대신 종목명을 보여주기 위한 배치 해소 (검색·관심그룹·게이트 시드 공통)."""
    codes = [str(c).strip() for c in req.codes if str(c).strip()]
    return {"labels": _labels(codes)}


# ── /factor-portfolio ────────────────────────────────────────────────────────
def _factor_sample_rows(n: int) -> list[dict]:
    """유니버스 팩터 표본 행 — factor-xray와 동일 소스(snapshot_db + mock 폴백)."""
    from src.data.snapshot_db import sample_factors
    sample = sample_factors(n) or []
    if not sample:
        from src.data.mock_gate import mock_allowed
        if mock_allowed():
            from src.data.fundamentals_store import FundamentalsStore
            from src.data.price_factors_store import PriceFactorsStore
            fs = FundamentalsStore.get_default()
            ps = PriceFactorsStore.get_default()
            for i in range(80):
                code = f"{100 + i * 137 % 900:03d}{i * 41 % 1000:03d}"
                row = {"stock_code": code}
                try:
                    row.update(fs.get_factors(code, None) or {})
                    row.update(ps.get_factors(code, None) or {})
                except Exception:
                    continue
                sample.append(row)
    return sample


def _rows_for_tickers(tickers: list[str]) -> list[dict]:
    from src.data.fundamentals_store import FundamentalsStore
    from src.data.price_factors_store import PriceFactorsStore
    fs = FundamentalsStore.get_default()
    ps = PriceFactorsStore.get_default()
    rows = []
    for c in tickers:
        row: dict = {"stock_code": c}
        try:
            row.update(fs.get_factors(c, None) or {})
            row.update(ps.get_factors(c, None) or {})
        except Exception:
            pass
        rows.append(row)
    return rows


def _factor_weights(codes: list[str], score_map: dict[str, float],
                    weighting: str, lookback: int) -> dict[str, float]:
    """top-K 종목 → 비중(%). equal/factor_tilt는 시세 불필요, 나머지는 수익률 기반."""
    n = len(codes)
    if weighting == "equal" or n == 0:
        w = 1.0 / max(n, 1)
        return {c: round(w * 100, 2) for c in codes}
    if weighting == "factor_tilt":
        s = np.array([score_map.get(c, 0.0) for c in codes], dtype=float)
        s = s - s.min() + 1e-6                 # 양수 시프트(순위 보존)
        s = s / s.sum()
        return {codes[i]: round(float(s[i]) * 100, 2) for i in range(n)}
    # 수익률 기반 (inverse_vol|risk_parity|min_var|hrp) — 시세 없으면 균등 폴백
    returns, _b, _ex, _cov = _load_clean_returns(codes, None, lookback)
    if returns is None or len(returns.columns) < 2:
        w = 1.0 / n
        return {c: round(w * 100, 2) for c in codes}
    names = list(returns.columns)
    R = returns.values
    from src.engine.allocation_studio import _inverse_vol_w, weights_for_model
    wv = _inverse_vol_w(R) if weighting == "inverse_vol" else weights_for_model(weighting, R)
    return {names[i]: round(float(wv[i]) * 100, 2) for i in range(len(names))}


@router.post("/factor-portfolio")
def allocation_factor_portfolio(req: FactorPortfolioRequest):
    """팩터 기반 포트폴리오 — 방향 인지 z-score 가중합으로 후보 유니버스를 점수화하고
    상위 K종목을 선정, 지정 방식(균등/팩터틸트/역변동성/리스크패리티/최소분산/HRP)으로 비중화."""
    try:
        from src.data.stock_master import get_stock_name
        from src.engine.filter_ast import FIELD_BY_ID

        rows = _rows_for_tickers(req.tickers) if req.tickers else _factor_sample_rows(req.sample_size)
        rows = [r for r in rows if r.get("stock_code")]
        if len(rows) < max(req.top_k, 3):
            return {"error": True,
                    "message": "후보 종목이 부족합니다. 유니버스를 적재하거나 종목을 직접 지정하세요.",
                    "candidates": len(rows)}

        total_w = sum(max(f.weight, 0.0) for f in req.factors) or 1.0
        scores: dict[str, float] = {}
        cov_w: dict[str, float] = {}
        factor_meta = []
        for f in req.factors:
            meta = FIELD_BY_ID.get(f.id)
            hb = bool(getattr(meta, "higher_better", True)) if meta else True
            direction = f.direction if f.direction in (1, -1) else (1 if hb else -1)
            pairs = [(r["stock_code"], _xf(r.get(f.id), None)) for r in rows]
            arr = np.array([v for _, v in pairs if v is not None], dtype=float)
            covered = arr.size >= 10 and float(arr.std(ddof=1)) > 1e-12
            factor_meta.append({"id": f.id, "label": getattr(meta, "label", f.id),
                                "direction": direction, "covered": covered, "n": int(arr.size)})
            if not covered:
                continue
            mean, std = float(arr.mean()), float(arr.std(ddof=1))
            wf = max(f.weight, 0.0) / total_w
            for code, v in pairs:
                if v is None:
                    continue
                z = float(np.clip((v - mean) / std * direction, -3.0, 3.0))
                scores[code] = scores.get(code, 0.0) + wf * z
                cov_w[code] = cov_w.get(code, 0.0) + wf

        ranked = sorted(((c, scores[c] / cov_w[c]) for c in scores if cov_w[c] > 0),
                        key=lambda x: x[1], reverse=True)
        if len(ranked) < 2:
            return {"error": True,
                    "message": "선택한 팩터로 점수화 가능한 종목이 부족합니다(팩터 데이터 결측).",
                    "factors": factor_meta, "candidates": len(rows)}

        top = ranked[: req.top_k]
        codes = [c for c, _ in top]
        score_map = {c: round(s, 3) for c, s in top}
        weights = _factor_weights(codes, score_map, req.weighting, req.lookback_days)
        holdings = [{"code": c, "name": get_stock_name(c) or c,
                     "weight": weights.get(c, 0.0), "score": score_map[c],
                     "coverage_pct": round(cov_w.get(c, 0.0) * 100, 0)}
                    for c in codes]
        holdings = [h for h in holdings if h["weight"] > 0]
        holdings.sort(key=lambda h: h["weight"], reverse=True)
        return {"error": False, "holdings": holdings, "factors": factor_meta,
                "weighting": req.weighting, "candidates": len(rows), "ranked": len(ranked),
                "note": "유니버스 표본 방향 인지 z-score 가중합 → 상위 K 선정. 커버리지 <100%는 일부 팩터 결측 재정규화."}
    except Exception:
        logger.exception("factor-portfolio 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /timing ──────────────────────────────────────────────────────────────────
def _canary_eval(c: CanarySpec, mk: str):
    """단일 카나리 평가 → (통과 여부|None, 표시값|None)."""
    if c.kind == "indicator":
        from src.engine.macro_analytics import _latest, _macro_series
        val = _latest(_macro_series(), c.id)
        if val is None:
            return None, None
        ok = (float(val) > c.threshold) if c.direction == "above" else (float(val) < c.threshold)
        return ok, round(float(val), 3)
    from src.engine.tactical_allocations import (
        _above_ma_d,
        _above_ma_m,
        _abs_mom,
        _score_13612,
    )
    if c.signal == "abs_mom":
        v = _abs_mom(c.id, mk, c.lookback)
        return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)
    if c.signal == "score_13612":
        v = _score_13612(c.id, mk)
        return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)
    if c.signal == "ma_month":
        v = _above_ma_m(c.id, mk, max(c.lookback, 2))
        return (v is True), (1.0 if v else 0.0 if v is not None else None)
    if c.signal == "ma_day":
        v = _above_ma_d(c.id, mk, max(c.lookback, 5))
        return (v is True), (1.0 if v else 0.0 if v is not None else None)
    v = _abs_mom(c.id, mk, c.lookback)
    return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)


def _timing_holding(t: str, mk: str) -> tuple[str, str]:
    from src.data.etf_prices import resolve
    from src.data.stock_master import get_stock_name
    code, name = resolve(t, mk)
    if not name or name == code or name == t:
        name = get_stock_name(code) or get_stock_name(t) or name or code
    return code, name


@router.post("/timing")
def allocation_timing(req: TimingRequest):
    """카나리(자산·지표) 브레드스 게이트 → 위험-온/오프 자산군 스위치 + 추세 오버레이.
    시장 타이밍 컴포짓(timing_panel)을 함께 반환. VAA/PAA/DAA 규칙을 사용자 파라미터로 일반화."""
    try:
        from src.engine.tactical_allocations import _above_ma_d, _abs_mom, _signal

        mk = req.market if req.market in ("kr", "us") else "kr"
        details, hits = [], 0
        for c in req.canaries:
            ok, val = _canary_eval(c, mk)
            if ok:
                hits += 1
            _, lbl = _timing_holding(c.id, mk) if c.kind == "asset" else (c.id, c.id)
            details.append({"kind": c.kind, "id": c.id, "signal": c.signal,
                            "label": lbl, "value": val, "pass": bool(ok)})
        total = len(req.canaries)
        need = req.min_breadth if req.min_breadth > 0 else total
        risk_on = hits >= need

        # 리스크-온/오프 자산군 결정
        weights: dict[str, float] = {}      # ticker -> weight%
        if risk_on:
            if req.risk_on_assets:
                w = round(100.0 / len(req.risk_on_assets), 2)
                weights = {t: w for t in req.risk_on_assets}
            elif req.holdings:
                tot = sum(max(v, 0.0) for v in req.holdings.values()) or 1.0
                weights = {t: round(max(v, 0.0) / tot * 100, 2) for t, v in req.holdings.items()}
        else:
            off = req.risk_off_assets or ["IEF", "SHY"]
            w = round(100.0 / len(off), 2)
            weights = {t: w for t in off}

        # 추세 오버레이 (마켓타이밍) — 추세 이탈 자산은 현금(단기채)으로
        overlay = req.overlay or {}
        otype = overlay.get("type", "none")
        cash_pct = 0.0
        holdings_out = []
        for t, w in weights.items():
            code, name = _timing_holding(t, mk)
            in_trend = True
            if otype in ("ma_day", "abs_mom") and w > 0:
                if otype == "ma_day":
                    r = _above_ma_d(t, mk, int(overlay.get("n", 200)))
                    in_trend = bool(r) if r is not None else True
                else:
                    r = _abs_mom(t, mk, int(overlay.get("lookback", 12)))
                    in_trend = (r is not None and r > 0)
            wt = w if in_trend else 0.0
            if not in_trend:
                cash_pct += w
            holdings_out.append({"ticker": t, "code": code, "label": name,
                                 "weight": round(wt, 2), "in_trend": in_trend})
        cash_pct = round(cash_pct, 2)
        if cash_pct > 0:
            cc, cn = _timing_holding("BIL", mk)
            holdings_out.append({"ticker": "BIL", "code": cc, "label": cn,
                                 "weight": cash_pct, "in_trend": True, "is_cash": True})

        signal_label = _signal({h["ticker"]: h["weight"] for h in holdings_out})

        # 시장 타이밍 컴포짓 (재사용) — 실패해도 카나리 결과는 유효
        market_timing = None
        try:
            from src.engine.macro_analytics import timing_panel
            tp = timing_panel(mk)
            market_timing = {"composite": tp.get("composite"),
                             "components": tp.get("components"),
                             "assets": tp.get("assets")}
        except Exception as e:
            logger.debug(f"timing_panel 실패(무시): {e}")

        return {"error": False, "market": mk,
                "canary": {"signal": "risk_on" if risk_on else "risk_off",
                           "hits": hits, "total": total, "need": need, "details": details},
                "holdings": holdings_out, "cash_pct": cash_pct,
                "signal_label": signal_label, "overlay": otype,
                "market_timing": market_timing}
    except Exception:
        logger.exception("timing 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /stress-correlation ──────────────────────────────────────────────────────
@router.post("/stress-correlation")
def allocation_stress_correlation(req: StressCorrRequest):
    """상관-국면 스트레스 — 위기 시 상관이 target_rho로 수렴한다고 가정하고 공분산을 재구성,
    포트폴리오 변동성·VaR·자산별 기여 VaR의 base 대비 변화를 산출 (PortfolioRiskModel 재사용)."""
    try:
        from scipy.stats import norm

        from src.models.portfolio_risk import PortfolioRiskModel

        returns, _b, excluded, coverage = _load_clean_returns(req.tickers, None, req.lookback_days)
        if returns is None or len(returns.columns) < 2:
            return {"error": True, "message": "분석 가능한 자산이 2개 미만입니다.", "excluded": excluded}
        names = list(returns.columns)
        n = len(names)
        if req.weights:
            w = np.array([max(float(req.weights.get(t, 0.0)), 0.0) for t in names], dtype=float)
            if w.sum() <= 0:
                w = np.ones(n)
        else:
            w = np.ones(n)
        w = w / w.sum()

        ann = math.sqrt(252.0)
        prm = PortfolioRiskModel(confidence_level=req.confidence_level)
        base_var, base_vol_d = prm.calculate_portfolio_var(returns, w, req.portfolio_value)
        base_comp = prm.component_var(returns, w, req.portfolio_value)

        sig = returns.std().values
        corr = returns.corr().values
        off = ~np.eye(n, dtype=bool)
        stressed = corr.copy()
        stressed[off] = corr[off] + (req.target_rho - corr[off]) * req.intensity
        np.fill_diagonal(stressed, 1.0)
        cov_s = np.outer(sig, sig) * stressed
        var_d = float(w @ cov_s @ w)
        s_vol_d = float(np.sqrt(max(var_d, 0.0)))
        z = float(norm.ppf(req.confidence_level))
        s_var = z * s_vol_d * req.portfolio_value
        s_marg = (cov_s @ w) / (s_vol_d + 1e-12) * z * req.portfolio_value
        s_comp = w * s_marg

        labels = _labels(names)
        return {
            "error": False, "names": names, "labels": labels,
            "confidence_level": req.confidence_level, "target_rho": req.target_rho,
            "intensity": req.intensity,
            "base": {"port_vol_pct": round(base_vol_d * ann * 100, 2),
                     "var_amount": round(base_var, 0),
                     "component_var": {names[i]: round(float(base_comp[i]), 0) for i in range(n)}},
            "stressed": {"port_vol_pct": round(s_vol_d * ann * 100, 2),
                         "var_amount": round(s_var, 0),
                         "component_var": {names[i]: round(float(s_comp[i]), 0) for i in range(n)}},
            "delta_vol_pct": round((s_vol_d / base_vol_d - 1) * 100, 1) if base_vol_d > 0 else None,
            "delta_var_pct": round((s_var / base_var - 1) * 100, 1) if base_var > 0 else None,
            "corr_shift": {"from_avg_rho": round(float(corr[off].mean()), 3),
                           "to_avg_rho": round(float(stressed[off].mean()), 3)},
            "excluded": excluded, "coverage": coverage,
        }
    except Exception:
        logger.exception("stress-correlation 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
