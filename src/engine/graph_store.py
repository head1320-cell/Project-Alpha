"""
Knowledge Graph Store — Screener V3 Milestone 4a (Supply Chain Graph)
==========================================================================
종목 간 밸류체인 관계를 경량 인메모리 그래프로 구축.

관계 유형:
  · supplier   — 공급사 (A가 B에 납품)
  · customer   — 고객사 (A가 B로부터 매출)
  · competitor — 경쟁사 (동일 시장)

핵심: BFS 탐색으로 N-hop 관계망 추출.
  예: neighbors("005930", "supplier", depth=2)
      → 삼성전자의 1차·2차 공급사

DeterministicMockStore 상속 → 종목 코드 기반 일관된 mock 밸류체인.
실제로는 FactSet Supply Chain / 매출 의존도 데이터로 교체.

성능: lazy — graph 조건이 있을 때만 탐색.
"""

from __future__ import annotations

import logging
from collections import deque

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


# 알려진 한국 대형주 (그래프 노드 풀)
_KNOWN_STOCKS = [
    "005930", "000660", "035420", "035720", "051910", "006400",
    "005380", "000270", "012330", "207940", "068270", "005490",
    "015760", "017670", "030200", "096770", "034730", "003550",
    "066570", "105560", "055550", "086790", "316140", "024110",
]

# 종목명 매핑 (UI 표시용)
_STOCK_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "005380": "현대차", "000270": "기아", "012330": "현대모비스",
    "207940": "삼성바이오로직스", "068270": "셀트리온", "005490": "POSCO홀딩스",
    "015760": "한국전력", "017670": "SK텔레콤", "030200": "KT",
    "096770": "SK이노베이션", "034730": "SK", "003550": "LG",
    "066570": "LG전자", "105560": "KB금융", "055550": "신한지주",
    "086790": "하나금융지주", "316140": "우리금융지주", "024110": "기업은행",
}


class GraphStore(DeterministicMockStore):
    """밸류체인 지식 그래프 (Mock + FactSet 연결 여지)."""

    _singleton: GraphStore | None = None

    @classmethod
    def get_default(cls) -> GraphStore:
        if cls._singleton is None:
            cls._singleton = cls()
            cls._singleton._build_graph()
        return cls._singleton

    def __init__(self, cache_ttl: int = 3600 * 24):
        super().__init__(cache_ttl)
        self._edges: dict = {}  # stock → {relation → [stocks]}

    def _build_graph(self):
        """결정론적 mock 밸류체인 구축."""
        for stock in _KNOWN_STOCKS:
            self._edges[stock] = {"supplier": [], "customer": [], "competitor": []}

        for stock in _KNOWN_STOCKS:
            rng = self._rng(stock, "graph")
            others = [s for s in _KNOWN_STOCKS if s != stock]
            rng.shuffle(others)

            # 공급사 2~4개
            n_sup = rng.randint(2, 4)
            suppliers = others[:n_sup]
            self._edges[stock]["supplier"] = suppliers
            # 양방향: 공급사의 customer에 자신 추가
            for sup in suppliers:
                if stock not in self._edges[sup]["customer"]:
                    self._edges[sup]["customer"].append(stock)

            # 경쟁사 1~3개 (대칭)
            n_comp = rng.randint(1, 3)
            competitors = others[n_sup:n_sup + n_comp]
            self._edges[stock]["competitor"] = competitors
            for comp in competitors:
                if stock not in self._edges[comp]["competitor"]:
                    self._edges[comp]["competitor"].append(stock)

    def neighbors(self, target: str, relation: str, depth: int = 1) -> set[str]:
        """
        BFS로 target의 relation 관계망을 depth-hop까지 탐색.

        Returns: 관계망 내 종목 코드 집합 (target 제외)
        """
        if target not in self._edges:
            return set()

        visited = {target}
        frontier = deque([(target, 0)])
        result = set()

        while frontier:
            node, d = frontier.popleft()
            if d >= depth:
                continue
            for neighbor in self._edges.get(node, {}).get(relation, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.add(neighbor)
                    frontier.append((neighbor, d + 1))

        return result

    def get_relations(self, stock: str) -> dict:
        """종목의 직접 관계 (1-hop) — UI 표시용."""
        edges = self._edges.get(stock, {})
        return {
            "supplier":   [{"code": s, "name": _STOCK_NAMES.get(s, s)} for s in edges.get("supplier", [])],
            "customer":   [{"code": s, "name": _STOCK_NAMES.get(s, s)} for s in edges.get("customer", [])],
            "competitor": [{"code": s, "name": _STOCK_NAMES.get(s, s)} for s in edges.get("competitor", [])],
        }

    def search_stocks(self, query: str) -> list[dict]:
        """종목 검색 (그래프 타겟 선택용)."""
        q = query.strip().lower()
        results = []
        for code, name in _STOCK_NAMES.items():
            if q in code or q in name.lower():
                results.append({"code": code, "name": name})
        return results[:10]

    def all_nodes(self) -> list[dict]:
        return [{"code": c, "name": _STOCK_NAMES.get(c, c)} for c in _KNOWN_STOCKS]


# ═══════════════════════════════════════════════════════════════════════════════
# 평가기 + lazy 컨텍스트 빌더 (register_kind)
# ═══════════════════════════════════════════════════════════════════════════════

def eval_graph(item, cond, ctx: dict) -> bool:
    """그래프 관계 평가 — lazy 주입된 _graph 컨텍스트(관계망 집합) 사용."""
    gctx = ctx.get("_graph", {})
    key = f"{cond.graph_target}:{cond.graph_relation}:{cond.graph_depth or 1}"
    network = gctx.get(key)
    if network is None:
        return False
    code = getattr(item, "stock_code", None)
    return code in network


def _collect_graph_specs(group) -> list:
    """AST에서 graph 조건의 (target, relation, depth) 수집."""
    specs = []
    for c in group.conditions:
        if c.kind == "graph":
            specs.append((c.graph_target, c.graph_relation, c.graph_depth or 1))
    for g in group.groups:
        specs.extend(_collect_graph_specs(g))
    return specs


def build_graph_context(group, items) -> dict:
    """lazy: 각 graph 조건의 관계망 사전계산."""
    specs = _collect_graph_specs(group)
    if not specs:
        return {}
    store = GraphStore.get_default()
    gctx = {}
    for (target, relation, depth) in specs:
        network = store.neighbors(target, relation, depth)
        gctx[f"{target}:{relation}:{depth}"] = network
    return {"_graph": gctx}


def graph_meta_catalog() -> dict:
    """API용 그래프 메타 (관계 유형 + 노드 목록)."""
    store = GraphStore.get_default()
    return {
        "relations": [
            {"id": "supplier", "label": "공급사", "description": "타겟에 납품하는 기업"},
            {"id": "customer", "label": "고객사", "description": "타겟으로부터 매출이 발생하는 기업"},
            {"id": "competitor", "label": "경쟁사", "description": "동일 시장 경쟁 기업"},
        ],
        "max_depth": 3,
        "nodes": store.all_nodes(),
    }
