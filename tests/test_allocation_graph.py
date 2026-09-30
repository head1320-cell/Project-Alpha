"""BI2 · AAS 그래프의 핵심 사슬 노드 — ★`/analyze`·`/backtest` 와 같은 수를 낸다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` §4.3·§5 ·
대상 `src/api/allocation_graph_nodes.py` · `src/api/allocation_graph_routes.py`

## 거는 것

- ★골든★: 기본 사슬(universe → returns → estimate → [views] → optimizer → risk)의 가중치·
  흐름·리스크 기여·ENB·제약 보고 == 같은 입력의 `run_analyze`. 백테스트 노드 == `/backtest`.
  노드는 사본을 만들지 않고 같은 함수를 부른다 — 이 골든이 갈라짐을 잡는다.
- 파라미터 규칙은 요청 모델(`AnalyzeRequest`·`BacktestRequest`)이 단일 출처다.
- 운영 모드(mock 불가)에서는 합성 수익률을 만들지 않는다 → returns failed + 사유, 하류 blocked.
- 모르는 모델·못 쓰는 EP·백테스트에 모자란 lookback 은 노드 실패 + 사유(짝: 맞으면 ok).
"""
from __future__ import annotations

import json
import os

import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_routes import (  # noqa: E402
    AnalyzeRequest,
    BacktestRequest,
    allocation_backtest,
    run_analyze,
)
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_routes import (  # noqa: E402
    T3,
    _fake_returns_df,
    _patch_caps,
    _patch_returns,
)

VIEW = {"assets": ["005930"], "direction": 1, "magnitude_pct": 4.0, "confidence": 60}


@pytest.fixture()
def market(monkeypatch):
    df = _fake_returns_df(T3, n=1100)
    _patch_returns(monkeypatch, df)
    _patch_caps(monkeypatch)
    return df


def _node(id_, type_, **params):
    return {"id": id_, "type": type_, "params": params, "position": {"x": 0, "y": 0}}


def _edge(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp,
            "target": t, "target_port": tp}


def chain(*, tickers=T3, weights=None, lookback=756, model="mvo", views=None,
          constraints=None, estimate=None, backtest=None, risk=True):
    nodes = [_node("u", "universe", tickers=list(tickers),
                   **({"weights": weights} if weights else {})),
             _node("r", "returns", lookback_days=lookback),
             _node("e", "estimate", **(estimate or {})),
             _node("o", "optimizer", model=model,
                   **({"constraints": constraints} if constraints else {}))]
    edges = [_edge("u", "universe", "r", "universe"),
             _edge("r", "returns", "e", "returns"),
             _edge("r", "returns", "o", "returns"),
             _edge("e", "belief", "o", "belief")]
    if views is not None:
        nodes.append(_node("v", "views", views=views))
        edges.append(_edge("v", "views", "o", "views"))
    if risk:
        nodes.append(_node("k", "risk"))
        edges.append(_edge("o", "weights", "k", "weights"))
    if backtest is not None:
        nodes.append(_node("b", "backtest", **backtest))
        edges += [_edge("r", "returns", "b", "returns"), _edge("o", "weights", "b", "weights")]
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _run(g):
    return pg.run(g, gn.REGISTRY)


# ── ★골든★ — `/analyze` 와 같은 수 ────────────────────────────────────────

@pytest.mark.parametrize("model,views,constraints", [
    ("mvo", None, None),
    ("bl", [VIEW], None),
    ("risk_parity", None, None),
    ("hrp", None, None),
    ("min_var", None, {"max_weight_pct": 40}),
    ("bl", [VIEW], {"max_weight_pct": 45, "min_weight_pct": 5}),
])
def test_the_default_chain_equals_analyze(market, model, views, constraints):
    out = _run(chain(model=model, views=views, constraints=constraints))
    assert out["ok"], {k: (v["status"], v["reason"]) for k, v in out["nodes"].items()}
    ref = run_analyze(AnalyzeRequest(tickers=T3, model=model, views=views,
                                     constraints=constraints))
    w, k = out["nodes"]["o"]["view"], out["nodes"]["k"]["view"]
    assert w["weights"] == ref["weights"]["optimized"]
    assert w["flow"] == ref["flow"]
    assert w["views_applied"] == ref["views_applied"]
    assert w["skipped_views"] == ref["skipped_views"]
    assert w["mu_engine"] == ref["mu_engine"]
    assert w["constraints_report"] == ref["constraints_report"]
    assert k["risk_contribution_optimized"] == ref["risk_contribution_optimized"]
    assert k["enb"] == ref["enb"]


@pytest.mark.parametrize("model", ["bl", "mvo"])
def test_the_conditional_belief_equals_analyze(market, model):
    """★추정 설정이 실제로 옵티마이저에 들어간다★ — 조건부 μ/Σ 를 켠 경우도 `/analyze` 와 같다.
    (끈 경우만 거는 골든은 옵티마이저가 믿음을 무시해도 통과한다.)"""
    est = {"conditional": True}
    out = _run(chain(model=model, estimate=est))
    assert out["nodes"]["o"]["status"] == "ok", out["nodes"]["o"]["reason"]
    ref = run_analyze(AnalyzeRequest(tickers=T3, model=model, conditional=True))
    o = out["nodes"]["o"]["view"]
    assert o["weights"] == ref["weights"]["optimized"]
    assert o["mu_engine"] == ref["mu_engine"]
    assert o["belief"]["blocked_reason"] == ref["conditional"].get("blocked_reason")
    assert out["nodes"]["k"]["view"]["risk_contribution_optimized"] == \
        ref["risk_contribution_optimized"]


def test_current_holdings_reach_the_constraint_solver_like_analyze(market):
    """`w_current` 는 회전율 제약에 쓰인다 — 유니버스의 현재 비중이 같은 자리로 간다."""
    cur = {"005930": 0.5, "000660": 0.3, "035420": 0.2}
    cons = {"turnover_cap_pct": 20}
    out = _run(chain(weights=cur, model="mvo", constraints=cons))
    ref = run_analyze(AnalyzeRequest(tickers=T3, weights=cur, model="mvo", constraints=cons))
    assert out["nodes"]["o"]["view"]["weights"] == ref["weights"]["optimized"]
    assert out["nodes"]["o"]["view"]["constraints_report"] == ref["constraints_report"]


def test_the_backtest_node_equals_the_backtest_route(market):
    bt = {"rebalance": "Q", "cost_bps": 15.0}
    out = _run(chain(model="bl", views=[VIEW], lookback=1008, backtest=bt))
    assert out["nodes"]["b"]["status"] == "ok", out["nodes"]["b"]["reason"]
    ref = allocation_backtest(BacktestRequest(tickers=T3, model="bl", views=[VIEW],
                                              lookback_days=1008, **bt))
    got = out["nodes"]["b"]["view"]
    for key in ("metrics", "summary", "equity_curve", "rebalances", "perf_label",
                "lookahead_evidence", "coverage"):
        assert got.get(key) == ref.get(key), key


# ── 파라미터 — 요청 모델이 단일 출처 ─────────────────────────────────────

@pytest.mark.parametrize("node_type,field,bad,good", [
    ("returns", "lookback_days", 89, 90),
    ("returns", "as_of", "2026/01/01", "2026-01-01"),
    ("optimizer", "delta", 0.4, 0.5),
    ("optimizer", "tau", 1.5, 1.0),
    ("universe", "tickers", [], ["005930"]),
    ("estimate", "regime_weighting", "soft", "probabilistic"),
    ("backtest", "cost_bps", 101, 100),
    ("backtest", "rebalance", "W", "M"),
])
def test_node_params_follow_the_request_models(node_type, field, bad, good):
    spec = gn.REGISTRY.get(node_type)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        spec.params_model.model_validate({field: bad, **_required(node_type, field)})
    spec.params_model.model_validate({field: good, **_required(node_type, field)})   # ★짝★


def _required(node_type, field):
    return {"tickers": ["005930"]} if node_type == "universe" and field != "tickers" else {}


def test_a_view_with_both_forms_is_refused_at_the_views_node():
    g = {"format": pg.FORMAT, "version": 1, "edges": [],
         "nodes": [_node("v", "views", views=[{"assets": ["005930"],
                                               "weights": {"005930": 1.0}}])]}
    rep = pg.validate(g, gn.REGISTRY)
    assert [e["node_id"] for e in rep["errors"] if e["code"] == "bad_params"] == ["v"]


# ── 실패는 이름으로, 하류는 막힌다 ────────────────────────────────────────

def test_fewer_than_two_assets_fails_returns_and_blocks_downstream(monkeypatch):
    _patch_returns(monkeypatch, _fake_returns_df(["005930"], n=800))
    out = _run(chain())
    r = out["nodes"]["r"]
    assert r["status"] == "failed" and "2개 미만" in r["reason"]
    assert r["view"] is None
    for nid in ("o", "k"):
        assert out["nodes"][nid]["status"] == "blocked"


def test_production_never_invents_returns(monkeypatch):
    """★운영에서 합성값 금지★ — 적재 데이터가 없으면 mock 폴백이 아니라 실패 + 사유."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: pd.DataFrame())
    out = _run(chain())
    assert out["nodes"]["r"]["status"] == "failed"
    assert out["nodes"]["o"]["status"] == "blocked"


def test_mock_mode_uses_the_labelled_synthetic_fallback(monkeypatch):
    """★짝★ — 개발(mock) 모드에서는 같은 빈 적재가 **합성으로 라벨된** 수익률이 된다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda tickers, start, end: pd.DataFrame())
    _patch_caps(monkeypatch)
    out = _run(chain())
    r = out["nodes"]["r"]
    assert r["status"] == "ok"
    assert r["provenance"]["source"] == "mock"
    assert r["provenance"]["data_grade"] == "E0"
    assert out["nodes"]["o"]["provenance"]["perf_label"]["data_real"] is False


def test_loaded_data_is_not_given_a_grade_it_cannot_show(market):
    """DB 적재분의 등급은 이 경로에서 행 단위로 관측되지 않는다 → 미상 + 사유(지어내지 않음)."""
    r = _run(chain())["nodes"]["r"]
    assert r["provenance"]["source"] == "db"
    assert r["provenance"]["data_grade"] is None and r["provenance"]["data_grade_reason"]


def test_an_unknown_model_is_refused_before_running_and_lists_what_exists(market):
    """모델은 카탈로그 enum 이라 **실행 전** 검증에서 걸린다 — 캔버스가 바로 빨갛게 그린다."""
    g = chain(model="magic")
    assert [e["node_id"] for e in pg.validate(g, gn.REGISTRY)["errors"]
            if e["code"] == "bad_params"] == ["o"]
    out = _run(g)
    o = out["nodes"]["o"]
    assert o["status"] == "blocked" and "magic" in o["reason"] and "mvo" in o["reason"]
    assert out["nodes"]["k"]["status"] == "blocked"


def test_a_model_the_environment_cannot_solve_fails_with_its_reason(market, monkeypatch):
    """★짝★ — 이름은 알지만 이 환경에서 못 푸는 모델은 실행 시 실패 + 가용성 사유."""
    import src.engine.allocation_studio as st
    real = st.model_availability
    monkeypatch.setattr(st, "model_availability", lambda: {
        **real(), "hrp": {"available": False, "reason": "scipy.cluster 가 없어"}})
    o = _run(chain(model="hrp"))["nodes"]["o"]
    assert o["status"] == "failed" and "scipy.cluster" in o["reason"]


def test_unavailable_entropy_pooling_fails_with_the_probe_reason(market, monkeypatch):
    monkeypatch.setattr("src.engine.capability.probe_all",
                        lambda: {"entropy_pooling": {"ok": False, "reason": "요건 X 없음"}})
    o = _run(chain(model="ep", views=[VIEW]))["nodes"]["o"]
    assert o["status"] == "failed" and "요건 X 없음" in o["reason"]


def test_a_future_as_of_fails_returns_like_analyze(market):
    g = chain()
    g["nodes"][1]["params"]["as_of"] = "2999-01-01"
    r = _run(g)["nodes"]["r"]
    assert r["status"] == "failed" and r["reason"]


def test_the_backtest_needs_the_backtest_lookback_floor(market):
    """분석(≥90)은 되지만 `/backtest`(≥252)는 안 되는 lookback — 같은 규칙으로 거부."""
    out = _run(chain(lookback=200, backtest={}))
    assert out["nodes"]["o"]["status"] == "ok"
    b = out["nodes"]["b"]
    assert b["status"] == "failed" and "lookback_days" in b["reason"]
    assert _run(chain(lookback=1008, backtest={}))["nodes"]["b"]["status"] == "ok"   # ★짝★


def test_a_backtest_plan_refusal_is_a_node_failure_not_a_result(market, monkeypatch):
    """`walk_forward` 가 계획 단계에서 거부하면(`{"error": True}`) 그것은 결과가 아니다 —
    곡선 없는 딕셔너리를 `ok` 로 그리면 캔버스가 빈 백테스트를 성공처럼 보인다."""
    monkeypatch.setattr("src.engine.allocation_backtest.walk_forward",
                        lambda *a, **k: {"error": True, "message": "학습 구간이 부족합니다"})
    b = _run(chain(lookback=1008, backtest={}))["nodes"]["b"]
    assert b["status"] == "failed" and "학습 구간" in b["reason"] and b["view"] is None


def test_the_backtest_says_the_conditional_belief_did_not_enter_it(market):
    """`/backtest` 에는 조건부 μ/Σ 가 없다 — 같은 뜻을 유지하되 숨기지 않는다."""
    out = _run(chain(lookback=1008, estimate={"conditional": True}, backtest={}))
    assert "조건부" in (out["nodes"]["b"]["view"] or {}).get("belief_note", "")
    out2 = _run(chain(lookback=1008, backtest={}))
    assert (out2["nodes"]["b"]["view"] or {}).get("belief_note") is None      # ★짝★


# ── 카탈로그·라우트 ───────────────────────────────────────────────────────

CORE = {"universe", "returns", "views", "estimate", "optimizer", "risk", "backtest"}


def test_the_catalog_has_the_core_chain_with_typed_ports():
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    # 핵심 사슬은 늘 있다 — BK 웨이브가 노드를 더한다(각 웨이브 테스트가 자기 노드를 건다).
    assert set(cat) >= CORE
    # BT1 — 포트는 역할(role)과 싣는 값(gives)을 함께 낸다(없는 포트는 키가 없다).
    assert [{k: p[k] for k in ("name", "type", "required")} for p in cat["optimizer"]["inputs"]] == [
        {"name": "returns", "type": "Returns", "required": True},
        {"name": "belief", "type": "Belief", "required": True},
        {"name": "views", "type": "Views", "required": False}]
    assert all(p["role"] for p in cat["optimizer"]["inputs"])
    assert cat["optimizer"]["outputs"] == [{"name": "weights", "type": "Weights",
                                            "gives": [{"key": "req"}, {"key": "sigma_annual"}]}]
    models = cat["optimizer"]["params_schema"]["properties"]["model"]
    assert set(models["enum"]) == set(__import__(
        "src.engine.allocation_studio", fromlist=["x"]).model_availability())


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_the_node_types_route_serves_the_catalog(client):
    r = client.get("/api/v1/allocation/graph/node-types")
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == pg.FORMAT and body["version"] == pg.VERSION
    assert {n["type"] for n in body["nodes"]} >= CORE
    assert set(body["port_types"]) >= {"Universe", "Returns", "Weights"}


def test_the_validate_route_names_errors(client):
    g = chain()
    g["edges"].append(_edge("u", "universe", "o", "returns"))
    r = client.post("/api/v1/allocation/graph/validate", json=g)
    assert r.status_code == 200
    codes = {e["code"] for e in r.json()["errors"]}
    assert {"type_mismatch"} <= codes or {"multiple_inputs"} <= codes


def test_the_run_route_returns_json_per_node(client, market):
    r = client.post("/api/v1/allocation/graph/run", json=chain(model="bl", views=[VIEW]))
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body["ok"] is True
    assert set(body["nodes"]) == {"u", "r", "e", "o", "v", "k"}
    json.dumps(body)                                         # 직렬화 가능


def test_a_foreign_file_gets_a_readable_refusal_not_a_500(client):
    r = client.post("/api/v1/allocation/graph/run", json={"format": "comfy", "nodes": []})
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["errors"]


# ── ★사본 금지★ — 노드는 산수를 다시 쓰지 않는다 (AST) ───────────────────

#: 노드 모듈이 엔진에서 직접 가져와도 되는 것. `optimize` 는 `run_analyze` 도 직접 부르는
#: 진입점이고, 나머지는 판정·레지스트리다. 제약·백테스트·리스크 산수는 라우트와 **같이
#: 쓰는 도우미**(`_apply_constraints`·`_policy_backtest`·`_risk_contribution_report`)로만.
_ALLOWED_ENGINE_IMPORTS = {
    ("src.engine", "portfolio_graph"), ("src.engine", "allocation_studio"),
    ("src.engine.allocation_studio", "optimize"), ("src.engine.entropy_views", "EPUnavailable"),
    ("src.engine.capability", "probe_all"),
}


def test_the_nodes_do_not_import_the_arithmetic_directly():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path("src/api/allocation_graph_nodes.py").read_text("utf-8"))
    seen = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            and (n.module or "").startswith("src.engine") for a in n.names}
    assert seen, "★공허 금지★ — 스캔이 아무것도 못 보면 이 테스트는 증거가 아니다"
    assert seen <= _ALLOWED_ENGINE_IMPORTS, seen - _ALLOWED_ENGINE_IMPORTS


# ★계산 중 DB 쓰기 0★ (BL0) — 이 파일의 모든 그래프 계산이 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
