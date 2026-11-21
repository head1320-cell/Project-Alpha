"""하루 유형 센 값의 저장소 — (주인, 모형, 날, 종목)마다 그날 장 시작 구간의 유형 또는 세지 못한 사유 (설계 2026-11-17 §6 · 구현 계획 §7.6 · K5).

시장 국면에 하루 유형 비중을 더하려면 약 1,060거래일 × 바구니 종목을 세야 한다 — 한 요청의 상한(시간 · 바이트)에 들지 않아
★나눠 세어 여기에 남긴다★(세는 것은 명시적 쓰기 문 하나뿐 · 국면을 내는 문은 읽기만 한다).

- **한 줄** = 주인 · 모형 열쇠 · 날 · 종목 → 유형 번호(1 ~ k) 또는 NULL + 사유 코드 · 쓴 봉의 출처 · 서명 · 센 시각.
  ★주인이 열쇠에 든다★ — 모형은 주인마다다(`intraday_day_types` 의 PK 가 (주인, 열쇠)). 남의 센 값은 오지 않는다.
- **서명**(`day_sig`) = 이 저장소의 판 · 하루 유형의 판 · 그날 일파일의 꼴 · 크기 · 고친 시각(ns) · 정규장 시각 · mock 게이트.
  읽는 쪽이 지금 서명과 다른 줄을 '낡음'으로 보고 쓰지 않는다(봉 · 장 시각 · 게이트 · 셈의 뜻이 바뀌면 같은 날도 다른 값이 될 수 있다).
  ★서명은 일파일의 사본 상태를 말할 뿐 내용을 해시하지 않는다★ — 같은 크기 · 같은 고친 시각으로 내용만 바꾸면 알지 못한다(한계 · 문서에 적음).
- **같은 (주인, 모형, 날, 종목)을 다시 적으면 그 줄이 바뀐다**(다시 센 값 — 서명이 따라간다).
- ★운영 게이트에서는 출처가 합성인 줄을 돌려주지 않는다★ — 게이트가 서명에 들어 있어 운영에서는 mock 에서 센 줄이 이미 낡음이지만,
  로더를 지나 합성 봉이 세어진 줄이 생겨도(결함) 운영의 답에 섞이지 않게 한 번 더 막는다. mock 은 그대로(등급 E0 은 읽는 쪽이 매긴다).
- **읽거나 쓰지 못하면 `None`** — 빈 값(`{}`)과 다르다. 어긋난 줄(유형과 사유가 함께 · 둘 다 없음 · 모르는 출처)은 쓰지 않고 `ValueError`.
- ★지우는 길이 없다★ — 보존 ④ 재생성 가능(일파일과 모형으로 다시 센다 · `src/data/retention.py`). 합성값을 만들지 않는다 — 센 것만 적는다.

`intraday_day_types` 와 같은 방어적 raw-SQL 관용구다(DB 는 선택적이고 실패하면 `None`). 덮어쓰기는 `macro_observation_store` 와 같은
`ON CONFLICT … DO UPDATE` 다(SQLite · PostgreSQL 둘 다).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

import src.data.minute_bars as minute_bars
from src.data.mock_gate import mock_allowed
from src.engine.intraday import day_types

logger = logging.getLogger(__name__)

_TABLE = "intraday_day_type_counts"
#: 이 저장소의 판 — 센 값의 뜻(사유 코드 · 한 줄의 모양)이 바뀌면 올린다. 서명에 들어가 옛 줄을 낡음으로 만든다.
VERSION = 1
#: 표를 만들어 둔 DB. 프로세스가 다른 DB 로 붙으면(시험 · 폴백) 그 DB 에도 표를 만든다.
_ready_for: str | None = None

REASONS = {
    "store_unavailable": "하루 유형 센 값 저장소를 읽거나 쓰지 못했습니다(세지 않았다는 뜻이 아닙니다).",
}
#: 한 줄의 출처 — 세션의 출처 그대로(`minute_feed`). 유형이 없는 줄은 출처가 없다.
SOURCES = ("kis", "synthetic", "unknown")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")

_UPSERT = (
    f"INSERT INTO {_TABLE} (username, model_key, day, ticker, label, reason, source, sig, counted_at) "
    "VALUES (:user, :key, :day, :ticker, :label, :reason, :source, :sig, :now) "
    "ON CONFLICT (username, model_key, day, ticker) DO UPDATE SET "
    "label=EXCLUDED.label, reason=EXCLUDED.reason, source=EXCLUDED.source, sig=EXCLUDED.sig, counted_at=EXCLUDED.counted_at"
)


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
            "username VARCHAR(60) NOT NULL, model_key VARCHAR(64) NOT NULL, day VARCHAR(10) NOT NULL, "
            "ticker VARCHAR(20) NOT NULL, label INTEGER, reason VARCHAR(40), source VARCHAR(12), sig VARCHAR(200) NOT NULL, "
            "counted_at DOUBLE PRECISION, PRIMARY KEY (username, model_key, day, ticker))"))
    _ready_for = url


def day_sig(day: str, rules: Mapping[str, Any]) -> str:
    """그날 센 값이 기대는 것의 서명 — 판 둘 · 일파일(꼴 · 크기 · 고친 시각 ns 또는 `none`) · 정규장 시각 · 게이트. ★파일을 읽지 않는다★(stat 만)."""
    path = minute_bars._existing_day_path(day)
    if path is None:
        file_part = "none"
    else:
        try:
            st = path.stat()
            file_part = f"{path.name[len(day):]}:{st.st_size}:{st.st_mtime_ns}"
        except OSError:                                          # 있다고 본 파일이 사라졌다 — 다음 세기에서 다시 본다
            file_part = "stat_failed"
    session = f"{rules.get('open')}-{rules.get('close')}" if rules.get("available") else "no_rules"
    gate = "mock" if mock_allowed() else "prod"
    return f"c{VERSION}|t{day_types.VERSION}|{file_part}|{session}|{gate}"


def _checked(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """한 줄은 유형(1 이상의 정수 · 출처 있음)과 사유(비지 않은 글 · 출처 없음) 가운데 꼭 하나 — 어긋나면 `ValueError`."""
    out = []
    for r in rows:
        ticker, label, reason, source = r.get("ticker"), r.get("label"), r.get("reason"), r.get("source")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(f"종목이 비었습니다: {r!r}")
        if label is not None:
            if reason is not None or isinstance(label, bool) or not isinstance(label, int) or label < 1:
                raise ValueError(f"유형이 있는 줄은 1 이상의 정수 유형만 가집니다: {r!r}")
            if source not in SOURCES:
                raise ValueError(f"모르는 출처입니다: {r!r}")
        elif not isinstance(reason, str) or not reason or source is not None:
            raise ValueError(f"유형이 없는 줄은 사유만 가집니다: {r!r}")
        out.append({"ticker": ticker.strip(), "label": label, "reason": reason, "source": source})
    return out


def put(user: str, model_key: str, day: str, rows: Sequence[Mapping[str, Any]], sig: str) -> int | None:
    """그날 센 줄들을 남긴다(같은 종목은 바꾼다) → 적은 줄 수. 어긋난 줄이 하나라도 있으면 아무것도 쓰지 않고 `ValueError` · DB 실패는 `None`."""
    if not _DAY.fullmatch(str(day)):
        raise ValueError(f"날짜는 YYYY-MM-DD 입니다: {day!r}")
    checked = _checked(rows)
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        now = time.time()
        params = [{"user": user, "key": model_key, "day": day, "sig": sig, "now": now, **r} for r in checked]
        with engine.begin() as c:
            if params:
                c.execute(text(_UPSERT), params)
        return len(params)
    except Exception as err:                                    # noqa: BLE001 — DB 는 선택적이다. 실패는 '모른다'로 올린다
        logger.warning("하루 유형 센 값 쓰기 실패: %s", err)
        return None


def get(user: str, model_key: str, first_day: str, last_day: str) -> dict[tuple[str, str], dict[str, Any]] | None:
    """[first_day, last_day] 안의 내 센 줄들 → {(날, 종목): {label, reason, source, sig, counted_at}}. 없으면 `{}` · 읽지 못하면 `None`.

    운영 게이트에서는 출처가 합성인 줄을 빼고 돌려준다(읽는 쪽에는 세지 않은 것으로 보인다 → 다시 세면 로더가 막는다)."""
    try:
        engine = _engine()
        _ensure(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            rs = c.execute(text(
                f"SELECT day, ticker, label, reason, source, sig, counted_at FROM {_TABLE} "
                "WHERE username = :user AND model_key = :key AND day >= :first AND day <= :last"),
                {"user": user, "key": model_key, "first": first_day, "last": last_day}).fetchall()
    except Exception as err:                                    # noqa: BLE001
        logger.warning("하루 유형 센 값 읽기 실패: %s", err)
        return None
    hide_synthetic = not mock_allowed()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for day, ticker, label, reason, source, sig, counted_at in rs:
        if hide_synthetic and source == "synthetic":
            continue
        out[(str(day), str(ticker))] = {"label": None if label is None else int(label), "reason": reason, "source": source,
                                        "sig": sig, "counted_at": float(counted_at) if counted_at is not None else None}
    return out
