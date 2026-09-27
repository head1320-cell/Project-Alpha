"""BL3 W3b · 기업 분석 현업 모델 노드 — C1(EVA·가치의 층·배수 PEG·영업 동인 MC)
==============================================================================
노드는 `company_model_routes` 라우트 함수를 **그대로** 부른다(골든). 엔진 수치는 `test_practice_models.py` 가 손으로 푼 값으로 지킨다.

## 거는 것
- 종목·가격 규칙은 W3 와 같다(모르는 코드 실패 · 가격 없음 실패 / 직접 입력 짝).
- ★운영에서 DART 이력의 합성 폴백 연도는 버리고 센다★ — 클라이언트가 실패하면 조용히 합성 재무를 주기 때문이다(짝: mock 허용이면 쓴다).
- 가치의 층의 '성장까지' 값은 가치평가 샌드박스의 통합 적정가 그대로 · 가중 합이 1 이 아니면 실패.
- 배수의 EPS 성장률은 팩터 스토어의 관측값 — 없으면 '미상'(0 이 아니다).
- 계산 중 쓰기 0(`graph_write_guard`).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import company_model_routes as cmr  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import _node  # noqa: E402

pytestmark = pytest.mark.usefixtures("graph_write_guard")

CODE, PX = "005930", 50000.0
KINDS = ("company_eva", "company_value_layers", "company_multiples", "company_driver_mc")
FAST = {"company_multiples": {"peers": False}, "company_driver_mc": {"n": 300}}


def _one(kind, **params):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("c", kind, **params)], "edges": []}
    return pg.run(g, gn.REGISTRY)["nodes"]["c"]


def _p(kind, **kw):
    return {"code": CODE, **FAST.get(kind, {}), **kw}


def test_the_four_c1_nodes_are_registered():
    assert set(KINDS) <= set(gn.REGISTRY.types())


@pytest.mark.parametrize("kind", KINDS)
def test_each_node_computes_in_mock_mode_as_practice_and_labels_its_inputs(kind):
    r = _one(kind, **_p(kind, price=PX))
    assert r["status"] == "ok", r["reason"]
    assert r["lineage"]["practice"] is True and r["lineage"]["pit"] == "forward_only"
    bases = {i["basis"] for i in r["view"]["result"]["inputs"]}
    assert bases & {"가정", "근사"}, "모든 모델은 적어도 하나의 가정·근사를 드러낸다"
    assert r["explain"]["title"] and r["explain"]["trust"]


@pytest.mark.parametrize("kind", KINDS)
def test_an_unknown_code_fails(kind):
    r = _one(kind, **_p(kind, code="999999"))
    assert r["status"] == "failed" and "999999" in r["reason"]


@pytest.mark.parametrize("kind", KINDS)
def test_without_a_price_it_fails_and_with_one_it_computes(kind, monkeypatch):
    monkeypatch.setattr("src.engine.company_views.prices_for", lambda codes: ({}, {c: "unavailable" for c in codes}))
    assert "가격" in _one(kind, **_p(kind))["reason"]
    assert _one(kind, **_p(kind, price=PX))["status"] == "ok"


# ══ 골든 — 노드 == 라우트 ════════════════════════════════════════════════════

def test_eva_equals_the_route():
    r = _one("company_eva", **_p("company_eva", price=PX, fade_years=7))
    ref = cmr.company_model_eva(CODE, cmr.EvaRequest(price=PX, fade_years=7))
    assert r["view"]["result"] == ref
    assert ref["available"] is True and ref["value_driver"]["available"] is True


def test_value_layers_equal_the_route_and_use_the_sandbox_value():
    from src.engine.company_analytics import valuation_sandbox
    r = _one("company_value_layers", **_p("company_value_layers", price=PX, w_asset=0.2, w_epv=0.3, w_full=0.5))
    ref = cmr.company_model_value_layers(CODE, cmr.LayersRequest(price=PX, w_asset=0.2, w_epv=0.3, w_full=0.5))
    assert r["view"]["result"] == ref
    assert ref["full_per_share"] == valuation_sandbox(CODE, PX, {})["unified"]["value"]


def test_multiples_equal_the_route():
    r = _one("company_multiples", **_p("company_multiples", price=PX))
    assert r["view"]["result"] == cmr.company_model_multiples(CODE, cmr.MultiplesRequest(price=PX, peers=False))


def test_driver_mc_equals_the_route_and_is_reproducible():
    r = _one("company_driver_mc", **_p("company_driver_mc", price=PX, seed=11))
    ref = cmr.company_model_driver_mc(CODE, cmr.DriverMcRequest(price=PX, n=300, seed=11))
    assert r["view"]["result"] == ref
    assert _one("company_driver_mc", **_p("company_driver_mc", price=PX, seed=11))["view"]["result"]["quantiles"] \
        == ref["quantiles"]


# ══ 가정의 출처 ═════════════════════════════════════════════════════════════

def _basis(res, key):
    return next(i for i in res["inputs"] if i["key"] == key)


def test_an_empty_ronic_is_the_latest_roic_and_is_labelled_approximate():
    ref = cmr.company_model_eva(CODE, cmr.EvaRequest(price=PX))
    assert ref["value_driver"]["ronic"] == pytest.approx(ref["latest"]["roic"])
    assert _basis(ref, "ronic")["basis"] == "근사"
    # 짝: 직접 정하면 가정
    own = cmr.company_model_eva(CODE, cmr.EvaRequest(price=PX, ronic=0.15))
    assert own["value_driver"]["ronic"] == 0.15 and _basis(own, "ronic")["basis"] == "가정"


def test_an_unknown_eps_growth_is_unknown_not_zero(monkeypatch):
    from src.data.fundamentals_store import FundamentalsStore

    class _S:
        def get_factors(self, code):
            return {}
    monkeypatch.setattr(FundamentalsStore, "get_default", classmethod(lambda cls: _S()))
    ref = cmr.company_model_multiples(CODE, cmr.MultiplesRequest(price=PX, peers=False))
    assert ref["peg"] is None and _basis(ref, "eps_growth")["basis"] == "미상"


def test_layer_weights_that_do_not_sum_to_one_fail():
    r = _one("company_value_layers", **_p("company_value_layers", price=PX, w_asset=0.5, w_epv=0.5, w_full=0.5))
    assert r["status"] == "failed" and "합" in r["reason"]


# ══ 운영: DART 이력의 합성 폴백은 버리고 센다 ═════════════════════════════════

def _mocked_dart(monkeypatch, *, mock_years: int):
    from src.data import dart_client as dc
    from src.engine.valuation.valuation_models import ValuationEngine
    real = dc.DARTClient()._mock_financial_statement

    def hist(self, corp_code, years=5, current_year=None):
        out = []
        for i, y in enumerate(range(2024, 2024 - years, -1)):
            fs = real(corp_code, str(y))
            fs.is_mock = i < mock_years
            out.append(fs)
        return out
    monkeypatch.setattr(dc.DARTClient, "get_financial_history", hist)

    def load(self, code, price, market_cap=None, bsns_year=None):
        fs = real("x", "2025")
        fs.is_mock = False
        ValuationEngine.prepare_statement(fs, price, market_cap=market_cap)
        return {"available": True, "fs": fs, "corp_name": "삼성전자", "is_mock": False, "reason": None}
    monkeypatch.setattr(ValuationEngine, "load_statement", load)


def test_in_production_synthetic_history_years_are_dropped_and_counted(monkeypatch):
    _mocked_dart(monkeypatch, mock_years=2)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    d = cmr.load_inputs(CODE, PX)
    assert d["dropped_mock"] == 2 and len(d["history"]) == 3
    assert all(not getattr(fs, "is_mock", False) for fs in d["history"])
    out = cmr.company_model_driver_mc(CODE, cmr.DriverMcRequest(price=PX, n=200))
    assert out["dropped_mock_years"] == 2 and "합성" in out["history_note"]


def test_in_development_synthetic_history_is_kept(monkeypatch):
    _mocked_dart(monkeypatch, mock_years=2)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    d = cmr.load_inputs(CODE, PX)
    assert d["dropped_mock"] == 0 and len(d["history"]) == 5


def test_practice_follows_the_mock_gate_even_when_the_result_is_not_flagged(monkeypatch):
    """결과에 `is_mock` 이 없어도 mock 이 허용된 환경이면 연습용이다(짝: 운영 환경이면 연습용이 아니다)."""
    fake = {"available": True, "inputs": [], "eps": 1.0, "per": 1.0, "peg": None, "justified": {}, "peer": {},
            "matrix": {}, "is_mock": False}
    monkeypatch.setattr(cmr, "company_model_multiples", lambda code, req: fake)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert _one("company_multiples", **_p("company_multiples", price=PX))["lineage"]["practice"] is True
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert _one("company_multiples", **_p("company_multiples", price=PX))["lineage"]["practice"] is False
