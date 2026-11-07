"""AM6 — 빌드 식별자 주입 경로가 **실재하는지** 못 박는다 (정적 트립와이어).

## 왜 정적으로 거나

`.dockerignore:18` 이 `.git` 을 제외한다. 그래서 컨테이너 안에서는
`git rev-parse` 가 통하지 않고 ★빌드 시각 주입이 유일한 경로★ 다. 주입 경로가
사라지면 배포된 모든 실행이 다시 미상이 되는데, **파이썬 테스트로는 그것이
보이지 않는다** — 로컬에서는 `.git` 이 있어 전부 초록이기 때문이다.

그래서 빌드 파일 자체를 읽는다. ★이 저장소가 이미 쓰는 방식★(AE3 의 유통 표면
부재 트립와이어, AH4 의 주석-트립와이어)과 같다.

## ★이 파일이 주장하지 않는 것★

- **주입이 실제로 동작함을 증명하지 않는다.** 여기서 보는 것은 **선언**이고,
  값이 실제로 들어갔는지는 컨테이너를 띄워야 안다. 그 한계를 적어 둔다.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    p = _ROOT / name
    assert p.exists(), f"{name} 이 없다"
    return p.read_text(encoding="utf-8")


def test_the_dockerignore_still_excludes_git():
    """★전제를 먼저 건다★ 이것이 바뀌면 주입이 유일한 경로가 아니게 된다.

    그때는 이 파일의 다른 테스트들이 과하다 — 하지만 **조용히** 과해지면
    안 되므로 여기서 red 로 알린다.
    """
    lines = [ln.strip() for ln in _read(".dockerignore").splitlines()]
    assert ".git" in lines, (
        "`.git` 이 더 이상 제외되지 않는다면 컨테이너 안에서 측정이 가능해진다 "
        "— `build_probe` 와 이 트립와이어를 다시 보라")


def test_the_backend_image_accepts_and_exports_a_build_identifier():
    """★`ARG` 만 있고 `ENV` 가 없으면 런타임에 보이지 않는다★"""
    df = _read("Dockerfile.backend")
    assert re.search(r"^ARG\s+GIT_SHA", df, re.M), "ARG GIT_SHA 가 없다"
    assert re.search(r"^ENV\s+GIT_SHA=\$GIT_SHA", df, re.M), (
        "ARG 를 ENV 로 내보내지 않으면 컨테이너 프로세스가 읽지 못한다")


def test_the_compose_backend_passes_the_build_identifier_through():
    yml = _read("docker-compose.yml")
    backend = yml.split("backend:", 1)[1].split("frontend:", 1)[0]
    assert "GIT_SHA:" in backend, "compose 의 backend 빌드가 값을 넘기지 않는다"


def test_ci_injects_the_commit_it_is_testing():
    """CI 는 `.git` 이 있어 측정도 되지만, **머지 커밋이 아니라 그 커밋**을
    기록하려면 주입이 정확하다."""
    ci = _read(".github/workflows/ci.yml")
    assert "GIT_SHA" in ci, "CI 가 빌드 식별자를 주입하지 않는다"
    assert "github.sha" in ci


def test_the_example_env_documents_the_variable():
    """★모르는 설정은 없는 설정이다★ 주입할 수 있다는 것을 알 수 있어야 한다."""
    assert "GIT_SHA" in _read(".env.example")
