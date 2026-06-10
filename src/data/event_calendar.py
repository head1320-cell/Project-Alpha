"""
Event Calendar — Screener V2 Milestone 3
==========================================================================
이벤트 기반 필터용 캘린더 (실적 발표 / 배당락).

전략:
  · earnings_date / ex_dividend_date per ticker
  · DART 연동 여지 (현재 deterministic mock)
  · days_until(ticker, event) → 임박일수

이벤트 유형:
  · earnings    — 실적 발표
  · ex_dividend — 배당락
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class EventMeta:
    id: str
    label: str
    description: str


EVENT_CATALOG: list[EventMeta] = [
    EventMeta("earnings",    "실적 발표",  "다음 분기 실적 발표 예정일까지 일수"),
    EventMeta("ex_dividend", "배당락",     "다음 배당락일까지 일수"),
]

EVENT_BY_ID = {e.id: e for e in EVENT_CATALOG}


# ═══════════════════════════════════════════════════════════════════════════════
# Mock 이벤트 일자 생성 (deterministic)
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_event_date(stock_code: str, event_type: str) -> datetime:
    """종목별 deterministic 이벤트 일자."""
    seed = sum(ord(c) for c in stock_code) + sum(ord(c) for c in event_type)
    rng = random.Random(seed)
    today = datetime.now()

    if event_type == "earnings":
        # 분기 실적: 0~90일 내 랜덤
        days_ahead = rng.randint(1, 90)
    elif event_type == "ex_dividend":
        # 배당락: 0~180일 내 (연/반기)
        days_ahead = rng.randint(1, 180)
    else:
        days_ahead = rng.randint(1, 60)

    return today + timedelta(days=days_ahead)


class EventCalendar:
    """이벤트 캘린더 제공 (Mock + DART 연동 여지)."""

    _singleton: EventCalendar | None = None

    @classmethod
    def get_default(cls) -> EventCalendar:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def days_until(self, stock_code: str, event_type: str) -> int | None:
        """이벤트까지 남은 일수 (없으면 None)."""
        if event_type not in EVENT_BY_ID:
            return None
        event_date = _mock_event_date(stock_code, event_type)
        delta = (event_date - datetime.now()).days
        return max(0, delta)

    def get_events(self, stock_code: str) -> dict:
        """종목의 모든 이벤트 임박일수."""
        return {
            "earnings_days":    self.days_until(stock_code, "earnings"),
            "ex_dividend_days": self.days_until(stock_code, "ex_dividend"),
            "_source": "mock",
        }


def events_catalog() -> dict:
    """API용 이벤트 카탈로그."""
    return {
        "events": [
            {"id": e.id, "label": e.label, "description": e.description}
            for e in EVENT_CATALOG
        ],
    }
