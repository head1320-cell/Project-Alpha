"""KRX·DART·KIS 집계 매크로 계열 + 주기 혼합 규칙 (P4-D2)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
KRX·DART·KIS 는 **종목** 데이터지만 집계하면 매크로다 — 시장폭(등락 비율) ·
신용잔고 · 투자자별 수급 · 시장 밸류에이션. 이미 적재 경로가 있으므로 **새 클라이언트를
만들지 않고 집계 계층만** 올린다.

★그런데 주기가 섞인다 — 그 규칙이 이 모듈의 본체다★
일간(신용잔고·시장폭·수급) · 분기(DART 재무) · 월간(ECOS·FRED)이 한 인덱스에 들어온다.
실측으로 확인했다: 수집기에 리샘플 정책이 **없다**(`"frequency": "m"` 은 FRED 서버측
집계뿐). 월말 `ffill` 로 뭉개면 일간 계열의 고주파 엣지가 통째로 죽는다.

    원 주기                        월간 변환
    ─────────────────────────────  ────────────────────────────────────────────
    일간 (스톡/플로우)             월중 평균 + 월간 모멘텀을 **별도 계열**로
    일간 (리스크: 변동성·스프레드)  월중 평균 + **월중 최대** (꼬리를 평균이 지운다)
    분기 (DART 재무)               공표월에만 관측, 사이는 ffill + `stale_months`
    월간 (ECOS·FRED)               그대로

★원칙은 `ffill` 금지가 아니라 "ffill 한 값을 그 달의 관측인 척하지 않는다" 다★
채운 달은 `stale_months > 0` 을 달고, 모델과 화면이 그걸 보고 다르게 다룰 수 있게 한다.

MIDAS(Mixed Data Sampling)까지는 가지 않는다 — 240관측에 MIDAS 는 또 하나의 과적합
기계다. A8 이 4상태 HMM 을 (관측 48 / 모수 32)로 기각한 것과 같은 판단이다.

★이 환경에는 집계 원천이 없다★
`daily_prices` · `investor_flows` 두 테이블이 **모두 존재하지 않는다**(실측). 그래서
`collect_derived_macro()` 는 값이 아니라 사유를 낸다 — 0 으로 채우면 화면이 "시장폭이
0" 으로 읽는다. 키는 값이 없어도 존재한다(M1-S 계약).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Aggregation(str, Enum):
    """일간/분기 관측을 월간으로 내리는 방법."""

    MEAN = "mean"                          # 월중 평균 — 일간 스톡/플로우의 기본
    MAX = "max"                            # 월중 최대 — 리스크 계열의 꼬리 보존
    LAST_WITH_STALENESS = "last_stale"     # 분기 저빈도 — ffill + 몇 달 끌었는지


@dataclass(frozen=True)
class MonthlyPoint:
    """월간 관측 하나.

    `stale_months` 가 이 자료구조의 존재 이유다 — 0 은 그 달에 실제 관측이 있었다는
    뜻이고, 양수는 그만큼 전에 공표된 값을 끌어왔다는 뜻이다. 둘을 같은 자리에
    같은 모양으로 넣으면 저빈도 데이터가 고빈도인 척한다.
    """

    period: str            # "YYYYMM"
    value: float
    stale_months: int = 0


@dataclass(frozen=True)
class DerivedSeriesSpec:
    """집계 매크로 계열 하나의 선언.

    ★규칙 없는 계열을 만들지 않는다★ 집계 방법과 원 주기를 안 적으면 그 계열은
    어딘가에서 조용히 뭉개진다. `reason_when_missing` 은 원천이 없을 때 화면이
    그릴 문장이다 — 사유 없는 미가용을 만들지 않기 위해 스펙에 함께 둔다.
    """

    key: str
    label: str
    unit: str
    source: str                 # KRX | KIS | DART
    source_table: str           # 존재 확인 대상
    source_freq: str            # "daily" | "quarterly"
    how: Aggregation
    reason_when_missing: str
    momentum_key: str | None = None   # 모멘텀을 별도 계열로 낼 때의 키


def _period_of(day: str) -> str:
    """'YYYY-MM-DD' → 'YYYYMM'. 구분자 유무 모두 받는다."""
    t = day.replace("-", "")
    return t[:6]


def _month_add(period: str, n: int) -> str:
    y, m = int(period[:4]), int(period[4:6])
    idx = (y * 12 + (m - 1)) + n
    return f"{idx // 12:04d}{idx % 12 + 1:02d}"


def to_monthly(points: list[tuple[str, float]], *, how: Aggregation,
               fill_until: str | None = None) -> list[MonthlyPoint]:
    """일간·분기 관측 → 월간 계열.

    ★관측이 없는 달은 점을 만들지 않는다★ (`LAST_WITH_STALENESS` 제외 — 그건
    끌어오는 것이 목적이고, 끌어온 사실을 `stale_months` 로 밝힌다.) 0 으로 채우면
    "값이 0" 과 "관측 없음" 이 같은 모양이 된다.

    `fill_until` 은 `YYYY-MM` 또는 `YYYYMM` — ffill 의 끝이다. 끝을 안 정하면 죽은
    값이 영원히 최신인 척한다.
    """
    if not points:
        return []

    buckets: OrderedDict[str, list[float]] = OrderedDict()
    for day, value in sorted(points):
        if value is None:
            continue
        buckets.setdefault(_period_of(day), []).append(float(value))

    if how is Aggregation.MEAN:
        return [MonthlyPoint(p, sum(v) / len(v)) for p, v in buckets.items()]
    if how is Aggregation.MAX:
        return [MonthlyPoint(p, max(v)) for p, v in buckets.items()]

    # ── LAST_WITH_STALENESS — 공표월은 stale 0, 이후 끌어온 달은 1, 2 … ──────
    published = [(p, v[-1]) for p, v in buckets.items()]
    end = _period_of(fill_until) if fill_until else published[-1][0]
    out: list[MonthlyPoint] = []
    for i, (period, value) in enumerate(published):
        nxt = published[i + 1][0] if i + 1 < len(published) else None
        cur, carried = period, 0
        while cur <= end and (nxt is None or cur < nxt):
            out.append(MonthlyPoint(cur, value, carried))
            cur, carried = _month_add(cur, 1), carried + 1
    return out


def momentum(monthly: list[MonthlyPoint], *, months: int = 3) -> list[MonthlyPoint]:
    """월간 계열 → n개월 변화율(%) — **별도 계열**이다.

    ★평균만 남기면 "얼마나 빨리 변하고 있는가" 가 사라진다★ 일간 원천을 월중 평균으로
    내리는 순간 고주파 엣지가 죽으므로, 같은 자리를 덮지 않고 옆에 계열을 하나 더 둔다.

    되돌아볼 구간이 모자란 앞부분은 **값을 만들지 않는다**. 0 기준의 변화율은 정의되지
    않으므로 그 달도 건너뛴다 — 무한대를 내면 하류가 그것을 수치로 받는다.
    """
    out: list[MonthlyPoint] = []
    for i in range(months, len(monthly)):
        base = monthly[i - months].value
        if base == 0:
            continue
        out.append(MonthlyPoint(monthly[i].period,
                                (monthly[i].value / base - 1.0) * 100.0))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 계열 선언 — 규칙 없는 계열은 없다
# ═══════════════════════════════════════════════════════════════════════════════
_PRICES = "daily_prices"
_FLOWS = "investor_flows"

_NO_PRICES = ("KRX 일별 전종목(`daily_prices`)이 적재되지 않았습니다 — "
              "`python -m src.data.krx_ingest` 로 백필한 뒤 집계됩니다.")
_NO_FLOWS = ("투자자별 수급(`investor_flows`)이 적재되지 않았습니다 — "
             "KIS 키를 넣고 수급 동기화를 돌린 뒤 집계됩니다.")

_SPECS: tuple[DerivedSeriesSpec, ...] = (
    DerivedSeriesSpec(
        key="KR_BREADTH", label="시장폭(상승 종목 비율)", unit="%",
        source="KRX", source_table=_PRICES, source_freq="daily",
        how=Aggregation.MEAN, momentum_key="KR_BREADTH_MOM3",
        reason_when_missing=_NO_PRICES),
    DerivedSeriesSpec(
        key="KR_NEW_HIGH_RATIO", label="신고가 종목 비율", unit="%",
        source="KRX", source_table=_PRICES, source_freq="daily",
        how=Aggregation.MEAN, momentum_key="KR_NEW_HIGH_RATIO_MOM3",
        reason_when_missing=_NO_PRICES),
    DerivedSeriesSpec(
        key="KR_XSECT_VOL", label="종목간 수익률 분산(횡단면 변동성)", unit="%",
        source="KRX", source_table=_PRICES, source_freq="daily",
        # ★리스크 계열이라 월중 최대를 쓴다★ 평균은 사건이 있었다는 사실을 지운다.
        how=Aggregation.MAX,
        reason_when_missing=_NO_PRICES),
    DerivedSeriesSpec(
        key="KR_TURNOVER", label="시장 회전율(거래대금/시총)", unit="%",
        source="KRX", source_table=_PRICES, source_freq="daily",
        how=Aggregation.MEAN, momentum_key="KR_TURNOVER_MOM3",
        reason_when_missing=_NO_PRICES),
    DerivedSeriesSpec(
        key="KR_FOREIGN_NET", label="외국인 순매수(시장 합계)", unit="억원",
        source="KIS", source_table=_FLOWS, source_freq="daily",
        how=Aggregation.MEAN, momentum_key="KR_FOREIGN_NET_MOM3",
        reason_when_missing=_NO_FLOWS),
    DerivedSeriesSpec(
        key="KR_INSTITUTION_NET", label="기관 순매수(시장 합계)", unit="억원",
        source="KIS", source_table=_FLOWS, source_freq="daily",
        how=Aggregation.MEAN, momentum_key="KR_INSTITUTION_NET_MOM3",
        reason_when_missing=_NO_FLOWS),
)


def derived_series_specs() -> tuple[DerivedSeriesSpec, ...]:
    return _SPECS


# ═══════════════════════════════════════════════════════════════════════════════
# 수집 — 원천이 없으면 **없다고 답한다**
# ═══════════════════════════════════════════════════════════════════════════════
def _table_exists(table: str) -> bool:
    try:
        from sqlalchemy import text

        from src.database import get_engine
        with get_engine().connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))  # noqa: S608 — 내부 상수만
        return True
    except Exception:
        return False


def collect_derived_macro() -> dict[str, dict[str, Any]]:
    """선언된 모든 집계 계열의 상태 맵.

    ★키는 값이 없어도 존재한다 (M1-S 계약)★ 키가 사라지면 화면은 "그 지표를 안 본다"
    로, `0` 이 들어가면 "0 이다" 로 읽는다 — 둘 다 거짓이다.

    ★합성하지 않는다★ 원천 테이블이 없으면 값 없이 사유만 낸다. `mock_gate` 가
    세운 원칙과 같다: 운영에서 조회가 실패하면 합성값으로 가리지 않는다.
    """
    have: dict[str, bool] = {}
    out: dict[str, dict[str, Any]] = {}
    for spec in _SPECS:
        if spec.source_table not in have:
            have[spec.source_table] = _table_exists(spec.source_table)
        block: dict[str, Any] = {
            "label": spec.label, "unit": spec.unit, "source": spec.source,
            "source_freq": spec.source_freq, "aggregation": spec.how.value,
        }
        if not have[spec.source_table]:
            out[spec.key] = {**block, "available": False, "value": None,
                             "monthly": [], "reason": spec.reason_when_missing}
            continue
        # 원천이 있어도 이 환경에서 실제 집계가 검증된 적은 없다 — 값이 나오는 경로는
        # 백필된 환경에서 `verify_connection.py` 로 확인한 뒤 열린다(M1-I 관례).
        out[spec.key] = {**block, "available": False, "value": None, "monthly": [],
                         "reason": (f"`{spec.source_table}` 은 있지만 집계 파이프라인이 "
                                    "실데이터로 검증된 적이 없습니다 — 백필된 환경에서 "
                                    "확인한 뒤 사람이 엽니다.")}
    return out
