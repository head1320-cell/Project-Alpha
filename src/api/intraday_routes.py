"""분봉 백테스트의 문 (설계: 2026-11-14 분봉 백테스트 · W4).

- `GET  /coverage`  분봉이 ★어느 날 · 어떤 출처로 · 얼마나★ 있는지.
- `GET  /templates` 화면이 내놓을 수 있는 규칙 틀과 설정 칸, 상한, 분봉만으로는 알 수 없는 것.
- `POST /simulate`  규칙 하나를 돌린다 — 체결을 만들고 매매일지 엔진으로 계산해 돌려준다.
- `POST /validate`  같은 규칙을 ★판정★한다 — 표본외 · 비용 두 배 · 슬리피지 민감도 · (선언한 격자의) 워크포워드 · 다중 비교 → 관문 표.

분봉은 파일만 읽는다(증권사 클라이언트를 만들지 않는다 · 분봉 파일에 쓰지 않는다 · 주문 경로에 닿지 않는다).
쓰는 것은 하나다 — ★시행 기록★(`src/data/intraday_trials`): 돌릴 때마다 설정 요약값과 일별 손익 흐름을 남겨 몇 번 해 봤는지를 센다.
기록하지 못하면 계산은 그대로 답하되 시행 횟수는 '모른다'로 답한다(N=1 로 꾸미지 않는다).
출처와 운영 차단은 `src/data/minute_bars`, 세는 일은 `src/data/minute_quality`, 봉을 엔진의 하루로 옮기는 일은
`src/data/minute_feed`, 계산은 `src/engine/intraday` 가 한다. 이 문들은 ⑴ 로그인 ⑵ 상한과 사유 ⑶ 기억과 시간 예산만 맡는다.
★도구는 규칙을 추천하지 않는다★ — 틀과 매개변수는 받은 그대로 엔진에 넘기고, 상한을 넘으면 잘라서 계산하지 않고 거절한다.

★값이 없는 것을 0 으로 내지 않는다★ — 운영 게이트가 막은 합성 하루, 읽지 못한 파일, 시간 예산을 넘겨 아직 확인하지
않은 하루는 봉 수가 `None` 이고 사유가 붙는다. 분봉만으로 알 수 없는 것(봉 시각의 뜻 · 소급 한도 · 단일가·VI·정지)은
답에 늘 사유와 확인 방법을 실어 보낸다.
"""
from __future__ import annotations

import logging
import math
import time
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from itertools import product
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import src.data.minute_bars as minute_bars
from src.api.auth import require_login
from src.api.trade_journal_routes import master_lookup
from src.data import intraday_trials as trials
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.data.minute_quality import DEFECTS, check_day
from src.data.mock_gate import mock_allowed
from src.engine import intraday
from src.engine.intraday import expr, rules, simulator
from src.engine.intraday import gates as gate_table
from src.engine.intraday import validate as validation
from src.engine.intraday.simulator import ASSUMPTIONS, SKIP_REASONS, CostAssumptions, PositionRules, RuleSpec, SimError

__all__ = ["RuleSpec", "router"]

logger = logging.getLogger("api.intraday")
router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

#: 한 번에 물을 수 있는 기간(달력 일수)과 종목 수. 넘으면 ★잘라서 답하지 않는다★.
MAX_COVERAGE_DAYS = 31
MAX_DETAIL_TICKERS = 30

#: 한 요청이 하루 요약을 새로 세는 데 쓰는 시간(초). 전 종목 하루(약 백만 줄)를 읽고 세는 데 이 환경에서 2초쯤 걸렸다 —
#: 처음 묻는 한 달이면 한 요청을 넘는다. 넘긴 날은 `not_checked` 로 답하고, 센 날은 기억해 두어 다음 요청이 이어서 센다.
CHECK_BUDGET_SEC = 8.0

#: 실행 문의 상한. ★넘으면 잘라서 계산하지 않는다★ — 앞부분만의 결과는 다른 결과다.
#: 종목×거래일 2,000(약 78만 봉 · 서른 종목 × 66거래일)은 이 환경에서 봉을 읽어 하루로 옮기는 데 2.2초, 한 번 돌리는 데
#: 0.7~2.1초였다(틀 일곱 · 한 번씩의 관측 — 합성 분봉).
MAX_TICKER_DAYS = 2_000
MAX_RANGE_DAYS = 366
#: 읽을 일파일 크기의 합. 전 종목 하루(csv.gz 22MB)를 읽는 데 0.64초였다 — 200MB 면 읽는 데만 6초쯤이다.
MAX_LOAD_BYTES = 200 * 1024 * 1024
#: 답에 싣는 건너뜀 목록의 길이(합계와 사유별 건수는 늘 전부 싣는다).
SKIPPED_LIMIT = 200

#: 판정 문의 상한. 워크포워드의 격자는 사용자가 ★미리 선언한★ 칸이다 — 도구가 넓히거나 제안하지 않는다(칸마다 한 시행으로 센다).
MAX_GRID_CELLS = 12
MIN_FOLDS, MAX_FOLDS = 2, 12
#: 판정 한 번의 계산량 = 종목 × 거래일 × 돌리는 횟수(슬리피지 가정마다 한 번 + 격자의 칸마다 한 번).
#: 6,000 은 위에서 잰 값으로 10초 안에 드는 크기다 — 격자 없이 세 번이면 종목×거래일 2,000(읽기 2.2초 + 세 번 2~6초),
#: 격자 열두 칸이면 400(읽기 0.5초 + 열다섯 번 2~6초 + 구간별 계산 1초쯤). 넘으면 잘라서 판정하지 않고 거절한다.
MAX_VALIDATE_WORK = 6_000
#: 슬리피지 민감도를 보는 틱. 여기에 기본 가정과 그보다 한 틱 불리한 값을 더해 본다.
SENSITIVITY_TICKS = (0, 1, 2)
WALK_FORWARD_NOTE = "격자의 칸은 받은 그대로이며 넓히거나 고르지 않았습니다. 칸마다 한 시행으로 세었습니다."

REASONS = {
    "not_checked_yet": "한 번에 확인할 수 있는 시간을 넘겨 이 날짜는 아직 확인하지 않았습니다. 다시 불러오면 이어서 확인합니다.",
    "range_too_long": "기간이 한 번에 볼 수 있는 일수를 넘었습니다.",
    "bad_range": "시작일이 종료일보다 늦습니다.",
    "too_many_tickers": "종목 수가 한 번에 볼 수 있는 수를 넘었습니다.",
    "no_tickers": "종목이 하나도 없습니다.",
    "too_many_ticker_days": "종목 수와 적재된 거래일 수의 곱이 한 번에 계산할 수 있는 양을 넘었습니다.",
    "too_much_data": "읽어야 할 분봉 파일이 한 번에 읽을 수 있는 크기를 넘었습니다.",
    "too_much_work": "종목 수와 거래일 수와 계산 횟수의 곱이 한 번에 판정할 수 있는 양을 넘었습니다.",
    "grid_too_large": "격자의 칸 수가 한 번에 볼 수 있는 수를 넘었습니다.",
    "grid_too_small": "격자에는 칸이 둘 이상 있어야 합니다.",
    "grid_unknown_position": "격자에 포지션 설정이 아닌 이름이 있습니다.",
    "bad_folds": "구간 수가 허용 범위를 벗어났습니다.",
    # 엔진이 거절한 설정(`RuleError` · `SimError` · `ExprError` 의 사유)
    "unknown_kind": "모르는 규칙 틀입니다.",
    "unknown_param": "그 규칙 틀에 없는 매개변수가 있습니다.",
    "param_out_of_range": "매개변수가 허용 범위를 벗어났습니다.",
    "param_not_integer": "정수여야 하는 매개변수에 정수가 아닌 값이 들어왔습니다.",
    "param_not_number": "수여야 하는 매개변수에 수가 아닌 값이 들어왔습니다.",
    "bad_choice": "고를 수 없는 값을 골랐습니다.",
    "bad_amount": "금액은 0 보다 커야 합니다.",
    "bad_percent": "비율은 0 과 100 사이여야 합니다.",
    "bad_time": "시각을 읽지 못했습니다. 네 자리 숫자로 적어야 합니다.",
    "bad_count": "횟수는 1 이상의 정수여야 합니다.",
    "bad_slippage": "슬리피지 틱은 0 이상의 정수여야 합니다.",
    "bad_participation": "참여율 상한은 0 보다 크고 1 이하여야 합니다.",
    "bad_commission": "수수료율은 0 이상이어야 합니다.",
    "bad_setting": "설정을 받아들이지 못했습니다.",
}

EMPTY = {
    "not_loaded": "이 기간에 적재된 분봉이 없습니다.",
    "no_usable_bars": "쓸 수 있는 분봉이 없습니다. 건너뛴 사유를 보십시오.",
}

#: 화면의 설정 칸 — 포지션·위험 규칙. 기본값은 출발점일 뿐이고 "좋은 값"이라는 뜻이 아니다(비워 둔 칸은 그 규칙을 쓰지 않는다).
POSITION_FIELDS = (
    {"key": "amount", "label": "거래당 진입 금액", "type": "float", "min": 1, "max": 1e12, "default": 1_000_000, "unit": "원"},
    {"key": "stop_pct", "label": "손절", "type": "float", "min": 0.01, "max": 99, "default": None, "unit": "%"},
    {"key": "target_pct", "label": "익절", "type": "float", "min": 0.01, "max": 99, "default": None, "unit": "%"},
    {"key": "trail_pct", "label": "추적 손절", "type": "float", "min": 0.01, "max": 99, "default": None, "unit": "%"},
    {"key": "time_exit", "label": "시간 청산", "type": "time", "min": None, "max": None, "default": None, "unit": ""},
    {"key": "entry_from", "label": "진입 시작", "type": "time", "min": None, "max": None, "default": None, "unit": ""},
    {"key": "entry_until", "label": "진입 마감", "type": "time", "min": None, "max": None, "default": None, "unit": ""},
    {"key": "max_entries_per_ticker", "label": "종목당 하루 진입 수", "type": "int", "min": 1, "max": 100, "default": 1, "unit": "회"},
    {"key": "max_open_positions", "label": "동시 보유 종목 수", "type": "int", "min": 1, "max": 30, "default": None, "unit": "종목"},
    {"key": "daily_loss_limit", "label": "하루 최대 손실", "type": "float", "min": 1, "max": 1e12, "default": None, "unit": "원"},
    {"key": "cooldown_after_loss_min", "label": "손실 뒤 재진입 금지", "type": "int", "min": 1, "max": 390, "default": None, "unit": "분"},
)
COST_FIELDS = (
    {"key": "commission_bp", "label": "수수료율(편도)", "type": "float", "min": 0, "max": 1_000, "default": None, "unit": "bp"},
    {"key": "slippage_ticks", "label": "슬리피지(편도)", "type": "int", "min": 0, "max": 20, "default": 1, "unit": "틱"},
    {"key": "participation_cap", "label": "참여율 상한", "type": "float", "min": 0.001, "max": 1, "default": 0.1, "unit": "배"},
    # 종목 마스터가 시장 구분을 모르는 종목은 매도세를 정할 수 없다 — 사용자가 가정을 선언하면 그 가정으로 계산하고 그렇게 적는다.
    {"key": "unknown_market", "label": "시장 구분을 모르는 종목의 시장", "type": "choice", "min": None, "max": None, "default": None,
     "unit": "", "choices": [{"value": "KOSPI", "label": "코스피"}, {"value": "KOSDAQ", "label": "코스닥"},
                             {"value": "KONEX", "label": "코넥스"}]},
    {"key": "unknown_instrument", "label": "시장 구분을 모르는 종목의 상품", "type": "choice", "min": None, "max": None,
     "default": None, "unit": "", "choices": [{"value": "stock", "label": "주식"}, {"value": "etf", "label": "ETF"}]},
)

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


# ── 규칙 틀과 실행 ─────────────────────────────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RuleBody(_Strict):
    kind: str
    params: dict = Field(default_factory=dict)


class PositionBody(_Strict):
    amount: float
    stop_pct: float | None = None
    target_pct: float | None = None
    trail_pct: float | None = None
    time_exit: str | None = None
    entry_from: str | None = None
    entry_until: str | None = None
    max_entries_per_ticker: int | None = 1
    max_open_positions: int | None = None
    daily_loss_limit: float | None = None
    cooldown_after_loss_min: int | None = None


class CostsBody(_Strict):
    commission_bp: float | None = None          # 없으면 모름 — 0 과 다르다(비용 뒤 값이 미상이 된다)
    slippage_ticks: int = 1
    participation_cap: float | None = 0.1
    unknown_market: Literal["KOSPI", "KOSDAQ", "KONEX"] | None = None        # 마스터가 모르는 종목의 가정(없으면 매도세 미상)
    unknown_instrument: Literal["stock", "etf"] | None = None


class SimulateBody(_Strict):
    tickers: list[str]
    from_: date = Field(alias="from")
    to: date
    rule: RuleBody
    position: PositionBody
    costs: CostsBody = Field(default_factory=CostsBody)


class WalkForwardBody(_Strict):
    folds: int
    rule: dict[str, list] = Field(default_factory=dict)          # 규칙 매개변수 → 볼 값들
    position: dict[str, list] = Field(default_factory=dict)      # 포지션 설정 → 볼 값들


class ValidateBody(SimulateBody):
    walk_forward: WalkForwardBody | None = None


def _session_view(found: dict) -> dict:
    return {k: found.get(k) for k in ("available", "open", "closing_auction_from", "close", "grade", "sources", "reason", "message")}


@router.get("/templates")
def templates(_user=Depends(require_login)) -> dict:
    return {
        "templates": rules.describe(),
        "position": [dict(f) for f in POSITION_FIELDS],
        "costs": [dict(f) for f in COST_FIELDS],
        "limits": {"tickers": MAX_DETAIL_TICKERS, "ticker_days": MAX_TICKER_DAYS, "range_days": MAX_RANGE_DAYS,
                   "bytes": MAX_LOAD_BYTES, "grid_cells": MAX_GRID_CELLS, "validate_work": MAX_VALIDATE_WORK,
                   "folds_min": MIN_FOLDS, "folds_max": MAX_FOLDS},
        "session_rules": _session_view(session_rules()),
        "unknowns": [dict(u) for u in UNKNOWNS],
        "gate": {"mock": mock_allowed()},
    }


def _setting(body: SimulateBody) -> tuple[list[str], RuleSpec, dict, PositionRules, CostAssumptions]:
    """받은 설정을 엔진의 값으로 — 어긋나면 엔진의 사유 그대로 거절한다. ★파일을 읽기 전에★ 끝낸다."""
    tickers = list(dict.fromkeys(t.strip() for t in body.tickers if t.strip()))
    if not tickers:
        raise _refuse("no_tickers")
    if len(tickers) > MAX_DETAIL_TICKERS:
        raise _refuse("too_many_tickers", limit=MAX_DETAIL_TICKERS, tickers=len(tickers))
    if body.from_ > body.to:
        raise _refuse("bad_range")
    span = (body.to - body.from_).days + 1
    if span > MAX_RANGE_DAYS:
        raise _refuse("range_too_long", limit=MAX_RANGE_DAYS, days=span)
    position = PositionRules(**body.position.model_dump())
    costs = CostAssumptions(**body.costs.model_dump())
    try:
        params = rules.resolve(body.rule.kind, body.rule.params)
        spec = rules.build(body.rule.kind, body.rule.params)
        simulator.validate(spec, position, costs)
    except (rules.RuleError, SimError, expr.ExprError) as err:
        code = err.code if err.code in REASONS else "bad_setting"
        raise _refuse(code, detail=err.detail) from None
    return tickers, spec, params, position, costs


def _plan(body: SimulateBody, tickers: list[str]) -> minute_feed.Plan:
    """읽을 날과 크기 — ★읽기 전에★ 상한을 본다."""
    plan = minute_feed.plan(body.from_, body.to)
    if len(tickers) * len(plan.dates) > MAX_TICKER_DAYS:
        raise _refuse("too_many_ticker_days", limit=MAX_TICKER_DAYS, ticker_days=len(tickers) * len(plan.dates),
                      tickers=len(tickers), days=len(plan.dates))
    if plan.bytes > MAX_LOAD_BYTES:
        raise _refuse("too_much_data", limit=MAX_LOAD_BYTES, bytes=plan.bytes, days=len(plan.dates))
    return plan


def _shared(body: SimulateBody, tickers: list[str], params: dict, session: dict) -> dict:
    request = {"tickers": tickers, "from": body.from_.isoformat(), "to": body.to.isoformat(),
               "rule": {"kind": body.rule.kind, "params": params},
               "position": body.position.model_dump(), "costs": body.costs.model_dump()}
    return {"request": request, "template": next(t for t in rules.describe() if t["kind"] == body.rule.kind),
            "session_rules": _session_view(session), "unknowns": [dict(u) for u in UNKNOWNS], "gate": {"mock": mock_allowed()},
            "limits": {"tickers": MAX_DETAIL_TICKERS, "ticker_days": MAX_TICKER_DAYS}}


_NO_DATA = {"days": 0, "sessions": 0, "bars": 0, "skipped": [], "skipped_total": 0, "skipped_by_reason": {}, "shifted_days": []}


def _data(days: list, out: dict) -> dict:
    skipped = out["skipped"]
    return {"days": len(days), "sessions": out["counts"]["sessions"], "bars": out["counts"]["bars"],
            "skipped": [{**row, "message": SKIP_REASONS.get(row["reason"]) or minute_bars.DAY_REASONS.get(row["reason"])}
                        for row in skipped[:SKIPPED_LIMIT]],
            "skipped_total": len(skipped), "skipped_by_reason": dict(Counter(row["reason"] for row in skipped)),
            "shifted_days": [d.date for d in days if d.shifted]}


def _needs_prev(*specs: RuleSpec) -> bool:
    return any(expr.uses_prev(t) for spec in specs for t in (spec.entry, spec.entry_stop, spec.exit) if t is not None)


# ── 시행 기록 ──────────────────────────────────────────────────────────────────────────
def _trial_setting(kind: str, params: dict, position: dict, costs: dict) -> dict:
    """시행을 가르는 설정 — 받은 꼴이 아니라 ★정해진 꼴★(기본값을 채운 매개변수 · 검증을 지난 포지션과 비용)."""
    return {"rule": {"kind": kind, "params": params}, "position": position, "costs": costs}


def _record(user: str, out: dict, setting: dict, tickers: list[str], body: SimulateBody) -> dict | None:
    """실행 하나를 시행으로 남긴다 → `trials.record` 의 답(실패하면 `None`)."""
    daily = validation.daily_values(out["journal"], out["dates"])
    return trials.record(user, grade=out["origin"]["grade"] or "unknown", setting=setting, tickers=tickers,
                         start=body.from_.isoformat(), end=body.to.isoformat(), daily={**daily, "dates": out["dates"]})


def _family(user: str, out: dict, tickers: list[str], body: SimulateBody) -> dict | None:
    return trials.family(user, grade=out["origin"]["grade"] or "unknown", tickers=tickers, start=body.from_.isoformat(),
                         end=body.to.isoformat())


def _trial_view(made: dict | None, family: dict | None) -> dict:
    """화면에 싣는 시행 기록의 답. 하나라도 실패했으면 그 수는 `None` 이고 사유가 붙는다 — 1 이 아니다."""
    failed = made is None or family is None
    return {"recorded": made is not None, "new": made["new"] if made else None, "runs": made["runs"] if made else None,
            "family_n": None if failed else len(family["trials"]), "user_total": None if failed else family["user_total"],
            "reason": "store_unavailable" if failed else None,
            "message": trials.REASONS["store_unavailable"] if failed else None}


@router.post("/simulate")
def simulate(body: SimulateBody, user=Depends(require_login)) -> dict:
    tickers, spec, params, position, costs = _setting(body)
    plan = _plan(body, tickers)
    session = session_rules()
    master = master_lookup()
    shared = _shared(body, tickers, params, session)
    if not plan.dates:
        logger.info("intraday simulate: tickers=%s days=0 fills=0", len(tickers))
        return {**shared, "empty": {"reason": "not_loaded", "message": EMPTY["not_loaded"]}, "data": dict(_NO_DATA),
                "origin": None, "journal": None, "assumptions": [], "events_by_kind": {}, "breakeven": None, "trial": None}

    days = minute_feed.build_days(tickers, body.from_, body.to, rules=session, master=master, need_prev=_needs_prev(spec))
    out = intraday.run(days, spec, position, costs, rules=session, master=master)
    usable = out["counts"]["sessions"] > 0
    trial = None
    if usable:                                                  # 본 것이 없으면 해 본 것도 아니다
        made = _record(user.username, out, _trial_setting(body.rule.kind, params, body.position.model_dump(),
                                                          body.costs.model_dump()), tickers, body)
        trial = _trial_view(made, _family(user.username, out, tickers, body) if made else None)
    logger.info("intraday simulate: tickers=%s days=%s sessions=%s fills=%s skipped=%s", len(tickers), len(days),
                out["counts"]["sessions"], len(out["fills"]), len(out["skipped"]))
    return {
        **shared,
        "empty": None if usable else {"reason": "no_usable_bars", "message": EMPTY["no_usable_bars"]},
        "data": _data(days, out),
        "origin": out["origin"],
        "journal": out["journal"],
        "assumptions": [{"key": key, "label": ASSUMPTIONS[key], "count": count} for key, count in out["assumptions"].items()],
        "events_by_kind": dict(Counter(e["kind"] for e in out["events"])),
        "breakeven": validation.breakeven_cost(out["journal"]),
        "trial": trial,
    }


# ── 판정 ──────────────────────────────────────────────────────────────────────────────
def _cells(body: ValidateBody, base: dict, costs: CostAssumptions) -> list[dict]:
    """선언한 격자 → 칸들(선언한 순서의 곱). ★파일을 읽기 전에★ 전부 검사한다 — 한 칸이라도 어긋나면 거절한다."""
    wf = body.walk_forward
    if wf is None:
        return []
    if not MIN_FOLDS <= wf.folds <= MAX_FOLDS:
        raise _refuse("bad_folds", min=MIN_FOLDS, max=MAX_FOLDS, folds=wf.folds)
    unknown = sorted(set(wf.position) - set(PositionBody.model_fields))
    if unknown:
        raise _refuse("grid_unknown_position", keys=unknown)
    axes = [("rule", key, list(dict.fromkeys(values))) for key, values in wf.rule.items()]
    axes += [("position", key, list(dict.fromkeys(values))) for key, values in wf.position.items()]
    count = math.prod(len(values) for _, _, values in axes)
    if count > MAX_GRID_CELLS:
        raise _refuse("grid_too_large", limit=MAX_GRID_CELLS, cells=count)
    if count < 2:
        raise _refuse("grid_too_small", cells=count)

    cells = []
    for index, combo in enumerate(product(*(values for _, _, values in axes))):
        over: dict[str, dict] = {"rule": {}, "position": {}}
        for (section, key, _), value in zip(axes, combo, strict=True):
            over[section][key] = value
        try:
            given = {**body.rule.params, **over["rule"]}
            params = rules.resolve(body.rule.kind, given)
            spec = rules.build(body.rule.kind, given)
            position = PositionBody(**{**body.position.model_dump(), **over["position"]})
            position_rules = PositionRules(**position.model_dump())
            simulator.validate(spec, position_rules, costs)
        except (rules.RuleError, SimError, expr.ExprError) as err:
            raise _refuse(err.code if err.code in REASONS else "bad_setting", detail=err.detail, cell=index) from None
        except ValidationError:
            raise _refuse("bad_setting", cell=index) from None
        setting = _trial_setting(body.rule.kind, params, position.model_dump(), body.costs.model_dump())
        cells.append({"index": index, "rule": {key: params[key] for key in over["rule"]},
                      "position": {key: getattr(position, key) for key in over["position"]},
                      "is_base": trials.digest(setting) == trials.digest(base), "setting": setting, "spec": spec,
                      "position_rules": position_rules})
    return cells


@router.post("/validate")
def validate(body: ValidateBody, user=Depends(require_login)) -> dict:
    tickers, spec, params, position, costs = _setting(body)
    base_setting = _trial_setting(body.rule.kind, params, body.position.model_dump(), body.costs.model_dump())
    cells = _cells(body, base_setting, costs)
    base_ticks, doubled_ticks = costs.slippage_ticks, costs.slippage_ticks * 2
    ticks = sorted({*SENSITIVITY_TICKS, base_ticks, base_ticks + 1})
    simulations = len({*ticks, doubled_ticks}) + sum(not c["is_base"] for c in cells)
    plan = _plan(body, tickers)
    ticker_days = len(tickers) * len(plan.dates)
    if ticker_days * simulations > MAX_VALIDATE_WORK:
        raise _refuse("too_much_work", limit=MAX_VALIDATE_WORK, work=ticker_days * simulations, ticker_days=ticker_days,
                      simulations=simulations)

    session = session_rules()
    master = master_lookup()
    shared = _shared(body, tickers, params, session)
    wf = body.walk_forward
    if wf is not None:
        shared["request"]["walk_forward"] = {"folds": wf.folds, "rule": {k: list(dict.fromkeys(v)) for k, v in wf.rule.items()},
                                             "position": {k: list(dict.fromkeys(v)) for k, v in wf.position.items()}}
    nothing = {"origin": None, "summary": None, "out_of_sample": None, "slippage": [], "stress": None, "walk_forward": None,
               "multiplicity": None, "trial": None, "gates": None, "breakeven": None, "assumptions": []}
    if not plan.dates:
        logger.info("intraday validate: tickers=%s days=0", len(tickers))
        return {**shared, "empty": {"reason": "not_loaded", "message": EMPTY["not_loaded"]}, "data": dict(_NO_DATA), **nothing}

    days = minute_feed.build_days(tickers, body.from_, body.to, rules=session, master=master,
                                  need_prev=_needs_prev(spec, *(c["spec"] for c in cells)))

    def run_at(slippage: int) -> dict:
        return intraday.run(days, spec, position, replace(costs, slippage_ticks=slippage), rules=session, master=master)

    base = run_at(base_ticks)
    if base["counts"]["sessions"] <= 0:
        logger.info("intraday validate: tickers=%s days=%s sessions=0", len(tickers), len(days))
        return {**shared, "empty": {"reason": "no_usable_bars", "message": EMPTY["no_usable_bars"]}, "data": _data(days, base),
                **nothing, "origin": base["origin"]}

    # ① 같은 체결 줄을 날짜로 가른다 · ② 슬리피지 가정을 바꿔 다시 돌린다 · ③ 비용을 두 배로 놓는다
    dates, fee = base["dates"], costs.commission_bp
    assume = {"unknown_market": costs.unknown_market, "unknown_instrument": costs.unknown_instrument}
    summary = validation.brief(base["journal"])
    oos = validation.out_of_sample(base["fills"], dates, commission_bp=fee, assume=assume, master=master)
    at = {base_ticks: base}
    for slippage in {*ticks, doubled_ticks} - {base_ticks}:
        at[slippage] = run_at(slippage)
    slippage_rows = [{"ticks": t, "is_base": t == base_ticks, **validation.brief(at[t]["journal"])} for t in ticks]
    doubled_fee = None if fee is None else fee * 2
    stress = {"double": validation.result(at[doubled_ticks]["fills"], commission_bp=doubled_fee, assume=assume, master=master),
              "commission_bp": doubled_fee, "slippage_ticks": doubled_ticks}

    # ④ 선언한 격자의 칸을 한 번씩 돌린다(기본 설정과 같은 칸은 다시 돌리지 않는다)
    cell_runs = [base if c["is_base"] else intraday.run(days, c["spec"], c["position_rules"], costs, rules=session, master=master)
                 for c in cells]
    walk = None
    if wf is not None:
        found = validation.walk_forward([r["fills"] for r in cell_runs], dates, wf.folds, commission_bp=fee, assume=assume,
                                        master=master)
        walk = {**found, "message": validation.REASONS.get(found["reason"]) if found["reason"] else None,
                "note": WALK_FORWARD_NOTE,
                "cells": [{"index": c["index"], "rule": c["rule"], "position": c["position"], "is_base": c["is_base"],
                           "whole": validation.brief(r["journal"])} for c, r in zip(cells, cell_runs, strict=True)]}

    # ⑤ 시행을 남기고 센다 — 하나라도 남기지 못했으면 시행 횟수는 모른다
    who = user.username
    made = _record(who, base, base_setting, tickers, body)
    others_made = [_record(who, r, c["setting"], tickers, body) for c, r in zip(cells, cell_runs, strict=True) if not c["is_base"]]
    split = oos["split"]
    if made and split:
        trials.mark_oos(who, made["trial_key"], split["out_of_sample_from"], split["out_of_sample_to"])
    family = _family(who, base, tickers, body) if made and all(others_made) else None
    trial = _trial_view(made, family)
    multiplicity, views, trial_error = None, None, trials.REASONS["store_unavailable"]
    if family is not None:
        trial_error = None
        rest = [t for t in family["trials"] if t["trial_key"] != made["trial_key"]]
        daily = validation.daily_values(base["journal"], dates)

        def flow(row: dict) -> list[float] | None:
            kept = row["daily"]
            return kept["values"] if kept and kept.get("basis") == "net" else None

        same_days = all(t["daily"].get("dates") == dates for t in rest if flow(t) is not None)
        multiplicity = validation.multiplicity(daily["values"] if daily["basis"] == "net" else None, [flow(t) for t in rest],
                                               same_days=same_days)
        if split:
            views = trials.views_of(family["trials"], split["out_of_sample_from"], split["out_of_sample_to"])

    table = gate_table.build(origin=base["origin"], sessions=base["counts"]["sessions"], skipped=len(base["skipped"]),
                             bar_label_known=False, summary=summary, slippage_ticks=base_ticks, oos=oos, oos_views=views,
                             stress=stress, multiplicity=multiplicity, trial_error=trial_error)
    logger.info("intraday validate: tickers=%s days=%s sessions=%s simulations=%s cells=%s", len(tickers), len(days),
                base["counts"]["sessions"], simulations, len(cells))
    return {
        **shared,
        "empty": None,
        "data": _data(days, base),
        "origin": base["origin"],
        "summary": summary,
        "out_of_sample": {**oos, "views": views},
        "slippage": slippage_rows,
        "stress": stress,
        "walk_forward": walk,
        "multiplicity": multiplicity,
        "trial": trial,
        "gates": table,
        "breakeven": validation.breakeven_cost(base["journal"]),
        "assumptions": [{"key": key, "label": ASSUMPTIONS[key], "count": count} for key, count in base["assumptions"].items()],
    }
