"""연구 기록의 상태는 넷이다 — 빈 값 ≠ 삭제됨 ≠ 저장소 장애 ≠ 네트워크 (R0-S)
==============================================================================
실측된 결함: 같은 사실을 뭉개는 층이 **셋** 겹쳐 있었다.

  1. `research_runs.py:154`     `except: return []`      저장소 장애 = 빈 목록
  2. `research_routes.py:53`    `{"runs": […]}`          가용성 정보 없음
  3. `ResearchRunsPanel.tsx:98` `.catch(() => null)`     네트워크 오류 = null
     → `:178` 이 그 결과를 **"기록된 런 없음"** 으로 렌더

연구 기록이 **사라진 것처럼** 보이는 것은 이 플랫폼에서 가장 겁나는 화면이다. 한 층만
고치면 위/아래에서 다시 뭉개지므로 셋을 함께 고치고, 여기서는 1·2 를 잠근다.

★핵심은 "장애를 빈 목록으로 보고하지 않는다" 와 "빈 목록은 여전히 빈 목록이다" 가
**둘 다** 참이어야 한다는 것이다★ 하나를 만족시키려고 다른 하나를 없애면 안 된다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _break_storage(monkeypatch):
    """저장소를 죽인다 — 엔진 획득 자체가 실패하는 형태(드라이버 부재와 같은 모양)."""
    import src.data.research_runs as rr

    def boom():
        raise RuntimeError("storage down (test)")

    monkeypatch.setattr(rr, "_engine", boom)


# ── 1. ★저장소 장애는 빈 목록이 아니다★ ─────────────────────────────────────
def test_storage_failure_is_reported_not_returned_as_an_empty_list(client, monkeypatch):
    _break_storage(monkeypatch)
    r = client.get("/api/v1/research-runs")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False, "저장소가 죽었는데 정상으로 답했다"
    assert body["reason"], "사유 없이 막으면 화면이 무엇을 말할지 알 수 없다"
    assert body["runs"] == []          # 키는 유지 — 기존 소비자가 깨지지 않는다


def test_empty_list_is_still_an_empty_list(client):
    """1번을 만족시키려고 빈 상태를 없애면 안 된다 — 기록이 없는 것도 하나의 사실이다."""
    r = client.get("/api/v1/research-runs", params={"kind": "no_such_kind_zzz"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True, "정상인데 장애로 답했다"
    assert body["runs"] == []
    assert not body.get("reason")


# ── 2. 단건 조회: 없음(404)과 장애(503)는 다른 사실이다 ─────────────────────
def test_missing_run_is_404(client):
    r = client.get("/api/v1/research-runs/rr_does_not_exist")
    assert r.status_code == 404


def test_storage_failure_on_single_read_is_503_not_404(client, monkeypatch):
    """404 로 답하면 화면은 "그 런은 삭제됐다" 고 말하게 된다 — 기록은 멀쩡한데."""
    _break_storage(monkeypatch)
    r = client.get("/api/v1/research-runs/rr_anything")
    assert r.status_code == 503, r.text


# ── 3. 저장 실패는 이미 정직하다 — 회귀만 막는다 ────────────────────────────
def test_recording_failure_still_says_it_was_not_recorded(client, monkeypatch):
    _break_storage(monkeypatch)
    r = client.post("/api/v1/research-runs",
                    json={"kind": "allocation_analyze", "inputs": {}, "outputs": {}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is False
    assert body["run_id"] is None
