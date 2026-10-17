"""네이버 DataLab 검색어 트렌드 클라이언트 (M1-I)
==============================================================================
공식 API: `POST https://openapi.naver.com/v1/datalab/search`
인증: `X-Naver-Client-Id` / `X-Naver-Client-Secret` 헤더.

응답(공식 명세):
    {"startDate","endDate","timeUnit",
     "results":[{"title","keywords":[...],
                 "data":[{"period":"2026-01-01","ratio":42.1}, ...]}]}

★`ratio` 는 절대 검색량이 아니다★
------------------------------------------------------------------------------
요청 구간 내 **최댓값을 100 으로 정규화한 상대 지수**다. 그래서 구간이 달라지면 같은
날의 값이 달라진다. 이 사실을 노트로 달지 않으면 화면은 이 숫자를 검색 건수처럼 읽고,
서로 다른 구간의 값을 비교하게 된다.

★verified_live=False★ 이 환경에서는 `openapi.naver.com` 이 프록시 403 이라 실호출로
확인하지 못했다. 파서는 공식 명세를 따라 썼고, 확인은 `verify_connection.py` 다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi.naver.com"
SEARCH_PATH = "/v1/datalab/search"

_MIN_INTERVAL_SEC = 0.2      # 공식 쿼터 보호 (일 1,000회)


def parse_search_response(payload: dict[str, Any]) -> dict[str, Any]:
    """공식 응답 → `{available, series:{title: [{date, ratio}]}, start, end, unit}`.

    ★값이 없는 그룹은 빈 리스트로 남긴다★ 키를 지우면 "그 키워드를 안 봤다" 로 읽힌다.
    """
    results = (payload or {}).get("results") or []
    if not isinstance(results, list):
        return {"available": False, "reason": "results 가 리스트가 아닙니다.", "series": {}}

    series: dict[str, list[dict[str, Any]]] = {}
    for grp in results:
        title = str(grp.get("title") or "").strip() or "(무제)"
        rows: list[dict[str, Any]] = []
        for d in grp.get("data") or []:
            period = str(d.get("period") or "").strip()
            ratio = d.get("ratio")
            if not period or ratio is None:
                continue        # 지어내지 않는다
            try:
                rows.append({"date": period, "ratio": float(ratio)})
            except (TypeError, ValueError):
                continue
        rows.sort(key=lambda r: r["date"])
        series[title] = rows

    if not series:
        return {"available": False, "reason": "응답에 시계열이 없습니다.", "series": {}}
    return {
        "available": True,
        "series": series,
        "start": (payload or {}).get("startDate"),
        "end": (payload or {}).get("endDate"),
        "unit": (payload or {}).get("timeUnit"),
        "note": ("`ratio` 는 요청 구간 내 최댓값을 100 으로 둔 **상대 지수**입니다 — "
                 "절대 검색량이 아니고, 구간이 달라지면 같은 날의 값도 달라집니다."),
    }


class NaverDataLabClient:
    """네이버 DataLab — 키 없으면 비활성(호출하지 않는다)."""

    def __init__(self, client_id: str | None = None,
                 client_secret: str | None = None, timeout: float = 10.0):
        self.client_id = client_id if client_id is not None else os.getenv("NAVER_CLIENT_ID", "")
        self.client_secret = (client_secret if client_secret is not None
                              else os.getenv("NAVER_CLIENT_SECRET", ""))
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id) and bool(self.client_secret)

    def _throttle(self) -> None:
        with self._lock:
            wait = _MIN_INTERVAL_SEC - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def fetch_trends(self, keyword_groups: list[dict[str, Any]], *,
                     start: str, end: str, time_unit: str = "month") -> dict[str, Any]:
        """검색어 트렌드 조회.

        Args:
            keyword_groups: `[{"groupName": "반도체", "keywords": ["반도체", "HBM"]}]`
        """
        if not self.is_configured:
            return {"available": False, "series": {},
                    "reason": "NAVER_CLIENT_ID/SECRET 이 없습니다 — 호출하지 않았습니다."}
        if not keyword_groups:
            return {"available": False, "series": {}, "reason": "키워드 그룹이 비었습니다."}

        self._throttle()
        try:
            import requests
            r = requests.post(
                f"{BASE_URL}{SEARCH_PATH}",
                headers={"X-Naver-Client-Id": self.client_id,
                         "X-Naver-Client-Secret": self.client_secret,
                         "Content-Type": "application/json"},
                json={"startDate": start, "endDate": end, "timeUnit": time_unit,
                      "keywordGroups": keyword_groups[:5]},   # 공식 상한 5
                timeout=self.timeout)
            r.raise_for_status()
            return parse_search_response(r.json())
        except Exception as e:  # noqa: BLE001 — 실패는 사유로, 예외로 화면을 깨지 않는다
            logger.warning(f"Naver DataLab 호출 실패: {type(e).__name__}: {e}")
            return {"available": False, "series": {},
                    "reason": f"네이버 DataLab 호출 실패: {type(e).__name__}"}
