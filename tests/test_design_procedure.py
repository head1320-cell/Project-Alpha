"""BT1 · 설계 절차 — ★그래프가 스스로 절차를 말한다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-30-bt-canvas-procedure-node-link-design.md` §1 ·
대상 `src/domain/design_procedure.py`(순수) · `POST /api/v1/allocation/graph/validate` 의 `procedure`

## 거는 것 (짝으로 항상-제안·항상-침묵 구현을 배제한다)
- 단계 상태: 빈 그래프는 모두 비어 있음, 핵심 사슬은 데이터·생각·비중이 채움, 입력이 빠진 노드는 막힘.
- 다음 한 걸음 규칙 1~6 은 **순서대로** 이긴다. 각 규칙은 조건이 없으면 나오지 않는다.
- 붙일 노드는 이어질 선(`attach`)을 함께 낸다 — 붙이기만 하고 잇지 않는 제안은 없다.
- 문장은 "잴 수 있게"까지만 — 통과·좋아짐을 약속하지 않는다. 금지 표현이 없다.
- 설정값은 추천하지 않는다(`attach`·`kind` 뿐, 파라미터 없음).
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_routes as routes  # noqa: E402
from src.api.allocation_graph_nodes import PORT_PLAIN, STAGES  # noqa: E402
from src.domain import design_procedure as proc  # noqa: E402

KINDS = routes._kinds()
F = {"format": "project-alpha.portfolio-graph", "version": 1}
BANNED = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략", "통과해요", "좋아져요")


def _n(i, t, **p):
    return {"id": i, "type": t, "params": p}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


def _proc(nodes, edges):
    return proc.evaluate(nodes, edges, KINDS, STAGES, PORT_PLAIN)


UNI = _n("u", "universe", tickers=["005930", "000660"])
CORE = [UNI, _n("r", "returns"), _n("es", "estimate"), _n("o", "optimizer")]
CORE_E = [_e("u", "universe", "r", "universe"), _e("r", "returns", "es", "returns"),
          _e("r", "returns", "o", "returns"), _e("es", "belief", "o", "belief")]


def _step(p, key):
    return next(s for s in p["steps"] if s["key"] == key)


# ── 단계 ─────────────────────────────────────────────────────────────────────

def test_the_six_steps_follow_the_palette_stages_with_their_need():
    p = _proc([], [])
    assert [s["key"] for s in p["steps"]] == [s["key"] for s in STAGES]
    assert {s["key"]: s["need"] for s in p["steps"]} == {
        "data": "required", "signal": "optional", "belief": "optional", "build": "required",
        "check": "recommended", "act": "optional"}
    assert all(s["state"] == "empty" and s["node_ids"] == [] for s in p["steps"])


def test_the_core_chain_fills_data_belief_build_and_leaves_check_empty():
    p = _proc(CORE, CORE_E)
    assert {s["key"]: s["state"] for s in p["steps"]} == {
        "data": "filled", "signal": "empty", "belief": "filled", "build": "filled",
        "check": "empty", "act": "empty"}
    assert _step(p, "build")["node_ids"] == ["o"] and "‘비중 계산’" in _step(p, "build")["text"]


def test_a_node_missing_a_required_input_blocks_its_step_and_the_pair_is_filled():
    p = _proc(CORE, CORE_E[:-1])                     # 추정 → 비중 계산 선이 없다
    assert _step(p, "build")["state"] == "blocked"
    assert _step(_proc(CORE, CORE_E), "build")["state"] == "filled"     # ★짝★


def test_a_step_with_nodes_but_unmeasurable_gates_is_partial_not_filled():
    # 종목만 있으면 데이터 단계에 노드는 있지만 데이터·시점 관문을 잴 수 없다 — "채움"이라 부르지 않는다.
    st = _step(_proc([UNI], []), "data")
    assert st["state"] == "partial" and st["node_ids"] == ["u"]
    assert st["text"].startswith("‘종목 고르기’ — ") and "수익률 불러오기" in st["text"]
    both = _proc(CORE[:2], CORE_E[:1])
    assert _step(both, "data")["state"] == "filled"                                   # ★짝★ 수익률이 있으면 채움
    # 확인하기에 흔들림 나눠 보기만 있으면 거래비용·처음 보는 기간은 아직이다
    risk_only = _proc(CORE + [_n("k", "risk")], CORE_E + [_e("o", "weights", "k", "weights")])
    assert _step(risk_only, "check")["state"] == "partial"


def test_each_step_says_which_gates_it_feeds():
    p = _proc([], [])
    assert _step(p, "data")["feeds_gates"] == ["data", "pit"]
    assert _step(p, "check")["feeds_gates"] == ["cost", "oos"]
    assert _step(p, "act")["feeds_gates"] == []      # 실행은 어떤 관문도 확인하지 않는다


# ── 다음 한 걸음 ─────────────────────────────────────────────────────────────

def test_rule1_a_missing_input_is_connected_from_an_existing_producer_first():
    nxt = _proc(CORE, CORE_E[:-1])["next"]
    assert nxt["action"] == "connect" and nxt["kind"] is None
    assert nxt["attach"] == [{"source": "es", "source_port": "belief", "target": "o", "target_port": "belief"}]


def test_rule1_without_a_producer_suggests_adding_one_wired_to_the_gap():
    nodes = [UNI, _n("r", "returns"), _n("o", "optimizer")]
    edges = [_e("u", "universe", "r", "universe"), _e("r", "returns", "o", "returns")]
    nxt = _proc(nodes, edges)["next"]
    assert nxt["action"] == "add" and nxt["kind"] == "estimate"
    assert nxt["attach"] == [{"source": proc.NEW, "source_port": "belief", "target": "o", "target_port": "belief"}]


def test_rule1_never_suggests_a_downstream_node_as_the_producer():
    # 중립화의 입력(비중)이 비었고, 그 하류의 노출 조절이 비중을 낸다 — 거기서 끌어오면 고리가 생긴다.
    nodes = [_n("nz", "neutralize"), _n("x", "exposure_overlay")]
    edges = [_e("nz", "weights", "x", "weights")]
    nxt = _proc(nodes, edges)["next"]
    assert nxt["attach"][0]["target"] == "nz"
    assert nxt["attach"][0]["source"] != "x" and nxt["action"] == "add"
    # ★짝★ 하류가 아닌 곳에 비중이 있으면 그것을 잇자고 한다.
    nodes2 = nodes + [_n("o", "optimizer")]
    nxt2 = _proc(nodes2, edges)["next"]
    assert nxt2["action"] == "connect" and nxt2["attach"][0]["source"] == "o"


def test_rule2_an_empty_canvas_starts_with_the_universe_then_returns():
    first = _proc([], [])["next"]
    assert first["kind"] == "universe" and first["attach"] == [] and first["unlocks"] == []
    second = _proc([UNI], [])["next"]
    assert second["kind"] == "returns" and second["unlocks"] == ["data", "pit"]
    assert second["attach"] == [{"source": "u", "source_port": "universe", "target": proc.NEW,
                                 "target_port": "universe"}]


def test_rule3_without_a_build_step_suggests_the_optimizer_wired_to_returns():
    nodes, edges = CORE[:2], CORE_E[:1]
    nxt = _proc(nodes, edges)["next"]
    assert nxt["kind"] == "optimizer" and nxt["unlocks"] == ["build"]
    assert nxt["attach"][0]["source"] == "r"


def test_rule4_after_the_optimizer_suggests_the_backtest_that_unlocks_cost_and_oos():
    nxt = _proc(CORE, CORE_E)["next"]
    assert nxt["kind"] == "backtest" and nxt["unlocks"] == ["cost", "oos"]
    assert {(a["source"], a["target_port"]) for a in nxt["attach"]} == {("o", "weights"), ("r", "returns")}
    assert "잴 수 있게" in nxt["text"]


def test_rule4_is_silent_when_there_is_no_optimizer_to_replay():
    # 점수→비중만 있으면 과거로 돌려 보기는 규칙이 없어 실패한다 — 그것을 제안하지 않는다.
    nodes = [UNI, _n("f", "factor_scores"), _n("s", "scores_to_weights"), _n("r", "returns")]
    edges = [_e("u", "universe", "f", "universe"), _e("f", "scores", "s", "scores"),
             _e("u", "universe", "r", "universe"), _e("r", "returns", "s", "returns")]
    nxt = _proc(nodes, edges)["next"]
    assert nxt is None or nxt["kind"] != "backtest"


def test_rule5_suggests_a_check_only_from_weights_that_can_carry_the_covariance():
    nodes = [UNI, _n("f", "factor_scores"), _n("s", "scores_to_weights"), _n("r", "returns")]
    edges = [_e("u", "universe", "f", "universe"), _e("f", "scores", "s", "scores"),
             _e("u", "universe", "r", "universe")]
    assert _proc(nodes, edges)["next"] is None                 # 수익률이 없으면 흔들림 나눠 보기가 실패한다
    nxt = _proc(nodes, edges + [_e("r", "returns", "s", "returns")])["next"]     # ★짝★
    assert nxt["kind"] == "risk" and nxt["attach"][0]["source"] == "s"


def test_rule6_a_full_procedure_has_no_next_and_says_so():
    nodes = CORE + [_n("b", "backtest")]
    edges = CORE_E + [_e("o", "weights", "b", "weights"), _e("r", "returns", "b", "returns")]
    p = _proc(nodes, edges)
    assert p["next"] is None and p["done_text"] == "절차를 다 채웠어요 — 계산해 보세요."
    assert _proc(CORE, CORE_E)["done_text"] is None                               # ★짝★


def test_by_gate_offers_the_step_that_makes_each_gate_measurable():
    bg = _proc(CORE, CORE_E)["by_gate"]
    assert bg["cost"]["kind"] == bg["oos"]["kind"] == "backtest"
    assert bg["economic"] is None and bg["live"] is None      # 이 그래프에서 재는 노드가 없다
    assert bg["build"] is None                                 # 이미 있다


def test_sentences_promise_measurement_not_passing():
    seen = []
    for nodes, edges in (([], []), ([UNI], []), (CORE[:2], CORE_E[:1]), (CORE, CORE_E), (CORE, CORE_E[:-1])):
        p = _proc(nodes, edges)
        seen += [s["text"] for s in p["steps"]] + ([p["next"]["text"]] if p["next"] else [])
        seen += [v["text"] for v in p["by_gate"].values() if v]
    assert seen and not [t for t in seen for w in BANNED if w in t]


def test_suggestions_never_carry_parameter_values():
    for nodes, edges in (([], []), (CORE, CORE_E)):
        nxt = _proc(nodes, edges)["next"]
        assert set(nxt) == {"action", "kind", "label", "text", "attach", "unlocks"}


def test_korean_particles_follow_the_final_consonant():
    assert proc._obj("비중 계산") == "‘비중 계산’을" and proc._obj("흔들림 나눠 보기") == "‘흔들림 나눠 보기’를"
    assert proc._subj("종목") == "‘종목’이" and proc._subj("과거로 돌려 보기") == "‘과거로 돌려 보기’가"


def test_the_pure_module_reads_nothing_outside():
    tree = ast.parse(pathlib.Path("src/domain/design_procedure.py").read_text("utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in mods if m and (m.startswith("src.") or m in {"os", "sqlalchemy", "requests"})}, mods


# ── 문 ───────────────────────────────────────────────────────────────────────

def test_validate_carries_the_procedure_even_for_an_empty_graph():
    rep = routes.graph_validate({**F, "nodes": [], "edges": []})
    assert rep["ok"] is True and rep["procedure"]["next"]["kind"] == "universe"


def test_validate_has_no_procedure_for_a_broken_document():
    rep = routes.graph_validate({"format": "x"})
    assert rep["ok"] is False and rep["procedure"] is None


@pytest.mark.parametrize("bad", [None, [], "x"])
def test_validate_survives_non_object_documents(bad):
    assert routes.graph_validate(bad)["procedure"] is None
