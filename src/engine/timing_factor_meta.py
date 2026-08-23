"""§3.2 `TimingFactorDefinition` 의 구조화 메타 — 카탈로그 항목에 덧입힌다 (Phase 12a).

Phase 11a 감사가 A1·A2 로 적은 것을 채운다: 정의에 9개 필드를 요구하는데 3개만 있었고,
`provenance` 는 열거형이어야 하는데 **자유 텍스트 인용문**이었다.

★인용문을 버리지 않는다★
─────────────────────────────────────────────────────────────────────────────
자유 텍스트가 분류보다 **더 많은 것**을 말한다("Keller & Keuning (VAA/DAA)" vs
`systrader_public`). §6 이 막으려는 위험(유료 전략 복제 암시)도 실제 출처를 적는 쪽이 더 잘
막는다. 그래서 인용문은 `provenance` 에 그대로 두고, 필터·그룹에 쓸 **분류**를
`provenance_class` 로 따로 붙인다. 하나를 다른 하나로 대체하면 정보가 준다.

★값을 지어내지 않는다★
─────────────────────────────────────────────────────────────────────────────
29개 항목에 8개 필드를 손으로 채우면 그중 상당수가 추측이 된다. 그래서 **유도**한다 —
단위에서 범위를, 출처에서 공표지연·개정정책을. 유도할 수 없는 것은 `None` 으로 두지
`"N/A"` 같은 그럴듯한 문자열로 채우지 않는다.

★미분류는 조용히 통과하지 않는다★
`classify()` 는 매칭 규칙이 없으면 `None` 을 돌려주고, 테스트가 카탈로그 전체에 대해 그것을
금지한다. 기본값을 `user_defined` 로 두면 새 팩터를 추가할 때마다 출처가 조용히 틀려진다.
"""
from __future__ import annotations

from typing import Any

# ── §3.2 / §6 열거형 ────────────────────────────────────────────────────────────
PROVENANCE_CLASSES = (
    "systrader_public",          # §6 첫 묶음 — 공개 문서화된 개념(듀얼모멘텀·VAA/DAA·GTAA…)
    "generic_public_technical",  # §6 둘째 묶음 — 이격도·돌파·오버나이트 등 일반 기술 시그널
    "institutional_public",      # 공공기관 시계열 (FRED/ALFRED/ECOS)
    "user_defined",              # 사용자가 만든 것
)

USE_MODES = ("gate", "ranking", "sizing", "tilt", "risk_off_trigger", "scenario_trigger")

AVAILABILITIES = ("available", "partial", "unavailable")

# 인용문 → 분류. **위에서부터 첫 일치**이므로 순서가 의미를 갖는다.
# (FRED/ECOS 를 먼저 둔다 — "generic" 을 함께 담은 인용문이 있어도 출처가 우선이다.)
_CLASS_RULES: tuple[tuple[str, str], ...] = (
    ("FRED", "institutional_public"),
    ("ALFRED", "institutional_public"),
    ("ECOS", "institutional_public"),
    ("systrader79", "systrader_public"),
    # §6 이 첫 묶음에 명시적으로 나열한 개념들의 원저자다 —
    # "dual momentum · accelerating dual momentum · MA trend filters · Defense First".
    ("Antonacci", "systrader_public"),
    ("Keller", "systrader_public"),
    ("Faber", "systrader_public"),
    ("classic trend filter", "generic_public_technical"),
    ("generic", "generic_public_technical"),
    # 한국 대체 구현 — 개념 자체는 일반 기술 시그널이고 ETF 는 그 입력일 뿐이다.
    ("ETF proxy", "generic_public_technical"),
)


def classify(provenance: str | None) -> str | None:
    """인용문에서 §6 분류를 유도한다. 규칙이 없으면 **None** — 기본값으로 때우지 않는다."""
    if not provenance:
        return None
    for needle, cls in _CLASS_RULES:
        if needle.lower() in provenance.lower():
            return cls
    return None


# ── use_mode ───────────────────────────────────────────────────────────────────
# 기본은 `gate` 다 — 카탈로그의 절대다수가 "임계 통과 여부"로 쓰인다(default_threshold +
# default_direction 이 그 증거). 다르게 쓰이는 것만 적는다.
_USE_MODE_OVERRIDES: dict[str, str] = {
    # 연속 비중 — 이진 신호가 아니라 노출 크기를 정한다(원 규칙이 그렇다).
    "avg_abs_momentum": "sizing",
    "target_vol_size": "sizing",
    # 벤치마크 대비 상대 순위 — 통과/탈락이 아니라 줄 세우기다.
    "relative_momentum": "ranking",
}

# ── 공표 지연 · 개정 정책 ───────────────────────────────────────────────────────
# 가격 파생 팩터는 장 마감값에서 계산되고 개정되지 않는다. 기관 시계열만 다르므로
# **그것들만** 적는다(팩터 id 기준 — 시리즈마다 사실이 다르다).
_SOURCE_TIMING: dict[str, tuple[str, str]] = {
    # (release_lag, revision_policy)
    "financial_conditions": ("주간(수요일 공표)", "revised"),
    "curve_slope": ("미국 장 마감 당일", "revised"),
    "vix_term_structure": ("미국 장 마감 당일", "not_revised"),
    "vix_term_spread": ("미국 장 마감 당일", "not_revised"),
    # 임의 시리즈를 받는 범용 팩터 — 하나로 단정할 수 없다. 모른다고 적는다.
    "indicator": ("시리즈에 따라 다름", "series_dependent"),
}
_PRICE_DERIVED_TIMING = ("장 마감 당일", "not_revised")

# ── allowed_range ──────────────────────────────────────────────────────────────
# 단위가 범위를 결정한다. 경계가 **실제로** 있는 것만 적는다 — 수익률·스프레드에 임의의
# 상한을 씌우면 정상 값이 검증에서 튕긴다.
_RANGE_BY_UNIT: dict[str, tuple[float, float]] = {
    "weight_0_1": (0.0, 1.0),
    "bool": (0.0, 1.0),
    "ratio_0_1": (0.0, 1.0),
}

# 모든 팩터가 같은 실패 양식을 갖는다 — 이건 우연이 아니라 **설계**다(§3.3 세 상태).
# 팩터마다 다른 문장을 지어내는 대신 그 사실을 그대로 적는다.
EXPECTED_FAILURE_MODE = (
    "값을 얻지 못하면 None → SignalState.unavailable. 합성에서 보수적으로 risk_off 로 "
    "접히되 별도로 집계된다. 0 이나 마지막 값으로 대체하지 않는다."
)


def enrich(entry: dict[str, Any]) -> dict[str, Any]:
    """카탈로그 항목 하나에 §3.2 필드를 덧붙인다(원본은 건드리지 않는다)."""
    out = dict(entry)
    fid = out.get("id", "")

    out["provenance_class"] = classify(out.get("provenance"))
    out["use_mode"] = _USE_MODE_OVERRIDES.get(fid, "gate")
    out["allowed_range"] = list(_RANGE_BY_UNIT[out["unit"]]) if out.get("unit") in _RANGE_BY_UNIT else None

    lag, rev = _SOURCE_TIMING.get(fid, _PRICE_DERIVED_TIMING)
    out["release_lag"] = lag
    out["revision_policy"] = rev

    # 구현된 팩터는 가용하다. 데이터 소스가 아예 없는 항목은 CATALOG 가 아니라
    # UNAVAILABLE_FACTORS 로 들어오며 자기 값을 이미 갖고 있다.
    out.setdefault("availability", "available")
    out.setdefault("unavailable_reason", None)
    out["expected_failure_mode"] = EXPECTED_FAILURE_MODE
    return out


# ── §6.1 "소스 없음" 묶음 — 카탈로그에는 보이되 켤 수 없다 ──────────────────────
# 스펙 §6.1 의 마지막 행: "No source. Catalogue-visible, **non-enableable**, concrete reason
# shown". 목록에서 아예 빼면 사용자는 이 팩터들을 **고려한 적조차 없게** 된다 —
# "우리가 안 하기로 했다" 와 "그런 게 있는 줄 몰랐다" 는 다른 상태고, 후자가 더 나쁘다.
#
# 평가기가 없으므로 `evaluate()` 는 이 id 들에 None 을 돌려준다(= unavailable). 그것이
# 정확히 맞는 동작이라 별도 분기를 두지 않았다.
_UNAVAILABLE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("vix_skew", "VIX 스큐", "volatility",
     "옵션 체인 스냅샷이 필요합니다 — 수집 경로를 보유하고 있지 않습니다."),
    ("borrow_short_interest", "대차잔고 · 공매도 잔고", "regime",
     "공개 시계열 피드가 없습니다. KRX 공표는 지연·부분 공개라 시점 정합을 맞출 수 없습니다."),
    ("option_implied_correlation", "옵션 내재 상관", "correlation",
     "지수와 개별 종목 옵션 IV 를 동시에 수집해야 합니다 — 두 소스 모두 없습니다."),
    ("crowding", "포지셔닝 혼잡도", "regime",
     "포지셔닝 데이터(COT · 펀드 플로우)를 보유하고 있지 않습니다."),
)

UNAVAILABLE_FACTORS: list[dict[str, Any]] = [
    {
        "id": fid, "label": label, "family": family,
        "evaluation_frequency": "day",
        "params": {}, "default_threshold": 0.0, "default_direction": "above",
        "unit": "raw",
        "desc": f"★데이터 소스가 없어 사용할 수 없습니다★ {reason} "
                "목록에 남겨 두는 이유는, 빼 버리면 이 팩터를 검토한 적조차 없게 되기 때문입니다.",
        "provenance": "spec §6.1 (no source)",
        "provenance_class": "institutional_public",
        "existing": False,
        "use_mode": "gate",
        "allowed_range": None,
        "release_lag": None,
        "revision_policy": None,
        "availability": "unavailable",
        "unavailable_reason": reason,
        "expected_failure_mode": EXPECTED_FAILURE_MODE,
    }
    for fid, label, family, reason in _UNAVAILABLE_SPECS
]

#: §3.2 가 정의에 요구하는 필드 — 테스트가 이 목록으로 카탈로그 전체를 검사한다.
REQUIRED_DEFINITION_FIELDS = (
    "provenance", "provenance_class", "use_mode", "unit", "allowed_range",
    "evaluation_frequency", "release_lag", "revision_policy",
    "availability", "unavailable_reason", "expected_failure_mode",
)
