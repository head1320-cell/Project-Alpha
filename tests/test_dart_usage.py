"""DART 사용량·쿼터 감지 — 사용한도(status 020) 도달을 UI에서 볼 수 있게."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.dart_client as dc  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _client(monkeypatch, payload):
    monkeypatch.setattr(dc, "_USAGE", dc._fresh_usage())
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: _Resp(payload))
    monkeypatch.setattr(dc, "_dart_cache_get", lambda k: None)   # 디스크 캐시 격리
    monkeypatch.setattr(dc, "_dart_cache_set", lambda k, v: None)
    c = dc.DARTClient.__new__(dc.DARTClient)  # __init__ 우회(키/네트워크 불필요)
    c.api_key = "test-key-0123456789"  # is_configured: len>10 필요
    c.timeout = 3
    c._last_call_time = 0.0
    return c


def test_success_counts_request(monkeypatch):
    c = _client(monkeypatch, {"status": "000", "list": []})
    assert c._get("list.json", {}) is not None
    u = dc.dart_usage()
    assert u["requests"] == 1 and u["quota_exhausted"] is False


def test_quota_020_sets_flag(monkeypatch):
    c = _client(monkeypatch, {"status": "020", "message": "사용한도를 초과하였습니다."})
    assert c._get("list.json", {}) is None
    u = dc.dart_usage()
    assert u["requests"] == 1
    assert u["errors"].get("020") == 1
    assert u["quota_exhausted"] is True
    assert "한도" in (u["last_error"] or {}).get("message", "")


def test_other_error_no_quota_flag(monkeypatch):
    c = _client(monkeypatch, {"status": "013", "message": "조회된 데이타가 없습니다."})
    assert c._get("list.json", {}) is None
    u = dc.dart_usage()
    assert u["errors"].get("013") == 1 and u["quota_exhausted"] is False
