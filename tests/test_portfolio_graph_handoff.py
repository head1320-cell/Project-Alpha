"""CF3 · 엔진의 전달 점검 고리 — ★선마다 건너간 것(facts)과 빠지거나 바뀐 것(issues)★
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §CF3. 장난감 노드로 **엔진만** 건다.

- 출력 포트 타입별 `facts(value)` · 받는 쪽 `intake(handoff)` — (종류, 입력 포트) 덮어쓰기가 타입 기본보다 먼저.
- `run()` 보고서에 `edges[edge_id] = {source, target, facts, facts_reason, checks, issues, issues_reason}`.
  받아들여진 선만 · 보내는 노드가 ok 일 때만 · 부분 계산이면 계산한 받는 쪽만.
- ★미상 ≠ 깨끗함★ — 규칙이 없거나 받는 노드가 계산되지 않았으면 `issues: None` + 사유. `[]` 는 점검했고 찾지 못함뿐.
- 예외·모양 위반은 `None` + 사유(지어내지 않는다) · 저장(`save_node`)은 고리를 부르지 않는다.
"""
from __future__ import annotations

import pytest

from src.engine import portfolio_graph as pg
from tests.test_portfolio_graph_engine import _CHAIN, _e, _g, _n, _registry


def _facts(v):
    return [{"key": "value", "label": "값", "text": str(v), "value": v}]


def _clean(h):
    return {"checks": ["값이 정수인지"], "issues": []}


def _reg(**over):
    reg = _registry()
    reg.set_port_facts("Num", over.get("facts", _facts))
    if over.get("intake", True):
        reg.set_port_intake("Num", over.get("intake_fn", _clean))
    return reg


def _edges(rep):
    return rep["edges"]


def test_every_accepted_edge_from_an_ok_source_has_a_record():
    rep = pg.run(_CHAIN, _reg())
    assert set(_edges(rep)) == {"c1.out->s.a", "c2.out->s.b", "s.out->t.x"}
    r = _edges(rep)["c1.out->s.a"]
    assert r["source"] == "c1" and r["target"] == "s"
    assert r["facts"] == [{"key": "value", "label": "값", "text": "2", "value": 2}]
    assert r["issues"] == [] and r["checks"] == ["값이 정수인지"]


def test_facts_are_computed_once_per_output_port():
    calls = []

    def spy(v):
        calls.append(v)
        return _facts(v)

    g = _g([_n("c", "const", value=4), _n("a", "add"), _n("b", "add")],
           [_e("c", "out", "a", "a"), _e("c", "out", "b", "a")])
    rep = pg.run(g, _reg(facts=spy))
    assert len(_edges(rep)) == 2 and calls == [4]


def test_no_rule_is_unknown_not_clean():
    """★미상 ≠ 깨끗함★ — 점검 규칙이 없으면 `issues` 는 None + 사유이지 [] 가 아니다."""
    rep = pg.run(_CHAIN, _reg(intake=False))
    r = _edges(rep)["c1.out->s.a"]
    assert r["issues"] is None and "점검 규칙이 없어요" in r["issues_reason"]
    assert r["facts"]                                      # 사실은 여전히 있다


def test_a_failed_target_is_not_checked():
    g = _g([_n("c", "const", value=1), _n("x", "boom")], [_e("c", "out", "x", "a")])
    r = _edges(pg.run(g, _reg()))["c.out->x.a"]
    assert r["issues"] is None and "계산되지 않아" in r["issues_reason"]
    assert r["facts"]


def test_no_record_when_the_source_did_not_compute():
    g = _g([_n("c", "const", value=1), _n("x", "boom"), _n("t", "label")],
           [_e("c", "out", "x", "a"), _e("x", "out", "t", "x")])
    assert "x.out->t.x" not in _edges(pg.run(g, _reg()))


def test_override_beats_the_type_default():
    reg = _reg()
    reg.set_intake("label", "x", lambda h: {"checks": ["글자로 바꿈"],
                                            "issues": [{"level": "changed", "code": "to_text",
                                                        "text": f"{h.target_kind} 가 수를 글자로 바꿨어요."}]})
    rep = pg.run(_CHAIN, reg)
    assert _edges(rep)["s.out->t.x"]["issues"] == [
        {"level": "changed", "code": "to_text", "text": "label 가 수를 글자로 바꿨어요."}]
    assert _edges(rep)["c1.out->s.a"]["issues"] == []          # 다른 선은 기본 규칙


def test_the_handoff_carries_what_a_rule_needs():
    seen = {}

    def look(h):
        seen.update(edge=h.edge_id, src=(h.source, h.source_kind, h.source_port), dst=(h.target, h.target_kind, h.target_port),
                    typ=h.port_type, value=h.value, sview=h.source_view, view=h.view, inputs=dict(h.inputs))
        return {"checks": [], "issues": []}

    reg = _reg()
    reg.set_intake("add", "b", look)
    pg.run(_CHAIN, reg)
    assert seen == {"edge": "c2.out->s.b", "src": ("c2", "const", "out"), "dst": ("s", "add", "b"), "typ": "Num",
                    "value": 3, "sview": {"value": 3}, "view": {"value": 5}, "inputs": {"a": 2, "b": 3}}


@pytest.mark.parametrize("bad", [
    {"checks": [], "issues": [{"level": "terrible", "code": "x", "text": "t"}]},          # 모르는 단계
    {"checks": [], "issues": [{"level": "lost", "code": "x", "text": "가" * 241}]},       # 너무 긴 글
    {"checks": [], "issues": [{"level": "lost", "code": "x"}]},                           # 글 없음
    {"issues": []},                                                                       # checks 없음
    [],                                                                                   # 모양이 틀림
])
def test_badly_shaped_issues_are_withheld(bad):
    rep = pg.run(_CHAIN, _reg(intake_fn=lambda h: bad))
    r = _edges(rep)["c1.out->s.a"]
    assert r["issues"] is None and r["issues_reason"]


@pytest.mark.parametrize("bad", [
    [{"key": "k", "label": "l", "text": "t", "value": float("nan")}],                     # 유한하지 않음
    [{"key": "k", "label": "l"}],                                                         # 글 없음
    [{"key": f"k{i}", "label": "l", "text": "t"} for i in range(13)],                     # 너무 많음
])
def test_badly_shaped_facts_are_withheld(bad):
    r = _edges(pg.run(_CHAIN, _reg(facts=lambda v: bad)))["c1.out->s.a"]
    assert r["facts"] is None and r["facts_reason"]


def test_exceptions_become_reasons_not_crashes():
    def fail(*_):
        raise RuntimeError("규칙 고장")

    rep = pg.run(_CHAIN, _reg(facts=fail, intake_fn=fail))
    r = _edges(rep)["c1.out->s.a"]
    assert r["facts"] is None and r["issues"] is None
    assert r["facts_reason"] and r["issues_reason"]
    assert rep["nodes"]["s"]["status"] == pg.STATUS_OK        # 점검이 실패해도 계산은 그대로


def test_partial_runs_only_record_computed_targets():
    rep = pg.run(_CHAIN, _reg(), targets=["s"])
    assert set(_edges(rep)) == {"c1.out->s.a", "c2.out->s.b"}


def test_duplicate_edge_ids_get_no_record():
    g = _g([_n("c1", "const", value=1), _n("c2", "const", value=2), _n("s", "add")],
           [_e("c1", "out", "s", "a", id_="same"), _e("c2", "out", "s", "b", id_="same")])
    assert "same" not in _edges(pg.run(g, _reg()))


def test_save_node_does_not_call_the_hooks():
    calls = []

    def spy(v):
        calls.append(v)
        return _facts(v)

    reg = _reg(facts=spy)
    pg._execute(_CHAIN, reg)
    assert calls == []


def test_setters_refuse_unknown_targets():
    reg = _registry()
    with pytest.raises(ValueError):
        reg.set_port_facts("Nope", _facts)
    with pytest.raises(ValueError):
        reg.set_port_intake("Nope", _clean)
    with pytest.raises(ValueError):
        reg.set_intake("nope", "a", _clean)
    with pytest.raises(ValueError):
        reg.set_intake("add", "zz", _clean)


# ★계산 중 DB 쓰기 0★ (BL0) — 그래프 테스트 모듈은 모두 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
