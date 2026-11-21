"""과거 시점(as_of) 스크리닝은 ★그 시점 값이 있는 항목★으로만 거르고 정렬한다 (2026-11-13 — 감사 §12 · 사용자 결정 "막는다").

재 보니(감사 §11) 조건 필드 157개 가운데 143개가 과거 시점 평가에서도 ★오늘 값★이었다 — 평가 뒤에 세 저장소가 붙이는 팩터다.
그 필드에 건 조건·정렬은 미래 정보로 과거 유니버스를 고른다(룩어헤드). 이 결과가 생존편향 보정 백테스트의 후보 풀로 들어간다.

계약
  1. 과거 시점 요청의 조건(종류 · 필드 · 수식 속 필드)·정렬(1차 · 2차)이 시점 값이 없는 항목을 쓰면 ★계산하지 않고★ 그 항목을 짚어 사유를 낸다.
     판정은 `ValuationScreener.run` 한 곳 — 라우트 · 백테스트 · 캔버스 노드가 모두 거기를 지난다.
  2. 유동성 게이트는 과거 시점에 ★적용하지 않고 그렇다고 말한다★(오늘의 거래대금·거래 상태로 과거를 거르지 않는다 — 사용자 결정).
  3. 그 시점 공시가 주지 않은 재무 칸은 ★미상★이다(평가 때의 오늘 값을 남기지 않는다 — §11 의 '부분 적용') + 몇 종목의 어느 칸인지 싣는다.
  현재 스크리닝은 아무것도 바뀌지 않는다(짝).

★이 파일이 말하지 않는 것★ — 시점 값이 있다고 한 항목의 ★품질★(정정공시 빈티지 · 분할 전후 주식 수 · 시총 시계열의 범위)은 미검증이다.
"""
from __future__ import annotations

import pytest

ASOF = "2024-06-28"
U = ["005930", "000660", "035420"]
META = {"trade_date": ASOF, "source": "krx", "price_basis": "raw"}


@pytest.fixture
def mem_snapshot(monkeypatch):
    import src.data.snapshot_db as sdb
    store: dict = {}
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: store[k] for k in keys if k in store})
    monkeypatch.setattr(sdb, "write_many", lambda payload: store.update(payload))
    return store


def _group(*conds, logic="AND", groups=()):
    from src.engine.filter_ast import parse_group
    return parse_group({"logic": logic, "conditions": list(conds), "groups": list(groups)})


def _c(field, op="gt", value=0, **extra):
    return {"field": field, "op": op, "value": value, **extra}


def _screener():
    from src.engine.screener import ValuationScreener
    return ValuationScreener()


# ── 1. 판정 함수 ─────────────────────────────────────────────────────────────

def test_the_capable_set_is_in_the_field_registry_and_is_small():
    """시점 값이 있다고 하는 항목은 모두 등록부에 있고, 붙이는 팩터(펀더멘털·가격·확장)는 하나도 없다."""
    from src.engine.filter_ast import FIELD_BY_ID
    from src.engine.pit_fields import PIT_CAPABLE_FIELDS
    from src.engine.pit_store import PIT_FIN_KEYS
    assert PIT_CAPABLE_FIELDS <= set(FIELD_BY_ID) and set(PIT_FIN_KEYS) <= PIT_CAPABLE_FIELDS
    assert not PIT_CAPABLE_FIELDS & {"roe", "dividend_yield", "debt_to_equity", "return_12m", "momentum_12_1", "operating_margin", "foreign_ownership"}


def test_conditions_on_todays_factors_are_named(monkeypatch):
    from src.engine.pit_fields import pit_violations
    bad = pit_violations(_group(_c("roe"), _c("per", "lt", 10), _c("momentum_12_1")), None, None)
    assert len(bad) == 2 and all("조건" in b for b in bad)
    assert any("roe" in b for b in bad) and any("momentum_12_1" in b for b in bad) and not any("per" in b.lower().split("(")[-1] for b in bad)


def test_conditions_on_point_in_time_fields_pass():
    """★짝★ — 시점 값이 있는 항목만 쓰면 아무것도 막지 않는다(늘 막는 구현이 아니다)."""
    from src.engine.pit_fields import pit_violations
    g = _group(_c("per", "lt", 10), _c("roe_pct"), _c("debt_ratio_pct", "lt", 100), _c("composite_score"))
    assert pit_violations(g, "composite_score", "gap_pct") == []
    assert pit_violations(None, None, None) == [] and pit_violations(_group(), "composite_score", None) == []


def test_nested_groups_formulas_and_other_kinds_are_checked():
    from src.engine.pit_fields import pit_violations
    nested = _group(_c("per", "lt", 10), groups=[{"logic": "OR", "conditions": [_c("return_12m")], "groups": []}])
    assert any("return_12m" in b for b in pit_violations(nested, None, None))
    formula = _group({"field": "__formula__", "kind": "formula", "formula": "(per*0.4)+(operating_margin*0.6)", "op": "gt", "value": 1})
    bad = pit_violations(formula, None, None)
    assert any("operating_margin" in b for b in bad) and not any("(per)" in b for b in bad)
    ok_formula = _group({"field": "__formula__", "kind": "formula", "formula": "(per*0.4)+(pbr*0.6)", "op": "gt", "value": 1})
    assert pit_violations(ok_formula, None, None) == []
    # 항목의 값이 아니라 오늘의 데이터로 문맥을 만드는 종류 — `field` 칸에 시점 가능한 이름이 적혀 있어도 막는다(종류로 판정한다).
    technical = _group({"field": "per", "kind": "technical", "indicator": "rsi_14", "op": "lt", "value": 30})
    assert pit_violations(technical, None, None) == ["조건 종류 ‘기술적 지표’"]


def test_sort_keys_are_checked():
    from src.engine.pit_fields import pit_violations
    assert any("정렬" in b and "return_12m" in b for b in pit_violations(None, "return_12m", None))
    assert any("정렬" in b and "roe" in b for b in pit_violations(None, "composite_score", "roe"))
    assert pit_violations(None, "composite_score", "roe_pct") == []


def test_the_message_is_screen_text():
    """화면에 그대로 실리는 문장이다 — 항목의 이름표를 쓰고, 개발자 낱말을 앞세우지 않는다."""
    from src.engine.pit_fields import PitFieldNotAvailable
    msg = str(PitFieldNotAvailable(["조건 ‘ROE’(roe)"]))
    assert "과거 시점" in msg and "‘ROE’" in msg and "그 시점 값" in msg
    assert not any(w in msg for w in ("look-ahead", "PIT", "as_of", "mock"))


# ── 2. run() — 한 곳에서 막는다 ────────────────────────────────────────────────

def test_a_past_date_run_with_a_factor_condition_is_refused_before_any_evaluation(monkeypatch, mem_snapshot):
    from src.engine.pit_fields import PitFieldNotAvailable
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    sc = _screener()
    evaluated = []
    monkeypatch.setattr(sc, "_evaluate_one_safe", lambda code, params: evaluated.append(code))
    with pytest.raises(PitFieldNotAvailable) as e:
        sc.run(universe=U, limit=10, liquidity_floor="off", as_of_date=ASOF, filter_ast=_group(_c("roe", "gt", 10)))
    assert evaluated == [] and "roe" in str(e.value)


def test_the_same_condition_runs_in_a_current_screening(monkeypatch, mem_snapshot):
    """★짝★ — 현재 스크리닝은 그대로다(같은 조건이 돈다)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _screener().run(universe=U, limit=10, liquidity_floor="off", filter_ast=_group(_c("roe", "gt", -1000)), sort_by="return_12m")
    assert r.total_evaluated == 3


def test_a_past_date_run_with_point_in_time_conditions_runs(monkeypatch, mem_snapshot):
    """★짝★ — 시점 값이 있는 항목의 조건·정렬은 과거 시점에서도 돈다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _screener().run(universe=U, limit=10, as_of_date=ASOF, filter_ast=_group(_c("roe_pct", "gt", -1000)),
                        sort_by="composite_score", sort_by_secondary="gap_pct")
    assert len(r.items) == 3


def test_a_past_date_sort_on_a_factor_is_refused(monkeypatch, mem_snapshot):
    from src.engine.pit_fields import PitFieldNotAvailable
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    with pytest.raises(PitFieldNotAvailable):
        _screener().run(universe=U, limit=10, as_of_date=ASOF, sort_by="momentum_12_1")
    with pytest.raises(PitFieldNotAvailable):
        _screener().run(universe=U, limit=10, as_of_date=ASOF, sort_by="composite_score", sort_by_secondary="return_3m")


def test_the_attach_step_never_changes_a_point_in_time_field(monkeypatch, mem_snapshot):
    """집합과 동작을 묶는다 — '시점 값이 있다'고 한 항목은 붙이기가 바꾸지 못한다(누가 붙이는 팩터를 그 집합에 넣으면 여기서 걸린다)."""
    from src.engine.pit_fields import PIT_CAPABLE_FIELDS
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    sc = _screener()
    seen: dict = {}
    orig = sc._evaluate_one_safe

    def ev(code, params):
        it = orig(code, params)
        if it is not None:
            seen[code] = {f: getattr(it, f, None) for f in PIT_CAPABLE_FIELDS}
        return it

    monkeypatch.setattr(sc, "_evaluate_one_safe", ev)
    r = sc.run(universe=U, limit=10, as_of_date=ASOF)
    assert len(r.items) == 3
    for it in r.items:
        assert {f: getattr(it, f, None) for f in PIT_CAPABLE_FIELDS} == seen[it.stock_code]


# ── 3. 유동성 게이트 — 과거 시점에는 적용하지 않고 그렇다고 말한다 ────────────────────

def test_the_liquidity_gate_is_not_applied_to_a_past_date_and_says_so(monkeypatch, mem_snapshot):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    sc = _screener()
    r = sc.run(universe="kospi50", limit=100, as_of_date=ASOF, liquidity_floor="institutional")
    gate = r.asof["liquidity_gate"]
    assert gate["applied"] is False and gate["reason"] == "asof_not_supported" and "과거 시점" in gate["note"]
    assert sc._liquidity_stats["applied"] is False and sc._liquidity_stats["filtered_out"] == 0
    assert r.total_passed == len(r.items) == r.evaluated_actual                 # 게이트가 아무도 빼지 않았다


def test_the_liquidity_gate_still_filters_a_current_screening(monkeypatch, mem_snapshot):
    """★짝★ — 현재 스크리닝의 게이트는 그대로 거른다(공허하지 않게: 기관 수준 문턱이 실제로 누군가를 뺀다)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    sc = _screener()
    r = sc.run(universe="kospi50", limit=100, liquidity_floor="institutional")
    assert sc._liquidity_stats["applied"] is True and sc._liquidity_stats["filtered_out"] > 0
    assert r.asof is None


# ── 4. 공시가 주지 않은 칸은 미상이다(부분 적용) ─────────────────────────────────

FILING = {"roe_pct": 7.7, "roa_pct": 4.4, "debt_ratio_pct": 40.0, "per": None, "pbr": None,
          "dividend_yield_pct": None, "fcf_억": None, "market_cap_억": None, "_source": "pit_dart"}


def _prod_world(monkeypatch, filing):
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    store = PITStore()
    monkeypatch.setattr(store, "_dart_snapshot", lambda *a, **k: dict(filing) if filing else None)
    monkeypatch.setattr(PITStore, "get_default", classmethod(lambda cls: store))
    monkeypatch.setattr(PITStore, "price_asof_detail", lambda self, code, asof, cur: (81500.0, dict(META), None))


def _item_with_todays_values():
    """평가 직후의 항목 — 여덟 칸에 ★오늘 재무로 계산한 값★이 들어 있다."""
    from src.engine.screener import ScreenerItem
    item = object.__new__(ScreenerItem)
    for k, v in {"roe_pct": 10.0, "roa_pct": 5.0, "per": 12.0, "pbr": 1.2, "debt_ratio_pct": 80.0,
                 "dividend_yield_pct": 2.0, "fcf_억": 1000.0, "market_cap_억": 50000.0}.items():
        setattr(item, k, v)
    item.fundamentals_is_mock = False
    return item


def test_fields_the_filing_does_not_give_are_unknown_not_todays_values(monkeypatch):
    from src.engine.screener import ValuationScreener
    _prod_world(monkeypatch, FILING)
    sc = object.__new__(ValuationScreener)
    out = sc._apply_pit_financials(_item_with_todays_values(), "005930", ASOF)
    assert (out.roe_pct, out.roa_pct, out.debt_ratio_pct) == (7.7, 4.4, 40.0)
    assert [out.per, out.pbr, out.dividend_yield_pct, out.fcf_억, out.market_cap_억] == [None] * 5
    assert out.asof_financials == {"available": True, "missing": ["per", "pbr", "dividend_yield_pct", "fcf_억", "market_cap_억"]}
    assert sc._asof_summary()["financials_partial"] == {
        "count": 1, "missing": {"per": 1, "pbr": 1, "dividend_yield_pct": 1, "fcf_억": 1, "market_cap_억": 1}}


def test_a_complete_filing_reports_nothing_partial(monkeypatch):
    """★짝★ — 공시가 여덟 칸을 다 주면 미상도 보고도 없다(늘 '부분'이라 하는 구현이 아니다)."""
    from src.engine.screener import ValuationScreener
    full = {**FILING, "per": 9.9, "pbr": 1.1, "dividend_yield_pct": 2.2, "fcf_억": 100.0, "market_cap_억": 4_000_000.0}
    _prod_world(monkeypatch, full)
    sc = object.__new__(ValuationScreener)
    out = sc._apply_pit_financials(_item_with_todays_values(), "005930", ASOF)
    assert out.per == 9.9 and not hasattr(out, "asof_financials")
    assert sc._asof_summary()["financials_partial"] == {"count": 0, "missing": {}}


def test_a_field_unknown_at_evaluation_is_not_counted_as_dropped(monkeypatch):
    """평가 때도 값이 없던 칸은 '오늘 값을 걷어 낸 것'이 아니다 — 세지 않는다(mock 의 시가총액이 그렇다)."""
    from src.engine.screener import ValuationScreener
    _prod_world(monkeypatch, FILING)
    item = _item_with_todays_values()
    item.market_cap_억 = None
    sc = object.__new__(ValuationScreener)
    out = sc._apply_pit_financials(item, "005930", ASOF)
    assert "market_cap_억" not in out.asof_financials["missing"]


# ── 5. 라우트 · 캔버스 노드 — 사유가 그대로 나온다 ──────────────────────────────────

def _pit_request(**over):
    import src.api.screener_routes as sr
    body = {"universe": "kospi50", "custom_tickers": U, "as_of_date": ASOF, "sort_by": "composite_score", "limit": 10,
            "filter_ast": {"logic": "AND", "conditions": [], "groups": []}}
    body.update(over)
    return sr.PITRunRequest(**body)


def test_the_past_date_route_answers_400_naming_the_fields(monkeypatch, mem_snapshot):
    from fastapi import HTTPException

    import src.api.screener_routes as sr
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(sr, "get_screener", _screener)
    with pytest.raises(HTTPException) as e:
        sr.screener_run_pit(_pit_request(filter_ast={"logic": "AND", "conditions": [_c("roe", "gt", 10)], "groups": []}))
    assert e.value.status_code == 400 and "‘ROE’" in e.value.detail and "과거 시점" in e.value.detail


def test_the_past_date_route_reports_the_gate_and_runs_point_in_time_conditions(monkeypatch, mem_snapshot):
    """★짝★ — 시점 값이 있는 조건은 돌고, 응답이 게이트를 적용하지 않았다고 말한다."""
    import src.api.screener_routes as sr
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(sr, "get_screener", _screener)
    out = sr.screener_run_pit(_pit_request(filter_ast={"logic": "AND", "conditions": [_c("roe_pct", "gt", -1000)], "groups": []}))
    assert len(out["items"]) == 3 and out["asof"]["liquidity_gate"]["applied"] is False


def test_every_canvas_preset_can_be_used_on_a_past_date():
    """캔버스 스크리닝 노드의 기본 조건은 과거 시점에서도 쓸 수 있다 — 고르자마자 거절되는 기본값을 두지 않는다."""
    from src.api import allocation_graph_nodes  # noqa: F401 — 노드 모듈은 등록부를 거쳐 불러야 한다(순환 임포트)
    from src.api.allocation_graph_nodes_signal import _presets_filter
    from src.engine.filter_ast import parse_group
    from src.engine.pit_fields import pit_violations
    presets = _presets_filter()
    assert len(presets) >= 4
    for p in presets:
        g = parse_group(p["value"])
        assert g.validate() is None, p["label"]
        assert pit_violations(g, "composite_score", None) == [], p["label"]


def test_the_canvas_node_fails_with_the_reason_on_a_factor_condition(monkeypatch, mem_snapshot):
    import src.api.allocation_graph_nodes_signal as sig
    import src.api.screener_routes as sr
    from src.api import allocation_graph_nodes  # noqa: F401
    from src.engine import portfolio_graph as pg
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(sr, "get_screener", _screener)
    p = sig.ScreenerParams(as_of=ASOF, filter_ast={"logic": "AND", "conditions": [_c("momentum_12_1", "gt", 0)], "groups": []})
    with pytest.raises(pg.NodeFailure) as e:
        sig._screener({"universe": {"tickers": U}}, p)
    assert "과거 시점" in str(e.value) and "momentum_12_1" in str(e.value)


def test_the_canvas_node_says_the_gate_was_not_applied(monkeypatch, mem_snapshot):
    import src.api.allocation_graph_nodes_signal as sig
    import src.api.screener_routes as sr
    from src.api import allocation_graph_nodes  # noqa: F401
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(sr, "get_screener", _screener)
    out = sig._screener({"universe": {"tickers": U}}, sig.ScreenerParams(as_of=ASOF, top_n=3))
    assert out.view["liquidity_gate"]["applied"] is False
    facts = sig._explain_screener(out.view, {}, None)["facts"]
    assert any("유동성 문턱" in f and "적용하지 않았습니다" in f for f in facts)


# ── 6. 백테스트의 시점 유니버스 — 후보 풀을 오늘 값으로 고르지 않는다 ─────────────────────

def _backtest(monkeypatch, **kw):
    import src.api.screener_routes as sr
    import src.engine.universe_select as us
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(sr, "get_screener", _screener)
    monkeypatch.setattr(us, "tickers_asof", lambda d: list(U))
    ran: list = []

    def fake_backtest(**k):
        ran.append(k)
        return {"error": False, "result": {"statistics": {}, "equity_curve": [], "equity_dates": [],
                                           "drawdown_curve": [], "monthly_returns": [], "trades": []}}

    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", fake_backtest)
    body = {"filter_ast": {"logic": "AND", "conditions": [], "groups": []}, "buy_conditions": None, "sell_conditions": None,
            "universe": "all_asof", "start_date": ASOF}
    body.update(kw)
    return sr._screen_to_backtest_core(sr.ScreenToBacktestRequest(**body)), ran


def test_a_point_in_time_universe_backtest_refuses_a_factor_condition(monkeypatch, mem_snapshot):
    """생존편향 보정 유니버스의 후보 풀을 오늘의 ROE 로 고르지 않는다 — 백테스트를 돌리지 않고 그 항목을 짚어 알린다."""
    out, ran = _backtest(monkeypatch, filter_ast={"logic": "AND", "conditions": [_c("roe", "gt", 10)], "groups": []})
    assert out["error"] is True and out["reason"] == "pit_field_not_available"
    assert "‘ROE’" in out["message"] and "과거 시점" in out["message"] and out["fields"]
    assert ran == []


def test_a_point_in_time_universe_backtest_refuses_a_factor_sort(monkeypatch, mem_snapshot):
    out, ran = _backtest(monkeypatch, sort_by="momentum_12_1")
    assert out.get("error") is True and out.get("reason") == "pit_field_not_available" and ran == []


def test_a_point_in_time_universe_backtest_runs_with_point_in_time_conditions(monkeypatch, mem_snapshot):
    """★짝★ — 시점 값이 있는 조건이면 돈다. 유니버스 메타가 게이트를 적용하지 않았다고 말한다."""
    out, ran = _backtest(monkeypatch, filter_ast={"logic": "AND", "conditions": [_c("roe_pct", "gt", -1000)], "groups": []},
                         liquidity_floor="institutional")
    assert out.get("reason") != "pit_field_not_available" and len(ran) == 1
    gate = out["universe"]["asof_screening"]["liquidity_gate"]
    assert gate["applied"] is False and gate["reason"] == "asof_not_supported"
    assert out["universe"]["tickers_screened"] == 3                     # 기관 수준 문턱이 과거 후보를 빼지 않았다


def test_a_todays_membership_backtest_still_takes_factor_conditions(monkeypatch, mem_snapshot):
    """★짝★ — 시점 유니버스가 아닌 백테스트(오늘의 구성 종목)는 그대로다. 같은 조건이 돈다."""
    out, ran = _backtest(monkeypatch, universe="kospi50", liquidity_floor="off",
                         filter_ast={"logic": "AND", "conditions": [_c("roe", "gt", -1000)], "groups": []})
    assert out.get("reason") != "pit_field_not_available" and len(ran) == 1
