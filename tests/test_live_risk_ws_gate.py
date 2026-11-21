"""실시간 위험 웹소켓(`/ws/live-risk/{ticker}`)은 ★운영에서 값을 지어내지 않는다★ (2026-11-14 · 합성값 전수 감사 §3)

## 무엇이 문제였나

이 웹소켓은 종목과 무관하게 75,000원에서 시작하는 난수 걸음 · 고정 수량 1,333주 · 난수 VaR 를 1초마다 내보냈다.
게이트도 라벨도 없었고, 한도를 넘으면 "VaR 한도 초과 — 자동 헤지 신호 발생"이라는 문장까지 붙였다.
관측(운영 게이트): `000660` 을 물었는데 75,077원 · VaR 1,073,001원 · `breach: true` · 경고 문장.

둘째 결함: 설정(`trading_config`)에 `auto_mode`·`var_limit` 이 처음에는 없다(토글 라우트가 불려야 생긴다).
그래서 토글 전에는 첫 전송 전에 `KeyError` 로 끝나고, 연결은 받은 채 아무것도 보내지 않았다.

## 이 파일이 거는 계약

① 운영 — 수치를 보내지 않는다. 사유를 한 번 보내고 닫는다. 난수 함수는 불리지 않는다.
② mock — 그대로 보내되 ★합성이라고 적는다★(짝).
③ 설정 키가 없어도 mock 흐름이 끊기지 않는다.
④ 한도 판정은 설정이 있을 때만 한다(짝: 넘으면 경고 · 꺼져 있으면 없음).

## 왜 소켓을 직접 열지 않는가

처리기를 가짜 소켓으로 부른다. 고치기 전 동작이 '아무것도 보내지 않고 끝남'이라, 진짜 클라이언트로 받으면
시험이 실패하지 않고 ★멈춘다★(받기에 시한이 없다) — 회귀가 CI 를 세우는 시험은 쓰지 않는다.
경로가 라우터에 걸려 있는지는 라우트 표로 따로 본다.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from starlette.websockets import WebSocketDisconnect

import src.api.system_routes as sr

NUMERIC_KEYS = ("price", "portfolio_value", "intraday_var", "var_limit", "breach", "alert")


class FakeSocket:
    """처리기가 쓰는 만큼의 웹소켓 — `limit` 번 보내면 상대가 끊은 것으로 한다(흐름이 끝없이 돌지 않게)."""

    def __init__(self, limit: int = 3):
        self.limit, self.sent, self.accepted, self.closed = limit, [], False, False

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        assert self.accepted and not self.closed, "받기 전이거나 닫은 뒤에 보냈다"
        self.sent.append(payload)
        if len(self.sent) >= self.limit:
            raise WebSocketDisconnect()

    async def close(self, code: int = 1000):
        self.closed = True


def _run(ticker: str = "000660", limit: int = 3) -> FakeSocket:
    ws = FakeSocket(limit)
    asyncio.run(asyncio.wait_for(sr.live_risk(ws, ticker), timeout=10))
    return ws


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    """1초 대기를 0초로 — 이 모듈이 보는 `asyncio` 만 바꾼다(전역 `asyncio.sleep` 은 건드리지 않는다)."""
    real_sleep = asyncio.sleep
    monkeypatch.setattr(sr, "asyncio", types.SimpleNamespace(sleep=lambda _s: real_sleep(0)))


@pytest.fixture
def config(monkeypatch):
    """토글 라우트가 불리기 전의 설정 — 판정 키가 없다."""
    cfg = {"auto_trading": False, "risk_limit": 0.02, "max_position": 1_000_000}
    monkeypatch.setattr(sr, "trading_config", cfg)
    return cfg


@pytest.fixture
def rng_calls(monkeypatch):
    calls: list[str] = []
    real = sr.random

    def wrap(name):
        def f(*a, **k):
            calls.append(name)
            return getattr(real, name)(*a, **k)
        return f

    monkeypatch.setattr(sr, "random", types.SimpleNamespace(normalvariate=wrap("normalvariate"), uniform=wrap("uniform")))
    return calls


def test_the_route_is_still_mounted_at_the_same_path():
    assert [r.path for r in sr.router.routes if getattr(r, "endpoint", None) is sr.live_risk] == ["/ws/live-risk/{ticker}"]


# ══ ① 운영 — 지어내지 않는다 ══════════════════════════════════════════════════

def test_prod_sends_a_reason_and_no_numbers(config, rng_calls, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    ws = _run("000660")
    assert len(ws.sent) == 1, f"운영에서 보낸 메시지 수: {len(ws.sent)}"
    first = ws.sent[0]
    assert first["available"] is False and first["is_mock"] is False
    assert first["reason"] == "no_feed" and first["message"]
    assert first["ticker"] == "000660"
    assert [k for k in NUMERIC_KEYS if k in first] == [], "운영 응답에 수치·경고 칸이 실렸다"
    assert rng_calls == [], "운영에서 난수 함수를 불렀다"


def test_prod_closes_after_the_reason(config, monkeypatch):
    """사유만 보내고 흐름을 열어 두면 받는 쪽은 '값이 곧 온다'고 읽는다 — 닫는다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert _run().closed is True


# ══ ② mock — 보내되 합성이라고 적는다(짝) ═════════════════════════════════════

def test_mock_stream_is_labelled_synthetic_on_every_message(config, rng_calls, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    ws = _run(limit=3)
    assert len(ws.sent) == 3
    for m in ws.sent:
        assert m["available"] is True and m["is_mock"] is True and "합성" in m["message"]
        assert isinstance(m["price"], float) and m["intraday_var"] > 0
    assert rng_calls, "mock 인데 난수 함수를 부르지 않았다 — 시험이 공허하다"


# ══ ③ 설정 키가 없어도 끊기지 않는다 ══════════════════════════════════════════

def test_mock_stream_survives_a_config_without_the_limit_keys(config, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert "auto_mode" not in config and "var_limit" not in config
    ws = _run("005930", limit=2)
    assert len(ws.sent) == 2, "판정 키가 없다고 흐름이 끊겼다"
    m = ws.sent[0]
    assert m["breach"] is False and "alert" not in m
    assert m["var_limit"] is None, "없는 한도를 숫자로 채우지 않는다"


# ══ ④ 한도 판정 ═══════════════════════════════════════════════════════════════

def test_mock_breach_alert_needs_both_the_switch_and_the_limit(config, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    config.update({"auto_mode": True, "var_limit": 1.0})          # 어떤 VaR 도 넘는 한도
    m = _run("005930", limit=1).sent[0]
    assert m["breach"] is True and "alert" in m
    assert m["is_mock"] is True, "경고가 붙은 메시지일수록 합성 표기가 빠지면 안 된다"


def test_mock_no_alert_when_the_switch_is_off(config, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    config.update({"auto_mode": False, "var_limit": 1.0})
    m = _run("005930", limit=1).sent[0]
    assert m["breach"] is False and "alert" not in m
