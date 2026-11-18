"""하루 유형 비중을 더한 시장 국면(K5) E2E 가 쓰는 분봉을 심는다 — `MINUTE_BARS_DIR`(저장소 밖)에 일파일을 쓴다. 저장소 루트에서 돌린다.

비중을 더한 국면은 적합 창(750거래일) + 비중 창(20거래일)만큼 앞선 바구니 분봉이 있어야 계산된다. 그래서 길게 심는다:
  · 평일 2021-11-01 ~ 2025-03-31(약 890일) · 005930 · 000660 — 모의 게이트의 수집기가 만든다(출처 열 `synthetic` · 결정적 씨앗).
    판정 기간을 2025-01 ~ 03 으로 두면 읽기 구간(판정 시작일의 1,250 달력일 앞 · 2021-08 말)의 앞 두 달은 분봉이 없다 →
    그 날들이 든 비중 창은 '분봉 없는 날' 미상이고, 적합 창은 그 뒤의 날로 찬다(2021-11-29 ~ 2024-12-31 ≈ 800거래일 ≥ 750).
  · 다른 스펙의 날 · 종목 조합(2026 년의 날들)과 겹치지 않는다 — 최근 한 달 적재 표시도 바뀌지 않는다.
이미 그날 파일이 있으면 다시 만들지 않는다(같은 씨앗이라 같은 값 · 다시 돌려도 빠르다).

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

import src.data.minute_bars as mb  # noqa: E402

TICKERS = ["005930", "000660"]
FIRST, LAST = date(2021, 11, 1), date(2025, 3, 31)

days, d = [], FIRST
while d <= LAST:
    if d.weekday() < 5:
        days.append(d.isoformat())
    d += timedelta(days=1)
made = 0
for day in days:
    if mb._existing_day_path(day) is None:
        mb.collect_day(TICKERS, day)
        made += 1
print(json.dumps({"dir": os.environ["MINUTE_BARS_DIR"], "first": days[0], "last": days[-1], "days": len(days), "made": made}))
