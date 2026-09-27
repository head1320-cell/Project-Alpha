"""기업 분석 현업 모델 API (BL3 W3b) — 엔진 `src/engine/valuation/practice_models.py` 에 데이터를 대 준다.

POST /api/v1/company/{code}/models/eva           — EVA · EVA 소멸 가치 · 가치 동인 공식
POST /api/v1/company/{code}/models/value-layers  — 가치의 층(Greenwald 3층) + 층별 확률 가중
POST /api/v1/company/{code}/models/multiples     — 성장률 × PEG 격자 · 정당 PBR/PER · 피어 PER
POST /api/v1/company/{code}/models/driver-mc     — 영업 동인 몬테카를로

## 데이터
- 최근 재무: `ValuationEngine.load_statement` — **mock 게이트**가 여기 있다(운영에서 DART 실패 → 합성 폴백이면 계산하지 않는다).
- 재무 이력: `DARTClient.get_financial_history` — 이 클라이언트는 DART 가 실패하면 합성 재무로 폴백한다(`is_mock=True`). ★운영에서는
  그 해를 버리고 몇 해를 버렸는지 적는다★(`/valuation/financial` 은 이 게이트가 없다 — 그 화면의 결함으로 따로 기록).
- 계산 불가는 500 이 아니라 200 + `{available: false, reason}` — 적자·자료 없음은 그 기업에 대한 사실이다.
"""
from __future__ import annotations

import functools
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.company_models")
router = APIRouter(prefix="/api/v1/company", tags=["company-models"])


class _Priced(BaseModel):
    price: float = Field(..., gt=0, description="현재가(원)")


class EvaRequest(_Priced):
    fade_years: int = Field(5, ge=1, le=30)
    g: float | None = Field(None, ge=-0.05, le=0.15, description="가치 동인 공식의 성장률 — 비우면 영구성장률")
    ronic: float | None = Field(None, gt=-1, le=1, description="새 투자 수익률 — 비우면 최근 ROIC")


class LayersRequest(_Priced):
    w_asset: float = Field(0.25, ge=0, le=1)
    w_epv: float = Field(0.25, ge=0, le=1)
    w_full: float = Field(0.5, ge=0, le=1)


class MultiplesRequest(_Priced):
    growth_axis: list[float] = Field(default_factory=lambda: [5.0, 10.0, 15.0, 20.0, 25.0], min_length=1, max_length=8)
    peg_axis: list[float] = Field(default_factory=lambda: [0.5, 0.75, 1.0, 1.25, 1.5], min_length=1, max_length=8)
    peers: bool = True


class DriverMcRequest(_Priced):
    sigma_growth: float = Field(0.03, ge=0, le=0.5)
    sigma_margin: float = Field(0.02, ge=0, le=0.5)
    sigma_reinvest: float = Field(0.01, ge=0, le=0.5)
    years: int = Field(5, ge=3, le=15)
    n: int = Field(2000, ge=100, le=20000)
    seed: int = 20260927


# ── 데이터 ───────────────────────────────────────────────────────────────────

def load_inputs(code: str, price: float, *, history_years: int = 5) -> dict:
    """`{available, reason, fs, history, dropped_mock, corp_name, is_mock, params, defaults}`."""
    from src.data.dart_client import DARTClient, get_corp_code
    from src.data.mock_gate import mock_allowed
    from src.engine.company_analytics import _mcap, resolve_default_params
    from src.engine.valuation.valuation_models import ValuationEngine, ValuationParams

    client = DARTClient()
    loaded = ValuationEngine(client).load_statement(code, price, market_cap=_mcap(code))
    if not loaded["available"]:
        return {"available": False, "reason": loaded["reason"] or "재무제표를 가져오지 못했어요"}
    history: list = []
    dropped = 0
    corp = get_corp_code(code)
    if corp:
        try:
            raw = client.get_financial_history(corp, years=history_years)
        except Exception as e:  # noqa: BLE001 — 이력이 없으면 이력이 필요한 모델만 사유와 함께 멈춘다
            logger.warning("재무 이력 조회 실패 %s: %s", code, e)
            raw = []
        allow = mock_allowed()
        for fs in raw:
            if getattr(fs, "is_mock", False) and not allow:
                dropped += 1
                continue
            history.append(fs)
    d = resolve_default_params(code)
    params = ValuationParams(risk_free_rate=d["rf"], market_premium=d["erp"], beta=d["beta"],
                             terminal_growth_rate=d["g"], projection_years=int(d["years"]))
    return {"available": True, "reason": None, "fs": loaded["fs"], "history": history, "dropped_mock": dropped,
            "corp_name": loaded["corp_name"], "is_mock": bool(loaded["is_mock"]), "params": params, "defaults": d}


def _wrap(code: str, data: dict, out: dict) -> dict:
    extra: dict[str, Any] = {"code": str(code), "corp_name": data["corp_name"], "is_mock": data["is_mock"],
                             "history_years": len(data["history"]), "dropped_mock_years": data["dropped_mock"]}
    if data["dropped_mock"]:
        extra["history_note"] = (f"DART 를 못 읽어 합성으로 채워진 {data['dropped_mock']}개 연도를 버렸어요 — "
                                 "이 환경은 합성 재무를 쓰지 않아요.")
    return {**out, **extra}


def _guard(fn):
    """예외는 500 한 줄로(내부 문구를 밖에 내지 않는다). `wraps` 가 시그니처를 넘겨 FastAPI 가 본문 모델을 읽는다."""
    @functools.wraps(fn)
    def run(code: str, req):
        try:
            return fn(code, req)
        except HTTPException:
            raise
        except Exception:
            logger.exception("%s 실패", fn.__name__)
            raise HTTPException(500, "처리 중 오류가 발생했습니다.")
    return run


# ── 라우트 ───────────────────────────────────────────────────────────────────

@router.post("/{code}/models/eva")
@_guard
def company_model_eva(code: str, req: EvaRequest):
    """EVA · 소멸 가치 · 가치 동인 공식 — RONIC 을 비우면 최근 ROIC(근사)를 쓴다."""
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price)
    if not data["available"]:
        return data
    p = data["params"]
    probe = pm.eva_analysis(data["history"], data["fs"], p, fade_years=req.fade_years)
    roic = ((probe.get("latest") or {}).get("roic")) if probe.get("available") else None
    ronic = req.ronic if req.ronic is not None else roic
    g = req.g if req.g is not None else p.terminal_growth_rate
    out = pm.eva_analysis(data["history"], data["fs"], p, fade_years=req.fade_years, g=g, ronic=ronic)
    for i in out.get("inputs") or []:
        if i["key"] == "ronic" and req.ronic is None:
            i.update(basis=pm.APPROX, source="최근 ROIC 를 새 투자 수익률로 씀")
        if i["key"] == "g" and req.g is None:
            i.update(source="영구성장률 가정 그대로")
    return _wrap(code, data, out)


@router.post("/{code}/models/value-layers")
@_guard
def company_model_value_layers(code: str, req: LayersRequest):
    """가치의 층 — 성장까지 넣은 층은 가치평가 샌드박스의 통합 적정가(같은 엔진)."""
    from src.engine.company_analytics import valuation_sandbox
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price)
    if not data["available"]:
        return data
    full = (valuation_sandbox(code, req.price, {}).get("unified") or {}).get("value")
    full = float(full) if isinstance(full, (int, float)) and full > 0 else None
    out = pm.value_layers(data["history"], data["fs"], data["params"], full_value_per_share=full,
                          weights=(req.w_asset, req.w_epv, req.w_full))
    return _wrap(code, data, out)


@router.post("/{code}/models/multiples")
@_guard
def company_model_multiples(code: str, req: MultiplesRequest):
    """성장률 × PEG 격자 · 정당 PBR/PER — EPS 성장률은 팩터 스토어의 3년 EPS CAGR(관측)."""
    from src.data.fundamentals_store import FundamentalsStore
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price)
    if not data["available"]:
        return data
    try:
        gr = FundamentalsStore.get_default().get_factors(code).get("eps_cagr_3y")
        gr = float(gr) if isinstance(gr, (int, float)) else None
    except Exception:  # noqa: BLE001 — 모르면 미상(0 이 아니다)
        gr = None
    peer = None
    if req.peers:
        try:
            from src.engine.company_analytics import comps_table
            m = (comps_table(code).get("median_row") or {}).get("per")
            peer = float(m) if isinstance(m, (int, float)) and m > 0 else None
        except Exception:  # noqa: BLE001
            peer = None
    out = pm.multiples_matrix(data["fs"], price=req.price, params=data["params"], eps_growth_pct=gr,
                              growth_axis=req.growth_axis, peg_axis=req.peg_axis, peer_per_median=peer)
    return _wrap(code, data, out)


@router.post("/{code}/models/driver-mc")
@_guard
def company_model_driver_mc(code: str, req: DriverMcRequest):
    """영업 동인 몬테카를로 — 분포 중심은 재무 이력(관측), 폭은 요청(가정)."""
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price)
    if not data["available"]:
        return data
    out = pm.driver_monte_carlo(data["history"], data["fs"], data["params"], sigma_growth=req.sigma_growth,
                                sigma_margin=req.sigma_margin, sigma_reinvest=req.sigma_reinvest,
                                years=req.years, n=req.n, seed=req.seed, price=req.price)
    return _wrap(code, data, out)
