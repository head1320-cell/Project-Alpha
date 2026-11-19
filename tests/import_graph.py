"""import 그래프 — LLM 경계 시험(`tests/test_llm_boundary.py`)의 검사기 (G7 ① · 2026-11-19).

`tests/synthetic_scan.py` 와 같은 자리다: 파일을 읽어 그래프를 짓는 함수(`build_graph`)와 그래프에서 위반을 찾는 순수 함수
(`direct_users` · `path_to`)를 나눠, 짝 시험이 지어낸 그래프를 넣을 수 있게 한다. 등록부는 `src/domain/llm_boundary.py`.

## 잡는 것
- 모든 깊이의 `import a.b` · `from a.b import c`(상대 import 는 그 파일의 패키지 기준으로 풀어서) ·
  글자 상수를 받는 `importlib.import_module("a.b")` · `__import__("a.b")`.
- 함수 안의 늦은 import 도 길로 센다 — 부르지 않는 함수의 import 도 길이다(넘치게 잡는다).

## ★못 잡는 것★
- `getattr` 로 돌려 부르기 · 별칭(`m = importlib; m.import_module(...)` 은 잡지만 이름을 변수로 지으면 못 잡는다) ·
  실행 중에 지은 이름 · `exec`. 모듈 단위라 '이 함수가 저 함수를 부른다'는 보지 못한다.
"""
from __future__ import annotations

import ast
from collections import deque
from collections.abc import Callable, Collection
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module_name(path: Path, root: Path = ROOT) -> str:
    """`src/engine/x.py` → `src.engine.x` · `src/services/canvas_assist/__init__.py` → `src.services.canvas_assist`."""
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_names(source: str, module: str, *, is_package: bool = False) -> set[str]:
    """한 파일이 가리키는 import 이름 전부(점 이름). `module` 은 그 파일의 모듈 이름 — 상대 import 를 풀 때 쓴다."""
    tree = ast.parse(source)
    pkg = module.split(".") if is_package else module.split(".")[:-1]
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg[: len(pkg) - (n.level - 1)]
                mod = ".".join([*base, n.module] if n.module else base)
            else:
                mod = n.module or ""
            if mod:
                out.add(mod)
                out.update(f"{mod}.{a.name}" for a in n.names if a.name != "*")
        elif isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name in ("import_module", "__import__") and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str):
                out.add(n.args[0].value)
    return out


def resolve(name: str, modules: Collection[str]) -> str:
    """점 이름 → 저장소 모듈(가장 긴 접두) · 저장소 밖이면 최상위 이름(예: `anthropic.types` → `anthropic`)."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in modules:
            return cand
    return parts[0]


def build_graph(root: Path = ROOT, package: str = "src") -> dict[str, set[str]]:
    """모듈 → 그 모듈이 가리키는 모듈(저장소 안은 모듈 이름 · 밖은 최상위 이름). 자기 자신은 뺀다."""
    files = {module_name(p, root): p for p in sorted((root / package).rglob("*.py"))}
    graph: dict[str, set[str]] = {}
    for mod, path in files.items():
        names = imported_names(path.read_text(encoding="utf-8"), mod, is_package=path.name == "__init__.py")
        graph[mod] = {t for t in (resolve(x, files) for x in names) if t and t != mod}
    return graph


def under(name: str, prefixes: Collection[str]) -> bool:
    """`name` 이 접두 가운데 하나이거나 그 아래 모듈인가(점 경계 — `src.engine` 은 `src.engineer` 를 품지 않는다)."""
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def direct_users(graph: dict[str, set[str]], llm: Collection[str]) -> dict[str, set[str]]:
    """LLM 모듈을 직접 가리키는 모듈(LLM 모듈 자신은 빼고) → 가리키는 LLM 모듈."""
    return {m: {t for t in ts if under(t, llm)} for m, ts in graph.items()
            if not under(m, llm) and any(under(t, llm) for t in ts)}


def path_to(graph: dict[str, set[str]], start: str, target: Callable[[str], bool],
            cut: Collection[tuple[str, str]] = ()) -> list[str] | None:
    """`start` 에서 `target` 을 만족하는 모듈까지의 가장 짧은 길(끊은 간선은 지나지 않는다) — 없으면 None."""
    prev: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        for nxt in sorted(graph.get(here, ())):
            if (here, nxt) in cut or nxt in prev:
                continue
            prev[nxt] = here
            if target(nxt):
                path = [nxt]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])  # type: ignore[arg-type]
                return path[::-1]
            queue.append(nxt)
    return None
