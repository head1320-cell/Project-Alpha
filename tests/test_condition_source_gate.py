"""원천이 없는 조건 종류는 ★운영에서 계산하지 않는다★ — '이벤트' · 'Z-Score' (2026-11-14 · 합성값 전수 감사 §3)

## 무엇이 문제였나

스크리너 조건 종류 둘은 실데이터 원천이 없다 — 값이 전부 난수에서 나온다.

- `event` — `event_calendar._mock_event_date`: "실적 발표까지 N일"·"배당락까지 N일"을 종목 코드에서 뽑은 난수로.
- `z_score` — `z_score.compute_rolling_stats`: 종목의 '과거 20분기 분포'를 난수로 만들어 평균·표준편차·Z 를 계산.

둘 다 게이트가 없었다. 관측(운영 게이트): `get_events("005930")` → 실적 발표 56일 뒤 · 배당락 173일 뒤(`_source: "mock"`),
`compute_rolling_stats("005930", "per", 20, 12.3, {})` → 평균 13.51 · 표준편차 2.306 · Z −0.525.
운영의 스크리너가 "PER 이 자기 5년 평균 대비 −1σ" 를 난수로 판정했다(그 조건을 쓰는 프리셋도 있다).

## 이 파일이 거는 계약 — 두 층

원천 층: ① 운영에서는 값을 만들지 않는다(미상 + 사유 · 생성기는 불리지 않는다) ② mock 에서는 그대로(짝).
요청 층: ③ 운영에서 그 조건을 쓴 요청은 ★계산하지 않고 그 조건을 짚어 사유를 낸다★(조용히 '통과 0건'으로 만들지 않는다 —
과거 시점 선별의 선례와 같다) ④ mock 에서는 통과(짝) ⑤ 다른 조건 종류는 영향받지 않는다(짝).
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.data.event_calendar as ec
import src.engine.z_score as zs
from src.engine.condition_sources import (
    UNSOURCED_KINDS,
    ConditionSourceUnavailable,
    unsourced_conditions,
    unsourced_reason,
)
from src.engine.filter_ast import FilterCondition, FilterGroup, apply_filter_ast

CODE = "005930"
EVENT = dict(field="__e__", kind="event", event_type="earnings", within_days=365)
ZSCORE = dict(field="__z__", kind="z_score", z_field="per", z_window=20, op="lt", value=99.0)
FIELD = dict(field="per", op="lt", value=1_000.0)


def _prod(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")


def _mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")


def _items(n: int = 5) -> list:
    return [SimpleNamespace(stock_code=f"00{i:04d}", per=10.0 + i, roe_pct=8.0, roa_pct=3.0, pbr=1.0, debt_ratio_pct=50.0,
                            dividend_yield_pct=2.0, fcf_억=100.0, market_cap_억=1_000.0) for i in range(n)]


def _group(*conds: dict, logic: str = "AND", groups: list | None = None) -> FilterGroup:
    return FilterGroup(logic=logic, conditions=[FilterCondition(**c) for c in conds], groups=groups or [])


# ══ 원천 층 — 이벤트 ══════════════════════════════════════════════════════════

def test_prod_event_calendar_knows_nothing_and_says_why(monkeypatch):
    _prod(monkeypatch)
    made: list = []
    real = ec._mock_event_date
    monkeypatch.setattr(ec, "_mock_event_date", lambda *a: made.append(a) or real(*a))
    cal = ec.EventCalendar()
    assert cal.days_until(CODE, "earnings") is None and cal.days_until(CODE, "ex_dividend") is None
    out = cal.get_events(CODE)
    assert out["earnings_days"] is None and out["ex_dividend_days"] is None
    assert out["_source"] == "unavailable" and out["_reason"]
    assert made == [], "운영에서 이벤트 일자 생성기를 불렀다"


def test_mock_event_calendar_still_answers_and_is_labelled(monkeypatch):
    _mock(monkeypatch)
    out = ec.EventCalendar().get_events(CODE)
    assert 0 <= out["earnings_days"] <= 90 and 0 <= out["ex_dividend_days"] <= 180
    assert out["_source"] == "mock" and "_reason" not in out


def test_an_unknown_event_type_is_unknown_in_both_modes(monkeypatch):
    for setter in (_prod, _mock):
        setter(monkeypatch)
        assert ec.EventCalendar().days_until(CODE, "merger") is None


# ══ 원천 층 — Z-Score ═════════════════════════════════════════════════════════

def test_prod_rolling_stats_are_unknown_and_nothing_is_drawn(monkeypatch):
    _prod(monkeypatch)
    drawn: list = []
    real = random.Random

    class Spy(real):
        def __init__(self, *a, **k):
            drawn.append(a)
            super().__init__(*a, **k)

    monkeypatch.setattr(random, "Random", Spy)
    assert zs.compute_rolling_stats(CODE, "per", 20, 12.3, {}) is None
    assert drawn == [], "운영에서 과거 분포를 난수로 뽑았다"


def test_mock_rolling_stats_still_come_out(monkeypatch):
    _mock(monkeypatch)
    out = zs.compute_rolling_stats(CODE, "per", 20, 12.3, {})
    assert out and out["n"] == 20 and out["std"] > 0 and isinstance(out["z"], float)


def test_prod_z_context_is_empty_so_no_stock_passes_on_a_fabricated_z(monkeypatch):
    """요청 층을 지나치는 호출자가 있어도(직접 문맥을 만드는 경우) 판정 재료가 없어야 한다."""
    _prod(monkeypatch)
    ctx = zs.build_z_score_context(_group(ZSCORE), _items()).get("_zscore", {})
    assert ctx == {}


# ══ 요청 층 — 검증 ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cond,label", [(EVENT, "이벤트"), (ZSCORE, "Z-Score")])
def test_prod_validation_refuses_the_condition_and_names_it(monkeypatch, cond, label):
    _prod(monkeypatch)
    err = FilterCondition(**cond).validate()
    assert err and label in err and "원천" in err


@pytest.mark.parametrize("cond", [EVENT, ZSCORE])
def test_mock_validation_accepts_the_condition(monkeypatch, cond):
    _mock(monkeypatch)
    assert FilterCondition(**cond).validate() is None


def test_prod_validation_leaves_other_kinds_alone(monkeypatch):
    """짝 — 운영이면 무엇이든 거절하는 구현을 배제한다."""
    _prod(monkeypatch)
    assert FilterCondition(**FIELD).validate() is None
    assert FilterCondition(field="__t__", kind="technical", indicator="rsi_14", op="lt", value=30.0).validate() is None
    assert unsourced_reason("field") is None and unsourced_reason("technical") is None


def test_a_malformed_condition_is_still_reported_as_malformed(monkeypatch):
    """모양이 틀린 조건에 '원천이 없다'고 답하면 고칠 곳을 잘못 알려 준다."""
    _prod(monkeypatch)
    err = FilterCondition(field="__e__", kind="event", event_type="merger", within_days=5).validate()
    assert err and "event_type" in err


def test_nested_groups_are_checked(monkeypatch):
    _prod(monkeypatch)
    g = _group(FIELD, groups=[_group(FIELD, groups=[_group(EVENT)])])
    assert g.validate() and "이벤트" in g.validate()
    assert len(unsourced_conditions(g)) == 1


def test_the_table_lists_exactly_the_kinds_without_a_source():
    """원천을 붙이면 이 표에서 지운다 — 표가 바뀌면 이 시험도 함께 본다."""
    assert set(UNSOURCED_KINDS) == {"event", "z_score"}


# ══ 요청 층 — 필터 적용 ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("cond,label", [(EVENT, "이벤트"), (ZSCORE, "Z-Score")])
def test_prod_filter_refuses_instead_of_returning_nothing(monkeypatch, cond, label):
    _prod(monkeypatch)
    with pytest.raises(ConditionSourceUnavailable) as e:
        apply_filter_ast(_items(), _group(cond))
    assert label in str(e.value)


def test_prod_filter_refuses_even_when_another_branch_could_pass(monkeypatch):
    """OR 로 묶였다고 그 조건만 조용히 빼면 사용자가 건 조건과 다른 결과가 나간다."""
    _prod(monkeypatch)
    with pytest.raises(ConditionSourceUnavailable):
        apply_filter_ast(_items(), _group(FIELD, EVENT, logic="OR"))


def test_prod_filter_still_runs_plain_conditions(monkeypatch):
    _prod(monkeypatch)
    items = _items()
    assert apply_filter_ast(items, _group(FIELD)) == items
    assert apply_filter_ast(items, _group(dict(field="per", op="lt", value=12.5))) == items[:3]


@pytest.mark.parametrize("cond", [EVENT, ZSCORE])
def test_mock_filter_evaluates_the_condition(monkeypatch, cond):
    """짝 — mock 에서는 예전처럼 계산된다(넓은 문턱이라 전부 통과)."""
    _mock(monkeypatch)
    items = _items()
    assert apply_filter_ast(items, _group(cond)) == items


# ══ 진입점 — 평가 전에 거절한다 ═══════════════════════════════════════════════

def test_the_screener_refuses_before_touching_the_universe(monkeypatch):
    from src.engine.screener import ValuationScreener
    _prod(monkeypatch)
    sc = ValuationScreener.__new__(ValuationScreener)
    touched: list = []
    monkeypatch.setattr(ValuationScreener, "_resolve_universe", lambda self, u: touched.append(u) or [])
    with pytest.raises(ConditionSourceUnavailable):
        sc.run(universe="kospi50", filter_ast=_group(ZSCORE))
    assert touched == [], "거절할 요청인데 유니버스를 먼저 풀었다"


@pytest.fixture
def client():
    from src.api import screener_routes
    app = FastAPI()
    app.include_router(screener_routes.router)
    return TestClient(app)


def test_the_preset_that_uses_z_score_answers_with_the_reason_in_prod(client, monkeypatch):
    """프리셋 실행 라우트는 검증을 거치지 않는다 — 그래도 뭉뚱그린 500 이 아니라 사유가 나가야 한다."""
    _prod(monkeypatch)
    r = client.post("/api/v1/screener/presets/v3_historical_value/run", json={})
    assert r.status_code == 400, r.text[:200]
    assert "Z-Score" in r.json()["detail"] and "원천" in r.json()["detail"]


def test_screen_to_backtest_reports_the_refusal_and_runs_nothing(monkeypatch):
    """후보 풀을 지어낸 값으로 고른 백테스트는 돌지 않는다 — 오류 블록에 사유가 실린다(검증을 거치지 않는 경로다)."""
    from src.api import screener_routes as sr
    from src.engine.screener import ValuationScreener
    _prod(monkeypatch)
    ran: list = []
    monkeypatch.setattr(sr, "get_screener", lambda: ValuationScreener.__new__(ValuationScreener))
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", lambda **k: ran.append(k) or {"error": False, "result": {}})
    req = sr.ScreenToBacktestRequest(buy_conditions=None, sell_conditions=None, filter_ast={
        "logic": "AND", "groups": [], "conditions": [dict(ZSCORE)]})
    out = sr._screen_to_backtest_core(req)
    assert out["error"] is True and out["reason"] == "condition_source_unavailable"
    assert "Z-Score" in out["message"] and out["screened_count"] == 0
    assert ran == [], "거절한 요청인데 백테스트를 돌렸다"
