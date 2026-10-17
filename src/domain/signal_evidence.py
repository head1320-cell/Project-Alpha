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
    timing_rule      33개   ✔ 24개 etf_prices · ✘ 5개 키 없음 · ✘ 4개 소스 없음(AX)

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

#: ★스토어가 출처를 선언한 필드★ — 가격일 수도 재무일 수도 있다. 가격으로
#: 뭉뚱그리면 재무 필드에 "가격이 mock 에서 온다" 는 거짓 사유가 붙는다.
BACKING_STORE = "store"

#: ★기관 시계열(FRED/ALFRED/ECOS) 빈티지 리더★(AX) — mock 게이트가 이 경로를
#: 지배하지 않는다. `FRED_API_KEY` 가 가른다. 스토어 쪽과 뭉치면 *"mock 게이트가
#: 열려 있어 합성입니다"* 라는 거짓 사유가 붙는다 — AW 에서 가격으로 뭉쳤다가
#: 만든 거짓과 같은 모양이다.
BACKING_VINTAGE = "vintage"

#: 종류·카테고리 → 뒷받침. ★여기 없는 것은 미상이다★(낙관적으로 분류하지
#: 않는다). 키는 `(kind, category)` 이고 카테고리가 `None` 이면 종류만 본다.
KNOWN_BACKING: dict[tuple[str, str | None], str] = {
    (KIND_STRATEGY_TOKEN, None): BACKING_PRICE,
    # ★AY — `(KIND_ALPHA_EXPR, "price")` 를 뺐다★ 그 열 개는 이제 `origin`
    #   (`ohlcv_loader`)으로 판정한다. 같은 질문에 두 기계가 답하면 한쪽만
    #   고쳐도 안 깨진다(`source_registry` 가 같은 이유를 적어 두었다).
    #   ★등급 값은 바뀌지 않는다★ — 둘 다 mock 게이트로 E0/E2 다.
}

_BASIS_TOKEN = (
    "factor_tokens.BASE_TOKENS 여덟 개가 전부 가격·거래량입니다(실측) — "
    "그 값은 KIS 가격 경로에서 옵니다")

_REASON_STORE_MOCK = (
    "mock 게이트가 열려 있어 이 스토어가 읽는 적재 경로가 합성입니다 — "
    "그 값은 지어낸 것입니다.")

_REASON_STORE_PROVIDER = (
    "mock 게이트가 닫혀 있어 이 스토어의 값이 제공자에서 파생됩니다. "
    "★실제로 적재됐는지는 여기서 확인하지 않습니다★ — 순수 규칙은 저장 상태를 "
    "알 수 없고, 아는 척하면 그것이 지어내기입니다.")

_BASIS_ORIGIN = (
    "이 필드는 {origin} 에서 병합됐습니다 — ★어느 스토어에서 왔는지는 병합 "
    "자리가 아는 구조적 사실이고, 선언된 출처 원문을 해석한 것이 아닙니다.★")

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

#: ★AW 가 되살린 출처를 등급으로 옮기는 표★ — 선언된 출처가 있는 스토어만
#: 여기 있다. `base_fields_store` 는 ★어디서 오는지 확인한 적이 없어★ 없다.
#: `etf_prices`(AX)는 `load_ohlcv_unified(DB→KIS→mock)` 를 **재사용**하므로
#: 스토어와 똑같이 mock 게이트가 지배한다 — 사유 문구가 그대로 참이다.
BACKED_ORIGINS = ("fundamentals_store", "price_factors_store",
                  "extended_factors_store", "etf_prices", "ohlcv_loader")

_REASON_BASE_FIELD = (
    "이 필드는 base_fields_store 로 옮겨졌지만 ★선언된 출처가 없습니다★ — "
    "원래 filter_ast 안에 맨손으로 적혀 있었고 어느 제공자에서 오는지 저장소가 "
    "확인한 적이 없습니다. 적는 것이 곧 지어내기입니다.")

_REASON_NO_ORIGIN = (
    "이 신호는 어느 스토어에서 왔는지를 실어 나르지 않습니다 — 출처를 물을 "
    "자리가 없습니다.")

#: ★AX — mock 게이트가 지배하지 않는 출처★. 여기 있는 것은 `FRED_API_KEY`
#: 유무로 가른다(환경변수 관측이지 네트워크 호출이 아니다 — `mock_allowed()`
#: 를 읽는 것과 같은 종류다).
VINTAGE_ORIGINS = ("pit_macro",)

#: 이름을 한 곳에만 둔다 — 사유 문구가 이 상수를 그대로 담아야 하므로.
FRED_KEY_ENV = "FRED_API_KEY"

_BASIS_VINTAGE = (
    "이 팩터는 {origin} 의 기관 시계열 빈티지 리더를 지납니다 — 어느 리더를 "
    "부르는지는 카탈로그가 선언하고 AST 대조가 지킵니다.")

_REASON_VINTAGE_NO_KEY = (
    f"{FRED_KEY_ENV} 가 없어 이 경로는 아무 값도 내지 않습니다 — pit_macro 는 "
    "빈 결과를 돌려주고 0 으로 대체하지 않습니다. ★mock 게이트는 이 경로를 "
    "지배하지 않으므로 합성으로 접지도 않습니다★ — 미상은 아무 주장도 아닙니다.")

_REASON_VINTAGE_KEYED = (
    f"{FRED_KEY_ENV} 가 있어 이 팩터가 기관 시계열에서 파생됩니다. "
    "★E4(시점 고정)로 올리지 않습니다★ — 빈티지 리더를 지나는 것과 빈티지가 "
    "실제로 고정됐음을 확인한 것은 다르고, 순수 규칙은 후자를 모릅니다. "
    "실제로 응답·적재됐는지도 여기서 확인하지 않습니다.")

_REASON_TIMING_NO_SOURCE = (
    "이 타이밍 팩터는 평가 함수 자체가 없습니다(스펙 §6.1 '소스 없음') — "
    "카탈로그가 스스로 unavailable 이라고 광고하고 그 사유를 답니다. "
    "출처를 적는 것이 곧 지어내기입니다.")

#: ★AX 가 이 문장을 거짓으로 만들었다★ — 24개가 이제 `etf_prices` 를 싣는다.
#: 남는 미상은 평가 함수가 없는 §6.1 묶음이고, 사유가 그것을 말한다.
_REASON_TIMING = _REASON_TIMING_NO_SOURCE


def _unsupplied_reason(key: str) -> str | None:
    """★사유를 여기 베껴 적지 않는다★(AY) — 레지스트리가 단일 출처다.

    `signal_supply.UNSUPPLIED` 에 **사유·막는 질문·승급 조건**이 함께 있고,
    테스트가 그 승급 조건이 아직 참인지 확인한다. 여기서 문장을 복사하면
    레지스트리를 고쳐도 응답이 안 따라온다.
    """
    from src.domain.signal_supply import UNSUPPLIED_BY_KEY

    e = UNSUPPLIED_BY_KEY.get(key)
    if e is None:
        return None
    return f"{e.reason} {e.blocks}"

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


def _fred_key_present() -> bool:
    """★호출 시점에 환경을 읽는다★ — `_mock_open()` 과 같은 종류의 관측이다.

    네트워크를 건드리지 않는다. *"키가 있다"* 는 *"읽혔다"* 가 아니고, 그
    한계를 사유가 적는다.
    """
    import os

    return bool(os.getenv(FRED_KEY_ENV, "").strip())


def _unknown_reason(kind: Any, origin: Any = None,
                    category: Any = None) -> str:
    """왜 못 정하는가. ★사유 없는 미상은 금지★ (CLAUDE.md 4절)."""
    if kind == KIND_SCREENER_FIELD:
        return _REASON_BASE_FIELD if origin else _REASON_NO_ORIGIN
    if kind == KIND_TIMING_RULE:
        return _REASON_TIMING
    if kind == KIND_ALPHA_EXPR:
        # ★공급 모듈이 없는 묶음은 레지스트리가 말한다★(AY)
        reason = _unsupplied_reason(f"{kind}.{category}") if category else None
        return reason or _REASON_NO_ORIGIN
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
    origin = getattr(signal, "origin", None)
    backing, basis = _backing(kind, category)

    # ★AW — 스토어가 출처를 선언하면 그것으로 판정한다★ 해석이 아니라
    #   구조적 사실이다(어느 스토어에서 병합됐는가).
    if backing is None and origin in BACKED_ORIGINS:
        backing, basis = BACKING_STORE, _BASIS_ORIGIN.format(origin=origin)

    # ★AX — 기관 시계열은 다른 것에 지배된다★ mock 게이트가 아니라 키다.
    #   키가 없으면 이 경로는 아무 값도 내지 않으므로 ★미상★이고, 합성으로
    #   접지 않는다(`E0` 은 "합성이라고 안다" 는 주장이다).
    if backing is None and origin in VINTAGE_ORIGINS:
        if not _fred_key_present():
            return {
                "signal_id": getattr(signal, "signal_id", None),
                "grade": None,
                "reason": _REASON_VINTAGE_NO_KEY,
                "basis": None,
                "note": _NOTE,
            }
        backing, basis = BACKING_VINTAGE, _BASIS_VINTAGE.format(origin=origin)

    if backing not in (BACKING_PRICE, BACKING_STORE, BACKING_VINTAGE):
        return {
            "signal_id": getattr(signal, "signal_id", None),
            "grade": None,
            "reason": _unknown_reason(kind, origin, category),
            "basis": None,
            "note": _NOTE,
        }

    # ★빈티지 경로는 mock 게이트를 읽지 않는다★ — 읽으면 거짓 사유가 붙는다.
    if backing == BACKING_VINTAGE:
        return {
            "signal_id": getattr(signal, "signal_id", None),
            # ★E4(시점 고정)로 올리지 않는다★ — 사유가 그 이유를 적는다.
            "grade": PROV_E2,
            "reason": _REASON_VINTAGE_KEYED,
            "basis": basis,
            "note": _NOTE,
        }

    synthetic = _mock_open()
    if backing == BACKING_STORE:
        reason = _REASON_STORE_MOCK if synthetic else _REASON_STORE_PROVIDER
    else:
        reason = _REASON_MOCK if synthetic else _REASON_PROVIDER
    return {
        "signal_id": getattr(signal, "signal_id", None),
        "grade": PROV_E0 if synthetic else PROV_E2,
        "reason": reason,
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
