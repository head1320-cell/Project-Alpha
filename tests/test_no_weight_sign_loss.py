"""사용자가 준 비중의 **부호**를 라우트 경계에서 지우는 것을 정적으로 막는다.

`tests/test_no_order_executor_bypass.py` 관례 — CI 가 재발을 차단하고, 탐지기
자신이 실제로 동작하는지도 함께 건다.

★왜 정적 가드가 필요한가★ 이 결함 계열은 **두 슬라이스에 걸쳐** 나타났다.
두 번째 슬라이스에서 "측정된 곳 전부" 를 닫겠다고 했는데, 열거 grep 이
`head -30` 에서 잘렸고 그것을 완전한 목록으로 취급했다 — 여덟 곳이 남았다.
사람이 grep 으로 세면 또 잘린다. 세는 일을 CI 에 넘긴다.

★경계에서만 잰다★ 사용자가 준 비중은 부호가 **미지수**다. 옵티마이저 출력
(`allocation_studio`·`risk_allocations`·`_risk_budget_weights`)은 구조적으로
비음수라 같은 규칙을 걸면 잡음이 된다. 그래서 범위는 `src/api/*.py` 에서
`req.holdings`·`req.weights` 를 읽는 **함수**다(실측: 그런 줄 25개).

막는 두 가지:
  1. `max(<expr>, 0)` — 숏을 0 으로 자른다
  2. `X / X.sum()`   — net 정규화. 달러중립(Σw≈0)에서 무너진다
     (실측: `PortfolioAnalyzer` 가 `{A: inf, B: -inf}` 를 냈다)

교정은 `src/engine/portfolio_weights.signed_fractions` 로 한다.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "src" / "api"

#: 사용자가 준 비중이 들어오는 이름.
BOUNDARY_ATTRS = ("holdings", "weights")

#: 비중처럼 보이는 이름 — `max(var_d, 0.0)` 같은 **수치 가드**와 가르는 기준.
#: (첫 실행에서 `max(var_d, 0.0)`(sqrt 가드)를 잡아 오탐이 났다. 분산을 0 으로
#:  자르는 것은 CLAUDE.md 의 "수치 안전" 이 **요구하는** 것이지 결함이 아니다.)
WEIGHTY = ("w", "weight", "weights", "holding", "holdings", "wf", "user_w")

#: ★사유 없는 예외를 만들지 않는다★ (파일, 함수) → 왜 여기서는 괜찮은가.
#: 지금은 비어 있다 — 경계에서 부호를 지우는 곳이 하나도 남지 않았다는 뜻이다.
ALLOWED: dict[tuple[str, str], str] = {}


# ── 탐지기 ────────────────────────────────────────────────────────────────
def _reads_boundary(fn: ast.AST) -> bool:
    """이 함수가 `req.holdings` / `req.weights` 를 읽는가."""
    return any(isinstance(n, ast.Attribute) and n.attr in BOUNDARY_ATTRS
               and isinstance(n.value, ast.Name) and n.value.id == "req"
               for n in ast.walk(fn))


def _is_zero(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in (0, 0.0)


def _mentions_weight(node: ast.AST) -> bool:
    """이 식이 비중처럼 보이는 이름을 참조하는가."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in WEIGHTY:
            return True
        if isinstance(n, ast.Attribute) and n.attr in WEIGHTY:
            return True
    return False


def _clamps(fn: ast.AST) -> list[int]:
    """`max(<비중>, 0)` — 숏을 0 으로 자른다.

    ★분산·표준편차의 sqrt 가드는 대상이 아니다★ `max(var_d, 0.0)` 은 음수 분산을
    막는 수치 안전 장치이고, 이 저장소가 **요구하는** 패턴이다.
    """
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "max" and len(n.args) == 2 and _is_zero(n.args[1])
            and _mentions_weight(n.args[0])]


def _net_normalizes(fn: ast.AST) -> list[int]:
    """`X / X.sum()` — net 으로 나눈다. `X / np.abs(X).sum()` 은 통과."""
    out = []
    for n in ast.walk(fn):
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)):
            continue
        rhs = n.right
        if (isinstance(rhs, ast.Call) and isinstance(rhs.func, ast.Attribute)
                and rhs.func.attr == "sum" and isinstance(rhs.func.value, ast.Name)
                and isinstance(n.left, ast.Name)
                and n.left.id == rhs.func.value.id):
            out.append(n.lineno)
    return out


def _scan(tree: ast.AST, rel: str) -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _reads_boundary(fn):
            continue
        lines = _clamps(fn) + _net_normalizes(fn)
        if lines:
            found[(rel, fn.name)] = sorted(lines)
    return found


def scan_repo() -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for p in sorted(API_DIR.glob("*.py")):
        rel = str(p.relative_to(REPO_ROOT))
        found.update(_scan(ast.parse(p.read_text()), rel))
    return found


# ── 1. ★탐지기가 실제로 위반을 잡는가★ ─────────────────────────────────
def test_the_detector_catches_a_clamp():
    """가드가 무의미하게 항상 통과하지 않는지 — 합성 소스로 확인."""
    bad = ("def route(req):\n"
           "    h = {c: max(float(w), 0.0) for c, w in req.holdings.items()}\n"
           "    return h\n")
    assert _scan(ast.parse(bad), "x.py") == {("x.py", "route"): [2]}


def test_the_detector_catches_net_normalization():
    bad = ("def route(req):\n"
           "    w = np.array(req.weights)\n"
           "    w = w / w.sum()\n"
           "    return w\n")
    assert _scan(ast.parse(bad), "x.py") == {("x.py", "route"): [3]}


# ── 2. ★짝 — 정상 코드를 잡지 않는다★ ──────────────────────────────────
def test_the_detector_passes_the_corrected_shape():
    """`signed_fractions` + gross 정규화는 통과해야 한다."""
    good = ("def route(req):\n"
            "    h = signed_fractions(req.holdings)\n"
            "    w = np.array(list(h.values()))\n"
            "    w = w / np.abs(w).sum()\n"
            "    return w\n")
    assert _scan(ast.parse(good), "x.py") == {}


def test_the_detector_ignores_functions_that_never_see_user_weights():
    """★경계에서만 잰다★ 옵티마이저 출력은 구조적으로 비음수다."""
    optimizer = ("def _erc_weights(S):\n"
                 "    w = solve(S)\n"
                 "    w = np.clip(w, 0, None)\n"
                 "    w = w / w.sum()\n"
                 "    return w\n")
    assert _scan(ast.parse(optimizer), "x.py") == {}


def test_the_detector_does_not_flag_unrelated_max_calls():
    """`max(x, 0)` 이 아닌 `max(a, b)` 는 대상이 아니다."""
    ok = ("def route(req):\n"
          "    n = max(len(req.holdings), 3)\n"
          "    return n\n")
    assert _scan(ast.parse(ok), "x.py") == {}


def test_the_detector_does_not_flag_a_variance_sqrt_guard():
    """★첫 실행에서 이 오탐이 났다★ 분산을 0 으로 자르는 것은 결함이 아니라
    CLAUDE.md 의 "수치 안전" 이 요구하는 것이다 — 적자기업 실데이터에서
    음수 분산이 나오면 `sqrt` 가 터진다."""
    ok = ("def route(req):\n"
          "    w = signed_fractions(req.weights)\n"
          "    var_d = float(w @ cov @ w)\n"
          "    return float(np.sqrt(max(var_d, 0.0)))\n")
    assert _scan(ast.parse(ok), "x.py") == {}


# ── 3. ★실제 스캔 == 허용목록★ (양방향) ────────────────────────────────
def test_the_repository_has_no_unregistered_sign_loss():
    """★새로 추가하면 CI 가 실패한다★"""
    found = scan_repo()
    unregistered = {k: v for k, v in found.items() if k not in ALLOWED}
    assert not unregistered, (
        "라우트 경계에서 비중의 부호를 지우고 있습니다. "
        "`src.engine.portfolio_weights.signed_fractions` 를 쓰거나, 정말 옳다면 "
        f"사유와 함께 ALLOWED 에 등록하십시오: {unregistered}")


def test_no_dead_entries_in_the_allowlist():
    """★죽은 예외가 쌓이지 않게★ — 고쳐 놓고 남겨 둔 항목은 실패한다."""
    found = scan_repo()
    dead = [k for k in ALLOWED if k not in found]
    assert not dead, f"더 이상 위반이 아닌 허용목록 항목 — 지우십시오: {dead}"


def _reason_ok(why: object) -> bool:
    return isinstance(why, str) and len(why) >= 20


def test_every_allowlist_entry_carries_a_reason():
    """사유 없는 예외를 만들지 않는다.

    ★지금 `ALLOWED` 가 비어 있어 이 순회는 무의미하다★ 그래서 검사기 자체가
    빈 사유를 거부하는지도 함께 건다 — 나중에 항목이 생겼을 때 실제로 동작한다.
    """
    for key, why in ALLOWED.items():
        assert _reason_ok(why), key
    assert not _reason_ok("")
    assert not _reason_ok("짧음")
    assert _reason_ok("이 함수는 포트폴리오 비중이 아니라 팩터 중요도를 다룬다")


# ── 4. ★실행 경계는 이 가드의 대상이 아니다★ ──────────────────────────
def test_the_execution_clamp_is_out_of_scope_by_construction():
    """`execution_plan.build_plan` 의 `max(..., 0)` 은 ★P3 가 검토하고 유지하기로
    한 두 번째 방어선★ 이다(`test_long_only_chain.py`). 이 가드는 `src/api/` 의
    라우트 경계만 보므로 그것을 건드리지 않는다 — 우연이 아니라 설계다.
    """
    src = (REPO_ROOT / "src" / "engine" / "execution_plan.py").read_text()
    assert "max(current_weights.get(c, 0.0), 0.0)" in src, "P3 결정이 사라졌다"
    assert all(not k[0].startswith("src/engine/") for k in scan_repo()), \
        "이 가드가 엔진까지 보고 있다 — 범위를 넘었다"
