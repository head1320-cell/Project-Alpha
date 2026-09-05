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
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

ALFRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_FAR_FUTURE = "9999-12-31"

#: 관측기간이 `YYYY-MM-DD` 인가. ★스토어에 `YYYYMM` 이 섞여 있어 필요하다★
#: — 읽을 수 없는 형식은 몇 개월 전인지 모르므로 값을 만들지 않는다.
_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


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


def load_vintage_obs(series_id: str, *, cache: dict | None = None):
    """`(관측, 실패사유)` — ★"없다" 와 "못 읽었다" 를 가른다★

    `_load_vintage_obs` 는 둘 다 `None` 으로 뭉갠다. 그런데 처방이 다르다:

      · 관측 `None`, 사유 `None` → **확인했더니 빈티지가 없다** (적재가 얕다)
      · 관측 `None`, 사유 있음   → **확인하지 못했다** (DB 장애 등) — ★미상★

    이걸 구별하지 않으면 DB 가 잠깐 죽었을 때 소비자가 "빈티지가 없구나" 로 읽고
    조용히 라이브(룩어헤드)로 넘어간다. **하지 않은 진술**이다.

    `cache` 를 주면 계열당 한 번만 읽는다 — 실행 스코프 컨텍스트가 그것을 소유한다.
    ★실패도 캐시한다★ 한 실행 안에서 DB 가 살아났다 죽었다 하면 같은 토큰이 봉마다
    다른 판정을 받아 "전부-아니면-전혀" 가 깨진다.
    """
    if cache is not None and series_id in cache:
        return cache[series_id]
    got = _read_vintage_obs(series_id)
    if cache is not None:
        cache[series_id] = got
    return got


def _read_vintage_obs(series_id: str):
    try:
        from src.data.macro_observation_store import load as _load
    except Exception as e:  # noqa: BLE001
        return None, f"스토어를 불러오지 못했습니다: {e}"
    try:
        obs = _load(series_id) or []
    except Exception as e:  # noqa: BLE001
        logger.debug("빈티지 조회 실패 (%s): %s", series_id, e)
        return None, f"빈티지 조회에 실패했습니다: {type(e).__name__}: {e}"
    obs = [o for o in obs if getattr(o, "vintage_id", "") and o.release_timestamp]
    return (obs or None), None


def _load_vintage_obs(series_id: str, *, cache: dict | None = None):
    """계열의 빈티지 관측을 ★스토어에서 한 번만★ 읽는다. 없거나 못 읽으면 `None`.

    ★빈 `vintage_id` 는 빈티지가 아니다★ (`series_as_of` 와 같은 가드 — 순환 거짓)
    bitemporal 로 말하면 그 행에는 **transaction time 이 없다**. 언제부터 알려진
    값인지 없는 행은 as-of 질의에 답할 수 없다 — 통과시키면 자기가 써 넣은 현재값을
    빈티지라 주장하게 된다.

    ★읽기를 여기 하나로 모은 이유★ — 현재값과 lag 값처럼 **같은 계열을 두 번**
    필요로 하는 소비자가 생겼다. 각자 읽으면 조회가 배로 늘고, 그때부터 "실행당
    1회" 계약이 조용히 깨진다.

    실패 사유까지 필요하면 `load_vintage_obs` 를 쓴다(미상 ≠ 없음).
    """
    return load_vintage_obs(series_id, cache=cache)[0]


def _shift_period_months(period: str, months: int) -> str | None:
    """관측기간을 `months` 개월 **앞으로**. 형식을 모르면 `None` — ★추측하지 않는다★.

    ★위치가 아니라 달력이다★ 목록에서 k칸 뒤로 세면 결측이 하나만 있어도 다른
    기간을 집는다. 그리고 그 값도 그럴듯해서 눈으로는 못 잡는다.

    ★날짜를 만들지 않고 문자열로 민다★ `date(y, m, d)` 를 세우면 말일 처리에서
    존재하지 않는 날을 **보정**하게 되는데, 보정된 기간은 스토어에 없는 기간이다.
    여기서는 이동한 키로 **정확히 일치하는 기간만** 찾는다 — 없으면 없는 것이다.

    스토어에는 `YYYYMM` 과 `YYYY-MM-DD` 가 섞여 있다(쓰는 곳이 셋). 읽을 수 없는
    형식이면 몇 개월 전인지 **모르므로** 값을 만들지 않는다.
    """
    m = _PERIOD_RE.match(str(period))
    if not m:
        return None
    total = int(m.group(1)) * 12 + (int(m.group(2)) - 1) - int(months)
    y, mo = divmod(total, 12)
    return f"{y:04d}-{mo + 1:02d}-{m.group(3)}"


def accumulate_for_bars(obs, bar_dates, *, lag_months: int = 0):
    """★순수 함수★ 관측 리스트 → 봉마다 그 시점에 알 수 있었던 값.

    ★왜 단일 `as_of` 로는 안 되는가★
    벡터화 경로는 전 구간을 한 번에 평가한다. 창 전체에 하나의 `as_of` 를 쓰면 창
    마지막 봉의 빈티지가 창 첫 봉에도 적용돼 **창 안에서 여전히 룩어헤드**다.

    `lag_months` 를 주면 그 봉의 최신 관측기간에서 **그만큼 앞선 기간**의 값을
    ★같은 known 집합에서★ 찾는다. 전년비의 분모가 그것이다 — 분자만 그 시점 값이고
    분모가 오늘의 최신 개정본이면 룩어헤드를 분모로 되들인다.

    공표 전 봉은 `NaN` 이다 — ★그때는 알 수 없었다★. 첫 값으로 채우면 룩어헤드다.

    ★스토어를 모른다★ 그래서 DB 픽스처 없이 위 규칙들을 테스트로 못 박을 수 있다.
    """
    import pandas as _pd

    if not obs:
        return None
    idx = _pd.DatetimeIndex(bar_dates)
    if len(idx) > 1 and not idx.is_monotonic_increasing:
        # ★조용히 정렬하지 않는다★ 한 방향으로 훑으며 흡수하므로 오름차순이 전제다.
        # 몰래 정렬하면 호출자가 넘긴 순서와 반환 인덱스가 어긋나 값이 엉뚱한
        # 날짜에 붙는다 — 결과는 그럴듯하고 틀렸다.
        raise ValueError("봉 날짜는 오름차순이어야 합니다 (누적기 전제)")

    # 공표 시각 순으로 훑으며 "그 시점까지 알려진 관측기간별 최신값" 을 누적한다.
    rows = sorted(obs, key=lambda o: (o.release_timestamp, o.observation_period))
    known: dict[str, float] = {}          # 관측기간 → 그때까지 알려진 최신값
    out: list[float | None] = []
    i = 0
    for bar in idx:
        bar_s = bar.strftime("%Y-%m-%d")
        while i < len(rows) and rows[i].release_timestamp[:10] <= bar_s:
            known[rows[i].observation_period] = float(rows[i].value)
            i += 1
        if not known:
            out.append(None)              # ★공표 전 — 알 수 없었다★
            continue
        # 그 봉 이하의 관측기간 중 가장 최근 것(관측기간 자체가 미래면 못 쓴다)
        usable = [p for p in known if p[:10] <= bar_s]
        if not usable:
            out.append(None)
            continue
        p0 = max(usable)
        if not lag_months:
            out.append(known[p0])
            continue
        target = _shift_period_months(p0, lag_months)
        out.append(known.get(target) if target else None)
    return _pd.Series(out, index=idx, dtype="float64")


def pit_series_for_bars(series_id: str, bar_dates, *, obs_cache: dict | None = None):
    """봉마다 ★그 봉 시점에 알 수 있었던★ 값 → `pandas.Series`(bar_dates 인덱스).

    ★봉마다 스토어를 읽지 않는다★ `macro_observation_store.load(series_id=)` 자체는
    PK 선두 컬럼 조건이라 범위 스캔이지만, `as_of` 필터가 **그 계열의 전 빈티지·전
    기간 행을 다 가져온 뒤 파이썬에서** 걸린다(계열당 수만 행). 봉마다 부르면
    O(봉수 × 그 계열 전체)다. **한 번 읽어** 누적한다.
    """
    obs = _load_vintage_obs(series_id, cache=obs_cache)
    if obs is None:
        return None
    return accumulate_for_bars(obs, bar_dates)


def pit_pair_for_bars(series_id: str, bar_dates, *, lag_months: int,
                      obs_cache: dict | None = None):
    """전년비·전월차용 ★쌍★ — `(현재값, lag 값)`. 스토어는 **1회만** 읽는다.

    ★왜 두 시리즈를 한 함수가 주는가★ `pit_series_for_bars` 를 두 번 부르면 조회가
    2회가 되어 "실행당 1회" 계약이 깨진다. 그리고 두 번 읽는 사이에 스토어가 바뀌면
    분자와 분모가 **다른 스냅샷**에서 나온다 — 파생값은 단일 transaction-time
    슬라이스 안에서 계산해야 한다.
    """
    obs = _load_vintage_obs(series_id, cache=obs_cache)
    if obs is None:
        return None
    cur = accumulate_for_bars(obs, bar_dates)
    lag = accumulate_for_bars(obs, bar_dates, lag_months=lag_months)
    if cur is None or lag is None:
        return None
    return cur, lag


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
