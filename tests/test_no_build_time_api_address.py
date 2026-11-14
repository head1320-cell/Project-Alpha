"""프론트가 API 주소를 ★빌드 타임에 박지 않는다★ (CLAUDE.md §6 프론트엔드 불변식)

`NEXT_PUBLIC_*` 는 `next build` 때 번들에 글자로 박힌다. 그 값으로 API 주소를 정하면 같은 이미지를 다른 곳에
띄울 수 없고, 빌드에서 값을 빠뜨리면 브라우저가 사용자의 `localhost:8000` 을 부른다(2026-10 이전에 실제로 그랬다).
`next.config.js` 의 `rewrites()` 도 목적지를 빌드 타임에 `routes-manifest.json` 에 박는다. 그래서 브라우저는 늘
같은 출처의 런타임 프록시(`/api/backend` — `src/app/api/backend/[...path]/route.ts` 가 요청마다 `BACKEND_URL` 을 읽는다)만 부른다.

2026-11-13 까지 `shared/api/apiBase.ts` 에 "별도 API 도메인을 쓸 때만" 이라는 선택적 override 가 남아 있었고
(Dockerfile·compose·.env.example 이 그 값을 날랐다), 불변식을 지키는 시험이 없었다 — 이 파일이 그 시험이다.

정적 검사다(빌드 타임 인라인은 실행해서는 안 보인다 — `OrderExecutor` 정적 강제와 같은 종류). 검사기가 늘 통과하거나
늘 거부하는 구현이 아님은 아래 짝 시험이 건다.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONT_SRC = ROOT / "frontend" / "src"
#: 빌드·배포 설정 — 여기에 `NEXT_PUBLIC_` 이 값으로 실리면 빌드 타임 주입이다.
DEPLOY_FILES = ("Dockerfile.frontend", "docker-compose.yml", ".env.example")

_TS_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_ENV_READ = re.compile(r"process\.env\.NEXT_PUBLIC_\w+|process\.env\[\s*['\"]NEXT_PUBLIC_")
_REWRITES = re.compile(r"\brewrites\s*[:(]")


def ts_violations(text: str) -> list[str]:
    """주석 밖에서 `process.env.NEXT_PUBLIC_*` 를 읽는 곳."""
    return _ENV_READ.findall(_TS_COMMENT.sub("", text))


def deploy_violations(text: str) -> list[str]:
    """`#` 주석 밖에서 `NEXT_PUBLIC_` 을 값으로 싣는 줄(Dockerfile ARG/ENV · compose args · env 파일)."""
    return [ln.strip() for ln in text.splitlines() if "NEXT_PUBLIC_" in ln.split("#", 1)[0]]


def rewrites_violations(text: str) -> list[str]:
    """`next.config.js` 의 주석 밖 `rewrites()`/`rewrites:`."""
    return _REWRITES.findall(_TS_COMMENT.sub("", text))


def test_frontend_source_never_reads_a_next_public_variable():
    files = [p for p in FRONT_SRC.rglob("*") if p.suffix in (".ts", ".tsx")]
    assert len(files) > 300, "프론트 소스를 못 찾았다 — 검사가 공허하다"
    bad = {str(p.relative_to(ROOT)): v for p in files if (v := ts_violations(p.read_text(encoding="utf-8")))}
    assert bad == {}


def test_build_and_deploy_config_never_injects_a_next_public_value():
    bad = {}
    for name in DEPLOY_FILES:
        p = ROOT / name
        assert p.exists(), f"{name} 이 없다 — 검사 대상 목록이 낡았다"
        if v := deploy_violations(p.read_text(encoding="utf-8")):
            bad[name] = v
    assert bad == {}


def test_next_config_has_no_rewrites():
    assert rewrites_violations((ROOT / "frontend" / "next.config.js").read_text(encoding="utf-8")) == []


def test_the_browser_goes_through_the_same_origin_runtime_proxy():
    """★있어야 하는 쪽★ — 금지만 걸면 '아무 주소도 없음'도 통과한다. 프록시 경로와 그 라우트가 실제로 있다."""
    api_base = (FRONT_SRC / "shared" / "api" / "apiBase.ts").read_text(encoding="utf-8")
    assert '"/api/backend"' in _TS_COMMENT.sub("", api_base)
    route = FRONT_SRC / "app" / "api" / "backend" / "[...path]" / "route.ts"
    assert route.exists() and "BACKEND_URL" in route.read_text(encoding="utf-8")


# ── 짝 — 검사기가 늘 통과·늘 거부가 아니다 ─────────────────────────────────────────

def test_the_scanners_catch_a_planted_violation():
    assert ts_violations('const a = process.env.NEXT_PUBLIC_API_URL ?? "x";') == ["process.env.NEXT_PUBLIC_API_URL"]
    assert ts_violations('const a = process.env["NEXT_PUBLIC_API_BASE"];') != []
    assert deploy_violations("ARG NEXT_PUBLIC_API_URL=http://localhost:8000\nENV A=1") == ["ARG NEXT_PUBLIC_API_URL=http://localhost:8000"]
    assert deploy_violations("        NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-}") != []
    assert rewrites_violations("const c = { async rewrites() { return []; } };") != []


def test_the_scanners_ignore_comments_and_other_env():
    assert ts_violations("// `NEXT_PUBLIC_*` 는 빌드 타임에 인라인된다\n/* process.env.NEXT_PUBLIC_X */\nconst b = process.env.BACKEND_URL;") == []
    assert deploy_violations("# NEXT_PUBLIC_API_URL 은 쓰지 않는다\nBACKEND_URL=http://backend:8000") == []
    assert rewrites_violations("// rewrites() 는 쓰지 않는다\nconst c = { async redirects() { return []; } };") == []
