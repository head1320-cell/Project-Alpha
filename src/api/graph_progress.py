"""그래프 계산 진행 곁줄 (CF5a) — `/run` 은 그대로, 진행만 곁으로
==============================================================================
캔버스의 실행 줄은 노드마다 대기 → 계산 중 → 완료·막힘·실패를 보인다. `/run` 응답은 바꾸지 않고(그 JSON 을 읽는 곳이 많다)
화면이 만든 실행 id(`rid`)의 통에 엔진 이벤트를 넣고, `GET /progress/{rid}`(SSE)가 그 통을 읽는다.

- ★프로세스 안 통이다★ — `uvicorn --workers 1` 전제(캐시·쿼터·적재 상태처럼 프로세스 로컬). 프로세스가 여럿이면 곁줄은 비고
  화면은 "진행을 받지 못했어요"라고 말한다 — 계산과 결과는 `/run` 이 그대로 낸다(진행은 보기일 뿐, 최종 상태는 보고서가 정한다).
- 늦게 붙어도 쌓인 것부터 다시 준다(화면이 곁줄을 먼저 열지만 순서는 보장되지 않는다).
- 시작하지 않은 rid 는 `wait_s` 뒤 `{"type": "timeout"}` 으로 끝낸다 · 열린 통은 `max_open` 개까지(넘치면 가장 오래 닫힌 것부터 비움) ·
  닫힌 통은 `keep_s` 동안만 남긴다.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

#: 실행 id — 화면이 만든다(영숫자·하이픈 8~64자). 경로·질의 둘 다 이 형식만 받는다.
RID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


@dataclass
class _Box:
    created: float
    events: list[dict] = field(default_factory=list)
    closed_at: float | None = None


class ProgressHub:
    def __init__(self, max_open: int = 64, keep_s: float = 120.0, wait_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max_open, self._keep_s, self._wait_s, self._clock = max_open, keep_s, wait_s, clock
        self._boxes: dict[str, _Box] = {}
        self._cond = threading.Condition()

    def _box(self, rid: str) -> _Box:
        """잠금 안에서만 부른다. 오래 닫힌 통을 비우고, 없으면 만든다(상한을 넘으면 가장 오래 닫힌 것 → 가장 오래된 것부터 비움)."""
        now = self._clock()
        for k in [k for k, b in self._boxes.items() if b.closed_at is not None and now - b.closed_at > self._keep_s]:
            del self._boxes[k]
        box = self._boxes.get(rid)
        if box is None:
            while len(self._boxes) >= self._max_open:
                closed = [k for k, b in self._boxes.items() if b.closed_at is not None]
                pool = closed or list(self._boxes)
                del self._boxes[min(pool, key=lambda k: self._boxes[k].closed_at or self._boxes[k].created)]
            box = self._boxes[rid] = _Box(created=now)
        return box

    def emit(self, rid: str, event: dict) -> None:
        with self._cond:
            self._box(rid).events.append(event)
            self._cond.notify_all()

    def close(self, rid: str) -> None:
        with self._cond:
            self._box(rid).closed_at = self._clock()
            self._cond.notify_all()

    def follow(self, rid: str) -> Iterator[dict]:
        """쌓인 이벤트부터 내주고, 닫히면 `end`. 아무것도 오지 않은 채 `wait_s` 가 지나면 `timeout`."""
        i, since = 0, self._clock()
        while True:
            with self._cond:
                box = self._box(rid)
                while i >= len(box.events) and box.closed_at is None:
                    left = self._wait_s - (self._clock() - since)
                    if not box.events and left <= 0:
                        break
                    self._cond.wait(timeout=left if not box.events else 1.0)
                    box = self._box(rid)
                batch, i = box.events[i:], len(box.events)
                closed, empty = box.closed_at is not None, not box.events
            if empty and not closed:
                yield {"type": "timeout"}
                return
            yield from batch
            if closed:
                yield {"type": "end"}
                return
