"""
Analyzer Pipeline — Screener V3 Phase 0
==========================================================================
후처리(Post-Processing) 레이어 — M7(다중공선성), M8(스트레스 테스트)의 토대.

★ 핵심 설계 결정 ★
  M1-M6은 "조건"(kind 디스패처 — 무엇을 통과시킬까)이지만,
  M7-M8은 "분석"(통과한 종목 집합을 어떻게 진단할까)이다.
  → 완전히 다른 레이어. kind 디스패처에 넣지 않고 별도 파이프라인으로 분리.

구조:
  · ANALYZER_REGISTRY — analyzer 이름 → 함수 등록 테이블
  · run_analyzers(items, requested) — 요청된 analyzer만 실행
  · 각 analyzer: (items, **params) → dict 결과

Phase 4에서 M7(collinearity), M8(stress_test)가 여기 등록됨.
Phase 0에서는 골격 + 등록 메커니즘 + no-op 검증만.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Analyzer 등록 테이블
# ═══════════════════════════════════════════════════════════════════════════════

ANALYZER_REGISTRY: dict[str, Callable] = {}


def register_analyzer(name: str, fn: Callable):
    """후처리 analyzer 등록 (M7/M8이 여기 등록)."""
    ANALYZER_REGISTRY[name] = fn
    logger.debug(f"Analyzer 등록: {name}")


def available_analyzers() -> list[str]:
    return sorted(ANALYZER_REGISTRY.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# 파이프라인 실행
# ═══════════════════════════════════════════════════════════════════════════════

def run_analyzers(items: list, requested: list[str], params: dict = None) -> dict:
    """
    통과 종목 집합에 요청된 analyzer들을 실행.

    Args:
        items:     스크리닝 통과 종목 (ScreenerItem 리스트)
        requested: 실행할 analyzer 이름들 (예: ["collinearity", "stress_test"])
        params:    analyzer별 파라미터 {analyzer_name: {...}}
    Returns:
        {analyzer_name: result_dict} — 실패한 것은 error 포함
    """
    params = params or {}
    results: dict[str, Any] = {}

    if not items:
        return {name: {"error": "통과 종목 없음", "available": False} for name in requested}

    for name in requested:
        fn = ANALYZER_REGISTRY.get(name)
        if fn is None:
            results[name] = {"error": f"미등록 analyzer: {name}", "available": False}
            continue
        try:
            analyzer_params = params.get(name, {})
            results[name] = fn(items, **analyzer_params)
        except Exception as e:
            logger.warning(f"Analyzer 실행 실패 ({name}): {e}")
            results[name] = {"error": str(e), "available": False}

    return results


def analyzer_catalog() -> dict:
    """API용 — 가용 analyzer 메타 (UI 버튼 구성용)."""
    meta = {
        "collinearity": {
            "label": "팩터 다중공선성 진단",
            "description": "통과 종목들의 팩터 상관관계를 분석하여 편향(예: 가치주 편중)을 경고",
            "icon": "grid",
            "trigger": "auto",  # 스크리닝 후 자동
        },
        "stress_test": {
            "label": "매크로 스트레스 테스트",
            "description": "유가 폭등·금리 인상 등 시나리오를 가해 종목 생존/탈락 시뮬레이션",
            "icon": "zap",
            "trigger": "manual",  # 버튼 클릭
        },
    }
    return {
        "analyzers": [
            {"name": name, **info}
            for name, info in meta.items()
            if name in ANALYZER_REGISTRY  # 실제 등록된 것만
        ],
        "registered": available_analyzers(),
    }



# ═══════════════════════════════════════════════════════════════════════════════
# M7/M8 analyzer 등록 (모듈 로드 시 자동)
# ═══════════════════════════════════════════════════════════════════════════════

def _register_analyzers():
    """후처리 analyzer 등록 (지연 import로 순환 방지)."""
    try:
        from src.engine.collinearity_analyzer import register as reg_collin
        reg_collin()
    except Exception as e:
        logger.debug(f"collinearity analyzer 등록 실패: {e}")
    try:
        from src.engine.stress_test_analyzer import register as reg_stress
        reg_stress()
    except Exception as e:
        logger.debug(f"stress_test analyzer 등록 실패: {e}")


_register_analyzers()
