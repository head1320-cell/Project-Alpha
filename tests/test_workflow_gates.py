"""BJ1 · 증거 관문 판정 — ★건너뛴 관문은 통과한 관문이 아니다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-workflow-ux-design.md` §4.1·§4.3 ·
대상 `src/domain/workflow_gates.py`(순수) · `POST /api/v1/allocation/graph/run` 의 `gates`

CLAUDE.md §1 의 관문 순서 8개. 상태: confirmed · assumed · partial · unknown · skipped · failed.

## 거는 것 (짝으로 항상-확인·항상-건너뜀 구현을 배제한다)
- 백테스트가 없으면 비용·처음 보는 기간 = 건너뜀, 있으면 가정·부분(짝).
- mock → 데이터 = 몰라요("연습용"); 등급이 기록돼 있으면 확인(짝).
- 실패·막힘은 확인이 되지 않는다. 경제적 가치·모의/실계좌는 이 그래프에서 **절대 확인되지 않는다**.
- 요약의 확인 개수는 관문 상태와 같다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain import workflow_gates as wg  # noqa: E402

STAGE = {"universe": "data", "returns": "data", "views": "belief", "estimate": "belief",
         "optimizer": "build", "risk": "check", "backtest": "check", "alpha": "signal"}


def _nodes(*types):
    return [{"id": t, "type": t} for t in types]


def _ok(view=None, prov=None):
    return {"status": "ok", "view": view or {}, "provenance": prov or {}, "reason": None}


RET_MOCK = _ok({"coverage": {"as_of_effective": "2026-09-25"}}, {"source": "mock", "data_grade": "E0"})
RET_DB = _ok({"coverage": {"as_of_effective": "2026-09-25"}},
             {"source": "db", "data_grade": None, "data_grade_reason": "행 단위 출처 미기록"})
RET_GRADED = _ok({"coverage": {"as_of_effective": "2026-09-25"}}, {"source": "db", "data_grade": "E4"})
OPT = _ok({"constraints_report": None})
BT = _ok({"config": {"cost_bps": 10.0},
          "lookahead_evidence": {"ok_axes": ["window", "as_of"], "unknown_axes": ["universe", "price"],
                                 "broken_axes": []}},
         {"perf_label": {"data_real": False}})


def _gate(rep, key):
    return next(g for g in rep["gates"] if g["key"] == key)


def test_there_are_eight_gates_in_the_claude_md_order():
    rep = wg.evaluate(_nodes(), {}, STAGE)
    assert [g["key"] for g in rep["gates"]] == \
        ["data", "pit", "signal", "build", "cost", "oos", "economic", "live"]
    assert all(g["state"] == "skipped" and g["reasons"] for g in rep["gates"]), \
        "빈 그래프는 전부 건너뜀이고, 건너뛴 이유를 말한다"


def test_without_a_backtest_cost_and_oos_are_skipped():
    rep = wg.evaluate(_nodes("returns", "optimizer"), {"returns": RET_MOCK, "optimizer": OPT}, STAGE)
    assert _gate(rep, "cost")["state"] == "skipped"
    assert _gate(rep, "oos")["state"] == "skipped"
    assert _gate(rep, "build")["state"] == "confirmed"


def test_with_a_backtest_cost_is_assumed_and_oos_is_partial():
    """★짝★ — 항상-건너뜀 구현을 배제한다."""
    rep = wg.evaluate(_nodes("returns", "optimizer", "backtest"),
                      {"returns": RET_MOCK, "optimizer": OPT, "backtest": BT}, STAGE)
    cost = _gate(rep, "cost")
    assert cost["state"] == "assumed" and "0.1%" in cost["reasons"][0]["text"]
    oos = _gate(rep, "oos")
    assert oos["state"] == "partial"
    states = [r["state"] for r in oos["reasons"]]
    assert states.count("confirmed") == 2 and states.count("unknown") >= 2


def test_practice_data_is_unknown_and_recorded_grade_is_confirmed():
    mock = wg.evaluate(_nodes("returns"), {"returns": RET_MOCK}, STAGE)
    assert _gate(mock, "data")["state"] == "unknown"
    assert "연습용" in _gate(mock, "data")["reasons"][0]["text"]
    db = wg.evaluate(_nodes("returns"), {"returns": RET_DB}, STAGE)
    assert _gate(db, "data")["state"] == "unknown" and "몰라요" in _gate(db, "data")["reasons"][0]["text"]
    graded = wg.evaluate(_nodes("returns"), {"returns": RET_GRADED}, STAGE)
    assert _gate(graded, "data")["state"] == "confirmed"          # ★짝★


def test_pit_records_the_cut_date_but_not_publication_time():
    g = _gate(wg.evaluate(_nodes("returns"), {"returns": RET_DB}, STAGE), "pit")
    assert g["state"] == "partial"
    assert {r["state"] for r in g["reasons"]} == {"confirmed", "unknown"}


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_failure_or_block_is_never_confirmed(status):
    bad = {"status": status, "view": None, "provenance": {}, "reason": "x"}
    rep = wg.evaluate(_nodes("returns", "optimizer"), {"returns": bad, "optimizer": bad}, STAGE)
    for key in ("data", "build"):
        assert _gate(rep, key)["state"] in ({"failed"} if status == "failed" else {"unknown"}), key


def test_an_infeasible_constraint_fails_the_build_gate():
    opt = _ok({"constraints_report": {"status": "infeasible", "reason": "상한 합이 100% 미만"}})
    assert _gate(wg.evaluate(_nodes("optimizer"), {"optimizer": opt}, STAGE), "build")["state"] == "failed"


def test_a_signal_node_is_not_a_confirmed_signal():
    rep = wg.evaluate(_nodes("alpha"), {"alpha": _ok()}, STAGE)
    assert _gate(rep, "signal")["state"] == "unknown"


def test_economic_value_and_live_are_never_confirmed_here():
    rep = wg.evaluate(_nodes("returns", "optimizer", "backtest"),
                      {"returns": RET_GRADED, "optimizer": OPT, "backtest": BT}, STAGE)
    for key in ("economic", "live"):
        assert _gate(rep, key)["state"] == "skipped" and _gate(rep, key)["reasons"]


def test_the_summary_counts_what_the_gates_say():
    rep = wg.evaluate(_nodes("returns", "optimizer", "backtest"),
                      {"returns": RET_MOCK, "optimizer": OPT, "backtest": BT}, STAGE)
    n = sum(g["state"] == "confirmed" for g in rep["gates"])
    assert rep["summary"]["confirmed"] == n == 1
    assert rep["summary"]["text"] == "8개 관문 중 1개만 확인했어요."


def test_the_pure_module_reads_nothing_outside():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path("src/domain/workflow_gates.py").read_text("utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in mods if m and (m.startswith("src.") or m in {"os", "sqlalchemy"})}, mods


# ── 문에 실린다 ────────────────────────────────────────────────────────────

def test_the_run_route_carries_gates(monkeypatch):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    from tests.test_allocation_graph import chain
    from tests.test_allocation_routes import T3, _fake_returns_df, _patch_caps, _patch_returns
    _patch_returns(monkeypatch, _fake_returns_df(T3, n=1100))
    _patch_caps(monkeypatch)
    body = TestClient(create_app()).post("/api/v1/allocation/graph/run",
                                         json=chain(lookback=1008, backtest={})).json()
    assert [g["key"] for g in body["gates"]["gates"]][:2] == ["data", "pit"]
    assert next(g for g in body["gates"]["gates"] if g["key"] == "cost")["state"] == "assumed"


def test_any_build_stage_node_counts_for_the_build_gate():
    """BK W2 — 비중은 옵티마이저만 만들지 않는다(점수→비중·중립화·묶음 합치기). 짝: 신호만 있으면 건너뜀."""
    stage = {**STAGE, "scores_to_weights": "build"}
    rep = wg.evaluate(_nodes("alpha", "scores_to_weights"), {"alpha": _ok(), "scores_to_weights": _ok()}, stage)
    assert _gate(rep, "build")["state"] == "confirmed"
    only_signal = wg.evaluate(_nodes("alpha"), {"alpha": _ok()}, stage)
    assert _gate(only_signal, "build")["state"] == "skipped"
