"""AAS 그래프의 핵심 사슬 노드 — ★`/analyze`·`/backtest` 의 사본이 아니다★ (BI2)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` §4.3 · 실행기
`src/engine/portfolio_graph.py`

`run_analyze` 는 분석 산수의 **단일 출처**다(재현 엔드포인트가 그대로 부른다). 이 노드들은
그 산수를 다시 쓰지 않고 **같은 함수**를 같은 순서로 부른다 — `_load_clean_returns` ·
`build_belief` · `optimize` · `_apply_constraints` · `_risk_contribution_report` ·
`_enb_report` · `_policy_backtest`. 순서(오케스트레이션)만 여기 있고, 그것이 갈라지는지는
골든 테스트(`tests/test_allocation_graph.py`)가 `run_analyze`·`/backtest` 와 대조한다.

## 노드 경계가 가짜가 아닌 이유 — 그리고 한 군데 예외

`build_belief` 는 옵티마이저의 **모델**을 읽는다(모델마다 조건부 뷰가 다르다). 그래서
`estimate` 노드는 μ/Σ 를 **미리 계산하지 않고 추정 설정을 나른다** — 옵티마이저가 자기
모델 아래에서 `/analyze` 와 똑같이 `build_belief` 를 부른다. 설정을 미리 계산해 두면
모델을 바꿨을 때 다른 모델의 믿음이 조용히 섞인다.

## 파라미터 규칙의 단일 출처

노드 파라미터 모델은 `AnalyzeRequest`·`BacktestRequest` 의 **필드 정의를 그대로 복사해**
만든다(`_subset`). 범위를 여기 다시 적으면 두 곳이 갈라진다. 옵티마이저 노드는 결국
`AnalyzeRequest` 를 만들어 부르므로, 조합 규칙(예: 뷰 형식)도 같은 검증을 지난다.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from src.api.allocation_graph_explain import EXPLAINERS, MODEL_PLAIN
from src.api.allocation_pipeline import build_belief
from src.api.allocation_routes import (
    AllocationView,
    AnalyzeRequest,
    BacktestRequest,
    _apply_constraints,
    _check_as_of,
    _enb_report,
    _ep_unavailable_reason,
    _labels,
    _load_clean_returns,
    _policy_backtest,
    _risk_contribution_report,
    _unknown_tickers,
    _w_dict,
)
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine import allocation_studio as _studio
from src.engine import portfolio_graph as pg

logger = logging.getLogger(__name__)

PORT_TYPES = ("Universe", "Returns", "Belief", "Views", "Weights", "RiskReport",
              "BacktestResult",
              # BK — 레포 도구를 노드로 옮기며 생기는 값. 선언만 먼저(BK0), 노드는 웨이브마다.
              "Scenario", "StressReport", "Scores", "RegimeState", "TimingSignal", "Trades",
              "TargetVersion", "StrategyResult",
              # BL3 W1 — 백그라운드에서 끝난 조건식 백테스트 실행 한 건(불러오기 노드가 낸다).
              "BacktestRun")


def weights_value(names: list[str], weights: Any, *, sigma_annual: Any = None,
                  sigma_source: str | None = None, req: Any = None, opt: Any = None,
                  **extra: Any) -> dict:
    """★Weights 포트 값의 계약★ (BK0) — 생산자가 여럿이 되므로 모양을 한 곳에서 정한다.

    - `names`·`weights`(배열) — 필수.
    - `sigma_annual`·`sigma_source` — 연율 공분산. 없으면 리스크 분해가 **실패**한다(지어내지 않는다).
    - `req` — 이 비중을 만든 **규칙**(옵티마이저 요청). 없으면 정책 백테스트가 되돌려 볼 것이 없어
      **거절**한다. 옵티마이저만 이것을 싣는다.
    """
    return {"names": list(names), "weights": weights, "sigma_annual": sigma_annual,
            "sigma_source": sigma_source, "req": req, "opt": opt, **extra}

_FORBID = ConfigDict(extra="forbid")


def _subset(name: str, source: type[BaseModel], fields: tuple[str, ...],
            ui: dict[str, dict] | None = None, **overrides: Any) -> type[BaseModel]:
    """요청 모델의 필드 정의를 **복사**해 노드 파라미터 모델을 만든다(범위를 다시 적지 않는다).

    `ui` 는 화면용 메타(BJ1) — 쉬운 이름·질문·기본/전문가 층·프리셋. 스키마의 `x-ui` 로
    나가고 **검증 규칙에는 끼어들지 않는다**(범위·선택지는 여전히 요청 모델 하나).
    """
    ui = ui or {}
    spec: dict[str, Any] = {}
    for f in fields:
        fi = copy.deepcopy(source.model_fields[f])
        if f in ui:
            fi.json_schema_extra = {"x-ui": ui[f]}
        spec[f] = (fi.annotation, fi)
    spec.update(overrides)
    return create_model(name, __config__=_FORBID, **spec)


def _ui(label: str, tier: str = "basic", **kw: Any) -> dict:
    return {"label": label, "tier": tier, **kw}


def _pydantic_reason(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in d['loc']) or '(전체)'}: {d['msg']}"
                     for d in e.errors())


#: 카탈로그 enum 은 모델 **이름**이다. 이 환경에서 풀 수 있는지는 실행 시점에 다시 묻는다.
_MODELS = tuple(_studio.model_availability())

#: 퀀트 워크플로우 단계 — 팔레트·이야기의 묶음(BJ1). 순서가 곧 흐름이다.
STAGES = [
    {"key": "data", "label": "데이터"},
    {"key": "signal", "label": "신호"},
    {"key": "belief", "label": "생각 정하기"},
    {"key": "build", "label": "비중 정하기"},
    {"key": "check", "label": "확인하기"},
    {"key": "act", "label": "실행·기록"},
]

UniverseParams = _subset("UniverseParams", AnalyzeRequest, ("tickers", "weights", "benchmark"), ui={
    "tickers": _ui("종목", question="어떤 종목으로 할까요?", help="종목 코드를 쉼표로 넣어요."),
    "weights": _ui("지금 비중", "advanced", help="들고 있는 비중을 알려 주면 회전율 제약에 써요."),
    "benchmark": _ui("비교 기준", "advanced", help="성과를 비교할 지수예요."),
})
ReturnsParams = _subset("ReturnsParams", AnalyzeRequest, ("lookback_days", "as_of"), ui={
    "lookback_days": _ui("기간", question="얼마나 긴 과거를 볼까요?", unit="거래일",
                         presets=[{"label": "1년", "value": 252}, {"label": "3년", "value": 756},
                                  {"label": "5년", "value": 1260}]),
    "as_of": _ui("기준일", "advanced",
                 help="비우면 오늘이에요. 과거 날짜로 고정하면 그날까지의 데이터만 써요."),
})
EstimateParams = _subset("EstimateParams", AnalyzeRequest,
                         ("conditional", "require_verified_macro", "regime_weighting",
                          "regime_mode", "rebalance"), ui={
    "conditional": _ui("경기 국면 반영", question="경기 국면을 반영할까요?",
                       help="켜면 지금 국면과 비슷했던 과거로 기대 수익을 잡아요."),
    "require_verified_macro": _ui("확인된 국면 판정만 쓰기", "advanced"),
    "regime_weighting": _ui("국면 가중 방식", "advanced",
                            options={"hard": "확정 국면", "probabilistic": "확률 가중"}),
    "regime_mode": _ui("국면 모드", "advanced", options={"live": "오늘 기준", "backtest": "과거 기준"}),
    "rebalance": _ui("보유 기간", "advanced", options={"M": "한 달", "Q": "한 분기"}),
})
OptimizerParams = _subset(
    "OptimizerParams", AnalyzeRequest, ("delta", "tau", "constraints"), ui={
        "delta": _ui("위험 회피 정도", question="위험을 얼마나 피할까요?", widget="slider",
                     ends=["과감하게", "신중하게"]),
        "tau": _ui("내 생각 불확실성 τ", "advanced", help="클수록 내 생각이 비중을 더 크게 움직여요."),
        "constraints": _ui("제약", question="한 종목에 최대 얼마까지 둘까요?",
                           presets=[{"label": "제한 없음", "value": None},
                                    {"label": "40%", "value": {"max_weight_pct": 40}},
                                    {"label": "30%", "value": {"max_weight_pct": 30}},
                                    {"label": "20%", "value": {"max_weight_pct": 20}}]),
    },
    model=(Literal[_MODELS], Field("mvo", json_schema_extra={"x-ui": _ui(
        "계산 방식", question="어떤 방식으로 나눌까요?", widget="cards",
        options={m: MODEL_PLAIN.get(m, m) for m in _MODELS})})))
BacktestParams = _subset("BacktestParams", BacktestRequest,
                         ("rebalance", "window_days", "cost_bps"), ui={
    "rebalance": _ui("리밸런싱 주기", question="얼마나 자주 비중을 맞출까요?",
                     options={"M": "매월", "Q": "분기마다"}),
    "window_days": _ui("학습 기간", "advanced", help="비우면 처음부터 모든 과거를 써요(확장 창)."),
    "cost_bps": _ui("거래비용", question="거래비용을 얼마로 볼까요?", unit="bp",
                    presets=[{"label": "0.05%", "value": 5}, {"label": "0.1%", "value": 10},
                             {"label": "0.3%", "value": 30}]),
})


class ViewsParams(BaseModel):
    model_config = _FORBID
    views: list[AllocationView] = Field(
        default_factory=list, max_length=30,
        json_schema_extra={"x-ui": _ui("내 생각", question="어떤 전망을 넣을까요?",
                                       help="종목의 1년 기대 수익과 확신을 적어요.")})


# ── 노드 처리기 ──────────────────────────────────────────────────────────────

def _universe(inputs: dict, p) -> pg.NodeOutput:
    value = {"tickers": list(p.tickers), "weights": p.weights, "benchmark": p.benchmark}
    return pg.NodeOutput(
        values={"universe": value},
        view={"tickers": value["tickers"], "labels": _labels(value["tickers"]),
              "weights": p.weights, "benchmark": p.benchmark,
              "unknown_tickers": _unknown_tickers(value["tickers"])})


def _returns(inputs: dict, p) -> pg.NodeOutput:
    u = inputs["universe"]
    try:
        _check_as_of(p.as_of)
    except HTTPException as e:
        raise pg.NodeFailure(str(e.detail)) from e
    returns, bench, excluded, coverage = _load_clean_returns(
        u["tickers"], u["benchmark"], p.lookback_days, as_of=p.as_of)
    if returns is None or len(returns.columns) < 2:
        why = "; ".join(f"{x['ticker']}: {x['reason']}" for x in excluded) or "없음"
        raise pg.NodeFailure("분석 가능한 자산이 2개 미만입니다. 시세가 적재된 자산을 "
                             f"추가하세요. (제외: {why})")
    names = list(returns.columns)
    source = coverage.get("source")
    provenance = {
        "source": source,
        # ★등급은 아는 만큼만★ mock 폴백은 합성(E0)이 확실하다. DB 적재분은 이 경로가
        # 행 단위 출처를 싣지 않아 E1~E4 중 무엇인지 알 수 없다 — 지어내지 않는다.
        "data_grade": "E0" if source == "mock" else None,
        "data_grade_reason": (None if source == "mock" else
                              "DB 적재분 — 이 경로는 행 단위 출처를 싣지 않아 픽스처·제공자"
                              "·실 과거·시점고정 중 어느 것인지 관측되지 않았습니다."),
        "as_of_effective": coverage.get("as_of_effective"),
    }
    value = {"universe": u, "lookback_days": p.lookback_days, "as_of": p.as_of,
             "returns": returns, "bench": bench, "excluded": excluded,
             "coverage": coverage, "names": names}
    return pg.NodeOutput(
        values={"returns": value},
        view={"names": names, "labels": _labels(names), "n_assets": len(names),
              "excluded": excluded, "coverage": coverage},
        provenance=provenance,
        # ★연습용은 하류 전부로 흐른다★ (BK0) — 합성 수익률로 만든 비중·충격·성과는 모두 연습용.
        tags={"practice": source == "mock", "sources": [f"returns:{source or '미상'}"]})


def _views(inputs: dict, p) -> pg.NodeOutput:
    views = [v.model_dump() for v in p.views]
    return pg.NodeOutput(values={"views": views},
                         view={"n_views": len(views), "views": views})


def _estimate(inputs: dict, p) -> pg.NodeOutput:
    settings = p.model_dump()
    note = ("조건부 μ/Σ 를 요청했습니다 — 옵티마이저가 자기 모델 아래에서 계산하고, 검증 "
            "관문이 막으면 표본 추정으로 계산하며 그 사유를 옵티마이저 결과에 적습니다."
            if p.conditional else
            "표본(trailing) μ/Σ — 조건부 추정을 요청하지 않았습니다.")
    return pg.NodeOutput(values={"belief": settings},
                         view={"settings": settings, "note": note})


def _optimizer(inputs: dict, p) -> pg.NodeOutput:
    r, belief_settings = inputs["returns"], inputs["belief"]
    avail = _studio.model_availability().get(p.model) or {}
    if not avail.get("available"):
        raise pg.NodeFailure(f"{p.model} 모델을 이 환경에서 풀 수 없습니다 — "
                             f"{avail.get('reason') or '가용성 미상'}")
    u = r["universe"]
    # ★회사 뷰는 사용자 뷰와 섞지 않는다★ (BK W5) — `/analyze use_company_views` 와 같은 자리
    # (`optimize(company_views=…)`)로 넘겨야 공시 `company_views_used` 가 제 몫만 센다. 사용자 뷰
    # (`AllocationView`)에는 `source` 칸이 없어 이 갈래에 잡히지 않는다.
    co_source = _studio._company_source()                   # 회사 뷰 출처 라벨의 단일 출처
    incoming = list(inputs.get("views") or [])
    company = [v for v in incoming if v.get("source") == co_source]
    user_views = [v for v in incoming if v.get("source") != co_source]
    try:
        req = AnalyzeRequest(
            tickers=u["tickers"], weights=u["weights"], benchmark=u["benchmark"],
            lookback_days=r["lookback_days"], as_of=r["as_of"],
            views=user_views or None,
            model=p.model, delta=p.delta, tau=p.tau, constraints=p.constraints,
            **belief_settings)
    except ValidationError as e:
        raise pg.NodeFailure(f"요청 조합이 /analyze 규칙에 맞지 않습니다 — "
                             f"{_pydantic_reason(e)}") from e
    if req.model == "ep":
        from src.engine.capability import probe_all
        why = _ep_unavailable_reason(probe_all())
        if why:
            raise pg.NodeFailure(why)

    import numpy as np

    from src.engine.allocation_studio import optimize
    from src.engine.entropy_views import EPUnavailable
    returns, names = r["returns"], r["names"]
    R = returns.values
    belief = build_belief(req, returns, names)
    views = [v.model_dump() for v in (req.views or [])]
    try:
        opt = optimize(req.model, names, R, views=views or None,
                       delta=req.delta, tau=req.tau,
                       s_override=belief.s_override, extra_views=belief.extra_views,
                       company_views=company or None)
    except EPUnavailable as e:
        raise pg.NodeFailure(str(e)) from e
    constraints_report = _apply_constraints(req, names, R, opt, r["bench"])
    weights = np.asarray(opt["weights"], dtype=float)
    value = weights_value(names, weights, sigma_annual=opt["sigma_annual"],
                          sigma_source=opt.get("sigma_source", "trailing"), req=req, opt=opt,
                          constraints_report=constraints_report)
    view = {
        "names": names, "labels": _labels(names), "model": req.model,
        "params": {"delta": req.delta, "tau": req.tau},
        "weights": _w_dict(names, weights),
        "flow": {stage: _w_dict(names, w) for stage, w in opt["flow"].items()},
        "views_applied": opt["views_applied"], "skipped_views": opt["skipped_views"],
        "cap_missing": opt["cap_missing"], "mu_engine": opt.get("mu_engine"),
        "ep": opt.get("ep"), "constraints_report": constraints_report,
        "company_views_used": opt.get("company_views_used"),
        "belief": {"conditional": req.conditional, "blocked": belief.blocked,
                   "blocked_reason": belief.blocked_reason},
    }
    provenance = {"perf_label": backtest_label(is_mock_data=mock_allowed()).to_dict(),
                  "data_source": r["coverage"].get("source"),
                  "sigma_source": opt.get("sigma_source", "trailing"),
                  "mu_engine": opt.get("mu_engine")}
    return pg.NodeOutput(values={"weights": value}, view=view, provenance=provenance)


def _risk(inputs: dict, p) -> pg.NodeOutput:
    w = inputs["weights"]
    names, sigma = w["names"], w.get("sigma_annual")
    if sigma is None:
        raise pg.NodeFailure("이 비중에는 공분산이 함께 오지 않아 위험을 나눌 수 없어요 — "
                             "공분산을 추정하는 노드(비중 계산)의 비중을 이어 주세요.")
    sigma_source = w.get("sigma_source") or "미상"
    view = {
        "risk_contribution_optimized": _risk_contribution_report(
            w["weights"], sigma, names,
            weights_source="optimized", sigma_source=sigma_source),
        "enb": {**_enb_report(w["weights"], sigma, names),
                "weights_source": "optimized", "sigma_source": sigma_source},
    }
    return pg.NodeOutput(values={"risk": view}, view=view,
                         provenance={"sigma_source": sigma_source})


def _backtest_admits(lineage: dict) -> str | None:
    """정책 백테스트가 받지 않는 계보 (BK0) — 조용히 벗겨 내지 않고 거절한다."""
    if lineage.get("overlay"):
        return ("오늘 계산한 노출 조절이 얹힌 비중이에요. 오늘의 판단을 과거 전체에 쓰면 미래를 "
                "보고 한 계산이 돼요 — ‘시점별 타이밍 시뮬레이션’으로 과거를 확인해 주세요.")
    if lineage.get("pit") == "forward_only":
        return ("지금 시점에만 쓸 수 있는 값(전망·국면 스냅샷)이 섞여 있어요. 과거에 쓰면 미래를 "
                "보고 한 계산이 돼서 백테스트하지 않아요.")
    return None


def _backtest(inputs: dict, p) -> pg.NodeOutput:
    r, w = inputs["returns"], inputs["weights"]
    req: AnalyzeRequest | None = w.get("req")
    if req is None:
        # 이 노드는 비중을 되돌리지 않고 **규칙(옵티마이저 요청)** 을 다시 돌린다. 규칙 없는
        # 비중을 받아 옵티마이저 성과를 그 비중의 성과처럼 보이면 안 된다.
        raise pg.NodeFailure("이 비중에는 과거로 되돌려 볼 규칙이 없어요 — 정책 백테스트는 "
                             "‘비중 계산’ 노드의 규칙을 시점마다 다시 풀어요. 비중 계산 노드를 이어 주세요.")
    try:
        breq = BacktestRequest(
            tickers=r["universe"]["tickers"], benchmark=r["universe"]["benchmark"],
            lookback_days=r["lookback_days"], as_of=r["as_of"],
            model=req.model, views=req.views, constraints=req.constraints,
            delta=req.delta, tau=req.tau,
            rebalance=p.rebalance, window_days=p.window_days, cost_bps=p.cost_bps)
    except ValidationError as e:
        raise pg.NodeFailure(f"정책 백테스트 규칙에 맞지 않습니다(/backtest 와 같은 규칙) — "
                             f"{_pydantic_reason(e)}") from e
    out = _policy_backtest(breq, r["returns"], r["bench"], r["excluded"], r["coverage"])
    if out.get("error"):
        raise pg.NodeFailure(str(out.get("message") or out.get("reason")
                                 or "백테스트 계획 단계에서 거부됐습니다."))
    out = dict(out)
    out["belief_note"] = (
        "조건부 μ/Σ 는 이 백테스트에 들어가지 않았습니다 — /backtest 와 같은 정의로, 각 "
        "리밸런싱 시점의 표본 추정만 씁니다." if req.conditional else None)
    return pg.NodeOutput(values={"backtest": out}, view=out,
                         provenance={"perf_label": out.get("perf_label"),
                                     "lookahead_evidence": out.get("lookahead_evidence")})


# ── 레지스트리 ───────────────────────────────────────────────────────────────

P = pg.Port

# ── 저장 (BL2) ────────────────────────────────────────────────────────────────

def _save_research_run(values: dict, view: dict, params: Any) -> dict:
    """비중 계산 → **연구 기록 남기기** (BL2 · 마법사 OPTIMIZE 의 '기록' 을 옮김).

    ★기록은 `/analyze` 가 남긴다★ 재현(`/research-runs/{id}/reproduce`)이 그 경로를 다시 부르기 때문이다. 그런데
    캔버스에는 `/analyze` 에 없는 칸이 있다(예: 회사 뷰의 수렴 기간). 그 경로가 미리보기와 **다른 비중**을 내면 그 기록은
    재현하면 다른 것이 나오는 거짓 기록이다 — 그래서 먼저 기록 없이 계산해 대조하고, 같을 때만 기록한다.
    """
    from src.api.allocation_routes import run_analyze
    req: AnalyzeRequest = values["weights"]["req"]
    upd: dict[str, Any] = {"run_name": "노드 캔버스 기록"}
    if view.get("company_views_used"):
        upd["use_company_views"] = True
    probe = run_analyze(req.model_copy(update={**upd, "record_run": False}))
    got = (probe.get("weights") or {}).get("optimized") or {}
    want = view.get("weights") or {}
    if set(got) != set(want) or any(abs(float(got[k]) - float(want[k])) > 1e-6 for k in want):
        raise pg.NodeFailure("기록 경로(/analyze)가 이 미리보기와 다른 비중을 내서 기록하지 않았어요 — "
                             "/analyze 에 없는 설정(예: 회사 뷰의 수렴 기간)을 기본값으로 돌리면 기록할 수 있어요.")
    out = run_analyze(req.model_copy(update={**upd, "record_run": True}))
    rid = out.get("run_id")
    if not rid:
        raise pg.NodeFailure("DB 를 쓸 수 없어 연구 기록을 남기지 못했어요.")
    return {"saved_id": rid, "text": f"연구 기록으로 남겼어요 · {rid}"}


REGISTRY = pg.Registry(port_types=PORT_TYPES)
for _spec in (
    pg.NodeSpec("universe", "유니버스", stage="data", plain_label="종목 고르기",
                plain_description="분석할 종목과 지금 비중을 정해요.", explain=EXPLAINERS["universe"], inputs=(), outputs=(P("universe", "Universe"),),
                run=_universe, params_model=UniverseParams, category="입력",
                description="종목 목록 · 현재 비중(선택) · 벤치마크."),
    pg.NodeSpec("returns", "수익률", stage="data", plain_label="수익률 불러오기",
                plain_description="기간과 기준일을 정해요.", explain=EXPLAINERS["returns"], inputs=(P("universe", "Universe"),),
                outputs=(P("returns", "Returns"),), run=_returns, params_model=ReturnsParams,
                category="데이터",
                description="적재된 일별 수익률(lookback·절단일). 운영에서는 합성하지 않는다."),
    pg.NodeSpec("views", "BL 뷰", stage="belief", plain_label="내 생각 넣기",
                plain_description="“삼성전자가 오를 것” 같은 전망을 넣어요.", explain=EXPLAINERS["views"], inputs=(), outputs=(P("views", "Views"),), run=_views,
                params_model=ViewsParams, category="입력",
                description="절대(assets) 또는 부호 있는 조합(weights) 뷰."),
    pg.NodeSpec("estimate", "추정 설정", stage="belief", plain_label="기대 수익 추정",
                plain_description="과거 기준 또는 경기 국면을 반영해요.", explain=EXPLAINERS["estimate"], inputs=(P("returns", "Returns"),),
                outputs=(P("belief", "Belief"),), run=_estimate, params_model=EstimateParams,
                category="추정",
                description="표본 또는 국면조건부 μ/Σ 설정. 계산은 옵티마이저가 자기 모델로 한다."),
    pg.NodeSpec("optimizer", "옵티마이저", stage="build", plain_label="비중 계산",
                plain_description="여러 방식 중 하나로 비중을 나눠요.", explain=EXPLAINERS["optimizer"],
                inputs=(P("returns", "Returns"), P("belief", "Belief"),
                        P("views", "Views", required=False)),
                outputs=(P("weights", "Weights"),), run=_optimizer,
                params_model=OptimizerParams, category="배분",
                save=_save_research_run, save_label="연구 기록 남기기",
                description="/analyze 와 같은 최적화·제약. 결과는 가중치와 정책을 함께 나른다."),
    pg.NodeSpec("risk", "리스크 분해", stage="check", plain_label="흔들림 나눠 보기",
                plain_description="어느 종목이 위험을 얼마나 만드는지 봐요.", explain=EXPLAINERS["risk"], inputs=(P("weights", "Weights"),),
                outputs=(P("risk", "RiskReport"),), run=_risk, category="분석",
                description="오일러 리스크 기여 · ENB/Neff (추천 포트폴리오 기준)."),
    pg.NodeSpec("backtest", "정책 백테스트", stage="check", plain_label="과거로 돌려 보기",
                plain_description="이 규칙대로 했다면 어땠을지 봐요.", explain=EXPLAINERS["backtest"],
                inputs=(P("returns", "Returns"), P("weights", "Weights")),
                outputs=(P("backtest", "BacktestResult"),), run=_backtest, admits=_backtest_admits,
                params_model=BacktestParams, category="분석",
                description="같은 정책을 walk-forward 로 시점 밖에서 재현(/backtest 와 같다)."),
):
    REGISTRY.register(_spec)


# ── BK 웨이브 노드 — 모듈마다 자기 노드를 등록한다(이 파일을 더 키우지 않는다) ──────────
from src.api import allocation_graph_nodes_check as _check  # noqa: E402

_check.register(REGISTRY)
from src.api import allocation_graph_nodes_signal as _signal  # noqa: E402

_signal.register(REGISTRY)
from src.api import allocation_graph_nodes_macro as _macro  # noqa: E402

_macro.register(REGISTRY)
from src.api import allocation_graph_nodes_act as _act  # noqa: E402

_act.register(REGISTRY)
from src.api import allocation_graph_nodes_strategy as _strategy  # noqa: E402

_strategy.register(REGISTRY)
from src.api import allocation_graph_nodes_bl2 as _bl2  # noqa: E402

_bl2.register(REGISTRY)
from src.api import allocation_graph_nodes_backtest as _backtest  # noqa: E402

_backtest.register(REGISTRY)
from src.api import allocation_graph_nodes_macro_w2 as _macro_w2  # noqa: E402

_macro_w2.register(REGISTRY)
from src.api import allocation_graph_nodes_company as _company  # noqa: E402

_company.register(REGISTRY)
