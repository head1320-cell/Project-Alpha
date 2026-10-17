"""JSON 이 실을 수 없는 값의 정직한 처리 — 공용 (P3-1 에서 추출)

★조용히 지우지 않는다★ `None` 으로만 바꾸면 "값이 없다" 와 "무한이다" 가 같아
보인다. 무한 손익비는 **손실 거래가 0이었다는 정보**이고, 발산한 비율은 **분모가
0이었다는 정보**다. 그래서 바꾸되 **어느 키가 그랬는지 이름을 남긴다.**

`company_routes` 가 백테스트 통계(`profit_factor=inf`)로 500 을 맞고 만든 것을
`allocation_routes` 가 같이 쓰게 옮겼다 — 같은 산수를 두 곳에 두지 않는다.
"""
from __future__ import annotations

import math
from typing import Any

NON_FINITE_KEY = "non_finite"


def finite(payload: Any) -> tuple[Any, list[str]]:
    """(정제된 payload, 비유한 값이었던 경로 목록)."""
    dropped: list[str] = []

    def walk(o: Any, path: str) -> Any:
        if isinstance(o, float):
            if math.isfinite(o):
                return o
            dropped.append(f"{path.lstrip('.')}={o}")
            return None
        if isinstance(o, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
        return o

    return walk(payload, ""), dropped


def finite_payload(payload: dict) -> dict:
    """dict 응답용 — 비유한 값이 있었으면 `non_finite` 로 이름을 함께 싣는다."""
    out, dropped = finite(payload)
    if dropped and isinstance(out, dict):
        out[NON_FINITE_KEY] = dropped
    return out
