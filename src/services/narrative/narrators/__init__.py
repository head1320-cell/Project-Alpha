"""
Narrators — 6 도메인 narrator 클래스
=======================================
각 narrator는 도메인 데이터를 받아 Claude에 프롬프트를 생성하고 결과를 반환.

설계:
  BaseNarrator (abstract) — invoke() / stream() 공통 로직
    ├─ StockNarrator           — 종목 분석
    ├─ PortfolioNarrator       — 포트폴리오 보고서
    ├─ MacroNarrator           — 매크로 브리핑
    ├─ OperationsNarrator      — 운영 사건 분석
    ├─ CounterfactualNarrator  — What-If 시나리오
    └─ DailyNarrator           — 일일 요약
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any, Optional

from src.services.narrative.claude_client import (
    ClaudeClient,
    NarrativeRequest,
    NarrativeResponse,
)
from src.services.narrative.prompts import (
    counterfactual_prompt,
    daily_summary_prompt,
    macro_briefing_prompt,
    operations_analysis_prompt,
    portfolio_report_prompt,
    stock_analysis_prompt,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Base Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class BaseNarrator(ABC):
    """Narrator 공통 베이스. 도메인 데이터 → prompt → Claude → response."""

    DOMAIN: str = "base"
    DEFAULT_MAX_TOKENS: int = 2000
    DEFAULT_TEMPERATURE: float = 0.3

    def __init__(self, client: ClaudeClient | None = None):
        self.client = client or ClaudeClient.get_default()

    @abstractmethod
    def build_prompts(self, **inputs) -> tuple[str, str]:
        """Subclass: 입력 데이터 → (system, user) prompts."""
        ...

    def generate(self, max_tokens: int | None = None,
                  temperature: float | None = None,
                  model: str | None = None,
                  **inputs) -> NarrativeResponse:
        """단발 호출 (블로킹)."""
        system, user = self.build_prompts(**inputs)
        req = NarrativeRequest(
            system_prompt=system,
            user_prompt=user,
            max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
            temperature=temperature or self.DEFAULT_TEMPERATURE,
            model=model,
            metadata={"domain": self.DOMAIN},
        )
        return self.client.invoke(req)

    def stream(self, max_tokens: int | None = None,
                temperature: float | None = None,
                model: str | None = None,
                **inputs) -> Generator[str, None, NarrativeResponse]:
        """스트리밍 generator (SSE)."""
        system, user = self.build_prompts(**inputs)
        req = NarrativeRequest(
            system_prompt=system,
            user_prompt=user,
            max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
            temperature=temperature or self.DEFAULT_TEMPERATURE,
            model=model,
            metadata={"domain": self.DOMAIN},
        )
        return self.client.stream(req)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Stock Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class StockNarrator(BaseNarrator):
    """종목 가치평가 결과 → 자연어 분석."""

    DOMAIN = "stock_analysis"

    def build_prompts(self, stock_item: dict, valuation_detail: dict) -> tuple[str, str]:
        return stock_analysis_prompt(stock_item, valuation_detail)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Portfolio Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class PortfolioNarrator(BaseNarrator):
    """백테스트 결과 + 5-Factor Attribution → 포트폴리오 보고서."""

    DOMAIN = "portfolio_report"
    DEFAULT_MAX_TOKENS = 2500

    def build_prompts(self, backtest_result: dict, attribution: dict) -> tuple[str, str]:
        return portfolio_report_prompt(backtest_result, attribution)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Macro Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class MacroNarrator(BaseNarrator):
    """현재 매크로 환경 → 시장 시사점 브리핑."""

    DOMAIN = "macro_briefing"

    def build_prompts(self, regime_state: dict) -> tuple[str, str]:
        return macro_briefing_prompt(regime_state)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Operations Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class OperationsNarrator(BaseNarrator):
    """Kill switch / Audit log → 운영 사건 사후 분석."""

    DOMAIN = "operations_analysis"
    DEFAULT_MAX_TOKENS = 2500

    def build_prompts(self, events: list, audit_summary: dict) -> tuple[str, str]:
        return operations_analysis_prompt(events, audit_summary)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Counterfactual Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class CounterfactualNarrator(BaseNarrator):
    """What-If 시나리오 비교 → 의사결정 가치 정량화."""

    DOMAIN = "counterfactual"
    DEFAULT_MAX_TOKENS = 2500

    def build_prompts(self, actual: dict, scenarios: list) -> tuple[str, str]:
        return counterfactual_prompt(actual, scenarios)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Daily Narrator
# ═══════════════════════════════════════════════════════════════════════════════

class DailyNarrator(BaseNarrator):
    """모든 활동 통합 일일 요약."""

    DOMAIN = "daily_summary"
    DEFAULT_MAX_TOKENS = 2000

    def build_prompts(self, activities: dict) -> tuple[str, str]:
        return daily_summary_prompt(activities)


# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════

NARRATOR_REGISTRY: dict[str, type[BaseNarrator]] = {
    "stock":          StockNarrator,
    "portfolio":      PortfolioNarrator,
    "macro":          MacroNarrator,
    "operations":     OperationsNarrator,
    "counterfactual": CounterfactualNarrator,
    "daily":          DailyNarrator,
}


def get_narrator(domain: str, client: ClaudeClient | None = None) -> BaseNarrator:
    """Factory: domain 이름으로 narrator 인스턴스 생성."""
    cls = NARRATOR_REGISTRY.get(domain)
    if not cls:
        raise ValueError(f"Unknown narrator domain: {domain}. "
                         f"Available: {list(NARRATOR_REGISTRY.keys())}")
    return cls(client)
