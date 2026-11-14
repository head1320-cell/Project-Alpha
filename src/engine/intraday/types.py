"""분봉 백테스트 엔진이 주고받는 값."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PrevDay:
    """전일의 종가·고가·저가와 그것을 어디서 얻었는가(`minute` 전일 분봉 · `daily` 일봉). 원주가다 — 권리락은 모른다."""

    close: float
    high: float
    low: float
    basis: str
    date: str | None = None        # 그 값이 나온 날 — 바로 앞 거래일이 아닐 수 있다(적재가 빠진 날)


@dataclass(frozen=True)
class Session:
    """한 종목의 하루치 봉. `time` 은 `"HHMMSS"` 오름차순 · 겹침 없음(부르는 쪽이 품질 검사로 걸러 준다)."""

    ticker: str
    date: str                      # YYYY-MM-DD
    time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    source: str                    # kis · synthetic · unknown
    prev: PrevDay | None = None
    market: str | None = None      # 매도세를 정하는 데 쓴다 — 모르면 None(일지가 세금을 미상으로 둔다)
    instrument: str | None = None
    name: str | None = None
