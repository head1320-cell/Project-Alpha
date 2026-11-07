"""03 CAUSAL — 방향성 매크로 그래프 $G_{macro}$ (M1-M)
==============================================================================
프론티어: DeePM — Vectorized Variable Selection Network + Directed Delay Causal Sieve.
대체:     `src/engine/causal_graph.py` 의 Granger 유의 간선 + 지연.

★대체 엔진이 무엇을 말하고 무엇을 말하지 않는지 분명히 한다★
Granger 인과는 "A 의 과거가 B 의 미래를 예측하는 데 도움이 되는가" 이지 **개입 인과가
아니다.** 공통 원인이 있으면 둘 다 유의하게 나온다. 이 구분을 노트에 적지 않으면
사용자는 그래프의 화살표를 "A 를 움직이면 B 가 움직인다" 로 읽는다.
"""

from __future__ import annotations

from typing import Any

from src.engine.macro_models.base import Engine, Studio, load_series, ok, series_span, unavailable

_INPUTS = ("KOSPI", "USD_KRW", "KR_3Y", "KR_10Y", "VIXCLS", "T10Y2Y",
           "BAMLH0A0HYM2", "M2SL", "KR_CPI", "INDPRO")

STUDIO = Studio(
    id="causal-deepm",
    label="CAUSAL",
    question="어떤 매크로 변수가 어떤 변수를 앞서 움직이는가?",
    frontier=Engine(
        name="DeePM (VSN + Delay Causal Sieve)",
        kind="frontier",
        summary="변수 선택망 + 지연 인과 체 — 방향성 그래프와 지연을 함께 학습",
        requires=("torch", "frontier_sample"),
    ),
    substitute=Engine(
        name="Granger 유의 간선",
        kind="substitute",
        summary="statsmodels 그레인저 검정 — 예측적 선행관계와 지연 (개입 인과 아님)",
        requires=("statsmodels", "causal_graph", "causal_sample"),
    ),
    inputs=_INPUTS,
)


def run(months: int = 60, **_: Any) -> dict[str, Any]:
    series = load_series(_INPUTS, months)
    if len(series) < 3:
        have = ", ".join(sorted(series)) or "없음"
        return unavailable(
            STUDIO.substitute.name,
            f"인과 그래프를 그리려면 시리즈가 3개 이상 필요합니다 — 지금 {len(series)}개 ({have}).")

    from src.engine.causal_graph import granger_edges
    g = granger_edges(series)
    if not g.get("available"):
        return unavailable(STUDIO.substitute.name,
                           g.get("note") or "그레인저 검정을 돌릴 수 없습니다.")

    return ok(
        STUDIO.substitute.name,
        {"nodes": g.get("nodes", []), "edges": g.get("edges", []),
         "n_series": len(series)},
        note=("★그레인저 인과는 개입 인과가 아닙니다★ 화살표는 '과거가 미래를 예측하는 데 "
              "도움이 된다' 는 뜻이고, 공통 원인이 있으면 양쪽 모두 유의하게 나옵니다. "
              "이 그래프로 '움직이면 따라 움직인다' 를 주장하지 마세요."),
        span=series_span(series, months),
    )
