"""분봉 백테스트 엔진이 주고받는 값."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class PrevDay:
    """전일의 종가·고가·저가와 그것을 어디서 얻었는가(`minute` 전일 분봉 · `daily` 일봉). 원주가다 — 권리락은 모른다."""

    close: float
    high: float
    low: float
    basis: str
    date: str | None = None        # 그 값이 나온 날 — 바로 앞 거래일이 아닐 수 있다(적재가 빠진 날)


@dataclass(frozen=True, eq=False)
class DayTypeRef:
    """규칙이 쓰는 하루 유형 모형 하나 — 번호 순 중심(k × N · 첫 봉 시가 대비 bp) · 분 수 N · 유형 수 k.

    저장한 모형의 `types[j].path` 그대로다(학습과 같은 배정 — `day_types.assign`)."""

    centroids: np.ndarray
    minutes: int
    k: int


@dataclass(frozen=True, eq=False)
class RuleContext:
    """규칙 맥락 — 그 규칙의 지표가 세션 밖에서 읽어야 하는 것(읽기 전용). 문 층이 사용자의 것만 골라 싣는다.

    ★맥락이 필요한 지표가 맥락 없이 불리면 명시적으로 실패한다★ — 미상으로 두면 그 조건을 쓴 규칙이 조용히 거래 0 이 된다."""

    day_types: Mapping[str, DayTypeRef] = field(default_factory=dict)      # 모형 열쇠 → 모형


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
    context: RuleContext | None = None    # 규칙 맥락 — 쓰는 규칙에만 실린다(걸음 엔진이 자른 세션에도 그대로 잇는다)
