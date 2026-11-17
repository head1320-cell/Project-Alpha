"""국면별 성과 나눔의 문 (설계 2026-11-17 §3 · 구현 계획 §7.3 · K2a).

- `GET /trials/{trial_key}/regime-split?index=KOSPI|KOSDAQ&k=2..4` — 내 시행 하나의 일별 흐름을 그 기간의 시장 국면(가장 큰 확률)별로 나눈다.

★읽기만이다★ — 시행 줄을 읽고(실행 횟수 불변) 국면을 계산할 뿐, 시행을 남기지 않고 아무 표에도 쓰지 않는다(시행 수 N 이 늘지 않는다).
남의 시행과 없는 시행은 같은 답(404)이고, 기록을 읽지 못하면 '없음'이 아니라 503 이다.
국면은 시장 국면의 문과 ★같은 함수★(`regime_answer`)로 계산한다 — 같은 읽기 · 같은 등급 규칙 · 같은 빈 값 사유(운영 합성 거절 · 장애 ≠ 없음).
운영에서는 합성 분봉으로 남은 시행을 나누지 않는다(그 시행의 손익이 합성 분봉의 값이다).
나눔은 관측이며 결정에 쓰지 않는다 — 국면 조건을 넣으면 나아진다는 뜻이 아니다. 계산은 `src/engine/regime_split`.
주문 경로 · 증권사 클라이언트를 들이지 않는다.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.auth import require_login
from src.api.intraday_market_regime_routes import INDEXES, regime_answer
from src.data import intraday_trials as trials
from src.data.mock_gate import mock_allowed
from src.engine import market_regime as mr
from src.engine.regime_split import split_by_regime

logger = logging.getLogger("api.intraday.regime_split")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

REASONS = {
    "store_unavailable": "시행 기록을 읽지 못했습니다. 시행이 없다는 뜻이 아닙니다.",
    "not_found": "그 시행을 찾지 못했습니다.",
}
EMPTY = {
    "no_flow": "이 시행의 기록에 일별 손익이 없어 나누지 않았습니다.",
    "flow_mismatch": "이 시행의 일별 손익이 거래일 수와 맞지 않아 나누지 않았습니다.",
    "bad_flow": "이 시행의 일별 기록을 읽을 수 없어 나누지 않았습니다.",
    "state_out_of_range": "국면 계산이 국면 수 밖의 번호를 내어 나누지 않았습니다. 시행 기록의 문제가 아닙니다.",
    "synthetic_trial_in_production": "운영에서는 합성 분봉으로 남은 시행을 나누지 않습니다.",
}
#: 엔진의 거절 코드 → 빈 값 사유. 그 밖의 값 오류(숫자가 아닌 값 등)는 `bad_flow` — 사유가 원인과 같아야 한다.
_ENGINE_REFUSALS = ("flow_mismatch", "state_out_of_range")
NOTES = (
    "국면별 숫자는 관측이며 결정에 쓰지 않습니다.",
    "국면 조건을 규칙에 넣으면 나아진다는 뜻이 아닙니다.",
    "그날의 국면은 그날 시가 전에 아는 값(전 거래일 종가까지)입니다.",
    "날 수가 적은 국면의 숫자는 그 날 수와 함께 읽으십시오.",
    "손익은 이 시행의 마지막 실행이 남긴 일별 값입니다.",
)


def _empty(code: str) -> dict[str, str]:
    return {"reason": code, "message": EMPTY[code]}


@router.get("/trials/{trial_key}/regime-split")
def regime_split(trial_key: str = Path(..., min_length=1, max_length=128),
                 index: Literal["KOSPI", "KOSDAQ"] = Query(...),
                 k: int = Query(..., ge=mr.K_RANGE[0], le=mr.K_RANGE[1]),
                 user=Depends(require_login)) -> dict[str, Any]:
    got = trials.daily_of(user.username, trial_key)
    if got is None:
        raise HTTPException(status_code=503, detail={"code": "store_unavailable", "reason": REASONS["store_unavailable"]})
    if not got["found"]:
        raise HTTPException(status_code=404, detail={"code": "not_found", "reason": REASONS["not_found"]})

    mock = mock_allowed()
    shared: dict[str, Any] = {"trial_key": trial_key, "index": index, "name": INDEXES[index], "k": k, "from": got["from"],
                              "to": got["to"], "mock": mock, "trial_grade": got["grade"] if got["grade"] in ("E0", "E3") else None,
                              "notes": list(NOTES)}
    nothing = {"split": None, "regime_grade": None, "regime_grade_reason": None, "source": None, "coverage": None}
    if got["grade"] == "E0" and not mock:
        logger.warning("운영에서 합성 분봉의 시행을 나누려 했다 — 나누지 않는다")
        return {**shared, **nothing, "empty": _empty("synthetic_trial_in_production")}
    daily = got["daily"]
    if not isinstance(daily, dict) or not daily.get("dates") or daily.get("values") is None:
        return {**shared, **nothing, "empty": _empty("no_flow")}

    regime = regime_answer(index, k, date.fromisoformat(got["from"]), date.fromisoformat(got["to"]))
    part = {"regime_grade": regime["grade"], "regime_grade_reason": regime["grade_reason"], "source": regime["source"],
            "coverage": regime["coverage"]}
    if regime["empty"] is not None:
        return {**shared, **part, "split": None, "empty": regime["empty"]}
    try:
        split = split_by_regime(daily, regime["days"], k)
    except (ValueError, KeyError, TypeError) as err:
        code = str(err) if isinstance(err, ValueError) and str(err) in _ENGINE_REFUSALS else "bad_flow"
        logger.warning("시행을 국면별로 나누지 않는다(%s)", code)
        return {**shared, **part, "split": None, "empty": _empty(code)}
    return {**shared, **part, "split": split, "empty": None}
