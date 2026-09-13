"""AF4 — 무장 여부 표면과 ★`/status` 불변★.

운영 화면이 "킬스위치: 미발동" 만 보여 주면 안전망 넷이 서 있다고 읽힌다.
이 표면은 **무엇이 왜 불능인지** 말한다. 그리고 기존 `/status` 는 건드리지 않았다는
것을 골든으로 못 박는다 — 관리 화면이 그 응답을 그리고 있다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod

_SECRET = "af-readiness-test-secret-0123456789abcd"
_ALL_TRIGGERS = {"auto_dd", "auto_cb", "auto_risk", "auto_api"}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()

    import src.api.stage13_routes as stage13
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)

    from src.app_factory import create_app
    # ★모듈 스코프가 아니고, `with` 도 쓰지 않는다★(AD 의 교훈)
    c = TestClient(create_app())
    c.post("/api/v1/live/init-schema", headers=_admin(c))
    yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _admin(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "frm123!"}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ── 무장 표면 ───────────────────────────────────────────────────────────────

def test_readiness_requires_login(client):
    assert client.get("/api/v1/live/kill-switch/readiness").status_code == 401


def test_readiness_covers_every_trigger(client):
    """★전수★ — 트리거가 어느 목록에도 없으면 조용히 사라진 것이다."""
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    covered = {t["trigger"] for t in body["armed"]} | {
        t["trigger"] for t in body["inoperable"]}
    assert covered == _ALL_TRIGGERS


def test_the_inoperable_triggers_say_why(client):
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    assert body["inoperable"], "이 환경에서 전부 무장일 리 없다"
    for row in body["inoperable"]:
        assert row["reason"], f"{row['trigger']} 에 사유가 없다"


def test_auto_api_is_named_as_inoperable_in_this_repository(client):
    """★이 저장소에는 API 실패 횟수를 기록하는 코드가 없다★ — 그 사실이 보인다."""
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    names = {t["trigger"]: t["reason"] for t in body["inoperable"]}
    assert "auto_api" in names
    assert "기록" in names["auto_api"]


def test_the_note_says_lowering_thresholds_would_not_help(client):
    """★임계값 문제가 아니라 재료 문제다★ — 운영자가 엉뚱한 곳을 고치지 않도록."""
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    assert "임계" in body["note"]


def test_the_summary_counts_both_sides(client):
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    assert "무장" in body["summary"] and "불능" in body["summary"]


def test_a_failed_account_fetch_is_reported_not_swallowed(client, monkeypatch):
    """★변이 n 을 죽인다★ — 조회가 죽으면 빈 응답이 "다 무장됨" 으로 읽힌다.

    실패했다는 사실이 `account_state_reason` 으로 나와야, 운영자가 "불능 넷" 을
    보고 *"재료가 없다"* 와 *"조회가 죽었다"* 를 가릴 수 있다.
    """
    import src.api.stage13_routes as stage13

    def _boom(self):
        raise RuntimeError("브로커 연결 실패(테스트)")

    executor = stage13.get_executor()
    monkeypatch.setattr(type(executor), "_fetch_account_state", _boom, raising=False)

    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    assert body["account_state_reason"], "조회 실패를 삼켰다"
    assert "조회" in body["account_state_reason"]
    # 그리고 여전히 네 트리거를 덮는다 — 빈 응답이 아니다.
    covered = {t["trigger"] for t in body["armed"]} | {
        t["trigger"] for t in body["inoperable"]}
    assert covered == _ALL_TRIGGERS


def test_a_healthy_fetch_reports_no_reason(client):
    """★짝★ — 언제나 사유를 채우는 구현을 배제한다."""
    body = client.get("/api/v1/live/kill-switch/readiness",
                      headers=_admin(client)).json()
    assert body["account_state_reason"] is None


# ── ★`/status` 를 건드리지 않았다★ ────────────────────────────────────────

def test_the_status_response_keys_are_unchanged(client):
    """★골든★ — 관리 화면이 이 응답을 그린다. 키가 늘면 그것도 변경이다."""
    body = client.get("/api/v1/live/kill-switch/status").json()
    assert set(body) == {"is_active", "active_event"}


def test_the_status_route_is_still_open(client):
    """계좌 조회를 붙이지 않았으므로 여전히 토큰 없이 답한다."""
    assert client.get("/api/v1/live/kill-switch/status").status_code == 200


# ── ★감사 기록이 반만 판 것을 청산으로 적지 않는다★ ─────────────────────

def test_a_gradual_kill_records_no_closed_positions(client):
    """★AF 의 핵심을 표면에서 확인한다★ — mock 계좌에 포지션이 없으면 0 이고,
    있더라도 gradual 은 `n_positions_closed` 를 올리지 않는다."""
    res = client.post("/api/v1/live/kill-switch/trigger",
                      json={"reason": "AF 테스트 발동입니다",
                            "liquidation_mode": "gradual"},
                      headers=_admin(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["n_positions_closed"] == 0
    assert "liquidation" in body
    assert body["liquidation"]["mode"] == "gradual"


def test_the_trigger_response_declares_whether_liquidation_completed(client):
    res = client.post("/api/v1/live/kill-switch/trigger",
                      json={"reason": "AF 테스트 발동입니다",
                            "liquidation_mode": "gradual"},
                      headers=_admin(client))
    body = res.json()
    assert "liquidation_complete" in body
    assert isinstance(body["liquidation_complete"], bool)


def test_a_hold_mode_kill_does_not_claim_any_liquidation(client):
    """★짝★ — 청산하지 않기로 한 발동이 '완료' 로 읽히지 않는지."""
    res = client.post("/api/v1/live/kill-switch/trigger",
                      json={"reason": "AF 테스트 발동입니다",
                            "liquidation_mode": "hold"},
                      headers=_admin(client))
    body = res.json()
    assert body["n_positions_closed"] == 0
    assert body["liquidation"]["partial"] == []
