"""프런트 스타일 검사기 — ADR 007 §8 의 래칫이 쓰는 순수 함수 (U0-c)
==============================================================================
입력은 ★글★이다(파일을 열지 않는다) — 그래서 심은 위반으로 검사기 자체를 시험할 수 있다(`tests/test_frontend_style_ratchet.py`).

무엇을 세나
- `globals.css`: 척도 밖 글자 크기 · 척도 밖 반경 · 날 `z-index` · 토큰 정의 밖의 hex · 척도 밖 중단점 · 모든 속성에 거는 전환 ·
  등락색을 쓰는 선택자 · 수 칸에 상태색을 쓰는 선택자.
- `.tsx`: 요소의 `title=` 속성 · 낱 `<table>` 을 그리는 파일.

★한계(정직하게)★ — 글자를 훑는다. 인라인 `style={{…}}` · 실행 중에 지은 클래스 이름 · Tailwind 유틸리티로 적은 값 · 다른 CSS 파일은 보지 못한다.
CSS 는 정규식이 아니라 작은 걸음 해석기로 규칙을 나눈다(중괄호 깊이 · 문자열 · 주석) — 선택자 안의 `{` 같은 꼴은 이 저장소에 없다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ADR 007 §3 의 척도. 값을 바꾸면 ADR 을 함께 고친다.
FONT_SCALE_PX = frozenset({11, 12, 13, 14, 16, 18, 22, 28})
RADIUS_SCALE_PX = frozenset({0, 2, 4, 8, 12, 20, 999})
BREAKPOINTS_PX = frozenset({480, 640, 900, 1280, 1600})
#: `max-width: 1279px` 처럼 문턱 바로 아래를 가리키는 값도 척도 안이다.
BREAKPOINT_OK_PX = BREAKPOINTS_PX | frozenset(b - 1 for b in BREAKPOINTS_PX)

UPDOWN_TOKENS = ("--tx-up", "--tx-down", "--tx-up-ink", "--tx-down-ink", "--tx-up-soft", "--tx-down-soft")
STATUS_TOKENS = ("--tx-danger", "--tx-warn", "--tx-ok")

GEN_BEGIN, GEN_END = "/* BS5-GEN:BEGIN */", "/* BS5-GEN:END */"


def strip_css_comments(css: str) -> str:
    """`/* … */` 를 지운다(문자열 안은 둔다). 줄바꿈은 남긴다 — 줄 번호가 흔들리지 않게."""
    out: list[str] = []
    i, n = 0, len(css)
    quote: str | None = None
    while i < n:
        c = css[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(css[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append(c)
            i += 1
            continue
        if css.startswith("/*", i):
            j = css.find("*/", i + 2)
            chunk = css[i : (n if j < 0 else j + 2)]
            out.append("\n" * chunk.count("\n"))
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def drop_generated(css: str) -> str:
    """다크 생성 구역(생성기가 만든 글 — 사람이 적은 값이 아니다)을 뺀다. 주석을 지우기 ★전에★ 부른다."""
    a = css.find(GEN_BEGIN)
    b = css.find(GEN_END)
    if a < 0 or b < 0 or b < a:
        return css
    return css[:a] + "\n" * css[a : b + len(GEN_END)].count("\n") + css[b + len(GEN_END) :]


@dataclass(frozen=True)
class Rule:
    selector: str  #: 공백을 하나로 줄인 선택자 글(쉼표 목록 그대로)
    decls: tuple[tuple[str, str], ...]  #: (속성, 값) — 속성은 소문자
    media: tuple[str, ...]  #: 감싼 `@media` 의 조건 글(바깥부터)


def _split_decls(body: str) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    depth = 0
    quote: str | None = None
    start = 0
    parts: list[str] = []
    for i, c in enumerate(body):
        if quote:
            if c == quote and body[i - 1] != "\\":
                quote = None
            continue
        if c in "\"'":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ";" and depth == 0:
            parts.append(body[start:i])
            start = i + 1
    parts.append(body[start:])
    for p in parts:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        k, v = k.strip(), " ".join(v.split())
        if k and v:
            out.append((k if k.startswith("--") else k.lower(), v))
    return tuple(out)


def css_rules(css: str) -> list[Rule]:
    """주석을 지운 CSS → 규칙 목록. `@media` · `@supports` · `@container` · `@layer` 안으로 들어가고 `@keyframes` · `@font-face` 는 건너뛴다."""
    rules: list[Rule] = []

    def walk(text: str, media: tuple[str, ...]) -> None:
        i, n = 0, len(text)
        while i < n:
            j = text.find("{", i)
            if j < 0:
                return
            prelude = " ".join(text[i:j].split())
            # 앞에 남은 `@import …;` 같은 문장은 떼어 낸다
            if ";" in prelude:
                prelude = prelude.rsplit(";", 1)[1].strip()
            depth, k = 1, j + 1
            quote: str | None = None
            while k < n and depth:
                c = text[k]
                if quote:
                    if c == quote and text[k - 1] != "\\":
                        quote = None
                elif c in "\"'":
                    quote = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                k += 1
            body = text[j + 1 : k - 1]
            low = prelude.lower()
            if low.startswith(("@keyframes", "@-webkit-keyframes", "@font-face", "@property")):
                pass
            elif low.startswith("@media"):
                walk(body, media + (prelude[len("@media") :].strip(),))
            elif low.startswith("@"):
                walk(body, media)  # @supports · @container · @layer — 조건은 중단점 척도의 대상이 아니다
            elif prelude:
                rules.append(Rule(prelude, _split_decls(body), media))
            i = k

    walk(css, ())
    return rules


_PX = re.compile(r"(?<![\w.#-])(-?\d*\.?\d+)px\b")


def _px_values(value: str) -> list[float]:
    return [float(m) for m in _PX.findall(value)]


def offscale_font_sizes(rules: list[Rule]) -> list[tuple[str, str]]:
    """`font-size: Npx` 가운데 척도 밖(선택자, 값). `var()` · em · rem · % · `clamp()` 는 날 px 가 아니라 세지 않는다."""
    out = []
    for r in rules:
        for k, v in r.decls:
            if k != "font-size":
                continue
            m = re.fullmatch(r"(-?\d*\.?\d+)px(?:\s*!important)?", v)
            if m and float(m.group(1)) not in FONT_SCALE_PX:
                out.append((r.selector, v))
    return out


_RADIUS_PROPS = re.compile(r"border(-(top|bottom|start|end)-(left|right|start|end))?-radius")


def offscale_radii(rules: list[Rule]) -> list[tuple[str, str]]:
    """반경 선언 가운데 px 값이 하나라도 척도 밖인 것. `%` · `var()` · `inherit` 는 세지 않는다."""
    out = []
    for r in rules:
        for k, v in r.decls:
            if not _RADIUS_PROPS.fullmatch(k):
                continue
            literal = re.sub(
                r"var\([^()]*(?:\([^()]*\)[^()]*)*\)", "", v
            )  # var(--x, 4px) 의 폴백은 토큰을 쓰는 것으로 본다
            if any(px not in RADIUS_SCALE_PX for px in _px_values(literal)):
                out.append((r.selector, v))
    return out


def raw_z_indexes(rules: list[Rule]) -> list[tuple[str, str]]:
    """숫자를 글자로 적은 `z-index`. `auto` · `var(--tx-z-*)` · `inherit` 는 세지 않는다."""
    out = []
    for r in rules:
        for k, v in r.decls:
            if k == "z-index" and re.fullmatch(r"-?\d+(?:\s*!important)?", v):
                out.append((r.selector, v))
    return out


_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])")


def raw_hex(rules: list[Rule]) -> list[tuple[str, str]]:
    """토큰 정의(사용자 정의 속성의 값) ★밖★의 hex 색(선택자, 그 hex). `url(…)` 안은 보지 않는다."""
    out = []
    for r in rules:
        for k, v in r.decls:
            if k.startswith("--"):
                continue
            for h in _HEX.findall(re.sub(r"url\([^)]*\)", "", v)):
                out.append((r.selector, h.lower()))
    return out


_WIDTH_COND = re.compile(r"\(\s*(?:min|max)-width\s*:\s*(-?\d*\.?\d+)px\s*\)")


def offscale_breakpoints(rules: list[Rule]) -> list[str]:
    """`@media` 의 폭 조건 가운데 척도 밖 — ★서로 다른 조건 글★의 목록(같은 조건을 쓰는 규칙이 여럿이어도 한 번)."""
    seen: set[str] = set()
    for r in rules:
        for cond in r.media:
            for m in _WIDTH_COND.finditer(cond):
                if float(m.group(1)) not in BREAKPOINT_OK_PX:
                    seen.add(" ".join(m.group(0).split()))
    return sorted(seen)


_TIME = re.compile(r"-?\d*\.?\d+m?s")


def transition_all(rules: list[Rule]) -> list[tuple[str, str]]:
    """모든 속성에 거는 전환 — `transition: all …` · `transition-property: all` · ★속성 이름 없이 시간만 적은 꼴★(뜻이 all 이다).

    초점 고리(outline)까지 늦추는 꼴이라 ADR 007 §6 이 금지한다. `none` 은 전환이 없는 것이라 세지 않는다.
    """
    out = []
    for r in rules:
        for k, v in r.decls:
            val = re.sub(r"\s*!important$", "", v)
            if k == "transition-property":
                if any(seg.strip() == "all" for seg in val.split(",")):
                    out.append((r.selector, v))
                continue
            if k != "transition":
                continue
            depth, start, segs = 0, 0, []
            for i, c in enumerate(val):
                depth += c == "("
                depth -= c == ")"
                if c == "," and depth == 0:
                    segs.append(val[start:i])
                    start = i + 1
            segs.append(val[start:])
            for seg in segs:
                words = re.sub(r"\([^()]*\)", "()", seg).split()
                if (
                    not words
                    or words == ["none"]
                    or words[0] in ("inherit", "initial", "unset", "revert")
                    or words[0].startswith("var")
                ):
                    continue
                named = [
                    w
                    for w in words
                    if not _TIME.fullmatch(w)
                    and not re.fullmatch(
                        r"(ease(-in)?(-out)?|linear|step-(start|end)|cubic-bezier\(\)|steps\(\)|allow-discrete|normal)",
                        w,
                    )
                ]
                if not named or named[0] == "all":
                    out.append((r.selector, v))
                    break
    return out


def _uses(value: str, tokens: tuple[str, ...]) -> bool:
    return any(re.search(r"var\(\s*" + re.escape(t) + r"\s*[,)]", value) for t in tokens)


def updown_selectors(rules: list[Rule]) -> set[str]:
    """등락색 토큰을 ★쓰는★ 규칙의 선택자(토큰을 정의하는 선언은 쓰는 것이 아니다)."""
    return {r.selector for r in rules if any(not k.startswith("--") and _uses(v, UPDOWN_TOKENS) for k, v in r.decls)}


#: 수 칸으로 읽는 선택자 조각 — `.num` · `td.num` · `[data-num]` · 이름이 `-num` 으로 끝나는 클래스(`.pg-td-num` 등).
_NUM_CELL = re.compile(r"(?:\.num\b|\[data-num\b|\.[\w-]*-num\b)")


def status_on_number_selectors(rules: list[Rule]) -> set[str]:
    """수 칸 선택자에 상태색(위험 · 주의 · 정상)을 입힌 규칙 — ADR 007 §4-2 가 금지한다(상태색은 수에 입히지 않는다)."""
    out = set()
    for r in rules:
        if not any(not k.startswith("--") and _uses(v, STATUS_TOKENS) for k, v in r.decls):
            continue
        for sel in r.selector.split(","):
            # 마지막 복합 선택자(실제로 칠해지는 요소)만 본다
            last = re.split(r"[\s>+~]+", sel.strip())[-1]
            if _NUM_CELL.search(last):
                out.add(r.selector)
    return out


# ── TSX ─────────────────────────────────────────────────────────────────────────────────────────


def strip_ts_comments(src: str) -> str:
    """`//` · `/* */` 주석을 지운다(문자열 · 템플릿 안은 둔다). 줄바꿈은 남긴다. `tests/test_frontend_claim_words.py` 와 같은 규칙이다."""
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
            chunk = src[i : (n if j < 0 else j + 2)]
            out.append("\n" * chunk.count("\n"))
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _owner_tag(src: str, pos: int) -> str | None:
    """`pos` 의 속성이 붙은 JSX 여는 꼬리표의 이름. 뒤로 걸으며 `{…}` 안은 건너뛴다."""
    depth = 0
    i = pos - 1
    while i >= 0:
        c = src[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return None  # 속성이 아니라 식 안에 있었다
            depth -= 1
        elif c == ">" and depth == 0 and i > 0 and src[i - 1] != "=":
            return None  # 앞 꼬리표가 이미 닫혔다 — 속성 자리가 아니다
        elif c == "<" and depth == 0:
            m = re.match(r"<([A-Za-z][\w.]*)", src[i:])
            return m.group(1) if m else None
        i -= 1
    return None


def element_title_attrs(tsx: str) -> list[int]:
    """요소(소문자 꼬리표)의 `title=` 속성이 있는 줄 번호. 부품의 prop(`<Section title=…>`)과 SVG `<title>` 요소는 세지 않는다."""
    src = strip_ts_comments(tsx)
    out = []
    for m in re.finditer(r"(?<![\w.-])title=", src):
        tag = _owner_tag(src, m.start())
        if tag and tag[0].islower():
            out.append(src.count("\n", 0, m.start()) + 1)
    return out


def has_raw_table(tsx: str) -> bool:
    """낱 `<table>` 을 그리는가(주석 밖)."""
    return re.search(r"<table[\s>]", strip_ts_comments(tsx)) is not None
