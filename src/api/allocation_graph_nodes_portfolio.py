"""AAS 그래프 — 여러 전략을 한 포트폴리오로 (BM C2) · ★기존 슬리브 결합을 그대로 부른다★
==============================================================================
설계 `docs/superpowers/specs/2026-09-27-canvas-workspace-design.md` §C2. 테스트 `tests/test_graph_portfolio_combine.py`.

캔버스의 전략 상자마다 비중(Weights)이 나오고, 이 노드가 그것을 한 포트폴리오로 합친다.
- 배분 규칙은 `sleeve_combine.combine_sleeves` **그대로**다(방식·수식 불변 — 배분 정책 변경이 아니다). 바뀐 것은 입력 수(2~8)와 이름뿐.
- 전략 이름은 파라미터 `labels`(포트 → 이름) — 화면이 전략 상자 이름으로 채운다. 비우면 "전략 1"…(포트 번호 그대로).
- 전략 사이 상관은 **같은 수익 행렬**로 `sleeve_analytics` 를 불러 구한다(두 번 읽지 않는다).
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _labels, _ui, weights_value
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg

P = pg.Port
N_PORTS = 8
PORTS = tuple(f"s{i}" for i in range(1, N_PORTS + 1))

#: `sleeve_combine` 노드와 같은 선택지(같은 엔진 방식) — 쉬운 이름도 같다.
METHODS = {"risk_parity": "위험 똑같이", "equal": "똑같이", "inverse_vol": "덜 흔들리는 쪽에 더",
           "min_var": "흔들림 최소", "hrp": "비슷한 것끼리 묶어"}
#: 엔진이 풀리지 않으면 역변동성으로 바꾸는 방식 — 그 경우인지 결과에 표시되지 않는다.
SILENT_FALLBACK = ("min_var", "hrp")


class PortfolioCombineParams(BaseModel):
    model_config = _FORBID
    method: Literal[tuple(METHODS)] = Field("risk_parity", json_schema_extra={"x-ui": _ui(
        "합치는 방식", question="전략끼리 어떻게 나눌까요?", widget="cards", options=METHODS)})
    labels: dict[str, str] = Field(default_factory=dict, json_schema_extra={"x-ui": _ui(
        "전략 이름", tier="advanced", help="포트(s1~s8)마다 전략 이름. 캔버스가 전략 상자 이름으로 채워요.")})

    @field_validator("labels")
    @classmethod
    def _known_ports(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if k not in PORTS]
        if bad:
            raise ValueError(f"없는 포트: {', '.join(bad)} (s1~s{N_PORTS})")
        long = [k for k, x in v.items() if not x.strip() or len(x) > 40]
        if long:
            raise ValueError(f"전략 이름은 1~40자: {', '.join(long)}")
        return {k: x.strip() for k, x in v.items()}


def _portfolio_combine(inputs: dict, p: PortfolioCombineParams) -> pg.NodeOutput:
    from src.engine import sleeve_combine as sc
    sleeves, ports = [], []
    for i, port in enumerate(PORTS, start=1):
        w = inputs.get(port)
        if w is None:
            continue
        sleeves.append({"name": p.labels.get(port) or f"전략 {i}",
                        "weights": {n: float(x) * 100.0 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}})
        ports.append(port)
    names = [s["name"] for s in sleeves]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise pg.NodeFailure(f"전략 이름이 겹쳐요({', '.join(dup)}) — 이름이 같으면 전략별 몫을 나눌 수 없어요. 전략 상자 이름을 바꿔 주세요.")
    if len(sleeves) < 2:
        raise pg.NodeFailure("전략이 두 개 이상 있어야 합칠 수 있어요.")
    ret = sc._load_ret_matrix(sleeves)
    out = sc.combine_sleeves(sleeves, method=p.method, ret_matrix=ret)
    if out.get("error"):
        raise pg.NodeFailure(str(out.get("message")))
    ana = sc.sleeve_analytics(sleeves, ret_matrix=ret, weights=out["sleeve_allocation"])
    cm = ana.get("correlation") or {}
    corr = None if ana.get("error") else {"labels": names, "matrix": [[cm[a][b] for b in names] for a in names]}
    cw = out["combined_weights_pct"]
    codes = list(cw)
    arr = np.array([cw[c] / 100.0 for c in codes], dtype=float)
    strategies = [{"port": port, "label": name, "share_pct": out["sleeve_allocation"][name],
                   "risk_pct": out["risk_contribution_pct"][name], "vol_pct": out["sleeve_vol_pct"][name],
                   "n_holdings": len(s["weights"])} for port, name, s in zip(ports, names, sleeves)]
    view = {"result": out, "labels": _labels(codes), "strategies": strategies, "correlation": corr,
            "correlation_reason": ana.get("message") if ana.get("error") else None}
    return pg.NodeOutput(values={"weights": weights_value(codes, arr)}, view=view,
                         tags={"practice": mock_allowed(), "sources": ["portfolio_combine"]})


def _explain(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    facts = [f"{s['label']}: 몫 {s['share_pct']:.1f}% · 위험 분담 {s['risk_pct']:.1f}%" for s in view.get("strategies") or []]
    trust = [_t(CONFIRMED, f"{r.get('n_sleeves')}개 전략의 수익 흐름으로 몫을 정하고 종목 비중을 합쳤어요(묶음 합치기와 같은 계산).")]
    if r.get("method") in SILENT_FALLBACK:
        trust.append(_t(UNKNOWN, "이 방식은 계산이 안 풀리면 엔진이 역변동성으로 바꿔요 — 이 결과가 그 경우인지는 표시되지 않아요."))
    trust.append(_t(ASSUMED, "전략 수익은 각 전략의 지금 비중을 과거에 고정해 만든 흐름이에요 — 전략이 과거에 실제로 낸 성과가 아니에요."))
    if view.get("correlation") is None:
        trust.append(_t(UNKNOWN, f"전략 사이 상관을 재지 못했어요 — {view.get('correlation_reason') or '사유 없음'}"))
    rows = [x for x in (view.get("strategies") or []) if isinstance(x.get("share_pct"), (int, float))]
    top = max(rows, key=lambda x: x["share_pct"]) if rows else None
    headline = None if top is None else {"label": f"{top['label']} 몫", "value": top["share_pct"], "unit": "%",
                                         "text": f"가장 큰 몫은 {top['label']} {top['share_pct']:.1f}%"}
    return {"title": f"{r.get('n_sleeves')}개 전략을 {r.get('n_stocks')}종목 포트폴리오로 합쳤어요", "headline": headline, "facts": facts,
            "trust": trust, "unmeasured": ["전략 사이 상관이 앞으로 유지될지", "전략마다 다른 리밸런싱 주기"]}


def glance(view: dict) -> dict | None:
    from src.api.allocation_graph_glance import _bars_from
    alloc = (view.get("result") or {}).get("sleeve_allocation")
    return _bars_from(alloc, caption="전략별 몫")


def register(registry: pg.Registry) -> None:
    registry.register(pg.NodeSpec(
        "portfolio_combine", "포트폴리오 합치기", plain_label="전략 합치기", category="배분", stage="build",
        plain_description="전략 여러 개의 비중을 한 포트폴리오로 합쳐요. 전략마다 몫과 위험 분담을 보여 줘요.",
        description="전략(슬리브) 2~8개 결합 — sleeve_combine.combine_sleeves 그대로(/combine-sleeves 와 같다).",
        inputs=tuple(P(port, "Weights", required=i < 2) for i, port in enumerate(PORTS)),
        outputs=(P("weights", "Weights"),), run=_portfolio_combine, params_model=PortfolioCombineParams,
        explain=_explain, glance=glance))
