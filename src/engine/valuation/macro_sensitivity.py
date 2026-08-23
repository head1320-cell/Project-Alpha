"""매크로 민감도 — 서술이 아니라 **수치** (P2-4)

설계 문서 §4·C.3 이 요구한 출력 형식:

```
+100bp 10Y  → 적정가치 −9.5%
```

★AI 가 서술하지 않는다★(`.md` §19) 계산된 수치이고 provenance 가 남는다.

★구조적 채널 — 표본도 회귀도 필요 없다★
──────────────────────────────────────────────────────────────────────────────
`+100bp` 를 `rf` 로 태우면 `ke = rf + β·erp` 와 `kd = rf + 1.5%` 를 통과해 RIM·DCF·
DDM 이 **정확히** 움직인다. 통계 추정이 아니라 모델의 항등식이므로 `n_obs` 도
표준오차도 없다 — `method: "structural_exact"` 가 그것을 말한다.

이것이 말하는 바를 정확히 적어 둔다: **"rf 가 100bp 오르고 다른 것이 그대로면 우리
DCF 가 X% 내린다"** 다. 시장이 그렇게 반응한다는 주장이 아니다.

★실측이 정한 것 둘★
──────────────────────────────────────────────────────────────────────────────
**① 비대칭이다.** mock 삼성전자: −100bp → **+11.62%** vs +100bp → **−9.54%**.
한쪽만 재서 "민감도 −9.5%" 로 내면 볼록성이 사라진다 → **양방향을 따로** 낸다.

**② 모델별 반응이 3.6배 갈린다.** 같은 −100bp 에 DCF **−20.19%** · DDM −10.18% ·
RIM **−5.59%**. 통합값 하나만 내면 그 사실이 평균에 지워진다 — P2-3 과 같은 이유로
모델별로 함께 낸다.

★낼 수 없는 것을 낼 수 있는 척하지 않는다★
──────────────────────────────────────────────────────────────────────────────
설계 문서는 `GDP −2σ → EPS`, `USD +10% → EPS`, `Oil +30% → EBIT` 도 예로 들었다.
**셋 다 이 저장소에서 산출할 수 없다:**

  · EPS·EBIT 는 밸류에이션 모델의 **입력**이지 출력이 아니다. 매크로에서 EPS 로
    가는 채널이 코드에 없고, 연간 재무 10행으로 그 회귀를 추정하는 것은 날조다.
  · **유가 계열 자체가 수집기에 없다** — 61계열을 확인했다.

그래서 그 셋은 `available:false` + 사유로 나간다. 빈칸이 아니라 **왜 없는지**가
언더라이팅의 정보다.
"""
from __future__ import annotations

import logging

from src.engine.valuation.valuation_models import (
    ValuationParams,
    weighted_intrinsic,
)

logger = logging.getLogger(__name__)

# 구조적으로 전파되는 충격 — 전부 `rf` 채널이다.
# (bp 단위. 양방향을 **따로** 재므로 부호가 있는 값을 쌍으로 둔다.)
DEFAULT_RATE_SHOCKS_BP = (-100, 100)

# ★채널이 없는 항목 — 지어내지 않고 사유를 낸다★
_NO_CHANNEL = (
    {"shock": "GDP −2σ", "target": "EPS",
     "reason": ("밸류에이션 모델은 EPS 를 **입력**으로 받지 산출하지 않습니다. "
                "매크로 → EPS 채널이 코드에 없고, 연간 재무 10행으로 그 회귀를 "
                "추정하는 것은 근거 없는 숫자를 만드는 일입니다.")},
    {"shock": "USD +10%", "target": "EPS",
     "reason": ("같은 이유 — 환율에서 EPS 로 가는 채널이 없습니다. 수출입 비중별 "
                "민감도를 쓰려면 매출 구성 데이터가 필요하고 이 저장소에 없습니다.")},
    {"shock": "Oil +30%", "target": "EBIT",
     "reason": "유가 계열이 매크로 수집기에 없습니다(61계열 확인). 관측 자체가 없습니다.",
     },
)

_MODEL_ORDER = ("RIM", "DCF", "DDM")

# ★코어 계열을 코드에 고정한다★ 수집기에는 61계열이 있지만 61개를 훑어 유의한 것만
# 보고하면 데이터 마이닝이다(Gemini 가 지적한 차원의 저주와 같은 계열). 다섯 개를
# 미리 못박고 **전부** 보고한다 — 고르지 않는 것이 요점이다.
CORE_SERIES = ("KR_10Y", "KR_BASE_RATE", "KR_CPI", "USD_KRW", "KOSPI")

# 회귀에 요구하는 최소 관측 월. 매크로가 60개월이라 무조건부는 통과하지만
# 국면조건부(국면당 ~13개월)는 대부분 여기서 막힌다 — **그 사유가 산출물이다.**
MIN_MONTHS = 24


def _unavailable(reason: str, **extra) -> dict:
    out = {"available": False, "method": None, "base_value": None,
           "rows": [], "unavailable": [], "reason": reason}
    out.update(extra)
    return out


def _shifted(base: ValuationParams, rf_delta: float) -> ValuationParams:
    return ValuationParams(
        risk_free_rate=base.risk_free_rate + rf_delta,
        market_premium=base.market_premium, beta=base.beta,
        terminal_growth_rate=base.terminal_growth_rate,
        projection_years=base.projection_years, tax_rate=base.tax_rate,
        weight_rim=base.weight_rim, weight_dcf=base.weight_dcf,
        weight_ddm=base.weight_ddm)


def macro_sensitivity(fs, base_params: ValuationParams | None = None, *,
                      rate_shocks_bp: tuple[int, ...] = DEFAULT_RATE_SHOCKS_BP) -> dict:
    """금리 충격 → 적정가치. 순수 함수 — I/O 0, 표본 0.

    Args:
        fs: **평가 준비가 끝난** FinancialStatement (`load_statement` 의 결과).
        base_params: 충격을 걸 기준 가정.
        rate_shocks_bp: bp 단위 금리 충격. 기본은 ±100bp — ★양방향을 따로 낸다★.
    """
    from src.engine.valuation.valuation_distribution import _models_for

    if fs is None:
        return _unavailable("재무제표가 없습니다")
    base = base_params or ValuationParams()

    base_models = _models_for(fs, base)
    base_value = weighted_intrinsic(base_models, base)
    if base_value <= 0:
        return _unavailable(
            "기본 가정에서 적정가치가 산출되지 않아 충격을 걸 대상이 없습니다")
    base_by_model = {m.model: float(m.intrinsic_value_per_share) for m in base_models
                     if m.available and m.intrinsic_value_per_share > 0}

    rows: list[dict] = []
    for bp in rate_shocks_bp:
        p = _shifted(base, bp / 10000.0)
        if p.risk_free_rate < 0:
            rows.append({
                "shock": f"{bp:+d}bp 10Y", "unit": "bp", "target": "적정가치",
                "available": False, "method": "structural_exact",
                "reason": f"충격 후 무위험수익률이 음수({p.risk_free_rate:.4f})가 됩니다",
            })
            continue
        models = _models_for(fs, p)
        value = weighted_intrinsic(models, p)
        by_model = {m.model: float(m.intrinsic_value_per_share) for m in models
                    if m.available and m.intrinsic_value_per_share > 0}
        rows.append({
            "shock": f"{bp:+d}bp 10Y", "unit": "bp", "target": "적정가치",
            "available": value > 0,
            "method": "structural_exact",
            "channel": "rf → ke = rf + β·erp, kd = rf + 1.5%p",
            "value_pct": (round((value / base_value - 1.0) * 100, 2)
                          if value > 0 else None),
            "value_won": round(value, 0) if value > 0 else None,
            "direction": ("하락" if value < base_value else "상승") if value > 0 else None,
            # ★모델별로 함께 낸다★ 실측에서 같은 충격에 DCF −20.19% vs RIM −5.59%.
            "by_model_pct": {
                m: round((by_model[m] / base_by_model[m] - 1.0) * 100, 2)
                for m in _MODEL_ORDER
                if m in by_model and base_by_model.get(m, 0) > 0},
            "reason": None if value > 0 else "충격 후 어떤 모델도 적정가치를 내지 못했습니다",
        })

    ok = [r for r in rows if r.get("available") and r.get("value_pct") is not None]
    asymmetry = None
    if len(ok) >= 2:
        # ★비대칭을 숫자로 남긴다★ 대칭이면 |상승폭| == |하락폭| 이다.
        mags = sorted(abs(r["value_pct"]) for r in ok)
        asymmetry = {
            "min_abs_pct": mags[0], "max_abs_pct": mags[-1],
            "ratio": round(mags[-1] / mags[0], 2) if mags[0] > 0 else None,
            "note": ("같은 크기의 반대 충격이 같은 크기로 움직이지 않습니다(볼록성). "
                     "한 방향만 재서 '민감도' 하나로 내면 이 사실이 사라집니다."),
        }

    return {
        "available": bool(ok),
        "method": "structural_exact",
        "base_value": round(base_value, 0),
        "base_by_model": {m: round(v, 0) for m, v in base_by_model.items()},
        "rows": rows,
        "asymmetry": asymmetry,
        # ★낼 수 없는 것은 빈칸이 아니라 사유로★
        "unavailable": [{**item, "available": False, "method": None}
                        for item in _NO_CHANNEL],
        "reason": None if ok else "어떤 충격에서도 적정가치를 산출하지 못했습니다",
        "note": ("이 수치는 **모델의** 민감도입니다 — 'rf 가 그만큼 움직이고 다른 것이 "
                 "그대로면 우리 DCF 가 이만큼 변한다'. 시장이 그렇게 반응한다는 "
                 "주장이 아니며, 통계 추정이 아니라 모델의 항등식입니다."),
    }


def macro_sensitivity_for(code: str, current_price: float) -> dict:
    """종목 코드로 민감도. `load_statement` 를 타므로 **mock 게이트를 공짜로 받는다.**"""
    from src.data.dart_client import DARTClient
    from src.engine.company_analytics import _mcap, resolve_default_params
    from src.engine.valuation.valuation_models import ValuationEngine

    d = resolve_default_params(code)
    base = ValuationParams(risk_free_rate=d["rf"], market_premium=d["erp"],
                           beta=d["beta"], terminal_growth_rate=d["g"],
                           projection_years=int(d["years"]))
    loaded = ValuationEngine(DARTClient()).load_statement(
        code, current_price, market_cap=_mcap(code))
    if not loaded["available"]:
        return _unavailable(loaded["reason"] or "재무제표를 가져오지 못했습니다")
    out = macro_sensitivity(loaded["fs"], base)
    out["code"] = str(code)
    out["corp_name"] = loaded["corp_name"]
    out["is_mock"] = loaded["is_mock"]
    out["base_assumptions"] = d
    return out


# ── 통계 채널 — ★대부분 사유가 나오는 것이 정답이다★ ────────────────────────
#
# 종목 월별 수익률 ↔ 매크로 계열 변화의 베타. 구조적 채널과 **완전히 다른 것**이므로
# 절대 섞지 않는다: 저쪽은 모델의 항등식이고 이쪽은 60개월짜리 표본의 추정이다.


def _monthly_returns(code: str, months: int = 60):
    """월말 종가 기준 월별 수익률. ★창의 끝은 오늘★ (결함 B 와 같은 함정)."""
    from datetime import datetime, timedelta

    from src.data.ohlcv_loader import load_ohlcv_unified
    end = datetime.now().date()
    start = end - timedelta(days=int(months * 31.5) + 60)
    d = load_ohlcv_unified(code, start.isoformat(), end.isoformat(), prefer="auto")
    if d is None or d.empty:
        return None
    return d["close"].resample("ME").last().pct_change().dropna()


def _series_monthly_change(series) -> dict[str, float]:
    """매크로 계열 → {월: 변화율}. 월 키는 `conditional_market` 과 같은 정규형."""
    from src.engine.conditional_market import _normalize_month

    ts = list(getattr(series, "timestamps", None) or [])
    vals = list(getattr(series, "values", None) or [])
    pairs = []
    for t, v in zip(ts, vals):
        m = _normalize_month(str(t)[:7])
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if m is not None:
            pairs.append((m, fv))
    pairs.sort()
    out = {}
    for (_, prev), (m, cur) in zip(pairs, pairs[1:]):
        if prev not in (0, None):
            out[m] = cur / prev - 1.0
    return out


def _ols_beta(x: list[float], y: list[float]) -> dict:
    """단순회귀 y = a + b·x. 베타 · 표준오차 · t값. numpy 만 쓴다."""
    import numpy as np

    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = xa.size
    if n < 3:
        return {"available": False, "reason": f"관측이 {n}개뿐입니다"}
    vx = float(((xa - xa.mean()) ** 2).sum())
    if vx <= 0:
        return {"available": False, "reason": "설명변수가 상수라 기울기를 낼 수 없습니다"}
    beta = float(((xa - xa.mean()) * (ya - ya.mean())).sum() / vx)
    alpha = float(ya.mean() - beta * xa.mean())
    resid = ya - (alpha + beta * xa)
    dof = n - 2
    se = float(np.sqrt((resid ** 2).sum() / dof / vx)) if dof > 0 else None
    return {
        "available": True, "n_obs": int(n),
        "beta": round(beta, 4),
        "std_error": round(se, 4) if se else None,
        "t_stat": (round(beta / se, 2) if se and se > 0 else None),
        "r_squared": round(float(1 - (resid ** 2).sum()
                                 / max(((ya - ya.mean()) ** 2).sum(), 1e-30)), 4),
    }


def statistical_sensitivity(code: str, *, series_map: dict | None = None,
                            core: tuple[str, ...] = CORE_SERIES,
                            min_months: int = MIN_MONTHS) -> dict:
    """종목 월별 수익률 ↔ 코어 매크로 계열의 베타.

    ★유의한 것만 고르지 않는다★ 코어 다섯을 전부 보고한다. 61계열을 훑어 t값이 큰
    것만 내면 그것이 데이터 마이닝이고, 다중검정 보정 없이 "유의하다" 고 말하는
    것은 거짓이다. 그래서 `multiple_testing` 에 몇 개를 동시에 봤는지 적는다.

    ★상관은 인과가 아니다★ 이 값은 60개월짜리 동시대 상관이다. 그레인저 검정이든
    회귀든 인과를 말하지 않는다 — 라벨로 남긴다.
    """
    if series_map is None:
        try:
            from src.engine.regime_analyzer import RegimeAnalyzer
            series_map = RegimeAnalyzer().collector.collect_all(use_cache=True).series
        except Exception as e:  # noqa: BLE001
            logger.warning("매크로 수집 실패 %s: %s", code, e)
            return {"available": False,
                    "reason": f"매크로 계열을 수집하지 못했습니다 ({type(e).__name__})"}

    rets = _monthly_returns(code)
    if rets is None or rets.empty:
        return {"available": False, "reason": "월별 수익률을 만들 수 없습니다"}
    from src.engine.conditional_market import _month_key
    stock = {_month_key(ts): float(v) for ts, v in rets.items()}

    rows = []
    for name in core:
        s = series_map.get(name)
        if s is None:
            rows.append({"series": name, "available": False,
                         "reason": "이 계열이 수집기에 없습니다"})
            continue
        macro = _series_monthly_change(s)
        months = sorted(set(macro) & set(stock))
        if len(months) < min_months:
            rows.append({"series": name, "available": False, "n_obs": len(months),
                         "reason": (f"겹치는 달이 {len(months)}개뿐이라 "
                                    f"기울기를 내지 않았습니다 (최소 {min_months}개). "
                                    "얇은 표본의 베타는 부호조차 믿을 수 없습니다.")})
            continue
        fit = _ols_beta([macro[m] for m in months], [stock[m] for m in months])
        rows.append({"series": name, "span": [months[0], months[-1]], **fit})

    ok = [r for r in rows if r.get("available")]
    return {
        "available": bool(ok),
        "method": "ols_contemporaneous_monthly",
        "rows": rows,
        "multiple_testing": {
            "n_tested": len(core), "series": list(core),
            "note": ("코어 계열을 **코드에 고정**하고 전부 보고합니다. 유의한 것만 "
                     "골라 내면 다중검정 보정 없는 데이터 마이닝이 됩니다 — "
                     f"{len(core)}개를 동시에 봤다는 사실을 t값과 함께 읽으십시오."),
        },
        # ★`causal_deep` 이 쓰는 문구 그대로★
        "causality": ("상관·회귀는 인과가 아닙니다. 이 기울기는 동시대 월별 상관이며 "
                      "방향·매개·공통요인을 구분하지 못합니다."),
        "reason": None if ok else "코어 계열 중 어느 것도 최소 관측을 넘지 못했습니다",
    }
