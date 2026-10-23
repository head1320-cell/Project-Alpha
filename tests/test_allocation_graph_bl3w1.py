"""BL3 W1 · 백테스트 웨이브 — 시작은 버튼, 읽기는 노드 (사용자 결정)
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W1. 조건식 백테스트는 실데이터에서 수 분 걸리고 기존 화면은 백그라운드 워커가
실행 행을 남긴다. 캔버스 규칙 "계산 중 쓰기 0" 을 지키려고 **시작(저장 버튼)과 읽기(노드)를 나눈다.**

## 거는 것
- 설정 노드: 계산은 요청 검증 + 요약뿐(create_run 0) · 조건식은 서버 필드 목록으로 검사(짝: 모르는 필드 거절).
  '백테스트 시작' = 기존 `create_run` 과 같은 경로 한 번(워커 1회) — 설정이 그대로 실린다.
- 불러오기 노드: 끝난 실행 == `run_full`(성과 라벨 포함) · 진행 중 / 실패 / 없음 / 저장소 장애는 **서로 다른 문장**.
- 귀인 노드: 라우트와 같은 본문(`factor_attribution_for_run`) · 운영은 저장된 관측만 넘긴다(수집기 0).
- 비교 노드: 이미 계산된 지표만 나란히 · 조건이 다르면 먼저 경고(짝: 같으면 경고 없음).
- 스크리너 `as_of`: `run-pit` 라우트 함수 그대로(짝: 비우면 지금 경로).
"""
from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.backtest_runs as br  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, client  # noqa: E402,F401


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _g(nodes, edges=()):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": list(nodes), "edges": list(edges)}


@pytest.fixture(scope="module")
def payload() -> dict:
    """실제 `_screen_to_backtest_core` 응답(워커가 저장하는 모양 그대로) — mock 데이터."""
    from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core
    req = ScreenToBacktestRequest(
        custom_tickers=["005930", "000660"], filter_ast={"logic": "AND", "conditions": [], "groups": []},
        strategy_name="Condition", buy_conditions=[{"factor_token": "종가", "function_id": "base", "op": "gte", "rhs": 0}],
        sell_conditions=[], start_date="2021-01-01", end_date="2025-12-31", max_positions=2, max_tickers=2)
    out = _screen_to_backtest_core(req)
    if not (out or {}).get("backtest"):
        pytest.skip("이 환경에서 백테스트를 낼 수 없다")
    return out


def _row(rid, status, **k):
    base = {"run_id": rid, "created_at": 1.0, "started_at": 1.0, "completed_at": None, "requested_by": "user",
            "strategy_name": "캔버스", "status": status, "progress_percent": 0, "current_stage": status,
            "status_message": None, "data_snapshot_id": None, "engine_version": None, "result_version": None,
            "error_code": None, "error_message": None, "correlation_id": None, "is_mock_data": True,
            "is_pit_verified": None, "input_snapshot": None, "parameter_snapshot": None, "result": None}
    return {**base, **k}


@pytest.fixture()
def runs(monkeypatch, payload):
    store: dict[str, dict] = {
        "run_ok": _row("run_ok", "completed", result=payload, progress_percent=100,
                       input_snapshot={"start_date": "2021-01-01", "end_date": "2025-12-31", "commission_rate": 0.0015,
                                       "slippage_rate": 0.0005, "universe": "kospi200", "strategy_name": "Condition"}),
        "run_ok2": _row("run_ok2", "completed", result=copy.deepcopy(payload), progress_percent=100,
                        input_snapshot={"start_date": "2021-01-01", "end_date": "2025-12-31", "commission_rate": 0.0015,
                                        "slippage_rate": 0.0005, "universe": "kospi200", "strategy_name": "Condition"}),
        "run_busy": _row("run_busy", "simulating", progress_percent=45, status_message="시뮬레이션 중"),
        "run_bad": _row("run_bad", "failed", error_code="engine_error", error_message="백테스트 실행 중 오류가 발생했습니다."),
    }
    box = {"store": store, "created": [], "submitted": [], "down": False}

    def get_run(rid, strict=False):
        if box["down"]:
            raise br.BacktestStoreError("db down")
        r = store.get(rid)
        return copy.deepcopy(r) if r else None

    def create_run(name, snap, requested_by="user"):
        box["created"].append((name, snap))
        store["run_new"] = _row("run_new", "queued", input_snapshot=snap)
        return "run_new"
    monkeypatch.setattr(br, "get_run", get_run)
    monkeypatch.setattr(br, "get_status", get_run)
    monkeypatch.setattr(br, "create_run", create_run)
    monkeypatch.setattr("src.api.backtest_run_routes._submit", lambda fn, *a: box["submitted"].append(a))
    return box


# ══ 설정 · 시작 ══════════════════════════════════════════════════════════════

def _setup(**p):
    return _node("s", "backtest_setup", **p)


def test_the_setup_node_builds_a_request_the_route_accepts_and_starts_nothing(runs):
    from src.api.screener_routes import ScreenToBacktestRequest
    r = _run(_g([_setup(strategy_name="Momentum", start_date="2022-01-01", end_date="2024-12-31", max_tickers=5)]))["nodes"]["s"]
    assert r["status"] == "ok", r["reason"]
    cfg = r["view"]["config"]
    req = ScreenToBacktestRequest(**cfg)                                     # ★라우트 모델이 판정한다★
    assert (req.strategy_name, req.start_date, req.end_date, req.max_tickers) == ("Momentum", "2022-01-01", "2024-12-31", 5)
    assert runs["created"] == [] and runs["submitted"] == []                # 계산은 시작하지 않는다


def test_an_unknown_filter_field_is_refused_by_the_server_field_list(runs):
    bad = {"logic": "AND", "conditions": [{"field": "no_such_field_zz", "op": "gt", "value": 1}], "groups": []}
    r = _run(_g([_setup(filter_ast=bad)]))["nodes"]["s"]
    assert r["status"] == "failed" and "조건" in r["reason"]
    good = {"logic": "AND", "conditions": [{"field": "per", "op": "lt", "value": 10}], "groups": []}
    assert _run(_g([_setup(filter_ast=good)]))["nodes"]["s"]["status"] == "ok"     # 짝


def test_an_end_before_the_start_is_refused(runs):
    r = _run(_g([_setup(start_date="2024-01-01", end_date="2023-01-01")]))["nodes"]["s"]
    assert r["status"] == "failed" and "끝" in r["reason"]


def test_starting_creates_one_run_with_the_previewed_config_and_one_worker(client, runs):
    g = _g([_setup(strategy_name="Momentum")])
    rep = _run(g)
    out = client.post("/api/v1/allocation/graph/save",
                      json={"graph": g, "node_id": "s", "preview_hash": rep["nodes"]["s"]["view_hash"]}).json()
    assert out["ok"] is True and out["saved_id"] == "run_new", out
    assert len(runs["created"]) == 1 and runs["created"][0][1] == rep["nodes"]["s"]["view"]["config"]
    assert len(runs["submitted"]) == 1 and runs["submitted"][0][0] == "run_new"
    assert "결과 불러오기" in out["text"]


def test_starting_without_a_store_says_so(client, runs, monkeypatch):
    monkeypatch.setattr(br, "create_run", lambda *a, **k: None)
    g = _g([_setup()])
    rep = _run(g)
    out = client.post("/api/v1/allocation/graph/save",
                      json={"graph": g, "node_id": "s", "preview_hash": rep["nodes"]["s"]["view_hash"]}).json()
    assert out["ok"] is False and "DB" in out["message"] and runs["submitted"] == []


# ══ 불러오기 ═════════════════════════════════════════════════════════════════

def _load(rid=None):
    return _node("l", "backtest_load", **({"run_id": rid} if rid else {}))


def test_a_finished_run_loads_like_the_route_with_its_performance_label(runs):
    from src.api.backtest_run_routes import run_full
    r = _run(_g([_load("run_ok")]))["nodes"]["l"]
    assert r["status"] == "ok", r["reason"]
    ref = run_full("run_ok")
    bt = ref["result"]["backtest"]
    assert r["view"]["statistics"] == bt["statistics"]
    assert r["view"]["equity"]["values"] == bt["equity_curve"]
    assert r["provenance"]["perf_label"] == ref["perf_label"]
    assert r["lineage"]["practice"] is True                              # 연습용 데이터 실행


@pytest.mark.parametrize("rid,words", [
    ("run_busy", ("아직", "45%")),
    ("run_bad", ("실패", "오류가 발생")),
    ("run_nope", ("찾지 못",)),
    (None, ("골라",)),
])
def test_unfinished_failed_missing_or_unset_runs_each_say_what_happened(runs, rid, words):
    r = _run(_g([_load(rid)]))["nodes"]["l"]
    assert r["status"] == "failed"
    assert all(w in r["reason"] for w in words), r["reason"]


def test_an_unreadable_store_is_not_a_missing_run(runs):
    runs["down"] = True
    r = _run(_g([_load("run_ok")]))["nodes"]["l"]
    assert r["status"] == "failed" and "읽을 수 없" in r["reason"] and "찾지 못" not in r["reason"]


# ══ 귀인 ═════════════════════════════════════════════════════════════════════

def test_attribution_equals_the_route_in_development(runs):
    from src.api.backtest_run_routes import run_factor_attribution
    g = _g([_load("run_ok"), _node("a", "backtest_attribution")], [_edge("l", "run", "a", "run")])
    r = _run(g)["nodes"]["a"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == run_factor_attribution("run_ok")
    assert r["view"]["result"]["available"] is True and r["view"]["result"]["months_from_run"] > 0


def test_attribution_in_production_passes_only_stored_series(runs, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    seen = []
    import src.engine.factor_exposure as fe
    real = fe.resolve_proxies
    monkeypatch.setattr("src.api.allocation_graph_nodes_bl2.macro_series_map",
                        lambda: ({"STORED": object()}, {"pit": "forward_only", "practice": False, "sources": ["x"]}))
    monkeypatch.setattr(fe, "resolve_proxies", lambda sm=None, **k: seen.append(sm) or real({}, **k))
    g = _g([_load("run_ok"), _node("a", "backtest_attribution")], [_edge("l", "run", "a", "run")])
    _run(g)
    assert seen and list(seen[0]) == ["STORED"], "★수집기가 아니라 저장된 관측★"


# ══ 비교 ═════════════════════════════════════════════════════════════════════

def _cmp(a, b):
    return _g([_node("l", "backtest_load", run_id=a), _node("m", "backtest_load", run_id=b), _node("c", "backtest_compare")],
              [_edge("l", "run", "c", "a"), _edge("m", "run", "c", "b")])


def test_comparing_two_runs_puts_existing_numbers_side_by_side(runs):
    r = _run(_cmp("run_ok", "run_ok2"))["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    stats = runs["store"]["run_ok"]["result"]["backtest"]["statistics"]
    row = next(x for x in r["view"]["rows"] if x["key"] == "total_return_pct")
    assert row["a"] == stats["total_return_pct"] and row["diff"] == 0
    assert r["view"]["differences"] == []                                   # 같은 조건 — 경고 없음(짝)


def test_comparing_runs_under_different_conditions_warns_first(runs):
    runs["store"]["run_ok2"]["input_snapshot"]["commission_rate"] = 0.003
    runs["store"]["run_ok2"]["input_snapshot"]["end_date"] = "2024-12-31"
    r = _run(_cmp("run_ok", "run_ok2"))["nodes"]["c"]
    labels = {d["key"] for d in r["view"]["differences"]}
    assert {"commission_rate", "end_date"} <= labels
    assert "같은 조건이 아니에요" in r["explain"]["title"] or any("같은 조건" in t["text"] for t in r["explain"]["trust"])


# ══ 시점 고정 스크리너 ═══════════════════════════════════════════════════════

def test_the_screener_with_as_of_uses_the_pit_route(monkeypatch):
    import src.api.screener_routes as sr
    seen = []
    monkeypatch.setattr(sr, "screener_run_pit", lambda req: seen.append(req) or {
        "as_of_date": req.as_of_date, "universe": req.universe, "total_evaluated": 50, "total_passed": 3,
        "items": [{"stock_code": c, "corp_name": c, "composite_score": 1.0} for c in ("005930", "000660", "035420")]})
    core = []
    monkeypatch.setattr(sr, "_run_advanced_core", lambda *a, **k: core.append(a) or {"items": []})
    r = _run(_g([_node("x", "screener", as_of="2023-06-30", top_n=3)]))["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    assert seen[0].as_of_date == "2023-06-30" and core == []
    assert r["view"]["tickers"] == ["005930", "000660", "035420"] and r["view"]["as_of"] == "2023-06-30"
    # 짝: 비우면 지금 경로(고급 스크리너) — PIT 라우트는 부르지 않는다
    seen.clear()
    _run(_g([_node("x", "screener", top_n=3)]))
    assert seen == [] and len(core) == 1


# ★계산 중 DB 쓰기 0★ (BL0)
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")


def test_every_attribution_factor_has_a_plain_name():
    """화면은 팩터 id(duration·credit…)가 아니라 쉬운 이름을 쓴다 — 새 팩터를 더하면 이름도 더해야 한다."""
    from src.api.allocation_graph_nodes_backtest import FACTOR_KO
    from src.engine.factor_exposure import FACTOR_PROXIES
    assert set(FACTOR_PROXIES) <= set(FACTOR_KO), set(FACTOR_PROXIES) - set(FACTOR_KO)
