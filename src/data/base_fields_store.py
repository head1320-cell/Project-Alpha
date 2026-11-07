"""스크리너 기본 필드 — ★맨손 리터럴이 살던 곳★ (AW3)
==============================================================================
소비자: `src/engine/filter_ast._register_base_fields()` · 등급 규칙
`src/domain/signal_evidence.py`

## 왜 옮겼나

AV 가 신호 157개의 출처를 저장소가 말할 수 없다고 이름 붙였다. 그중
145개는 `fundamentals_store`·`price_factors_store`·`extended_factors_store`
에서 병합되므로 **어느 스토어에서 왔는지**가 구조적으로 드러나는데,
★14개는 `filter_ast.FIELD_CATALOG` 안에 맨손으로 적혀 있어 출처를 물을
자리조차 없었다.★ 그 14개를 여기로 옮겨 나머지와 같은 모양으로 만든다.

## ★값은 한 글자도 바꾸지 않았다★

옮기기 전 상태를 `tests/test_filter_ast_golden.py` 가 기계로 떠내 못 박아
두었다. id·라벨·카테고리·단위·방향·상하한이 전부 그대로이고, ★등록 순서도
그대로다★ — `_register_base_fields()` 가 맨 먼저 돈다.

CLAUDE.md §6 은 스크리너 3-레이어를 리팩터링 대상이 아니라고 못 박는다.
★이 이동은 같은 필드가 다른 파일에서 오게 하는 것뿐이고★, 유동성 게이트·
필터 kind·후처리 analyzer 는 건드리지 않았다.

## ★근거를 적지 않았다★

다른 세 스토어는 `source` 칸을 갖지만, 이 14개는 ★어디서도 근거를 찾을 수
없었다★. 적는 것이 곧 지어내기이므로 비워 둔다 — 누군가 확인하면 그때
채운다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaseFieldMeta:
    """기본 필드 하나. ★`filter_ast.FieldMeta` 의 일곱 칸과 같은 모양★

    다른 스토어의 `FactorMeta` 와 달리 `source` 칸이 없다 — 있는 척하면
    비어 있는 칸이 "근거가 없다" 가 아니라 "아직 안 적었다" 로 읽힌다.
    """

    id: str
    label: str
    category: str
    unit: str
    higher_better: bool
    typical_min: float
    typical_max: float


#: ★`filter_ast.FIELD_CATALOG` 에서 그대로 옮겨 온 순서★ — 바꾸면 골든
#: 스냅샷이 죽는다.
BASE_FIELDS: tuple[BaseFieldMeta, ...] = (
    # 밸류에이션
    BaseFieldMeta("per",             "PER",        "valuation",     "배", False, 0, 50),
    BaseFieldMeta("pbr",             "PBR",        "valuation",     "배", False, 0, 10),
    BaseFieldMeta("gap_pct",         "괴리율",      "valuation",     "%",  False, -80, 80),
    BaseFieldMeta("intrinsic_value", "적정가",      "valuation",     "원", True, 0, 1000000),
    # 수익성
    BaseFieldMeta("roe_pct",         "ROE",        "profitability", "%",  True, -10, 40),
    BaseFieldMeta("roa_pct",         "ROA",        "profitability", "%",  True, -10, 25),
    # 배당
    BaseFieldMeta("dividend_yield_pct", "배당수익률", "dividend",   "%",  True, 0, 10),
    # 안정성
    BaseFieldMeta("debt_ratio_pct",  "부채비율",    "stability",     "%",  False, 0, 300),
    BaseFieldMeta("fcf_억",          "잉여현금흐름", "stability",     "억", True, -5000, 50000),
    # 시가총액은 규모(Size) 팩터 — 안정성 아님 (CIO 실사: 팩터 분류 체계 재정립)
    BaseFieldMeta("market_cap_억",   "시가총액",    "size",          "억", True, 0, 5000000),
    # 종합 스코어
    BaseFieldMeta("composite_score", "종합 점수",   "score",         "점", True, 0, 100),
    BaseFieldMeta("gap_score",       "저평가 점수", "score",         "점", True, 0, 100),
    BaseFieldMeta("roe_score",       "수익성 점수", "score",         "점", True, 0, 100),
    BaseFieldMeta("stability_score", "안정성 점수", "score",         "점", True, 0, 100),
)

#: ★`_BY_ID` 는 반드시 `BASE_FIELDS` 에서 파생한다★ — 따로 만들면 두 읽기
#: 경로가 갈라진다(`source_registry` 가 같은 이유를 적어 두었다).
BASE_FIELD_BY_ID = {f.id: f for f in BASE_FIELDS}
