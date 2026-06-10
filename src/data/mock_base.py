"""
Deterministic Mock Store Base — Screener V3 Phase 0
==========================================================================
모든 V3 신규 데이터 레이어(consensus, graph, sentiment, vector...)의 부모 클래스.

V2에서 검증된 deterministic mock 패턴을 공통화:
  · 종목코드 기반 해시 → 항상 일관된 가짜 데이터 (재현 가능)
  · 시드 RNG 제공
  · 공통 캐시 (TTL)
  · 싱글톤 헬퍼

이로써 5개 신규 스토어의 중복 코드를 제거하고, 일관된 mock 동작을 보장한다.
실제 데이터 연결 시 builder만 교체하면 됨.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DeterministicMockStore:
    """
    결정론적 Mock 데이터 스토어 베이스.

    하위 클래스는 보통 다음만 구현:
      · get_default() (싱글톤)
      · 도메인별 조회 메서드 (내부에서 self._rng / self.cached 사용)
    """

    def __init__(self, cache_ttl: int = 3600 * 6):
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    # ─── 결정론적 시드 ────────────────────────────────────────────────

    @staticmethod
    def _seed(*keys: Any) -> int:
        """
        임의 키들로부터 결정론적 정수 시드 생성.
        같은 키 → 항상 같은 시드 → 항상 같은 mock 데이터.
        """
        joined = "|".join(str(k) for k in keys)
        digest = hashlib.md5(joined.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _rng(self, *keys: Any) -> random.Random:
        """결정론적 시드 RNG."""
        return random.Random(self._seed(*keys))

    # ─── 공통 캐시 ────────────────────────────────────────────────────

    def cached(self, key: str, builder: Callable[[], T]) -> T:
        """
        캐시 조회 후 없으면 builder()로 생성하여 저장.
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry and time.time() - entry[0] < self.cache_ttl:
                return entry[1]
        value = builder()
        with self._lock:
            self._cache[key] = (time.time(), value)
        return value

    def cache_clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    # ─── mock 분포 헬퍼 ───────────────────────────────────────────────

    def _normal(self, *keys: Any, mu: float = 0.0, sigma: float = 1.0) -> float:
        """결정론적 정규분포 샘플."""
        return self._rng(*keys).gauss(mu, sigma)

    def _uniform(self, *keys: Any, lo: float = 0.0, hi: float = 1.0) -> float:
        """결정론적 균등분포 샘플."""
        return self._rng(*keys).uniform(lo, hi)

    def _choice(self, *keys: Any, options: list) -> Any:
        """결정론적 선택."""
        return self._rng(*keys).choice(options)

    def _maybe_missing(self, *keys: Any, value: Any, missing_rate: float = 0.07) -> Any:
        """
        결측치 시뮬 — 실데이터 정합성 테스트용 (Gemini 지적 수용).
        결정론적으로 missing_rate 확률로 None 반환.
        실제 데이터는 구멍투성이이므로, mock도 결측을 흉내 내어
        None 처리 로직이 실데이터 전환 시 붕괴하지 않도록 검증한다.
        """
        if self._uniform(*keys, "missing") < missing_rate:
            return None
        return value
