"""AC6 — ★CORS 의 `"*"` 가 사라졌다★ (로드맵 완료 판정의 넷째 조항).

`allow_origins=["*"]` 와 `allow_credentials=True` 는 **공존할 수 없는 조합**이다 —
브라우저가 거부하므로 지금까지 의도대로 동작한 적이 없고, 그럼에도 목록에 `"*"` 가
있다는 것은 "아무 출처나 허용" 이라는 **틀린 의도**가 코드에 적혀 있다는 뜻이다.
"""
from __future__ import annotations

import src.app_factory as factory
from src.app_factory import CORS_ORIGINS, resolve_cors_origins


def test_the_wildcard_is_gone():
    """★완료 판정★."""
    assert "*" not in CORS_ORIGINS


def test_the_wildcard_never_coexists_with_credentials():
    """불변식 — 자격 증명을 함께 보내는 설정에서 `"*"` 는 금지."""
    app = factory.create_app()
    cors = [m for m in app.user_middleware if "CORS" in str(m)]
    assert cors, "CORS 미들웨어가 없다"
    opts = cors[0].kwargs if hasattr(cors[0], "kwargs") else {}
    origins = opts.get("allow_origins", CORS_ORIGINS)
    if opts.get("allow_credentials"):
        assert "*" not in origins


def test_the_local_development_origins_survive():
    """★짝★ — 전부 지워서 통과시키는 구현을 배제한다."""
    assert "http://localhost:3000" in CORS_ORIGINS


def test_deployment_origins_come_from_the_environment(monkeypatch):
    """빌드 타임에 박지 않고 환경변수로 선언한다(프런트 규율과 같은 방향)."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS",
                       "https://alpha.example.com, https://admin.example.com")
    origins = resolve_cors_origins()
    assert "https://alpha.example.com" in origins
    assert "https://admin.example.com" in origins
    assert "http://localhost:3000" in origins


def test_a_wildcard_in_the_environment_is_refused(monkeypatch):
    """★환경변수로도 `"*"` 를 되살릴 수 없다★ — 뒷문을 만들지 않는다."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    assert "*" not in resolve_cors_origins()


def test_blank_entries_are_dropped(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " , ,https://ok.example.com, ")
    origins = resolve_cors_origins()
    assert "" not in origins
    assert "https://ok.example.com" in origins


def test_no_environment_means_just_the_local_defaults(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert set(resolve_cors_origins()) == set(CORS_ORIGINS)


def test_the_source_no_longer_contains_a_wildcard_origin():
    """★전수★ — 주석을 지우고 값만 되돌리는 변이를 막는다."""
    import pathlib
    src = pathlib.Path(factory.__file__).read_text(encoding="utf-8")
    # 목록 리터럴 안에 '"*"' 가 있으면 실패.
    assert '    "*",' not in src
