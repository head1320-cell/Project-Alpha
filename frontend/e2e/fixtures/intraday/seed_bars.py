"""분봉 백테스트 E2E 가 쓰는 분봉을 심는다 — `MINUTE_BARS_DIR`(저장소 밖)에 일파일을 쓴다. 저장소 루트에서 돌린다.

두 묶음:
  · 손으로 만든 열흘(2026-03-02 ~ 03-13 · 035720) — 봉 넷짜리 하루. 화면의 값을 ★손 계산과 맞추기 위한★ 고정 자료다.
      09:00  시 10,000  고 10,020  저  9,990  종 10,000
      09:01  시 10,000  고 10,060  저 10,000  종 10,060
      09:02  시 10,070  고 10,100  저 10,060  종 10,090
      09:03  시 10,090  고 10,120  저 10,080  종 10,110
    출처 열은 `kis` 로 적는다 — 화면의 '실제 분봉' 경로(알림 없음 · 데이터 무결성 통과)를 보기 위한 것이고, 제공자에게서 받은 값이 아니다.
  · 합성 12일(2026-04-01 ~ 04-16 · 005930 · 000660) — 모의 게이트의 수집기가 만든다(출처 열 `synthetic`).
    화면의 '합성 분봉' 알림과 데이터 무결성 미달을 보기 위한 것이다.

모의 게이트(`KIS_USE_MOCK=1`)에서만 돈다 — 운영 게이트에서 분봉을 지어내지 않는다.
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

WIN = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_060, 10_000, 10_060, 1_000),
       ("090200", 10_070, 10_100, 10_060, 10_090, 1_000), ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)]
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]


def weekdays(start: date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


hand, synthetic = weekdays(date(2026, 3, 2), 10), weekdays(date(2026, 4, 1), 12)
for day in hand:
    mb._write_day_file(pd.DataFrame([("035720", *row, "kis") for row in WIN], columns=COLS), day)
for day in synthetic:
    mb.collect_day(["005930", "000660"], day)
print(json.dumps({"dir": os.environ["MINUTE_BARS_DIR"], "hand": [hand[0], hand[-1]], "synthetic": [synthetic[0], synthetic[-1]]}))
