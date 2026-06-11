"""
KIS Master File Parser
=======================
KIS 공개 URL에서 KOSPI/KOSDAQ 종목 마스터파일을 다운로드하고
stocks 테이블에 Upsert합니다. 인증 불필요.

원본 로직:
  backtester/scripts/download_master.py → parse_krx_master()

확장:
  - async 다운로드
  - DB Upsert (stocks 테이블)
  - FastAPI 엔드포인트 연동
"""

import asyncio
import logging
import urllib.request
import zipfile
from datetime import datetime
from io import BytesIO

from sqlalchemy import text

logger = logging.getLogger(__name__)

# KIS 공개 URL (인증 불필요)
MASTER_URLS = {
    "KOSPI":  "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
    "KOSDAQ": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
}

# ═══════════════════════════════════════════════════════════════════════════════
# 테일(고정폭) 필드 스펙 — KIS 공식 open-trading-api 샘플 전사
#   stocks_info/kis_kospi_code_mst.py (테일 227자 + 개행) /
#   stocks_info/kis_kosdaq_code_mst.py (테일 221자 + 개행)
# 테일은 전부 ASCII(숫자·Y/N·코드)라 바이트 기준으로도 동일 길이 — 행 끝에서 역방향 슬라이스.
# ═══════════════════════════════════════════════════════════════════════════════

KOSPI_TAIL_FIELDS: list[tuple[str, int]] = [
    ("그룹코드", 2), ("시가총액규모", 1), ("지수업종대분류", 4), ("지수업종중분류", 4), ("지수업종소분류", 4),
    ("제조업", 1), ("저유동성", 1), ("지배구조지수종목", 1), ("KOSPI200섹터업종", 1), ("KOSPI100", 1),
    ("KOSPI50", 1), ("KRX", 1), ("ETP", 1), ("ELW발행", 1), ("KRX100", 1),
    ("KRX자동차", 1), ("KRX반도체", 1), ("KRX바이오", 1), ("KRX은행", 1), ("SPAC", 1),
    ("KRX에너지화학", 1), ("KRX철강", 1), ("단기과열", 1), ("KRX미디어통신", 1), ("KRX건설", 1),
    ("Non1", 1), ("KRX증권", 1), ("KRX선박", 1), ("KRX섹터_보험", 1), ("KRX섹터_운송", 1),
    ("SRI", 1), ("기준가", 9), ("매매수량단위", 5), ("시간외수량단위", 5), ("거래정지", 1),
    ("정리매매", 1), ("관리종목", 1), ("시장경고", 2), ("경고예고", 1), ("불성실공시", 1),
    ("우회상장", 1), ("락구분", 2), ("액면변경", 2), ("증자구분", 2), ("증거금비율", 3),
    ("신용가능", 1), ("신용기간", 3), ("전일거래량", 12), ("액면가", 12), ("상장일자", 8),
    ("상장주수", 15), ("자본금", 21), ("결산월", 2), ("공모가", 7), ("우선주", 1),
    ("공매도과열", 1), ("이상급등", 1), ("KRX300", 1), ("KOSPI", 1), ("매출액", 9),
    ("영업이익", 9), ("경상이익", 9), ("당기순이익", 5), ("ROE", 9), ("기준년월", 8),
    ("시가총액", 9), ("그룹사코드", 3), ("회사신용한도초과", 1), ("담보대출가능", 1), ("대주가능", 1),
]

KOSDAQ_TAIL_FIELDS: list[tuple[str, int]] = [
    ("그룹코드", 2), ("시가총액규모", 1),
    ("지수업종대분류", 4), ("지수업종중분류", 4), ("지수업종소분류", 4), ("벤처기업", 1), ("저유동성", 1),
    ("KRX", 1), ("ETP", 1), ("KRX100", 1), ("KRX자동차", 1), ("KRX반도체", 1),
    ("KRX바이오", 1), ("KRX은행", 1), ("SPAC", 1), ("KRX에너지화학", 1), ("KRX철강", 1),
    ("단기과열", 1), ("KRX미디어통신", 1), ("KRX건설", 1), ("투자주의환기", 1), ("KRX증권", 1),
    ("KRX선박", 1), ("KRX섹터_보험", 1), ("KRX섹터_운송", 1), ("KOSDAQ150", 1), ("기준가", 9),
    ("매매수량단위", 5), ("시간외수량단위", 5), ("거래정지", 1), ("정리매매", 1), ("관리종목", 1),
    ("시장경고", 2), ("경고예고", 1), ("불성실공시", 1), ("우회상장", 1), ("락구분", 2),
    ("액면변경", 2), ("증자구분", 2), ("증거금비율", 3), ("신용가능", 1), ("신용기간", 3),
    ("전일거래량", 12), ("액면가", 12), ("상장일자", 8), ("상장주수", 15), ("자본금", 21),
    ("결산월", 2), ("공모가", 7), ("우선주", 1), ("공매도과열", 1), ("이상급등", 1),
    ("KRX300", 1), ("매출액", 9), ("영업이익", 9), ("경상이익", 9), ("당기순이익", 5),
    ("ROE", 9), ("기준년월", 8), ("시가총액", 9), ("그룹사코드", 3), ("회사신용한도초과", 1),
    ("담보대출가능", 1), ("대주가능", 1),
]

TAIL_FIELDS_BY_MARKET = {"KOSPI": KOSPI_TAIL_FIELDS, "KOSDAQ": KOSDAQ_TAIL_FIELDS}
TAIL_LEN_BY_MARKET = {m: sum(w for _, w in f) for m, f in TAIL_FIELDS_BY_MARKET.items()}  # 227 / 221


def _parse_tail(line: bytes, market: str) -> dict | None:
    """행 끝 고정폭 테일 → 필드 dict. 길이 부족·예외 시 None (3필드 폴백)."""
    fields = TAIL_FIELDS_BY_MARKET.get(market)
    if not fields:
        return None
    tail_len = TAIL_LEN_BY_MARKET[market]
    if len(line) < 21 + tail_len:  # 단축(9)+표준(12)+테일 — 종목명이 비어도 이 이상
        return None
    try:
        tail = line[-tail_len:].decode("latin-1")  # ASCII 영역 — 1:1 길이 보존 디코딩
        out: dict = {}
        pos = 0
        for name, w in fields:
            out[name] = tail[pos:pos + w].strip()
            pos += w
        return out
    except Exception:
        return None


def _to_int(s: str | None) -> int | None:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None

# 인메모리 캐시 (검색용)
_symbol_cache: dict[str, list[dict]] = {}
_last_fetched: datetime | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 다운로드 + 파싱 (원본 parse_krx_master 그대로)
# ═══════════════════════════════════════════════════════════════════════════════

def _download_and_extract(url: str) -> bytes:
    """URL에서 ZIP 다운로드 → 첫 번째 파일 반환."""
    with urllib.request.urlopen(url, timeout=60) as resp:
        content = resp.read()
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            return zf.read(zf.namelist()[0])
    except zipfile.BadZipFile:
        return content


def parse_krx_master(content: bytes, market: str) -> list[dict]:
    """
    KOSPI/KOSDAQ 마스터파일 파싱.

    파일 형식: EUC-KR, 고정 폭 (바이트 기준)
      bytes  0- 8 (9B):  단축코드
      bytes  9-20 (12B): 표준코드
      bytes 21-60 (40B): 한글종목명
      행 끝 고정폭 테일(KOSPI 227B / KOSDAQ 221B): 관리종목·시장경고·거래정지·
      시가총액(억)·지수업종코드 등 — _parse_tail()로 추출, 실패 시 3필드 폴백.
    """
    symbols: list[dict] = []
    for line in content.split(b"\n"):
        if len(line) < 61:
            continue
        code = line[0:9].decode("euc-kr", errors="ignore").strip()
        isin = line[9:21].decode("euc-kr", errors="ignore").strip()  # 표준코드(ISIN) — KRX MDC 조회 키
        name = line[21:61].decode("euc-kr", errors="ignore").strip()
        if len(code) > 6:
            code = code[-6:]
        if not (code and name and code.isdigit()):
            continue
        sym: dict = {"ticker": code, "name": name, "market": market,
                     "isin": isin if len(isin) == 12 else ""}
        tail = _parse_tail(line, market)
        if tail:
            sym.update({
                "group_code": tail.get("그룹코드") or "",        # ST주권 / EF ETF / RT리츠 …
                "cap_size": tail.get("시가총액규모") or "",       # 1대 / 2중 / 3소
                "sector_code": tail.get("지수업종대분류") or "",
                "is_managed": tail.get("관리종목") == "Y",
                "alert_code": tail.get("시장경고") or "00",       # 00정상 / 01주의 / 02경고 / 03위험
                "is_halted": tail.get("거래정지") == "Y",
                "is_clearing": tail.get("정리매매") == "Y",
                "is_caution": tail.get("투자주의환기") == "Y",    # 코스닥 전용 (KOSPI는 False)
                "market_cap_억": _to_int(tail.get("시가총액")),
            })
        symbols.append(sym)
    return symbols


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DB Upsert
# ═══════════════════════════════════════════════════════════════════════════════

def _upsert_symbols(engine, symbols: list[dict]) -> int:
    """stocks 테이블에 bulk upsert. 메모리 안전 (50개씩 청크)."""
    if not symbols:
        return 0

    CHUNK = 50
    inserted = 0

    with engine.begin() as conn:
        for i in range(0, len(symbols), CHUNK):
            chunk = symbols[i:i + CHUNK]
            for s in chunk:
                try:
                    # PostgreSQL ON CONFLICT
                    conn.execute(text("""
                        INSERT INTO stocks (ticker, name, market, currency, is_active)
                        VALUES (:ticker, :name, :market, 'KRW', 1)
                        ON CONFLICT (ticker) DO UPDATE
                          SET name   = EXCLUDED.name,
                              market = EXCLUDED.market
                    """), s)
                except Exception:
                    # SQLite fallback (no ON CONFLICT UPDATE syntax)
                    try:
                        conn.execute(text("""
                            INSERT OR REPLACE INTO stocks (ticker, name, market, currency, is_active)
                            VALUES (:ticker, :name, :market, 'KRW', 1)
                        """), s)
                    except Exception:
                        pass
            inserted += len(chunk)

    return inserted


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 동기 캐시 로드 (검색용)
# ═══════════════════════════════════════════════════════════════════════════════

def load_symbol_cache(engine) -> dict[str, list[dict]]:
    """DB → 인메모리 캐시 로드."""
    global _symbol_cache, _last_fetched
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, name, market FROM stocks WHERE is_active = 1"
            )).fetchall()

        cache: dict[str, list[dict]] = {}
        for ticker, name, market in rows:
            mkt = (market or "").upper()
            if mkt not in cache:
                cache[mkt] = []
            cache[mkt].append({"ticker": ticker, "name": name, "market": mkt})

        _symbol_cache = cache
        _last_fetched = datetime.utcnow()
        total = sum(len(v) for v in cache.values())
        logger.info(f"Symbol cache loaded: {total} symbols")
        return cache
    except Exception as e:
        logger.error(f"load_symbol_cache error: {e}")
        return {}


def search_symbols(query: str, market: str | None = None, limit: int = 30) -> list[dict]:
    """인메모리 캐시에서 종목 검색. DB 없이도 동작."""
    q = query.lower().strip()
    results = []

    for mkt, syms in _symbol_cache.items():
        if market and mkt != market.upper():
            continue
        for s in syms:
            if q in s["ticker"].lower() or q in s["name"].lower():
                results.append(s)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 비동기 전체 수집 엔트리포인트
# ═══════════════════════════════════════════════════════════════════════════════

async def collect_master_files(engine=None) -> dict:
    """
    마스터파일 다운로드 → 파싱 → DB Upsert → 캐시 로드.
    FastAPI 엔드포인트에서 호출.
    """
    results = {}
    all_symbols: list[dict] = []
    start = datetime.utcnow()

    for market, url in MASTER_URLS.items():
        try:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(None, _download_and_extract, url)
            symbols = parse_krx_master(content, market)
            results[market] = len(symbols)
            all_symbols.extend(symbols)
            logger.info(f"{market}: {len(symbols)} symbols parsed")
        except Exception as e:
            logger.error(f"{market} master fetch failed: {e}")
            results[market] = 0

    # DB Upsert
    db_count = 0
    if engine and all_symbols:
        try:
            db_count = await asyncio.get_running_loop().run_in_executor(
                None, _upsert_symbols, engine, all_symbols
            )
        except Exception as e:
            logger.error(f"DB upsert failed: {e}")

    # 캐시 갱신
    if engine:
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, load_symbol_cache, engine
            )
        except Exception as e:
            logger.warning(f"Cache reload failed: {e}")
    else:
        # DB 없으면 캐시 직접 구성
        global _symbol_cache
        cache: dict[str, list[dict]] = {}
        for s in all_symbols:
            m = s["market"]
            if m not in cache:
                cache[m] = []
            cache[m].append(s)
        _symbol_cache = cache

    # 플래그 캐시 저장 (관리/감리·시총·업종 — DB 없이도 동작하는 단일 산출물)
    flags_saved = 0
    managed_count = alerted_count = halted_count = 0
    sanity: dict = {}
    if all_symbols:
        try:
            from src.data import stock_master as sm
            flags_saved = sm.save_master_flags(all_symbols)
            sm.reload_master_flags()  # MANAGED/SUPERVISED 모듈 변수 + _status_codes 캐시 갱신
            managed_count = sum(1 for s in all_symbols if s.get("is_managed") or s.get("is_halted") or s.get("is_clearing"))
            alerted_count = sum(1 for s in all_symbols
                                if (s.get("alert_code") or "00") != "00" or s.get("is_caution"))
            halted_count = sum(1 for s in all_symbols if s.get("is_halted"))
            # sanity: 실파일 오프셋 정합 확인용 (삼성전자 시총 >100조=1,000,000억, 업종코드 채움 비율)
            ss = next((s for s in all_symbols if s["ticker"] == "005930"), None)
            with_tail = [s for s in all_symbols if "sector_code" in s]
            sanity = {
                "samsung_mcap_억": (ss or {}).get("market_cap_억"),
                "tail_parsed_pct": round(len(with_tail) / len(all_symbols) * 100, 1),
                "sector_filled_pct": round(
                    sum(1 for s in with_tail if s.get("sector_code")) / max(len(with_tail), 1) * 100, 1),
            }
        except Exception as e:
            logger.error(f"master flags cache save failed: {e}")

    elapsed = (datetime.utcnow() - start).total_seconds()
    return {
        **results,
        "total": sum(results.values()),
        "db_upserted": db_count,
        "flags_cached": flags_saved,
        "managed_count": managed_count,
        "alerted_count": alerted_count,
        "halted_count": halted_count,
        "sanity": sanity,
        "elapsed_sec": round(elapsed, 1),
        "completed_at": datetime.utcnow().isoformat(),
    }
