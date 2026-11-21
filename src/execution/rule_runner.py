"""규칙 가동기 — 기록 전용(SHADOW) · 재생 (설계 W5 §5.4 · 구현 계획 §4)
==============================================================================
가동 하나 = 계좌 하나 × 시행 하나 × 하루. 봉이 닫힐 때마다 걸음 엔진(`engine.intraday.stepper`)을 한 걸음 밀고, 새로 생긴 체결 줄마다
신호 하나를 ★계좌 실행기의 `execute_signal` 한 길로만★ 보낸다(감사 → 비상 정지 → 위험 검사 → 모드). 기록 전용에서는 증권사로
아무것도 나가지 않고, 시뮬레이터가 계산한 체결을 '가상'으로 적는다(`data.rule_runs` — 실제 체결의 자리에는 쓰지 않는다).

## ★가동되는 것은 시행으로 세어진 설정뿐이다★

설정은 부르는 쪽이 넘기지 않는다 — 시행 줄(`data.intraday_trials`)에서 읽어 여기서 짓는다. 분봉 백테스트로 한 번도 돌려 보지 않은
설정은 가동할 길이 없고, 가동 중인 규칙은 기록된 설정과 다를 수 없다. 받는 것은 그날의 봉(`Day`)뿐이다 — 문 층이 백테스트와 같은
준비(`data.minute_feed`)로 지어 넘긴다.

## ★가동은 메모리에만 있다 — 재시작하면 전부 꺼진다★

모드와 같은 규칙이다(`account_executors`). DB 에서 가동을 되살려 신호가 다시 나가는 길을 조용히 열지 않는다. 꺼진 가동은 기록에
'중단됨'으로 남고(`reset()` — 기동 때), 메모리에 없는 '가동 중'은 읽는 자리에서도 '중단됨'으로 바로잡는다. 다시 켜는 것은 사람이 한다.
`uvicorn --workers 1` 전제다.

## 멈추는 조건 (`STOPS` — 전부 사유와 문장이 남는다)

봉을 보기 전에: 계좌의 모드가 시작할 때와 다르다 · 비상 정지 · 앞 봉과의 빈틈이 `GAP_MINUTES` 를 넘는다(낡은 봉으로 계속 돌지 않는다).
주문 경로의 답으로: 비상 정지로 거절 · 기록 전용의 답이 아니다(그 사이 모드가 바뀌었다) · 거절이 `MAX_REJECTIONS` 번 이어졌다 · 예외.
그 밖에: 사용자의 정지 · 다시 계산한 체결이 앞에서 낸 것과 다르다 · 기록을 쓰지 못했다 · 하루가 끝났다.
★멈춘 가동은 청산 신호를 내지 않는다★ — 없는 청산을 지어내지 않는다(하루의 끝까지 간 가동만 강제 청산 줄을 낸다).

## 이 조각이 하지 않는 것

모의투자(PAPER) 주문으로의 가동 · 장중 조회 공급 · 배경 스레드(재생의 시계는 부르는 쪽이 민다) · 자동 재개. 계좌의 소유는 문이 먼저 보고
여기서도 한 번 더 본다.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import src.data.intraday_trials as trials
import src.data.rule_runs as rule_runs
import src.execution.broker_accounts as broker_accounts
from src.data.mock_gate import mock_allowed
from src.engine import intraday
from src.engine.intraday import rules
from src.engine.intraday import setting as setting_parts
from src.engine.intraday.simulator import CostAssumptions, Day, PositionRules, RuleSpec
from src.engine.intraday.stepper import REASONS as STEP_REASONS
from src.engine.intraday.stepper import StepError, Stepper
from src.execution.account_executors import get_account_executor
from src.execution.order_executor import ExecutionMode

logger = logging.getLogger(__name__)

#: 앞 봉과 이만큼(분)보다 넓게 벌어지면 봉이 끊긴 것으로 본다. ★설정값★이다(재 본 값이 아니다) — 고른 종목 전부에 봉이 없는 시간을 본다.
GAP_MINUTES = 5
#: 한 계좌에서 동시에 도는 가동 수 · 가동 하나의 종목 수. 걸음마다 하루를 처음부터 다시 돈다(잰 값은 HISTORY).
MAX_RUNS_PER_ACCOUNT = 3
MAX_RUN_TICKERS = 10
#: 주문 경로의 거절이 이만큼 이어지면 멈춘다(받아들여진 신호가 끼면 처음부터 다시 센다).
MAX_REJECTIONS = 3

REASONS = {
    "store_unavailable": "가동 기록이나 실행 기록을 읽거나 쓰지 못했습니다(없는 것과 다릅니다).",
    "not_found": "가동을 찾지 못했습니다.",
    "no_trial": "이 설정으로 분봉 백테스트를 실행한 기록이 없습니다. 실행 기록이 있는 설정만 가동합니다.",
    "bad_setting": "실행 기록에 적힌 설정을 지금의 규칙 틀로 읽지 못했습니다.",
    "synthetic_in_production": "합성 분봉이나 합성 분봉으로 실행한 설정은 운영에서 가동하지 않습니다.",
    "bad_day": "받은 하루의 종목이 실행 기록의 종목과 다릅니다.",
    "no_usable_bars": "그 날짜에 쓸 수 있는 분봉이 없습니다.",
    "too_many_runs": "한 계좌에서 동시에 가동하는 규칙 수의 상한에 닿았습니다.",
    "too_many_tickers": "가동 하나의 종목 수 상한을 넘었습니다.",
    "mode_not_supported": "지금은 기록 전용 모드에서만 가동합니다. 모의투자 주문으로의 가동은 아직 없습니다.",
    "kill_switch_active": "비상 정지가 걸려 있어 가동을 시작하지 않았습니다.",
    "feed_not_supported": "지금은 적재된 하루를 다시 흘리는 재생만 있습니다.",
    "not_running": "가동 중이 아닙니다. 멈춘 가동은 되살리지 않습니다.",
    "bad_bars": "걸음 수는 1 이상의 정수입니다.",
}

STOPS = {
    "user": "사용자가 정지했습니다.",
    "kill_switch": "비상 정지가 걸려 가동을 멈췄습니다.",
    "risk_rejections": f"주문 경로가 신호를 연달아 {MAX_REJECTIONS}번 거절해 가동을 멈췄습니다.",
    "feed_gap": f"봉이 {GAP_MINUTES}분 넘게 끊겨 가동을 멈췄습니다. 낡은 봉으로 계속 돌지 않습니다.",
    "not_monotone": STEP_REASONS["not_monotone"],
    "mode_changed": "계좌의 실행 모드가 가동을 시작할 때와 달라져 가동을 멈췄습니다. 다시 가동하려면 직접 켜야 합니다.",
    "finished": "하루의 봉을 끝까지 돌았습니다.",
    "store_unavailable": "가동 기록을 쓰지 못해 가동을 멈췄습니다.",
    "order_error": "주문 경로에서 오류가 나 가동을 멈췄습니다.",
}


class RunRefused(Exception):
    """가동기가 하지 않은 일과 그 사유. `extra` 는 사유를 읽는 데 필요한 값(상한 · 건너뛴 종목)이다."""

    def __init__(self, code: str, **extra: Any) -> None:
        super().__init__(REASONS[code])
        self.code, self.message, self.extra = code, REASONS[code], extra


@dataclass(frozen=True)
class Setting:
    """시행 줄에서 읽어 지은 설정. `request` 는 가동 기록에 남기는 사본이다(그때 무엇을 돌렸는지)."""

    trial_key: str
    grade: str
    tickers: tuple[str, ...]
    request: dict
    rule: RuleSpec
    position: PositionRules
    costs: CostAssumptions


@dataclass
class _Active:
    run_id: int
    username: str
    account_id: str
    mode: str
    stepper: Stepper
    labels: list[str]
    done: int = 0                      # 민 봉의 수
    signals: int = 0                   # 주문 경로에 보낸 신호의 수
    seq: int = 0                       # 적은 가상 체결의 수(다음 순번)
    rejections: int = 0                # 이어진 거절
    closed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


#: 돌고 있는 가동(가동 번호 → 상태). ★프로세스 로컬★ — 재시작하면 비어 있다.
_active: dict[int, _Active] = {}
#: 등록부와 '닫기'를 지킨다. 잡는 순서는 늘 가동의 자물쇠 → 이것이다.
_lock = threading.Lock()


# ── 설정 ─────────────────────────────────────────────────────────────────────────────

def parts_of(setting: dict) -> tuple[RuleSpec, PositionRules, CostAssumptions]:
    """설정 사본(시행 줄의 설정 · 가동 줄의 `request`) → 규칙 · 포지션 · 비용. 지금의 틀로 읽히지 않으면 `bad_setting`.

    관제(`rule_monitor`)도 이 함수로 ★그때 돌린 설정★을 다시 짓는다 — 읽는 길이 둘로 갈리지 않는다.
    몸은 `src.engine.intraday.setting.parts_of` 에 있다(분봉 하루 보기도 같은 함수로 읽는다 · G4) — 여기는 사유를 가동기의 것으로 바꿀 뿐이다."""
    try:
        return setting_parts.parts_of(setting)
    except setting_parts.SettingUnreadable:
        raise RunRefused("bad_setting") from None


def setting_of(username: str, trial_key: str) -> Setting:
    """내 시행 하나를 가동할 설정으로 — 없거나 남의 것이면 `no_trial`, 지금의 틀로 읽히지 않으면 `bad_setting`."""
    row = trials.trial_of(username, trial_key)
    if row is None:
        raise RunRefused("store_unavailable")
    if not row["found"]:
        raise RunRefused("no_trial")
    setting = row["setting"]
    rule, position, costs = parts_of(setting)
    tickers = tuple(sorted(row["tickers"]))
    request = {**setting, "tickers": list(tickers), "from": row["from"], "to": row["to"]}
    return Setting(trial_key, row["grade"], tickers, request, rule, position, costs)


# ── 시작 ─────────────────────────────────────────────────────────────────────────────

def start(username: str, account_id: str, trial_key: str, day: Day, *, session: dict | None = None,
          feed: str = "replay") -> dict:
    """가동을 연다(아직 봉을 밀지 않는다). `day` 는 그날의 봉, `session` 은 `market_rules.session_rules()` 의 답이다."""
    if feed != "replay":
        raise RunRefused("feed_not_supported")
    setting = setting_of(username, trial_key)
    if len(setting.tickers) > MAX_RUN_TICKERS:
        raise RunRefused("too_many_tickers", limit=MAX_RUN_TICKERS, tickers=len(setting.tickers))
    if set(day.sessions) - set(setting.tickers):
        raise RunRefused("bad_day")
    synthetic = setting.grade == "E0" or any(s.source == "synthetic" for s in day.sessions.values())
    if synthetic and not mock_allowed():
        raise RunRefused("synthetic_in_production")
    if not any(len(s.time) for s in day.sessions.values()):
        raise RunRefused("no_usable_bars", skipped=[{"ticker": t, "reason": r} for t, r in day.skipped])
    if not _owns(username, account_id):
        raise RunRefused("not_found")
    executor = get_account_executor(account_id)
    if executor.state.mode != ExecutionMode.SHADOW:
        raise RunRefused("mode_not_supported")
    if executor.kill_switch.is_active():
        raise RunRefused("kill_switch_active")
    stepper = Stepper(day, setting.rule, setting.position, setting.costs, rules=session)
    labels = sorted({str(t) for s in day.sessions.values() for t in s.time})
    with _lock:
        if sum(1 for a in _active.values() if a.account_id == account_id) >= MAX_RUNS_PER_ACCOUNT:
            raise RunRefused("too_many_runs", limit=MAX_RUNS_PER_ACCOUNT)
        run_id = rule_runs.open_run(username, account_id, trial_key, setting.request, day.date, feed=feed,
                                    mode=executor.state.mode, grade=intraday.session_grade(day.sessions.values()),
                                    tickers=list(setting.tickers))
        if run_id is None:
            raise RunRefused("store_unavailable")
        _active[run_id] = _Active(run_id, username, account_id, executor.state.mode, stepper, labels)
    logger.info("규칙 가동 시작: run=%s account=%s day=%s tickers=%s bars=%s", run_id, account_id, day.date,
                len(setting.tickers), len(labels))
    return _view(_row(username, account_id, run_id))


def _owns(username: str, account_id: str) -> bool:
    return any(a["account_id"] == account_id for a in broker_accounts.list_masked(username))


# ── 걸음 ─────────────────────────────────────────────────────────────────────────────

def advance(username: str, account_id: str, run_id: int, bars: int | None = None) -> dict:
    """봉을 `bars` 개 민다(`None` 이면 끝까지). 마지막 봉을 밀면 하루가 끝난다 — 강제 청산 줄이 그때 나온다."""
    _row(username, account_id, run_id)
    if bars is not None and (isinstance(bars, bool) or not isinstance(bars, int) or bars < 1):
        raise RunRefused("bad_bars")
    act = _active.get(run_id)
    if act is None:
        raise RunRefused("not_running")
    new: list[dict] = []
    with act.lock:
        if act.closed:
            raise RunRefused("not_running")
        left = bars
        while not act.closed and act.done < len(act.labels) and (left is None or left > 0):
            executor = get_account_executor(act.account_id)
            reason = _before_bar(act, executor)
            if reason:
                _close(act, "stopped", reason)
                break
            label = act.labels[act.done]
            try:
                rows = act.stepper.step(label)
            except StepError as err:
                _close(act, "stopped", err.code)
                break
            act.done += 1
            stop = _emit(act, executor, rows, new)
            if rule_runs.update_run(act.run_id, last_bar=label, bars=act.done, signals=act.signals) is None:
                stop = stop or ("store_unavailable", None)
            if stop:
                _close(act, "stopped", *stop)
                break
            if left is not None:
                left -= 1
        if not act.closed and act.done == len(act.labels):
            _finish(act, new)
    return {**_view(_row(username, account_id, run_id)), "new_fills": new}


def _minutes(label: str) -> int:
    return int(label[:2]) * 60 + int(label[2:4])


def _before_bar(act: _Active, executor, *, gap: bool = True) -> str | None:
    """봉을 보기 전에 — 멈춰야 하면 그 사유."""
    if executor.state.mode != act.mode:
        return "mode_changed"
    if executor.kill_switch.is_active():
        return "kill_switch"
    if gap and act.done and _minutes(act.labels[act.done]) - _minutes(act.labels[act.done - 1]) > GAP_MINUTES:
        return "feed_gap"
    return None


def _emit(act: _Active, executor, rows: list[dict], new: list[dict]) -> tuple[str, str | None] | None:
    """새 체결 줄마다 신호 하나 → 주문 경로의 답과 함께 가상 체결로 적는다. 멈춰야 하면 `(사유, 문장)`."""
    events = act.stepper.events[len(act.stepper.events) - len(rows):]
    for row, event in zip(rows, events, strict=True):
        if executor.state.mode != act.mode:                       # 봉을 본 뒤에 바뀌었다 — 보내지 않는다
            return ("mode_changed", None)
        signal = {"ticker": row["symbol"], "side": row["side"].upper(), "quantity": row["quantity"], "price": row["price"],
                  "order_type": "MARKET", "strategy_id": act.run_id, "source": "rule_run"}
        try:
            answer = executor.execute_signal(signal, actor=f"rule:{act.username}")
        except Exception as err:                                  # noqa: BLE001 — 주문 경로가 터지면 가동을 멈춘다
            logger.error("규칙 가동 %s: 주문 경로 오류 %s", act.run_id, type(err).__name__)
            return ("order_error", f"{STOPS['order_error']} 오류 종류: {type(err).__name__}.")   # 오류의 글은 싣지 않는다
        act.signals += 1
        if rule_runs.add_fill(act.run_id, act.seq, row, event=event, order=answer) is None:
            return ("store_unavailable", None)
        kept = bool(rule_runs.keeps_class())                      # 적힌 줄과 같은 모양으로 답한다(칸을 못 붙인 DB 면 비운다)
        new.append({"seq": act.seq, "executed_at": row["executed_at"], "symbol": row["symbol"], "side": row["side"],
                    "quantity": row["quantity"], "price": row["price"], "kind": "virtual", "event": event,
                    "client_order_id": answer.get("client_order_id"), "order_status": answer.get("status"),
                    "order_reason": answer.get("reason"), "market": row.get("market") if kept else None,
                    "instrument": row.get("instrument") if kept else None, "classified": kept})
        act.seq += 1
        status = answer.get("status")
        if status == "SHADOW_LOGGED":
            act.rejections = 0
            continue
        if status != "REJECTED":                                   # 기록 전용의 답이 아니다 — 그 사이 모드가 바뀌었다
            return ("mode_changed", None)
        if answer.get("reason") == "kill_switch_active":
            return ("kill_switch", None)
        act.rejections += 1
        if act.rejections >= MAX_REJECTIONS:
            return ("risk_rejections", None)
    return None


def _finish(act: _Active, new: list[dict]) -> None:
    """하루가 끝났다 — 남은 수량의 강제 청산 줄을 내고 닫는다. 멈춰야 할 까닭이 있으면 내지 않는다."""
    executor = get_account_executor(act.account_id)
    reason = _before_bar(act, executor, gap=False)
    if reason:
        _close(act, "stopped", reason)
        return
    try:
        rows = act.stepper.finish()
    except StepError as err:
        _close(act, "stopped", err.code)
        return
    stop = _emit(act, executor, rows, new)
    if rule_runs.update_run(act.run_id, signals=act.signals) is None:
        stop = stop or ("store_unavailable", None)
    if stop:
        _close(act, "stopped", *stop)
    else:
        _close(act, "finished", "finished")


def _close(act: _Active, status: str, reason: str, message: str | None = None) -> None:
    """가동을 닫는다 — 기록에 사유를 적고 메모리에서 뺀다. 가동의 자물쇠를 잡은 채로 부른다."""
    text = message or STOPS.get(reason) or STEP_REASONS.get(reason) or reason
    with _lock:
        if not rule_runs.update_run(act.run_id, status=status, stop_reason=reason, stop_message=text, ended=True):
            logger.error("규칙 가동 %s: 멈춘 사유(%s)를 적지 못했습니다", act.run_id, reason)
        _active.pop(act.run_id, None)
    act.closed = True
    logger.info("규칙 가동 끝: run=%s status=%s reason=%s bars=%s signals=%s", act.run_id, status, reason, act.done, act.signals)


# ── 정지 · 읽기 ───────────────────────────────────────────────────────────────────────

def stop(username: str, account_id: str, run_id: int) -> dict:
    """사용자의 정지. 이미 멈췄거나 끝난 가동은 그대로 둔다(끝난 가동을 '정지'로 바꾸지 않는다)."""
    _row(username, account_id, run_id)
    act = _active.get(run_id)
    if act is not None:
        with act.lock:
            if not act.closed:
                _close(act, "stopped", "user")
    return _view(_row(username, account_id, run_id))


def get(username: str, account_id: str, run_id: int) -> dict:
    """내 계좌의 가동 하나와 그 가상 체결."""
    view = _view(_row(username, account_id, run_id))
    fills = rule_runs.fills_of(run_id)
    if fills is None:
        raise RunRefused("store_unavailable")
    return {**view, "fills": fills}


def runs(username: str, account_id: str, limit: int = 50) -> list[dict]:
    """내 계좌의 가동들(최근 순). 체결은 싣지 않는다."""
    rows = rule_runs.runs_of(username, account_id, limit)
    if rows is None:
        raise RunRefused("store_unavailable")
    return [_view(_repaired(username, account_id, row)) for row in rows]


def active(account_id: str) -> list[int]:
    """그 계좌에서 지금 도는 가동 번호."""
    with _lock:
        return sorted(a.run_id for a in _active.values() if a.account_id == account_id)


def reset() -> int | None:
    """★기동 때 한 번★ — 메모리의 가동을 비우고, 기록에 '가동 중'으로 남은 줄을 '중단됨'으로 바꾼다 → 바꾼 줄 수(못 썼으면 `None`)."""
    with _lock:
        for act in _active.values():
            act.closed = True
        _active.clear()
        return rule_runs.mark_interrupted()


def _row(username: str, account_id: str, run_id: int) -> dict:
    row = rule_runs.run_of(username, account_id, run_id)
    if row is None:
        raise RunRefused("store_unavailable")
    if not row["found"]:
        raise RunRefused("not_found")
    return _repaired(username, account_id, row)


def _repaired(username: str, account_id: str, row: dict) -> dict:
    """메모리에 없는 '가동 중'은 가동 중이 아니다 — '중단됨'으로 바로잡아 돌려준다(기동 때의 표시가 실패했더라도)."""
    if row["status"] != "running":
        return row
    with _lock:
        if row["run_id"] in _active:
            return row
        fresh = rule_runs.run_of(username, account_id, row["run_id"])        # 그 사이에 닫혔을 수 있다 — 자물쇠 안에서 다시 읽는다
        if fresh is None:
            raise RunRefused("store_unavailable")
        if fresh.get("status") == "running":
            rule_runs.update_run(row["run_id"], status="interrupted", stop_reason="interrupted",
                                 stop_message=rule_runs.REASONS["interrupted"], ended=True)
            fresh = rule_runs.run_of(username, account_id, row["run_id"])
            if fresh is None:
                raise RunRefused("store_unavailable")
    return {**row, **fresh}


def _view(row: dict) -> dict:
    """기록 한 줄 + 지금 도는지와 시계. 시계는 도는 가동에만 있다(멈춘 가동의 봉은 메모리에 없다)."""
    act = _active.get(row["run_id"])
    clock = None
    if act is not None and not act.closed:
        clock = {"total": len(act.labels), "done": act.done, "next": act.labels[act.done] if act.done < len(act.labels) else None}
    request = row.get("request")
    said = rules.rule_text(request.get("rule") if isinstance(request, dict) else None)     # 읽기만 — 가동의 뜻은 바뀌지 않는다
    return {**{k: v for k, v in row.items() if k != "found"}, **said, "active": clock is not None, "clock": clock, "new_fills": []}
