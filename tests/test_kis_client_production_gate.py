"""운영에서는 ★mock 클라이언트를 돌려주지 않는다★

## 무엇이 문제였나 — 가드가 잘못된 계층에 있었다

`get_kis_client()` 는 `mock_allowed()` 를 올바르게 본다. 그런데 **그 다음에 두 번째
분기**가 있었다:

```python
    app_key = os.getenv("KIS_APP_KEY", "")
    if not app_key or not app_secret:
        logger.warning("KIS_APP_KEY/SECRET 미설정 → MockKISClient fallback")
        _kis_singleton = MockKISClient()      # ← 운영인데 mock 을 돌려준다
```

그래서 호출부가 `if mock_allowed(): return` 으로 성실히 막아도, **그 직후
`get_kis_client()` 를 부르면 mock 을 받는다.** 호출부 17곳 중 `MockKISClient` 를
직접 확인하는 곳은 6곳뿐이었다.

실제 노출 사례 — `src/data/market_data.py` 는 `mock_allowed()` 로 막은 **뒤**
`client.get_daily_ohlcv()` 를 부르는데, 그 client 가 mock 이면 `rng.gauss` 로 만든
**합성 일봉**(`date: "MOCK"`)을 받는다.

CLAUDE.md §6: *"운영에서는 합성값을 만들지 않습니다 — 실패하면 None/빈값 + 사유."*
mock 은 `KIS_USE_MOCK` 이 **정확히 `"1"`** 일 때만이다.

## 개발 환경은 조이지 않는다

`.env.example` 기본값이 `KIS_USE_MOCK=1` 이라 첫 분기에서 mock 이 나간다.
이 변경이 조이는 것은 **키 없이 운영 모드로 도는 경우**뿐이다 — 그리고 그때
합성값이 나가는 것이 바로 사고다.
"""
from __future__ import annotations

import os

import pytest

import src.execution.kis_client as kc


@pytest.fixture(autouse=True)
def _reset_singleton():
    """★싱글턴이 게이트를 무력화하지 않게★ 매 테스트마다 초기화한다.

    `_kis_singleton` 은 모듈 전역이라, 한 테스트가 만든 클라이언트가 다음 테스트로
    새어 나가면 이 파일 전체가 공허해진다.
    """
    kc._kis_singleton = None
    yield
    kc._kis_singleton = None


def _production(monkeypatch, *, keys: bool):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    if keys:
        monkeypatch.setenv("KIS_APP_KEY", "k" * 20)
        monkeypatch.setenv("KIS_APP_SECRET", "s" * 40)
    else:
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)


# ── 운영: 거절한다 ──────────────────────────────────────────────────────────

def test_production_without_credentials_refuses_instead_of_faking(monkeypatch):
    """★핵심★ 키가 없으면 mock 이 아니라 **사유가 담긴 예외**다."""
    _production(monkeypatch, keys=False)
    with pytest.raises(kc.KISCredentialsMissing) as ei:
        kc.get_kis_client()
    assert "KIS_APP_KEY" in str(ei.value), f"사유가 불충분하다: {ei.value}"


def test_the_refusal_never_hands_back_a_mock(monkeypatch):
    """★짝★ "예외를 던진다" 만 걸면, 던지고 나서 mock 을 캐시하는 구현도 통과한다."""
    _production(monkeypatch, keys=False)
    with pytest.raises(kc.KISCredentialsMissing):
        kc.get_kis_client()
    assert kc._kis_singleton is None, (
        f"거절해 놓고 mock 을 싱글턴에 심었다: {type(kc._kis_singleton).__name__}")


def test_a_graceful_caller_gets_none_and_a_reason(monkeypatch):
    """적재·보강 훅처럼 **열화가 맞는** 호출부를 위한 통로."""
    _production(monkeypatch, keys=False)
    client, reason = kc.try_kis_client()
    assert client is None
    assert reason and "KIS_APP_KEY" in reason, f"사유가 없다: {reason!r}"


def test_a_graceful_caller_still_gets_a_real_client_when_configured(monkeypatch):
    """★짝★ `try_` 가 **항상** None 을 주면 그것도 틀렸다."""
    _production(monkeypatch, keys=True)
    client, reason = kc.try_kis_client()
    assert client is not None and reason is None
    assert type(client).__name__ == "KISClient"


# ── 개발: 예전 그대로 ───────────────────────────────────────────────────────

def test_the_mock_mode_is_untouched(monkeypatch):
    """★짝 (변이 F6)★ 위 테스트만 걸면 "항상 예외" 구현도 통과한다.

    `KIS_USE_MOCK=1` 은 이 저장소의 **개발 기본값**이다(`.env.example`). 여기서
    예외가 나면 개발 환경 전체가 죽는다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    client = kc.get_kis_client()
    assert type(client).__name__ == "MockKISClient"
    got, reason = kc.try_kis_client()
    assert type(got).__name__ == "MockKISClient" and reason is None


@pytest.mark.parametrize("value", ["", "0", "true", "TRUE", "yes", "2", " 1"])
def test_only_exactly_one_enables_mock(monkeypatch, value):
    """★`KIS_USE_MOCK` 이 정확히 "1" 일 때만 mock★ — CLAUDE.md 불변식.

    "1 이 아니면 운영" 이므로, 이 값들에서는 키가 없으면 **거절**해야 한다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", value)
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    with pytest.raises(kc.KISCredentialsMissing):
        kc.get_kis_client()


# ── 소비자: 합성 일봉이 새지 않는다 ─────────────────────────────────────────

def test_market_data_does_not_return_synthetic_bars_in_production(monkeypatch):
    """★실제 노출 사례★ `market_data` 는 `mock_allowed()` 로 막은 **뒤**
    `get_kis_client()` 를 불렀다 — 그 client 가 mock 이면 난수 일봉이 들어온다."""
    _production(monkeypatch, keys=False)
    from src.data import market_data as md
    fn = getattr(md, "_real_kis_ohlcv", None)
    if fn is None:
        pytest.skip("이 저장소에 _real_kis_ohlcv 가 없다 — 경로가 바뀌었으면 재조준")
    got = fn("005930", days=200)
    assert got is None or len(got) == 0, (
        f"운영에서 합성 일봉이 나왔다: {type(got)} rows={0 if got is None else len(got)}")


def test_the_singleton_cannot_leak_a_mock_into_production(monkeypatch):
    """★싱글턴이 게이트를 우회하지 않는다★

    개발 모드에서 만든 mock 이 캐시된 채 운영으로 넘어가면, 그 프로세스는 계속
    합성값을 낸다. 실제로 이 저장소는 `uvicorn --workers 1` 이라 프로세스가 길다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert type(kc.get_kis_client()).__name__ == "MockKISClient"
    _production(monkeypatch, keys=False)
    with pytest.raises(kc.KISCredentialsMissing):
        kc.get_kis_client(force_reload=True)


# ── 열화가 맞는 자리는 사유를 돌려준다 ──────────────────────────────────────

def test_the_minute_bar_probe_degrades_with_a_reason(monkeypatch):
    """★진단 도구는 500 이 아니라 사유를 낸다★

    `probe_history` 는 mock 모드에서도 예외 대신 `note` 를 담은 행을 낸다. 키가
    없을 때도 같은 모양이어야 호출자가 분기하지 않는다 — 그래서 여기는
    `try_kis_client()` 를 쓴다.
    """
    _production(monkeypatch, keys=False)
    from src.data import minute_bars as mb
    rows = mb.probe_history("005930")
    assert rows, "진단이 빈 목록을 냈다 — 왜 못 하는지 말하지 않는다"
    assert all(r["bars"] is None for r in rows), "키가 없는데 봉 수를 지어냈다"
    assert all("KIS_APP_KEY" in (r.get("note") or "") for r in rows), (
        f"사유가 없다: {rows[0]}")


def test_the_intraday_collector_counts_the_failure_instead_of_crashing(monkeypatch):
    """★분봉 수집은 실패를 세고 계속한다★

    `_fetch_minute_bars` 는 감싸지 않은 채 클라이언트를 부르지만, 단 하나뿐인
    호출부가 `try/except` 로 잡아 `failed` 를 센다. 즉 예외가 **관측 가능한
    흔적**으로 남는다 — 조용한 실패가 아니다.
    """
    _production(monkeypatch, keys=False)
    from src.data import minute_bars as mb
    with pytest.raises(kc.KISCredentialsMissing):
        mb._fetch_minute_bars("005930", "2024-01-02")
