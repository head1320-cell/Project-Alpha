"""★계산은 쓰지 않는다★ — 그래프 계산 중 DB 쓰기를 **런타임에** 잡는 픽스처 (BL0)
==============================================================================
AST 트립와이어(`test_allocation_graph_bk0.py::test_run_functions_never_call_a_write`)는 노드 모듈이
**직접** 부르는 이름만 본다. 노드가 감싼 함수 안의 쓰기(`alpha_validate(record_run=True)` ·
`macro_collector → record_series` · `company thesis-backtest` …)는 보지 못한다(BL 감사 실측).

이 픽스처는 알려진 쓰기 함수 전부를 "그래프 계산 중이면 기록" 하는 감시로 바꾸고, 계산 구간은
`portfolio_graph._execute` 를 감싸 표시한다. ★저장 문(`save_node`)의 쓰기는 `_execute` 가 끝난 뒤라 허용된다★ —
사용자 결정("계산은 쓰지 않고, 저장은 버튼")을 그대로 옮긴 것이다. 픽스처 준비(시드)의 쓰기도 계산 밖이라 허용.

노드 안의 예외는 엔진이 "실패" 로 삼키므로 감시는 **예외가 아니라 기록**으로 알리고, 테스트가 끝날 때
기록이 비어 있지 않으면 실패한다 — 삼켜서 통과하는 일이 없다.

쓰는 곳: 그래프 테스트 모듈마다 `pytestmark = pytest.mark.usefixtures("graph_write_guard")` 와 이 모듈의 import.
"""
from __future__ import annotations

import functools
import importlib
import sys

import pytest

#: (모듈, 이름) — 함수, 또는 "클래스.메서드". 새 쓰기 경로가 생기면 여기에 더한다.
WRITERS: tuple[tuple[str, str], ...] = (
    ("src.data.research_runs", "record_run"), ("src.data.research_runs", "delete_run"),
    ("src.data.target_versions", "save_target"),
    ("src.data.execution_store", "create_plan"), ("src.data.execution_store", "transition"),
    ("src.data.execution_store", "record_fills"), ("src.data.execution_store", "delete_plan"),
    ("src.data.journal_store", "create_entry"), ("src.data.journal_store", "update_review"),
    ("src.data.journal_store", "delete_entry"),
    ("src.data.research_cases", "create_case"), ("src.data.research_cases", "update_case"),
    ("src.data.research_cases", "advance_pointer"),
    ("src.data.backtest_runs", "create_run"), ("src.data.backtest_runs", "set_result"),
    ("src.data.backtest_runs", "delete_run"),
    ("src.data.regime_snapshots", "create_snapshot"), ("src.data.regime_snapshots", "attach_evidence"),
    ("src.data.regime_snapshots", "delete_snapshot"),
    ("src.data.company_snapshots", "create_snapshot"), ("src.data.company_snapshots", "delete_snapshot"),
    ("src.data.alpha_registry", "upsert_alpha"), ("src.data.alpha_registry", "attach_validation"),
    ("src.data.alpha_registry", "promote_alpha"), ("src.data.alpha_registry", "delete_alpha"),
    ("src.data.timing_rules", "save_rule_set"), ("src.data.timing_rules", "delete_rule_set"),
    ("src.engine.regime_snapshot_builder", "build_and_store"),
    ("src.engine.company_snapshot_builder", "build_and_store"),
    ("src.engine.strategy_registry", "StrategyRegistry.register"),
    ("src.engine.multi_strategy_backtest", "MultiStrategyBacktester._persist"),
    # BL3 W5 — 리밸런싱 판단의 결정 기록. 계산은 record_decision=False 라 부르지 않는다(저장 버튼만).
    ("src.data.investment_decisions", "save_decision"),
)


#: ★관측 수집(빈티지 기록)은 사용자 기록이 아니다★ (BL0 실측) — 조건부 μ/Σ 를 요청한 옵티마이저는 `/analyze` 와
#: 똑같이 매크로 수집기를 부르고, 수집기는 받은 관측을 **빈티지로 기록**한다(`macro_observation_store`). 이것이 시점
#: 정합(PIT)의 재료다 — 막으면 데이터 무결성이 나빠진다. 그래서 실패로 치지 않고 **따로 기록**해 드러낸다(`ingestion`).
INGESTION: tuple[tuple[str, str], ...] = (
    ("src.data.macro_observation_store", "save"), ("src.data.macro_observation_store", "record_series"),
)


class _Guard:
    def __init__(self) -> None:
        self.computing = 0
        self.violations: list[str] = []
        self.ingestion: list[str] = []


def _watch(guard: _Guard, label: str, fn, sink: str = "violations"):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        if guard.computing:
            getattr(guard, sink).append(label)
        return fn(*a, **k)
    wrapper.__graph_write_guard__ = True
    return wrapper


@pytest.fixture()
def graph_write_guard(monkeypatch):
    from src.engine import portfolio_graph as pg

    guard = _Guard()
    for (mod_name, attr), sink in [*((w, "violations") for w in WRITERS), *((w, "ingestion") for w in INGESTION)]:
        mod = importlib.import_module(mod_name)
        owner_name, _, name = attr.rpartition(".")
        owner = getattr(mod, owner_name) if owner_name else mod
        original = getattr(owner, name)
        wrapped = _watch(guard, f"{mod_name}.{attr}", original, sink)
        monkeypatch.setattr(owner, name, wrapped)
        if not owner_name:
            # `from src.data.x import f` 로 이미 묶인 이름도 바꾼다 — 원본 모듈만 바꾸면 그 사본은 감시를 피한다.
            for m in list(sys.modules.values()):
                if m is not None and m is not mod and getattr(m, name, None) is original:
                    monkeypatch.setattr(m, name, wrapped)

    real_execute = pg._execute

    @functools.wraps(real_execute)
    def execute(*a, **k):
        guard.computing += 1
        try:
            return real_execute(*a, **k)
        finally:
            guard.computing -= 1
    monkeypatch.setattr(pg, "_execute", execute)
    yield guard
    assert not guard.violations, f"그래프 계산 중 DB 쓰기: {sorted(set(guard.violations))}"
