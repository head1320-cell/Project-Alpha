"""BU0b · 프런트 금지 표현 — ★화면 글자도 증거보다 강하게 말하지 않는다★
==============================================================================
CLAUDE.md §2: "검증됨·입증됨·견고함·프로덕션 레디·투자 우위·더 나은 전략" 은 뒷받침할 증거가 저장소에 있을 때만 쓴다.
서버 설명(`test_allocation_graph_explain.py`)은 이미 막는다. 다른 탭을 토스식으로 다시 쓰면 **화면이 직접 쓰는 문장**이 늘어나므로
(답 문장·안내·빈 화면) 프런트 소스도 같은 규칙으로 막는다.

## 규칙
- `frontend/src` 의 .ts/.tsx 에서 **주석을 뺀 나머지**(문자열·템플릿·JSX 글자)에 금지 표현이 있으면 실패.
- 부정 문맥("~이 되지 않아요")은 ★파일 + 그 문장 조각★ 허용 목록으로만 연다(줄 번호는 흔들려서 쓰지 않는다).
- 허용 목록 항목이 더는 일치하지 않으면 실패(낡은 허용은 남기지 않는다).
- 검사기 자체가 공허하지 않은지 짝 테스트: 문자열·템플릿·JSX 글자는 잡고, 주석은 잡지 않는다.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
BANNED = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략")

#: (경로, 그 줄에 있어야 하는 문장 조각) — 금지 표현을 **부정하는** 문장만.
ALLOW: tuple[tuple[str, str], ...] = (
    ("frontend/src/widgets/backtester/BacktestResults.tsx", '이 실행은 "검증됨" 이 되지 않아요'),
)


def strip_comments(src: str) -> str:
    """// · /* */ 주석을 지운다(문자열·템플릿 안의 // 는 둔다). 줄 수는 그대로 둔다(줄바꿈 보존)."""
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            chunk = src[i:(n if j < 0 else j + 2)]
            out.append("\n" * chunk.count("\n"))
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def findings(rel: str, src: str) -> list[tuple[int, str, str]]:
    out = []
    for no, line in enumerate(strip_comments(src).splitlines(), 1):
        for w in BANNED:
            if w in line and not any(rel == p and frag in line for p, frag in ALLOW):
                out.append((no, w, line.strip()[:120]))
    return out


def _files():
    return sorted(p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts)


def test_no_frontend_string_makes_a_banned_claim():
    files = _files()
    assert len(files) > 100
    bad = [f"{p.relative_to(ROOT)}:{no} «{w}» {line}"
           for p in files for no, w, line in findings(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))]
    assert bad == [], "금지 표현은 증거가 있을 때만 — 부정 문맥이면 ALLOW 에 파일·문장 조각으로:\n" + "\n".join(bad)


def test_every_allowlist_entry_still_matches_a_line():
    stale = []
    for rel, frag in ALLOW:
        p = ROOT / rel
        if not p.exists() or frag not in strip_comments(p.read_text(encoding="utf-8")):
            stale.append((rel, frag))
    assert stale == [], f"낡은 허용 항목: {stale}"


@pytest.mark.parametrize("snippet", [
    'const a = "이 전략은 검증됨";',
    "const b = `결과가 ${x} 견고함을 보여요`;",
    "return <p>투자 우위가 있어요</p>;",
    "label: '프로덕션 레디',",
])
def test_the_scanner_catches_strings_templates_and_jsx_text(snippet):
    assert findings("x.tsx", snippet), snippet


@pytest.mark.parametrize("snippet", [
    "// 검증됨 이라고 쓰지 않는다",
    "/* 더 나은 전략이라고\n 말하지 않는다 */ const ok = 1;",
    'const url = "https://example.com"; // 입증됨 아님',
])
def test_the_scanner_ignores_comments_but_keeps_strings_with_slashes(snippet):
    assert findings("x.tsx", snippet) == [], snippet


def test_the_allowlist_opens_only_the_exact_file_and_sentence():
    neg = 'msg = `제외 전 기준이고, 그래서 이 실행은 "검증됨" 이 되지 않아요.`;'
    rel = ALLOW[0][0]
    assert findings(rel, neg) == []
    assert findings("frontend/src/other.tsx", neg), "다른 파일에서는 열리지 않는다"
    assert findings(rel, 'msg = "이 실행은 검증됨";'), "같은 파일이라도 다른 문장은 열리지 않는다"
