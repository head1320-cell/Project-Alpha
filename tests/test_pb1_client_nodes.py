"""CF 3부 PB1 — 고객·계좌·목표·보유 진단 노드 (★관측만 — 비중을 바꾸지 않는다★)
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §8.2 · 사용자 결정(2026-10-23): PB 자산관리 기능.

- `client_profile` 고객 — 별칭(개인정보 모양이면 거절) · 위험 성향 · 출처 · 평가일 · 투자 기간. ★비면 미상 + 사유★(기본값으로 채우지 않는다).
- `account` 계좌 점검 — 비중(+고객) → 기존 `/accounts/diagnose` 를 그대로 부른다. 선언 안 한 한도는 '판정 못 함'(통과가 아니다) · 공매도 비중은 사유와 함께 실패.
- `goal` 목표까지 — 계좌 → 기존 `/accounts/glidepath` 를 그대로. 실적 ⟂ 계획 규율 유지.
- `holdings_check` 보유 진단 — 비중 → 기존 `/diagnostics/holdings` 를 그대로.
- ★어느 것도 비중을 바꾸지 않는다★ — 옵티마이저 결과는 이 노드들을 붙여도 같다. 주문·최적화기 import 0(AST).
"""
from __future__ import annotations

import ast
import json
import os
import pathlib

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _g(nodes, edges):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _run(g):
    return pg.run(g, gn.REGISTRY)["nodes"]


def _with(extra_nodes, extra_edges, **kw):
    g = chain(**kw)
    g["nodes"] += extra_nodes
    g["edges"] += extra_edges
    return g


# ── 등록 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,ins,outs", [
    ("client_profile", [], [("client", "Client")]),
    ("account", [("weights", "Weights", True), ("client", "Client", False)], [("account", "Account")]),
    ("goal", [("account", "Account", True), ("client", "Client", False)], []),
    ("holdings_check", [("weights", "Weights", True)], []),
])
def test_registered_with_ports(kind, ins, outs):
    spec = gn.REGISTRY.get(kind)
    assert spec is not None and spec.explain is not None and spec.plain_label and spec.category == "고객"
    assert [(p.name, p.type, p.required) for p in spec.inputs] == ins
    assert [(p.name, p.type) for p in spec.outputs] == outs


# ── 고객 ────────────────────────────────────────────────────────────────

def test_client_unknowns_stay_unknown_with_reasons():
    out = _run(_g([_node("c", "client_profile")], []))["c"]
    assert out["status"] == "ok"
    v = out["view"]
    assert v["risk_tolerance"] is None and v["profile_source"] == "unknown" and v["assessed_at"] is None
    trust = " ".join(t["text"] for t in out["explain"]["trust"])
    assert "모르" in trust                                   # 미상이라고 말한다
    assert "비중을 바꾸지 않아요" in trust                     # 관측만


def test_client_declared_profile_is_carried_and_aged():
    out = _run(_g([_node("c", "client_profile", alias="고객 A-12", risk_tolerance="moderate",
                         profile_source="survey", assessed_at="2026-01-02", horizon_years=10)], []))["c"]
    v = out["view"]
    assert v["alias"] == "고객 A-12" and v["risk_tolerance"] == "moderate" and v["horizon_years"] == 10
    assert isinstance(v["assessed_age_days"], int) and v["assessed_age_days"] > 0
    assert any("설문" in t["text"] and t["state"] == "assumed" for t in out["explain"]["trust"])


@pytest.mark.parametrize("alias", ["010-1234-5678", "hong@example.com", "900101-1234567", "계좌 12345678901",
                                   "01012345678", "02.123.4567"])
def test_client_alias_refuses_pii_shapes(alias):
    """★별칭만★ — 전화·이메일·주민번호·긴 숫자열 모양이면 그 이유로 실패한다(노드를 몰라서 실패하는 것과 구별)."""
    assert gn.REGISTRY.get("client_profile") is not None
    out = _run(_g([_node("c", "client_profile", alias=alias)], []))["c"]
    assert out["status"] != "ok" and "별칭" in (out.get("reason") or "")


@pytest.mark.parametrize("alias", ["고객 A-12", "A-12", "김 PB 상담 3번", "2026 정기점검"])
def test_client_alias_allows_plain_aliases(alias):
    """짝 — 짧은 숫자·하이픈이 든 별칭까지 막지 않는다(항상-거부 금지)."""
    assert _run(_g([_node("c", "client_profile", alias=alias)], []))["c"]["status"] == "ok"


# ── 계좌 점검 ─────────────────────────────────────────────────────────────

def _acct_graph(params, *, client=None):
    nodes = [_node("a", "account", **params)]
    edges = [_edge("o", "weights", "a", "weights")]
    if client is not None:
        nodes.append(_node("c", "client_profile", **client))
        edges.append(_edge("c", "client", "a", "client"))
    return _with(nodes, edges)


def test_undeclared_limit_is_undetermined_not_pass(market):
    r = _run(_acct_graph({"account_type": "irp", "risky_asset_classes": ["EQUITY"]}))["a"]
    assert r["status"] == "ok", r.get("reason")
    verdicts = {v["kind"]: v["verdict"] for v in r["view"]["result"]["verdicts"]}
    assert verdicts and set(verdicts.values()) == {"undetermined"}


def test_declared_limit_is_judged(market):
    """짝 — 출처·기준일과 함께 선언하면 판정이 난다(항상 판정 못 함 구현 배제).

    연습 종목은 자산군이 배정되지 않아 위험자산 비중이 [0, 100] 구간이다(미배정 ≠ 0 — AD3). 70% 한도는 그 구간을 걸쳐
    '판정 못 함' 이 정직한 답이고, 구간 전체를 덮는 100% 한도는 '넘지 않음' 이다.
    """
    def verdict(value):
        r = _run(_acct_graph({"account_type": "irp", "risky_asset_classes": ["EQUITY"],
                              "limits": [{"kind": "risky_asset_max_pct", "value": value, "source": "PB 선언",
                                          "as_of": "2026-10-01"}]}))["a"]
        return {x["kind"]: x["verdict"] for x in r["view"]["result"]["verdicts"]}["risky_asset_max_pct"]
    assert verdict(100) == "pass"
    assert verdict(70) == "undetermined"


def test_account_says_the_optimizer_does_not_know(market):
    r = _run(_acct_graph({"account_type": "irp"}))["a"]
    assert any("최적화기" in t["text"] for t in r["explain"]["trust"])


def _current_graph(weights, kind="account", **params):
    a, b, c = T3
    return _g([_node("u", "universe", tickers=list(T3), weights=weights), _node("cw", "current_weights"),
               _node("x", kind, **params)],
              [_edge("u", "universe", "cw", "universe"), _edge("cw", "weights", "x", "weights")])


@pytest.mark.parametrize("kind,params", [("account", {"account_type": "general"}), ("holdings_check", {})])
def test_short_weights_fail_with_reason(market, kind, params):
    a, b, c = T3
    r = _run(_current_graph({a: 60.0, b: 50.0, c: -10.0}, kind, **params))["x"]
    assert r["status"] == "failed" and "공매도" in r["reason"]


@pytest.mark.parametrize("kind,params", [("account", {"account_type": "general"}), ("holdings_check", {})])
def test_long_only_current_weights_are_checked(market, kind, params):
    """짝 — 같은 길로 롱온리 비중이면 점검한다."""
    a, b, c = T3
    r = _run(_current_graph({a: 50.0, b: 30.0, c: 20.0}, kind, **params))["x"]
    assert r["status"] == "ok", r.get("reason")


def test_unknown_account_type_is_refused():
    from pydantic import ValidationError
    spec = gn.REGISTRY.get("account")
    assert spec is not None
    with pytest.raises(ValidationError):
        spec.params_model(account_type="pension_x")
    spec.params_model(account_type="irp")                     # 짝 — 아는 유형은 받는다


# ── 목표까지 ──────────────────────────────────────────────────────────────

def test_goal_runs_on_the_account(market):
    g = _with([_node("a", "account", account_type="irp", risky_asset_classes=["EQUITY"]),
               _node("t", "goal", target_retirement_year=2045,
                     curve=[{"years_to_target": 20, "risky_target_pct": 70},
                            {"years_to_target": 0, "risky_target_pct": 30}])],
              [_edge("o", "weights", "a", "weights"), _edge("a", "account", "t", "account")])
    r = _run(g)["t"]
    assert r["status"] == "ok", r.get("reason")
    assert r["view"]["result"]["glide"] is not None
    json.dumps(r["view"], allow_nan=False)


def test_goal_without_curve_does_not_invent_a_target(market):
    """곡선(2점 미만)이 없으면 목표 비중을 지어내지 않는다 — glidepath 의 규율 그대로."""
    g = _with([_node("a", "account", account_type="irp"), _node("t", "goal", target_retirement_year=2045)],
              [_edge("o", "weights", "a", "weights"), _edge("a", "account", "t", "account")])
    r = _run(g)["t"]
    assert r["status"] == "ok" and r["view"]["result"]["glide"]["target_pct"] is None


# ── 보유 진단 ──────────────────────────────────────────────────────────────

def test_holdings_check_runs_and_says_practice(market):
    g = _with([_node("h", "holdings_check")], [_edge("o", "weights", "h", "weights")])
    r = _run(g)["h"]
    assert r["status"] == "ok", r.get("reason")
    assert "risk_contributions" in r["view"]["result"]


# ── 관측만 ───────────────────────────────────────────────────────────────

def test_optimizer_weights_do_not_change_when_client_nodes_are_attached(market):
    base = _run(chain())["o"]["view"]["weights"]
    g = _with([_node("c", "client_profile", risk_tolerance="conservative"),
               _node("a", "account", account_type="irp"), _node("h", "holdings_check")],
              [_edge("o", "weights", "a", "weights"), _edge("c", "client", "a", "client"),
               _edge("o", "weights", "h", "weights")])
    r = _run(g)
    assert r["a"]["status"] == "ok" and r["c"]["status"] == "ok" and r["h"]["status"] == "ok"   # 붙인 노드가 실제로 돌았다
    assert r["o"]["view"]["weights"] == base


def test_the_weights_passed_downstream_are_untouched(market):
    """★관측만★ — 계좌·보유 진단을 붙여도 옵티마이저가 넘긴 비중 값(하류가 받는 그 값) 자체가 같다."""
    import numpy as np
    base = np.asarray(pg._execute(chain(), gn.REGISTRY)[1]["o"]["weights"]["weights"], dtype=float)
    g = _with([_node("a", "account", account_type="irp"), _node("h", "holdings_check")],
              [_edge("o", "weights", "a", "weights"), _edge("o", "weights", "h", "weights")])
    after = np.asarray(pg._execute(g, gn.REGISTRY)[1]["o"]["weights"]["weights"], dtype=float)
    assert np.array_equal(base, after)


def test_module_imports_no_order_or_optimizer_path():
    tree = ast.parse((ROOT / "src/api/allocation_graph_nodes_client.py").read_text(encoding="utf-8"))
    # `from src.engine import constrained_opt` 은 모듈 이름이 아니라 가져오는 이름에 있다 — 둘 다 본다.
    names = {f"{n.module or ''}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = [m for m in names if any(x in m for x in ("constrained_opt", "trading_engine", "order_executor", "stage13"))]
    assert not bad, bad


# ── 설명이 구간·격차를 정직하게 말한다 ─────────────────────────────────────

def _pb_chain():
    a, b, c = T3
    return _g([_node("u", "universe", tickers=list(T3), weights={a: 50.0, b: 30.0, c: 20.0}), _node("cw", "current_weights"),
               _node("a", "account", account_type="irp", risky_asset_classes=["EQUITY"]),
               _node("t", "goal", target_retirement_year=2045,
                     curve=[{"years_to_target": 20, "risky_target_pct": 70}, {"years_to_target": 0, "risky_target_pct": 30}])],
              [_edge("u", "universe", "cw", "universe"), _edge("cw", "weights", "a", "weights"),
               _edge("a", "account", "t", "account")])


def test_account_says_the_risky_interval_and_the_unassigned_share(market):
    """연습 종목은 자산군 미배정 — 위험자산 비중은 점이 아니라 0~100% 구간이고, 그 이유(미배정 몫)를 말한다."""
    r = _run(_pb_chain())["a"]
    facts = " ".join(r["explain"]["facts"])
    assert "0~100%" in facts and "자산군을 모르는 보유 100%" in facts


def test_goal_says_the_gap_is_unknown_when_target_is_inside_the_interval(market):
    r = _run(_pb_chain())["t"]
    assert r["view"]["result"]["glide"]["gap"]["state"] == "unknown"
    facts = " ".join(r["explain"]["facts"])
    assert "차이는 몰라요" in facts
    assert not any(w in facts for w in ("많아요", "적어요"))       # 부호를 지어내지 않는다


def test_goal_states_a_known_gap_with_its_sign():
    """짝 — 구간이 목표 밖이면 부호와 폭을 말한다(설명기를 직접 — 연습 종목은 늘 미배정이라)."""
    from src.api.allocation_graph_nodes_client import _explain_goal
    view = {"result": {"glide": {"target_pct": 40.0, "gap": {"state": "above", "lo": 10.0, "hi": 20.0, "sign": 1}},
                       "contribution": {"months": None}}}
    facts = " ".join(_explain_goal(view, {}, None)["facts"])
    assert "목표보다 10.0~20.0%p 많아요" in facts
    view["result"]["glide"]["gap"] = {"state": "below", "lo": -20.0, "hi": -5.0, "sign": -1}
    assert "목표보다 5.0~20.0%p 적어요" in " ".join(_explain_goal(view, {}, None)["facts"])


def test_account_without_a_type_stops_instead_of_defaulting(market):
    """계좌 유형을 기본값(일반)으로 채우지 않는다 — 비워 두면 이유와 함께 멈춘다."""
    a, b, c = T3
    r = _run(_current_graph({a: 50.0, b: 30.0, c: 20.0}, "account"))["x"]
    assert r["status"] == "failed" and "계좌 유형" in r["reason"]


def test_future_assessment_date_is_refused():
    out = _run(_g([_node("c", "client_profile", risk_tolerance="moderate", assessed_at="2099-01-01")], []))["c"]
    assert out["status"] == "failed" and "미래" in out["reason"]
