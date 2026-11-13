"""운영의 시점(as_of) 평가는 ★적재된 실제 종가★로만 계산하고, 없으면 그 종목을 사유와 함께 뺀다 (2026-11-13 · 감사 §7 A안).

감사: `docs/specs/2026-11-12-pit-asof-prod-synthetic-audit.md` — F1(시점 가격) · F4·F5(as_of ↔ `item:` 캐시 혼선).
재무(F2·F2b)의 계약은 `tests/test_pit_asof_prod_tripwire.py` 에 있다.

★이 시험이 말하지 않는 것★ — 운영 DB 실측이 아니다(임시 sqlite · 가짜 저장소). 예측력·경제적 가치와 무관하다:
답하는 질문은 "과거 시점 평가가 그 시점에 관측할 수 있던 값만 쓰는가"(데이터 무결성 · 시점 정합)다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

ASOF = "2024-06-28"


@pytest.fixture
def prices(tmp_path):
    """`daily_prices` 가 있는 임시 DB — 제품의 스키마 함수로 만든다(시험이 표 모양을 지어내지 않는다)."""
    from src.data.krx_ingest import ensure_table
    eng = create_engine(f"sqlite:///{tmp_path}/px.db")
    ensure_table(eng)

    def add(ticker, day, close, source="krx", basis="raw", adj=None):
        with eng.begin() as c:
            c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close, adj_close, source, price_basis) "
                           "VALUES (:t, :d, :c, :a, :s, :b)"),
                      {"t": ticker, "d": day, "c": close, "a": adj, "s": source, "b": basis})
    eng.add = add
    return eng


# ── 1. close_asof — 적재된 종가를 그대로 · 못 읽은 세 경우는 서로 다른 사유 ─────────────────

def test_the_loaded_close_on_the_day_is_returned_with_its_provenance(prices):
    from src.engine.universe_select import close_asof
    prices.add("005930", "2024-06-27", 81000.0)
    prices.add("005930", ASOF, 81500.0, source="krx", basis="raw", adj=40750.0)
    prices.add("005930", "2024-07-01", 99999.0)                       # as_of 뒤의 봉은 보지 않는다(룩어헤드)
    row, why = close_asof("005930", ASOF, engine=prices)
    assert why is None
    assert row == {"close": 81500.0, "trade_date": ASOF, "source": "krx", "price_basis": "raw"}   # close 이지 adj_close 가 아니다


def test_a_non_trading_day_reads_the_previous_bar(prices):
    from src.engine.universe_select import close_asof
    prices.add("005930", "2024-06-28", 81500.0)
    row, why = close_asof("005930.KS", "2024-06-30", engine=prices)   # 일요일 · 접미사
    assert why is None and row["close"] == 81500.0 and row["trade_date"] == "2024-06-28"


def test_nothing_loaded_stale_and_store_error_are_three_reasons(prices):
    from src.engine.universe_select import ASOF_CLOSE_MAX_STALE_DAYS, close_asof
    assert close_asof("000660", ASOF, engine=prices) == (None, "not_loaded")
    prices.add("000660", "2024-07-05", 200000.0)                      # as_of 뒤에만 봉이 있다 — 여전히 미적재
    assert close_asof("000660", ASOF, engine=prices) == (None, "not_loaded")
    prices.add("035420", "2023-01-02", 180000.0)                      # 1년 반 전의 봉을 그 날 종가라 하지 않는다
    assert close_asof("035420", ASOF, engine=prices) == (None, "stale")
    assert 5 <= ASOF_CLOSE_MAX_STALE_DAYS <= 15                       # 긴 연휴는 덮고 상장폐지·적재 공백은 덮지 않는 범위

    class Broken:
        def connect(self):
            raise RuntimeError("db down")
    assert close_asof("005930", ASOF, engine=Broken()) == (None, "store_error")   # DB 오류 ≠ 미적재


def test_the_stale_limit_is_a_boundary_not_a_constant_answer(prices):
    """★짝★ — 한도 안쪽은 읽고 바깥쪽은 낡았다고 한다(늘 읽거나 늘 거부하는 구현이 아니다)."""
    from datetime import date, timedelta

    from src.engine.universe_select import ASOF_CLOSE_MAX_STALE_DAYS, close_asof
    d = date.fromisoformat(ASOF)
    prices.add("111111", (d - timedelta(days=ASOF_CLOSE_MAX_STALE_DAYS)).isoformat(), 5000.0)
    prices.add("222222", (d - timedelta(days=ASOF_CLOSE_MAX_STALE_DAYS + 1)).isoformat(), 5000.0)
    assert close_asof("111111", ASOF, engine=prices)[1] is None
    assert close_asof("222222", ASOF, engine=prices) == (None, "stale")


# ── 2. PITStore — 운영은 실제 종가 또는 없음 · mock 은 그대로 ────────────────────────────

def _store():
    from src.engine.pit_store import PITStore
    return PITStore()


def test_prod_price_is_the_loaded_close_and_ignores_the_price_passed_in(monkeypatch, prices):
    import src.engine.universe_select as us
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    prices.add("005930", ASOF, 81500.0)
    real = us.close_asof
    monkeypatch.setattr(us, "close_asof", lambda t, d, engine=None: real(t, d, engine=prices))
    s = _store()
    assert s.get_price_asof("005930", ASOF, 71000.0) == 81500.0 == s.get_price_asof("005930", ASOF, 50000.0)
    px, meta, why = s.price_asof_detail("005930", ASOF, 71000.0)
    assert (px, why) == (81500.0, None) and meta["trade_date"] == ASOF and meta["source"] == "krx" and meta["price_basis"] == "raw"


def test_prod_price_is_absent_with_a_reason_when_no_close_is_loaded(monkeypatch, prices):
    import src.engine.universe_select as us
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    real = us.close_asof
    monkeypatch.setattr(us, "close_asof", lambda t, d, engine=None: real(t, d, engine=prices))
    s = _store()
    assert s.get_price_asof("005930", ASOF, 71000.0) is None          # 현재가 × 추세 × 난수를 과거 종가로 내지 않는다
    assert s.price_asof_detail("005930", ASOF, 71000.0) == (None, None, "not_loaded")


def test_mock_price_never_reads_the_price_store(monkeypatch):
    """★짝★ — mock 은 그 날의 mock 종가 그대로이고 DB 를 보지 않는다(운영 경로가 mock 을 바꾸지 않았다)."""
    import src.engine.universe_select as us
    from src.data.ohlcv_loader import mock_price_asof
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(us, "close_asof", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mock 이 DB 를 읽었다")))
    s = _store()
    px, meta, why = s.price_asof_detail("005930", ASOF, 71000.0)
    assert px == mock_price_asof("005930", ASOF) == s.get_price_asof("005930", ASOF, 1.0) and meta is None and why is None


# ── 3. 스크리너 — 제외는 사유와 함께 세고 failures 와 섞지 않는다 ─────────────────────────

U = ["005930", "000660", "035420"]


@pytest.fixture
def mem_snapshot(monkeypatch):
    """`item:` 캐시를 메모리 dict 로 — DB 없이 읽기·쓰기를 관측한다."""
    import src.data.snapshot_db as sdb
    store: dict = {}
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: store[k] for k in keys if k in store})
    monkeypatch.setattr(sdb, "write_many", lambda payload: store.update(payload))
    return store


def _screener():
    from src.engine.screener import ValuationScreener
    return ValuationScreener()


def _run(sc, **k):
    return sc.run(universe=U, limit=10, liquidity_floor="off", **k)


def test_a_ticker_without_an_as_of_price_is_excluded_with_its_reason(monkeypatch, mem_snapshot):
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    real = PITStore.price_asof_detail

    def detail(self, code, asof, cur):
        return (None, None, "not_loaded") if code == "000660" else real(self, code, asof, cur)
    monkeypatch.setattr(PITStore, "price_asof_detail", detail)
    r = _run(_screener(), as_of_date=ASOF)
    assert sorted(it.stock_code for it in r.items) == ["005930", "035420"]
    assert r.asof["excluded"] == {"count": 1, "by_reason": {"not_loaded": 1}, "sample": [{"code": "000660", "reason": "not_loaded"}]}
    assert r.failures == 0                                            # 제외는 평가 실패가 아니다


def test_nothing_excluded_reports_zero_and_a_current_run_reports_nothing(monkeypatch, mem_snapshot):
    """★짝★ — 제외가 없으면 0 이고(늘 무언가를 빼는 구현이 아니다), as_of 가 아니면 이 칸은 없다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _run(_screener(), as_of_date=ASOF)
    assert len(r.items) == 3 and r.asof["excluded"] == {"count": 0, "by_reason": {}, "sample": []}
    assert _run(_screener()).asof is None


def test_an_error_while_reading_the_as_of_price_excludes_instead_of_using_todays_price(monkeypatch, mem_snapshot):
    """전에는 예외를 삼키고 ★현재가★로 계속 평가했다(`except: pass`) — 조용한 룩어헤드."""
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", "1")

    def boom(self, code, asof, cur):
        raise RuntimeError("store down")
    monkeypatch.setattr(PITStore, "price_asof_detail", boom)
    r = _run(_screener(), as_of_date=ASOF)
    assert r.items == [] and r.asof["excluded"]["by_reason"] == {"price_error": 3}


def test_a_real_as_of_close_is_labelled_on_the_item(monkeypatch, mem_snapshot):
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    meta = {"trade_date": "2024-06-28", "source": "krx", "price_basis": "raw"}
    monkeypatch.setattr(PITStore, "price_asof_detail", lambda self, code, asof, cur: (12345.0, dict(meta), None))
    r = _run(_screener(), as_of_date=ASOF)
    for it in r.items:
        assert it.current_price == 12345.0 and it.price_is_mock is False
        assert it.to_dict()["asof_price"] == meta


def test_mock_as_of_items_keep_the_mock_label_and_carry_no_provenance_block(monkeypatch, mem_snapshot):
    """★짝★ — mock 종가(출처 메타 없음)는 여전히 mock 라벨이고 항목에 출처 칸이 없다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _run(_screener(), as_of_date=ASOF)
    assert r.items and all(it.price_is_mock is True and "asof_price" not in it.to_dict() for it in r.items)


# ── 4. F4·F5 — as_of 평가는 `item:` 캐시를 읽지도 쓰지도 않는다 ───────────────────────────

def test_an_as_of_run_does_not_write_the_current_item_cache(monkeypatch, mem_snapshot):
    """F5 — 과거 시점으로 평가한 항목이 현재 캐시에 남아 뒤의 ★현재★ 스크리닝이 과거 값을 봤다."""
    from src.data.ohlcv_loader import mock_price_asof
    from src.engine.screener import ValuationScreener
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    _run(_screener(), as_of_date=ASOF)
    assert [k for k in mem_snapshot if k.startswith("item:")] == []
    now = _run(_screener())
    assert {it.stock_code: it.current_price for it in now.items} == {c: ValuationScreener._mock_price(c) for c in U}
    assert any(ValuationScreener._mock_price(c) != mock_price_asof(c, ASOF) for c in U), "두 가격이 같으면 이 시험은 공허하다"


def test_an_as_of_run_does_not_read_the_current_item_cache(monkeypatch, mem_snapshot):
    """F4 — 현재 항목이 캐시에 있으면 as_of 평가가 PIT 를 건너뛰고 ★오늘 값★을 돌려줬다."""
    from src.data.ohlcv_loader import mock_price_asof
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    _run(_screener())                                                  # 현재 항목이 캐시에 들어간다
    assert len([k for k in mem_snapshot if k.startswith("item:")]) == 3
    past = _run(_screener(), as_of_date=ASOF)
    assert {it.stock_code: it.current_price for it in past.items} == {c: mock_price_asof(c, ASOF) for c in U}


def test_a_current_run_still_uses_the_item_cache(monkeypatch, mem_snapshot):
    """★짝★ — 현재 스크리닝의 캐시는 그대로다(캐시를 통째로 끈 구현이 아니다)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    _run(_screener())
    sc = _screener()
    calls: list = []
    orig = sc._evaluate_one_safe
    monkeypatch.setattr(sc, "_evaluate_one_safe", lambda code, params: (calls.append(code), orig(code, params))[1])
    assert len(_run(sc).items) == 3 and calls == []


# ── 5. 응답 — run-pit · 캔버스 노드 ──────────────────────────────────────────────────

def test_the_pit_route_reports_what_it_excluded(monkeypatch, mem_snapshot):
    import src.api.screener_routes as sr
    from src.engine.pit_store import PITStore
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    real = PITStore.price_asof_detail
    monkeypatch.setattr(PITStore, "price_asof_detail",
                        lambda self, code, asof, cur: (None, None, "stale") if code == "035420" else real(self, code, asof, cur))
    monkeypatch.setattr(sr, "get_screener", _screener)
    out = sr.screener_run_pit(sr.PITRunRequest(universe="kospi50", custom_tickers=U, as_of_date=ASOF,
                                               filter_ast={"logic": "AND", "conditions": [], "groups": []}, limit=10))
    assert out["asof"]["excluded"]["count"] == 1 and out["asof"]["excluded"]["by_reason"] == {"stale": 1}
    assert "035420" not in [it["stock_code"] for it in out["items"]]
