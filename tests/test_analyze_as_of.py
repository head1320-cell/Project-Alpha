"""as_of — 최적화 경로의 데이터 절단일 (P1-A)
==============================================================================
실측된 결함: `allocation_routes.py:183` 이 `end = date.today()` 였고 **그 사실이
어디에도 기록되지 않았다**. 그래서 어제 만든 런을 오늘 다시 돌리면 다른 구간으로
계산되는데, 런만 보고는 그것이 "모델이 바뀐 것"인지 "데이터가 하루 늘어난 것"인지
구분할 수 없었다. 재현성이 이 플랫폼의 1번 원칙인데 그 좌표가 없었다.

★1·2 는 반드시 짝으로 읽어야 한다★
  1 만 있으면 `as_of` 를 **완전히 무시하는** 구현도 통과한다(항상 오늘로 돌리므로
  두 번의 결과가 같다). 2 가 "다르게 주면 실제로 다른 구간을 쓴다" 를 잠근다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

TICKERS = ["005930", "000660", "035420"]


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _analyze(client, **over):
    body = {"tickers": TICKERS, "model": "mvo", "lookback_days": 250, "mc_paths": 100}
    body.update(over)
    r = client.post("/api/v1/allocation/analyze", json=body)
    return r


def _ok(client, **over) -> dict:
    r = _analyze(client, **over)
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("error"):
        pytest.skip(f"이 환경에는 시세가 없다: {body.get('message')}")
    return body


# ── 1. 같은 as_of 로 두 번 → 같은 최적 비중 ─────────────────────────────────
def test_the_same_as_of_gives_the_same_weights(client):
    """이게 거짓이면 '재현' 이라는 말 자체가 성립하지 않는다."""
    pin = (date.today() - timedelta(days=7)).isoformat()
    a = _ok(client, as_of=pin)
    b = _ok(client, as_of=pin)
    assert a["weights"]["optimized"] == b["weights"]["optimized"]
    assert a["coverage"]["end"] == b["coverage"]["end"]


# ── 2. ★다른 as_of → 실제로 다른 구간★ (1번의 짝) ──────────────────────────
def test_a_different_as_of_actually_moves_the_data_window(client):
    """1번만 있으면 `as_of` 를 무시하는 구현도 통과한다 — 여기서 잠근다."""
    near = (date.today() - timedelta(days=7)).isoformat()
    far = (date.today() - timedelta(days=200)).isoformat()
    a = _ok(client, as_of=near)
    b = _ok(client, as_of=far)

    assert a["coverage"]["as_of_effective"] == near
    assert b["coverage"]["as_of_effective"] == far
    # 관측 마지막 날은 절단일보다 뒤일 수 없다 (휴장일이면 앞선다).
    assert a["coverage"]["end"] <= near
    assert b["coverage"]["end"] <= far
    assert b["coverage"]["end"] < a["coverage"]["end"], \
        "as_of 를 200일 당겼는데 데이터 구간이 그대로다 — as_of 가 무시되고 있다"


# ── 3. as_of 를 안 줘도 서버가 절단일을 스탬프한다 ──────────────────────────
def test_an_unpinned_run_still_records_the_cutoff_the_server_used(client):
    """UI 를 바꾸지 않고 이후의 모든 런을 재현 가능하게 만드는 것이 이 스탬프다."""
    body = _ok(client)
    cov = body["coverage"]
    assert cov["as_of_requested"] is None, "고정하지 않았는데 고정했다고 적었다"
    assert cov["as_of_effective"] == date.today().isoformat()


def test_a_pinned_run_records_that_it_was_pinned(client):
    """`as_of_requested` 가 `None` 인 것과 값이 있는 것은 다른 사실이다."""
    pin = (date.today() - timedelta(days=7)).isoformat()
    cov = _ok(client, as_of=pin)["coverage"]
    assert cov["as_of_requested"] == pin
    assert cov["as_of_effective"] == pin


# ── 4. 미래 as_of 는 고정이 아니라 고정한 척이다 ────────────────────────────
def test_a_future_as_of_is_refused_not_silently_clamped(client):
    future = (date.today() + timedelta(days=30)).isoformat()
    r = _analyze(client, as_of=future)
    assert r.status_code == 422, r.text
    assert "미래" in r.text


def test_a_malformed_as_of_is_refused(client):
    r = _analyze(client, as_of="2026/08/13")
    assert r.status_code == 422, r.text


# ── 5. 백테스트 경로도 같은 좌표를 갖는다 ───────────────────────────────────
def test_backtest_takes_as_of_too(client):
    pin = (date.today() - timedelta(days=7)).isoformat()
    r = client.post("/api/v1/allocation/backtest", json={
        "tickers": TICKERS, "model": "mvo", "lookback_days": 300, "as_of": pin})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("error"):
        pytest.skip(f"이 환경에는 시세가 없다: {body.get('message')}")
    assert body["coverage"]["as_of_effective"] == pin
