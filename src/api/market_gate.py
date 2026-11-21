"""야후 시세가 필요한 라우트의 관문 (2026-11-13 — 야후 시세 mock 게이트).

`MarketDataLoader`(야후)를 부르는 분석 라우트는 이 의존성을 단다. mock 게이트(`mock_gate.mock_allowed()` — 유일한 판정 기준)가
켜져 있으면 본문 검증·계산에 들어가기 전에 ★'사용 불가 + 사유'(503)★ 로 답한다 — 시도하지 않고, 합성 시세를 지어내지도 않는다.

왜 라우트마다 다는가: 이 라우트들은 `except Exception` 으로 모든 실패를 "처리 중 오류가 발생했습니다"(500) 한 문장으로 묶는다.
로더가 사유를 올려도 거기서 사라진다. 의존성은 핸들러보다 먼저 돌아 사유가 응답에 그대로 나온다.
로더 자체에도 같은 게이트가 있다(`src/data_loader.py` — 라우트 밖 호출자와 이 의존성을 빠뜨린 새 라우트를 막는다).
어느 라우트가 달아야 하는지는 `tests/test_mock_yahoo_gate.py` 가 핸들러 소스를 읽어 강제한다.
"""
from __future__ import annotations

from fastapi import HTTPException

from src.data.mock_gate import mock_allowed
from src.data_loader import MARKET_DOWNLOAD_BLOCKED


def require_market_download() -> None:
    """mock 이면 503 + 사유. 운영이면 아무것도 하지 않는다."""
    if mock_allowed():
        raise HTTPException(status_code=503, detail=MARKET_DOWNLOAD_BLOCKED)
