"""타이밍 API — 팩터 카탈로그 · 과거 미리보기 · 규칙 세트 CRUD · 평가 · 3자 비교.

스펙 §7 이 지정한 라우터. Phase 8b 까지 이 모듈이 **없어서** 타이밍 엔드포인트가
`allocation_routes.py`(1601줄) 안에 계속 쌓였다 — §7 이 "더 키우지 말라" 고 적은 바로 그
파일이다. 이 분리로 그 파일은 1133줄이 되고 타이밍 로직은 한 곳에 모인다.

★URL 은 한 글자도 바뀌지 않는다★
프리픽스를 `/api/v1/allocation` 으로 그대로 둔다. §7 의 문제 제기는 1601줄짜리 모듈이지
URL 구조가 아니다. 경로를 바꾸면 프론트엔드 클라이언트·E2E·저장된 룰셋이 전부 깨진다.
`tests/test_route_parity.py` 가 이동 **전에** 통과하도록 먼저 작성됐고, 이동 후에도 같은
{메서드, 경로} 집합을 요구한다.

★`POST /timing` 은 레거시 카나리 경로다★ (Drift D7-1)
`_canary_eval`/`passes()` 기반이고 라이브에서 쓰인다. D7-1 의 규칙은 "`passes()` 를 고치지
말 것" 이며, 파일을 옮기는 것은 거기에 해당하지 않는다 — 본문은 한 줄도 바꾸지 않았다.
"""

from __future__ import annotations

import logging

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.timing")

# ★프리픽스는 allocation 그대로★ — 모듈만 나뉘고 URL 은 불변이다.
router = APIRouter(prefix="/api/v1/allocation", tags=["timing"])


# ── 카나리·마켓타이밍 스키마 ─────────────────────────────────────────────────
class CanarySpec(BaseModel):
    kind: str = "asset"                      # asset|indicator
    id: str                                  # 자산 티커 또는 매크로 시리즈 id(VIXCLS 등)
    # 기존 4종 + 신규 팩터 id(avg_abs_momentum·accel_momentum·disparity·vol_breakout·
    # channel_breakout·overnight_return·defense_first) — timing_factors.CATALOG와 동일 id 체계
    signal: str = "score_13612"
    lookback: int = Field(12, ge=1, le=252)
    threshold: float = 0.0
    direction: str = "above"                 # above|below (threshold/indicator 통과 방향)
    params: dict[str, float] = Field(default_factory=dict)   # 팩터별 파라미터(ma_days·k·days 등)
    # ── TimingRule 공통 스키마(선택) — 지정 시 규칙 등록/저장에 그대로 실림 ──
    universe: list[str] = Field(default_factory=list)
    risk_off_asset: list[str] = Field(default_factory=list)
    rebalance_or_holding_period: str | None = None
    position_sizing: str | None = None
    leverage_cap: float | None = Field(None, ge=0, le=5)
    entry_condition: str | None = None
    exit_condition: str | None = None


class TimingRequest(BaseModel):
    market: str = "kr"                       # kr|us
    canaries: list[CanarySpec] = Field(..., min_length=1, max_length=8)
    min_breadth: int = Field(0, ge=0, le=8)  # 0 = 전부 통과 · k = k-of-N
    risk_on_assets: list[str] = Field(default_factory=list)
    risk_off_assets: list[str] = Field(default_factory=list)
    holdings: dict[str, float] | None = None  # 현재 포트폴리오(리스크-온 유지 + 오버레이 대상)
    overlay: dict | None = None              # {"type":"ma_day"|"abs_mom"|"none","n":200,"lookback":12}
    regime_blend: bool = False               # 이진 게이트 대신 국면확률 가중 연속 노출(휩쏘 억제)
    target_vol_pct: float | None = Field(None, ge=2, le=40)  # 목표 변동성(연 %) — 위험자산 노출 스케일


# ── /timing ──────────────────────────────────────────────────────────────────
def _canary_eval(c: CanarySpec, mk: str):
    """단일 카나리 평가 → (통과 여부|None, 표시값|None)."""
    if c.kind == "indicator":
        from src.engine.macro_analytics import _latest, _macro_series
        val = _latest(_macro_series(), c.id)
        if val is None:
            return None, None
        ok = (float(val) > c.threshold) if c.direction == "above" else (float(val) < c.threshold)
        return ok, round(float(val), 3)
    # 신규 팩터(모멘텀 연속비중·이격도·돌파·오버나이트·Defense First) — timing_factors 카탈로그
    from src.engine import timing_factors as _tf
    if c.signal in _tf.CATALOG_BY_ID and c.signal not in (
            "score_13612", "abs_mom", "ma_month", "ma_day", "indicator"):
        p = dict(c.params or {})
        # lookback 하나로 조작하던 기존 UI 호환 — 팩터별 주 파라미터에 매핑
        meta = _tf.CATALOG_BY_ID[c.signal]
        for k in ("months", "days", "max_months", "ma_days"):
            if k in (meta.get("params") or {}) and k not in p and c.lookback:
                p[k] = c.lookback
        v = _tf.evaluate(c.signal, c.id, mk, p)
        ok = _tf.passes(v, c.threshold, c.direction)
        return ok, (round(v, 4) if v is not None else None)

    from src.engine.tactical_allocations import (
        _above_ma_d,
        _above_ma_m,
        _abs_mom,
        _score_13612,
    )
    if c.signal == "abs_mom":
        v = _abs_mom(c.id, mk, c.lookback)
        return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)
    if c.signal == "score_13612":
        v = _score_13612(c.id, mk)
        return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)
    if c.signal == "ma_month":
        v = _above_ma_m(c.id, mk, max(c.lookback, 2))
        return (v is True), (1.0 if v else 0.0 if v is not None else None)
    if c.signal == "ma_day":
        v = _above_ma_d(c.id, mk, max(c.lookback, 5))
        return (v is True), (1.0 if v else 0.0 if v is not None else None)
    v = _abs_mom(c.id, mk, c.lookback)
    return (v is not None and v > c.threshold), (round(v, 4) if v is not None else None)


def _timing_holding(t: str, mk: str) -> tuple[str, str]:
    from src.data.etf_prices import resolve
    from src.data.stock_master import get_stock_name
    code, name = resolve(t, mk)
    if not name or name == code or name == t:
        name = get_stock_name(code) or get_stock_name(t) or name or code
    return code, name


def _timing_regime_probs(mk: str) -> dict | None:
    """현재 국면 확률(4사분면, 합=1) — 리짐-확률 블렌드용. 실패 시 None(정직 폴백)."""
    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        state = RegimeAnalyzer().analyze(market=("kr" if mk == "kr" else "us"))
        probs = dict(getattr(state, "regime_probs", {}) or {})
        if probs:
            return probs
        from src.engine.regime_axes import quadrant_probs
        return quadrant_probs(float(getattr(state, "growth_axis", 0) or 0),
                              float(getattr(state, "inflation_axis", 0) or 0))
    except Exception as e:
        logger.debug(f"timing 국면확률 실패(무시): {e}")
        return None


def _timing_realized_vol_pct(weights_pct: dict[str, float], mk: str) -> float | None:
    """위험자산 비중 바스켓의 실현 연율 변동성(%) — etf_prices 일별 수익 + Ledoit-Wolf 공분산."""
    tickers = [t for t, w in weights_pct.items() if w > 0]
    if len(tickers) < 1:
        return None
    try:
        from src.engine.macro_analytics import _aligned_returns, _closes_map
        from src.engine.risk_allocations import _cov
        names, R = _aligned_returns(_closes_map(tickers, mk, 400))
        if not names or R is None or R.shape[0] < 60:
            return None
        w = np.array([max(weights_pct.get(t, 0.0), 0.0) for t in names], dtype=float)
        s = w.sum()
        if s <= 0:
            return None
        w = w / s
        var_d = float(w @ _cov(R) @ w)
        return float(np.sqrt(max(var_d, 0.0) * 252.0) * 100.0)
    except Exception as e:
        logger.debug(f"timing 실현변동성 실패(무시): {e}")
        return None


# ── 타이밍 팩터 카탈로그 · 규칙 세트 (통합 팩터 창) ──────────────────────────
@router.get("/timing-factors")
def allocation_timing_factors():
    """팩터 창 카탈로그 — 패밀리별 그룹 + TimingRule 공통 스키마 필드 + 정직성 노트."""
    try:
        from src.engine.timing_factors import catalog
        return catalog()
    except Exception:
        logger.exception("timing-factors 카탈로그 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/timing-factors/{factor_id}/history")
def allocation_timing_factor_history(
    factor_id: str,
    ticker: str = Query("SPY", max_length=20),
    market: str = Query("kr", pattern="^(us|kr)$"),
    months: int = Query(24, ge=1, le=240),
    threshold: float | None = Query(None),
    direction: str | None = Query(None, pattern="^(above|below)$"),
):
    """팩터 과거 미리보기 — 값/임계/3-상태/전환횟수 (스펙 §8.1 요구 4).

    각 점은 `etf_prices.as_of(m)` 안에서 평가되어 그 시점 이후 시세를 보지 못한다.
    값을 만들 수 없는 팩터는 빈 그래프가 아니라 `limitations` 에 사유를 담아 200 으로 답한다 —
    미리보기 실패는 요청 오류가 아니고, 사용자는 왜 비었는지 알아야 한다.
    """
    try:
        from src.engine.timing_factor_history import factor_history
        return factor_history(factor_id, ticker.upper(), market, months=months,
                              threshold=threshold, direction=direction).to_dict()
    except Exception:
        logger.exception("timing factor history 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class TimingRuleSetRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    market: str = "kr"
    rules: list[dict] = Field(default_factory=list)   # TimingRule 스펙 리스트
    gate: dict = Field(default_factory=dict)          # 브레드스·자산군·오버레이·리스크제어
    notes: str | None = Field(None, max_length=2000)
    set_id: str | None = None                         # 지정 시 갱신


@router.post("/timing-rules")
def allocation_timing_rules_save(req: TimingRuleSetRequest):
    """규칙 세트 저장/갱신 — 각 rule은 TimingRule 스키마로 정규화해 보관(재현 가능)."""
    try:
        from src.data.timing_rules import save_rule_set
        from src.engine.timing_factors import rule_from_spec, stamp_pit
        norm = [stamp_pit(rule_from_spec(r)).to_dict() for r in (req.rules or [])]
        sid = save_rule_set(req.name, req.market, norm, req.gate, req.notes, req.set_id)
        if sid is None:
            # ★두 실패를 같은 말로 보고하지 않는다★
            # `save_rule_set` 은 "갱신할 세트가 없다" 와 "저장소를 못 쓴다" 를 똑같이 None 으로
            # 돌려준다. 둘 다 503("DB 를 쓸 수 없습니다")이라고 말하면, 세트가 삭제된 사용자는
            # 고칠 수 있는 문제를 인프라 장애로 오해하고 그대로 막힌다.
            if req.set_id:
                raise HTTPException(
                    422, f"갱신할 타이밍 룰셋을 찾을 수 없습니다: {req.set_id}. "
                         "삭제되었을 수 있습니다 — 새 룰셋으로 저장하세요.")
            raise HTTPException(503, "규칙 저장소(DB)를 사용할 수 없습니다.")
        # 저장된 버전을 함께 돌려준다 — 호출자가 재현 좌표(id + version)를 바로 들 수 있어야
        # 한다. ★버전 열이 degraded 면 None 을 준다 — 1 로 지어내지 않는다★ 그러면 이후에
        # 그 런이 어떤 룰로 계산됐는지 복원할 수 없는데도 복원 가능한 척하게 된다.
        from src.data.timing_rules import get_rule_set
        cur = get_rule_set(sid) or {}
        return {"set_id": sid, "version": cur.get("version"), "rules": norm}
    except HTTPException:
        raise
    except Exception:
        logger.exception("timing rule set 저장 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/timing-rules")
def allocation_timing_rules_list(limit: int = Query(50, ge=1, le=200)):
    try:
        from src.data.timing_rules import list_rule_sets
        return {"sets": list_rule_sets(limit=limit)}
    except Exception:
        logger.exception("timing rule set 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/timing-rules/{set_id}/versions")
def allocation_timing_rule_versions(set_id: str):
    """룰셋의 버전 이력 — 런에 박힌 버전이 **아직 실재하는지** 확인하는 용도.

    ★없는 버전을 현재 버전으로 대신 보여주면 안 된다★
    런은 계산 시점의 버전을 기록한다. 그 버전이 사라졌는데 화면이 현재 버전을 보여주면
    사용자는 그 런이 재현됐다고 믿는다 — 실제로는 다른 규칙으로 계산된 결과를 보고 있다.
    그래서 이 엔드포인트는 존재하는 버전만 돌려주고, 판단은 호출자가 한다.
    """
    from src.data.timing_rules import list_rule_set_versions
    return {"set_id": set_id, "versions": list_rule_set_versions(set_id)}


@router.delete("/timing-rules/{set_id}")
def allocation_timing_rules_delete(set_id: str):
    from src.data.timing_rules import delete_rule_set
    if not delete_rule_set(set_id):
        raise HTTPException(404, "규칙 세트를 찾을 수 없습니다.")
    return {"deleted": True}


class TimingThreeWayRequest(BaseModel):
    """3자 비교 요청 — V2 룰셋 스펙 + 붙일 국면 스냅샷.

    ★`TimingRequest`(레거시 카나리)와 별개다★ 이름이 비슷하다는 이유로 합치면 `passes()`
    기반 라이브 경로에 V2 3-상태 로직이 섞인다(Drift D7-1 이 피한 회귀).
    """
    market: str = Field("kr", pattern="^(us|kr)$")
    combination: str = "all"
    k: int = Field(1, ge=1, le=50)
    weights: list[float] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)
    #: 오버레이의 출처. **라이브 매크로가 아니라 버전이 박힌 스냅샷**이다.
    regime_snapshot_id: str | None = Field(None, max_length=40)
    #: 룰과 독립적으로 끌 수 있어야 한다 (스펙 §8: "조용한 오버라이드가 아니다").
    overlay_enabled: bool = True
    as_of: str | None = Field(None, max_length=32)


@router.post("/timing/three-way")
def allocation_timing_three_way(req: TimingThreeWayRequest):
    """기준 vs 타이밍만 vs 타이밍+매크로 — 스펙 §8 3자 비교의 HTTP 표면.

    `e6e05c1` 이 엔진(`MacroOverlay`·`three_way`·`conflict_explanation`)을 만들었지만 표면이
    없어 UI 에서 닿을 수 없었다. 이 라우트가 그 배선이며, 타이밍 단독 평가
    (`evaluate_rule_set`)와 **같은** `rule_set_states()` 파생을 쓴다 — 두 경로가 갈라지면
    비교되는 두 다리가 서로 다른 신호가 되고, 그건 비교가 아니다.
    """
    from src.data.regime_snapshots import get_snapshot
    from src.engine import timing_rules_v2 as v2
    from src.engine.macro_overlay import (
        conflict_explanation,
        overlay_from_snapshot,
        three_way,
    )

    if req.combination not in v2.COMBINATION_METHODS:
        raise HTTPException(
            422, f"알 수 없는 조합 방식: {req.combination}. "
                 f"가능한 값: {', '.join(v2.COMBINATION_METHODS)}")
    if not req.rules:
        raise HTTPException(422, "비교할 타이밍 규칙이 최소 1개 필요합니다.")

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
        k=req.k, weights=req.weights, set_id="three_way")

    try:
        states = v2.rule_set_states(rule_set, as_of=req.as_of, market=req.market)
        legs = three_way(states, method=req.combination, overlay=overlay,
                         k=req.k, weights=list(req.weights) or None)
    except ValueError as e:
        # 엔진의 거부(예: 매크로 없는 regime_conditioned)를 조용히 대치하지 않고 그대로 전달.
        raise HTTPException(422, str(e)) from e

    return {
        "legs": {name: {
            "state": sig.state.value, "exposure": sig.exposure, "method": sig.method,
            "on_count": sig.on_count, "off_count": sig.off_count,
            "unavailable_count": sig.unavailable_count, "explanation": sig.explanation,
        } for name, sig in legs.items()},
        "overlay": overlay.to_dict() if overlay is not None else None,
        "conflict": conflict_explanation(legs["timing_only"], overlay),
        "factor_states": [
            {"factor_id": r.factor_id, "state": s.value}
            for r, s in zip(rule_set.rules, states)
        ],
        "combination": req.combination,
        "as_of": req.as_of,
        "regime_snapshot_id": req.regime_snapshot_id,
    }


class TimingSimulateRequest(BaseModel):
    """과거 시뮬레이션 요청 — 인라인 룰 **또는** 저장된 룰셋 id.

    ★`set_id` 가 외부 파이프라인의 손잡이다★ 저장된 룰셋은 버전이 박혀 있으므로, 파이프라인이
    같은 좌표로 같은 결과를 다시 얻을 수 있다. 인라인 `rules` 는 저장 전 탐색용이다.
    """
    market: str = Field("kr", pattern="^(us|kr)$")
    combination: str = "all"
    k: int = Field(1, ge=1, le=50)
    weights: list[float] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)
    set_id: str | None = Field(None, max_length=40)
    months: int = Field(24, ge=1, le=240)
    #: backtest = 부적격 팩터가 있으면 **걷기 전에 거부**. forward = 걷되 부적격을 밝힌다.
    mode: str = Field("backtest", pattern="^(backtest|forward)$")
    #: 기준 시각(테스트·재현용). 없으면 오늘.
    anchor: str | None = Field(None, max_length=32)


@router.post("/timing/simulate")
def allocation_timing_simulate(req: TimingSimulateRequest):
    """룰셋 과거 시뮬레이션 — 월 간격 시점별 합성 상태·노출 (스펙 §7 "historical simulation").

    ★`mode="backtest"` 는 경고가 아니라 거부다★ 리스크 레지스터가 이 엔드포인트에 배정한
    `forward_only` 차단 지점이며, 거부는 **팩터 이름과 사유**를 담아 422 로 나간다. 조용히
    forward 로 강등하지 않는다 — 그러면 사용자는 백테스트를 받았다고 믿는다.
    """
    from src.engine import timing_rules_v2 as v2
    from src.engine.timing_simulation import simulate_rule_set

    if bool(req.rules) == bool(req.set_id):
        # ★둘 다/둘 다 아님을 같은 말로 거절하지 않는다★ 어느 쪽을 고쳐야 하는지가 다르다.
        raise HTTPException(
            422, "인라인 rules 또는 저장된 set_id 중 **정확히 하나**가 필요합니다"
                 + (" — 둘 다 주어졌습니다." if req.rules else " — 둘 다 비어 있습니다."))
    if req.combination not in v2.COMBINATION_METHODS:
        raise HTTPException(
            422, f"알 수 없는 조합 방식: {req.combination}. "
                 f"가능한 값: {', '.join(v2.COMBINATION_METHODS)}")

    specs, sid, market, combination = req.rules, "ad_hoc", req.market, req.combination
    k, weights, version = req.k, list(req.weights), None
    if req.set_id:
        from src.data.timing_rules import get_rule_set
        stored = get_rule_set(req.set_id)
        if stored is None:
            raise HTTPException(
                422, f"타이밍 룰셋을 찾을 수 없습니다: {req.set_id}. 삭제되었을 수 있습니다.")
        specs = list(stored.get("rules") or [])
        if not specs:
            raise HTTPException(422, f"룰셋 {req.set_id} 에 규칙이 없습니다.")
        sid, market = req.set_id, str(stored.get("market") or req.market)
        version = stored.get("version")
        gate = stored.get("gate") or {}
        # 저장된 조합 방식이 있으면 그것을 쓴다 — 저장된 룰셋을 요청 기본값으로 덮으면
        # "저장된 대로 재현" 이 아니게 된다.
        combination = str(gate.get("combination") or combination)
        k = int(gate.get("k") or k)
        weights = list(gate.get("weights") or weights)
        if combination not in v2.COMBINATION_METHODS:
            raise HTTPException(
                422, f"룰셋 {req.set_id} 의 조합 방식을 알 수 없습니다: {combination}.")

    rule_set = v2.rule_set_from_specs(
        specs, market=market, combination=combination, k=k, weights=weights, set_id=sid)

    try:
        sim = simulate_rule_set(rule_set, months=req.months, mode=req.mode,
                                market=market, anchor=req.anchor)
    except ValueError as e:
        # `ForwardOnlyError` 도 ValueError 다 — 적격성 거부와 엔진 거부를 같은 422 로 옮긴다.
        # 둘 다 "요청이 이대로는 성립하지 않는다" 이고, 사유 문장이 어느 쪽인지 말해 준다.
        raise HTTPException(422, str(e)) from e

    out = sim.to_dict()
    out["months"] = req.months
    out["anchor"] = req.anchor
    # ★재현 좌표는 id 만으로 부족하다★ 룰셋은 갱신될 때 버전이 오르므로, 어떤 버전으로 돌린
    # 시뮬레이션인지 함께 남기지 않으면 나중에 같은 숫자를 다시 만들 수 없다.
    out["rule_set_version"] = version
    return out


@router.post("/timing")
def allocation_timing(req: TimingRequest):
    """카나리(자산·지표) 브레드스 게이트 → 위험-온/오프 자산군 스위치 + 추세 오버레이.
    시장 타이밍 컴포짓(timing_panel)을 함께 반환. VAA/PAA/DAA 규칙을 사용자 파라미터로 일반화."""
    try:
        from src.engine.tactical_allocations import _above_ma_d, _abs_mom, _signal

        mk = req.market if req.market in ("kr", "us") else "kr"
        details, hits = [], 0
        for c in req.canaries:
            ok, val = _canary_eval(c, mk)
            if ok:
                hits += 1
            _, lbl = _timing_holding(c.id, mk) if c.kind == "asset" else (c.id, c.id)
            details.append({"kind": c.kind, "id": c.id, "signal": c.signal,
                            "label": lbl, "value": val, "pass": bool(ok)})
        total = len(req.canaries)
        need = req.min_breadth if req.min_breadth > 0 else total
        risk_on = hits >= need

        # 리스크-온/오프 자산군 구성
        def _on_basket() -> dict[str, float]:
            if req.risk_on_assets:
                w = 100.0 / len(req.risk_on_assets)
                return {t: w for t in req.risk_on_assets}
            if req.holdings:
                tot = sum(max(v, 0.0) for v in req.holdings.values()) or 1.0
                return {t: max(v, 0.0) / tot * 100 for t, v in req.holdings.items()}
            return {}

        def _off_basket() -> dict[str, float]:
            off = req.risk_off_assets or ["IEF", "SHY"]
            w = 100.0 / len(off)
            return {t: w for t in off}

        # 국면-확률 블렌드: 이진 게이트 대신 P(위험선호)로 온/오프 바스켓 연속 혼합(휩쏘 억제)
        regime_block = None
        weights: dict[str, float] = {}      # ticker -> weight%
        if req.regime_blend:
            probs = _timing_regime_probs(mk)
            if probs:
                p_on = float(probs.get("Goldilocks", 0) + probs.get("Reflation", 0))  # 성장+ 국면=위험선호
                p_on = max(0.0, min(1.0, p_on))
                on_b, off_b = _on_basket(), _off_basket()
                for t, w in on_b.items():
                    weights[t] = weights.get(t, 0.0) + w * p_on
                for t, w in off_b.items():
                    weights[t] = weights.get(t, 0.0) + w * (1.0 - p_on)
                weights = {t: round(v, 2) for t, v in weights.items() if v > 0.05}
                regime_block = {"probs": probs, "p_risk_on": round(p_on * 100, 1),
                                "note": "국면확률 가중 연속 노출 — 이진 게이트의 경계 휩쏘를 완화(성장+ 국면=위험선호)."}
        if not weights:  # 블렌드 미사용/실패 → 기존 이진 게이트
            src_b = _on_basket() if risk_on else _off_basket()
            weights = {t: round(v, 2) for t, v in src_b.items()}

        # 목표 변동성(vol targeting): 위험자산 실현 변동성이 목표를 넘으면 노출 축소(잔여=현금)
        vol_block = None
        vt_cash = 0.0
        if req.target_vol_pct is not None and weights:
            realized = _timing_realized_vol_pct(weights, mk)
            if realized is not None and realized > 0:
                scale = min(1.0, float(req.target_vol_pct) / realized)
                before = sum(weights.values())
                weights = {t: round(v * scale, 2) for t, v in weights.items()}
                vt_cash = round(before - sum(weights.values()), 2)
                vol_block = {"target_pct": req.target_vol_pct, "realized_pct": round(realized, 1),
                             "scale": round(scale, 3), "cash_added_pct": vt_cash,
                             "note": "위험자산 실현 변동성 기준 노출 스케일 — CTA/리스크패리티식 연속 리스크 제어."}

        # 추세 오버레이 (마켓타이밍) — 추세 이탈 자산은 현금(단기채)으로
        overlay = req.overlay or {}
        otype = overlay.get("type", "none")
        cash_pct = 0.0
        holdings_out = []
        for t, w in weights.items():
            code, name = _timing_holding(t, mk)
            in_trend = True
            if otype in ("ma_day", "abs_mom") and w > 0:
                if otype == "ma_day":
                    r = _above_ma_d(t, mk, int(overlay.get("n", 200)))
                    in_trend = bool(r) if r is not None else True
                else:
                    r = _abs_mom(t, mk, int(overlay.get("lookback", 12)))
                    in_trend = (r is not None and r > 0)
            wt = w if in_trend else 0.0
            if not in_trend:
                cash_pct += w
            holdings_out.append({"ticker": t, "code": code, "label": name,
                                 "weight": round(wt, 2), "in_trend": in_trend})
        cash_pct = round(cash_pct + vt_cash, 2)   # 추세 이탈 현금 + 목표변동성 현금
        if cash_pct > 0:
            cc, cn = _timing_holding("BIL", mk)
            holdings_out.append({"ticker": "BIL", "code": cc, "label": cn,
                                 "weight": cash_pct, "in_trend": True, "is_cash": True})

        signal_label = _signal({h["ticker"]: h["weight"] for h in holdings_out})

        # 시장 타이밍 컴포짓 (재사용) — 실패해도 카나리 결과는 유효
        market_timing = None
        try:
            from src.engine.macro_analytics import timing_panel
            tp = timing_panel(mk)
            market_timing = {"composite": tp.get("composite"),
                             "components": tp.get("components"),
                             "assets": tp.get("assets")}
        except Exception as e:
            logger.debug(f"timing_panel 실패(무시): {e}")

        return {"error": False, "market": mk,
                "canary": {"signal": "risk_on" if risk_on else "risk_off",
                           "hits": hits, "total": total, "need": need, "details": details},
                "holdings": holdings_out, "cash_pct": cash_pct,
                "signal_label": signal_label, "overlay": otype,
                "regime_blend": regime_block, "vol_target": vol_block,
                "market_timing": market_timing}
    except Exception:
        logger.exception("timing 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── /stress-correlation ──────────────────────────────────────────────────────
