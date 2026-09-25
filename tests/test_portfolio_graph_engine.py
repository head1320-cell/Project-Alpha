"""BI1 · 포트폴리오 그래프 실행기 — ★순수 엔진 계약★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` §4.1·4.2·4.4 ·
대상 `src/engine/portfolio_graph.py`

장난감 노드(정수 더하기)로 **엔진만** 건다 — 실제 포트폴리오 노드는 BI2.

## 거는 것

- 파일 포맷·버전이 다르면 명명된 오류로 거부한다(짝: 맞으면 통과).
- 연결은 출력 타입 == 입력 타입일 때만(짝: 맞으면 통과).
- 순환 거부 · 필수 입력 누락 · 한 입력 포트에 두 연결 · 없는 노드를 가리키는 링크 · 중복 id.
- ★모르는 노드 타입은 버리지 않는다★ — 결과에 자기 자리를 갖고 `blocked` + 사유.
- ★실패한 노드의 하류는 기본값으로 돌지 않는다★ — `blocked` + 어느 상류 때문인지.
- 성공 그래프는 전부 `ok`(항상-blocked 구현 배제) · 실행 순서는 위상 순서.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.engine import portfolio_graph as pg

# ── 장난감 레지스트리 ───────────────────────────────────────────────────────


class _ConstParams(BaseModel):
    value: int = Field(0, ge=-100, le=100)


def _const(inputs, params):
    return pg.NodeOutput(values={"out": params.value}, view={"value": params.value},
                         provenance={"grade": "E0"})


def _add(inputs, params):
    b = inputs.get("b")
    total = inputs["a"] + (b if b is not None else 0)
    return pg.NodeOutput(values={"out": total}, view={"value": total})


def _boom(inputs, params):
    raise pg.NodeFailure("일부러 실패 — 재료 없음")


def _label(inputs, params):
    return pg.NodeOutput(values={"text": f"v={inputs['x']}"}, view={"text": f"v={inputs['x']}"})


def _registry() -> pg.Registry:
    reg = pg.Registry(port_types=("Num", "Text"))
    reg.register(pg.NodeSpec("const", "상수", inputs=(),
                             outputs=(pg.Port("out", "Num"),), params_model=_ConstParams,
                             run=_const))
    reg.register(pg.NodeSpec("add", "더하기",
                             inputs=(pg.Port("a", "Num"), pg.Port("b", "Num", required=False)),
                             outputs=(pg.Port("out", "Num"),), run=_add))
    reg.register(pg.NodeSpec("boom", "실패", inputs=(pg.Port("a", "Num"),),
                             outputs=(pg.Port("out", "Num"),), run=_boom))
    reg.register(pg.NodeSpec("label", "글자", inputs=(pg.Port("x", "Num"),),
                             outputs=(pg.Port("text", "Text"),), run=_label))
    return reg


def _g(nodes, edges, **over):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}
    g.update(over)
    return g


def _n(id_, type_, **params):
    return {"id": id_, "type": type_, "params": params, "position": {"x": 0, "y": 0}}


def _e(src, sp, dst, dp, id_=None):
    return {"id": id_ or f"{src}.{sp}->{dst}.{dp}", "source": src, "source_port": sp,
            "target": dst, "target_port": dp}


def _codes(report) -> set[str]:
    return {e["code"] for e in report["errors"]}


_CHAIN = _g([_n("c1", "const", value=2), _n("c2", "const", value=3), _n("s", "add"),
             _n("t", "label")],
            [_e("c1", "out", "s", "a"), _e("c2", "out", "s", "b"), _e("s", "out", "t", "x")])


# ── 성공 경로 (짝의 한쪽 — 항상-거부 구현 배제) ──────────────────────────────

def test_a_valid_graph_validates_clean():
    rep = pg.validate(_CHAIN, _registry())
    assert rep["ok"] is True and rep["errors"] == []


def test_a_valid_graph_runs_every_node_ok_in_topological_order():
    out = pg.run(_CHAIN, _registry())
    assert out["ok"] is True
    assert {nid: r["status"] for nid, r in out["nodes"].items()} == \
        {"c1": "ok", "c2": "ok", "s": "ok", "t": "ok"}
    order = out["order"]
    assert order.index("c1") < order.index("s") < order.index("t")
    assert order.index("c2") < order.index("s")
    assert out["nodes"]["s"]["view"] == {"value": 5}
    assert out["nodes"]["t"]["view"] == {"text": "v=5"}


def test_an_unconnected_optional_input_is_none_not_a_default_value():
    g = _g([_n("c", "const", value=4), _n("s", "add")], [_e("c", "out", "s", "a")])
    out = pg.run(g, _registry())
    assert out["nodes"]["s"]["status"] == "ok" and out["nodes"]["s"]["view"] == {"value": 4}


def test_provenance_travels_with_the_node_result():
    out = pg.run(_CHAIN, _registry())
    assert out["nodes"]["c1"]["provenance"] == {"grade": "E0"}
    assert out["nodes"]["s"]["provenance"] == {}


# ── 포맷·버전 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("over,code", [
    ({"format": "comfyui-workflow"}, "format"),
    ({"version": 2}, "version"),
    ({"version": "1"}, "version"),
])
def test_a_foreign_file_is_refused_by_name(over, code):
    g = {**_CHAIN, **over}
    rep = pg.validate(g, _registry())
    assert rep["ok"] is False and code in _codes(rep)
    out = pg.run(g, _registry())
    assert out["ok"] is False and out["nodes"] == {}, "포맷이 다르면 아무것도 실행하지 않는다"


@pytest.mark.parametrize("bad", [None, [], "x", {"format": pg.FORMAT, "version": 1}])
def test_a_malformed_document_is_refused_not_crashed(bad):
    rep = pg.validate(bad, _registry())
    assert rep["ok"] is False and rep["errors"]


# ── 연결 규칙 ─────────────────────────────────────────────────────────────

def test_a_type_mismatch_is_refused():
    g = _g([_n("c", "const"), _n("t", "label"), _n("s", "add")],
           [_e("c", "out", "t", "x"), _e("t", "text", "s", "a")])
    rep = pg.validate(g, _registry())
    errs = [e for e in rep["errors"] if e["code"] == "type_mismatch"]
    assert errs and errs[0]["edge_id"] == "t.text->s.a"
    assert "Text" in errs[0]["message"] and "Num" in errs[0]["message"]


def test_a_cycle_is_refused_and_nothing_runs():
    g = _g([_n("a", "add"), _n("b", "add")],
           [_e("a", "out", "b", "a"), _e("b", "out", "a", "a")])
    rep = pg.validate(g, _registry())
    assert "cycle" in _codes(rep)
    out = pg.run(g, _registry())
    assert out["ok"] is False and out["nodes"] == {}


def test_a_missing_required_input_blocks_the_node_by_name():
    g = _g([_n("s", "add")], [])
    rep = pg.validate(g, _registry())
    errs = [e for e in rep["errors"] if e["code"] == "missing_input"]
    assert errs and errs[0]["node_id"] == "s" and "a" in errs[0]["message"]
    out = pg.run(g, _registry())
    assert out["nodes"]["s"]["status"] == "blocked"
    assert "a" in out["nodes"]["s"]["reason"]


def test_two_links_into_one_input_are_refused():
    g = _g([_n("c1", "const"), _n("c2", "const"), _n("s", "add")],
           [_e("c1", "out", "s", "a"), _e("c2", "out", "s", "a")])
    assert "multiple_inputs" in _codes(pg.validate(g, _registry()))


def test_one_output_may_fan_out():
    """★짝★ — 한 출력에서 여러 입력으로는 된다(ComfyUI 와 같다)."""
    g = _g([_n("c", "const", value=1), _n("s", "add")],
           [_e("c", "out", "s", "a"), _e("c", "out", "s", "b")])
    out = pg.run(g, _registry())
    assert out["ok"] and out["nodes"]["s"]["view"] == {"value": 2}


@pytest.mark.parametrize("edge,code", [
    (_e("ghost", "out", "s", "a"), "dangling_edge"),
    (_e("c", "nope", "s", "a"), "unknown_port"),
    (_e("c", "out", "s", "zzz"), "unknown_port"),
])
def test_a_link_to_nothing_is_named(edge, code):
    g = _g([_n("c", "const"), _n("s", "add")], [edge])
    assert code in _codes(pg.validate(g, _registry()))


def test_duplicate_node_ids_are_refused():
    g = _g([_n("c", "const"), _n("c", "const")], [])
    assert "duplicate_node" in _codes(pg.validate(g, _registry()))


def test_bad_params_are_refused_by_node_and_block_it():
    g = _g([_n("c", "const", value=999), _n("t", "label")], [_e("c", "out", "t", "x")])
    rep = pg.validate(g, _registry())
    errs = [e for e in rep["errors"] if e["code"] == "bad_params"]
    assert errs and errs[0]["node_id"] == "c"
    out = pg.run(g, _registry())
    assert out["nodes"]["c"]["status"] == "blocked"
    assert out["nodes"]["t"]["status"] == "blocked"


# ── 모르는 노드 — 버리지 않는다 ──────────────────────────────────────────

def test_an_unknown_node_type_keeps_its_place_and_says_why():
    g = _g([_n("c", "const", value=1), _n("x", "future_node", k=1), _n("t", "label")],
           [_e("c", "out", "x", "in"), _e("x", "out", "t", "x")])
    rep = pg.validate(g, _registry())
    assert "unknown_type" in _codes(rep)
    out = pg.run(g, _registry())
    assert set(out["nodes"]) == {"c", "x", "t"}, "★아무 노드도 버리지 않는다★"
    assert out["nodes"]["x"]["status"] == "blocked"
    assert "future_node" in out["nodes"]["x"]["reason"]
    assert out["nodes"]["t"]["status"] == "blocked"
    assert out["nodes"]["c"]["status"] == "ok", "관계없는 노드는 여전히 돈다"


# ── 실패 전파 ─────────────────────────────────────────────────────────────

def test_a_failed_node_blocks_its_downstream_and_names_the_culprit():
    g = _g([_n("c", "const", value=1), _n("b", "boom"), _n("t", "label"),
            _n("c2", "const", value=7), _n("t2", "label")],
           [_e("c", "out", "b", "a"), _e("b", "out", "t", "x"), _e("c2", "out", "t2", "x")])
    out = pg.run(g, _registry())
    assert out["ok"] is False
    b, t = out["nodes"]["b"], out["nodes"]["t"]
    assert b["status"] == "failed" and "재료 없음" in b["reason"]
    assert t["status"] == "blocked" and "b" in t["reason"] and "boom" in t["reason"]
    assert "view" not in t or t["view"] is None, "막힌 노드는 결과를 지어내지 않는다"
    assert out["nodes"]["t2"]["status"] == "ok", "★옆 가지는 계속 돈다★"


def test_an_unexpected_exception_is_a_failure_with_its_kind_not_a_crash():
    reg = _registry()

    def _crash(inputs, params):
        raise ZeroDivisionError("x")

    reg.register(pg.NodeSpec("crash", "터짐", inputs=(), outputs=(pg.Port("out", "Num"),),
                             run=_crash))
    out = pg.run(_g([_n("k", "crash")], []), reg)
    assert out["nodes"]["k"]["status"] == "failed"
    assert "ZeroDivisionError" in out["nodes"]["k"]["reason"]


def test_a_node_that_forgets_a_declared_output_fails_instead_of_passing_none():
    reg = _registry()
    reg.register(pg.NodeSpec("forget", "잊음", inputs=(), outputs=(pg.Port("out", "Num"),),
                             run=lambda i, p: pg.NodeOutput(values={}, view={})))
    g = _g([_n("f", "forget"), _n("t", "label")], [_e("f", "out", "t", "x")])
    out = pg.run(g, reg)
    assert out["nodes"]["f"]["status"] == "failed" and "out" in out["nodes"]["f"]["reason"]
    assert out["nodes"]["t"]["status"] == "blocked"


# ── 레지스트리·카탈로그 ───────────────────────────────────────────────────

def test_the_catalog_describes_ports_and_params_for_the_palette():
    cat = {c["type"]: c for c in _registry().catalog()}
    assert cat["add"]["inputs"] == [{"name": "a", "type": "Num", "required": True},
                                    {"name": "b", "type": "Num", "required": False}]
    assert cat["const"]["params_schema"]["properties"]["value"]["maximum"] == 100
    assert cat["add"]["params_schema"] is None


def test_the_registry_refuses_undeclared_port_types_and_duplicates():
    reg = pg.Registry(port_types=("Num",))
    with pytest.raises(ValueError):
        reg.register(pg.NodeSpec("x", "x", inputs=(pg.Port("a", "Str"),), outputs=(),
                                 run=_add))
    reg.register(pg.NodeSpec("y", "y", inputs=(), outputs=(), run=_add))
    with pytest.raises(ValueError):
        reg.register(pg.NodeSpec("y", "y", inputs=(), outputs=(), run=_add))


# ── BJ1 · 설명 자리 — ★모든 노드가 사람이 읽는 설명을 갖는다★ ─────────────

def _explaining_registry() -> pg.Registry:
    reg = pg.Registry(port_types=("Num",))
    reg.register(pg.NodeSpec(
        "const", "상수", inputs=(), outputs=(pg.Port("out", "Num"),), params_model=_ConstParams,
        run=_const, stage="data", plain_label="숫자 정하기", plain_description="숫자 하나를 내요",
        explain=lambda view, prov, params: {"title": f"숫자 {view['value']}을 정했어요"}))
    reg.register(pg.NodeSpec("boom", "실패", inputs=(pg.Port("a", "Num"),),
                             outputs=(pg.Port("out", "Num"),), run=_boom, plain_label="터지는 단계"))
    reg.register(pg.NodeSpec("label", "글자", inputs=(pg.Port("x", "Num"),),
                             outputs=(pg.Port("text", "Num"),), run=_label, plain_label="글자로 바꾸기"))
    return reg


def test_an_ok_node_carries_its_own_explanation():
    out = pg.run(_g([_n("c", "const", value=3)], []), _explaining_registry())
    assert out["nodes"]["c"]["explain"] == {"title": "숫자 3을 정했어요"}


def test_a_node_without_an_explainer_still_gets_a_plain_title():
    g = _g([_n("c", "const", value=3), _n("t", "label")], [_e("c", "out", "t", "x")])
    out = pg.run(g, _explaining_registry())
    assert out["nodes"]["t"]["explain"]["title"] == "‘글자로 바꾸기’를 계산했어요"


def test_a_failed_node_says_so_in_plain_words_with_the_reason():
    g = _g([_n("c", "const", value=1), _n("b", "boom"), _n("t", "label")],
           [_e("c", "out", "b", "a"), _e("b", "out", "t", "x")])
    out = pg.run(g, _explaining_registry())
    fb = out["nodes"]["b"]["explain"]
    assert fb["title"] == "계산하지 못했어요"
    assert fb["trust"] == [{"state": "failed", "text": "일부러 실패 — 재료 없음"}]
    tb = out["nodes"]["t"]["explain"]
    assert tb["title"] == "계산하지 못했어요"
    assert "앞 단계 ‘터지는 단계’" in tb["facts"][0], "막힌 이유는 상류의 쉬운 이름으로"


def test_an_explainer_that_crashes_does_not_hide_the_result_or_invent_text():
    reg = _explaining_registry()
    reg.register(pg.NodeSpec("bad", "나쁜 설명", inputs=(), outputs=(pg.Port("out", "Num"),),
                             run=lambda i, p: pg.NodeOutput(values={"out": 1}, view={"value": 1}),
                             explain=lambda v, pr, pa: 1 / 0))
    r = pg.run(_g([_n("x", "bad")], []), reg)["nodes"]["x"]
    assert r["status"] == "ok" and r["view"] == {"value": 1}, "설명 실패가 결과를 지우지 않는다"
    assert r["explain"]["trust"][0]["state"] == "unknown"
    assert "ZeroDivisionError" in r["explain"]["trust"][0]["text"]


def test_an_unknown_node_is_explained_as_unknown():
    g = _g([_n("f", "future_node")], [])
    ex = pg.run(g, _explaining_registry())["nodes"]["f"]["explain"]
    assert ex["title"] == "모르는 노드예요" and "future_node" in ex["facts"][0]


def test_the_catalog_carries_plain_words_and_stage():
    c = {x["type"]: x for x in _explaining_registry().catalog()}["const"]
    assert (c["stage"], c["plain_label"], c["plain_description"]) == ("data", "숫자 정하기", "숫자 하나를 내요")
