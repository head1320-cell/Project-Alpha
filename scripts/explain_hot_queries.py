#!/usr/bin/env python3
"""`daily_prices` 의 뜨거운 쿼리를 ★재본다★ — 관측만, 추론 금지
==============================================================================
문서: `docs/specs/DATA_PLATFORM_SPEC.md` §7-1

## 왜 이 스크립트가 있나

`daily_prices` 를 비롯한 핵심 데이터 테이블에는 **PK 외 보조 인덱스가 없다.**
소스를 읽어 쿼리 형태를 분류한 결과는 이렇다:

  · 지배적 경로(`WHERE ticker=…`)는 PK `(ticker, trade_date)` 의 **prefix** 라
    인덱스가 필요 없다. `mktcap_asof` 는 종목마다 불리지만 이 형태다.
  · `universe_select.tickers_asof` / `top_mktcap_asof` 의 넷은 **ticker 술어가
    없다** → PK 선두 컬럼이 안 걸린다 → 풀스캔. 다만 **요청당 1회**다
    (봉당·종목당이 아니다).

★거기서 멈췄다★ — 분류는 소스로 할 수 있지만 **실제 비용은 DB 앞에서만** 알 수
있고, 개발 컨테이너에는 DB 가 없다. 그래서 결론(인덱스를 만들지 말지)을 내리는
대신, **한 명령으로 재게** 만들어 둔다.

## 무엇을 보고 무엇을 보지 않나

이 스크립트는 실행계획과 1회 실측 시간을 **그대로 찍는다.** 임계값을 두지 않고
"느리다/빠르다" 를 판정하지 않는다 — 무엇이 느린지는 이 데이터와 이 하드웨어
앞에서 사람이 본다. `Seq Scan`(PG) / `SCAN`(SQLite) 이 보이면 그 쿼리는 인덱스를
안 쓴 것이고, 그것이 **문제인지 아닌지**는 행 수와 호출 빈도가 정한다.

★1회 측정은 1회 측정이다★ — 캐시 워밍·동시 부하를 통제하지 않았다.

## 사용

    python -m scripts.explain_hot_queries            # 실 DB (DATABASE_URL / 폴백)
    python -m scripts.explain_hot_queries --selftest # 임시 SQLite 로 스크립트 자체 검증
"""
from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

TABLE = "daily_prices"

#: `(이름, SQL, 파라미터, 출처, 기대)` — ★출처를 적는다★ 소스가 바뀌면 여기도 낡는다.
PROBES = [
    ("tickers_asof ①  기준일 찾기",
     f"SELECT MAX(trade_date) FROM {TABLE} WHERE trade_date <= :d",
     {"d": "2024-06-28"}, "universe_select.tickers_asof", "ticker 술어 없음 → 스캔"),
    ("tickers_asof ②  그날 거래 종목",
     f"SELECT ticker FROM {TABLE} WHERE trade_date = :d",
     {"d": "2024-06-28"}, "universe_select.tickers_asof", "ticker 술어 없음 → 스캔"),
    ("top_mktcap_asof ①  기준일",
     f"SELECT MAX(trade_date) FROM {TABLE} WHERE trade_date <= :d AND mktcap IS NOT NULL",
     {"d": "2024-06-28"}, "universe_select.top_mktcap_asof", "ticker 술어 없음 → 스캔"),
    ("top_mktcap_asof ②  시총 상위",
     f"SELECT ticker FROM {TABLE} WHERE trade_date = :d AND mktcap IS NOT NULL "
     "ORDER BY mktcap DESC LIMIT 200",
     {"d": "2024-06-28"}, "universe_select.top_mktcap_asof", "ticker 술어 없음 → 스캔"),
    # ── 대조군 — ★PK 로 덮이는 지배적 경로★ 둘을 나란히 재야 비교가 된다 ──
    ("mktcap_asof  (대조군)",
     f"SELECT mktcap FROM {TABLE} WHERE ticker=:t AND trade_date <= :d "
     "AND mktcap IS NOT NULL ORDER BY trade_date DESC LIMIT 1",
     {"t": "005930", "d": "2024-06-28"}, "universe_select.mktcap_asof", "PK prefix → 인덱스"),
    ("종목 시계열  (대조군)",
     f"SELECT trade_date, close FROM {TABLE} WHERE ticker=:t "
     "AND trade_date BETWEEN :s AND :e ORDER BY trade_date ASC",
     {"t": "005930", "s": "2023-01-01", "e": "2024-12-31"}, "ohlcv_loader",
     "PK prefix → 인덱스"),
]


def _explain_prefix(dialect: str) -> str | None:
    if dialect.startswith("postgres"):
        return "EXPLAIN ANALYZE "
    if dialect.startswith("sqlite"):
        return "EXPLAIN QUERY PLAN "
    return None          # ★모르는 방언이면 지어내지 않는다★


def _row_count(conn, text) -> int | None:
    try:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar() or 0)
    except Exception as e:  # noqa: BLE001
        print(f"  행 수를 세지 못했습니다: {type(e).__name__}: {e}")
        return None


def run(engine) -> int:
    from sqlalchemy import text

    dialect = engine.dialect.name
    prefix = _explain_prefix(dialect)
    print(f"엔진: {dialect}   ({engine.url.render_as_string(hide_password=True)})")
    if prefix is None:
        print(f"★{dialect} 의 EXPLAIN 문법을 모릅니다 — 계획 없이 시간만 잽니다.★")

    with engine.connect() as conn:
        n = _row_count(conn, text)
        print(f"{TABLE} 행 수: {n if n is not None else '미상'}\n")
        if not n:
            print("★행이 없습니다 — 이 측정은 아무것도 말해 주지 않습니다.★")

        for name, sql, params, origin, expect in PROBES:
            print(f"── {name}   ({origin})")
            print(f"   기대: {expect}")
            if prefix:
                try:
                    plan = conn.execute(text(prefix + sql), params).fetchall()
                    for row in plan:
                        print("   | " + " ".join(str(c) for c in row if c is not None))
                except Exception as e:  # noqa: BLE001
                    print(f"   계획을 얻지 못했습니다: {type(e).__name__}: {e}")
            try:
                t0 = time.perf_counter()
                rows = conn.execute(text(sql), params).fetchall()
                dt = (time.perf_counter() - t0) * 1000
                print(f"   실측: {dt:.1f} ms · {len(rows)} 행  (★1회 측정★)")
            except Exception as e:  # noqa: BLE001
                print(f"   실행 실패: {type(e).__name__}: {e}")
            print()

    print("★판정하지 않습니다★ — `Seq Scan`/`SCAN` 이 보이면 인덱스를 안 쓴 것이고,")
    print("그것이 문제인지는 위 행 수와 **호출 빈도**(요청당 1회인지)가 정합니다.")
    return 0


def _selftest() -> int:
    """★스크립트 자체가 도는지 본다★ — 임시 SQLite + 합성 행.

    개발 컨테이너에 DB 가 없어 실 측정을 못 하므로, 최소한 **안 돌아가는 스크립트를
    남기지는 않는다.** 여기서 나오는 숫자는 합성 데이터의 것이라 **성능에 대해
    아무것도 말하지 않는다.**
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    from src.data.krx_ingest import ensure_table
    ensure_table(eng)
    with eng.begin() as c:
        for i in range(200):
            c.execute(text(
                f"INSERT INTO {TABLE} (ticker, trade_date, close, mktcap) "
                "VALUES (:t, :d, :c, :m)"),
                {"t": f"{i:06d}", "d": "2024-06-28", "c": 1000.0 + i, "m": 1e10 + i})
    print("★셀프테스트 — 합성 SQLite★ 숫자는 성능을 말하지 않습니다.\n")
    return run(eng)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="임시 SQLite 로 스크립트 자체를 검증(실 DB 불필요)")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    from src.database import get_engine
    engine = get_engine()
    if engine is None:
        print("DB 엔진이 없습니다 — `DATABASE_URL` 을 확인하세요.")
        return 1
    return run(engine)


if __name__ == "__main__":
    sys.exit(main())
