"""하루 유형 E2E 가 쓰는 분봉을 심는다 — `MINUTE_BARS_DIR`(저장소 밖)에 일파일을 쓴다. 저장소 루트에서 돌린다.

유형 넷을 심은 열이틀(2026-05-04 ~ 05-19 평일 · 005380 · 035420 = 24표본) — 화면의 그림 값을 ★손 계산과 맞추기 위한★ 고정 자료다.
봉 다섯(09:00 ~ 09:04) · 첫 봉 시가 10,000 · 종가 = 10,000 + bp(10bp = 10원). 표본 i(날 순 · 종목 순)는 유형 i % 4:
    오름   +10 +20 +30 +40 +50     내림   −10 −20 −30 −40 −50
    V     −10 −20 −30 −20 −10     역V   +10 +20 +30 +20 +10
→ 끝값 오름차순 번호: 유형 1 = 내림(−50) · 2 = V(−10) · 3 = 역V(+10) · 4 = 오름(+50) · 유형마다 표본 6개.
출처 열은 `kis` 로 적는다 — 화면의 '실제 분봉' 경로(합성 알림 없음)를 보기 위한 것이고, 제공자에게서 받은 값이 아니다.
★뺀 표본이 있는 모형★ — 000270 · 068270 에 같은 네 유형을 열이틀(2026-06-01 ~ 06-16) 심고, 06-17 은 000270 의 봉 셋만 둔다
→ 학습 표본 24 · 뺀 표본 둘(000270 = 구간이 모자람 `short_window` · 068270 = 그날 봉 없음 `no_bars`).
합성 모형의 화면은 `seed_bars.py` 의 합성 12일(005930 · 000660)로 본다.

모의 게이트(`KIS_USE_MOCK=1`)에서만 돈다 — 운영 게이트나 저장소 안의 분봉 자리에는 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

if os.getenv("KIS_USE_MOCK") != "1" or not os.getenv("MINUTE_BARS_DIR"):
    sys.exit("KIS_USE_MOCK=1 과 MINUTE_BARS_DIR 를 주고 돌린다 — 운영 게이트나 저장소 안의 분봉 자리에는 쓰지 않는다")

sys.path.insert(0, os.getcwd())                 # 저장소 루트에서 돌린다 — `src` 를 그 자리에서 찾는다

import pandas as pd  # noqa: E402

import src.data.minute_bars as mb  # noqa: E402

PATHS = ([10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0],
         [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0])
TICKERS = ("005380", "035420")
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]


def weekdays(start: date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


EXCL_TICKERS = ("000270", "068270")


def bars(ticker: str, path: list[float]) -> list[tuple]:
    out, prev = [], 10_000.0
    for m, p in enumerate(path):
        close = 10_000.0 + p
        out.append((ticker, f"09{m:02d}00", prev, max(prev, close), min(prev, close), close, 1_000.0, "kis"))
        prev = close
    return out


def plant(days: list[str], tickers: tuple[str, ...]) -> int:
    i = 0
    for day in days:
        recs = []
        for ticker in tickers:
            recs += bars(ticker, PATHS[i % 4])
            i += 1
        mb._write_day_file(pd.DataFrame(recs, columns=COLS), day)
    return i


days = weekdays(date(2026, 5, 4), 12)
samples = plant(days, TICKERS)
excl = weekdays(date(2026, 6, 1), 13)
excl_samples = plant(excl[:12], EXCL_TICKERS)
mb._write_day_file(pd.DataFrame(bars(EXCL_TICKERS[0], PATHS[0][:3]), columns=COLS), excl[12])   # 봉 셋 · 068270 없음
print(json.dumps({"dir": os.environ["MINUTE_BARS_DIR"], "planted": [days[0], days[-1]], "samples": samples,
                  "excluded_case": [excl[0], excl[12]], "excluded_case_samples": excl_samples}))
