"""시장 스냅샷 파이프라인은 ★운영에서 합성 스냅샷을 만들지 않는다★ (2026-11-14 — 감사 `docs/specs/2026-11-13-market-snapshot-synthetic-audit.md` §5 '가').

감사가 본 것: `src/screener_pipeline.py` 가 mock 게이트를 지나지 않고 운영에서도 5분마다 실제 종목코드에 지어낸 값을 표 둘
(`market_snapshot_equity` · `market_snapshot_ficc`)에 쓰고, 레거시 라우트가 표시 없이 돌려줬다. 야후를 켠 운영에서 하나도 못 받으면
같은 합성 스냅샷으로 조용히 바뀌었다.

고친 뒤의 계약 — 판정은 `src/data/mock_gate.py::mock_allowed()` 하나, 겹은 둘이다:
  ① 쓰기: 운영은 합성 행을 만들지 않는다. 주식 표는 야후를 켰을 때 ★받은 것만★, FICC 표는 원천이 없어 비운다. 빈 결과는 표를 비운다
     (예전 버전이 써 둔 합성 행이 남지 않게).
  ② 읽기: 레거시 라우트는 ★이 프로세스가 실데이터로 써넣은 표만★ 낸다. 아니면 0건 + 사유(표에 행이 남아 있어도).
  mock 은 예전과 같은 합성 행을 만들고 응답에 합성 표시(`is_mock`)를 싣는다.

★이 파일이 말하지 않는 것★ — 야후가 답하는 값의 품질(없는 값을 `0`·`50`·`"Unknown"` 으로 채우는 자리가 그대로 있다 — 감사 문서 §7) ·
운영 DB·운영 호출처(미상) · 레거시 경로를 걷어 낼지(감사 '다' — 따로 결정).
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

EQUITY_Q = {"universe": "equity", "conditions": {"A": {"field": "per", "operator": "<", "value": 1e9}}, "logic_expression": "A", "limit": 500}
FICC_Q = {"universe": "ficc", "conditions": {"A": {"field": "price", "operator": "<", "value": 1e9}}, "logic_expression": "A", "limit": 500}
#: 사유 문장은 응답에 그대로 실린다 — 개발자 낱말·환경변수 이름·제공자 라이브러리 이름을 싣지 않는다(용어집 §6).
FORBIDDEN_IN_MESSAGE = ("mock", "Mock", "KIS_USE_MOCK", "MARKET_PIPELINE", "yfinance", "Yahoo", "yahoo")


def _frame(n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = pd.Series(range(100, 100 + n), index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0}, index=idx)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """임시 sqlite 에 스냅샷 표 둘 — 라우트·파이프라인이 이 엔진을 쓴다. 프로세스 로컬 상태는 시험마다 비운다."""
    import sqlalchemy

    import src.database as db
    import src.screener_pipeline as sp
    from src.screener_models import init_screener_tables
    eng = sqlalchemy.create_engine(f"sqlite:///{tmp_path}/snap.db")
    init_screener_tables(eng)
    monkeypatch.setattr(db, "get_engine", lambda: eng)
    monkeypatch.setattr(sp, "_WRITTEN", {}, raising=False)
    monkeypatch.setattr(sp, "USE_YFINANCE", False)
    return eng


@pytest.fixture
def yahoo(monkeypatch):
    """야후 내려받기를 가짜로 바꾼다 — `answers(batch)` 가 그 묶음의 일봉을 정한다(기본: 다 준다). 부른 묶음을 적어 둔다."""
    import yfinance
    state = {"calls": [], "answers": lambda batch: _frame()}

    def fake(tickers, *a, **k):
        batch = [tickers] if isinstance(tickers, str) else list(tickers)
        state["calls"].append(batch)
        return state["answers"](batch)

    class FakeTicker:
        def __init__(self, ticker, *a, **k):
            self.fast_info = {}
            self.info = {"shortName": f"{ticker} 실명", "sector": "Technology", "trailingPE": 12.5}

    monkeypatch.setattr(yfinance, "download", fake)
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    return state


def _mode(monkeypatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("KIS_USE_MOCK", raising=False)
    else:
        monkeypatch.setenv("KIS_USE_MOCK", value)


def _sp():
    import src.screener_pipeline as sp
    return sp


def _fetch(universe: str):
    """`(rows, origin)` — 행과 출처를 함께 돌려주는 것이 계약이다(라벨은 행을 만든 자리에서 붙는다)."""
    sp = _sp()
    out = asyncio.run(sp.fetch_equity_snapshot() if universe == "equity" else sp.fetch_ficc_snapshot())
    assert isinstance(out, tuple) and len(out) == 2, f"(rows, origin) 이 아니다: {type(out).__name__}"
    return out


def _refresh(engine) -> dict:
    return asyncio.run(_sp().refresh_all_snapshots(engine))


def _count(engine, table: str, where: str = "1=1") -> int:
    from sqlalchemy import text
    with engine.connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar() or 0)


def _seed_leftovers(monkeypatch, engine) -> None:
    """★예전 버전이 써 둔 합성 행★을 두 표에 심는다(28 + 267) — 프로세스 로컬 상태는 건드리지 않는다(다른 프로세스가 쓴 것처럼)."""
    sp = _sp()
    _mode(monkeypatch, "1")
    eq, _ = _fetch("equity")
    fi, _ = _fetch("ficc")
    sp._bulk_refresh_table(engine, "market_snapshot_equity", eq)
    sp._bulk_refresh_table(engine, "market_snapshot_ficc", fi)
    assert (_count(engine, "market_snapshot_equity"), _count(engine, "market_snapshot_ficc")) == (28, 267)


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.screener_legacy_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _unavailable(origin: dict, reason: str) -> None:
    assert origin["available"] is False and origin["is_mock"] is False and origin["source"] is None
    assert origin["reason"] == reason and origin["message"]


# ── ① 쓰기 — 운영은 합성 행을 만들지 않는다 ─────────────────────────────────────

def test_prod_equity_with_the_feed_off_makes_nothing_and_says_why(monkeypatch, engine):
    """운영 기본 설정(야후 꺼짐) — 예전엔 난수 28행을 만들었다."""
    _mode(monkeypatch, "0")
    rows, origin = _fetch("equity")
    assert rows == []
    _unavailable(origin, "feed_off")


def test_prod_ficc_makes_nothing_and_says_why(monkeypatch, engine):
    """FICC 는 실데이터 원천이 코드에 없다 — 운영에서는 늘 빈 결과 + 사유(예전엔 모든 모드에서 난수 267행)."""
    _mode(monkeypatch, "0")
    rows, origin = _fetch("ficc")
    assert rows == []
    _unavailable(origin, "no_feed")


def test_prod_equity_when_every_download_fails_is_empty_not_synthetic(monkeypatch, engine, yahoo):
    """★침묵 폴백★ — 야후를 켠 운영에서 하나도 못 받으면 예전엔 합성 28행으로 바뀌었다. 이제 빈 결과 + 사유다."""
    _mode(monkeypatch, "0")
    monkeypatch.setattr(_sp(), "USE_YFINANCE", True)
    yahoo["answers"] = lambda batch: pd.DataFrame()
    rows, origin = _fetch("equity")
    assert yahoo["calls"], "내려받기를 시도하지 않았다 — 이 시험은 '시도했고 못 받았다'를 본다"
    assert rows == []
    _unavailable(origin, "download_failed")


def test_prod_equity_keeps_only_what_arrived_and_labels_it_real(monkeypatch, engine, yahoo):
    """★짝★ — 받으면 쓴다. 일부만 받았으면 받은 종목만(빠진 종목을 지어내 채우지 않는다) · 몇 개를 청했고 몇 개를 받았는지 싣는다."""
    sp = _sp()
    _mode(monkeypatch, "0")
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    monkeypatch.setattr(sp, "EQUITY_TICKERS", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "005930.KS"])
    yahoo["answers"] = lambda batch: _frame() if "AAPL" in batch else pd.DataFrame()      # 첫 묶음(5종목)만 온다
    rows, origin = _fetch("equity")
    assert sorted(r["ticker"] for r in rows) == ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]
    assert origin["available"] is True and origin["source"] == "yahoo" and origin["is_mock"] is False and origin["reason"] is None
    assert (origin["requested"], origin["received"]) == (6, 5)
    assert all(r["name"] == f"{r['ticker']} 실명" for r in rows)                          # 받은 이름 그대로 — 지어낸 "… Corp" 가 아니다


# ── ★짝★ — mock 은 예전과 같은 합성 행 + 합성 표시 ───────────────────────────────

def test_mock_makes_the_same_synthetic_rows_and_labels_them(monkeypatch, engine):
    """mock 의 값은 그대로다(난수 고정 — 감사 때 본 표본과 같다). 달라진 것은 라벨 하나다."""
    _mode(monkeypatch, "1")
    eq, eq_origin = _fetch("equity")
    fi, fi_origin = _fetch("ficc")
    by = {r["ticker"]: r for r in eq}
    assert len(eq) == 28 and (by["000660.KS"]["per"], by["000660.KS"]["roe"]) == (17.81, 21.47) and (by["META"]["per"], by["META"]["roe"]) == (5.77, 0.81)
    kinds = [r["asset_type"] for r in fi]
    assert (kinds.count("bond"), kinds.count("option"), kinds.count("fx")) == (18, 240, 9)
    for origin in (eq_origin, fi_origin):
        assert origin["available"] is True and origin["is_mock"] is True and origin["source"] == "synthetic" and origin["message"]


def test_mock_does_not_download_even_when_the_feed_is_on(monkeypatch, engine, yahoo):
    _mode(monkeypatch, "1")
    monkeypatch.setattr(_sp(), "USE_YFINANCE", True)
    rows, origin = _fetch("equity")
    assert yahoo["calls"] == [] and len(rows) == 28 and origin["is_mock"] is True


@pytest.mark.parametrize("value", ["0", "true", "01", " 1", "TRUE", ""])
def test_anything_but_exactly_one_is_production(monkeypatch, engine, value):
    """`KIS_USE_MOCK` 이 정확히 `"1"` 일 때만 mock 이다(CLAUDE.md §6) — 비슷한 값은 운영이고 합성 행을 만들지 않는다."""
    _mode(monkeypatch, value)
    assert _fetch("equity")[0] == [] and _fetch("ficc")[0] == []


def test_an_unset_gate_is_mock(monkeypatch, engine):
    """★짝★ — 설정하지 않으면 mock 이다(개발 기본값). 위 시험이 '늘 빈 결과'인 구현으로 통과하지 않게."""
    _mode(monkeypatch, None)
    assert len(_fetch("equity")[0]) == 28 and len(_fetch("ficc")[0]) == 267


# ── ① 쓰기 — 표 ────────────────────────────────────────────────────────────────

def test_prod_refresh_clears_the_synthetic_rows_an_older_version_left(monkeypatch, engine):
    """예전 버전이 써 둔 합성 행(28 + 267)이 운영 갱신 한 번으로 사라진다 — 빈 결과가 '표를 건드리지 않음'이면 영영 남는다."""
    _seed_leftovers(monkeypatch, engine)
    _mode(monkeypatch, "0")
    res = _refresh(engine)
    assert (_count(engine, "market_snapshot_equity"), _count(engine, "market_snapshot_ficc")) == (0, 0)
    assert (res["equity_rows"], res["ficc_rows"]) == (0, 0)
    _unavailable(res["snapshot"]["equity"], "feed_off")
    _unavailable(res["snapshot"]["ficc"], "no_feed")


def test_mock_refresh_fills_both_tables(monkeypatch, engine):
    """★짝★ — mock 은 채운다(지어낸 이름 "… Corp" 도 그대로 — 합성 표시가 붙는다)."""
    _mode(monkeypatch, "1")
    res = _refresh(engine)
    assert (res["equity_rows"], res["ficc_rows"]) == (28, 267)
    assert (_count(engine, "market_snapshot_equity"), _count(engine, "market_snapshot_ficc")) == (28, 267)
    assert _count(engine, "market_snapshot_equity", "name LIKE '% Corp'") == 28
    assert res["snapshot"]["equity"]["is_mock"] is True and res["snapshot"]["ficc"]["is_mock"] is True


def test_prod_tables_never_hold_an_invented_name(monkeypatch, engine, yahoo):
    """★트립와이어★ — 운영의 어느 경로에서도 표에 지어낸 이름("… Corp")이 없다: 야후 꺼짐 · 켬(받음) · 켬(전부 실패)."""
    sp = _sp()
    full = list(sp.EQUITY_TICKERS)
    for feed_on, answers in ((False, None), (True, lambda b: _frame()), (True, lambda b: pd.DataFrame())):
        monkeypatch.setattr(sp, "EQUITY_TICKERS", full)
        _seed_leftovers(monkeypatch, engine)
        _mode(monkeypatch, "0")
        monkeypatch.setattr(sp, "USE_YFINANCE", feed_on)
        monkeypatch.setattr(sp, "EQUITY_TICKERS", ["AAPL", "000660.KS"])
        if answers is not None:
            yahoo["answers"] = answers
        _refresh(engine)
        assert _count(engine, "market_snapshot_equity", "name LIKE '% Corp'") == 0, (feed_on, answers)
        assert _count(engine, "market_snapshot_ficc") == 0
    assert _count(engine, "market_snapshot_equity") == 0                                  # 마지막 경우(전부 실패)는 표가 비어 있다


def test_a_failed_write_leaves_what_the_process_knows_unchanged(monkeypatch, engine, yahoo):
    """쓰기가 실패하면 표는 그대로다 — 그래서 '이 프로세스가 써넣은 것'의 기록도 그대로여야 한다(성공한 것으로 고치면 읽기 겹이 속는다)."""
    sp = _sp()
    _mode(monkeypatch, "0")
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    monkeypatch.setattr(sp, "EQUITY_TICKERS", ["AAPL", "MSFT"])

    def boom(*a, **k):
        raise RuntimeError("db down")

    real = sp._bulk_refresh_table
    monkeypatch.setattr(sp, "_bulk_refresh_table", boom)
    res = _refresh(engine)                                                               # 첫 쓰기부터 실패
    assert (res["equity_rows"], res["ficc_rows"]) == (0, 0)
    _unavailable(sp.snapshot_origin("equity"), "not_refreshed")
    monkeypatch.setattr(sp, "_bulk_refresh_table", real)
    _refresh(engine)                                                                     # 성공 — 실데이터 2행
    assert sp.snapshot_origin("equity")["source"] == "yahoo" and _count(engine, "market_snapshot_equity") == 2
    monkeypatch.setattr(sp, "_bulk_refresh_table", boom)
    yahoo["answers"] = lambda batch: pd.DataFrame()
    _refresh(engine)                                                                     # 다음 갱신은 쓰기 실패 — 표엔 앞의 2행이 그대로
    assert sp.snapshot_origin("equity")["source"] == "yahoo" and _count(engine, "market_snapshot_equity") == 2


def test_the_reasons_are_sentences_a_reader_can_be_shown(monkeypatch, engine, yahoo):
    """사유 문장은 응답에 그대로 실린다 — 합니다체 한 문장 · 개발자 낱말 없음."""
    sp = _sp()
    seen: list[str] = []
    _mode(monkeypatch, "1")
    seen += [_fetch("equity")[1]["message"], _fetch("ficc")[1]["message"]]
    _mode(monkeypatch, "0")
    seen += [_fetch("equity")[1]["message"], _fetch("ficc")[1]["message"], sp.snapshot_origin("equity")["message"]]
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    yahoo["answers"] = lambda batch: pd.DataFrame()
    seen.append(_fetch("equity")[1]["message"])
    assert len(set(seen)) == 5, seen                                                     # 합성(둘이 같다) · 꺼짐 · 원천 없음 · 갱신 전 · 못 받음
    for msg in seen:
        assert msg.endswith("니다.") and not any(w in msg for w in FORBIDDEN_IN_MESSAGE), msg


# ── ② 읽기 — 레거시 라우트 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [EQUITY_Q, FICC_Q])
def test_prod_route_serves_nothing_this_process_did_not_write(monkeypatch, engine, query):
    """★읽기 겹★ — 표에 예전 합성 행이 남아 있고 갱신이 아직(또는 실패해) 없어도 운영은 내지 않는다."""
    _seed_leftovers(monkeypatch, engine)
    _mode(monkeypatch, "0")
    r = _client().post("/screener", json=query)
    body = r.json()
    assert r.status_code == 200 and body["count"] == 0 and body["results"] == [] and body["universe"] == query["universe"]
    _unavailable(body["snapshot"], "not_refreshed")


def test_prod_route_after_a_default_refresh_is_empty_with_the_reason(monkeypatch, engine):
    _seed_leftovers(monkeypatch, engine)
    _mode(monkeypatch, "0")
    _refresh(engine)
    c = _client()
    eq, fi = c.post("/screener", json=EQUITY_Q).json(), c.post("/screener", json=FICC_Q).json()
    assert (eq["count"], fi["count"]) == (0, 0)
    _unavailable(eq["snapshot"], "feed_off")
    _unavailable(fi["snapshot"], "no_feed")


def test_prod_route_serves_downloaded_rows_with_a_real_label(monkeypatch, engine, yahoo):
    """★짝★ — 실데이터로 써넣은 표는 낸다(늘 0건인 구현을 배제). FICC 는 그때도 0건 + 사유."""
    sp = _sp()
    _mode(monkeypatch, "0")
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    monkeypatch.setattr(sp, "EQUITY_TICKERS", ["AAPL", "MSFT"])
    _refresh(engine)
    c = _client()
    eq, fi = c.post("/screener", json=EQUITY_Q).json(), c.post("/screener", json=FICC_Q).json()
    assert eq["count"] == 2 and sorted(r["ticker"] for r in eq["results"]) == ["AAPL", "MSFT"]
    assert eq["snapshot"]["available"] is True and eq["snapshot"]["source"] == "yahoo" and eq["snapshot"]["is_mock"] is False
    assert fi["count"] == 0
    _unavailable(fi["snapshot"], "no_feed")


@pytest.mark.parametrize(("query", "n"), [(EQUITY_Q, 28), (FICC_Q, 267)])
def test_mock_route_serves_rows_labelled_synthetic(monkeypatch, engine, query, n):
    """★짝★ — mock 은 예전처럼 내되 응답에 합성 표시가 붙는다."""
    _mode(monkeypatch, "1")
    _refresh(engine)
    body = _client().post("/screener", json=query).json()
    assert body["count"] == n and len(body["results"]) == n
    assert body["snapshot"]["is_mock"] is True and body["snapshot"]["source"] == "synthetic" and body["snapshot"]["message"]


def test_prod_does_not_serve_what_a_mock_refresh_wrote(monkeypatch, engine):
    """합성으로 써넣은 기록은 운영 판정에서 '낼 수 있음'이 아니다 — 읽기 겹은 기록의 출처까지 본다."""
    _mode(monkeypatch, "1")
    _refresh(engine)
    _mode(monkeypatch, "0")
    body = _client().post("/screener", json=EQUITY_Q).json()
    assert body["count"] == 0 and body["snapshot"]["available"] is False and body["snapshot"]["is_mock"] is False


@pytest.mark.parametrize("mode", ["0", "1"])
def test_a_bad_request_is_still_a_400(monkeypatch, engine, mode):
    """입력 검증이 먼저다 — 게이트가 잘못된 요청을 '0건'으로 삼키지 않는다."""
    _mode(monkeypatch, mode)
    c = _client()
    assert c.post("/screener", json={**EQUITY_Q, "universe": "crypto"}).status_code == 400
    assert c.post("/screener", json={**EQUITY_Q, "conditions": {"A": {"field": "name", "operator": "<", "value": 1}}}).status_code == 400


def test_status_says_where_each_table_came_from(monkeypatch, engine):
    """`GET /screener/status` — 행 수·갱신 시각에 표마다 출처 라벨이 붙는다."""
    c = _client()
    _mode(monkeypatch, "1")
    _refresh(engine)
    r = c.get("/screener/status")
    assert r.status_code == 200, r.text
    m = r.json()
    assert (m["equity_rows"], m["ficc_rows"]) == (28, 267) and m["equity_updated_at"] and m["ficc_updated_at"]
    assert m["snapshot"]["equity"]["is_mock"] is True and m["snapshot"]["ficc"]["is_mock"] is True
    _mode(monkeypatch, "0")
    _refresh(engine)
    r = c.get("/screener/status")
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["equity_rows"], p["ficc_rows"], p["equity_updated_at"], p["ficc_updated_at"]) == (0, 0, None, None)
    _unavailable(p["snapshot"]["equity"], "feed_off")
    _unavailable(p["snapshot"]["ficc"], "no_feed")


def test_manual_refresh_reports_the_origin(monkeypatch, engine):
    """`POST /screener/refresh` — 운영은 0행 + 사유, mock 은 28 · 267행 + 합성 표시."""
    c = _client()
    _mode(monkeypatch, "0")
    p = c.post("/screener/refresh").json()
    assert (p["equity_rows"], p["ficc_rows"]) == (0, 0)
    _unavailable(p["snapshot"]["equity"], "feed_off")
    _unavailable(p["snapshot"]["ficc"], "no_feed")
    _mode(monkeypatch, "1")
    m = c.post("/screener/refresh").json()
    assert (m["equity_rows"], m["ficc_rows"]) == (28, 267) and m["snapshot"]["equity"]["is_mock"] is True
