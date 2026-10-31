"""★종목별 커버리지★ — "적재됐다" 와 "충분히 적재됐다" 는 다르다 (③)

## 무엇이 문제였나

`db-status` 는 테이블별 **전체 행 수**만 낸다. 그래서 이 둘이 구별되지 않는다:

    1종목 × 40행  = 40행
    2,700종목 × 40행 = 108,000행 ... 도 "행 수" 하나로는 같은 종류의 사실이다

정작 물어야 하는 것은 **"내 유니버스의 몇 %가 내 백테스트 기간을 덮는가"** 다.
그것이 "백테스트가 왜 빈약한가" 에 답한다. 지금은 어디에도 없다.

## 무겁다 — 그래서 온디맨드다

`daily_prices` 는 수백만 행이다. 기존 코드가 종목 수를 `pg_stats` 추정치로 쓰는
이유가 그것이다(`data_routes.py`, 미확정이면 `None` — "0 금지"). 그 규율을 따른다:

  · 탭을 여는 것만으로는 **안 돈다** — 버튼을 눌러야 집계한다
  · 결과는 TTL 캐시
  · ★추정치는 추정치라고 라벨한다★ — 실측인 척하면 사용자가 잘못 판단한다
  · 못 재면 `None` + 사유
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

import src.data.coverage as cov  # noqa: E402


@pytest.fixture
def db(monkeypatch, tmp_path):
    """3종목만 적재된 `daily_prices` — 하나는 기간을 덮고 둘은 못 덮는다."""
    eng = create_engine(f"sqlite:///{tmp_path}/c.db")
    with eng.begin() as c:
        c.execute(text(
            'CREATE TABLE daily_prices(ticker VARCHAR(12) NOT NULL, trade_date DATE NOT NULL,'
            ' "open" FLOAT, high FLOAT, low FLOAT, close FLOAT, volume BIGINT,'
            " PRIMARY KEY(ticker, trade_date))"))
        # ★슬랙(±10일)을 감안한 날짜를 쓴다★ 처음엔 매월 15일만 넣었더니 12월
        # 마지막 행이 12-15 라 "연말까지 덮는다" 판정을 못 받았다 — 제품이 아니라
        # 픽스처의 문제였다. 연초·연말 가까이에 행을 둔다.
        rows = []
        # ★"일찍 시작했지만 일찍 끝난" 종목이 있어야 꼬리 검사가 보인다★
        # 000004 는 시작 조건은 통과하고 **끝 조건만** 실패한다 — 이 종목이 없으면
        # `s.hi >= :hi` 를 빼는 변이가 드러나지 않는다(변이 F18 이 그렇게 살아남았다).
        for tk, start, n in (("000001", 2020, 5), ("000002", 2023, 2),
                             ("000003", 2024, 1), ("000004", 2020, 2)):
            for y in range(start, start + n):
                for md in ("01-02", "06-15", "12-28"):
                    rows.append({"t": tk, "d": f"{y}-{md}"})
        c.execute(text('INSERT INTO daily_prices(ticker, trade_date, "open", high, low,'
                       " close, volume) VALUES(:t,:d,1,1,1,1,1)"), rows)
    monkeypatch.setattr(cov, "_engine", lambda: eng)
    cov.clear_cache()
    return eng


@pytest.fixture
def client(db):
    from src.api.data_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── 무엇을 답하는가 ─────────────────────────────────────────────────────────

def test_it_answers_how_many_tickers_cover_the_window(db):
    """★핵심★ "3종목 중 몇 개가 2023–2024 를 덮는가"."""
    r = cov.ticker_coverage("stocks", start="2023-01-01", end="2024-12-31")
    assert r["tickers_total"] == 4, r
    assert r["tickers_covering"] == 2, f"기간을 덮는 종목 수가 틀렸다: {r}"
    assert r["measured"] is True, "실측인데 추정이라고 했다"


def test_a_ticker_missing_the_tail_is_not_counted_as_covering(db):
    """★"적재됐다" 와 "충분히 적재됐다" 는 다르다★ (변이 F18)

    `000004` 는 2020 에 시작해 2021 에 끝난다 — **시작 조건은 통과하고 끝 조건만
    실패**한다. 그런 종목이 있어야 꼬리 검사가 실제로 걸린다.
    """
    r = cov.ticker_coverage("stocks", start="2020-01-01", end="2024-12-31")
    assert r["tickers_total"] == 4, r
    assert r["tickers_covering"] == 1, f"끝이 모자란 종목을 덮었다고 셌다: {r}"


def test_the_result_names_the_dataset_it_measured(db):
    """어느 데이터셋을 잰 것인지 말하지 않으면 숫자가 떠돈다."""
    r = cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert r["key"] == "stocks" and r["table"] == "daily_prices"


def test_an_unknown_dataset_is_refused_not_invented(db):
    with pytest.raises(KeyError):
        cov.ticker_coverage("존재하지않음", start="2023-01-01", end="2023-12-31")


# ── 미상 ≠ 0 ────────────────────────────────────────────────────────────────

def test_an_unmeasurable_dataset_says_so_rather_than_reporting_zero(monkeypatch, db):
    """★못 재면 None + 사유★ `0종목` 은 "재봤더니 없다" 는 **하지 않은 진술**이다."""
    monkeypatch.setattr(cov, "_engine",
                        lambda: (_ for _ in ()).throw(RuntimeError("DB 다운")))
    cov.clear_cache()
    r = cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert r["tickers_total"] is None and r["tickers_covering"] is None, r
    assert r["reason"], "왜 못 쟀는지 말하지 않는다"
    assert r["measured"] is False, "못 쟀는데 실측이라고 라벨했다"


def test_a_dataset_without_a_ticker_column_is_honest_about_it(db):
    """모든 데이터셋이 종목 축을 갖지는 않는다(매크로는 시계열이다).

    ★이 테스트는 한때 공허했다★ (변이 F19) — `tickers_total is None` 만 걸었는데,
    매크로에 종목 컬럼을 **지어낸** 변이도 통과했다. 픽스처 DB 에 그 테이블이 없어
    DB 오류로 None 이 됐기 때문이다. 즉 **이유가 다른데 결과가 같았다.**
    사유가 '종목 축 없음' 인지까지 걸어야 구별된다.
    """
    r = cov.ticker_coverage("macro", start="2023-01-01", end="2023-12-31")
    assert r["tickers_total"] is None, "매크로에 종목 수를 지어냈다"
    assert "종목 축이 없는" in (r["reason"] or ""), (
        f"종목 축이 없다는 사유가 아니다(DB 오류로 우연히 None 이 됐을 수 있다): {r['reason']}")
    # ★재보지 않았으면 measured 가 아니다★ (변이 F4)
    assert r["measured"] is False, "재지 않았는데 실측이라고 라벨했다"


# ── 온디맨드 + 캐시 ─────────────────────────────────────────────────────────

def test_the_expensive_query_is_cached(db, monkeypatch):
    """★탭을 여는 것만으로 무거운 집계가 돌면 안 된다★"""
    calls = {"n": 0}
    real = cov._count_coverage

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(cov, "_count_coverage", counted)
    cov.clear_cache()
    for _ in range(4):
        cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert calls["n"] == 1, f"캐시가 안 먹는다: {calls['n']}회 집계"


def test_a_different_window_is_not_served_from_the_wrong_cache_entry(db):
    """★짝★ "캐시한다" 만 걸면 **모든 질문에 같은 답**을 주는 구현도 통과한다."""
    a = cov.ticker_coverage("stocks", start="2020-01-01", end="2024-12-31")
    b = cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert a["tickers_covering"] != b["tickers_covering"], (
        f"다른 기간인데 같은 답을 줬다: {a} vs {b}")


# ── 라우트 ──────────────────────────────────────────────────────────────────

def test_the_route_returns_coverage(client):
    r = client.get("/api/v1/data/coverage",
                   params={"target": "stocks", "start": "2023-01-01", "end": "2024-12-31"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["tickers_covering"] == 2 and b["key"] == "stocks"


def test_the_route_refuses_an_unknown_target_with_404(client):
    r = client.get("/api/v1/data/coverage",
                   params={"target": "없는대상", "start": "2023-01-01", "end": "2023-12-31"})
    assert r.status_code == 404, r.text


def test_a_failure_is_retried_rather_than_cached(monkeypatch, db):
    """★실패를 기억하면 DB 가 돌아와도 영원히 미상이다★ (변이 F20)

    성공은 TTL 캐시해도 되지만 실패는 아니다 — 일시적 DB 오류 한 번이 그 프로세스의
    커버리지 보고를 10분간 죽인다.
    """
    cov.clear_cache()
    boom = {"on": True}
    real = cov._engine

    def flaky():
        if boom["on"]:
            raise RuntimeError("DB 일시 오류")
        return real()

    monkeypatch.setattr(cov, "_engine", flaky)
    r1 = cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert r1["tickers_total"] is None and r1["reason"]

    boom["on"] = False
    r2 = cov.ticker_coverage("stocks", start="2023-01-01", end="2023-12-31")
    assert r2["tickers_total"] is not None, (
        "DB 가 돌아왔는데도 캐시된 실패를 돌려준다")
