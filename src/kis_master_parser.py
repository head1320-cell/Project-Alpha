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
    KOSPI/KOSDAQ 마스터파일 파싱 — 원본 그대로.

    파일 형식: EUC-KR, 고정 폭 (바이트 기준)
      bytes  0- 8 (9B):  단축코드
      bytes  9-20 (12B): 표준코드
      bytes 21-60 (40B): 한글종목명
    """
    symbols: list[dict] = []
    for line in content.split(b"\n"):
        if len(line) < 61:
            continue
        code = line[0:9].decode("euc-kr", errors="ignore").strip()
        name = line[21:61].decode("euc-kr", errors="ignore").strip()
        if len(code) > 6:
            code = code[-6:]
        if code and name and code.isdigit():
            symbols.append({"ticker": code, "name": name, "market": market})
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

    elapsed = (datetime.utcnow() - start).total_seconds()
    return {
        **results,
        "total": sum(results.values()),
        "db_upserted": db_count,
        "elapsed_sec": round(elapsed, 1),
        "completed_at": datetime.utcnow().isoformat(),
    }
