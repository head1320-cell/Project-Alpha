"""하루 유형 모형의 문 (설계 2026-11-16 §3 T1 · 구현 계획 §5.3).

- `POST /day-types`       장 시작 N분의 경로로 하루 유형 모형을 학습한다(쓰기 — 같은 입력은 같은 열쇠 · 다시 학습하지 않는다).
- `GET  /day-types`       내 모형들(최신 순 · 요약).
- `GET  /day-types/{key}` 내 모형 하나(중심 경로 · 유형별 표본 수 · 표본별 유형까지).

봉은 실행 문과 ★같은 길★로 읽는다 — 같은 상한(`intraday_routes.checked_scope` · `planned`) · 같은 준비(`minute_feed.build_days`) ·
같은 운영 게이트(로더가 합성 행을 막는다). 이 문이 한 번 더 본다: 운영에서 합성 표본이 하나라도 섞이면 학습하지 않는다.
운영에서 읽기는 합성(E0) 모형을 내주지 않는다 — 목록은 뺀 수와 사유를 싣고(조용히 줄이지 않는다), 하나는 없는 것과 같은 답이다.

★학습은 시행이 아니다★ — 규칙을 돌린 것이 아니므로 시행 기록(`intraday_trials`)에 쓰지 않는다. ★도구는 유형 수를 고르지 않는다★ —
k 와 N 은 받은 그대로다. 계산은 `src/engine/intraday/day_types`, 저장은 `src/data/intraday_day_types` 가 한다.
이 문은 ⑴ 로그인 ⑵ 상한과 사유 ⑶ 같은 열쇠의 재사용 ⑷ 게이트만 맡는다. 주문 경로 · 증권사 클라이언트를 들이지 않는다.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import src.data.minute_bars as minute_bars
from src.api import intraday_routes as base
from src.api.auth import require_login
from src.data import intraday_day_types as store
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.data.mock_gate import mock_allowed
from src.engine.intraday import GRADE_REASONS, day_types
from src.engine.intraday.simulator import SKIP_REASONS

logger = logging.getLogger("api.intraday.day_types")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

GRADE_SYNTHETIC = base.GRADE_SYNTHETIC
_KEY = re.compile(r"[0-9a-f]{64}")

REASONS = {
    **day_types.REFUSALS,
    "not_loaded": base.EMPTY["not_loaded"],
    "synthetic_in_production": "운영에서는 모의 모드에서 만든 합성 분봉으로 학습하지 않습니다.",
    "store_unavailable": store.REASONS["store_unavailable"],
    "not_found": "그 하루 유형 모형이 없습니다.",
}
HIDDEN_SYNTHETIC = "운영에서는 합성 분봉으로 학습한 모형을 보이지 않습니다."
#: 답에 늘 싣는 사실 — 이 모형이 무엇이 아닌지.
NOTES = (
    "유형은 장 시작 구간의 가격 경로가 닮은 표본끼리 묶은 것입니다. 그 뒤의 움직임이나 수익을 예측한다는 뜻이 아닙니다.",
    "유형 번호는 구간 마지막 분의 값(첫 봉 시가 대비)이 낮은 것부터 매겼습니다. 번호에 다른 뜻은 없습니다.",
    "그날의 유형은 구간의 마지막 봉이 닫힌 뒤에야 정해집니다.",
)


class DayTypeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tickers: list[str]
    from_: date = Field(alias="from")
    to: date
    minutes: int = 30
    k: int = 6


def _refuse(code: str, status: int = 400, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "reason": REASONS[code], **extra})


def _limits() -> dict:
    return {"tickers": base.MAX_DETAIL_TICKERS, "ticker_days": base.MAX_TICKER_DAYS, "range_days": base.MAX_RANGE_DAYS,
            "bytes": base.MAX_LOAD_BYTES, "minutes": [day_types.MIN_MINUTES, day_types.MAX_MINUTES],
            "k": [day_types.MIN_K, day_types.MAX_K], "min_samples_per_type": day_types.MIN_SAMPLES_PER_TYPE}


def _message(reason: str) -> str | None:
    return day_types.EXCLUDE_REASONS.get(reason) or SKIP_REASONS.get(reason) or minute_bars.DAY_REASONS.get(reason)


def _excluded(rows: list[tuple[str, str, str]]) -> dict:
    """뺀 표본의 요약 — 사유별 수 · 사유의 문장(행 목록이 잘려도 모든 사유의 문장이 남는다) · 앞의 행들."""
    counts = dict(Counter(r for _, _, r in rows))
    return {"total": len(rows), "by_reason": counts, "messages": {r: _message(r) for r in counts},
            "rows": [{"date": d, "ticker": t, "reason": r, "message": _message(r)} for d, t, r in rows[:base.SKIPPED_LIMIT]]}


def _body(got: day_types.Collected, fitted: dict, request: dict) -> dict:
    """저장하는 몸통 — 이 모형을 다시 설명하는 데 필요한 것 전부(T2 가 학습한 날을 읽는다)."""
    return {
        "request": request,
        "types": fitted["types"], "loss": fitted["loss"], "agreement": fitted["agreement"],
        "members": [{"date": d, "ticker": t, "type": label, "start": s[:4]}
                    for (d, t), label, s in zip(got.samples, fitted["labels"], got.starts, strict=True)],
        "days": sorted({d for d, _ in got.samples}),
        "starts": [{"start": s, "samples": n} for s, n in sorted(Counter(s[:4] for s in got.starts).items())],
        "excluded": _excluded(got.excluded), "sources": got.sources,
    }


def _summary(row: dict) -> dict:
    return {k: row[k] for k in ("key", "created_at", "method", "version", "seed", "minutes", "k", "grade", "tickers",
                                "first_day", "last_day", "samples")} | {"synthetic": row["grade"] == GRADE_SYNTHETIC}


def _view(row: dict) -> dict:
    grade = row["grade"]
    return {**_summary(row), "grade_reason": GRADE_REASONS.get(grade if grade in ("E0", "E3") else "unknown"),
            **{k: row["body"][k] for k in ("request", "types", "loss", "agreement", "members", "days", "starts", "excluded")}}


def _answer(row: dict, *, created: bool, stored: bool) -> dict:
    return {"model": _view(row), "created": created, "stored": stored,
            "store_reason": None if stored else REASONS["store_unavailable"], "notes": list(NOTES),
            "gate": {"mock": mock_allowed()}, "limits": _limits()}


@router.post("/day-types")
def train(body: DayTypeBody, user=Depends(require_login)) -> dict:
    tickers = base.checked_scope(body.tickers, body.from_, body.to)
    try:
        day_types.check_setting(body.minutes, body.k)
    except day_types.DayTypeError as err:
        raise _refuse(err.code, **err.detail) from None
    plan = base.planned(body.from_, body.to, tickers)              # 상한은 읽기 전에(실행 문과 같은 값)
    if not plan.dates:
        raise _refuse("not_loaded")
    days = minute_feed.build_days(tickers, body.from_, body.to, rules=session_rules())
    got = day_types.collect(days, body.minutes)
    if not mock_allowed() and got.sources.get("synthetic"):         # 로더가 막았어야 한다 — 한 번 더 본다
        raise _refuse("synthetic_in_production", samples=got.sources["synthetic"])
    needed = day_types.MIN_SAMPLES_PER_TYPE * body.k
    if len(got.samples) < needed:
        raise _refuse("too_few_samples", samples=len(got.samples), needed=needed, k=body.k, excluded=_excluded(got.excluded))

    key = day_types.model_key(got, minutes=body.minutes, k=body.k)
    known = store.model_of(user.username, key)
    if known is not None and known["found"]:                        # 같은 입력 = 같은 모형 — 다시 학습하지 않는다
        logger.info("day types: key=%s… reused", key[:8])
        return _answer(known, created=False, stored=True)
    try:
        fitted = day_types.fit(got.X, body.k)
    except day_types.DayTypeError as err:
        raise _refuse(err.code, **err.detail) from None
    request = {"tickers": tickers, "from": body.from_.isoformat(), "to": body.to.isoformat(), "minutes": body.minutes,
               "k": body.k}
    head = {"grade": got.grade, "minutes": body.minutes, "k": body.k, "method": day_types.METHOD,
            "version": day_types.VERSION, "seed": day_types.SEED, "tickers": sorted({t for _, t in got.samples}),
            "first_day": got.samples[0][0], "last_day": got.samples[-1][0], "samples": len(got.samples)}
    kept = _body(got, fitted, request)
    saved = store.save(user.username, key=key, body=kept, **head)
    logger.info("day types: key=%s… samples=%s k=%s stored=%s", key[:8], len(got.samples), body.k, saved is not None)
    if saved is None:                                               # 모형은 답하되 남기지 못했다고 말한다
        return _answer({"key": key, "created_at": None, **head, "body": kept}, created=True, stored=False)
    return _answer(saved["model"], created=saved["created"], stored=True)


@router.get("/day-types")
def my_day_types(limit: int = Query(50, ge=1, le=200), user=Depends(require_login)) -> dict:
    """내 모형들 — 운영 게이트에서는 합성 모형을 빼고 그 수를 싣는다. 못 읽으면 빈 목록이 아니라 `available: false` + 사유."""
    mock = mock_allowed()
    rows = store.models_of(user.username, limit)
    if rows is None:
        return {"available": False, "reason": REASONS["store_unavailable"], "models": [], "hidden_synthetic": None,
                "hidden_reason": None, "gate": {"mock": mock}, "limits": _limits()}
    shown = [r for r in rows if mock or r["grade"] != GRADE_SYNTHETIC]
    hidden = len(rows) - len(shown)
    return {"available": True, "reason": None, "models": [_summary(r) for r in shown], "hidden_synthetic": hidden,
            "hidden_reason": HIDDEN_SYNTHETIC if hidden else None, "gate": {"mock": mock}, "limits": _limits()}


@router.get("/day-types/{key}")
def my_day_type(key: str, user=Depends(require_login)) -> dict:
    """내 모형 하나. 남의 것 · 없는 것 · 운영의 합성 모형은 같은 답(404)이다."""
    if not _KEY.fullmatch(key):
        raise _refuse("not_found", status=404)
    row = store.model_of(user.username, key)
    if row is None:
        raise _refuse("store_unavailable", status=503)
    if not row["found"] or (row["grade"] == GRADE_SYNTHETIC and not mock_allowed()):
        raise _refuse("not_found", status=404)
    return _answer(row, created=False, stored=True)
