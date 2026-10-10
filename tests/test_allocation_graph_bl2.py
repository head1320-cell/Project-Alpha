"""BL2a · 마법사 고유 기능 이전 — 저장 버튼 둘 (연구 기록 · 타이밍 규칙)
==============================================================================
마법사에만 있던 쓰기 두 가지를 노드의 '저장하기'(`/graph/save`, BK0 계약)로 옮긴다:
- 비중 계산 → **연구 기록 남기기** — 마법사와 같은 경로(`run_analyze(record_run=True)`). 기록된 비중 == 노드 미리보기.
  회사 뷰를 쓴 비중이면 기록 요청에도 `use_company_views` 를 싣는다(짝: 안 쓰면 싣지 않는다).
- 타이밍 신호 → **규칙 저장** — `/timing-rules` 와 같은 문(정규화·버전). 저장된 조합 방식·k 가 노드와 같다.
실행 계획 저장은 노드가 아니라 실행실 서랍이 **승인된 실행 목표에서만** 만든다(`_resolve_target` 의 R0 차단선).

## 거는 것
- 계산은 여전히 쓰지 않는다(그래프 쓰기 감시) · 저장은 미리보기 해시가 같을 때 한 번.
- 저장 가능한 노드 집합 == {실행 목표, 결정 기록, 비중 계산, 타이밍 신호} — 주문 목록은 저장하지 않는다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import VIEW, _edge, _node, chain, client, market  # noqa: E402,F401
from tests.test_allocation_graph_w5 import _co_graph, co  # noqa: E402,F401


@pytest.fixture()
def recorded(monkeypatch):
    calls = []

    def fake_record(kind, inputs, outputs, snapshot=None, name=None, **k):
        calls.append({"kind": kind, "inputs": inputs, "outputs": outputs, "snapshot": snapshot, "name": name})
        return "rr_canvas_1"
    monkeypatch.setattr("src.data.research_runs.record_run", fake_record)
    return calls


def _save(client, g, nid):
    rep = pg.run(g, gn.REGISTRY)
    r = client.post("/api/v1/allocation/graph/save",
                    json={"graph": g, "node_id": nid, "preview_hash": rep["nodes"][nid]["view_hash"]})
    return rep, r.json()


@pytest.mark.parametrize("model,views", [("bl", [VIEW]), ("hrp", None)])
def test_recording_the_optimizer_records_what_was_previewed(client, market, recorded, model, views):
    g = chain(model=model, views=views, risk=False)
    rep, out = _save(client, g, "o")
    assert out["ok"] is True and out["saved_id"] == "rr_canvas_1", out
    assert len(recorded) == 1
    rec = recorded[0]
    from src.data.research_runs import KIND_ANALYZE
    assert rec["kind"] == KIND_ANALYZE and rec["outputs"]["weights"]["optimized"] == rep["nodes"]["o"]["view"]["weights"]
    assert rec["inputs"]["model"] == model and rec["inputs"]["use_company_views"] is False
    assert "연구 기록" in out["text"]


def test_a_company_view_optimizer_is_recorded_with_company_views(client, market, recorded, co):
    g = _co_graph()
    rep, out = _save(client, g, "o")
    assert out["ok"] is True, out
    assert recorded[0]["inputs"]["use_company_views"] is True
    assert recorded[0]["outputs"]["weights"]["optimized"] == rep["nodes"]["o"]["view"]["weights"]


def test_a_record_that_would_not_match_the_preview_is_refused(client, market, recorded, monkeypatch):
    """★기록은 /analyze 가 남긴다 — 그 경로가 캔버스와 다른 비중을 내면 기록하지 않는다★
    회사 뷰 노드의 '수렴 기간' 은 /analyze 에 없는 칸이다. 기록 경로는 기본값으로 다시 계산하므로 비중이 갈라진다 —
    그 기록은 재현하면 미리보기와 다른 것이 나오는 거짓 기록이다."""
    import src.engine.company_views as cv

    def fake_views(codes, prices, *, as_of=None, convergence_years=None, **k):
        mag = 4.0 if convergence_years is None else 15.0            # 수렴 기간이 뷰 크기를 바꾼다
        return [{"assets": [codes[0]], "direction": 1, "magnitude_pct": mag, "confidence": 60.0,
                 "source": cv.SOURCE, "label": "x", "is_mock": True, "confidence_saturated": False,
                 "research_usage": cv._usage()}], {}
    monkeypatch.setattr(cv, "company_views", fake_views)
    monkeypatch.setattr(cv, "prices_for", lambda codes: ({c: 50_000.0 for c in codes}, {c: "caller" for c in codes}))
    g = _co_graph()
    next(n for n in g["nodes"] if n["id"] == "c")["params"] = {"convergence_years": 3}
    rep, out = _save(client, g, "o")
    assert rep["nodes"]["o"]["status"] == "ok"
    assert out["ok"] is False and out["code"] == "save_failed" and "미리보기" in out["message"], out
    assert recorded == []                                             # 한 줄도 남기지 않았다
    # 짝: 수렴 기간을 비우면(= /analyze 와 같은 계산) 기록한다
    next(n for n in g["nodes"] if n["id"] == "c")["params"] = {}
    _, out2 = _save(client, g, "o")
    assert out2["ok"] is True and len(recorded) == 1, out2


def test_saving_timing_rules_stores_the_node_rules_once(client, monkeypatch):
    saved = []

    def fake_save(name, market, rules, gate=None, notes=None, set_id=None):
        saved.append({"name": name, "market": market, "rules": rules, "gate": gate})
        return "trs_canvas_1"
    monkeypatch.setattr("src.data.timing_rules.save_rule_set", fake_save)
    monkeypatch.setattr("src.data.timing_rules.get_rule_set", lambda sid: {"version": 3})
    g = {"format": pg.FORMAT, "version": pg.VERSION, "edges": [],
         "nodes": [_node("t", "timing_signal", combination="k_of_n", k=2, market="us",
                         rules=[{"factor_id": "abs_mom"}, {"factor_id": "ma_month"}, {"factor_id": "drawdown"}])]}
    rep, out = _save(client, g, "t")
    if rep["nodes"]["t"]["status"] != "ok":
        pytest.skip(f"타이밍 노드가 이 환경에서 계산되지 않음: {rep['nodes']['t']['reason']}")
    assert out["ok"] is True and out["saved_id"] == "trs_canvas_1", out
    assert len(saved) == 1
    s = saved[0]
    assert s["market"] == "us" and s["gate"] == {"combination": "k_of_n", "k": 2}
    assert [r["factor_id"] for r in s["rules"]] == ["abs_mom", "ma_month", "drawdown"]
    assert "v3" in out["text"]


def test_an_unwritable_store_is_a_failure_not_a_saved_record(client, market, monkeypatch):
    """★저장소를 못 쓰면 저장했다고 말하지 않는다★ `record_run` 이 None(DB 미가용)이면 저장 실패로 답한다."""
    monkeypatch.setattr("src.data.research_runs.record_run", lambda *a, **k: None)
    _, out = _save(client, chain(model="hrp", risk=False), "o")
    assert out["ok"] is False and out["code"] == "save_failed" and "DB" in out["message"], out


def test_an_unwritable_rule_store_is_a_failure(client, monkeypatch):
    monkeypatch.setattr("src.data.timing_rules.save_rule_set", lambda *a, **k: None)
    g = {"format": pg.FORMAT, "version": pg.VERSION, "edges": [], "nodes": [_node("t", "timing_signal")]}
    rep, out = _save(client, g, "t")
    if rep["nodes"]["t"]["status"] != "ok":
        pytest.skip(f"타이밍 노드가 이 환경에서 계산되지 않음: {rep['nodes']['t']['reason']}")
    assert out["ok"] is False and out["code"] == "save_failed" and "DB" in out["message"], out


def test_the_savable_set_is_exactly_the_record_nodes():
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    assert {t for t, c in cat.items() if c["savable"]} == {"target_version", "decision_journal", "optimizer", "timing_signal",
                                                                "alpha_validate", "backtest_setup", "rebalance_decision"}
    assert cat["order_preview"]["savable"] is False                    # 실행 계획은 승인된 목표에서만


def test_every_save_button_says_what_it_does():
    """버튼은 누르면 일어나는 일을 말한다 — 저장하는 노드는 제 이름표가 있고(짝) 저장하지 않는 노드는 없다."""
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    labels = {t: c["save_label"] for t, c in cat.items() if c["savable"]}
    assert labels == {"target_version": "실행 목표로 저장", "decision_journal": "판단 기록 저장",
                      "optimizer": "연구 기록 남기기", "timing_signal": "타이밍 규칙 저장",
                      "alpha_validate": "검증 기록 남기기", "backtest_setup": "백테스트 시작",
                      "rebalance_decision": "결정 기록 남기기"}
    assert all(c["save_label"] is None for c in cat.values() if not c["savable"])


# ★계산 중 DB 쓰기 0★ (BL0)
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
