"""BK0 · 실제 노드에 건 공통 계약 — 연습용 계보 · 백테스트 문지기 · 저장 문 · 쓰기 금지
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §1

## 왜 백테스트 문지기가 필요한가 (감사에서 찾은 것)

정책 백테스트 노드는 입력 비중을 되돌리지 않는다 — **옵티마이저의 요청(`req`)으로 정책을 다시
만들어** walk-forward 한다(`allocation_graph_nodes._backtest`). 그래서 옵티마이저가 아닌 곳에서 온
비중(노출 조절·알파·중립화 …)을 받으면 그 비중이 아니라 **다른 것을** 백테스트하고도 그 비중의 성과처럼
보인다. 또 오늘 계산한 노출·전망 전용 뷰를 과거 전체에 쓰면 룩어헤드다. 둘 다 조용히 벗겨 내지 않고
**거절**한다(짝: 옵티마이저 비중·깨끗한 계보는 통과 — 기존 골든 그대로).
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, client, market  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]


# ── 연습용 계보 ───────────────────────────────────────────────────────────────

def test_mock_returns_mark_every_downstream_node_as_practice(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from tests.test_allocation_graph import _run
    rep = _run(chain(backtest={}))
    assert rep["nodes"]["r"]["provenance"]["source"] == "mock"
    for nid in ("r", "o", "k", "b"):
        assert rep["nodes"][nid]["lineage"]["practice"] is True, nid


def test_loaded_returns_are_not_marked_practice(market):
    from tests.test_allocation_graph import _run
    rep = _run(chain(backtest={}))
    assert rep["nodes"]["r"]["provenance"]["source"] != "mock"
    assert all(rep["nodes"][n]["lineage"]["practice"] is False for n in ("r", "o", "k", "b"))


# ── 백테스트 문지기 ───────────────────────────────────────────────────────────

def _fixed(inputs, p):
    names = inputs["returns"]["names"]
    w = np.full(len(names), 1.0 / len(names))
    tags = {"overlay": p.overlay}
    if p.pit:
        tags["pit"] = p.pit
    return pg.NodeOutput(values={"weights": gn.weights_value(names, w, sigma_annual=None)},
                         view={"weights": dict(zip(names, w.tolist()))}, tags=tags)


class _FixedParams(gn.BaseModel):
    overlay: bool = False
    pit: str | None = None


def _registry_with_fixed() -> pg.Registry:
    reg = pg.Registry(port_types=gn.PORT_TYPES)
    for t in gn.REGISTRY.types():
        reg.register(gn.REGISTRY.get(t))
    reg.register(pg.NodeSpec("fixed", "고정 비중", inputs=(pg.Port("returns", "Returns"),),
                             outputs=(pg.Port("weights", "Weights"),), run=_fixed, params_model=_FixedParams))
    return reg


def _fixed_graph(**params):
    g = chain(risk=False)
    g["nodes"].append(_node("f", "fixed", **params))
    g["nodes"].append(_node("b", "backtest"))
    g["edges"] += [_edge("r", "returns", "f", "returns"), _edge("r", "returns", "b", "returns"),
                   _edge("f", "weights", "b", "weights")]
    return g


def test_the_backtest_refuses_weights_that_carry_no_policy(market):
    rep = pg.run(_fixed_graph(), _registry_with_fixed())
    b = rep["nodes"]["b"]
    assert b["status"] == pg.STATUS_FAILED
    assert "되돌려 볼 규칙" in b["reason"]


def test_the_backtest_refuses_an_overlay_before_running(market):
    rep = pg.run(_fixed_graph(overlay=True), _registry_with_fixed())
    b = rep["nodes"]["b"]
    assert b["status"] == pg.STATUS_FAILED and "오늘" in b["reason"] and "노출" in b["reason"]


def test_the_backtest_refuses_forward_only_lineage(market):
    rep = pg.run(_fixed_graph(pit="forward_only"), _registry_with_fixed())
    assert rep["nodes"]["b"]["status"] == pg.STATUS_FAILED
    assert "지금 시점" in rep["nodes"]["b"]["reason"]


def test_the_optimizer_policy_still_backtests(market):
    """짝 — 기존 사슬은 그대로 돈다(항상-거절 구현 배제)."""
    from tests.test_allocation_graph import _run
    assert _run(chain(backtest={}))["nodes"]["b"]["status"] == pg.STATUS_OK


def test_risk_accepts_weights_with_a_covariance_and_refuses_without(market):
    reg = _registry_with_fixed()
    g = chain(risk=False)
    g["nodes"] += [_node("f", "fixed"), _node("k", "risk")]
    g["edges"] += [_edge("r", "returns", "f", "returns"), _edge("f", "weights", "k", "weights")]
    k = pg.run(g, reg)["nodes"]["k"]
    assert k["status"] == pg.STATUS_FAILED and "공분산" in k["reason"]
    from tests.test_allocation_graph import _run
    assert _run(chain())["nodes"]["k"]["status"] == pg.STATUS_OK


# ── 새 포트 타입 ──────────────────────────────────────────────────────────────

def test_the_new_port_types_are_declared_once():
    for t in ("Scenario", "StressReport", "Scores", "RegimeState", "TimingSignal", "Trades",
              "TargetVersion", "StrategyResult"):
        assert gn.PORT_TYPES.count(t) == 1, t


# ── 저장 문 ──────────────────────────────────────────────────────────────────

def test_the_save_route_refuses_a_node_that_cannot_save(client, market):
    g = chain()                            # 비중 계산은 BL2 부터 저장(연구 기록)한다 — 저장이 없는 리스크 분해로 본다
    rid = next(n["id"] for n in g["nodes"] if n["type"] == "risk")
    r = client.post("/api/v1/allocation/graph/save", json={"graph": g, "node_id": rid, "preview_hash": "x"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["code"] == "not_savable"


def test_the_save_route_needs_its_fields(client):
    assert client.post("/api/v1/allocation/graph/save", json={"graph": {}}).status_code == 422


# ── 쓰기·주문 금지 트립와이어 ─────────────────────────────────────────────────

#: 노드 모듈이 **계산 경로에서** 부르면 안 되는 이름 — 저장·기록·승인·주문.
_WRITE_CALLS = ("save_target", "create_plan", "record_run", "advance_pointer", "transition",
                "record_fills", "create_entry", "place_order", "submit_order")
_FORBIDDEN_IMPORTS = ("src.kis_order_executor", "src.engine.trading_engine")


def _node_modules() -> list[Path]:
    return sorted((ROOT / "src" / "api").glob("allocation_graph_nodes*.py"))


def test_node_modules_never_import_the_order_path():
    for path in _node_modules():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
                assert not any(n.startswith(_FORBIDDEN_IMPORTS) for n in names), (path.name, names)


def test_run_functions_never_call_a_write():
    """저장 함수는 `_save_*` 안에서만 — 계산(run) 경로의 함수는 쓰기 이름을 부르지 않는다."""
    for path in _node_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if fn.name.startswith("_save_"):
                continue
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                f = call.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                assert name not in _WRITE_CALLS and not name.startswith("_save_"), (path.name, fn.name, name)


# ★계산 중 DB 쓰기 0★ (BL0) — 이 파일의 모든 그래프 계산이 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
