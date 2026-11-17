"""규칙 맥락 — 규칙의 지표가 세션 밖에서 읽는 것을 ★그 사용자의 것만★ 골라 싣는다 (구현 계획 2026-11-16 §6 · T2).

지금의 맥락은 하루 유형 모형 하나다(지표 `day_type_is`). 규칙을 돌리는 다섯 길 — `simulate` · `validate`(문 · 캔버스 설정 노드 ·
캔버스 실행 단추) · `divergence` · 규칙 가동(시작 · 관제) — 이 모두 이 모듈을 지난다:

    load(사용자, 규칙, 판정 시작일)   ★봉을 읽기 전에★ — 쓰는 모형을 읽고, 거절할 것은 거절한다
    attach(하루들, 읽은 것)           봉을 읽은 뒤 — 세션마다 같은 맥락 객체를 싣는다(받은 하루는 바꾸지 않는다)
    facts(읽은 것, 판정 종목)         판정 응답의 사실 줄(서버 문장 그대로 화면에 나간다)

거절(사유와 함께 400 · 저장소를 읽지 못하면 503):
- 없는 모형 · 남의 모형 · 운영 게이트의 합성(E0) 모형 = 같은 답(`day_type_model_missing` — 있는지를 알려 주지 않는다)
- 유형 번호가 그 모형의 유형 수보다 크다(`day_type_out_of_range`)
- ★학습 마지막 날 ≥ 판정 시작일★(`day_type_model_overlaps`) — 학습은 판정 시작일 전에 끝나야 한다. 겹친 모형은 판정할 날을 보고
  유형을 정했고, 판정 기간보다 뒤의 날로 학습한 모형은 뒤의 날을 본 것이다(둘 다 앞보기).
모형을 쓰지 않는 규칙은 저장소를 묻지 않고 맥락 없이 그대로 지난다(기존 경로 · 골든 불변).

맥락이 필요한 지표가 맥락 없이 불리면 엔진이 명시적으로 실패한다(`indicators.IndicatorError("rule_context_missing")`) —
이 모듈을 지나지 않은 길이 생기면 조용히 거래 0 이 되지 않고 드러난다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import numpy as np
from fastapi import HTTPException

from src.data import intraday_day_types as store
from src.data.mock_gate import mock_allowed
from src.engine.intraday import indicators
from src.engine.intraday.simulator import Day, RuleSpec
from src.engine.intraday.types import DayTypeRef, RuleContext

GRADE_SYNTHETIC = "E0"

REASONS = {
    "day_type_model_missing": "하루 유형 모형을 찾지 못했습니다. 내가 학습한 모형만 쓸 수 있습니다.",
    "day_type_out_of_range": "유형 번호가 그 모형의 유형 수보다 큽니다.",
    "day_type_model_overlaps": ("하루 유형 모형의 학습 기간이 판정 기간과 겹치거나 판정 기간보다 뒤에 있습니다. "
                                "학습은 판정 시작일 전에 끝나야 합니다."),
    "store_unavailable": store.REASONS["store_unavailable"],
}

#: 사실 줄의 문장들(화면이 서버 글자 그대로 싣는다).
SAME_TICKERS = "판정 종목과 같은 종목으로 학습했습니다."
OTHER_TICKERS = "판정 종목과 학습 종목이 같지 않습니다."
SYNTHETIC_FACT = "모의 모드에서 만든 합성 분봉으로 학습한 모형입니다. 장치를 확인하는 용도입니다."

#: 하루 유형 모형을 읽는 지표들 — 등록부에서 읽는다(맥락 칸 이름이 `day_types` 인 것).
_DAY_TYPE_INDICATORS = frozenset(name for name, spec in indicators.INDICATORS.items() if spec.context == "day_types")


@dataclass(frozen=True)
class Loaded:
    """읽은 맥락 — 엔진에 넘길 맥락(쓰는 모형이 없으면 `None`)과 사실 줄에 쓰는 모형 요약."""

    context: RuleContext | None
    models: tuple[dict, ...] | list[dict]


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


def load(username: str, spec: RuleSpec, start: date) -> Loaded:
    """그 규칙이 쓰는 모형을 읽는다 — ★봉을 읽기 전에★. 거절할 것은 사유와 함께 `HTTPException`."""
    wanted = uses(spec)
    if not wanted:
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
    return Loaded(RuleContext(day_types=refs), models)


def attach(days: list[Day], loaded: Loaded) -> list[Day]:
    """세션마다 같은 맥락 객체를 싣는다. 맥락이 없으면 받은 목록 그대로(같은 객체)."""
    if loaded.context is None:
        return days
    ctx = loaded.context
    return [replace(d, sessions={t: replace(s, context=ctx) for t, s in d.sessions.items()}) for d in days]


def facts(loaded: Loaded, tickers: list[str]) -> list[dict]:
    """판정 응답의 사실 줄 — 모형마다 학습 기간 · 종목 수 · 판정 종목과 같은지 · 합성이면 그렇다고."""
    out = []
    for m in loaded.models:
        same = sorted(m["tickers"]) == sorted(tickers)
        sentences = [f"하루 유형 모형 {m['key'][:8]}의 학습 기간은 {m['first_day']}~{m['last_day']}이며 "
                     f"종목 {len(m['tickers'])}개로 학습했습니다. 학습은 판정 시작일 전에 끝났습니다.",
                     SAME_TICKERS if same else OTHER_TICKERS]
        if m["grade"] == GRADE_SYNTHETIC:
            sentences.append(SYNTHETIC_FACT)
        out.append({**m, "same_tickers": same, "sentences": sentences})
    return out
