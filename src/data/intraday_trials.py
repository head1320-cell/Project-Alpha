"""시행 횟수 기록 — 분봉 백테스트를 ★몇 번 해 봤는가(N)★ 를 세는 자리 (설계 §8.2 · W4d).

같은 사람이 설정을 바꿔 가며 여러 번 돌리고 가장 좋아 보이는 것을 고르면, 그 숫자는 운으로도 좋아진다. 그 보정
(`deflated_sharpe`)은 N 을 요구하는데, 이 저장소에는 실행 이력의 N 을 세는 자리가 없었다(`multiplicity_evidence`).
여기가 그 첫 자리다 — ★분봉 백테스트만 센다.★

- **한 시행** = 설정(규칙 틀 · 매개변수 · 포지션 · 비용)이 하나라도 다른 실행. 같은 설정 · 같은 종목 · 같은 기간을
  다시 돌린 것은 새 시행이 아니다(그 줄의 실행 횟수만 는다).
- **가족**(N 을 세는 범위) = 그 사용자의 시행 가운데 ★기간이 겹치고 종목이 하나라도 겹치는★ 것. 기간을 하루 옮기거나
  종목 하나를 바꿔 N 을 되돌릴 수 없게 넓게 잡는다.
- **출처 등급이 다르면 다른 시행이다.** 합성 분봉 위에서 해 본 것은 실제 분봉을 본 것이 아니다 — 서로의 N 에도,
  서로의 흐름에도 들어가지 않는다(모의 모드에서 쌓인 합성 흐름이 운영의 보정에 섞이지 않게).
- 일별 손익 흐름을 함께 남긴다. 보정은 시행들 사이의 샤프 흩어짐을 요구한다 — 흐름이 없으면 만들 수 없다.
- ★지우는 길이 없다.★ 지우면 N 이 줄어 보정이 약해진다.
- 기록하지 못하면 `None` 이다. ★N=1 로 꾸미지 않는다★ — 부르는 쪽이 '모른다'로 답한다(`REASONS`).

N 은 ★하한★이다. 이 도구 밖에서 해 본 것 · 기록에 실패한 실행은 세지 못한다.

**결과 요약**(캔버스 노드 설계 §6) — 캔버스의 '분봉 백테스트 실행' 단추가 그 실행의 판정 요약을 시행 줄에 함께 남기고,
'분봉 결과 조회' 노드가 그것을 읽는다. ★시행을 세는 길과 닿지 않는다★: 열을 붙이지 못한 DB 에서도 N 은 지금처럼 세고,
결과 기능만 '모른다'(`None`)가 된다. 읽기는 늘 본인 것만이고, 남의 것과 없는 것은 같은 답이다.
남기는 것은 모의 실행의 설정과 그 결과의 일별 합계다 — 주문·계좌·고객 정보가 아니다.
`backtest_runs` 와 같은 방어적 raw-SQL 관용구(DB 는 선택적이고 실패하면 `None`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterable
from typing import Any

from src.data import schema_add_columns

logger = logging.getLogger(__name__)

_TABLE = "intraday_trials"
#: 표를 만들어 둔 DB. 프로세스가 다른 DB 로 붙으면(시험 · 폴백) 그 DB 에도 표를 만든다.
_ready_for: str | None = None
#: 결과 요약 열을 쓸 수 있는 DB. 붙이지 못했으면 `None` — 결과 기능만 '모른다'가 되고 시행 세기는 그대로 돈다.
_results_for: str | None = None
_RESULT_COLS = [("result", "TEXT"), ("result_at", "DOUBLE PRECISION")]

REASONS = {
    "store_unavailable": "시행 기록을 읽거나 쓰지 못했습니다. 시행 횟수를 알 수 없어 보정하지 않았습니다.",
}

_COLS = ("trial_key, setting, tickers, period_from, period_to, daily, runs, oos_views, oos_from, oos_to, "
         "created_at, updated_at")


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure(engine) -> None:
    global _ready_for, _results_for
    url = str(engine.url)
    if _ready_for == url:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "trial_key VARCHAR(64) PRIMARY KEY, username VARCHAR(60), grade VARCHAR(10), "
            "setting_digest VARCHAR(64), setting TEXT, tickers TEXT, "
            "period_from VARCHAR(10), period_to VARCHAR(10), daily TEXT, "
            "runs INTEGER, oos_views INTEGER, oos_from VARCHAR(10), oos_to VARCHAR(10), "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION)"))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_itr_user ON {_TABLE} (username, grade, period_from, period_to)"))
    # 결과 요약 열 — 먼저 만들어진 표(W4d)에도 덧붙인다. 붙었는지는 도우미가 SELECT 로 확인한다.
    _results_for = url if schema_add_columns.add_columns(engine, _TABLE, _RESULT_COLS, label="분봉 시행의 결과 요약") else None
    _ready_for = url


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(setting: dict) -> str:
    """설정의 요약값 — 칸의 순서만 다르면 같고, 값이 하나라도 다르면 다르다(`None` 과 0 도 다르다)."""
    return hashlib.sha256(_canonical(setting).encode()).hexdigest()


def _key(user: str, grade: str, setting: dict, tickers: list[str], start: str, end: str) -> str:
    return hashlib.sha256(_canonical([user, grade, digest(setting), tickers, start, end]).encode()).hexdigest()


def _load(raw: str | None) -> Any:
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def record(user: str, *, grade: str, setting: dict, tickers: Iterable[str], start: str, end: str,
           daily: dict) -> dict[str, Any] | None:
    """실행 하나를 남긴다 → `{trial_key, new, runs}`. 같은 시행이면 실행 횟수와 흐름만 바꾼다. 실패하면 `None`."""
    names = sorted(set(tickers))
    key = _key(user, grade, setting, names, start, end)
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        now = time.time()
        bump = text(f"UPDATE {_TABLE} SET runs = runs + 1, daily = :daily, updated_at = :now WHERE trial_key = :key")
        row = {"key": key, "daily": _canonical(daily), "now": now}
        with engine.begin() as c:
            new = c.execute(bump, row).rowcount == 0
            if new:
                c.execute(text(
                    f"INSERT INTO {_TABLE} (trial_key, username, grade, setting_digest, setting, tickers, period_from, "
                    "period_to, daily, runs, oos_views, oos_from, oos_to, created_at, updated_at) VALUES "
                    "(:key, :user, :grade, :digest, :setting, :tickers, :start, :end, :daily, 1, 0, NULL, NULL, :now, :now)"),
                    {**row, "user": user, "grade": grade, "digest": digest(setting), "setting": _canonical(setting),
                     "tickers": _canonical(names), "start": start, "end": end})
            runs = c.execute(text(f"SELECT runs FROM {_TABLE} WHERE trial_key = :key"), {"key": key}).scalar()
        return {"trial_key": key, "new": new, "runs": int(runs)}
    except Exception as err:                                    # noqa: BLE001 — DB 는 선택적이다. 실패는 '모른다'로 올린다
        logger.warning("intraday trial 기록 실패: %s", err)
        return None


def mark_oos(user: str, trial_key: str, oos_from: str, oos_to: str) -> int | None:
    """그 시행의 표본외 구간을 한 번 봤다고 적는다 → 지금까지 본 횟수. 내 시행이 아니거나 실패하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        where = "WHERE trial_key = :key AND username = :user"
        args = {"key": trial_key, "user": user}
        with engine.begin() as c:
            done = c.execute(text(f"UPDATE {_TABLE} SET oos_views = oos_views + 1, oos_from = :a, oos_to = :b {where}"),
                             {**args, "a": oos_from, "b": oos_to}).rowcount
            if not done:
                return None
            return int(c.execute(text(f"SELECT oos_views FROM {_TABLE} {where}"), args).scalar())
    except Exception as err:                                    # noqa: BLE001
        logger.warning("intraday trial 표본외 기록 실패: %s", err)
        return None


def family(user: str, *, grade: str, tickers: Iterable[str], start: str, end: str) -> dict[str, Any] | None:
    """가족 = 이 사용자 · 이 출처 등급의 시행 가운데 기간이 겹치고 종목이 하나라도 겹치는 것(처음 만든 순서).

    `user_total` 은 그 사용자 · 그 등급의 전체 시행 수다. 읽지 못하면 `None` — 빈 가족(N=0)과 다르다."""
    wanted = set(tickers)
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        who = {"user": user, "grade": grade}
        with engine.connect() as c:
            total = c.execute(text(f"SELECT COUNT(*) FROM {_TABLE} WHERE username = :user AND grade = :grade"), who).scalar()
            rows = c.execute(text(
                f"SELECT {_COLS} FROM {_TABLE} WHERE username = :user AND grade = :grade "
                "AND period_from <= :end AND period_to >= :start ORDER BY created_at, trial_key"),
                {**who, "start": start, "end": end}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("intraday trial 읽기 실패: %s", err)
        return None
    found = []
    for r in rows:
        names = _load(r[2]) or []
        if wanted.isdisjoint(names):
            continue
        found.append({"trial_key": r[0], "setting": _load(r[1]), "tickers": names, "from": r[3], "to": r[4],
                      "daily": _load(r[5]), "runs": int(r[6] or 0), "oos_views": int(r[7] or 0), "oos_from": r[8],
                      "oos_to": r[9], "created_at": r[10], "updated_at": r[11]})
    return {"trials": found, "user_total": int(total or 0)}


# ── 결과 요약 ──────────────────────────────────────────────────────────────────────────
def _results_ready(engine) -> bool:
    _ensure(engine)
    return _results_for == str(engine.url)


def keep_result(user: str, trial_key: str, result: dict) -> bool | None:
    """내 시행 줄에 그 실행의 결과 요약을 남긴다(다시 실행하면 바꿔 쓴다) → 남겼으면 참 · 내 시행이 아니면 거짓 · 실패하면 `None`."""
    try:
        engine = _engine()
        if not _results_ready(engine):
            return None
        from sqlalchemy import text
        with engine.begin() as c:
            done = c.execute(text(f"UPDATE {_TABLE} SET result = :result, result_at = :now "
                                  "WHERE trial_key = :key AND username = :user"),
                             {"result": _canonical(result), "now": time.time(), "key": trial_key, "user": user}).rowcount
        return bool(done)
    except Exception as err:                                    # noqa: BLE001
        logger.warning("intraday trial 결과 요약 기록 실패: %s", err)
        return None


_RESULT_HEAD = "trial_key, grade, setting, tickers, period_from, period_to, runs, result_at"


def _head(r) -> dict[str, Any]:
    return {"trial_key": r[0], "grade": r[1], "setting": _load(r[2]), "tickers": _load(r[3]) or [], "from": r[4], "to": r[5],
            "runs": int(r[6] or 0), "result_at": r[7]}


def result_of(user: str, trial_key: str) -> dict[str, Any] | None:
    """내 시행의 결과 요약 → `{found: True, result, …}` · 없으면 `{found: False}` · 읽지 못하면 `None`.

    ★남의 시행과 없는 시행은 같은 답이다★ — 있는지를 알려 주지 않는다. 요약이 깨져 읽히지 않으면 '없음'이 아니라 '모른다'다."""
    try:
        engine = _engine()
        if not _results_ready(engine):
            return None
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(f"SELECT {_RESULT_HEAD}, result FROM {_TABLE} "
                                 "WHERE trial_key = :key AND username = :user AND result IS NOT NULL"),
                            {"key": trial_key, "user": user}).fetchone()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("intraday trial 결과 요약 읽기 실패: %s", err)
        return None
    if row is None:
        return {"found": False}
    result = _load(row[8])
    if not isinstance(result, dict):
        logger.warning("intraday trial 결과 요약이 깨져 있다: %s", trial_key)
        return None
    return {"found": True, "result": result, **_head(row)}


def results_of(user: str, limit: int = 50) -> list[dict[str, Any]] | None:
    """결과 요약이 있는 내 시행들(남긴 시각의 최근 순 · 요약 자체는 싣지 않는다). 읽지 못하면 `None` — 빈 목록과 다르다."""
    try:
        engine = _engine()
        if not _results_ready(engine):
            return None
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT {_RESULT_HEAD} FROM {_TABLE} WHERE username = :user AND result IS NOT NULL "
                                  "ORDER BY result_at DESC, trial_key LIMIT :limit"),
                             {"user": user, "limit": int(limit)}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("intraday trial 결과 목록 읽기 실패: %s", err)
        return None
    return [_head(r) for r in rows]


def views_of(rows: Iterable[dict], oos_from: str, oos_to: str) -> int:
    """이 표본외 구간과 ★겹치는★ 표본외 구간을 본 횟수의 합 — 다른 시행으로 본 것도 같은 날들을 본 것이다."""
    return sum(int(r.get("oos_views") or 0) for r in rows
               if r.get("oos_from") and r.get("oos_to") and r["oos_from"] <= oos_to and r["oos_to"] >= oos_from)
