"""스트레스·시나리오 API — 팩터 X-ray · 충격 · 민감도 · 시나리오 카탈로그 (P8 ③).

왜 새 라우터인가
──────────────────────────────────────────────────────────────────────────────
스펙 §7 의 방향은 "`allocation_routes.py` 를 더 키우지 말고 새 라우터" 이고, 그
패턴은 `timing_routes.py` · `scenario_routes.py` 로 **두 번 검증됐다**. 그때
1,601 → 1,133줄이 됐던 파일이 다시 2,546줄로 자랐고, 검토서가 지목한 것이 정확히
그 파일이다(§2: "진짜 문제는 프레임워크 부재가 아니라 god-route 하나").

★URL 은 한 글자도 바뀌지 않는다★
프리픽스를 `/api/v1/allocation` 으로 그대로 둔다. §7 의 문제 제기는 모듈 크기이지
URL 구조가 아니다. 경로를 바꾸면 프론트엔드 클라이언트·E2E·저장된 팩이 전부
깨진다. `tests/test_route_parity.py` 의 `ALLOCATION_PATHS` 가 이동 **전에**
통과하도록 먼저 작성됐고(P8 ①), 이동 후에도 같은 {메서드, 경로} 집합을 각각
**정확히 한 번** 요구한다.

★본문은 한 줄도 바꾸지 않았다★ — `timing_routes` 분리 때와 같은 규율이다.

★재수출하지 않는다★
②(벨리프 파이프라인)는 호출부가 라우트에 남아 재수출이 필요했다. 여기서는
**라우트 자체가 옮겨 오므로** 소비자가 이 모듈을 직접 import 한다 — 의존이
숨지 않고 보인다. `scenario_routes` 와 테스트들의 import 경로를 같이 고쳤다.
monkeypatch 대상도 마찬가지다: `allocation_routes` 를 겨누면 조용히 빗나간다.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.allocation_routes import (
    _MIN_OBS,
    AllocationView,
    _labels,
    _load_clean_returns,
    _mock_returns_fallback,
    # ★`_xf` 는 남는 쪽에도 소비자가 있다★ `/factor-portfolio` 의
    # `_factor_weights` 가 같은 변환을 쓴다. 두 벌을 만들면 정확히 이
    # 리팩터가 없애려던 것(같은 산수 두 곳)이 다시 생긴다.
    _xf,
)
from src.engine.portfolio_weights import signed_fractions
from src.engine.scenario_packs import HIST_WINDOWS

logger = logging.getLogger("api.allocation")

# ★프리픽스는 allocation 그대로★ — 모듈만 나뉘고 URL 은 불변이다.
router = APIRouter(prefix="/api/v1/allocation", tags=["allocation-stress"])


# ★정의는 `scenario_packs` 로 옮겼다★ 시나리오 세 출처 중 둘은 엔진에 있는데 이것만 라우터
# 상수로 남으면 레지스트리가 라우터를 import 해야 한다. 윈도우 **가용성**은 DB 적재 범위에
# 달린 런타임 사실이라 계속 이 파일이 판정한다(아래 stress-catalog).
_HIST_WINDOWS = HIST_WINDOWS


# ── 요청 모델 ─────────────────────────────────────────────────────────────────
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


# ── 상관-국면 스트레스 ───────────────────────────────────────────────────────
class StressCorrRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=2, max_length=30)
    weights: dict[str, float] | None = None
    lookback_days: int = Field(756, ge=90, le=3650)
    target_rho: float = Field(0.9, ge=0.0, le=0.99)     # 위기 시 수렴 상관
    intensity: float = Field(1.0, ge=0.0, le=1.0)        # 충격 강도(0=무·1=완전)
    confidence_level: float = Field(0.95, ge=0.8, le=0.999)
    portfolio_value: float = Field(1e8, gt=0)


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

        # ★부호를 잃지 않는다★ 예전에는 `max(w,0)/Σmax(w,0)` 이라 숏 다리가
        # 사라졌고, 전액 숏 북에는 "보유 비중 합이 0입니다" 라는 거짓 사유가 나갔다.
        holdings = signed_fractions(req.holdings)
        if not holdings:
            return {"error": True, "message": "보유 비중이 없습니다 (gross = 0)."}

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
                # ★커버리지는 gross★ 부호대로 더하면 중립 북에서 0 에 붙어
                # `pf_z` 가 조용히 None(= "잴 수 없다")이 된다 — 잴 수 있는데도.
                cov_w += abs(w)
            pf_z = acc / cov_w if cov_w > 1e-9 else None

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


def historical_replay(holdings: dict[str, float], scenario: str, benchmark: str) -> tuple[dict, str]:
    """역사 윈도우 리플레이 — `/stress` 와 그래프 노드가 **같은 함수**를 부른다 (BK W1).

    `holdings` 는 `signed_fractions` 를 지난 분수. 반환 `(응답, 출처)` — 출처는 `"db"` ·
    `"mock"`(mock 게이트를 지난 합성 폴백) · `"none"`(시세 없음). 응답 모양은 `/stress` 그대로다
    (출처는 라우트 응답에 싣지 않는다 — 노드가 계보로 나른다).
    """
    win = _HIST_WINDOWS[scenario]
    from src.kis_portfolio_analyzer import load_returns
    df = load_returns(list(holdings) + [benchmark], win["start"], win["end"])
    source = "db"
    if df is None or df.empty:
        source = "none"
        mock_df = _mock_returns_fallback(list(holdings) + [benchmark],
                                         win["start"], win["end"])
        if mock_df is not None:
            df = mock_df
            source = "mock"
    avail = [c for c in holdings if df is not None and not df.empty and c in df.columns
             and int(df[c].dropna().shape[0]) >= _MIN_OBS]
    if not avail:
        return ({"error": False, "mode": "historical", "available": False,
                 "scenario": scenario, "label": win["label"],
                 "reason": "해당 기간 시세 데이터 미보유 (KRX 백필 범위 밖)"}, "none")
    dropped = [c for c in holdings if c not in avail]
    sub = df[avail].dropna()
    w = np.array([holdings[c] for c in avail])
    # ★gross 로 나눈다★ `w.sum()` 은 넷이라 달러중립에서 폭발한다.
    w = w / np.abs(w).sum()
    port = sub.values @ w
    eq = np.cumprod(1.0 + port)
    dd = eq / np.maximum.accumulate(eq) - 1.0
    out = {
        "error": False, "mode": "historical", "available": True,
        "scenario": scenario, "label": win["label"],
        "dates": [str(d.date()) for d in sub.index],
        "portfolio_dd": [round(float(x) * 100, 2) for x in dd],
        "max_dd_pct": round(float(dd.min()) * 100, 2),
        "total_return_pct": round(float(eq[-1] - 1.0) * 100, 2),
        "dropped": dropped,
    }
    if benchmark in df.columns:
        b = df[benchmark].reindex(sub.index).ffill().dropna()
        if len(b) >= _MIN_OBS:
            beq = np.cumprod(1.0 + b.values)
            bdd = beq / np.maximum.accumulate(beq) - 1.0
            out["benchmark_dd"] = [round(float(x) * 100, 2) for x in bdd]
            out["benchmark_max_dd_pct"] = round(float(bdd.min()) * 100, 2)
            out["benchmark_label"] = benchmark
    return out, source


def hypothetical_shock(holdings: dict[str, float], scenario: str, severity: float) -> dict:
    """가상 시나리오(M8) 충격 가중합 — `/stress` 와 그래프 노드가 같은 함수를 부른다 (BK W1)."""
    from src.engine.stress_test_analyzer import STRESS_SCENARIOS, _stock_shock
    if scenario not in STRESS_SCENARIOS:
        return {"error": True, "message": f"미지원 시나리오: {scenario}"}
    sev = float(severity)
    rows = []
    port_shock = 0.0
    for code, w in holdings.items():
        item = _shock_inputs(code)
        shock = round(_stock_shock(item, scenario) * sev, 2)
        port_shock += w * shock
        rows.append({"stock_code": code, "corp_name": item.corp_name,
                     "weight_pct": round(w * 100, 2), "shock_pct": shock,
                     "contribution_pct": round(w * shock, 2)})
    rows.sort(key=lambda x: x["shock_pct"])
    return {
        "error": False, "mode": "hypothetical", "available": True,
        "scenario": scenario, "severity": sev,
        "label": STRESS_SCENARIOS[scenario]["label"],
        "portfolio_shock_pct": round(port_shock, 2),
        "rows": rows,
        "note": f"종목 펀더멘털(부채·PER·배당·ROE·베타) 기반 M8 충격 추정의 가중합 (배율 {sev:g}×).",
    }


@router.post("/stress")
def allocation_stress(req: StressRequest):
    """가상 시나리오(M8 펀더멘털 충격 가중합) 또는 역사 윈도우 리플레이."""
    try:
        holdings = signed_fractions(req.holdings)   # ★부호 보존 · gross 정규화★
        if not holdings:
            return {"error": True, "message": "보유 비중이 없습니다 (gross = 0)."}
        if req.scenario in _HIST_WINDOWS:
            return historical_replay(holdings, req.scenario, req.benchmark)[0]
        return hypothetical_shock(holdings, req.scenario, req.severity)
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


_STRESS_NOTE = (
    "가상·국내팩은 팩터 민감도로 추정한 충격이라 severity 배율이 적용됩니다. "
    "역사 리플레이는 실제 시세를 그대로 재생하므로 배율이 적용되지 않으며, "
    "적재된 시세 범위를 벗어난 구간은 합성하지 않고 미가용으로 표시합니다. "
    "★분류(패밀리)와 모형 종류(model_type)는 다른 축입니다★ — 국내 시나리오팩도 "
    "역사가 아니라 **가정 충격**입니다."
)

#: 실행 엔진 → 레거시 `mode` 값. ★한 글자도 바뀌지 않는다★ 프론트엔드가 결과 렌더링을
#: 이 값으로 분기하므로, 패밀리를 12종으로 늘리는 것과 `mode` 는 별개 축이다.
_ENGINE_MODE = {"m8": "hypothetical", "hist_replay": "historical", "kr_pack": "kr_pack"}


@router.get("/stress-scenarios")
def allocation_stress_scenarios():
    """통합 시나리오 카탈로그 — 스펙 §5 의 12 패밀리 + **두 축**(패밀리 · model_type).

    Phase 9 이전에는 패밀리가 셋(가상·역사·국내팩)이었고 `mode: "kr_pack"` 이 인식론적
    주장인 것처럼 실려 나갔다. 이제 분류는 §5 의 12 패밀리가, "이것이 역사인가 가정인가" 는
    `model_type` 이 맡는다. 팩이 없는 패밀리도 **사유와 함께** 목록에 남는다.

    기존 /stress-catalog(가상+역사)와 /kr-scenario-catalog(국내)는 그대로 유지.
    """
    try:
        from src.engine.scenario_packs import PACKS, families

        # 가용성은 런타임 사실(적재 범위)이라 레거시 카탈로그가 계속 판정한다.
        legacy = {s["id"]: s for s in allocation_stress_catalog()["scenarios"]}

        by_family: dict[str, list[dict]] = {}
        for pack in PACKS.values():
            leg = legacy.get(pack.pack_id, {})
            item = pack.to_dict()
            item["mode"] = _ENGINE_MODE[pack.engine]
            item["available"] = bool(leg.get("available", True))
            if leg.get("reason"):
                item["reason"] = leg["reason"]
            by_family.setdefault(pack.family, []).append(item)

        fams = families()
        groups = [{"family": f["id"], "label": f["label"],
                   "items": sorted(by_family.get(f["id"], []), key=lambda i: i["label"]),
                   **({"reason": f["reason"]} if f.get("reason") else {})}
                  for f in fams]

        return {"groups": groups, "families": fams, "note": _STRESS_NOTE}
    except HTTPException:
        raise
    except Exception:
        logger.exception("stress-scenarios 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


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
        holdings = signed_fractions(req.holdings)   # ★부호 보존 · gross 정규화★
        return run_scenario(list(holdings), holdings, req.scenario,
                            severity=req.severity, sleeves=req.sleeves)
    except Exception:
        logger.exception("kr-scenario 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/stress-correlation")
def allocation_stress_correlation(req: StressCorrRequest):
    """상관-국면 스트레스 — 위기 시 상관이 target_rho로 수렴한다고 가정하고 공분산을 재구성,
    포트폴리오 변동성·VaR·자산별 기여 VaR의 base 대비 변화를 산출 (PortfolioRiskModel 재사용)."""
    try:
        returns, _b, excluded, coverage = _load_clean_returns(req.tickers, None, req.lookback_days)
        if returns is None or len(returns.columns) < 2:
            return {"error": True, "message": "분석 가능한 자산이 2개 미만입니다.", "excluded": excluded}
        names = list(returns.columns)
        n = len(names)
        if req.weights:
            # ★조용한 대체 금지★ 예전에는 전액 숏 북에서 `w.sum() <= 0` 이 걸려
            # **균등가중으로 바꿔치기**했다 — 사용자가 준 것과 다른 포트폴리오를
            # 분석해 놓고 그렇게 말하지 않는 자리였다.
            w = np.array([float(req.weights.get(t, 0.0)) for t in names], dtype=float)
            if np.abs(w).sum() <= 0:
                w = np.ones(n)
        else:
            w = np.ones(n)
        out = stress_correlation_report(returns, w, target_rho=req.target_rho, intensity=req.intensity,
                                        confidence_level=req.confidence_level,
                                        portfolio_value=req.portfolio_value)
        out.update({"excluded": excluded, "coverage": coverage})
        return out
    except Exception:
        logger.exception("stress-correlation 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


def stress_correlation_report(returns, w, *, target_rho: float, intensity: float,
                              confidence_level: float, portfolio_value: float) -> dict:
    """상관-국면 스트레스 본체 — `/stress-correlation` 과 그래프 노드가 같은 함수를 부른다 (BK W1).

    `returns` 는 일별 수익률 프레임(열 = 자산), `w` 는 같은 순서의 비중 배열(gross 로 정규화한다).
    위기 시 상관이 `target_rho` 로 수렴한다고 **가정**하고 공분산을 재구성해 변동성·VaR·자산별
    기여 VaR 의 base 대비 변화를 낸다(PortfolioRiskModel 재사용).
    """
    from scipy.stats import norm

    from src.models.portfolio_risk import PortfolioRiskModel

    names = list(returns.columns)
    n = len(names)
    w = np.asarray(w, dtype=float)
    w = w / np.abs(w).sum()          # ★gross★ net 은 달러중립에서 0 이다

    ann = math.sqrt(252.0)
    prm = PortfolioRiskModel(confidence_level=confidence_level)
    base_var, base_vol_d = prm.calculate_portfolio_var(returns, w, portfolio_value)
    base_comp = prm.component_var(returns, w, portfolio_value)

    sig = returns.std().values
    corr = returns.corr().values
    off = ~np.eye(n, dtype=bool)
    stressed = corr.copy()
    stressed[off] = corr[off] + (target_rho - corr[off]) * intensity
    np.fill_diagonal(stressed, 1.0)
    cov_s = np.outer(sig, sig) * stressed
    var_d = float(w @ cov_s @ w)
    s_vol_d = float(np.sqrt(max(var_d, 0.0)))
    z = float(norm.ppf(confidence_level))
    s_var = z * s_vol_d * portfolio_value
    s_marg = (cov_s @ w) / (s_vol_d + 1e-12) * z * portfolio_value
    s_comp = w * s_marg

    labels = _labels(names)
    return {
        "error": False, "names": names, "labels": labels,
        "confidence_level": confidence_level, "target_rho": target_rho,
        "intensity": intensity,
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
    }
