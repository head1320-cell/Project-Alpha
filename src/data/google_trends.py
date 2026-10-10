"""구글 검색 트렌드 클라이언트 — **공식 API 만** 쓴다 (M1-I)
==============================================================================
공식 Google Trends API 를 쓴다. `POST {BASE}/v1beta/trends:fetchTimeseries`,
인증은 API 키(`?key=`).

★비공식 스크래핑 엔드포인트는 쓰지 않는다★
------------------------------------------------------------------------------
`pytrends` 류가 치는 내부 endpoint 는 문서화돼 있지 않고 수시로 바뀌며 429 가 잦다.
그런 클라이언트를 쓰면 **한 번도 실행된 적 없는 코드가 동작하는 것처럼** 남고, 깨져도
조용히 빈 값이 되어 mock 이 덮는다. 공식 API 는 계약이 문서화돼 있으므로 파서를
명세에 맞춰 쓸 수 있고, 틀리면 틀렸다고 말할 수 있다.

★값은 상대 지수다★ 네이버 `ratio` 와 같은 성질 — 구간 최댓값을 100 으로 둔 정규화
값이지 검색 건수가 아니다. 구간이 바뀌면 같은 날 값도 바뀐다.

★verified_live=False★ 이 환경에서는 호스트가 프록시 403 이라 실호출로 확인하지 못했다.
확인은 `verify_connection.py::check_trends`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://trends.googleapis.com"
TIMESERIES_PATH = "/v1beta/trends:fetchTimeseries"

_MIN_INTERVAL_SEC = 0.5


def parse_timeseries_response(payload: dict[str, Any]) -> dict[str, Any]:
    """공식 응답 → `{available, series:{term: [{date, value}]}, note}`.

    응답 모양(명세):
        {"timelineData":[{"date":"2026-01-01","values":[{"term":"AI","value":73}, ...]}]}

    ★값이 없는 점은 버린다★ `None` 을 0 으로 바꾸면 "검색이 없었다" 로 읽히는데,
    실제로 참인 것은 "그 점의 값을 받지 못했다" 이다.
    """
    rows = (payload or {}).get("timelineData") or []
    if not isinstance(rows, list):
        return {"available": False, "series": {},
                "reason": "timelineData 가 리스트가 아닙니다."}

    series: dict[str, list[dict[str, Any]]] = {}
    for pt in rows:
        date = str(pt.get("date") or "").strip()
        if not date:
            continue
        for v in pt.get("values") or []:
            term = str(v.get("term") or "").strip()
            raw = v.get("value")
            if not term or raw is None:
                continue        # 지어내지 않는다
            try:
                series.setdefault(term, []).append({"date": date, "value": float(raw)})
            except (TypeError, ValueError):
                continue

    if not series:
        return {"available": False, "series": {}, "reason": "응답에 시계열이 없습니다."}
    for rows_ in series.values():
        rows_.sort(key=lambda r: r["date"])
    return {
        "available": True,
        "series": series,
        "note": ("값은 요청 구간 최댓값을 100 으로 둔 **상대 지수**입니다 — 검색 건수가 "
                 "아니고, 구간이 달라지면 같은 날의 값도 달라집니다."),
    }


class GoogleTrendsClient:
    """공식 Google Trends API — 키 없으면 비활성(호출하지 않는다)."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_TRENDS_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _throttle(self) -> None:
        with self._lock:
            wait = _MIN_INTERVAL_SEC - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def fetch_trends(self, terms: list[str], *, start: str, end: str,
                     region: str = "KR") -> dict[str, Any]:
        """검색어 시계열 조회. 실패는 사유로 돌려주고 예외를 올리지 않는다."""
        if not self.is_configured:
            return {"available": False, "series": {},
                    "reason": "GOOGLE_TRENDS_API_KEY 가 없습니다 — 호출하지 않았습니다."}
        if not terms:
            return {"available": False, "series": {}, "reason": "검색어가 비었습니다."}

        self._throttle()
        try:
            import requests
            r = requests.post(
                f"{BASE_URL}{TIMESERIES_PATH}",
                params={"key": self.api_key},
                json={"terms": terms[:5], "startDate": start, "endDate": end,
                      "region": region},
                timeout=self.timeout)
            r.raise_for_status()
            return parse_timeseries_response(r.json())
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Google Trends 호출 실패: {type(e).__name__}: {e}")
            return {"available": False, "series": {},
                    "reason": f"구글 트렌드 호출 실패: {type(e).__name__}"}
