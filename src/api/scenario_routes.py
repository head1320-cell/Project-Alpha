"""시나리오 API — 팩 실행 · 3자 비교 (스펙 §5 × Phase 7b, Phase 9).

왜 새 라우터인가
──────────────────────────────────────────────────────────────────────────────
§7 의 방향은 "`allocation_routes.py` 를 더 키우지 말고 새 라우터" 이고, 기술부채 정리에서
`timing_routes.py` 로 그 패턴이 이미 검증됐다. 프리픽스는 `/api/v1/allocation` 그대로다 —
§7 의 문제 제기는 모듈 크기이지 URL 구조가 아니다.

★재구현하지 않는다★
- 3자 비교의 파생은 `rule_set_states` + `three_way` 를 **그대로** 부른다. 두 번째 구현을
  만들면 타이밍 탭과 스트레스 탭이 서로 다른 신호를 "같은 것" 이라며 비교하게 된다.
- 충격 계산은 기존 경로에 위임한다. m8·역사 리플레이는 `allocation_stress` 가 이미 하는
  일이고(라이브 경로 — 본문을 건드리지 않는다), 국내팩·인라인 팩은 `run_scenario` 다.

★합성은 곱셈이다★ (사용자 결정)
3자 비교는 다리마다 노출(0~1)을, 시나리오는 손실(%)을 준다. 다리별 손실 = 충격 × 노출이고
나머지는 현금이라 충격을 받지 않는다. 새로운 시나리오 수학은 없다 —
`scenario_packs.compose_with_exposure` 한 줄이며 선형 근사라는 사실이 응답에 함께 나간다.

★사용자 정의 팩의 `model_type` 은 서버가 정한다★
클라이언트가 "역사적 사실" 이라고 주장할 수 있으면 §5 전체가 무의미해진다. 인라인 팩은
언제나 `hypothetical` 이고 저장되지 않는다(저장·버전·삭제는 Phase 10).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.scenario")

router = APIRouter(prefix="/api/v1/allocation", tags=["scenario"])


#: 계수·가정의 허용 범위. ★경계를 스키마가 막는다★
#: 이 값들은 `_z()` 로 표준화된 노출(±3σ 클립)에 곱해지고, 그 결과가 다시 변동성·VaR 프록시로
#: 들어간다. 1e300 같은 값이 들어오면 곱셈이 inf 가 되고 inf 는 JSON 에 그대로 실려 나가 엄격한
#: 파서를 깨뜨린다 — 계산 중간에 잡는 것보다 입구에서 거절하는 편이 사유가 분명하다.
_Coefficient = Annotated[float, Field(ge=-100, le=100)]
_Assumption = Annotated[float, Field(ge=-10, le=10)]


class InlinePack(BaseModel):
    """사용자 정의 충격. `model_type` 필드는 **없다** — 서버가 정한다."""
    label: str = Field("사용자 정의 시나리오", max_length=200)
    description: str = Field("", max_length=1000)
    market: float = Field(..., ge=-90, le=90)              # 시장 기본충격 (%)
    #: 팩터 → 계수 (%). 팩터 수는 엔진의 노출 행렬(7종)이 상한이다.
    factors: dict[str, _Coefficient] = Field(..., min_length=1, max_length=16)
    assumptions: dict[str, _Assumption] = Field(default_factory=dict, max_length=16)


class ScenarioRunRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    pack_id: str | None = Field(None, max_length=80)
    pack: InlinePack | None = None
    severity: float = Field(1.0, ge=0.25, le=3.0)
    sleeves: dict[str, str] | None = None
    benchmark: str = "069500"


class ScenarioThreeWayRequest(ScenarioRunRequest):
    """시나리오 × 3자 비교. 타이밍 쪽 필드는 `/timing/three-way` 와 같은 이름이다."""
    market: str = Field("kr", pattern="^(us|kr)$")
    combination: str = "all"
    k: int = Field(1, ge=1, le=50)
    weights: list[float] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)
    regime_snapshot_id: str | None = Field(None, max_length=40)
    overlay_enabled: bool = True
    as_of: str | None = Field(None, max_length=32)


def _resolve_pack(req: ScenarioRunRequest) -> tuple[object, dict | None]:
    """`pack_id`(등록·저장) 또는 인라인 정의 → `(ScenarioPack, 정의|None)`. 정확히 하나여야 한다.

    정의를 함께 돌려주는 이유: 등록 팩은 계수가 엔진 안에 있지만 인라인·저장 팩은 요청/DB 에
    있다. `_run_pack` 이 출처마다 다시 찾아 나서면 "어디서 계수를 읽는가" 가 두 곳으로 갈라진다.

    ★저장 팩은 등록 팩 **다음**에 찾는다★ 등록 id 를 저장 팩이 가릴 수 있으면, 사용자가
    `semi_selloff` 라는 이름으로 저장하는 것만으로 내장 시나리오를 조용히 바꿔치기할 수 있다.
    """
    from src.engine.scenario_packs import definition_of, get_pack, inline_pack, saved_pack

    if bool(req.pack_id) == bool(req.pack):
        raise HTTPException(
            422, "pack_id 또는 인라인 pack 중 **정확히 하나**가 필요합니다"
                 + (" — 둘 다 주어졌습니다." if req.pack_id else " — 둘 다 비어 있습니다."))
    if req.pack is not None:
        return inline_pack(req.pack.model_dump()), req.pack.model_dump()

    pid = req.pack_id or ""
    pack = get_pack(pid)
    if pack is not None:
        return pack, None

    from src.data.scenario_packs_store import get_pack as get_saved
    row = get_saved(pid)
    if row is None:
        raise HTTPException(422, f"알 수 없는 시나리오 팩: {req.pack_id}")
    return saved_pack(row), definition_of(row)


def _run_pack(pack, req: ScenarioRunRequest, definition: dict | None = None) -> dict:
    """팩 실행 → 원 결과 + `shock_pct`/`shock_basis`.

    ★두 종류의 손실을 같은 이름으로 부르지 않는다★ 가정 충격은 즉시 손실(%)을 내고, 역사
    리플레이는 그 구간의 **최대 낙폭**을 낸다. 둘 다 `shock_pct` 로 싣되 `shock_basis` 가
    무엇을 잰 숫자인지 밝힌다 — 밝히지 않으면 나란히 놓인 두 팩이 비교 가능해 보인다.
    """
    holdings = {str(c): max(float(w), 0.0) for c, w in req.holdings.items()}

    if pack.engine in ("kr_pack", "inline", "saved"):
        from src.engine.kr_scenario_pack import run_scenario
        # 정의는 `_resolve_pack` 이 이미 골라 놓았다 — 등록 팩은 None(엔진이 계수를 갖는다),
        # 인라인·저장 팩은 그 정의. 여기서 다시 출처를 판단하지 않는다.
        out = run_scenario(list(holdings), holdings, pack.engine_key,
                           severity=req.severity, sleeves=req.sleeves,
                           definition=definition)
        if out.get("error"):
            raise HTTPException(422, out.get("message") or "시나리오 실행에 실패했습니다.")
        return {**out, "shock_pct": out.get("portfolio_shock_pct"),
                "shock_basis": "즉시 충격 (팩터 민감도 선형 추정)"}

    # m8 · 역사 리플레이 — 기존 라이브 경로에 그대로 위임한다(본문 무변경).
    from src.api.allocation_routes import StressRequest, allocation_stress
    out = allocation_stress(StressRequest(
        holdings=holdings, scenario=pack.engine_key,
        severity=req.severity, benchmark=req.benchmark))
    if out.get("error"):
        raise HTTPException(422, out.get("message") or "시나리오 실행에 실패했습니다.")
    if out.get("available") is False:
        # ★미가용을 0 으로 채우지 않는다★ 데이터가 없는 구간은 "충격 없음" 이 아니다.
        return {**out, "shock_pct": None,
                "shock_basis": "미가용 — 해당 구간 시세를 보유하지 않습니다"}
    if out.get("mode") == "historical":
        return {**out, "shock_pct": out.get("max_dd_pct"),
                "shock_basis": "구간 최대 낙폭 (실제 시세 리플레이)"}
    return {**out, "shock_pct": out.get("portfolio_shock_pct"),
            "shock_basis": "즉시 충격 (펀더멘털·베타 민감도 추정)"}


# ── 사용자 정의 팩 CRUD (Phase 10a — Phase 9 에서 재배치된 §5 `user-authored`) ────────
class PackSaveRequest(BaseModel):
    """저장 요청. ★`model_type` 필드는 여기에도 없다★ — 저장 경로가 §5 의 구멍이 되면 안 된다.

    본문은 `InlinePack` 을 그대로 재사용한다(경계값 검증이 이미 붙어 있다). 실행과 저장이
    서로 다른 스키마를 쓰면 인라인으로는 통과하는 값이 저장으로는 막히는 일이 생긴다.
    """
    pack: InlinePack
    notes: str = Field("", max_length=2000)
    #: 지정하면 갱신 — 버전이 오르고 그 시점 내용이 이력에 남는다.
    pack_id: str | None = Field(None, max_length=40)


@router.post("/scenario-packs")
def scenario_pack_save(req: PackSaveRequest):
    """사용자 정의 팩 저장/갱신. 저장돼도 `model_type` 은 언제나 `hypothetical` 이다."""
    from src.data.scenario_packs_store import get_pack as get_saved
    from src.data.scenario_packs_store import save_pack
    from src.engine.scenario_packs import saved_pack

    spec = {**req.pack.model_dump(), "notes": req.notes}
    pid = save_pack(spec, req.pack_id)
    if pid is None:
        # ★두 실패를 같은 말로 보고하지 않는다★ 고쳐야 할 것이 서로 다르다
        # (`timing-rules` 저장이 같은 이유로 갈라 두었다).
        if req.pack_id:
            raise HTTPException(
                422, f"갱신할 시나리오 팩을 찾을 수 없습니다: {req.pack_id}. "
                     "삭제되었을 수 있습니다 — 새 팩으로 저장하세요.")
        raise HTTPException(503, "시나리오 팩 저장소(DB)를 사용할 수 없습니다.")
    row = get_saved(pid) or {}
    return {"pack_id": pid, "version": row.get("version"),
            **saved_pack(row).to_dict()}


@router.get("/scenario-packs")
def scenario_packs_list(limit: int = 50):
    from src.data.scenario_packs_store import list_packs
    from src.engine.scenario_packs import saved_pack
    return {"packs": [{**saved_pack(r).to_dict(), "version": r.get("version"),
                       "updated_at": r.get("updated_at")} for r in list_packs(limit)]}


@router.get("/scenario-packs/{pack_id}/versions")
def scenario_pack_versions(pack_id: str):
    """버전 이력 — 런에 박힌 팩 버전이 **아직 실재하는지** 확인하는 용도.

    해시를 함께 싣는다. 버전 번호만으로는 "v3 과 v4 가 실제로 다른 충격인가" 를 알 수 없는데,
    그걸 모르면 재현 가능 여부도 판단할 수 없다.
    """
    from src.data.scenario_packs_store import list_pack_versions
    return {"pack_id": pack_id, "versions": list_pack_versions(pack_id)}


@router.delete("/scenario-packs/{pack_id}")
def scenario_pack_delete(pack_id: str):
    from src.data.scenario_packs_store import delete_pack
    if not delete_pack(pack_id):
        raise HTTPException(404, "시나리오 팩을 찾을 수 없습니다.")
    return {"deleted": True}


@router.post("/scenario-run")
def scenario_run(req: ScenarioRunRequest):
    """시나리오 팩 실행 — 등록된 팩 또는 요청에 실린 사용자 정의 팩.

    결과에 `model_type` 과 팩 정체성이 **함께** 실린다. 라벨이 결과와 떨어져 다니면
    "이건 가정입니다" 가 카탈로그 화면에만 남고 결과 화면에서는 사라진다(§5).
    """
    pack, definition = _resolve_pack(req)
    out = _run_pack(pack, req, definition)
    return {**out, "pack": pack.to_dict(),
            "model_type": pack.model_type.value,
            "pack_id": pack.pack_id, "content_hash": pack.content_hash,
            "identity": pack.identity}


@router.post("/scenario-three-way")
def scenario_three_way(req: ScenarioThreeWayRequest):
    """기준 vs 타이밍만 vs 타이밍+매크로 — **시나리오 아래에서**.

    Phase 7b 가 만든 비교를 두 번째로 구현하지 않는다. 같은 `rule_set_states` 파생과 같은
    `three_way` 를 쓰고, 여기서는 그 결과의 **노출**만 시나리오 손실에 곱한다.
    """
    from src.data.regime_snapshots import get_snapshot
    from src.engine import timing_rules_v2 as v2
    from src.engine.macro_overlay import (
        conflict_explanation,
        overlay_from_snapshot,
        three_way,
    )
    from src.engine.scenario_packs import COMPOSITION_NOTE, compose_with_exposure

    if req.combination not in v2.COMBINATION_METHODS:
        raise HTTPException(
            422, f"알 수 없는 조합 방식: {req.combination}. "
                 f"가능한 값: {', '.join(v2.COMBINATION_METHODS)}")
    if not req.rules:
        raise HTTPException(422, "비교할 타이밍 규칙이 최소 1개 필요합니다.")

    pack, definition = _resolve_pack(req)
    scenario = _run_pack(pack, req, definition)

    overlay = None
    if req.regime_snapshot_id:
        snap = get_snapshot(req.regime_snapshot_id)
        if snap is None:
            raise HTTPException(
                422, f"국면 스냅샷을 찾을 수 없습니다: {req.regime_snapshot_id}. "
                     "스냅샷은 매크로 탭에서 먼저 저장해야 합니다.")
        overlay = overlay_from_snapshot(snap, enabled=req.overlay_enabled)

    rule_set = v2.rule_set_from_specs(
        req.rules, market=req.market, combination=req.combination,
        k=req.k, weights=req.weights, set_id="scenario_three_way")
    try:
        states = v2.rule_set_states(rule_set, as_of=req.as_of, market=req.market)
        legs = three_way(states, method=req.combination, overlay=overlay,
                         k=req.k, weights=list(req.weights) or None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    shock = scenario.get("shock_pct")
    # ★판정하지 못한 다리에는 손실을 적지 않는다★
    # 오버레이가 없으면 `timing_macro` 는 노출 0.0 의 **unavailable** 이다. 그 0 을 그대로
    # 곱하면 "매크로를 붙인 쪽은 한 푼도 안 잃었다" 로 표시되어, 만들지 못한 다리가 셋 중
    # 가장 안전해 보인다. 노출 0 인 현금 포지션과 "알 수 없음" 은 다른 사실이다.
    usable = {n: s.exposure for n, s in legs.items()
              if s.state is not v2.SignalState.UNAVAILABLE}
    composed = (compose_with_exposure(shock, usable)
                if shock is not None and usable else None)

    return {
        "legs": {name: {
            "state": sig.state.value, "exposure": sig.exposure, "method": sig.method,
            "on_count": sig.on_count, "off_count": sig.off_count,
            "unavailable_count": sig.unavailable_count, "explanation": sig.explanation,
            **(composed.get(name, {}) if composed else {}),
        } for name, sig in legs.items()},
        "scenario": {
            "shock_pct": shock, "shock_basis": scenario.get("shock_basis"),
            "label": pack.label, "available": scenario.get("available", True),
            **({"reason": scenario["reason"]} if scenario.get("reason") else {}),
        },
        "pack": pack.to_dict(),
        "model_type": pack.model_type.value,
        "identity": pack.identity,
        "overlay": overlay.to_dict() if overlay is not None else None,
        "conflict": conflict_explanation(legs["timing_only"], overlay),
        "combination": req.combination,
        "composition_note": COMPOSITION_NOTE,
        # 충격을 못 구했으면 다리별 손실도 없다 — 0 으로 채우면 "충격 없음" 으로 읽힌다.
        "composed": composed is not None,
    }
