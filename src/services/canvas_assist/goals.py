"""목표 표(AI1) — '목표로 시작'의 네 목표를 ★서버 문장으로★ 근거에 싣는다(사용자 결정 2026-10-23: 네 목표를 설계에 기억 + 고치기).

화면 `frontend/src/entities/portfolio-graph/goals.ts` 의 `GOALS` 와 키·제목·설명이 같다(`tests/test_ai1_goal.py` 패리티).
문서 `meta.goal` 은 화면이 보낸 값이라 ★키로만★ 받는다 — 모르는 키·형식이 틀린 값은 없음(`None`). 문장에는 숫자가 없다(숫자 검사를 넓히지 않는다).
"""
from __future__ import annotations

from typing import Any

GOALS: dict[str, dict[str, str]] = {
    "build": {"title": "새 포트폴리오 만들기", "sub": "종목을 고르면 비중을 나누고, 위험과 과거 성과를 함께 봐요."},
    "check": {"title": "비중의 위험 점검", "sub": "정한 비중이 하루에 얼마나 잃을 수 있는지, 위기 충격에서 어떤지 봐요."},
    "timing": {"title": "타이밍 규칙 시험", "sub": "타이밍 신호로 노출을 줄였을 때의 목표 비중과 주문 목록을 봐요. 주문은 나가지 않아요."},
    "company": {"title": "기업 하나 깊게", "sub": "한 기업의 적정가를 여러 모델로 보고, 가치가 어디쯤 몰려 있는지 봐요."},
}


def goal_of(graph: Any) -> dict[str, str] | None:
    meta = graph.get("meta") if isinstance(graph, dict) else None
    key = meta.get("goal") if isinstance(meta, dict) else None
    if not isinstance(key, str) or key not in GOALS:
        return None
    return {"key": key, **GOALS[key]}
