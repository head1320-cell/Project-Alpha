"""목표 표(AI1) — '목표로 시작'의 네 목표를 ★서버 문장으로★ 근거에 싣는다(사용자 결정 2026-10-23: 네 목표를 설계에 기억 + 고치기).

화면 `frontend/src/entities/portfolio-graph/goals.ts` 의 `GOALS` 와 키·제목·설명이 같다(`tests/test_ai1_goal.py` 패리티).
문서 `meta.goal` 은 화면이 보낸 값이라 ★키로만★ 받는다 — 모르는 키·형식이 틀린 값은 없음(`None`). 문장에는 숫자가 없다(숫자 검사를 넓히지 않는다).
"""
from __future__ import annotations

from typing import Any

GOALS: dict[str, dict[str, str]] = {
    "build": {"title": "새 포트폴리오 만들기", "sub": "종목을 선택하면 비중을 산출하고 위험과 과거 성과를 함께 분석합니다."},
    "check": {"title": "비중의 위험 점검", "sub": "지정 비중의 일간 손실 위험(VaR)과 위기 충격 시 손실을 점검합니다."},
    "timing": {"title": "타이밍 규칙 시험", "sub": "타이밍 신호로 노출을 축소했을 때의 목표 비중과 주문 목록을 산출합니다. 주문은 전송하지 않습니다."},
    "company": {"title": "단일 기업 심층 분석", "sub": "한 기업의 적정가를 복수 모형으로 산출하고 가치 분포를 분석합니다."},
}


def goal_of(graph: Any) -> dict[str, str] | None:
    meta = graph.get("meta") if isinstance(graph, dict) else None
    key = meta.get("goal") if isinstance(meta, dict) else None
    if not isinstance(key, str) or key not in GOALS:
        return None
    return {"key": key, **GOALS[key]}
