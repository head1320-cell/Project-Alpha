"""난수를 쓰는 자리를 찾는 두 도구 — ① 소스 스캐너(정적) ② 난수 진입점의 덫(동적).

`tests/route_walk.py` 와 같은 자리다: 시험과 재는 도구(`scripts/probe_synthetic_draws.py`)가 같이 쓴다.
등록부는 `src/data/synthetic_registry.py` — 이 파일이 뽑는 키(`경로::함수`)와 그 등록부의 키가 같아야 한다.

## ① 스캐너가 잡는 것

- `import random [as r]` 뒤의 `r.<무엇>` · `from random import X` / `from numpy.random import X` 뒤의 `X`
- `import numpy [as np]` 뒤의 `np.random.<무엇>`
- `<무엇>.manual_seed`
- `self._rng` · `self._normal` · `self._uniform` · `self._choice` · `self._maybe_missing` (mock 스토어의 원시 함수 호출)

## ★못 잡는 것★

- 난수 없이 해시·상수로 값을 만드는 자리 · 별칭 대입(`R = random.Random`) · `getattr` 로 돌려 부르는 자리.
- 스캐너는 "난수 기계를 이름으로 가리킨다"는 것만 본다. 게이트 뒤인지는 ②가 실제로 돌려서 본다.
"""
from __future__ import annotations

import ast
import os
import random
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK_PRIMITIVES = frozenset({"_rng", "_normal", "_uniform", "_choice", "_maybe_missing"})


# ══ ① 정적 — 소스 스캐너 ══════════════════════════════════════════════════════

def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def scan_file(path: Path) -> dict[str, list[str]]:
    """파일 하나 → `{함수 경로(클래스.메서드 · 바깥.안): [가리킨 이름…]}`. 함수 밖이면 `<module>`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rnd_mods: set[str] = set()      # `random` 모듈을 가리키는 이름
    np_mods: set[str] = set()       # `numpy` 를 가리키는 이름
    from_names: set[str] = set()    # `from random import X` 의 X
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "random":
                    rnd_mods.add(a.asname or "random")
                elif a.name == "numpy":
                    np_mods.add(a.asname or "numpy")
        elif isinstance(n, ast.ImportFrom) and n.module in ("random", "numpy.random"):
            from_names.update(a.asname or a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module == "numpy":
            rnd_mods.update(a.asname or "random" for a in n.names if a.name == "random")

    def hit(n: ast.AST) -> str | None:
        if isinstance(n, ast.Attribute):
            d = _dotted(n)
            if d is None:
                return None
            h = d.split(".")
            if h[0] in rnd_mods and len(h) >= 2:
                return d
            if h[0] in np_mods and len(h) >= 3 and h[1] == "random":
                return d
            if h[-1] == "manual_seed":
                return d
            if h[0] == "self" and len(h) == 2 and h[1] in MOCK_PRIMITIVES:
                return d
        elif isinstance(n, ast.Name) and n.id in from_names:
            return n.id
        return None

    out: dict[str, set[str]] = {}
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    def visit(node: ast.AST, qual: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, scopes):
                visit(child, f"{qual}.{child.name}" if qual else child.name)
                continue
            for n in ast.walk(child):
                if isinstance(n, scopes):
                    # 식 안에 묻힌 함수 정의(람다 제외)는 없다고 본다 — 있으면 바깥 함수에 붙는다.
                    continue
                h = hit(n)
                if h:
                    out.setdefault(qual or "<module>", set()).add(h)

    visit(tree, "")
    return {k: sorted(v) for k, v in out.items()}


def scan_sources(root: Path = ROOT) -> dict[str, list[str]]:
    """`src/**.py` 와 `main_api.py` 전부 → `{"경로::함수": [가리킨 이름…]}`."""
    files = sorted((root / "src").rglob("*.py"))
    if (root / "main_api.py").exists():
        files.append(root / "main_api.py")
    out: dict[str, list[str]] = {}
    for p in files:
        for qual, names in scan_file(p).items():
            out[f"{p.relative_to(root).as_posix()}::{qual}"] = names
    return out


def importers_of(module: str, root: Path = ROOT) -> list[str]:
    """`src.<…>.<module>` 을 임포트하는 `src/` · `main_api.py` 의 파일(자기 자신 제외)."""
    found: list[str] = []
    files = sorted((root / "src").rglob("*.py")) + [root / "main_api.py"]
    leaf = module.rsplit(".", 1)[-1]
    for p in files:
        rel = p.relative_to(root).as_posix()
        if rel == module.replace(".", "/") + ".py":
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import) and any(a.name == module for a in n.names):
                found.append(rel)
            elif isinstance(n, ast.ImportFrom) and (
                    n.module == module
                    or (n.module == module.rsplit(".", 1)[0] and any(a.name == leaf for a in n.names))):
                found.append(rel)
    return sorted(set(found))


# ══ ② 동적 — 난수 진입점의 덫 ═════════════════════════════════════════════════

_RANDOM_FUNCS = ("seed", "random", "uniform", "gauss", "normalvariate", "sample", "choice", "choices", "randint",
                 "randrange", "shuffle", "betavariate", "expovariate", "lognormvariate", "triangular")
_NUMPY_FUNCS = ("seed", "default_rng", "normal", "uniform", "randint", "lognormal", "standard_normal", "dirichlet",
                "choice", "multivariate_normal", "exponential", "random", "rand", "randn", "permutation", "shuffle",
                "binomial", "poisson", "beta", "gamma")


def _src_frames(root: Path, skip: int) -> tuple[str, ...]:
    """호출 사슬에서 `src/` · `main_api.py` 의 프레임만 — 안쪽부터. 키는 스캐너와 같은 모양(`경로::함수`)."""
    prefix = str(root).replace("\\", "/") + "/"
    keys: list[str] = []
    f = sys._getframe(skip)
    while f is not None:
        fn = f.f_code.co_filename.replace("\\", "/")
        if fn.startswith(prefix + "src/") or fn == prefix + "main_api.py":
            keys.append(f"{fn[len(prefix):]}::{f.f_code.co_qualname.replace('.<locals>', '')}")
        f = f.f_back
    return tuple(keys)


def install_tripwire(record: Callable[[tuple[str, ...]], None], setattr_fn=setattr, root: Path = ROOT) -> None:
    """난수 진입점을 가로채 ★누가 뽑았는가★를 `record(호출 사슬의 src 프레임들)` 로 알린다. 값은 그대로 돌려준다.

    가로채는 것: `random.Random(…)` · `random` 모듈 함수 · `numpy.random` 의 모듈 함수 · `default_rng` · `RandomState(…)`.
    이미 만들어 둔 RNG 객체의 메서드(`rng.gauss`)는 보지 않는다 — 만든 자리(`random.Random(seed)`)가 기록된다.
    `setattr_fn` — pytest 의 `monkeypatch.setattr` 를 넘기면 시험이 끝날 때 되돌려진다.
    """
    import numpy as np

    def note() -> None:
        frames = _src_frames(root, 3)
        if frames:
            record(frames)

    real_random = random.Random

    class SpyRandom(real_random):
        def __init__(self, *a, **k):
            note()
            super().__init__(*a, **k)

    setattr_fn(random, "Random", SpyRandom)

    real_state = np.random.RandomState

    class SpyState(real_state):
        def __init__(self, *a, **k):
            note()
            super().__init__(*a, **k)

    setattr_fn(np.random, "RandomState", SpyState)

    def wrap(real):
        def spy(*a, **k):
            note()
            return real(*a, **k)
        return spy

    for name in _RANDOM_FUNCS:
        setattr_fn(random, name, wrap(getattr(random, name)))
    for name in _NUMPY_FUNCS:
        setattr_fn(np.random, name, wrap(getattr(np.random, name)))


def drop_proxy_env() -> None:
    for k in list(os.environ):
        if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            del os.environ[k]
