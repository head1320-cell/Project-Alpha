"""감시자가 ★안전 경로를 우회하지 못하게★ 정적으로 막는다 (P1-d)

`tests/test_no_order_executor_bypass.py` 의 선례를 잇는다 — 그 테스트는
`main_api.py` 가 `TradingEngine` 없이 `OrderExecutor` 를 만들어 6중 안전장치를
통째로 우회했던 사고의 재발을 정적으로 차단한다.

감시자는 새로 생긴 **자동 실행 가능 경로**다. 세 가지를 건다:

    ① 감시 코드는 어떤 실행기도 생성하지 않는다 (주문 능력을 갖지 않는다)
    ② `trigger()` 호출은 ★환경변수 분기 안에만★ 있다 (기본은 관측만)
    ③ `src/domain/` 은 순수 타입이다 — 저장·네트워크 라이브러리를 직접 쓰지 않는다

★각 검사에 짝과 오탐 배제를 붙인다★ — 항상 통과하는 가드는 증거가 아니다.
"""
from __future__ import annotations

import ast
import io
import pathlib
import tokenize

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 감시 경로 — 여기서는 주문을 낼 수 없어야 한다.
_MONITOR_FILES = ("src/execution/risk_monitor.py",)
_DOMAIN_DIR = REPO_ROOT / "src" / "domain"

#: 이름만 같은 두 실행기 클래스 **둘 다** 대상이다.
_EXECUTOR_NAMES = ("OrderExecutor", "TradingEngine")

#: 순수 타입 계층이 직접 쓰면 안 되는 것 — 저장·네트워크.
_FORBIDDEN_IN_DOMAIN = ("sqlalchemy", "requests", "httpx", "psycopg2", "asyncpg")


def _code(src: str) -> str:
    """주석을 **뺀** 소스. ★설명 주석은 위반이 아니다★(W 에서 같은 오탐을 겪었다)."""
    lines = dict(enumerate(src.splitlines(), 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and tok.start[0] in lines:
                lines[tok.start[0]] = lines[tok.start[0]].replace(tok.string, "")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return "\n".join(lines[k] for k in sorted(lines))


def _constructs_executor(src: str) -> list[str]:
    """`OrderExecutor(...)` 처럼 **호출**하는 곳. 임포트만으로는 위반이 아니다."""
    hits = []
    try:
        tree = ast.parse(_code(src))
    except SyntaxError:
        return hits
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name in _EXECUTOR_NAMES:
                hits.append(name)
    return hits


def _trigger_calls_outside_the_flag(src: str) -> list[int]:
    """`…trigger(` 호출 중 `autotrigger_allowed()` 분기 **밖**에 있는 것의 줄 번호."""
    tree = ast.parse(_code(src))

    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            names = {n.func.id for n in ast.walk(node.test)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if "autotrigger_allowed" in names:
                for inner in ast.walk(node):
                    guarded.add(getattr(inner, "lineno", -1))

    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "trigger" and node.lineno not in guarded):
            bad.append(node.lineno)
    return bad


def _domain_imports(src: str) -> set[str]:
    """모듈·함수 안 어디든 있는 import 의 최상위 패키지 이름."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(_code(src))):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ① 감시자는 주문 능력을 갖지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_monitor_never_constructs_an_executor():
    bad = {}
    for rel in _MONITOR_FILES:
        hits = _constructs_executor((REPO_ROOT / rel).read_text(encoding="utf-8"))
        if hits:
            bad[rel] = hits
    assert not bad, f"★감시 코드가 실행기를 만들었다★: {bad}"


def test_the_executor_guard_catches_a_real_construction():
    """★테스트의 테스트★"""
    assert _constructs_executor("ex = OrderExecutor(client)\n") == ["OrderExecutor"]
    assert _constructs_executor("eng = TradingEngine(cfg)\n") == ["TradingEngine"]


def test_the_executor_guard_ignores_a_comment_and_a_bare_import():
    assert _constructs_executor("# OrderExecutor(client) 를 만들면 안 된다\nX = 1\n") == []
    assert _constructs_executor("from src.execution.order_executor import OrderExecutor\n") == []


# ═══════════════════════════════════════════════════════════════════════════
# ② 자동 발동은 ★플래그 분기 안에만★
# ═══════════════════════════════════════════════════════════════════════════

def test_trigger_is_only_called_behind_the_flag():
    src = (REPO_ROOT / "src/execution/risk_monitor.py").read_text(encoding="utf-8")
    assert _trigger_calls_outside_the_flag(src) == [], \
        "★플래그 밖에서 킬스위치를 발동한다★"


def test_the_flag_guard_catches_an_unguarded_trigger():
    """★테스트의 테스트★"""
    bad = "def f(ks, v):\n    ks.trigger(source=v.source, reason=v.reason)\n"
    assert _trigger_calls_outside_the_flag(bad) == [2]


def test_the_flag_guard_accepts_a_guarded_trigger():
    """★짝★ 분기 안에 있으면 위반이 아니다(항상-거부 구현 배제)."""
    ok = ("def f(ks, v):\n"
          "    if autotrigger_allowed():\n"
          "        ks.trigger(source=v.source, reason=v.reason)\n")
    assert _trigger_calls_outside_the_flag(ok) == []


def test_the_monitor_really_contains_a_trigger_call():
    """★공허 배제★ — 호출이 아예 없으면 ② 는 언제나 통과한다."""
    src = _code((REPO_ROOT / "src/execution/risk_monitor.py").read_text(encoding="utf-8"))
    assert ".trigger(" in src


# ═══════════════════════════════════════════════════════════════════════════
# ③ `src/domain/` 은 ★순수 타입★
# ═══════════════════════════════════════════════════════════════════════════

def test_domain_does_not_import_storage_or_network():
    bad = {}
    for path in sorted(_DOMAIN_DIR.glob("*.py")):
        hit = _domain_imports(path.read_text(encoding="utf-8")) & set(_FORBIDDEN_IN_DOMAIN)
        if hit:
            bad[path.name] = sorted(hit)
    assert not bad, f"★도메인 계층이 저장·네트워크를 직접 썼다★: {bad}"


def test_domain_does_not_construct_executors():
    bad = {}
    for path in sorted(_DOMAIN_DIR.glob("*.py")):
        hits = _constructs_executor(path.read_text(encoding="utf-8"))
        if hits:
            bad[path.name] = hits
    assert not bad, bad


def test_the_domain_guard_catches_a_forbidden_import():
    """★테스트의 테스트★"""
    assert _domain_imports("from sqlalchemy import text\n") & set(_FORBIDDEN_IN_DOMAIN)
    assert _domain_imports("def f():\n    import requests\n") & set(_FORBIDDEN_IN_DOMAIN)


def test_the_domain_guard_allows_first_party_imports():
    """★짝★ 다른 우리 모듈을 부르는 것은 막지 않는다."""
    ok = "def f():\n    from src.engine.filter_ast import FIELD_BY_ID\n"
    assert not (_domain_imports(ok) & set(_FORBIDDEN_IN_DOMAIN))


def test_the_domain_scan_is_not_empty():
    """★공허 배제★"""
    assert len(list(_DOMAIN_DIR.glob("*.py"))) >= 2
