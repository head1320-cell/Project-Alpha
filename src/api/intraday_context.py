"""규칙 맥락 — 규칙의 지표가 세션 밖에서 읽는 것을 ★그 사용자의 것만★ 골라 싣는다 (구현 계획 2026-11-16 §6 · T2 · §7.4 · K3).

맥락은 둘이다 — 하루 유형 모형(지표 `day_type_is` · T2)과 시장 국면(지표 `regime_prob` · K3). 규칙을 돌리는 다섯 길 —
`simulate` · `validate`(문 · 캔버스 설정 노드 · 캔버스 실행 단추) · `divergence` · 규칙 가동(시작 · 관제) — 이 모두 이 모듈을 지난다:

    load(사용자, 규칙, 시작일, end=, dates=)   ★봉을 읽기 전에★ — 쓰는 모형 · 국면을 읽고, 거절할 것은 거절한다
    attach(하루들, 읽은 것)                    봉을 읽은 뒤 — 세션마다 같은 맥락 객체를 싣는다(받은 하루는 바꾸지 않는다)
    facts(읽은 것, 판정 종목)                  판정 응답의 사실 줄(서버 문장 그대로 화면에 나간다 · `kind` 로 가른다)

거절(사유와 함께 400 · 저장소를 읽지 못하면 503):
- 없는 모형 · 남의 모형 · 운영 게이트의 합성(E0) 모형 = 같은 답(`day_type_model_missing` — 있는지를 알려 주지 않는다)
- 유형 번호가 그 모형의 유형 수보다 크다(`day_type_out_of_range`)
- ★학습 마지막 날 ≥ 판정 시작일★(`day_type_model_overlaps`) — 학습은 판정 시작일 전에 끝나야 한다. 겹친 모형은 판정할 날을 보고
  유형을 정했고, 판정 기간보다 뒤의 날로 학습한 모형은 뒤의 날을 본 것이다(둘 다 앞보기).
모형을 쓰지 않는 규칙은 저장소를 묻지 않고 맥락 없이 그대로 지난다(기존 경로 · 골든 불변).

시장 국면(K3) — 국면을 쓰는 규칙은 판정 기간(`end`)과 분봉이 적재된 날(`dates`)이 있어야 한다(없으면 `ValueError` — 부르는 쪽의 결함이다.
조용히 하루로 줄이지 않는다). (지수, 국면 수)마다 시장 국면 문과 ★같은 함수★(`regime_answer`)를 한 번 — 같은 날은 국면 절 · 국면별 나눔 ·
규칙 조건이 같은 값을 본다(그날 시가 전에 알던 값 · 전 거래일 종가까지). 거절:
- 지수 일봉 저장소를 읽지 못함 → 503 `regime_store_unavailable`(적재가 없다는 뜻이 아니다)
- 국면을 계산하지 못함(적재 없음 · 운영의 합성 · 날짜 겹침) → 400 `regime_unavailable`(시장 국면 문의 그 문장을 붙인다)
- 분봉이 적재된 날 가운데 확률을 아는 날이 없음 → 400 `regime_unknown_all`(사유별 날 수) — 거래 0 인 판정과 그 시행을 남기지 않는다.
일부 날만 모르면 돈다 — 그날은 조건을 충족하지 않고, 사실 줄이 아는 날 · 모르는 날 · 사유별 날 수를 적는다.

맥락이 필요한 지표가 맥락 없이 불리면 엔진이 명시적으로 실패한다(`indicators.IndicatorError("rule_context_missing")`) —
이 모듈을 지나지 않은 길이 생기면 조용히 거래 0 이 되지 않고 드러난다.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from types import MappingProxyType
from typing import Any

import numpy as np
from fastapi import HTTPException

from src.api.intraday_market_regime_routes import GRADE_UNKNOWN as REGIME_GRADE_UNKNOWN
from src.api.intraday_market_regime_routes import INDEXES as REGIME_INDEXES
from src.api.intraday_market_regime_routes import NOTES as REGIME_NOTES
from src.api.intraday_market_regime_routes import regime_answer
from src.data import intraday_day_types as store
from src.data.mock_gate import mock_allowed
from src.engine.intraday import indicators, rules
from src.engine.intraday.simulator import Day, RuleSpec
from src.engine.intraday.types import DayTypeRef, RegimeRef, RuleContext

GRADE_SYNTHETIC = "E0"

REASONS = {
    "day_type_model_missing": "하루 유형 모형을 찾지 못했습니다. 내가 학습한 모형만 쓸 수 있습니다.",
    "day_type_out_of_range": "유형 번호가 그 모형의 유형 수보다 큽니다.",
    "day_type_model_overlaps": ("하루 유형 모형의 학습 기간이 판정 기간과 겹치거나 판정 기간보다 뒤에 있습니다. "
                                "학습은 판정 시작일 전에 끝나야 합니다."),
    "store_unavailable": store.REASONS["store_unavailable"],
    "regime_store_unavailable": "지수 일봉 저장소를 읽지 못해 시장 국면을 계산하지 않았습니다. 적재가 없다는 뜻이 아닙니다.",
    "regime_unavailable": "시장 국면을 계산하지 못해 국면 조건을 쓴 규칙을 돌리지 않았습니다.",
    "regime_unknown_all": "분봉이 적재된 날 가운데 시장 국면 확률을 아는 날이 없어 계산하지 않았습니다.",
}

#: 사실 줄의 문장들(화면이 서버 글자 그대로 싣는다).
SAME_TICKERS = "판정 종목과 같은 종목으로 학습했습니다."
OTHER_TICKERS = "판정 종목과 학습 종목이 같지 않습니다."
SYNTHETIC_FACT = "모의 모드에서 만든 합성 분봉으로 학습한 모형입니다. 장치를 확인하는 용도입니다."
#: 시장 국면의 사실 줄(K3).
REGIME_WHEN = "{name} 시장 국면(국면 {k}개)의 확률은 그날 시가 전에 알던 값입니다. 전 거래일 종가까지의 지수 일봉으로 계산했고 그날 종가는 쓰지 않았습니다."
REGIME_COUNT = "분봉이 적재된 날 {loaded}일 가운데 국면 확률을 아는 날은 {known}일입니다."
REGIME_UNKNOWN = "확률을 모르는 날 {unknown}일은 국면 조건을 충족하지 않은 것으로 계산했습니다."
REGIME_SYNTHETIC = "모의 모드의 합성 지수 일봉으로 계산한 국면입니다. 변동성이 일정한 걸음이라 국면이 없는 자료이며 장치를 확인하는 용도입니다."
#: 분봉은 있는데 그날의 지수 일봉이 없는 날의 사유(국면 답에 그날 줄이 없다).
NO_INDEX_DAY = "그날의 지수 일봉이 적재돼 있지 않아 국면 확률을 계산하지 않았습니다."

#: 하루 유형 모형을 읽는 지표들 — 등록부에서 읽는다(맥락 칸 이름이 `day_types` 인 것).
_DAY_TYPE_INDICATORS = frozenset(name for name, spec in indicators.INDICATORS.items() if spec.context == "day_types")


@dataclass(frozen=True)
class Loaded:
    """읽은 맥락 — 엔진에 넘길 맥락(쓰는 모형 · 국면이 없으면 `None`)과 사실 줄에 쓰는 모형 요약 · 국면 사실 줄."""

    context: RuleContext | None
    models: tuple[dict, ...] | list[dict]
    regimes: tuple[dict, ...] | list[dict] = ()


def _refuse(code: str, status: int = 400, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "reason": REASONS[code], **extra})


def uses(spec: RuleSpec) -> dict[str, set[int]]:
    """규칙의 나무 셋에서 하루 유형 모형 열쇠 → 쓰인 유형 번호들(읽기만 · 평가하지 않는다). 검사를 지난 나무에만 쓴다."""
    found: dict[str, set[int]] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("ind") in _DAY_TYPE_INDICATORS:
            params = indicators.resolve(node["ind"], {k: v for k, v in node.items() if k != "ind"})
            found.setdefault(params["model"], set()).add(int(params["type"]))
        for arg in node.get("args", []):
            walk(arg)

    for tree in (spec.entry, spec.entry_stop, spec.exit):
        walk(tree)
    return found


def load(username: str, spec: RuleSpec, start: date, *, end: date | None = None, dates: Sequence[str] | None = None) -> Loaded:
    """그 규칙이 쓰는 모형 · 국면을 읽는다 — ★봉을 읽기 전에★. 거절할 것은 사유와 함께 `HTTPException`.

    `end` · `dates`(분봉이 적재된 날 — 읽기 전에 아는 것)는 국면을 쓰는 규칙에만 쓴다. 그 규칙에 없으면 부르는 쪽의 결함이다(`ValueError`)."""
    wanted = uses(spec)
    regimes_wanted = rules.regime_uses(spec)
    if not wanted and not regimes_wanted:
        return Loaded(None, [])
    refs: dict[str, DayTypeRef] = {}
    models: list[dict] = []
    for key in sorted(wanted):
        row = store.model_of(username, key)
        if row is None:
            raise _refuse("store_unavailable", status=503)
        if not row["found"] or (row["grade"] == GRADE_SYNTHETIC and not mock_allowed()):
            raise _refuse("day_type_model_missing", model=key[:8])
        top = max(wanted[key])
        if top > row["k"]:
            raise _refuse("day_type_out_of_range", model=key[:8], type=top, k=row["k"])
        if row["last_day"] >= start.isoformat():
            raise _refuse("day_type_model_overlaps", model=key[:8], first_day=row["first_day"], last_day=row["last_day"],
                          start=start.isoformat())
        centroids = np.asarray([t["path"] for t in row["body"]["types"]], dtype=np.float64)
        refs[key] = DayTypeRef(centroids=centroids, minutes=int(row["minutes"]), k=int(row["k"]))
        models.append({"key": key, "minutes": int(row["minutes"]), "k": int(row["k"]), "first_day": row["first_day"],
                       "last_day": row["last_day"], "tickers": list(row["tickers"]), "grade": row["grade"]})
    regime_refs: dict[tuple[str, int], RegimeRef] = {}
    regime_facts: list[dict] = []
    if regimes_wanted:
        if end is None or dates is None:
            raise ValueError("국면 조건을 쓴 규칙은 판정 기간(end)과 분봉이 적재된 날(dates)이 있어야 맥락을 싣는다")
        for index, k in sorted(regimes_wanted):
            ref, fact = _regime(index, k, sorted(regimes_wanted[(index, k)]), start, end, list(dates))
            regime_refs[(index, k)] = ref
            regime_facts.append(fact)
    return Loaded(RuleContext(day_types=refs, regimes=regime_refs), models, regime_facts)


def _regime(index: str, k: int, states: list[int], start: date, end: date, dates: list[str]) -> tuple[RegimeRef, dict]:
    """(지수, 국면 수) 하나 — 시장 국면 문과 같은 함수의 답 → 날짜별 확률 · 사실 줄. 쓸 수 없으면 거절한다."""
    answer = regime_answer(index, k, start, end)
    empty = answer.get("empty")
    if empty:
        if empty.get("reason") == "store_error":
            raise _refuse("regime_store_unavailable", status=503, index=index, k=k)
        raise HTTPException(status_code=400, detail={"code": "regime_unavailable", "index": index, "k": k, "empty": empty.get("reason"),
                                                     "reason": f"{REASONS['regime_unavailable']} {empty.get('message')}"})
    probs: dict[str, tuple[float, ...] | None] = {}
    why: dict[str, str] = {}
    for row in answer["days"]:
        p = row.get("probs")
        probs[row["date"]] = None if p is None else tuple(float(x) for x in p)
        if p is None:
            why[row["date"]] = str(row.get("reason") or "")
    known = [d for d in dates if probs.get(d) is not None]
    counted: dict[str, list] = {}                                 # 사유 → [날 수, 처음 난 날] — 많은 것부터 · 같으면 먼저 난 것부터
    for d in sorted(dates):
        if probs.get(d) is None:
            reason = why.get(d) or NO_INDEX_DAY
            counted.setdefault(reason, [0, d])[0] += 1
    unknown = [{"reason": r, "days": n} for r, (n, _first) in sorted(counted.items(), key=lambda item: (-item[1][0], item[1][1]))]
    if dates and not known:
        lines = " ".join(f"{u['days']}일: {u['reason']}" for u in unknown)
        raise HTTPException(status_code=400, detail={"code": "regime_unknown_all", "index": index, "k": k, "reasons": unknown,
                                                     "reason": f"{REASONS['regime_unknown_all']} {lines}".strip()})
    name = REGIME_INDEXES[index]
    sentences = [REGIME_WHEN.format(name=name, k=k), REGIME_COUNT.format(loaded=len(dates), known=len(known))]
    if unknown:
        sentences.append(REGIME_UNKNOWN.format(unknown=sum(u["days"] for u in unknown)))
        sentences.extend(f"{u['days']}일: {u['reason']}" for u in unknown)
    grade = answer.get("grade")
    if grade == GRADE_SYNTHETIC:
        sentences.append(REGIME_SYNTHETIC)
    elif grade is None:
        sentences.append(answer.get("grade_reason") or REGIME_GRADE_UNKNOWN)
    sentences.append(REGIME_NOTES[0])
    fact = {"kind": "regime", "key": f"{index}:{k}", "index": index, "name": name, "k": k, "states": states, "grade": grade,
            "days": {"loaded": len(dates), "known": len(known), "unknown": len(dates) - len(known)},
            "unknown_reasons": unknown, "sentences": sentences}
    return RegimeRef(index=index, k=k, probs=MappingProxyType(probs)), fact


def attach(days: list[Day], loaded: Loaded) -> list[Day]:
    """세션마다 같은 맥락 객체를 싣는다. 맥락이 없으면 받은 목록 그대로(같은 객체)."""
    if loaded.context is None:
        return days
    ctx = loaded.context
    return [replace(d, sessions={t: replace(s, context=ctx) for t, s in d.sessions.items()}) for d in days]


def facts(loaded: Loaded, tickers: list[str]) -> list[dict]:
    """판정 응답의 사실 줄 — 하루 유형 모형마다(`kind: day_type` · 학습 기간 · 종목 수 · 판정 종목과 같은지 · 합성이면 그렇다고)
    + 시장 국면마다(`kind: regime` · 아는 날 · 모르는 날과 사유별 날 수 · 등급 — `load` 가 지어 둔 것)."""
    out = []
    for m in loaded.models:
        same = sorted(m["tickers"]) == sorted(tickers)
        sentences = [f"하루 유형 모형 {m['key'][:8]}의 학습 기간은 {m['first_day']}~{m['last_day']}이며 "
                     f"종목 {len(m['tickers'])}개로 학습했습니다. 학습은 판정 시작일 전에 끝났습니다.",
                     SAME_TICKERS if same else OTHER_TICKERS]
        if m["grade"] == GRADE_SYNTHETIC:
            sentences.append(SYNTHETIC_FACT)
        out.append({**m, "kind": "day_type", "same_tickers": same, "sentences": sentences})
    out.extend(dict(f) for f in loaded.regimes)
    return out
