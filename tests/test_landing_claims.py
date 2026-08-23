"""랜딩(/)이 하는 주장이 실재하는지 정적으로 검사한다.

랜딩의 '보장' 밴드는 주장마다 그것을 강제하는 테스트 파일 경로를 함께 적는다.
그 경로가 이름이 바뀌거나 지워지면, 랜딩은 **없는 보장을 광고하는 페이지**가 된다.
사람 눈에는 띄지 않는다 — 화면에는 그럴듯한 경로 문자열이 그대로 남아 있기 때문이다.

같은 이유로 푸터의 내부 링크도 검사한다. 라우트가 사라져도 링크는 남고, 방문자는
404 를 만나기 전까지 그 사실을 모른다.

★이 파일이 하는 일은 '통과' 가 아니라 '썩지 않게 하기' 다★
그래서 존재 검사만으로는 부족하다. 인용이 0건이어도 존재 검사는 전부 통과한다
(빈 목록에 대한 all() 은 참이다). 보장 밴드를 통째로 지워도 초록인 테스트가 되는 것이다.
이 세션에서 그런 '아무것도 지키지 않는 초록 테스트' 를 세 번 잡았기 때문에,
최소 개수를 함께 못 박는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LANDING = REPO_ROOT / "frontend" / "src" / "app" / "page.tsx"

# 랜딩이 인용하는 테스트 경로 — GUARANTEES 항목의 `test:` 값만 센다.
#
# ★처음에는 그냥 "tests/test_....py" 를 파일 전체에서 찾았는데, 그 정규식은 구멍이었다★
# 랜딩 주석에 이 파일 이름(tests/test_landing_claims.py)이 적혀 있어서, 보장을 하나
# 지워도 총 인용 수가 6을 유지해 최소 개수 검사가 통과했다(프로브로 확인).
# 주석·문서 언급이 보장 개수를 부풀리지 않도록 `test:` 키에 붙은 값만 센다.
_TEST_CITATION = re.compile(r'test:\s*"(tests/test_[a-z0-9_]+\.py)"')
# 랜딩이 링크하는 내부 라우트 — href="/..." (앵커 "#..." 와 외부 URL 은 제외)
_INTERNAL_HREF = re.compile(r'href="(/[a-zA-Z0-9/_\-]*)"')

# 보장 밴드가 약속하는 항목 수. 줄이려면 이 상수와 랜딩을 함께 고쳐야 한다.
MIN_CITATIONS = 6


@pytest.fixture(scope="module")
def landing_source() -> str:
    assert LANDING.exists(), f"랜딩 소스가 없다: {LANDING}"
    return LANDING.read_text(encoding="utf-8")


def test_landing_cites_at_least_the_promised_number_of_tests(landing_source: str) -> None:
    """★인용이 사라지면 이 줄이 먼저 빨개진다★

    존재 검사만 두면 인용 0건일 때도 통과한다 — 보장 밴드를 지운 것을 못 잡는다.
    """
    cited = sorted(set(_TEST_CITATION.findall(landing_source)))
    assert len(cited) >= MIN_CITATIONS, (
        f"랜딩이 인용한 테스트가 {len(cited)}건뿐이다(최소 {MIN_CITATIONS}건). "
        f"보장 밴드가 지워졌거나 인용 형식이 바뀌었다: {cited}"
    )


def test_every_cited_test_file_exists(landing_source: str) -> None:
    """인용한 경로가 실재해야 한다. 파일명이 바뀌면 랜딩도 함께 고쳐야 한다."""
    cited = sorted(set(_TEST_CITATION.findall(landing_source)))
    missing = [c for c in cited if not (REPO_ROOT / c).exists()]
    assert not missing, (
        f"랜딩이 실재하지 않는 테스트를 보장의 근거로 인용하고 있다: {missing}. "
        "파일을 옮겼다면 frontend/src/app/page.tsx 의 GUARANTEES 도 함께 고칠 것."
    )


def test_cited_tests_are_collectible(landing_source: str) -> None:
    """인용된 파일이 비어 있거나 테스트가 없으면 '강제한다'는 말이 성립하지 않는다."""
    cited = sorted(set(_TEST_CITATION.findall(landing_source)))
    toothless = []
    for c in cited:
        body = (REPO_ROOT / c).read_text(encoding="utf-8")
        if not re.search(r"^\s*(def test_|class Test)", body, re.MULTILINE):
            toothless.append(c)
    assert not toothless, (
        f"인용된 파일에 테스트 함수가 없다 — 보장을 강제하지 못한다: {toothless}"
    )


def test_every_internal_link_resolves_to_a_real_route(landing_source: str) -> None:
    """푸터·파이프라인·CTA 의 내부 링크가 전부 실재하는 App Router 라우트여야 한다.

    라우트가 사라져도 링크는 남는다. 방문자는 404 를 만나기 전까지 모른다.
    """
    app_dir = REPO_ROOT / "frontend" / "src" / "app"
    hrefs = sorted(set(_INTERNAL_HREF.findall(landing_source)))
    assert hrefs, "랜딩에 내부 링크가 하나도 없다 — 정규식이 깨졌을 가능성이 높다."

    broken = []
    for href in hrefs:
        rel = href.strip("/")
        target = app_dir / rel / "page.tsx" if rel else app_dir / "page.tsx"
        if not target.exists():
            broken.append(href)
    assert not broken, (
        f"랜딩이 존재하지 않는 라우트로 링크한다: {broken}"
    )


def test_landing_does_not_reintroduce_the_stale_test_count(landing_source: str) -> None:
    """옛 통계 블록의 `TEST SUITE 470` 이 되살아나지 않는지.

    그 값은 'MEASURED, NOT MARKETED' 라는 제목 아래 실려 있었고, 실측과 달랐다.
    """
    assert "470" not in landing_source, (
        "낡은 테스트 수(470)가 랜딩에 다시 들어왔다 — 실측 값으로 고칠 것."
    )
