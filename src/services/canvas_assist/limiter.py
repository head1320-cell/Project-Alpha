"""사용자별 시간당 호출 한도 — 프로세스 안 기억(`uvicorn --workers 1` 전제, 재시작하면 비워진다).

세는 것은 ★Claude 를 실제로 부른 횟수★다. 캐시 적중은 부르지 않으니 세지 않는다(부르는 쪽 `service` 가 지킨다).
"""
from __future__ import annotations

import threading
from collections import deque


class HourlyLimiter:
    WINDOW = 3600.0

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, user: str, limit: int, now: float) -> bool:
        """한도 안이면 이번 호출을 적고 True. 지난 한 시간(미끄러지는 창) 안의 호출만 센다."""
        with self._lock:
            q = self._hits.setdefault(user, deque())
            while q and now - q[0] >= self.WINDOW:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
