"""mock 모드(`KIS_USE_MOCK` 이 정확히 `"1"`)는 ★야후 시세를 내려받지 않는다★ (2026-11-13 — 야후 시세 mock 게이트).

앞 묶음(`tests/test_mock_no_external_calls.py`)은 기동과 인자 없는 GET 만 쟀고, 사용자가 실행하는 분석(POST)이 읽는 야후 시세는
게이트가 없다고 적어 두었다. 이 파일이 그 나머지다 — 야후로 나가는 자리는 셋이다:
  ① `src/data_loader.py::MarketDataLoader`(위험·전략·AI·신용·포트폴리오 라우트 22곳이 쓴다)
  ② `src/kis_strategies/factor_tokens.py::_market_fetch`(해외 지수 토큰 — DOW·NASDAQ·니케이·상해·VIX)
  ③ `src/screener_pipeline.py::fetch_equity_snapshot`(`MARKET_PIPELINE_USE_YFINANCE` 를 켰을 때만)

판정은 `src/data/mock_gate.py::mock_allowed()` 하나다. mock 에서는 ★시도하지 않고 사유를 말한다★ — 재시도·대기도 없다.
시도하지 않은 것은 실패가 아니다(사유가 다르다). 합성 시세를 지어내지도 않는다(막힌 분석은 '사용 불가 + 사유').

★이 파일이 말하지 않는 것★ — 운영에서 야후가 답하는 값의 품질 · 키가 있어야 도는 데몬 · 수동 수집 라우트.
`fetch_equity_snapshot` 은 야후를 쓰지 않을 때 합성 스냅샷을 만든다(운영에서도 — 이 묶음이 고치지 않은 기존 동작이며 HISTORY 에 적었다).
"""
from __future__ import annotations

import asyncio
import inspect
import os

import pandas as pd
import pytest

REASON_WORDS = ("합성 데이터 모드", "내려받지 않습니다")
#: 화면에 그대로 실릴 수 있는 문장이다 — 개발자 낱말·환경변수 이름·제공자 라이브러리 이름을 싣지 않는다(용어집 §6).
FORBIDDEN_IN_REASON = ("mock", "Mock", "KIS_USE_MOCK", "yfinance", "yf.")


def _frame(n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = pd.Series(range(100, 100 + n), index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Adj Close": close, "Volume": 1000.0}, index=idx)


@pytest.fixture
def yahoo(monkeypatch):
    """야후 내려받기를 가짜로 바꾸고 부른 횟수를 센다 — 세 자리 모두 `yfinance.download` 한 함수를 지난다."""
    import yfinance

    import src.data_loader as dl
    calls: list[str] = []

    def fake(ticker, *a, **k):
        calls.append(ticker if isinstance(ticker, str) else ",".join(ticker))
        return _frame()

    class FakeTicker:
        """`yf.Ticker(t).info` 도 야후로 나간다 — 내려받기와 같이 가짜로 바꾸고 센다(시험이 실제로 나가지 않게)."""

        def __init__(self, ticker, *a, **k):
            calls.append(f"Ticker:{ticker}")
            self.fast_info = {}
            self.info = {}

    monkeypatch.setattr(yfinance, "download", fake)
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    monkeypatch.setattr(dl.yf, "download", fake)
    # 재시도 대기가 있으면 시험이 느려질 뿐 아니라 '시도했다'는 뜻이다 — 부르면 바로 드러나게.
    monkeypatch.setattr(dl.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError(f"대기했다({s}초) — 시도하지 않아야 한다")))
    return calls


def _mode(monkeypatch, value: str | None):
    if value is None:
        monkeypatch.delenv("KIS_USE_MOCK", raising=False)
    else:
        monkeypatch.setenv("KIS_USE_MOCK", value)


# ── ① MarketDataLoader ──────────────────────────────────────────────────────

def test_mock_mode_loader_does_not_download_and_says_why(monkeypatch, yahoo):
    import src.data_loader as dl
    _mode(monkeypatch, "1")
    with pytest.raises(dl.MarketDataBlockedInMock) as e:
        dl.MarketDataLoader("AAPL", "2024-01-01", "2025-01-01").fetch_prices()
    assert yahoo == []
    msg = str(e.value)
    assert all(w in msg for w in REASON_WORDS) and not any(w in msg for w in FORBIDDEN_IN_REASON), msg


def test_real_mode_loader_downloads(monkeypatch, yahoo):
    """★짝★ — 운영에서는 내려받는다(늘 막는 구현이 아니다)."""
    import src.data_loader as dl
    _mode(monkeypatch, "0")
    prices = dl.MarketDataLoader("AAPL", "2024-01-01", "2025-01-01").fetch_prices()
    assert yahoo == ["AAPL"] and len(prices) == 300


@pytest.mark.parametrize("value", ["true", "01", " 1", "yes", "0", ""])
def test_the_gate_is_exactly_one(monkeypatch, yahoo, value):
    """정확히 `"1"` 일 때만 mock 이다 — 그 밖의 값은 운영이고 내려받는다."""
    import src.data_loader as dl
    _mode(monkeypatch, value)
    dl.MarketDataLoader("AAPL", "2024-01-01", "2025-01-01").fetch_prices()
    assert yahoo == ["AAPL"]


def test_an_unset_gate_is_mock(monkeypatch, yahoo):
    import src.data_loader as dl
    _mode(monkeypatch, None)
    with pytest.raises(dl.MarketDataBlockedInMock):
        dl.MarketDataLoader("AAPL", "2024-01-01", "2025-01-01").fetch_returns()
    assert yahoo == []


def test_not_trying_is_not_a_download_failure(monkeypatch, yahoo):
    """시도하지 않은 것(mock)과 시도했다가 못 받은 것(운영)은 다른 예외·다른 문장이다 — 둘 다 `ValueError` 라 기존 호출자는 그대로 돈다."""
    import src.data_loader as dl
    _mode(monkeypatch, "0")
    monkeypatch.setattr(dl.yf, "download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    with pytest.raises(ValueError) as failed:
        dl.MarketDataLoader("NOPE", "2024-01-01", "2025-01-01").fetch_prices()
    assert not isinstance(failed.value, dl.MarketDataBlockedInMock) and "No data found" in str(failed.value)
    assert issubclass(dl.MarketDataBlockedInMock, ValueError)


def test_mock_mode_vix_is_an_empty_series_without_a_download(monkeypatch, yahoo):
    """VIX 는 보조 피처라 못 받으면 빈 계열이다(기존 계약) — mock 에서도 같고, 내려받지 않는다."""
    import src.data_loader as dl
    _mode(monkeypatch, "1")
    vix = dl.MarketDataLoader("AAPL", "2024-01-01", "2025-01-01").fetch_vix()
    assert vix.empty and yahoo == []


# ── 라우트 — 사유가 응답에 그대로 나온다 ──────────────────────────────────────

def _loader_routes():
    """핸들러가 `MarketDataLoader(` 를 부르는 라우트 — 소스를 읽어 찾는다(새 라우트가 생기면 저절로 든다)."""
    import main_api

    from tests.route_walk import flat_routes
    out = []
    for r in flat_routes(main_api.app):
        ep = getattr(r, "endpoint", None)
        if ep is None:
            continue
        try:
            src = inspect.getsource(ep)
        except (OSError, TypeError):
            continue
        if "MarketDataLoader(" in src:
            for m in sorted(getattr(r, "methods", None) or []):
                out.append((m, r.path))
    return sorted(set(out))


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("LIFECYCLE_DAEMONS", "0")
    import main_api
    from fastapi.testclient import TestClient
    return TestClient(main_api.app)


def test_the_route_scan_is_not_vacuous():
    """★공허한 분기 금지★ — 훑기가 실제로 라우트를 찾는다(못 찾으면 아래 시험이 아무것도 안 보고 통과한다)."""
    paths = {p for _, p in _loader_routes()}
    assert {"/calculate-var", "/strategy-backtest", "/efficient-frontier", "/lstm-forecast", "/dcc-garch"} <= paths, sorted(paths)


def test_mock_mode_routes_answer_unavailable_with_the_reason(monkeypatch, yahoo, client):
    """mock: 야후 시세가 필요한 분석은 '사용 불가 + 사유'다 — 뭉뚱그린 500 이 아니고, 내려받지도 않는다."""
    _mode(monkeypatch, "1")
    bad = []
    for method, path in _loader_routes():
        r = client.request(method, path, json={})
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        if r.status_code != 503 or not isinstance(detail, str) or not all(w in detail for w in REASON_WORDS):
            bad.append((method, path, r.status_code, str(detail)[:80]))
    assert bad == [] and yahoo == []


def test_real_mode_routes_are_not_blocked(monkeypatch, yahoo, client):
    """★짝★ — 운영에서는 막지 않는다. 빈 본문이라 입력 검증(422)에서 멈춘다 — 503 이 아니다."""
    _mode(monkeypatch, "0")
    blocked = [(m, p) for m, p in _loader_routes() if client.request(m, p, json={}).status_code == 503]
    assert blocked == []


def test_real_mode_route_computes_from_the_download(monkeypatch, yahoo, client):
    """★짝★ — 운영에서 실제로 계산까지 간다(게이트가 라우트를 망가뜨리지 않았다)."""
    _mode(monkeypatch, "0")
    r = client.post("/rolling-sharpe", json={"ticker": "AAPL", "start_date": "2024-01-01", "end_date": "2025-03-01"})
    assert r.status_code == 200 and yahoo == ["AAPL"], r.text[:200]


def test_a_route_that_needs_no_market_download_is_not_blocked_in_mock(monkeypatch, client):
    """★짝★ — 야후가 필요 없는 라우트는 mock 에서도 그대로다(라우터째 막지 않았다)."""
    _mode(monkeypatch, "1")
    assert client.get("/frtb-lh-map").status_code == 200


# ── ② 해외 지수 토큰 ─────────────────────────────────────────────────────────

@pytest.fixture
def tokens():
    import src.kis_strategies.factor_tokens as ft
    saved = (dict(ft._market_cache), dict(ft._macro_failures))
    ft._market_cache.clear()
    ft._macro_failures.clear()
    yield ft
    ft._market_cache.clear()
    ft._market_cache.update(saved[0])
    ft._macro_failures.clear()
    ft._macro_failures.update(saved[1])


def test_mock_mode_foreign_index_is_unavailable_with_the_reason(monkeypatch, yahoo, tokens):
    _mode(monkeypatch, "1")
    assert tokens._market_df("DOW지수") is None and yahoo == []
    reason = tokens.macro_availability()["unavailable"]["market:DOW지수"]["reason"]
    assert all(w in reason for w in REASON_WORDS) and not any(w in reason for w in FORBIDDEN_IN_REASON), reason


def test_real_mode_foreign_index_downloads(monkeypatch, yahoo, tokens):
    """★짝★ — 운영에서는 받아온다."""
    _mode(monkeypatch, "0")
    df = tokens._market_df("DOW지수")
    assert df is not None and list(df.columns) == ["open", "high", "low", "close", "volume"] and yahoo == ["^DJI"]
    assert "market:DOW지수" not in tokens.macro_availability()["unavailable"]


def test_mock_mode_domestic_index_still_loads_from_the_local_loader(monkeypatch, yahoo, tokens):
    """★짝★ — 국내 지수는 야후가 아니라 일봉 로더를 지난다. mock 에서도 막지 않는다(해외 가지만 막는다)."""
    import src.data.ohlcv_loader as ol
    _mode(monkeypatch, "1")
    seen: list[str] = []

    def fake(sym, start, end, prefer="auto"):
        seen.append(sym)
        return _frame().rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]

    monkeypatch.setattr(ol, "load_ohlcv_unified", fake)
    assert tokens._market_df("KOSPI지수") is not None and seen == ["KOSPI"] and yahoo == []


# ── ③ 시장 스냅샷 파이프라인(야후를 켠 경우) ─────────────────────────────────

def test_mock_mode_snapshot_pipeline_does_not_download_even_when_opted_in(monkeypatch, yahoo):
    import src.screener_pipeline as sp
    _mode(monkeypatch, "1")
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    rows = asyncio.run(sp.fetch_equity_snapshot())
    assert yahoo == [] and len(rows) > 0


def test_real_mode_snapshot_pipeline_downloads_when_opted_in(monkeypatch, yahoo):
    """★짝★ — 운영에서 켜면 받아온다."""
    import src.screener_pipeline as sp
    _mode(monkeypatch, "0")
    monkeypatch.setattr(sp, "USE_YFINANCE", True)
    monkeypatch.setattr(sp, "EQUITY_TICKERS", ["AAPL", "MSFT"])
    asyncio.run(sp.fetch_equity_snapshot())
    assert "AAPL,MSFT" in yahoo and "Ticker:AAPL" in yahoo, yahoo
