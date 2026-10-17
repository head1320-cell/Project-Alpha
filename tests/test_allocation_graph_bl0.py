"""BL0 · 안전 가드 — 주문 경로 import 를 더 넓게 막고, 계산 중 쓰기를 런타임에 잡는다
==============================================================================
계획 `/root/.claude/plans` BL0 · 감사 실측(2026-09-26):
- 옛 트립와이어는 `src.kis_order_executor`·`src.engine.trading_engine` 만 막았다. 실주문 경로
  `src.execution.order_executor.OrderExecutor`·`src.execution.kis_client`·`src.api.kis_gateway` 와 실주문 라우트
  모듈(`trading_routes`·`account_order_routes`·`stage13_routes`)은 비어 있었다. `from src.execution import
  order_executor` 처럼 **이름으로** 들여오는 꼴도 잡지 못했다.
- 쓰기 검사는 노드 모듈이 **직접** 부르는 이름만 봤다 → `tests/graph_write_guard.py` 가 런타임에 잡는다.

## 거는 것 (짝)
- 금지 import 판별기가 모듈 꼴 · 이름 꼴 · 하위 모듈을 모두 잡는다 / 무관한 import 는 잡지 않는다.
- 노드 모듈 전수에 금지 import 0.
- 감시는 계산 중 쓰기를 기록한다 / 계산 밖(저장 문·시드)의 쓰기는 기록하지 않는다 / 쓰지 않는 노드는 0.
- 그래프 테스트 모듈 전부가 감시를 쓴다(빠진 파일이 없다).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.engine import portfolio_graph as pg
from tests.graph_write_guard import graph_write_guard  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

#: 노드 모듈이 들여오면 안 되는 실주문·계좌 경로 — 모듈 또는 그 하위.
ORDER_PATH = ("src.kis_order_executor", "src.engine.trading_engine", "src.execution.order_executor",
              "src.execution.kis_client", "src.api.kis_gateway", "src.api.trading_routes",
              "src.api.account_order_routes", "src.api.stage13_routes", "src.api.stage13_extensions")


def order_path_imports(source: str) -> list[str]:
    """이 소스가 들여오는 실주문 경로 이름들. `import a.b` · `from a import b` · `from a.b import c` 모두 전체 이름으로 본다."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            full = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            full = [mod] + [f"{mod}.{a.name}" for a in node.names]
        else:
            continue
        hits += [n for n in full if any(n == p or n.startswith(p + ".") for p in ORDER_PATH)]
    return hits


@pytest.mark.parametrize("src", [
    "from src.execution.order_executor import OrderExecutor",
    "from src.execution import order_executor",
    "import src.execution.kis_client",
    "from src.api import kis_gateway",
    "from src.api.stage13_routes import live_submit",
    "from src.engine.trading_engine import TradingEngine",
])
def test_the_order_path_detector_catches_every_import_form(src):
    assert order_path_imports(src), src


@pytest.mark.parametrize("src", [
    "from src.execution.order_netting import OrderNettingEngine",     # 네팅 계산은 주문 경로가 아니다
    "from src.api.execution_routes import ExecPlanRequest",           # 미리보기 문
    "from src.api import stage11_routes",
    "import src.execution",
])
def test_the_order_path_detector_leaves_unrelated_imports_alone(src):
    assert not order_path_imports(src), src


def test_no_node_module_imports_the_order_path():
    mods = sorted((ROOT / "src" / "api").glob("allocation_graph_nodes*.py"))
    assert len(mods) >= 6, "★공허 금지★ — 노드 모듈을 못 찾으면 이 검사는 증거가 아니다"
    for path in mods:
        assert not order_path_imports(path.read_text(encoding="utf-8")), path.name


# ── 런타임 쓰기 감시 ──────────────────────────────────────────────────────────

def _one_node_graph(kind: str) -> dict:
    return {"format": pg.FORMAT, "version": pg.VERSION,
            "nodes": [{"id": "n", "type": kind, "params": {}, "position": {"x": 0, "y": 0}}], "edges": []}


def _registry_with(run) -> pg.Registry:
    from pydantic import BaseModel

    class NoParams(BaseModel):
        pass
    reg = pg.Registry(port_types=("X",))
    reg.register(pg.NodeSpec("probe", "probe", inputs=(), outputs=(), run=run, params_model=NoParams))
    return reg


def test_the_guard_records_a_write_during_compute(monkeypatch, request):
    import src.data.research_runs as rr
    monkeypatch.setattr(rr, "record_run", lambda *a, **k: "rr_fake")      # 진짜 DB 에 닿지 않게 먼저 바꾼다
    guard = request.getfixturevalue("graph_write_guard")

    def writes(inputs, p):
        import src.data.research_runs as m
        m.record_run("analyze", {}, {})
        return pg.NodeOutput(values={}, view={})
    rep = pg.run(_one_node_graph("probe"), _registry_with(writes))
    assert rep["nodes"]["n"]["status"] == "ok"                              # 엔진은 모른다 — 감시만 안다
    assert guard.violations == ["src.data.research_runs.record_run"]
    guard.violations.clear()                                                # 이 테스트는 잡히는 것을 본 것이다


def test_a_name_bound_by_from_import_is_watched_too(monkeypatch, request):
    """`from src.data.research_runs import record_run` 으로 **미리 묶인 사본**도 감시한다 — 원본 모듈만 바꾸면 빠져나간다."""
    import sys
    import types

    import src.data.research_runs as rr
    fake = lambda *a, **k: "rr_fake"  # noqa: E731
    monkeypatch.setattr(rr, "record_run", fake)
    bound = types.ModuleType("bl0_bound_copy")
    bound.record_run = fake                                                 # 모듈 적재 때 묶인 이름의 흉내
    monkeypatch.setitem(sys.modules, "bl0_bound_copy", bound)
    guard = request.getfixturevalue("graph_write_guard")

    def writes(inputs, p):
        sys.modules["bl0_bound_copy"].record_run("analyze", {}, {})
        return pg.NodeOutput(values={}, view={})
    pg.run(_one_node_graph("probe"), _registry_with(writes))
    assert guard.violations == ["src.data.research_runs.record_run"]
    guard.violations.clear()


def test_a_write_outside_compute_is_not_a_violation(monkeypatch, request):
    import src.data.research_runs as rr
    monkeypatch.setattr(rr, "record_run", lambda *a, **k: "rr_fake")
    guard = request.getfixturevalue("graph_write_guard")
    import src.data.research_runs as m
    m.record_run("analyze", {}, {})                                         # 저장 문·시드 — 계산 밖
    assert guard.violations == []


def test_a_node_that_does_not_write_leaves_the_guard_empty(request):
    guard = request.getfixturevalue("graph_write_guard")
    rep = pg.run(_one_node_graph("probe"), _registry_with(lambda i, p: pg.NodeOutput(values={}, view={})))
    assert rep["nodes"]["n"]["status"] == "ok" and guard.violations == []


def test_observation_ingestion_is_recorded_apart_not_as_a_violation(monkeypatch, request):
    """★관측 수집은 사용자 기록이 아니다★ — 조건부 추정이 부르는 수집기의 빈티지 기록은 따로 드러낸다(실패 아님).
    짝: 같은 계산 안의 사용자 기록 쓰기는 여전히 위반이다."""
    import src.data.macro_observation_store as mos
    import src.data.research_runs as rr
    monkeypatch.setattr(mos, "record_series", lambda *a, **k: None)
    monkeypatch.setattr(rr, "record_run", lambda *a, **k: "rr_fake")
    guard = request.getfixturevalue("graph_write_guard")

    def ingests(inputs, p):
        import src.data.macro_observation_store as m
        m.record_series("kr", "x", [])
        return pg.NodeOutput(values={}, view={})
    pg.run(_one_node_graph("probe"), _registry_with(ingests))
    assert guard.ingestion == ["src.data.macro_observation_store.record_series"] and guard.violations == []

    def ingests_and_records(inputs, p):
        import src.data.research_runs as m
        m.record_run("analyze", {}, {})
        return ingests(inputs, p)
    pg.run(_one_node_graph("probe"), _registry_with(ingests_and_records))
    assert guard.violations == ["src.data.research_runs.record_run"]
    guard.violations.clear()


def test_every_graph_test_module_uses_the_guard():
    mods = sorted({*(ROOT / "tests").glob("test_allocation_graph*.py"), *(ROOT / "tests").glob("test_portfolio_graph*.py")})
    assert len(mods) >= 10
    missing = [m.name for m in mods if m.name != Path(__file__).name
               and 'usefixtures("graph_write_guard")' not in m.read_text(encoding="utf-8")]
    assert not missing, missing


def test_a_leftover_violation_fails_the_test_at_teardown(tmp_path):
    """★삼켜서 통과하는 일이 없다★ — 노드 안 예외는 엔진이 "실패" 로 삼키므로, 감시는 끝날 때 기록으로 실패시킨다.
    짝: 쓰지 않는 계산은 같은 경로로 통과한다."""
    import os
    import subprocess
    import sys
    body = '''
import pytest
from src.engine import portfolio_graph as pg
from tests.graph_write_guard import graph_write_guard  # noqa: F401
from tests.test_allocation_graph_bl0 import _one_node_graph, _registry_with

@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    import src.data.research_runs as rr
    monkeypatch.setattr(rr, "record_run", lambda *a, **k: "rr_fake")

def _node(write):
    def run(inputs, p):
        if write:
            import src.data.research_runs as m
            m.record_run("analyze", {}, {})
        return pg.NodeOutput(values={}, view={})
    return run

@pytest.mark.usefixtures("_fake")
def test_WRITE(request):
    request.getfixturevalue("graph_write_guard")
    pg.run(_one_node_graph("probe"), _registry_with(_node(True)))

@pytest.mark.usefixtures("_fake")
def test_CLEAN(request):
    request.getfixturevalue("graph_write_guard")
    pg.run(_one_node_graph("probe"), _registry_with(_node(False)))
'''
    f = tmp_path / "test_inner_guard.py"
    f.write_text(body, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "KIS_USE_MOCK": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(f)],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    out = r.stdout + r.stderr
    assert "ERROR at teardown of test_WRITE" in out and "그래프 계산 중 DB 쓰기" in out, out[-2000:]
    assert "teardown of test_CLEAN" not in out and "2 passed, 1 error" in out, out[-2000:]
