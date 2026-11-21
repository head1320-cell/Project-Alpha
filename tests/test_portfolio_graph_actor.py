"""실행자 전달 (`wants_actor`) — ★순수 엔진 계약★
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md` §5.1 · 대상 `src/engine/portfolio_graph.py`

시행 기록처럼 **누가 했는가**가 있어야 도는 노드가 있다. 엔진은 그 값을 ★선언한 노드에만★ 마지막 인자로 넘긴다 —
주변 상태(스레드 · 컨텍스트 변수)를 쓰지 않으므로 앞 요청의 실행자가 다음 요청에 샐 길이 없다.

## 거는 것 (모두 짝과 함께)
- 선언한 노드는 `run` · `save` 에서 실행자를 받는다 — 짝: 선언하지 않은 노드의 호출 꼴은 그대로다(인자가 하나라도 늘면 `TypeError`).
- 실행자를 주지 않으면 `None` 이다(지어내지 않는다) — 짝: 준 값은 ★그대로★ 온다(엔진은 뜻을 모른다).
- 계보도 받는 노드는 `(inputs, params, lineage, actor)` 순서다.
- 한 번의 실행에 준 실행자는 그 실행에만 쓰인다 — 다음 실행에 남지 않는다.
"""
from __future__ import annotations

import pytest

from src.engine import portfolio_graph as pg
from tests.graph_write_guard import graph_write_guard  # noqa: F401

#: ★계산 중 DB 쓰기 0★ (BL0) — 그래프 시험 모듈은 모두 이 감시를 쓴다.
pytestmark = pytest.mark.usefixtures("graph_write_guard")

SEEN: list[tuple] = []


def _plain(inputs, p):                                   # 인자 둘 — 셋을 받으면 TypeError
    return pg.NodeOutput(values={"out": 1}, view={"value": 1})


def _who(inputs, p, actor):
    SEEN.append(("run", actor))
    return pg.NodeOutput(values={"out": 2}, view={"value": 2, "who": getattr(actor, "name", actor)})


def _who_with_lineage(inputs, p, lineage, actor):
    SEEN.append(("run_lineage", dict(lineage), actor))
    return pg.NodeOutput(values={}, view={"value": 3})


def _save_plain(values, view, params) -> dict:           # 인자 셋 — 넷을 받으면 TypeError
    SEEN.append(("save_plain",))
    return {"saved_id": "p", "text": "저장했습니다"}


def _save_who(values, view, params, actor) -> dict:
    SEEN.append(("save", actor))
    return {"saved_id": "w", "text": "저장했습니다"}


def _registry() -> pg.Registry:
    reg = pg.Registry(port_types=("Num",))
    reg.register(pg.NodeSpec("plain", "보통", inputs=(), outputs=(pg.Port("out", "Num"),), run=_plain,
                             save=_save_plain, save_label="저장"))
    reg.register(pg.NodeSpec("who", "실행자를 받는 노드", inputs=(), outputs=(pg.Port("out", "Num"),), run=_who,
                             save=_save_who, save_label="저장", wants_actor=True))
    reg.register(pg.NodeSpec("both", "계보와 실행자", inputs=(pg.Port("a", "Num"),), outputs=(), run=_who_with_lineage,
                             wants_lineage=True, wants_actor=True))
    return reg


def _graph(*kinds: str, edges: list | None = None) -> dict:
    return {"format": pg.FORMAT, "version": pg.VERSION,
            "nodes": [{"id": k, "type": k, "params": {}} for k in kinds], "edges": edges or []}


def setup_function() -> None:
    SEEN.clear()


def test_a_declaring_node_receives_the_actor_exactly_as_given():
    actor = object()
    report = pg.run(_graph("who"), _registry(), actor=actor)
    assert report["nodes"]["who"]["status"] == "ok"
    assert SEEN == [("run", actor)]                      # 같은 객체 — 엔진은 고치지도 감싸지도 않는다


def test_a_node_that_does_not_declare_keeps_its_two_argument_call():
    report = pg.run(_graph("plain", "who"), _registry(), actor="김")
    assert report["nodes"]["plain"]["status"] == "ok", report["nodes"]["plain"]["reason"]
    assert report["nodes"]["who"]["view"]["who"] == "김"


def test_without_an_actor_the_declaring_node_gets_none_not_a_made_up_one():
    pg.run(_graph("who"), _registry())
    assert SEEN == [("run", None)]


def test_lineage_comes_before_the_actor():
    g = _graph("plain", "both", edges=[{"source": "plain", "source_port": "out", "target": "both", "target_port": "a"}])
    report = pg.run(g, _registry(), actor="김")
    assert report["nodes"]["both"]["status"] == "ok", report["nodes"]["both"]["reason"]
    kind, lineage, actor = SEEN[-1]
    assert kind == "run_lineage" and isinstance(lineage, dict) and actor == "김"


def test_save_hands_the_actor_to_a_declaring_node():
    reg = _registry()
    h = pg.run(_graph("who"), reg, actor="김")["nodes"]["who"]["view_hash"]
    SEEN.clear()
    out = pg.save_node(_graph("who"), "who", h, reg, actor="김")
    assert out["ok"] is True and out["saved_id"] == "w"
    assert SEEN == [("run", "김"), ("save", "김")]        # 다시 계산할 때도 · 저장할 때도 같은 실행자


def test_save_keeps_the_three_argument_call_for_other_nodes():
    reg = _registry()
    h = pg.run(_graph("plain"), reg)["nodes"]["plain"]["view_hash"]
    out = pg.save_node(_graph("plain"), "plain", h, reg, actor="김")
    assert out["ok"] is True, out
    assert SEEN == [("save_plain",)]


def test_the_actor_of_one_run_does_not_linger_into_the_next():
    reg = _registry()
    pg.run(_graph("who"), reg, actor="김")
    pg.run(_graph("who"), reg)
    assert SEEN == [("run", "김"), ("run", None)]


def test_a_view_that_depends_on_the_actor_makes_a_stale_preview_for_someone_else():
    """미리보기를 본 사람과 저장하는 사람이 다르면 해시가 다르다 — 남의 미리보기로 저장되지 않는다."""
    reg = _registry()
    h = pg.run(_graph("who"), reg, actor="김")["nodes"]["who"]["view_hash"]
    out = pg.save_node(_graph("who"), "who", h, reg, actor="이")
    assert out["ok"] is False and out["code"] == "stale"
    assert ("save", "이") not in SEEN
