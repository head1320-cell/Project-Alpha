"""규칙 가동의 관제 — ★읽기만★ (설계 W5 §6 · 구현 계획 `docs/superpowers/plans/2026-11-15-rule-run-monitor.md`)
==============================================================================
가동 하나를 두고 "지금 무슨 일이 일어났나"를 모은다: 주문(상태별 · 거절은 주문 경로가 한 말과 함께) · 체결(가상인지 증권사 체결인지) ·
실현손익(매매일지 엔진) · 규칙 안 일 손실 한도까지 남은 폭 · 비상 정지 · 그날의 분봉 백테스트와 같은지.

## ★쓰지 않는다 · 주문 경로를 부르지 않는다★

가동 · 정지 · 비상 정지는 이미 있는 문이 한다. 여기서는 가동 기록 · 주문 기록을 읽고 순수 함수로 계산할 뿐이다
(`tests/test_rule_run_monitor.py` 가 모든 표의 줄 수와 이 파일의 부름 이름으로 건다).

## 무엇을 근거로 세는가

- **설정**은 가동 줄이 품은 사본(`request`)이다 — 시행 줄이 사라져도 ★그때 돌린 것★으로 계산한다. 지금의 틀로 읽히지 않으면 손익 · 한도 · 견줌은 값 없음 + 사유.
- **주문**은 주문 기록(`live_orders`)을 계좌 실행기로 읽어 주문 번호로 가상 체결 줄과 잇는다. 가동 번호가 같은 다른 출처의 줄은 번호가 맞지 않아 섞이지 않는다.
  신호는 있는데 주문 기록에 줄이 없으면 그 수를 센다(`unrecorded`). 주문 기록을 못 읽으면 가동 기록에 적힌 답으로 열화하고 그렇게 적는다(`basis`).
- **실현손익**은 `trade_journal.analyze` 다 — 분봉 백테스트(`intraday.run`)와 같은 부름(같은 비용 가정 · 같은 종목 마스터). 미청산은 평가하지 않는다.
  ★거절된 신호의 가상 체결도 손익에 든다★: 가상 체결은 시뮬레이터가 계산한 것이고 걸음 엔진은 주문 경로의 답을 모른다. 거절이 없었다고도,
  거절 뒤의 세계도 지어내지 않는다 — 그 수(`includes_rejected`)를 함께 적는다.
- **한도까지 남은 폭**은 시뮬레이터의 판정과 같은 값이다(`simulator.sell` 의 `state.realized` — 비용 전 · 일부 청산 포함 · 한 번 닿으면 닿은 것).
- **"그날의 백테스트와 같다"** 는 다시 계산해 본 관측이다. 끝까지 돈 가동만 견준다.

봉을 짓는 일은 문 층이 넘긴다(`day_of`) — 이 모듈은 `src.api` 를 들여오지 않는다(가동기와 같은 규칙).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import src.execution.rule_runner as rule_runner
from src.engine.intraday import NOT_MODELED
from src.engine.intraday.simulator import CostAssumptions, simulate
from src.engine.trade_journal import analyze
from src.engine.trade_journal.fills import normalize
from src.engine.trade_journal.matching import match
from src.execution.account_executors import get_account_executor

logger = logging.getLogger(__name__)

#: 가동 번호 하나로 읽는 주문 기록의 상한. 닿으면 '기록에 없는 신호'는 세지 못한다(모른다고 적는다).
ORDER_SCAN = 1_000

REASONS = {
    "order_log_unavailable": "주문 기록을 읽지 못했습니다. 가동 기록에 적힌 답으로 집계했으며 거절 문장은 없습니다.",
    "order_log_truncated": "이 가동 번호의 주문 기록이 조회 상한을 넘어, 기록에 없는 신호와 증권사 체결을 세지 못했습니다.",
    "bad_setting": "가동 기록에 적힌 설정을 지금의 규칙 틀로 읽지 못했습니다.",
    "no_loss_limit": "이 설정에는 하루 최대 손실이 없습니다.",
    "cost_unknown": "비용을 모르는 체결이 있어 비용 뒤 손익을 내지 않았습니다.",
    "classified_at_read": "이 가동의 체결 줄에는 가동 때의 시장 · 상품이 적혀 있지 않아, 지금의 종목 마스터로 매도세를 정했습니다.",
    "replay_has_no_lag": "재생은 적재된 하루를 다시 흘립니다. 봉의 지연은 장중 공급에서만 잽니다.",
}

#: 그날의 분봉 백테스트와 견준 결과의 문장.
BACKTEST = {
    "same": "가상 체결이 지금 적재된 봉으로 다시 계산한 그날의 분봉 백테스트 체결과 줄 단위로 같습니다.",
    "differs": "가상 체결이 지금 적재된 봉으로 다시 계산한 그날의 분봉 백테스트 체결과 다릅니다. 가동 뒤에 봉이 바뀌었거나 결함입니다.",
    "running": "가동 중입니다. 하루를 끝까지 돈 뒤에 그날의 분봉 백테스트와 견줍니다.",
    "stopped": "하루를 끝까지 돌지 않은 가동은 그날의 분봉 백테스트와 견주지 않습니다.",
    "not_loaded": "그날의 분봉을 지금 읽지 못해 분봉 백테스트와 견주지 못했습니다.",
}

_FILL_KEYS = ("executed_at", "symbol", "side", "quantity", "price")


class DayUnavailable(Exception):
    """그날의 봉을 지을 수 없다 — 사유 문장과 함께(문 층의 `day_of` 가 던진다 · 예: 규칙 맥락의 모형을 읽지 못함).

    '적재되지 않음'과 다른 사유를 '적재되지 않음'으로 말하지 않으려고 둔다 — 관제는 그 문장을 그대로 싣는다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
_CLASS_KEYS = ("market", "instrument")


def _rows(fills: list[dict]) -> list[dict]:
    """체결 줄에서 체결 자체만(시각 · 종목 · 방향 · 수량 · 가격) — 한도의 누계와 백테스트와 견주는 단위다."""
    return [{k: f[k] for k in _FILL_KEYS} for f in fills]


def _recorded(fills: list[dict]) -> bool:
    """모든 줄의 시장 · 상품이 ★가동 때 적힌 값★인가. 하나라도 아니면 가동 전체를 읽는 때의 마스터로 정한다(한 가동에 두 기준을 섞지 않는다)."""
    return all(f.get("classified") for f in fills)


def _names_only(master: Callable[[str], dict | None] | None) -> Callable[[str], dict | None] | None:
    """종목의 ★이름만★ 주는 마스터 — 가동 때 몰랐던 시장 · 상품을 지금의 마스터가 채우지 않게 한다(이름은 표시일 뿐 값에 닿지 않는다)."""
    if master is None:
        return None

    def lookup(symbol: str) -> dict | None:
        flags = master(symbol)
        name = flags.get("name") if isinstance(flags, dict) else None
        return {"name": name} if name else None
    return lookup


# ── 주문 ─────────────────────────────────────────────────────────────────────────────

def _order_log(account_id: str, run_id: int) -> tuple[dict[str, dict] | None, bool]:
    """이 가동 번호로 적힌 주문 기록(주문 번호 → 줄)과 상한에 닿았는지. 읽지 못하면 `(None, False)`."""
    try:
        rows = get_account_executor(account_id).list_orders(strategy_id=run_id, limit=ORDER_SCAN)
    except Exception as err:                                      # noqa: BLE001 — 못 읽음은 열화다(가동 기록의 답으로 센다)
        logger.warning("관제: 주문 기록 읽기 실패 %s", type(err).__name__)
        return None, False
    return {r["client_order_id"]: r for r in rows}, len(rows) >= ORDER_SCAN


def _orders(fills: list[dict], log: dict[str, dict] | None, truncated: bool) -> tuple[dict, dict]:
    """→ (주문 묶음, 체결 묶음). 상태는 주문 기록의 지금 값, 기록에 없는 신호는 가동 기록에 적힌 답."""
    by_status: dict[str, int] = {}
    rejected: list[dict] = []
    unrecorded = broker = 0
    for f in fills:
        row = log.get(f["client_order_id"]) if log is not None else None
        if row is None:
            unrecorded += 1
            row = {}
        status = row.get("status") or f["order_status"] or "UNKNOWN"
        by_status[status] = by_status.get(status, 0) + 1
        if row.get("filled_quantity"):
            broker += 1
        if status == "REJECTED":
            rejected.append({"seq": f["seq"], "executed_at": f["executed_at"], "symbol": f["symbol"], "side": f["side"],
                             "quantity": f["quantity"], "reason_code": row.get("reason_code") or f["order_reason"],
                             "message": row.get("error_message")})
    if log is None:
        basis, reason = "run_record", REASONS["order_log_unavailable"]
    else:
        basis, reason = "order_log", REASONS["order_log_truncated"] if truncated else None
    known = reason is None                                        # 기록을 다 읽었을 때만 '없다'를 셀 수 있다
    return ({"basis": basis, "reason": reason, "signals": len(fills), "by_status": by_status, "rejected": rejected,
             "unrecorded": unrecorded if known else None},
            {"virtual": len(fills), "broker": broker if known else None, "broker_reason": reason})


# ── 실현손익 · 한도 ───────────────────────────────────────────────────────────────────

def pnl_of(fills: list[dict], costs: CostAssumptions, master: Callable[[str], dict | None] | None) -> tuple[dict, dict]:
    """→ (손익 묶음, 매매일지 전체). 실현손익은 청산을 마친 거래 + 일부 청산한 몫이다(미청산 수량은 평가하지 않는다).

    매도세를 가르는 시장 · 상품은 ★체결 줄에 적힌 가동 때의 값★이다(그때 몰랐으면 모른다 — 사용자의 가정이 있으면 가정). 그 값이 적히지
    않은 옛 줄이면 읽는 때의 종목 마스터로 정하고 `classification` 에 그렇게 적는다."""
    recorded = _recorded(fills)
    rows = [{k: f.get(k) for k in _FILL_KEYS + _CLASS_KEYS} for f in fills] if recorded else _rows(fills)
    journal = {**analyze(rows, costs.journal_options(), master=_names_only(master) if recorded else master),
               "not_covered": list(NOT_MODELED)}
    summary = journal["summary"]
    partial = summary["open_realized"]
    gross = summary["gross"]["total"] + partial["gross"]
    # 비용을 모르는 거래가 하나도 없을 때만 '비용 뒤'를 낸다(요약의 `net` 은 그때 늘 있다) — 아는 거래만의 합을 전체인 것처럼 적지 않는다.
    cost_known = summary["net_excluded"] == 0 and partial["net"] is not None
    net = summary["net"]["total"] + partial["net"] if cost_known else None
    return ({"available": True, "reason": None, "gross": gross, "cost": gross - net if cost_known else None, "net": net,
             "net_reason": None if cost_known else REASONS["cost_unknown"],
             "closed_trades": journal["trades_total"], "open_positions": len(journal["open_positions"]),
             "includes_rejected": sum(1 for f in fills if f["order_status"] == "REJECTED"), "basis": journal["basis"],
             "classification": ({"basis": "recorded", "reason": None} if recorded
                                else {"basis": "read_time_master", "reason": REASONS["classified_at_read"]})},
            journal)


def loss_limit(fills: list[dict], limit: float | None) -> dict:
    """그날 비용 전 실현손익의 누계와 규칙의 일 손실 한도 — ★시뮬레이터의 판정과 같은 값★.

    시뮬레이터는 매도마다 `(매도가 − 진입가) × 수량` 을 더하고 누계가 `−한도` 이하가 되면 그날 새 진입을 멈춘다(되돌리지 않는다).
    그래서 `touched` 는 끝의 누계가 아니라 ★매도 순서대로의 누계가 한 번이라도 닿았는지★다. 포지션 계산은 새로 쓰지 않는다 — 매매일지의 왕복 매칭."""
    parsed, _rejects = normalize(_rows(fills))
    per_sell: dict[int, float] = {}
    for trade in match(parsed).trades:
        for m in trade.matches:
            per_sell[m.sell.row] = per_sell.get(m.sell.row, 0.0) + m.gross
    total = lowest = 0.0
    for row in sorted(per_sell):
        total += per_sell[row]
        lowest = min(lowest, total)
    if limit is None:
        return {"limit": None, "reason": REASONS["no_loss_limit"], "realized_gross": total, "room": None, "touched": None}
    return {"limit": float(limit), "reason": None, "realized_gross": total, "room": float(limit) + total, "touched": lowest <= -limit}


# ── 그날의 백테스트와 견주기 ──────────────────────────────────────────────────────────

def _backtest(run: dict, fills: list[dict], parts, day_of) -> dict:
    out = {"run_fills": len(fills), "backtest_fills": None}
    if run["status"] != "finished":
        return {"state": "not_compared", "reason": BACKTEST["running" if run["active"] else "stopped"], **out}
    if parts is None:
        return {"state": "unknown", "reason": REASONS["bad_setting"], **out}
    rule, position, costs = parts
    try:
        built = day_of(list(run["tickers"]), rule, run["day"]) if day_of is not None else None
    except DayUnavailable as err:                               # 적재와 다른 사유 — 그 문장 그대로
        return {"state": "unknown", "reason": err.reason, **out}
    if built is None:
        return {"state": "unknown", "reason": BACKTEST["not_loaded"], **out}
    day, session = built
    again = _rows(simulate([day], rule, position, costs, rules=session)["fills"])
    state = "same" if again == _rows(fills) else "differs"
    return {"state": state, "reason": BACKTEST[state], "run_fills": len(fills), "backtest_fills": len(again)}


# ── 입구 ─────────────────────────────────────────────────────────────────────────────

def view(username: str, account_id: str, run_id: int, *, master: Callable[[str], dict | None] | None = None,
         day_of: Callable | None = None) -> dict:
    """내 계좌의 가동 하나와 그 관제 → `{"run": …, "monitor": …}`. 없거나 남의 것이면 `RunRefused("not_found")`.

    `master` 는 종목 마스터(매매일지가 이름을 읽는다 — 시장 · 상품은 옛 줄일 때만), `day_of(tickers, rule, day)` 는 그날의 봉을 분봉 백테스트와 같은 준비로
    지어 `(Day, session)` 을 주거나 적재돼 있지 않으면 `None` 을 준다."""
    run = rule_runner.get(username, account_id, run_id)
    fills = run["fills"]
    log, truncated = _order_log(account_id, run_id)
    orders, counts = _orders(fills, log, truncated)
    try:
        parts = rule_runner.parts_of(run["request"])
    except rule_runner.RunRefused:
        parts = None
    journal = None
    if parts is None:
        why = REASONS["bad_setting"]
        pnl = {"available": False, "reason": why, "gross": None, "cost": None, "net": None, "net_reason": None,
               "closed_trades": None, "open_positions": None, "includes_rejected": None, "basis": None, "classification": None}
        limit = {"limit": None, "reason": why, "realized_gross": None, "room": None, "touched": None}
    else:
        pnl, journal = pnl_of(fills, parts[2], master)
        limit = loss_limit(fills, parts[1].daily_loss_limit)
    kill = get_account_executor(account_id).kill_switch
    return {"run": run, "monitor": {
        "orders": orders, "fills": counts, "pnl": pnl, "loss_limit": limit,
        "kill": {"active": kill.is_active(), "own": kill.active_event() is not None},
        "feed": {"kind": run["feed"], "lag_seconds": None, "lag_reason": REASONS["replay_has_no_lag"]},
        "backtest": _backtest(run, fills, parts, day_of),
        # 하루가 끝난 뒤에만 일지 전체를 싣는다(도는 가동은 요약만 — 주기 조회의 본문을 작게).
        "journal": journal if fills and not run["active"] else None,
    }}
