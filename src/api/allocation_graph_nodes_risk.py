"""AAS 그래프 — 리스크 노드 (BL3 W4) · ★외부를 부르지 않고 같은 모델 클래스를 부른다★
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W4. 테스트 `tests/test_allocation_graph_bl3w4.py`.

화면 라우트(`risk_routes` — `/calculate-var` 등)는 종목마다 `MarketDataLoader`(yfinance)를 부른다. 노드는 그 경로를 쓰지 않는다:
**Returns 포트(DB 적재분·개발 mock — 계보가 이미 붙어 있다) + Weights 포트**를 받아 라우트와 **같은 모델 클래스**를 직접 부른다.
모델은 로그수익률을 기대하므로(라우트의 `fetch_returns` 가 로그) 단순수익률을 `log1p` 로 정확히 바꾼다.

포트폴리오 계열 = 비중을 Returns 열에 맞춰 **gross(Σ|w|) 정규화**(라우트와 같은 규칙 — 달러중립에서 0 나누기를 막는다) 후 Σwᵢrᵢ.
`series` 에 종목 코드를 적으면 그 종목 하나만 본다(비중 불필요).

★침묵 폴백을 여기서 먼저 막는다★(모델 코드는 바꾸지 않는다): 롤링 샤프는 창보다 짧으면 `current: 0` 을 내므로 실패시킨다 ·
FRTB 스트레스 창을 못 찾으면 모델이 현재 ES 를 스트레스 ES 자리에 넣으므로 '못 찾음' 을 드러낸다 · EWMA 반감기 같은 무한대는
엄격한 JSON 이 아니므로 `None`(정의되지 않음)으로 바꾼다.
"""
from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.api.allocation_graph_explain import ASSUMED, CONFIRMED, UNKNOWN, _t
from src.api.allocation_graph_nodes import _FORBID, _labels, _ui
from src.engine import portfolio_graph as pg
from src.models.frtb_es import LIQUIDITY_HORIZON_MAP

P = pg.Port
PORTFOLIO = "portfolio"
RETURN_BASIS = "log1p(단순수익률) — 모델이 기대하는 로그수익률로 정확히 바꿨어요"
_DCC_MAX_ASSETS = 6
_MIN_OBS = 60


def _finite(x: Any) -> Any:
    """무한대·NaN → None(정의되지 않음). numpy 수는 파이썬 수로 — 뷰는 엄격한 JSON 이어야 한다."""
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_finite(v) for v in x.tolist()]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else None
    return x


# ── 계열 만들기 ──────────────────────────────────────────────────────────────

def _to_log(simple: pd.Series | pd.DataFrame, what: str):
    if (np.asarray(simple, dtype=float) <= -1).any():
        raise pg.NodeFailure(f"{what}에 하루 -100% 이하 수익률이 있어 로그수익률로 바꿀 수 없어요 — 수익률 데이터를 확인해 주세요.")
    return np.log1p(simple)


def _aligned_weights(R: pd.DataFrame, w: dict) -> tuple[np.ndarray, float]:
    names = list(w["names"])
    missing = [n for n in names if n not in R.columns]
    if missing:
        raise pg.NodeFailure(f"비중의 종목 {', '.join(missing)} 이(가) 수익률에 없어요 — 같은 수익률에서 나온 비중을 이어 주세요.")
    wd = dict(zip(names, np.asarray(w["weights"], dtype=float)))
    arr = np.array([float(wd.get(c, 0.0)) for c in R.columns])
    gross = float(np.abs(arr).sum())
    if gross <= 0:
        raise pg.NodeFailure("비중이 모두 0 이에요 — 위험을 잴 포지션이 없어요.")
    return arr / gross, gross


def _series(inputs: dict, series: str) -> dict:
    """포트폴리오 또는 한 종목의 로그수익률 계열 + 그 계열을 만든 방식(입력 표에 싣는다)."""
    rv = inputs["returns"]
    R: pd.DataFrame = rv["returns"]
    notes: list[dict] = []
    if series == PORTFOLIO:
        w = inputs.get("weights")
        if w is None:
            raise pg.NodeFailure("포트폴리오의 위험을 재려면 비중을 이어 주세요 — 한 종목만 보려면 '무엇을 볼까' 에 종목 코드를 적어요.")
        arr, gross = _aligned_weights(R, w)
        if abs(gross - 1.0) > 1e-9:
            notes.append({"key": "gross", "label": "비중 합(절댓값)", "value": round(gross, 4), "basis": "가정",
                          "source": f"합 {gross:.3f} 을 1 로 맞췄어요 — 현금·빈 비중은 위험에서 빠져요(라우트와 같은 규칙)"})
        simple = R @ arr
        lr = _to_log(simple, "포트폴리오 수익률")
        weights = {c: round(float(x), 6) for c, x in zip(R.columns, arr)}
    else:
        if series not in R.columns:
            raise pg.NodeFailure(f"'{series}' 은(는) 수익률에 없어요 — 있는 것: {', '.join(map(str, R.columns))} 또는 'portfolio'.")
        lr = _to_log(R[series], f"{series} 수익률")
        arr, weights = None, None
    cov = rv.get("coverage") or {}
    meta = {"series": series, "label": "포트폴리오" if series == PORTFOLIO else (_labels([series]).get(series) or series),
            "obs": int(len(lr)), "start": str(lr.index[0])[:10] if len(lr) else None,
            "end": str(lr.index[-1])[:10] if len(lr) else None, "return_basis": RETURN_BASIS,
            "source": cov.get("source"), "weights": weights}
    return {"lr": lr, "R": R, "w": arr, "meta": meta, "notes": notes}


def _obs_input(s: dict) -> dict:
    m = s["meta"]
    return {"key": "sample", "label": "과거 표본", "value": f"{m['start']} ~ {m['end']} ({m['obs']}일)", "basis": "관측",
            "source": f"수익률 노드 — 출처 {m['source'] or '미상'}"}


def _value_input(v: float) -> dict:
    return {"key": "portfolio_value", "label": "평가 금액", "value": v, "unit": "원", "basis": "가정",
            "source": "직접 정한 금액 — 계좌 잔고가 아니에요"}


def _out(s: dict, result: dict, inputs: list[dict]) -> pg.NodeOutput:
    view = {"meta": s["meta"], "result": _finite({**result, "inputs": [_obs_input(s), *inputs, *s["notes"]]})}
    return pg.NodeOutput(values={}, view=view, provenance={"return_basis": "log1p", "source": s["meta"]["source"]})


def _need(s: dict, n: int, what: str) -> None:
    if s["meta"]["obs"] < n:
        raise pg.NodeFailure(f"{what}은(는) 최소 {n} 관측이 필요해요 — 지금 {s['meta']['obs']}일이에요. 수익률 기간을 늘려 주세요.")


def _eok(x: Any) -> str:
    if not isinstance(x, (int, float)):
        return "—"
    return f"{x / 1e8:,.2f}억 원" if abs(x) >= 1e8 else f"{x / 1e4:,.0f}만 원"


def _base_trust(view: dict) -> list[dict]:
    m = view.get("meta") or {}
    return [_t(CONFIRMED, f"과거 {m.get('obs')}일({m.get('start')} ~ {m.get('end')})의 수익률로 쟀어요 — 앞으로의 손실을 약속하지 않아요."),
            _t(ASSUMED, "라우트 화면(/risk-tools)은 yfinance 로그수익률을 쓰고, 이 노드는 수익률 노드의 계열을 log1p 로 바꿔 써요 "
                        "— 기간·출처가 달라 값이 다를 수 있어요.")]


# ── 공통 파라미터 ────────────────────────────────────────────────────────────

_SERIES_UI = _ui("무엇을 볼까", question="어느 계열의 위험을 잴까요?",
                 presets=[{"label": "포트폴리오", "value": PORTFOLIO}],
                 help="'portfolio' 면 이어진 비중으로 묶은 포트폴리오, 종목 코드를 적으면 그 종목 하나만 봐요.")


class _SeriesParams(BaseModel):
    model_config = _FORBID
    series: str = Field(PORTFOLIO, min_length=1, max_length=20, json_schema_extra={"x-ui": _SERIES_UI})


class _Valued(_SeriesParams):
    portfolio_value: float = Field(1e8, gt=0, le=1e13, json_schema_extra={"x-ui": _ui(
        "평가 금액", question="얼마를 들고 있다고 볼까요?", unit="원",
        presets=[{"label": "1천만", "value": 1e7}, {"label": "1억", "value": 1e8}, {"label": "10억", "value": 1e9}],
        help="손실을 금액으로 보여 주려는 값이에요 — 계좌 잔고를 읽지 않아요.")})


_CL_UI = _ui("신뢰수준", question="얼마나 드문 손실까지 볼까요?",
             presets=[{"label": "95%", "value": 0.95}, {"label": "99%", "value": 0.99}],
             help="99% 면 '100일 중 하루 정도' 겪을 만한 손실이에요.")


# ── VaR·ES ───────────────────────────────────────────────────────────────────

class VarEsParams(_Valued):
    confidence_level: float = Field(0.99, ge=0.9, le=0.999, json_schema_extra={"x-ui": _CL_UI})


def _var_es(inputs: dict, p: VarEsParams) -> pg.NodeOutput:
    from src.models.parametric import ParametricRiskModel
    from src.models.portfolio_risk import PortfolioRiskModel
    s = _series(inputs, p.series)
    _need(s, 30, "VaR")
    r, v, cl = s["lr"], p.portfolio_value, p.confidence_level
    res: dict = {"confidence_level": cl}
    for key, ewma in (("normal", False), ("ewma", True)):
        m = ParametricRiskModel(cl, ewma)
        vp, ep = float(m.calculate_var(r)), float(m.calculate_es(r))
        res[key] = {"var_pct": vp, "es_pct": ep, "var_amount": vp * v, "es_amount": ep * v}
    hv = float(ParametricRiskModel(cl).historical_var(r))
    res["historical"] = {"var_pct": hv, "var_amount": hv * v, "n_obs": int(len(r)),
                         "n_beyond": int((r < -hv).sum())}
    if s["w"] is not None:
        comp = PortfolioRiskModel(cl, False).component_var(_to_log(s["R"], "수익률"), s["w"], v)
        res["components"] = [{"name": c, "label": _labels([c]).get(c) or c, "amount": float(x)}
                             for c, x in zip(s["R"].columns, comp)]
        res["components_reason"] = None
    else:
        res["components"], res["components_reason"] = None, "한 종목만 볼 때는 나눌 구성이 없어요."
    return _out(s, res, [_value_input(v),
                         {"key": "cl", "label": "신뢰수준", "value": cl, "basis": "가정", "source": "직접 정한 값"},
                         {"key": "dist", "label": "정규분포", "value": "정규·EWMA 두 방법", "basis": "가정",
                          "source": "꼬리가 두꺼운 실제 수익률에선 손실을 작게 볼 수 있어요 — 역사적 방법과 나란히 보세요"},
                         {"key": "lambda", "label": "EWMA 감쇠 λ", "value": "0.94", "basis": "가정", "source": "RiskMetrics 관행값"}])


def _explain_var_es(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    cl = r.get("confidence_level") or 0.99
    h = r.get("historical") or {}
    title = (f"하루 동안 {cl:.0%} 확률로 손실이 {_eok(h.get('var_amount'))}을 넘지 않았어요"
             if isinstance(h.get("var_amount"), (int, float)) else "VaR 를 쟀어요")
    facts = [f"정규분포 {_eok((r.get('normal') or {}).get('var_amount'))} · EWMA {_eok((r.get('ewma') or {}).get('var_amount'))} · "
             f"과거 그대로 {_eok(h.get('var_amount'))}",
             f"그 선을 넘는 날의 평균 손실(ES, 정규) {_eok((r.get('normal') or {}).get('es_amount'))}"]
    comps = r.get("components") or []
    if comps:
        top = max(comps, key=lambda c: abs(c.get("amount") or 0))
        facts.append(f"손실 위험을 가장 많이 만드는 종목: {top['label']} ({_eok(top['amount'])})")
    trust = [*_base_trust(view),
             _t(ASSUMED, "세 방법은 합치지 않았어요 — 정규·EWMA 는 분포 가정, 과거 그대로는 표본의 순서 없는 재현이에요."),
             _t(CONFIRMED, f"과거 그대로 방법: {h.get('n_obs')}일 중 {h.get('n_beyond')}일이 이 선을 넘었어요.")]
    if comps:
        trust.append(_t(ASSUMED, "종목별 구성은 정규·표본 공분산으로 나눈 값이라 정규 VaR 와 평균 항만큼 달라요."))
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["유동성이 마를 때 팔지 못하는 손실", "표본에 없던 위기(표본 밖 꼬리)"]}


# ── 몬테카를로 VaR ───────────────────────────────────────────────────────────

class McVarParams(_Valued):
    confidence_level: float = Field(0.99, ge=0.9, le=0.999, json_schema_extra={"x-ui": _CL_UI})
    holding_period: int = Field(1, ge=1, le=20, json_schema_extra={"x-ui": _ui(
        "보유 기간", question="며칠 들고 있다고 볼까요?", unit="일",
        presets=[{"label": "1일", "value": 1}, {"label": "5일", "value": 5}, {"label": "10일", "value": 10}])})
    n_simulations: int = Field(10000, ge=1000, le=50000, json_schema_extra={"x-ui": _ui(
        "경로 수", "advanced", help="많을수록 추정 오차가 줄어요 — 상한 5만.")})
    use_ewma: bool = Field(True, json_schema_extra={"x-ui": _ui(
        "최근 변동성 가중(EWMA)", "advanced", help="끄면 전체 표본의 표준편차를 써요.")})
    ewma_lambda: float = Field(0.94, ge=0.8, le=0.999, json_schema_extra={"x-ui": _ui("EWMA 감쇠", "advanced")})


def _mc_var(inputs: dict, p: McVarParams) -> pg.NodeOutput:
    from src.models.monte_carlo import MonteCarloVaR
    s = _series(inputs, p.series)
    _need(s, 30, "몬테카를로 VaR")
    eng = MonteCarloVaR(n_simulations=p.n_simulations, holding_period=p.holding_period,
                        confidence_level=p.confidence_level, seed=42)
    if s["w"] is not None:
        res = eng.multi_asset_var(_to_log(s["R"], "수익률"), s["w"], p.portfolio_value,
                                  use_ewma=p.use_ewma, ewma_lambda=p.ewma_lambda)
        res["kind"] = "multi"
    else:
        res = eng.single_asset_var(s["lr"], p.portfolio_value, use_ewma=p.use_ewma, ewma_lambda=p.ewma_lambda)
        res["kind"] = "single"
    return _out(s, res, [_value_input(p.portfolio_value),
                         {"key": "gbm", "label": "가격 경로", "value": "기하 브라운 운동(정규 충격)", "basis": "가정",
                          "source": "꼬리가 두꺼운 날·급변(점프)은 들어 있지 않아요"},
                         {"key": "seed", "label": "난수 시드", "value": 42, "basis": "가정",
                          "source": "고정 — 같은 입력이면 같은 수가 나와요"},
                         {"key": "paths", "label": "경로 수", "value": p.n_simulations, "unit": "개", "basis": "가정",
                          "source": "직접 정한 값"}])


def _explain_mc_var(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    multi = r.get("kind") == "multi"
    var = r.get("mc_var_amount") if multi else r.get("var_amount")
    es = r.get("mc_es_amount") if multi else r.get("es_amount")
    cl, hp = r.get("confidence_level") or 0.99, r.get("holding_period_days") or 1
    title = f"{hp}일 동안 {cl:.0%} 확률로 손실이 {_eok(var)}을 넘지 않았어요(모의 경로)"
    facts = [f"그 선을 넘는 경로의 평균 손실(ES) {_eok(es)}", f"추정 오차(표준오차) ±{_eok(r.get('var_std_error'))}"]
    if multi and isinstance(r.get("diversification_benefit"), (int, float)):
        facts.append(f"종목을 섞어 줄어든 위험(분산 효과) {_eok(r['diversification_benefit'])}")
    trust = [*_base_trust(view),
             _t(ASSUMED, "가격이 정규 충격의 기하 브라운 운동을 따른다고 가정했어요 — 급락이 몰리는 날은 작게 나올 수 있어요."),
             _t(CONFIRMED, "난수 시드를 고정해 같은 입력이면 같은 수가 나와요.")]
    return {"title": title, "facts": facts, "trust": trust,
            "unmeasured": ["점프·꼬리 의존(위기 때 함께 떨어지는 정도의 변화)"]}


# ── 변동성 모델 ──────────────────────────────────────────────────────────────

class VolModelsParams(_SeriesParams):
    ewma_lambda: float = Field(0.94, ge=0.8, le=0.999, json_schema_extra={"x-ui": _ui(
        "EWMA 감쇠", question="최근 날을 얼마나 무겁게 볼까요?",
        presets=[{"label": "0.94", "value": 0.94}, {"label": "0.97", "value": 0.97}],
        help="클수록 오래된 날도 오래 기억해요.")})


def _vol_models(inputs: dict, p: VolModelsParams) -> pg.NodeOutput:
    from src.models.garch import VolatilityModelComparison
    s = _series(inputs, p.series)
    _need(s, _MIN_OBS, "GARCH 추정")
    res = VolatilityModelComparison(s["lr"], p.ewma_lambda).compare()
    return _out(s, res, [{"key": "lambda", "label": "EWMA 감쇠 λ", "value": f"{p.ewma_lambda:g}", "basis": "가정", "source": "직접 정한 값"},
                         {"key": "garch", "label": "GARCH(1,1)", "value": "최대우도 추정", "basis": "관측",
                          "source": "이 표본에 맞춘 모수 — 표본이 바뀌면 달라져요"}])


def _explain_vol_models(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    cv, ms = r.get("current_volatility") or {}, r.get("model_selection") or {}
    ga = r.get("garch") or {}
    g, e = cv.get("garch_annual"), cv.get("ewma_annual")
    title = (f"지금 변동성은 연 {g:.1%}(GARCH) · {e:.1%}(EWMA)로 봐요"
             if isinstance(g, (int, float)) and isinstance(e, (int, float)) else "변동성 모델을 비교했어요")
    facts = []
    if isinstance(ga.get("long_run_vol_annual"), (int, float)):
        facts.append(f"GARCH 의 장기 평균 변동성 연 {ga['long_run_vol_annual']:.1%} · 반감기 {ga.get('half_life_days')}일")
    if ms:
        facts.append(f"표본 안 적합: AIC 는 {ms.get('aic_winner')}, BIC 는 {ms.get('bic_winner')}")
    trust = [*_base_trust(view),
             _t(ASSUMED, "AIC·BIC 는 이 표본에 얼마나 잘 맞는지(표본 안 적합)예요 — 앞날의 변동성을 더 잘 맞힌다는 뜻이 아니에요."),
             _t(UNKNOWN, "EWMA 는 평균으로 돌아가지 않아 장기 변동성·반감기가 정의되지 않아요(빈칸).")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["표본 밖 변동성 예측 적중률"]}


# ── 보유기간 VaR ─────────────────────────────────────────────────────────────

class HoldingVarParams(_Valued):
    holding_periods: list[int] = Field([1, 5, 10, 20], min_length=1, max_length=6, json_schema_extra={"x-ui": _ui(
        "보유 기간들", unit="일", help="1~250일, 여섯 개까지.")})
    confidence_levels: list[float] = Field([0.95, 0.99], min_length=1, max_length=3, json_schema_extra={"x-ui": _ui(
        "신뢰수준들", "advanced")})
    method: Literal["parametric", "historical"] = Field("parametric", json_schema_extra={"x-ui": _ui(
        "방법", question="하루 손실을 어떻게 잴까요?",
        presets=[{"label": "정규분포", "value": "parametric"}, {"label": "과거 그대로", "value": "historical"}])})


def _holding_var(inputs: dict, p: HoldingVarParams) -> pg.NodeOutput:
    from src.models.risk_analytics import holding_period_var_es
    if any(not 1 <= t <= 250 for t in p.holding_periods):
        raise pg.NodeFailure("보유 기간은 1~250일이에요.")
    if any(not 0.9 <= c <= 0.999 for c in p.confidence_levels):
        raise pg.NodeFailure("신뢰수준은 0.9~0.999 예요.")
    s = _series(inputs, p.series)
    _need(s, 30, "보유기간 VaR")
    res = holding_period_var_es(s["lr"], holding_periods=list(p.holding_periods),
                                confidence_levels=list(p.confidence_levels),
                                portfolio_value=p.portfolio_value, method=p.method)
    return _out(s, res, [_value_input(p.portfolio_value),
                         {"key": "sqrt_t", "label": "√T 확장", "value": "하루 값 × √보유일", "basis": "가정",
                          "source": "날마다 독립이고 분포가 같다는 가정 — 추세·변동성 뭉침이 있으면 틀려요"}])


def _explain_holding_var(view: dict, prov: dict, params: Any) -> dict:
    rows = (view.get("result") or {}).get("results") or []
    top = max(rows, key=lambda x: (x.get("confidence_level") or 0, x.get("holding_period_days") or 0)) if rows else None
    title = (f"{top['holding_period_days']}일 들고 있으면 {top['confidence_level']:.0%} 확률로 손실이 "
             f"{_eok(top['var_amount'])}을 넘지 않는다고 봐요" if top else "보유기간 VaR 를 쟀어요")
    trust = [*_base_trust(view),
             _t(ASSUMED, "하루 값을 √보유일로 늘렸어요 — 날마다 독립이라는 가정이라 변동성이 뭉치는 시기엔 작게 나올 수 있어요.")]
    return {"title": title, "facts": [f"{r['holding_period_days']}일 · {r['confidence_level']:.0%}: {_eok(r['var_amount'])}"
                                      for r in rows[:6]],
            "trust": trust, "unmeasured": ["보유 중 리밸런싱·손절의 효과"]}


# ── FRTB ES ──────────────────────────────────────────────────────────────────

class FrtbParams(_Valued):
    risk_factor_type: Literal[tuple(LIQUIDITY_HORIZON_MAP)] = Field(  # type: ignore[valid-type]
        "large_cap_equity", json_schema_extra={"x-ui": _ui(
            "위험 요인 종류", question="얼마나 빨리 팔 수 있는 자산인가요?",
            presets=[{"label": "대형주(10일)", "value": "large_cap_equity"},
                     {"label": "중소형주(20일)", "value": "small_cap_equity"}],
            help="규제 표의 유동성 기간(10~120일)을 정해요.")})


def _frtb_es(inputs: dict, p: FrtbParams) -> pg.NodeOutput:
    from src.models.frtb_es import FRTBExpectedShortfall
    s = _series(inputs, p.series)
    _need(s, _MIN_OBS, "FRTB ES")
    res = FRTBExpectedShortfall().single_ticker_report(s["lr"], p.portfolio_value, p.risk_factor_type)
    # 스트레스 구간을 찾았는지는 모델이 말한다(BL3 M4) — 노드는 그 플래그를 윗단으로 올려 화면·설명이 쓰게 한다.
    res["stress_window_found"] = bool((res.get("stressed_es") or {}).get("stress_window_found"))
    return _out(s, res, [_value_input(p.portfolio_value),
                         {"key": "lh", "label": "유동성 기간", "value": LIQUIDITY_HORIZON_MAP[p.risk_factor_type],
                          "unit": "일", "basis": "가정", "source": f"규제 표의 '{p.risk_factor_type}' 칸"},
                         {"key": "stress", "label": "스트레스 구간", "value": "표본 안 최악 250일", "basis": "근사",
                          "source": "규제는 2007년 이후 전체에서 고르지만 여기선 받은 표본 안에서만 찾아요"}])


def _explain_frtb(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    se = r.get("stressed_es") or {}
    title = (f"규제 공식(IMA)으로 계산한 자본 {_eok(r.get('imcc_capital_charge'))}"
             if isinstance(r.get("imcc_capital_charge"), (int, float)) else "FRTB ES 를 쟀어요")
    facts = [f"ES 97.5%(과거 그대로) {_eok((r.get('historical_es') or {}).get('es_amount'))}"]
    trust = [*_base_trust(view),
             _t(ASSUMED, "규제 공식의 계산값이에요 — 감독 승인을 받은 내부모형이 아니에요.")]
    if r.get("stress_window_found"):
        facts.append(f"스트레스 ES {_eok(se.get('stressed_es_975'))} ({se.get('stress_window_start')} ~ "
                     f"{se.get('stress_window_end')}, 현재의 {se.get('stress_ratio')}배)")
        trust.append(_t(ASSUMED, "스트레스 구간은 받은 표본 안의 최악 250일이에요 — 표본 밖 위기(예: 2008)는 들어 있지 않아요."))
    else:
        trust.append(_t(UNKNOWN, f"표본이 {r.get('observations')}일이라 250일 스트레스 구간을 찾지 못했어요 — "
                                 "스트레스 ES 자리에 현재 ES 를 그대로 둔 값이에요. 수익률 기간을 늘려 주세요."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["모형 승인·백테스트 예외(규제 트래픽 라이트)"]}


# ── 롤링 샤프 ────────────────────────────────────────────────────────────────

class RollingSharpeParams(_SeriesParams):
    window: int = Field(252, ge=20, le=756, json_schema_extra={"x-ui": _ui(
        "창 길이", question="몇 일씩 묶어 볼까요?", unit="거래일",
        presets=[{"label": "6개월", "value": 126}, {"label": "1년", "value": 252}])})
    risk_free_rate: float = Field(0.03, ge=0, le=0.2, json_schema_extra={"x-ui": _ui(
        "무위험수익률", "advanced", help="연 수익률 — 가정이에요.")})


def _rolling_sharpe(inputs: dict, p: RollingSharpeParams) -> pg.NodeOutput:
    from src.models.risk_analytics import rolling_sharpe
    s = _series(inputs, p.series)
    if s["meta"]["obs"] <= p.window:
        raise pg.NodeFailure(f"수익률이 {s['meta']['obs']}일이라 {p.window}일 창을 한 번도 채우지 못해요 — "
                             "기간을 늘리거나 창을 줄여 주세요.")
    res = rolling_sharpe(s["lr"], window=p.window, risk_free_rate=p.risk_free_rate)
    return _out(s, res, [{"key": "rf", "label": "무위험수익률", "value": p.risk_free_rate, "basis": "가정",
                          "source": "직접 정한 연 수익률 — 관측값이 아니에요"},
                         {"key": "window", "label": "창 길이", "value": p.window, "unit": "일", "basis": "가정",
                          "source": "직접 정한 값"}])


def _explain_rolling_sharpe(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    cur = r.get("current")
    title = f"최근 {r.get('window')}일 샤프 비율은 {cur:.2f}예요" if isinstance(cur, (int, float)) else "롤링 샤프를 쟀어요"
    facts = [f"구간 평균 {r.get('mean')} · 가장 낮을 때 {r.get('min')} · 가장 높을 때 {r.get('max')}"]
    trust = [*_base_trust(view),
             _t(ASSUMED, "과거 창마다의 위험 대비 수익이에요 — 다음 창의 샤프를 예측하지 않아요.")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["비용·세금을 뺀 샤프"]}


# ── 동적 상관 ────────────────────────────────────────────────────────────────

class DccParams(BaseModel):
    model_config = _FORBID


def _dcc(inputs: dict, p: DccParams) -> pg.NodeOutput:
    from src.models.dcc_garch_wwr import dcc_garch_full_report
    rv = inputs["returns"]
    R: pd.DataFrame = rv["returns"]
    if len(R.columns) > _DCC_MAX_ASSETS:
        raise pg.NodeFailure(f"동적 상관은 종목 {_DCC_MAX_ASSETS}개까지 봐요 — 지금 {len(R.columns)}개예요. 유니버스를 줄여 주세요.")
    lr_df = _to_log(R, "수익률")
    s = {"lr": lr_df, "R": R, "w": None, "notes": [],
         "meta": {"series": "assets", "label": "종목 쌍", "obs": int(len(lr_df)),
                  "start": str(lr_df.index[0])[:10] if len(lr_df) else None,
                  "end": str(lr_df.index[-1])[:10] if len(lr_df) else None, "return_basis": RETURN_BASIS,
                  "source": (rv.get("coverage") or {}).get("source"), "weights": None,
                  "labels": _labels(list(R.columns))}}
    _need(s, _MIN_OBS, "동적 상관")
    res = dcc_garch_full_report(lr_df)
    return _out(s, res, [{"key": "dcc", "label": "DCC-GARCH(1,1)", "value": "종목별 GARCH + 상관 동학", "basis": "관측",
                          "source": "이 표본에 맞춘 모수"},
                         {"key": "normal", "label": "충격 분포", "value": "정규", "basis": "가정", "source": "우도 추정의 가정"}])


def _explain_dcc(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    d = r.get("dcc_garch") or {}
    stats = d.get("correlation_stats") or {}
    title = "종목 사이 상관이 시간에 따라 어떻게 움직였는지 봤어요"
    facts = []
    if isinstance(d.get("dcc_persistence"), (int, float)):
        facts.append(f"상관의 지속성 {d['dcc_persistence']:.2f} (1 에 가까울수록 한번 바뀐 상관이 오래가요)")
    for pair, st in list(stats.items())[:3]:
        if isinstance(st, dict) and isinstance(st.get("mean"), (int, float)):
            facts.append(f"{pair}: 평균 {st['mean']:.2f} · 범위 {st.get('min')} ~ {st.get('max')}")
    trust = [*_base_trust(view), _t(ASSUMED, "상관은 함께 움직인 정도예요 — 한쪽이 다른 쪽을 움직인다는 뜻(인과)이 아니에요.")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["위기 때 상관이 한꺼번에 오르는 정도(표본 밖)"]}


# ══ 파생·신용 계산기 (R2) ════════════════════════════════════════════════════
# 입력 포트가 없는 계산 노드 — 모든 칸이 가정이다(시장에서 읽지 않는다). 선물 헤지만 수익률·비중을 이으면 β 를 관측한다.

def _assumed(key: str, label: str, value: Any, unit: str | None = None, source: str = "직접 넣은 값") -> dict:
    return {"key": key, "label": label, "value": value, "basis": "가정", "source": source, **({"unit": unit} if unit else {})}


def _calc_out(result: dict, inputs: list[dict], provenance: dict | None = None) -> pg.NodeOutput:
    return pg.NodeOutput(values={}, view={"result": _finite({**result, "inputs": inputs})}, provenance=provenance or {})


_CALC_TRUST = "모든 입력은 직접 넣은 가정이에요 — 시장 가격·신용등급을 읽지 않았어요."


class OptionParams(BaseModel):
    model_config = _FORBID
    S: float = Field(100.0, gt=0, json_schema_extra={"x-ui": _ui("기초자산 가격", question="지금 기초자산은 얼마인가요?")})
    K: float = Field(100.0, gt=0, json_schema_extra={"x-ui": _ui("행사가", question="얼마에 사고팔 권리인가요?")})
    T: float = Field(0.25, ge=0, le=30, json_schema_extra={"x-ui": _ui(
        "만기", unit="년", presets=[{"label": "3개월", "value": 0.25}, {"label": "1년", "value": 1.0}])})
    r: float = Field(0.035, ge=-0.05, le=0.3, json_schema_extra={"x-ui": _ui("무위험수익률", help="연율, 연속복리.")})
    sigma: float = Field(0.25, gt=0, le=5, json_schema_extra={"x-ui": _ui(
        "변동성", question="1년에 얼마나 출렁인다고 볼까요?", presets=[{"label": "20%", "value": 0.2}, {"label": "30%", "value": 0.3}])})
    option_type: Literal["call", "put"] = Field("call", json_schema_extra={"x-ui": _ui(
        "종류", presets=[{"label": "콜(살 권리)", "value": "call"}, {"label": "풋(팔 권리)", "value": "put"}])})


def _option(inputs: dict, p: OptionParams) -> pg.NodeOutput:
    from src.models.ficc_engine import FICCEngine
    res = FICCEngine.bs_greeks(p.S, p.K, p.T, p.r, p.sigma, p.option_type)
    return _calc_out(res, [_assumed("S", "기초자산 가격", f"{p.S:g}"), _assumed("K", "행사가", f"{p.K:g}"),
                           _assumed("T", "만기", p.T, "년"), _assumed("r", "무위험수익률", p.r),
                           _assumed("sigma", "변동성", p.sigma, source="내재·과거 변동성을 읽지 않은 직접 입력"),
                           _assumed("model", "모형", "블랙-숄즈(유럽형, 배당 없음)", source="만기 전 행사·배당은 반영하지 않아요")])


def _explain_option(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    kind = "콜" if str(r.get("Type")).upper() == "CALL" else "풋"
    if r.get("at_expiry"):
        return {"title": f"만기인 {kind} 옵션 — 내재가치 {r.get('Price')}만 남아요",
                "facts": ["시간 가치가 없어 감마·베가·세타·로는 0 이에요",
                          "델타는 내가격이면 ±1, 외가격이면 0, 등가격이면 정의되지 않아요"],
                "trust": [_t(ASSUMED, _CALC_TRUST)], "unmeasured": ["만기 당일의 결제 방식(현금/실물)"]}
    return {"title": f"이 {kind} 옵션의 이론가는 {r.get('Price')}예요",
            "facts": [f"델타 {r.get('Delta')} — 기초자산이 1 오르면 옵션값이 이만큼 움직여요",
                      f"베가 {r.get('Vega')} (변동성 1%p 당) · 세타 {r.get('Theta')} (하루 당) · 로 {r.get('Rho')} (금리 1%p 당)"],
            "trust": [_t(ASSUMED, _CALC_TRUST), _t(ASSUMED, "블랙-숄즈 유럽형 — 조기행사·배당·변동성 스마일은 반영하지 않아요.")],
            "unmeasured": ["시장 호가(내재변동성)와의 차이"]}


class BondParams(BaseModel):
    model_config = _FORBID
    face_value: float = Field(10000.0, gt=0, json_schema_extra={"x-ui": _ui("액면", unit="원")})
    coupon_rate: float = Field(0.035, ge=0, le=0.3, json_schema_extra={"x-ui": _ui("쿠폰 금리", help="연율.")})
    ytm: float = Field(0.04, ge=-0.05, le=0.5, json_schema_extra={"x-ui": _ui(
        "만기 수익률", question="시장이 요구하는 수익률은?", help="직접 넣는 값이에요 — 시장 금리를 읽지 않아요.")})
    years_to_maturity: int = Field(5, ge=1, le=50, json_schema_extra={"x-ui": _ui("남은 만기", unit="년")})
    freq: Literal[1, 2, 4, 12] = Field(2, json_schema_extra={"x-ui": _ui(
        "이자 지급 횟수", "advanced", unit="회/년", presets=[{"label": "연 1회", "value": 1}, {"label": "반기", "value": 2},
                                                           {"label": "분기", "value": 4}])})


def _bond(inputs: dict, p: BondParams) -> pg.NodeOutput:
    from src.models.ficc_engine import FICCEngine
    res = FICCEngine.bond_analytics(p.face_value, p.coupon_rate, p.ytm, p.years_to_maturity, p.freq)
    return _calc_out(res, [_assumed("face", "액면", p.face_value, "원"), _assumed("coupon", "쿠폰 금리", p.coupon_rate),
                           _assumed("ytm", "만기 수익률", p.ytm, source="직접 넣은 값 — 시장 금리가 아니에요"),
                           _assumed("years", "남은 만기", p.years_to_maturity, "년"), _assumed("freq", "지급 횟수", p.freq, "회/년")])


def _explain_bond(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    return {"title": f"이 채권의 가격은 {r.get('Price')}예요",
            "facts": [f"수정 듀레이션 {r.get('Modified_Duration')} — 금리가 1%p 오르면 가격이 약 {r.get('Modified_Duration')}% 내려요",
                      f"볼록성 {r.get('Convexity')} · 1bp 가치(DV01) {r.get('DV01')}"],
            "trust": [_t(ASSUMED, _CALC_TRUST), _t(ASSUMED, "고정 쿠폰·일정한 수익률로 할인했어요 — 수익률 곡선의 모양은 반영하지 않아요.")],
            "unmeasured": ["신용 스프레드·조기상환 옵션"]}


class HedgeParams(BaseModel):
    model_config = _FORBID
    portfolio_value: float = Field(1e9, gt=0, le=1e13, json_schema_extra={"x-ui": _ui(
        "헤지할 금액", unit="원", presets=[{"label": "1억", "value": 1e8}, {"label": "10억", "value": 1e9}])})
    current_beta: float | None = Field(1.0, ge=-3, le=5, json_schema_extra={"x-ui": _ui(
        "지금 β", question="시장이 1% 움직일 때 몇 % 움직이나요?",
        help="비우고 수익률·비중을 이으면 과거 표본으로 재요.")})
    target_beta: float = Field(0.0, ge=-3, le=5, json_schema_extra={"x-ui": _ui(
        "목표 β", presets=[{"label": "0(시장 중립)", "value": 0.0}, {"label": "0.5", "value": 0.5}])})
    futures_price: float = Field(350.0, gt=0, json_schema_extra={"x-ui": _ui(
        "선물 가격", help="예시값이에요 — 오늘의 선물 가격으로 바꿔 주세요.")})
    multiplier: int = Field(250000, gt=0, json_schema_extra={"x-ui": _ui(
        "거래 승수", "advanced", unit="원/포인트", help="코스피200 선물은 25만 원이에요.")})


def _measured_beta(inputs: dict) -> tuple[float, int, str]:
    rv, w = inputs["returns"], inputs["weights"]
    bench = rv.get("bench")
    if bench is None or len(bench) == 0:
        raise pg.NodeFailure("비교 기준(지수) 수익률이 없어 β 를 잴 수 없어요 — 유니버스의 비교 기준을 정하거나 β 를 직접 넣어 주세요.")
    R = rv["returns"]
    arr, _ = _aligned_weights(R, w)
    both = pd.concat([R @ arr, bench], axis=1).dropna()
    if len(both) < 30:
        raise pg.NodeFailure(f"β 를 잴 겹치는 날이 {len(both)}일뿐이에요 — 최소 30일이 필요해요.")
    var_b = float(np.var(both.iloc[:, 1], ddof=1))
    if var_b <= 0:
        raise pg.NodeFailure("비교 기준 수익률이 움직이지 않아(분산 0) β 를 잴 수 없어요.")
    beta = float(np.cov(both.iloc[:, 0], both.iloc[:, 1], ddof=1)[0, 1] / var_b)
    span = f"{str(both.index[0])[:10]} ~ {str(both.index[-1])[:10]}"
    return beta, len(both), span


def _hedge(inputs: dict, p: HedgeParams) -> pg.NodeOutput:
    from src.models.hedging import HedgingSimulator
    wired = inputs.get("returns") is not None and inputs.get("weights") is not None
    if wired:
        beta, n, span = _measured_beta(inputs)
        beta_in = {"key": "beta", "label": "지금 β", "value": f"{beta:.3f}", "basis": "관측",
                   "source": f"포트폴리오 대 비교 기준 일간 수익률 {n}일({span}) 공분산/분산 — 과거 표본"}
    elif p.current_beta is None:
        raise pg.NodeFailure("지금 β 가 없어요 — 값을 넣거나 수익률·비중을 이어 과거 표본으로 재 주세요.")
    else:
        beta = float(p.current_beta)
        beta_in = _assumed("beta", "지금 β", f"{beta:.3f}")
    # 반올림 뒤 β·감소율·β=0 사유는 모델이 낸다(BL3 M5) — 노드는 그대로 싣는다.
    res = HedgingSimulator(p.futures_price, p.multiplier).equity_futures_hedge(p.portfolio_value, beta, p.target_beta)
    return _calc_out(res, [beta_in, _assumed("target", "목표 β", f"{p.target_beta:.3f}"),
                           _assumed("value", "헤지할 금액", p.portfolio_value, "원"),
                           _assumed("F", "선물 가격", p.futures_price, source="예시·직접 입력 — 오늘 가격이 아니에요"),
                           _assumed("M", "거래 승수", p.multiplier, "원/포인트")],
                     {"beta_basis": "관측" if wired else "가정"})


def _fb(x: Any) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "—"


def _explain_hedge(view: dict, prov: dict, params: Any) -> dict:
    fb = _fb
    r = view.get("result") or {}
    n = r.get("contracts_to_trade")
    cur, after = r.get("current_beta"), r.get("beta_after_rounding")
    title = (f"선물 {abs(n)}계약을 {'팔면' if n < 0 else '사면'} β 가 {fb(cur)} → {fb(after)} 가 돼요"
             if isinstance(n, int) and n != 0 else
             f"목표까지 {abs(r.get('raw_contracts') or 0):.2f}계약이라 반올림하면 0계약 — β 는 {fb(cur)} 그대로예요")
    facts = [f"계약 1개의 크기 {_eok(r.get('contract_value'))} · 헤지 명목 {_eok(r.get('hedge_notional'))}",
             f"계산상 {r.get('raw_contracts')}계약을 반올림했어요 (목표 β {fb(r.get('target_beta'))})"]
    trust = [_t(ASSUMED, "선물 가격·승수는 직접 넣은 값이에요.")]
    if prov.get("beta_basis") == "관측":
        trust.append(_t(CONFIRMED, "β 는 이어진 수익률·비중의 과거 표본으로 쟀어요 — 앞으로도 같다는 보장은 없어요."))
    else:
        trust.append(_t(ASSUMED, "β 는 직접 넣은 값이에요."))
    if r.get("reduction_reason"):
        trust.append(_t(UNKNOWN, r["reduction_reason"]))
    else:
        trust.append(_t(ASSUMED, "'줄어드는 위험' 은 β(시장 위험)의 감소율이에요 — 종목 고유의 위험은 그대로 남아요."))
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["베이시스 위험·롤오버 비용·증거금"]}


class CvaParams(BaseModel):
    model_config = _FORBID
    notional: float = Field(1e10, gt=0, le=1e14, json_schema_extra={"x-ui": _ui("명목 금액", unit="원")})
    maturity_years: float = Field(5.0, gt=0, le=30, json_schema_extra={"x-ui": _ui("만기", unit="년")})
    position_type: Literal["irs", "fx_forward", "option"] = Field("irs", json_schema_extra={"x-ui": _ui(
        "거래 종류", presets=[{"label": "금리스왑", "value": "irs"}, {"label": "통화선도", "value": "fx_forward"},
                               {"label": "옵션", "value": "option"}], help="노출 곡선의 모양을 정해요.")})
    cds_spread_bps: float = Field(150.0, gt=0, le=5000, json_schema_extra={"x-ui": _ui(
        "상대방 CDS 스프레드", unit="bp", question="상대방이 부도날 위험을 시장은 얼마로 보나요?")})
    recovery_rate: float = Field(0.40, ge=0, lt=1, json_schema_extra={"x-ui": _ui("회수율", "advanced")})
    risk_free_rate: float = Field(0.03, ge=-0.05, le=0.3, json_schema_extra={"x-ui": _ui("무위험수익률", "advanced")})
    volatility: float = Field(0.02, gt=0, le=1, json_schema_extra={"x-ui": _ui(
        "노출 변동성", "advanced", help="양식화된 노출 곡선의 높이를 정해요.")})
    bank_cds_spread_bps: float = Field(50.0, gt=0, le=5000, json_schema_extra={"x-ui": _ui("우리 CDS 스프레드", "advanced", unit="bp")})
    bank_recovery: float = Field(0.40, ge=0, lt=1, json_schema_extra={"x-ui": _ui("우리 회수율", "advanced")})
    spread_shock_bps: float = Field(100.0, ge=0, le=5000, json_schema_extra={"x-ui": _ui("스프레드 충격", "advanced", unit="bp")})
    cds_1y: float = Field(0.0, ge=0, le=5000, json_schema_extra={"x-ui": _ui("CDS 1년", "advanced", unit="bp", help="두 칸 이상 넣으면 기간구조를 만들어요.")})
    cds_3y: float = Field(0.0, ge=0, le=5000, json_schema_extra={"x-ui": _ui("CDS 3년", "advanced", unit="bp")})
    cds_5y: float = Field(0.0, ge=0, le=5000, json_schema_extra={"x-ui": _ui("CDS 5년", "advanced", unit="bp")})
    cds_10y: float = Field(0.0, ge=0, le=5000, json_schema_extra={"x-ui": _ui("CDS 10년", "advanced", unit="bp")})


def _cva(inputs: dict, p: CvaParams) -> pg.NodeOutput:
    from src.models.cva_engine import CVAEngine
    ts = {k: v for k, v in {1: p.cds_1y, 3: p.cds_3y, 5: p.cds_5y, 10: p.cds_10y}.items() if v > 0}
    res = CVAEngine(p.risk_free_rate, p.recovery_rate).full_cva_report(
        notional=p.notional, maturity_years=p.maturity_years, cds_spread_bps=p.cds_spread_bps,
        position_type=p.position_type, volatility=p.volatility, bank_cds_spread_bps=p.bank_cds_spread_bps,
        bank_recovery=p.bank_recovery, spread_shock_bps=p.spread_shock_bps,
        cds_term_structure=ts if len(ts) >= 2 else None)       # 라우트와 같은 규칙: 두 점 이상이어야 기간구조
    return _calc_out(res, [_assumed("notional", "명목 금액", p.notional, "원"), _assumed("maturity", "만기", p.maturity_years, "년"),
                           _assumed("cds", "상대방 CDS 스프레드", p.cds_spread_bps, "bp", "직접 넣은 값 — 시장 호가를 읽지 않았어요"),
                           _assumed("rr", "회수율", p.recovery_rate),
                           _assumed("ee", "노출 곡선", f"양식화({p.position_type})",
                                    source="거래 종류별 정해진 모양 × 변동성 — 시장 시뮬레이션이 아니에요"),
                           _assumed("ts", "CDS 기간구조", f"{len(ts)}점" if len(ts) >= 2 else "없음(단일 스프레드)")])


def _explain_cva(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    u, b, st = r.get("unilateral_cva") or {}, r.get("bilateral_cva") or {}, r.get("stressed_cva") or {}
    title = f"상대방 부도 위험의 값(CVA)은 {_eok(u.get('cva_amount'))}이에요"
    facts = [f"우리 쪽 부도 위험(DVA)까지 넣은 순값(BCVA) {_eok(b.get('bcva_amount'))}",
             f"상대방 스프레드가 넓어지면 CVA {_eok(st.get('stressed_cva'))} (+{st.get('stress_loss_pct')}%)",
             f"연 스프레드로 환산 {u.get('cva_spread_bps')}bp",
             f"해마다 드는 순비용 근사(BCVA) {_eok((r.get('bcva_spread') or {}).get('bcva_running_annual'))}"]
    trust = [_t(ASSUMED, _CALC_TRUST),
             _t(ASSUMED, "노출 곡선은 거래 종류별로 정해진 모양(양식화)이에요 — 금리·환율 경로를 시뮬레이션한 값이 아니에요."),
             _t(ASSUMED, "연간 순비용은 스프레드 × 평균 노출의 근사예요 — 기간별 할인·생존확률을 넣은 CVA 와 다른 값이에요.")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["담보·네팅 계약의 효과", "노출과 부도의 상관(Wrong-Way)"]}


_RATINGS = ("AAA", "AA", "A", "BBB", "BB", "B", "CCC")


class IrcPosition(BaseModel):
    model_config = _FORBID
    name: str = Field(..., min_length=1, max_length=40, json_schema_extra={"x-ui": _ui("이름")})
    rating: Literal[_RATINGS] = Field("BBB", json_schema_extra={"x-ui": _ui("등급")})  # type: ignore[valid-type]
    notional: float = Field(1e9, gt=0, le=1e13, json_schema_extra={"x-ui": _ui("금액", unit="원")})
    modified_duration: float = Field(5.0, gt=0, le=30, json_schema_extra={"x-ui": _ui("수정 듀레이션")})
    recovery_rate: float = Field(0.40, ge=0, lt=1, json_schema_extra={"x-ui": _ui("회수율", "advanced")})
    liquidity_horizon_months: int = Field(3, ge=3, le=12, json_schema_extra={"x-ui": _ui("유동성 기간", "advanced", unit="개월")})


class IrcParams(BaseModel):
    model_config = _FORBID
    positions: list[IrcPosition] = Field(
        [{"name": "회사채 A", "rating": "BBB", "notional": 1e9, "modified_duration": 5.0},
         {"name": "회사채 B", "rating": "BB", "notional": 5e8, "modified_duration": 3.0}],
        min_length=1, max_length=20, validate_default=True, json_schema_extra={"x-ui": _ui(
            "신용 포지션", question="어떤 채권을 들고 있나요?", help="20개까지.")})
    n_simulations: int = Field(50000, ge=1000, le=50000, json_schema_extra={"x-ui": _ui("경로 수", "advanced")})


def _irc(inputs: dict, p: IrcParams) -> pg.NodeOutput:
    from src.models.credit_spread_idr import CreditPosition, IncrementalRiskCharge
    pos = [CreditPosition(name=x.name, rating=x.rating, notional=x.notional, modified_duration=x.modified_duration,
                          recovery_rate=x.recovery_rate, liquidity_horizon_months=x.liquidity_horizon_months)
           for x in p.positions]
    res = IncrementalRiskCharge().calculate_irc(pos, n_simulations=p.n_simulations, seed=42)
    return _calc_out(res, [_assumed("positions", "포지션", f"{len(pos)}개", source="등급·금액·듀레이션 모두 직접 입력"),
                           _assumed("matrix", "등급 전이 확률", "S&P 1년 평균(1981~2020)",
                                    source="코드에 담긴 상수표 — 한국 시장에 맞춘 값이 아니에요"),
                           _assumed("seed", "난수 시드", 42, source="고정 — 같은 입력이면 같은 수")])


def _explain_irc(view: dict, prov: dict, params: Any) -> dict:
    r = view.get("result") or {}
    title = f"신용 등급이 바뀌거나 부도날 때의 추가 위험 자본(IRC)은 {_eok(r.get('irc_total'))}이에요"
    facts = [f"등급 변화로 인한 스프레드 위험 {_eok(r.get('spread_risk_component'))} · 부도 위험 {_eok(r.get('default_risk_component'))}",
             f"유동성 기간으로 조정하면 {_eok(r.get('irc_lh_adjusted'))}"]
    trust = [_t(ASSUMED, _CALC_TRUST),
             _t(ASSUMED, "등급 전이 확률은 코드에 담긴 S&P 1년 평균표예요 — 한국 등급·경기 국면에 맞춘 값이 아니에요.")]
    return {"title": title, "facts": facts, "trust": trust, "unmeasured": ["발행사끼리의 부도 상관(집중 위험)"]}


# ── 등록 ─────────────────────────────────────────────────────────────────────

def register(registry: pg.Registry) -> None:
    rw = (P("returns", "Returns"), P("weights", "Weights", required=False))
    common = {"outputs": (), "category": "리스크", "stage": "check"}
    for spec in (
        pg.NodeSpec("var_es", "VaR·ES", plain_label="하루에 얼마나 잃을 수 있나",
                    plain_description="정규·EWMA·과거 그대로 세 방법으로 드문 날의 손실과 그 너머 평균 손실을 재요.",
                    inputs=rw, run=_var_es, params_model=VarEsParams, explain=_explain_var_es,
                    description="ParametricRiskModel·PortfolioRiskModel(/calculate-var 와 같은 모델) · 수익률 노드 계열.", **common),
        pg.NodeSpec("mc_var", "몬테카를로 VaR", plain_label="모의 경로로 본 손실",
                    plain_description="수만 개의 가격 경로를 만들어 손실 분포의 꼬리를 봐요.",
                    inputs=rw, run=_mc_var, params_model=McVarParams, explain=_explain_mc_var,
                    description="MonteCarloVaR(seed=42)(/mc-var·/mc-portfolio-var 와 같은 모델).", **common),
        pg.NodeSpec("vol_models", "변동성 모델", plain_label="지금 얼마나 출렁이나",
                    plain_description="GARCH 와 EWMA 로 지금의 변동성과 앞으로 며칠의 흐름을 나란히 봐요.",
                    inputs=rw, run=_vol_models, params_model=VolModelsParams, explain=_explain_vol_models,
                    description="VolatilityModelComparison(/garch-compare 와 같은 모델).", **common),
        pg.NodeSpec("holding_var", "보유기간 VaR", plain_label="며칠 들고 있으면",
                    plain_description="하루 손실을 보유 기간에 맞게 늘려 1·5·10·20일 손실을 봐요.",
                    inputs=rw, run=_holding_var, params_model=HoldingVarParams, explain=_explain_holding_var,
                    description="holding_period_var_es(/holding-period-var 와 같은 함수).", **common),
        pg.NodeSpec("frtb_es", "FRTB ES", plain_label="규제 방식의 꼬리 손실",
                    plain_description="97.5% ES·스트레스 구간·유동성 기간으로 규제 공식의 자본을 계산해요.",
                    inputs=rw, run=_frtb_es, params_model=FrtbParams, explain=_explain_frtb,
                    description="FRTBExpectedShortfall.single_ticker_report(/frtb-es 와 같은 모델).", **common),
        pg.NodeSpec("rolling_sharpe", "롤링 샤프", plain_label="위험 대비 수익의 흐름",
                    plain_description="같은 길이의 창을 밀어 가며 샤프 비율이 어떻게 변했는지 봐요.",
                    inputs=rw, run=_rolling_sharpe, params_model=RollingSharpeParams, explain=_explain_rolling_sharpe,
                    description="rolling_sharpe(/rolling-sharpe 와 같은 함수) · 창보다 짧으면 실패.", **common),
        pg.NodeSpec("dcc_corr", "동적 상관", plain_label="함께 움직임의 변화",
                    plain_description="종목 쌍의 상관이 시간에 따라 어떻게 바뀌었는지 DCC-GARCH 로 봐요.",
                    inputs=(P("returns", "Returns"),), run=_dcc, params_model=DccParams, explain=_explain_dcc,
                    description="dcc_garch_full_report(/dcc-garch 와 같은 모델) · 종목 6개까지.", **common),
        pg.NodeSpec("option_calc", "옵션 계산기", plain_label="옵션의 이론가", category="파생·신용", stage="check",
                    plain_description="기초자산·행사가·만기·변동성을 넣어 옵션값과 그릭을 봐요.",
                    inputs=(), outputs=(), run=_option, params_model=OptionParams, explain=_explain_option,
                    description="FICCEngine.bs_greeks(/analyze-option 과 같다) · 0 이하 입력은 거절."),
        pg.NodeSpec("bond_calc", "채권 계산기", plain_label="채권 가격과 금리 민감도", category="파생·신용", stage="check",
                    plain_description="쿠폰·만기·수익률을 넣어 가격·듀레이션·볼록성을 봐요.",
                    inputs=(), outputs=(), run=_bond, params_model=BondParams, explain=_explain_bond,
                    description="FICCEngine.bond_analytics(/analyze-bond 와 같다)."),
        pg.NodeSpec("futures_hedge", "선물 헤지", plain_label="시장 위험 줄이기", category="파생·신용", stage="check",
                    plain_description="지수 선물 몇 계약으로 β 를 목표까지 낮출지 계산해요.",
                    inputs=(P("returns", "Returns", required=False), P("weights", "Weights", required=False)), outputs=(),
                    run=_hedge, params_model=HedgeParams, explain=_explain_hedge,
                    description="HedgingSimulator.equity_futures_hedge(/calculate-hedge 와 같다) · 이으면 β 를 관측."),
        pg.NodeSpec("cva_calc", "CVA", plain_label="상대방 부도 위험의 값", category="파생·신용", stage="check",
                    plain_description="장외 거래 상대가 부도날 위험을 가격(CVA·DVA)으로 봐요.",
                    inputs=(), outputs=(), run=_cva, params_model=CvaParams, explain=_explain_cva,
                    description="CVAEngine.full_cva_report(/calculate-cva 와 같다) · 양식화 노출 곡선."),
        pg.NodeSpec("irc_calc", "IRC", plain_label="신용 등급 변화의 위험", category="파생·신용", stage="check",
                    plain_description="등급 강등·부도로 생길 수 있는 손실의 추가 위험 자본을 봐요.",
                    inputs=(), outputs=(), run=_irc, params_model=IrcParams, explain=_explain_irc,
                    description="IncrementalRiskCharge.calculate_irc(/calculate-irc 와 같다) · 시드 42."),
    ):
        registry.register(spec)
