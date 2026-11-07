"""AAS 그래프 — 기록끼리 견고성 (BS3) · 비중이 아니라 ★이미 있는 기록★끼리 같이 무너지는지(관측만)
==============================================================================
설계 `docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md` §BS3. 테스트 `tests/test_record_robustness.py`.

'견고성 비교'(`sleeve_analytics`)는 **지금 비중을 과거에 들고 있었다면**의 흐름을 잰다. 이 노드는 기록을 잰다:
- 등록한 전략 — `StrategyRegistry.load_returns_matrix`(백테스트를 다시 돌려 곡선이 맞는지 확인한 뒤 남긴 일별 수익)
- 불러온 백테스트 실행(`BacktestRun` — `equity_dates`·`equity_curve`)
- 정책 백테스트 결과(`BacktestResult` — `dates`·`equity_curve`)

★어느 것도 실거래 기록이 아니다★ — 저장소에 전략별 실거래 일별 기록은 없다(믿음 칸이 그렇게 말한다).
포트는 정확히 같은 타입끼리만 이어지므로 실행 넷(r1~r4)·결과 둘(t1~t2)을 따로 받는다. 흐름은 ★날짜 교집합★으로 맞춘다.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _ui
from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label
from src.engine import portfolio_graph as pg

P = pg.Port
RUN_PORTS = ("r1", "r2", "r3", "r4")
RESULT_PORTS = ("t1", "t2")
#: 공통 날짜가 이보다 적으면 재지 않는다 — 상관 창(최대 120)·위기일(10%)을 말할 수 없다.
MIN_OVERLAP = 60
_DATA_KO = {"synthetic": "연습용(합성)", "real": "실데이터", "unknown": "모름"}


class RecordParams(BaseModel):
    model_config = _FORBID
    strategy_ids: list[int] = Field(default_factory=list, max_length=6, json_schema_extra={"x-ui": _ui(
        "등록한 전략", question="등록한 전략 중 무엇을 함께 볼까요?", widget="pick", source="strategies",
        help="백테스트 실행을 전략으로 등록하면 여기에 나와요. 이어 둔 실행·결과와 함께 봐요.")})
    window: Literal[20, 60, 120] = Field(60, json_schema_extra={"x-ui": _ui(
        "상관 창", "advanced", unit="거래일", presets=[{"label": "한 달", "value": 20}, {"label": "석 달", "value": 60},
                                                    {"label": "반년", "value": 120}])})
    shock_rho: Literal[0.7, 0.8, 0.9] = Field(0.8, json_schema_extra={"x-ui": _ui(
        "치솟는 상관", "advanced", presets=[{"label": "0.7", "value": 0.7}, {"label": "0.8", "value": 0.8},
                                         {"label": "0.9", "value": 0.9}])})


def _data_of(mock: bool | None) -> str:
    """★모르면 실데이터라고 하지 않는다★."""
    return "unknown" if mock is None else ("synthetic" if mock else "real")


def _returns(dates: list, values: list) -> dict[str, float]:
    """곡선 → 날짜별 일별 수익(첫날은 수익이 없다). 값이 0 이하·비유한이면 그 구간을 버린다(지어내지 않는다)."""
    out: dict[str, float] = {}
    for i in range(1, min(len(dates), len(values))):
        a, b = values[i - 1], values[i]
        if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or a <= 0:
            continue
        out[str(dates[i])[:10]] = float(b) / float(a) - 1.0
    return out


# ── 등록한 전략 ──────────────────────────────────────────────────────────────

def _registry():
    from src.api import stage11_routes as s11
    from src.database import get_sync_engine
    from src.engine.strategy_registry import StrategyRegistry
    try:
        s11._guard()
    except Exception as e:  # noqa: BLE001 — HTTPException 의 detail 을 그대로
        raise pg.NodeFailure(f"등록한 전략을 읽을 수 없어요 — {getattr(e, 'detail', e)}") from e
    return StrategyRegistry(get_sync_engine())


def _registry_list() -> dict[int, dict]:
    return {int(r["id"]): r for r in _registry().list(active_only=False)}


def _registry_matrix(ids: list[int]):
    return _registry().load_returns_matrix(ids, drop_na_rows=False)


def _registry_rows(ids: list[int]):
    meta = _registry_list()
    if not meta:
        raise pg.NodeFailure("등록한 전략이 없어요 — 백테스트 결과에서 전략으로 등록하세요")
    missing = [i for i in ids if i not in meta]
    if missing:
        raise pg.NodeFailure(f"등록되지 않은 전략 id 예요: {', '.join(map(str, missing))} — 목록에서 다시 골라 주세요")
    return _registry_matrix(ids), meta


# ── 기록 모으기 ──────────────────────────────────────────────────────────────

def _collect(inputs: dict, p: RecordParams) -> list[dict]:
    series: list[dict] = []
    if p.strategy_ids:
        mat, meta = _registry_rows(list(p.strategy_ids))
        for sid in p.strategy_ids:
            col = mat[sid].dropna() if sid in mat.columns else None
            m = meta[sid]
            series.append({
                "label": str(m.get("name") or f"전략 {sid}"), "source": "registered", "ref": sid,
                "data": _data_of(m.get("is_mock_data")), "pit": m.get("is_pit_verified"),
                "note": "등록 전략 — 백테스트 재현 기록이에요(실거래 아님)",
                "returns": {} if col is None else {str(d)[:10]: float(v) for d, v in col.items()}})
    for port in RUN_PORTS:
        v = inputs.get(port)
        if v is None:
            continue
        # 포트 값은 `backtest_load` 의 출력 그대로 — {"run_id", "run": 실행 행}(`_attribution` 과 같은 모양).
        run = v.get("run") or {}
        res = run.get("result") or {}
        bt = res.get("backtest") if isinstance(res.get("backtest"), dict) else res
        series.append({
            "label": str(run.get("strategy_name") or v.get("run_id") or port), "source": "backtest_run",
            "ref": v.get("run_id"), "data": _data_of(run.get("is_mock_data")),
            "pit": run.get("is_pit_verified"), "note": "불러온 백테스트 실행(과거 시뮬레이션)",
            "returns": _returns(bt.get("equity_dates") or [], bt.get("equity_curve") or [])})
    for port in RESULT_PORTS:
        v = inputs.get(port)
        if v is None:
            continue
        bt = v                                             # 포트 값이 곧 `backtest` 노드의 결과 사전이다
        series.append({
            "label": f"정책 백테스트 {port[1]}", "source": "backtest_result", "ref": port,
            "data": "synthetic" if mock_allowed() else "real", "pit": None,
            "note": "정책 백테스트 결과(과거 시뮬레이션 · 리밸런싱 시점마다 다시 푼 비중)",
            "returns": _returns(bt.get("dates") or [], bt.get("equity_curve") or [])})
    # 이름이 겹치면 번호를 붙인다 — 같은 이름 둘은 표에서 가를 수 없다.
    seen: dict[str, int] = {}
    for s in series:
        k = seen.get(s["label"], 0)
        seen[s["label"]] = k + 1
        if k:
            s["label"] = f"{s['label']} ({k + 1})"
    return series


def _record_robustness(inputs: dict, p: RecordParams) -> pg.NodeOutput:
    from src.api import robustness_inputs as ri
    from src.api.allocation_graph_robustness import robustness_view
    series = _collect(inputs, p)
    if len(series) < 2:
        raise pg.NodeFailure("기록이 둘 이상 있어야 같이 무너지는지 볼 수 있어요 — 실행·결과를 잇거나 등록한 전략을 골라 주세요")
    empty = [s["label"] for s in series if len(s["returns"]) < 2]
    if empty:
        raise pg.NodeFailure(f"수익 곡선이 비어 있는 기록이 있어요({', '.join(empty)})")
    common = sorted(set.intersection(*(set(s["returns"]) for s in series)))
    if len(common) < MIN_OVERLAP:
        raise pg.NodeFailure(f"기록끼리 겹치는 날이 {len(common)}일뿐이라 잴 수 없어요(적어도 {MIN_OVERLAP}일) — "
                             "같은 기간의 기록을 골라 주세요")
    names = [s["label"] for s in series]
    S = np.array([[s["returns"][d] for s in series] for d in common], dtype=float)
    mk, why = ri.market_on_dates(ri.KR_PROXY[0], common)
    rob = robustness_view(names, S, None, window=p.window, target_rho=p.shock_rho, dates=common,
                          market_returns=mk, market_reason=why, market_label=ri.KR_PROXY[1])
    if rob.get("available"):
        mixed = {s["data"] for s in series}
        rob["perf_label"] = {**backtest_label(is_mock_data=mixed != {"real"}).to_dict(),
                             "kind_reason": "기록끼리 — 과거 백테스트에서 나온 곡선이에요(실거래 기록이 아니에요)."}
    view = {"series": [{k: s[k] for k in ("label", "source", "ref", "data", "pit", "note")} | {"n_days": len(s["returns"])}
                       for s in series],
            "robustness": rob}
    return pg.NodeOutput(values={}, view=view,
                         tags={"practice": any(s["data"] != "real" for s in series), "sources": ["record_robustness"]})


def _explain(view: dict, prov: dict, params: Any) -> dict:
    rob = view.get("robustness") or {}
    series = view.get("series") or []
    trust = [_t(ASSUMED, "기록은 모두 과거 백테스트에서 나왔어요 — 실거래 기록이 아니에요."),
             _t(ASSUMED, "기록끼리 몫은 똑같이 나눴다고 봤어요(합친 흔들림·충격 계산).")]
    for s in series:
        state = CONFIRMED if s.get("data") == "real" else UNKNOWN if s.get("data") == "unknown" else ASSUMED
        pit = "시점 고정 확인" if s.get("pit") is True else "시점 고정 미확인"
        trust.append(_t(state, f"{s.get('label')}: {s.get('note')} · {_DATA_KO.get(s.get('data'), s.get('data'))} · {pit}"))
    if rob.get("available"):
        p0 = rob.get("period") or {}
        trust.insert(0, _t(CONFIRMED, f"기록 {len(series)}개를 겹치는 날짜({p0.get('start')}~{p0.get('end')} · "
                                      f"{rob.get('n_days')}거래일)로 맞춰 쟀어요."))
        crisis = rob.get("crisis") or {}
        if crisis.get("basis") != "market":
            trust.append(_t(UNKNOWN, str(crisis.get("market_reason") or crisis.get("note") or "시장 자료 없이 위기일을 골랐어요.")))
    else:
        trust.append(_t(UNKNOWN, f"견고성을 재지 못했어요 — {rob.get('reason') or '사유 없음'}"))
    eff = rob.get("effective_n") or {}
    headline = None if eff.get("value") is None else {
        "label": "실질 독립 개수", "value": eff["value"], "unit": "개",
        "text": f"기록 {eff.get('n')}개가 실제로는 약 {eff['value']:.1f}개처럼 움직였어요"}
    return {"title": f"기록 {len(series)}개가 같이 무너지는지 봤어요", "headline": headline,
            "facts": list(rob.get("story") or []), "trust": trust,
            "unmeasured": ["앞으로도 같을지(과거 관계예요)", "돈이 되는지(경제적 가치)", "실거래에서 같을지"]}


def _glance(view: dict) -> dict | None:
    from src.api.allocation_graph_glance import _bars_from
    pairs = ((view.get("robustness") or {}).get("crisis") or {}).get("pairs") or []
    return _bars_from({f"{x['a']}·{x['b']}": x.get("crisis_rho") for x in pairs}, unit=None, caption="위기일 상관(쌍별)")


def register(registry: pg.Registry) -> None:
    registry.register(
        pg.NodeSpec("record_robustness", "기록끼리 견고성", stage="check", plain_label="기록으로 같이 무너지나 보기",
                    plain_description="등록한 전략·백테스트 실행·정책 백테스트 결과끼리 평소·위기 때 얼마나 같이 움직였는지, "
                                      "크게 잃은 구간이 겹쳤는지 날짜를 맞춰 봐요.",
                    inputs=tuple(P(k, "BacktestRun", required=False) for k in RUN_PORTS)
                    + tuple(P(k, "BacktestResult", required=False) for k in RESULT_PORTS),
                    outputs=(), run=_record_robustness, params_model=RecordParams, explain=_explain,
                    glance=_glance, category="확인",
                    description="StrategyRegistry.load_returns_matrix · backtest run/result 곡선 + strategy_robustness(관측만)."))
