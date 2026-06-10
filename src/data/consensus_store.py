"""
Consensus Store — Screener V3 Milestone 1 (Forward-Looking Estimates)
==========================================================================
후행적 재무제표의 한계를 극복하는 컨센서스 추정치 데이터.

DeterministicMockStore 상속 → 종목별 일관된 mock 추정치.
실제 데이터 연결 시 _build_estimates만 교체.

추정치 필드:
  · fwd_eps_1m_chg   — 1개월 선행 EPS 추정치 변화율 (%)
  · fwd_per          — 선행 PER (12개월 추정 EPS 기준)
  · revision_score   — 애널리스트 리비전 점수 (-100 ~ 100, 상향 우세 = 양수)
  · target_upside    — 목표주가 대비 상승여력 (%)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


@dataclass
class EstimateMeta:
    id: str
    label: str
    unit: str
    typical_min: float
    typical_max: float
    higher_better: bool
    description: str


ESTIMATE_CATALOG: list[EstimateMeta] = [
    EstimateMeta("fwd_eps_1m_chg", "선행 EPS 1개월 변화", "%",  -30, 30,  True,  "최근 1개월 선행 EPS 추정치 변화율 — 양수 = 상향 조정"),
    EstimateMeta("fwd_per",        "선행 PER",          "배",  0,   40,  False, "12개월 추정 EPS 기준 PER"),
    EstimateMeta("revision_score", "리비전 점수",        "점",  -100, 100, True, "애널리스트 추정 상·하향 점수 (양수 = 상향 우세)"),
    EstimateMeta("target_upside",  "목표가 상승여력",    "%",  -40, 80,  True,  "컨센서스 목표주가 대비 현재가 상승여력"),
]

ESTIMATE_BY_ID = {e.id: e for e in ESTIMATE_CATALOG}


class ConsensusStore(DeterministicMockStore):
    """컨센서스 추정치 제공 (Mock + 실데이터 연결 여지)."""

    _singleton: ConsensusStore | None = None

    @classmethod
    def get_default(cls) -> ConsensusStore:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def get_estimates(self, stock_code: str) -> dict:
        """단일 종목의 모든 추정치 (캐시 + 결정론적)."""
        return self.cached(
            f"est:{stock_code}",
            lambda: self._build_estimates(stock_code),
        )

    def _build_estimates(self, stock_code: str) -> dict:
        # 종목별 결정론적 추정치
        eps_chg = round(self._normal(stock_code, "fwd_eps", mu=2.0, sigma=8.0), 2)
        fwd_per = round(abs(self._normal(stock_code, "fwd_per", mu=14.0, sigma=7.0)) + 3, 2)
        # 리비전은 EPS 변화와 약한 상관 (상향 조정 시 점수↑)
        revision = round(max(-100, min(100, eps_chg * 4 + self._normal(stock_code, "rev", mu=0, sigma=20))), 1)
        upside = round(self._normal(stock_code, "upside", mu=12.0, sigma=20.0), 1)
        # 결측치 시뮬 — 일부 종목은 컨센서스 미커버 (실데이터 정합성)
        return {
            "fwd_eps_1m_chg": self._maybe_missing(stock_code, "m_eps", value=eps_chg, missing_rate=0.10),
            "fwd_per":        self._maybe_missing(stock_code, "m_per", value=fwd_per, missing_rate=0.08),
            "revision_score": self._maybe_missing(stock_code, "m_rev", value=revision, missing_rate=0.12),
            "target_upside":  self._maybe_missing(stock_code, "m_up", value=upside, missing_rate=0.10),
            "_source":        "consensus_mock",
        }


def estimates_catalog() -> dict:
    """API용 추정치 카탈로그."""
    return {
        "category": {
            "id": "estimate",
            "label": "추정치",
            "fields": [
                {
                    "id": e.id, "label": e.label, "unit": e.unit,
                    "typical_min": e.typical_min, "typical_max": e.typical_max,
                    "higher_better": e.higher_better, "description": e.description,
                }
                for e in ESTIMATE_CATALOG
            ],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 평가기 + lazy 컨텍스트 빌더 (register_kind로 등록)
# ═══════════════════════════════════════════════════════════════════════════════

def eval_estimate(item, cond, ctx: dict) -> bool:
    """Forward estimate 평가 — lazy 주입된 _est 컨텍스트 사용."""
    from src.engine.filter_ast import FilterCondition, _eval_absolute
    est = ctx.get("_est", {})
    code = getattr(item, "stock_code", None)
    data = est.get(code)
    if not data:
        return False
    val = data.get(cond.estimate_field)
    if val is None:
        return False
    tmp = FilterCondition(field="__est__", op=cond.op, value=cond.value, value2=cond.value2)
    return _eval_absolute(val, tmp)


def build_estimate_context(group, items) -> dict:
    """lazy: 통과 후보 종목들의 추정치 일괄 조회."""
    store = ConsensusStore.get_default()
    est_ctx = {}
    for it in items:
        code = getattr(it, "stock_code", None)
        if code:
            est_ctx[code] = store.get_estimates(code)
    return {"_est": est_ctx}
