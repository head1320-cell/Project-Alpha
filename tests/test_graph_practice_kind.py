"""BT7 · 연습용 표시 — ★화면이 문구 부분일치로 판정하지 않게, 서버가 표시를 단다★
==============================================================================
`explain.trust` 의 연습용(합성 데이터) 줄은 `kind: "practice"` 를 단다. 화면의 "연습용 데이터" 칩은 이 표시만 본다
(예전엔 `text.includes("연습용")` — 문구를 다듬으면 칩이 조용히 사라지거나 엉뚱한 줄에 붙을 수 있었다).

## 거는 것
- 노드 모듈에서 연습용 문구를 `_t(UNKNOWN, …)` 로 직접 만드는 곳이 없다(AST) — 모두 `_practice(…)` 를 거친다.
- `_practice` 는 몰라요(unknown) 상태와 표시를 함께 단다.
- mock 으로 핵심 사슬을 돌리면 수익률 불러오기의 설명에 표시가 있고, 종목 고르기에는 없다(짝).
- 표시가 붙은 줄은 모두 연습용을 말한다 — 표시를 다른 줄에 붙이지 않는다(역방향).
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import allocation_graph_explain as ex  # noqa: E402
from src.api import allocation_graph_routes as routes  # noqa: E402

API = pathlib.Path(__file__).resolve().parents[1] / "src" / "api"
F = {"format": "project-alpha.portfolio-graph", "version": 1}


def _strings_of(tree: ast.Module) -> dict[str, str]:
    """모듈 상단의 `NAME = "..."` 상수."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _text_of(arg: ast.AST, consts: dict[str, str]) -> str:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return consts.get(arg.id, "")
    if isinstance(arg, ast.JoinedStr):
        return "".join(v.value for v in arg.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def test_no_node_module_builds_a_practice_line_without_the_mark():
    offenders = []
    files = sorted(API.glob("allocation_graph*.py"))
    assert len(files) > 10
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        consts = _strings_of(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t" \
                    and len(node.args) >= 2 and "연습용" in _text_of(node.args[1], consts):
                offenders.append(f"{f.name}:{node.lineno}")
    assert offenders == [], f"연습용 줄은 _practice(...) 로 — 표시 없이 만든 곳: {offenders}"


def test_the_practice_helper_marks_the_line_as_unknown_and_practice():
    t = ex._practice()
    assert t == {"state": ex.UNKNOWN, "text": ex._PRACTICE, "kind": "practice"}
    assert ex._practice("다른 문장")["kind"] == "practice"
    assert "kind" not in ex._t(ex.UNKNOWN, "연습용과 상관없는 줄")                    # ★짝★ 보통 줄엔 없다


def test_a_mock_core_chain_marks_returns_as_practice_and_not_the_universe():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes.router)
    nodes = [{"id": "u", "type": "universe", "params": {"tickers": ["005930", "000660"]}},
             {"id": "r", "type": "returns", "params": {}}]
    edges = [{"id": "u.universe->r.universe", "source": "u", "source_port": "universe", "target": "r",
              "target_port": "universe"}]
    body = TestClient(app).post("/api/v1/allocation/graph/run", json={**F, "nodes": nodes, "edges": edges}).json()
    kinds = lambda nid: [t.get("kind") for t in (body["nodes"][nid].get("explain") or {}).get("trust", [])]  # noqa: E731
    assert "practice" in kinds("r")
    assert "practice" not in kinds("u")
    for nid in ("u", "r"):
        for t in (body["nodes"][nid].get("explain") or {}).get("trust", []):
            if t.get("kind") == "practice":
                assert "연습용" in t["text"] and t["state"] == ex.UNKNOWN
