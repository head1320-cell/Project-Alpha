"""기업 분석 현업 모델 API (BL3 W3b) — 엔진 `src/engine/valuation/practice_models.py` 에 데이터를 대 준다.

POST /api/v1/company/{code}/models/eva           — EVA · EVA 소멸 가치 · 가치 동인 공식
POST /api/v1/company/{code}/models/value-layers  — 가치의 층(Greenwald 3층) + 층별 확률 가중
POST /api/v1/company/{code}/models/multiples     — 성장률 × PEG 격자 · 정당 PBR/PER · 피어 PER
POST /api/v1/company/{code}/models/driver-mc     — 영업 동인 몬테카를로
POST /api/v1/company/{code}/models/scenarios     — 이산 확률 시나리오(각 행 = 샌드박스와 같은 엔진)
POST /api/v1/company/{code}/models/decision-tree — 의사결정 나무(가지·확률·값은 입력)
POST /api/v1/company/{code}/models/sotp          — 합산가치·지주사 NAV(자회사 시총은 조회, 지분율·배수는 입력)
POST /api/v1/company/{code}/models/real-option   — 실물옵션(블랙-숄즈 + CRR 이항)

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


class ScenarioRow(BaseModel):
    name: str = Field("시나리오", max_length=20)
    prob: float = Field(..., ge=0, le=1)
    rf: float | None = Field(None, ge=0, le=0.15)
    beta: float | None = Field(None, ge=0.1, le=3.0)
    erp: float | None = Field(None, ge=0, le=0.15)
    g: float | None = Field(None, ge=0, le=0.05)


class ScenariosRequest(_Priced):
    scenarios: list[ScenarioRow] = Field(..., max_length=8)


class TreeBranch(BaseModel):
    id: str = Field(..., max_length=20)
    parent: str = Field("", max_length=20)
    label: str = Field("", max_length=40)
    prob: float = Field(..., ge=0, le=1)
    value: float | None = Field(None, description="끝 가지의 주당 가치(원)")


class DecisionTreeRequest(_Priced):
    branches: list[TreeBranch] = Field(..., max_length=40)


class SotpSegment(BaseModel):
    name: str = Field("부문", max_length=30)
    metric: float = Field(..., description="EBITDA·순이익 등(억원)")
    multiple: float = Field(..., ge=0, le=100)


class SotpSubsidiary(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    stake_pct: float = Field(..., ge=0, le=100)


class SotpRequest(_Priced):
    segments: list[SotpSegment] = Field(default_factory=list, max_length=12)
    subsidiaries: list[SotpSubsidiary] = Field(default_factory=list, max_length=12)
    holding_discount_pct: float = Field(0.0, ge=0, lt=100)
    net_debt_eok: float | None = Field(None, description="순차입금(억원) — 비우면 총부채(근사, DCF 와 같은 다리)")


class RealOptionRequest(_Priced):
    S: float = Field(..., gt=0, description="사업 가치(억원)")
    K: float = Field(..., gt=0, description="투자비·처분가(억원)")
    T: float = Field(..., gt=0, le=30)
    sigma: float = Field(..., gt=0, le=2)
    q: float = Field(0.0, ge=0, le=0.5)
    kind: str = Field("call", pattern="^(call|put)$")
    n_steps: int = Field(500, ge=50, le=2000)


# ── 데이터 ───────────────────────────────────────────────────────────────────

def load_inputs(code: str, price: float, *, history_years: int = 5, history: bool = True) -> dict:
    """`{available, reason, fs, history, dropped_mock, corp_name, is_mock, params, defaults}`."""
    from src.data.dart_client import DARTClient, get_corp_code
    from src.data.mock_gate import mock_allowed
    from src.engine.company_analytics import _mcap, resolve_default_params
    from src.engine.valuation.valuation_models import ValuationEngine, ValuationParams

    client = DARTClient()
    loaded = ValuationEngine(client).load_statement(code, price, market_cap=_mcap(code))
    if not loaded["available"]:
        return {"available": False, "reason": loaded["reason"] or "재무제표를 가져오지 못했어요"}
    hist: list = []
    dropped = 0
    corp = get_corp_code(code) if history else None
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
            hist.append(fs)
    d = resolve_default_params(code)
    params = ValuationParams(risk_free_rate=d["rf"], market_premium=d["erp"], beta=d["beta"],
                             terminal_growth_rate=d["g"], projection_years=int(d["years"]))
    return {"available": True, "reason": None, "fs": loaded["fs"], "history": hist, "dropped_mock": dropped,
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


@router.post("/{code}/models/scenarios")
@_guard
def company_model_scenarios(code: str, req: ScenariosRequest):
    """시나리오마다 가정을 바꿔 가치평가 샌드박스와 **같은 엔진**(`ValuationEngine.evaluate`)으로 주당 가치를 내고 확률로 묶는다."""
    from src.engine.company_analytics import _engine, _make_params, _mcap
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price, history=False)
    if not data["available"]:
        return data
    d, eng, mcap = data["defaults"], _engine(), _mcap(code)
    rows = []
    for sc in req.scenarios:
        pick = {k: (getattr(sc, k) if getattr(sc, k) is not None else d[k]) for k in ("rf", "beta", "erp", "g")}
        r = eng.evaluate(code, req.price, params=_make_params(pick["rf"], pick["beta"], pick["erp"], pick["g"],
                                                             d["years"]), market_cap=mcap)
        v = round(r.intrinsic_value, 0) if r.intrinsic_value > 0 else None
        rows.append({"name": sc.name, "prob": sc.prob, "value": v, "assumptions": pick,
                     "changed": [k for k in ("rf", "beta", "erp", "g") if getattr(sc, k) is not None]})
    out = pm.scenario_weighted(rows, price=req.price)
    return _wrap(code, data, out)


@router.post("/{code}/models/decision-tree")
@_guard
def company_model_decision_tree(code: str, req: DecisionTreeRequest):
    """의사결정 나무 — 재무를 읽지 않는다(가지·확률·값 모두 입력). 종목 이름만 붙인다."""
    from src.data.mock_gate import mock_allowed
    from src.data.stock_master import get_stock_name
    from src.engine.valuation import practice_models as pm
    out = pm.decision_tree([b.model_dump() for b in req.branches], price=req.price)
    return {**out, "code": str(code), "corp_name": get_stock_name(code), "is_mock": False,
            "practice": mock_allowed(), "history_years": 0, "dropped_mock_years": 0}


@router.post("/{code}/models/sotp")
@_guard
def company_model_sotp(code: str, req: SotpRequest):
    """합산가치 — 상장 자회사 시총은 조회(`_mcap`), 지분율·배수·할인은 입력. 순차입금을 비우면 총부채(근사)."""
    from src.data.stock_master import get_stock_name
    from src.engine.company_analytics import _mcap
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price, history=False)
    if not data["available"]:
        return data
    fs = data["fs"]
    subs = []
    for s in req.subsidiaries:
        name = get_stock_name(s.code)
        mc = _mcap(s.code) if name else None
        subs.append({"code": s.code, "name": name, "stake_pct": s.stake_pct, "market_cap": mc,
                     "reason": None if name else "모르는 종목코드예요"})
    tl = fs.total_liabilities
    net_debt = req.net_debt_eok if req.net_debt_eok is not None else ((tl or 0.0) / 1e8)
    out = pm.sotp([x.model_dump() for x in req.segments], subs, net_debt=net_debt,
                  holding_discount_pct=req.holding_discount_pct, shares=fs.shares_outstanding)
    for i in out.get("inputs") or []:
        if i["key"] == "net_debt":
            i.update(basis=pm.ASSUMED if req.net_debt_eok is not None else pm.APPROX,
                     source="입력" if req.net_debt_eok is not None else "총부채(DCF 와 같은 다리)")
    return _wrap(code, data, out)


@router.post("/{code}/models/real-option")
@_guard
def company_model_real_option(code: str, req: RealOptionRequest):
    """실물옵션 — 무위험수익률은 가치평가 기본 가정(출처 라벨 그대로), 나머지는 입력. 주당 옵션 가치도 낸다."""
    from src.engine.valuation import practice_models as pm
    data = load_inputs(code, req.price, history=False)
    if not data["available"]:
        return data
    d = data["defaults"]
    out = pm.real_option(S=req.S, K=req.K, T=req.T, sigma=req.sigma, r=d["rf"], q=req.q, kind=req.kind,
                         n_steps=req.n_steps)
    for i in out.get("inputs") or []:
        if i["key"] == "r":
            i.update(source=d["rf_source"])
    shares = data["fs"].shares_outstanding
    if out.get("available") and shares:
        per = out["black_scholes"]["value"] * 1e8 / shares
        out["per_share"] = {"black_scholes": per, "binomial": out["binomial"]["value"] * 1e8 / shares,
                            "vs_price_pct": per / req.price * 100}
    return _wrap(code, data, out)
