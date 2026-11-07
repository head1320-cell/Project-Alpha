"""BF3 · ★없는 모듈을 import 하는 코드가 조용히 생기지 않는다★ — 저장소 전체
==============================================================================
대상(읽기만): `src/` 전체 · 레지스트리 `src/engine/multistrategy_availability.MISSING`

## 왜

멀티전략 서브시스템은 모듈 다섯을 import 하는데 그 다섯은 저장소에 한 번도 없었다.
그 사실이 드러난 것은 석 달 뒤 **실물로 돌려 봤을 때**였다(BB) — import 가 함수
안에 있어서 모듈 로드도, 테스트도, 린트도 아무것도 걸리지 않았다.

이 파일이 그 틈을 막는다: `src/` 전수 AST 로 **없는 `src.*` 모듈을 import 하는
자리**를 모두 찾고, 그것이 **등록된 목록과 정확히 같은지** 본다.

- 새로 끊긴 import 가 생기면 red — *"고치거나, 없는 것이 맞다면 등록하라"*.
- 누가 모듈을 복원하면 red — *"승급: 레지스트리에서 빼라"*(등록이 거짓이 된다).
"""
from __future__ import annotations

import ast
import pathlib

from src.engine.multistrategy_availability import MISSING

SRC = pathlib.Path("src")


def _exists(module: str) -> bool:
    p = pathlib.Path(*module.split("."))
    return p.with_suffix(".py").exists() or (p / "__init__.py").exists() or p.is_dir()


def _dangling(files) -> dict[str, set[str]]:
    """`{없는 모듈: {그것을 import 하는 파일}}` — 절대 import 만 본다."""
    out: dict[str, set[str]] = {}
    for f in files:
        text = f.read_text(encoding="utf-8") if isinstance(f, pathlib.Path) else f[1]
        name = str(f) if isinstance(f, pathlib.Path) else f[0]
        tree = ast.parse(text)
        for n in ast.walk(tree):
            mods: list[str] = []
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module \
                    and n.module.split(".")[0] == "src":
                mods = [n.module]
            elif isinstance(n, ast.Import):
                mods = [a.name for a in n.names if a.name.split(".")[0] == "src"]
            for m in mods:
                if not _exists(m):
                    out.setdefault(m, set()).add(name)
    return out


def test_the_detector_finds_a_dangling_import():
    """★대조군★ — 항상-빈 탐지기는 아래 전칭을 공허하게 만든다."""
    fake = [("x.py", "def f():\n    from src.engine.does_not_exist import X\n"),
            ("y.py", "from src.engine.multistrategy_availability import MISSING\n")]
    assert _dangling(fake) == {"src.engine.does_not_exist": {"x.py"}}


def test_every_dangling_import_in_src_is_registered_and_nothing_else():
    """변이 — 새로 끊긴 import · 복원된 모듈 · 레지스트리 누락 전부 여기서 red."""
    found = _dangling(sorted(SRC.rglob("*.py")))
    registered = {m.module for m in MISSING}
    assert set(found) == registered, {
        "등록 안 된 끊긴 import (고치거나 등록하라)": sorted(set(found) - registered),
        "레지스트리에 있지만 실제로는 있다 (승급: 빼라)": sorted(registered - set(found)),
    }


def test_the_registry_names_the_real_importers():
    """★레지스트리가 사실을 말한다★ — `needed_by` 가 실제로 그 모듈을 import 한다."""
    found = _dangling(sorted(SRC.rglob("*.py")))
    for m in MISSING:
        assert set(m.needed_by) == found.get(m.module, set()), (
            m.module, sorted(found.get(m.module, set())))
