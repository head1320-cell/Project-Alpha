"""국면별 성과 나눔의 문 (설계 2026-11-17 §3 · 구현 계획 §7.3 · K2a · K2b).

- `GET /trials/{trial_key}/regime-split?index=KOSPI|KOSDAQ&k=2..4` — 내 시행 하나의 일별 흐름을 그 기간의 시장 국면(가장 큰 확률)별로 나눈다(K2a).
- `GET /trials/{trial_key}/regime-day-types?index&k&model` — 그 시행의 종목 · 기간의 (날, 종목) 표본을 내 하루 유형 모형으로 배정해
  그날의 시장 국면별로 유형마다 센다(K2b · 하루 유형 비율 × 국면).

★읽기만이다★ — 시행 줄 · 모형 줄 · 적재된 분봉을 읽고 국면을 계산할 뿐, 규칙을 돌리지 않고 시행을 남기지 않고 아무 표에도 쓰지 않는다
(시행 수 N 이 늘지 않는다). 남의 시행 · 남의 모형은 없는 것과 같은 답(404)이고, 기록을 읽지 못하면 '없음'이 아니라 503 이다.
국면은 시장 국면의 문과 ★같은 함수★(`regime_answer`)로 계산한다 — 같은 읽기 · 같은 등급 규칙 · 같은 빈 값 사유(운영 합성 거절 · 장애 ≠ 없음).
운영에서는 합성 분봉으로 남은 시행 · 합성 분봉으로 학습한 모형 · 합성 분봉의 표본을 쓰지 않는다.
표본의 봉은 실행 · 학습 문과 ★같은 준비★(같은 상한 · `minute_feed.build_days`)로 읽고, 유형은 학습 문과 ★같은 배정★(`day_types.collect` · `assign`)으로 센다.
나눔과 비율은 관측이며 결정에 쓰지 않는다 — 국면 조건을 넣으면 나아진다는 뜻도, 국면이 유형을 예측한다는 뜻도 아니다.
계산은 `src/engine/regime_split` · `src/engine/regime_day_types`. 주문 경로 · 증권사 클라이언트를 들이지 않는다.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Path, Query

import src.data.minute_bars as minute_bars
from src.api import intraday_routes as base
from src.api.auth import require_login
from src.api.intraday_context import SYNTHETIC_FACT
from src.api.intraday_market_regime_routes import INDEXES, regime_answer
from src.data import intraday_day_types as models
from src.data import intraday_trials as trials
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.data.mock_gate import mock_allowed
from src.engine import market_regime as mr
from src.engine.intraday import GRADE_REASONS, day_types
from src.engine.intraday.simulator import SKIP_REASONS
from src.engine.regime_day_types import day_types_by_regime
from src.engine.regime_split import split_by_regime

logger = logging.getLogger("api.intraday.regime_split")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

GRADE_SYNTHETIC = "E0"
_MODEL_KEY = re.compile(r"[0-9a-f]{64}")

REASONS = {
    "store_unavailable": "시행 기록을 읽지 못했습니다. 시행이 없다는 뜻이 아닙니다.",
    "not_found": "그 시행을 찾지 못했습니다.",
    "model_not_found": "그 하루 유형 모형을 찾지 못했습니다. 내가 학습한 모형만 쓸 수 있습니다.",
    "model_store_unavailable": models.REASONS["store_unavailable"],
}
EMPTY = {
    "no_flow": "이 시행의 기록에 일별 손익이 없어 나누지 않았습니다.",
    "flow_mismatch": "이 시행의 일별 손익이 거래일 수와 맞지 않아 나누지 않았습니다.",
    "bad_flow": "이 시행의 일별 기록을 읽을 수 없어 나누지 않았습니다.",
    "state_out_of_range": "국면 계산이 국면 수 밖의 번호를 내어 나누지 않았습니다. 시행 기록의 문제가 아닙니다.",
    "synthetic_trial_in_production": "운영에서는 합성 분봉으로 남은 시행을 나누지 않습니다.",
    # 하루 유형 비율 × 국면(K2b)
    "not_loaded": base.EMPTY["not_loaded"],
    "model_unreadable": "하루 유형 모형의 기록이 그 모형의 유형 수 · 분 수와 맞지 않거나 읽히지 않아 세지 않았습니다.",
    "bad_samples": "표본 기록을 읽을 수 없어 세지 않았습니다.",
    "synthetic_samples_in_production": "운영에서는 합성 분봉의 표본을 세지 않습니다.",
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


# ── 하루 유형 비율 × 국면 (K2b) ─────────────────────────────────────────────────────────────────
#: 답에 늘 싣는 사실 — 이 표가 무엇이 아닌지. 화면은 이 글을 그대로 보인다.
DAY_TYPE_NOTES = (
    "유형 비율은 같은 날의 두 이름표를 겹쳐 센 관측입니다. 국면은 그날 시가 전에 아는 값이고 유형은 장 시작 구간이 닫힌 뒤에 정해집니다.",
    "어느 쪽이 다른 쪽을 예측한다는 뜻이 아닙니다. 비율의 차이가 그 국면의 성질이라는 뜻도 아닙니다.",
    "비율의 분모는 그 묶음에서 유형을 정한 표본입니다. 뺀 표본은 분모에 넣지 않습니다.",
    "표본 안 분류는 모형이 학습에 쓴 날(어느 종목이든)의 표본입니다. 모형이 그날을 보고 유형의 중심을 정했으므로 학습 밖의 표본과 같은 무게로 읽지 마십시오.",
    "표본은 이 시행의 종목과 기간의 분봉을 지금 다시 읽어 셉니다. 그 사이 적재가 바뀌었으면 시행이 쓴 봉과 다를 수 있습니다.",
    "표본 수가 적은 칸의 비율은 그 수와 함께 읽으십시오.",
)
#: 모형 사실 줄의 문장들(화면이 서버 글자 그대로 싣는다).
SAME_TICKERS = "이 시행의 종목과 같은 종목으로 학습했습니다."
OTHER_TICKERS = "이 시행의 종목과 학습 종목이 같지 않습니다."
NO_OVERLAP = "모형의 학습 날 가운데 이 시행의 기간 안에 있는 날은 없습니다."
SYNTHETIC_MODEL = SYNTHETIC_FACT
#: 엔진의 거절 코드 → 빈 값 사유(원인과 같은 사유). 유형 번호가 밖이면 모형의 중심이 그 모형의 유형 수와 맞지 않은 것이다.
_DAY_TYPE_REFUSALS = {"type_out_of_range": "model_unreadable", "state_out_of_range": "state_out_of_range"}


def _http(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "reason": REASONS[code]})


def excluded_message(code: str) -> str | None:
    """뺀 사유의 문장 — 하루 유형 학습 문과 같은 차례(엔진의 사유 → 시뮬레이터의 사유 → 적재의 사유). 모르는 사유는 지어내지 않는다."""
    return day_types.EXCLUDE_REASONS.get(code) or SKIP_REASONS.get(code) or minute_bars.DAY_REASONS.get(code)


def _shape(row: dict) -> tuple[np.ndarray, list[str]] | None:
    """모형의 중심 · 학습 날. 중심의 모양이 그 모형의 (유형 수, 분 수)가 아니거나 · 유한하지 않거나 · 학습 날이 없거나 · 읽히지 않으면 `None`."""
    try:
        centres = np.asarray([t["path"] for t in row["body"]["types"]], dtype=np.float64)
        days = [str(d) for d in row["body"]["days"]]
    except (KeyError, TypeError, ValueError):
        return None
    if centres.shape != (int(row["k"]), int(row["minutes"])) or not np.isfinite(centres).all() or not days:
        return None
    return centres, days


def _model_view(row: dict, key: str, trial: dict, shape: tuple[np.ndarray, list[str]] | None) -> dict[str, Any]:
    """모형 사실 — 학습 기간 · 종목 · 분 수 · 유형 수 · 이 시행의 종목과 같은지 · 이 시행의 기간 안의 학습 날 수 · 합성."""
    tickers = sorted(row["tickers"])
    same = tickers == sorted(trial["tickers"])
    overlap = None if shape is None else sum(1 for d in shape[1] if trial["from"] <= d <= trial["to"])
    facts = [f"하루 유형 모형 {key[:8]}의 학습 기간은 {row['first_day']}~{row['last_day']}이며 종목 {len(tickers)}개 · "
             f"장 시작 {row['minutes']}분 · 유형 {row['k']}개로 학습했습니다.",
             SAME_TICKERS if same else OTHER_TICKERS]
    if overlap is not None:
        facts.append(NO_OVERLAP if overlap == 0 else
                     f"모형의 학습 날 가운데 {overlap}일이 이 시행의 기간 안에 있습니다. 그날의 표본은 표본 안 분류로 따로 셉니다.")
    if row["grade"] == GRADE_SYNTHETIC:
        facts.append(SYNTHETIC_MODEL)
    return {"key": key, "minutes": int(row["minutes"]), "k": int(row["k"]), "first_day": row["first_day"],
            "last_day": row["last_day"], "tickers": tickers, "same_tickers": same, "overlap_days": overlap,
            "grade": row["grade"] if row["grade"] in ("E0", "E3") else None, "synthetic": row["grade"] == GRADE_SYNTHETIC,
            "facts": facts}


@router.get("/trials/{trial_key}/regime-day-types")
def regime_day_types(trial_key: str = Path(..., min_length=1, max_length=128),
                     index: Literal["KOSPI", "KOSDAQ"] = Query(...),
                     k: int = Query(..., ge=mr.K_RANGE[0], le=mr.K_RANGE[1]),
                     model: str = Query(..., min_length=1, max_length=128),
                     user=Depends(require_login)) -> dict[str, Any]:
    trial = trials.trial_of(user.username, trial_key)
    if trial is None:
        raise _http(503, "store_unavailable")
    if not trial["found"]:
        raise _http(404, "not_found")
    if not _MODEL_KEY.fullmatch(model):                                  # 있을 수 없는 열쇠 — 저장소를 묻지 않는다
        raise _http(404, "model_not_found")
    row = models.model_of(user.username, model)
    if row is None:
        raise _http(503, "model_store_unavailable")
    mock = mock_allowed()
    if not row["found"] or (row["grade"] == GRADE_SYNTHETIC and not mock):   # 남의 것 · 없는 것 · 운영의 합성 모형은 같은 답
        raise _http(404, "model_not_found")

    shape = _shape(row)
    shared: dict[str, Any] = {
        "trial_key": trial_key, "index": index, "name": INDEXES[index], "k": k, "from": trial["from"], "to": trial["to"],
        "mock": mock, "trial_grade": trial["grade"] if trial["grade"] in ("E0", "E3") else None,
        "model": _model_view(row, model, trial, shape), "notes": list(DAY_TYPE_NOTES)}
    regime_part: dict[str, Any] = {"regime_grade": None, "regime_grade_reason": None, "source": None, "coverage": None}
    samples_part: dict[str, Any] = {"samples_grade": None, "samples_grade_reason": None, "sources": None,
                                    "excluded_messages": {}}

    def answer(table: dict | None, empty: dict | None) -> dict[str, Any]:
        return {**shared, **regime_part, **samples_part, "table": table, "empty": empty}

    if trial["grade"] == GRADE_SYNTHETIC and not mock:
        logger.warning("운영에서 합성 분봉의 시행으로 하루 유형을 세려 했다 — 세지 않는다")
        return answer(None, _empty("synthetic_trial_in_production"))
    if shape is None:
        logger.warning("하루 유형 모형 %s… 의 기록이 머리와 맞지 않는다 — 세지 않는다", model[:8])
        return answer(None, _empty("model_unreadable"))
    start, end = date.fromisoformat(trial["from"]), date.fromisoformat(trial["to"])
    tickers = base.checked_scope(list(trial["tickers"]), start, end)
    if not base.planned(start, end, tickers).dates:                       # 상한은 읽기 전에(실행 · 학습 문과 같은 값)
        return answer(None, _empty("not_loaded"))

    regime = regime_answer(index, k, start, end)
    regime_part.update(regime_grade=regime["grade"], regime_grade_reason=regime["grade_reason"], source=regime["source"],
                       coverage=regime["coverage"])
    if regime["empty"] is not None:
        return answer(None, regime["empty"])

    got = day_types.collect(minute_feed.build_days(tickers, start, end, rules=session_rules()), int(row["minutes"]))
    if not mock and got.sources.get("synthetic"):                       # 로더가 막았어야 한다 — 한 번 더 본다
        logger.warning("운영에서 합성 분봉의 표본이 문까지 왔다 — 세지 않는다")
        return answer(None, _empty("synthetic_samples_in_production"))
    grade = "none" if not got.samples else got.grade if got.grade in ("E0", "E3") else "unknown"
    samples_part.update(samples_grade=grade if grade in ("E0", "E3") else None, samples_grade_reason=GRADE_REASONS[grade],
                        sources=dict(got.sources),
                        excluded_messages={code: excluded_message(code) for code in sorted({r for _, _, r in got.excluded})})

    centres, train_days = shape
    labels = (day_types.assign(centres, got.X) + 1).tolist()            # 학습 문 · 지표와 같은 배정(가장 가까운 중심)
    samples = [(d, t, label, None) for (d, t), label in zip(got.samples, labels, strict=True)]
    samples += [(d, t, None, why) for d, t, why in got.excluded]
    try:
        table = day_types_by_regime(samples, regime["days"], k, int(row["k"]), train_days)
    except (ValueError, KeyError, TypeError) as err:
        code = _DAY_TYPE_REFUSALS.get(str(err), "bad_samples") if isinstance(err, ValueError) else "bad_samples"
        logger.warning("하루 유형을 국면별로 세지 않는다(%s)", code)
        return answer(None, _empty(code))
    return answer(table, None)
