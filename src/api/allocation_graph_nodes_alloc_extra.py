"""AAS 그래프 — 배분 추가 노드 (BL3 W5) · ★라우트 함수를 같은 요청으로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W5. 테스트 `tests/test_allocation_graph_bl3w5.py`.

- 리밸런싱 판단 — `rebalance_decision_route`(record_decision=False 명시). 기록은 저장 버튼만: 기록 없이 다시 계산해
  미리보기와 같을 때만 `record_decision=True`(BL2a 연구 기록과 같은 규율).
- 노출 → 상품 — `implement_exposures_route`. 구현 못 한 노출은 재분배하지 않는다(라우트 규칙 그대로). 출력 Weights 에는 공분산이
  없다 — 하류 위험 분해는 기존 규칙대로 사유와 함께 실패한다(지어내지 않는다).
- 페어 · 시장 충격 · 현금 수익 · 전략 용량 · 멀티전략 반사실 — 각 라우트 함수. 멀티전략 문(503·422)의 사유는 노드 실패의 사유다.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _labels, _ui, weights_value
from src.engine import portfolio_graph as pg

P = pg.Port
_EXPOSURE_LABELS = {"equity": "국내 주식", "equity_us": "미국 주식", "equity_small": "중소형주", "duration": "장기 금리(듀레이션)",
                    "credit": "크레딧", "commodity": "원자재", "real_estate": "리츠", "em": "신흥국"}


def _finite(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else None
    return x


def _detail(e: HTTPException) -> str:
    d = e.detail
    if isinstance(d, dict):
        return str(d.get("reason") or d.get("message") or d)
    return str(d)


def _call(fn, req, what: str) -> dict:
    """라우트 함수 호출 — HTTPException 의 사유를 노드 실패의 사유로(500 의 뭉뚱그린 문장은 그대로 보인다)."""
    try:
        return fn(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"{what} — {_detail(e)}") from e


def _assumed(key: str, label: str, value: Any, unit: str | None = None, source: str = "직접 넣은 값") -> dict:
    return {"key": key, "label": label, "value": value, "basis": "가정", "source": source, **({"unit": unit} if unit else {})}


# ── 리밸런싱 판단 ────────────────────────────────────────────────────────────

class HoldingRow(BaseModel):
    model_config = _FORBID
    code: str = Field("005930", pattern=r"^[0-9A-Z.]{1,12}$", json_schema_extra={"x-ui": _ui("종목코드")})
    pct: float = Field(0.0, ge=0, le=100, json_schema_extra={"x-ui": _ui("지금 비중(%)")})


class RebalanceParams(BaseModel):
    model_config = _FORBID
    holdings: list[HoldingRow] = Field(
        [], max_length=30, json_schema_extra={"x-ui": _ui(
            "지금 들고 있는 비중", question="지금 무엇을 얼마나 들고 있나요?",
            help="비우면 유니버스 노드의 '지금 비중' 을 써요. 둘 다 없으면 판단할 수 없어요.")})
    portfolio_value: float = Field(1e8, gt=0, le=1e13, json_schema_extra={"x-ui": _ui(
        "평가 금액", unit="원", presets=[{"label": "1천만", "value": 1e7}, {"label": "1억", "value": 1e8}],
        help="거래비용을 금액으로 재려는 값이에요 — 계좌를 읽지 않아요.")})
    horizon_days: int = Field(63, ge=1, le=756, json_schema_extra={"x-ui": _ui(
        "보유 기간", "advanced", unit="영업일", help="연 효용 개선을 이 기간으로 환산해 일회성 비용과 견줘요.")})
    hysteresis_mult: float = Field(0.5, ge=0, le=50, json_schema_extra={"x-ui": _ui(
        "머뭇거림 폭", "advanced", help="비용 × (1 + 이 값)을 넘어야 거래해요 — 잦은 거래를 막는 문턱이에요.")})


def _rebalance_request(inputs: dict, p: RebalanceParams, *, record: bool):
    from src.api.allocation_routes import RebalanceDecisionRequest
    w = inputs["weights"]
    req = w.get("req")
    if req is None:
        raise pg.NodeFailure("이 비중에는 만든 규칙(유니버스·기간·모델)이 없어요 — 비중 계산 노드의 비중을 이어 주세요.")
    holdings = {h.code: h.pct for h in p.holdings if h.pct > 0} or dict(req.weights or {})
    if not holdings:
        raise pg.NodeFailure("지금 들고 있는 비중이 없어요 — 설정에 적거나 유니버스 노드의 '지금 비중' 을 채워 주세요.")
    target = {n: float(x) * 100 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}
    base = req.model_dump()
    return RebalanceDecisionRequest(**{**base, "holdings": holdings, "weight_unit": "percent",
                                       "portfolio_value": p.portfolio_value, "target_weights": target,
                                       "horizon_days": p.horizon_days, "hysteresis_mult": p.hysteresis_mult,
                                       "record_decision": record})


def _rebalance(inputs: dict, p: RebalanceParams) -> pg.NodeOutput:
    from src.api import allocation_routes as ar
    req = _rebalance_request(inputs, p, record=False)       # ★계산은 기록하지 않는다★ — 기본값에 기대지 않고 명시
    res = _call(ar.rebalance_decision_route, req, "리밸런싱 판단을 하지 못했어요")
    res = {k: v for k, v in res.items() if k != "research_context"}
    res["hysteresis_mult"] = p.hysteresis_mult               # 저울의 문턱(비용 × (1 + 이 값))을 화면이 그린다
    res["inputs"] = [
        {"key": "holdings", "label": "지금 비중", "value": f"{len(req.holdings)}종목", "basis": "가정",
         "source": "직접 적은 값" if p.holdings else "유니버스 노드의 '지금 비중'"},
        _assumed("value", "평가 금액", p.portfolio_value, "원", "직접 정한 금액 — 계좌 잔고가 아니에요"),
        _assumed("horizon", "보유 기간", p.horizon_days, "영업일"),
        _assumed("hyst", "머뭇거림 폭", f"{p.hysteresis_mult:g}", source="비용 × (1 + 이 값) 을 넘어야 거래"),
    ]
    view = {"result": _finite(res), "labels": _labels(sorted(set(req.holdings) | set(req.target_weights or {})))}
    return pg.NodeOutput(values={"weights": inputs["weights"]}, view=view,
                         provenance={"source": (res.get("coverage") or {}).get("source")})


def _save_decision(values: dict, view: dict, params: Any) -> dict:
    """결정 기록 남기기 — 기록 없이 다시 계산해 미리보기와 같을 때만 기록한다(BL2a 와 같은 규율)."""
    from src.api import allocation_routes as ar
    p = params if isinstance(params, RebalanceParams) else RebalanceParams(**(params or {}))
    probe = ar.rebalance_decision_route(_rebalance_request(values, p, record=False))
    want = (view or {}).get("result") or {}
    if probe.get("decision") != want.get("decision") or probe.get("target_weights") != want.get("target_weights"):
        raise pg.NodeFailure("다시 계산하니 이 미리보기와 다른 판단이 나와 기록하지 않았어요 — 다시 계산한 뒤 기록해 주세요.")
    out = ar.rebalance_decision_route(_rebalance_request(values, p, record=True))
    if not out.get("dec_id"):
        raise pg.NodeFailure(f"결정을 기록하지 못했어요 — {out.get('persist_reason') or '사유 미상'}")
    return {"saved_id": out["dec_id"], "text": f"결정 기록으로 남겼어요 · {out['dec_id']}"}


_DECISION_KO = {"trade": "거래할 가치가 있어요", "hold": "지금은 그대로 두는 게 나아요",
                "undetermined": "판단할 수 없어요"}


def _explain_rebalance(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    d = r.get("decision")
    b, c = r.get("benefit") or {}, r.get("cost") or {}
    title = _DECISION_KO.get(d, "리밸런싱을 판단했어요")
    if d == "undetermined":
        title += f" — {b.get('reason') or r.get('reason') or '편익을 모름'}"
    facts = []
    if r.get("reason"):
        facts.append(str(r["reason"]))
    if isinstance(c.get("turnover_pct"), (int, float)):
        facts.append(f"회전율 {c['turnover_pct']:.1f}% · 주문 {c.get('n_orders')}건 · 비용 {c.get('cost_bp')}bp")
    trust = []
    if (b.get("provenance") or {}).get("self_referential"):
        trust.append(_t(ASSUMED, "편익을 잰 기대수익이 이 목표를 고른 바로 그 추정이에요 — 이득은 구조적으로 보장되고, "
                                 "전망이 맞았다는 증거가 아니에요."))
    if b.get("note"):
        trust.append(_t(ASSUMED, str(b["note"])))
    if c.get("reason"):
        trust.append(_t(UNKNOWN, f"비용: {c['reason']}"))
    if (r.get("coverage") or {}).get("source") == "mock":
        trust.append(_t(UNKNOWN, "연습용 합성 수익률로 잰 판단이에요."))
    trust.append(_t(CONFIRMED, "무거래 밴드는 자산마다 달라요(비용·포지션 크기·불확실성에 따라) — 고정 ±5% 가 아니에요."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["세금·체결 지연", "판단 뒤 실제 체결가"]}


# ── 노출 → 상품 ──────────────────────────────────────────────────────────────

class ExposureRow(BaseModel):
    model_config = _FORBID
    exposure: Literal[tuple(_EXPOSURE_LABELS)] = Field("equity", json_schema_extra={"x-ui": _ui(  # type: ignore[valid-type]
        "노출", options=_EXPOSURE_LABELS)})
    pct: float = Field(0.0, ge=0, le=100, json_schema_extra={"x-ui": _ui("비중(%)")})


class ImplementParams(BaseModel):
    model_config = _FORBID
    exposures: list[ExposureRow] = Field(
        [{"exposure": "equity", "pct": 60.0}, {"exposure": "duration", "pct": 40.0}],
        min_length=1, max_length=12, validate_default=True, json_schema_extra={"x-ui": _ui(
            "노출 비중", question="어떤 시장에 얼마씩 담을까요?", help="합이 100 이 아니어도 돼요 — 남는 비중은 현금이에요.")})
    market: Literal["kr", "us", "any"] = Field("kr", json_schema_extra={"x-ui": _ui(
        "상장 시장", options={"kr": "국내 상장 우선", "us": "미국 상장", "any": "어디든"})})
    portfolio_value: float = Field(1e8, gt=0, le=1e13, json_schema_extra={"x-ui": _ui("평가 금액", "advanced", unit="원")})


def _implement(inputs: dict, p: ImplementParams) -> pg.NodeOutput:
    from src.api.allocation_routes import ImplementExposuresRequest, implement_exposures_route
    ex: dict[str, float] = {}
    for row in p.exposures:
        ex[row.exposure] = ex.get(row.exposure, 0.0) + row.pct
    res = _call(implement_exposures_route, ImplementExposuresRequest(
        exposures=ex, market=p.market, portfolio_value=p.portfolio_value), "상품으로 옮기지 못했어요")
    holdings = {k: v for k, v in (res.get("holdings") or {}).items() if (v or 0) > 0}
    if not holdings:
        why = "; ".join(f"{k}: {v}" for k, v in (res.get("unresolved") or {}).items()) or res.get("reason") or "놓인 비중 0"
        raise pg.NodeFailure(f"상품에 놓인 비중이 없어요 — {why}")
    view = {"result": _finite(res), "labels": _labels(list(holdings))}
    names = list(holdings)
    w = weights_value(names, np.array([holdings[n] / 100.0 for n in names]), sigma_annual=None,
                      sigma_source=None, exposure_implementation=True)
    mock = res.get("price_source") == "mock"
    return pg.NodeOutput(values={"weights": w}, view=view, provenance={"price_source": res.get("price_source")},
                         tags={"practice": mock, "sources": [f"instruments:{res.get('price_source') or '미상'}"]})


def _explain_implement(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    lines = r.get("lines") or []
    title = f"노출 {len(lines)}개를 상품으로 옮겼어요" + (f" — {r['unplaced_pct']:.0f}% 는 놓지 못했어요"
                                                    if (r.get("unplaced_pct") or 0) > 0 else "")
    facts = [f"{_EXPOSURE_LABELS.get(x['exposure'], x['exposure'])} {x['weight_pct']:.0f}% → {x['instrument']}"
             + (" (해외 상장)" if x.get("foreign_listing") else "") for x in lines[:6]]
    trust = [_t(CONFIRMED, "놓지 못한 노출의 비중은 다른 상품에 나눠 주지 않았어요 — 요청하지 않은 노출이 커지지 않게요.")]
    for k, v in (r.get("unavailable") or {}).items():
        trust.append(_t(UNKNOWN, str(v)))
    for k, v in (r.get("unresolved") or {}).items():
        trust.append(_t(UNKNOWN, str(v)))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["상품의 추적 오차", "환헤지 여부"]}


# ── 페어 스프레드 ────────────────────────────────────────────────────────────

class PairParams(BaseModel):
    model_config = _FORBID
    long_code: str = Field("005930", pattern=r"^[0-9A-Z.]{1,12}$", json_schema_extra={"x-ui": _ui("살 종목")})
    short_code: str = Field("000660", pattern=r"^[0-9A-Z.]{1,12}$", json_schema_extra={"x-ui": _ui("팔 종목")})
    hedge_ratio: float | None = Field(None, gt=0, le=10, json_schema_extra={"x-ui": _ui(
        "헤지 비율", "advanced", help="비우면 두 종목의 β 비율(β_살 ÷ β_팔)로 정해요.")})


def _pair(inputs: dict, p: PairParams) -> pg.NodeOutput:
    from src.api.sleeve_routes import PairSpreadRequest, pair_spread
    from src.data.mock_gate import mock_allowed
    res = _call(pair_spread, PairSpreadRequest(long_code=p.long_code, short_code=p.short_code, hedge_ratio=p.hedge_ratio),
                "페어를 만들지 못했어요")
    if res.get("error"):
        raise pg.NodeFailure(f"페어를 만들지 못했어요 — {res.get('message')}")
    practice = mock_allowed()
    res = {**res, "inputs": [
        {"key": "betas", "label": "β", "value": " · ".join(f"{k} {v:.2f}" if isinstance(v, (int, float)) else f"{k} 모름"
                                                         for k, v in (res.get("betas") or {}).items()),
         "basis": "관측" if not practice else "가정",
         "source": "가격 팩터 저장소 1년 β" + (" — 연습용 합성" if practice else "")},
        ({"key": "hedge_ratio", "label": "헤지 비율", "value": res["hedge_ratio"], "basis": "가정", "source": "직접 넣은 값"}
         if p.hedge_ratio is not None else
         {"key": "hedge_ratio", "label": "헤지 비율", "value": res["hedge_ratio"], "basis": "근사",
          "source": "β_살 ÷ β_팔 — 과거 β 가 유지된다는 가정"}),
    ]}
    return pg.NodeOutput(values={}, view={"result": _finite(res), "labels": _labels([p.long_code, p.short_code])},
                         tags={"practice": practice})


def _explain_pair(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    lab = view.get("labels") or {}
    title = (f"{lab.get(r.get('long'), r.get('long'))} 1 을 살 때 {lab.get(r.get('short'), r.get('short'))} "
             f"{r.get('hedge_ratio')} 를 팔아요")
    trust = []
    if r.get("beta_neutral") is None:
        trust.append(_t(UNKNOWN, r.get("beta_reason") or "순 β 를 모르는 상태예요."))
    elif r.get("beta_neutral"):
        trust.append(_t(CONFIRMED, "과거 β 로 보면 시장 방향 노출이 없어요(순 β ≈ 0)."))
    else:
        trust.append(_t(ASSUMED, f"순 β {r.get('net_beta')} 만큼 시장 방향 노출이 남아요."))
    trust.append(_t(ASSUMED, "β 는 과거 1년 값이에요 — 두 종목의 관계가 깨지면(페어 붕괴) 헤지가 듣지 않아요."))
    return {"title": title, "facts": [str(r.get("note") or "")], "trust": trust,
            "unmeasured": ["공매도 차입 비용·가능 여부", "공적분(장기 관계)"]}


# ── 시장 충격 ────────────────────────────────────────────────────────────────

def _asset_classes() -> tuple[str, ...]:
    from src.engine.market_impact import ASSET_CLASS_TIERS
    return tuple(ASSET_CLASS_TIERS)


class ImpactParams(BaseModel):
    model_config = _FORBID
    order_value_krw: float = Field(1e8, gt=0, le=1e13, json_schema_extra={"x-ui": _ui(
        "주문 금액", unit="원", question="한 번에 얼마를 사고팔까요?")})
    adv_krw: float = Field(5e9, gt=0, le=1e14, json_schema_extra={"x-ui": _ui(
        "하루 평균 거래대금", unit="원", help="그 종목이 하루에 거래되는 금액이에요 — 직접 넣는 값이에요.")})
    daily_volatility: float = Field(0.018, gt=0, le=1, json_schema_extra={"x-ui": _ui("하루 변동성", "advanced")})
    asset_class: Literal[_asset_classes()] = Field("kospi_mid", json_schema_extra={"x-ui": _ui(  # type: ignore[valid-type]
        "종목 규모", "advanced")})
    side: Literal["BUY", "SELL"] = Field("BUY", json_schema_extra={"x-ui": _ui(
        "방향", options={"BUY": "사기", "SELL": "팔기"})})


def _impact(inputs: dict, p: ImpactParams) -> pg.NodeOutput:
    from src.api.stage12_routes import MarketImpactRequest, realism_market_impact, realism_market_impact_calibration
    res = _call(realism_market_impact, MarketImpactRequest(**p.model_dump()), "시장 충격을 추정하지 못했어요")
    cal = realism_market_impact_calibration()
    res = {**res, "formula": cal.get("formula"), "split": cal.get("permanent_temporary_split"),
           "inputs": [_assumed("order", "주문 금액", p.order_value_krw, "원"),
                      _assumed("adv", "하루 평균 거래대금", p.adv_krw, "원", "직접 넣은 값 — 시세 저장소를 읽지 않았어요"),
                      _assumed("vol", "하루 변동성", p.daily_volatility),
                      _assumed("alpha", "충격 계수 α", res.get("alpha"), source=f"코드 상수표의 '{p.asset_class}' 칸")]}
    return pg.NodeOutput(values={}, view={"result": _finite(res)})


def _explain_impact(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    title = (f"이 주문은 가격을 약 {r.get('total_impact_bps'):.1f}bp 움직일 것으로 봐요"
             if isinstance(r.get("total_impact_bps"), (int, float)) else "시장 충격을 추정했어요")
    facts = [f"거래대금 대비 주문 {100 * (r.get('participation_rate') or 0):.2f}% · 예상 비용 {r.get('estimated_cost_krw'):,.0f}원"
             if isinstance(r.get("estimated_cost_krw"), (int, float)) else "",
             f"식: {r.get('formula')}"]
    trust = [_t(ASSUMED, "제곱근 법칙(충격 ∝ √(주문/거래대금))의 추정이에요 — 호가창을 읽은 값이 아니에요."),
             _t(ASSUMED, f"영구·일시 충격을 {r.get('split')} 로 나눴어요 — 코드의 가정이에요.")]
    return {"title": title, "facts": [f for f in facts if f], "trust": trust, "unmeasured": ["실제 호가 깊이", "분할 주문의 효과"]}


# ── 현금 수익 ────────────────────────────────────────────────────────────────

class CashParams(BaseModel):
    model_config = _FORBID
    invested_ratio: float = Field(0.9, ge=0, le=1, json_schema_extra={"x-ui": _ui(
        "투자 비중", question="자산의 몇 %를 투자하고 있나요?", help="비중 노드를 이으면 그 비중의 합(절댓값, 최대 1)을 써요.")})
    as_of_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui(
        "기준일", "advanced", help="비우면 오늘이에요. 그날까지 저장된 금리만 봐요.")})
    cash_floor: float = Field(0.0, ge=0, le=1, json_schema_extra={"x-ui": _ui("최소 현금", "advanced")})


def _cash(inputs: dict, p: CashParams) -> pg.NodeOutput:
    from src.api.stage12_routes import CashYieldRequest, realism_cash_yield
    w = inputs.get("weights")
    if w is not None:
        invested = min(1.0, float(np.abs(np.asarray(w["weights"], dtype=float)).sum()))
        inv_in = {"key": "invested", "label": "투자 비중", "value": round(invested, 4), "basis": "관측",
                  "source": "이어진 비중의 합(절댓값, 최대 1)"}
    else:
        invested = p.invested_ratio
        inv_in = _assumed("invested", "투자 비중", invested)
    as_of = p.as_of_date or date.today().isoformat()
    res = _call(realism_cash_yield, CashYieldRequest(invested_ratio=invested, as_of_date=as_of, cash_floor=p.cash_floor),
                "현금 수익을 계산하지 못했어요")
    assumed = res.get("rf_is_assumed")
    rf_in = {"key": "rf", "label": "무위험 금리", "value": res.get("rf_annual"),
             "basis": "가정" if assumed else "관측",
             "source": (f"저장된 금리가 없어 기본값을 썼어요({res.get('rf_source')})" if assumed
                        else f"{res.get('rf_source')} — {as_of} 이전 마지막 값")}
    res = {**res, "annual_cash_return": res.get("cash_ratio", 0) * (res.get("rf_annual") or 0),
           "as_of_date": as_of, "inputs": [inv_in, rf_in]}
    return pg.NodeOutput(values={}, view={"result": _finite(res)})


def _explain_cash(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    ann = r.get("annual_cash_return")
    title = (f"놀고 있는 현금 {100 * (r.get('cash_ratio') or 0):.1f}% 가 1년에 약 {100 * ann:.2f}%를 더해요"
             if isinstance(ann, (int, float)) else "현금 수익을 계산했어요")
    trust = [_t(UNKNOWN if r.get("rf_is_assumed") else CONFIRMED,
                "금리는 저장된 값이 없어 기본값(가정)이에요." if r.get("rf_is_assumed")
                else f"금리는 {r.get('rf_source')} 의 저장된 값이에요."),
             _t(ASSUMED, "단리·일할 계산이에요 — 실제 예치 상품의 조건은 반영하지 않아요.")]
    return {"title": title, "facts": [f"연 금리 {100 * (r.get('rf_annual') or 0):.2f}% · 기준일 {r.get('as_of_date')}"],
            "trust": trust, "unmeasured": ["세금", "예치 한도"]}


# ── 멀티전략 — 전략 용량 · 반사실 ───────────────────────────────────────────

_STRATEGY_UI = _ui("전략", question="어떤 전략들을 볼까요?", widget="pick", source="strategies",
                   help="백테스트 실행을 전략으로 등록하면 여기에 나와요.")


class CapacityParams(BaseModel):
    model_config = _FORBID
    strategy_ids: list[int] = Field([], max_length=20, json_schema_extra={"x-ui": _STRATEGY_UI})
    as_of_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui("기준일", "advanced")})
    max_pct_of_adv: float = Field(0.05, gt=0, le=1, json_schema_extra={"x-ui": _ui(
        "거래대금 대비 최대 비율", "advanced", help="하루 거래대금의 몇 %까지 사고팔 수 있다고 볼지예요.")})
    holding_period_days: int = Field(5, ge=1, le=60, json_schema_extra={"x-ui": _ui("쌓는 기간", "advanced", unit="일")})
    safety_buffer: float = Field(0.7, gt=0, le=1, json_schema_extra={"x-ui": _ui("안전 여유", "advanced")})


def _capacity(inputs: dict, p: CapacityParams) -> pg.NodeOutput:
    from src.api.stage12_routes import CapacityRequest, realism_capacity_estimate
    if not p.strategy_ids:
        raise pg.NodeFailure("전략을 하나 이상 골라 주세요.")
    as_of = p.as_of_date or date.today().isoformat()
    res = _call(realism_capacity_estimate, CapacityRequest(
        strategy_ids=p.strategy_ids, as_of_date=as_of, max_pct_of_adv=p.max_pct_of_adv,
        holding_period_days=p.holding_period_days, safety_buffer=p.safety_buffer), "용량을 추정하지 못했어요")
    res = {**res, "inputs": [_assumed("max_pct", "거래대금 대비 최대 비율", p.max_pct_of_adv),
                             _assumed("hold", "쌓는 기간", p.holding_period_days, "일"),
                             _assumed("buffer", "안전 여유", p.safety_buffer),
                             {"key": "adv", "label": "거래대금", "value": "종가×거래량 평균", "basis": "관측",
                              "source": "benchmark_prices — 전략의 종목들"}]}
    return pg.NodeOutput(values={}, view={"result": _finite(res)})


def _explain_capacity(view: dict, prov: dict, params: Any) -> dict:
    caps = (view.get("result") or {}).get("capacities") or {}
    known = [v for v in caps.values() if isinstance(v, dict) and v.get("available")]
    unknown = [v for v in caps.values() if isinstance(v, dict) and not v.get("available")]
    title = f"전략 {len(caps)}개 중 {len(known)}개의 용량을 쟀어요"
    facts = [f"전략 {v.get('strategy_id')}: {v['capacity_krw'] / 1e8:,.0f}억 원까지" for v in known[:5]]
    trust = [_t(ASSUMED, "용량 = 거래대금 × 비율 × 기간 × 여유 — 가정 세 개의 곱이에요.")]
    for v in unknown[:5]:
        trust.append(_t(UNKNOWN, f"전략 {v.get('strategy_id')}: {v.get('reason') or v.get('message')} — 제약을 걸지 않았어요(무한대 아님)."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["시장 충격을 넣은 순수익 기준 용량"]}


class CounterfactualParams(BaseModel):
    model_config = _FORBID
    strategy_ids: list[int] = Field([], max_length=20, json_schema_extra={"x-ui": _STRATEGY_UI})
    start_date: str = Field("2023-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui("시작일")})
    end_date: str = Field("2025-12-31", pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui("끝일")})
    base_allocation_method: Literal["hrp", "inverse_vol"] = Field("hrp", json_schema_extra={"x-ui": _ui(
        "기준 배분", options={"hrp": "비슷한 것끼리 묶어", "inverse_vol": "덜 흔들리는 쪽에 더"})})
    scenarios: list[str] = Field(["baseline", "no_netting", "equal_weight"], min_length=1, max_length=8,
                                 json_schema_extra={"x-ui": _ui("시나리오", "advanced")})
    regime_market: Literal["kr", "us"] = Field("kr", json_schema_extra={"x-ui": _ui("국면 시장", "advanced")})


def _counterfactual(inputs: dict, p: CounterfactualParams) -> pg.NodeOutput:
    from src.api.stage11_routes import CounterfactualRequest, multibacktest_counterfactual
    if len(p.strategy_ids) < 1:
        raise pg.NodeFailure("전략을 하나 이상 골라 주세요.")
    res = _call(multibacktest_counterfactual, CounterfactualRequest(
        strategy_ids=p.strategy_ids, start_date=p.start_date, end_date=p.end_date,
        base_allocation_method=p.base_allocation_method, scenarios=list(p.scenarios),
        regime_market=p.regime_market), "반사실을 계산하지 못했어요")
    scen = res.get("scenarios") or []
    if scen and not any(x.get("success") for x in scen):
        # ★전부 실패한 비교를 '완료' 로 보이지 않는다★ — 시나리오마다의 사유를 모아 실패시킨다.
        why = "; ".join(sorted({str(x.get("error") or "사유 미상") for x in scen}))
        raise pg.NodeFailure(f"시나리오가 하나도 돌지 않았어요 — {why}")
    return pg.NodeOutput(values={}, view={"result": _finite(res)},
                         provenance={"perf_label": res.get("perf_label")} if res.get("perf_label") else {})


def _explain_counterfactual(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    return {"title": "같은 전략을 다른 규칙으로 돌렸다면을 나란히 봤어요",
            "facts": [str(r.get("summary") or "")] if r.get("summary") else [],
            "trust": [_t(ASSUMED, "반사실도 시뮬레이션이에요 — 모든 시나리오가 같은 비용 가정을 받아요."),
                      _t(UNKNOWN, "원천 실행의 데이터가 합성인지는 전략별 출처 칸을 보세요.")],
            "unmeasured": ["시나리오 사이 차이의 통계적 유의성"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("rebalance_decision", "리밸런싱 판단", plain_label="지금 거래할 가치가 있나", category="실행", stage="act",
                    plain_description="목표 비중으로 옮길 때 얻는 효용과 드는 비용을 견줘 거래할지 판단해요.",
                    inputs=(P("weights", "Weights"),), outputs=(), run=_rebalance, params_model=RebalanceParams,
                    explain=_explain_rebalance, save=_save_decision, save_label="결정 기록 남기기",
                    description="rebalance_decision_route(record_decision=False) — 기록은 저장 버튼만."),
        pg.NodeSpec("implement_exposures", "노출 → 상품", plain_label="시장 비중을 상품으로", category="배분", stage="build",
                    plain_description="국내 주식·금리·원자재 같은 비중을 실제로 살 수 있는 상장 상품으로 바꿔요.",
                    inputs=(), outputs=(P("weights", "Weights"),), run=_implement, params_model=ImplementParams,
                    explain=_explain_implement, description="implement_exposures_route(/implement 와 같다)."),
        pg.NodeSpec("pair_spread", "페어 스프레드", plain_label="한 종목 사고 한 종목 팔기", category="배분", stage="build",
                    plain_description="두 종목을 사고팔아 시장 방향 노출을 줄이는 비율을 봐요.",
                    inputs=(), outputs=(), run=_pair, params_model=PairParams, explain=_explain_pair,
                    description="sleeve_routes.pair_spread(/pair-spread 와 같다)."),
        pg.NodeSpec("market_impact", "시장 충격", plain_label="주문이 가격을 얼마나 밀까", category="실행", stage="act",
                    plain_description="주문 금액과 거래대금으로 체결 때 가격이 얼마나 움직일지 추정해요.",
                    inputs=(), outputs=(), run=_impact, params_model=ImpactParams, explain=_explain_impact,
                    description="realism_market_impact(/realism/market-impact/estimate 와 같다)."),
        pg.NodeSpec("cash_yield", "현금 수익", plain_label="놀고 있는 현금의 이자", category="실행", stage="act",
                    plain_description="투자하지 않은 현금이 무위험 금리로 얼마를 버는지 봐요.",
                    inputs=(P("weights", "Weights", required=False),), outputs=(), run=_cash, params_model=CashParams,
                    explain=_explain_cash, description="realism_cash_yield(/realism/cash-yield/estimate 와 같다) · 금리 출처 표시."),
        pg.NodeSpec("strategy_capacity", "전략 용량", plain_label="얼마까지 굴릴 수 있나", category="전략", stage="check",
                    plain_description="전략 종목들의 거래대금으로 그 전략에 넣을 수 있는 돈의 한도를 추정해요.",
                    inputs=(), outputs=(), run=_capacity, params_model=CapacityParams, explain=_explain_capacity,
                    description="realism_capacity_estimate(/realism/capacity/estimate 와 같다) · 모르면 무한대가 아니라 모름."),
        pg.NodeSpec("counterfactual", "멀티전략 반사실", plain_label="다른 규칙이었다면", category="전략", stage="check",
                    plain_description="같은 전략 묶음을 상계·균등 배분 같은 다른 규칙으로 돌렸을 때와 나란히 봐요.",
                    inputs=(), outputs=(), run=_counterfactual, params_model=CounterfactualParams,
                    explain=_explain_counterfactual,
                    description="multibacktest_counterfactual(/multibacktest/counterfactual 와 같다) · 멀티전략 문 그대로."),
    ):
        registry.register(spec)
