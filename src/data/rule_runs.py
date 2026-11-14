"""가동 기록 — 가동 요청 · 가동 · 가상 체결을 적는 자리 (설계 W5 §5 · 구현 계획 §3)

- **가동 요청**(`rule_arm_requests`): 캔버스가 남긴 '이 시행을 가동해 달라'는 한 줄. ★요청은 가동이 아니다★ — 가동은 내 계좌에서 사람이 한다.
  지우기는 표시만 한다(무엇을 요청했었는지는 남는다). 같은 시행의 살아 있는 요청은 한 줄이다.
- **가동**(`rule_runs`): 계좌 하나 × 시행 하나 × 하루. `run_id`(정수)가 주문 · 감사 줄의 `strategy_id` 자리에 들어가 가동과 주문을 잇는다.
  설정은 가동할 때의 사본을 함께 적는다(시행 줄이 뒤에 바뀌어도 그때 무엇을 돌렸는지 남는다).
- **가상 체결**(`rule_run_fills`): 기록 전용 가동에서 시뮬레이터가 계산한 체결과, 그 신호가 주문 경로에서 받은 답.
  ★종류는 늘 `virtual` 이다★ — 증권사가 알려 준 체결이 아니다. 실제 체결의 자리(`live_fills`)에는 쓰지 않는다.

전부 사용자로 갈린다 — 남의 것과 없는 것은 같은 답이다. 읽거나 쓰지 못하면 `None` 이다(빈 목록 · '없음'과 다르다 — `REASONS`).
`intraday_trials` 와 같은 방어적 raw-SQL 관용구다. 합성값을 만들지 않는다 — 적힌 것만 돌려준다.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_REQUESTS, _RUNS, _FILLS = "rule_arm_requests", "rule_runs", "rule_run_fills"
#: 표를 만들어 둔 DB(주소별) — 프로세스가 다른 DB 로 붙으면 그 DB 에도 만든다.
_ready_for: str | None = None

STATUSES = ("running", "stopped", "finished", "interrupted")
REASONS = {
    "store_unavailable": "가동 기록을 읽거나 쓰지 못했습니다.",
    "interrupted": "서버가 다시 시작돼 가동이 중단됐습니다. 다시 가동하려면 직접 켜야 합니다.",
}
#: 가동 중에 바뀌는 칸 — 그 밖의 칸(누구의 · 어느 계좌의 · 무엇을 · 어느 모드로)은 고치는 길이 없다.
_PROGRESS = ("status", "stop_reason", "stop_message", "last_bar", "bars", "signals")
_RUN_COLS = ("run_id, username, account_id, trial_key, request, tickers, day, feed, mode, grade, status, stop_reason, "
             "stop_message, last_bar, bars, signals, started_at, ended_at")


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure(engine) -> None:
    global _ready_for
    url = str(engine.url)
    if _ready_for == url:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_REQUESTS} (id INTEGER PRIMARY KEY, username VARCHAR(60), trial_key VARCHAR(64), "
            "note TEXT, created_at DOUBLE PRECISION, removed_at DOUBLE PRECISION)"))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_rar_user ON {_REQUESTS} (username, created_at)"))
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_RUNS} (run_id INTEGER PRIMARY KEY, username VARCHAR(60), account_id VARCHAR(64), "
            "trial_key VARCHAR(64), request TEXT, tickers TEXT, day VARCHAR(10), feed VARCHAR(20), mode VARCHAR(10), "
            "grade VARCHAR(10), status VARCHAR(20), stop_reason VARCHAR(40), stop_message TEXT, last_bar VARCHAR(6), "
            "bars INTEGER, signals INTEGER, started_at DOUBLE PRECISION, ended_at DOUBLE PRECISION)"))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_rr_owner ON {_RUNS} (username, account_id, started_at)"))
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_FILLS} (run_id INTEGER, seq INTEGER, executed_at VARCHAR(19), symbol VARCHAR(12), "
            "side VARCHAR(4), quantity DOUBLE PRECISION, price DOUBLE PRECISION, kind VARCHAR(10), event VARCHAR(30), "
            "client_order_id VARCHAR(40), order_status VARCHAR(20), order_reason VARCHAR(60), PRIMARY KEY (run_id, seq))"))
    _ready_for = url


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(raw: str | None) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _next_id(c, table: str, column: str) -> int:
    """다음 번호. `--workers 1` 전제의 프로세스 하나가 쓰고, 겹치면 기본 키가 막는다(쓰는 쪽이 `None` 으로 답한다)."""
    from sqlalchemy import text
    return int(c.execute(text(f"SELECT COALESCE(MAX({column}), 0) + 1 FROM {table}")).scalar())


# ── 가동 요청 ────────────────────────────────────────────────────────────────

def add_request(user: str, trial_key: str, note: str | None = None) -> dict[str, Any] | None:
    """요청 한 줄 → `{id, trial_key, new, created_at}`. 같은 시행의 살아 있는 요청이 있으면 그것을 돌려준다(`new=False`)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            row = c.execute(text(f"SELECT id, created_at FROM {_REQUESTS} WHERE username = :user AND trial_key = :key "
                                 "AND removed_at IS NULL"), {"user": user, "key": trial_key}).fetchone()
            if row is not None:
                return {"id": int(row[0]), "trial_key": trial_key, "new": False, "created_at": row[1]}
            new_id, now = _next_id(c, _REQUESTS, "id"), time.time()
            c.execute(text(f"INSERT INTO {_REQUESTS} (id, username, trial_key, note, created_at, removed_at) VALUES "
                           "(:id, :user, :key, :note, :now, NULL)"),
                      {"id": new_id, "user": user, "key": trial_key, "note": note, "now": now})
        return {"id": new_id, "trial_key": trial_key, "new": True, "created_at": now}
    except Exception as err:                                    # noqa: BLE001 — 실패는 '모른다'로 올린다
        logger.warning("가동 요청 기록 실패: %s", err)
        return None


def requests_of(user: str, limit: int = 50) -> list[dict[str, Any]] | None:
    """내 살아 있는 요청들(최근 순). 읽지 못하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT id, trial_key, note, created_at FROM {_REQUESTS} WHERE username = :user "
                                  "AND removed_at IS NULL ORDER BY created_at DESC, id DESC LIMIT :limit"),
                             {"user": user, "limit": int(limit)}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 요청 목록 읽기 실패: %s", err)
        return None
    return [{"id": int(r[0]), "trial_key": r[1], "note": r[2], "created_at": r[3]} for r in rows]


def remove_request(user: str, request_id: int) -> bool | None:
    """내 요청을 목록에서 뺀다(줄은 남는다) → 뺐으면 참 · 내 살아 있는 요청이 아니면 거짓 · 실패하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            done = c.execute(text(f"UPDATE {_REQUESTS} SET removed_at = :now WHERE id = :id AND username = :user "
                                  "AND removed_at IS NULL"), {"now": time.time(), "id": int(request_id), "user": user}).rowcount
        return bool(done)
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 요청 지우기 실패: %s", err)
        return None


# ── 가동 ────────────────────────────────────────────────────────────────────

def open_run(user: str, account_id: str, trial_key: str, request: dict, day: str, *, feed: str, mode: str, grade: str,
             tickers: list[str]) -> int | None:
    """가동 한 줄을 연다(`running`) → 가동 번호. 실패하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            run_id = _next_id(c, _RUNS, "run_id")
            c.execute(text(
                f"INSERT INTO {_RUNS} ({_RUN_COLS}) VALUES (:run_id, :user, :account, :key, :request, :tickers, :day, :feed, "
                ":mode, :grade, 'running', NULL, NULL, NULL, 0, 0, :now, NULL)"),
                {"run_id": run_id, "user": user, "account": account_id, "key": trial_key, "request": _dump(request),
                 "tickers": _dump(sorted(tickers)), "day": day, "feed": feed, "mode": mode, "grade": grade, "now": time.time()})
        return run_id
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 기록 열기 실패: %s", err)
        return None


def update_run(run_id: int, *, ended: bool = False, **progress) -> bool | None:
    """진행과 멈춘 사유를 적는다 → 적었으면 참 · 없는 가동이면 거짓 · 실패하면 `None`. 진행이 아닌 칸은 고칠 수 없다."""
    bad = [k for k in progress if k not in _PROGRESS]
    if bad or progress.get("status", STATUSES[0]) not in STATUSES:
        raise ValueError(f"가동 기록에서 고칠 수 없는 칸이나 값입니다: {bad or progress.get('status')}")
    if not progress and not ended:
        return True
    sets = [f"{k} = :{k}" for k in progress] + (["ended_at = :ended_at"] if ended else [])
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            done = c.execute(text(f"UPDATE {_RUNS} SET {', '.join(sets)} WHERE run_id = :run_id"),
                             {**progress, "ended_at": time.time(), "run_id": int(run_id)}).rowcount
        return bool(done)
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 기록 갱신 실패: %s", err)
        return None


def _run(r) -> dict[str, Any]:
    return {"run_id": int(r[0]), "account_id": r[2], "trial_key": r[3], "request": _load(r[4]), "tickers": _load(r[5]) or [],
            "day": r[6], "feed": r[7], "mode": r[8], "grade": r[9], "status": r[10], "stop_reason": r[11], "stop_message": r[12],
            "last_bar": r[13], "bars": int(r[14] or 0), "signals": int(r[15] or 0), "started_at": r[16], "ended_at": r[17]}


def run_of(user: str, account_id: str, run_id: int) -> dict[str, Any] | None:
    """내 계좌의 가동 하나 → `{found: True, …}` · 없거나 남의 것이면 `{found: False}` · 읽지 못하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(f"SELECT {_RUN_COLS} FROM {_RUNS} WHERE run_id = :run_id AND username = :user "
                                 "AND account_id = :account"), {"run_id": int(run_id), "user": user, "account": account_id}).fetchone()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 기록 읽기 실패: %s", err)
        return None
    return {"found": False} if row is None else {"found": True, **_run(row)}


def runs_of(user: str, account_id: str, limit: int = 50) -> list[dict[str, Any]] | None:
    """내 계좌의 가동들(최근 순). 읽지 못하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT {_RUN_COLS} FROM {_RUNS} WHERE username = :user AND account_id = :account "
                                  "ORDER BY started_at DESC, run_id DESC LIMIT :limit"),
                             {"user": user, "account": account_id, "limit": int(limit)}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가동 목록 읽기 실패: %s", err)
        return None
    return [_run(r) for r in rows]


def mark_interrupted() -> int | None:
    """★기동 때 한 번★ — `running` 으로 남은 가동을 `interrupted` 로 바꾼다(가동은 메모리에만 있다 — 재시작하면 전부 꺼진다) → 바꾼 줄 수."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            done = c.execute(text(f"UPDATE {_RUNS} SET status = 'interrupted', stop_reason = 'interrupted', stop_message = :msg, "
                                  "ended_at = :now WHERE status = 'running'"), {"msg": REASONS["interrupted"], "now": time.time()}).rowcount
        return int(done)
    except Exception as err:                                    # noqa: BLE001
        logger.warning("중단된 가동 표시 실패: %s", err)
        return None


# ── 가상 체결 ────────────────────────────────────────────────────────────────

def add_fill(run_id: int, seq: int, fill: dict, *, event: str, order: dict) -> bool | None:
    """가상 체결 한 줄과 그 신호가 주문 경로에서 받은 답. 같은 순번을 두 번 쓰지 못한다(덮어쓰지 않고 `None`)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_FILLS} (run_id, seq, executed_at, symbol, side, quantity, price, kind, event, client_order_id, "
                "order_status, order_reason) VALUES (:run_id, :seq, :at, :symbol, :side, :qty, :price, 'virtual', :event, "
                ":coid, :status, :reason)"),
                {"run_id": int(run_id), "seq": int(seq), "at": fill["executed_at"], "symbol": fill["symbol"], "side": fill["side"],
                 "qty": fill["quantity"], "price": fill["price"], "event": event, "coid": order.get("client_order_id"),
                 "status": order.get("status"), "reason": order.get("reason")})
        return True
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가상 체결 기록 실패: %s", err)
        return None


def fills_of(run_id: int) -> list[dict[str, Any]] | None:
    """그 가동의 가상 체결(낸 순서). ★소유는 `run_of` 가 먼저 본다★ — 이 함수는 번호만 받는 안쪽 통로다. 읽지 못하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT seq, executed_at, symbol, side, quantity, price, kind, event, client_order_id, "
                                  f"order_status, order_reason FROM {_FILLS} WHERE run_id = :run_id ORDER BY seq"),
                             {"run_id": int(run_id)}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("가상 체결 읽기 실패: %s", err)
        return None
    return [{"seq": int(r[0]), "executed_at": r[1], "symbol": r[2], "side": r[3], "quantity": r[4], "price": r[5], "kind": r[6],
             "event": r[7], "client_order_id": r[8], "order_status": r[9], "order_reason": r[10]} for r in rows]
