"""ingest-doctor — 적재 소스(DART/KRX/KIS) 실도달 진단. 키 없는 환경은 정직 안내."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from main_api import ingest_doctor  # noqa: E402


def test_doctor_shape_without_keys(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = ingest_doctor()
    assert set(out.keys()) >= {"dart", "krx", "kis", "dart_usage"}
    for src in ("dart", "krx", "kis"):
        assert out[src]["ok"] is False               # 키 없음/mock — 정직하게 False
        assert out[src]["message"]                    # 원인 문구 존재
    assert "미설정" in out["dart"]["message"]
    assert "미설정" in out["krx"]["message"]
    assert "mock" in out["kis"]["message"].lower() or "미설정" in out["kis"]["message"]
