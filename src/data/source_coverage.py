"""소스 커버리지 + "이 키를 넣으면 무엇이 열리는가" (P4-D5)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
배포 후 `.env` 에 키를 넣는 사람이 **넣기 전에 효과를 볼 수 있어야** 한다. 지금은
키가 없으면 화면이 정직하게 `unavailable` 을 낼 뿐, 무엇을 넣으면 무엇이 열리는지
말해 주지 않는다.

D1~D4 가 재료를 다 만들어 놨다 — 레지스트리(계열 선언·검증 상태·빈티지) · 능력
사다리(요건별 프로브) · 집계 계열(원천 테이블) · 적재 깊이. **이 모듈은 그것들을
조인만 한다.** 새 판정 로직을 만들지 않는다: 계열 수는 레지스트리에서 세고, 요건
가부는 `capability.probe_all()` 이 답하고, 빈티지 적격성은 `research_usage()` 가
답한다. 같은 판정을 두 곳에 두면 반드시 갈라진다.

★키 값은 어떤 형태로도 내지 않는다★
------------------------------------------------------------------------------
CLAUDE.md: "API 키를 채팅·이슈·로그에 노출 금지". 이 보고서는 화면과 로그로 나가므로
**존재 여부(bool)만** 낸다. 값·접두사·꼬리·길이·마스킹 조각도 내지 않는다 —
마스킹은 안전해 보이지만 길이와 접두사를 흘리고, 그걸로 어느 키인지 좁혀진다.
그래서 이 모듈은 환경변수를 `os.getenv(...)` 로 읽되 **즉시 `bool()` 로 접어** 값이
어떤 반환 경로에도 실리지 않게 한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from src.data.source_registry import (
    ECOS,
    FRED,
    GOOGLE,
    KRX,
    NAVER,
    all_specs,
    revision_bias_note,
    specs_by_provider,
)

# 집계 계열의 원천 — ECOS/FRED 처럼 레지스트리 계열을 갖지는 않지만 키가 필요하다.
DART = "DART"
KIS = "KIS"


def _configured(*env_vars: str) -> bool:
    """★값을 절대 밖으로 내보내지 않는다★ 여기서 즉시 bool 로 접는다.

    호출자가 값을 만질 수 없어야 유출 경로가 구조적으로 닫힌다 — 반환 타입이
    `bool` 이므로 실수로 실을 수도 없다.
    """
    return any(bool((os.getenv(v) or "").strip()) for v in env_vars)


@dataclass(frozen=True)
class KeySlot:
    """환경변수 하나(또는 한 묶음)와 그것이 여는 것."""

    label: str
    env_vars: tuple[str, ...]
    provider: str | None                      # 레지스트리 계열을 여는 경우
    series_count: int                         # 그 제공자의 선언 계열 수 (레지스트리에서 유도)
    capability_requirements: tuple[str, ...]  # 이 키가 막고 있는 사다리 요건
    unlocks_levels: tuple[str, ...]           # 그 요건이 걸린 레벨
    unlocks: str                              # 사람이 읽는 한 줄
    configured: bool = False
    note: str = ""
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)


def _levels_for(requirements: tuple[str, ...]) -> tuple[str, ...]:
    """요건 이름 → 그 요건이 걸린 레벨. `capability` 의 선언에서 유도한다."""
    from src.engine.capability import LEVEL_REQUIREMENTS
    return tuple(lv for lv, reqs in LEVEL_REQUIREMENTS.items()
                 if any(r in reqs for r in requirements))


#: 키 슬롯 선언 — `.env.example` 의 슬롯과 같은 이름을 쓴다.
#: `series_count`/`unlocks_levels` 는 **여기 적지 않는다** — 아래에서 유도한다.
_SLOT_DECL: tuple[tuple[str, tuple[str, ...], str | None, tuple[str, ...], str], ...] = (
    ("한국은행 ECOS", ("BOK_API_KEY",), ECOS, (),
     "한국 매크로 계열"),
    ("FRED / ALFRED", ("FRED_API_KEY",), FRED, (),
     "미국 매크로 계열 (ALFRED 빈티지 → 백테스트 적격)"),
    ("KRX", ("KRX_API_KEY",), KRX, (),
     "KRX 파생 지표 + 일별 전종목 백필(집계 매크로의 원천)"),
    ("DART", ("DART_API_KEY",), DART, (),
     "재무 원천 — 분기 집계 매크로"),
    ("KIS", ("KIS_APP_KEY", "KIS_APP_SECRET"), KIS, (),
     "시세·투자자 수급 — 일간 집계 매크로"),
    ("검색 트렌드", ("NAVER_CLIENT_ID", "GOOGLE_TRENDS_API_KEY"), NAVER, ("trends_api",),
     "검색 트렌드 계열"),
    ("LLM (Anthropic)", ("ANTHROPIC_API_KEY",), None, ("llm",),
     "공시문 → 뷰 변환 (Agentic MCP 프론티어 엔진)"),
)


def key_slots() -> tuple[KeySlot, ...]:
    """키 슬롯 현황. **호출할 때마다 환경을 다시 읽는다** — 키를 넣자마자 반영돼야
    하므로 캐시하지 않는다(`capability.probe_all` 이 캐시하지 않는 것과 같은 이유)."""
    out: list[KeySlot] = []
    for label, env_vars, provider, reqs, what in _SLOT_DECL:
        # ★계열 수는 세지 말고 레지스트리에서 유도한다★ (CLAUDE.md)
        n = len(specs_by_provider(provider)) if provider else 0
        if provider == NAVER:               # 트렌드는 두 제공자에 걸쳐 있다
            n += len(specs_by_provider(GOOGLE))
        levels = _levels_for(reqs)
        bits = []
        if n:
            bits.append(f"계열 {n}종")
        if reqs:
            bits.append("사다리 요건 " + "·".join(reqs))
        if levels:
            bits.append("레벨 " + "·".join(sorted(levels)))
        out.append(KeySlot(
            label=label, env_vars=tuple(env_vars), provider=provider,
            series_count=n, capability_requirements=tuple(reqs),
            unlocks_levels=levels,
            unlocks=f"{what} — " + (", ".join(bits) if bits else "사다리 요건 없음"),
            configured=_configured(*env_vars),
        ))
    return tuple(out)


def _provider_rows() -> list[dict[str, Any]]:
    """제공자별 커버리지 — 선언/검증/빈티지 적격성."""
    from src.data.source_registry import PROVIDER_HAS_VINTAGE
    rows: list[dict[str, Any]] = []
    for provider in sorted({s.provider for s in all_specs()}):
        specs = specs_by_provider(provider)
        # 사유는 계열 하나를 대표로 읽는다 — 사유는 제공자 속성이다(P4-D1).
        note = revision_bias_note(specs[0].key) if specs else None
        rows.append({
            "provider": provider,
            "declared": len(specs),
            "verified": sum(1 for s in specs if s.verified_live),
            "derived": sum(1 for s in specs if s.derived_from),
            "backtest_eligible": bool(PROVIDER_HAS_VINTAGE.get(provider, False)),
            "revision_bias_note": note,
        })
    return rows


def coverage_report(*, include_ladder: bool = True) -> dict[str, Any]:
    """한 장의 표 — 제공자 커버리지 · 키 슬롯 · 사다리 현황.

    ★값이 아니라 상태만 낸다★ 키는 `configured: bool`, 계열은 개수, 사다리는
    레벨과 사유. 어떤 필드에도 비밀이 실리지 않는다.

    ★비용을 적어 둔다 (실측)★
    ┌─────────────────────────────────────────────┬────────┐
    │ `key_slots()` (환경변수만)                   │ 0.00초 │
    │ `coverage_report()` — 키 없음                │ 1.1초  │
    │ `coverage_report()` — 키 있으나 호스트 불통  │ 51.6초 │
    └─────────────────────────────────────────────┴────────┘
    사다리의 `frontier_sample` 프로브가 관측 수를 **실제로 세느라** 매크로를 수집하고,
    키가 있으면 수집기가 라이브 호출을 시도하기 때문이다. 이 환경처럼 호스트가 막혀
    있으면 계열마다 스로틀 + 타임아웃을 문다.

    프로브를 캐시해서 가리지 않는다 — M1-C 가 "의존성이 설치되면 그 즉시 사다리가
    열려야 한다" 를 근거로 캐시를 거부했고 그 판단은 유효하다. 대신 **비용을 고르게**
    한다: 키·제공자 표만 필요하면 `include_ladder=False` 로 즉시 받고, 사다리가
    필요할 때만 값을 치른다.
    """
    ladder: dict[str, Any] | None = None
    if include_ladder:
        from src.engine.capability import resolve
        res = resolve()
        ladder = {
            "level": res.get("level"),
            "note": res.get("note"),
            "blocked_level": res.get("blocked_level"),
            "blocked_reason": res.get("blocked_reason"),
        }
    return {
        "providers": _provider_rows(),
        "keys": [
            {
                "label": s.label,
                "env_vars": list(s.env_vars),
                "configured": s.configured,
                "provider": s.provider,
                "series_count": s.series_count,
                "capability_requirements": list(s.capability_requirements),
                "unlocks_levels": list(s.unlocks_levels),
                "unlocks": s.unlocks,
            }
            for s in key_slots()
        ],
        "ladder": ladder,
    }
