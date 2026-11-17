"""하루 유형 모형의 저장소 — 사용자마다 학습한 e-means 모형을 남긴다 (설계 2026-11-16 §3 T1 · 구현 계획 §5.2).

- **한 모형** = 주인 + 열쇠. 열쇠는 엔진(`src.engine.intraday.day_types.model_key`)이 학습 표본 · 봉 · 설정에서 짓는다 —
  같은 주인이 같은 열쇠로 다시 저장하면 ★쓰지 않고★ 처음 것을 돌려준다(같은 입력 = 같은 모형 · 학습 시각도 처음 것).
- **남의 모형과 없는 모형은 같은 답이다** — 있는지를 알려 주지 않는다(D3 사용자별 · 남의 모형으로 지은 규칙은 남의 시행을 빌린 것이 된다).
- **읽거나 쓰지 못하면 `None`** — 빈 목록 · 없음과 다르다. 몸통이 깨져 읽히지 않는 줄도 '없음'이 아니라 '모른다'다.
- ★지우는 길이 없다★ — T2 의 규칙이 이 열쇠로 모형을 가리킨다. 지우면 지난 시행이 무엇을 조건으로 썼는지 설명할 수 없다
  (보존 분류 ③ 결정 기록 · `src/data/retention.py`).
- 합성값을 만들지 않는다 — 적힌 것만 돌려준다. 운영 게이트에서 합성(E0) 모형을 내줄지는 문 층이 정한다(등급 칸을 함께 돌려준다).

`intraday_trials` 와 같은 방어적 raw-SQL 관용구다(DB 는 선택적이고 실패하면 `None`). 새 표라 덧붙일 열이 없다 —
열이 늘 때 `schema_add_columns` 관용구를 쓴다.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "intraday_day_types"
#: 표를 만들어 둔 DB. 프로세스가 다른 DB 로 붙으면(시험 · 폴백) 그 DB 에도 표를 만든다.
_ready_for: str | None = None

REASONS = {
    "store_unavailable": "하루 유형 모형 저장소를 읽거나 쓰지 못했습니다(모형이 없는 것과 다릅니다).",
}

_HEAD = "model_key, grade, minutes, k, method, version, seed, tickers, first_day, last_day, samples, created_at"


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
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "username VARCHAR(60) NOT NULL, model_key VARCHAR(64) NOT NULL, grade VARCHAR(10), "
            "minutes INTEGER, k INTEGER, method VARCHAR(20), version INTEGER, seed INTEGER, "
            "tickers TEXT, first_day VARCHAR(10), last_day VARCHAR(10), samples INTEGER, body TEXT, "
            "created_at DOUBLE PRECISION, PRIMARY KEY (username, model_key))"))
        c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_idt_user ON {_TABLE} (username, created_at)"))
    _ready_for = url


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(r) -> dict[str, Any]:
    return {"key": r[0], "grade": r[1], "minutes": int(r[2]), "k": int(r[3]), "method": r[4], "version": int(r[5]),
            "seed": int(r[6]), "tickers": json.loads(r[7]) if r[7] else [], "first_day": r[8], "last_day": r[9],
            "samples": int(r[10]), "created_at": float(r[11])}


def _read(c, user: str, key: str) -> dict[str, Any] | None:
    """한 줄 → 몸통까지. 없으면 `{found: False}`. 몸통이 읽히지 않으면 예외(부르는 쪽이 '모른다'로 올린다)."""
    from sqlalchemy import text
    r = c.execute(text(f"SELECT {_HEAD}, body FROM {_TABLE} WHERE username = :user AND model_key = :key"),
                  {"user": user, "key": key}).fetchone()
    if r is None:
        return {"found": False}
    return {"found": True, **_row(r), "body": json.loads(r[12])}


def save(user: str, *, key: str, grade: str, minutes: int, k: int, method: str, version: int, seed: int,
         tickers: list[str], first_day: str, last_day: str, samples: int, body: dict) -> dict[str, Any] | None:
    """모형 하나를 남긴다 → `{created, model}`. 같은 주인 · 같은 열쇠가 있으면 쓰지 않고 그 줄(`created: False`). 실패하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        row = {"user": user, "key": key, "grade": grade, "minutes": int(minutes), "k": int(k), "method": method,
               "version": int(version), "seed": int(seed), "tickers": _canonical(list(tickers)), "first_day": first_day,
               "last_day": last_day, "samples": int(samples), "body": _canonical(body), "now": time.time()}
        with engine.begin() as c:
            known = _read(c, user, key)
            if known["found"]:
                return {"created": False, "model": known}
        try:
            with engine.begin() as c:
                c.execute(text(
                    f"INSERT INTO {_TABLE} (username, model_key, grade, minutes, k, method, version, seed, tickers, "
                    "first_day, last_day, samples, body, created_at) VALUES (:user, :key, :grade, :minutes, :k, :method, "
                    ":version, :seed, :tickers, :first_day, :last_day, :samples, :body, :now)"), row)
            created = True
        except IntegrityError:                                  # 같은 열쇠가 그 사이에 먼저 들어왔다 — 그 줄을 돌려준다
            created = False
        with engine.connect() as c:
            return {"created": created, "model": _read(c, user, key)}
    except Exception as err:                                    # noqa: BLE001 — DB 는 선택적이다. 실패는 '모른다'로 올린다
        logger.warning("하루 유형 모형 저장 실패: %s", err)
        return None


def models_of(user: str, limit: int = 50) -> list[dict[str, Any]] | None:
    """내 모형들(최신 순 · 몸통 없이). 읽지 못하면 `None` — 빈 목록과 다르다. 남의 모형은 오지 않는다."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rows = c.execute(text(f"SELECT {_HEAD} FROM {_TABLE} WHERE username = :user "
                                  "ORDER BY created_at DESC, model_key LIMIT :limit"),
                             {"user": user, "limit": int(limit)}).fetchall()
        return [_row(r) for r in rows]
    except Exception as err:                                    # noqa: BLE001
        logger.warning("하루 유형 모형 목록 읽기 실패: %s", err)
        return None


def model_of(user: str, key: str) -> dict[str, Any] | None:
    """내 모형 하나 → `{found: True, …, body}` · 없거나 남의 것이면 `{found: False}` · 읽지 못하면 `None`."""
    try:
        engine = _engine()
        _ensure(engine)
        with engine.connect() as c:
            return _read(c, user, key)
    except Exception as err:                                    # noqa: BLE001 — 몸통이 깨진 줄도 여기로(없음이 아니다)
        logger.warning("하루 유형 모형 읽기 실패: %s", err)
        return None
