"""랜딩(/)이 하는 주장이 실재하는지 정적으로 검사한다.

랜딩의 '보장' 밴드는 주장마다 그것을 강제하는 테스트 파일 경로를 함께 적는다.
그 경로가 이름이 바뀌거나 지워지면, 랜딩은 **없는 보장을 광고하는 페이지**가 된다.
(BU8a 에서 그 띠를 지웠다 — 아래 주석. 지금은 내부 링크와 낡은 숫자만 건다.)
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

# 랜딩이 링크하는 내부 라우트 — href="/..." (앵커 "#..." 와 외부 URL 은 제외)
_INTERNAL_HREF = re.compile(r'href="(/[a-zA-Z0-9/_\-]*)"')

# ★(BU8a) 보장 띠와 그 인용 테스트 셋을 거뒀다★
# 예전 첫 화면에는 '보장 여섯 + 그것을 강제하는 테스트 경로' 띠가 있었고, 이 파일이 인용 6건 이상 · 실재 · 테스트 함수 있음을 걸었다.
# 사용자 지시로 첫 화면을 히어로 · 스튜디오 · 리서치 경로만 남기고 그 띠를 지웠다(docs/HISTORY.md BU8a).
# 보장을 광고하지 않으니 "광고한 보장이 실재하는가" 를 볼 대상이 없다 — 남은 인용 0건에 존재 검사를 걸면 늘 통과하는
# 공허한 검사가 되므로, 최소 개수와 함께 셋 다 지웠다. 첫 화면에 보장을 다시 적는다면 인용 검사도 함께 되살릴 것.


@pytest.fixture(scope="module")
def landing_source() -> str:
    assert LANDING.exists(), f"랜딩 소스가 없다: {LANDING}"
    return LANDING.read_text(encoding="utf-8")


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
