"""그래프 백테스트 요청 모델의 설정 — Pydantic v2 방식이고, 모르는 필드는 ★오류 없이 버린다★.

`class Config:`(v1 방식)는 Pydantic 2 에서 정의할 때마다 `PydanticDeprecatedSince20` 경고를 내고 v3 에서 없어진다(2026-11-08 · 스택 최신화 뒤
남은 경고). `model_config = ConfigDict(...)` 로 옮기면서, 그 설정이 하던 일(React Flow 가 덧붙이는 필드를 버림)을 동작으로 못 박는다.
"""
from __future__ import annotations

import importlib
import warnings

import pytest
from pydantic import ValidationError
from pydantic.warnings import PydanticDeprecatedSince20


def test_defining_the_models_raises_no_pydantic_deprecation():
    import src.models.graph_schema as gs
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(gs)
    dep = [w for w in caught if issubclass(w.category, PydanticDeprecatedSince20)]
    assert not dep, f"v1 방식 설정이 남았다: {[str(w.message)[:80] for w in dep]}"


def _node(**extra):
    return {"id": "n1", "type": "dataSource", "position": {"x": 0, "y": 0}, "data": {"type": "dataSource"}, **extra}


def test_unknown_fields_are_dropped_not_rejected_and_not_kept():
    """★짝★ React Flow 가 덧붙이는 낯선 필드(예: `zIndex`)는 받아 주되 모델에 남기지 않는다 — forbid·allow 둘 다 배제."""
    from src.models.graph_schema import GraphBacktestRequest, GraphEdge, GraphNode

    n = GraphNode.model_validate(_node(zIndex=3))
    assert not hasattr(n, "zIndex") and "zIndex" not in n.model_dump()

    e = GraphEdge.model_validate({"source": "a", "target": "b", "interactionWidth": 20})
    assert "interactionWidth" not in e.model_dump()

    r = GraphBacktestRequest.model_validate({"nodes": [_node()], "viewport": {"x": 0, "y": 0, "zoom": 1}})
    assert "viewport" not in r.model_dump()


def test_the_real_rules_still_reject():
    """설정을 옮겨도 모델의 실제 검사는 그대로 — 자기 자신으로 가는 선은 거부한다."""
    from src.models.graph_schema import GraphEdge
    with pytest.raises(ValidationError):
        GraphEdge.model_validate({"source": "a", "target": "a"})
