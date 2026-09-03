"""status 폴링이 왜 실패했는지 ★분류해서★ 말한다 (③)

## 무엇이 문제였나 — 이것은 수정이 아니라 관측이다

사용자가 보낸 화면에 **"연결이 불안정합니다 — 재시도 중"** 이 떠 있었다. 그것은
`RunMonitor` 의 `statusQ.failureCount >= 3` — 즉 `GET /runs/{id}/status` 가 **3회
연속** 실패했다는 뜻이다. 그런데 지금은 그 실패의 사유가 **서버 로그에만** 있고
응답에는 없다. 그래서 다음에 같은 화면이 나와도 원인을 말할 수 없다.

★고치기 전에 재현한다★ — 이 컨테이너에는 `daily_prices` 도 KIS 키도 Postgres 도
없어(SQLite 로 폴백한다) 사용자의 실패를 **재현하지 못했다**. 그래서 이 슬라이스는
원인을 고치지 않는다. 후보 가설을 **다음 번에 가를 수 있게** 만들 뿐이다:

  ⑴ 커넥션 풀 고갈 — `pool_size=5 + overflow=10`, `pool_timeout` 기본 30초.
     30초는 1초 폴링 주기보다 길어 요청이 쌓인다.
  ⑵ SQLite 폴백 시 워커의 진행 UPDATE 와 API 의 SELECT 가 **쓰기 락**에서 만난다.

## ★사유는 분류해서 내보낸다 — 원문을 그대로 실으면 안 된다★

DB 예외 문자열에는 접속 URL(자격증명 포함)이 섞일 수 있다. CLAUDE.md 의
"API 키를 채팅·이슈·로그에 노출 금지" 가 여기에도 걸린다. 그래서 서버가
**분류만** 실어 보내고 원문은 로그에 남긴다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import classify_store_failure, router  # noqa: E402

URL = "/api/v1/backtest/runs/bt_x/status"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _fail_with(monkeypatch, message: str):
    def _boom(run_id, strict=False):
        if strict:
            raise br.BacktestStoreError(message)
        return None
    monkeypatch.setattr(br, "get_status", _boom)


# ── 분류 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg,expected", [
    ("QueuePool limit of size 5 overflow 10 reached, connection timed out", "pool_exhausted"),
    ("(sqlite3.OperationalError) database is locked", "store_locked"),
    ("could not translate host name \"db\" to address", "store_unreachable"),
    ("무언가 처음 보는 오류", "unknown"),
])
def test_each_candidate_cause_gets_its_own_label(msg, expected):
    """★가설을 가를 수 있어야 관측이다★ 전부 'unknown' 이면 아무것도 안 한 것이다."""
    assert classify_store_failure(msg) == expected


def test_the_response_carries_the_label(client, monkeypatch):
    _fail_with(monkeypatch, "QueuePool limit of size 5 overflow 10 reached, connection timed out")
    r = client.get(URL)
    assert r.status_code == 503
    d = r.json()["detail"]
    assert d["cause"] == "pool_exhausted", d
    assert d["message"], "사람이 읽을 문구가 없다"


def test_the_response_never_leaks_the_raw_store_error(client, monkeypatch):
    """★자격증명이 섞일 수 있는 원문을 클라이언트로 내보내지 않는다★

    이것이 '짝' 이다 — 위 테스트가 "사유를 말하라" 이고, 이것이 "원문은 말하지
    말라" 다. 둘 중 하나만 있으면 반대쪽으로 틀린 구현이 통과한다.
    """
    raw = "postgresql://alpha:s3cr3t-pw@db:5432/alpha — QueuePool limit reached"
    _fail_with(monkeypatch, raw)
    body = client.get(URL).text
    for leak in ("s3cr3t-pw", "postgresql://", "alpha:s3cr3t", "5432"):
        assert leak not in body, f"원문이 응답에 샜다: {leak!r}"


def test_an_unknown_cause_is_not_dressed_up_as_a_known_one(client, monkeypatch):
    """★미상은 분류가 아니다★ 모르면 'unknown' 이라고 적는다 — 그럴듯한 라벨을
    붙이면 다음 사람이 잘못된 곳을 판다."""
    _fail_with(monkeypatch, "완전히 새로운 무언가")
    d = client.get(URL).json()["detail"]
    assert d["cause"] == "unknown"
    assert "확인" in d["message"] or "알 수 없" in d["message"], d


def test_a_missing_run_is_still_a_plain_404(client, monkeypatch):
    """분류를 붙이면서 기존 404 규약을 깨지 않는다 — 프런트가 '만료된 링크'를
    이 경로로 판정한다."""
    monkeypatch.setattr(br, "get_status", lambda run_id, strict=False: None)
    assert client.get(URL).status_code == 404
