"""CF3 · 관계 문장 — 선 하나가 무엇을 어디서 어디로, 무엇에 쓰이려고 나르는지 (서버가 쓴다)
==============================================================================
대상 `src/api/allocation_graph_relations.py`(순수 — `src.*` import 0). 틀:
`‘{보내는 노드}’의 {포트 쉬운 이름}({선 요약}) → ‘{받는 노드}’ {받는 포트 쉬운 이름} 자리. {받는 포트 role}`
요약이 없으면(계산 전) 괄호를, role 이 없으면 둘째 문장을 뺀다. `/validate`·`/run` 이 `relations` 를 싣는다.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_relations as rel  # noqa: E402
from tests.test_allocation_graph_explain import FORBIDDEN  # noqa: E402
from tests.test_cf3_golden import VIEWS, _chain, market  # noqa: E402, F401

KINDS = {
    "src": {"plain_label": "수익률 불러오기", "inputs": [],
            "outputs": [{"name": "returns", "type": "Returns"}]},
    "dst": {"plain_label": "비중 계산", "inputs": [
        {"name": "returns", "type": "Returns", "required": True, "role": "공분산을 재는 데 써요."},
        {"name": "other", "type": "Returns", "required": False}], "outputs": []},
}
PLAIN = {"Returns": "수익률"}
NODES = [{"id": "a", "type": "src"}, {"id": "b", "type": "dst"}]


def _e(tp="returns", id_="a.returns->b.returns", **over):
    return {"id": id_, "source": "a", "source_port": "returns", "target": "b", "target_port": tp, **over}


def test_the_template_with_a_brief_and_a_role():
    out = rel.relations(NODES, [_e()], KINDS, PLAIN, briefs={("a", "returns"): "5종목 · 756일"})
    r = out["a.returns->b.returns"]
    assert r["text"] == "‘수익률 불러오기’의 수익률(5종목 · 756일) → ‘비중 계산’ 수익률 자리. 공분산을 재는 데 써요."
    assert r == {**r, "flows": "수익률", "role": "공분산을 재는 데 써요.", "required": True, "brief": "5종목 · 756일"}


def test_no_brief_no_parentheses():
    r = rel.relations(NODES, [_e()], KINDS, PLAIN)["a.returns->b.returns"]
    assert "(" not in r["text"] and r["brief"] is None


def test_no_role_no_second_sentence():
    r = rel.relations(NODES, [_e("other", id_="x")], KINDS, PLAIN)["x"]
    assert r["text"] == "‘수익률 불러오기’의 수익률 → ‘비중 계산’ 수익률 자리." and r["role"] is None
    assert r["required"] is False


@pytest.mark.parametrize("bad", [
    _e(target="zz"), _e(tp="nope"), {**_e(), "source_port": "nope"},
    {**_e(), "source": "b", "target": "a", "target_port": "x"},
])
def test_invalid_edges_get_no_sentence(bad):
    assert rel.relations(NODES, [bad], KINDS, PLAIN) == {}


def test_types_must_match():
    kinds = {**KINDS, "dst": {**KINDS["dst"], "inputs": [{"name": "returns", "type": "Weights", "required": True}]}}
    assert rel.relations(NODES, [_e()], kinds, PLAIN) == {}


def test_the_module_is_pure():
    tree = ast.parse(pathlib.Path("src/api/allocation_graph_relations.py").read_text("utf-8"))
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in mods if m.startswith("src")], mods


# ── 라우트 ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_validate_carries_relations_without_briefs(client):
    body = client.post("/api/v1/allocation/graph/validate", json=_chain("bl", views=VIEWS)).json()
    r = body["relations"]["r.returns->o.returns"]
    assert r["text"].startswith("‘수익률 불러오기’의 수익률 →") and "(" not in r["text"].split("→")[0]
    assert r["role"] and r["text"].endswith(r["role"])
    assert set(body["relations"]) == {e["id"] for e in _chain("bl", views=VIEWS)["edges"]}


def test_run_carries_relations_with_briefs_and_edges(client, market):
    body = client.post("/api/v1/allocation/graph/run", json=_chain("bl", views=VIEWS)).json()
    r = body["relations"]["r.returns->o.returns"]
    brief = body["nodes"]["r"]["briefs"]["returns"]
    assert f"({brief})" in r["text"] and r["brief"] == brief
    assert body["edges"]["v.views->o.views"]["issues"]               # 다리 빠진 생각 둘
    texts = [x["text"] for x in body["relations"].values()] + \
            [i["text"] for x in body["edges"].values() for i in x["issues"] or []] + \
            [f["text"] for x in body["edges"].values() for f in x["facts"] or []]
    assert not [t for t in texts for w in FORBIDDEN if w in t]
