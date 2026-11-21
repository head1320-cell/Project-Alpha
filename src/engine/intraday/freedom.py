"""자유도 공시(G3 · 구현 계획 §4) — 이 자료로 고를 수 있었던 값의 수를 거래 수 곁에 적는다.

답하는 물음은 하나다: **이 결과를 내기까지 손잡이가 몇 개였고 거래는 몇 건이었나.** 기술일 뿐 기준이 아니다 —
값 하나당 거래가 몇 건이면 충분한지 정하지 않고(그 경계는 자료 · 규칙마다 다르다 — 이중하강 논쟁) 관문의 상태를 바꾸지 않는다.

세는 것
- 규칙: `rules.free_values` — 틀의 매개변수 전부 · 직접 구성의 상수 · 지표 매개변수(기본값 포함) · 연산 덧칸.
- 포지션: 정한 칸(None 이 아닌 칸 — 기본값을 그대로 둔 칸도 센다). 진입 금액은 세지 않는다(크기일 뿐 신호의 모양을 바꾸지 않는다).
- 비용 가정은 받지 않는다(전략의 손잡이가 아니라 가정이다 — 비용 민감도 관문이 따로 본다).
"""
from __future__ import annotations

from typing import Any

from src.engine.intraday import rules

#: 포지션 설정 가운데 손잡이로 세는 칸(문의 `PositionBody` 와 같은 이름 · 진입 금액 `amount` 는 뺀다).
POSITION_KNOBS = ("stop_pct", "target_pct", "trail_pct", "time_exit", "entry_from", "entry_until", "max_entries_per_ticker",
                  "max_open_positions", "daily_loss_limit", "cooldown_after_loss_min")

#: 이 공시가 답하는 물음(어떤 물음에 답했는지 먼저 밝힌다 — CLAUDE.md §2). 셈의 물음이며 표현력 · 예측력 · 경제적 가치의 물음이 아니다.
QUESTION = "이 결과를 낸 설정에 조정 가능한 값은 몇 개이고 값 하나당 거래는 몇 건인가"
BASIS = ("규칙의 값(틀의 매개변수 · 직접 구성의 상수 · 지표 매개변수 · 연산의 봉 수와 시각)과 포지션 설정 가운데 정한 칸을 셉니다. "
         "기본값을 그대로 둔 칸도 셉니다. 그 값도 이 자료로 고를 수 있었던 값입니다. 진입 금액과 비용 가정은 세지 않습니다.")
LIMIT = ("값 하나당 거래 수는 기술이며 기준이 아닙니다. 몇 건이면 넉넉한지 정하지 않으며 관문의 상태를 바꾸지 않습니다. "
         "이 설정에 이르기까지 다른 값을 넣어 본 횟수는 시행 횟수가 따로 셉니다.")


def disclose(kind: str, params: dict | None, position: dict, *, trades: int | None) -> dict[str, Any]:
    """규칙 · 포지션 설정과 거래 수 → 공시(수 · 이름 · 서버 문장). 규칙이 검사를 지나지 못하면 `rules.RuleError` 그대로."""
    rule = rules.free_values(kind, params)
    named = [key for key in POSITION_KNOBS if position.get(key) is not None]
    count = rule["count"] + len(named)
    per = trades / count if trades and count else None
    head = f"조정 가능한 값 {count}개(규칙 {rule['count']} · 포지션 {len(named)})"
    if trades is None:
        message = f"{head} · 거래 수는 알 수 없습니다."
    elif count == 0:
        message = f"조정 가능한 값이 없습니다(규칙 0 · 포지션 0). 거래는 {trades:,}건입니다."
    elif trades == 0:
        message = f"{head} · 거래 0건입니다. 거래가 없어 값 하나당 거래 수를 계산하지 않았습니다."
    else:
        message = f"{head} · 거래 {trades:,}건 · 값 하나당 거래 {per:.1f}건입니다."
    return {"rule": rule["count"], "rule_names": rule["names"], "position": len(named), "position_names": named,
            "count": count, "trades": trades, "per_value": per, "question": QUESTION, "message": message, "basis": BASIS,
            "limit": LIMIT}
