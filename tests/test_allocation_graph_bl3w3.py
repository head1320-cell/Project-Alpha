"""BL3 W3 · 기업 웨이브 — 샌드박스 · 역DCF · 가치 분포 · 재무 심층 · 위험 심층 · 매크로 민감도 · 테제 점검
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W3. 노드는 `company_routes` 의 라우트 함수를 **그대로** 부른다(골든).

## 거는 것
- 종목은 `stock_master.get_stock_name` 으로 판정한다 — mock 가격은 가짜 코드에도 값을 주므로 가격으로 판정하지 않는다(짝: 아는 코드는 통과).
- 가격은 비우면 `company_views.prices_for` 의 값과 **출처**를 쓴다. 못 구하면 사유 실패(짝: 직접 넣으면 계산) — 지어내지 않는다.
- 엔진이 `available: false` 로 답하면(적자 기업의 역DCF · 재무 미적재 · 조건 없는 테제) 숫자 대신 그 사유로 실패한다.
- 매크로 민감도의 통계 블록은 BL2b `macro_series_map()` 계열 — 운영은 저장된 관측만(외부 호출 0 · 적재 0).
- 계산 중 쓰기 0(`graph_write_guard`). 계보는 `forward_only`(오늘의 재무·가격) · mock 이면 연습용.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import company_routes as cr  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import _node  # noqa: E402
from tests.test_allocation_graph_bl2b import live_and_store  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

CODE = "005930"
KINDS = ("company_valuation", "reverse_dcf", "valuation_distribution", "financial_deep", "risk_deep",
         "company_macro_sensitivity", "thesis_check")
KILL = {"logic": "AND", "conditions": [{"field": "roe", "op": "lt", "value": 8}], "groups": []}


def _one(kind, **params):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("c", kind, **params)], "edges": []}
    return pg.run(g, gn.REGISTRY)["nodes"]["c"]


def _px():
    from src.engine.company_views import prices_for
    return prices_for([CODE])[0][CODE]


def _params(kind):
    return {"code": CODE, **({"kill_conditions": KILL, "claim": "메모리 업황 회복"} if kind == "thesis_check" else {})}


# ══ 카탈로그 · 공통 ══════════════════════════════════════════════════════════

def test_all_seven_company_nodes_are_registered_and_thesis_backtest_is_not():
    kinds = set(gn.REGISTRY.types())
    assert set(KINDS) <= kinds
    assert "thesis_backtest" not in kinds


@pytest.mark.parametrize("kind", KINDS)
def test_an_unknown_code_fails_instead_of_valuing_a_fake_company(kind):
    r = _one(kind, **{**_params(kind), "code": "999999"})
    assert r["status"] == "failed" and "999999" in r["reason"] and "종목" in r["reason"]


@pytest.mark.parametrize("kind", [k for k in KINDS if k not in ("financial_deep", "thesis_check")])
def test_without_a_price_the_node_fails_and_with_one_it_computes(kind, monkeypatch):
    monkeypatch.setattr("src.engine.company_views.prices_for", lambda codes: ({}, {c: "unavailable" for c in codes}))
    r = _one(kind, code=CODE)
    assert r["status"] == "failed" and "가격" in r["reason"]
    # 짝: 가격을 직접 넣으면 계산한다(그 출처는 '직접 입력')
    r = _one(kind, code=CODE, price=50000)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["price_source"] == "직접 입력"


@pytest.mark.parametrize("kind", [k for k in KINDS if k != "financial_deep"])
def test_each_node_is_practice_in_mock_mode_and_names_the_company(kind, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _one(kind, **_params(kind))
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["name"] == "삼성전자"
    assert r["lineage"]["practice"] is True and r["lineage"]["pit"] == "forward_only"
    assert r["explain"]["title"] and r["explain"]["trust"]


# ══ 골든 — 노드 == 라우트 ════════════════════════════════════════════════════

def test_valuation_sandbox_equals_the_route():
    px = _px()
    r = _one("company_valuation", code=CODE)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["price"] == px and r["view"]["price_source"] != "직접 입력"
    assert r["view"]["result"] == cr.company_valuation_sandbox(CODE, price=px, rf=None, beta=None, erp=None, g=None, years=None)


def test_valuation_sandbox_passes_the_expert_assumptions():
    r = _one("company_valuation", code=CODE, price=50000, rf=0.04, g=0.01, years=5)
    assert r["status"] == "ok", r["reason"]
    ref = cr.company_valuation_sandbox(CODE, price=50000, rf=0.04, beta=None, erp=None, g=0.01, years=5)
    assert r["view"]["result"] == ref
    # 짝: 가정을 바꾸면 값이 바뀐다(무시하지 않는다)
    base = cr.company_valuation_sandbox(CODE, price=50000, rf=None, beta=None, erp=None, g=None, years=None)
    assert ref["unified"]["value"] != base["unified"]["value"]


def test_reverse_dcf_equals_the_route():
    r = _one("reverse_dcf", code=CODE, price=50000)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == cr.company_reverse_dcf(CODE, price=50000, market_cap=None, bracket_lo=-0.5, bracket_hi=0.5)


def test_an_unavailable_reverse_dcf_fails_with_the_engine_reason(monkeypatch):
    monkeypatch.setattr(cr, "company_reverse_dcf", lambda *a, **k: {"available": False, "reason": "FCF 가 음수라 근이 없습니다"})
    r = _one("reverse_dcf", code=CODE, price=50000)
    assert r["status"] == "failed" and "FCF 가 음수" in r["reason"]


def test_valuation_distribution_equals_the_route():
    r = _one("valuation_distribution", code=CODE, price=50000, n=500)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == cr.company_valuation_distribution(CODE, price=50000, n=500)


def test_financial_deep_without_loaded_statements_fails_with_the_note():
    ref = cr.company_financial_deep(CODE)
    assert ref["available"] is False          # mock 에는 재무 시계열이 적재돼 있지 않다(전제 확인)
    r = _one("financial_deep", code=CODE)
    assert r["status"] == "failed" and ref["note"] in r["reason"]


def test_financial_deep_with_statements_equals_the_route(monkeypatch):
    doc = {"available": True, "qoe": {"years": [2024], "red_flags": []}, "nwc": {"years": [2024]},
           "waterfall": {"years": [2024]}, "dupont": {"years": [2024]}, "roic_wacc": None}
    monkeypatch.setattr(cr, "company_financial_deep", lambda code: doc)
    r = _one("financial_deep", code=CODE)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == doc


def test_risk_deep_equals_the_route():
    r = _one("risk_deep", code=CODE, price=50000)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == cr.company_risk_deep(CODE, price=50000)


def test_macro_sensitivity_in_development_equals_the_route(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _one("company_macro_sensitivity", code=CODE, price=50000)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == cr.company_macro_sensitivity(CODE, price=50000, statistical=True)


def test_macro_sensitivity_can_leave_out_the_statistical_block():
    r = _one("company_macro_sensitivity", code=CODE, price=50000, statistical=False)
    assert r["status"] == "ok", r["reason"]
    assert "statistical" not in r["view"]["result"]
    assert r["view"]["result"] == cr.company_macro_sensitivity(CODE, price=50000, statistical=False)


def test_macro_sensitivity_in_production_reads_only_the_store(live_and_store, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.services.macro_collector as mc
    calls = []
    monkeypatch.setattr(mc.BokClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr(mc.FredClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr("src.data.macro_observation_store.coverage",
                        lambda *a, **k: {"available": True, "rows": len(live_and_store["rows"])})
    seen = []
    import src.engine.valuation.macro_sensitivity as ms
    real = ms.statistical_sensitivity
    monkeypatch.setattr(ms, "statistical_sensitivity",
                        lambda code, series_map=None, **k: seen.append(series_map) or real(code, series_map=series_map, **k))
    r = _one("company_macro_sensitivity", code=CODE, price=50000)
    assert seen and seen[-1], "저장된 계열이 통계 블록에 들어갔다"
    assert calls == [] and live_and_store["recorded"] == []
    assert r["status"] in ("ok", "failed")


def test_thesis_check_equals_the_route_and_saves_nothing():
    r = _one("thesis_check", code=CODE, claim="메모리 업황 회복", kill_conditions=KILL)
    assert r["status"] == "ok", r["reason"]
    # 노드는 스크리너와 같은 조건 모델(`ConditionModel`)을 거친다 — 같은 정규화 목록을 라우트에 넣은 결과와 같아야 한다
    from src.api.screener_routes import FilterGroupModel
    kills = [c.model_dump(exclude_none=True) for c in FilterGroupModel(**KILL).conditions]
    ref = cr.company_thesis_check(CODE, cr.ThesisCheckRequest(claim="메모리 업황 회복", kill_conditions=kills))
    assert r["view"]["result"] == ref
    assert ref["kill_conditions"]["rows"][0]["valid"] is True, "★공허 금지★ — 실제로 유효한 조건을 점검했다"


def test_a_thesis_with_an_unknown_field_fails_with_the_registry_reason():
    bad = {"logic": "AND", "conditions": [{"field": "no_such_field", "op": "gt", "value": 1}], "groups": []}
    r = _one("thesis_check", code=CODE, claim="x", kill_conditions=bad)
    assert r["status"] == "failed" and "no_such_field" in r["reason"]


def test_a_thesis_without_kill_conditions_fails():
    r = _one("thesis_check", code=CODE, claim="x", kill_conditions={"logic": "AND", "conditions": [], "groups": []})
    assert r["status"] == "failed" and "kill" in r["reason"]


def test_a_thesis_with_nested_groups_is_refused_instead_of_flattened():
    nested = {"logic": "AND", "conditions": [{"field": "roe", "op": "lt", "value": 8}],
              "groups": [{"logic": "OR", "conditions": [{"field": "per", "op": "gt", "value": 30}], "groups": []}]}
    r = _one("thesis_check", code=CODE, claim="x", kill_conditions=nested)
    assert r["status"] == "failed" and "묶음" in r["reason"]


def test_a_zero_fair_value_is_not_described_as_no_gap(monkeypatch):
    """괴리율은 적정가가 없으면 0 으로 온다(`compute_gap_pct`) — '차이 없음' 으로 말하면 미상을 0 으로 만든다."""
    out = {"unified": {"value": 0.0, "gap_pct": 0, "models": []}, "assumptions": [], "sensitivity": {},
           "football_field": {"bands": []}, "comps": {}}
    monkeypatch.setattr(cr, "company_valuation_sandbox", lambda *a, **k: out)
    r = _one("company_valuation", code=CODE, price=50000)
    assert r["status"] == "ok"
    assert "정하지 못했" in r["explain"]["title"] and "%" not in r["explain"]["title"]


def test_the_sandbox_title_says_which_side_the_price_is_on(monkeypatch):
    out = {"unified": {"value": 40000.0, "gap_pct": 25.0, "models": []}, "assumptions": [], "sensitivity": {},
           "football_field": {"bands": []}, "comps": {}}
    monkeypatch.setattr(cr, "company_valuation_sandbox", lambda *a, **k: out)
    assert "높아요" in _one("company_valuation", code=CODE, price=50000)["explain"]["title"]
    out["unified"]["gap_pct"] = -25.0
    assert "낮아요" in _one("company_valuation", code=CODE, price=30000)["explain"]["title"]
