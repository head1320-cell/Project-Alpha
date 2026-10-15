"""
KIS Gateway — Priority Queue 기반 Rate Limiter
====================================================
KIS 호출을 큐로 직렬화 + 우선순위 부여. 모든 KIS 호출은 이 게이트웨이를 통과.

핵심:
  · 단일 큐로 호출 순서 보장 (race condition 차단)
  · Priority Queue로 긴급 호출 (Kill switch 취소) 우선
  · Rate limit 엄격 준수 (초당 N회, KIS 한도 20 기본 18)
  · 통계 노출 (큐 깊이, 평균 대기 시간, 호출 분포)
  · Circuit breaker (연속 실패 시 자동 차단)
  · Graceful degradation (큐 가득 차도 시스템 다운 X)

우선순위 (낮을수록 빠름):
  0 — KILL/CANCEL (취소/긴급 청산)
  1 — SELL (포지션 정리)
  2 — BUY (일반 매수)
  3 — QUERY (잔고, 시세 등 조회)

설계 원칙 (방어적):
  · 모든 worker 예외는 격리 — 한 호출 실패가 다른 호출에 영향 X
  · Future timeout으로 무한 대기 차단
  · 종료 시 큐의 모든 pending 호출 정리
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

class GatewayPriority(IntEnum):
    KILL    = 0     # Kill switch, 취소
    SELL    = 1     # 매도 (포지션 정리)
    BUY     = 2     # 매수
    QUERY   = 3     # 조회


@dataclass
class GatewayConfig:
    """KIS Gateway 설정."""
    calls_per_second:        float = 18.0
    max_queue_size:          int = 500
    request_timeout_seconds: float = 30.0
    worker_count:            int = 1
    circuit_failure_threshold: int = 5
    circuit_reset_seconds:   float = 30.0


@dataclass(order=True)
class _GatewayRequest:
    """우선순위 큐 아이템."""
    priority: int                       # 정렬 키
    enqueued_at: float                  # 동일 우선순위 → FIFO
    request_id: str = field(compare=False)
    operation: str = field(compare=False)
    callable_: Callable = field(compare=False, default=None)
    args: tuple = field(compare=False, default_factory=tuple)
    kwargs: dict = field(compare=False, default_factory=dict)
    future: threading.Event = field(compare=False, default=None)
    result_holder: dict = field(compare=False, default_factory=dict)


@dataclass
class GatewayStats:
    """게이트웨이 운영 통계 (모니터링용)."""
    total_enqueued:  int = 0
    total_executed:  int = 0
    total_failed:    int = 0
    total_timeouts:  int = 0
    total_rejected:  int = 0
    queue_full_drops: int = 0

    by_priority: dict = field(default_factory=lambda: {
        "KILL": 0, "SELL": 0, "BUY": 0, "QUERY": 0,
    })
    by_operation: dict = field(default_factory=dict)

    avg_wait_ms:     float = 0
    avg_exec_ms:     float = 0
    p95_wait_ms:     float = 0

    last_call_at:    str | None = None
    last_error:      str | None = None

    circuit_state:   str = "CLOSED"
    circuit_failures: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Limiter (token bucket)
# ═══════════════════════════════════════════════════════════════════════════════

class _TokenBucket:
    """엄격한 초당 N회 호출 제한."""

    def __init__(self, calls_per_second: float):
        self.calls_per_second = max(1.0, calls_per_second)
        self.tokens = self.calls_per_second
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, timeout: float = 5.0):
        """토큰 1개 획득. 없으면 대기."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
            time.sleep(0.01)
        return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.calls_per_second,
                           self.tokens + elapsed * self.calls_per_second)
        self.last_refill = now


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════════

class _CircuitBreaker:
    """N회 연속 실패 → OPEN → 대기 → HALF_OPEN → 성공 시 CLOSED."""

    def __init__(self, threshold: int, reset_seconds: float):
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure_time: float | None = None
        self.lock = threading.Lock()

    def call_allowed(self) -> tuple[bool, str]:
        with self.lock:
            if self.state == "OPEN":
                if self.last_failure_time and \
                   time.monotonic() - self.last_failure_time > self.reset_seconds:
                    self.state = "HALF_OPEN"
                    return True, "HALF_OPEN"
                return False, "OPEN"
            return True, self.state

    def record_success(self):
        with self.lock:
            self.failures = 0
            self.state = "CLOSED"

    def record_failure(self):
        with self.lock:
            self.failures += 1
            self.last_failure_time = time.monotonic()
            if self.failures >= self.threshold:
                self.state = "OPEN"
                return True
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# KISGateway
# ═══════════════════════════════════════════════════════════════════════════════

class KISGateway:
    """
    KIS 호출 중앙 직렬화 게이트웨이.

    Usage:
        gateway = KISGateway(kis_client, GatewayConfig(), notifier=notifier)
        gateway.start()

        # 주문 (높은 우선순위)
        result = gateway.submit(
            operation="place_order",
            priority=GatewayPriority.BUY,
            args=("005930", "BUY", 100),
            kwargs={"order_type": "LIMIT", "price": 70000},
        )

        # Kill switch 취소 (최우선)
        result = gateway.submit(
            operation="cancel_order",
            priority=GatewayPriority.KILL,
            kwargs={"kis_order_id": "...", "kis_order_no": "..."},
        )

        # 조회 (낮은 우선순위)
        result = gateway.submit(
            operation="get_balance",
            priority=GatewayPriority.QUERY,
        )

        gateway.stop()
    """

    def __init__(self, kis_client, config: GatewayConfig | None = None,
                  notifier=None):
        self.kis = kis_client
        self.config = config or GatewayConfig()
        self.notifier = notifier

        self._heap: list = []   # min-heap (priority, enqueued_at, ...)
        self._heap_lock = threading.Lock()
        self._heap_cv = threading.Condition(self._heap_lock)

        self._rate_limiter = _TokenBucket(self.config.calls_per_second)
        self._circuit = _CircuitBreaker(
            self.config.circuit_failure_threshold,
            self.config.circuit_reset_seconds,
        )

        self.stats = GatewayStats()
        self._wait_samples: list = []     # 최근 N개 wait time (P95용)
        self._stats_lock = threading.Lock()

        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def start(self):
        if self._workers:
            return
        for i in range(max(1, self.config.worker_count)):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"KISGW-{i}", daemon=True,
            )
            t.start()
            self._workers.append(t)
        logger.info(f"KIS Gateway 시작 (workers={len(self._workers)}, "
                     f"rate={self.config.calls_per_second}/s)")

    def stop(self, timeout: float = 5.0):
        self._stop_event.set()
        with self._heap_cv:
            self._heap_cv.notify_all()

        for t in self._workers:
            t.join(timeout=timeout)
        self._workers.clear()

        # 큐에 남은 요청들에 timeout 통보
        with self._heap_lock:
            for req in self._heap:
                req.result_holder["error"] = "Gateway shutdown"
                req.future.set()
            self._heap.clear()

    # ─────────────────────────────────────────────────────────────────────
    # 공개 API
    # ─────────────────────────────────────────────────────────────────────

    def submit(
        self,
        operation: str,
        priority: int = GatewayPriority.BUY,
        args: tuple = (),
        kwargs: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        """
        KIS 호출을 큐에 enqueue + 결과 대기.

        Returns: KIS API 응답 (operation별 dict)
        Raises:  TimeoutError, RuntimeError
        """
        kwargs = kwargs or {}
        timeout = timeout if timeout is not None else self.config.request_timeout_seconds

        # 1. Circuit check
        allowed, state = self._circuit.call_allowed()
        if not allowed:
            self.stats.total_rejected += 1
            raise RuntimeError(f"Circuit breaker {state} — KIS 호출 차단")

        # 2. Validate operation
        if not hasattr(self.kis, operation):
            raise ValueError(f"Unknown KIS operation: {operation}")
        callable_ = getattr(self.kis, operation)

        # 3. Build request
        priority_int = int(priority)
        if priority_int not in (0, 1, 2, 3):
            priority_int = GatewayPriority.BUY

        req = _GatewayRequest(
            priority=priority_int,
            enqueued_at=time.monotonic(),
            request_id=f"REQ-{uuid.uuid4().hex[:10]}",
            operation=operation,
            callable_=callable_,
            args=args, kwargs=kwargs,
            future=threading.Event(),
            result_holder={},
        )

        # 4. Enqueue
        with self._heap_cv:
            if len(self._heap) >= self.config.max_queue_size:
                self.stats.queue_full_drops += 1
                raise RuntimeError(
                    f"KIS Gateway 큐 가득 참 ({len(self._heap)}/{self.config.max_queue_size})"
                )
            heapq.heappush(self._heap, req)
            self.stats.total_enqueued += 1
            self._increment_priority_stat(priority_int)
            self._heap_cv.notify()

        # 5. Wait for result
        completed = req.future.wait(timeout=timeout)
        if not completed:
            self.stats.total_timeouts += 1
            self._notify_warn(
                "KIS Gateway Timeout",
                f"{operation} priority={priority_int} {timeout}초 초과",
            )
            raise TimeoutError(
                f"KIS Gateway timeout ({operation}, {timeout}s)"
            )

        # 6. Extract result
        if "error" in req.result_holder:
            raise RuntimeError(req.result_holder["error"])
        return req.result_holder.get("result")

    def get_stats(self) -> dict:
        """현재 게이트웨이 상태."""
        with self._heap_lock:
            queue_size = len(self._heap)
            priorities_in_queue = {}
            for r in self._heap:
                key = self._priority_name(r.priority)
                priorities_in_queue[key] = priorities_in_queue.get(key, 0) + 1

        # P95 wait time
        with self._stats_lock:
            if len(self._wait_samples) > 20:
                sorted_w = sorted(self._wait_samples)
                self.stats.p95_wait_ms = float(sorted_w[int(0.95 * len(sorted_w))])

        return {
            **self.stats.__dict__,
            "queue_size":           queue_size,
            "queue_max":            self.config.max_queue_size,
            "queue_by_priority":    priorities_in_queue,
            "workers_running":      sum(1 for t in self._workers if t.is_alive()),
            "rate_limit_per_sec":   self.config.calls_per_second,
            "current_tokens":       round(self._rate_limiter.tokens, 2),
        }

    # ─────────────────────────────────────────────────────────────────────
    # 내부: worker loop
    # ─────────────────────────────────────────────────────────────────────

    def _worker_loop(self):
        while not self._stop_event.is_set():
            req = self._dequeue_one(timeout=0.5)
            if req is None:
                continue
            self._execute_request(req)

    def _dequeue_one(self, timeout: float) -> _GatewayRequest | None:
        """큐에서 최우선 요청 1개 꺼내기."""
        deadline = time.monotonic() + timeout
        with self._heap_cv:
            while not self._heap and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._heap_cv.wait(timeout=remaining)
            if self._stop_event.is_set():
                return None
            if not self._heap:
                return None
            return heapq.heappop(self._heap)

    def _execute_request(self, req: _GatewayRequest):
        """rate-limit 획득 + KIS 호출 + future 완료."""
        wait_start = time.monotonic()
        wait_ms = (wait_start - req.enqueued_at) * 1000

        with self._stats_lock:
            self._wait_samples.append(wait_ms)
            if len(self._wait_samples) > 200:
                self._wait_samples = self._wait_samples[-100:]
            # 이동 평균
            self.stats.avg_wait_ms = (
                self.stats.avg_wait_ms * 0.95 + wait_ms * 0.05
            ) if self.stats.avg_wait_ms > 0 else wait_ms

        # Rate limit acquire (timeout 적용)
        if not self._rate_limiter.acquire(timeout=10.0):
            req.result_holder["error"] = "Rate limit acquire timeout"
            req.future.set()
            self.stats.total_failed += 1
            return

        # 실제 호출
        exec_start = time.monotonic()
        try:
            result = req.callable_(*req.args, **req.kwargs)
            exec_ms = (time.monotonic() - exec_start) * 1000

            req.result_holder["result"] = result
            self._circuit.record_success()

            with self._stats_lock:
                self.stats.total_executed += 1
                self.stats.avg_exec_ms = (
                    self.stats.avg_exec_ms * 0.95 + exec_ms * 0.05
                ) if self.stats.avg_exec_ms > 0 else exec_ms
                self.stats.last_call_at = datetime.now().isoformat()
                op_count = self.stats.by_operation.get(req.operation, 0)
                self.stats.by_operation[req.operation] = op_count + 1
                self.stats.circuit_state = "CLOSED"
                self.stats.circuit_failures = 0

            # 느린 호출 경고
            if exec_ms > 5000:
                self._notify_warn(
                    "KIS API 지연",
                    f"{req.operation} {exec_ms:.0f}ms (5s 초과)",
                )

        except Exception as e:
            req.result_holder["error"] = str(e)
            tripped = self._circuit.record_failure()
            self.stats.total_failed += 1
            self.stats.last_error = str(e)[:200]

            with self._stats_lock:
                self.stats.circuit_failures = self._circuit.failures
                if tripped:
                    self.stats.circuit_state = "OPEN"
                    self._notify_critical(
                        "Circuit Breaker OPEN",
                        f"{req.operation} {self._circuit.failures}회 연속 실패 — "
                        f"KIS 호출 {self.config.circuit_reset_seconds}초 차단",
                    )

            logger.error(f"KIS Gateway exec 실패 ({req.operation}): {e}")
        finally:
            req.future.set()

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _increment_priority_stat(self, priority: int):
        with self._stats_lock:
            name = self._priority_name(priority)
            self.stats.by_priority[name] = self.stats.by_priority.get(name, 0) + 1

    @staticmethod
    def _priority_name(priority: int) -> str:
        return {0: "KILL", 1: "SELL", 2: "BUY", 3: "QUERY"}.get(priority, "BUY")

    def _notify_critical(self, title: str, message: str):
        if self.notifier:
            try:
                self.notifier.critical(title, message)
            except Exception:
                pass

    def _notify_warn(self, title: str, message: str):
        if self.notifier:
            try:
                self.notifier.warn(title, message)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# KISGatewayClient — 기존 KISClient 인터페이스를 게이트웨이로 wrap
# ═══════════════════════════════════════════════════════════════════════════════

class KISGatewayClient:
    """
    기존 OrderExecutor 등이 직접 KISClient 호출하던 코드를 게이트웨이로 우회.

    인터페이스는 KISClient와 동일 (place_order, cancel_order, get_balance, get_price).
    내부적으로 KISGateway를 통해 priority queue로 실행.
    """

    def __init__(self, gateway: KISGateway):
        self.gateway = gateway

    def place_order(self, ticker: str, side: str, quantity: int,
                     order_type: str = "MARKET", price: float | None = None) -> dict:
        priority = GatewayPriority.SELL if side == "SELL" else GatewayPriority.BUY
        return self.gateway.submit(
            operation="place_order", priority=priority,
            args=(ticker, side, quantity),
            kwargs={"order_type": order_type, "price": price},
        )

    def cancel_order(self, kis_order_id: str, kis_order_no: str,
                       cancel_qty: int | None = None) -> dict:
        return self.gateway.submit(
            operation="cancel_order", priority=GatewayPriority.KILL,
            kwargs={"kis_order_id": kis_order_id, "kis_order_no": kis_order_no,
                     "cancel_qty": cancel_qty},
        )

    def get_balance(self) -> dict:
        return self.gateway.submit(
            operation="get_balance", priority=GatewayPriority.QUERY,
        )

    def get_price(self, ticker: str) -> dict:
        return self.gateway.submit(
            operation="get_price", priority=GatewayPriority.QUERY,
            args=(ticker,),
        )
