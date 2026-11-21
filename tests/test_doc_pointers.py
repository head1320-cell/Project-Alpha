"""★docstring 의 경로도 계약이다★ — 죽은 포인터 전수 검사 (AO6)

AO 에서 실측으로 하나 나왔다: `src/domain/investor_profile.py`(AD2)가
`frontend/src/entities/investor-profile/types.ts` 를 *"프런트 타입"* 이라며
가리키고 있었지만 **그 파일은 만들어진 적이 없다.** 설계 문서가 *(제안)* 이라고
적어 둔 것을 docstring 이 이미 있는 것처럼 옮겨 적은 것이다.

★파일이 없는 것보다 없는 파일을 가리키는 것이 나쁘다★ — 다음 사람이 그 파일을
찾다가 못 찾으면 자기가 뭘 놓쳤다고 생각하고, 찾은 척 넘어가면 잘못된 전제 위에
쌓는다. `frontend/src/...` 는 저장소 안의 경로라 **기계가 확인할 수 있다.**

★이 검사가 하지 않는 것★ — `http` 링크·문서(`docs/`) 안의 링크는 보지 않는다.
전자는 이 환경에서 막혀 있고(증거 매트릭스 §0-2 `EGRESS_BLOCKED`), 후자는 범위가
따로다. 여기서 거는 것은 **파이썬 소스가 프런트 파일을 가리키는 경우**뿐이다.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCANNED = ("src", "scripts")
_PATTERN = re.compile(r"frontend/src/[A-Za-z0-9_@/.\-]+")
#: 경로 뒤에 붙어 오는 문장부호 — `(…)` · 백틱 · 쉼표.
_TRAILING = ".,)`'\"·"


def _mentions() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for top in _SCANNED:
        for path in (_ROOT / top).rglob("*.py"):
            for raw in set(_PATTERN.findall(path.read_text(encoding="utf-8"))):
                target = raw.rstrip(_TRAILING)
                # ★디렉터리 자체를 가리키는 것도 확인 대상이다★
                found.setdefault(str(path.relative_to(_ROOT)), set()).add(target)
    return found


def test_every_frontend_path_named_in_python_source_exists():
    """★없는 파일을 가리키지 않는다★ — AD2 의 유령 포인터가 이것으로 잡혔다."""
    dead = {
        src: sorted(t for t in targets if not (_ROOT / t).exists())
        for src, targets in _mentions().items()
    }
    dead = {k: v for k, v in dead.items() if v}
    assert not dead, f"존재하지 않는 프런트 경로를 가리킵니다: {dead}"


def test_the_scanner_actually_finds_paths():
    """★테스트의 테스트★ — 스캐너가 0건이면 위 검사는 언제나 통과한다.

    정규식이나 대상 디렉터리를 잘못 고쳐 아무것도 못 찾게 되면, 죽은 포인터
    검사가 **조용히 항상-통과**가 된다. 그 상태를 이 테스트가 거부한다.
    """
    mentions = _mentions()
    # ★실측 하한★ — 이 글을 쓰는 시점에 파이썬 소스가 가리키는 프런트 파일은
    # 셋이다(`PolicyBacktest.tsx` · `PerfLabel.tsx` · `glidepath/types.ts`).
    # 개수를 박는 것이 아니라 **0 이 되는 것을 막는** 하한이다.
    assert len(mentions) >= 3, f"파이썬 소스에서 찾은 프런트 경로가 너무 적습니다: {mentions}"
    assert sum(len(v) for v in mentions.values()) >= 3
