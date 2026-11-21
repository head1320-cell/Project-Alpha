"""조건 종류의 ★값의 원천★ — 지금 계산할 수 있는가 (2026-11-14 · 합성값 전수 감사 §3)

스크리너의 조건 종류 가운데 둘은 실데이터 원천이 없다 — 값이 합성(난수)에서만 나온다:

- `event`   실적 발표·배당락까지 남은 날 (`src/data/event_calendar.py`)
- `z_score` 종목 자신의 과거 분포 대비 위치 (`src/engine/z_score.py`)

mock 모드에서는 그 합성값으로 계산한다. 운영에서는 ★계산하지 않는다★ — 그 조건을 짚어 사유를 낸다.
조용히 '통과 0건'으로 만들지 않는다(과거 시점 선별의 선례 `pit_fields.py` 와 같은 결정: 막는다).

판정은 이 파일 하나다. 부르는 자리 셋 — 조건 검증(`FilterCondition.validate`) · 필터 적용(`apply_filter_ast`) ·
스크리너 진입(`ValuationScreener.run`, 평가 전에 본다). 원천을 붙이면 `UNSOURCED_KINDS` 에서 그 종류를 지운다.
"""
from __future__ import annotations

from src.data.mock_gate import mock_allowed

#: 실데이터 원천이 없는 조건 종류 → (화면 이름, 사유). `tests/test_condition_source_gate.py` 가 동작에 묶는다.
UNSOURCED_KINDS: dict[str, tuple[str, str]] = {
    "event": ("이벤트", "실적 발표·배당락 일정의 실데이터 원천이 연결돼 있지 않습니다"),
    "z_score": ("Z-Score", "종목별 과거 분포의 실데이터 원천이 연결돼 있지 않습니다"),
}


def unsourced_reason(kind: str | None) -> str | None:
    """이 조건 종류를 지금 계산할 수 없으면 그 사유(화면 문장), 계산할 수 있으면 `None`."""
    meta = UNSOURCED_KINDS.get(kind or "")
    if meta is None or mock_allowed():
        return None
    label, why = meta
    return f"조건 종류 ‘{label}’ 계산 불가 — {why}."


def _conditions(group):
    yield from getattr(group, "conditions", None) or []
    for g in getattr(group, "groups", None) or []:
        yield from _conditions(g)


def unsourced_conditions(group) -> list[str]:
    """조건 묶음(중첩 포함)에서 지금 계산할 수 없는 조건 종류의 사유 목록 — 비어 있으면 통과."""
    out: list[str] = []
    for c in _conditions(group) if group is not None else ():
        why = unsourced_reason(getattr(c, "kind", None))
        if why and why not in out:
            out.append(why)
    return out


class ConditionSourceUnavailable(ValueError):
    """원천이 없는 조건 종류를 쓴 요청 — 계산하지 않는다. 문장은 화면에 그대로 실린다."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__(" ".join(self.reasons))
