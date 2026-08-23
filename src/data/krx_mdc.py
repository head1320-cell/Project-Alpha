"""KRX 정보데이터시스템(MDC) 비공식 어댑터 — 투자자별 수급 **과거 백필** (1회성)
==========================================================================
⚠ 비공식: data.krx.co.kr 웹 화면([12009] 투자자별 거래실적)의 JSON 엔드포인트.
  스펙은 pykrx 1.2.8 소스에서 전사(런타임 의존 없음 — pykrx는 numpy≥2 강제라 미사용).
  KRX 개편·로그인 강제 시 깨질 수 있으나, 용도가 1회 과거 백필이고
  이후 일별 누적은 공식 KIS(kis_flows)가 담당 → 의존이 일시적.
  실패 시 빈 응답으로 안전 중단(기존 데이터 무영향).

제공: 11개 투자자 주체(금융투자·보험·투신·사모·은행·기타금융·연기금·
      기타법인·개인·외국인·기타외국인)의 일별 순매수 거래량/거래대금(원).
저장: investor_flows — KIS 3주체 합계와 의미 정합(기관계=기관 7주체 합,
      외국인=외국인+기타외국인) + 세부 주체 4종(연기금/투신/사모/기타법인).
주의: 금액 단위가 KRX=원, KIS=pbmn으로 다를 수 있음 — 같은 날짜에 두 소스를
      섞지 않도록 KIS 일별 적재는 3주체 컬럼만 갱신(bulk_upsert_flows full 분리).

실행 (사용자 환경):
    python -m src.data.krx_mdc --start 2015-01-01 --all-listed
소요: 종목당 2콜(량+금액) × 1초 간격 → 2,700종목 ≈ 1.5시간/연도청크 무관(기간은 1콜).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

MDC_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
MDC_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
    "X-Requested-With": "XMLHttpRequest",
}
BLD_INVESTOR_DETAIL = "dbms/MDC/STAT/standard/MDCSTAT02303"

# TRDVAL1~11 순서 (pykrx wrap.py 상세 매핑 전사)
DETAIL_INVESTORS = ("금융투자", "보험", "투신", "사모", "은행", "기타금융",
                    "연기금", "기타법인", "개인", "외국인", "기타외국인")
_ORGN_MEMBERS = ("금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금")

_CALL_INTERVAL_SEC = 1.0   # pykrx와 동일한 예의 간격
_CHUNK_DAYS = 700          # KRX 1콜 최대 ~2년 — 안전하게 700일 분할


def _num(s) -> float | None:
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_investor_detail(payload: dict) -> list[dict]:
    """MDC 응답 → [{date, 금융투자: v, ..., 기타외국인: v}] (과거→현재 정렬)."""
    out = []
    for r in (payload or {}).get("output", []) or []:
        d = str(r.get("TRD_DD") or "").strip().replace("/", "-")
        if len(d) != 10:
            continue
        row = {"date": d}
        for i, name in enumerate(DETAIL_INVESTORS, start=1):
            row[name] = _num(r.get(f"TRDVAL{i}"))
        out.append(row)
    out.sort(key=lambda x: x["date"])
    return out


def _default_fetcher(isin: str, start: str, end: str, value_type: str) -> list[dict]:
    """실제 MDC 호출 (테스트에선 fetcher 주입으로 대체). value_type: qty|amt."""
    import httpx
    data = {
        "bld": BLD_INVESTOR_DETAIL,
        "strtDd": start.replace("-", ""),
        "endDd": end.replace("-", ""),
        "isuCd": isin,
        "inqTpCd": 2,
        "trdVolVal": 1 if value_type == "qty" else 2,
        "askBid": 3,           # 순매수
        "detailView": 1,
    }
    time.sleep(_CALL_INTERVAL_SEC)
    r = httpx.post(MDC_URL, headers=MDC_HEADERS, data=data, timeout=30)
    r.raise_for_status()
    return parse_investor_detail(r.json())


def rows_to_flow_records(qty_rows: list[dict], amt_rows: list[dict]) -> list[dict]:
    """량/금액 행 병합 → investor_flows 레코드 (KIS 3주체 정합 + 세부 4주체).

    금액은 ★억원 단위로 정규화★ 저장 — KRX MDC 거래대금은 원 단위 → /1e8.
    (KIS pbmn=백만원과 혼합 저장돼 표시가 100배 뻥튀기되던 문제 — 적재 단일화)"""
    amt_by_date = {r["date"]: r for r in amt_rows or []}

    def _sum(row, names):
        vals = [row.get(n) for n in names if row.get(n) is not None]
        return sum(vals) if vals else None

    def _억(v):  # 원 → 억원
        return (v / 1e8) if v is not None else None

    out = []
    for q in qty_rows or []:
        a = amt_by_date.get(q["date"], {})
        out.append({
            "date": q["date"],
            "prsn_qty": q.get("개인"), "prsn_amt": _억(a.get("개인")),
            "frgn_qty": _sum(q, ("외국인", "기타외국인")),
            "frgn_amt": _억(_sum(a, ("외국인", "기타외국인"))),
            "orgn_qty": _sum(q, _ORGN_MEMBERS), "orgn_amt": _억(_sum(a, _ORGN_MEMBERS)),
            "pension_qty": q.get("연기금"), "pension_amt": _억(a.get("연기금")),
            "trust_qty": q.get("투신"), "trust_amt": _억(a.get("투신")),
            "pe_qty": q.get("사모"), "pe_amt": _억(a.get("사모")),
            "othercorp_qty": q.get("기타법인"), "othercorp_amt": _억(a.get("기타법인")),
        })
    return out


def _date_chunks(start: str, end: str):
    from datetime import timedelta
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    while s <= e:
        c_end = min(s + timedelta(days=_CHUNK_DAYS - 1), e)
        yield s.strftime("%Y-%m-%d"), c_end.strftime("%Y-%m-%d")
        s = c_end + timedelta(days=1)


def backfill_flows_krx(start: str, end: str | None = None,
                       tickers: list[str] | None = None, all_listed: bool = False,
                       engine=None, fetcher=None) -> dict:
    """투자자별 수급 과거 백필 — ISIN은 KIS 마스터 캐시(collect-master 선행 필요)."""
    from src.data.kis_flows import bulk_upsert_flows, ensure_flows_table
    from src.data.stock_master import load_master_flags

    fetcher = fetcher or _default_fetcher
    engine = engine if engine is not None else _engine()
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_flows_table(engine)

    flags = load_master_flags()
    if not flags:
        return {"error": True,
                "message": "마스터 캐시 없음 — POST /api/v1/symbols/collect-master 먼저 실행"}

    if tickers is None:
        if all_listed:
            tickers = [c for c, f in flags.items() if (f.get("group_code") or "ST") == "ST"]
        else:
            from src.data_sync import SEED_TICKERS
            tickers = [t[0] for t in SEED_TICKERS]

    end = end or datetime.now().strftime("%Y-%m-%d")
    stats = {"tickers": len(tickers), "loaded": 0, "rows": 0,
             "no_isin": 0, "errors": 0}

    for tk in tickers:
        isin = (flags.get(tk) or {}).get("isin") or ""
        if len(isin) != 12:
            stats["no_isin"] += 1
            continue
        try:
            qty_rows: list[dict] = []
            amt_rows: list[dict] = []
            for c_start, c_end in _date_chunks(start, end):
                qty_rows += fetcher(isin, c_start, c_end, "qty")
                amt_rows += fetcher(isin, c_start, c_end, "amt")
            records = rows_to_flow_records(qty_rows, amt_rows)
            if not records:
                continue
            stats["rows"] += bulk_upsert_flows(engine, tk, records, full=True)
            stats["loaded"] += 1
            if stats["loaded"] % 50 == 0:
                logger.info(f"KRX 수급 백필: {stats['loaded']}/{len(tickers)}종목 "
                            f"{stats['rows']:,}행")
        except Exception as e:
            stats["errors"] += 1
            logger.warning(f"KRX 수급 백필 실패 [{tk}]: {type(e).__name__}: {e}")
            if stats["errors"] >= 10 and stats["loaded"] == 0:
                stats["error"] = True
                stats["message"] = "연속 실패 — KRX 엔드포인트 변경/차단 가능성, 중단"
                return stats
    return stats


def _engine():
    from src.database import get_engine
    return get_engine()


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="KRX MDC 투자자별 수급 과거 백필 (비공식·1회성)")
    ap.add_argument("--start", required=True, help="시작일 YYYY-MM-DD")
    ap.add_argument("--end", default=None)
    ap.add_argument("--tickers", default=None, help="쉼표 구분 (기본 SEED)")
    ap.add_argument("--all-listed", action="store_true", help="마스터 전 주권 (~1.5시간)")
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    print(f"KRX 수급 백필 결과: "
          f"{backfill_flows_krx(args.start, args.end, tickers, args.all_listed)}")


if __name__ == "__main__":
    main()
