"""AAS 그래프 — 신호·후보 노드 (BK W2) · ★스크리너·알파·팩터·슬리브를 다시 쓰지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W2

마법사의 CONSTRUCT·ALPHA LAB·OPTIMIZE 도구와 스크리너를 노드로 옮긴다. 산수는 같은 함수다 —
`screener_routes._run_advanced_core`(스크리너 3-레이어·`ValuationScreener` 는 손대지 않는다) ·
`allocation_routes.factor_scores`(`/factor-portfolio` 본문에서 꺼냄) · `alpha_lab.score_alpha` ·
`_factor_weights`·`_raw_weights_for_model` · `neutralize_portfolio` · `combine_sleeves`.

## ★기존 도구의 조용한 폴백을 노드는 하지 않는다★
- `_factor_weights` 는 시세가 없으면 균등 비중으로, `weights_for_model` 은 최적화가 실패하면 역변동성으로
  **말없이** 바꾼다. 노드는 수익률 기반 비중에 그래프의 수익률을 요구하고, 최적화가 안 풀리면 **실패 + 사유**.

## 계보
- 스크리너·팩터 점수·알파(기준일 없음)는 **오늘의 값으로 고른 것**이다 — `pit: forward_only`. 이 종목들로
  과거를 돌리면 미래를 보고 고른 셈이라, 하류의 정책 백테스트가 거절한다(BK0 문지기).
- 알파에 기준일을 주면 공시 지연을 둔 근사 시점 정합이라 `pit: unknown`(확인되지 않았다).
- 재무·팩터 스토어는 개발(mock) 모드에서 합성일 수 있어 `practice` 를 넘치게 단다(운영에서는 붙지 않는다).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api import allocation_routes as _ar
from src.api import screener_routes as _sr
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _pct, _t
from src.api.allocation_graph_nodes import _subset, _ui, weights_value
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg

logger = logging.getLogger(__name__)

P = pg.Port
_FORBID = ConfigDict(extra="forbid")

_TODAY = "오늘 기준 값으로 골랐어요 — 이 종목들로 과거를 돌려 보면 미래를 보고 고른 셈이라 과거 검증은 막아요."
_DEV = "개발 모드라 재무·시세 값이 합성일 수 있어요 — 실제 종목 선택을 말해 주지 않아요."


def _plain_items(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    return [{k: it.get(k) for k in keys if k in it} for it in items]


# ── 스크리너 ─────────────────────────────────────────────────────────────────

_UNIVERSE_LABEL = {"kospi50": "코스피 50", "kospi200": "코스피 200", "kosdaq150": "코스닥 150",
                   "etf": "ETF", "mapped": "매핑 종목"}


def _presets_filter() -> list[dict]:
    c = lambda f, op, v: {"field": f, "op": op, "value": v}  # noqa: E731
    return [
        {"label": "조건 없음", "value": {"logic": "AND", "conditions": [], "groups": []}},
        {"label": "싼 종목", "value": {"logic": "AND", "conditions": [c("per", "lt", 10), c("pbr", "lt", 1)], "groups": []}},
        {"label": "꾸준히 버는", "value": {"logic": "AND", "conditions": [c("roe", "gt", 10)], "groups": []}},
        {"label": "배당 주는", "value": {"logic": "AND", "conditions": [c("dividend_yield", "gt", 3)], "groups": []}},
        {"label": "빚이 적은", "value": {"logic": "AND", "conditions": [c("debt_to_equity", "lt", 1)], "groups": []}},
    ]


class ScreenerParams(BaseModel):
    model_config = _FORBID
    universe: Literal[tuple(_UNIVERSE_LABEL)] = Field("kospi50", json_schema_extra={"x-ui": _ui(
        "후보 범위", question="어디서 고를까요?", widget="cards", options=_UNIVERSE_LABEL,
        help="앞에 ‘종목 고르기’를 이으면 그 종목들 안에서 골라요.")})
    filter_ast: _sr.FilterGroupModel = Field(
        default_factory=lambda: _sr.FilterGroupModel(logic="AND", conditions=[], groups=[]),
        json_schema_extra={"x-ui": _ui("조건", question="어떤 조건으로 거를까요?", widget="filter",
                                       presets=_presets_filter(),
                                       help="조건은 서버가 필드 목록으로 검사해요 — 모르는 필드는 계산하지 않아요.")})
    top_n: int = Field(10, ge=3, le=30, json_schema_extra={"x-ui": _ui(
        "넘길 종목 수", question="몇 종목을 넘길까요?", unit="개",
        presets=[{"label": "5개", "value": 5}, {"label": "10개", "value": 10}, {"label": "20개", "value": 20}])})
    sort_by: str = Field("composite_score", max_length=60, json_schema_extra={"x-ui": _ui(
        "정렬 기준", "advanced", help="필드 id 예: composite_score · roe · per")})
    ascending: bool = Field(False, json_schema_extra={"x-ui": _ui("작은 값 먼저", "advanced")})
    liquidity_floor: Literal["off", "relaxed", "standard", "institutional"] = Field(
        "standard", json_schema_extra={"x-ui": _ui("유동성 문턱", "advanced", options={
            "off": "없음", "relaxed": "느슨하게", "standard": "보통", "institutional": "기관 수준"})})


def _screener(inputs: dict, p: ScreenerParams) -> pg.NodeOutput:
    cand = inputs.get("universe")
    req = _sr.AdvancedRunRequest(
        universe=p.universe, custom_tickers=list(cand["tickers"]) if cand else None,
        filter_ast=p.filter_ast, sort_by=p.sort_by, ascending=p.ascending,
        limit=max(p.top_n, 50), liquidity_floor=p.liquidity_floor)
    try:
        out = _sr._run_advanced_core(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"조건을 확인해 주세요 — {e.detail}") from e
    items = out.get("items") or []
    picked = items[: p.top_n]
    tickers = [it["stock_code"] for it in picked if it.get("stock_code")]
    if len(tickers) < 2:
        raise pg.NodeFailure(f"조건에 맞는 종목이 {len(tickers)}개뿐이에요 — 조건을 넓히거나 후보 범위를 키워 주세요.")
    ds = out.get("data_source") or {}
    practice = not bool(ds.get("fully_real"))
    view = {"tickers": tickers, "labels": _ar._labels(tickers),
            "items": _plain_items(picked, ("stock_code", "corp_name", "composite_score", "per", "pbr", "roe",
                                           "dividend_yield", "market_cap")),
            "total_evaluated": out.get("total_evaluated"), "total_passed": out.get("total_passed"),
            "universe": "직접 이은 종목" if cand else _UNIVERSE_LABEL.get(p.universe, p.universe),
            "data_source": ds, "liquidity_gate": out.get("liquidity_gate")}
    return pg.NodeOutput(
        values={"universe": {"tickers": tickers, "weights": None, "benchmark": "KOSPI"}}, view=view,
        provenance={"data_source": ds},
        tags={"pit": "forward_only", "practice": practice, "sources": ["screener:" + ("real" if not practice else "mock")]})


def _explain_screener(view: dict, prov: dict, params: Any) -> dict:
    n = len(view.get("tickers") or [])
    passed, evaluated = view.get("total_passed"), view.get("total_evaluated")
    facts = [f"{view.get('universe')}에서 {evaluated}종목을 보고 {passed}종목이 조건을 통과했어요."]
    names = [view["labels"].get(c, c) for c in (view.get("tickers") or [])[:3]]
    if names:
        facts.append("앞쪽 종목: " + ", ".join(names) + ".")
    trust = [_t(CONFIRMED, "조건은 서버의 필드 목록으로 검사했어요."), _t(UNKNOWN, _TODAY)]
    if not (view.get("data_source") or {}).get("fully_real"):
        trust.append(_t(UNKNOWN, "재무나 시세 중 하나 이상이 합성(mock) 데이터예요 — 실제 선택을 말해 주지 않아요."))
    return {"title": f"조건에 맞는 종목 {n}개를 골랐어요",
            "headline": {"label": "넘긴 종목", "value": n, "unit": "개", "text": f"{n}개"},
            "facts": facts, "trust": trust,
            "unmeasured": ["이 조건이 과거에도 좋은 종목을 골랐는지", "고른 뒤의 성과"]}


# ── 팩터 점수 ────────────────────────────────────────────────────────────────

def _factor_options() -> dict[str, str]:
    from src.engine.filter_ast import FIELD_BY_ID
    return {fid: getattr(meta, "label", fid) for fid, meta in FIELD_BY_ID.items()}


FactorItem = _subset("FactorItem", _ar.FactorSpec, ("id", "weight", "direction"), ui={
    "id": _ui("팩터", options=_factor_options()),
    "weight": _ui("가중치", help="상대 비중이에요(합이 1일 필요 없어요)."),
    "direction": _ui("방향", options={"0": "자동", "1": "높을수록 좋음", "-1": "낮을수록 좋음"}),
})


class FactorScoreParams(BaseModel):
    model_config = _FORBID
    factors: list[FactorItem] = Field(
        default_factory=lambda: [FactorItem(id="per"), FactorItem(id="roe")], min_length=1, max_length=12,
        json_schema_extra={"x-ui": _ui("팩터", question="어떤 성격에 점수를 줄까요?",
                                       help="방향 ‘자동’은 필드가 알고 있는 좋은 방향을 따라요.")})
    sample_size: int = Field(400, ge=50, le=1500, json_schema_extra={"x-ui": _ui(
        "표본 크기", "advanced", help="앞에 종목을 잇지 않으면 유니버스 표본에서 점수를 매겨요.")})


def _factor_scores(inputs: dict, p: FactorScoreParams) -> pg.NodeOutput:
    cand = inputs.get("universe")
    rows = _ar._rows_for_tickers(cand["tickers"]) if cand else _ar._factor_sample_rows(p.sample_size)
    rows = [r for r in rows if r.get("stock_code")]
    specs = [_ar.FactorSpec(**f.model_dump()) for f in p.factors]
    ranked, meta, cov_w = _ar.factor_scores(rows, specs)
    if len(ranked) < 2:
        raise pg.NodeFailure("고른 팩터로 점수를 매길 수 있는 종목이 부족해요(팩터 값 결측) — 팩터나 후보를 바꿔 주세요.")
    scores = {c: round(s, 3) for c, s in ranked}
    view = {"scores": scores, "labels": _ar._labels([c for c, _ in ranked[:30]]), "factors": meta,
            "coverage": {c: round(cov_w.get(c, 0.0) * 100, 0) for c, _ in ranked[:30]},
            "candidates": len(rows), "source": "tickers" if cand else "sample"}
    return pg.NodeOutput(values={"scores": {"scores": scores, "kind": "factor"}}, view=view,
                         tags={"pit": "forward_only", "practice": mock_allowed(), "sources": ["factor_scores"]})


def _explain_factor_scores(view: dict, prov: dict, params: Any) -> dict:
    scores = view.get("scores") or {}
    top = next(iter(scores), None)
    meta = view.get("factors") or []
    miss = [m["label"] for m in meta if not m.get("covered")]
    facts = [f"후보 {view.get('candidates')}종목 중 {len(scores)}종목에 점수를 매겼어요."]
    if top:
        facts.append(f"1위는 {view['labels'].get(top, top)}예요.")
    trust = [_t(CONFIRMED, "팩터마다 표준점수를 방향에 맞춰 더했어요(±3으로 자름).")]
    if miss:
        trust.append(_t(UNKNOWN, f"값이 모자란 팩터는 점수에 넣지 않았어요: {', '.join(miss)}."))
    if view.get("source") == "sample":
        trust.append(_t(ASSUMED, "유니버스 표본에서 골랐어요 — 표본 순서가 고정돼 있지 않아 다시 하면 후보가 달라질 수 있어요."))
    trust.append(_t(UNKNOWN, _TODAY))
    if mock_allowed():
        trust.append(_t(UNKNOWN, _DEV))
    return {"title": f"{len(scores)}종목에 팩터 점수를 매겼어요", "facts": facts, "trust": trust,
            "unmeasured": ["이 점수가 앞으로의 수익을 예측하는지", "팩터끼리 겹치는 정도"]}


# ── 알파 점수 ────────────────────────────────────────────────────────────────

class AlphaParams(BaseModel):
    model_config = _FORBID
    expr: str = Field("zscore(mom_6m) - zscore(vol_60d)", min_length=1, max_length=400, json_schema_extra={
        "x-ui": _ui("알파 식", question="어떤 식으로 점수를 낼까요?", presets=[
            {"label": "추세 − 변동성", "value": "zscore(mom_6m) - zscore(vol_60d)"},
            {"label": "12-1 모멘텀", "value": "zscore(mom_12_1)"},
            {"label": "싸고 잘 버는", "value": "zscore(earnings_yield) + zscore(roe)"},
            {"label": "단기 반전", "value": "zscore(reversal_5d)"}],
            help="알파 실험실과 같은 식이에요. 필드: mom_6m · vol_60d · roe · earnings_yield …")})
    as_of: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui(
        "기준일", "advanced", help="비우면 오늘이에요. 과거 날짜를 넣으면 그날까지의 값으로 계산해요.")})
    alpha_id: str | None = Field(None, max_length=40, json_schema_extra={"x-ui": _ui(
        "등록된 알파", question="등록한 알파를 쓸까요?", widget="pick", source="alphas",
        help="고르면 그 알파의 식을 써요(위 식 칸보다 먼저예요). 알파 서랍에서 등록해요.")})


def registry_expr(alpha_id: str) -> tuple[str, dict]:
    """레지스트리 알파 → `(식, 출처)`. ★없는 id 를 조용히 넘기지 않는다★ (BL2b)."""
    from src.data.alpha_registry import get_alpha
    row = get_alpha(alpha_id)
    if not row or not row.get("expr"):
        raise pg.NodeFailure(f"등록된 알파 {alpha_id} 을(를) 찾지 못했어요 — 알파 서랍에서 확인하거나 비워 두세요.")
    return str(row["expr"]), {"alpha_id": alpha_id, "name": row.get("name"), "version": row.get("version")}


def _alpha_score(inputs: dict, p: AlphaParams) -> pg.NodeOutput:
    from src.engine import alpha_lab
    tickers = list(inputs["universe"]["tickers"])
    expr, source = (registry_expr(p.alpha_id) if p.alpha_id else (p.expr, None))
    out = alpha_lab.score_alpha(expr, tickers, as_of=p.as_of)
    if not out.get("available"):
        raise pg.NodeFailure(f"알파 점수를 내지 못했어요 — {out.get('reason')}")
    ranked = sorted(out["scores"].items(), key=lambda kv: kv[1], reverse=True)
    scores = {c: round(float(s), 4) for c, s in ranked}
    view = {"scores": scores, "labels": _ar._labels([c for c, _ in ranked[:30]]), "expr": out["expr"],
            "as_of_requested": out.get("as_of_requested"), "as_of_effective": out.get("as_of_effective"),
            "coverage": out.get("coverage"), "n_universe": out.get("n_universe"), "expr_source": source}
    return pg.NodeOutput(values={"scores": {"scores": scores, "kind": "alpha", "as_of": out.get("as_of_effective")}},
                         view=view, provenance={"as_of_effective": out.get("as_of_effective")},
                         tags={"pit": "unknown" if p.as_of else "forward_only", "practice": mock_allowed(),
                               "sources": ["alpha_lab"]})


def _explain_alpha(view: dict, prov: dict, params: Any) -> dict:
    n = len(view.get("scores") or {})
    trust = [_t(CONFIRMED, f"{view.get('as_of_effective')}까지의 값으로 계산했어요.")]
    if getattr(params, "as_of", None):
        trust.append(_t(UNKNOWN, "재무 값은 공시 지연을 둔 근사라 그날 실제로 알 수 있었는지는 확인하지 않았어요."))
    else:
        trust.append(_t(UNKNOWN, _TODAY))
    if mock_allowed():
        trust.append(_t(UNKNOWN, _DEV))
    src = view.get("expr_source")
    return {"title": f"{n}종목에 알파 점수를 매겼어요",
            "facts": [f"식: {view.get('expr')}",
                      *([f"등록된 알파 ‘{src.get('name')}’ v{src.get('version')}의 식이에요."] if src else []), f"{view.get('n_universe')}종목 중 {view.get('coverage')}종목이 유한한 점수를 가졌어요."],
            "trust": trust, "unmeasured": ["이 알파의 예측력(IC) — 알파 실험실에서 따로 재요", "거래 비용"]}


# ── 점수로 비중 ──────────────────────────────────────────────────────────────

_WEIGHTING = {"equal": "똑같이", "factor_tilt": "점수만큼 더", "inverse_vol": "덜 흔들리는 쪽에 더",
              "risk_parity": "위험 똑같이", "min_var": "흔들림 최소", "hrp": "비슷한 것끼리 묶어"}
_RETURN_BASED = {"inverse_vol", "risk_parity", "min_var", "hrp"}


class ScoresToWeightsParams(BaseModel):
    model_config = _FORBID
    top_k: int = Field(10, ge=2, le=30, json_schema_extra={"x-ui": _ui(
        "담을 종목 수", question="상위 몇 종목을 담을까요?", unit="개",
        presets=[{"label": "5개", "value": 5}, {"label": "10개", "value": 10}, {"label": "20개", "value": 20}])})
    weighting: Literal[tuple(_WEIGHTING)] = Field("equal", json_schema_extra={"x-ui": _ui(
        "나누는 방식", question="어떻게 나눌까요?", widget="cards", options=_WEIGHTING,
        help="흔들림을 쓰는 방식은 ‘수익률 불러오기’를 이어야 해요.")})


def _scores_to_weights(inputs: dict, p: ScoresToWeightsParams) -> pg.NodeOutput:
    from src.engine.allocation_studio import _cov, _inverse_vol_w, _raw_weights_for_model
    score_map = inputs["scores"]["scores"]
    ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)[: p.top_k]
    codes = [c for c, _ in ranked]
    r = inputs.get("returns")
    sigma = None
    if p.weighting in _RETURN_BASED:
        if r is None:
            raise pg.NodeFailure(f"‘{_WEIGHTING[p.weighting]}’은 흔들림을 써요 — ‘수익률 불러오기’를 이어 주세요 "
                                 "(균등 비중으로 몰래 바꾸지 않아요).")
        missing = [c for c in codes if c not in r["returns"].columns]
        if missing:
            raise pg.NodeFailure(f"수익률에 없는 종목이 있어요: {', '.join(missing)} — 같은 종목의 수익률을 이어 주세요.")
        R = r["returns"][codes].values
        S = _cov(R) * 252.0
        w = _inverse_vol_w(R) if p.weighting == "inverse_vol" else _raw_weights_for_model(p.weighting, R, None, S)
        if w is None or not np.all(np.isfinite(w)):
            raise pg.NodeFailure(f"‘{_WEIGHTING[p.weighting]}’ 계산이 풀리지 않았어요 — 역변동성으로 몰래 바꾸지 않아요.")
        w = np.asarray(w, dtype=float)
        sigma = S
    else:
        pct = _ar._factor_weights(codes, dict(ranked), p.weighting, 252)
        # `/factor-portfolio` 처럼 비중이 0 으로 반올림된 종목은 담지 않는다(틸트의 꼴찌).
        codes = [c for c in codes if pct.get(c, 0.0) > 0]
        w = np.array([pct[c] / 100.0 for c in codes], dtype=float)
        if r is not None and all(c in r["returns"].columns for c in codes):
            sigma = _cov(r["returns"][codes].values) * 252.0
    w = w / w.sum()
    view = {"weights": {c: round(float(x) * 100, 2) for c, x in zip(codes, w)}, "labels": _ar._labels(codes),
            "weighting": p.weighting, "scores": {c: s for c, s in ranked if c in codes}, "has_sigma": sigma is not None}
    return pg.NodeOutput(values={"weights": weights_value(codes, w, sigma_annual=sigma,
                                                          sigma_source="표본(수익률 노드)" if sigma is not None else None)},
                         view=view)


def _explain_scores_to_weights(view: dict, prov: dict, params: Any) -> dict:
    w = view.get("weights") or {}
    top = max(w, key=lambda k: w[k]) if w else None
    trust = [_t(CONFIRMED, f"점수 상위 {len(w)}종목을 ‘{_WEIGHTING.get(view.get('weighting'), view.get('weighting'))}’ 방식으로 나눴어요.")]
    if not view.get("has_sigma"):
        trust.append(_t(UNKNOWN, "공분산이 없어 ‘흔들림 나눠 보기’는 이 비중을 계산하지 못해요 — 수익률을 이어 주세요."))
    return {"title": f"점수로 {len(w)}종목의 비중을 정했어요",
            "headline": ({"label": f"가장 큰 비중 · {view['labels'].get(top, top)}", "value": w[top], "unit": "%",
                          "text": _pct(w[top])} if top else None),
            "trust": trust, "unmeasured": ["이 비중의 과거 성과(규칙이 아니라 한 시점의 비중이라 정책 백테스트가 없어요)"]}


# ── 중립화 ───────────────────────────────────────────────────────────────────

class NeutralizeParams(BaseModel):
    model_config = _FORBID
    mode: Literal["beta", "sector", "both"] = Field("beta", json_schema_extra={"x-ui": _ui(
        "무엇을 없앨까요", question="무엇에 대한 치우침을 없앨까요?", widget="cards",
        options={"beta": "시장 민감도(베타)", "sector": "업종 쏠림", "both": "둘 다"})})
    target_beta: float = Field(0.0, ge=-2.0, le=2.0, json_schema_extra={"x-ui": _ui("목표 베타", "advanced")})
    dollar_neutral: bool = Field(False, json_schema_extra={"x-ui": _ui("롱·숏 금액 맞추기", "advanced")})


def _neutralize(inputs: dict, p: NeutralizeParams) -> pg.NodeOutput:
    from src.engine.neutralize import neutralize_portfolio
    w = inputs["weights"]
    pct = {n: float(x) * 100.0 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}
    out = neutralize_portfolio(pct, mode=p.mode, target_beta=p.target_beta, dollar_neutral=p.dollar_neutral)
    errs = [str(out[k].get("message")) for k in ("beta", "sector") if isinstance(out.get(k), dict) and out[k].get("error")]
    if errs:
        raise pg.NodeFailure("중립화를 하지 못했어요 — " + " / ".join(errs))
    after = out["weights"]
    names = list(after)
    arr = np.array([after[n] / 100.0 for n in names], dtype=float)
    view = {"before": {k: round(v, 2) for k, v in pct.items()}, "after": {k: round(v, 2) for k, v in after.items()},
            "labels": _ar._labels(names), "result": out}
    return pg.NodeOutput(values={"weights": weights_value(names, arr, neutralized=True)}, view=view,
                         tags={"practice": mock_allowed(), "sources": ["neutralize"]})


def _explain_neutralize(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    b = r.get("beta") or {}
    facts = []
    if "beta_before" in b or "portfolio_beta_before" in b:
        facts.append(f"베타 {b.get('beta_before', b.get('portfolio_beta_before'))} → {b.get('beta_after', b.get('portfolio_beta_after'))}")
    shorts = [k for k, v in (view.get("after") or {}).items() if v < 0]
    if shorts:
        facts.append(f"숏 포지션이 생긴 종목 {len(shorts)}개가 있어요.")
    return {"title": "치우침을 없앤 비중을 만들었어요", "facts": facts,
            "trust": [_t(ASSUMED, "과거 베타·업종 분류로 맞췄어요 — 앞으로도 그 베타일지는 몰라요."),
                      _t(UNKNOWN, "중립화한 비중은 최적화 제약이 아니라 사후 변환이라 실행 목표로는 쓸 수 없어요.")],
            "unmeasured": ["중립화 뒤의 기대 수익", "숏 비용"]}


# ── 슬리브 합치기 ────────────────────────────────────────────────────────────

_SLEEVE_METHODS = {"risk_parity": "위험 똑같이", "equal": "똑같이", "inverse_vol": "덜 흔들리는 쪽에 더",
                   "min_var": "흔들림 최소", "hrp": "비슷한 것끼리 묶어"}


class SleeveParams(BaseModel):
    model_config = _FORBID
    method: Literal[tuple(_SLEEVE_METHODS)] = Field("risk_parity", json_schema_extra={"x-ui": _ui(
        "합치는 방식", question="묶음끼리 어떻게 나눌까요?", widget="cards", options=_SLEEVE_METHODS)})


def _sleeve_combine(inputs: dict, p: SleeveParams) -> pg.NodeOutput:
    from src.engine.sleeve_combine import combine_sleeves
    sleeves = []
    for port in ("a", "b", "c"):
        w = inputs.get(port)
        if w is None:
            continue
        sleeves.append({"name": f"묶음 {port.upper()}",
                        "weights": {n: float(x) * 100.0 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}})
    out = combine_sleeves(sleeves, method=p.method)
    if out.get("error"):
        raise pg.NodeFailure(str(out.get("message")))
    cw = out["combined_weights_pct"]
    names = list(cw)
    arr = np.array([cw[n] / 100.0 for n in names], dtype=float)
    view = {"result": out, "labels": _ar._labels(names)}
    return pg.NodeOutput(values={"weights": weights_value(names, arr)}, view=view,
                         tags={"practice": mock_allowed(), "sources": ["sleeve_combine"]})


def _explain_sleeves(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    alloc = r.get("sleeve_allocation") or {}
    facts = [f"{k}: {_pct(float(v))}" for k, v in alloc.items()]
    trust = [_t(CONFIRMED, f"{r.get('n_sleeves')}개 묶음의 수익 흐름으로 묶음 비중을 정하고 종목 비중을 합쳤어요.")]
    if r.get("method") in ("min_var", "hrp"):
        trust.append(_t(UNKNOWN, "이 방식은 계산이 안 풀리면 엔진이 역변동성으로 바꿔요 — 이 결과가 그 경우인지는 표시되지 않아요."))
    trust.append(_t(ASSUMED, "묶음 수익은 각 묶음의 지금 비중을 과거에 고정해 만든 흐름이에요."))
    return {"title": f"{r.get('n_sleeves')}개 묶음을 {r.get('n_stocks')}종목 비중으로 합쳤어요", "facts": facts,
            "trust": trust, "unmeasured": ["묶음 사이 상관이 앞으로 유지될지"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("screener", "스크리너", stage="signal", plain_label="조건으로 종목 거르기",
                    plain_description="재무·시세 조건으로 후보를 걸러 종목 목록을 만들어요.",
                    inputs=(P("universe", "Universe", required=False),), outputs=(P("universe", "Universe"),),
                    run=_screener, params_model=ScreenerParams, explain=_explain_screener, category="신호",
                    description="유동성 게이트 → 필터 → 정렬(/screener/run-advanced 와 같다)."),
        pg.NodeSpec("factor_scores", "팩터 점수", stage="signal", plain_label="팩터로 점수 매기기",
                    plain_description="가치·수익성 같은 성격에 점수를 매겨요.",
                    inputs=(P("universe", "Universe", required=False),), outputs=(P("scores", "Scores"),),
                    run=_factor_scores, params_model=FactorScoreParams, explain=_explain_factor_scores, category="신호",
                    description="방향 인지 z-score 가중합(/factor-portfolio 의 점수와 같다)."),
        pg.NodeSpec("alpha_score", "알파 점수", stage="signal", plain_label="알파 식으로 점수 매기기",
                    plain_description="알파 실험실의 식으로 오늘(또는 기준일)의 점수를 내요.",
                    inputs=(P("universe", "Universe"),), outputs=(P("scores", "Scores"),),
                    run=_alpha_score, params_model=AlphaParams, explain=_explain_alpha, category="신호",
                    description="score_alpha — 라이브 크로스섹션 점수."),
        pg.NodeSpec("scores_to_weights", "점수 → 비중", stage="build", plain_label="점수로 비중 정하기",
                    plain_description="점수 상위 종목을 골라 비중을 나눠요.",
                    inputs=(P("scores", "Scores"), P("returns", "Returns", required=False)),
                    outputs=(P("weights", "Weights"),), run=_scores_to_weights, params_model=ScoresToWeightsParams,
                    explain=_explain_scores_to_weights, category="배분",
                    description="상위 K → 균등·틸트·역변동성·위험균등·최소분산·HRP(폴백 없음)."),
        pg.NodeSpec("neutralize", "중립화", stage="build", plain_label="치우침 없애기",
                    plain_description="시장 민감도나 업종 쏠림을 없앤 비중을 만들어요.",
                    inputs=(P("weights", "Weights"),), outputs=(P("weights", "Weights"),),
                    run=_neutralize, params_model=NeutralizeParams, explain=_explain_neutralize, category="배분",
                    description="베타·섹터 중립화(/neutralize 와 같다). 결과는 연구용 — 실행 목표가 아니다."),
        pg.NodeSpec("sleeve_combine", "슬리브 결합", stage="build", plain_label="묶음 합치기",
                    plain_description="비중 묶음 2~3개를 위험 기준으로 하나로 합쳐요.",
                    inputs=(P("a", "Weights"), P("b", "Weights"), P("c", "Weights", required=False)),
                    outputs=(P("weights", "Weights"),), run=_sleeve_combine, params_model=SleeveParams,
                    explain=_explain_sleeves, category="배분",
                    description="2단계 슬리브 결합(/combine-sleeves 와 같다)."),
    ):
        registry.register(spec)
