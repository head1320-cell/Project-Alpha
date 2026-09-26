"""AAS 그래프 — 전략·기업 노드 (BK W5) · ★기존 문을 그대로 부르고, 아는 만큼만 말한다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W5

- 전략 묶음 돌려 보기(`strategy_backtest`): `/multibacktest/run` 을 **`save=False` 로** 그대로 부른다 —
  같은 가드(코어 부재 503 · 없는 기능 422) · 같은 비용 블록 · 같은 출처(`sources`·`perf_label`). ★기록하지
  않는다★(`run_and_save` 가 아니라 `run`). `hrp_macro` 는 선택지에 없다 — 배분기(`allocator.METHODS`)가
  가진 것만 고르게 하고, 문의 거절은 그대로 둔다.
- 기업 전망 넣기(`company_views`): `/analyze` 의 `use_company_views` 와 같은 함수(`prices_for`·
  `company_views`)다. 뷰는 **지금 시점 전용**(`pit: forward_only`) — 하류 정책 백테스트가 거절한다.
  옵티마이저는 이 뷰를 사용자 뷰와 섞지 않고 `company_views=` 로 따로 넘긴다(`/analyze` 와 같은 자리).
- 가치평가로 점수 매기기(`valuation_scores`): `/valuation/compare` 를 그대로 부른다. 점수는 **−괴리율**
  (싼 만큼 높다). ★적정가를 못 낸 종목(데이터 없음 → 괴리율 0)은 점수에 넣지 않는다★ — 미상 ≠ 0.
- 결정 되짚기(`attribution_review`): `/attribution/{run_id}` 와 같은 `_attribution_for`. 저장된 연구
  실행을 읽기만 한다. 벤치마크 구성종목이 없어 못 재는 분해는 "안 쟀어요" 로 그대로 둔다.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _pydantic_reason, _subset, _ui
from src.api.stage11_routes import MultiBacktestRunRequest
from src.api.valuation_routes import EvaluateRequest
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg
from src.engine.allocator import METHODS

logger = logging.getLogger(__name__)

P = pg.Port
_FORBID = ConfigDict(extra="forbid")
_DATE = r"^\d{4}-\d{2}-\d{2}$"
_TODAY_ONLY = "오늘의 재무·가격으로 만든 값이에요 — 과거에 쓰면 미래를 보고 한 계산이 돼서 과거 검증은 막아요."


def _labels(codes: list[str]) -> dict[str, str]:
    from src.api.allocation_routes import _labels as lab
    return lab(codes)


def _detail_reason(detail: Any) -> str:
    """HTTPException detail(문자열 · `{reason}` · 가용성 블록) → 한 줄 사유."""
    if isinstance(detail, dict):
        return str(detail.get("reason") or detail)
    return str(detail)


# ── 전략 묶음 돌려 보기 ───────────────────────────────────────────────────────

_METHOD = {"hrp": "비슷한 것끼리 묶어", "inverse_vol": "덜 흔들리는 쪽에 더"}
#: 배분기 엔진(`_validate_config`)이 받는 리밸런싱 정책 — 테스트가 엔진이 다 받는지 확인한다.
_POLICY = {"monthly": "매달", "quarterly": "분기마다", "weekly": "매주", "daily": "매일",
           "regime_change": "국면이 바뀔 때"}

StrategyParams = _subset(
    "StrategyBacktestParams", MultiBacktestRunRequest,
    ("strategy_ids", "initial_capital", "netting_enabled", "commission_rate", "slippage_rate",
     "lookback_days", "max_weight", "min_weight", "regime_market"),
    ui={
        "strategy_ids": _ui("전략", question="어떤 전략들을 묶을까요?", widget="pick", source="strategies",
                            help="백테스트 실행을 전략으로 등록하면 여기에 나와요."),
        "initial_capital": _ui("시작 금액", "advanced", unit="원"),
        "netting_enabled": _ui("주문 상계", "advanced", help="전략끼리 반대 주문을 서로 지워 비용을 줄여요."),
        "commission_rate": _ui("수수료율", "advanced"),
        "slippage_rate": _ui("슬리피지율", "advanced"),
        "lookback_days": _ui("비중 계산 기간", "advanced", unit="일"),
        "max_weight": _ui("전략 하나의 최대 비중", "advanced"),
        "min_weight": _ui("전략 하나의 최소 비중", "advanced"),
        "regime_market": _ui("국면을 볼 시장", "advanced", options={"kr": "한국", "us": "미국"}),
    },
    allocation_method=(Literal[tuple(METHODS)], Field("hrp", json_schema_extra={"x-ui": _ui(
        "나누는 방식", question="전략끼리 어떻게 나눌까요?", widget="cards", options=_METHOD)})),
    rebalance_policy=(Literal[tuple(_POLICY)], Field("monthly", json_schema_extra={"x-ui": _ui(
        "다시 나누는 때", question="언제 비중을 다시 맞출까요?", options=_POLICY)})),
    start_date=(str | None, Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
        "시작일", "advanced", help="비우면 고른 전략들이 함께 기록된 첫날부터예요.")})),
    end_date=(str | None, Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
        "종료일", "advanced", help="비우면 함께 기록된 마지막 날까지예요.")})),
)


#: 문으로 그대로 넘기는 칸 — 사용자가 노드에서 **정한 것만** 넘긴다.
_PASS_THROUGH = ("initial_capital", "netting_enabled", "commission_rate", "slippage_rate", "lookback_days",
                 "max_weight", "min_weight", "regime_market")


def _common_span(ids: list[int]) -> tuple[str, str]:
    """고른 전략들이 **함께** 기록된 첫날·마지막 날 — 엔진이 쓰는 같은 수익률 행렬에서 읽는다."""
    from src.database import get_sync_engine
    from src.engine.strategy_registry import StrategyRegistry
    m = StrategyRegistry(get_sync_engine()).load_returns_matrix(ids, drop_na_rows=True)
    if m is None or m.empty:
        raise pg.NodeFailure("고른 전략들이 함께 기록된 날이 없어요 — 기간이 겹치는 전략을 골라 주세요.")
    return str(m.index.min().date()), str(m.index.max().date())


def _strategy_backtest(inputs: dict, p) -> pg.NodeOutput:
    from src.api import stage11_routes as s11
    ids = list(p.strategy_ids)
    span = None
    start, end = p.start_date, p.end_date
    if start is None or end is None:
        try:
            s11._guard()                                   # 코어가 없으면 기간을 읽기 전에 사유를 말한다
        except HTTPException as e:
            raise pg.NodeFailure(f"전략 묶음을 돌릴 수 없어요 — {_detail_reason(e.detail)}") from e
        span = _common_span(ids)
        start, end = start or span[0], end or span[1]
    # ★사용자가 정한 칸만 넘긴다★ — 문의 비용 블록은 "명시한 요율" 과 "기본값" 을 가른다
    # (`cost_explicit_fields`). 노드 기본값까지 넘기면 기본 요율이 "명시" 로 둔갑한다.
    chosen = {k: getattr(p, k) for k in _PASS_THROUGH if k in p.model_fields_set}
    req = s11.MultiBacktestRunRequest(
        strategy_ids=ids, start_date=start, end_date=end, allocation_method=p.allocation_method,
        rebalance_policy=p.rebalance_policy, save=False, **chosen)
    try:
        out = s11.multibacktest_run(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"전략 묶음을 돌리지 못했어요 — {_detail_reason(e.detail)}") from e
    if not out.get("success"):
        raise pg.NodeFailure(f"전략 묶음을 돌리지 못했어요 — {out.get('message')}")
    recs = out.get("daily_records") or []
    view = {
        "summary": out["summary"], "strategy_names": {str(k): v for k, v in out["strategy_names"].items()},
        "n_trading_days": out["n_trading_days"], "warnings": out.get("warnings") or [],
        "sources": out.get("sources"), "perf_label": out.get("perf_label"), "cost_model": out.get("cost_model"),
        "period": {"start": start, "end": end, "whole_record": span is not None},
        "method": p.allocation_method, "policy": p.rebalance_policy,
        "curve": [{"date": r["date"], "equity": r["portfolio_equity"], "dd": r["drawdown_pct"]} for r in recs],
        "last_weights": {str(k): v for k, v in (recs[-1]["weights"] if recs else {}).items()},
    }
    strategies = (out.get("sources") or {}).get("strategies") or []
    mock = [s.get("is_mock_data") for s in strategies]
    pit = [s.get("is_pit_verified") for s in strategies]
    tags = {"practice": any(m is True for m in mock),
            "pit": "pit" if pit and all(x is True for x in pit) else "unknown",
            "sources": ["multibacktest"] + ([] if all(m is not None for m in mock) else ["전략 출처 미상"])}
    return pg.NodeOutput(values={"result": view}, view=view, tags=tags,
                         provenance={"perf_label": out.get("perf_label")})


def _explain_strategy(view: dict, prov: dict, params: Any) -> dict:
    s = view.get("summary") or {}
    names = view.get("strategy_names") or {}
    per = view.get("period") or {}
    facts = [f"전략 {len(names)}개를 ‘{_METHOD.get(view.get('method'), view.get('method'))}’ 방식으로 "
             f"{_POLICY.get(view.get('policy'), view.get('policy'))} 다시 나눴어요.",
             f"기간은 {per.get('start')} ~ {per.get('end')}" + (" (함께 기록된 전체)" if per.get("whole_record") else "") + "예요."]
    if s.get("max_drawdown_pct") is not None:
        facts.append(f"가장 크게 빠진 폭은 {abs(float(s['max_drawdown_pct'])):.1f}%예요.")
    trust = [_t(CONFIRMED, "기록하지 않고 계산만 했어요 — 실행 기록은 남지 않아요.")]
    srcs = (view.get("sources") or {}).get("strategies") or []
    if any(x.get("is_mock_data") is True for x in srcs):
        trust.append(_t(UNKNOWN, "연습용(합성) 데이터로 등록된 전략이 있어요 — 실제 성과를 말해 주지 않아요."))
    if not all(x.get("is_pit_verified") is True for x in srcs):
        trust.append(_t(UNKNOWN, "시점 정합이 확인되지 않은 전략이 있어요."))
    for w in view.get("warnings") or []:
        trust.append(_t(ASSUMED, str(w)))
    return {"title": f"전략 {len(names)}개를 묶어 돌려 봤어요",
            "headline": ({"label": "전체 수익", "value": s["total_return_pct"], "unit": "%",
                          "text": f"{float(s['total_return_pct']):+.1f}%"} if s.get("total_return_pct") is not None else None),
            "facts": facts, "trust": trust,
            "unmeasured": ["매크로 기울기 배분(hrp_macro) — 규칙이 정해지지 않아 아직 없어요",
                           "표본 밖 성과 — 등록된 전략의 과거 기록을 다시 나눈 결과예요"]}


# ── 기업 전망 넣기 ────────────────────────────────────────────────────────────

class CompanyViewsParams(BaseModel):
    model_config = _FORBID
    convergence_years: float | None = Field(None, ge=1, le=30, json_schema_extra={"x-ui": _ui(
        "차이가 좁혀지는 기간", question="적정가와의 차이가 몇 년에 걸쳐 좁혀진다고 볼까요?", unit="년",
        presets=[{"label": "가치평가 가정 그대로", "value": None}, {"label": "3년", "value": 3},
                 {"label": "5년", "value": 5}],
        help="가정이에요 — 잰 값이 아니에요.")})


def _company_views(inputs: dict, p: CompanyViewsParams) -> pg.NodeOutput:
    from src.engine.company_views import company_views, prices_for
    r = inputs["returns"]
    names = list(r["names"])
    prices, price_source = prices_for(names)
    views, reasons = company_views(names, prices, as_of=r["as_of"], convergence_years=p.convergence_years)
    if not views:
        why = "; ".join(f"{c}: {x.get('reason') or x.get('kind')}" for c, x in list(reasons.items())[:3])
        raise pg.NodeFailure(f"기업 전망을 하나도 만들지 못했어요 — {why or '사유 미상'}")
    user = list(inputs.get("views") or [])
    any_mock = any(v.get("is_mock") for v in views)
    view = {"views": views, "reasons": reasons, "price_source": price_source, "n_user_views": len(user),
            "labels": _labels(names), "as_of": r["as_of"], "any_mock": any_mock,
            "saturated": sum(1 for v in views if v.get("confidence_saturated")),
            "research_usage": views[0]["research_usage"]}
    return pg.NodeOutput(values={"views": user + views}, view=view,
                         tags={"pit": "forward_only", "practice": any_mock or mock_allowed(),
                               "sources": ["company_views"]})


def _explain_company(view: dict, prov: dict, params: Any) -> dict:
    views, reasons = view.get("views") or [], view.get("reasons") or {}
    facts = [f"종목 {len(views)}개에 전망을 만들었어요" + (f" · {len(reasons)}개는 만들지 못했어요" if reasons else "") + "."]
    if view.get("n_user_views"):
        facts.append(f"내 생각 {view['n_user_views']}개와 함께 넘겨요.")
    trust = [_t(ASSUMED, "적정가와의 차이가 일정 기간에 걸쳐 좁혀진다고 가정했어요 — 폭은 잰 값이 아니에요."),
             _t(UNKNOWN, _TODAY_ONLY)]
    if view.get("saturated"):
        trust.append(_t(ASSUMED, f"{view['saturated']}개는 확신이 상한에 닿았어요."))
    if view.get("any_mock") or mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 재무·가격이 합성일 수 있어요 — 실제 전망을 말해 주지 않아요."))
    return {"title": f"기업 전망 {len(views)}개를 만들었어요", "facts": facts, "trust": trust,
            "unmeasured": ["이 전망이 맞았는지(예측력)", "과거 시점의 재무로 만든 전망(빈티지 재무가 없어요)"]}


# ── 가치평가로 점수 매기기 ────────────────────────────────────────────────────

ValuationParams_ = _subset("ValuationScoresParams", EvaluateRequest, ("beta", "projection_years"), ui={
    "beta": _ui("베타", question="시장보다 얼마나 흔들린다고 볼까요?",
                presets=[{"label": "시장과 같게(1.0)", "value": 1.0}, {"label": "덜 흔들림(0.8)", "value": 0.8},
                         {"label": "더 흔들림(1.2)", "value": 1.2}], help="가정이에요 — 할인율에 들어가요."),
    "projection_years": _ui("내다보는 기간", "advanced", unit="년"),
})


def _no_intrinsic(row: dict) -> bool:
    """적정가를 못 낸 행 — 엔진이 괴리율을 0 으로 채운다(정의 불가). 점수로 쓰면 '적정' 으로 위장한다."""
    return row.get("verdict") == "데이터 없음" or not float(row.get("intrinsic_value") or 0) > 0


def _valuation_scores(inputs: dict, p) -> pg.NodeOutput:
    from src.api.valuation_routes import CompareRequest, valuation_compare
    from src.engine.company_views import prices_for
    codes = list(inputs["universe"]["tickers"])
    prices, price_source = prices_for(codes)
    reasons = {c: "현재가를 구하지 못했어요 — 지어내지 않아요." for c in codes if c not in prices}
    priced = [c for c in codes if c in prices]
    if not priced:
        raise pg.NodeFailure("현재가를 구한 종목이 없어 가치평가를 할 수 없어요.")
    try:
        req = CompareRequest(stocks=[{"stock_code": c, "current_price": prices[c]} for c in priced],
                             beta=p.beta, projection_years=p.projection_years)
    except ValidationError as e:
        raise pg.NodeFailure(f"가치평가 비교 규칙에 맞지 않아요(/valuation/compare 와 같은 규칙) — "
                             f"{_pydantic_reason(e)}") from e
    try:
        out = valuation_compare(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"가치평가를 하지 못했어요 — {_detail_reason(e.detail)}") from e
    scores: dict[str, float] = {}
    for row in out["results"]:
        t = str(row.get("ticker"))
        if row.get("error"):
            reasons[t] = str(row["error"])
        elif _no_intrinsic(row):
            reasons[t] = "재무가 없어 적정가를 내지 못했어요 — 괴리율 0(적정)으로 치지 않아요."
        else:
            scores[t] = round(-float(row["gap_pct"]), 4)
    if not scores:
        raise pg.NodeFailure("적정가를 낸 종목이 없어요 — " + "; ".join(f"{c}: {w}" for c, w in list(reasons.items())[:3]))
    any_mock = any(row.get("is_mock") for row in out["results"])
    view = {"rows": out["results"], "scores": scores, "reasons": reasons, "labels": _labels(codes),
            "price_source": price_source, "any_mock": any_mock,
            "params": {"beta": p.beta, "projection_years": p.projection_years}}
    return pg.NodeOutput(values={"scores": {"scores": scores, "kind": "valuation"}}, view=view,
                         tags={"pit": "forward_only", "practice": any_mock or mock_allowed(),
                               "sources": ["valuation_compare"]})


def _explain_valuation(view: dict, prov: dict, params: Any) -> dict:
    scores, reasons = view.get("scores") or {}, view.get("reasons") or {}
    labels = view.get("labels") or {}
    top = max(scores, key=lambda k: scores[k]) if scores else None
    facts = [f"{len(scores)}종목의 적정가를 계산했어요" + (f" · {len(reasons)}종목은 못 했어요" if reasons else "") + ".",
             "점수는 ‘적정가보다 싼 정도’(−괴리율)예요 — 높을수록 싸요."]
    trust = [_t(ASSUMED, f"베타 {view['params']['beta']} · {view['params']['projection_years']}년 전망을 가정했어요."),
             _t(UNKNOWN, _TODAY_ONLY)]
    if view.get("any_mock") or mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 재무가 합성일 수 있어요 — 실제 가치를 말해 주지 않아요."))
    return {"title": f"{len(scores)}종목에 가치평가 점수를 매겼어요",
            "headline": ({"label": f"가장 싼 종목 · {labels.get(top, top)}", "value": scores[top], "unit": "%",
                          "text": f"적정가보다 {scores[top]:.1f}% 싸요" if scores[top] >= 0 else
                                  f"적정가보다 {-scores[top]:.1f}% 비싸요"} if top else None),
            "facts": facts, "trust": trust,
            "unmeasured": ["이 점수로 고른 종목의 미래 성과(예측력)", "과거 시점의 재무로 계산한 적정가"]}


# ── 결정 되짚기 ──────────────────────────────────────────────────────────────

class AttributionParams(BaseModel):
    model_config = _FORBID
    run_id: str = Field(..., min_length=1, max_length=64, json_schema_extra={"x-ui": _ui(
        "연구 기록", question="어떤 결정을 되짚어 볼까요?", widget="pick", source="research_runs",
        help="‘비중 계산’ 결과를 연구 기록으로 남기면 여기에 나와요.")})
    as_of: str | None = Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
        "기준일", "advanced", help="비우면 오늘까지의 가격으로 되짚어요.")})


def _attribution(inputs: dict, p: AttributionParams) -> pg.NodeOutput:
    from src.api.attribution_routes import _attribution_for
    try:
        rep = _attribution_for(p.run_id, as_of=p.as_of)
    except HTTPException as e:
        raise pg.NodeFailure(f"그 기록을 되짚지 못했어요 — {_detail_reason(e.detail)}") from e
    src = (rep.get("coverage") or {}).get("source")
    rep = {**rep, "labels": _labels([a["code"] for a in (rep.get("contribution") or {}).get("assets") or []])}
    return pg.NodeOutput(values={}, view=rep,
                         tags={"practice": src == "mock", "sources": [f"attribution:{src or '미상'}"]})


def _explain_attribution(view: dict, prov: dict, params: Any) -> dict:
    ret = view.get("returns") or {}
    eva = view.get("expected_vs_actual") or {}
    cov = view.get("coverage") or {}
    facts = [f"{view.get('decision_date')}에 내린 결정을 {view.get('as_of')}까지({view.get('elapsed_days')}일) 되짚었어요."]
    if eva.get("expected_return_pct") is not None and eva.get("actual_return_pct") is not None:
        facts.append(f"기대는 {float(eva['expected_return_pct']):+.1f}%, 실제는 {float(eva['actual_return_pct']):+.1f}%예요.")
    trust = []
    if cov.get("has_expost"):
        trust.append(_t(CONFIRMED, f"결정 뒤의 가격으로만 쟀어요 — 종목 {cov.get('covered')}/{cov.get('tickers')}개."))
    else:
        trust.append(_t(UNKNOWN, "결정 뒤 지난 시간이 없거나 가격이 없어 실제 수익을 재지 못했어요."))
    if cov.get("missing"):
        trust.append(_t(UNKNOWN, f"가격이 없는 종목은 빼고 쟀어요: {', '.join(cov['missing'])}."))
    if cov.get("source") == "mock":
        trust.append(_t(UNKNOWN, "연습용(합성) 가격이에요 — 실제 성과를 말해 주지 않아요."))
    return {"title": "결정을 되짚어 봤어요" if cov.get("has_expost") else "아직 되짚을 결과가 없어요",
            "headline": ({"label": "실제 수익", "value": ret["portfolio_pct"], "unit": "%",
                          "text": f"{float(ret['portfolio_pct']):+.1f}%"} if ret.get("portfolio_pct") is not None else None),
            "facts": facts, "trust": trust,
            "unmeasured": ["종목 선택·업종 배분·팩터 효과 — 벤치마크 구성종목 비중이 없어 나누지 않아요"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("strategy_backtest", "전략 묶음 백테스트", stage="check", plain_label="전략 묶음 돌려 보기",
                    plain_description="등록한 전략 여러 개를 한 계좌처럼 나눠 담았다면 어땠을지 봐요. 기록은 남기지 않아요.",
                    inputs=(), outputs=(P("result", "StrategyResult"),), run=_strategy_backtest,
                    params_model=StrategyParams, explain=_explain_strategy, category="전략",
                    description="/multibacktest/run(save=False) — 같은 가드·비용·출처. hrp_macro 는 선택지에 없다."),
        pg.NodeSpec("company_views", "기업 전망", stage="belief", plain_label="기업 전망 넣기",
                    plain_description="재무로 계산한 적정가와 지금 가격의 차이를 전망으로 바꿔 넣어요.",
                    inputs=(P("returns", "Returns"), P("views", "Views", required=False)),
                    outputs=(P("views", "Views"),), run=_company_views, params_model=CompanyViewsParams,
                    explain=_explain_company, category="추정",
                    description="/analyze use_company_views 와 같은 company_views. 지금 시점 전용(forward_only)."),
        pg.NodeSpec("valuation_scores", "가치평가 점수", stage="signal", plain_label="가치평가로 점수 매기기",
                    plain_description="종목마다 적정가를 계산해 얼마나 싼지 점수로 매겨요.",
                    inputs=(P("universe", "Universe"),), outputs=(P("scores", "Scores"),), run=_valuation_scores,
                    params_model=ValuationParams_, explain=_explain_valuation, category="신호",
                    description="/valuation/compare 와 같은 3-모델 가치평가. 점수 = −괴리율, 적정가 없음은 제외."),
        pg.NodeSpec("attribution_review", "성과 귀인", stage="act", plain_label="결정 되짚기",
                    plain_description="저장한 결정이 그 뒤 실제로 어땠는지 기대와 비교해요.",
                    inputs=(), outputs=(), run=_attribution, params_model=AttributionParams,
                    explain=_explain_attribution, category="기록",
                    description="/attribution/{run_id} 와 같은 _attribution_for — 읽기만 한다."),
    ):
        registry.register(spec)
