# 대상 경로: src/data/minute_bars.py
#
# 분봉 적재·로더 — "신호는 일봉, 체결만 분봉" 하이브리드의 데이터 계층.
#
#   수집:  python -m src.data.minute_bars --tickers 005930,000660 [--date YYYYMMDD]
#          python -m src.data.minute_bars --file tickers.txt
#          python -m src.data.minute_bars --probe          # 일별분봉 소급 한도 실측
#   저장:  data/minute_bars/{YYYY-MM-DD}.parquet (일자당 1파일, ticker 컬럼 포함)
#          — 종목×일자 파일 폭발 방지. zstd 압축으로 전 주권 1일 ≈ 수 MB.
#   로더:  load_minute_bars(ticker, "YYYY-MM-DD") → DataFrame[time,open,high,low,close,volume]
#          일파일 LRU 캐시 — 엔진이 날짜 순서로 돌므로 적중률 높음.
#
# KIS_USE_MOCK=1: 수집은 결정적 합성 분봉(파이프라인 검증용 — 일봉 mock과 무관한
# 데모 데이터임을 명시), 로더는 수집된 파일이 있을 때만 반환(없으면 None → 엔진이
# 일봉 모델로 폴백 = 기존 동작 불변).

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.mock_gate import mock_allowed

logger = logging.getLogger(__name__)

COLUMNS = ["ticker", "time", "open", "high", "low", "close", "volume"]
_THROTTLE_SEC = 0.06  # ≈16콜/초 (KIS 한도 20/초 이내)


def bars_dir() -> Path:
    return Path(os.getenv("MINUTE_BARS_DIR", "data/minute_bars"))


def day_path(date: str) -> Path:
    """date: YYYY-MM-DD"""
    return bars_dir() / f"{date}.parquet"


def _existing_day_path(date: str) -> Path | None:
    """일파일 탐색 — parquet 우선, pyarrow 없는 환경의 csv.gz 폴백도 인식."""
    p = day_path(date)
    if p.exists():
        return p
    alt = p.with_suffix(".csv.gz")
    return alt if alt.exists() else None


def _read_day_file(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"ticker": str, "time": str})


def _write_day_file(df: pd.DataFrame, date: str) -> Path:
    """parquet(zstd) 저장 — pyarrow/fastparquet 미설치면 csv.gz 폴백 (이식성 우선)."""
    path = day_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False, compression="zstd")
        return path
    except ImportError:
        alt = path.with_suffix(".csv.gz")
        df.to_csv(alt, index=False, compression="gzip")
        return alt


def _norm_date(date: str | None) -> str:
    """YYYYMMDD/YYYY-MM-DD/None(오늘) → YYYY-MM-DD"""
    if not date:
        return datetime.now().strftime("%Y-%m-%d")
    d = str(date).strip().replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


# ─── 합성 분봉 (mock — 파이프라인 검증용) ────────────────────────────────────
def _mock_minute_bars(ticker: str, date: str) -> list[dict]:
    rng = np.random.RandomState(abs(hash(f"{ticker}|{date}")) % (2**31))
    anchor = 10_000 + (abs(hash(ticker)) % 90) * 1_000
    n = 390  # 09:01 ~ 15:30
    closes = anchor * np.cumprod(1 + rng.normal(0, 0.0008, n))
    out = []
    for i in range(n):
        total = 9 * 60 + 1 + i
        spread = closes[i] * 0.001
        out.append({
            "time": f"{total // 60:02d}{total % 60:02d}00",
            "open": float(closes[i] - spread / 2), "high": float(closes[i] + spread),
            "low": float(closes[i] - spread), "close": float(closes[i]),
            "volume": float(rng.randint(100, 5_000)),
        })
    return out


def _fetch_minute_bars(ticker: str, date: str) -> list[dict]:
    """KIS 분봉 1종목 — 당일이면 당일분봉, 과거면 일별분봉. mock 모드는 합성."""
    if mock_allowed():
        return _mock_minute_bars(ticker, date)
    from src.execution.kis_client import get_kis_client
    client = get_kis_client()
    today = datetime.now().strftime("%Y-%m-%d")
    if date == today:
        return client.get_minute_bars_today(ticker)
    return client.get_minute_bars_dated(ticker, date.replace("-", ""))


# ─── 수집 (재개 가능 — 이미 적재된 종목 스킵) ────────────────────────────────
def collect_day(tickers: list[str], date: str | None = None,
                throttle: float = _THROTTLE_SEC) -> dict:
    """일자 1개의 분봉을 종목들에 대해 수집 → 일파일 parquet upsert.

    매일 장 마감 후 cron: 보유 + 후보 풀 종목으로 호출. 전 주권 ~2,700도
    13콜/종목 × 16콜/초 ≈ 30분. 이미 적재된 종목은 스킵(재개 가능)."""
    date = _norm_date(date)
    existing = None
    done: set[str] = set()
    found = _existing_day_path(date)
    if found is not None:
        try:
            existing = _read_day_file(found)
            done = set(existing["ticker"].astype(str).unique())
        except Exception:
            existing = None
    rows: list[dict] = []
    ok, skipped, failed = 0, 0, 0
    for tk in tickers:
        tk = str(tk).strip()
        if not tk:
            continue
        if tk in done:
            skipped += 1
            continue
        try:
            bars = _fetch_minute_bars(tk, date)
        except Exception as e:
            logger.warning(f"분봉 수집 실패 {tk} {date}: {e}")
            failed += 1
            continue
        if not bars:
            failed += 1
            continue
        for b in bars:
            rows.append({"ticker": tk, **b})
        ok += 1
        if throttle > 0 and not mock_allowed():
            time.sleep(throttle)
    out_path = found
    if rows:
        new_df = pd.DataFrame(rows, columns=COLUMNS)
        for c in ("open", "high", "low", "close", "volume"):
            new_df[c] = new_df[c].astype(np.float32)
        merged = (pd.concat([existing, new_df], ignore_index=True)
                  if existing is not None else new_df)
        out_path = _write_day_file(merged, date)
        _load_day.cache_clear()
    return {"date": date, "collected": ok, "skipped": skipped, "failed": failed,
            "rows_added": len(rows), "path": str(out_path) if out_path else None}


# ─── 로더 (일파일 LRU — 엔진이 날짜순 순회라 적중률 높음) ────────────────────
@lru_cache(maxsize=4)
def _load_day(date: str) -> pd.DataFrame | None:
    path = _existing_day_path(date)
    if path is None:
        return None
    try:
        return _read_day_file(path)
    except Exception as e:
        logger.warning(f"분봉 일파일 로드 실패 {date}: {e}")
        return None


def load_minute_bars(ticker: str, date: str) -> pd.DataFrame | None:
    """(종목, 일자) 분봉 — 적재돼 있으면 time 오름차순 DataFrame, 없으면 None.

    None이면 호출부(하이브리드 체결)가 일봉 모델로 폴백 — 기존 동작 불변."""
    day = _load_day(_norm_date(date))
    if day is None:
        return None
    sub = day[day["ticker"].astype(str) == str(ticker)]
    if sub.empty:
        return None
    return sub.sort_values("time").reset_index(drop=True)


def clear_cache() -> None:
    _load_day.cache_clear()


# ─── 일별분봉 소급 한도 실측 (verify_connection 【9】에서도 호출) ─────────────
PROBE_OFFSETS = [1, 7, 30, 90, 180, 365]


def probe_history(ticker: str = "005930") -> list[dict]:
    """과거 N일 전 일자들의 일별분봉을 1콜씩 — 어느 시점까지 데이터가 오는지 실측.

    KIS가 소급 한도를 문서화하지 않아 이것이 유일한 확정 방법. 실키 필요."""
    if mock_allowed():
        return [{"offset_days": o, "date": None, "bars": None,
                 "note": "mock 모드 — 실키(KIS_USE_MOCK=0)에서만 실측 가능"}
                for o in PROBE_OFFSETS]
    from src.execution.kis_client import get_kis_client
    client = get_kis_client()
    out = []
    for o in PROBE_OFFSETS:
        d = datetime.now() - timedelta(days=o)
        while d.weekday() >= 5:  # 주말 회피
            d -= timedelta(days=1)
        ds = d.strftime("%Y%m%d")
        try:
            bars = client.get_minute_bars_dated(ticker, ds)
            out.append({"offset_days": o, "date": ds, "bars": len(bars)})
        except Exception as e:
            out.append({"offset_days": o, "date": ds, "bars": 0, "error": str(e)[:80]})
        time.sleep(0.1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="KIS 분봉 수집기 — 일파일 parquet 적재")
    ap.add_argument("--tickers", help="쉼표 구분 종목코드")
    ap.add_argument("--file", help="종목코드 목록 파일 (한 줄에 하나)")
    ap.add_argument("--date", help="YYYYMMDD (기본 오늘 — 과거면 일별분봉 API)")
    ap.add_argument("--probe", action="store_true", help="일별분봉 소급 한도 실측")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.probe:
        for r in probe_history():
            print(r)
        return
    tickers: list[str] = []
    if args.tickers:
        tickers += [t.strip() for t in args.tickers.split(",") if t.strip()]
    if args.file:
        tickers += [ln.strip() for ln in Path(args.file).read_text().splitlines() if ln.strip()]
    if not tickers:
        ap.error("--tickers 또는 --file 필요")
    print(collect_day(tickers, args.date))


if __name__ == "__main__":
    main()
