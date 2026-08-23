"""실데이터 전용 게이트 — 합성(mock) 데이터를 서빙해도 되는 환경인가?
==========================================================================
운영(KIS_USE_MOCK=0, 실키)에선 합성 mock을 사용자에게 절대 노출하지 않는다 → 실데이터 또는 정직한 None.
mock 생성기는 명시적 개발/테스트(KIS_USE_MOCK=1, 샌드박스/CI)에서만 도달.
"""

import os


def mock_allowed() -> bool:
    """합성(mock) 데이터 서빙 허용 여부.

    True  — KIS_USE_MOCK=1 (명시적 개발/테스트/샌드박스): mock 폴백 허용.
    False — KIS_USE_MOCK=0 또는 기타 (운영): 실 호출 실패 시 mock 대신 None/빈값(정직 "—").
    기본값은 "1"(mock) — 키 없는 개발 환경 안전.
    """
    return os.getenv("KIS_USE_MOCK", "1") == "1"
