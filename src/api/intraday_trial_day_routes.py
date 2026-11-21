"""분봉 하루 보기의 문 (G4 · 구현 계획 §5).
- `GET /trials/{trial_key}/day?date=YYYY-MM-DD&ticker=XXXXXX` — 내 시행 하나의 하루를 ★시행 줄의 설정으로 다시 계산해★
  그 종목이 본 봉과 그 체결을 함께 준다. 날짜 · 종목이 없으면 거래가 있는 첫 날 · 그날 첫 체결 종목이다.
★읽기만이다★ — 시행을 남기지 않고 아무 표에도 쓰지 않는다. 문은 시행 열쇠만 받는다 — 임의의 설정을 받으면 시행 수 밖에서 설정을
탐색하는 길이 되기 때문이다. 남의 시행은 없는 시행과 같은 답(404)이고, 기록을 읽지 못하면 '없음'이 아니라 503 이다.
그날 시행의 ★모든 종목★을 돌린다 — 동시 보유 상한 · 하루 최대 손실은 종목 사이에 걸린다. 준비는 실행 문 · 가동과 같은 길
(`intraday_routes.prepared_day`), 설정 읽기도 같은 함수(`engine.intraday.setting.parts_of`), 계산도 같은 부름(`engine.intraday.run`)이다.
규칙 맥락(하루 유형 모형 · 시장 국면)은 ★실행 문과 같은 부름★(시행의 기간 · 그 기간의 적재된 날)으로 싣는다 — 가동처럼 그날 하나로
읽으면 국면을 모르는 날을 거절하게 되는데, 실행은 그날을 '국면 조건을 충족하지 않은 날'로 계산했다.
다시 계산한 그날 값은 시행 줄의 그날 값(`validate.daily_values`)과 매번 견준다 — ★시행 줄의 기준(비용 전 · 뒤)으로★ 견주고(시행 줄의
기준은 실행 전체가 정한다), 다르면 그리되 그렇다고 적는다(명시적 열화).
운영에서는 합성 분봉으로 남은 시행을 다시 그리지 않는다. 주문 경로 · 증권사 클라이언트를 들이지 않는다(정적 시험).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

import src.data.minute_bars as minute_bars
from src.api import intraday_context
from src.api import intraday_routes as base
from src.api.auth import require_login
from src.data import intraday_trials as trials
from src.data.mock_gate import mock_allowed
from src.engine import intraday
from src.engine.intraday import setting as setting_parts
from src.engine.intraday import validate as validation
from src.engine.intraday.simulator import FILL_KINDS, SKIP_REASONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/intraday", tags=["intraday"])

#: 같은 그날 값으로 보는 손익 차의 한도(원). 화면이 보이는 가장 작은 단위(1원)보다 작아 어떤 표시 숫자도 바꾸지 못하는 차이다.
SAME_TOLERANCE_WON = 0.01

REASONS = {
    "store_unavailable": trials.REASONS["store_unavailable"],
    "not_found": "그 시행을 찾지 못했습니다.",
    "bad_date": "날짜를 읽지 못했습니다.",
    "date_outside_trial": "이 시행의 기간 밖 날짜입니다.",
    "ticker_not_in_trial": "이 시행의 종목이 아닙니다.",
}

EMPTY = {
    "synthetic_trial_in_production": "합성 분봉으로 남은 시행이라 운영에서는 다시 그리지 않습니다.",
    "bad_setting": "이 시행의 설정을 지금의 규칙 틀로 읽지 못했습니다. 다시 계산하지 않았습니다.",
    "no_days": "이 시행의 기간에 적재된 날이 없습니다.",
    "not_loaded": minute_bars.DAY_REASONS["not_loaded"],
}

CHECK = {
    "same": "다시 계산한 그날 값(거래 수 · 이긴 거래 수 · 손익)이 시행 줄에 남은 그날 값과 같습니다.",
    "different": "다시 계산한 그날 값이 시행 줄에 남은 그날 값과 다릅니다. 실행 뒤 그날 분봉 파일이 바뀌었을 수 있습니다. "
                 "표식은 지금 다시 계산한 체결입니다.",
    "unknown": "시행 줄에 그날 값이 남아 있지 않아 다시 계산한 값과 견주지 못했습니다.",
}

#: 국면 조건을 쓴 규칙의 그날 확률 — 실행 문과 같은 부름으로 실은 값. 화면은 이 글을 사실 줄 끝에 그대로 보인다.
DAY_REGIME_KNOWN = "그날 {name} 시장 국면(국면 {k}개)의 확률은 {shares}입니다. 그날 시가 전에 알던 값입니다."
DAY_REGIME_UNKNOWN = ("그날 {name} 시장 국면(국면 {k}개)의 확률을 몰라 국면 조건을 충족하지 않은 것으로 계산했습니다. "
                      "실행 문과 같은 규칙입니다. {why}")

#: 답에 늘 싣는 사실 — 이 그림이 무엇이고 무엇이 아닌지. 화면은 이 글을 그대로 보인다.
FACTS = (
    "시행 줄의 설정으로 이 하루를 다시 계산한 체결입니다. 다시 계산은 시행으로 세지 않습니다.",
    "그날 시행의 모든 종목을 함께 다시 계산합니다. 동시 보유 상한과 하루 최대 손실은 종목 사이에 걸립니다.",
    "봉은 시뮬레이터가 본 정규장 봉입니다. 거래가 없던 분은 봉이 없어 축에서 빠집니다.",
    "봉의 시각이 그 분의 시작인지 끝인지는 제공자 문서로 확인하지 못했습니다.",
    "체결가에는 슬리피지 가정이 들어 있어 그 봉의 고가와 저가 밖에 있을 수 있습니다.",
)


def _refuse(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "reason": REASONS[code]})


def _stored(daily: Any) -> dict[str, list] | None:
    """시행 줄의 일별 흐름 — 날짜와 손익이 함께 있어야 쓴다. 깨졌으면 `None`(0 으로 채우지 않는다)."""
    if not isinstance(daily, dict):
        return None
    dates, values = daily.get("dates"), daily.get("values")
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
        return None
    return daily


def _choices(start: date, end: date, tickers: list[str], daily: dict | None) -> dict[str, list]:
    if daily is not None:
        counts = daily.get("trades")
        counts = counts if isinstance(counts, list) and len(counts) == len(daily["dates"]) else [None] * len(daily["dates"])
        dates = [{"date": str(d), "trades": None if n is None else int(n)} for d, n in zip(daily["dates"], counts, strict=True)]
    else:
        dates = [{"date": d, "trades": None} for d in base.minute_feed.plan(start, end).dates]
    return {"dates": dates, "tickers": tickers}


def _default_date(choices: dict) -> str | None:
    rows = choices["dates"]
    traded = [r["date"] for r in rows if r["trades"]]
    return traded[0] if traded else rows[0]["date"] if rows else None


def _on_basis(journal: dict, day: str, basis: str | None) -> dict[str, Any] | None:
    """다시 계산한 그날 값을 그 기준으로(`None` 이면 다시 계산한 일지 자신의 기준). 하루만 돌렸으니 일지의 요약이 곧 그날 값이다.
    시행 줄의 기준은 실행 ★전체★가 정한다(한 거래라도 비용을 모르면 모든 날이 비용 전) — 그날만 다시 돌리면 비용을 다 알아 비용 뒤일 수
    있어, 비용 전으로 남은 날은 비용 전으로 견준다. 비용 뒤로 남은 날인데 지금 비용을 모르는 거래가 있으면 견줄 값이 없다(`None`)."""
    own = validation.daily_values(journal, [day])
    if basis is None or basis == own["basis"]:
        return {"basis": own["basis"], "total": own["values"][0], "trades": own["trades"][0], "wins": own["wins"][0]}
    if basis == "gross":
        gross = journal["summary"]["gross"]
        return {"basis": "gross", "total": float(gross["total"]), "trades": int(gross["n"]), "wins": int(gross["wins"])}
    return None


def _check(stored: dict | None, day: str, journal: dict) -> dict[str, Any]:
    """다시 계산한 그날 값 ↔ 시행 줄의 그날 값 — 시행 줄의 기준으로. 거래 수 · 이긴 수가 같고 손익 차가 `SAME_TOLERANCE_WON` 이하면 같음.
    그 기준으로 다시 계산할 수 없으면(비용 뒤인데 지금 비용을 모름) 다시 계산한 자신의 기준을 보이고 다름이다."""
    if stored is None or day not in stored["dates"]:
        return {"status": "unknown", "message": CHECK["unknown"], "stored": None, "recomputed": _on_basis(journal, day, None)}
    i = stored["dates"].index(day)

    def at(key: str) -> Any:
        values = stored.get(key)
        return values[i] if isinstance(values, list) and len(values) == len(stored["dates"]) else None

    kept = {"basis": stored.get("basis"), "total": float(stored["values"][i]), "trades": at("trades"), "wins": at("wins")}
    again = _on_basis(journal, day, kept["basis"]) or _on_basis(journal, day, None)
    same = (kept["basis"] == again["basis"] and abs(kept["total"] - again["total"]) <= SAME_TOLERANCE_WON
            and kept["trades"] in (None, again["trades"]) and kept["wins"] in (None, again["wins"]))
    status = "same" if same else "different"
    return {"status": status, "message": CHECK[status], "stored": kept, "recomputed": again}


def _skipped(ticker: str, day, out: dict) -> dict[str, str] | None:
    """그날 그 종목을 쓰지 않은 사유 — 봉을 준비한 쪽(`Day.skipped`)이나 시뮬레이터(`out.skipped`)가 건너뛴 것."""
    for t, reason in day.skipped:
        if t == ticker:
            return {"reason": reason, "message": SKIP_REASONS.get(reason) or minute_bars.DAY_REASONS.get(reason) or reason}
    for row in out["skipped"]:
        if row["ticker"] == ticker:
            return {"reason": row["reason"], "message": SKIP_REASONS.get(row["reason"]) or row["reason"]}
    return None


def _regime_lines(loaded: intraday_context.Loaded, day: str) -> list[str]:
    """국면 조건을 쓴 규칙이면 (지수, 국면 수)마다 그날 확률 한 줄 — 모르면 실행과 같은 규칙으로 계산했다는 것과 그날의 사유."""
    ctx = loaded.context
    if ctx is None:
        return []
    out = []
    for (index, k), ref in sorted(ctx.regimes.items()):
        name = intraday_context.REGIME_INDEXES[index]
        probs = ref.probs.get(day)
        if probs is None:
            why = loaded.unknown.get((index, k), {}).get(day) or intraday_context.NO_INDEX_DAY
            out.append(DAY_REGIME_UNKNOWN.format(name=name, k=k, why=why))
        else:
            shares = " · ".join(f"국면 {i} {p:.2f}" for i, p in enumerate(probs, start=1))
            out.append(DAY_REGIME_KNOWN.format(name=name, k=k, shares=shares))
    return out


def _bars(session) -> dict[str, list] | None:
    if session is None:
        return None
    return {"time": [f"{t[:2]}:{t[2:4]}:{t[4:6]}" for t in (str(x) for x in session.time)],
            **{k: [float(v) for v in getattr(session, k)] for k in ("open", "high", "low", "close", "volume")}}


@router.get("/trials/{trial_key}/day")
def trial_day(trial_key: str = Path(..., min_length=1, max_length=128),
              day: str | None = Query(None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"),
              ticker: str | None = Query(None, pattern=r"^[0-9A-Za-z]{1,12}$"),
              user=Depends(require_login)) -> dict[str, Any]:
    got = trials.daily_of(user.username, trial_key)
    if got is None:
        raise _refuse(503, "store_unavailable")
    if not got["found"]:
        raise _refuse(404, "not_found")
    tickers = sorted(dict.fromkeys(str(t) for t in got["tickers"]))
    start, end = date.fromisoformat(got["from"]), date.fromisoformat(got["to"])
    if day is not None:
        try:
            when = date.fromisoformat(day)
        except ValueError:
            raise _refuse(422, "bad_date") from None
        if not start <= when <= end:
            raise _refuse(422, "date_outside_trial")
    if ticker is not None and ticker not in tickers:
        raise _refuse(422, "ticker_not_in_trial")

    stored = _stored(got["daily"])
    choices = _choices(start, end, tickers, stored)
    mock = mock_allowed()
    shared: dict[str, Any] = {"trial_key": trial_key, "from": got["from"], "to": got["to"], "mock": mock, "choices": choices,
                              "trial_grade": got["grade"] if got["grade"] in ("E0", "E3") else None, "facts": list(FACTS)}
    nothing = {"date": day, "ticker": ticker, "name": None, "bars": None, "origin": None, "fills": [], "trades": [],
               "others": {"fills": 0}, "skipped": None, "check": None}

    def empty(code: str) -> dict[str, Any]:
        return {**shared, **nothing, "empty": {"reason": code, "message": EMPTY[code]}}

    if got["grade"] == "E0" and not mock:
        logger.warning("운영에서 합성 분봉의 시행을 다시 그리려 했다 — 그리지 않는다")
        return empty("synthetic_trial_in_production")
    try:
        rule, position, costs = setting_parts.parts_of(got["setting"])
    except setting_parts.SettingUnreadable:
        return empty("bad_setting")
    day = day if day is not None else _default_date(choices)
    if day is None:
        return empty("no_days")
    nothing["date"] = day
    # 규칙 맥락은 실행 문과 같은 부름(시행의 기간 · 그 기간의 적재된 날)으로 — 그다음 그날의 봉만 같은 준비로 짓는다
    loaded = intraday_context.load(user.username, rule, start, end=end, dates=base.minute_feed.plan(start, end).dates)
    prepared = base.prepared_day(user.username, tickers, rule, date.fromisoformat(day), loaded=loaded)
    if prepared is None:
        return empty("not_loaded")
    one, session_rules = prepared
    out = intraday.run([one], rule, position, costs, rules=session_rules, master=base.master_lookup())

    kinds = {e["row"]: e["kind"] for e in out["events"]}
    if ticker is None:
        ticker = out["fills"][0]["symbol"] if out["fills"] else tickers[0]
    session = one.sessions.get(ticker)
    fills = [{"time": f["executed_at"][11:], "side": f["side"], "quantity": f["quantity"], "price": f["price"],
              "kind": kinds[i], "kind_label": FILL_KINDS.get(kinds[i])}
             for i, f in enumerate(out["fills"]) if f["symbol"] == ticker]
    record = base.master_lookup()(ticker) if session is None else None
    name = session.name if session is not None else (record.get("name") if isinstance(record, dict) else None)
    grade = intraday.session_grade([session]) if session is not None else None
    journal = out["journal"] or {"trades": []}
    shared["facts"] = [*FACTS, *_regime_lines(loaded, day)]
    return {**shared, "date": day, "ticker": ticker, "name": name, "bars": _bars(session),
            "origin": None if session is None else {"grade": grade if grade in ("E0", "E3") else None, "source": session.source},
            "fills": fills, "trades": [r for r in journal["trades"] if r["symbol"] == ticker],
            "others": {"fills": len(out["fills"]) - len(fills)}, "skipped": _skipped(ticker, one, out),
            "check": _check(stored, day, out["journal"]) if out["journal"] else None,
            "empty": None}
