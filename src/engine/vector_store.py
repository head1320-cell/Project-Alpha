"""
Vector Store — Screener V3 Milestone 6 (Vector-based Twin Discovery)
==========================================================================
특정 종목과 재무/주가 흐름이 유사한 기업 탐색 (벡터 유사도).

핵심:
  · 각 종목을 재무/가격 특성 → 8차원 임베딩 벡터로 변환 (deterministic)
  · 코사인 유사도로 'Twin 종목' 발견
  · 예: "삼성전자와 유사도 0.8+ 종목" → 비슷한 재무 프로파일 기업

DeterministicMockStore 상속 → 종목별 일관된 임베딩.
실제로는 재무 시계열 + 가격 패턴을 학습한 임베딩 모델로 교체.

성능: lazy — vector_sim 조건이 있을 때만 임베딩 + 유사도 계산.
"""

from __future__ import annotations

import logging
import math

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)

EMBED_DIM = 8


class VectorStore(DeterministicMockStore):
    """종목 임베딩 + 코사인 유사도 (Mock + 실 임베딩 모델 연결 여지)."""

    _singleton: VectorStore | None = None

    @classmethod
    def get_default(cls) -> VectorStore:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def get_embedding(self, stock_code: str, item=None) -> list[float]:
        """
        종목의 임베딩 벡터 (8차원).

        item이 있으면 실제 재무 특성을 반영, 없으면 코드 기반 결정론적.
        실제로는 재무 시계열 + 가격 패턴 임베딩 모델 사용.
        """
        cache_key = f"embed:{stock_code}"
        cached = self._cache.get(cache_key)
        if cached and item is None:
            import time
            if time.time() - cached[0] < self.cache_ttl:
                return cached[1]

        if item is not None:
            # 재무 특성을 정규화하여 임베딩 구성 (의미있는 유사도)
            vec = self._embed_from_financials(stock_code, item)
        else:
            # 코드 기반 결정론적 임베딩
            vec = [self._normal(stock_code, f"dim{i}", mu=0, sigma=1) for i in range(EMBED_DIM)]

        vec = self._normalize(vec)
        import time
        self._cache[cache_key] = (time.time(), vec)
        return vec

    def _embed_from_financials(self, stock_code: str, item) -> list[float]:
        """재무 특성 → 임베딩 (유사 재무 = 유사 벡터)."""
        def norm(val, lo, hi):
            if val is None:
                return 0.0
            return max(-2, min(2, (val - (lo + hi) / 2) / ((hi - lo) / 2 + 1e-9)))

        # 8개 재무 차원 (스케일 정규화)
        base = [
            norm(getattr(item, "per", None), 0, 40),
            norm(getattr(item, "pbr", None), 0, 8),
            norm(getattr(item, "roe_pct", None), -10, 40),
            norm(getattr(item, "roa_pct", None), -5, 20),
            norm(getattr(item, "debt_ratio_pct", None), 0, 300),
            norm(getattr(item, "dividend_yield_pct", None), 0, 8),
            norm(getattr(item, "gap_pct", None), -50, 50),
            norm(math.log10((getattr(item, "market_cap_억", None) or 1000) + 1), 2, 6),
        ]
        # 약간의 종목 고유 노이즈 (동일 재무라도 미세 차이)
        noise = [self._normal(stock_code, f"vn{i}", mu=0, sigma=0.15) for i in range(EMBED_DIM)]
        return [b + n for b, n in zip(base, noise)]

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        mag = math.sqrt(sum(x * x for x in vec))
        if mag < 1e-9:
            return vec
        return [x / mag for x in vec]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """두 벡터의 코사인 유사도 (정규화된 벡터 → 내적)."""
        if len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))


# ═══════════════════════════════════════════════════════════════════════════════
# 평가기 + lazy 컨텍스트 빌더 (register_kind)
# ═══════════════════════════════════════════════════════════════════════════════

def eval_vector_sim(item, cond, ctx: dict) -> bool:
    """벡터 유사도 평가 — 기준 종목과 코사인 유사도 >= threshold면 통과."""
    vctx = ctx.get("_vector", {})
    target_vec = vctx.get("_target")
    if target_vec is None:
        return False
    code = getattr(item, "stock_code", None)
    item_vec = vctx.get(code)
    if item_vec is None:
        return False
    sim = VectorStore.cosine_similarity(target_vec, item_vec)
    return sim >= (cond.vector_threshold or 0.8)


def _collect_vector_target(group) -> str | None:
    """AST에서 vector_sim 조건의 기준 종목 추출 (첫 번째)."""
    for c in group.conditions:
        if c.kind == "vector_sim":
            return c.vector_ticker
    for g in group.groups:
        t = _collect_vector_target(g)
        if t:
            return t
    return None


def build_vector_context(group, items) -> dict:
    """lazy: 기준 종목 임베딩 + 각 후보 임베딩 사전계산."""
    target = _collect_vector_target(group)
    if not target:
        return {}
    store = VectorStore.get_default()

    vctx = {}
    # 후보 종목 임베딩 (재무 기반)
    target_item = None
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        vctx[code] = store.get_embedding(code, it)
        if code == target:
            target_item = it

    # 기준 종목 임베딩 (후보에 있으면 그 임베딩, 없으면 코드 기반)
    if target_item is not None:
        vctx["_target"] = vctx[target]
    else:
        vctx["_target"] = store.get_embedding(target)

    return {"_vector": vctx}


def vector_meta_catalog() -> dict:
    """API용 벡터 메타 (그래프 노드 재사용 — 검색 가능 종목)."""
    try:
        from src.engine.graph_store import GraphStore
        nodes = GraphStore.get_default().all_nodes()
    except Exception:
        nodes = []
    return {
        "embed_dim": EMBED_DIM,
        "nodes": nodes,
        "note": "재무/가격 특성 기반 8차원 임베딩. 코사인 유사도로 유사 종목(Twin) 탐색.",
    }
