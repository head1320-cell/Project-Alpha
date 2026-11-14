"""과거 시점(as_of) 평가의 재무 여덟 칸은 ★'붙이기' 단계를 지나도 그 시점 값★이다 (2026-11-13 — 감사 §11 · F6a).

2026-11-13 의 고침(감사 §10)은 `_apply_pit_financials` 까지만 봤다: 그 시점 공시의 값(또는 미상 `None` + 사유)을 항목에 싣는다.
그런데 `ValuationScreener.run` 은 평가 뒤에 펀더멘털·팩터를 ★붙이고★(`attach_fundamentals` 등), 그 단계가 여덟 칸 가운데 일부를
★오늘 값으로 덮어썼다★ — 재 보니(감사 §11):
  · `per` · `pbr` 은 늘(저장소의 팩터 id 가 기본 필드와 같은 이름이다 · mock 도)
  · `roe_pct` · `roa_pct` · `dividend_yield_pct` 는 저장소 출처가 실데이터(`dart_real`)일 때(기본 필드를 저장소 값에 맞추는 동기화)
그래서 '미상' 라벨(`asof_financials.available=False`)이 붙은 항목의 칸에 오늘 값이 들어 있었고, 그 칸에 건 조건이 오늘 값으로 걸렸다(룩어헤드).

이 파일은 `run()` 을 끝까지 돌려 본다(함수 하나만 떼어 보지 않는다 — 앞 시험이 그래서 놓쳤다).

★이 파일이 말하지 않는 것(F6 의 나머지 — 고치지 않았다)★ — 여덟 칸 밖의 조건 필드(펀더멘털·가격·확장 팩터)는 과거 시점 평가에서도
현재 값으로 붙는다(`test_the_other_factors_are_still_attached_with_todays_values` 가 그 사실을 적어 둔다). 읽은 공시에 없는 칸이
평가 때의 값으로 남는 '부분 적용'도 그대로다.
"""
from __future__ import annotations

import pytest

ASOF = "2024-06-28"
U = ["005930"]
EIGHT = ("roe_pct", "roa_pct", "per", "pbr", "debt_ratio_pct", "dividend_yield_pct", "fcf_억", "market_cap_억")
#: 저장소가 들고 있는 ★오늘★ 값 — 운영에서 DART 적재가 끝난 상태를 흉내 낸다(출처 `dart_real`).
TODAY = {"per": 30.0, "pbr": 3.0, "roe": 25.0, "roa": 15.0, "dividend_yield": 9.9, "operating_margin": 33.3, "_source": "dart_real"}
#: 그 시점 공시에서 읽은 값.
FILING = {"roe_pct": 7.7, "roa_pct": 4.4, "per": 9.9, "pbr": 1.1, "debt_ratio_pct": 40.0, "dividend_yield_pct": 2.2,
          "fcf_억": 100.0, "market_cap_억": 4_000_000.0, "_source": "pit_dart"}
META = {"trade_date": ASOF, "source": "krx", "price_basis": "raw"}


@pytest.fixture
def mem_snapshot(monkeypatch):
    import src.data.snapshot_db as sdb
    store: dict = {}
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: store[k] for k in keys if k in store})
    monkeypatch.setattr(sdb, "write_many", lambda payload: store.update(payload))
    return store


def _world(monkeypatch, *, mock: str, filing: dict | None, loaded_store: bool = True):
    """그 시점 종가는 적재돼 있고(81,500), 그 시점 공시는 `filing`(없으면 못 읽음), 펀더멘털 저장소는 오늘 값(`TODAY`)을 들고 있다."""
    import src.data.fundamentals_store as fs
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", mock)
    store = PITStore()
    monkeypatch.setattr(store, "_dart_snapshot", lambda *a, **k: dict(filing) if filing else None)
    monkeypatch.setattr(PITStore, "get_default", classmethod(lambda cls: store))
    monkeypatch.setattr(PITStore, "price_asof_detail", lambda self, code, asof, cur: (81500.0, dict(META), None))
    if loaded_store:
        monkeypatch.setattr(fs.FundamentalsStore, "get_factors", lambda self, code, item=None: dict(TODAY))
        monkeypatch.setattr(fs.FundamentalsStore, "prime", lambda self, keys: None)


def _run(as_of: str | None = ASOF, filter_ast=None):
    """`run()` 을 끝까지 — 평가 직후(붙이기 전)의 여덟 칸도 함께 돌려준다."""
    from src.engine.screener import ValuationScreener
    sc = ValuationScreener()
    evaluated: dict = {}
    orig = sc._evaluate_one_safe

    def ev(code, params):
        it = orig(code, params)
        if it is not None:
            evaluated[code] = {k: getattr(it, k, None) for k in EIGHT}
        return it

    sc._evaluate_one_safe = ev
    r = sc.run(universe=U, limit=10, liquidity_floor="off", as_of_date=as_of, filter_ast=filter_ast)
    return r, evaluated


def _eight(it) -> dict:
    return {k: getattr(it, k, None) for k in EIGHT}


def _where(field: str, op: str, value: float):
    from src.engine.filter_ast import parse_group
    return parse_group({"logic": "AND", "conditions": [{"field": field, "op": op, "value": value}], "groups": []})


# ── 운영: 그 시점 공시를 읽었다 ──────────────────────────────────────────────

def test_the_filing_values_survive_the_attach_step(monkeypatch, mem_snapshot):
    """읽은 공시의 값이 끝까지 간다 — 저장소의 오늘 값(ROE 25 · PER 30 …)으로 바뀌지 않는다."""
    _world(monkeypatch, mock="0", filing=FILING)
    r, _ = _run()
    assert len(r.items) == 1
    assert _eight(r.items[0]) == {k: FILING[k] for k in EIGHT}


def test_a_condition_on_a_pit_field_is_judged_by_the_filing_value_not_todays(monkeypatch, mem_snapshot):
    """★룩어헤드★ — 그 시점 ROE 는 7.7 이다. 'ROE > 20' 은 걸러야 하고(오늘 값 25 로 통과시키면 안 된다) ★짝★ 'ROE > 5' 는 통과한다."""
    _world(monkeypatch, mock="0", filing=FILING)
    high, _ = _run(filter_ast=_where("roe_pct", "gt", 20))
    low, _ = _run(filter_ast=_where("roe_pct", "gt", 5))
    assert [it.stock_code for it in high.items] == [] and [it.stock_code for it in low.items] == U


# ── 운영: 그 시점 공시를 못 읽었다 ────────────────────────────────────────────

def test_unknown_stays_unknown_through_the_attach_step(monkeypatch, mem_snapshot):
    """못 읽었으면 여덟 칸은 끝까지 미상이다 — '미상' 라벨이 붙은 항목의 칸에 오늘 값이 들어 있으면 안 된다(CLAUDE.md §4)."""
    _world(monkeypatch, mock="0", filing=None)
    r, _ = _run()
    it = r.items[0]
    assert _eight(it) == dict.fromkeys(EIGHT)
    assert it.to_dict()["asof_financials"]["available"] is False and it.to_dict()["asof_financials"]["reason"]
    assert r.asof["financials_unavailable"]["count"] == 1


def test_a_condition_on_an_unknown_field_does_not_pass_on_todays_value(monkeypatch, mem_snapshot):
    """미상인 칸에 건 조건은 그 종목을 통과시키지 않는다(감사 §10 '바뀌는 동작 ③' — 붙이기 때문에 사실이 아니었다)."""
    _world(monkeypatch, mock="0", filing=None)
    r, _ = _run(filter_ast=_where("per", "gt", 20))                 # 오늘 PER 30 이면 통과했다
    assert [it.stock_code for it in r.items] == []


# ── mock: 저장소를 흉내 내지 않고 실제 mock 저장소로 ─────────────────────────────

def test_mock_as_of_item_keeps_what_the_evaluation_set(monkeypatch, mem_snapshot):
    """mock 도 같다 — 붙이기가 여덟 칸을 바꾸지 않는다(예전엔 PER·PBR 이 저장소 값으로 바뀌었다)."""
    _world(monkeypatch, mock="1", filing=None, loaded_store=False)
    r, evaluated = _run()
    assert r.items and all(_eight(it) == evaluated[it.stock_code] for it in r.items)
    assert evaluated[U[0]]["per"] is not None and evaluated[U[0]]["pbr"] is not None      # 공허하지 않다 — 덮이던 두 칸에 값이 있다


# ── ★짝★ — 고침이 좁다 ────────────────────────────────────────────────────────

def test_a_current_run_still_syncs_the_base_fields_from_the_loaded_store(monkeypatch, mem_snapshot):
    """현재 스크리닝은 그대로다 — 기본 필드를 저장소의 실데이터 값에 맞춘다(헤더 PER 과 팩터 PER 이 어긋나던 문제의 고침을 되돌리지 않는다)."""
    _world(monkeypatch, mock="0", filing=FILING)
    r, _ = _run(as_of=None)
    it = r.items[0]
    assert (it.roe_pct, it.roa_pct, it.per, it.pbr, it.dividend_yield_pct) == (25.0, 15.0, 30.0, 3.0, 9.9)


def test_the_other_factors_are_still_attached_with_todays_values(monkeypatch, mem_snapshot):
    """★남은 것(F6)★ — 여덟 칸 밖의 팩터는 과거 시점 평가에서도 현재 값으로 붙는다. 이 시험은 그 사실을 적어 둔다(고치면 함께 바뀐다)."""
    _world(monkeypatch, mock="0", filing=FILING)
    r, _ = _run()
    assert r.items[0].operating_margin == 33.3
