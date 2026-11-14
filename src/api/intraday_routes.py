"""분봉 백테스트의 문 (설계: 2026-11-14 분봉 백테스트 · W4).

지금 있는 문은 하나다 — `GET /api/v1/intraday/coverage`: 분봉이 ★어느 날 · 어떤 출처로 · 얼마나★ 있는지.
파일만 읽는다(증권사 클라이언트를 만들지 않는다 · 쓰지 않는다). 출처와 운영 차단은 `src/data/minute_bars`,
세는 일은 `src/data/minute_quality` 가 하고, 이 문은 ⑴ 로그인 ⑵ 상한과 사유 ⑶ 하루 요약의 기억 ⑷ 시간 예산을 맡는다.

★값이 없는 것을 0 으로 내지 않는다★ — 운영 게이트가 막은 합성 하루, 읽지 못한 파일, 시간 예산을 넘겨 아직 확인하지
않은 하루는 봉 수가 `None` 이고 사유가 붙는다. 분봉만으로 알 수 없는 것(봉 시각의 뜻 · 소급 한도 · 단일가·VI·정지)은
답에 늘 사유와 확인 방법을 실어 보낸다.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

import src.data.minute_bars as minute_bars
from src.api.auth import require_login
from src.data.market_rules import session_rules
from src.data.minute_quality import DEFECTS, check_day
from src.data.mock_gate import mock_allowed

router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

#: 한 번에 물을 수 있는 기간(달력 일수)과 종목 수. 넘으면 ★잘라서 답하지 않는다★.
MAX_COVERAGE_DAYS = 31
MAX_DETAIL_TICKERS = 30

#: 한 요청이 하루 요약을 새로 세는 데 쓰는 시간(초). 전 종목 하루(약 백만 줄)를 읽고 세는 데 이 환경에서 2초쯤 걸렸다 —
#: 처음 묻는 한 달이면 한 요청을 넘는다. 넘긴 날은 `not_checked` 로 답하고, 센 날은 기억해 두어 다음 요청이 이어서 센다.
CHECK_BUDGET_SEC = 8.0

REASONS = {
    "not_checked_yet": "한 번에 확인할 수 있는 시간을 넘겨 이 날짜는 아직 확인하지 않았습니다. 다시 불러오면 이어서 확인합니다.",
    "range_too_long": "기간이 한 번에 볼 수 있는 일수를 넘었습니다.",
    "bad_range": "시작일이 종료일보다 늦습니다.",
    "too_many_tickers": "종목 수가 한 번에 볼 수 있는 수를 넘었습니다.",
}

#: 분봉만으로는 알 수 없는 것. 답에 늘 실린다 — 화면이 이 사정을 감추지 않게.
UNKNOWNS = (
    {"what": "bar_label", "label": "봉 시각의 뜻",
     "reason": "봉의 시각이 그 1분의 시작인지 끝인지 확인하지 못했습니다. 시각 조건은 1분 어긋날 수 있습니다.",
     "how_to_verify": "실제 키로 당일 분봉을 받아 첫 봉과 마지막 봉의 시각을 봅니다."},
    {"what": "lookback", "label": "과거 분봉의 소급 한도",
     "reason": "제공자가 과거 분봉을 얼마나 멀리 주는지 문서에 없고 실제 키 없이는 잴 수 없습니다.",
     "how_to_verify": "python -m src.data.minute_bars --probe"},
    {"what": "auction_vi_halt", "label": "단일가 · 변동성 완화장치 · 거래정지",
     "reason": "제공자 응답에 표시가 없어 어느 봉이 그 구간인지 알 수 없습니다. 종가 단일가 구간은 시각으로 추론합니다.",
     "how_to_verify": "거래소 공시와 그날의 봉을 맞춰 봅니다."},
)

_SUMMARY_KEYS = ("tickers", "bars", "sources", "defects", "defect_total", "zero_volume_bars",
                 "session_shifted", "session_shift", "shift_reason")

#: 하루 요약의 기억 — (파일 · 고친 시각 · 크기 · 게이트 · 정규장 시각) → 요약. 프로세스 로컬이다(`--workers 1`).
#: ★게이트가 열쇠에 들어 있다★: 모의 게이트에서 센 합성 하루가 게이트가 닫힌 뒤 '적재됨'으로 나가면 안 된다.
_summaries: dict[tuple, dict] = {}


def clear_coverage_cache() -> None:
    _summaries.clear()


def _refuse(code: str, **extra) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "reason": REASONS[code], **extra})


def _blank(day: str, status: str, reason: str, message: str, blocked_rows: int = 0) -> dict:
    return {"date": day, "status": status, **dict.fromkeys(_SUMMARY_KEYS), "blocked_rows": blocked_rows,
            "reason": reason, "message": message, "by_ticker": {}, "missing_tickers": []}


def _day_row(day: str, wanted: list[str], rules: dict, started: float) -> dict | None:
    """하루의 답. 파일이 없으면 `None`(목록에 싣지 않는다)."""
    path = minute_bars._existing_day_path(day)
    if path is None:
        return None
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size, mock_allowed(), rules.get("open"), rules.get("close"))
    known = _summaries.get(key)
    if known is not None and not wanted:
        return {**known, "by_ticker": {}, "missing_tickers": []}
    if time.monotonic() - started >= CHECK_BUDGET_SEC:
        return _blank(day, "not_checked", "not_checked_yet", REASONS["not_checked_yet"])

    loaded = minute_bars.load_day_frame(day)
    if loaded.frame is None:
        status = "blocked" if loaded.reason == "synthetic_rows_blocked" else "unreadable"
        row = _blank(day, status, loaded.reason, minute_bars.DAY_REASONS[loaded.reason], loaded.blocked_rows)
        _summaries[key] = {k: v for k, v in row.items() if k not in ("by_ticker", "missing_tickers")}
        return row
    checked = check_day(loaded.frame, rules, detail=wanted)
    summary = {"date": day, "status": "loaded", **{k: checked[k] for k in _SUMMARY_KEYS},
               "blocked_rows": loaded.blocked_rows, "reason": None, "message": None}
    _summaries[key] = summary
    return {**summary, "by_ticker": checked["by_ticker"],
            "missing_tickers": [t for t in wanted if t not in checked["by_ticker"]]}


@router.get("/coverage")
def coverage(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    tickers: str | None = None,
    _user=Depends(require_login),
) -> dict:
    end = to or date.today()
    start = from_ or end - timedelta(days=MAX_COVERAGE_DAYS - 1)
    if start > end:
        raise _refuse("bad_range")
    span = (end - start).days + 1
    if span > MAX_COVERAGE_DAYS:
        raise _refuse("range_too_long", limit=MAX_COVERAGE_DAYS, days=span)
    wanted = list(dict.fromkeys(t.strip() for t in (tickers or "").split(",") if t.strip()))
    if len(wanted) > MAX_DETAIL_TICKERS:
        raise _refuse("too_many_tickers", limit=MAX_DETAIL_TICKERS, tickers=len(wanted))

    rules = session_rules()
    started = time.monotonic()
    rows = []
    for back in range(span):                                   # 최근 날짜부터 센다 — 예산이 모자라면 오래된 쪽이 남는다
        row = _day_row((end - timedelta(days=back)).isoformat(), wanted, rules, started)
        if row is not None:
            rows.append(row)
    rows.reverse()

    loaded = [r for r in rows if r["status"] == "loaded"]
    summary = {
        "calendar_days": span,
        "loaded_days": len(loaded),
        "blocked_days": sum(r["status"] == "blocked" for r in rows),
        "unreadable_days": sum(r["status"] == "unreadable" for r in rows),
        "not_checked_days": sum(r["status"] == "not_checked" for r in rows),
        "bars": sum(r["bars"] for r in loaded),
        "sources": {name: sum(r["sources"][name] for r in loaded) for name in ("kis", "synthetic", "unknown")},
        "defect_total": sum(r["defect_total"] for r in loaded),
    }
    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "gate": {"mock": mock_allowed()},
        "days": rows,
        "summary": summary,
        "empty": None if rows else {"reason": "not_loaded", "message": "이 기간에 적재된 분봉이 없습니다."},
        "session_rules": {k: rules.get(k) for k in ("available", "open", "closing_auction_from", "close", "grade",
                                                    "sources", "reason", "message")},
        "defect_names": list(DEFECTS),
        "unknowns": [dict(u) for u in UNKNOWNS],
        "limits": {"days": MAX_COVERAGE_DAYS, "tickers": MAX_DETAIL_TICKERS},
    }
