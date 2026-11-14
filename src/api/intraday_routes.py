"""분봉 백테스트의 문 (설계: 2026-11-14 분봉 백테스트 · W4).

- `GET  /coverage`  분봉이 ★어느 날 · 어떤 출처로 · 얼마나★ 있는지.
- `GET  /templates` 화면이 내놓을 수 있는 규칙 틀과 설정 칸, 상한, 분봉만으로는 알 수 없는 것.
- `POST /simulate`  규칙 하나를 돌린다 — 체결을 만들고 매매일지 엔진으로 계산해 돌려준다.

전부 파일만 읽는다(증권사 클라이언트를 만들지 않는다 · 분봉 파일에 쓰지 않는다 · 주문 경로에 닿지 않는다).
출처와 운영 차단은 `src/data/minute_bars`, 세는 일은 `src/data/minute_quality`, 봉을 엔진의 하루로 옮기는 일은
`src/data/minute_feed`, 계산은 `src/engine/intraday` 가 한다. 이 문들은 ⑴ 로그인 ⑵ 상한과 사유 ⑶ 기억과 시간 예산만 맡는다.
★도구는 규칙을 추천하지 않는다★ — 틀과 매개변수는 받은 그대로 엔진에 넘기고, 상한을 넘으면 잘라서 계산하지 않고 거절한다.

★값이 없는 것을 0 으로 내지 않는다★ — 운영 게이트가 막은 합성 하루, 읽지 못한 파일, 시간 예산을 넘겨 아직 확인하지
않은 하루는 봉 수가 `None` 이고 사유가 붙는다. 분봉만으로 알 수 없는 것(봉 시각의 뜻 · 소급 한도 · 단일가·VI·정지)은
답에 늘 사유와 확인 방법을 실어 보낸다.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import src.data.minute_bars as minute_bars
from src.api.auth import require_login
from src.api.trade_journal_routes import master_lookup
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.data.minute_quality import DEFECTS, check_day
from src.data.mock_gate import mock_allowed
from src.engine import intraday
from src.engine.intraday import expr, rules, simulator
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
#: 종목×거래일 2,000(약 78만 봉)은 이 환경에서 한 번 돌리는 데 2~4초였다(틀 일곱 · 한 번씩의 관측).
MAX_TICKER_DAYS = 2_000
MAX_RANGE_DAYS = 366
#: 읽을 일파일 크기의 합. 전 종목 하루(csv.gz 22MB)를 읽는 데 0.64초였다 — 200MB 면 읽는 데만 6초쯤이다.
MAX_LOAD_BYTES = 200 * 1024 * 1024
#: 답에 싣는 건너뜀 목록의 길이(합계와 사유별 건수는 늘 전부 싣는다).
SKIPPED_LIMIT = 200

REASONS = {
    "not_checked_yet": "한 번에 확인할 수 있는 시간을 넘겨 이 날짜는 아직 확인하지 않았습니다. 다시 불러오면 이어서 확인합니다.",
    "range_too_long": "기간이 한 번에 볼 수 있는 일수를 넘었습니다.",
    "bad_range": "시작일이 종료일보다 늦습니다.",
    "too_many_tickers": "종목 수가 한 번에 볼 수 있는 수를 넘었습니다.",
    "no_tickers": "종목이 하나도 없습니다.",
    "too_many_ticker_days": "종목 수와 적재된 거래일 수의 곱이 한 번에 계산할 수 있는 양을 넘었습니다.",
    "too_much_data": "읽어야 할 분봉 파일이 한 번에 읽을 수 있는 크기를 넘었습니다.",
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


class SimulateBody(_Strict):
    tickers: list[str]
    from_: date = Field(alias="from")
    to: date
    rule: RuleBody
    position: PositionBody
    costs: CostsBody = Field(default_factory=CostsBody)


def _session_view(found: dict) -> dict:
    return {k: found.get(k) for k in ("available", "open", "closing_auction_from", "close", "grade", "sources", "reason", "message")}


@router.get("/templates")
def templates(_user=Depends(require_login)) -> dict:
    return {
        "templates": rules.describe(),
        "position": [dict(f) for f in POSITION_FIELDS],
        "costs": [dict(f) for f in COST_FIELDS],
        "limits": {"tickers": MAX_DETAIL_TICKERS, "ticker_days": MAX_TICKER_DAYS, "range_days": MAX_RANGE_DAYS,
                   "bytes": MAX_LOAD_BYTES},
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


@router.post("/simulate")
def simulate(body: SimulateBody, _user=Depends(require_login)) -> dict:
    tickers, spec, params, position, costs = _setting(body)
    plan = minute_feed.plan(body.from_, body.to)
    if len(tickers) * len(plan.dates) > MAX_TICKER_DAYS:
        raise _refuse("too_many_ticker_days", limit=MAX_TICKER_DAYS, ticker_days=len(tickers) * len(plan.dates),
                      tickers=len(tickers), days=len(plan.dates))
    if plan.bytes > MAX_LOAD_BYTES:
        raise _refuse("too_much_data", limit=MAX_LOAD_BYTES, bytes=plan.bytes, days=len(plan.dates))

    session = session_rules()
    master = master_lookup()
    needs_prev = any(expr.uses_prev(t) for t in (spec.entry, spec.entry_stop, spec.exit) if t is not None)
    request = {"tickers": tickers, "from": body.from_.isoformat(), "to": body.to.isoformat(),
               "rule": {"kind": body.rule.kind, "params": params},
               "position": body.position.model_dump(), "costs": body.costs.model_dump()}
    shared = {"request": request, "template": next(t for t in rules.describe() if t["kind"] == body.rule.kind),
              "session_rules": _session_view(session), "unknowns": [dict(u) for u in UNKNOWNS], "gate": {"mock": mock_allowed()},
              "limits": {"tickers": MAX_DETAIL_TICKERS, "ticker_days": MAX_TICKER_DAYS}}
    if not plan.dates:
        logger.info("intraday simulate: tickers=%s days=0 fills=0", len(tickers))
        return {**shared, "empty": {"reason": "not_loaded", "message": EMPTY["not_loaded"]},
                "data": {"days": 0, "sessions": 0, "bars": 0, "skipped": [], "skipped_total": 0, "skipped_by_reason": {},
                         "shifted_days": []},
                "origin": None, "journal": None, "assumptions": [], "events_by_kind": {}, "breakeven": None}

    days = minute_feed.build_days(tickers, body.from_, body.to, rules=session, master=master, need_prev=needs_prev)
    out = intraday.run(days, spec, position, costs, rules=session, master=master)
    skipped = out["skipped"]
    usable = out["counts"]["sessions"] > 0
    logger.info("intraday simulate: tickers=%s days=%s sessions=%s fills=%s skipped=%s", len(tickers), len(days),
                out["counts"]["sessions"], len(out["fills"]), len(skipped))
    return {
        **shared,
        "empty": None if usable else {"reason": "no_usable_bars", "message": EMPTY["no_usable_bars"]},
        "data": {"days": len(days), "sessions": out["counts"]["sessions"], "bars": out["counts"]["bars"],
                 "skipped": [{**row, "message": SKIP_REASONS.get(row["reason"]) or minute_bars.DAY_REASONS.get(row["reason"])}
                             for row in skipped[:SKIPPED_LIMIT]],
                 "skipped_total": len(skipped), "skipped_by_reason": dict(Counter(row["reason"] for row in skipped)),
                 "shifted_days": [d.date for d in days if d.shifted]},
        "origin": out["origin"],
        "journal": out["journal"],
        "assumptions": [{"key": key, "label": ASSUMPTIONS[key], "count": count} for key, count in out["assumptions"].items()],
        "events_by_kind": dict(Counter(e["kind"] for e in out["events"])),
        "breakeven": validation.breakeven_cost(out["journal"]),
    }
