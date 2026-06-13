# 대상 경로: src/data/sector_labels.py
#
# 지수업종 코드 → 한글 라벨 해석 (정직 우선 — 잘못된 이름을 지어내지 않음).
#
# KIS 마스터의 지수업종 대/중/소분류는 숫자 코드다. 권위 있는 코드→한글 매핑은
# 실제 마스터 파일을 받아야 확정되므로, 여기서는:
#   1) SECTOR_CODE_LABELS: 사용자가 실파일 확인 후 채우는 오버라이드(기본 비어 있음)
#   2) 비어 있으면 "업종 {코드}" 로 정직 폴백 (틀린 한글명 위험 0)
#   3) curated STOCK_SECTOR(한글) 는 종목 단위로 우선 적용 — universe_select 에서 결합
#
# 즉 collect-master 적재 시: 전 종목이 실제 업종 코드로 "그룹화"되고(평면 10 → 실제 코드
# 단위로 세분), 라벨은 오버라이드/curated 가 있으면 한글, 없으면 코드 그대로 표시된다.
# 라벨 품질은 오버라이드를 채울수록 좋아지고, 그룹핑 자체는 즉시 실데이터로 작동한다.

from __future__ import annotations

# 실파일 확인 후 채우는 코드→한글 (예: {"0021": "철강금속"}). 기본 비어 있음 — 추측 금지.
SECTOR_CODE_LABELS: dict[str, str] = {}


def label_for(code: str | None, *, level: str = "대분류") -> str | None:
    """지수업종 코드 → 표시 라벨. 매핑 없으면 '업종 {코드}' 정직 폴백, 코드도 없으면 None."""
    c = (code or "").strip()
    if not c:
        return None
    lbl = SECTOR_CODE_LABELS.get(c)
    if lbl:
        return lbl
    return f"업종 {c}"


def is_real_label(code: str | None) -> bool:
    """오버라이드로 실제 한글명이 매핑됐는지 (sanity 리포트용)."""
    return bool((code or "").strip() and SECTOR_CODE_LABELS.get((code or "").strip()))
