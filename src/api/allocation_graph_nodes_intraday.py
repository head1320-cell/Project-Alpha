"""AAS 그래프 — 분봉 백테스트 노드 둘 · ★실행은 단추, 읽기는 노드★ (기존 조건식 백테스트와 같은 꼴)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md` · ADR 006 §7(새 기능은 기존 모듈 안에)

- **분봉 백테스트 설정**(`intraday_setup`) — 계산은 ★쓰기 0 · 봉을 읽지 않는다★: 판정 문과 같은 읽기 전 검사(`prepare`)와
  분봉 파일이 있는 날 세기뿐이다. 단추 **'분봉 백테스트 실행'** 이 판정 문의 본체(`run_validation`)를 한 번 불러 계산 · 판정 ·
  시행 기록을 하고, 그 결과 요약을 시행 줄에 남긴다. 캔버스에서 설정을 바꿔 가며 본 것이 시행 횟수에서 새지 않는다.
- **분봉 결과 불러오기**(`intraday_load`) — 남긴 요약을 ★읽기만★ 한다(다시 계산하지 않는다). 본인 것만 · 남의 것과 없는 것은
  같은 문장 · 운영 게이트에서는 합성 등급의 결과를 내주지 않는다.

둘 다 실행자를 받는다(`wants_actor`) — 시행 기록은 사용자별이다. 둘 다 출력 포트가 없다 — 분봉 결과를 비교·순위에 잇는 길이
구조에 없다. ★도구는 규칙과 종목을 추천하지 않는다★: 종목 칸은 비어서 시작하고, AI 추천·말로 설계의 후보 표에도 없다(`NOT_OFFERED`).

매개변수 모델은 등록부에서 만든다(`rules.describe()` · `POSITION_FIELDS` · `COST_FIELDS`) — 칸의 사본을 여기 두지 않는다.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, create_model

from src.api import graph_actor
from src.api import intraday_routes as routes
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _practice, _t
from src.api.allocation_graph_nodes import _FORBID, _pydantic_reason, _ui
from src.data import intraday_trials as trials
from src.data.mock_gate import mock_allowed
from src.engine import portfolio_graph as pg
from src.engine.intraday import rules

P = pg.Port

SETUP, LOAD = "intraday_setup", "intraday_load"
#: AI 추천 · 말로 설계가 후보로 삼지 않는 종류 — 도구는 규칙과 종목을 추천하지 않는다(`canvas_assist_routes.offered_kinds`).
NOT_OFFERED = (SETUP, LOAD)
_WHO = "분봉 백테스트는 로그인한 사용자만 사용합니다"
_DATE = r"^\d{4}-\d{2}-\d{2}$"
_KEY = r"^[0-9a-f]{64}$"
_REAL, _SYNTHETIC = routes.GRADE_REAL, routes.GRADE_SYNTHETIC

REASONS = {
    "no_period": "기간을 지정하십시오 — 시작일과 종료일이 필요합니다.",
    "no_pick": "조회할 분봉 백테스트를 선택하십시오 — ‘분봉 백테스트’ 노드에서 ‘분봉 백테스트 실행’을 누르면 여기에 표시됩니다.",
    "not_found": "이 분봉 백테스트 결과를 찾지 못했습니다 — 본인이 실행한 결과만 조회할 수 있습니다.",
    "store_unreadable": routes.RESULTS_UNREADABLE,
    "synthetic_in_production": "모의 모드에서 합성 분봉으로 만든 결과입니다 — 운영에서는 조회하지 않습니다.",
    "trial_not_recorded": "시행을 기록하지 못해 결과를 남기지 않았습니다 — 시행 횟수를 셀 수 없는 실행은 캔버스에 남기지 않습니다.",
    "result_not_kept": "시행은 기록했지만 결과 요약을 남기지 못했습니다 — 결과 저장소에 쓰지 못했습니다.",
}


# ── 매개변수 모델 — 등록부에서 만든다 ────────────────────────────────────────────────────────
def _annotation(d: dict) -> Any:
    kind = d["type"]
    if kind == "choice":
        return Literal[tuple(c["value"] for c in d["choices"])]
    return {"int": int, "float": float}.get(kind, str)


def _field(d: dict, tier: str, **hints: Any) -> tuple[Any, Any]:
    """등록부의 칸 정의 하나 → 모델의 칸. 기본값 · 범위 · 단위는 등록부 그대로다(여기서 정하지 않는다)."""
    bounds = {k: d[src] for k, src in (("ge", "min"), ("le", "max")) if d.get(src) is not None and d["type"] in ("int", "float")}
    if d["type"] == "choice":
        hints = {"widget": "cards", "options": {c["value"]: c["label"] for c in d["choices"]}, **hints}
    else:                                                        # 수 · 시각 — 선택지가 없어 직접 적는다(등록부의 범위·단위 그대로)
        hints = {"widget": "input", **hints}
    ui = _ui(d["label"], tier, **({"unit": d["unit"]} if d.get("unit") else {}), **hints)
    kind = _annotation(d)
    optional = d.get("default") is None
    return (kind | None if optional else kind), Field(d.get("default"), json_schema_extra={"x-ui": ui}, **bounds)


_TEMPLATES = {t["kind"]: t for t in rules.describe()}
_BASIC_POSITION = ("amount", "stop_pct", "target_pct")
_BASIC_COSTS = ("commission_bp", "slippage_ticks")
_HELP = {
    "commission_bp": "비우면 비용 후 값은 미상입니다(0 과 다릅니다).",
    "unknown_market": "종목 목록에 시장 구분이 없는 종목에만 적용하는 가정입니다. 비우면 그 종목의 매도세는 미상입니다.",
    "time_exit": "네 자리 숫자로 적습니다(예: 1500).",
}


def _setup_model() -> type[BaseModel]:
    fields: dict[str, Any] = {
        "tickers": (list[str], Field(default_factory=list, json_schema_extra={"x-ui": _ui(
            "종목", question="대상 종목", widget="tickers",
            help="종목 묶음을 연결하면 그 종목을 사용합니다. 도구는 종목을 추천하지 않습니다.")})),
        "start_date": (str | None, Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
            "시작일", question="백테스트 시작일", widget="input", input="date",
            help="분봉이 적재된 날은 ‘데이터 상태’ 화면에서 확인합니다.")})),
        "end_date": (str | None, Field(None, pattern=_DATE, json_schema_extra={"x-ui": _ui(
            "종료일", question="백테스트 종료일", widget="input", input="date")})),
        "rule": (Literal[tuple(_TEMPLATES)], Field(next(iter(_TEMPLATES)), json_schema_extra={"x-ui": _ui(
            "규칙 틀", question="매매 규칙", widget="cards", options={k: t["label"] for k, t in _TEMPLATES.items()},
            order=list(_TEMPLATES),                              # 화면(백테스트 › 분봉 규칙)과 같은 순서 — 등록부의 순서다
            help="틀은 출발점입니다 — 좋은 규칙이라는 뜻이 아닙니다.")})),
    }
    for kind, template in _TEMPLATES.items():
        for d in template["params"]:
            fields[f"{kind}__{d['key']}"] = _field(d, "basic", show_if={"rule": [kind]})
    for d in routes.POSITION_FIELDS:
        fields[d["key"]] = _field(d, "basic" if d["key"] in _BASIC_POSITION else "advanced",
                                  **({"help": _HELP[d["key"]]} if d["key"] in _HELP else {}))
    for d in routes.COST_FIELDS:
        fields[d["key"]] = _field(d, "basic" if d["key"] in _BASIC_COSTS else "advanced",
                                  **({"help": _HELP[d["key"]]} if d["key"] in _HELP else {}))
    return create_model("IntradaySetupParams", __config__=_FORBID, **fields)


SetupParams = _setup_model()


class LoadParams(BaseModel):
    model_config = _FORBID
    trial_key: str | None = Field(None, pattern=_KEY, json_schema_extra={"x-ui": _ui(
        "분봉 백테스트", question="대상 분봉 백테스트", widget="pick", source="intraday_results",
        help="‘분봉 백테스트’ 노드에서 실행한 결과가 여기에 표시됩니다(본인 것만).")})


# ── 설정 ──────────────────────────────────────────────────────────────────────────────
def _refusal(err: HTTPException) -> str:
    """판정 문의 거절 → 노드의 실패 사유. ★문의 문장 그대로★ — 여기서 규칙을 새로 정하지 않는다."""
    d = err.detail if isinstance(err.detail, dict) else {"reason": str(err.detail)}
    text = str(d.get("reason"))
    if d.get("detail"):
        text += f" ({d['detail']})"
    now = next((d[k] for k in ("work", "ticker_days", "tickers", "days", "bytes", "cells") if isinstance(d.get(k), int)), None)
    if isinstance(d.get("limit"), int) and now is not None:
        text += f" 상한 {d['limit']:,} · 지금 {now:,}."
    return text


def _body(inputs: dict, p: Any) -> tuple[routes.ValidateBody, str, int]:
    """노드의 매개변수 → 판정 문의 요청 본문 · 종목이 어디서 왔는지 · 쓰지 않은 직접 입력 종목 수."""
    if not p.start_date or not p.end_date:
        raise pg.NodeFailure(REASONS["no_period"])
    linked = inputs.get("universe")
    typed = [str(t) for t in p.tickers]
    tickers = [str(t) for t in (linked.get("tickers") or [])] if linked is not None else typed
    params = {d["key"]: getattr(p, f"{p.rule}__{d['key']}") for d in _TEMPLATES[p.rule]["params"]}
    try:
        body = routes.ValidateBody(**{
            "tickers": tickers, "from": p.start_date, "to": p.end_date, "rule": {"kind": p.rule, "params": params},
            "position": {d["key"]: getattr(p, d["key"]) for d in routes.POSITION_FIELDS},
            "costs": {d["key"]: getattr(p, d["key"]) for d in routes.COST_FIELDS}})
    except ValidationError as e:
        raise pg.NodeFailure(f"분봉 백테스트 요청 규칙에 맞지 않습니다 — {_pydantic_reason(e)}") from e
    return body, ("universe" if linked is not None else "typed"), (len(typed) if linked is not None else 0)


def _setup(inputs: dict, p: Any, actor: Any) -> pg.NodeOutput:
    graph_actor.require(actor, _WHO)
    body, source, ignored = _body(inputs, p)
    try:
        ready = routes.prepare(body)                             # 문과 같은 읽기 전 검사 — 봉을 읽지 않는다
    except HTTPException as e:
        raise pg.NodeFailure(_refusal(e)) from e
    view = {"request": routes.request_view(body, ready.tickers, ready.params),
            "rule_label": _TEMPLATES[p.rule]["label"], "tickers_from": source, "typed_ignored": ignored,
            "days": {"calendar": (body.to - body.from_).days + 1, "loaded": len(ready.plan.dates)},
            "work": {"ticker_days": ready.ticker_days, "simulations": ready.simulations,
                     "total": ready.ticker_days * ready.simulations, "limit": routes.MAX_VALIDATE_WORK},
            "mock": mock_allowed()}
    return pg.NodeOutput(values={}, view=view)


def _execute(values: dict, view: dict, params: Any, actor: Any) -> dict:
    """'분봉 백테스트 실행' — 판정 문의 본체를 ★한 번★. 설정은 미리보기의 것 그대로다. 시행을 세지 못한 실행은 남기지 않는다."""
    user = graph_actor.require(actor, _WHO)
    try:
        response, made = routes.run_validation(routes.ValidateBody(**view["request"]), user)
    except HTTPException as e:
        raise pg.NodeFailure(_refusal(e)) from e
    if response["empty"]:
        raise pg.NodeFailure(response["empty"]["message"])
    if made is None:
        raise pg.NodeFailure(REASONS["trial_not_recorded"])
    summary = {**response, "data": {k: v for k, v in response["data"].items() if k != "skipped"}}
    if trials.keep_result(user, made["trial_key"], summary) is not True:
        raise pg.NodeFailure(REASONS["result_not_kept"])
    return {"saved_id": made["trial_key"],
            "text": "분봉 백테스트를 실행하고 시행으로 기록했습니다 — ‘분봉 결과 조회’에서 확인합니다"}


def _explain_setup(view: dict, prov: dict, params: Any) -> dict:
    r, days, work = view.get("request") or {}, view.get("days") or {}, view.get("work") or {}
    costs = r.get("costs") or {}
    fee = costs.get("commission_bp")
    facts = [f"기간 {r.get('from')} ~ {r.get('to')} · 종목 {len(r.get('tickers') or [])}개 · 달력 {days.get('calendar')}일 가운데 분봉이 적재된 날 {days.get('loaded')}일",
             f"비용 가정: 수수료율 {'미상(비용 후 값은 산출하지 않습니다)' if fee is None else f'{fee}bp'} · 슬리피지 {costs.get('slippage_ticks')}틱",
             f"계산량 {work.get('total'):,} (상한 {work.get('limit'):,})"]
    if view.get("typed_ignored"):
        facts.append(f"종목 묶음을 연결해 직접 넣은 종목 {view['typed_ignored']}개는 사용하지 않았습니다.")
    trust = [_t(CONFIRMED, "판정 문과 같은 규칙으로 요청과 계산량을 검사했습니다."),
             _t(ASSUMED, "종목은 지금 정한 묶음입니다 — 과거 구간에서는 사후 선택입니다."),
             _t(ASSUMED, "실행은 계산하지 않고 ‘분봉 백테스트 실행’을 눌러야 시작하며, 실행마다 시행으로 기록됩니다.")]
    if view.get("mock"):
        trust.append(_t(ASSUMED, "모의 모드입니다 — 적재된 분봉이 합성일 수 있으며 출처는 실행할 때 정해집니다."))
    return {"title": f"‘{view.get('rule_label')}’ 분봉 백테스트 실행 준비를 마쳤습니다", "facts": facts, "trust": trust,
            "unmeasured": ["아직 실행하지 않았습니다 — 결과는 ‘분봉 결과 조회’에서 확인합니다", "출처 등급(실제 · 합성)은 실행할 때 정해집니다"]}


# ── 결과 불러오기 ─────────────────────────────────────────────────────────────────────────
def _grade(result: dict) -> str | None:
    return (result.get("origin") or {}).get("grade")


def _load(inputs: dict, p: LoadParams, actor: Any) -> pg.NodeOutput:
    user = graph_actor.require(actor, _WHO)
    if not p.trial_key:
        raise pg.NodeFailure(REASONS["no_pick"])
    found = trials.result_of(user, p.trial_key)
    if found is None:
        raise pg.NodeFailure(REASONS["store_unreadable"])
    if not found["found"]:                                       # 남의 것과 없는 것은 같은 문장이다
        raise pg.NodeFailure(REASONS["not_found"])
    result = found["result"]
    grade = _grade(result)
    if grade == _SYNTHETIC and not mock_allowed():               # 운영에서는 합성 위의 숫자를 내주지 않는다
        raise pg.NodeFailure(REASONS["synthetic_in_production"])
    view = {**result, "trial_key": p.trial_key, "result_at": found["result_at"], "runs": found["runs"]}
    return pg.NodeOutput(values={}, view=view,
                         tags={"pit": "unknown", "practice": grade != _REAL, "sources": [f"intraday_trial:{p.trial_key[:12]}"]})


def _won(v: float) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(round(v)):,}원"


def _explain_load(view: dict, prov: dict, params: Any) -> dict:
    s, counts = view.get("summary") or {}, (view.get("gates") or {}).get("counts") or {}
    net, gross, grade = s.get("net_total"), s.get("gross_total"), _grade(view)
    when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(view.get("result_at") or 0))) + " UTC"
    facts = [f"거래 {s.get('trades')}건 · 비용 전 실현손익 {_won(float(gross))}" if gross is not None else f"거래 {s.get('trades')}건",
             f"이 실행의 관문 일곱: 통과 {counts.get('ok', 0)} · 미달 {counts.get('degraded', 0)} · 미상 {counts.get('unknown', 0)}",
             f"실행 {when} · 같은 설정 실행 {view.get('runs')}회 — 시행 횟수는 그때의 값입니다"]
    if net is None:
        facts.insert(0, "비용 후 실현손익은 미상입니다 — 수수료율을 지정하지 않았거나 매도세를 산출하지 못했습니다.")
    trust = [_t(CONFIRMED, "실행할 때 남긴 요약을 그대로 읽었습니다 — 다시 계산하지 않았습니다.")]
    if grade == _SYNTHETIC:
        trust.append(_practice("합성 분봉 위의 숫자입니다 — 계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다."))
    elif grade != _REAL:
        trust.append(_t(UNKNOWN, "분봉의 출처 등급은 미상입니다."))
    trust += [_t(UNKNOWN, "시점 정합은 미상입니다 — 봉 시각의 뜻(그 1분의 시작인지 끝인지)을 확인하지 못했습니다."),
              _t(ASSUMED, "종목은 사용자가 정한 묶음입니다 — 과거 구간에서는 사후 선택입니다.")]
    return {"title": "분봉 백테스트 결과를 조회했습니다",
            # 머리 수는 원 단위 정수로(카드는 수를 그대로 그린다) — 요약의 값 자체는 보기(view)에 소수까지 그대로 있다.
            "headline": ({"label": "비용 후 실현손익", "value": round(float(net)), "unit": "원", "text": _won(float(net))}
                         if net is not None else None),
            "facts": facts, "trust": trust,
            "unmeasured": ["실제 계좌에서의 경제적 가치", "모의·실계좌 체결", "호가·체결 대기열·시장 충격"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────────────
def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec(SETUP, "분봉 백테스트 설정", stage="check", plain_label="분봉 백테스트",
                    plain_description="정한 종목에 장중 규칙 하나를 과거 분봉으로 실행합니다. 실행은 버튼으로 시작하며 실행마다 시행으로 기록됩니다.",
                    inputs=(P("universe", "Universe", required=False),), outputs=(), run=_setup, params_model=SetupParams,
                    explain=_explain_setup, category="백테스트", save=_execute, save_label="분봉 백테스트 실행",
                    wants_actor=True,
                    description="판정 문의 읽기 전 검사(prepare)만 · 쓰기 0 · 봉을 읽지 않음 · 실행 = run_validation(같은 본체 · 시행 기록)."),
        pg.NodeSpec(LOAD, "분봉 결과 불러오기", stage="check", plain_label="분봉 결과 조회",
                    plain_description="실행한 분봉 백테스트의 판정 요약을 조회합니다. 본인이 실행한 결과만 조회합니다.",
                    inputs=(), outputs=(), run=_load, params_model=LoadParams, explain=_explain_load, category="백테스트",
                    wants_actor=True,
                    description="시행 줄의 결과 요약(읽기만) · 본인 것만 · 운영 게이트에서는 합성 등급을 내주지 않음."),
    ):
        registry.register(spec)


__all__ = ["LOAD", "NOT_OFFERED", "REASONS", "SETUP", "register"]
