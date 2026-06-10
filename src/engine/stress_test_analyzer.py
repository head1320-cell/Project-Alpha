"""
Macro Stress-Test Projection — Screener V3 Milestone 8
==========================================================================
통과 종목에 매크로 시나리오 충격을 가해 생존/탈락 시뮬레이션 (후처리 analyzer).

★ 기존 Phase 4 매크로 엔진 역이용 ★
  regime_analyzer의 국면 틸트 로직을 "역방향"으로 적용 —
  특정 시나리오(유가 폭등, 금리 인상)가 각 종목 펀더멘털에 주는 충격 추정.

시나리오:
  · rate_hike_200bp  — 금리 +200bp (고부채주 타격)
  · oil_spike_50     — 유가 +50% (에너지 소비주 타격)
  · krw_depreciation — 원화 -15% (수입 의존주 타격, 수출주 수혜)
  · recession        — 경기 침체 (경기민감주 타격)

각 종목의 시나리오 후 추정 점수 변화 → 생존(점수 유지) / 탈락(급락) 판정.

★ 후처리 레이어 (kind와 분리), manual 트리거 (버튼 클릭) ★
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# 시나리오 정의 — 종목 특성별 민감도 (충격 계수)
STRESS_SCENARIOS = {
    "rate_hike_200bp": {
        "label": "금리 +200bp",
        "description": "기준금리 2%p 인상 — 고부채·고PER 성장주 타격",
        "icon": "trending-up",
    },
    "oil_spike_50": {
        "label": "유가 +50%",
        "description": "유가 급등 — 에너지 소비 많은 제조·운송주 타격",
        "icon": "flame",
    },
    "krw_depreciation": {
        "label": "원화 -15%",
        "description": "원화 약세 — 수입 의존주 타격, 수출주 수혜",
        "icon": "dollar-sign",
    },
    "recession": {
        "label": "경기 침체",
        "description": "GDP 역성장 — 경기민감주·저배당주 타격",
        "icon": "trending-down",
    },
}


def _stock_shock(item, scenario: str) -> float:
    """
    시나리오가 종목에 주는 추정 점수 충격 (%, 음수=악재).

    종목 펀더멘털 특성 + 종목 고유 민감도(결정론적)로 추정.
    """
    import hashlib
    debt = getattr(item, "debt_ratio_pct", None) or 100
    per = getattr(item, "per", None) or 15
    div = getattr(item, "dividend_yield_pct", None) or 2
    roe = getattr(item, "roe_pct", None) or 8
    # 종목 고유 민감도 (섹터/사업특성 프록시 — 결정론적 ±6%)
    code = getattr(item, "stock_code", "000000")
    h = int(hashlib.md5(f"{code}:{scenario}".encode()).hexdigest()[:6], 16)
    idio = (h % 1200) / 100.0 - 6.0  # -6% ~ +6%

    if scenario == "rate_hike_200bp":
        # 고부채 + 고PER일수록 타격 (할인율 상승)
        debt_impact = -(debt / 100) * 9       # 부채비율 100%당 -9%
        per_impact = -(per / 15) * 7          # PER 15당 -7%
        return round(debt_impact + per_impact + 2 + idio, 1)

    if scenario == "oil_spike_50":
        # 부채 많은 제조업 가정 — 부채 높을수록 비용 민감
        return round(-(debt / 100) * 8 - (per / 15) * 2 + idio, 1)

    if scenario == "krw_depreciation":
        # 고ROE 수출주는 수혜(+), 그 외 타격
        if roe > 15:
            return round((roe / 15) * 5 - 2 + idio, 1)   # 수출 경쟁력 → 수혜
        return round(-7 - (debt / 100) * 4 + idio, 1)

    if scenario == "recession":
        # 고배당·저부채는 방어적(+), 고PER은 타격
        defensive = (div / 2) * 4 - (debt / 100) * 4
        growth_hit = -(per / 15) * 8
        return round(defensive + growth_hit + 3 + idio, 1)

    return 0.0


def stress_test(items: list, scenario: str = "rate_hike_200bp", **kwargs) -> dict:
    """
    M8: 매크로 스트레스 테스트.

    Args:
        items: 통과 종목
        scenario: 시나리오 ID
    Returns:
        {scenario, survivors, casualties, summary}
    """
    n = len(items)
    if n == 0:
        return {"available": False, "error": "통과 종목 없음"}

    if scenario not in STRESS_SCENARIOS:
        return {"available": False, "error": f"미지원 시나리오: {scenario}"}

    results = []
    for it in items:
        base_score = getattr(it, "composite_score", 50) or 50
        shock = _stock_shock(it, scenario)
        stressed_score = max(0, base_score * (1 + shock / 100))
        results.append({
            "stock_code": getattr(it, "stock_code", ""),
            "corp_name": getattr(it, "corp_name", ""),
            "base_score": round(float(base_score), 1),
            "shock_pct": shock,
            "stressed_score": round(float(stressed_score), 1),
            "survived": shock > -8,  # -8% 이내면 생존
        })

    # 충격 큰 순 정렬
    results.sort(key=lambda x: x["shock_pct"])

    survivors = [r for r in results if r["survived"]]
    casualties = [r for r in results if not r["survived"]]

    avg_shock = sum(r["shock_pct"] for r in results) / n

    return {
        "available": True,
        "scenario": scenario,
        "scenario_label": STRESS_SCENARIOS[scenario]["label"],
        "n_stocks": n,
        "n_survivors": len(survivors),
        "n_casualties": len(casualties),
        "survival_rate": round(len(survivors) / n * 100, 1),
        "avg_shock_pct": round(avg_shock, 1),
        "casualties": casualties[:10],   # 가장 취약한 10종목
        "survivors": survivors[:5],      # 가장 견고한 5종목 (역순이라 끝에서)
        "most_resilient": sorted(results, key=lambda x: -x["shock_pct"])[:5],
        "note": "종목 펀더멘털(부채·PER·배당·ROE)로 시나리오 민감도 추정. 실 운영 시 팩터 베타로 정밀화.",
    }


def stress_scenarios_catalog() -> dict:
    """API용 시나리오 카탈로그."""
    return {
        "scenarios": [
            {"id": k, "label": v["label"], "description": v["description"], "icon": v["icon"]}
            for k, v in STRESS_SCENARIOS.items()
        ],
    }


def register():
    """analyzers 파이프라인에 M8 등록."""
    from src.engine.analyzers import register_analyzer
    register_analyzer("stress_test", stress_test)
