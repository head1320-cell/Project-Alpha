"""AAS 그래프 — 백테스트 웨이브 (BL3 W1) · ★시작은 버튼, 읽기는 노드★ (사용자 결정)
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W1. 조건식 백테스트는 실데이터에서 수 분 걸리고, 기존 화면은 백그라운드
워커(`backtest_run_routes.create_run` → `_worker` → `_screen_to_backtest_core`)가 실행 행을 남긴다. 캔버스 규칙
"계산 중 쓰기 0" 을 지키려고 둘로 나눈다:

- **조건식 백테스트 설정** — 계산은 요청 검증 + 요약뿐. 저장 버튼 **'백테스트 시작'** 이 `create_run` 라우트 함수를 한 번
  부른다(같은 워커 · 같은 기록 · 새 큐 없음).
- **백테스트 결과 불러오기** — `run_full` 라우트 함수 그대로 읽는다(성과 라벨 · 실행 가정 포함). 끝나지 않았으면 진행률로,
  실패했으면 그 사유로 실패한다 — 하류는 막힌다.
- **매크로 팩터 귀인** — 라우트와 같은 본문 `factor_attribution_for_run`. 계열은 BL2b `macro_series_map()`(운영 = 저장된
  관측만 · 수집기 0).
- **두 실행 비교** — 이미 계산된 지표를 나란히 둔다(차이는 뺄셈뿐 · 새 지표를 만들지 않는다). 조건이 다르면 먼저 말한다.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from src.api import screener_routes as _sr
from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _pct, _signed_pct, _t
from src.api.allocation_graph_nodes import _FORBID, _pydantic_reason, _ui
from src.api.allocation_graph_nodes_signal import _presets_filter
from src.engine import portfolio_graph as pg

logger = logging.getLogger(__name__)

P = pg.Port

_UNIVERSES = {"kospi50": "KOSPI 50", "kospi200": "KOSPI 200", "kosdaq150": "KOSDAQ 150"}


def _strategy_options() -> dict[str, str]:
    """전략 레지스트리의 영문 키 → 쉬운 이름(같은 클래스의 한글 이름). 조건식 전략(Condition)은 이 노드가 아직 조건 편집기를
    싣지 않아 선택지에 두지 않는다."""
    from src.kis_strategies.strategies import STRATEGY_REGISTRY
    out: dict[str, str] = {}
    for k, cls in STRATEGY_REGISTRY.items():
        if k.isascii():
            out[k] = cls().name
    return out


_STRATEGIES = _strategy_options()
_DATE = r"^\d{4}-\d{2}-\d{2}$"


class SetupParams(BaseModel):
    model_config = _FORBID
    universe: Literal[tuple(_UNIVERSES)] = Field("kospi200", json_schema_extra={"x-ui": _ui(
        "후보 범위", question="어디서 종목을 고를까요?", widget="cards", options=_UNIVERSES)})
    filter_ast: _sr.FilterGroupModel = Field(
        default_factory=lambda: _sr.FilterGroupModel(logic="AND", conditions=[], groups=[]),
        json_schema_extra={"x-ui": _ui("조건", question="어떤 조건으로 거를까요?", widget="filter",
                                       presets=_presets_filter(),
                                       help="조건은 서버가 필드 목록으로 검사해요 — 모르는 필드는 시작하지 않아요.")})
    strategy_name: Literal[tuple(_STRATEGIES)] = Field("GoldenCross", json_schema_extra={"x-ui": _ui(
        "사고파는 규칙", question="어떤 규칙으로 사고팔까요?", widget="cards", options=_STRATEGIES)})
    start_date: str = Field("2023-01-01", pattern=_DATE, json_schema_extra={"x-ui": _ui(
        "시작", question="언제부터 돌려 볼까요?", presets=[{"label": "2021년부터", "value": "2021-01-01"},
                                                     {"label": "2023년부터", "value": "2023-01-01"}])})
    end_date: str = Field("2024-12-31", pattern=_DATE, json_schema_extra={"x-ui": _ui("끝", "advanced")})
    max_tickers: int = Field(10, ge=1, le=30, json_schema_extra={"x-ui": _ui(
        "종목 수", "advanced", unit="개", help="조건을 통과한 상위 몇 종목으로 돌릴지예요.")})
    max_positions: int = Field(5, ge=1, le=30, json_schema_extra={"x-ui": _ui("동시 보유", "advanced", unit="개")})
    initial_capital: float = Field(100_000_000, gt=0, json_schema_extra={"x-ui": _ui("시작 금액", "advanced", unit="원")})
    commission_rate: float = Field(0.0015, ge=0, le=0.05, json_schema_extra={"x-ui": _ui("수수료율", "advanced")})
    slippage_rate: float = Field(0.0005, ge=0, le=0.05, json_schema_extra={"x-ui": _ui("슬리피지율", "advanced")})
    charge_sell_tax: bool = Field(False, json_schema_extra={"x-ui": _ui(
        "매도세 부과", "advanced", help="켜면 실행 준비실과 같은 증권거래세율을 매겨요(기본 꺼짐).")})
    stop_loss_pct: float | None = Field(None, gt=0, le=90, json_schema_extra={"x-ui": _ui("손절 %", "advanced")})
    take_profit_pct: float | None = Field(None, gt=0, le=500, json_schema_extra={"x-ui": _ui("익절 %", "advanced")})


def _config(p: SetupParams) -> dict:
    """노드 파라미터 → `ScreenToBacktestRequest` 페이로드. ★판정은 라우트 모델이 한다★ — 여기서 규칙을 새로 정하지 않는다."""
    cfg = p.model_dump(mode="json", exclude_none=True)
    try:
        req = _sr.ScreenToBacktestRequest(**cfg)
    except ValidationError as e:
        raise pg.NodeFailure(f"백테스트 요청 규칙에 맞지 않아요 — {_pydantic_reason(e)}") from e
    from src.engine.filter_ast import parse_group
    try:
        err = parse_group(req.filter_ast.model_dump()).validate()
    except Exception as e:  # noqa: BLE001 — 구문이 틀린 조건식은 사유와 함께 실패
        err = str(e)
    if err:
        raise pg.NodeFailure(f"조건을 확인해 주세요 — {err}")
    if req.end_date <= req.start_date:
        raise pg.NodeFailure("끝나는 날이 시작하는 날보다 뒤여야 해요.")
    return req.model_dump(mode="json")


def _setup(inputs: dict, p: SetupParams) -> pg.NodeOutput:
    cfg = _config(p)
    view = {"config": cfg, "strategy_label": _STRATEGIES.get(p.strategy_name, p.strategy_name),
            "universe_label": _UNIVERSES.get(p.universe, p.universe),
            "n_conditions": len(p.filter_ast.conditions) + len(p.filter_ast.groups)}
    return pg.NodeOutput(values={}, view=view)


def _start_backtest(values: dict, view: dict, params: SetupParams) -> dict:
    """'백테스트 시작' — `create_run` 라우트 함수 그대로(같은 워커 · 같은 실행 기록). 설정은 미리보기의 것 그대로 싣는다."""
    from src.api.backtest_run_routes import CreateRunRequest, create_run
    try:
        out = create_run(CreateRunRequest(config=view["config"],
                                          strategy_name=f"캔버스 · {view.get('strategy_label')}"[:120]))
    except HTTPException as e:
        raise pg.NodeFailure(str(e.detail)) from e
    rid = out.get("run_id")
    if not rid:
        raise pg.NodeFailure("DB 를 쓸 수 없어 백테스트를 시작하지 못했어요.")
    return {"saved_id": rid,
            "text": f"백테스트를 시작했어요 · {rid} — 끝나면 ‘백테스트 결과 불러오기’로 봐요"}


def _explain_setup(view: dict, prov: dict, params: Any) -> dict:
    c = view.get("config") or {}
    return {"title": f"{view.get('universe_label')}에서 ‘{view.get('strategy_label')}’로 돌려 볼 준비가 됐어요",
            "facts": [f"기간 {c.get('start_date')} ~ {c.get('end_date')} · 상위 {c.get('max_tickers')}종목 · 조건 {view.get('n_conditions')}개",
                      f"비용: 수수료 {float(c.get('commission_rate', 0)) * 100:.2f}% · 슬리피지 {float(c.get('slippage_rate', 0)) * 100:.2f}%"
                      + (" · 매도세" if c.get("charge_sell_tax") else " · 매도세 안 매김")],
            "trust": [_t(CONFIRMED, "서버의 백테스트 요청 규칙과 조건 필드 목록으로 확인했어요."),
                      _t(ASSUMED, "수 분 걸릴 수 있어요 — 계산하지 않고, ‘백테스트 시작’을 누르면 백그라운드에서 돌아요.")],
            "unmeasured": ["아직 돌리지 않았어요 — 결과는 ‘백테스트 결과 불러오기’에서 봐요"]}


# ── 결과 불러오기 ────────────────────────────────────────────────────────────

class LoadParams(BaseModel):
    model_config = _FORBID
    run_id: str | None = Field(None, max_length=80, json_schema_extra={"x-ui": _ui(
        "백테스트", question="어느 백테스트를 볼까요?", widget="pick", source="backtest_runs",
        help="‘조건식 백테스트 설정’에서 시작한 실행이 여기에 나와요.")})


_STAGE_KO = {"draft": "준비", "queued": "대기", "validating": "확인", "loading_data": "데이터 불러오기",
             "simulating": "시뮬레이션", "calculating_metrics": "지표 계산", "persisting_results": "저장"}
_END_KO = {"failed": "실패했어요", "cancelled": "취소됐어요", "expired": "시간이 지나 멈췄어요"}


def _load(inputs: dict, p: LoadParams) -> pg.NodeOutput:
    from src.api.backtest_run_routes import run_full
    if not p.run_id:
        raise pg.NodeFailure("불러올 백테스트를 골라 주세요 — ‘조건식 백테스트 설정’에서 시작하면 여기에 생겨요.")
    try:
        r = run_full(p.run_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise pg.NodeFailure(f"백테스트 {p.run_id} 을(를) 찾지 못했어요 — 지워졌을 수 있어요.") from e
        raise pg.NodeFailure(f"실행 저장소를 읽을 수 없어요 — {e.detail} (실행이 없는 것과 달라요)") from e
    st = r.get("status")
    if st in _END_KO:
        raise pg.NodeFailure(f"이 백테스트는 {_END_KO[st]}(실패 사유: {r.get('error_message') or '미상'}).")
    if st != "completed":
        pct = int(r.get("progress_percent") or 0)
        raise pg.NodeFailure(f"아직 끝나지 않았어요 — {pct}% · {_STAGE_KO.get(st, st)}. 끝나면 다시 계산해 주세요.")
    result = r.get("result") or {}
    bt = result.get("backtest") if isinstance(result.get("backtest"), dict) else result
    view = {"run_id": p.run_id, "strategy_name": r.get("strategy_name"), "statistics": bt.get("statistics") or {},
            "equity": {"dates": bt.get("equity_dates") or [], "values": bt.get("equity_curve") or []},
            "benchmark": bt.get("benchmark"), "screened_count": result.get("screened_count"),
            "input": r.get("input_snapshot") or {}, "execution_assumption": r.get("execution_assumption"),
            "is_mock_data": r.get("is_mock_data"), "is_pit_verified": r.get("is_pit_verified")}
    practice = r.get("is_mock_data") is not False                  # 미상은 연습용 쪽으로(넘치게 말한다)
    return pg.NodeOutput(values={"run": {"run_id": p.run_id, "run": r}}, view=view,
                         provenance={"perf_label": r.get("perf_label")},
                         tags={"pit": "pit" if r.get("is_pit_verified") is True else "unknown", "practice": practice,
                               "sources": [f"backtest_run:{p.run_id}"]})


_STAT_KO = (("total_return_pct", "총수익", "%"), ("cagr", "연평균(CAGR)", "%"), ("sharpe_ratio", "샤프", ""),
            ("max_drawdown_pct", "최대 낙폭", "%"), ("win_rate", "승률", "%"), ("num_trades", "거래 수", "회"),
            ("profit_factor", "손익비", ""))


def _explain_load(view: dict, prov: dict, params: Any) -> dict:
    s = view.get("statistics") or {}
    tr = s.get("total_return_pct")
    trust = [_t(CONFIRMED, "백그라운드에서 끝난 실행의 저장된 결과를 그대로 읽었어요.")]
    if view.get("is_mock_data") is not False:
        trust.append(_t(UNKNOWN, "연습용(합성) 데이터로 돈 실행이거나 데이터 출처를 확인하지 못했어요 — 실제 성과가 아니에요."))
    if view.get("is_pit_verified") is not True:
        trust.append(_t(UNKNOWN, "시점 정합을 확인하지 못했어요 — 그때 알 수 없던 값이 섞였을 수 있어요."))
    return {"title": f"백테스트 {view.get('run_id')}의 결과를 불러왔어요",
            "headline": ({"label": "총수익", "value": tr, "unit": "%", "text": _signed_pct(float(tr))} if tr is not None else None),
            "facts": [f"{lab} {s.get(k)}{u}" for k, lab, u in _STAT_KO[1:4] if s.get(k) is not None],
            "trust": trust, "unmeasured": ["표본 밖 성과", "실제 체결(모의·실계좌)"]}


# ── 매크로 팩터 귀인 ─────────────────────────────────────────────────────────

#: 팩터 id → 쉬운 이름(화면용 · 라우트 응답은 건드리지 않는다). 모르는 id 는 id 그대로 보인다.
FACTOR_KO = {"duration": "금리(듀레이션)", "inflation": "물가", "credit": "신용", "growth": "성장", "usd": "달러",
             "commodity": "원자재", "equity": "주식", "volatility": "변동성", "liquidity": "유동성"}

def _attribution(inputs: dict, p: Any) -> pg.NodeOutput:
    from src.api.allocation_graph_nodes_bl2 import macro_series_map
    from src.api.backtest_run_routes import _ProxyResolutionError, factor_attribution_for_run
    run = inputs["run"]
    series, tags = macro_series_map()
    try:
        out = factor_attribution_for_run(run["run"], run["run_id"], series_map=series)
    except _ProxyResolutionError as e:
        raise pg.NodeFailure(f"팩터 계열을 고르지 못했어요 — {e}") from e
    if not out.get("available"):
        raise pg.NodeFailure(f"귀인을 계산하지 못했어요 — {out.get('reason') or '사유 미상'}")
    labels = {r["factor"]: FACTOR_KO.get(r["factor"], r["factor"]) for r in out.get("rows") or []}
    return pg.NodeOutput(values={}, view={"result": out, "labels": labels}, tags=tags)


def _explain_attribution(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    rows = r.get("rows") or []
    top = max(rows, key=lambda x: abs(float(x.get("contribution_pct") or 0))) if rows else None
    trust = [_t(CONFIRMED, f"실행의 월별 수익률 {r.get('months_from_run')}개월을 매크로 팩터로 나눴어요(결합 회귀).")]
    if any(x.get("collinear") for x in rows):
        trust.append(_t(UNKNOWN, "서로 비슷하게 움직이는 팩터가 있어 개별 기여는 서로 상쇄될 수 있어요 — 따로 읽지 마세요."))
    trust += ([_t(UNKNOWN, "개발 모드라 매크로 지표가 합성(연습용)이에요.")] if prov.get("practice") else [])
    return {"title": "무엇이 이 수익을 만들었는지 나눠 봤어요",
            "facts": ([f"가장 큰 몫: {FACTOR_KO.get(top.get('factor'), top.get('factor'))} {_signed_pct(float(top.get('contribution_pct') or 0))}"] if top else [])
                     + ([f"설명력(R²) {r['diagnostics']['r_squared']:.2f}"] if (r.get("diagnostics") or {}).get("r_squared") is not None else []),
            "trust": trust, "unmeasured": ["인과(회귀는 같이 움직였다는 것만 말해요)"]}


# ── 두 실행 비교 ─────────────────────────────────────────────────────────────

_COND_KO = {"start_date": "시작", "end_date": "끝", "commission_rate": "수수료율", "slippage_rate": "슬리피지율",
            "charge_sell_tax": "매도세", "charge_spread": "스프레드", "charge_market_impact": "시장충격",
            "universe": "후보 범위", "strategy_name": "규칙"}


def _stats(run: dict) -> dict:
    res = (run.get("run") or {}).get("result") or {}
    bt = res.get("backtest") if isinstance(res.get("backtest"), dict) else res
    return bt.get("statistics") or {}


def _compare(inputs: dict, p: Any) -> pg.NodeOutput:
    a, b = inputs["a"], inputs["b"]
    sa, sb = _stats(a), _stats(b)
    rows = []
    for k, label, unit in _STAT_KO:
        x, y = sa.get(k), sb.get(k)
        diff = round(float(y) - float(x), 4) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None
        rows.append({"key": k, "label": label, "unit": unit, "a": x, "b": y, "diff": diff})
    ia = (a.get("run") or {}).get("input_snapshot") or {}
    ib = (b.get("run") or {}).get("input_snapshot") or {}
    differences = [{"key": k, "label": lab, "a": ia.get(k), "b": ib.get(k)}
                   for k, lab in _COND_KO.items() if ia.get(k) != ib.get(k)]
    ma, mb = (a.get("run") or {}).get("is_mock_data"), (b.get("run") or {}).get("is_mock_data")
    if ma != mb:
        differences.append({"key": "is_mock_data", "label": "데이터(연습용/실제)", "a": ma, "b": mb})
    view = {"a": a["run_id"], "b": b["run_id"], "rows": rows, "differences": differences}
    return pg.NodeOutput(values={}, view=view)


def _explain_compare(view: dict, prov: dict, params: Any) -> dict:
    diffs = view.get("differences") or []
    tr = next((r for r in view.get("rows") or [] if r["key"] == "total_return_pct"), {})
    trust = [_t(CONFIRMED, "두 실행이 이미 계산한 지표를 나란히 놨어요 — 새로 계산한 수는 차이(뺄셈)뿐이에요.")]
    if diffs:
        trust.insert(0, _t(UNKNOWN, "같은 조건이 아니에요 — " + ", ".join(d["label"] for d in diffs)
                           + "이(가) 달라 차이가 규칙 때문인지 조건 때문인지 가를 수 없어요."))
    title = ("같은 조건이 아니에요 — 차이를 규칙 탓으로 읽지 마세요" if diffs
             else f"두 백테스트를 나란히 놨어요 (총수익 차이 {_pct(float(tr['diff']))})" if tr.get("diff") is not None
             else "두 백테스트를 나란히 놨어요")
    return {"title": title, "trust": trust,
            "unmeasured": ["차이가 우연인지(통계적 유의성)", "표본 밖에서도 같은 차이가 나는지"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    for spec in (
        pg.NodeSpec("backtest_setup", "조건식 백테스트 설정", stage="check", plain_label="조건으로 골라 사고팔아 보기",
                    plain_description="조건으로 고른 종목을 정한 규칙대로 과거에 사고팔아 봐요. 시작은 버튼으로 해요.",
                    inputs=(), outputs=(), run=_setup, params_model=SetupParams, explain=_explain_setup,
                    category="백테스트", save=_start_backtest, save_label="백테스트 시작",
                    description="ScreenToBacktestRequest 검증만(쓰기 0) · 시작 = create_run 라우트 함수(같은 워커)."),
        pg.NodeSpec("backtest_load", "백테스트 결과 불러오기", stage="check", plain_label="백테스트 결과 보기",
                    plain_description="백그라운드에서 끝난 백테스트의 결과를 불러와요.",
                    inputs=(), outputs=(P("run", "BacktestRun"),), run=_load, params_model=LoadParams,
                    explain=_explain_load, category="백테스트",
                    description="run_full 라우트 함수(성과 라벨·실행 가정) · 진행 중·실패·없음·저장소 장애는 각각 실패."),
        pg.NodeSpec("backtest_attribution", "매크로 팩터 귀인", stage="check", plain_label="수익을 나눠 보기",
                    plain_description="백테스트 수익이 어떤 매크로 흐름에서 왔는지 나눠 봐요.",
                    inputs=(P("run", "BacktestRun"),), outputs=(), run=_attribution,
                    explain=_explain_attribution, category="백테스트",
                    description="factor_attribution_for_run(라우트와 같은 본문) · 운영은 저장된 관측만."),
        pg.NodeSpec("backtest_compare", "두 실행 비교", stage="check", plain_label="두 백테스트 나란히",
                    plain_description="두 백테스트의 지표를 나란히 놓고, 조건이 다르면 먼저 알려 줘요.",
                    inputs=(P("a", "BacktestRun"), P("b", "BacktestRun")), outputs=(), run=_compare,
                    explain=_explain_compare, category="백테스트",
                    description="이미 계산된 statistics 나란히 · 차이는 뺄셈뿐 · 조건 차이 경고."),
    ):
        registry.register(spec)
