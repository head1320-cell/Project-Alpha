"""신호가 어디서 왔는가 — ★출처 등급 규칙★ (AV)
==============================================================================
카탈로그 `src/domain/signal_definition.py` · 표면 `src/api/signal_routes.py` ·
같은 모양의 선례 `src/engine/research_panel.evidence_grade`(패널의 출처를
규칙으로 등급화한다)

## 왜 이 모듈이 생겼나

`SignalDefinition.evidence_grade` 는 선언만 되고 저장소 전체에서 **대입
0건**이었다 — 같은 dataclass 의 `availability`·`unavailable_reason` 은
채워지는데 그 하나만 빠져 있었다. `GET /signals` 는 그 칸을 이미 내보내고
있으니, 화면은 지금까지 언제나 `null` 을 받았다. 갭 분석 §1 이 지목한
균열이고, 그것을 닫으려 만든 모듈에서 아직 안 닫혔다.

## ★같은 글자, 다른 축★ — 이 모듈이 조심하는 것

`E0~E3` 이라는 글자가 저장소에서 **두 척도**로 쓰인다:

    CLAUDE.md 2절                     출처   E2 = 제공자 파생
    source_registry.EVIDENCE_GRADES   확신도 E2 = 메타 API 응답에서 관측

그리고 빈 필드의 주석은 ★확신도 쪽★을 가리키고 있었다. CLAUDE.md 가
`capability.py` 의 `L0~L3` 에 대해 *"방향이 정반대니 절대 섞지 마세요"* 라고
적어 둔 바로 그 위험이다. 신호에는 **출처 척도**를 쓰고, 상수 이름을 달리해
(`PROV_*`) 섞이지 않게 한다. ★`source_registry` 는 임포트하지 않는다★ —
AST 테스트가 지킨다.

## ★아는 것에서만 파생한다★

실측(2026-09-21, 신호 215개):

    strategy_token    8개   ✔ BASE_TOKENS 가 전부 가격·거래량이다
    alpha_expr       17개   ✔ 카테고리가 price/fund 로 갈려 있다
    screener_field  157개   ✘ filter_ast 병합이 FactorMeta.source 를 버린다
    timing_rule      33개   ✘ 개정 정책은 아는데 출처는 모른다

★157개(73%)가 미상이고 그 사유가 구체적인 결함을 가리킨다★ — 그 목록이 이
모듈의 산출물이다. 다섯 어댑터는 고치지 않았다: ★모르는 것을 알게 만들지
않는다★(그것은 별건이고, 이 규칙이 그 별건을 **이름으로** 가리킨다).

## ★이 모듈이 주장하지 않는 것★

- **미상을 합성으로 접지 않는다.** `E0` 은 *"합성이라고 안다"* 는 주장이고
  미상은 아무 주장도 아니다.
- **신호의 뜻·유용성을 말하지 않는다.** 등급은 ★어디서 왔는가★일 뿐이고,
  예측력도 경제적 가치도 아니다(CLAUDE.md 2절의 네 질문 중 어느 것도 아니다).
- **쓸 수 있는가를 말하지 않는다.** `availability` 는 다른 축이고, 이 등급은
  그 값과 무관하다.
- **실데이터 모드에서 적재를 확인하지 않는다.** mock 게이트 밖에서는
  *"제공자에서 파생된다"* 까지만 말한다 — 실제로 적재됐는지는 순수 모듈이
  알 수 없고, 아는 척하면 그것이 곧 지어내기다.
"""
from __future__ import annotations

from typing import Any

from src.domain.signal_definition import (
    KIND_ALPHA_EXPR,
    KIND_SCREENER_FIELD,
    KIND_STRATEGY_TOKEN,
    KIND_TIMING_RULE,
)

#: ★출처 척도★ — CLAUDE.md 2절. E5(경제적 검증)는 신호 하나에 붙는 등급이
#: 아니라 전략에 붙는 판정이라 여기 두지 않는다.
PROV_E0 = "E0"      # 합성
PROV_E1 = "E1"      # 픽스처
PROV_E2 = "E2"      # 제공자 파생
PROV_E3 = "E3"      # 실 과거
PROV_E4 = "E4"      # 시점 고정

PROVENANCE_GRADES = (PROV_E0, PROV_E1, PROV_E2, PROV_E3, PROV_E4)

PROVENANCE_LABELS = {
    PROV_E0: "합성",
    PROV_E1: "픽스처",
    PROV_E2: "제공자 파생",
    PROV_E3: "실 과거",
    PROV_E4: "시점 고정",
}

#: ★가격·거래량에 뒷받침되는 종류★ — 실측으로 확인한 것만 넣는다.
#: `strategy_token` 의 `BASE_TOKENS` 는 여덟 개가 전부 시가·고가·저가·종가·
#: 현재가·주가·거래량·거래대금이고, `alpha_expr` 은 카테고리가 `price` 다.
BACKING_PRICE = "price"

#: 종류·카테고리 → 뒷받침. ★여기 없는 것은 미상이다★(낙관적으로 분류하지
#: 않는다). 키는 `(kind, category)` 이고 카테고리가 `None` 이면 종류만 본다.
KNOWN_BACKING: dict[tuple[str, str | None], str] = {
    (KIND_STRATEGY_TOKEN, None): BACKING_PRICE,
    (KIND_ALPHA_EXPR, "price"): BACKING_PRICE,
}

_BASIS_TOKEN = (
    "factor_tokens.BASE_TOKENS 여덟 개가 전부 가격·거래량입니다(실측) — "
    "그 값은 KIS 가격 경로에서 옵니다")

_BASIS_ALPHA_PRICE = (
    "alpha_lab.FIELDS 가 이 신호를 `price` 그룹으로 분류합니다 — 그 값은 "
    "KIS 가격 경로에서 옵니다")

_REASON_MOCK = (
    "mock 게이트가 열려 있어 가격이 MockKISClient 에서 옵니다 — 그 값은 "
    "지어낸 것입니다.")

_REASON_PROVIDER = (
    "mock 게이트가 닫혀 있어 가격이 제공자에서 파생됩니다. ★실제로 적재됐는지는 "
    "여기서 확인하지 않습니다★ — 순수 규칙은 저장 상태를 알 수 없고, 아는 척하면 "
    "그것이 지어내기입니다.")

_REASON_SCREENER = (
    "이 신호의 출처가 카탈로그에 도달하지 않습니다 — filter_ast 의 병합이 "
    "FieldMeta 를 만들 때 FactorMeta.source(문헌 인용)를 버립니다. "
    "★기록이 없는 것이 아니라 옮기다 떨어뜨린 것입니다.★")

_REASON_TIMING = (
    "이 신호는 개정 정책(revision_policy)은 아는데 ★무엇에서 계산되는지는 "
    "실어 나르지 않습니다★ — 개정 정책과 출처는 다른 축입니다.")

_REASON_UNMAPPED = (
    "이 종류·카테고리의 뒷받침을 이 규칙이 모릅니다 — 새 어댑터나 새 그룹이 "
    "생기면 ★조용히 통과시키지 않고★ 미상으로 둡니다.")

_NOTE = (
    "등급은 ★이 값이 어디서 왔는가★만 말합니다 — 예측력도 경제적 가치도 "
    "쓸 수 있는지도 아닙니다. 미상은 합성이 아닙니다: 등급이 없다는 것은 "
    "저장소가 출처를 말할 수 없다는 뜻이지, 값이 지어낸 것이라는 뜻이 "
    "아닙니다. 그리고 이 척도는 source_registry 의 확신도 척도와 글자만 "
    "같고 다른 축입니다.")


def _mock_open() -> bool:
    """★호출 시점에 환경을 읽는다★ — 임포트 시점에 굳히면 못 바꾼다."""
    from src.data.mock_gate import mock_allowed

    return mock_allowed()


def _backing(kind: Any, category: Any) -> tuple[str | None, str | None]:
    """(뒷받침, 근거). 모르면 `(None, None)` — ★낙관적으로 분류하지 않는다★."""
    if (kind, None) in KNOWN_BACKING:
        return KNOWN_BACKING[(kind, None)], _BASIS_TOKEN
    key = (kind, category if isinstance(category, str) else None)
    if key in KNOWN_BACKING:
        return KNOWN_BACKING[key], _BASIS_ALPHA_PRICE
    return None, None


def _unknown_reason(kind: Any) -> str:
    """왜 못 정하는가. ★사유 없는 미상은 금지★ (CLAUDE.md 4절)."""
    if kind == KIND_SCREENER_FIELD:
        return _REASON_SCREENER
    if kind == KIND_TIMING_RULE:
        return _REASON_TIMING
    return _REASON_UNMAPPED


def signal_grade(signal: Any) -> dict[str, Any]:
    """신호 하나의 출처 등급. ★모르면 `None` + 사유★

    Args:
        signal: `SignalDefinition`(또는 `kind`·`category`·`signal_id` 를 가진 것).

    Returns:
        `signal_id` · `grade`(어휘 안이거나 `None`) · `reason` · `basis`
        (★무엇을 보고 그렇게 정했는가★ — 등급만 내면 다음 사람이 검증할 수
        없다) · `note`.
    """
    kind = getattr(signal, "kind", None)
    category = getattr(signal, "category", None)
    backing, basis = _backing(kind, category)

    if backing != BACKING_PRICE:
        return {
            "signal_id": getattr(signal, "signal_id", None),
            "grade": None,
            "reason": _unknown_reason(kind),
            "basis": None,
            "note": _NOTE,
        }

    synthetic = _mock_open()
    return {
        "signal_id": getattr(signal, "signal_id", None),
        "grade": PROV_E0 if synthetic else PROV_E2,
        "reason": _REASON_MOCK if synthetic else _REASON_PROVIDER,
        "basis": basis,
        "note": _NOTE,
    }


def grade_catalog(catalog: Any) -> dict[str, Any]:
    """카탈로그 전체의 등급 분포와 ★빈틈 목록★.

    ★빈 카탈로그에 전칭을 주장하지 않는다★ — 파이썬에서 `all([])` 은 `True`
    라, 신호가 하나도 없는 상태가 "전부 등급이 붙었다" 로 읽히면 아무 일도
    없는 것이 가장 강한 주장이 된다(AT 에서 같은 함정을 만났다).
    """
    signals = getattr(catalog, "signals", ()) or ()
    by_grade: dict[str, int] = {}
    ungraded: list[dict[str, Any]] = []

    for signal in signals:
        verdict = signal_grade(signal)
        grade = verdict["grade"]
        if grade is None:
            ungraded.append({"signal_id": verdict["signal_id"],
                             "kind": getattr(signal, "kind", None),
                             "reason": verdict["reason"]})
            continue
        by_grade[grade] = by_grade.get(grade, 0) + 1

    n_graded = sum(by_grade.values())
    return {
        "n_signals": len(signals),
        "n_graded": n_graded,
        "n_ungraded": len(ungraded),
        "by_grade": by_grade,
        "labels": {g: PROVENANCE_LABELS[g] for g in by_grade},
        "ungraded": ungraded,
        # ★신호가 없으면 완전하지 않다★ — 빈 것은 전칭의 근거가 아니다.
        "complete": n_graded > 0 and not ungraded,
        "note": _NOTE,
    }
