"""AAS 그래프 — 마법사에만 있던 계산을 노드로 (BL2b) · ★라우트·엔진 함수를 그대로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL2b. 마법사 제거(BL4)의 전제 — 마법사 화면에서만 볼 수 있던 계산을 캔버스로 옮긴다.
같은 수인지는 `tests/test_allocation_graph_bl2b.py` 골든이 라우트와 대조한다.

| 노드 | 부르는 것 |
|---|---|
| 효율적 프런티어 | `PortfolioAnalyzer.efficient_frontier` + MC 구름 — `/analyze` 3·4 단계와 같은 호출 |
| 국면 앙상블 · 국면 설명 | `regime_ensemble` · `regime_transitions`+`regime_drivers` — `/macro/regime-*` 와 같은 함수 |
| 세 갈래 시나리오 · 직접 만든 시나리오 | `/scenario-three-way` · `/scenario-run` 라우트 함수 |
| 전략 건강 · 묶음 분석 | `/strategy-health` 라우트 함수 · `sleeve_analytics` |
| 알파 검증 · 알파 포트폴리오 | `/alpha-lab/validate` · `/alpha-lab/portfolio` 라우트 함수, ★`record_run=False` 명시★ |

## 매크로 데이터 경로 (사용자 결정 — 저장된 관측 + mock 연습용)
운영(`mock_allowed()` 거짓)은 `MacroCollector.collect_all(store_only=True)` — 저장된 관측만 읽는다(외부 호출 0 · 캐시 0 ·
적재 0). 저장소를 못 읽거나 관측이 없으면 사유 있는 실패다(빈 계열로 계산하지 않는다). 개발(mock)은 `/macro` 라우트와
**같은** 수집기 호출이고 계보에 연습용을 단다. 라우트는 운영에서 계산할 때마다 BOK·FRED 를 부르고 관측을 적재한다 —
그 일은 매크로 화면의 몫이고, 캔버스 계산이 하지 않는다.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _pct, _signed_pct, _t
from src.api.allocation_graph_nodes import _FORBID, _labels, _ui, weights_value
from src.api.allocation_graph_nodes_check import holdings_pct
from src.api.allocation_graph_nodes_signal import registry_expr
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine import portfolio_graph as pg
from src.engine.kr_scenario_pack import FACTORS
from src.engine.scenario_packs import PACKS

logger = logging.getLogger(__name__)

P = pg.Port

_MARKETS = {"kr": "한국", "us": "미국"}
_UNIVERSES = {"kospi50": "KOSPI 50", "kospi200": "KOSPI 200", "kosdaq150": "KOSDAQ 150"}
_DEV_MACRO = "개발 모드라 매크로 지표가 합성(연습용)이에요 — 실제 국면을 말해 주지 않아요."
_STORE_NOTE = "저장된 관측만 읽었어요(이 계산은 외부를 호출하지 않아요) — 공표 시각을 모르는 관측이라 지금 시점 전용이에요."


def _detail(e: HTTPException) -> str:
    return str(e.detail)


# ── 매크로 데이터 경로 ────────────────────────────────────────────────────────

def macro_series_map() -> tuple[dict, dict]:
    """`(series_map, 계보 태그)`. 운영은 저장소만, 개발은 `/macro` 라우트와 같은 수집기(연습용)."""
    if mock_allowed():
        from src.api.macro_routes import _get_analyzer
        snap = _get_analyzer().collector.collect_all(use_cache=True)
        return (getattr(snap, "series", None) or {}), {
            "pit": "forward_only", "practice": True, "sources": ["macro_collector:mock"]}
    from src.data.macro_observation_store import coverage
    cov = coverage()
    if not cov.get("available"):
        raise pg.NodeFailure(f"매크로 관측 저장소를 읽을 수 없어요 — {cov.get('reason') or '사유 미상'}. "
                             "관측이 없는 것과 달라요.")
    if not cov.get("rows"):
        raise pg.NodeFailure("저장된 매크로 관측이 없어요 — 매크로 화면을 한 번 열어 수집하면 저장돼요"
                             "(캔버스 계산은 외부를 호출하지 않아요).")
    from src.services.macro_collector import MacroCollector
    snap = MacroCollector().collect_all(use_cache=False, store_only=True)
    series = snap.series or {}
    if not any(getattr(s, "values", None) for s in series.values()):
        raise pg.NodeFailure("저장된 매크로 관측으로 만든 지표가 하나도 없어요 — 매크로 화면에서 먼저 수집해 주세요.")
    return series, {"pit": "forward_only", "practice": False, "sources": ["macro_observation_store"]}


def _macro_trust(prov: dict) -> list[dict]:
    return [_t(UNKNOWN, _DEV_MACRO)] if prov.get("practice") else [_t(UNKNOWN, _STORE_NOTE)]


# ── 효율적 프런티어 ───────────────────────────────────────────────────────────

class FrontierParams(BaseModel):
    model_config = _FORBID
    n_points: int = Field(30, ge=10, le=60, json_schema_extra={"x-ui": _ui(
        "곡선 점 수", question="곡선을 몇 점으로 그릴까요?", unit="점",
        presets=[{"label": "20점", "value": 20}, {"label": "30점", "value": 30}, {"label": "60점", "value": 60}],
        help="점이 많을수록 곡선이 매끄럽고 계산이 느려져요.")})


def _frontier(inputs: dict, p: FrontierParams) -> pg.NodeOutput:
    from src.api.allocation_routes import _RF
    from src.kis_portfolio_analyzer import PortfolioAnalyzer
    returns = inputs["returns"]["returns"]
    an = PortfolioAnalyzer(returns=returns, weights=None)
    try:
        ef = an.efficient_frontier(n_points=p.n_points)
    except Exception as e:  # noqa: BLE001 — 풀이 실패는 사유와 함께 노드 실패
        raise pg.NodeFailure(f"프런티어를 풀지 못했어요 — {e}") from e
    curve = ef.round(4).to_dict("records") if ef is not None and not ef.empty else []
    if not curve:
        raise pg.NodeFailure("프런티어의 점을 하나도 풀지 못했어요 — 종목이 너무 적거나 수익률이 비슷해요.")
    cloud, cloud_reason = None, None
    try:
        from src.models.portfolio_optimizer import efficient_frontier as mc_frontier
        mc = mc_frontier(returns, n_portfolios=1500, risk_free_rate=_RF)
        f = mc.get("frontier", {}) if isinstance(mc, dict) else {}
        cloud = {"returns": f.get("returns", []), "volatilities": f.get("volatilities", []),
                 "sharpes": f.get("sharpe_ratios", [])}
    except Exception as e:  # noqa: BLE001 — 구름은 보조 — 없으면 없다고 적는다
        cloud_reason = str(e)
    point = None
    w = inputs.get("weights")
    if w is not None:
        names = list(w["names"])
        missing = [n for n in names if n not in returns.columns]
        if missing:
            raise pg.NodeFailure(f"비중의 종목 {', '.join(missing)} 이(가) 수익률에 없어요 — 같은 수익률에서 나온 비중을 이어 주세요.")
        arr = np.zeros(len(returns.columns))
        for n, x in zip(names, np.asarray(w["weights"], dtype=float)):
            arr[list(returns.columns).index(n)] = x
        mu = an.returns.mean().values * an.trading_days
        cov = an.returns.cov().values * an.trading_days
        point = {"return": round(float(arr @ mu) * 100, 3), "volatility": round(float(np.sqrt(arr @ cov @ arr)) * 100, 3)}
    view = {"curve": curve, "cloud": cloud, "cloud_reason": cloud_reason, "point": point,
            "names": list(returns.columns), "labels": _labels(list(returns.columns))}
    return pg.NodeOutput(values={}, view=view)


def _explain_frontier(view: dict, prov: dict, params: Any) -> dict:
    curve = view.get("curve") or []
    best = max(curve, key=lambda r: float(r.get("sharpe") or 0)) if curve else None
    facts = [f"곡선 {len(curve)}점 · 흔들림 {_pct(float(curve[0]['volatility']))} ~ {_pct(float(curve[-1]['volatility']))}."] if curve else []
    if best:
        facts.append(f"흔들림 대비 수익이 가장 좋은 점: 연 {_pct(float(best['return']))} · 흔들림 {_pct(float(best['volatility']))}.")
    pt = view.get("point")
    if pt:
        facts.append(f"이은 비중은 연 {_pct(pt['return'])} · 흔들림 {_pct(pt['volatility'])} 자리에 있어요.")
    trust = [_t(CONFIRMED, "불러온 기간의 평균 수익률과 공분산으로 그렸어요."),
             _t(ASSUMED, "과거 평균이 앞으로도 같다고 가정한 곡선이에요 — 예측이 아니에요.")]
    if view.get("cloud") is None:
        trust.append(_t(UNKNOWN, f"무작위 조합 구름은 그리지 못했어요 — {view.get('cloud_reason') or '사유 미상'}."))
    return {"title": "같은 흔들림에서 가장 높은 수익의 경계를 그렸어요",
            "headline": ({"label": "가장 좋은 점의 흔들림", "value": best["volatility"], "unit": "%",
                          "text": _pct(float(best["volatility"]))} if best else None),
            "facts": facts, "trust": trust,
            "unmeasured": ["추정 오차(기대수익이 조금 틀려도 곡선이 크게 움직여요)", "거래 비용", "앞으로의 수익"]}


# ── 국면 앙상블 · 국면 설명 ───────────────────────────────────────────────────

class EnsembleParams(BaseModel):
    model_config = _FORBID
    market: Literal["kr", "us"] = Field("kr", json_schema_extra={"x-ui": _ui(
        "시장", question="어느 시장의 국면을 볼까요?", widget="cards", options=_MARKETS)})
    months: int = Field(60, ge=24, le=240, json_schema_extra={"x-ui": _ui(
        "기간", "advanced", unit="개월", presets=[{"label": "3년", "value": 36}, {"label": "5년", "value": 60}],
        help="상태 전환·군집 모형이 배우는 기간이에요. 짧으면 모형이 서지 않을 수 있어요.")})


class ExplainParams(EnsembleParams):
    forecast_k: int = Field(3, ge=1, le=12, json_schema_extra={"x-ui": _ui(
        "몇 달 뒤까지", "advanced", unit="개월", help="전환 위험을 몇 달 뒤까지 볼지예요.")})


def _regime_ensemble(inputs: dict, p: EnsembleParams) -> pg.NodeOutput:
    from src.engine.regime_ensemble import regime_ensemble
    series, tags = macro_series_map()
    out = regime_ensemble(series, market=p.market, months=p.months)
    return pg.NodeOutput(values={}, view={"result": out, "market": p.market}, tags=tags,
                         provenance={"practice": tags["practice"]})


def _explain_ensemble(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    tools = r.get("tools") or {}
    names = {"axis": "성장·물가 축", "markov": "상태 전환 모형", "cluster": "군집 모형"}
    picks = (r.get("agreement") or {}).get("picks") or {}
    facts = [f"{names.get(k, k)}: {v}" for k, v in picks.items()]
    trust = [_t(UNKNOWN, f"{names.get(k, k)}는 계산하지 못했어요 — {t.get('reason') or '사유 미상'}")
             for k, t in tools.items() if not t.get("available")]
    trust += _macro_trust(prov)
    agree = (r.get("agreement") or {}).get("unanimous")
    title = ("세 방법이 같은 국면을 가리켜요" if agree else
             "방법마다 다른 국면을 가리켜요" if picks else "국면을 판정할 수 있는 방법이 없었어요")
    return {"title": title, "facts": facts + ["세 방법을 평균 내지 않아요 — 갈리는 것 자체가 정보예요."],
            "trust": trust, "unmeasured": ["국면 판정이 앞으로의 수익을 맞히는지(예측력)"]}


def _regime_explain(inputs: dict, p: ExplainParams) -> pg.NodeOutput:
    from src.engine.regime_drivers import regime_drivers
    from src.engine.regime_transitions import regime_transitions
    series, tags = macro_series_map()
    tr = regime_transitions(series, market=p.market, months=p.months, forecast_k=p.forecast_k)
    target = tr.get("current") if tr.get("available") else None
    dr = regime_drivers(series, market=p.market, regime=target)
    out = {"market": p.market, "transitions": tr, "drivers": dr, "span": tr.get("span")}
    return pg.NodeOutput(values={}, view={"result": out}, tags=tags, provenance={"practice": tags["practice"]})


def _explain_regime_explain(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    tr, span = r.get("transitions") or {}, r.get("span") or {}
    facts = []
    if tr.get("available"):
        facts.append(f"지금 국면: {tr.get('current')}")
    if span:
        n, asked = span.get("n_months"), getattr(params, "months", None)
        facts.append(f"분류할 수 있었던 기간: {n}개월" + (f" (요청 {asked}개월보다 짧아요)" if span.get("truncated") else ""))
    trust = [] if tr.get("available") else [_t(UNKNOWN, f"전환 위험을 계산하지 못했어요 — {tr.get('reason') or '사유 미상'}")]
    trust += _macro_trust(prov)
    return {"title": "지금 국면이 왜 나왔고 얼마나 이어질지 봤어요" if tr.get("available") else "국면 경로를 만들지 못했어요",
            "facts": facts, "trust": trust,
            "unmeasured": ["전환 확률이 실제 전환을 맞히는지", "공표 지연·개정(빈티지)"]}


# ── 세 갈래 시나리오 ──────────────────────────────────────────────────────────

_SCENARIOS = tuple(PACKS)


class ThreeWayParams(BaseModel):
    model_config = _FORBID
    scenario: Literal[_SCENARIOS] = Field("rate_hike_200bp", json_schema_extra={"x-ui": _ui(
        "시나리오", question="어떤 상황에서 비교할까요?", widget="cards",
        options={k: pk.label for k, pk in PACKS.items()})})
    severity: float = Field(1.0, ge=0.25, le=3.0, json_schema_extra={"x-ui": _ui(
        "강도", "advanced", widget="slider", ends=["약하게", "세게"], help="가정 충격에만 곱해요.")})


def _three_way(inputs: dict, p: ThreeWayParams) -> pg.NodeOutput:
    from src.api.scenario_routes import ScenarioThreeWayRequest, scenario_three_way
    sig = inputs["signal"]
    reg = inputs.get("regime")
    try:
        out = scenario_three_way(ScenarioThreeWayRequest(
            holdings=holdings_pct(inputs["weights"]), pack_id=p.scenario, severity=p.severity,
            market=sig["market"], combination=sig["combination"], k=sig["k"], rules=list(sig["specs"]),
            regime_snapshot_id=(reg or {}).get("snapshot_id"), as_of=sig.get("as_of")))
    except HTTPException as e:
        raise pg.NodeFailure(f"세 갈래 비교를 하지 못했어요 — {_detail(e)}") from e
    return pg.NodeOutput(values={}, view={"result": out}, tags={"practice": mock_allowed()})


_LEG = {"baseline": "그대로 두기", "timing_only": "타이밍만", "timing_macro": "타이밍 + 국면"}


def _explain_three_way(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    legs = r.get("legs") or {}
    facts = []
    for k, leg in legs.items():
        loss = leg.get("shock_pct")                       # 다리별 합성 손실(노출 × 충격) — 판정 못 한 다리엔 없다
        facts.append(f"{_LEG.get(k, k)}: 노출 {_pct(float(leg.get('exposure') or 0) * 100)}"
                     + (f" · 손실 {_signed_pct(float(loss))}" if loss is not None else " · 손실 미계산"))
    trust = [_t(ASSUMED, str(r.get("composition_note") or "노출을 시나리오 손실에 곱했어요."))]
    if not r.get("composed"):
        trust.append(_t(UNKNOWN, "충격을 구하지 못해 갈래별 손실을 적지 않았어요."))
    if r.get("overlay") is None:
        trust.append(_t(UNKNOWN, "경기 국면을 잇지 않아 ‘타이밍 + 국면’ 갈래는 판정하지 않았어요."))
    return {"title": f"‘{(r.get('scenario') or {}).get('label')}’에서 세 갈래를 비교했어요",
            "facts": facts, "trust": trust, "unmeasured": ["시나리오가 실제로 일어날 확률", "갈래 사이의 거래 비용"]}


# ── 직접 만든 시나리오 ────────────────────────────────────────────────────────

_BASIC_FACTORS = ("mkt_beta", "momentum", "value")


def _factor_field(fid: str) -> Any:
    tier = "basic" if fid in _BASIC_FACTORS else "advanced"
    return (float, Field(0.0, ge=-100, le=100, json_schema_extra={"x-ui": _ui(
        FACTORS[fid], tier, unit="%", presets=[{"label": "−5%", "value": -5.0}, {"label": "0", "value": 0.0},
                                               {"label": "+5%", "value": 5.0}],
        help="이 성격이 1σ 강한 종목에 더하는 충격이에요(음수 = 악재).")}))


class _CustomBase(BaseModel):
    model_config = _FORBID
    label: str = Field("사용자 정의 시나리오", max_length=200, json_schema_extra={"x-ui": _ui(
        "이름", "advanced", widget="text")})
    market_shock: float = Field(-5.0, ge=-90, le=90, json_schema_extra={"x-ui": _ui(
        "시장 전체 충격", question="시장 전체가 얼마나 움직인다고 볼까요?", unit="%",
        presets=[{"label": "−10%", "value": -10.0}, {"label": "−5%", "value": -5.0}, {"label": "+5%", "value": 5.0}])})
    pack_id: str | None = Field(None, max_length=80, json_schema_extra={"x-ui": _ui(
        "저장된 시나리오", "advanced", widget="pick", source="scenario_packs",
        help="고르면 아래 충격 대신 저장된 시나리오를 써요.")})


from pydantic import create_model  # noqa: E402

CustomParams = create_model("CustomScenarioParams", __base__=_CustomBase,
                            **{fid: _factor_field(fid) for fid in FACTORS})


def _custom_scenario(inputs: dict, p: Any) -> pg.NodeOutput:
    from src.api.scenario_routes import InlinePack, ScenarioRunRequest, scenario_run
    pct = holdings_pct(inputs["weights"])
    if p.pack_id:
        req = ScenarioRunRequest(holdings=pct, pack_id=p.pack_id)
    else:
        factors = {fid: float(getattr(p, fid)) for fid in FACTORS if float(getattr(p, fid)) != 0.0}
        if not factors:
            raise pg.NodeFailure("팩터 충격을 하나 이상 정해 주세요 — 시장 충격만으로는 시나리오를 만들지 않아요"
                                 "(0 인 팩터를 지어 넣지 않아요).")
        req = ScenarioRunRequest(holdings=pct, pack=InlinePack(label=p.label, market=p.market_shock, factors=factors))
    try:
        out = scenario_run(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"시나리오를 계산하지 못했어요 — {_detail(e)}") from e
    view = {"result": out, "pack": out.get("pack")}
    return pg.NodeOutput(values={"stress": view}, view=view, tags={"practice": mock_allowed()},
                         provenance={"model_type": out.get("model_type")})


def _explain_custom(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    shock = r.get("shock_pct")
    return {"title": f"‘{(r.get('pack') or {}).get('label')}’에 이 비중을 넣어 봤어요",
            "headline": ({"label": "예상 충격", "value": shock, "unit": "%", "text": _signed_pct(float(shock))}
                         if shock is not None else None),
            "facts": [f"측정 방식: {r.get('shock_basis') or '미상'}"],
            "trust": [_t(ASSUMED, "직접 정한 충격이에요 — 일어난 일이 아니라 가정이에요(가정 모델)."),
                      *([_t(UNKNOWN, "개발 모드라 종목의 팩터 값이 합성일 수 있어요.")] if mock_allowed() else [])],
            "unmeasured": ["이 충격이 일어날 확률", "충격 뒤 회복"]}


# ── 전략 건강 ────────────────────────────────────────────────────────────────

def _strategy_health(inputs: dict, p: Any) -> pg.NodeOutput:
    from src.api.attribution_routes import get_strategy_health
    try:
        out = get_strategy_health()
    except HTTPException as e:
        raise pg.NodeFailure(f"전략 건강을 읽지 못했어요 — {_detail(e)}") from e
    return pg.NodeOutput(values={}, view={"result": out})


_HEALTH_KO = {"healthy": "건강", "watch": "지켜보기", "de_risk": "줄이기", "paused": "멈춤", "retired": "폐기"}


def _explain_health(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    counts = r.get("counts") or {}
    n = int(r.get("n") or len(r.get("items") or []))
    facts = [f"{_HEALTH_KO.get(k, k)} {v}개" for k, v in counts.items() if v]
    unmeasured = sorted({s.get("label") for it in r.get("items") or [] for s in it.get("signals") or []
                         if s.get("status") == "unmeasured"} - {None})
    return {"title": f"등록된 알파 {n}개의 상태를 봤어요" if n else "등록된 알파가 없어요 — 알파 서랍에서 등록해요",
            "facts": facts, "trust": [_t(CONFIRMED, str(r.get("note") or "측정 가능한 신호로만 판정했어요."))],
            "unmeasured": unmeasured or ["실거래 성과"]}


# ── 묶음 분석 ────────────────────────────────────────────────────────────────

def _sleeve_analytics(inputs: dict, p: Any) -> pg.NodeOutput:
    from src.engine.sleeve_combine import sleeve_analytics
    sleeves = [{"name": f"묶음 {i + 1}", "weights": holdings_pct(inputs[k])}
               for i, k in enumerate(("a", "b", "c", "d")) if inputs.get(k) is not None]
    out = sleeve_analytics(sleeves)
    if isinstance(out, dict) and out.get("available") is False:
        raise pg.NodeFailure(f"묶음 사이를 재지 못했어요 — {out.get('reason') or '사유 미상'}")
    return pg.NodeOutput(values={}, view={"result": out, "n": len(sleeves)}, tags={"practice": mock_allowed()})


def _explain_sleeves(view: dict, prov: dict, params: Any) -> dict:
    return {"title": f"묶음 {view.get('n')}개가 얼마나 겹치는지 봤어요",
            "trust": [_t(CONFIRMED, "각 묶음의 과거 수익률로 상관·군집·위험 기여를 쟀어요."),
                      _t(ASSUMED, "과거 상관이 앞으로도 같다고 본 결과예요.")],
            "unmeasured": ["위기 때 상관(보통 더 높아져요 — ‘상관이 치솟으면’ 노드로 봐요)"]}


# ── 알파 검증 · 알파 포트폴리오 ───────────────────────────────────────────────

class AlphaValidateParams(BaseModel):
    model_config = _FORBID
    expr: str = Field("zscore(mom_6m) - zscore(vol_60d)", min_length=1, max_length=1000, json_schema_extra={
        "x-ui": _ui("알파 식", question="어떤 식을 검증할까요?", help="등록된 알파를 고르면 그 식을 써요.")})
    alpha_id: str | None = Field(None, max_length=40, json_schema_extra={"x-ui": _ui(
        "등록된 알파", question="등록한 알파를 검증할까요?", widget="pick", source="alphas",
        help="고르면 그 알파의 식을 쓰고, 검증 기록을 그 알파에 붙일 수 있어요.")})
    universe: Literal[tuple(_UNIVERSES)] = Field("kospi50", json_schema_extra={"x-ui": _ui(
        "종목 범위", "advanced", widget="cards", options=_UNIVERSES)})
    months: int = Field(24, ge=6, le=60, json_schema_extra={"x-ui": _ui(
        "기간", "advanced", unit="개월", presets=[{"label": "1년", "value": 12}, {"label": "2년", "value": 24}])})
    quantiles: int = Field(5, ge=3, le=10, json_schema_extra={"x-ui": _ui("분위 수", "advanced", unit="개")})


def _validate_request(p: AlphaValidateParams, *, record: bool) -> Any:
    from src.api.alpha_routes import ValidateRequest
    expr = registry_expr(p.alpha_id)[0] if p.alpha_id else p.expr
    return ValidateRequest(expr=expr, universe=p.universe, months=p.months, quantiles=p.quantiles,
                           alpha_id=p.alpha_id, record_run=record)


def _alpha_validate(inputs: dict, p: AlphaValidateParams) -> pg.NodeOutput:
    from src.api import alpha_routes as _al
    src = registry_expr(p.alpha_id)[1] if p.alpha_id else None
    try:
        out = _al.alpha_validate(_validate_request(p, record=False))          # ★계산은 기록하지 않는다★
    except HTTPException as e:
        raise pg.NodeFailure(f"알파를 검증하지 못했어요 — {_detail(e)}") from e
    if out.get("error"):
        raise pg.NodeFailure(f"알파를 검증하지 못했어요 — {out.get('message') or '사유 미상'}")
    # ★롱숏 수익·샤프·낙폭은 성과 숫자다★ — 무슨 성과인지(과거 시뮬레이션 · 비용 미반영) 라벨을 단다.
    label = {**backtest_label(is_mock_data=mock_allowed()).to_dict(),
             "kind_reason": "점수 상·하위 분위를 과거에 사고판 시뮬레이션이에요(거래 비용 미반영)."}
    return pg.NodeOutput(values={}, view={"result": out, "expr_source": src},
                         provenance={"perf_label": label},
                         tags={"practice": mock_allowed(), "sources": ["alpha_lab"]})


def _save_alpha_validation(values: dict, view: dict, params: AlphaValidateParams) -> dict:
    """알파 검증 → **검증 기록 남기기** — 라우트가 기록하고, 등록된 알파면 그 알파에 붙인다(알파 서랍의 '검증 단계' 요건).
    요청은 미리보기와 `record_run` 만 다르다. 그래도 기록된 결과가 미리보기와 다르면 그렇다고 말한다."""
    from src.api import alpha_routes as _al
    try:
        out = _al.alpha_validate(_validate_request(params, record=True))
    except HTTPException as e:
        raise pg.NodeFailure(_detail(e)) from e
    rid = out.get("run_id")
    if not rid:
        raise pg.NodeFailure("DB 를 쓸 수 없어 검증 기록을 남기지 못했어요.")
    if out.get("ic") != (view.get("result") or {}).get("ic"):
        raise pg.NodeFailure(f"기록한 검증({rid})이 미리보기와 달라요 — 기록함에서 확인해 주세요.")
    tail = " · 알파에 붙였어요" if params.alpha_id else ""
    return {"saved_id": rid, "text": f"검증 기록으로 남겼어요 · {rid}{tail}"}


def _explain_validate(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    ic = (r.get("ic") or {})
    agg = ic.get("agg") or ic if isinstance(ic, dict) else {}
    mean, icir = agg.get("mean"), agg.get("icir")
    facts = [f"기간 {r.get('period_start')} ~ {r.get('period_end')} · {r.get('n_periods')}번 잰 결과예요."]
    if mean is not None:
        facts.append(f"평균 IC {float(mean):+.3f}" + (f" · ICIR {float(icir):+.2f}" if icir is not None else ""))
    src = view.get("expr_source")
    if src:
        facts.append(f"등록된 알파 ‘{src.get('name')}’ v{src.get('version')}의 식이에요.")
    trust = [_t(CONFIRMED, "과거 표본에서 점수 순위와 다음 달 수익의 순위 상관(IC)을 쟀어요."),
             _t(UNKNOWN, "거래 비용·슬리피지를 빼지 않았어요.")]
    if mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 가격·재무 값이 합성일 수 있어요 — 예측력을 말해 주지 않아요."))
    return {"title": "알파 식의 과거 순위 상관을 쟀어요",
            "headline": ({"label": "평균 IC", "value": mean, "text": f"{float(mean):+.3f}"} if mean is not None else None),
            "facts": facts, "trust": trust, "unmeasured": ["표본 밖 예측력", "거래 비용을 뺀 성과"]}


_WEIGHTINGS = {"equal": "똑같이", "factor_tilt": "점수만큼 더", "inverse_vol": "덜 흔들리는 쪽에 더",
               "risk_parity": "위험을 똑같이", "min_var": "흔들림 최소", "hrp": "계층 위험 균형"}


class AlphaPortfolioParams(BaseModel):
    model_config = _FORBID
    alpha_ids: list[str] = Field(..., min_length=1, max_length=8, json_schema_extra={"x-ui": _ui(
        "알파", question="어떤 알파들을 합칠까요?", widget="pick", source="alphas",
        help="승인된 알파만 쓸 수 있어요 — 나머지는 서버가 사유와 함께 막아요.")})
    universe: Literal[tuple(_UNIVERSES)] = Field("kospi200", json_schema_extra={"x-ui": _ui(
        "종목 범위", "advanced", widget="cards", options=_UNIVERSES)})
    top_k: int = Field(10, ge=2, le=30, json_schema_extra={"x-ui": _ui(
        "담을 종목 수", "advanced", unit="개", presets=[{"label": "10개", "value": 10}, {"label": "20개", "value": 20}])})
    weighting: Literal[tuple(_WEIGHTINGS)] = Field("equal", json_schema_extra={"x-ui": _ui(
        "나누는 방식", "advanced", widget="cards", options=_WEIGHTINGS)})
    as_of: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui(
        "기준일", "advanced", help="비우면 오늘이에요.")})


def _alpha_portfolio(inputs: dict, p: AlphaPortfolioParams) -> pg.NodeOutput:
    from src.api import alpha_routes as _al
    req = _al.AlphaPortfolioRequest(alphas=[_al.AlphaWeightSpec(alpha_id=a) for a in p.alpha_ids],
                                    universe=p.universe, top_k=p.top_k, weighting=p.weighting, as_of=p.as_of,
                                    record_run=False)                               # ★계산은 기록하지 않는다★
    try:
        out = _al.alpha_portfolio(req)
    except HTTPException as e:
        raise pg.NodeFailure(f"알파 포트폴리오를 만들지 못했어요 — {_detail(e)}") from e
    if not out.get("available"):
        why = "; ".join(f"{b.get('name') or b.get('alpha_id')}: {b.get('reason')}" for b in out.get("blocked") or [])
        raise pg.NodeFailure(f"{out.get('reason') or '알파 포트폴리오를 만들지 않았어요.'}" + (f" — {why}" if why else ""))
    base = {str(c): float(v) for c, v in (out.get("base_weights") or {}).items() if float(v) > 0}
    if not base:
        raise pg.NodeFailure("비중이 모두 0이라 담을 종목이 없어요.")
    codes = list(base)
    w = np.array([base[c] for c in codes], dtype=float)
    w = w / w.sum()
    view = {"weights": out["base_weights"], "labels": _labels(codes), "holdings": out.get("holdings"),
            "pairwise": out.get("pairwise"), "effective_n": out.get("effective_n"), "warnings": out.get("warnings"),
            "excluded": out.get("excluded"), "note": out.get("note"), "as_of_effective": out.get("as_of_effective")}
    return pg.NodeOutput(values={"weights": weights_value(codes, w)}, view=view,
                         tags={"pit": "unknown" if p.as_of else "forward_only", "practice": mock_allowed(),
                               "sources": ["alpha_combine"]})


def _explain_alpha_portfolio(view: dict, prov: dict, params: Any) -> dict:
    w = view.get("weights") or {}
    trust = [_t(CONFIRMED, "승인된 알파의 점수를 합쳐 상위 종목을 골랐어요."),
             _t(UNKNOWN, str(view.get("note") or "거래 비용을 반영하지 않았어요."))]
    trust += [_t(UNKNOWN, str(x)) for x in view.get("warnings") or []]
    if mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 가격·재무 값이 합성일 수 있어요."))
    en = view.get("effective_n")
    return {"title": f"알파를 합쳐 {len(w)}종목의 비중을 정했어요",
            "facts": [f"실질 알파 수 {float(en):.1f}개" if en is not None else "실질 알파 수 미상"],
            "trust": trust, "unmeasured": ["이 비중의 과거 성과(한 시점의 비중이라 정책 백테스트가 없어요)"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("frontier", "효율적 프런티어", stage="check", plain_label="흔들림 대비 수익의 경계",
                    plain_description="같은 흔들림에서 가장 높은 수익을 내는 조합들을 곡선으로 그려요.",
                    inputs=(P("returns", "Returns"), P("weights", "Weights", required=False)), outputs=(),
                    run=_frontier, params_model=FrontierParams, explain=_explain_frontier, category="확인",
                    description="PortfolioAnalyzer.efficient_frontier + MC 구름(/analyze 3·4 단계와 같다)."),
        pg.NodeSpec("regime_ensemble", "국면 앙상블", stage="signal", plain_label="세 방법으로 국면 보기",
                    plain_description="축·상태 전환·군집 세 방법이 각각 어떤 국면을 가리키는지 나란히 봐요.",
                    inputs=(), outputs=(), run=_regime_ensemble, params_model=EnsembleParams,
                    explain=_explain_ensemble, category="거시",
                    description="regime_ensemble(/macro/regime-ensemble 과 같다) · 운영은 저장된 관측만."),
        pg.NodeSpec("regime_explain", "국면 설명", stage="signal", plain_label="국면이 왜 나왔나",
                    plain_description="지금 국면을 만든 지표와 다음 달들로 넘어갈 확률을 봐요.",
                    inputs=(), outputs=(), run=_regime_explain, params_model=ExplainParams,
                    explain=_explain_regime_explain, category="거시",
                    description="regime_transitions + regime_drivers(/macro/regime-explain 과 같다) · 운영은 저장된 관측만."),
        pg.NodeSpec("scenario_three_way", "세 갈래 시나리오", stage="check", plain_label="상황별 세 갈래 비교",
                    plain_description="그대로 두기 · 타이밍만 · 타이밍+국면을 같은 충격 아래서 비교해요.",
                    inputs=(P("weights", "Weights"), P("signal", "TimingSignal"),
                            P("regime", "RegimeState", required=False)), outputs=(),
                    run=_three_way, params_model=ThreeWayParams, explain=_explain_three_way, category="확인",
                    description="/scenario-three-way 라우트 함수 — 같은 rule_set_states·three_way."),
        pg.NodeSpec("custom_scenario", "직접 만든 시나리오", stage="check", plain_label="내가 정한 충격 넣기",
                    plain_description="시장과 성격별 충격을 직접 정해 이 비중에 넣어 봐요.",
                    inputs=(P("weights", "Weights"),), outputs=(P("stress", "StressReport"),),
                    run=_custom_scenario, params_model=CustomParams, explain=_explain_custom, category="확인",
                    description="/scenario-run 라우트 함수(인라인 팩 · 저장된 팩) — model_type 은 서버가 정한다."),
        pg.NodeSpec("strategy_health", "전략 건강", stage="check", plain_label="알파들 상태 보기",
                    plain_description="등록한 알파들이 건강한지, 줄이거나 멈출 것이 있는지 봐요.",
                    inputs=(), outputs=(), run=_strategy_health, explain=_explain_health, category="알파",
                    description="/strategy-health 라우트 함수(읽기만)."),
        pg.NodeSpec("sleeve_analytics", "묶음 분석", stage="check", plain_label="묶음끼리 겹치나",
                    plain_description="비중 묶음 둘 이상이 얼마나 같이 움직이는지 봐요.",
                    inputs=(P("a", "Weights"), P("b", "Weights"), P("c", "Weights", required=False),
                            P("d", "Weights", required=False)), outputs=(),
                    run=_sleeve_analytics, explain=_explain_sleeves, category="확인",
                    description="sleeve_analytics(/sleeve-analytics 와 같다)."),
        pg.NodeSpec("alpha_validate", "알파 검증", stage="signal", plain_label="알파 식 검증하기",
                    plain_description="알파 식의 점수가 과거에 다음 달 수익 순위와 얼마나 맞았는지 재요.",
                    inputs=(), outputs=(), run=_alpha_validate, params_model=AlphaValidateParams,
                    explain=_explain_validate, category="알파",
                    save=_save_alpha_validation, save_label="검증 기록 남기기",
                    description="/alpha-lab/validate 라우트 함수 record_run=False · 저장은 버튼으로 한 번."),
        pg.NodeSpec("alpha_portfolio", "알파 포트폴리오", stage="build", plain_label="알파로 비중 만들기",
                    plain_description="승인된 알파 여럿의 점수를 합쳐 상위 종목의 비중을 정해요.",
                    inputs=(), outputs=(P("weights", "Weights"),), run=_alpha_portfolio,
                    params_model=AlphaPortfolioParams, explain=_explain_alpha_portfolio, category="알파",
                    description="/alpha-lab/portfolio 라우트 함수 record_run=False — 승인 사다리 차단 그대로."),
    ):
        registry.register(spec)
