"""KIS 투자자별 수급 적재 → investor_flows (개인/외국인/기관 일별 순매수)
==========================================================================
KIS 종목별 투자자 TR(FHKST01010900)은 **최근 ~30영업일만** 반환한다.
→ 깊은 과거 백필은 불가 — 매일(또는 주기적으로) 실행해 누적하는 구조.
적재된 기간만 수급 토큰(외국인순매수량 등)이 평가되고, 그 외 봉은 건너뜀.

실행 (사용자 환경, KIS 실키 + KIS_USE_MOCK=0):
    python -m src.data.kis_flows --all-listed        # 마스터 전 주권 (~2,700콜 ≈ 3분)
    python -m src.data.kis_flows --tickers 005930,000660
금액 단위: KIS 응답(pbmn) 그대로 저장 — verify_connection 【7】 샘플로 단위 확인.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_CHUNK = 500

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS investor_flows (
    ticker        VARCHAR(12) NOT NULL,
    trade_date    DATE        NOT NULL,
    prsn_qty      FLOAT,
    frgn_qty      FLOAT,
    orgn_qty      FLOAT,
    prsn_amt      FLOAT,
    frgn_amt      FLOAT,
    orgn_amt      FLOAT,
    pension_qty   FLOAT,
    pension_amt   FLOAT,
    trust_qty     FLOAT,
    trust_amt     FLOAT,
    pe_qty        FLOAT,
    pe_amt        FLOAT,
    othercorp_qty FLOAT,
    othercorp_amt FLOAT,
    PRIMARY KEY (ticker, trade_date)
)
"""

# 세부 주체(연기금/투신/사모/기타법인)는 KRX MDC 백필(krx_mdc)만 제공 — 마이그레이션 대상
_MIGRATE_COLUMNS = ("pension_qty FLOAT", "pension_amt FLOAT", "trust_qty FLOAT",
                    "trust_amt FLOAT", "pe_qty FLOAT", "pe_amt FLOAT",
                    "othercorp_qty FLOAT", "othercorp_amt FLOAT")

# KIS 일별 적재용 — 3주체 컬럼만 갱신 (KRX 백필이 채운 세부 주체를 NULL로 덮지 않음)
_UPSERT = """
INSERT INTO investor_flows
    (ticker, trade_date, prsn_qty, frgn_qty, orgn_qty, prsn_amt, frgn_amt, orgn_amt)
VALUES
    (:ticker, :trade_date, :prsn_qty, :frgn_qty, :orgn_qty, :prsn_amt, :frgn_amt, :orgn_amt)
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    prsn_qty=EXCLUDED.prsn_qty, frgn_qty=EXCLUDED.frgn_qty, orgn_qty=EXCLUDED.orgn_qty,
    prsn_amt=EXCLUDED.prsn_amt, frgn_amt=EXCLUDED.frgn_amt, orgn_amt=EXCLUDED.orgn_amt
"""

# KRX MDC 백필용 — 전 컬럼 갱신
_UPSERT_FULL = """
INSERT INTO investor_flows
    (ticker, trade_date, prsn_qty, frgn_qty, orgn_qty, prsn_amt, frgn_amt, orgn_amt,
     pension_qty, pension_amt, trust_qty, trust_amt, pe_qty, pe_amt,
     othercorp_qty, othercorp_amt)
VALUES
    (:ticker, :trade_date, :prsn_qty, :frgn_qty, :orgn_qty, :prsn_amt, :frgn_amt, :orgn_amt,
     :pension_qty, :pension_amt, :trust_qty, :trust_amt, :pe_qty, :pe_amt,
     :othercorp_qty, :othercorp_amt)
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    prsn_qty=EXCLUDED.prsn_qty, frgn_qty=EXCLUDED.frgn_qty, orgn_qty=EXCLUDED.orgn_qty,
    prsn_amt=EXCLUDED.prsn_amt, frgn_amt=EXCLUDED.frgn_amt, orgn_amt=EXCLUDED.orgn_amt,
    pension_qty=EXCLUDED.pension_qty, pension_amt=EXCLUDED.pension_amt,
    trust_qty=EXCLUDED.trust_qty, trust_amt=EXCLUDED.trust_amt,
    pe_qty=EXCLUDED.pe_qty, pe_amt=EXCLUDED.pe_amt,
    othercorp_qty=EXCLUDED.othercorp_qty, othercorp_amt=EXCLUDED.othercorp_amt
"""

FLOW_FIELDS = ("prsn_qty", "frgn_qty", "orgn_qty", "prsn_amt", "frgn_amt", "orgn_amt",
               "pension_qty", "pension_amt", "trust_qty", "trust_amt",
               "pe_qty", "pe_amt", "othercorp_qty", "othercorp_amt")

# 토큰 해석용 시리즈 캐시 — {(ticker, field): Series}
_series_cache: dict[tuple[str, str], pd.Series | None] = {}


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from src.database import get_engine
    return get_engine()


def ensure_flows_table(engine) -> None:
    """테이블 생성 + 세부 주체 컬럼 마이그레이션 (ALTER 멱등 — 이미 있음 무시)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    for col in _MIGRATE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE investor_flows ADD COLUMN {col}"))
        except Exception:
            pass


def bulk_upsert_flows(engine, ticker: str, rows: list[dict], full: bool = False) -> int:
    """정규화 행 UPSERT. full=True(KRX 백필)면 세부 주체 컬럼까지 갱신,
    False(KIS 일별)면 3주체만 — KRX가 채운 세부 주체를 덮지 않는다."""
    if not rows:
        return 0
    from sqlalchemy import text
    fields = FLOW_FIELDS if full else FLOW_FIELDS[:6]
    payload = [{"ticker": ticker, "trade_date": r["date"],
                **{f: r.get(f) for f in fields}} for r in rows]
    stmt = text(_UPSERT_FULL if full else _UPSERT)
    with engine.begin() as conn:
        for i in range(0, len(payload), _CHUNK):
            conn.execute(stmt, payload[i:i + _CHUNK])
    return len(payload)


def sync_investor_flows(tickers: list[str] | None = None, all_listed: bool = False,
                        engine=None, client=None) -> dict:
    """종목 루프로 최근 ~30영업일 수급을 적재 (일배치 — 누적용).

    KIS_USE_MOCK=1 또는 MockKISClient면 실데이터가 없으므로 안내 후 종료."""
    import os
    if client is None:
        from src.execution.kis_client import get_kis_client
        client = get_kis_client()
    if os.getenv("KIS_USE_MOCK", "1") == "1" or type(client).__name__ == "MockKISClient":
        return {"error": True,
                "message": "KIS mock 모드 — 수급 적재는 실키 필요 (KIS_USE_MOCK=0)"}

    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_flows_table(engine)

    if tickers is None:
        if all_listed:
            from src.data_sync import _all_listed_tickers
            tickers = _all_listed_tickers()
        if not tickers:
            from src.data_sync import SEED_TICKERS
            tickers = [t[0] for t in SEED_TICKERS]

    stats = {"tickers": len(tickers), "loaded": 0, "rows": 0, "errors": 0}
    for tk in tickers:
        try:
            rows = client.get_investor_daily(tk)
            if hasattr(client, "throttle"):
                client.throttle()
            if not rows:
                continue
            stats["rows"] += bulk_upsert_flows(engine, tk, rows)
            stats["loaded"] += 1
            if stats["loaded"] % 100 == 0:
                logger.info(f"수급 적재 진행: {stats['loaded']}/{len(tickers)}종목 {stats['rows']:,}행")
        except Exception as e:
            stats["errors"] += 1
            logger.debug(f"수급 적재 실패 [{tk}]: {e}")
    _series_cache.clear()  # 새 데이터 반영
    return stats


def load_flows_series(ticker: str, field: str, engine=None) -> pd.Series | None:
    """수급 토큰 해석용 — investor_flows에서 (ticker, field) 시계열 (캐시)."""
    key = (str(ticker), field)
    if key in _series_cache:
        return _series_cache[key]
    s = None
    try:
        from sqlalchemy import text
        engine = _get_engine(engine)
        if engine is not None and field in FLOW_FIELDS:
            with engine.connect() as conn:
                rows = conn.execute(text(
                    f"SELECT trade_date, {field} FROM investor_flows "  # noqa: S608 — 필드 화이트리스트
                    "WHERE ticker=:t ORDER BY trade_date ASC"), {"t": str(ticker)}).fetchall()
            if rows:
                idx = pd.DatetimeIndex([pd.Timestamp(str(r[0])[:10]) for r in rows])
                s = pd.Series([float(r[1]) if r[1] is not None else float("nan") for r in rows],
                              index=idx)
    except Exception:
        s = None
    _series_cache[key] = s
    return s


def flows_status(engine=None) -> dict:
    """investor_flows 적재 현황 — 행수/종목수/날짜범위/세부주체 보유. 테이블 없으면 0(정직)."""
    out = {"rows": 0, "tickers": 0, "min_date": None, "max_date": None, "has_detail": False}
    engine = _get_engine(engine)
    if engine is None:
        return out
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(trade_date), MAX(trade_date), "
                "COUNT(pension_qty) FROM investor_flows")).fetchone()
        if row:
            out["rows"] = int(row[0] or 0)
            out["tickers"] = int(row[1] or 0)
            out["min_date"] = str(row[2])[:10] if row[2] else None
            out["max_date"] = str(row[3])[:10] if row[3] else None
            out["has_detail"] = int(row[4] or 0) > 0
    except Exception:
        pass
    return out


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="KIS 투자자별 수급 적재 (최근 ~30영업일 누적)")
    ap.add_argument("--tickers", default=None, help="쉼표 구분 종목코드 (기본 SEED)")
    ap.add_argument("--all-listed", action="store_true", help="마스터 전 주권 대상")
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    print(f"수급 적재 결과: {sync_investor_flows(tickers=tickers, all_listed=args.all_listed)}")


if __name__ == "__main__":
    main()
