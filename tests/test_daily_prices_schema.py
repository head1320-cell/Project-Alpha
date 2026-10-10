"""`daily_prices` 스키마가 ★생성 순서와 무관★ 해야 한다 (H1)

## 무엇이 문제였나

이 테이블을 선언하는 곳이 **둘**이다:

  · `data/krx_ingest.py` 의 raw DDL — `mktcap`·`list_shares`·`source`·`price_basis`
    를 포함하고, **인덱스는 안 만든다**
  · `kis_models.py::DailyPrice` 의 SQLAlchemy 모델 — 그 넷이 **없고**,
    대신 `Index("ix_daily_date", "trade_date")` 를 선언한다

그리고 기동 시 `startup/lifecycle.py` 가 `init_async_db()`(→ `create_all`)를
**먼저** 부르고 KRX 백필 데몬을 **나중에** 띄운다. 그런데 사용자가 CLI 백필
(`python -m src.data.krx_ingest`)로 DB 를 먼저 만들 수도 있다. 그러면:

    create_all 먼저   → 인덱스 있음   + 컬럼은 ALTER 가 채운다
    ensure_table 먼저 → ★인덱스 없음★ + 컬럼은 ALTER 가 채운다

`create_all(checkfirst=True)` 는 **이미 있는 테이블을 통째로 건너뛴다** — 그
테이블의 인덱스도 만들지 않는다. 컬럼은 `_MIGRATE_COLUMNS` 의 `ALTER` 가 양쪽 다
치유하지만 **인덱스는 치유되지 않았다.**

⇒ ★같은 제품의 두 DB 가 성능 특성이 다르고, 코드만 봐서는 어느 쪽인지 알 수 없다.★

## 이 파일이 거는 계약

★순서와 무관하게 같은 스키마★ — 그것뿐이다. "인덱스가 몇 개냐" 를 고정하지 않고
**두 경로가 일치하는가**를 본다. 늘리든 줄이든 한쪽만 바뀌면 여기서 걸린다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.kis_models  # noqa: E402,F401 — AsyncBase.metadata 에 등록되는 부작용
from src.data.krx_ingest import ensure_table  # noqa: E402
from src.database_async import AsyncBase  # noqa: E402

TABLE = "daily_prices"

#: raw DDL 에만 있고 모델에는 없는 컬럼 — `_MIGRATE_COLUMNS` 가 채워야 한다.
DDL_ONLY_COLUMNS = {"mktcap", "list_shares", "source", "price_basis"}


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)


def _create_all(eng):
    AsyncBase.metadata.create_all(eng)


def _schema(eng) -> tuple[dict[str, list[str]], set[str]]:
    """`({인덱스명: 컬럼}, 컬럼집합)`"""
    insp = inspect(eng)
    idx = {i["name"]: list(i["column_names"]) for i in insp.get_indexes(TABLE)}
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    return idx, cols


def _built(*steps) -> tuple[dict[str, list[str]], set[str]]:
    eng = _engine()
    try:
        for step in steps:
            step(eng)
        return _schema(eng)
    finally:
        eng.dispose()


# ═══════════════════════════════════════════════════════════════════════════════
# ① ★알맹이★ — 순서가 결과를 바꾸지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_schema_does_not_depend_on_creation_order():
    """★두 경로가 같은 스키마를 낸다★

    실제 기동은 `create_all` 먼저지만, CLI 백필로 DB 를 먼저 만드는 것도 문서가
    안내하는 정상 경로다. 둘이 갈리면 **어느 DB 인지에 따라 성능이 다르고**
    코드만 봐서는 알 수 없다.
    """
    a_idx, a_cols = _built(_create_all, ensure_table)
    b_idx, b_cols = _built(ensure_table, _create_all)
    assert a_idx == b_idx, (
        f"생성 순서에 따라 인덱스가 다르다\n  create_all 먼저: {a_idx}\n"
        f"  ensure_table 먼저: {b_idx}")
    assert a_cols == b_cols, f"생성 순서에 따라 컬럼이 다르다\n  {a_cols ^ b_cols}"


def test_both_orders_carry_the_ddl_only_columns():
    """★짝★ 컬럼 마이그레이션이 죽으면 안 된다 — 지금도 참이고, 회귀를 막는다.

    모델에는 이 넷이 없다. `_MIGRATE_COLUMNS` 의 `ALTER` 가 양쪽 순서 모두에서
    되붙이는 것이 지금 동작이 맞는 이유다.
    """
    for label, steps in (("create_all 먼저", (_create_all, ensure_table)),
                         ("ensure_table 먼저", (ensure_table, _create_all))):
        _, cols = _built(*steps)
        assert DDL_ONLY_COLUMNS <= cols, f"{label}: 빠진 컬럼 {sorted(DDL_ONLY_COLUMNS - cols)}"


# ═══════════════════════════════════════════════════════════════════════════════
# ② 인덱스가 **무엇을** 거는가 — 이름만 맞는 인덱스를 배제한다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_cross_sectional_index_covers_trade_date():
    """★PK 로 답할 수 없는 유일한 축★

    `universe_select.tickers_asof`/`top_mktcap_asof` 는 ticker 술어가 없어
    PK `(ticker, trade_date)` 의 선두 컬럼이 안 걸린다. 그 축이 `trade_date` 다.
    """
    idx, _ = _built(ensure_table)
    assert "ix_daily_date" in idx, f"횡단면 인덱스가 없다: {idx}"
    assert idx["ix_daily_date"] == ["trade_date"], (
        f"이름은 맞는데 다른 컬럼을 건다: {idx['ix_daily_date']}")


def test_the_model_does_not_duplicate_the_primary_key():
    """PK 와 같은 `(ticker, trade_date)` 인덱스는 **쓰기 비용만** 낸다.

    ★기존 DB 의 것을 지우지는 않는다★ — 저장소에 인덱스 삭제 마이그레이션 선례가
    없다. 새 DB 에 더 만들지 않을 뿐이다.
    """
    idx, _ = _built(_create_all)
    dupes = [n for n, cols in idx.items() if cols == ["ticker", "trade_date"]]
    assert not dupes, f"PK 와 중복인 인덱스를 선언하고 있다: {dupes}"


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 멱등 — 기동마다 불린다
# ═══════════════════════════════════════════════════════════════════════════════

def test_ensure_table_is_idempotent_and_quiet(caplog):
    """데몬이 재시작마다 부른다 — 두 번째 호출이 터지면 적재가 멈춘다.

    ★"터지지 않는다" 로는 부족하다★ 아래 `except` 가 실패를 경고로 바꾸므로,
    `IF NOT EXISTS` 를 빼도 "안 터진다" 는 그대로 참이다(변이가 실제로 살아남았다).
    재호출은 **조용해야** 한다 — `IF NOT EXISTS` 는 "이미 있음은 오류가 아니다"
    라는 뜻이고, 그래야 경고가 **진짜 실패**만 가리킨다.
    """
    import logging

    eng = _engine()
    try:
        ensure_table(eng)                       # 1회차 — 여기서 만들어진다
        with caplog.at_level(logging.WARNING):
            ensure_table(eng)
            ensure_table(eng)                   # 2·3회차 — 아무 말도 없어야 한다
        noisy = [r.message for r in caplog.records if "인덱스" in r.message]
        assert not noisy, f"재호출이 인덱스 경고를 냈다 — 멱등이 아니다: {noisy}"
        idx, cols = _schema(eng)
        assert "ix_daily_date" in idx and DDL_ONLY_COLUMNS <= cols, (idx, cols)
    finally:
        eng.dispose()


def test_an_index_failure_is_not_swallowed_silently(monkeypatch, caplog):
    """★검증 없는 `except: pass` 를 되풀이하지 않는다★

    `schema_add_columns` 가 그 함정을 적어 뒀다 — 삼키면 "붙었다고 믿고" 이후
    조회가 통째로 깨진다. 인덱스 생성이 실패하면 **사유가 로그에 남아야** 한다.
    실패는 인덱스 DDL 만 터뜨려 주입한다(테이블 DDL·컬럼 ALTER 는 지나가야 한다).
    """
    import logging

    import src.data.krx_ingest as K

    def _boom(engine, sql):
        raise RuntimeError("의도적 인덱스 실패")

    monkeypatch.setattr(K, "_run_index_ddl", _boom)
    eng = _engine()
    try:
        with caplog.at_level(logging.WARNING):
            ensure_table(eng)          # ★터지지 않아야 한다 — 적재를 막으면 안 된다★
        _, cols = _schema(eng)
        assert DDL_ONLY_COLUMNS <= cols, "인덱스 실패가 컬럼 마이그레이션까지 막았다"
        assert any("인덱스" in r.message for r in caplog.records), (
            f"인덱스 생성 실패를 조용히 넘겼다 — 로그: {[r.message for r in caplog.records]}")
    finally:
        eng.dispose()
