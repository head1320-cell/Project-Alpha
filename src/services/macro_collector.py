"""
Multi-Source Macro Collector — Phase 4
==========================================================================
한국은행(BOK ECOS) + FRED + 시장 데이터 통합 수집 + 정규화 파이프라인.

핵심 지표 (10종):
  · 한국: 기준금리, 국고채 3년, 국고채 10년, CPI, USD/KRW, KOSPI
  · 미국: Fed Funds Rate, T10Y, T2Y, T10Y2Y, VIX, DXY, Gold

정규화:
  · Z-Score: 5년 평균/표준편차 기준 표준화
  · Percentile: 5년 데이터 내 백분위 (0-100)
  · MoM Change: 전월 대비 변화율

방어적 프로그래밍:
  · BOK/FRED API key 없어도 Mock 데이터로 정상 동작
  · 외부 API 장애 시 마지막 로컬 캐시 반환
  · Rate Limit (BOK: 분당 100회, FRED: 일 120회) 대응

환경변수:
  BOK_API_KEY  — https://ecos.bok.or.kr/api/
  FRED_API_KEY — https://fred.stlouisfed.org/docs/api/

캐시: SQLite-based (외부 API 호출 최소화).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from src.data.source_registry import (
    ECOS,
    ecos_collection_targets,
    fred_collection_targets,
    specs_by_provider,
)

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

#: ★수집 경로가 빈티지를 가져오는가★ — 사실이 **있는 곳**에 둔다.
#:
#: 국면 축(`regime_axes.axis_revision_status`)이 이 값을 읽어 "PIT 관리됨" 을
#: 판정한다. ★이것은 사실 진술이지 스위치가 아니다★ — 코드가 하지 않는 일을
#: 참이라 적으면 그것은 승인 집행이 아니라 거짓 선언이고,
#: `tests/test_axis_revision_status.py` 가 `tokenize` 로 소스와 대조해 잡는다.
#:
#: ★오늘 참인 이유★ `collect_all()` 이 계열마다 `macro_observation_store` 를
#: **as-of 로 조회**하고(`_from_vintage_store`), 빈티지가 있으면 그것으로 시계열을
#: 만든다. 없으면 기존 경로를 쓰되 `MacroSeries.vintage_used=False` 로 라벨한다.
#:
#: ★그래도 축이 열리지는 않는다★ 판정은 이 값과 **⑶ 그 계열에 실제 빈티지 행이
#: 있는가**(`regime_axes._series_has_vintage`, 관측)의 **논리곱**이다. 빈티지 0건인
#: 오늘은 축 출력이 이전과 완전히 같고, 키가 들어와 빈티지가 쌓인 **계열만** 열린다.
COLLECTOR_READS_VINTAGE = True

BOK_BASE_URL = "https://ecos.bok.or.kr/api"
FRED_BASE_URL = "https://api.stlouisfed.org/fred"


def _history_years() -> int:
    """매크로 시계열 적재 깊이(년). BOK/FRED는 수십 년 제공(과거 5년 하드코딩 제거).

    ★기본 20년 = 240개월 (P4-D3)★
    `capability.REQUIREMENTS["frontier_sample"]` 이 프론티어 모델 학습에 240관측을
    요구한다. 기본값이 15(180개월)면 **키를 정상적으로 넣어도 사다리가 안 올라간다** —
    설정을 따로 만져야만 열리는 천장은 사실상 닫힌 천장이다. 기본값을 요건에 맞춘다.

    이 값은 mock 길이도 함께 정한다(아래 `_generate_mock_series` 호출부). 합성으로
    사다리가 올라가는 것은 `_min_observations(require_real_source=True)` 가 막는다.
    """
    try:
        return max(1, int(os.getenv("MACRO_HISTORY_YEARS", "20")))
    except ValueError:
        return 20


#: 계열당 저장 하한(개월). YoY(13) 변환 후에도 5년 z-표본이 남는 최소치 —
#: 이 값은 예전 `[-72:]` 상한이 실제로 지키려던 **하한**이다.
_MIN_STORE_MONTHS = 72


def _store_cap() -> int:
    """계열당 저장 개월 상한. 적재 깊이에서 유도하되 z-표본 하한을 지킨다 (P4-D3)."""
    return max(_MIN_STORE_MONTHS, _history_years() * 12)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MacroSeries:
    """단일 매크로 지표의 시계열 + 정규화."""
    indicator:    str            # "KR_BASE_RATE", "FRED_T10Y" 등
    name:         str            # 한글명
    unit:         str            # "%", "원", "지수" 등
    source:       str            # "BOK" / "FRED" / "MOCK"
    timestamps:   list[str]      # ISO 날짜
    values:       list[float]

    # 정규화 메트릭
    latest:       float | None = None
    prev:         float | None = None       # 전월값
    yoy:          float | None = None       # YoY %p
    mom_pct:      float | None = None       # MoM %
    z_score:      float | None = None       # 5년 Z-Score
    percentile:   float | None = None       # 5년 Percentile (0-100)
    mean_5y:      float | None = None
    std_5y:       float | None = None
    trend:        str = "flat"                 # "up" | "down" | "flat"
    last_update:  str | None = None
    #: ★이 값이 빈티지에서 왔는가★ 어디서 왔는지 **행마다** 말한다 — 라벨이
    #: 없으면 PIT 값과 현재값이 화면에서 구분되지 않는다.
    vintage_used: bool = False
    #: PIT 조회 시점(`collect_all(as_of=...)`). 라이브면 `None`.
    as_of:        str | None = None

    #: ★`source="unavailable"` 일 때 **왜** 인지★ 값이 왔으면 None 이다.
    #: 예전에는 `source="unavailable"` 한 문자열이 전부라 **키 없음**·**좌표 미검증**·
    #: **검증됐는데 빈 응답**·**파생 원계열 부재** 가 구분되지 않았다. 넷의 처방이
    #: 전부 다른데, 사용자도 우리도 어디를 고쳐야 할지 알 수 없었다.
    reason:       str | None = None


@dataclass
class MacroSnapshot:
    """모든 매크로 지표 통합 스냅샷."""
    timestamp:   str
    series:      dict[str, MacroSeries] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "series": {k: asdict(v) for k, v in self.series.items()},
            "count": len(self.series),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics helpers
# ═══════════════════════════════════════════════════════════════════════════════

#: z-표본 창(개월). 필드명 `mean_5y`·`std_5y` 가 약속하는 값 — 5년 = 60개월.
_Z_WINDOW_MONTHS = 60


def _normalize(values: list[float]) -> dict:
    """Z-Score + Percentile + 추세 계산.

    z·percentile 은 **최근 5년 창**으로 낸다(`_Z_WINDOW_MONTHS`). 추세는 최근
    6개월 vs 이전 6개월이라 창과 무관하다.
    """
    if not values or len(values) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    cleaned = [v for v in values if v is not None and not math.isnan(v)]
    if len(cleaned) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    # ★z-표본 창을 5년으로 고정한다 (P4-D3)★
    #
    # 이 함수는 `mean_5y`·`std_5y` 라는 이름으로 값을 내면서 실제로는 **받은 구간
    # 전부**로 계산하고 있었다. 저장이 72개월이던 시절에는 "대략 5년" 이라 티가 나지
    # 않았지만, 이름이 약속한 것과 다른 값이었다.
    #
    # P4-D3 이 깊이를 240개월로 열자 이 불일치가 **동작으로 터졌다.** mock 은 드리프트
    # 있는 랜덤워크라 구간이 길어질수록 최신값이 전체 평균에서 멀어지고(z ∝ n),
    # 그 결과 국면이 DEFENSIVE·고스트레스로 뒤집혀 타이밍 노출이 0 이 됐다
    # (`test_three_way_endpoint::test_a_real_snapshot_does_not_zero_out_exposure`).
    #
    # 즉 깊이 확장이 만든 새 버그가 아니라 **원래 있던 이름-구현 불일치**가 드러난
    # 것이다. 이름이 약속한 대로 고친다 — 창을 고정하면 z 는 적재 깊이와 무관해지고,
    # 그것이 하류 국면 로직이 처음부터 가정하던 바다.
    window = cleaned[-_Z_WINDOW_MONTHS:]
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    std = math.sqrt(variance)

    latest = cleaned[-1]
    z_score = (latest - mean) / std if std > 0 else 0
    percentile = sum(1 for v in window if v <= latest) / len(window) * 100

    # 추세: 최근 6개월 평균 vs 이전 6개월 평균
    if len(cleaned) >= 12:
        recent = sum(cleaned[-6:]) / 6
        prior = sum(cleaned[-12:-6]) / 6
        diff_pct = (recent - prior) / prior if abs(prior) > 1e-6 else 0
        trend = "up" if diff_pct > 0.02 else "down" if diff_pct < -0.02 else "flat"
    elif len(cleaned) >= 3:
        recent_avg = sum(cleaned[-3:]) / 3
        diff = recent_avg - cleaned[-min(6, len(cleaned))]
        trend = "up" if diff > std * 0.5 else "down" if diff < -std * 0.5 else "flat"
    else:
        trend = "flat"

    return {
        "z_score":    round(z_score, 3),
        "percentile": round(percentile, 1),
        "mean_5y":    round(mean, 4),
        "std_5y":     round(std, 4),
        "trend":      trend,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BOK ECOS Client (한국은행)
# ═══════════════════════════════════════════════════════════════════════════════

# ★`BOK_INDICATORS` 는 P4-D1 에서 삭제됐다★
# 통계표코드로 키를 잡은 6개짜리 사전이었고 **소비자가 0개**였다. 그러면서 실제 조회
# 목록(`bok_targets`)과 다른 값을 들고 있었으므로, 남겨 두면 "문서가 코드와 다른"
# 두 번째 레지스트리가 된다 — CLAUDE.md 가 개수 세지 말고 레지스트리를 읽으라고
# 적어 둔 바로 그 실패다. 조회 좌표는 `source_registry.ecos_collection_targets()`.


class BokClient:
    """한국은행 ECOS API 클라이언트."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("BOK_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 10

    def _throttle(self):
        """분당 100건 → 안전하게 0.7초/회."""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < 0.7:
                time.sleep(0.7 - elapsed)
            self._last_call = time.time()

    def fetch_series(
        self, stat_code: str, item_code: str = "0",
        start: str | None = None, end: str | None = None,
        period: str = "M",     # M=월, D=일, A=년
        limit: int = 1000,
    ) -> tuple[list[str], list[float]]:
        """BOK 시계열 조회 → (timestamps, values).

        Args:
            limit: 응답 행 상한. ★기본값 1000 은 기존 동작이다 — 바꾸지 말 것★
                월별 20년이 240행이라 월 단위 수집에는 충분하다. 그러나
                **일별**은 다르다 — 2005년부터면 5,000행이 넘어서 1000 에
                걸리면 **20년 커브가 4년으로 조용히 잘린다**. 일별을 받는
                호출자(`factor_tokens._ecos_series`)가 큰 값을 넘긴다.
        """
        if not self.is_configured or requests is None:
            return [], []

        # ── 기간 기본값 — ★아는 포맷만 만들고 모르는 것은 거절한다★ ──────
        #
        # 예전 코드는 `"%Y%m" if period == "M" else "%Y"` 였다. 즉 **M 과 A 만**
        # 만들 수 있었고, `period="D"` 로 start/end 를 생략하면 `2006`~`2026` 이라는
        # 일별로는 무효한 범위가 조용히 만들어졌다. 살아 있는 버그는 아니었다 —
        # 유일한 일별 호출자(`factor_tokens._ecos_series`)가 YYYYMMDD 를 명시로
        # 넘긴다. 주기를 일급으로 만들면 그 구멍이 살아나므로 여기서 메운다.
        #
        # ★분기(Q)는 지어내지 않는다★ ECOS 의 분기 TIME 표기(`2024Q1`? `20241`?)를
        # 오프라인에서 확인할 수 없다. 추측한 좌표로 회사채를 국고채라고 불렀던
        # 것과 정확히 같은 종류의 오류이므로, 포맷을 만드는 대신 **거절**한다.
        if period == "Q" and not (start and end):
            logger.warning(
                "BOK 분기 조회 거절 (%s): 분기 TIME 표기가 검증되지 않았습니다 — "
                "지어낸 포맷으로 호출하지 않습니다. start/end 를 명시하면 그대로 씁니다.",
                stat_code)
            return [], []
        _FMT = {"D": "%Y%m%d", "M": "%Y%m", "A": "%Y"}
        if not end:
            end = datetime.now().strftime(_FMT.get(period, "%Y"))
        if not start:
            yr = int(end[:4]) - _history_years()
            start = f"{yr}{end[4:]}"          # M→YYYYMM · D→YYYYMMDD · A→YYYY

        url = (f"{BOK_BASE_URL}/StatisticSearch/{self.api_key}/json/kr/1/{int(limit)}"
               f"/{stat_code}/{period}/{start}/{end}/{item_code}")
        self._throttle()

        try:
            r = requests.get(url, timeout=self.timeout)
            data = r.json()
            rows = data.get("StatisticSearch", {}).get("row", [])
            if not rows:
                return [], []
            timestamps = [row["TIME"] for row in rows]
            values = []
            for row in rows:
                try:
                    values.append(float(row["DATA_VALUE"]))
                except (ValueError, KeyError, TypeError):
                    values.append(None)
            return timestamps, values
        except Exception as e:
            logger.warning(f"BOK 호출 실패 ({stat_code}): {e}")
            return [], []

    # ── 메타 API — ★응답 모양을 모른다는 사실을 설계에 반영한다★ ────────────
    #
    # 서비스명 `StatisticTableList`·`StatisticItemList` 는 이 저장소의 선행 감사
    # 문서 3건에 이미 기록돼 있다(2026-08-26 두 건 · 08-27 §A.4) — 추측이 아니다.
    # ★그러나 응답 **필드명**은 검증된 적이 없다.★ 그래서 파서를 두지 않고 원시
    # dict 를 그대로 돌려준다. 주기 추출은 별도 함수가 하고, 못 찾으면 사유를 낸다.

    def _fetch_meta(self, service: str, path: str = "") -> tuple[list[dict], str | None]:
        """(행, 사유). ★`fetch_series` 와 같은 스로틀·키 판정을 쓴다★

        메타 호출이 따로 스로틀을 갖지 않는 것이 중요하다 — 분당 한도는 서비스별이
        아니라 키별이고, 경로가 둘이면 한도를 넘긴 쪽이 조용히 실패한다.
        """
        if not self.is_configured:
            from src.data.source_registry import REASON_NO_KEY
            return [], REASON_NO_KEY
        if requests is None:
            return [], "requests 를 사용할 수 없습니다."
        url = f"{BOK_BASE_URL}/{service}/{self.api_key}/json/kr/1/{META_PAGE_SIZE}{path}"
        self._throttle()
        try:
            data = requests.get(url, timeout=self.timeout).json()
        except Exception as e:
            return [], f"{service} 호출 실패: {e}"
        rows = (data.get(service) or {}).get("row") or []
        if not rows:
            # ECOS 는 오류를 200 + RESULT 블록으로 돌려주기도 한다. 그 문구를
            # 지어내지 않고 **있으면 그대로** 전달한다.
            res = (data.get("RESULT") or {})
            detail = res.get("MESSAGE") or res.get("CODE")
            return [], f"{service} 응답이 비었습니다." + (f" ({detail})" if detail else "")
        return list(rows), None

    def probe_series(self, stat_code: str, item_code: str, period: str,
                     start: str, end: str, limit: int = 5) -> dict:
        """★프로브 전용★ 원시 응답을 **삼키지 않고** 돌려준다.

        `fetch_series` 는 실패를 `([], [])` 로 삼킨다 — 운영에서는 그것이 옳다
        (호출자는 값이 필요하지 흔적이 필요하지 않다). 그러나 **왜** 비었는지를
        알아내는 것이 목적일 때는 정확히 그 삼킨 것이 필요하다.

        ★운영 경로를 고치지 않고 경로를 하나 더 둔다★ — 대신 같은 `_throttle` 과
        `is_configured` 를 쓴다. 분당 한도는 서비스별이 아니라 **키별**이고, 스로틀
        없는 경로가 하나라도 생기면 한도를 넘긴 쪽이 조용히 실패한다.

        `limit` 이 작다(기본 5) — 이것은 대량 적재가 아니라 **메타 검증**이다.
        """
        out: dict = {"stat_code": stat_code, "item_code": item_code, "period": period,
                     "start": start, "end": end}
        if not self.is_configured:
            from src.data.source_registry import REASON_NO_KEY
            return {**out, "status": "no_key", "reason": REASON_NO_KEY}
        if requests is None:
            return {**out, "status": "no_client", "reason": "requests 를 사용할 수 없습니다."}
        url = (f"{BOK_BASE_URL}/StatisticSearch/{self.api_key}/json/kr/1/{int(limit)}"
               f"/{stat_code}/{period}/{start}/{end}/{item_code}")
        self._throttle()
        try:
            r = requests.get(url, timeout=self.timeout)
            out["http_status"] = getattr(r, "status_code", None)
            data = r.json()
        except Exception as e:
            return {**out, "status": "call_failed", "reason": f"{type(e).__name__}: {e}"}
        rows = (data.get("StatisticSearch") or {}).get("row") or []
        if not rows:
            # ECOS 는 오류를 200 + RESULT 블록으로 돌려주기도 한다. 그 문구를
            # 지어내지 않고 **있으면 그대로** 전달한다.
            res = data.get("RESULT") or {}
            return {**out, "status": "empty", "ecos_code": res.get("CODE"),
                    "ecos_message": res.get("MESSAGE")}
        # ★TIME 은 해석하지 않고 **그대로** 남긴다★ 포맷이 무엇인지가 질문이므로,
        # 파싱해서 정규화하면 답을 지워 버리게 된다.
        return {**out, "status": "ok", "row_count": len(rows),
                "time_sample": [str(r_.get("TIME")) for r_ in rows[:3]],
                "row_keys": sorted(rows[0])}

    def fetch_table_list(self) -> tuple[list[dict], str | None]:
        """통계표 목록 (`StatisticTableList`)."""
        return self._fetch_meta("StatisticTableList")

    def fetch_item_list(self, stat_code: str) -> tuple[list[dict], str | None]:
        """한 통계표의 항목 목록 (`StatisticItemList`)."""
        return self._fetch_meta("StatisticItemList", f"/{stat_code}")


#: 메타 응답에서 주기를 담을 **가능성이 있는** 키들. ★어느 것인지 모른다★ —
#: 실응답을 본 적이 없으므로 후보를 순회하고, 못 찾으면 `None` + 사유다.
#: 하나로 단정해 적으면 그 키가 아닐 때 파서가 조용히 실패한다.
META_CYCLE_KEYS = ("CYCLE", "P_CYCLE", "CYCLE_NAME", "PERIOD")
META_PAGE_SIZE = 1000


def cycle_from_meta_row(row: dict) -> tuple[str | None, str | None]:
    """메타 행에서 공표 주기를 뽑는다 → (주기, 사유).

    ★못 찾으면 조용히 성공한 척하지 않는다★ 기본값 `"M"` 을 돌려주면 그 값은
    "확인된 월별" 과 구분되지 않는다. 그것이 정확히 이 축을 만든 이유다.
    """
    from src.data.source_registry import ECOS_CYCLES

    for k in META_CYCLE_KEYS:
        raw = row.get(k)
        if raw is None:
            continue
        v = str(raw).strip().upper()[:1]
        if v in ECOS_CYCLES:
            return v, None
        return None, (f"주기 필드 {k!r} 의 값 {raw!r} 을 해석할 수 없습니다 — "
                      f"알려진 주기는 {'·'.join(ECOS_CYCLES)} 입니다.")
    return None, (f"응답에 주기 필드가 없습니다 — 후보 {'·'.join(META_CYCLE_KEYS)} 중 "
                  f"어느 것도 없습니다. 실제 키: {sorted(row)[:8]}")


# ═══════════════════════════════════════════════════════════════════════════════
# FRED Client (미 연준)
# ═══════════════════════════════════════════════════════════════════════════════

#: FRED 지표 — ★`source_registry` 가 단일 출처다 (P4-D1)★ ECOS 와 같은 이유로,
#: 레지스트리와 수집기가 계열 목록을 각자 들면 갈라진다.
FRED_INDICATORS = fred_collection_targets()


class FredClient:
    """FRED API 클라이언트."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 10

    def _throttle(self):
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)
            self._last_call = time.time()

    def fetch_series(
        self, series_id: str,
        start: str | None = None, end: str | None = None,
        frequency: str | None = "m",
    ) -> tuple[list[str], list[float]]:
        """FRED 시계열 조회.

        Args:
            frequency: 서버측 집계 주기. ★기본값 `"m"` 은 기존 동작이다 —
                대시보드 수집은 월별로 충분하다. `None` 이면 파라미터를
                **보내지 않아** 제공자 원본 주기(국채금리는 일별)를 받는다.

                ★일별이 필요한 호출자는 반드시 `None` 을 넘길 것★ — `"m"` 으로
                받으면 일별 금리가 월별로 뭉개지고, 일별 봉에 정렬한 뒤 ffill 되어
                **그럴듯해 보인다**. `pit_macro` 가 같은 이유로 빈티지 조회에서
                frequency 를 보내지 않는다(§모듈 독스트링 3번).
        """
        if not self.is_configured or requests is None:
            return [], []

        if not start:
            start = (datetime.now() - timedelta(days=365 * _history_years())).strftime("%Y-%m-%d")
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": end,
        }
        # ★`None` 이면 키 자체를 넣지 않는다★ 빈 문자열을 보내면 FRED 가 거부한다.
        if frequency:
            params["frequency"] = frequency
        self._throttle()

        try:
            r = requests.get(f"{FRED_BASE_URL}/series/observations", params=params, timeout=self.timeout)
            data = r.json()
            obs = data.get("observations", [])
            timestamps = []
            values = []
            for o in obs:
                try:
                    v = float(o["value"])
                    timestamps.append(o["date"])
                    values.append(v)
                except (ValueError, KeyError, TypeError):
                    continue
            return timestamps, values
        except Exception as e:
            logger.warning(f"FRED 호출 실패 ({series_id}): {e}")
            return [], []


# ═══════════════════════════════════════════════════════════════════════════════
# Mock data generators (API key 미설정 시)
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_mock_series(
    indicator: str, length: int = 84,
    base: float = 100, vol: float = 5, trend: float = 0.0,
) -> tuple[list[str], list[float]]:
    """Mock 시계열 생성 (deterministic by indicator hash)."""
    import random
    seed = sum(ord(c) for c in indicator)
    rng = random.Random(seed)

    end = datetime.now().replace(day=1)
    timestamps = []
    values = []
    cur = base
    for i in range(length):
        dt = end - timedelta(days=30 * (length - i - 1))
        timestamps.append(dt.strftime("%Y%m"))
        cur += trend + rng.gauss(0, vol)
        values.append(round(cur, 4))
    return timestamps, values


MOCK_PROFILES = {
    "KR_BASE_RATE":  {"base": 3.50, "vol": 0.08, "trend": -0.005},
    "KR_3Y":         {"base": 3.42, "vol": 0.10, "trend": -0.003},
    "KR_10Y":        {"base": 3.65, "vol": 0.12, "trend": -0.002},
    "KR_CPI":        {"base": 113.4, "vol": 0.3,  "trend": 0.1},
    "USD_KRW":       {"base": 1380, "vol": 12,    "trend": 0.5},
    "KOSPI":         {"base": 2480, "vol": 38,    "trend": 2.5},
    "FEDFUNDS":      {"base": 5.25, "vol": 0.05, "trend": -0.008},
    "DGS3MO":        {"base": 5.30, "vol": 0.08, "trend": -0.009},
    "DGS2":          {"base": 4.45, "vol": 0.12, "trend": -0.012},
    "DGS10":         {"base": 4.20, "vol": 0.15, "trend": -0.010},
    "DGS30":         {"base": 4.35, "vol": 0.14, "trend": -0.008},
    "T10Y2Y":        {"base": -0.25, "vol": 0.18, "trend": 0.015},
    "VIXCLS":        {"base": 16.8, "vol": 4.5,  "trend": 0.0},
    "DTWEXBGS":      {"base": 121.4, "vol": 1.2, "trend": -0.05},
    "CPIAUCSL":      {"base": 308,  "vol": 0.6,  "trend": 0.25},
    "BAMLH0A0HYM2":  {"base": 3.45, "vol": 0.5,  "trend": -0.01},
    # 국면 축 실물 지표 — mock도 현실적 스케일 (기본 {base:100,vol:5}는 실업률 100% 같은 왜곡 유발)
    "KR_LEADING_CYCLE": {"base": 100.2, "vol": 0.35, "trend": -0.02},
    "KR_IP":         {"base": 112.5, "vol": 1.1,  "trend": 0.12},
    "INDPRO":        {"base": 103.2, "vol": 0.5,  "trend": 0.06},
    "UNRATE":        {"base": 4.0,  "vol": 0.12, "trend": 0.008},
    "PAYEMS":        {"base": 158_000, "vol": 250, "trend": 130},
    "GDPC1":         {"base": 22_700, "vol": 70,  "trend": 38},
    "T10YIE":        {"base": 2.30, "vol": 0.07, "trend": 0.001},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Unified Collector
# ═══════════════════════════════════════════════════════════════════════════════

#: `as_of` PIT 요청인데 그 계열에 빈티지가 없을 때. ★현재값을 주지 않는다★
REASON_NO_VINTAGE_FOR_ASOF = (
    "빈티지가 없어 시점 고정 조회에 답할 수 없습니다 — 현재 개정본으로 과거를 "
    "채점하면 그것은 시점 정합이 아니라 개정 편향입니다(`ac938c4`). "
    "ALFRED 빈티지를 적재하면(`macro_vintage_backfill`) 이 계열이 열립니다."
)


#: 저장소 경로에서 계열이 비었을 때의 사유 — "API 키가 없다" 류의 사유와 처방이 다르다.
REASON_NOT_IN_STORE = ("저장된 관측이 없습니다 — 매크로 화면에서 한 번 수집하면 저장됩니다"
                       "(이 경로는 외부를 호출하지 않습니다).")


def _stored_series(key: str) -> tuple[list[str], list[float]]:
    """관측 스토어의 **빈티지 없는** 행 → `(timestamps, values)` (BL2b · `store_only`).

    빈티지 있는 행은 `_from_vintage_store` 가 먼저 본다(그쪽이 우선이다). 여기 남는 것은 수집 파이프라인이
    `record_series` 로 적은 행이라 공표시각이 비어 있다 — 그래서 같은 기간의 여러 조회 중 **가장 늦게 가져온**
    값을 쓴다(`retrieved_at`). 판정 규칙은 공용 `latest_vintage_per_period` 를 그대로 쓴다(두 벌 금지).
    """
    from src.data.macro_observation_store import load
    from src.data.pit_macro import latest_vintage_per_period
    obs = [o for o in load(key) if not o.vintage_id]
    rows = sorted(latest_vintage_per_period(obs, stamp_of=lambda o: o.retrieved_at),
                  key=lambda o: o.observation_period)
    return [o.observation_period for o in rows], [float(o.value) for o in rows]


def _from_vintage_store(key: str, as_of: str | None):
    """관측 스토어에서 **빈티지 있는** 관측만 골라 `(timestamps, values)`.

    ★로직은 `pit_macro.series_as_of` 로 옮겼다★ — 조건식(백테스트)도 같은 판정이
    필요해졌고, 복제하면 두 벌이 갈라진다. 특히 "빈 `vintage_id` 행을 버린다" 가
    한쪽만 빠지면 조용히 거짓 PIT 가 된다. 이 함수는 기존 호출부를 위한 얇은 별칭이다.
    """
    from src.data.pit_macro import series_as_of
    return series_as_of(key, as_of)


class MacroCollector:
    """
    BOK + FRED 통합 수집 + 정규화 + 캐시.

    Usage:
        collector = MacroCollector()
        snapshot = collector.collect_all()
        kr10y = snapshot.series["KR_10Y"]
        print(f"국고채 10년: {kr10y.latest}%, Z={kr10y.z_score}")
    """

    _singleton: MacroCollector | None = None

    @classmethod
    def get_default(cls) -> MacroCollector:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(
        self,
        bok_client: BokClient | None = None,
        fred_client: FredClient | None = None,
        cache_ttl: int = 3600 * 6,  # 6시간 (매크로는 일 1회 갱신)
    ):
        self.bok = bok_client or BokClient()
        self.fred = fred_client or FredClient()
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, MacroSeries]] = {}
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────
    # 핵심 수집
    # ─────────────────────────────────────────────────────────────────────

    def collect_all(self, use_cache: bool = True,
                    as_of: str | None = None, *, store_only: bool = False) -> MacroSnapshot:
        """모든 지표 통합 수집.

        ★두 모드를 라벨한다 — 조용히 섞지 않는다★

            as_of=None   라이브. 빈티지가 있으면 그것을, 없으면 기존 경로를 쓰고
                         `vintage_used=False` 로 남긴다.
            as_of=날짜   PIT 요청. 그 계열에 빈티지가 없으면 ★값을 내지 않는다★ —
                         현재 개정본으로 과거를 채점하는 것이 `ac938c4` 가 막은
                         결함이다.

        기존 호출부 11곳은 전부 `as_of` 없이 부르므로 **동작이 이전과 같다**.

        ★`store_only=True` — 저장된 관측만 (BL2b)★ 외부 API 를 부르지 않고 `macro_observation_store`
        에 쌓인 관측으로 **같은 정규화**를 거친 계열을 만든다. 캐시를 읽지도 쓰지도 않고, 읽은 것을
        다시 적재하지 않으며, 없으면 mock 으로 채우지 않는다(개발 모드에서도). 계산 노드가 운영에서
        계산할 때마다 BOK·FRED 를 부르고 관측을 적재하지 않게 하려는 경로다.
        """
        live = not store_only
        series_map = {}

        # 한국 매크로 (6종)
        # ★조회 좌표는 `source_registry` 가 단일 출처다 (P4-D1)★
        # 예전에는 이 리스트와 레지스트리가 통계표/항목 코드를 **각자** 들고 있었다.
        # 11계열일 땐 눈으로 맞출 수 있었지만 P4-D1 이 33계열로 늘리면서 반드시
        # 갈라진다 — 한쪽에만 계열을 추가하면 "수집은 되는데 상태를 못 내거나"
        # "상태는 있는데 값이 영원히 안 오는" 조합이 생기고 둘 다 조용하다.
        #
        # ★신규 계열은 실호출로 검증된 적이 없다★ 통계표/항목 코드가 틀리면 시리즈가
        # 예외 없이 조용히 빈다. `source_registry` 가 mock 폴백을 막으므로 빈 값이
        # 그럴듯한 숫자로 덮이지 않는다 — 그래야 코드가 틀렸다는 것을 알 수 있다.
        # 검증은 `verify_connection.py::check_ecos`, verified_live 는 사람이 올린다.
        bok_targets = ecos_collection_targets()
        for key, stat, item, name, unit in bok_targets:
            series_map[key] = self._collect_one(
                key=key, name=name, unit=unit,
                # ★기본인자 바인딩★ 바로 아래 FRED 루프는 `lambda fid=fred_id:` 인데
                # 여기만 `lambda: ...(stat, item)` 이라 **늦은 바인딩**이었다. 지금은
                # `_collect_one` 이 같은 반복 안에서 동기로 부르므로 값이 맞아
                # 살아 있는 버그는 아니었지만, 누군가 스레드풀·async 로 바꾸는 순간
                # 11개 시리즈가 전부 마지막 stat 코드를 조회한다. 두 루프의 관례를 맞춘다.
                fetcher=(lambda k=key: _stored_series(k)) if store_only
                else (lambda s=stat, i=item: self.bok.fetch_series(s, i)),
                use_cache=use_cache, as_of=as_of,
                source="BOK", live=live,
            )

        # ── 파생 스프레드 (레지스트리의 `derived_from` 이 정의한다) ──────────
        # ★원계열 둘이 다 있을 때만 계산한다★ 하나라도 없으면 사유를 남기고 값을 내지
        # 않는다 — 한쪽만으로 스프레드를 만드는 것은 합성이다.
        # P4-D1 에서 하드코딩 1건 → 레지스트리 순회로 바꿨다. 파생 계열을 추가할 때
        # 레지스트리에만 적으면 되고, 수집기를 고치는 걸 잊어 키만 있고 값이 영원히
        # 안 오는 조합이 생기지 않는다.
        for spec in specs_by_provider(ECOS):
            if len(spec.derived_from) != 2:
                continue
            minuend, subtrahend = spec.derived_from
            series_map[spec.key] = self._derive_spread(
                series_map.get(minuend), series_map.get(subtrahend),
                key=spec.key, name=spec.label, unit=spec.unit)

        # 미국 매크로 (10종)
        for fred_id, meta in FRED_INDICATORS.items():
            series_map[fred_id] = self._collect_one(
                key=fred_id, name=meta["name"], unit=meta["unit"],
                fetcher=(lambda fid=fred_id: _stored_series(fid)) if store_only
                else (lambda fid=fred_id: self.fred.fetch_series(fid)),
                use_cache=use_cache, as_of=as_of,
                source="FRED", live=live,
            )

        return MacroSnapshot(
            timestamp=datetime.now().isoformat(),
            series=series_map,
        )

    def _derive_spread(self, corp: MacroSeries | None, govt: MacroSeries | None,
                       *, key: str, name: str, unit: str) -> MacroSeries:
        """두 계열의 차이로 만드는 파생 스프레드 (M1-I, P4-D1 에서 일반화).

        ★한쪽만으로 만들지 않는다★ 둘 중 하나라도 없거나 겹치는 관측이 없으면 값 없이
        `source="unavailable"` 로 돌려준다. 한쪽 값을 스프레드처럼 쓰면 그건 합성이고,
        화면은 그것을 실측 스프레드로 읽는다.
        """
        cv = list(corp.values) if corp and corp.values else []
        gv = list(govt.values) if govt and govt.values else []
        n = min(len(cv), len(gv))
        if n == 0:
            # ★파생의 실패 원인은 넷째다★ 키도 좌표도 주기도 아니라 **원계열이
            # 없다**. 어느 다리가 빠졌는지 말해 주지 않으면 사용자는 스프레드
            # 자체가 고장난 줄 안다 — 고쳐야 할 곳은 원계열 쪽이다.
            missing = [n_ for n_, s_ in (("피감수", cv), ("감수", gv)) if not s_]
            return MacroSeries(
                indicator=key, name=name, unit=unit,
                source="unavailable", timestamps=[], values=[],
                reason=(f"원계열이 없어 스프레드를 만들 수 없습니다({'·'.join(missing)} "
                        f"쪽). ★한쪽만으로 만들지 않습니다★ — 한쪽 값을 스프레드처럼 "
                        f"쓰면 그것은 합성이고, 화면은 실측 스프레드로 읽습니다."))

        vals = [round(float(c) - float(g), 4) for c, g in zip(cv[-n:], gv[-n:], strict=False)]
        ts = list(corp.timestamps)[-n:] if corp and corp.timestamps else []
        norm = _normalize(vals)
        latest = vals[-1]
        prev = vals[-2] if len(vals) >= 2 else None
        yoy = (vals[-1] - vals[-13]) if len(vals) >= 13 else None   # %p 단위 → 차이
        return MacroSeries(
            indicator=key, name=name, unit=unit,
            # 원계열이 mock 이면 파생도 mock 이다 — 출처를 승격시키지 않는다.
            source=(corp.source if corp else "unavailable"),
            timestamps=ts, values=vals,
            latest=round(latest, 4), prev=(round(prev, 4) if prev is not None else None),
            yoy=(round(yoy, 3) if yoy is not None else None),
            mom_pct=None,
            z_score=norm["z_score"], percentile=norm["percentile"],
            mean_5y=norm["mean_5y"], std_5y=norm["std_5y"], trend=norm["trend"],
            # ★`last_update` 를 반드시 채운다 — 비우면 PIT 게이트가 이 계열을 거부한다★
            #
            # M1-I 이후 잠복해 있던 결함이다. `observations_from_series` 는
            # `released = last_update or period` 로 공표시각을 정하는데, 여기서
            # `last_update` 를 안 넣으면 `period`("202608")로 폴백한다. 그 문자열을
            # ISO `as_of`("2026-08-16T…")와 비교하면 **다섯 번째 글자에서 '0' > '-'**
            # 라 `"202608" > "2026-08-16T…"` 가 참이 되고, 스냅샷 생성이
            # `LookAheadError` 로 422 를 낸다.
            #
            # 지금까지 안 터진 이유는 유일한 파생 계열(KR_CREDIT_SPREAD)의 원계열
            # KR_CORP3Y 가 미검증이라 **항상 unavailable** 이었기 때문이다. 값이
            # 나오는 파생 계열이 생기는 순간(P4-D1 의 KR_TERM_SPREAD) 드러났다.
            #
            # 스프레드는 두 다리가 **모두** 관측된 뒤에야 알 수 있으므로 늦은 쪽을 쓴다.
            last_update=max(
                (x for x in (getattr(corp, "last_update", None),
                             getattr(govt, "last_update", None)) if x),
                default=datetime.now().isoformat(),
            ),
        )

    def _unavailable_reason(self, key: str, source: str) -> str:
        """수집 실패의 원인 — ★판정 로직은 레지스트리가 갖는다★

        여기서 새로 판정하지 않고 `source_registry.unavailable_reason_for()` 에
        태운다. 사유 문구가 두 곳에 있으면 갈라지고, 갈라진 사유는 틀린 사유다.
        이 함수가 더하는 것은 **어느 클라이언트가 키를 갖고 있었는가** 하나뿐이다.
        """
        from src.data.source_registry import unavailable_reason_for

        client = self.bok if source == "BOK" else self.fred
        return unavailable_reason_for(
            key, configured=bool(getattr(client, "is_configured", False)))

    def _collect_one(
        self, key: str, name: str, unit: str,
        fetcher, use_cache: bool, source: str, as_of: str | None = None,
        live: bool = True,
    ) -> MacroSeries:
        """단일 지표 수집 — 캐시 확인 → 외부 호출 → Mock fallback.

        ★신규 미검증 소스는 mock 으로 채우지 않는다 (M1-I)★
        `source_registry.new_source_mock_allowed()` 가 판정한다. 기존 지표는 영향 없다.
        """
        # ★PIT 조회는 캐시를 쓰지도 남기지도 않는다★ as_of 산출이 캐시에 남으면
        # 다음 라이브 조회가 과거 값을 받는다 — 화면이 조용히 과거를 본다.
        if live and use_cache and as_of is None:
            with self._lock:
                entry = self._cache.get(key)
                if entry:
                    ts, cached = entry
                    if time.time() - ts < self.cache_ttl:
                        return cached

        timestamps, values = [], []
        actual_source = source
        unavailable_reason: str | None = None
        vintage_used = False

        # ★빈티지가 있으면 그것이 우선이다★ 개정 이력이 있는데 현재 개정본을 쓰는
        # 것은 가진 정보를 버리는 것이다.
        vintage = _from_vintage_store(key, as_of)
        if vintage is not None:
            timestamps, values = vintage
            vintage_used = True
        elif as_of is not None:
            # ★PIT 요청에는 현재값을 주지 않는다★ 답할 수 없으면 답하지 않는다.
            actual_source = "unavailable"
            unavailable_reason = REASON_NO_VINTAGE_FOR_ASOF
        else:
            # 외부 API 호출
            try:
                timestamps, values = fetcher()
            except Exception as e:
                logger.warning(f"{source} fetcher 실패 ({key}): {e}")

        # Fallback to Mock — mock 모드만. 운영(KIS_USE_MOCK=0)선 합성 금지 → 정직 unavailable.
        # ★PIT 요청은 mock 으로 채우지 않는다★ 합성값으로 과거를 채점하면 그것은
        # 시점 정합이 아니라 날조다.
        if not values and as_of is None and not live:
            # ★저장소 경로는 합성으로 채우지 않는다★ — 없으면 없다고 말한다(개발 모드에서도).
            actual_source = "unavailable"
            unavailable_reason = REASON_NOT_IN_STORE
        elif not values and as_of is None:
            from src.data.mock_gate import mock_allowed
            from src.data.source_registry import new_source_mock_allowed
            if mock_allowed() and new_source_mock_allowed(key):
                profile = MOCK_PROFILES.get(key, {"base": 100, "vol": 5, "trend": 0})
                # ★mock 길이는 깊이를 따라가지 **않는다** (P4-D3 에서 시도했다 되돌림)★
                #
                # 처음엔 `length=_history_years() * 12` 로 바꿔 mock 도 240개월을 내게
                # 했다. 파이프라인이 20년치를 감당하는지 개발 환경에서 확인하려는
                # 의도였고, D4 의 출처 조건이 있으니 합성으로 프론티어가 열릴 위험도
                # 없었다. 그런데 **실측해 보니 값이 비쌌다.**
                #
                # mock 은 드리프트 있는 랜덤워크(`cur += trend + gauss(0, vol)`)라
                # 구간이 3배가 되면 합성 국면이 DEFENSIVE·고스트레스로 치우치고,
                # 타이밍 노출이 0 으로 떨어져 `test_three_way_endpoint::
                # test_a_real_snapshot_does_not_zero_out_exposure` 를 깨뜨렸다.
                # 그 테스트는 과거 실제 사고(단위/어휘 불일치로 포트폴리오가 전액
                # 위험-오프로 떨어진 것)를 막는 가드라 약화시킬 수 없다.
                #
                # 얻는 것과 잃는 것을 견줬다 — 얻는 것은 "mock 으로도 240 경로를
                # 밟아 본다" 뿐이고, 잃는 것은 합성 국면 상태의 안정성이다.
                # **깊이가 실제로 필요한 곳은 실 데이터 경로다**(키가 들어오면
                # BOK/FRED 가 수십 년을 준다). mock 은 그대로 둔다.
                timestamps, values = _generate_mock_series(
                    key, length=60, **profile,
                )
                actual_source = "MOCK"
            else:
                actual_source = "unavailable"   # 운영 — 실 BOK/FRED 미수신(키 미설정/실패) → "—"
                # ★"unavailable" 만으로는 어디를 고쳐야 할지 알 수 없다★
                # 키가 없는 것과 좌표가 틀린 것과 주기가 안 맞는 것은 처방이 전부
                # 다른데, 예전에는 이 한 문자열로 전부 뭉개졌다.
                unavailable_reason = self._unavailable_reason(key, source)

        # 정규화 + 메트릭
        clean = [v for v in values if v is not None and not math.isnan(v)]
        norm = _normalize(clean)
        latest = clean[-1] if clean else None
        prev = clean[-2] if len(clean) >= 2 else None
        # YoY: 금리 등 %단위는 %p 차이, 지수/레벨형은 % 변화 (이전엔 지수도 점차로 빼던 버그)
        if len(clean) >= 13:
            yoy = (clean[-1] - clean[-13]) if unit == "%" \
                else ((clean[-1] / clean[-13] - 1) * 100 if clean[-13] > 0 else None)
        else:
            yoy = None
        mom_pct = ((clean[-1] - clean[-2]) / clean[-2] * 100) \
            if (len(clean) >= 2 and clean[-2] != 0) else None

        series = MacroSeries(
            indicator=key, name=name, unit=unit, source=actual_source,
            # ★저장 상한을 적재 깊이에 맞춘다 (P4-D3)★
            # 예전에는 `[-72:]` 하드코딩이었다. 사유("YoY 변환 후에도 5년 z-표본 확보")는
            # **하한**의 근거지 상한의 근거가 아닌데 상한으로 쓰이고 있었다. 그 결과
            # `MACRO_HISTORY_YEARS` 를 20으로 올려도 저장 단계에서 72로 잘려,
            # `frontier_sample`(240) 은 **어떤 설정으로도 열릴 수 없었다.**
            # 깊이에서 유도하되 72 아래로는 내려가지 않게 해 기존 z-표본 가정을 지킨다.
            timestamps=timestamps[-_store_cap():],
            values=clean[-_store_cap():] if clean else [],
            latest=round(latest, 4) if latest is not None else None,
            prev=round(prev, 4) if prev is not None else None,
            yoy=round(yoy, 3) if yoy is not None else None,
            mom_pct=round(mom_pct, 3) if mom_pct is not None else None,
            z_score=norm["z_score"],
            percentile=norm["percentile"],
            mean_5y=norm["mean_5y"],
            std_5y=norm["std_5y"],
            trend=norm["trend"],
            last_update=datetime.now().isoformat(),
            vintage_used=vintage_used,
            as_of=as_of,
            # ★값이 왔으면 None 이다★ 항상 사유를 채우면 "왜 비었나" 라는 질문에
            # 답하는 필드가 아니라 그냥 또 하나의 설명문이 된다.
            reason=unavailable_reason,
        )

        if as_of is None and live:
            with self._lock:
                self._cache[key] = (time.time(), series)

        # ★영속 기록★ 이 캐시는 **프로세스 메모리**다 — 재시작하면 사라지고,
        # 그래서 과거 매크로 실험을 재현할 수 없었다(계보 감사 §B1).
        # `macro_observation_store` 가 실 관측치를 남긴다. ★기록만 한다★ —
        # 읽는 소비자는 없고, 국면 축 배선은 배분 정책이라 별도 승인 사항이다.
        #
        # ★저장 원시함수가 아니라 수집 파이프라인에 둔다★ Phase 1 에서
        # `save_master_flags` 안에 DB 미러링을 넣었다가 그 함수를 픽스처로 쓰던
        # 테스트 3개를 깨뜨렸다. 부작용은 파이프라인의 일이다.
        # 비-REAL(`MOCK`·`unavailable`)은 스토어가 스스로 거른다.
        try:
            from src.data.macro_observation_store import record_series
            # ★스토어에서 읽은 것을 스토어에 되쓰지 않는다★ 순환이고, 빈티지 행을
            # `vintage_id=""` 사본으로 오염시킨다.
            # 저장소 경로(`live=False`)는 저장소에서 읽은 것이므로 같은 이유로 되쓰지 않는다.
            if not vintage_used and live:
                record_series(series)
        except Exception as e:  # noqa: BLE001 — 기록 실패가 수집을 실패로 만들지 않는다
            logger.debug(f"매크로 관측 기록 실패 ({key}): {e}")
        return series

    def cache_clear(self):
        with self._lock:
            self._cache.clear()

    def cache_stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "ttl_seconds": self.cache_ttl,
                "bok_configured": self.bok.is_configured,
                "fred_configured": self.fred.is_configured,
            }

    def connection_status(self) -> dict:
        """매크로 실연결 점검 — 소스별 키 설정 + 모드. 운영서 키 없으면 지표 'unavailable'."""
        from src.data.mock_gate import mock_allowed
        allow = mock_allowed()
        return {
            "mock_allowed": allow,
            "real_mode": not allow,
            "bok_configured": self.bok.is_configured,
            "fred_configured": self.fred.is_configured,
            "note": ("mock 모드 — 키 없으면 합성 MOCK 서빙"
                     if allow else
                     "운영 모드 — 실 BOK/FRED만, 미설정 지표는 unavailable(정직 '—')"),
        }
