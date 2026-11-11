"""화면 문체 래칫 — ★옮긴 폴더에는 해요체가 없다 · 어디까지 옮겼는지는 이 목록이 말한다★ (ADR 005)
==============================================================================================================
2026-11-11 · 사용자 지시 "쉬운 말이 어색하다 — 전문 용어로 다 바꿔 달라". 화면 문체를 해요체에서 개조식 + 합니다체로 옮긴다
(`docs/decisions/adr-005-professional-voice.md` · 용어집 `docs/specs/2026-11-11-ui-terminology.md`).

보이는 문구가 약 7,000개라 모듈 단위로 여러 번에 걸쳐 옮긴다. 그래서 이 시험은 ★래칫★이다:

- `frontend/src` 의 .ts/.tsx 에서 **주석을 뺀 나머지**(문자열·템플릿·JSX 글자)에 해요체 말끝이 있으면 그 파일은 "아직"이다.
- 아직 옮기지 않은 폴더는 `PENDING` 에 적는다. ★그 밖의 폴더에 해요체가 있으면 실패★(옮긴 곳에 다시 생기지 않는다).
- ★`PENDING` 의 폴더가 이미 깨끗하면 그것도 실패★ — 낡은 예외를 남기지 않는다. 폴더를 다 옮기면 목록에서 빼야 초록이 된다.
- 목록은 단계마다 줄고 마지막에 빈다.

## 해요체를 어떻게 찾나
"요" 앞 글자가 받침 없는 음절이고 모음이 ㅏ·ㅐ·ㅓ·ㅔ·ㅕ·ㅖ·ㅘ·ㅙ·ㅝ·ㅞ 이면 해요체 말끝이다(했어**요** · 이에**요** · 주세**요** · 돼**요** · 봐**요** · 바꿔**요**).
거기에 "~죠" · "~군요" 를 더한다. "요" 뒤에 한글이 이어지면 말끝이 아니다(해요체 라는 낱말 자체는 잡지 않는다).
수요·주요·필요·소요·중요는 앞 글자의 모음이나 받침 때문에 걸리지 않는다. "개요"만 따로 뺀다.

검사기가 공허하지 않은지는 아래 짝 시험이 본다(문자열·템플릿·JSX 글자는 잡고 주석은 잡지 않는다).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from tests.test_frontend_claim_words import strip_comments

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

#: 아직 옮기지 않은 폴더(저장소 뿌리 기준 접두). ★단계마다 줄인다 — 늘리지 않는다★
PENDING: tuple[str, ...] = ()        # 2026-11-11 변환기로 전 폴더를 한 번에 옮겨 비었다(HISTORY)

#: (경로, 그 줄에 있어야 하는 문장 조각) — 해요체를 **인용**하는 문장만(예: 사용자가 쓴 글을 그대로 보이는 자리). 지금은 없다.
ALLOW: tuple[tuple[str, str], ...] = ()

_OPEN_VOWELS = {0, 1, 4, 5, 6, 7, 9, 10, 14, 15}      # ㅏ ㅐ ㅓ ㅔ ㅕ ㅖ ㅘ ㅙ ㅝ ㅞ
_NOT_AN_ENDING = ("개요",)
_YO = re.compile(r"([가-힣])요(?![가-힣])")
_EXTRA = re.compile(r"(?:[가-힣]죠|군요)(?![가-힣])")


def _is_haeyo_stem(ch: str) -> bool:
    code = ord(ch) - 0xAC00
    return code % 28 == 0 and (code // 28) % 21 in _OPEN_VOWELS


def haeyo_hits(text: str) -> list[tuple[int, str]]:
    """주석을 걷은 글자에서 해요체 말끝을 찾는다 → [(줄 번호, 그 줄의 조각)]."""
    body = strip_comments(text)
    hits: list[tuple[int, str]] = []
    for m in list(_YO.finditer(body)) + list(_EXTRA.finditer(body)):
        word = m.group(0)
        if m.re is _YO and (not _is_haeyo_stem(m.group(1)) or word in _NOT_AN_ENDING):
            continue
        line = body.count("\n", 0, m.start()) + 1
        start = max(body.rfind("\n", 0, m.start()) + 1, m.start() - 40)
        hits.append((line, body[start:m.end()].strip()))
    return sorted(hits)


def _files() -> list[pathlib.Path]:
    return [p for p in sorted(SRC.rglob("*.ts*")) if not p.name.endswith(".d.ts")]


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _is_pending(rel: str) -> bool:
    return any(rel == pre or rel.startswith(pre.rstrip("/") + "/") for pre in PENDING)


def _allowed(rel: str, snippet: str) -> bool:
    return any(rel == path and frag in snippet for path, frag in ALLOW)


def test_migrated_folders_have_no_haeyo():
    """옮긴 폴더(= `PENDING` 밖)에는 해요체가 없다."""
    bad = []
    for p in _files():
        rel = _rel(p)
        if _is_pending(rel):
            continue
        for line, snippet in haeyo_hits(p.read_text()):
            if not _allowed(rel, snippet):
                bad.append(f"{rel}:{line}  …{snippet}")
    assert bad == [], f"옮긴 폴더에 해요체 {len(bad)}곳 — 처음 열: {bad[:10]}"


def test_pending_entries_are_not_stale():
    """★낡은 예외를 남기지 않는다★ 목록의 폴더는 있어야 하고, 아직 해요체가 남아 있어야 한다."""
    stale = []
    for pre in PENDING:
        path = ROOT / pre
        if not path.exists():
            stale.append(f"{pre} (없는 경로)")
            continue
        files = [path] if path.is_file() else [p for p in sorted(path.rglob("*.ts*")) if not p.name.endswith(".d.ts")]
        if not any(haeyo_hits(p.read_text()) for p in files):
            stale.append(f"{pre} (이미 깨끗하다 — 목록에서 뺄 것)")
    assert stale == [], stale


def test_pending_entries_do_not_overlap():
    """한 폴더가 두 번 적히면 하나를 지워도 다른 하나가 가린다."""
    for a in PENDING:
        for b in PENDING:
            assert a == b or not b.startswith(a.rstrip("/") + "/"), f"{b} 는 {a} 에 이미 들어 있다"


# ── 검사기 자체가 공허하지 않은지 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("src", [
    'const a = "불러오지 못했어요";',
    "const a = '계산하는 중이에요.';",
    "const a = `값을 넣어 주세요`;",
    "<p>지금 열려 있어요</p>",
    '<b title="x">됐죠</b>',
    'label: "그렇군요"',
    'const a = "바꿔요"; ',
    'const a = "실제 돈으로 주문해요";',
    'const a = "돼요";',
])
def test_the_detector_catches_haeyo_in_strings_templates_and_jsx(src):
    assert haeyo_hits(src), src


@pytest.mark.parametrize("src", [
    "// 불러오지 못했어요 — 주석은 화면에 안 나온다",
    "/* 계산하는 중이에요 */ const a = 1;",
    'const a = "수요 충격 · 주요 낙폭 구간 · 필요 자본 · 소요 기간 · 중요도";',
    'const a = "개요";',
    'const a = "조회 실패";',
    'const a = "산출했습니다.";',
    'const a = "값을 입력하십시오.";',
    'const a = "해요체 금지";',          # "요" 뒤에 한글이 이어진다 — 말끝이 아니다
])
def test_the_detector_ignores_comments_nouns_and_formal_endings(src):
    assert haeyo_hits(src) == [], haeyo_hits(src)
