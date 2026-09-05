"""PIT 매크로 — ALFRED 빈티지 기반 관측치 조회 (look-ahead 구조적 차단).

왜 별도 모듈인가
──────────────────────────────────────────────────────────────────────────────
기존 `src/services/macro_collector.py::FredClient.fetch_series` 는 대시보드용이다.
실측 결과 PIT 목적으로는 세 가지가 어긋나 있었다:

  1. realtime_start/realtime_end 미지정 → FRED 는 **오늘 시점 최신 개정판**을 반환한다.
     2020년 관측치를 요청해도 "2020년에 공표된 값"이 아니라 "지금까지 개정된 값"이 온다.
  2. 응답의 realtime_start 를 버려서 **관측치별 공표시각이 남지 않는다.**
     → 공표시각으로 거를 수가 없었다(필드를 만들려면 지어내야 했다).
  3. frequency="m" 서버측 집계가 월중 공표 타이밍을 뭉갠다.

기존 함수는 **건드리지 않는다**. 매크로 대시보드 20+ 호출부의 동작을 바꾸지 않기 위해
PIT 경로만 여기에 새로 둔다. 두 경로는 목적이 다르다:
  · fetch_series      — "지금 최신 값"     (대시보드)
  · fetch_observations — "그때 알 수 있던 값" (리서치/백테스트)

핵심 규율
──────────────────────────────────────────────────────────────────────────────
`observation_period <= as_of` 만으로는 룩어헤드가 막히지 않는다. 같은 관측기간에
여러 빈티지가 존재하고, 개정판은 나중에 공표되기 때문이다. 반드시
`release_timestamp <= as_of` 를 만족하는 **최신 빈티지**를 골라야 한다.

데이터가 없으면 0 이나 합성값이 아니라 **빈 결과**를 돌려준다(mock_gate 불변식).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

ALFRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_FAR_FUTURE = "9999-12-31"


# ═══════════════════════════════════════════════════════════════════════════════
# 상태 enum — DataStatus 와 ResearchUsage 는 직교한다
# ═══════════════════════════════════════════════════════════════════════════════
class DataStatus(str, Enum):
    """값의 출처/신선도."""
    REAL = "real"
    MOCK = "mock"
    DELAYED = "delayed"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ResearchUsage(str, Enum):
    """이 시리즈를 **어디까지** 쓸 수 있는가. 손으로 지정하지 않고 파생한다."""
    BACKTEST_ELIGIBLE = "backtest_eligible"
    FORWARD_ONLY = "forward_only"
    UNAVAILABLE = "unavailable"


class ForwardOnlyError(ValueError):
    """forward_only 팩터를 과거 시뮬레이션에 쓰려 할 때. 경고가 아니라 거부다."""


def derive_usage(*, has_vintage: bool, depth_ok: bool, lag_known: bool,
                 has_source: bool = True) -> ResearchUsage:
    """"가져올 수 있다" 와 "백테스트에 쓸 수 있다" 는 다르다.

    셋 중 하나라도 어긋나면 과거 시뮬레이션에 쓸 수 없다:
      · has_vintage — 개정 이력을 재구성할 수 있는가(없으면 오늘 값으로 과거를 채점하게 된다)
      · depth_ok    — 요청 구간을 덮을 이력이 있는가
      · lag_known   — 공표 지연이 모델링되어 있는가
    """
    if not has_source:
        return ResearchUsage.UNAVAILABLE
    if has_vintage and depth_ok and lag_known:
        return ResearchUsage.BACKTEST_ELIGIBLE
    return ResearchUsage.FORWARD_ONLY


def assert_backtest_eligible(usage_by_factor: dict[str, ResearchUsage]) -> None:
    """과거 시뮬레이션 진입 게이트. 문제 팩터를 **이름으로** 지목하고 중단한다."""
    bad = sorted(k for k, v in usage_by_factor.items()
                 if v is not ResearchUsage.BACKTEST_ELIGIBLE)
    if bad:
        raise ForwardOnlyError(
            "과거 시뮬레이션에 쓸 수 없는 팩터가 포함되어 있습니다: "
            + ", ".join(f"{k}({usage_by_factor[k].value})" for k in bad)
            + ". 빈티지 이력·구간 길이·공표지연 중 하나가 충족되지 않았습니다."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 관측치 — 타임스탬프 6종을 각각 독립 보관한다
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class MacroObservation:
    series_id: str
    observation_period: str      # 이 수치가 설명하는 기간 (FRED "date")
    release_timestamp: str       # 이 값이 처음 공표된 시각 (ALFRED realtime_start)
    vintage_id: str              # 어느 개정본인가 (realtime_start..realtime_end)
    retrieved_at: str            # 우리가 가져온 시각
    value: float
    data_status: DataStatus = DataStatus.REAL
    market_cutoff: str | None = None       # as_of 에서 쓸 수 있는 마지막 시장 시각
    execution_timestamp: str | None = None  # 실제로 행동 가능한 시각

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["data_status"] = self.data_status.value
        return d


def _http_get(url: str, params: dict | None = None, timeout: float | None = None):
    """테스트에서 monkeypatch 하는 단일 지점 (requests 를 모듈 전역에 두지 않는다)."""
    import requests
    return requests.get(url, params=params, timeout=timeout)


def fetch_observations(
    series_id: str,
    as_of: str,
    *,
    api_key: str | None = None,
    start: str | None = None,
    timeout: float = 10.0,
) -> list[MacroObservation]:
    """`as_of` 시점에 **알 수 있었던** 관측치만 반환한다.

    ALFRED 의미론: realtime_start=realtime_end=as_of 로 고정하면 그 시점에 유효했던
    빈티지만 돌아온다. frequency 는 보내지 않는다(서버측 집계가 공표 타이밍을 뭉갠다).

    키가 없거나 호출이 실패하면 **빈 리스트**. 0 이나 합성값으로 채우지 않는다.
    """
    key = api_key if api_key is not None else os.getenv("FRED_API_KEY", "")
    if not key or len(key) < 10:
        logger.info("FRED 키 미설정 — %s 는 unavailable (합성값 대체 안 함)", series_id)
        return []

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        # ★빈티지 고정★ — 이 두 줄이 없으면 오늘 시점 최신 개정판이 온다.
        "realtime_start": as_of,
        "realtime_end": as_of,
    }
    if start:
        params["observation_start"] = start
    params["observation_end"] = as_of

    try:
        r = _http_get(ALFRED_URL, params=params, timeout=timeout)
        rows = (r.json() or {}).get("observations", []) or []
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 정직하게 빈 결과
        logger.warning("ALFRED 호출 실패 (%s @ %s): %s", series_id, as_of, e)
        return []

    retrieved = datetime.now(timezone.utc).isoformat()
    out: list[MacroObservation] = []
    for o in rows:
        try:
            value = float(o["value"])          # FRED 결측은 "." → ValueError → 건너뜀
        except (KeyError, TypeError, ValueError):
            continue
        rs_raw = o.get("realtime_start")
        rs = rs_raw or as_of
        re_ = o.get("realtime_end") or _FAR_FUTURE
        # 방어: 서버가 as_of 이후 공표분을 섞어 보내더라도 여기서 잘라낸다.
        if rs > as_of:
            continue
        # ★빈티지가 없는 행에 빈티지를 지어내지 않는다★
        # 예전에는 realtime_start 가 없으면 as_of 로 채워 `vintage_id` 를 만들었다. 그러면
        # `has_vintage` 가 참이 되고 `lag_known` 도 (as_of >= 관측기간이라) 참이 되어,
        # **빈티지 정보가 전혀 없는 응답이 backtest_eligible 로 인증된다.** 게이트가 거짓말을
        # 하는 것이라 Phase 8b 에서 고쳤다. 값 자체는 버리지 않는다 — 전방 연구에는 쓸 수 있고,
        # 빈 vintage_id/release_timestamp 가 `derive_usage` 를 통해 등급을 낮춘다.
        out.append(MacroObservation(
            series_id=series_id,
            observation_period=o.get("date", ""),
            release_timestamp=rs_raw or "",
            vintage_id=f"{rs}..{re_}" if rs_raw else "",
            retrieved_at=retrieved,
            value=value,
            data_status=DataStatus.REAL,
        ))

    out.sort(key=lambda x: (x.observation_period, x.release_timestamp))
    return out


def series_as_of(series_id: str, as_of: str | None):
    """`as_of` 시점에 **알 수 있었던** 계열 → `(관측기간들, 값들)`. 없으면 `None`.

    ★이 함수가 공용인 이유★ 예전에는 같은 로직이 `macro_collector._from_vintage_store`
    안에 private 으로만 있었다. 조건식(백테스트)도 같은 판정이 필요해지면서, 복제하면
    두 벌이 갈라진다 — 특히 아래 가드는 한쪽만 빠져도 조용히 거짓 PIT 를 만든다.

    ★가장 미묘한 곳 — `vintage_id` 가 빈 행은 버린다★
    `macro_observation_store.record_series` 의 write-through 행은 `vintage_id=""` 이고,
    `load(as_of=)` 의 필터는 `release_timestamp` 가 빈 행을 **통과시킨다**(그 함수가
    스스로 적어 둔 규칙). 거르지 않으면 **자기가 써 넣은 현재값**을 빈티지로 되읽어
    PIT 를 주장하게 된다 — 순환 거짓이다.

    ★빈티지에서 읽은 계열은 스토어에 되쓰지 않는다★ 순환이고 빈티지 행을 사본으로
    오염시킨다. 이 함수는 읽기 전용이다.
    """
    try:
        from src.data.macro_observation_store import load as _load
    except Exception:  # noqa: BLE001
        return None
    try:
        obs = _load(series_id, as_of=as_of) or []
    except Exception as e:  # noqa: BLE001 — 조회 실패는 "빈티지 없음" 이지 오류가 아니다
        logger.debug("빈티지 조회 실패 (%s): %s", series_id, e)
        return None

    obs = [o for o in obs if getattr(o, "vintage_id", "")]
    if not obs:
        return None
    picked = latest_vintage_per_period(obs)
    if not picked:
        return None
    return ([o.observation_period for o in picked], [float(o.value) for o in picked])


def pit_series_for_bars(series_id: str, bar_dates):
    """봉마다 ★그 봉 시점에 알 수 있었던★ 값 → `pandas.Series`(bar_dates 인덱스).

    ★왜 단일 `as_of` 로는 안 되는가★
    벡터화 경로는 전 구간을 한 번에 평가한다. 창 전체에 하나의 `as_of` 를 쓰면 창
    마지막 봉의 빈티지가 창 첫 봉에도 적용돼 **창 안에서 여전히 룩어헤드**다.
    봉마다 다른 빈티지가 필요하다.

    ★그렇다고 봉마다 스토어를 읽지 않는다★ `macro_observation_store.load()` 는 전체
    스캔 + 파이썬 필터이고 인덱스도 없다. 봉마다 부르면 O(봉수 × 계열 전체)다.
    **한 번 읽어** 관측을 `(공표시각, 관측기간)` 으로 정렬한 뒤 봉을 훑으며 누적한다.

    공표 전 봉은 `NaN` 이다 — ★그때는 알 수 없었다★. 첫 값으로 채우면 룩어헤드다.
    """
    import pandas as _pd

    try:
        from src.data.macro_observation_store import load as _load
    except Exception:  # noqa: BLE001
        return None
    try:
        obs = _load(series_id) or []
    except Exception as e:  # noqa: BLE001
        logger.debug("빈티지 조회 실패 (%s): %s", series_id, e)
        return None

    # ★빈 `vintage_id` 는 빈티지가 아니다★ (`series_as_of` 와 같은 가드 — 순환 거짓)
    obs = [o for o in obs if getattr(o, "vintage_id", "") and o.release_timestamp]
    if not obs:
        return None

    idx = _pd.DatetimeIndex(bar_dates)
    # 공표 시각 순으로 훑으며 "그 시점까지 알려진 관측기간별 최신값" 을 누적한다.
    obs.sort(key=lambda o: (o.release_timestamp, o.observation_period))
    known: dict[str, float] = {}          # 관측기간 → 그때까지 알려진 최신값
    out: list[float | None] = []
    i = 0
    for bar in idx:
        bar_s = bar.strftime("%Y-%m-%d")
        while i < len(obs) and obs[i].release_timestamp[:10] <= bar_s:
            known[obs[i].observation_period] = float(obs[i].value)
            i += 1
        if not known:
            out.append(None)              # ★공표 전 — 알 수 없었다★
            continue
        # 그 봉 이하의 관측기간 중 가장 최근 것(관측기간 자체가 미래면 못 쓴다)
        usable = [p for p in known if p[:10] <= bar_s]
        out.append(known[max(usable)] if usable else None)
    return _pd.Series(out, index=idx, dtype="float64")


def latest_vintage_per_period(obs: list[MacroObservation]) -> list[MacroObservation]:
    """관측기간별로 **as_of 시점 기준 최신 빈티지** 하나만 남긴다.

    fetch_observations 가 이미 as_of 로 잘라 두었으므로, 여기서는 같은 기간에 남은
    빈티지 중 공표시각이 가장 늦은 것을 고르면 그것이 "그때 알던 최신값"이다.
    """
    best: dict[str, MacroObservation] = {}
    for o in obs:
        cur = best.get(o.observation_period)
        if cur is None or o.release_timestamp > cur.release_timestamp:
            best[o.observation_period] = o
    return [best[k] for k in sorted(best)]
