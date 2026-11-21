"""하루 유형 비중을 더한 시장 국면의 문 둘 (설계 2026-11-17 §6 · 구현 계획 §7.6 · K5).

- `POST /market-regime/day-type-counts` — 내 하루 유형 모형으로 바구니 종목의 날마다 유형을 세어 남긴다
  (쓰기 · 예산 안에서 날짜 순 · 남은 날은 다음 부름이 이어 센다).
- `GET  /market-regime/day-type-input`  — 지수만의 국면(시장 국면 문의 답 그대로)과, 고른 유형의 20거래일 합친 비중을 셋째 특징으로
  더한 국면을 나란히(★읽기만 — 아무 표에도 쓰지 않는다★).

**센 날** = 시장 국면 문과 ★같은 읽기 구간★(판정 시작일의 `HISTORY_CALENDAR_DAYS` 앞부터)의 지수 거래일 가운데 기간 안 마지막 거래일 ★전★의 날 —
거래일 d 의 국면은 d−1 의 비중(d−20 ~ d−1 의 표본)을 쓰므로 마지막 거래일의 표본은 어느 날의 국면에도 쓰이지 않는다.
세기는 실행 · 학습 문과 ★같은 준비★(`minute_feed.build_days`)와 ★같은 배정★(`day_types.collect` · `assign` · 모형의 분 수 · 저장된 중심)이다.
날마다 그날 일파일의 서명을 남기고(`day_type_counts.day_sig`), 서명이 지금과 다른 줄은 낡음으로 보고 쓰지 않는다 — 세기 문이 다시 센다.
세기 직전에 그날 일파일의 캐시를 비우고 읽기 앞뒤의 서명이 같을 때만 남긴다(서명과 내용이 다른 파일 상태를 보지 않게).

거절(사유와 함께 · 읽기 전에): 기간 규칙 = 시장 국면 문의 규칙 · 바구니 1 ~ 30종목 · 있을 수 없는 열쇠 · 남의 모형 · 없는 모형 · 운영의 합성 모형 =
같은 404(규칙 문과 같은 코드 · 같은 문장) · ★학습 마지막 날 ≥ 판정 시작일★(규칙 문과 같은 거절) · 유형 고르기(빈 · 범위 밖 · 중복 · 전부).
저장소 장애는 '없음'이 아니라 503 이다. 운영에서 합성 분봉의 표본은 세지 않는다(로더가 막는다 — 이 문이 한 번 더 본다).

★시행이 아니다★ — 규칙을 돌리지 않고 시행 기록에 쓰지 않는다(시행 수 N 불변). 다만 유형 조합 · 바구니를 바꿔 가며 다시 볼 수 있다는 사실을
답의 한계 문장에 적는다. ★도구는 유형 · 바구니 · 창 길이를 고르지 않는다★ — 받은 그대로이고 창은 시장 국면의 상수(20거래일)다.
계산은 `src/engine/day_type_share` · `src/engine/market_regime`, 저장은 `src/data/day_type_counts`. 주문 경로 · 증권사 클라이언트를 들이지 않는다.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import date
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import src.data.minute_bars as minute_bars
from src.api import intraday_context as ctx
from src.api import intraday_market_regime_routes as k1
from src.api import intraday_routes as base
from src.api.auth import require_login
from src.data import day_type_counts as counts
from src.data import intraday_day_types as models
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.data.mock_gate import mock_allowed
from src.engine import day_type_share as ds
from src.engine import market_regime as mr
from src.engine.intraday import GRADE_REASONS, day_types
from src.engine.intraday.simulator import SKIP_REASONS

logger = logging.getLogger("api.intraday.regime_share")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

GRADE_SYNTHETIC = "E0"
_KEY = re.compile(r"[0-9a-f]{64}")
#: 한 번의 세기 부름이 쓰는 시간 · 읽는 바이트의 상한 — 실행 문의 상한과 같은 값. 첫 날은 상한과 무관하게 센다(부름마다 나아간다).
COUNT_BUDGET_SEC = base.CHECK_BUDGET_SEC
COUNT_MAX_BYTES = base.MAX_LOAD_BYTES

REASONS = {
    "day_type_model_missing": ctx.REASONS["day_type_model_missing"],
    "day_type_model_overlaps": ctx.REASONS["day_type_model_overlaps"],
    "store_unavailable": models.REASONS["store_unavailable"],
    "counts_store_unavailable": counts.REASONS["store_unavailable"],
    "model_unreadable": "하루 유형 모형의 기록이 그 모형의 유형 수 · 분 수와 맞지 않거나 읽히지 않아 세지 않았습니다.",
    "regime_store_unavailable": ctx.REASONS["regime_store_unavailable"],
    "regime_unavailable": "지수 일봉이 없어 비중을 셀 날을 정하지 못했습니다.",
    "synthetic_samples_in_production": "운영에서는 합성 분봉의 표본을 세지 않습니다.",
}

#: 사실 줄의 문장(화면이 서버 글자 그대로 싣는다).
MODEL_FACT = ("하루 유형 모형 {key}의 학습 기간은 {first}~{last}이며 종목 {tickers}개 · 장 시작 {minutes}분 · 유형 {k}개로 학습했습니다. "
              "학습은 판정 시작일 전에 끝났습니다.")
TYPES_FACT = "고른 유형은 {types}입니다. 바구니 종목 {n}개의 표본 가운데 고른 유형의 몫을 20거래일 동안 합쳐 셋째 특징으로 썼습니다."
#: 셀 날 · 표본 수는 1,000 을 쉽게 넘는다(읽기 구간 1,250 달력일) — 화면의 수와 같게 천 단위 쉼표로 쓴다.
COUNTED = "비중을 셀 날 {needed:,}일 가운데 {counted:,}일을 셌습니다."
NOT_COUNTED = "아직 세지 않은 날 {n:,}일이 있습니다. 비중 세기로 이어서 셉니다."
STALE = "분봉 파일이나 장 운영 시각 · 게이트가 바뀌어 다시 셀 날 {n:,}일이 있습니다."
IN_SAMPLE = "비중에 쓴 표본 {classified:,}개 가운데 {n:,}개는 모형의 학습 표본입니다(표본 안 분류). 그 표본의 유형은 학습에 쓰인 값으로 정해졌습니다."
PARTIAL = "바구니의 일부 종목만 유형을 정한 날 {n:,}일은 정한 표본만으로 비중을 셌습니다."
RENUMBERED = ("비중을 더한 답에서 국면 번호가 앞 달의 적합과 다른 성분으로 바뀐 달이 {n}개 있습니다({months}). "
              "그 달 앞뒤의 같은 번호는 같은 국면이 아닐 수 있습니다.")
COMPARE = "두 답 모두 국면을 아는 날 {both:,}일 가운데 가장 큰 국면이 다른 날은 {differ:,}일입니다."
#: 답에 늘 싣는 한계 — 이 비중과 두 국면의 차이가 무엇이 아닌지.
NOTES = (
    "하루 유형 비중은 고른 유형이 바구니 표본 가운데 차지한 몫을 20거래일 동안 합친 값입니다. 다음 날의 국면이나 수익을 예측한다는 뜻이 아닙니다.",
    "그날의 국면은 전 거래일까지 20거래일의 비중을 씁니다. 그날의 하루 유형은 장 시작 구간이 끝나야 정해지므로 쓰지 않습니다.",
    "두 국면 띠의 차이는 관측입니다. 어느 쪽이 맞는다는 증거가 아닙니다.",
    "두 답의 국면 번호는 모두 적합 창에서 20거래일 실현 변동성의 평균이 낮은 국면부터 매겼습니다. 같은 번호라도 같은 국면이라는 뜻은 아닙니다.",
    "비중을 더한 답은 난수 시드마다 찾은 성분을 가장 잘 맞은 시드의 성분에 맞춘 뒤 평균합니다. 지수만의 답과 적합 방법이 이 점에서 다릅니다.",
    "유형 조합과 바구니를 바꿔 가며 다시 볼 수 있습니다. 바꿔 본 만큼 여러 번 본 것이며 시행 기록에는 남지 않습니다.",
)


#: 더한 답에 싣는 국면의 한계 — K1 의 문장 가운데 더한 답에서 틀리거나 넘치는 넷은 셋째 특징에 맞게 바꾼다:
#: 0 특징 · 2 계산 시점 · 3 적합 창(세 특징이 모두 있는 날만 · 비중을 모르는 날은 빠진다 — `market_regime.regime_days` 의 `known`)과
#: 같은 값의 조건(종가만이 아니라 분봉도) · 5 시드 일치도의 잰 값(지수만의 답으로 쟀다). 번호(1) · BIC(4)는 같은 말이 그대로 맞다.
WITH_SHARE_NOTES = (
    "국면은 지수의 20거래일 수익 · 실현 변동성과 하루 유형 비중이 닮은 날끼리 묶은 이름표입니다. 다음 날의 국면이나 수익을 예측한다는 뜻이 아닙니다.",
    k1.NOTES[1],
    "그날의 확률은 전 거래일 종가와 전 거래일까지 20거래일의 하루 유형 비중으로 계산합니다. 그날 종가와 그날의 하루 유형은 쓰지 않습니다.",
    f"적합은 달마다 그달 첫 거래일 전에 세 특징(20거래일 수익 · 실현 변동성 · 하루 유형 비중)이 모두 있는 마지막 {mr.FIT_DAYS}거래일로 다시 합니다. "
    f"비중을 모르는 날은 창에서 빠지고, 세 특징이 모두 있는 날이 {mr.FIT_DAYS}거래일보다 적은 달은 계산하지 않습니다. "
    "같은 종가와 같은 분봉에서는 같은 날이 언제 다시 봐도 같은 값입니다.",
    k1.NOTES[4],
    "난수 시드 일치도가 높다고 국면이 있다는 뜻이 아닙니다. 국면이 없는 합성 자료(변동성이 일정한 걸음)에서 지수만의 답의 일치도가 1 에 가깝게 "
    "나온 경우가 있었습니다(잰 값). 비중을 더한 답으로는 재지 않았습니다.",
)


class CountBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    model: str = Field(min_length=1, max_length=128)
    tickers: list[str]
    index: Literal["KOSPI", "KOSDAQ"]
    from_: date = Field(alias="from")
    to: date


def _refuse(code: str, status: int = 400, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "reason": REASONS[code], **extra})


def _message(code: str) -> str | None:
    return day_types.EXCLUDE_REASONS.get(code) or SKIP_REASONS.get(code) or minute_bars.DAY_REASONS.get(code)


def _grade(sources: Counter) -> str:
    """쓴 표본의 출처 등급 — 실행 문과 같은 규칙(가장 약한 출처가 정한다)."""
    if not sum(sources.values()):
        return "none"
    return "E0" if sources["synthetic"] else "unknown" if sources["unknown"] else "E3"


def _model(user: str, key: str, start: date) -> tuple[dict, np.ndarray, set[tuple[str, str]]]:
    """내 모형 → (줄, 중심, 학습 표본). 남의 것 · 없는 것 · 있을 수 없는 열쇠 · 운영의 합성 모형 = 같은 404 · 학습 날 겹침 400 · 장애 503."""
    if not _KEY.fullmatch(key):                                     # 있을 수 없는 열쇠 — 저장소를 묻지 않는다
        raise _refuse("day_type_model_missing", 404)
    row = models.model_of(user, key)
    if row is None:
        raise _refuse("store_unavailable", 503)
    if not row["found"] or (row["grade"] == GRADE_SYNTHETIC and not mock_allowed()):
        raise _refuse("day_type_model_missing", 404)
    if row["last_day"] >= start.isoformat():                       # 규칙 문(T2)과 같은 거절 — 학습은 판정 시작일 전에 끝나야 한다
        raise _refuse("day_type_model_overlaps", model=key[:8], first_day=row["first_day"], last_day=row["last_day"],
                      start=start.isoformat())
    try:
        centres = np.asarray([t["path"] for t in row["body"]["types"]], dtype=np.float64)
        members = {(str(m["date"]), str(m["ticker"])) for m in row["body"]["members"]}
    except (KeyError, TypeError, ValueError):
        raise _refuse("model_unreadable") from None
    if centres.shape != (int(row["k"]), int(row["minutes"])) or not np.isfinite(centres).all():
        raise _refuse("model_unreadable")
    return row, centres, members


def _needed(dates: list[str], to: date) -> list[str]:
    """셀 날 — 읽은 지수 거래일 가운데 기간 안 마지막 거래일 전의 날(그날의 표본은 어느 날의 국면에도 쓰이지 않는다)."""
    inside = [d for d in dates if d <= to.isoformat()]
    return [d for d in dates if d < inside[-1]] if inside else []


def _index_days(index: str, start: date, end: date) -> list[str]:
    got = k1.read_index(index, start, end)
    if got.empty is None:
        return got.dates
    if got.empty["reason"] == "store_error":
        raise _refuse("regime_store_unavailable", 503, index=index)
    raise HTTPException(status_code=400, detail={"code": "regime_unavailable", "index": index, "empty": got.empty["reason"],
                                                 "reason": f"{REASONS['regime_unavailable']} {got.empty['message']}"})


def _read(user: str, key: str, needed: list[str]) -> dict[tuple[str, str], dict]:
    rows = counts.get(user, key, needed[0], needed[-1]) if needed else {}
    if rows is None:
        raise _refuse("counts_store_unavailable", 503)
    return rows


def _usable(r: dict | None, sig: str) -> bool:
    """지금 서명으로 센 · 모양이 맞는 줄(유형과 사유 가운데 꼭 하나). 어긋난 줄은 세지 않은 것으로 본다(세기 문이 덮어쓴다)."""
    return r is not None and r["sig"] == sig and ((r["label"] is None) != (r["reason"] is None))


def _progress(rows: dict, needed: list[str], tickers: list[str], sigs: dict[str, str]) -> dict[str, Any]:
    """센 날(바구니 전부가 지금 서명으로 센 날) · 낡은 날과 그날의 낡은 줄 수 · 남은 날 — 저장소의 줄로만 센다."""
    fresh, stale, todo = [], {}, []
    for d in needed:
        mine = [rows.get((d, t)) for t in tickers]
        old = sum(1 for r in mine if r is not None and r["sig"] != sigs[d])
        if old:
            stale[d] = old
        (fresh if all(_usable(r, sigs[d]) for r in mine) else todo).append(d)
    return {"fresh": fresh, "stale": stale, "todo": todo}


def _count_day(day: str, tickers: list[str], rules: dict, minutes: int, centres: np.ndarray, mock: bool) -> tuple[list[dict], int]:
    """그날 바구니 종목들의 유형 · 사유(종목마다 한 줄) · 읽은 바이트. 학습 · 실행 문과 같은 준비 · 같은 배정이다."""
    path = minute_bars._existing_day_path(day)
    if path is None:
        return [{"ticker": t, "label": None, "reason": "not_loaded", "source": None} for t in tickers], 0
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    minute_bars.clear_cache()                                       # 캐시의 옛 내용이 아니라 지금 파일을 읽는다(서명과 같은 상태)
    d = date.fromisoformat(day)
    days = minute_feed.build_days(tickers, d, d, rules=rules)
    got = day_types.collect(days, minutes)
    if not mock and got.sources.get("synthetic"):                  # 로더가 막았어야 한다 — 한 번 더 본다
        logger.warning("운영에서 합성 분봉의 표본이 비중 세기까지 왔다 — 세지 않는다(%s)", day)
        raise _refuse("synthetic_samples_in_production", day=day, samples=got.sources["synthetic"])
    labels = (day_types.assign(centres, got.X) + 1).tolist() if got.samples else []
    source_of = {t: s.source for one in days for t, s in one.sessions.items()}
    out: dict[str, dict] = {}
    for (_, t), label in zip(got.samples, labels, strict=True):
        src = source_of.get(t)
        out[t] = {"ticker": t, "label": int(label), "reason": None, "source": src if src in counts.SOURCES else "unknown"}
    for _, t, reason in got.excluded:
        out.setdefault(t, {"ticker": t, "label": None, "reason": str(reason), "source": None})
    for t in tickers:                                               # 그 사이 파일이 사라졌다 — 적재되지 않은 날과 같다
        out.setdefault(t, {"ticker": t, "label": None, "reason": "not_loaded", "source": None})
    return [out[t] for t in tickers], size


@router.post("/market-regime/day-type-counts")
def count_day_types(body: CountBody, user=Depends(require_login)) -> dict[str, Any]:
    k1.check_period(body.from_, body.to)
    tickers = base.checked_scope(body.tickers, body.from_, body.to)
    row, centres, _members = _model(user.username, body.model, body.from_)
    mock = mock_allowed()
    needed = _needed(_index_days(body.index, body.from_, body.to), body.to)
    rules = session_rules()
    minutes = int(row["minutes"])
    sigs = {d: counts.day_sig(d, rules) for d in needed}
    before = _progress(_read(user.username, body.model, needed), needed, tickers, sigs)

    started = time.monotonic()
    spent, done_days, written, stale_rows, stopped = 0, 0, 0, 0, None
    for day in before["todo"]:
        if done_days and time.monotonic() - started >= COUNT_BUDGET_SEC:
            stopped = "budget"
            break
        if done_days and spent >= COUNT_MAX_BYTES:
            stopped = "bytes"
            break
        sig = counts.day_sig(day, rules)
        rows, size = _count_day(day, tickers, rules, minutes, centres, mock)
        spent += size
        done_days += 1
        if counts.day_sig(day, rules) != sig:                      # 읽는 사이 파일이 바뀌었다 — 남기지 않고 다음 부름이 다시 센다
            logger.info("비중 세기: %s 의 일파일이 읽는 사이 바뀌어 남기지 않았다", day)
            continue
        if counts.put(user.username, body.model, day, rows, sig) is None:
            raise _refuse("counts_store_unavailable", 503)
        written += len(rows)
        stale_rows += before["stale"].get(day, 0)
    seconds = time.monotonic() - started

    sigs = {d: counts.day_sig(d, rules) for d in needed}
    stored = _read(user.username, body.model, needed)
    after = _progress(stored, needed, tickers, sigs)
    used = [stored[(d, t)] for d in after["fresh"] for t in tickers]
    excluded = Counter(r["reason"] for r in used if r["label"] is None)
    grade = _grade(Counter(r["source"] for r in used if r["label"] is not None))
    logger.info("비중 세기: model=%s… days=%s rows=%s remaining=%s", body.model[:8], done_days, written, len(after["todo"]))
    return {
        "model": body.model, "index": body.index, "from": body.from_.isoformat(), "to": body.to.isoformat(), "tickers": tickers,
        "needed_days": len(needed), "counted_days": len(after["fresh"]), "remaining_days": len(after["todo"]),
        "stale_days": len(after["stale"]), "done": not after["todo"],
        "first_day": needed[0] if needed else None, "last_day": needed[-1] if needed else None,
        "next_day": after["todo"][0] if after["todo"] else None,
        "this_request": {"days": done_days, "rows": written, "stale_rows": stale_rows, "bytes": spent,
                         "seconds": round(seconds, 3), "stopped": stopped},
        "excluded_by_reason": dict(excluded), "excluded_messages": {c: _message(c) for c in sorted(excluded)},
        "grade": grade if grade in ("E0", "E3") else None, "grade_reason": GRADE_REASONS[grade],
        "gate": {"mock": mock},
        "limits": {"budget_sec": COUNT_BUDGET_SEC, "bytes": COUNT_MAX_BYTES, "tickers": base.MAX_DETAIL_TICKERS,
                   "window": ds.WINDOW, "history_calendar_days": k1.HISTORY_CALENDAR_DAYS},
    }


def _share_days(days: list[dict], dates: list[str], values: np.ndarray, codes: list[str | None],
                samples: np.ndarray) -> list[dict[str, Any]]:
    """판정 기간의 날마다 그날 국면이 쓴 비중(d−1 의 값) · 그 창의 표본 수 · 모르면 사유."""
    at = {d: i for i, d in enumerate(dates)}
    out = []
    for row in days:
        i = at[row["date"]] - 1
        code = "short" if i < 0 else codes[i]
        value = None if i < 0 or code is not None else float(values[i])
        out.append({"date": row["date"], "value": value, "samples": 0 if i < 0 else int(samples[i]),
                    "reason": code, "message": ds.REASONS[code] if code else None})
    return out


@router.get("/market-regime/day-type-input")
def day_type_input(index: Literal["KOSPI", "KOSDAQ"] = Query(...),
                   k: int = Query(..., ge=mr.K_RANGE[0], le=mr.K_RANGE[1]),
                   from_: date = Query(..., alias="from"),
                   to: date = Query(...),
                   model: str = Query(..., min_length=1, max_length=128),
                   types: list[int] = Query(...),
                   tickers: list[str] = Query(...),
                   user=Depends(require_login)) -> dict[str, Any]:
    k1.check_period(from_, to)
    basket = base.checked_scope(tickers, from_, to)
    row, _centres, members = _model(user.username, model, from_)
    try:
        chosen = ds.check_types(types, int(row["k"]))
    except ds.ShareError as err:
        raise HTTPException(status_code=400, detail={"code": err.code, "reason": str(err)}) from None
    rules = session_rules()
    seen: dict[str, Any] = {}

    def extra(dates: list[str]) -> tuple[np.ndarray, list[str | None]]:
        """같은 읽기의 지수 거래일 → 날마다의 비중 · 사유 문장. 지금 서명으로 센 날만 쓴다(낡은 날 · 덜 센 날 = 세지 않은 날)."""
        needed = _needed(dates, to)
        sigs = {d: counts.day_sig(d, rules) for d in needed}
        stored = _read(user.username, model, needed)
        state = _progress(stored, needed, basket, sigs)
        by_day = {d: ds.basket_day([(stored[(d, t)]["label"], stored[(d, t)]["reason"]) for t in basket]) for d in state["fresh"]}
        values, codes, samples = ds.window_share(dates, by_day, chosen)
        used = [(d, t, stored[(d, t)]) for d in state["fresh"] for t in basket]
        labelled = [(d, t, r) for d, t, r in used if r["label"] is not None]
        inside = [(d, t) for d, t, _ in labelled if (d, t) in members]
        excluded = Counter(r["reason"] for _, _, r in used if r["label"] is None)
        partial = sum(1 for d in state["fresh"] if by_day[d] and by_day[d].get("classified") and by_day[d].get("excluded"))
        seen.update(dates=dates, values=values, codes=codes, samples=samples, needed=needed, state=state,
                    classified=len(labelled), in_sample={"samples": len(inside), "days": len({d for d, _ in inside})},
                    excluded=excluded, partial=partial,
                    grade=_grade(Counter(r["source"] for _, _, r in labelled)))
        return values, [ds.REASONS[c] if c else None for c in codes]

    with_share = {**k1.regime_answer(index, k, from_, to, extra=extra), "notes": list(WITH_SHARE_NOTES)}
    index_only = k1.regime_answer(index, k, from_, to)

    view = {"key": model, "minutes": int(row["minutes"]), "k": int(row["k"]), "first_day": row["first_day"],
            "last_day": row["last_day"], "tickers": sorted(row["tickers"]),
            "grade": row["grade"] if row["grade"] in ("E0", "E3") else None, "synthetic": row["grade"] == GRADE_SYNTHETIC}
    facts = [MODEL_FACT.format(key=model[:8], first=row["first_day"], last=row["last_day"], tickers=len(row["tickers"]),
                               minutes=int(row["minutes"]), k=int(row["k"])),
             TYPES_FACT.format(types=" · ".join(f"유형 {t}" for t in chosen), n=len(basket))]
    if row["grade"] == GRADE_SYNTHETIC:
        facts.append(ctx.SYNTHETIC_FACT)
    answer: dict[str, Any] = {
        "index": index, "name": k1.INDEXES[index], "k": k, "from": from_.isoformat(), "to": to.isoformat(),
        "mock": mock_allowed(), "model": view, "types": list(chosen), "tickers": basket, "window": ds.WINDOW,
        "index_only": index_only, "with_share": with_share, "share": None, "counts": None, "compare": None,
        "facts": facts, "notes": list(NOTES),
    }
    if not seen:                                                    # 지수가 비어 비중을 쓸 데가 없었다 — 두 답의 빈 값 사유가 말한다
        return answer

    state, needed = seen["state"], seen["needed"]
    share_days = _share_days(with_share["days"], seen["dates"], seen["values"], seen["codes"], seen["samples"])
    unknown = Counter(d["reason"] for d in share_days if d["reason"])
    first_seen = {}
    for d in share_days:
        if d["reason"]:
            first_seen.setdefault(d["reason"], d["date"])
    grade = seen["grade"]
    answer["share"] = {
        "days": share_days,
        "unknown_by_reason": [{"reason": c, "days": n, "message": ds.REASONS[c]}
                              for c, n in sorted(unknown.items(), key=lambda item: (-item[1], first_seen[item[0]]))],
        "classified": seen["classified"], "in_sample": seen["in_sample"], "partial_days": seen["partial"],
        "excluded_by_reason": dict(seen["excluded"]), "excluded_messages": {c: _message(c) for c in sorted(seen["excluded"])},
        "grade": grade if grade in ("E0", "E3") else None, "grade_reason": GRADE_REASONS[grade],
    }
    remaining = len(state["todo"])
    answer["counts"] = {"needed_days": len(needed), "counted_days": len(state["fresh"]), "remaining_days": remaining,
                        "stale_days": len(state["stale"]), "first_day": needed[0] if needed else None,
                        "last_day": needed[-1] if needed else None}
    by_date = {r["date"]: r["top"] for r in index_only["days"]}
    both = [(by_date.get(r["date"]), r["top"]) for r in with_share["days"]
            if r["top"] is not None and by_date.get(r["date"]) is not None]
    answer["compare"] = {"both_days": len(both), "differ_days": sum(1 for a, b in both if a != b)}

    facts.append(COUNTED.format(needed=len(needed), counted=len(state["fresh"])))
    if remaining:
        facts.append(NOT_COUNTED.format(n=remaining))
    if state["stale"]:
        facts.append(STALE.format(n=len(state["stale"])))
    if seen["classified"]:
        facts.append(IN_SAMPLE.format(classified=seen["classified"], n=seen["in_sample"]["samples"]))
    if seen["partial"]:
        facts.append(PARTIAL.format(n=seen["partial"]))
    if grade in ("E0", "unknown"):
        facts.append(GRADE_REASONS[grade])
    fit = with_share.get("fit") or {}
    if fit.get("renumbered"):
        facts.append(RENUMBERED.format(n=fit["renumbered"], months=" · ".join(fit["renumbered_months"])))
    facts.append(COMPARE.format(both=len(both), differ=answer["compare"]["differ_days"]))
    return answer
