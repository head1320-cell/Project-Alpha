"""`src.database` 에서 임포트하는 이름은 ★실재해야 한다★ (Z2 도중 발견)

## 실측한 결함

`get_sync_engine` 을 **18곳**이 임포트하는데 `src/database.py` 에 그 이름이 없었다.
전부 `try/except` 안이라 `ImportError` 가 **HTTP 500 으로 조용히 바뀌었고**, 그래서
Stage 11(멀티백테스트) · Stage 12 · Stage 13(실거래) 의 모든 엔드포인트와
`dag_runner`·`graph_runner` 가 죽어 있었다.

    GET /api/v1/live/daily-pnl   → 500 "cannot import name 'get_sync_engine'"
    get_executor()               → ImportError

`get_engine()`(동기 엔진)은 있고 `database_async` 가 비동기를 맡는다. 즉
`get_sync_engine` 은 **있어야 할 이름이 빠진 것**이지 설계가 다른 것이 아니다.

## ★인스턴스가 아니라 부류를 죽인다★

한 이름을 더하는 것으로는 다음이 또 빠진다. 이 파일은 `src.database` 에서
임포트하는 **모든 이름**이 실재하는지 전수로 본다 — `ImportError` 를 삼키는
`try/except` 가 많아 런타임까지 가야 드러나기 때문이다.
"""
from __future__ import annotations

import ast
import io
import os
import pathlib
import tokenize

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.database as db  # noqa: E402

_ROOTS = (pathlib.Path("src"),)
_EXTRA = (pathlib.Path("main_api.py"),)


def _code(src: str) -> str:
    """주석을 뺀 소스 — 설명 주석 속 임포트 문장은 위반이 아니다."""
    lines = dict(enumerate(src.splitlines(), 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and tok.start[0] in lines:
                lines[tok.start[0]] = lines[tok.start[0]].replace(tok.string, "")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return "\n".join(lines[k] for k in sorted(lines))


def _imported_names(src: str) -> list[str]:
    """`from src.database import X, Y` 의 X·Y (함수 안 임포트도 포함)."""
    out: list[str] = []
    try:
        tree = ast.parse(_code(src))
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "src.database":
            out.extend(a.name for a in n.names)
    return out


def _files() -> list[pathlib.Path]:
    return sorted([p for r in _ROOTS for p in r.rglob("*.py")]
                  + [p for p in _EXTRA if p.exists()])


def test_every_name_imported_from_database_exists():
    """★`ImportError` 를 삼키는 `try/except` 가 많아 런타임까지 안 드러난다★"""
    have = set(dir(db))
    missing: dict[str, list[str]] = {}
    for path in _files():
        for name in _imported_names(path.read_text(encoding="utf-8")):
            if name not in have:
                missing.setdefault(name, []).append(str(path))
    assert not missing, f"`src.database` 에 없는 이름을 임포트합니다: {missing}"


def test_the_scan_finds_real_imports():
    """★공허 배제★ — 하나도 못 찾으면 위 테스트는 언제나 통과한다."""
    found = [n for p in _files() for n in _imported_names(p.read_text(encoding="utf-8"))]
    assert len(found) > 20, len(found)
    assert "get_engine" in found


def test_the_scan_catches_a_missing_name():
    """★테스트의 테스트★"""
    src = "def f():\n    from src.database import totally_not_there\n"
    assert _imported_names(src) == ["totally_not_there"]


def test_the_scan_ignores_a_comment():
    """★오탐 배제★"""
    assert _imported_names("# from src.database import ghost\nX = 1\n") == []


def test_the_sync_engine_accessor_is_the_sync_engine():
    """★이름이 가리키는 것이 맞는지★ — 별칭이 비동기 엔진을 가리키면 안 된다."""
    assert db.get_sync_engine() is db.get_engine()
