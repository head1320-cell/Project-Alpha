"""Tailwind 유틸리티 ↔ 레거시 CSS 클래스 **특정도 충돌** 정적 가드 (Phase C).

★왜 리팩터링이 아니라 가드인가★
─────────────────────────────────────────────────────────────────────────────
감사는 "Tailwind 와 레거시 클래스를 섞어 쓰는 파일 12개" 를 위험으로 적었다. 계획은
`globals.css` 의 미분류 규칙 2,448개를 `@layer` 로 감싸 유틸리티가 항상 이기게 만드는
것이었다.

★내가 처음 센 "충돌 0건" 은 틀렸다★
그 계수는 감사가 고른 **12개 파일만** 훑었고, 그 목록은 레거시 접두사 정규식
(`as|tfm|brun|…`)으로 뽑은 것이라 `card-md` 같은 이름이 애초에 들어 있지 않았다.
저장소 전체를 훑자 **22건**이 나왔다 — 전부 `.card-md` 대 padding 유틸리티다.

그래도 결론은 같다: 저장소 전체 캐스케이드를 바꾸지 않는다. ADR 001 이 그 위험을 직접
적어 두었다 — "스위트는 클래스와 기하를 단정하지 픽셀을 보지 않으므로 캐스케이드 변화를
**스스로 잡을 수 없다**". 22건은 한 가지 원인(중복 정의)에서 나오고 국소적이므로, 전면
수술의 근거가 되지 못한다.

그래서 예방적 수술 대신 **탐지기**를 남긴다. 기존 22건은 기준선으로 잠그고, 새 충돌이
들어오는 순간 CI 가 잡는다.

★이 파일 자체가 거짓말하지 않는지 확인한다★
"0건" 은 탐지기가 고장 났을 때도 나오는 값이다. 그래서 아래에 **합성 충돌**을 넣어 탐지기가
실제로 잡는지 함께 검증한다. 그 테스트가 없으면 이 가드는 언제 죽었는지 모른 채 초록으로
남는다.

같은 계층의 정적 가드 선례: `tests/test_no_order_executor_bypass.py`.
"""
from __future__ import annotations

import collections
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[1] / "frontend"
GLOBALS_CSS = FRONTEND / "src" / "app" / "globals.css"

#: Tailwind 유틸리티 접두사 → 그것이 실제로 세팅하는 CSS 속성.
#: 전부 담을 필요는 없다 — **레이아웃/간격/타이포처럼 실제로 부딪히는 것**만 본다.
UTILITY_PROPERTY: dict[str, str] = {
    "flex": "display", "grid": "display", "inline-flex": "display",
    "block": "display", "hidden": "display",
    "items-": "align-items", "justify-": "justify-content",
    "gap-": "gap", "p-": "padding", "px-": "padding", "py-": "padding",
    "pt-": "padding", "pb-": "padding", "pl-": "padding", "pr-": "padding",
    "m-": "margin", "mt-": "margin", "mb-": "margin", "ml-": "margin", "mr-": "margin",
    "text-": "font-size", "font-": "font-weight", "bg-": "background",
    "rounded": "border-radius", "w-": "width", "h-": "height",
    "opacity-": "opacity", "absolute": "position", "relative": "position",
    "fixed": "position", "overflow-": "overflow",
}


def _legacy_rules() -> dict[str, set[str]]:
    """globals.css 의 **최상위(레이어 밖)** 클래스 규칙 → 세팅하는 속성 집합.

    레이어 안(`@layer utilities { … }`)은 제외한다 — 거기 있는 규칙은 이미 캐스케이드
    질서에 편입돼 있어 이 가드가 말하려는 함정이 아니다.
    """
    css = GLOBALS_CSS.read_text()
    rules: dict[str, set[str]] = collections.defaultdict(set)
    for m in re.finditer(r"^(\.[a-zA-Z][\w-]*(?:[^{\n]*)?)\{([^}]*)\}", css, re.M):
        selector, body = m.group(1), m.group(2)
        props = {p.split(":")[0].strip() for p in body.split(";") if ":" in p}
        for cls in re.findall(r"\.([a-zA-Z][\w-]*)", selector):
            rules[cls] |= props
    return rules


def _utility_property(token: str) -> str | None:
    for prefix, prop in UTILITY_PROPERTY.items():
        if token == prefix or token.startswith(prefix):
            return prop
    return None


def find_collisions(class_list: list[str], rules: dict[str, set[str]]) -> list[tuple[str, str, str]]:
    """한 요소의 class 목록에서 (레거시클래스, 유틸리티, 충돌속성) 을 뽑는다."""
    legacy = [c for c in class_list if c in rules]
    utils = [c for c in class_list if c not in rules and _utility_property(c)]
    out: list[tuple[str, str, str]] = []
    for lc in legacy:
        for u in utils:
            prop = _utility_property(u)
            if prop and any(prop == p or p.startswith(prop) for p in rules[lc]):
                out.append((lc, u, prop))
    return out


def _tsx_files() -> list[pathlib.Path]:
    return sorted((FRONTEND / "src").rglob("*.tsx"))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 탐지기가 실제로 탐지하는가 — 이게 없으면 아래 "0건" 은 아무 뜻이 없다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_detector_actually_detects_a_synthetic_collision():
    """★합성 충돌★ `.tfm-row` 는 display·gap 을 세팅한다 — `flex gap-2` 와 정면 충돌이다."""
    rules = _legacy_rules()
    assert "tfm-row" in rules, "globals.css 에서 .tfm-row 를 찾지 못했습니다 — 파서가 깨졌습니다"
    hits = find_collisions(["tfm-row", "flex", "gap-2"], rules)
    props = {p for _, _, p in hits}
    assert "display" in props and "gap" in props, (
        f"탐지기가 명백한 충돌을 놓쳤습니다: {hits}")


def test_the_detector_does_not_cry_wolf():
    """충돌하지 않는 조합은 잡지 않는다 — 거짓 양성이 많으면 가드가 무시된다."""
    rules = _legacy_rules()
    # `.num` 은 font-family/font-variant 만 세팅한다 — margin 유틸리티와 겹치지 않는다.
    assert find_collisions(["num", "mt-2"], rules) == []


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 기존 충돌은 기준선으로 잠그고, 새 충돌만 막는다
# ═══════════════════════════════════════════════════════════════════════════════
#: 이미 존재하는 충돌 22건 — **전부 `.card-md` 대 padding 유틸리티**다.
#:
#: ★왜 고치지 않고 기준선으로 잠그는가★
#: `.card-md` 는 globals.css 에 **두 번** 정의돼 있다 — 191행(@layer 안)과 653행(밖).
#: 밖의 것이 이겨서 `padding: 1rem` 이 유틸리티를 덮는다. 그중 14건은 `p-4`(=1rem)라
#: 눈에 보이는 차이가 없지만, 8건(`p-3`×3 · `p-6` · `p-8` · `p-12`×3)은 작성자가 쓴 값이
#: **조용히 무시되고** 있다. 실재하는 시각 버그다.
#:
#: 그런데 이걸 지금 고치면 /screener · /macro · /company 의 여백이 실제로 바뀐다. 어느 쪽이
#: 옳은 값인지는 디자인 판단이고(3rem 을 의도했나, 아니면 1rem 으로 몇 달을 살아 그것이
#: 기준이 됐나), 이 스위트는 픽셀을 보지 않아 회귀를 잡지 못한다(ADR 001). 그래서
#: **눈으로 확인할 수 있는 사람이 정할 일**로 남기고, 여기서는 새 충돌만 막는다.
KNOWN_COLLISIONS: frozenset[str] = frozenset({
    "src/widgets/macro/MacroRadar.tsx:64", "src/widgets/macro/MacroRadar.tsx:73",
    "src/widgets/macro/MacroRadar.tsx:123", "src/widgets/macro/MacroRadar.tsx:211",
    "src/widgets/macro/MacroRadar.tsx:273", "src/widgets/macro/MacroRadar.tsx:350",
    "src/widgets/macro/MacroRadar.tsx:434", "src/widgets/macro/MacroRadar.tsx:474",
    "src/widgets/narrative/index.tsx:431", "src/widgets/narrative/index.tsx:438",
    "src/widgets/valuation/ScreenerPanel.tsx:74", "src/widgets/valuation/ScreenerPanel.tsx:206",
    "src/widgets/valuation/ScreenerPanel.tsx:213", "src/widgets/valuation/ScreenerPanel.tsx:220",
    "src/widgets/valuation/StockDetail.tsx:59", "src/widgets/valuation/StockDetail.tsx:119",
    "src/widgets/valuation/StockDetail.tsx:124", "src/widgets/valuation/StockDetail.tsx:176",
    "src/widgets/valuation/StockDetail.tsx:233", "src/widgets/valuation/StockDetail.tsx:301",
    "src/widgets/valuation/StockDetail.tsx:368", "src/widgets/valuation/StockDetail.tsx:447",
})


def _scan() -> dict[str, list[str]]:
    rules = _legacy_rules()
    out: dict[str, list[str]] = {}
    for path in _tsx_files():
        text = path.read_text()
        for m in re.finditer(r'className="([^"]+)"', text):
            hits = find_collisions(m.group(1).split(), rules)
            if not hits:
                continue
            line = text[: m.start()].count("\n") + 1
            key = f"{path.relative_to(FRONTEND)}:{line}"
            out.setdefault(key, []).extend(f".{lc} vs '{u}' (둘 다 {prop})" for lc, u, prop in hits)
    return out


def test_no_new_specificity_collision_is_introduced():
    """★새 충돌은 0건이어야 한다★ 기존 22건은 위 주석의 이유로 기준선에 잠겨 있다.

    걸리면 고르는 길은 둘이다 — 그 요소에서 유틸리티를 빼거나, 레거시 규칙에서 그 속성을
    빼거나. `@layer` 로 저장소 전체 캐스케이드를 바꾸는 것은 이 목록이 **크게 늘었을 때**
    검토할 일이지, 예방적으로 할 일이 아니다.
    """
    found = _scan()
    new = sorted(set(found) - KNOWN_COLLISIONS)
    assert not new, (
        "Tailwind 유틸리티와 레거시 클래스가 같은 속성을 두고 충돌합니다(신규):\n  "
        + "\n  ".join(f"{k}  {'; '.join(found[k])}" for k in new))


def test_the_known_collision_baseline_does_not_silently_grow_stale():
    """★고쳐 놓고 목록을 안 지우면 기준선이 거짓이 된다★ 사라진 항목도 알려 준다."""
    found = _scan()
    gone = sorted(KNOWN_COLLISIONS - set(found))
    assert not gone, (
        "이미 해결된 충돌이 기준선에 남아 있습니다 — KNOWN_COLLISIONS 에서 지우세요:\n  "
        + "\n  ".join(gone))


@pytest.mark.skipif(not GLOBALS_CSS.exists(), reason="frontend 없음")
def test_globals_css_layer_split_is_recorded_honestly():
    """감사에 적힌 수치가 지금도 맞는지 — 문서가 조용히 낡는 것을 막는다.

    최초 감사는 "레거시 블록에 @layer 가 없다" 고 적었는데 실측은 **일부는 있다** 였다
    (162–387행). 그 정정을 수치로 고정해 둔다.
    """
    css = GLOBALS_CSS.read_text()
    assert "@layer utilities {" in css, "레이어 블록이 사라졌습니다 — 감사 기록과 어긋납니다"
    # 최상위(레이어 밖) 클래스 규칙이 여전히 다수라는 사실 자체가 이 가드의 존재 이유다.
    assert len(_legacy_rules()) > 500, "최상위 레거시 규칙이 급감했습니다 — 기록을 갱신하세요"
