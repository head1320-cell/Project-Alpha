"""AAS 그래프 — 지금 비중 노드 (BL4) · ★마법사 STRESS 의 '지금 보유 대 목표' 를 캔버스로 옮긴다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL4 B4-1 ④. 테스트 `tests/test_allocation_graph_bl4.py`.

유니버스 노드의 '지금 비중' 을 Weights 로 낸다. 이것을 충격 노드에 이으면 지금 들고 있는 포트폴리오를, 옵티마이저
비중을 이으면 목표 포트폴리오를 흔든다 — 두 노드를 나란히 두면 마법사 STRESS 의 두 열이 된다.

- gross(Σ|w|)로 나눠 합 100% — `/analyze` 가 지금 비중을 분석하는 `PortfolioAnalyzer` 와 같은 규칙. ★부호 보존★
- ★없으면 만들지 않는다★ 지금 비중을 안 적었으면 균등 비중으로 바꿔치기하지 않고 사유와 함께 실패한다.
- 공분산·규칙을 싣지 않는다 — 하류 위험 분해·정책 백테스트는 기존 규칙대로 사유와 함께 실패한다.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _labels, weights_value
from src.engine import portfolio_graph as pg

P = pg.Port


class CurrentWeightsParams(BaseModel):
    model_config = _FORBID


def _current_weights(inputs: dict, p: CurrentWeightsParams) -> pg.NodeOutput:
    u = inputs["universe"]
    tickers = [str(t) for t in u.get("tickers") or []]
    given = u.get("weights")
    if not given:
        raise pg.NodeFailure("유니버스 노드에 ‘지금 비중’을 적지 않았어요 — 균등 비중으로 바꿔 계산하지 않아요. "
                             "유니버스 노드 설정의 ‘지금 비중’(전문가)에 들고 있는 비중을 넣어 주세요.")
    outside = [str(k) for k in given if str(k) not in tickers]
    if outside:
        raise pg.NodeFailure(f"‘지금 비중’의 종목 {', '.join(outside)} 이(가) 유니버스 종목 목록에 없어요 — "
                             "목록에 넣거나 비중에서 빼 주세요.")
    raw = np.array([float(given.get(t, 0.0)) for t in tickers], dtype=float)
    gross = float(np.abs(raw).sum())
    if not np.isfinite(raw).all() or gross <= 0:
        raise pg.NodeFailure("‘지금 비중’이 모두 0이라 들고 있는 포트폴리오가 없어요.")
    w = raw / gross
    pct = {t: round(float(x) * 100.0, 6) for t, x in zip(tickers, w)}
    view = {"weights": pct, "labels": _labels(tickers), "given": {str(k): float(v) for k, v in given.items()},
            "basis": "유니버스 노드의 ‘지금 비중’을 Σ|w| 로 나눠 합 100% 로 맞췄어요.",
            "zero_filled": [t for t in tickers if t not in given]}
    return pg.NodeOutput(values={"weights": weights_value(tickers, w)}, view=view,
                         tags={"sources": ["universe:current_weights"]})


def _explain_current(view: dict, prov: dict, params: Any) -> dict:
    w = view.get("weights") or {}
    facts = [f"{len(w)}종목 — 유니버스 노드의 ‘지금 비중’을 그대로 썼어요(합 100% 로 맞춤)."]
    zero = view.get("zero_filled") or []
    if zero:
        facts.append(f"비중을 적지 않은 {len(zero)}종목은 0% 예요.")
    trust = [_t(CONFIRMED, "사용자가 적은 비중이에요 — 계산으로 만든 값이 아니에요."),
             _t(ASSUMED, "적은 비중이 지금 계좌와 같은지는 확인하지 않았어요(계좌를 읽지 않아요)."),
             _t(UNKNOWN, "공분산을 함께 내지 않아요 — 위험 분해에 이으면 사유와 함께 멈춰요.")]
    return {"title": "지금 들고 있는 비중이에요", "facts": facts, "trust": trust,
            "unmeasured": ["지금 비중의 기대 수익·위험(공분산) — 목표와 나란히 보려면 충격 노드에 이어요"]}


def register(registry: pg.Registry) -> None:
    registry.register(pg.NodeSpec(
        "current_weights", "지금 비중", plain_label="지금 들고 있는 비중", category="배분", stage="build",
        plain_description="유니버스에 적은 지금 비중을 그대로 내요. 충격 노드에 이으면 목표 비중과 나란히 흔들어 볼 수 있어요.",
        inputs=(P("universe", "Universe"),), outputs=(P("weights", "Weights"),), run=_current_weights,
        params_model=CurrentWeightsParams, explain=_explain_current,
        description="유니버스 weights → Weights(gross 정규화 · 부호 보존) · 없으면 균등으로 바꾸지 않고 실패."))
