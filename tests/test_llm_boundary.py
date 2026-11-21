"""LLM 은 계산 · 결정 계층에 없다 — 정적 그래프와 동작으로 건다 (G7 ① · 2026-11-19)

등록부: `src/domain/llm_boundary.py` · 검사기: `tests/import_graph.py` · 계획: `docs/superpowers/plans/2026-11-16-evidence-and-trader-ux.md` §7.

## 거는 것
① 검사기 자체 — 심은 글의 여섯 꼴(머리 · 함수 안 · from · importlib · `__import__` · 상대)을 잡고 주석 · 글자는 잡지 않는다.
② 계산 · 결정 계층(engine · domain · execution · data)은 LLM 모듈을 직접 들이지 않는다(예외 0).
③ 그 밖에서 LLM 을 직접 들이는 모듈은 등록부와 같다(새 모듈 · 낡은 줄 모두 실패).
④ 계산 계층에서 LLM 모듈까지의 길은 등록 간선을 끊으면 0 — 새 길은 길 전체를 글로 보이며 실패 · 등록 간선은 그래프에 있고 실제로 무언가를 끊는다.
⑤ LLM 모듈 · LLM 을 직접 들이는 모듈은 주문을 낼 수 있는 모듈을 직접 들이지 않는다.
⑥ 동작 — 등록 간선이 빌리는 이름을 새 프로세스에서 불러와도 LLM 모듈이 메모리에 없다 ↔ 코파일럿을 불러오면 있다(짝).
⑦ 매크로 추천의 근거 글은 키가 있든 없든 같은 규칙 글이다 — 엔진은 LLM 을 부르지 않는다.

## ★말하지 않는 것★
- 모듈 단위 그래프다: 부르지 않는 함수의 import 도 길로 세고(넘치게 잡음) `getattr` · 변수로 지은 이름은 못 본다.
- 'LLM 이 주문에 닿지 않는다'의 증명이 아니다 — 시세 클라이언트가 계좌 등록부를 들여 모듈 그래프에서는 LLM 쪽에서
  계좌 실행기까지 길이 있다(관측). 그래서 ⑤ 는 직접 import 만 막고, 주문은 기존 가드(TradingEngine 6중 안전장치 ·
  OrderExecutor 정적 강제 · 캔버스 실행 묶음의 주문 경로 import 금지)가 지킨다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_graph import ROOT, build_graph, direct_users, imported_names, path_to, under  # noqa: E402
from src.domain import llm_boundary as lb  # noqa: E402


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return build_graph()


def _llm(name: str) -> bool:
    return under(name, lb.LLM_MODULES)


def _core(name: str) -> bool:
    return under(name, lb.CORE_PACKAGES)


# ══ ① 검사기 자체 ═════════════════════════════════════════════════════════════

PLANTED = {
    "head": "import anthropic\n",
    "lazy": "def f():\n    from src.services.narrative.claude_client import ClaudeClient\n    return ClaudeClient\n",
    "from": "from src.services import canvas_assist\n",
    "importlib": "import importlib\nm = importlib.import_module('src.services.screener_copilot')\n",
    "dunder": "x = __import__('anthropic')\n",
    "relative": "from ..services.narrative import claude_client\n",   # src.engine.planted 기준 → src.services.narrative
}


@pytest.mark.parametrize("kind", sorted(PLANTED))
def test_the_scanner_sees_each_import_form(kind):
    names = imported_names(PLANTED[kind], "src.engine.planted")
    assert any(_llm(n) for n in names), (kind, sorted(names))


def test_the_scanner_does_not_take_comments_or_strings_for_imports():
    src = "# import anthropic\nNOTE = 'from src.services.narrative import x'\n\ndef f():\n    return 'anthropic'\n"
    assert not any(_llm(n) for n in imported_names(src, "src.engine.planted"))


def test_a_package_init_resolves_relative_imports_from_itself():
    names = imported_names("from .service import suggest\n", "src.services.canvas_assist", is_package=True)
    assert "src.services.canvas_assist.service" in names


# ══ ② 계산 계층은 LLM 을 직접 들이지 않는다 ═════════════════════════════════════

def test_core_layers_import_no_llm_module_directly(graph):
    bad = {m: sorted(t) for m, t in direct_users(graph, lb.LLM_MODULES).items() if _core(m)}
    assert bad == {}, f"계산 · 결정 계층이 LLM 모듈을 들인다: {bad}"


def test_the_core_check_is_not_vacuous(graph):
    core = [m for m in graph if _core(m)]
    assert len(core) > 200, len(core)
    planted = {**graph, "src.engine.planted": {"src.services.narrative.claude_client"}}
    assert {m for m in direct_users(planted, lb.LLM_MODULES) if _core(m)} == {"src.engine.planted"}


# ══ ③ 그 밖의 직접 사용자 = 등록부 ═══════════════════════════════════════════════

def test_the_prefix_check_stops_at_a_dot_boundary():
    """`src.engine` 은 `src.engine.x` 와 자신을 품고 `src.engineer` 는 품지 않는다(짝) — 접두를 글자로만 보면 이웃 이름이 섞인다."""
    assert under("src.engine", ("src.engine",)) and under("src.engine.macro", ("src.engine",))
    assert not under("src.engineer", ("src.engine",)) and not under("src.engineer.x", ("src.engine",))
    assert not under("openai_compat", ("openai",)) and under("openai.types", ("openai",))


def _registry_diff(users: set[str], registered: set[str]) -> tuple[set[str], set[str]]:
    return users - registered, registered - users


def test_direct_users_are_exactly_the_registered_ones(graph):
    new, stale = _registry_diff(set(direct_users(graph, lb.LLM_MODULES)), set(lb.DIRECT_USERS))
    assert not new, f"LLM 을 직접 들이는 새 모듈 — 사유와 함께 src/domain/llm_boundary.py 의 DIRECT_USERS 에: {sorted(new)}"
    assert not stale, f"등록부에 있는데 더는 LLM 을 들이지 않는 모듈 — 등록부에서 지운다: {sorted(stale)}"


def test_the_registry_check_catches_a_new_user_and_a_stale_entry(graph):
    users = set(direct_users(graph, lb.LLM_MODULES))
    new, stale = _registry_diff(users | {"src.api.planted"}, set(lb.DIRECT_USERS) | {"src.api.gone"})
    assert (new, stale) == ({"src.api.planted"}, {"src.api.gone"})


def test_every_registered_user_says_why_and_none_is_in_the_core():
    assert lb.DIRECT_USERS, "등록부가 비었다 — 검사가 공허하다"
    for mod, why in lb.DIRECT_USERS.items():
        assert isinstance(why, str) and len(why) >= 20, mod
    assert not [m for m in lb.DIRECT_USERS if _core(m)], "계산 계층은 등록부에 들 수 없다(예외 0)"


# ══ ④ 길 래칫 ════════════════════════════════════════════════════════════════

def test_no_path_from_the_core_to_llm_except_through_registered_edges(graph):
    cut = set(lb.CORE_EDGES)
    leaks = {m: p for m in sorted(graph) if _core(m) for p in [path_to(graph, m, _llm, cut)] if p}
    assert not leaks, "계산 계층에서 LLM 모듈로 가는 새 길:\n" + "\n".join(" → ".join(p) for p in leaks.values())


def test_each_registered_edge_is_real_and_cuts_something(graph):
    assert lb.CORE_EDGES, "등록 간선이 비었다"
    for (src_mod, dst_mod), why in lb.CORE_EDGES.items():
        assert dst_mod in graph.get(src_mod, set()), f"등록 간선이 그래프에 없다(낡음): {src_mod} → {dst_mod}"
        assert _core(src_mod) and not _core(dst_mod), (src_mod, dst_mod)
        assert isinstance(why, str) and len(why) >= 20
        others = set(lb.CORE_EDGES) - {(src_mod, dst_mod)}
        assert path_to(graph, src_mod, _llm, others) is not None, f"끊을 길이 없는 등록(공허): {src_mod} → {dst_mod}"


def test_the_path_check_reports_a_planted_path_in_full(graph):
    planted = {**graph, "src.engine.planted_a": {"src.engine.planted_b"},
               "src.engine.planted_b": {"src.services.canvas_assist.service"}}
    got = path_to(planted, "src.engine.planted_a", _llm, set(lb.CORE_EDGES))
    assert got == ["src.engine.planted_a", "src.engine.planted_b", "src.services.canvas_assist.service"]


# ══ ⑤ 주문 방향(직접만) ═══════════════════════════════════════════════════════

def _order_leaks(g: dict[str, set[str]]) -> dict[str, list[str]]:
    side = {m for m in g if _llm(m)} | set(direct_users(g, lb.LLM_MODULES))
    return {m: sorted(t for t in g.get(m, ()) if t in lb.ORDER_MODULES) for m in side
            if any(t in lb.ORDER_MODULES for t in g.get(m, ()))}


def test_the_llm_side_imports_no_order_module_directly(graph):
    assert _order_leaks(graph) == {}


def test_the_order_check_names_real_modules_and_bites(graph):
    assert [o for o in lb.ORDER_MODULES if o not in graph] == [], "등록부의 주문 모듈이 저장소에 없다"
    svc = "src.services.canvas_assist.service"
    planted = {**graph, svc: graph[svc] | {"src.execution.order_executor"}}
    assert _order_leaks(planted) == {svc: ["src.execution.order_executor"]}


# ══ ⑥ 동작 — 등록 간선은 LLM 을 메모리에 올리지 않는다 ════════════════════════════

_EDGE = ("import src.engine.strategy_registry  # noqa: F401\n"
         "from src.api.screener_routes import ScreenToBacktestRequest, _backtest_kwargs, _effective_strategy, _factor_weights  # noqa: F401\n")
_PROBE = """
import json, sys
sys.path.insert(0, {root!r})
{imports}
pre = {prefixes!r}
print(json.dumps(sorted(m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in pre))))
"""


def _loaded(imports: str, prefixes: tuple[str, ...] = lb.LLM_MODULES) -> list[str]:
    """새 프로세스에서 `imports` 를 돌린 뒤 메모리에 올라온 모듈 가운데 `prefixes` 아래인 것."""
    code = _PROBE.format(root=str(ROOT), imports=imports, prefixes=tuple(prefixes))
    env = {**os.environ, "KIS_USE_MOCK": "1"}
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=300, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_registered_edge_does_not_load_any_llm_module():
    assert _loaded(_EDGE) == []


def test_the_memory_probe_sees_an_llm_module_when_one_is_loaded():
    assert "src.services.screener_copilot" in _loaded(_EDGE + "import src.services.screener_copilot\n")


def test_pb_sheets_borrows_only_parts_that_do_not_load_the_client():
    client = ("anthropic", "src.services.narrative.claude_client", "src.services.canvas_assist.service")
    assert _loaded("import src.services.pb_sheets  # noqa: F401\n", client) == []
    assert _loaded("import src.services.canvas_assist.service  # noqa: F401\n", client) != []   # 짝 — 검사가 볼 수 있다


def test_the_registered_edge_borrows_names_that_never_mention_the_copilot():
    import ast as _ast
    tree = _ast.parse((ROOT / "src/api/screener_routes.py").read_text(encoding="utf-8"))
    borrowed = {"ScreenToBacktestRequest", "_backtest_kwargs", "_effective_strategy", "_factor_weights"}
    found = {n.name: n for n in tree.body if isinstance(n, (_ast.FunctionDef, _ast.ClassDef)) and n.name in borrowed}
    assert set(found) == borrowed, sorted(borrowed - set(found))
    for name, node in found.items():
        text = _ast.unparse(node)
        assert "screener_copilot" not in text and "nl_to_ast" not in text, name


# ══ ⑦ 매크로 추천의 근거 글 ═══════════════════════════════════════════════════════

def test_the_macro_recommendation_is_the_same_with_or_without_an_llm_key(monkeypatch):
    from src.engine.macro_recommender import recommend
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    without = recommend("kr")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-not-a-key")
    with_key = recommend("kr")
    assert without["narrative_source"] == with_key["narrative_source"] == "rule"
    assert json.dumps(without, sort_keys=True, ensure_ascii=False) == json.dumps(with_key, sort_keys=True, ensure_ascii=False)
