"""신호 정의 — 다섯 카탈로그를 ★덮는 뷰★ (P1-c)
==============================================================================
설계: `docs/specs/2026-09-12-ra-domain-architecture.md` §2
소비자: `src/api/signal_routes.py` (`GET /signals`)

## 왜 필요한가

신호·팩터 정의가 다섯 갈래로 흩어져 있어 *"이 신호가 어떤 데이터에 기대고 그
데이터가 몇 등급인가"* 를 **한 번에 물을 자리가 없었다**.

## ★통합이 아니라 뷰다★

다섯을 합치지 않는다 — 스크리너 3-레이어와 `FIELD_BY_ID` 는 CLAUDE.md §6 이
리팩터 대상이 아니라고 못 박았다. 이 모듈은 **값을 보관하지 않고** 조회 시 합치며,
각 항목이 `owner_module` 로 원본을 가리킨다. ★복사하면 반드시 갈라진다.★

## ★부분 실패를 조용히 삼키지 않는다★

출처 하나가 죽으면 나머지는 그대로 내고, **무엇이 왜 빠졌는지**를
`SignalCatalog.unavailable_sources` 에 남긴다. 빈 목록을 정상처럼 돌려주는 것이
이 저장소가 금지한 침묵 폴백이다(CLAUDE.md §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 어느 카탈로그에서 왔나.
KIND_SCREENER_FIELD = "screener_field"
KIND_TIMING_RULE = "timing_rule"
KIND_ALPHA_EXPR = "alpha_expr"
KIND_STRATEGY_TOKEN = "strategy_token"
KIND_ALPHA_REGISTERED = "alpha_registered"
SIGNAL_KINDS = (KIND_SCREENER_FIELD, KIND_TIMING_RULE, KIND_ALPHA_EXPR,
                KIND_STRATEGY_TOKEN, KIND_ALPHA_REGISTERED)


@dataclass(frozen=True)
class SignalDefinition:
    """★값의 사본이 아니라 원본을 가리키는 카드★"""
    signal_id: str
    kind: str
    label: str
    category: str
    #: ★단일 출처★ — 이 신호의 진실이 사는 모듈. 값을 복사해 오지 않는다.
    owner_module: str
    #: ★데이터 출처★(AW) — 어느 스토어에서 왔나. 스크리너 필드는
    #: `filter_ast.FieldMeta.origin` 에서 그대로 받는다. 해석이 필요 없는
    #: 구조적 사실이고, 출처 등급이 읽는 유일한 칸이다.
    origin: str | None = None
    #: 타이밍 쪽은 이미 이 둘을 안다(`timing_factor_meta` 가 출처에서 파생시킨다).
    release_lag: str | None = None
    revision_policy: str | None = None
    observation_window: dict | None = None
    #: ★출처 척도★ — `signal_evidence.PROVENANCE_GRADES`(`E0~E4`,
    #: CLAUDE.md 2절: 합성·픽스처·제공자 파생·실 과거·시점 고정).
    #: ★`source_registry.EVIDENCE_GRADES` 가 아니다★ — 그쪽은 글자만 같은
    #: **확신도** 척도이고(AV 실측), 예전 주석이 그쪽을 가리키고 있었다.
    #: `SRC_*`·`L0~L3` 와도 다른 축이다.
    evidence_grade: str | None = None
    #: 왜 그 등급인가 · 왜 미상인가. ★사유 없이 미상으로 두지 않는다.★
    evidence_grade_reason: str | None = None
    availability: str | None = None
    #: 왜 못 쓰는가. ★사유 없이 목록에서 빼지 않는다.★
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class SignalCatalog:
    signals: tuple[SignalDefinition, ...] = ()
    #: `kind` → 못 읽은 사유. ★비어 있어야만 "전부 모았다" 고 말할 수 있다.★
    unavailable_sources: dict[str, str] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════
# 어댑터 — 각자 자기 출처만 읽는다. ★원본을 고치지 않는다.★
# ══════════════════════════════════════════════════════════════════════════

def _screener_fields() -> list[SignalDefinition]:
    from src.engine.filter_ast import FIELD_BY_ID
    # ★AW 가 되살린 칸을 그대로 받는다★ — 예전에는 병합이 출처를 버려서
    #   여기까지 올 것이 없었다.
    return [SignalDefinition(
        signal_id=f.id, kind=KIND_SCREENER_FIELD, label=f.label,
        category=f.category, owner_module="src.engine.filter_ast",
        origin=getattr(f, "origin", None),
    ) for f in FIELD_BY_ID.values()]


def _timing_rules() -> list[SignalDefinition]:
    from src.engine.timing_factors import catalog
    out: list[SignalDefinition] = []
    for group in catalog().get("groups", []):
        for item in group.get("factors", []):
            out.append(SignalDefinition(
                signal_id=item.get("id", ""), kind=KIND_TIMING_RULE,
                label=item.get("label", ""), category=item.get("family", ""),
                owner_module="src.engine.timing_factors",
                release_lag=item.get("release_lag"),
                revision_policy=item.get("revision_policy"),
                availability=item.get("availability"),
                unavailable_reason=item.get("unavailable_reason"),
                # ★AX 가 되살린 칸★ — 어느 로더에서 오는지는 카탈로그가
                #   선언하고 AST 대조가 지킨다. `provenance` 는 다른 축이라
                #   싣지 않는다(스크리너 카탈로그 API 로 이미 나간다).
                origin=item.get("origin"),
            ))
    return out


def _alpha_fields() -> list[SignalDefinition]:
    from src.engine.alpha_lab import FIELDS
    return [SignalDefinition(
        signal_id=fid, kind=KIND_ALPHA_EXPR, label=label, category=group,
        owner_module="src.engine.alpha_lab",
    ) for fid, label, group, _formula in FIELDS]


def _strategy_tokens() -> list[SignalDefinition]:
    from src.kis_strategies.factor_tokens import BASE_TOKENS
    return [SignalDefinition(
        signal_id=tok, kind=KIND_STRATEGY_TOKEN, label=tok, category="token",
        owner_module="src.kis_strategies.factor_tokens",
    ) for tok in BASE_TOKENS]


def _registered_alphas() -> list[SignalDefinition]:
    """DB 가 없거나 비어 있을 수 있다 — ★빈 목록은 실패가 아니다★(예외면 실패다)."""
    from src.data.alpha_registry import list_alphas
    return [SignalDefinition(
        signal_id=str(a.get("alpha_id") or a.get("id") or ""),
        kind=KIND_ALPHA_REGISTERED, label=str(a.get("label") or a.get("name") or ""),
        category=str(a.get("status") or ""), owner_module="src.data.alpha_registry",
    ) for a in (list_alphas() or [])]


#: 테스트가 개별 출처를 죽여 볼 수 있도록 **이름으로** 건다.
_ADAPTERS = {
    KIND_SCREENER_FIELD: _screener_fields,
    KIND_TIMING_RULE: _timing_rules,
    KIND_ALPHA_EXPR: _alpha_fields,
    KIND_STRATEGY_TOKEN: _strategy_tokens,
    KIND_ALPHA_REGISTERED: _registered_alphas,
}


def collect_signals() -> SignalCatalog:
    """다섯 출처를 조회 시 합친다. ★죽은 출처는 사유와 함께 남긴다.★

    ★출처 등급은 어댑터가 아니라 규칙이 붙인다★(AV) — 다섯 어댑터는 자기
    출처만 읽고, `signal_evidence` 가 *"이 신호가 어디서 왔는가"* 를 한 자리에서
    판정한다. 어댑터마다 등급을 적으면 다섯 벌이 되고, 한쪽만 고쳐도 아무
    테스트가 깨지지 않는다.
    """
    from dataclasses import replace

    from src.domain.signal_evidence import signal_grade

    signals: list[SignalDefinition] = []
    unavailable: dict[str, str] = {}
    for kind, adapter in _ADAPTERS.items():
        try:
            signals.extend(adapter())
        except Exception as e:                           # noqa: BLE001
            unavailable[kind] = f"{type(e).__name__}: {e}"

    graded = []
    for s in signals:
        verdict = signal_grade(s)
        graded.append(replace(s, evidence_grade=verdict["grade"],
                              evidence_grade_reason=verdict["reason"]))
    return SignalCatalog(signals=tuple(graded), unavailable_sources=unavailable)
