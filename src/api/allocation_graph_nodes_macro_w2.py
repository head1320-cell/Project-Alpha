"""AAS 그래프 — 매크로 웨이브 (BL3 W2) · ★라우트 본문을 꺼낸 공용 함수를 그대로 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 매크로. 같은 수인지는 `tests/test_allocation_graph_bl3w2.py` 골든이 라우트와 대조한다.

| 노드 | 부르는 것 |
|---|---|
| 수익률 곡선 | `macro_routes.yield_curve_view` (`/macro/yield-curve` 본문) |
| 지표 대시보드 | `macro_routes.dashboard_themes` (`/macro/dashboard` 본문) |
| 국면 합의 | `macro_routes.regime_consensus_view` (`/macro/regime-consensus` 본문) |
| 국면 예측 적중률 | `macro_routes.forecast_coverage_view` (`/macro/regime-forecast-coverage` 본문) |
| 장기 관계 | `macro_routes.long_run_view` (`/macro/long-run` 본문) — 계열은 `series_source` 주입 |
| 스튜디오 모델 | `macro_models.run_studio` (`/macro/studios/{id}`) — 계열은 `series_source` 주입 |

데이터는 BL2b `macro_series_map()` 하나로 받는다 — 운영은 **저장된 관측만**(외부 호출 0 · 적재 0), 개발은 `/macro` 라우트와
같은 수집기 출력 + 연습용 계보. 장기 관계·스튜디오 엔진은 안에서 `load_series` 로 수집기를 직접 부르므로 노드가 그 자리에
저장된 계열을 주입하고, 블록을 나가면 거둔다.

## 하지 않는 것
- 상관 패널(`/macro/correlations`) — 가격 적재가 DB → KIS → mock 사슬이라 운영에서 외부를 부를 수 있다. 노드로 만들지 않는다.
- 스튜디오의 프런티어 가용성 — 그 프로브는 관측 수를 세느라 수집기를 부른다. 노드는 대체 엔진만 돌리고, 프런티어 판정은
  매크로 화면의 능력 사다리에 맡긴다(그렇다고 적는다).
- 뷰 컴파일러(`agentic-mcp`) — 자산·뷰 입력이 필요한 다른 종류의 도구다.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _ui
from src.api.allocation_graph_nodes_bl2 import _MARKETS, EnsembleParams, _macro_trust, macro_series_map
from src.engine import portfolio_graph as pg

_STORE_GUIDE = "매크로 화면에서 먼저 수집해 주세요"


def _out(view: dict, tags: dict) -> pg.NodeOutput:
    return pg.NodeOutput(values={}, view=view, tags=tags, provenance={"practice": tags["practice"]})


# ── 수익률 곡선 ───────────────────────────────────────────────────────────────

def _yield_curve(inputs: dict, p: Any) -> pg.NodeOutput:
    from src.api.macro_routes import yield_curve_view
    series, tags = macro_series_map()
    out = yield_curve_view(series)
    if not out.get("points"):
        raise pg.NodeFailure(f"곡선을 그릴 미국 국채 금리가 없어요 — {_STORE_GUIDE}.")
    return _out({"result": out}, tags)


def _explain_yield_curve(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    sp = r.get("spread_2y10y_bp")
    inv = bool(r.get("inversion"))
    title = ("장단기 금리가 뒤집혀 있어요" if inv else "곡선이 정상(장기 금리가 더 높음)이에요")
    headline = ({"label": "10년 − 2년 금리차", "value": round(sp), "unit": "bp",
                 "text": f"{round(sp):+d}bp" + (" 역전" if inv else "")} if isinstance(sp, (int, float)) else None)
    facts = [f"{x.get('label')} {x.get('yield_pct'):.2f}%" for x in r.get("points") or []
             if isinstance(x.get("yield_pct"), (int, float))]
    trust = [_t(ASSUMED, "해석 문장은 경험칙이에요 — 역전 뒤 침체가 왔던 과거 사례를 옮긴 것이지 예측 모형이 아니에요."),
             *_macro_trust(prov)]
    return {"title": title, "headline": headline, "facts": facts, "trust": trust,
            "unmeasured": ["이 역전이 실제 침체로 이어지는지(예측력)"]}


# ── 지표 대시보드 ─────────────────────────────────────────────────────────────

_THEMES = {"": "전체", "growth": "성장", "inflation": "물가", "rates": "금리·통화",
           "liquidity": "유동성·신용", "sentiment": "수급·심리", "korea": "한국"}


class DashboardParams(BaseModel):
    model_config = _FORBID
    theme: Literal["", "growth", "inflation", "rates", "liquidity", "sentiment", "korea"] = Field(
        "", json_schema_extra={"x-ui": _ui("테마", question="어떤 지표를 볼까요?", widget="cards", options=_THEMES,
                                            help="비우면 여섯 테마를 모두 봐요.")})


def _as_dict(s: Any) -> dict:
    return asdict(s) if is_dataclass(s) else dict(s)


def _dashboard(inputs: dict, p: DashboardParams) -> pg.NodeOutput:
    from src.api.macro_routes import dashboard_themes
    series, tags = macro_series_map()
    themes = dashboard_themes({k: _as_dict(s) for k, s in series.items()})
    if p.theme:
        themes = [t for t in themes if t["key"] == p.theme]
    if not any(t["indicators"] for t in themes):
        raise pg.NodeFailure(f"이 테마에 보여 줄 지표가 없어요 — {_STORE_GUIDE}.")
    return _out({"themes": themes, "theme": p.theme}, tags)


def _explain_dashboard(view: dict, prov: dict, params: Any) -> dict:
    inds = [i for t in view.get("themes") or [] for i in t.get("indicators") or []]
    ranked = sorted((i for i in inds if isinstance(i.get("z_score"), (int, float))),
                    key=lambda i: abs(i["z_score"]), reverse=True)[:3]
    facts = [f"{i.get('name')}: 5년 평균에서 {i['z_score']:+.1f} 표준편차" for i in ranked]
    no_z = sum(1 for i in inds if not isinstance(i.get("z_score"), (int, float)))
    trust = [_t(CONFIRMED, "z 는 최근 5년(60개월) 창으로 쟀어요 — 창이 바뀌면 값도 바뀌어요.")]
    if no_z:
        trust.append(_t(UNKNOWN, f"{no_z}개 지표는 표본이 짧아 z 를 재지 못했어요 — 0 이 아니라 모름이에요."))
    trust += _macro_trust(prov)
    return {"title": f"지표 {len(inds)}개를 테마별로 모았어요",
            "facts": facts + (["평소와 가장 먼 지표부터 적었어요."] if facts else []),
            "trust": trust, "unmeasured": ["지표의 극단값이 앞으로의 수익을 말해 주는지(예측력)"]}


# ── 국면 합의 ─────────────────────────────────────────────────────────────────

_TOOLS = {"axis": "성장·물가 축", "markov": "상태 전환 모형", "cluster": "군집 모형"}


def _consensus(inputs: dict, p: EnsembleParams) -> pg.NodeOutput:
    from src.api.macro_routes import regime_consensus_view
    series, tags = macro_series_map()
    out = regime_consensus_view(series, market=p.market, months=p.months)
    if not out.get("n_available"):
        why = "; ".join(f"{_TOOLS.get(k, k)}: {v}" for k, v in (out.get("reasons") or {}).items()) or "사유 미상"
        raise pg.NodeFailure(f"국면을 판정한 방법이 하나도 없어요 — {why}")
    return _out({"result": out}, tags)


def _explain_consensus(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    v = r.get("verdict")
    if r.get("tie"):
        title = "방법끼리 표가 갈려 결론이 없어요"
    elif r.get("consensus"):
        title = f"가능한 방법이 모두 ‘{v}’로 모였어요"
    elif r.get("n_available", 0) < 2:
        title = f"한 방법만 답했어요(‘{v}’) — 합의가 아니에요"
    else:
        title = f"다수는 ‘{v}’지만 갈려요"
    facts = [f"{_TOOLS.get(k, k)}: {x}" for k, x in (r.get("per_tool") or {}).items()]
    trust = [_t(UNKNOWN, f"{_TOOLS.get(k, k)}는 판정하지 못했어요 — {x}") for k, x in (r.get("reasons") or {}).items()]
    trust += [_t(CONFIRMED, "세 방법을 평균 내지 않아요 — 갈리는 것 자체가 정보예요."), *_macro_trust(prov)]
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["합의된 국면이 실제로 맞는지(예측력)"]}


# ── 국면 예측 적중률 ──────────────────────────────────────────────────────────

class CoverageParams(BaseModel):
    model_config = _FORBID
    market: Literal["kr", "us"] = Field("kr", json_schema_extra={"x-ui": _ui(
        "시장", question="어느 시장의 국면 예측을 채점할까요?", widget="cards", options=_MARKETS)})
    months: int = Field(240, ge=24, le=600, json_schema_extra={"x-ui": _ui(
        "기간", "advanced", unit="개월", presets=[{"label": "10년", "value": 120}, {"label": "20년", "value": 240}],
        help="국면 경로를 만드는 기간이에요. 저장된 관측이 더 짧으면 있는 만큼만 써요.")})
    k: int = Field(1, ge=1, le=12, json_schema_extra={"x-ui": _ui(
        "몇 달 뒤", "advanced", unit="개월", help="몇 달 뒤 국면을 맞히는지 채점해요.")})
    alpha: float = Field(0.1, ge=0.01, le=0.5, json_schema_extra={"x-ui": _ui(
        "놓쳐도 되는 비율", "advanced", presets=[{"label": "10%", "value": 0.1}, {"label": "20%", "value": 0.2}],
        help="예측 집합이 목표로 덮을 몫은 1 − 이 값이에요.")})


def _coverage(inputs: dict, p: CoverageParams) -> pg.NodeOutput:
    from src.api.macro_routes import forecast_coverage_view
    series, tags = macro_series_map()
    out = forecast_coverage_view(series, market=p.market, months=p.months, k=p.k, alpha=p.alpha)
    if not out.get("available"):
        raise pg.NodeFailure(f"적중률을 잴 수 없어요 — {out.get('reason') or '사유 미상'}")
    return _out({"result": out}, tags)


def _explain_coverage(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    cov, tgt = r.get("coverage"), r.get("target")
    skill = r.get("set_size_skill_pct")
    title = (f"예측 집합이 {cov:.0%} 맞았어요 (목표 {tgt:.0%})"
             if isinstance(cov, (int, float)) and isinstance(tgt, (int, float)) else "적중률을 쟀어요")
    headline = ({"label": "기준선 대비 집합 축소", "value": round(skill, 1), "unit": "%",
                 "text": f"집합 {skill:+.1f}% 축소"} if isinstance(skill, (int, float)) else None)
    facts = [f"맞힘 {r.get('hits')} · 놓침 {r.get('misses')} (채점 {r.get('n_eval')}회)"]
    if isinstance(r.get("mean_set_size"), (int, float)):
        facts.append(f"평균 집합 크기 {r['mean_set_size']:.2f}개"
                     + (f" · 기준선 {r['baseline_mean_set_size']:.2f}개"
                        if isinstance(r.get("baseline_mean_set_size"), (int, float)) else ""))
    trust = [_t(CONFIRMED if r.get("walk_forward") else UNKNOWN,
                "각 시점 이전 경로만으로 예측했어요(미래를 쓰지 않은 채점)." if r.get("walk_forward")
                else "시점 이전 경로만 썼는지 확인되지 않았어요."),
             _t(ASSUMED, "적중률은 집합 크기와 함께 읽어야 해요 — 집합을 키우면 적중률은 언제든 올라가요."),
             *_macro_trust(prov)]
    if not r.get("baseline_available"):
        trust.append(_t(UNKNOWN, "기준선(기저율) 집합을 만들지 못해 비교가 없어요."))
    return {"title": title, "headline": headline, "facts": facts, "trust": trust,
            "unmeasured": ["국면을 맞히는 것이 수익으로 이어지는지(경제적 가치)"]}


# ── 장기 관계 ─────────────────────────────────────────────────────────────────

class LongRunParams(BaseModel):
    model_config = _FORBID
    months: int = Field(240, ge=24, le=600, json_schema_extra={"x-ui": _ui(
        "기간", unit="개월", question="몇 달의 관측으로 장기 관계를 볼까요?",
        presets=[{"label": "10년", "value": 120}, {"label": "20년", "value": 240}],
        help="저장된 관측이 더 짧으면 있는 만큼만 써요. 60개월보다 짧으면 판정하지 않아요.")})
    vars: str | None = Field(None, max_length=400, json_schema_extra={"x-ui": _ui(
        "계열(쉼표로 구분)", "advanced",
        help="비우면 미리 정해 둔 코어 셋을 써요. 최대 7개 — 데이터를 보고 고르면 검정이 검정이 아니게 돼요.")})


def _long_run(inputs: dict, p: LongRunParams) -> pg.NodeOutput:
    from src.api.macro_routes import long_run_view
    from src.engine.cointegration import CoreVariableError
    from src.engine.macro_models.base import series_source
    series, tags = macro_series_map()
    try:
        with series_source(series):
            out = long_run_view(p.vars, p.months)
    except CoreVariableError as e:
        raise pg.NodeFailure(str(e)) from e
    if not out.get("available"):
        raise pg.NodeFailure(f"장기 관계를 판정하지 못했어요 — {out.get('reason') or '사유 미상'}")
    return _out({"result": out}, tags)


_MODEL_KO = {"vecm": "오차수정 모형(VECM)", "diff_var": "차분 VAR"}


def _explain_long_run(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    m = r.get("model")
    title = (f"장기 균형 {r.get('coint_rank')}개를 찾아 {_MODEL_KO['vecm']}을 썼어요" if m == "vecm"
             else f"장기 균형이 없어 {_MODEL_KO['diff_var']}를 썼어요" if m == "diff_var"
             else f"{m} 모형을 썼어요")
    facts = [r.get("reason") or "", f"쓴 계열 {len(r.get('used') or [])}개: {', '.join(r.get('used') or [])}"]
    trust = [_t(CONFIRMED if not getattr(params, "vars", None) else ASSUMED,
                "미리 정해 둔 코어 셋이에요 — 데이터를 보고 고르지 않았어요." if not getattr(params, "vars", None)
                else "직접 고른 계열이에요 — 고르는 데 이 표본을 봤다면 검정의 p값이 부풀려져요.")]
    if r.get("missing_note"):
        trust.append(_t(UNKNOWN, r["missing_note"]))
    trust += _macro_trust(prov)
    return {"title": title, "facts": [f for f in facts if f], "trust": trust,
            "unmeasured": ["찾은 관계가 앞으로도 유지되는지(표본외)"]}


# ── 스튜디오 모델 ─────────────────────────────────────────────────────────────

_STUDIOS = {"neural-sde": "금리 곡선 요인", "tsfm-latent": "공통 잠재 상태",
            "causal-deepm": "선후 관계 그래프", "pinn-tail": "꼬리 위험"}


class StudioParams(BaseModel):
    model_config = _FORBID
    studio: Literal["neural-sde", "tsfm-latent", "causal-deepm", "pinn-tail"] = Field(
        "neural-sde", json_schema_extra={"x-ui": _ui("모델", question="어떤 질문을 모델에 물을까요?",
                                                    widget="cards", options=_STUDIOS)})
    months: int = Field(60, ge=12, le=240, json_schema_extra={"x-ui": _ui(
        "기간", "advanced", unit="개월", presets=[{"label": "5년", "value": 60}, {"label": "10년", "value": 120}])})
    target: Literal["KOSPI", "VIXCLS", "USD_KRW"] = Field("KOSPI", json_schema_extra={"x-ui": _ui(
        "꼬리 위험 대상", "advanced", options={"KOSPI": "코스피", "VIXCLS": "VIX", "USD_KRW": "원/달러"},
        help="꼬리 위험 모델에서만 써요.")})


def _studio(inputs: dict, p: StudioParams) -> pg.NodeOutput:
    from src.engine.macro_models.base import _module, run_studio, series_source
    series, tags = macro_series_map()
    with series_source(series):
        out = run_studio(p.studio, months=p.months, target=p.target)
    st = _module(p.studio).STUDIO
    info = {"id": st.id, "label": _STUDIOS[p.studio], "question": st.question,
            "frontier": st.frontier.name, "substitute": st.substitute.name}
    if not out.get("available"):
        raise pg.NodeFailure(f"‘{out.get('engine') or st.substitute.name}’을(를) 돌리지 못했어요 — "
                             f"{out.get('reason') or '사유 미상'}")
    return _out({"result": out, "studio": info}, tags)


def _explain_studio(view: dict, prov: dict, params: Any) -> dict:
    r, s = view.get("result") or {}, view.get("studio") or {}
    trust = [_t(CONFIRMED, f"이 숫자는 대체 엔진 ‘{r.get('engine') or s.get('substitute')}’이 냈어요."),
             _t(UNKNOWN, f"프런티어 엔진 ‘{s.get('frontier')}’은 이 노드가 돌리지 않아요 — "
                         "가용성은 매크로 화면의 능력 사다리가 판정해요.")]
    if r.get("note"):
        trust.append(_t(ASSUMED, str(r["note"]).replace("★", "")))
    trust += _macro_trust(prov)
    return {"title": f"{s.get('label')}: {s.get('question')}", "facts": [], "trust": trust,
            "unmeasured": ["모델이 찾은 구조가 앞으로도 유지되는지(표본외)"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("yield_curve", "수익률 곡선", stage="signal", plain_label="금리 곡선 보기",
                    plain_description="짧은 금리와 긴 금리의 모양, 뒤집혔는지를 봐요.",
                    inputs=(), outputs=(), run=_yield_curve, explain=_explain_yield_curve, category="거시",
                    description="macro_routes.yield_curve_view(/macro/yield-curve 본문) · 운영은 저장된 관측만."),
        pg.NodeSpec("macro_dashboard", "지표 대시보드", stage="signal", plain_label="거시 지표 한눈에",
                    plain_description="성장·물가·금리 같은 테마별로 지표가 평소와 얼마나 먼지 봐요.",
                    inputs=(), outputs=(), run=_dashboard, params_model=DashboardParams,
                    explain=_explain_dashboard, category="거시",
                    description="macro_routes.dashboard_themes(/macro/dashboard 본문) · 운영은 저장된 관측만."),
        pg.NodeSpec("regime_consensus", "국면 합의", stage="signal", plain_label="국면 판정이 모이나",
                    plain_description="세 방법의 국면 판정이 같은 곳을 가리키는지, 갈리는지 봐요.",
                    inputs=(), outputs=(), run=_consensus, params_model=EnsembleParams,
                    explain=_explain_consensus, category="거시",
                    description="macro_routes.regime_consensus_view(/macro/regime-consensus 본문) · 운영은 저장된 관측만."),
        pg.NodeSpec("regime_forecast_coverage", "국면 예측 적중률", stage="signal", plain_label="국면 예측 채점",
                    plain_description="다음 국면을 예측했을 때 실제로 얼마나 맞았는지 과거로 채점해요.",
                    inputs=(), outputs=(), run=_coverage, params_model=CoverageParams,
                    explain=_explain_coverage, category="거시",
                    description="macro_routes.forecast_coverage_view(/macro/regime-forecast-coverage 본문)."),
        pg.NodeSpec("long_run", "장기 관계", stage="signal", plain_label="지표들의 장기 균형",
                    plain_description="지표들이 길게 보면 함께 움직이는 균형이 있는지 검정해요.",
                    inputs=(), outputs=(), run=_long_run, params_model=LongRunParams,
                    explain=_explain_long_run, category="거시",
                    description="macro_routes.long_run_view(/macro/long-run 본문) · 계열은 저장된 관측 주입."),
        pg.NodeSpec("macro_studio", "스튜디오 모델", stage="signal", plain_label="거시 모델에 묻기",
                    plain_description="금리 요인·잠재 상태·선후 관계·꼬리 위험 모델을 지금 설치된 엔진으로 돌려요.",
                    inputs=(), outputs=(), run=_studio, params_model=StudioParams,
                    explain=_explain_studio, category="거시",
                    description="macro_models.run_studio(/macro/studios/{id}) 대체 엔진 · 계열은 저장된 관측 주입."),
    ):
        registry.register(spec)
