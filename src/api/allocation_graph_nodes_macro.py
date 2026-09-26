"""AAS 그래프 — 거시·타이밍 노드 (BK W3) · ★노출 조절은 기존 함수만 부른다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W3 · §3 ·
Macro→Allocation 승인 범위: `docs/decisions/adr-002-aas-node-canvas.md` §7

- 경기 국면(`regime`): 저장된 스냅샷을 **읽는다**(`regime_snapshots.get_snapshot`/`list_snapshots`).
  새로 만드는 일(DB 쓰기)은 매크로 탭의 몫이다 — 계산은 쓰지 않는다.
- 타이밍 신호(`timing_signal`): `rule_set_from_specs` → `rule_set_states` → `combine` (3자 비교와 같은 파생).
- ★노출 조절(`exposure_overlay`)★: 고른 판단(타이밍 · 타이밍+국면 · 직접)의 노출을 `three_way` 로 얻고
  `target_versions.compile_target` 로 적용한다 — `final = base × exposure`, 줄인 만큼 현금. 이 모듈은
  `MODE_CAP`·`REGIME_TILTS`·임계값을 읽지도 쓰지도 않는다(테스트가 소스로 확인).
  퀀트 고객을 위한 고도화: 세 판단을 나란히 보여 주고 고른 것만 적용 · 적용 강도(줄이는 쪽으로만) ·
  ★모든 신호를 읽지 못했으면 적용하지 않음★ · 실행 목표 상태(실행 가능/연구용)와 사유를 함께 나름.
- 시점별 타이밍 시뮬레이션(`timing_simulation`): `simulate_rule_set` — backtest 모드는 부적격 팩터가 있으면
  **거부**(엔진 규칙 그대로), forward 모드는 걷되 백테스트가 아니라고 말한다.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _josa, _pct, _t
from src.api.allocation_graph_nodes import _ui, weights_value
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg

logger = logging.getLogger(__name__)

P = pg.Port
_FORBID = ConfigDict(extra="forbid")

_STATE_PLAIN = {"risk_on": "위험-온", "risk_off": "위험-오프", "unavailable": "판단 불가"}
_REGIME_PLAIN = {"Goldilocks": "골디락스", "Reflation": "리플레이션", "Stagflation": "스태그플레이션",
                 "Deflation": "디플레이션"}
_MODE_PLAIN = {"NORMAL": "평소대로", "CAUTIOUS": "조심", "DEFENSIVE": "방어"}


# ── 경기 국면 ────────────────────────────────────────────────────────────────

class RegimeParams(BaseModel):
    model_config = _FORBID
    snapshot_id: str | None = Field(None, max_length=40, json_schema_extra={"x-ui": _ui(
        "스냅샷 번호", question="어느 스냅샷을 쓸까요?", presets=[{"label": "가장 최근", "value": None}],
        help="비우면 가장 최근에 저장한 스냅샷을 써요. 특정 번호는 전문가 설정에서 넣어요. 스냅샷은 매크로 탭에서 만들어요.")})


def _regime(inputs: dict, p: RegimeParams) -> pg.NodeOutput:
    from src.data import regime_snapshots as rs
    latest = False
    if p.snapshot_id:
        snap = rs.get_snapshot(p.snapshot_id)
        if snap is None:
            raise pg.NodeFailure(f"경기 국면 스냅샷 {p.snapshot_id} 을(를) 찾지 못했어요 — 번호를 확인하거나 비워 두세요.")
    else:
        rows = rs.list_snapshots(limit=1)
        if not rows:
            raise pg.NodeFailure("저장된 경기 국면 스냅샷이 없어요 — 매크로 탭에서 ‘지금 국면 저장’을 먼저 해 주세요.")
        snap = rs.get_snapshot(rows[0]["snapshot_id"]) or rows[0]
        latest = True
    usage = str(snap.get("research_usage") or "")
    view = {k: snap.get(k) for k in ("snapshot_id", "as_of", "regime", "recommended_mode", "confidence",
                                     "stress_score", "data_status", "research_usage", "explanation",
                                     "phase_probabilities")}
    view["latest"] = latest
    return pg.NodeOutput(values={"regime": dict(snap)}, view=view,
                         tags={"pit": "pit" if usage == "backtest_eligible" else "forward_only",
                               "practice": str(snap.get("data_status")) == "mock",
                               "sources": [f"regime_snapshot:{snap.get('snapshot_id')}"]})


def _explain_regime(view: dict, prov: dict, params: Any) -> dict:
    regime = str(view.get("regime") or "미확인")
    mode = str(view.get("recommended_mode") or "")
    facts = [f"권고는 ‘{_MODE_PLAIN.get(mode.upper(), mode or '미상')}’이에요.",
             f"스트레스 {float(view.get('stress_score') or 0):.0f}/100 · 신뢰도 {float(view.get('confidence') or 0) * 100:.0f}%.",
             f"기준일 {view.get('as_of') or '미상'} 스냅샷({view.get('snapshot_id')})이에요."]
    if view.get("latest"):
        facts.append("번호를 비워서 가장 최근 스냅샷을 썼어요.")
    trust = []
    if view.get("research_usage") != "backtest_eligible":
        trust.append(_t(UNKNOWN, "이 스냅샷은 지금 시점 전용이에요 — 과거 검증에는 쓰지 않아요."))
    if view.get("data_status") in ("partial", "mock", "unavailable"):
        trust.append(_t(UNKNOWN, f"데이터 상태가 ‘{view.get('data_status')}’예요 — 공표 시각을 모두 확정하지 못했어요."))
    plain = _REGIME_PLAIN.get(regime, regime)
    last = plain[-1:]
    # ㄹ 받침은 '로' — 받침 없는 말과 같다.
    ro = "으로" if ("가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 not in (0, 8)) else "로"
    return {"title": f"지금 경기 국면은 ‘{plain}’{ro} 봤어요", "facts": facts, "trust": trust,
            "unmeasured": ["국면 판정이 앞으로 맞을지", "국면이 바뀌는 시점"]}


# ── 타이밍 신호 ──────────────────────────────────────────────────────────────

def _timing_options() -> dict[str, str]:
    from src.engine.timing_factors import CATALOG
    return {c["id"]: c["label"] for c in CATALOG}


class TimingRuleItem(BaseModel):
    model_config = _FORBID
    factor_id: str = Field(..., min_length=1, max_length=60, json_schema_extra={"x-ui": _ui(
        "신호", options=_timing_options())})
    threshold: float | None = Field(None, json_schema_extra={"x-ui": _ui(
        "기준값", "advanced", help="비우면 카탈로그 기본값이에요.")})


_COMBOS = {"all": "모두 켜져야", "any": "하나라도 켜지면", "k_of_n": "k개 이상 켜지면", "weighted": "가중 합",
           "continuous": "켜진 비율만큼", "regime_conditioned": "국면에 따라"}


class TimingParams(BaseModel):
    model_config = _FORBID
    rules: list[TimingRuleItem] = Field(
        default_factory=lambda: [TimingRuleItem(factor_id="abs_mom"), TimingRuleItem(factor_id="ma_month")],
        min_length=1, max_length=12, json_schema_extra={"x-ui": _ui(
            "신호", question="어떤 신호로 판단할까요?", help="신호마다 위험-온/오프/판단 불가 셋 중 하나가 나와요.")})
    combination: Literal[tuple(_COMBOS)] = Field("all", json_schema_extra={"x-ui": _ui(
        "합치는 규칙", question="신호를 어떻게 합칠까요?", widget="cards", options=_COMBOS)})
    k: int = Field(1, ge=1, le=12, json_schema_extra={"x-ui": _ui("k", "advanced", help="‘k개 이상’일 때만 써요.")})
    market: Literal["kr", "us"] = Field("kr", json_schema_extra={"x-ui": _ui(
        "시장", "advanced", options={"kr": "한국", "us": "미국"})})
    as_of: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"x-ui": _ui(
        "기준일", "advanced", help="비우면 오늘이에요.")})


def _timing_signal(inputs: dict, p: TimingParams) -> pg.NodeOutput:
    from src.engine import timing_rules_v2 as v2
    specs = [r.model_dump(exclude_none=True) for r in p.rules]
    rule_set = v2.rule_set_from_specs(specs, market=p.market, combination=p.combination, k=p.k, set_id="graph")
    try:
        states = v2.rule_set_states(rule_set, as_of=p.as_of, market=p.market)
        composite = v2.combine(states, method=p.combination, k=p.k, weights=None)
    except ValueError as e:
        raise pg.NodeFailure(f"타이밍 신호를 계산하지 못했어요 — {e}") from e
    labels = _timing_options()
    view = {"factor_states": [{"factor_id": r.factor_id, "label": labels.get(r.factor_id, r.factor_id),
                               "state": s.value} for r, s in zip(rule_set.rules, states)],
            "composite": {"state": composite.state.value, "exposure": composite.exposure,
                          "on_count": composite.on_count, "off_count": composite.off_count,
                          "unavailable_count": composite.unavailable_count, "explanation": composite.explanation},
            "combination": p.combination, "k": p.k, "market": p.market, "as_of": p.as_of}
    value = {"specs": specs, "rule_set": rule_set, "states": list(states), "combination": p.combination,
             "k": p.k, "market": p.market, "as_of": p.as_of}
    return pg.NodeOutput(values={"signal": value}, view=view,
                         tags={"pit": "unknown" if p.as_of else "forward_only", "practice": mock_allowed(),
                               "sources": ["timing_rules_v2"]})


def _explain_timing(view: dict, prov: dict, params: Any) -> dict:
    c = view.get("composite") or {}
    st = _STATE_PLAIN.get(c.get("state"), c.get("state"))
    facts = [f"{f['label']}: {_STATE_PLAIN.get(f['state'], f['state'])}" for f in view.get("factor_states") or []]
    facts.append(f"합치는 규칙: {_COMBOS.get(view.get('combination'), view.get('combination'))}.")
    trust = [_t(CONFIRMED, "규칙대로 신호를 읽고 합쳤어요.")]
    if c.get("unavailable_count"):
        trust.append(_t(UNKNOWN, f"읽지 못한 신호 {c['unavailable_count']}개는 규칙대로 위험-오프로 셌어요."))
    trust.append(_t(UNKNOWN, "오늘 기준 신호예요 — 과거에도 이 판단이 맞았는지는 ‘시점별 타이밍 시뮬레이션’으로 봐요."
                    if not view.get("as_of") else "기준일 값이지만 그날 실제로 알 수 있었는지는 팩터마다 달라요."))
    if mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 시세가 합성일 수 있어요 — 실제 신호를 말해 주지 않아요."))
    total = len(view.get("factor_states") or [])
    title = (f"신호를 하나도 읽지 못해 규칙상 ‘{st}’로 셌어요"
             if total and c.get("unavailable_count") == total else
             f"타이밍 신호는 ‘{st}’{_josa(st, '이에요', '예요')}")
    return {"title": title,
            "headline": {"label": "권하는 주식 노출", "value": round(float(c.get("exposure") or 0) * 100, 1),
                         "unit": "%", "text": _pct(float(c.get("exposure") or 0) * 100)},
            "facts": facts, "trust": trust, "unmeasured": ["신호가 미래 수익을 맞히는지", "신호가 바뀔 때의 거래 비용"]}


# ── ★노출 조절★ ──────────────────────────────────────────────────────────────

_FOLLOW = {"timing": "타이밍 신호대로", "timing_macro": "타이밍 + 경기 국면", "manual": "직접 정할게요"}


class OverlayParams(BaseModel):
    model_config = _FORBID
    follow: Literal[tuple(_FOLLOW)] = Field("timing", json_schema_extra={"x-ui": _ui(
        "따를 판단", question="어느 판단을 따를까요?", widget="cards", options=_FOLLOW,
        help="세 판단을 결과에 나란히 보여 드려요. 적용은 고른 것 하나만 해요.")})
    manual_exposure_pct: float = Field(100.0, ge=0.0, le=100.0, json_schema_extra={"x-ui": _ui(
        "직접 정한 노출", unit="%", presets=[{"label": "100%", "value": 100.0}, {"label": "80%", "value": 80.0},
                                          {"label": "60%", "value": 60.0}, {"label": "40%", "value": 40.0}],
        help="‘직접 정할게요’를 고른 경우에만 써요.")})
    strength_pct: float = Field(100.0, ge=0.0, le=100.0, json_schema_extra={"x-ui": _ui(
        "적용 강도", "advanced", unit="%",
        help="100%는 규칙 그대로, 50%는 규칙이 줄이라는 만큼의 절반만 줄여요. 노출을 늘리는 쪽으로는 쓰지 않아요.")})


def _overlay(inputs: dict, p: OverlayParams) -> pg.NodeOutput:
    from src.data.target_versions import MODE_LONG_ONLY, MODE_LONG_SHORT, compile_target
    from src.engine.macro_overlay import conflict_explanation, overlay_from_snapshot, three_way
    w, sig, reg = inputs["weights"], inputs.get("signal"), inputs.get("regime")
    names = list(w["names"])
    base = np.asarray(w["weights"], dtype=float)
    base_pct = {n: float(x) * 100.0 for n, x in zip(names, base)}

    legs, conflict, unavailable, n_signals = {}, None, 0, 0
    if p.follow in ("timing", "timing_macro"):
        if sig is None:
            raise pg.NodeFailure("‘따를 판단’이 타이밍이라 ‘타이밍 신호’를 이어 주세요.")
        if p.follow == "timing_macro" and reg is None:
            raise pg.NodeFailure("‘타이밍 + 경기 국면’을 고르셨어요 — ‘경기 국면 불러오기’를 이어 주세요.")
    overlay = overlay_from_snapshot(reg, enabled=True) if reg is not None else None
    if sig is not None:
        states = sig["states"]
        n_signals, unavailable = len(states), sum(1 for s in states if getattr(s, "value", s) == "unavailable")
        raw = three_way(states, method=sig["combination"], overlay=overlay, k=sig["k"], weights=None)
        legs = {k: {"state": v.state.value, "exposure": float(v.exposure), "explanation": v.explanation}
                for k, v in raw.items()}
        conflict = conflict_explanation(raw["timing_only"], overlay)
    if p.follow in ("timing", "timing_macro") and n_signals and unavailable == n_signals:
        raise pg.NodeFailure(f"신호 {n_signals}개를 모두 읽지 못했어요 — 규칙대로면 전부 현금이 되지만, 읽지 못한 데이터로 "
                             "비중을 0으로 만들지 않아요. 데이터가 들어온 뒤 다시 계산해 주세요.")

    if p.follow == "manual":
        leg_exposure, source = p.manual_exposure_pct / 100.0, "직접 정함 — 근거 없음"
    else:
        leg = legs["timing_only" if p.follow == "timing" else "timing_macro"]
        leg_exposure = leg["exposure"]
        source = (f"타이밍 규칙 {n_signals}개({sig['combination']})" if p.follow == "timing"
                  else f"타이밍 + 경기 국면 스냅샷 {reg.get('snapshot_id')}")
    s = p.strength_pct / 100.0
    exposure = float(min(1.0, max(0.0, 1.0 - s * (1.0 - leg_exposure))))      # ★줄이는 쪽으로만★
    if p.strength_pct < 100:
        source += f" · 강도 {p.strength_pct:g}%"
    mode = MODE_LONG_SHORT if (base < 0).any() else MODE_LONG_ONLY
    tv = compile_target(base_pct, {"exposure": exposure, "source": source}, mode=mode,
                        neutralized=bool(w.get("neutralized")),
                        snapshot_id=(reg or {}).get("snapshot_id"))
    after = tv["final_weights"]
    arr = np.array([after[n] / 100.0 for n in names], dtype=float)
    view = {"before": {k: round(v, 4) for k, v in base_pct.items()}, "after": after, "cash_pct": tv["cash_weight"],
            "gross_before": tv["gross_before"], "gross_after": tv["gross_after"], "mode": mode,
            "exposure": exposure, "leg_exposure": leg_exposure, "strength_pct": p.strength_pct,
            "follow": p.follow, "source": source, "legs": legs, "conflict": conflict,
            "unavailable": unavailable, "n_signals": n_signals, "overlay": overlay.to_dict() if overlay else None,
            "status": tv["status"], "status_reason": tv["status_reason"], "labels": _labels(names)}
    return pg.NodeOutput(
        values={"weights": weights_value(names, arr, sigma_annual=w.get("sigma_annual"),
                                         sigma_source=w.get("sigma_source"), target=tv, exposure=exposure,
                                         neutralized=bool(w.get("neutralized")))},
        view=view, tags={"overlay": True, "sources": [f"exposure_overlay:{p.follow}"]})


def _labels(names: list[str]) -> dict[str, str]:
    from src.api.allocation_routes import _labels as lab
    return lab(names)


def _explain_overlay(view: dict, prov: dict, params: Any) -> dict:
    e = float(view.get("exposure") or 0)
    cash = view.get("cash_pct")
    if view.get("mode") == "long_short":
        title = f"총 포지션을 {_pct(float(view['gross_before']))}에서 {_pct(float(view['gross_after']))}로 줄였어요"
    elif e >= 0.9999:
        title = "노출을 줄이지 않았어요 — 그대로 100%예요"
    else:
        title = f"주식 비중을 100%에서 {_pct(e * 100, 0)}로 줄이고 {_pct(float(cash or 0), 0)}는 현금으로 뒀어요"
    legs = view.get("legs") or {}
    facts = [f"따른 판단: {_FOLLOW.get(view.get('follow'), view.get('follow'))}."]
    for k, lab in (("baseline", "기준"), ("timing_only", "타이밍만"), ("timing_macro", "타이밍 + 국면")):
        if k in legs:
            leg = legs[k]
            facts.append(f"{lab}: {_STATE_PLAIN.get(leg['state'], leg['state'])} · 노출 {_pct(float(leg['exposure']) * 100, 0)}")
    if view.get("conflict"):
        facts.append(str(view["conflict"]))
    trust = []
    if view.get("follow") == "manual":
        trust.append(_t(ASSUMED, "직접 정한 노출이에요 — 근거가 된 신호가 없어요."))
    elif float(view.get("strength_pct") or 100) >= 100:
        trust.append(_t(CONFIRMED, "기존 규칙이 낸 노출을 그대로 비중에 곱했어요 — 줄인 만큼은 현금이에요."))
    else:
        trust.append(_t(ASSUMED, f"규칙이 권한 것보다 약하게(강도 {float(view['strength_pct']):g}%) 적용했어요."))
    if view.get("unavailable"):
        trust.append(_t(UNKNOWN, f"읽지 못한 신호 {view['unavailable']}개는 규칙대로 위험-오프로 셌어요."))
    if view.get("follow") == "timing_macro" and not (view.get("overlay") or {}).get("usable", True):
        trust.append(_t(UNKNOWN, "경기 국면을 읽지 못해 국면은 노출을 바꾸지 않았어요."))
    if view.get("status") != "executable":
        trust.append(_t(UNKNOWN, f"이 비중은 실행 목표로는 쓸 수 없어요 — {view.get('status_reason')}"))
    trust.append(_t(UNKNOWN, "오늘의 판단을 얹은 비중이라 정책 백테스트는 막아요."))
    return {"title": title,
            "headline": {"label": "주식 노출", "value": round(e * 100, 1), "unit": "%", "text": _pct(e * 100)},
            "facts": facts, "trust": trust,
            "unmeasured": ["이 조절이 과거에 손실을 줄였는지 — ‘시점별 타이밍 시뮬레이션’으로 따로 봐요",
                           "현금으로 둔 몫의 기회비용"]}


# ── 시점별 타이밍 시뮬레이션 ──────────────────────────────────────────────────

class SimulationParams(BaseModel):
    model_config = _FORBID
    months: int = Field(24, ge=1, le=240, json_schema_extra={"x-ui": _ui(
        "기간", question="몇 달을 돌아볼까요?", unit="개월",
        presets=[{"label": "1년", "value": 12}, {"label": "2년", "value": 24}, {"label": "5년", "value": 60}])})
    mode: Literal["backtest", "forward"] = Field("backtest", json_schema_extra={"x-ui": _ui(
        "방식", widget="cards", options={"backtest": "과거 검증(쓸 수 없는 값이면 멈춤)", "forward": "참고용(쓸 수 없는 값도 표시)"},
        help="과거 검증은 그 시점에 알 수 없던 값을 쓰는 신호가 있으면 계산하지 않아요.")})


def _simulation(inputs: dict, p: SimulationParams) -> pg.NodeOutput:
    from src.engine import timing_simulation as ts
    sig = inputs["signal"]
    try:
        sim = ts.simulate_rule_set(sig["rule_set"], months=p.months, mode=p.mode, market=sig["market"])
    except ValueError as e:
        raise pg.NodeFailure(f"시뮬레이션을 멈췄어요 — {e}") from e
    out = sim.to_dict()
    return pg.NodeOutput(values={}, view={"result": out, "mode": p.mode},
                         tags={"practice": mock_allowed(), "sources": ["timing_simulation"]})


def _explain_simulation(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    pts = r.get("points") or []
    trust = []
    if r.get("backtest_eligible"):
        trust.append(_t(CONFIRMED, "모든 신호가 그 시점에 알 수 있던 값으로 계산됐어요."))
    else:
        trust.append(_t(UNKNOWN, str(r.get("warning") or "과거 검증에 쓸 수 없는 신호가 있어요 — 참고용이에요.")))
    if mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 시세가 합성일 수 있어요."))
    return {"title": f"지난 {len(pts)}개 시점 동안 신호가 {r.get('state_changes', 0)}번 바뀌었어요",
            "facts": [f"방식: {'과거 검증' if view.get('mode') == 'backtest' else '참고용'}."],
            "trust": trust, "unmeasured": ["이 신호대로 했을 때의 수익 — 여기서는 노출만 보여 줘요", "거래 비용"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("regime", "경기 국면", stage="signal", plain_label="경기 국면 불러오기",
                    plain_description="매크로 탭에 저장한 경기 국면 스냅샷을 불러와요.",
                    inputs=(), outputs=(P("regime", "RegimeState"),), run=_regime, params_model=RegimeParams,
                    explain=_explain_regime, category="거시", description="RegimeSnapshot 읽기(쓰기 없음)."),
        pg.NodeSpec("timing_signal", "타이밍 신호", stage="signal", plain_label="타이밍 신호",
                    plain_description="추세·변동성 같은 신호로 지금 위험-온인지 봐요.",
                    inputs=(), outputs=(P("signal", "TimingSignal"),), run=_timing_signal, params_model=TimingParams,
                    explain=_explain_timing, category="타이밍",
                    description="V2 룰셋 → 팩터별 3-상태 → 조합(3자 비교와 같은 파생)."),
        pg.NodeSpec("exposure_overlay", "노출 조절", stage="build", plain_label="노출 조절(비중에 적용)",
                    plain_description="타이밍·경기 국면 판단대로 주식 비중을 줄이고 나머지는 현금으로 둬요.",
                    inputs=(P("weights", "Weights"), P("signal", "TimingSignal", required=False),
                            P("regime", "RegimeState", required=False)),
                    outputs=(P("weights", "Weights"),), run=_overlay, params_model=OverlayParams,
                    explain=_explain_overlay, category="배분",
                    description="three_way 노출 × compile_target(기존 함수만 · 줄이는 쪽으로만)."),
        pg.NodeSpec("timing_simulation", "타이밍 시뮬레이션", stage="check", plain_label="시점별 타이밍 시뮬레이션",
                    plain_description="과거 시점마다 신호가 어땠는지 다시 계산해 봐요.",
                    inputs=(P("signal", "TimingSignal"),), outputs=(), run=_simulation, params_model=SimulationParams,
                    explain=_explain_simulation, category="확인",
                    description="simulate_rule_set — backtest 모드는 부적격 팩터면 거부."),
    ):
        registry.register(spec)
