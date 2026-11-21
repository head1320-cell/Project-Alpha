"""CF5a · 계산 진행 곁줄 — ★보고서는 그대로, 진행만 곁으로★
==============================================================================
대상 `src/engine/portfolio_graph.py`(`on_node`) · `src/api/graph_progress.py`(통) · `src/api/allocation_graph_routes.py`
(`/run` 머리글 `X-Graph-Progress` · `GET /progress/{rid}`).

캔버스의 실행 줄(ComfyUI 큐)은 노드마다 대기 → 계산 중 → 완료·막힘·실패와 걸린 시간을 보인다. `/run` 은 한 번에 보고서를 돌려주므로
진행은 곁줄로 흘린다. 거는 것:
- 엔진 이벤트 = 보고서 — 순서(`plan` = 보고서 `order`) · 노드마다 start 다음 바로 done · done 의 상태·시간 = 보고서 · 막힘·설정 오류 노드도 알린다.
- 문서가 망가져 계산하지 않으면 노드 이벤트가 없다(지어내지 않는다).
- ★`progress` 를 주어도 보고서는 같다★(시간 빼고) — 짝: 곁줄에 정말 실렸다.
- 통: 늦게 붙어도 쌓인 것부터 · 닫히면 `end` · 시작 안 된 rid 는 기다리다 `timeout` · 열린 통 상한 · 닫힌 지 오래면 비움 · 잘못된 rid 는 422.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import allocation_graph_routes as gr  # noqa: E402
from src.api.graph_progress import ProgressHub  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import chain, market  # noqa: E402,F401


def _events(g, targets=None):
    evs: list[dict] = []
    rep = pg.run(g, gn.REGISTRY, targets=targets, on_node=evs.append)
    return evs, rep


def _drop_times(x):
    if isinstance(x, dict):
        return {k: _drop_times(v) for k, v in x.items() if k != "elapsed_ms"}
    if isinstance(x, list):
        return [_drop_times(v) for v in x]
    return x


# ── 엔진 이벤트 = 보고서 ─────────────────────────────────────────────────────

def test_events_follow_the_report_order(market):
    evs, rep = _events(chain())
    assert rep["order"] and evs[0] == {"type": "plan", "order": rep["order"]}
    seq = [(e["type"], e["id"]) for e in evs[1:]]
    assert seq == [x for nid in rep["order"] for x in (("node_start", nid), ("node_done", nid))]
    for d in (e for e in evs if e["type"] == "node_done"):
        assert d["status"] == rep["nodes"][d["id"]]["status"]
        assert d["elapsed_ms"] == rep["nodes"][d["id"]]["elapsed_ms"]


def test_blocked_and_failed_nodes_are_announced_with_their_status(market):
    evs, rep = _events(chain(tickers=["005930"]))              # 종목 하나 — 수익률이 실패하고 아래가 막힌다
    done = {e["id"]: e["status"] for e in evs if e["type"] == "node_done"}
    assert done == {nid: r["status"] for nid, r in rep["nodes"].items()}
    assert "failed" in done.values() and "blocked" in done.values()


def test_a_broken_document_announces_no_nodes():
    evs, rep = _events({"nodes": "x"})
    assert rep["ok"] is False and evs == []


def test_partial_runs_announce_only_what_they_compute(market):
    evs, rep = _events(chain(), targets=["r"])
    assert evs[0] == {"type": "plan", "order": rep["partial"]["computed"]}
    assert {e["id"] for e in evs if e["type"] == "node_done"} == set(rep["partial"]["computed"]) == {"u", "r"}


def test_the_report_does_not_change_when_progress_is_followed(market):
    evs, with_cb = _events(chain())
    assert evs                                                  # 짝 — 곁줄에 정말 실렸다
    assert _drop_times(with_cb) == _drop_times(pg.run(chain(), gn.REGISTRY))


# ── 라우트 ─────────────────────────────────────────────────────────────────

def test_run_with_progress_returns_the_same_report_and_fills_the_box(market):
    rid = "cf5-test-0001"
    a = gr.graph_run(chain(), None, progress=rid)
    b = gr.graph_run(chain(), None, progress=None)
    assert _drop_times(a) == _drop_times(b)
    got = list(gr._PROGRESS.follow(rid))
    assert got[0]["type"] == "plan" and got[-1] == {"type": "end"}
    assert {e["id"] for e in got if e["type"] == "node_done"} == set(a["nodes"])


def test_the_progress_route_streams_server_sent_events(market):
    rid = "cf5-test-0002"
    gr.graph_run(chain(), None, progress=rid)
    from main_api import app
    with TestClient(app) as c, c.stream("GET", f"/api/v1/allocation/graph/progress/{rid}") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    evs = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
    assert evs[0]["type"] == "plan" and evs[-1] == {"type": "end"}


@pytest.mark.parametrize("rid", ["bad rid", "x" * 65, "a/b", "short1"])   # short1 = 8자 미만
def test_a_malformed_progress_id_is_refused(rid):
    from main_api import app
    with TestClient(app) as c:
        assert c.get(f"/api/v1/allocation/graph/progress/{rid}").status_code in (404, 422)
        assert c.post("/api/v1/allocation/graph/run", headers={"X-Graph-Progress": rid}, json={"nodes": [], "edges": []}).status_code == 422


# ── 통 ────────────────────────────────────────────────────────────────────

def test_a_late_follower_gets_everything_then_end():
    h = ProgressHub()
    h.emit("run-aaaa1111", {"type": "plan", "order": ["a"]})
    h.emit("run-aaaa1111", {"type": "node_start", "id": "a"})
    h.close("run-aaaa1111")
    assert list(h.follow("run-aaaa1111")) == [{"type": "plan", "order": ["a"]}, {"type": "node_start", "id": "a"}, {"type": "end"}]


def test_a_live_follower_receives_events_as_they_come():
    h = ProgressHub()
    got: list[dict] = []
    t = threading.Thread(target=lambda: got.extend(h.follow("run-live0001")))
    t.start()
    time.sleep(0.05)
    h.emit("run-live0001", {"type": "node_start", "id": "a"})
    time.sleep(0.05)
    h.emit("run-live0001", {"type": "node_done", "id": "a", "status": "ok", "elapsed_ms": 1})
    h.close("run-live0001")
    t.join(2)
    assert not t.is_alive()
    assert [e["type"] for e in got] == ["node_start", "node_done", "end"]


def test_a_run_that_never_starts_times_out():
    h = ProgressHub(wait_s=0.05)
    assert list(h.follow("never-started-1")) == [{"type": "timeout"}]


def test_open_boxes_are_capped_oldest_closed_first():
    h = ProgressHub(max_open=2, wait_s=0.05)
    for rid in ("cap-000001", "cap-000002", "cap-000003"):
        h.emit(rid, {"type": "plan", "order": []})
        h.close(rid)
    assert list(h.follow("cap-000001")) == [{"type": "timeout"}]          # 가장 오래 닫힌 것을 비웠다
    assert list(h.follow("cap-000003"))[-1] == {"type": "end"}             # 짝 — 새것은 남았다


def test_closed_boxes_expire():
    now = [0.0]
    h = ProgressHub(keep_s=10, wait_s=0.0, clock=lambda: now[0])
    h.emit("exp-000001", {"type": "plan", "order": []})
    h.close("exp-000001")
    now[0] = 5.0
    assert list(h.follow("exp-000001"))[-1] == {"type": "end"}             # 짝 — 아직 남아 있다
    now[0] = 11.0
    assert list(h.follow("exp-000001")) == [{"type": "timeout"}]
