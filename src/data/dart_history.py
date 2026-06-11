"""DART 재무 시계열 백필 → financials_history (PIT·성장/흑자전환 팩터의 원천)
==========================================================================
종목 × 과거 N년(연간 + 선택 분기)의 재무제표를 1회 적재해 두면:
  · PIT 스크리닝이 DB에서 즉시(쿼터 무소모·키 불필요) 동작
  · 분기/트레일링 구분, 흑자전환·3년연속류 파생 팩터의 기반 확보
  · [C] 시총 시계열과 결합 → 역사 PER/PBR 계산 가능

쿼터: DART 일 20,000건 — 전 주권(~2,700) × 10년 연간 = 27,000콜
→ `--max-calls 18000`으로 이틀 분할 (resume: 적재된 (종목,연도,보고서) 자동 skip).

실행 (사용자 환경, DART_API_KEY 필요):
    python -m src.data.dart_history --years 10 --all-listed --max-calls 18000
    python -m src.data.dart_history --years 5 --quarters --tickers 005930,000660
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS financials_history (
    ticker              VARCHAR(12) NOT NULL,
    bsns_year           VARCHAR(4)  NOT NULL,
    reprt_code          VARCHAR(5)  NOT NULL,
    revenue             FLOAT,
    operating_profit    FLOAT,
    net_income          FLOAT,
    gross_profit        FLOAT,
    total_assets        FLOAT,
    total_liabilities   FLOAT,
    total_equity        FLOAT,
    current_assets      FLOAT,
    current_liabilities FLOAT,
    operating_cf        FLOAT,
    capex               FLOAT,
    shares_outstanding  FLOAT,
    fetched_at          VARCHAR(32),
    PRIMARY KEY (ticker, bsns_year, reprt_code)
)
"""

_UPSERT = """
INSERT INTO financials_history
    (ticker, bsns_year, reprt_code, revenue, operating_profit, net_income, gross_profit,
     total_assets, total_liabilities, total_equity, current_assets, current_liabilities,
     operating_cf, capex, shares_outstanding, fetched_at)
VALUES
    (:ticker, :bsns_year, :reprt_code, :revenue, :operating_profit, :net_income, :gross_profit,
     :total_assets, :total_liabilities, :total_equity, :current_assets, :current_liabilities,
     :operating_cf, :capex, :shares_outstanding, :fetched_at)
ON CONFLICT (ticker, bsns_year, reprt_code) DO UPDATE SET
    revenue=EXCLUDED.revenue, operating_profit=EXCLUDED.operating_profit,
    net_income=EXCLUDED.net_income, gross_profit=EXCLUDED.gross_profit,
    total_assets=EXCLUDED.total_assets, total_liabilities=EXCLUDED.total_liabilities,
    total_equity=EXCLUDED.total_equity, current_assets=EXCLUDED.current_assets,
    current_liabilities=EXCLUDED.current_liabilities, operating_cf=EXCLUDED.operating_cf,
    capex=EXCLUDED.capex, shares_outstanding=EXCLUDED.shares_outstanding,
    fetched_at=EXCLUDED.fetched_at
"""

_FIELDS = ("revenue", "operating_profit", "net_income", "gross_profit",
           "total_assets", "total_liabilities", "total_equity",
           "current_assets", "current_liabilities", "operating_cf", "capex",
           "shares_outstanding")

REPRT_ANNUAL = "11011"
QUARTER_REPRTS = ("11013", "11012", "11014")  # 1Q, 반기, 3Q


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from src.database import get_engine
    return get_engine()


def ensure_history_table(engine) -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))


def upsert_statement(engine, ticker: str, fs) -> bool:
    """FinancialStatement 1건 UPSERT. 핵심 값이 전부 비면 저장하지 않음(False)."""
    row = {f: getattr(fs, f, None) for f in _FIELDS}
    if row["revenue"] is None and row["total_assets"] is None and row["net_income"] is None:
        return False
    from sqlalchemy import text
    row.update({
        "ticker": ticker, "bsns_year": str(fs.bsns_year), "reprt_code": str(fs.reprt_code),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    })
    with engine.begin() as conn:
        conn.execute(text(_UPSERT), row)
    return True


def existing_keys(engine) -> set[tuple]:
    """적재 완료 (ticker, year, reprt) 집합 — resume용."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, bsns_year, reprt_code FROM financials_history")).fetchall()
        return {(str(r[0]), str(r[1]), str(r[2])) for r in rows}
    except Exception:
        return set()


def backfill_financials(tickers: list[str] | None = None, all_listed: bool = False,
                        years: int = 10, include_quarters: bool = False,
                        max_calls: int | None = None,
                        engine=None, client=None) -> dict:
    """종목×연도(×분기) 재무 백필 — DART 일쿼터 대응 max_calls 분할 + resume."""
    from src.data.dart_client import DARTClient, get_corp_code
    client = client or DARTClient()
    if not client.is_configured:
        return {"error": True, "message": "DART_API_KEY 미설정 — .env에 키를 넣고 실행하세요"}

    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_history_table(engine)

    if tickers is None:
        if all_listed:
            from src.data_sync import _all_listed_tickers
            tickers = _all_listed_tickers()
        if not tickers:
            from src.data_sync import SEED_TICKERS
            tickers = [t[0] for t in SEED_TICKERS]

    last_year = datetime.now().year - 1
    year_list = [str(y) for y in range(last_year, last_year - years, -1)]
    reprts = (REPRT_ANNUAL,) + (QUARTER_REPRTS if include_quarters else ())

    done = existing_keys(engine)
    stats = {"tickers": len(tickers), "calls": 0, "saved": 0,
             "skipped": 0, "empty": 0, "no_corp": 0}

    for tk in tickers:
        corp = None
        corp_missing = False  # corp_code 매핑 실패 — 전부 skip된 종목과 구분(resume 버그 방지)
        for year in year_list:
            if corp_missing:
                break
            for reprt in reprts:
                if (tk, year, reprt) in done:
                    stats["skipped"] += 1
                    continue
                if max_calls is not None and stats["calls"] >= max_calls:
                    stats["stopped_at_quota"] = True
                    return stats
                if corp is None:
                    corp = get_corp_code(tk)
                    if not corp:
                        stats["no_corp"] += 1
                        corp_missing = True
                        break  # 이 종목의 모든 연도 skip
                try:
                    fs = client.get_financial_statement_full(corp, year, reprt_code=reprt)
                    stats["calls"] += 1
                    if fs is not None and upsert_statement(engine, tk, fs):
                        stats["saved"] += 1
                    else:
                        stats["empty"] += 1  # 상장 전 연도 등 — 정상
                except Exception as e:
                    stats["empty"] += 1
                    logger.debug(f"재무 조회 실패 [{tk} {year}/{reprt}]: {e}")
        if stats["saved"] and stats["saved"] % 500 == 0:
            logger.info(f"DART 백필 진행: {stats['saved']:,}건 저장 / {stats['calls']:,}콜")
    return stats


def history_snapshot(ticker: str, bsns_year: str, reprt_code: str, engine=None) -> dict | None:
    """적재된 (종목, 연도, 보고서) 재무 1건 → dict. 없으면 None (PIT가 실시간 폴백)."""
    from sqlalchemy import text
    try:
        engine = _get_engine(engine)
        if engine is None:
            return None
        cols = ", ".join(_FIELDS)
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT {cols} FROM financials_history "  # noqa: S608 — 컬럼 상수
                "WHERE ticker=:t AND bsns_year=:y AND reprt_code=:r"
            ), {"t": str(ticker), "y": str(bsns_year), "r": str(reprt_code)}).fetchone()
        if row is None:
            return None
        return {f: (float(v) if v is not None else None) for f, v in zip(_FIELDS, row)}
    except Exception:
        return None


# 손익 연환산 계수 — DART 분기 보고서의 손익 항목은 누적(1Q=3개월, 반기=6개월, 3Q=9개월)
# 기준이라 그대로 쓰면 ROE/PER이 ×4~×1.33 왜곡된다. (표준 XBRL 누적 가정 — 문서화)
ANNUALIZE_FACTOR = {"11011": 1.0, "11012": 2.0, "11013": 4.0, "11014": 4.0 / 3.0}


def annualized_net_income(row: dict, reprt_code: str | None) -> float | None:
    ni = row.get("net_income")
    if ni is None:
        return None
    return ni * ANNUALIZE_FACTOR.get(str(reprt_code or "11011"), 1.0)


def ratios_from_row(row: dict, reprt_code: str | None = None) -> dict:
    """재무 행 → PIT 스냅샷 비율 (ROE/ROA/부채비율 %). 분모 없으면 None.

    reprt_code가 분기 보고서면 손익(순이익)을 연환산해 연간 기준과 비교 가능하게."""
    def _div(a, b):
        return (a / b * 100.0) if (a is not None and b not in (None, 0, 0.0)) else None
    ni_ann = annualized_net_income(row, reprt_code)
    return {
        "roe_pct": _div(ni_ann, row.get("total_equity")),
        "roa_pct": _div(ni_ann, row.get("total_assets")),
        "debt_ratio_pct": _div(row.get("total_liabilities"), row.get("total_equity")),
    }


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="DART 재무 시계열 백필 → financials_history")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--quarters", action="store_true", help="분기 보고서(1Q/반기/3Q)도 적재")
    ap.add_argument("--tickers", default=None, help="쉼표 구분 (기본 SEED)")
    ap.add_argument("--all-listed", action="store_true", help="마스터 전 주권 대상")
    ap.add_argument("--max-calls", type=int, default=18000,
                    help="이번 실행 최대 호출 수 (DART 일쿼터 20,000 보호)")
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    stats = backfill_financials(tickers=tickers, all_listed=args.all_listed,
                                years=args.years, include_quarters=args.quarters,
                                max_calls=args.max_calls)
    print(f"재무 백필 결과: {stats}")
    if stats.get("stopped_at_quota"):
        print("→ 쿼터 도달로 중단 — 내일 같은 명령으로 재실행하면 이어서 적재됩니다(resume)")


if __name__ == "__main__":
    main()
