"""BK0 · 계보 태그 · 입력 문지기 · 미리보기 해시 · 저장 액션 — ★순수 엔진 계약★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §1 · 대상 `src/engine/portfolio_graph.py`

레포의 도구를 노드로 옮기면 **출처가 다른 값**(연습용 합성 · 전망 전용 · 오늘 판단을 얹은 비중)이
같은 포트를 타고 흐른다. 엔진이 그 사실을 하류로 나르지 않으면 백테스트가 모르고 섞는다.

## 거는 것 (모두 짝과 함께)
- 계보는 **하류로 전이된다**(직접 부모만이 아니다) — 연습용은 OR, 시점 정합은 가장 약한 값이 이긴다.
  짝: 태그 없는 그래프의 계보는 깨끗하다(항상-오염 구현 배제).
- `admits` 가 거절하면 노드는 **실패**하고 사유가 그대로 실린다 — 짝: 깨끗한 입력은 통과.
- 성공한 노드마다 `view_hash` — 같은 view 는 같은 해시, 다른 view 는 다른 해시.
- 저장은 **run 밖**에서만: 미리보기 해시가 지금 계산과 같을 때만 `save` 를 **한 번** 부른다.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.engine import portfolio_graph as pg


class _Src(BaseModel):
    value: int = Field(1, ge=0, le=100)
    practice: bool = False
    pit: str | None = None
    overlay: bool = False


def _source(inputs, p):
    tags = {"practice": p.practice, "overlay": p.overlay}
    if p.pit:
        tags["pit"] = p.pit
    return pg.NodeOutput(values={"out": p.value}, view={"value": p.value}, tags=tags)


def _pass(inputs, p):
    total = sum(v for v in inputs.values() if v is not None)
    return pg.NodeOutput(values={"out": total}, view={"value": total})


def _refuse_forward(lineage: dict) -> str | None:
    if lineage.get("pit") == "forward_only":
        return "전망 전용 값은 받지 않아요."
    if lineage.get("overlay"):
        return "노출을 얹은 값은 받지 않아요."
    return None


SAVED: list[dict] = []


def _save(values, view, params) -> dict:
    SAVED.append({"values": values, "view": view})
    return {"saved_id": f"sv_{values['out']}", "text": "저장했어요"}


def _registry() -> pg.Registry:
    reg = pg.Registry(port_types=("Num",))
    reg.register(pg.NodeSpec("src", "원천", inputs=(), outputs=(pg.Port("out", "Num"),),
                             run=_source, params_model=_Src))
    reg.register(pg.NodeSpec("pass", "전달", inputs=(pg.Port("a", "Num"), pg.Port("b", "Num", required=False)),
                             outputs=(pg.Port("out", "Num"),), run=_pass))
    reg.register(pg.NodeSpec("gate", "문지기", inputs=(pg.Port("a", "Num"),),
                             outputs=(pg.Port("out", "Num"),), run=_pass, admits=_refuse_forward))
    reg.register(pg.NodeSpec("keep", "보관", inputs=(pg.Port("a", "Num"),),
                             outputs=(pg.Port("out", "Num"),), run=_pass, save=_save))
    return reg


def _g(nodes, edges):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _n(id_, type_, **params):
    return {"id": id_, "type": type_, "params": params, "position": {"x": 0, "y": 0}}


def _e(src, dst, dp="a"):
    return {"id": f"{src}->{dst}.{dp}", "source": src, "source_port": "out", "target": dst, "target_port": dp}


# ── 계보 ─────────────────────────────────────────────────────────────────────

def test_practice_travels_downstream_transitively():
    rep = pg.run(_g([_n("s", "src", practice=True), _n("p1", "pass"), _n("p2", "pass")],
                    [_e("s", "p1"), _e("p1", "p2")]), _registry())
    assert rep["ok"], rep
    assert rep["nodes"]["s"]["lineage"]["practice"] is True
    assert rep["nodes"]["p2"]["lineage"]["practice"] is True, "직접 부모가 아니어도 전이된다"


def test_a_clean_graph_has_a_clean_lineage():
    rep = pg.run(_g([_n("s", "src"), _n("p1", "pass")], [_e("s", "p1")]), _registry())
    lin = rep["nodes"]["p1"]["lineage"]
    assert lin["practice"] is False and lin["overlay"] is False and lin["pit"] is None


@pytest.mark.parametrize("a,b,want", [
    ("pit", "pit", "pit"),
    ("pit", "unknown", "unknown"),
    ("unknown", "forward_only", "forward_only"),
    ("pit", "forward_only", "forward_only"),
    ("pit", None, "pit"),              # 선언하지 않은 쪽은 판정에 끼지 않는다
])
def test_the_weakest_point_in_time_claim_wins(a, b, want):
    rep = pg.run(_g([_n("x", "src", **({"pit": a} if a else {})), _n("y", "src", **({"pit": b} if b else {})),
                     _n("p", "pass")], [_e("x", "p", "a"), _e("y", "p", "b")]), _registry())
    assert rep["nodes"]["p"]["lineage"]["pit"] == want


def test_merge_lineage_is_a_pure_function():
    m = pg.merge_lineage({"practice": True, "sources": ["a"]}, {"pit": "pit", "sources": ["b", "a"]})
    assert m == {"pit": "pit", "practice": True, "overlay": False, "sources": ["a", "b"]}
    assert pg.merge_lineage() == {"pit": None, "practice": False, "overlay": False, "sources": []}


# ── 문지기 ───────────────────────────────────────────────────────────────────

def test_admits_refuses_forward_only_even_two_hops_up():
    rep = pg.run(_g([_n("s", "src", pit="forward_only"), _n("p", "pass"), _n("g", "gate")],
                    [_e("s", "p"), _e("p", "g")]), _registry())
    g = rep["nodes"]["g"]
    assert g["status"] == pg.STATUS_FAILED
    assert g["reason"] == "전망 전용 값은 받지 않아요."
    assert g["explain"]["title"] == "계산하지 못했어요"


def test_admits_refuses_an_overlay():
    rep = pg.run(_g([_n("s", "src", overlay=True), _n("g", "gate")], [_e("s", "g")]), _registry())
    assert rep["nodes"]["g"]["status"] == pg.STATUS_FAILED
    assert "노출" in rep["nodes"]["g"]["reason"]


def test_admits_lets_a_point_in_time_input_through():
    rep = pg.run(_g([_n("s", "src", pit="pit"), _n("g", "gate")], [_e("s", "g")]), _registry())
    assert rep["nodes"]["g"]["status"] == pg.STATUS_OK


# ── 미리보기 해시 ─────────────────────────────────────────────────────────────

def test_every_ok_node_has_a_stable_view_hash():
    g = _g([_n("s", "src", value=3), _n("p", "pass")], [_e("s", "p")])
    a, b = pg.run(g, _registry()), pg.run(g, _registry())
    assert a["nodes"]["p"]["view_hash"] and a["nodes"]["p"]["view_hash"] == b["nodes"]["p"]["view_hash"]
    c = pg.run(_g([_n("s", "src", value=4), _n("p", "pass")], [_e("s", "p")]), _registry())
    assert c["nodes"]["p"]["view_hash"] != a["nodes"]["p"]["view_hash"]


def test_failed_nodes_have_no_view_hash():
    rep = pg.run(_g([_n("s", "src", pit="forward_only"), _n("g", "gate")], [_e("s", "g")]), _registry())
    assert rep["nodes"]["g"].get("view_hash") is None


# ── 저장 액션 ─────────────────────────────────────────────────────────────────

def _keep_graph(value=5):
    return _g([_n("s", "src", value=value), _n("k", "keep")], [_e("s", "k")])


def test_run_never_calls_save():
    SAVED.clear()
    pg.run(_keep_graph(), _registry())
    assert SAVED == []


def test_save_calls_the_node_save_once_when_the_preview_matches():
    SAVED.clear()
    reg = _registry()
    h = pg.run(_keep_graph(), reg)["nodes"]["k"]["view_hash"]
    out = pg.save_node(_keep_graph(), "k", h, reg)
    assert out == {"ok": True, "saved_id": "sv_5", "text": "저장했어요", "node_id": "k"}
    assert len(SAVED) == 1 and SAVED[0]["values"]["out"] == 5


def test_save_refuses_a_stale_preview_and_writes_nothing():
    SAVED.clear()
    reg = _registry()
    h = pg.run(_keep_graph(5), reg)["nodes"]["k"]["view_hash"]
    out = pg.save_node(_keep_graph(6), "k", h, reg)
    assert out["ok"] is False and out["code"] == "stale"
    assert SAVED == []


@pytest.mark.parametrize("node_id,code", [("s", "not_savable"), ("zz", "no_node")])
def test_save_refuses_nodes_that_cannot_save(node_id, code):
    SAVED.clear()
    out = pg.save_node(_keep_graph(), node_id, "x", _registry())
    assert out["ok"] is False and out["code"] == code
    assert SAVED == []


def test_save_refuses_a_node_that_did_not_compute():
    SAVED.clear()
    g = _g([_n("s", "src"), _n("k", "keep")], [])            # 필수 입력 없음 → blocked
    out = pg.save_node(g, "k", "x", _registry())
    assert out["ok"] is False and out["code"] == "not_ok"
    assert SAVED == []


def test_catalog_says_which_nodes_can_save():
    cat = {c["type"]: c for c in _registry().catalog()}
    assert cat["keep"]["savable"] is True and cat["pass"]["savable"] is False


# ── 계보를 읽는 노드 (BK W4) ──────────────────────────────────────────────────

def test_a_node_that_asks_for_lineage_receives_its_merged_input_lineage():
    seen = {}

    def peek(inputs, p, lineage):
        seen.update(lineage)
        return pg.NodeOutput(values={"out": 0}, view={"practice": lineage["practice"]})
    reg = _registry()
    reg.register(pg.NodeSpec("peek", "보기", inputs=(pg.Port("a", "Num"),), outputs=(pg.Port("out", "Num"),),
                             run=peek, wants_lineage=True))
    rep = pg.run(_g([_n("s", "src", practice=True, pit="forward_only"), _n("p", "pass"), _n("k", "peek")],
                    [_e("s", "p"), _e("p", "k")]), reg)
    assert rep["nodes"]["k"]["status"] == "ok", rep["nodes"]["k"]["reason"]
    assert seen["practice"] is True and seen["pit"] == "forward_only"


def test_ordinary_nodes_are_still_called_with_two_arguments():
    rep = pg.run(_g([_n("s", "src"), _n("p", "pass")], [_e("s", "p")]), _registry())
    assert rep["nodes"]["p"]["status"] == "ok"
