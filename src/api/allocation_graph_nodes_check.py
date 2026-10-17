"""AAS 그래프 — 확인하기 노드 (BK W1) · ★마법사의 스트레스 도구를 다시 쓰지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W1

마법사 STRESS 단계의 도구를 캔버스 노드로 옮긴다. 산수는 **라우트와 같은 함수**를 부른다 —
`historical_replay`·`hypothetical_shock`·`stress_correlation_report`(라우트 본문에서 꺼낸 것) ·
`kr_scenario_pack.run_scenario` · `allocation_studio.sensitivity_matrix` · `/factor-xray` 라우트 함수.
같은 수인지는 `tests/test_allocation_graph_w1.py` 골든이 라우트와 대조한다.

## 이 노드들이 계보에 다는 것
- 역사 리플레이가 mock 폴백을 썼으면 `practice`. 적재 시세면 아니다.
- 가정 충격(M8·국내 팩)·팩터 성격은 종목 재무·팩터 스토어를 읽는다. 개발(mock) 모드에서는 그
  값이 합성일 수 있어 `practice` 로 단다 — **넘치게 말하는 쪽이 안전하다**(운영에서는 mock 게이트가
  닫혀 이 태그가 붙지 않는다).
- 이 노드들은 비중을 만들지 않는다 — 결과는 확인용이다(StressReport 또는 출력 없음).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import Field

from src.api.allocation_graph_explain import (
    ASSUMED,
    CONFIRMED,
    MODEL_PLAIN,
    UNKNOWN,
    _josa,
    _pct,
    _practice,
    _signed_pct,
    _t,
)
from src.api.allocation_graph_nodes import _subset, _ui
from src.api.allocation_stress_routes import (
    SensitivityRequest,
    StressCorrRequest,
    StressRequest,
    XrayRequest,
    allocation_factor_xray,
    historical_replay,
    hypothetical_shock,
    stress_correlation_report,
)
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine import portfolio_graph as pg
from src.engine.portfolio_weights import signed_fractions
from src.engine.scenario_packs import PACKS

logger = logging.getLogger(__name__)

P = pg.Port

_DEV_STORES = ("개발 모드라 종목 재무·팩터 값이 합성일 수 있어요 — 실제 충격을 말해 주지 않아요.")


def holdings_pct(w: dict) -> dict[str, float]:
    """Weights 값 → `{코드: 비중%}`. ★비중이 모두 0 이면 계산하지 않는다★ — 라우트처럼 균등
    가중으로 바꿔치기하면 사용자가 준 것과 다른 포트폴리오를 확인하게 된다."""
    names, weights = list(w["names"]), np.asarray(w["weights"], dtype=float)
    if len(names) != len(weights) or not np.isfinite(weights).all() or np.abs(weights).sum() <= 0:
        raise pg.NodeFailure("비중이 비어 있거나 모두 0이라 확인할 포트폴리오가 없어요.")
    return {n: float(x) * 100.0 for n, x in zip(names, weights)}


def _names_on(w: dict, returns) -> tuple[list[str], np.ndarray]:
    names = list(w["names"])
    missing = [n for n in names if n not in returns.columns]
    if missing:
        raise pg.NodeFailure(f"비중의 종목 {', '.join(missing)} 이(가) 수익률에 없어요 — 같은 수익률에서 "
                             "나온 비중을 이어 주세요.")
    return names, np.asarray(w["weights"], dtype=float)


# ── 시나리오 충격 ─────────────────────────────────────────────────────────────

_SCENARIOS = tuple(PACKS)

ScenarioParams = _subset(
    "ScenarioStressParams", StressRequest, ("severity", "benchmark"),
    ui={
        "severity": _ui("강도", question="얼마나 세게 넣어 볼까요?", widget="slider", ends=["약하게", "세게"],
                        help="가정 충격에만 곱해요. 실제 시세를 재생하는 과거 위기에는 적용하지 않아요."),
        "benchmark": _ui("비교 지수", "advanced", help="과거 위기 재생에서 함께 그릴 지수예요."),
    },
    scenario=(Literal[_SCENARIOS], Field("rate_hike_200bp", json_schema_extra={"x-ui": _ui(
        "시나리오", question="어떤 상황에 넣어 볼까요?", widget="cards",
        options={k: p.label for k, p in PACKS.items()},
        help="과거 위기는 실제 시세를 그대로 재생하고, 나머지는 가정 충격이에요.")})),
)


def _scenario_stress(inputs: dict, p) -> pg.NodeOutput:
    pack = PACKS[p.scenario]
    h = signed_fractions(holdings_pct(inputs["weights"]))
    practice, source = False, pack.engine
    if pack.engine == "hist_replay":
        out, src = historical_replay(h, p.scenario, p.benchmark)
        if not out.get("available"):
            raise pg.NodeFailure(f"‘{pack.label}’ 기간의 시세가 없어 재생하지 못했어요 — {out.get('reason')}")
        practice, source = src == "mock", f"hist_replay:{src}"
    elif pack.engine == "m8":
        out = hypothetical_shock(h, p.scenario, p.severity)
        practice = mock_allowed()
    else:
        from src.engine.kr_scenario_pack import run_scenario
        out = run_scenario(list(h), h, p.scenario, severity=p.severity)
        practice = mock_allowed()
    if out.get("error"):
        raise pg.NodeFailure(str(out.get("message") or "시나리오를 계산하지 못했어요."))
    view = {"pack": pack.to_dict(), "result": out}
    prov: dict[str, Any] = {"model_type": pack.model_type.value, "source": source}
    if pack.engine == "hist_replay":
        # ★과거 재생은 성과 숫자(기간 수익률·낙폭)를 낸다 — 무슨 성과인지 라벨을 단다★
        # 오늘의 비중을 그 기간에 고정해 돌린 시뮬레이션이다(리밸런싱 없음).
        prov["perf_label"] = {**backtest_label(is_mock_data=practice).to_dict(),
                              "kind_reason": "오늘의 비중을 그 기간에 고정해 재생한 시뮬레이션이에요(리밸런싱 없음)."}
    return pg.NodeOutput(values={"stress": view}, view=view, provenance=prov,
                         tags={"practice": practice, "sources": [f"scenario:{source}"]})


def _explain_scenario(view: dict, prov: dict, params: Any) -> dict:
    pack, r = view.get("pack") or {}, view.get("result") or {}
    label = pack.get("label") or r.get("label") or "시나리오"
    trust, facts = [], []
    if r.get("mode") == "historical":
        dd = float(r.get("max_dd_pct") or 0.0)
        title = f"‘{label}’ 때 이 비중이었다면 최대 {_pct(abs(dd))} 떨어졌어요"
        headline = {"label": "최대 낙폭", "value": r.get("max_dd_pct"), "unit": "%", "text": _signed_pct(dd)}
        dates = r.get("dates") or []
        if dates:
            facts.append(f"{dates[0]}부터 {dates[-1]}까지 실제 시세를 그대로 재생했어요.")
        facts.append(f"그 기간 전체 수익률은 {_signed_pct(float(r.get('total_return_pct') or 0))}예요.")
        if r.get("benchmark_max_dd_pct") is not None:
            facts.append(f"같은 기간 {r.get('benchmark_label')} 최대 낙폭은 {_signed_pct(float(r['benchmark_max_dd_pct']))}예요.")
        facts.append("실제 시세를 재생해서 강도 배율은 적용하지 않았어요.")
        if prov.get("source") == "hist_replay:mock":
            trust.append(_practice("연습용 합성 시세예요 — 실제 위기 때의 성과를 말해 주지 않아요."))
        else:
            trust.append(_t(CONFIRMED, "그 기간의 적재 시세를 그대로 재생했어요."))
            trust.append(_t(UNKNOWN, "적재 시세의 출처 등급은 몰라요."))
        if r.get("dropped"):
            trust.append(_t(UNKNOWN, f"그 기간 시세가 없는 {len(r['dropped'])}개 종목은 빼고 계산했어요: "
                                     f"{', '.join(r['dropped'])}."))
        unmeasured = ["같은 일이 다시 일어날 확률", "그때와 지금의 시장 구조 차이", "거래 비용과 유동성"]
    else:
        shock = float(r.get("portfolio_shock_pct") or 0.0)
        title = (f"‘{label}’{_josa(label, '이', '가')} 오면 이 비중은 약 {_signed_pct(shock)} "
                 "움직일 거라고 추정했어요")
        headline = {"label": "추정 충격", "value": r.get("portfolio_shock_pct"), "unit": "%",
                    "text": _signed_pct(shock)}
        facts.append(f"강도 배율 {float(r.get('severity') or 1):g}배를 적용했어요.")
        rows = r.get("rows") or []
        if rows:
            worst = rows[0]
            facts.append(f"가장 크게 흔들린 종목은 {worst.get('corp_name') or worst.get('stock_code')}"
                         f"({_signed_pct(float(worst.get('shock_pct') or 0))})이에요.")
        trust.append(_t(ASSUMED, "가정 충격이에요 — 실제로 일어난 적이 없고, 종목 민감도로 추정한 값이에요."))
        for n in r.get("notes") or []:
            if "결측" in n:
                trust.append(_t(UNKNOWN, n))
        if mock_allowed():
            trust.append(_t(UNKNOWN, _DEV_STORES))
        unmeasured = ["시나리오가 일어날 확률", "종목 사이의 연쇄 효과", "충격이 선형이 아닐 때의 크기"]
    return {"title": title, "headline": headline, "facts": facts, "trust": trust, "unmeasured": unmeasured}


# ── 상관 스트레스 ─────────────────────────────────────────────────────────────

CorrParams = _subset(
    "CorrStressParams", StressCorrRequest, ("target_rho", "intensity", "confidence_level", "portfolio_value"),
    ui={
        "target_rho": _ui("위기 때 상관", question="위기 때 종목들이 얼마나 같이 움직일까요?",
                          presets=[{"label": "0.7", "value": 0.7}, {"label": "0.8", "value": 0.8},
                                   {"label": "0.9", "value": 0.9}]),
        "intensity": _ui("강도", widget="slider", ends=["없음", "완전히"],
                         help="0이면 평소 상관 그대로, 1이면 위기 상관으로 완전히 바뀌어요."),
        "confidence_level": _ui("VaR 신뢰수준", "advanced"),
        "portfolio_value": _ui("평가 금액(원)", "advanced", unit="원"),
    })


def _corr_stress(inputs: dict, p) -> pg.NodeOutput:
    r, w = inputs["returns"], inputs["weights"]
    names, weights = _names_on(w, r["returns"])
    holdings_pct(w)                                   # 모두 0 이면 여기서 멈춘다
    out = stress_correlation_report(r["returns"][names], weights, target_rho=p.target_rho,
                                    intensity=p.intensity, confidence_level=p.confidence_level,
                                    portfolio_value=p.portfolio_value)
    view = {"result": out}
    return pg.NodeOutput(values={"stress": view}, view=view)


def _explain_corr(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    b, s = r.get("base") or {}, r.get("stressed") or {}
    dv = r.get("delta_vol_pct")
    shift = r.get("corr_shift") or {}
    if dv is None:
        title = "상관이 모이면 변동성이 어떻게 되는지 봤어요"
    elif dv > 0:
        title = f"상관이 {shift.get('to_avg_rho')}로 모이면 변동성이 {_pct(dv)} 커져요"
    else:
        title = f"상관이 {shift.get('to_avg_rho')}로 모여도 변동성은 커지지 않았어요"
    facts = [f"평소 변동성은 연 {_pct(float(b.get('port_vol_pct') or 0))}예요.",
             f"평균 상관이 {shift.get('from_avg_rho')}에서 {shift.get('to_avg_rho')}로 바뀌었어요."]
    if r.get("delta_var_pct") is not None:
        facts.append(f"VaR 금액이 {_signed_pct(float(r['delta_var_pct']))} 달라졌어요.")
    ti, it = float(r.get("target_rho") or 0), float(r.get("intensity") or 0)
    trust = [_t(ASSUMED, f"위기 때 종목 간 상관이 {ti:g}로 모인다고 가정했어요(강도 {it * 100:.0f}%)."),
             _t(ASSUMED, "손실이 정규분포를 따른다고 보고 VaR 를 계산했어요.")]
    return {"title": title,
            "headline": {"label": "위기 때 변동성(연)", "value": s.get("port_vol_pct"), "unit": "%",
                         "text": _pct(float(s.get("port_vol_pct") or 0))},
            "facts": facts, "trust": trust,
            "unmeasured": ["상관이 실제로 얼마나 모일지", "꼬리 손실의 실제 모양"]}


# ── 기대수익 민감도 ───────────────────────────────────────────────────────────

SensParams = _subset("SensitivityParams", SensitivityRequest, ("bump_pct",), ui={
    "bump_pct": _ui("틀리는 크기", question="기대수익이 얼마나 틀린다고 볼까요?", unit="%p",
                    presets=[{"label": "1%p", "value": 1.0}, {"label": "2%p", "value": 2.0},
                             {"label": "5%p", "value": 5.0}]),
})


def _sensitivity(inputs: dict, p) -> pg.NodeOutput:
    from src.api.allocation_routes import _labels
    from src.engine.allocation_studio import sensitivity_matrix
    r, w = inputs["returns"], inputs["weights"]
    req = w.get("req")
    if req is None:
        raise pg.NodeFailure("이 비중에는 다시 풀어 볼 규칙(위험 회피·생각)이 없어요 — ‘비중 계산’ 노드의 "
                             "비중을 이어 주세요.")
    names, _ = _names_on(w, r["returns"])
    views = [v.model_dump() for v in (req.views or [])]
    out = sensitivity_matrix(names, r["returns"][names].values, views=views or None,
                             delta=req.delta, tau=req.tau, bump_pct=p.bump_pct)
    basis = "bl" if views else "mvo"
    view = {"result": {**out, "labels": _labels(names)}, "model": req.model, "basis": basis,
            "has_constraints": bool(req.constraints)}
    return pg.NodeOutput(values={}, view=view)


def _explain_sensitivity(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    names, labels, m = r.get("names") or [], r.get("labels") or {}, r.get("matrix") or []
    best = (0.0, None, None)
    for i, row in enumerate(m):
        for j, d in enumerate(row):
            if abs(d) > abs(best[0]):
                best = (d, i, j)
    facts, trust = [], []
    bump = float(getattr(params, "bump_pct", 0) or 0)
    if best[1] is not None:
        ni, nj = names[best[1]], names[best[2]]
        facts.append(f"{labels.get(ni, ni)}의 기대수익을 {bump:g}%p 높이면 {labels.get(nj, nj)} 비중이 "
                     f"{best[0]:+.2f}%p 바뀌어요.")
    trust.append(_t(CONFIRMED, "같은 수익률과 같은 생각(뷰)으로 다시 풀었어요."))
    if view.get("model") != view.get("basis"):
        trust.append(_t(ASSUMED, f"이 점검은 ‘{MODEL_PLAIN.get(view.get('basis'), view.get('basis'))}’ 기준으로 "
                                 f"다시 풀어요 — 고른 방식(‘{MODEL_PLAIN.get(view.get('model'), view.get('model'))}’)의 "
                                 "민감도와 다를 수 있어요."))
    if view.get("has_constraints"):
        trust.append(_t(ASSUMED, "비중 제약은 이 점검에 넣지 않았어요."))
    return {"title": "기대수익이 조금 틀려도 비중이 얼마나 바뀌는지 봤어요",
            "headline": {"label": "가장 큰 비중 변화", "value": best[0], "unit": "%p", "text": f"{best[0]:+.2f}%p"},
            "facts": facts, "trust": trust,
            "unmeasured": ["공분산이 틀렸을 때의 민감도", "여러 종목이 함께 틀릴 때"]}


# ── 팩터 성격 ────────────────────────────────────────────────────────────────

def _factor_xray(inputs: dict, p) -> pg.NodeOutput:
    from src.data.snapshot_db import sample_factors
    pct = holdings_pct(inputs["weights"])
    # 라우트는 DB 표본이 비면 mock 모드에서 합성 표본을 쓴다 — 그 사실을 계보로 나른다.
    practice = mock_allowed() and not (sample_factors(500) or [])
    try:
        out = allocation_factor_xray(XrayRequest(holdings=pct))
    except HTTPException as e:
        raise pg.NodeFailure(f"팩터 성격을 계산하지 못했어요 — {e.detail}") from e
    if out.get("error"):
        raise pg.NodeFailure(str(out.get("message")))
    view = {"result": out}
    return pg.NodeOutput(values={}, view=view,
                         tags={"practice": practice, "sources": ["factor_xray:" + ("mock" if practice else "db")]})


def _explain_xray(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    fs = r.get("factors") or []
    if not fs:
        return {"title": "잴 수 있는 팩터가 없었어요",
                "trust": [_t(UNKNOWN, "종목의 팩터 값이나 비교할 유니버스 표본이 모자라 재지 못했어요.")],
                "unmeasured": ["모든 팩터 노출"]}
    top = max(fs, key=lambda f: abs(float(f["portfolio_z"]) - float(f["benchmark_z"])))
    facts = [f"{f['label']}: 이 비중 {float(f['portfolio_z']):+.2f}σ · 기준 {float(f['benchmark_z']):+.2f}σ"
             for f in sorted(fs, key=lambda f: -abs(float(f["portfolio_z"]) - float(f["benchmark_z"])))[:3]]
    trust = [_t(CONFIRMED, f"유니버스 표본 {fs[0].get('n_universe')}종목과 비교했어요.")]
    for f in fs:
        if float(f.get("coverage_pct") or 0) < 99.5:
            trust.append(_t(UNKNOWN, f"{f['label']}{_josa(f['label'], '은', '는')} 데이터가 없는 종목이 있어 "
                                     f"비중의 {_pct(float(f['coverage_pct']))}만 쟀어요."))
    if mock_allowed():
        trust.append(_t(UNKNOWN, _DEV_STORES))
    return {"title": f"이 비중은 ‘{top['label']}’ 쪽으로 가장 기울어 있어요",
            "headline": {"label": f"{top['label']} 노출", "value": top["portfolio_z"], "unit": "σ",
                         "text": f"{float(top['portfolio_z']):+.2f}σ"},
            "facts": facts, "trust": trust,
            "unmeasured": ["이 팩터들이 앞으로 돈이 될지(예측력)", "시점별 노출 변화"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("scenario_stress", "시나리오 충격", stage="check", plain_label="상황에 넣어 보기",
                    plain_description="과거 위기나 가정한 충격에 이 비중을 넣어 봐요.",
                    inputs=(P("weights", "Weights"),), outputs=(P("stress", "StressReport"),),
                    run=_scenario_stress, params_model=ScenarioParams, explain=_explain_scenario,
                    category="확인", description="역사 리플레이 · M8 가정 충격 · 국내 시나리오팩(/stress · /kr-scenario 와 같다)."),
        pg.NodeSpec("corr_stress", "상관 스트레스", stage="check", plain_label="상관이 치솟으면",
                    plain_description="위기 때 종목들이 같이 움직이면 흔들림이 얼마나 커지는지 봐요.",
                    inputs=(P("returns", "Returns"), P("weights", "Weights")),
                    outputs=(P("stress", "StressReport"),), run=_corr_stress, params_model=CorrParams,
                    explain=_explain_corr, category="확인",
                    description="위기 상관 수렴 가정 → 변동성·VaR·기여 VaR 변화(/stress-correlation 과 같다)."),
        pg.NodeSpec("sensitivity", "기대수익 민감도", stage="check", plain_label="기대수익이 틀리면?",
                    plain_description="기대수익이 조금 틀렸을 때 비중이 얼마나 바뀌는지 봐요.",
                    inputs=(P("returns", "Returns"), P("weights", "Weights")), outputs=(),
                    run=_sensitivity, params_model=SensParams, explain=_explain_sensitivity, category="확인",
                    description="자산별 μ +bump → 재최적화 비중 변화 N×N(/sensitivity 와 같다)."),
        pg.NodeSpec("factor_xray", "팩터 X-ray", stage="check", plain_label="어떤 성격인가요?",
                    plain_description="가치·모멘텀·규모 같은 성격이 어디로 기울었는지 봐요.",
                    inputs=(P("weights", "Weights"),), outputs=(),
                    run=_factor_xray, explain=_explain_xray, category="확인",
                    description="가중 팩터 z 노출 vs 유니버스·KOSPI200(/factor-xray 와 같다)."),
    ):
        registry.register(spec)
