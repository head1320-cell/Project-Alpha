"""운영 스크리너는 ★합성 바탕 가격을 쓰지 않는다★ (2026-11-21 · 감사 F3 · 사용자 결정 3 → 1)
================================================================================================
고치기 전: 운영(`KIS_USE_MOCK≠"1"`)의 기본 가격 공급자는 `_mock_price` → `ohlcv_loader.mock_price_level`(고정 표 · 표 밖은
`10,000 + (해시×137) % 200,000`)이었다. 실시세 보강(`_enrich_kis_quotes`)만 그것을 덮었고 — 키 없음 · KIS 실패 · 0 이하 시세 ·
상한 밖 · 복원(`item:`) 행은 합성 가격과 그 파생값(괴리율 · 판정 · 종합 점수 · PER · PBR · 배당수익률)을 그대로 실었다.

받은 결정: 실시세 → 적재 일봉 종가(출처 라벨) → 없으면 ★행은 남기고★ 가격 파생 칸은 미상 + 사유. 복원 행은 매번 적재 종가로 다시 매긴다.

계약 — 운영의 현재 스크리닝에서 모든 행은:
  · 합성 가격을 싣지 않는다 — 바탕값 함수(`mock_price_level`)를 ★부르지도 않는다★(부르면 터지게 해 둔다).
  · 가격이 있으면 출처가 있다(`price_source` — kis_live · daily_close(날짜·출처·가격 기준) · provider). 없으면 가격 파생 칸이 모두
    미상이고(판정 "시세 없음") 사유 둘이 있다(`price_unavailable` — 실시세 · 적재 종가).
  · 가격과 무관한 칸(적정가 · 재무 · ROE·안정성 점수)은 가격이 있든 없든 같다 — 평가를 통째로 버리지 않는다.
  · 결과에 출처별 수와 사유별 수가 실린다(`ScreenerResult.prices`).
★짝★ mock 은 한 자리도 바뀌지 않는다(`tests/test_screener_mock_golden.py` 가 얼렸다 — 여기서는 새 라벨이 mock 에 새지 않는 것만).

가짜: DART 재무 한 벌(진짜 `ValuationEngine` 을 탄다) · `universe_select.close_asof`(적재 종가) · KIS 클라이언트 · 영속 캐시(메모리) ·
펀더멘털·가격·확장 저장소(빈 값 — 붙이기가 칸을 되채우는 경우는 따로 본다).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from src.data.dart_client import FinancialStatement
from src.engine.screener import (
    PRICE_DERIVED_FIELDS,
    ScreenerFilters,
    ScreenerItem,
    ValuationScreener,
    sort_screener_items,
)
from src.engine.universe_select import close_asof as REAL_CLOSE_ASOF  # 고정 전에 잡아 둔다(아래 끝단 시험)
from src.engine.valuation.valuation_models import ValuationEngine, compute_gap_pct, gap_pct_to_verdict

U = ["005930", "000660", "123456"]
FS = FinancialStatement(
    corp_code="00126380", corp_name="테스트전자", bsns_year="2025", reprt_code="11011",
    revenue=300e12, operating_profit=35e12, net_income=28e12,
    total_assets=450e12, total_liabilities=100e12, total_equity=350e12,
    operating_cf=60e12, capex=45e12, shares_outstanding=5_969_782_550, dps=1444,
)
#: 가격과 무관한 칸 — 가격이 없어도 있을 때와 같아야 한다.
PRICE_FREE = ("intrinsic_value", "rim_value", "dcf_value", "ddm_value", "roe_pct", "roa_pct", "debt_ratio_pct", "fcf_억",
              "roe_score", "stability_score", "fundamentals_is_mock", "corp_name")


def _close(px: float, day: str = "2026-11-20", source: str = "krx", basis: str | None = "raw"):
    return {"close": px, "trade_date": day, "source": source, "price_basis": basis}, None


class _FakeDart:
    def get_financial_statement_full(self, corp_code, bsns_year):
        return copy.deepcopy(FS)

    def get_corp_info(self, corp_code):
        return None


class _Kis:
    """KIS 실시세 흉내 — 종목마다 시세 dict · 예외 · 없음(빈 dict). 이름이 `MockKISClient` 가 아니어야 보강이 돈다."""

    def __init__(self, quotes: dict):
        self.quotes = quotes
        self.calls: list[str] = []

    def get_price(self, code):
        self.calls.append(code)
        q = self.quotes.get(code, {})
        if isinstance(q, Exception):
            raise q
        return dict(q)


class _World:
    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.closes: dict = {}
        self.close_calls: list = []
        self.mem: dict = {}
        self.base_calls: list = []

    def kis(self, client):
        self.mp.setattr("src.execution.kis_client.get_kis_client", lambda *a, **k: client)
        return client

    def store(self, item: ScreenerItem):
        self.mem[f"item:{item.stock_code}"] = json.loads(json.dumps(item.to_dict(), default=str))


@pytest.fixture
def world(monkeypatch):
    """운영 게이트 · KIS 키 없음 · 적재 종가 없음(기본) · 저장소 빈 값 · 영속 캐시 메모리 · ★바탕값 함수는 부르면 기록된다★."""
    import src.data.extended_factors_store as xs
    import src.data.fundamentals_store as fs
    import src.data.ohlcv_loader as ol
    import src.data.price_factors_store as pfs
    import src.data.snapshot_db as sdb
    import src.engine.universe_select as us
    import src.execution.kis_client as kc
    w = _World(monkeypatch)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "DART_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None)

    def boom(code):
        w.base_calls.append(code)
        raise AssertionError(f"운영에서 합성 바탕값을 불렀다 ({code})")
    monkeypatch.setattr(ol, "mock_price_level", boom)

    def close_asof(t, d, engine=None):
        w.close_calls.append((t, d))
        return w.closes.get(t, (None, "not_loaded"))
    monkeypatch.setattr(us, "close_asof", close_asof)
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: copy.deepcopy(w.mem[k]) for k in keys if k in w.mem})
    monkeypatch.setattr(sdb, "write_many", lambda payload: w.mem.update(json.loads(json.dumps(payload, default=str))))
    for cls in (fs.FundamentalsStore, pfs.PriceFactorsStore, xs.ExtendedFactorsStore):
        monkeypatch.setattr(cls, "prime", lambda self, keys: None)
        monkeypatch.setattr(cls, "get_factors", lambda self, code, item=None, **kw: {})
    return w


def _run(universe=U, **kw):
    sc = ValuationScreener(dart_client=_FakeDart())
    return sc.run(universe=universe, limit=50, liquidity_floor="off", **kw)


def _by_code(result) -> dict:
    return {it.stock_code: it for it in result.items}


def _eval(price):
    return ValuationEngine(_FakeDart()).evaluate("005930", price)


def _unknown(it) -> bool:
    return all(getattr(it, f) is None for f in PRICE_DERIVED_FIELDS if f != "verdict") and it.verdict == "시세 없음"


# ── A. 키 없음 · 적재 종가 없음 ─────────────────────────────────────────────────────────────────────
def test_without_a_key_or_a_loaded_close_every_row_stays_with_an_unknown_price(world):
    r = _run()
    rows = _by_code(r)
    assert sorted(rows) == sorted(U), "가격이 없다고 행을 빼지 않는다(결정 3 → 1)"
    for it in rows.values():
        assert _unknown(it), {f: getattr(it, f) for f in PRICE_DERIVED_FIELDS}
        assert it.price_unavailable == {"live": "kis_credentials_missing", "close": "not_loaded"}
        assert it.price_source is None
        assert it.price_is_mock is False                      # 합성이 없다 — 없는 것은 합성이 아니다
        d = it.to_dict()
        assert d["price_unavailable"] == it.price_unavailable and d["price_source"] is None
    assert world.base_calls == [], "운영에서 합성 바탕값 함수를 불렀다"
    assert r.failures == 0
    assert r.prices == {"by_source": {"kis_live": 0, "daily_close": 0, "provider": 0, "unavailable": 3},
                        "unavailable": {"count": 3,
                                        "by_reason": {"live": {"kis_credentials_missing": 3}, "close": {"not_loaded": 3}},
                                        "sample": [{"code": c, "live": "kis_credentials_missing", "close": "not_loaded"}
                                                   for c in sorted(U)]}}


def test_without_a_price_the_price_free_fields_are_what_a_priced_row_has(world):
    """★짝★ 가격이 없어도 적정가·재무·ROE·안정성 점수는 있다 — 가격이 있는 같은 종목의 값과 같다."""
    world.closes = {"005930": _close(70_000.0)}
    rows = _by_code(_run(universe=["005930", "000660"]))
    priced, unpriced = rows["005930"], rows["000660"]
    assert priced.current_price == 70_000.0 and unpriced.current_price is None
    for f in PRICE_FREE:
        if f == "corp_name":
            continue
        assert getattr(unpriced, f) == getattr(priced, f), f
    assert unpriced.intrinsic_value > 0 and unpriced.roe_pct and unpriced.roe_score > 0   # 공허하지 않다


def test_the_close_is_read_for_today(world):
    _run(universe=["005930"])
    assert world.close_calls == [("005930", datetime.now().strftime("%Y-%m-%d"))]


# ── B. 적재 종가 ───────────────────────────────────────────────────────────────────────────────────
def test_a_loaded_close_prices_the_row_and_carries_its_source(world):
    world.closes = {"005930": _close(70_000.0), "000660": _close(90_000.0, source="kis", basis="adjusted"),
                    "123456": (None, "stale")}
    rows = _by_code(_run())
    a = rows["005930"]
    want = _eval(70_000.0)
    assert a.current_price == 70_000.0
    assert (a.gap_pct, a.verdict) == (want.gap_pct, want.verdict)
    assert (a.per, a.pbr, a.dividend_yield_pct) == (want.financial_summary["per"], want.financial_summary["pbr"],
                                                     want.financial_summary["dividend_yield_pct"])
    assert a.composite_score is not None and a.gap_score is not None
    assert a.price_source == {"kind": "daily_close", "trade_date": "2026-11-20", "source": "krx", "price_basis": "raw",
                              "live": "kis_credentials_missing"}
    assert a.price_unavailable is None
    # 가격 기준은 바꾸지 않고 그대로 싣는다(결정: 아무 기준이나 받고 라벨)
    assert rows["000660"].current_price == 90_000.0
    assert rows["000660"].price_source["price_basis"] == "adjusted" and rows["000660"].price_source["source"] == "kis"
    # ★짝★ 낡은 봉은 가격이 아니다 — 미상 + 그 사유(not_loaded 와 뭉개지 않는다)
    assert _unknown(rows["123456"]) and rows["123456"].price_unavailable["close"] == "stale"


def test_a_store_error_is_not_reported_as_not_loaded(world):
    """★짝★ DB 를 못 읽은 것은 '적재 안 됨'이 아니다 — 사유를 뭉개지 않는다."""
    world.closes = {"005930": (None, "store_error")}
    r = _run(universe=["005930", "000660"])
    rows = _by_code(r)
    assert rows["005930"].price_unavailable["close"] == "store_error"
    assert rows["000660"].price_unavailable["close"] == "not_loaded"
    assert r.prices["unavailable"]["by_reason"]["close"] == {"store_error": 1, "not_loaded": 1}


# ── C. KIS 가 일부 종목에서 실패 ─────────────────────────────────────────────────────────────────────
def test_kis_failures_fall_back_row_by_row_and_say_why(world):
    world.closes = {"005930": _close(70_000.0), "123456": _close(70_000.0)}
    kis = world.kis(_Kis({"005930": RuntimeError("timeout"), "000660": {"current_price": 0},
                          "123456": {"current_price": 90_000.0, "per": 11.0, "pbr": 1.5}}))
    r = _run()
    rows = _by_code(r)
    # 예외 → 적재 종가로 남고 실시세 사유를 적는다
    assert rows["005930"].current_price == 70_000.0
    assert rows["005930"].price_source["kind"] == "daily_close" and rows["005930"].price_source["live"] == "kis_error"
    # 0 이하 시세 → 적재 종가도 없으면 미상 + 사유 둘
    assert _unknown(rows["000660"])
    assert rows["000660"].price_unavailable == {"live": "kis_nonpositive", "close": "not_loaded"}
    # ★짝★ 실시세가 있으면 적재 종가보다 앞선다 — 괴리율·판정·점수는 실시세로 다시 낸다
    z = rows["123456"]
    assert z.current_price == 90_000.0
    assert z.price_source["kind"] == "kis_live" and isinstance(z.price_source["fetched_at"], str)
    assert z.gap_pct == round(compute_gap_pct(90_000.0, z.intrinsic_value), 2)
    assert z.verdict == gap_pct_to_verdict(z.gap_pct)
    assert (z.per, z.pbr) == (11.0, 1.5)
    assert sorted(kis.calls) == sorted(U)
    assert r.prices["by_source"] == {"kis_live": 1, "daily_close": 1, "provider": 0, "unavailable": 1}


def test_a_mock_kis_client_in_production_is_named_as_such(world):
    class MockKISClient:      # noqa: N801 — 이름으로 거른다(`_enrich_kis_quotes`)
        def get_price(self, code):
            raise AssertionError("mock 클라이언트를 부르지 않는다")
    world.kis(MockKISClient())
    it = _by_code(_run(universe=["005930"]))["005930"]
    assert it.price_unavailable == {"live": "kis_mock_client", "close": "not_loaded"}


# ── D. 실시세 상한 밖 ─────────────────────────────────────────────────────────────────────────────────
def test_rows_past_the_live_cap_are_not_quoted_and_say_so(world, monkeypatch):
    """적재 배치(`no_cap`)는 평가 상한이 없지만 실시세 보강에는 상한이 있다 — 상한 밖 행은 합성이 아니라 적재 종가 또는 미상 + 사유."""
    monkeypatch.setenv("SCREENER_MAX_LIVE_COMPUTE", "2")
    world.closes = {c: _close(70_000.0) for c in U}
    kis = world.kis(_Kis({c: {"current_price": 90_000.0} for c in U}))
    rows = _by_code(_run(no_cap=True))
    kinds = sorted(it.price_source["kind"] for it in rows.values())
    assert kinds == ["daily_close", "kis_live", "kis_live"]
    over = [it for it in rows.values() if it.price_source["kind"] == "daily_close"]
    assert over[0].price_source["live"] == "over_live_cap" and over[0].current_price == 70_000.0
    assert len(kis.calls) == 2                                  # ★짝★ 상한 안의 두 행만 불렀다


def test_the_evaluation_cap_does_not_invent_rows(world, monkeypatch):
    """평가 상한(요청 경로)에 걸린 종목은 결과에 없다 — `capped` 로 말한다(예전 그대로 · 가격을 지어 넣지 않는다)."""
    monkeypatch.setenv("SCREENER_MAX_LIVE_COMPUTE", "2")
    r = _run()
    assert r.capped is True and len(r.items) == 2
    assert all(_unknown(it) for it in r.items)


# ── E. 복원(item:) 행 ─────────────────────────────────────────────────────────────────────────────
def _legacy(code: str, price: float = 71_000.0) -> ScreenerItem:
    """고치기 전에 저장된 행 — 합성 가격 · 그 가격의 파생값 · 라벨 키 없음."""
    return ScreenerItem(stock_code=code, corp_name="옛 행", sector=None, current_price=price, intrinsic_value=100_000.0,
                        gap_pct=-29.0, verdict="저평가", composite_score=70.0, gap_score=79.0, roe_score=26.6,
                        stability_score=65.0, roe_pct=8.0, roa_pct=6.2, per=12.0, pbr=1.2, debt_ratio_pct=28.6,
                        dividend_yield_pct=2.0, market_cap_억=None, fcf_억=150_000.0)


def test_a_restored_legacy_row_is_repriced_and_its_synthetic_derivatives_dropped(world):
    world.store(_legacy("005930"))
    world.store(_legacy("000660"))
    world.closes = {"005930": _close(80_000.0)}
    kis = world.kis(_Kis({}))
    r = _run(universe=["005930", "000660"])
    rows = _by_code(r)
    a = rows["005930"]
    assert r.cache_misses == 0, "복원 경로를 보지 못했다"
    assert a.current_price == 80_000.0
    assert a.gap_pct == round(compute_gap_pct(80_000.0, 100_000.0), 2) and a.verdict == gap_pct_to_verdict(a.gap_pct)
    assert a.price_source["kind"] == "daily_close" and a.price_source["live"] == "restored_not_requoted"
    assert (a.per, a.pbr, a.dividend_yield_pct) == (None, None, None), "옛 행의 PER·PBR·배당은 합성 가격에서 나왔을 수 있다"
    assert a.price_is_mock is False
    b = rows["000660"]
    assert _unknown(b) and b.price_unavailable == {"live": "restored_not_requoted", "close": "not_loaded"}
    assert (b.roe_score, b.stability_score, b.roe_pct) == (26.6, 65.0, 8.0)   # 가격과 무관한 칸은 남는다
    assert kis.calls == [], "복원 행에는 실시세를 부르지 않는다(KIS 호출량은 예전 그대로)"


def test_a_row_stored_after_the_fix_keeps_its_ratios(world):
    """★짝★ 고친 뒤 저장된 행(라벨이 있다)의 PER·PBR·배당은 확인된 가격·실시세·저장소에서 나왔다 — 지우지 않는다(가격만 다시 매긴다)."""
    it = _legacy("005930")
    it.price_is_mock = False
    it.price_source = {"kind": "daily_close", "trade_date": "2026-11-19", "source": "krx", "price_basis": "raw",
                       "live": "kis_credentials_missing"}
    it.price_unavailable = None
    world.store(it)
    world.closes = {"005930": _close(80_000.0)}
    a = _by_code(_run(universe=["005930"]))["005930"]
    assert (a.per, a.pbr, a.dividend_yield_pct) == (12.0, 1.2, 2.0)
    assert a.current_price == 80_000.0 and a.price_source["trade_date"] == "2026-11-20"


def test_a_fresh_row_is_still_quoted_next_to_restored_rows(world):
    """★짝★ 복원 행을 실시세에서 뺀 것이 새로 평가한 행까지 빼지는 않는다."""
    world.store(_legacy("005930"))
    kis = world.kis(_Kis({"000660": {"current_price": 90_000.0}}))
    rows = _by_code(_run(universe=["005930", "000660"]))
    assert kis.calls == ["000660"]
    assert rows["000660"].price_source["kind"] == "kis_live"


def test_in_mock_mode_a_restored_row_is_unchanged(monkeypatch):
    """★짝★ mock 은 예전 그대로 — 복원 행을 다시 매기지 않고 라벨도 달지 않는다."""
    import src.data.snapshot_db as sdb
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    mem = {"item:005930": json.loads(json.dumps(_legacy("005930").to_dict()))}
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: copy.deepcopy(mem[k]) for k in keys if k in mem})
    monkeypatch.setattr(sdb, "write_many", lambda payload: None)
    r = ValuationScreener(dart_client=_FakeDart()).run(universe=["005930"], limit=5, liquidity_floor="off")
    it = r.items[0]
    assert (it.current_price, it.per, it.gap_pct, it.price_is_mock) == (71_000.0, 12.0, -29.0, True)
    assert "price_source" not in it.to_dict() and "price_unavailable" not in it.to_dict()
    assert r.prices is None


# ── F. mock 은 라벨이 없다(모양 그대로) ───────────────────────────────────────────────────────────────
def test_mock_rows_carry_no_price_labels(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("SNAPSHOT_DB", "0")
    r = ValuationScreener(dart_client=_FakeDart()).run(universe=U, limit=5, liquidity_floor="off")
    assert r.prices is None and len(r.items) == 3
    for it in r.items:
        assert it.price_is_mock is True and it.current_price and it.current_price > 0
        assert not {"price_source", "price_unavailable"} & set(it.to_dict())


# ── G. 점수 ─────────────────────────────────────────────────────────────────────────────────────────
def test_an_unknown_gap_has_no_gap_or_composite_score():
    sc = ValuationScreener(dart_client=_FakeDart())
    fin = {"roe_pct": 15.0, "debt_ratio_pct": 40.0, "fcf_억": 100.0}
    composite, gap, roe_s, stab = sc._compute_scores(None, fin)
    assert (composite, gap) == (None, None)
    assert (roe_s, stab) == sc._compute_scores(10.0, fin)[2:]          # 가격과 무관한 점수는 그대로


def test_a_zero_gap_still_scores_as_before():
    """★짝★ 괴리율 0(적정가 0 의 정의)은 예전 그대로 50점 · 종합 38.0 — F7 은 이 변경의 범위 밖이다."""
    sc = ValuationScreener(dart_client=_FakeDart())
    assert sc._compute_scores(0.0, {}) == (38.0, 50.0, 0.0, 40.0)


# ── H. 집합과 동작을 묶는다 · 가격 적용의 경로 무관성 ───────────────────────────────────────────────────
def _item_at(price) -> ScreenerItem:
    sc = ValuationScreener(dart_client=_FakeDart())
    return sc._to_item(ValuationEngine(_FakeDart()).evaluate("005930", price), "005930")


def test_exactly_the_registered_fields_move_with_the_price(monkeypatch):
    """두 가격으로 평가해 ★달라지는 항목 칸★이 정확히 `PRICE_DERIVED_FIELDS` 다 — 가격에 기대는 칸이 새로 생기면 여기서 짚힌다."""
    monkeypatch.setenv("SNAPSHOT_DB", "0")
    import dataclasses
    a, b = _item_at(50_000.0), _item_at(90_000.0)
    moved = {f.name for f in dataclasses.fields(ScreenerItem) if getattr(a, f.name) != getattr(b, f.name)}
    assert moved == set(PRICE_DERIVED_FIELDS)
    none = _item_at(None)
    assert _unknown(none)
    assert {f: getattr(none, f) for f in PRICE_FREE} == {f: getattr(a, f) for f in PRICE_FREE}


def test_applying_a_price_later_does_not_depend_on_how_the_row_was_evaluated(monkeypatch):
    """가격 없이 평가한 행에 가격 P 를 적용한 것 = 다른 가격으로 평가한 행에 P 를 적용한 것(정확히) ≈ P 로 평가한 것(괴리율은 반올림한
    적정가로 다시 내므로 0.01 안 — 실시세 보강이 예전부터 쓰던 산수다)."""
    monkeypatch.setenv("SNAPSHOT_DB", "0")
    sc = ValuationScreener(dart_client=_FakeDart())
    keys = ("current_price", "gap_pct", "verdict", "gap_score", "composite_score", "roe_score", "stability_score")
    x, y, z = _item_at(None), _item_at(50_000.0), _item_at(80_000.0)
    sc._apply_price(x, 80_000.0)
    sc._apply_price(y, 80_000.0)
    assert {k: getattr(x, k) for k in keys} == {k: getattr(y, k) for k in keys}
    assert x.gap_pct == pytest.approx(z.gap_pct, abs=0.011) and x.verdict == z.verdict


# ── I. 정렬 ─────────────────────────────────────────────────────────────────────────────────────────
def _row(code, gap, composite, unavailable=False, per=10.0):
    it = _legacy(code)
    it.gap_pct, it.composite_score, it.per = gap, composite, per
    if unavailable:
        it.current_price = None
        it.price_unavailable = {"live": "kis_error", "close": "not_loaded"}
    return it


@pytest.mark.parametrize("key,asc", [("composite_score", False), ("composite_score", True),
                                     ("gap_pct", True), ("gap_pct", False)])
def test_rows_without_a_price_sort_last_in_both_directions(key, asc):
    rows = [_row("A", -40.0, 80.0), _row("B", None, None, unavailable=True), _row("C", 10.0, 20.0), _row("D", -5.0, 55.0)]
    sort_screener_items(rows, key, ascending=asc)
    assert rows[-1].stock_code == "B"
    known = [r.stock_code for r in rows[:-1]]
    want = sorted(["A", "C", "D"], key=lambda c: {"A": (-40.0, 80.0), "C": (10.0, 20.0), "D": (-5.0, 55.0)}[c]
                  [0 if key == "gap_pct" else 1], reverse=not asc)
    assert known == want


def test_other_unknowns_still_sort_as_before():
    """★짝★ 가격이 없는 행만 옮긴다 — 다른 까닭의 미상(예: 적자 종목의 PER None)은 예전처럼 0 으로 센다(F3c · 따로 볼 일)."""
    rows = [_row("A", -40.0, 80.0, per=12.0), _row("B", -10.0, 60.0, per=None), _row("C", 10.0, 20.0, per=8.0)]
    sort_screener_items(rows, "per", ascending=True)
    assert [r.stock_code for r in rows] == ["B", "C", "A"]


# ── J. 예전 필터(ScreenerFilters) ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("filters", [ScreenerFilters(min_gap_pct=-50.0), ScreenerFilters(max_gap_pct=50.0)])
def test_an_unknown_gap_does_not_pass_a_gap_filter(filters):
    sc = ValuationScreener(dart_client=_FakeDart())
    assert sc._matches_filters(_row("B", None, None, unavailable=True), filters) is False
    assert sc._matches_filters(_row("A", -20.0, 60.0), filters) is True          # ★짝★ 아는 괴리율은 그대로 걸린다


# ── K. 공급자 주입 ───────────────────────────────────────────────────────────────────────────────────
def test_an_injected_provider_is_labelled_and_its_failure_is_not_filled(world):
    def provider(code):
        if code == "000660":
            raise RuntimeError("feed down")
        return 75_000.0
    sc = ValuationScreener(dart_client=_FakeDart(), price_provider=provider)
    rows = _by_code(sc.run(universe=["005930", "000660"], limit=5, liquidity_floor="off"))
    assert rows["005930"].current_price == 75_000.0 and rows["005930"].price_source["kind"] == "provider"
    assert _unknown(rows["000660"]) and rows["000660"].price_unavailable["close"] == "provider_error"
    assert world.close_calls == [], "주입한 공급자가 있으면 적재 종가를 읽지 않는다"


def test_the_safe_getter_does_not_fall_back_to_a_synthetic_price_in_production(world):
    sc = ValuationScreener(dart_client=_FakeDart(), price_provider=lambda c: (_ for _ in ()).throw(RuntimeError("x")))
    assert sc._get_price_safe("005930") is None
    assert world.base_calls == []


def test_the_safe_getter_still_falls_back_in_mock(monkeypatch):
    """★짝★ mock 은 예전 그대로 — 공급자가 터지면 mock 종가."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    sc = ValuationScreener(dart_client=_FakeDart(), price_provider=lambda c: (_ for _ in ()).throw(RuntimeError("x")))
    assert sc._get_price_safe("005930") == ValuationScreener._mock_price("005930") > 0


# ── L. 적재 배치(ingest) ────────────────────────────────────────────────────────────────────────────
def test_the_ingest_batch_stores_no_synthetic_price(world, monkeypatch):
    import src.data.snapshot_db as sdb
    import src.engine.screener as scr
    monkeypatch.setattr(scr, "DARTClient", _FakeDart)
    monkeypatch.setattr(sdb, "ingested_count", lambda: 0)
    monkeypatch.setattr(sdb, "count", lambda: len(world.mem))
    world.closes = {"005930": _close(70_000.0)}
    out = sdb.ingest_universe(["005930", "000660"])
    assert out["failures"] == 0
    stored = {k.split(":", 1)[1]: v for k, v in world.mem.items() if k.startswith("item:")}
    assert set(stored) == {"005930", "000660"}
    assert stored["005930"]["current_price"] == 70_000.0 and stored["005930"]["price_source"]["kind"] == "daily_close"
    assert stored["000660"]["current_price"] is None and stored["000660"]["price_unavailable"]["close"] == "not_loaded"
    assert all(v["price_is_mock"] is False for v in stored.values())
    assert world.base_calls == []


# ── 끝단: 진짜 `close_asof` · 임시 sqlite 의 `daily_prices`(제품의 스키마 함수로 만든다) ───────────────────────────
def test_end_to_end_on_a_loaded_daily_prices_table(world, monkeypatch, tmp_path):
    """가짜 없이 적재 표를 읽는다 — 어제 원주가 봉 · 수정주가 봉 · 낡은 봉(15일 전) · 봉 없음."""
    from datetime import timedelta

    from sqlalchemy import create_engine, text

    import src.engine.universe_select as us
    from src.data.krx_ingest import ensure_table
    eng = create_engine(f"sqlite:///{tmp_path}/px.db")
    ensure_table(eng)
    day = lambda n: (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")   # noqa: E731
    with eng.begin() as c:
        for t, d, px, src, basis in (("005930", day(1), 70_000.0, "krx", "raw"), ("000660", day(2), 90_000.0, "kis", "adjusted"),
                                     ("123456", day(15), 50_000.0, "krx", "raw")):
            c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close, source, price_basis) VALUES (:t, :d, :c, :s, :b)"),
                      {"t": t, "d": d, "c": px, "s": src, "b": basis})
    monkeypatch.setattr(us, "close_asof", REAL_CLOSE_ASOF)
    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    r = _run(universe=["005930", "000660", "123456", "999999"])
    rows = _by_code(r)
    assert rows["005930"].current_price == 70_000.0
    assert rows["005930"].price_source == {"kind": "daily_close", "trade_date": day(1), "source": "krx", "price_basis": "raw",
                                           "live": "kis_credentials_missing"}
    assert rows["000660"].current_price == 90_000.0 and rows["000660"].price_source["price_basis"] == "adjusted"
    assert _unknown(rows["123456"]) and rows["123456"].price_unavailable["close"] == "stale"
    assert _unknown(rows["999999"]) and rows["999999"].price_unavailable["close"] == "not_loaded"
    assert r.prices["by_source"] == {"kis_live": 0, "daily_close": 2, "provider": 0, "unavailable": 2}
    assert world.base_calls == []
