# 대상 경로: src/data/minute_bars.py
#
# 분봉 적재·로더 — 두 소비자의 데이터 계층.
#   ① 기존 백테스트 엔진의 하이브리드 체결("신호는 일봉, 체결만 분봉" — 그 엔진의 규칙으로 남는다)
#   ② 분봉 백테스트(`src/engine/intraday` — 신호도 분봉. ADR 006 §3 · 2026-11-14 승인)
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
#
# ★출처는 행 단위다★ (`source` 열 — `kis` · `synthetic` · 열이 없는 옛 파일은 `unknown`).
# 일파일은 게이트를 모른다: 모의 모드로 수집한 파일을 운영 프로세스가 읽을 수 있다. 그래서
# ★운영 게이트의 로더는 합성 행을 내주지 않는다★(`None` + 사유 — 엔진은 일봉 모델로 떨어지고 그렇게 센다).
# 출처 미상 행은 막지 않되 라벨이 따라간다 — 미상은 실데이터가 아니다.

from __future__ import annotations

import argparse
import logging
import os
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.mock_gate import mock_allowed

logger = logging.getLogger(__name__)

COLUMNS = ["ticker", "time", "open", "high", "low", "close", "volume"]

#: 행의 출처. ★`unknown` 은 "출처 열이 생기기 전에 쓰인 파일"이다 — 실데이터라는 뜻이 아니다.★
SOURCE_KIS = "kis"
SOURCE_SYNTHETIC = "synthetic"
SOURCE_UNKNOWN = "unknown"
SOURCES = (SOURCE_KIS, SOURCE_SYNTHETIC, SOURCE_UNKNOWN)
STORED_COLUMNS = [*COLUMNS, "source"]

#: `load_day_frame` 이 표를 주지 못할 때의 사유.
DAY_REASONS = {
    "not_loaded": "이 날짜의 분봉이 적재돼 있지 않습니다.",
    "synthetic_rows_blocked": "적재된 분봉이 전부 모의 모드에서 만든 합성값이라 운영에서는 쓰지 않습니다.",
    "unreadable": "이 날짜의 분봉 파일을 읽지 못했습니다.",
}


@dataclass(frozen=True)
class DayBars:
    """하루치 분봉과 그 사정. `frame` 은 `STORED_COLUMNS`(출처 열 포함) · 없으면 `reason` 이 까닭을 말한다."""

    frame: pd.DataFrame | None
    reason: str | None
    blocked_rows: int = 0          # 운영 게이트가 내주지 않은 합성 행 수
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
    df = (pd.read_parquet(path) if path.suffix == ".parquet"
          else pd.read_csv(path, dtype={"ticker": str, "time": str, "source": str}))
    if "source" not in df.columns:
        df["source"] = SOURCE_UNKNOWN              # 출처 열이 생기기 전의 파일 — 미상
    else:
        df["source"] = df["source"].where(df["source"].isin(SOURCES), SOURCE_UNKNOWN)
    return df


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
    # 씨앗은 내용에서 나온다 — `hash()` 는 프로세스마다 달라 "결정적"이 아니었다.
    rng = np.random.RandomState(zlib.crc32(f"{ticker}|{date}".encode()) % (2**31))
    anchor = 10_000 + (zlib.crc32(str(ticker).encode()) % 90) * 1_000
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


def _fetch_with_source(ticker: str, date: str) -> tuple[list[dict], str]:
    """KIS 분봉 1종목 — 당일이면 당일분봉, 과거면 일별분봉. mock 모드는 합성.

    ★출처는 값을 만든 바로 그 갈래가 정한다★ — 따로 게이트를 다시 읽어 맞히지 않는다."""
    if mock_allowed():
        return _mock_minute_bars(ticker, date), SOURCE_SYNTHETIC
    from src.execution.kis_client import get_kis_client
    client = get_kis_client()
    today = datetime.now().strftime("%Y-%m-%d")
    if date == today:
        return client.get_minute_bars_today(ticker), SOURCE_KIS
    return client.get_minute_bars_dated(ticker, date.replace("-", "")), SOURCE_KIS


def _fetch_minute_bars(ticker: str, date: str) -> list[dict]:
    return _fetch_with_source(ticker, date)[0]


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
            bars, source = _fetch_with_source(tk, date)
        except Exception as e:
            logger.warning(f"분봉 수집 실패 {tk} {date}: {e}")
            failed += 1
            continue
        if not bars:
            failed += 1
            continue
        for b in bars:
            rows.append({"ticker": tk, **b, "source": source})
        ok += 1
        if throttle > 0 and not mock_allowed():
            time.sleep(throttle)
    out_path = found
    if rows:
        new_df = pd.DataFrame(rows, columns=STORED_COLUMNS)
        for c in ("open", "high", "low", "close"):
            new_df[c] = new_df[c].astype(np.float32)
        # 거래량은 깎지 않는다 — float32 는 16,777,216 을 넘는 정수를 정확히 담지 못한다(저가주의 분당 거래량).
        new_df["volume"] = new_df["volume"].astype(np.float64)
        if existing is not None:
            existing = existing.astype({"volume": np.float64})
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


def load_day_frame(date: str) -> DayBars:
    """하루치 분봉(모든 종목 · 출처 열 포함)과 그 사정.

    ★운영 게이트에서는 합성 행을 뺀다★ — 게이트는 부르는 시점에 읽는다(캐시된 일파일은 게이트를 모른다).
    남는 행이 없으면 표 대신 사유를 준다. 출처 미상 행은 그대로 주되 라벨이 따라간다."""
    date = _norm_date(date)
    if _existing_day_path(date) is None:
        return DayBars(None, "not_loaded")
    day = _load_day(date)
    if day is None:
        return DayBars(None, "unreadable")
    if mock_allowed():
        return DayBars(day, None)
    synthetic = day["source"] == SOURCE_SYNTHETIC
    blocked = int(synthetic.sum())
    if blocked == len(day):
        return DayBars(None, "synthetic_rows_blocked" if blocked else "not_loaded", blocked)
    return DayBars(day[~synthetic] if blocked else day, None, blocked)


def load_minute_bars(ticker: str, date: str) -> pd.DataFrame | None:
    """(종목, 일자) 분봉 — 적재돼 있으면 time 오름차순 DataFrame, 없으면 None.

    None이면 호출부(하이브리드 체결)가 일봉 모델로 폴백 — 기존 동작 불변.
    운영 게이트에서는 합성 행이 없는 것으로 친다(`load_day_frame`). 돌려주는 열은 예전 그대로(`COLUMNS`)다."""
    day = load_day_frame(date).frame
    if day is None:
        return None
    sub = day[day["ticker"].astype(str) == str(ticker)]
    if sub.empty:
        return None
    return sub.sort_values("time").reset_index(drop=True)[COLUMNS]


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
    # ★진단 도구는 사유를 돌려준다★ 이 함수는 mock 모드에서도 예외 대신 `note` 를
    # 담은 행을 낸다 — 키가 없을 때도 같은 모양이어야 호출자가 분기하지 않는다.
    from src.execution.kis_client import try_kis_client
    client, reason = try_kis_client()
    if client is None:
        return [{"offset_days": o, "date": None, "bars": None, "note": reason}
                for o in PROBE_OFFSETS]
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
