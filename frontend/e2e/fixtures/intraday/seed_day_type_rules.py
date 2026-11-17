"""하루 유형 조건(T2) E2E 가 판정할 날을 심는다 — `MINUTE_BARS_DIR`(저장소 밖)에 일파일을 쓴다. 저장소 루트에서 돈다.

모형은 `seed_day_types.py` 가 심은 열이틀(005380 · 035420 · 2026-05-04 ~ 05-19 · 5분 · 유형 넷)로 학습한 것이다 —
끝값 오름차순 번호: 유형 1 = 내림 · 2 = V · 3 = 역V · 4 = 오름. 판정 날은 학습 기간 ★뒤★의 평일 넷이고 날마다 두 종목이 같은 경로다:
    07-01 역V(유형 3) · 07-02 오름(유형 4) · 07-03 내림(유형 1) · 07-06 V(유형 2)
봉 여덟(09:00 ~ 09:07) — 앞의 다섯은 그 유형의 경로(학습 자료와 같은 값 · 첫 봉 시가 10,000 · 10bp = 10원) · 뒤의 셋은 종가 10,000 · 10,010 · 10,020.
→ '하루 유형 3 > 0.5' 는 07-01 에만 09:04(창의 마지막 봉)에 서고 다음 봉(09:05) 시가에 산다 · 하루 끝에 판다(두 종목 = 거래 2건).
출처 열은 `kis` 로 적는다 — 화면의 '실제 분봉' 경로(합성 알림 없음)를 보기 위한 것이고, 제공자에게서 받은 값이 아니다.

모의 게이트(`KIS_USE_MOCK=1`)에서만 돈다 — 운영 게이트나 저장소 안의 분봉 자리에는 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import sys

if os.getenv("KIS_USE_MOCK") != "1" or not os.getenv("MINUTE_BARS_DIR"):
    sys.exit("KIS_USE_MOCK=1 과 MINUTE_BARS_DIR 를 주고 돌린다 — 운영 게이트나 저장소 안의 분봉 자리에는 쓰지 않는다")

sys.path.insert(0, os.getcwd())                 # 저장소 루트에서 돈다 — `src` 를 그 자리에서 찾는다

import pandas as pd  # noqa: E402

import src.data.minute_bars as mb  # noqa: E402

UP, DOWN = [10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0]
VEE, HAT = [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0]
JUDGE = {"2026-07-01": HAT, "2026-07-02": UP, "2026-07-03": DOWN, "2026-07-06": VEE}
TAIL = [0.0, 10.0, 20.0]
TICKERS = ("005380", "035420")
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]


def bars(ticker: str, path: list[float]) -> list[tuple]:
    out, prev = [], 10_000.0
    for m, p in enumerate(path):
        close = 10_000.0 + p
        out.append((ticker, f"09{m:02d}00", prev, max(prev, close), min(prev, close), close, 1_000.0, "kis"))
        prev = close
    return out


for day, path in JUDGE.items():
    recs = [row for ticker in TICKERS for row in bars(ticker, [*path, *TAIL])]
    mb._write_day_file(pd.DataFrame(recs, columns=COLS), day)
print(json.dumps({"dir": os.environ["MINUTE_BARS_DIR"], "judged": list(JUDGE), "tickers": list(TICKERS), "bars_per_day": 8}))
