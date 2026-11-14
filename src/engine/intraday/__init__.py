"""분봉 백테스트 엔진 — 순수 함수(입출력 없음). 설계: docs/superpowers/specs/2026-11-14-intraday-minute-simulator-design.md

    지표 등록부(`indicators`) → 표현식 나무(`expr`) → 체결가 규칙(`fills`) → 시뮬레이터(`simulator`) → ★매매일지 엔진★

시뮬레이터는 체결 줄만 만든다. `run` 이 그 줄을 `trade_journal.analyze` 에 넘긴다 — 왕복 매칭·비용·지표의 정의가
실거래 분석과 한 벌이다. ★체결 줄에 수수료·세금 금액을 싣지 않는다★: 실으면 일지가 그것을 '관측'으로 읽는다.
수수료는 요율만 넘기고(가정), 매도세는 일지가 거래일·시장·상품으로 정한다(추론), 시장을 모르면 미상으로 남는다.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from src.engine.trade_journal import analyze

from .simulator import ASSUMPTIONS, SKIP_REASONS, CostAssumptions, Day, PositionRules, RuleSpec, SimError, simulate
from .types import PrevDay, Session

__all__ = ["ASSUMPTIONS", "SKIP_REASONS", "CostAssumptions", "Day", "PositionRules", "PrevDay", "RuleSpec", "Session",
           "SimError", "run", "simulate"]

#: 출처 등급 → 화면 문장. 등급은 ★가장 약한 출처★가 정한다.
GRADE_REASONS = {
    "E3": "쓰인 분봉이 전부 제공자의 실제 응답입니다.",
    "E0": "모의 모드에서 만든 합성 분봉이 섞여 있습니다. 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.",
    "unknown": "출처를 알 수 없는 분봉이 섞여 있어 등급을 매기지 않았습니다.",
    "none": "쓰인 분봉이 없습니다.",
}


def _origin(sources: dict[str, int]) -> dict:
    key = ("none" if not any(sources.values()) else "E0" if sources["synthetic"] else "unknown" if sources["unknown"] else "E3")
    return {"kind": "simulated", "sessions": dict(sources), "grade": key if key in ("E0", "E3") else None,
            "grade_reason": GRADE_REASONS[key]}


def run(days: Sequence[Day], rule: RuleSpec, position: PositionRules, costs: CostAssumptions, *, rules: dict | None = None,
        master: Callable[[str], dict | None] | None = None) -> dict:
    """규칙 하나를 돌리고 그 체결을 매매일지로 계산한다."""
    out = simulate(days, rule, position, costs, rules=rules)
    journal = analyze(out["fills"], costs.journal_options(), master=master)
    return {"fills": out["fills"], "events": out["events"], "journal": journal, "origin": _origin(out["sources"]),
            "assumptions": out["assumptions"], "skipped": out["skipped"], "counts": out["counts"], "dates": out["dates"]}
