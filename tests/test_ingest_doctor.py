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


def test_doctor_kis_uses_factory_not_bare_constructor(monkeypatch):
    """실모드 KIS 진단이 get_kis_client() 팩토리를 쓰는지 — KISClient() 직접 호출은
    credentials 인자 누락으로 TypeError(관측된 버그)."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setenv("KIS_APP_KEY", "dummy-key")
    import src.execution.kis_client as kc

    class _FakeClient:
        def prewarm_token(self):
            return True

    monkeypatch.setattr(kc, "get_kis_client", lambda **k: _FakeClient())
    out = ingest_doctor()
    assert out["kis"]["ok"] is True                   # 팩토리 경유 → 예외 없이 정상


def test_doctor_kis_factory_failure_is_graceful(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setenv("KIS_APP_KEY", "dummy-key")
    import src.execution.kis_client as kc

    def _boom(**k):
        raise RuntimeError("토큰 발급 실패")

    monkeypatch.setattr(kc, "get_kis_client", _boom)
    out = ingest_doctor()
    assert out["kis"]["ok"] is False and "토큰 발급 실패" in out["kis"]["message"]
