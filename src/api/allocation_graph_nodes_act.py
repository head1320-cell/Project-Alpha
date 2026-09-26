"""AAS 그래프 — 실행·기록 노드 (BK W4) · ★계산은 쓰지 않고, 저장은 버튼 · 주문은 없다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W4

- 주문 목록 미리보기(`order_preview`): `execution_routes._compute` — `/execution-plan` 미리보기와 같은
  오더 diff·비용·사전 점검. **저장·승인·체결 입력 없음.** 주문 경로(`OrderExecutor`·`TradingEngine`)는
  import 조차 하지 않는다(BK0 AST 트립와이어).
- 실행 목표 만들기(`target_version`): `compile_target` 으로 목표를 **미리보기**하고, 저장은 '저장하기'
  버튼(`/graph/save` → `save_target` 한 번). ★연습용(합성) 데이터로 만든 비중은 실행 목표로 두지 않는다★ —
  입력 계보를 읽어(`wants_lineage`) 상태를 연구용으로 내린다. 저장은 되지만 실행 경로가 거절한다.
- 결정 기록(`decision_journal`): 저널 항목을 미리보기하고, 저장은 버튼(`create_entry` 한 번).
- 쓰는 함수는 `_save_*` 안에서만 부른다 — 계산 경로에서는 부르지 않는다(AST 트립와이어).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _pct, _t
from src.api.allocation_graph_nodes import _subset, _ui
from src.api.execution_routes import ExecPlanRequest
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg

logger = logging.getLogger(__name__)

P = pg.Port
_FORBID = ConfigDict(extra="forbid")
_PRACTICE_TARGET = "연습용(합성) 데이터로 만든 비중이에요 — 실행 목표로 쓰지 않아요."


def _pct_of(w: dict) -> dict[str, float]:
    return {n: float(x) * 100.0 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}


# ── 주문 목록 미리보기 ────────────────────────────────────────────────────────

OrderParams = _subset(
    "OrderPreviewParams", ExecPlanRequest, ("current_weights", "portfolio_value", "restricted"),
    ui={
        "current_weights": _ui("지금 비중", question="지금 무엇을 들고 있나요?",
                               presets=[{"label": "없어요(새로 사기)", "value": {}}],
                               help="종목 코드별 비중(%)은 전문가 설정에서 넣어요."),
        "portfolio_value": _ui("평가 금액", question="얼마로 계산할까요?", unit="원",
                               presets=[{"label": "1천만 원", "value": 1e7}, {"label": "1억 원", "value": 1e8},
                                        {"label": "10억 원", "value": 1e9}]),
        "restricted": _ui("거래 금지 종목", "advanced", help="이 종목은 주문을 만들지 않아요."),
    },
    turnover_cap_pct=(float | None, Field(None, ge=0, le=200, json_schema_extra={"x-ui": _ui(
        "회전율 한도", "advanced", unit="%", help="넘으면 사전 점검이 경고해요.")})),
)


def _order_preview(inputs: dict, p) -> pg.NodeOutput:
    from src.api.execution_routes import _compute
    target = _pct_of(inputs["weights"])
    limits = {"turnover_cap_pct": p.turnover_cap_pct} if p.turnover_cap_pct is not None else {}
    req = ExecPlanRequest(current_weights=dict(p.current_weights), target_weights=target, weight_unit="percent",
                          portfolio_value=p.portfolio_value, restricted=list(p.restricted), limits=limits)
    try:
        plan, pretrade = _compute(req, target)
    except HTTPException as e:
        raise pg.NodeFailure(f"주문 목록을 만들지 못했어요 — {e.detail}") from e
    view = {"plan": plan, "pretrade": pretrade, "portfolio_value": p.portfolio_value}
    return pg.NodeOutput(values={"trades": view}, view=view,
                         tags={"practice": mock_allowed(), "sources": ["execution_plan"]})


def _explain_orders(view: dict, prov: dict, params: Any) -> dict:
    plan, pre = view.get("plan") or {}, view.get("pretrade") or {}
    s = plan.get("summary") or {}
    orders = plan.get("orders") or []
    checks = pre.get("checks") or []
    blocks = [c for c in checks if c.get("status") == "block"]
    warns = [c for c in checks if c.get("status") == "warning"]
    facts = [f"사는 주문 {sum(1 for o in orders if o.get('side') == 'buy')}건 · 파는 주문 "
             f"{sum(1 for o in orders if o.get('side') == 'sell')}건이에요."]
    if s.get("est_cost") is not None:
        facts.append(f"예상 비용은 {float(s['est_cost']):,.0f}원이에요.")
    trust = [_t(CONFIRMED, "주문은 만들지 않았어요 — 목록만 미리 봤어요.")]
    trust += [_t("failed", f"{c['name']}: {c['detail']}") for c in blocks]
    trust += [_t(ASSUMED, f"{c['name']}: {c['detail']}") for c in warns]
    if mock_allowed():
        trust.append(_t(UNKNOWN, "개발 모드라 종가·거래대금이 합성일 수 있어요 — 실제 체결 금액을 말해 주지 않아요."))
    return {"title": f"주문 {len(orders)}건을 미리 만들어 봤어요" if orders else "바꿀 주문이 없어요",
            "headline": {"label": "사전 점검", "value": None, "unit": "",
                         "text": "승인 가능" if pre.get("can_approve") else "승인 불가"},
            "facts": facts, "trust": trust,
            "unmeasured": ["실제 체결 가격(슬리피지)", "주문을 나눠 낼 때의 시장 충격"]}


# ── 실행 목표 만들기 ──────────────────────────────────────────────────────────

class TargetParams(BaseModel):
    model_config = _FORBID
    note: str = Field("", max_length=500, json_schema_extra={"x-ui": _ui(
        "메모", question="이 목표에 남길 말이 있나요?", widget="text", help="저장할 때 함께 남아요.")})


def _target_version(inputs: dict, p: TargetParams, lineage: dict) -> pg.NodeOutput:
    from src.data.target_versions import MODE_LONG_ONLY, MODE_LONG_SHORT, STATUS_RESEARCH_ONLY, compile_target
    w = inputs["weights"]
    base = _pct_of(w)
    if w.get("target"):
        tv = dict(w["target"])                              # 노출 조절이 이미 컴파일한 목표 — 다시 만들지 않는다
    else:
        mode = MODE_LONG_SHORT if any(v < 0 for v in base.values()) else MODE_LONG_ONLY
        tv = compile_target(base, None, mode=mode, neutralized=bool(w.get("neutralized")))
    graph_blocks = []
    if lineage.get("practice"):
        graph_blocks.append(_PRACTICE_TARGET)
    if graph_blocks:
        reasons = [r for r in [tv.get("status_reason")] if r] + graph_blocks
        tv = {**tv, "status": STATUS_RESEARCH_ONLY, "status_reason": " / ".join(reasons)}
    view = {"target": tv, "graph_blocks": graph_blocks, "labels": _labels(list(tv["final_weights"]))}
    return pg.NodeOutput(values={"target": {"tv": tv}}, view=view)


def _save_target_version(values: dict, view: dict, params: TargetParams) -> dict:
    from src.data.target_versions import save_target
    tv = values["target"]["tv"]
    tpv_id = save_target(tv, note=params.note or "노드 캔버스에서 저장")
    if tpv_id is None:
        raise pg.NodeFailure("DB 를 쓸 수 없어 저장하지 못했어요.")
    kind = "실행할 수 있는" if tv["status"] == "executable" else "연구용"
    return {"saved_id": tpv_id, "text": f"{kind} 실행 목표로 저장했어요 · {tpv_id}"}


def _labels(names: list[str]) -> dict[str, str]:
    from src.api.allocation_routes import _labels as lab
    return lab(names)


def _explain_target(view: dict, prov: dict, params: Any) -> dict:
    tv = view.get("target") or {}
    ok = tv.get("status") == "executable"
    cash = tv.get("cash_weight")
    facts = [f"종목 {len(tv.get('final_weights') or {})}개" + (f" · 현금 {_pct(float(cash))}" if cash else "") + "예요."]
    if (tv.get("overlay") or {}).get("source"):
        facts.append(f"노출 조절 근거: {tv['overlay']['source']}.")
    trust = [_t(CONFIRMED, "목표 규칙(롱온리·출처·거래 가능성)을 검사했어요.")]
    if not ok:
        trust.append(_t("failed", str(tv.get("status_reason") or "실행할 수 없는 목표예요.")))
    trust.append(_t(UNKNOWN, "저장하기 전에는 기록되지 않아요 — 저장해도 주문은 나가지 않아요."))
    return {"title": "실행할 수 있는 목표를 만들었어요" if ok else "연구용 목표를 만들었어요",
            "headline": {"label": "상태", "value": None, "unit": "", "text": "실행 가능" if ok else "연구용"},
            "facts": facts, "trust": trust, "unmeasured": ["이 목표로 실제 체결했을 때의 결과"]}


# ── 결정 기록 ────────────────────────────────────────────────────────────────

_DECISION = {"adopt": "채택", "hold": "보류", "reject": "기각"}


class JournalParams(BaseModel):
    model_config = _FORBID
    title: str = Field("캔버스에서 내린 결정", min_length=1, max_length=200, json_schema_extra={"x-ui": _ui(
        "제목", question="어떤 결정인가요?", widget="text")})
    decision: Literal["adopt", "hold", "reject"] = Field("hold", json_schema_extra={"x-ui": _ui(
        "결정", question="이 목표를 어떻게 할까요?", widget="cards", options=_DECISION)})
    thesis: str = Field("", max_length=2000, json_schema_extra={"x-ui": _ui(
        "이유", question="왜 그렇게 정했나요?", widget="text")})
    counter: str = Field("", max_length=2000, json_schema_extra={"x-ui": _ui(
        "반대 근거", "advanced", widget="text", help="틀릴 수 있는 이유를 남겨 두면 나중에 되짚기 쉬워요.")})


def _journal(inputs: dict, p: JournalParams) -> pg.NodeOutput:
    tv = inputs["target"]["tv"]
    trades = inputs.get("trades")
    stress = inputs.get("stress")
    links = {"target": {"status": tv["status"], "status_reason": tv.get("status_reason"),
                        "final_weights": tv["final_weights"], "cash_weight": tv.get("cash_weight"),
                        "overlay": tv.get("overlay")},
             "source": "node_canvas"}
    if trades:
        links["orders"] = {"summary": (trades.get("plan") or {}).get("summary"),
                           "can_approve": (trades.get("pretrade") or {}).get("can_approve")}
    if stress:
        r = stress.get("result") or {}
        links["stress"] = {"label": r.get("label"), "mode": r.get("mode"),
                           "shock_pct": r.get("portfolio_shock_pct", r.get("max_dd_pct"))}
    record = {"decision": _DECISION[p.decision], "thesis": p.thesis, "counter_arguments": p.counter}
    view = {"title": p.title, "links": links, "record": record}
    return pg.NodeOutput(values={}, view=view)


def _save_journal(values: dict, view: dict, params: JournalParams) -> dict:
    from src.data.journal_store import create_entry
    eid = create_entry(view["title"], links=view["links"], record=view["record"])
    if eid is None:
        raise pg.NodeFailure("DB 를 쓸 수 없어 저장하지 못했어요.")
    return {"saved_id": eid, "text": f"결정을 기록했어요 · {eid}"}


def _explain_journal(view: dict, prov: dict, params: Any) -> dict:
    rec, links = view.get("record") or {}, view.get("links") or {}
    facts = [f"결정: {rec.get('decision')}.", f"목표 상태: {'실행 가능' if links.get('target', {}).get('status') == 'executable' else '연구용'}."]
    if "orders" in links:
        facts.append("주문 미리보기 요약을 함께 남겨요.")
    if "stress" in links:
        facts.append(f"충격 점검 ‘{links['stress'].get('label')}’을 함께 남겨요.")
    trust = [_t(UNKNOWN, "저장하기 전에는 기록되지 않아요.")]
    if not (rec.get("thesis") or "").strip():
        trust.append(_t(ASSUMED, "이유를 적지 않았어요 — 나중에 이 결정을 되짚기 어려워요."))
    return {"title": f"‘{view.get('title')}’ 기록을 준비했어요", "facts": facts, "trust": trust,
            "unmeasured": ["이 결정의 결과 — 기록한 뒤 성과 귀인으로 되짚어요"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("order_preview", "주문 목록", stage="act", plain_label="주문 목록 미리보기",
                    plain_description="지금 비중에서 목표로 가려면 무엇을 사고팔지 미리 봐요. 주문은 나가지 않아요.",
                    inputs=(P("weights", "Weights"),), outputs=(P("trades", "Trades"),),
                    run=_order_preview, params_model=OrderParams, explain=_explain_orders, category="실행",
                    description="/execution-plan 미리보기와 같은 오더 diff·비용·사전 점검(저장·승인 없음)."),
        pg.NodeSpec("target_version", "실행 목표", stage="act", plain_label="실행 목표 만들기",
                    plain_description="비중을 실행 목표로 만들어요. 저장은 버튼으로 한 번만 해요.",
                    inputs=(P("weights", "Weights"),), outputs=(P("target", "TargetVersion"),),
                    run=_target_version, params_model=TargetParams, explain=_explain_target, category="실행",
                    wants_lineage=True, save=_save_target_version,
                    description="compile_target 미리보기 · 저장은 /graph/save → save_target."),
        pg.NodeSpec("decision_journal", "결정 기록", stage="act", plain_label="결정 기록 남기기",
                    plain_description="무엇을 왜 정했는지 저널에 남겨요. 저장은 버튼으로 해요.",
                    inputs=(P("target", "TargetVersion"), P("trades", "Trades", required=False),
                            P("stress", "StressReport", required=False)),
                    outputs=(), run=_journal, params_model=JournalParams, explain=_explain_journal, category="기록",
                    save=_save_journal, description="저널 항목 미리보기 · 저장은 create_entry 한 번."),
    ):
        registry.register(spec)
