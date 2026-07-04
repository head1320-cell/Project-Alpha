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
    dps                 FLOAT,
    fetched_at          VARCHAR(32),
    PRIMARY KEY (ticker, bsns_year, reprt_code)
)
"""

# 기존 테이블 마이그레이션 (ALTER 멱등 — 이미 있음 무시)
_MIGRATE_COLUMNS = ("dps FLOAT",)

_UPSERT = """
INSERT INTO financials_history
    (ticker, bsns_year, reprt_code, revenue, operating_profit, net_income, gross_profit,
     total_assets, total_liabilities, total_equity, current_assets, current_liabilities,
     operating_cf, capex, shares_outstanding, dps, fetched_at)
VALUES
    (:ticker, :bsns_year, :reprt_code, :revenue, :operating_profit, :net_income, :gross_profit,
     :total_assets, :total_liabilities, :total_equity, :current_assets, :current_liabilities,
     :operating_cf, :capex, :shares_outstanding, :dps, :fetched_at)
ON CONFLICT (ticker, bsns_year, reprt_code) DO UPDATE SET
    revenue=EXCLUDED.revenue, operating_profit=EXCLUDED.operating_profit,
    net_income=EXCLUDED.net_income, gross_profit=EXCLUDED.gross_profit,
    total_assets=EXCLUDED.total_assets, total_liabilities=EXCLUDED.total_liabilities,
    total_equity=EXCLUDED.total_equity, current_assets=EXCLUDED.current_assets,
    current_liabilities=EXCLUDED.current_liabilities, operating_cf=EXCLUDED.operating_cf,
    capex=EXCLUDED.capex, shares_outstanding=EXCLUDED.shares_outstanding,
    dps=EXCLUDED.dps, fetched_at=EXCLUDED.fetched_at
"""

_FIELDS = ("revenue", "operating_profit", "net_income", "gross_profit",
           "total_assets", "total_liabilities", "total_equity",
           "current_assets", "current_liabilities", "operating_cf", "capex",
           "shares_outstanding", "dps")

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
    for col in _MIGRATE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE financials_history ADD COLUMN {col}"))
        except Exception:
            pass  # 이미 존재 — 정상


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
                        engine=None, client=None, progress_cb=None) -> dict:
    """종목×연도(×분기) 재무 백필 — DART 일쿼터 대응 max_calls 분할 + resume.

    progress_cb(done, total, saved, calls): 종목 1건 처리할 때마다 보고(UI 표면화).
    fallback_to_seed: all_listed=True인데 마스터 캐시가 비어(부팅 시 수집 경쟁 등) SEED
    30종목으로 축소됐는지 — 호출부가 '진짜 완료'와 '축소 실행'을 구분해 재시도 간격을
    조절할 수 있게(짧게 재시도 vs 다음날 증분)."""
    from src.data.dart_client import DARTClient, get_corp_code
    client = client or DARTClient()
    if not client.is_configured:
        return {"error": True, "message": "DART_API_KEY 미설정 — .env에 키를 넣고 실행하세요"}

    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_history_table(engine)

    fallback_to_seed = False
    if tickers is None:
        if all_listed:
            from src.data_sync import _all_listed_tickers
            tickers = _all_listed_tickers()
            if not tickers:
                fallback_to_seed = True
        if not tickers:
            from src.data_sync import SEED_TICKERS
            tickers = [t[0] for t in SEED_TICKERS]

    last_year = datetime.now().year - 1
    year_list = [str(y) for y in range(last_year, last_year - years, -1)]
    reprts = (REPRT_ANNUAL,) + (QUARTER_REPRTS if include_quarters else ())

    done = existing_keys(engine)
    stats = {"tickers": len(tickers), "calls": 0, "saved": 0,
             "skipped": 0, "empty": 0, "no_corp": 0, "fallback_to_seed": fallback_to_seed}

    for i, tk in enumerate(tickers):
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
        if progress_cb is not None:
            try:
                progress_cb(i + 1, len(tickers), stats["saved"], stats["calls"])
            except Exception:
                pass
    _HISTORY_CACHE.clear()  # 새 적재분 반영 (파생 팩터 캐시 무효화)
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


# ═══════════════════════════════════════════════════════════════════════════════
# 시계열 파생 팩터 — 흑자전환·3년연속·성장률류 (조건식 펀더멘털 토큰)
#   · YoY = 동일 보고서(누적) 전년 대비 — 누적끼리 비교라 연환산 불필요
#   · QOQ = 단일 분기값(누적 차분: 반기-1Q 등) 비교 — 인접 보고서 없으면 None(정직)
#   · 3년연속 = 최근 3개 연간 보고서 기준 (부족하면 None)
#   현재 스냅샷 기준(최신 적재 보고서) — 펀더멘털 토글과 동일한 look-ahead 근사.
# ═══════════════════════════════════════════════════════════════════════════════

_REPRT_MONTH = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}

HISTORY_FACTOR_IDS = (
    "ni_positive_3y", "op_positive_3y",
    "ni_turnaround_yoy", "ni_turnaround_qoq", "op_turnaround_yoy", "op_turnaround_qoq",
    "ni_growth_yoy", "ni_growth_qoq", "op_growth_qoq",
    "asset_growth_yoy", "equity_growth_yoy",
    "debt_ratio_growth_yoy", "current_ratio_growth_yoy",
    "gross_margin_growth_yoy", "asset_turnover_growth_yoy",
    "roa_growth_yoy", "roe_growth_yoy",
    "dps_up_3y", "dps_growth_yoy",
)

_HISTORY_CACHE: dict[str, dict] = {}


def load_history(ticker: str, engine=None) -> list[dict]:
    """종목의 전체 적재 행 (연대순 정렬, year/reprt/month 포함). 없으면 []."""
    from sqlalchemy import text
    try:
        engine = _get_engine(engine)
        if engine is None:
            return []
        cols = ", ".join(_FIELDS)
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT bsns_year, reprt_code, {cols} FROM financials_history "  # noqa: S608
                "WHERE ticker=:t"), {"t": str(ticker)}).fetchall()
        out = []
        for r in rows:
            year, reprt = str(r[0]), str(r[1])
            month = _REPRT_MONTH.get(reprt)
            if month is None:
                continue
            d = {f: (float(v) if v is not None else None) for f, v in zip(_FIELDS, r[2:])}
            d.update({"year": int(year), "reprt": reprt, "month": month,
                      "seq": int(year) * 12 + month})
            out.append(d)
        out.sort(key=lambda x: x["seq"])
        return out
    except Exception:
        return []


def _growth(cur, prev) -> float | None:
    """성장률(%) — 기반(prev)이 양수일 때만 의미 있음.

    음수 기반(전년 적자 등)의 '성장률'은 부호가 뒤집혀 오독을 유발 → None,
    그 경우는 흑자전환(turnaround) 토큰이 담당한다."""
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def _turnaround(cur, prev) -> float | None:
    if cur is None or prev is None:
        return None
    return 1.0 if (prev <= 0 < cur) else 0.0


def _ratio(a, b, scale=100.0) -> float | None:
    if a is None or b in (None, 0, 0.0):
        return None
    return a / b * scale


def _single_quarters(rows: list[dict], field: str) -> list[tuple[int, float]]:
    """누적 손익 → 단일 분기값 [(seq, value)]. 1Q=누적, 이후는 직전 보고서와의 차분
    (같은 연도 내 인접 보고서가 있을 때만 — 없으면 그 분기는 산출 불가)."""
    by_key = {(r["year"], r["month"]): r.get(field) for r in rows}
    singles = []
    for r in rows:
        v = r.get(field)
        if v is None:
            continue
        if r["month"] == 3:
            singles.append((r["seq"], v))
            continue
        prev = by_key.get((r["year"], r["month"] - 3))
        if prev is not None:
            singles.append((r["seq"], v - prev))
    return singles


def _compute_history_factors(rows: list[dict]) -> dict:
    out: dict = dict.fromkeys(HISTORY_FACTOR_IDS)
    if not rows:
        return out
    latest = rows[-1]

    # 동일 보고서 전년(YoY) — 누적끼리 비교
    prev_y = next((r for r in reversed(rows[:-1])
                   if r["year"] == latest["year"] - 1 and r["reprt"] == latest["reprt"]), None)
    if prev_y is not None:
        out["ni_turnaround_yoy"] = _turnaround(latest.get("net_income"), prev_y.get("net_income"))
        out["op_turnaround_yoy"] = _turnaround(latest.get("operating_profit"),
                                               prev_y.get("operating_profit"))
        out["ni_growth_yoy"] = _growth(latest.get("net_income"), prev_y.get("net_income"))
        out["asset_growth_yoy"] = _growth(latest.get("total_assets"), prev_y.get("total_assets"))
        out["equity_growth_yoy"] = _growth(latest.get("total_equity"), prev_y.get("total_equity"))
        for fid, cur_v, prev_v in (
            ("debt_ratio_growth_yoy",
             _ratio(latest.get("total_liabilities"), latest.get("total_equity")),
             _ratio(prev_y.get("total_liabilities"), prev_y.get("total_equity"))),
            ("current_ratio_growth_yoy",
             _ratio(latest.get("current_assets"), latest.get("current_liabilities")),
             _ratio(prev_y.get("current_assets"), prev_y.get("current_liabilities"))),
            ("gross_margin_growth_yoy",
             _ratio(latest.get("gross_profit"), latest.get("revenue")),
             _ratio(prev_y.get("gross_profit"), prev_y.get("revenue"))),
            ("asset_turnover_growth_yoy",
             _ratio(latest.get("revenue"), latest.get("total_assets"), 1.0),
             _ratio(prev_y.get("revenue"), prev_y.get("total_assets"), 1.0)),
            ("roa_growth_yoy",
             _ratio(latest.get("net_income"), latest.get("total_assets")),
             _ratio(prev_y.get("net_income"), prev_y.get("total_assets"))),
            ("roe_growth_yoy",
             _ratio(latest.get("net_income"), latest.get("total_equity")),
             _ratio(prev_y.get("net_income"), prev_y.get("total_equity"))),
        ):
            out[fid] = _growth(cur_v, prev_v)

    # 단일 분기(QOQ) — 누적 차분, 인접(3개월) 분기끼리만
    for fid_g, fid_t, field in (("ni_growth_qoq", "ni_turnaround_qoq", "net_income"),
                                ("op_growth_qoq", "op_turnaround_qoq", "operating_profit")):
        singles = _single_quarters(rows, field)
        if len(singles) >= 2 and singles[-1][0] - singles[-2][0] == 3:
            out[fid_g] = _growth(singles[-1][1], singles[-2][1])
            out[fid_t] = _turnaround(singles[-1][1], singles[-2][1])

    # 3년연속 (연간 보고서 3개 필요)
    annuals = [r for r in rows if r["reprt"] == REPRT_ANNUAL][-3:]
    if len(annuals) == 3:
        ni = [r.get("net_income") for r in annuals]
        op = [r.get("operating_profit") for r in annuals]
        if all(v is not None for v in ni):
            out["ni_positive_3y"] = 1.0 if all(v > 0 for v in ni) else 0.0
        if all(v is not None for v in op):
            out["op_positive_3y"] = 1.0 if all(v > 0 for v in op) else 0.0
        dps = [r.get("dps") for r in annuals]
        if all(v is not None for v in dps):
            out["dps_up_3y"] = 1.0 if (dps[0] <= dps[1] <= dps[2]) else 0.0
    if len(annuals) >= 2:
        out["dps_growth_yoy"] = _growth(annuals[-1].get("dps"), annuals[-2].get("dps"))
    return out


def history_factors(ticker: str, engine=None) -> dict:
    """시계열 파생 팩터 (캐시) — 적재 없으면 전부 None(조건 건너뜀)."""
    key = str(ticker)
    if key in _HISTORY_CACHE:
        return _HISTORY_CACHE[key]
    out = _compute_history_factors(load_history(key, engine))
    _HISTORY_CACHE[key] = out
    return out


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
