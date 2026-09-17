"""확률적 밸류에이션 P10~P90 (P2-3)

지금 Company 는 적정가를 **점 하나**로 낸다(`intrinsic_value: 34,986`). 그 숫자가
얼마나 믿을 만한지는 `valuation_sandbox` 의 5×5 격자와 `football_field` 의
Bear/Base/Bull 로 **그림**으로만 있다. 이 모듈은 그것을 **확률 진술**로 바꾼다 —
P10/P25/P50/P75/P90 과 **현재 주가가 그 분포의 몇 분위인지.**

★새 밸류에이션 모델을 짓지 않는다★ 같은 `compute_rim`/`compute_dcf`/`compute_ddm` 을
파라미터 분포로 감쌀 뿐이다. 가중평균은 `weighted_intrinsic` 한 벌을 쓴다.

★실측이 설계를 바꾼 것 — 모델 불일치가 파라미터 불확실성보다 크다★
──────────────────────────────────────────────────────────────────────────────
mock 삼성전자에서 rf±1%p × g±1%p 격자를 돌려 본 결과:

  · **파라미터** 불확실성 → 통합값 30,401 ~ 41,913 (**±16%**)
  · **모델 불일치**       → 같은 파라미터에서 RIM 57,152 / DCF 20,596 / DDM 19,432 (**약 3배**)

통합값 하나의 P10~P90 만 내면 **3배짜리 모델 불일치가 통째로 사라진다** — 평균이
그것을 지워 버리기 때문이다. 그래서 모델별 분포를 함께 내고 모델 불일치를 따로
보고한다. P2.5 의 `target_weight_range` 에서 "평균으로 접지 않는다" 와 같은 원칙이다.

DCF 가 모델 중 가장 민감한 것도 실측이다(rf±1%p 에서 13,949~31,563, 약 2.3배 — RIM 은
±6%). `dominant_driver` 가 "왜 이렇게 넓은가" 에 답한다.

★그리고 그 지배 파라미터가 **β** 다 — 우리가 폭을 지어낸 바로 그것★
실측(±1σ 일변량 충격): β **6,025** > erp 4,504 > rf 4,468 > g 2,225.
계획할 때는 rf 가 가장 클 것으로 봤는데 아니었다. β 의 σ=0.15 가 ke 를 0.9%p 움직여
rf 와 맞먹는데, **β 의 폭만은 저장소 어디에도 근거가 없다**(아래 참조). 즉 분포를
가장 넓히는 것이 우리가 가장 모르는 값이다 — 그래서 `dominant_driver` 와
`widths[*].measured` 를 **함께** 읽어야 한다.

★분포의 폭을 발명하지 않는다 — 그리고 **측정된 폭은 하나도 없다**★
──────────────────────────────────────────────────────────────────────────────
`company_analytics` 는 이미 파라미터 불확실성을 숫자로 선언해 두었다:
`_KE_STEPS`/`_G_STEPS = ±0.010`(민감도 격자가 탐색하는 범위)와 `football_field` 의
Bear/Bull(`g ±0.01`·`erp ∓0.01`). 그 ±1%p 를 **90% 구간의 반폭**으로 읽는다. 그러면
분포가 격자·풋볼필드와 같은 불확실성을 말하고, 누가 `_KE_STEPS` 를 넓히면 분포도
함께 넓어진다.

**그러나 그 ±1%p 자체가 측정치가 아니다.** 누군가 고른 탐색 범위다. β 는 더하다 —
`PriceFactorsStore._beta`(`:314`)는 `cov/var` 점추정만 돌려주고 **표준오차를 노출하지
않으므로** 폭이 순수한 가정이다. 그래서 네 폭 **전부** `measured: false` 로 나간다.
처음에는 β 만 그렇게 표시하려 했는데, 그러면 나머지 셋이 측정된 것처럼 읽힌다.

★일변량 격자는 결합 불확실성을 **과소평가**한다★ 격자는 한 번에 하나씩 흔들지만
여기서는 넷을 동시에 뽑으므로 유도된 ke 산포가 격자의 ±1%p 보다 넓다. 그것이 옳고,
`induced_ke` 로 그 사실을 눈에 보이게 남긴다.

★기각하되 조이지 않는다★ `g ≥ ke − _TV_GAP` 이면 TV 가 발산한다 —
`valuation_sandbox` 가 이미 그 칸을 `None` 으로 두는 그 조건이고 **같은 상수를
재사용**한다. 위반 표본은 버리고 그 수를 보고한다. 경계로 클램프하면 경계에 질량이
쌓여 분포가 인위적으로 좁아진다 — 설계 문서가 금지하는 "폭을 축소해 보이게 하는 것"
이 정확히 그 형태다.
"""
from __future__ import annotations

import logging

import numpy as np

from src.engine.valuation.valuation_models import (
    ValuationParams,
    compute_dcf,
    compute_ddm,
    compute_rim,
    weighted_intrinsic,
)

logger = logging.getLogger(__name__)

# 고정 시드 — 같은 입력이면 같은 분포가 나와야 한다(저장소 관례:
# `regime_transitions.SEED` · `allocation_routes` 의 `default_rng(42)`).
SEED = 20260822
DEFAULT_N = 2000
MAX_N = 20000

# 90% 양측 구간의 z — ±1%p 를 90% 반폭으로 읽는 환산 계수.
_Z90 = 1.6448536269514722

# ★저장소가 폭을 말한 적 없는 유일한 파라미터★ 1년 일간 베타(관측 ~252)의 표준오차는
# 통상 0.1~0.15 이지만 `_beta` 가 그것을 돌려주지 않으므로 **가정**이다.
BETA_SIGMA = 0.15

# rf 와 g 는 둘 다 **명목**이라 같이 움직인다(설계 문서: "상관을 무시하지 않는다").
# 이 값도 측정치가 아니라 가정이다.
RF_G_CORR = 0.5

# 유효 표본이 요청의 이 비율 미만이면 분위수를 내지 않는다 — 40개에서 뽑은 P10 은
# 분위수가 아니라 잡음이다.
_MIN_VALID_RATIO = 0.25

_PCTS = (10, 25, 50, 75, 90)
_MODELS = ("RIM", "DCF", "DDM")


def _unavailable(reason: str, **extra) -> dict:
    out = {
        "available": False, "method": "monte_carlo_parameters", "seed": None,
        "n_requested": None, "n_used": 0, "n_rejected": 0, "rejections": {},
        "unified": None, "by_model": None, "model_disagreement": None,
        "widths": None, "induced_ke": None, "dominant_driver": None,
        "reason": reason,
    }
    out.update(extra)
    return out


def repo_widths() -> dict:
    """★폭을 발명하지 않는다★ `company_analytics` 가 이미 선언한 범위를 읽는다.

    ★그리고 **어느 것도 측정치가 아니다**★ `_KE_STEPS` 는 누군가 고른 탐색 범위이지
    추정 표준오차가 아니다. 네 항목 전부 `measured: false` 로 나가는 것이 정확하다 —
    β 만 표시하면 나머지 셋이 측정된 것처럼 읽힌다.
    """
    from src.engine.company_analytics import _G_STEPS, _KE_STEPS

    ke_half = max(abs(s) for s in _KE_STEPS)
    g_half = max(abs(s) for s in _G_STEPS)
    # football_field 의 Bear/Bull 이 erp 를 ∓1%p 흔든다 — 같은 크기를 쓴다.
    erp_half = 0.01
    return {
        "rf": {"sigma": ke_half / _Z90, "half_width_90": ke_half, "measured": False,
               "source": "company_analytics._KE_STEPS — 민감도 격자가 탐색하는 범위"},
        "g": {"sigma": g_half / _Z90, "half_width_90": g_half, "measured": False,
              "source": "company_analytics._G_STEPS — 민감도 격자가 탐색하는 범위"},
        "erp": {"sigma": erp_half / _Z90, "half_width_90": erp_half, "measured": False,
                "source": "company_analytics.football_field 의 Bear/Bull 시나리오 폭"},
        "beta": {"sigma": BETA_SIGMA, "half_width_90": BETA_SIGMA * _Z90,
                 "measured": False,
                 "source": ("가정 — PriceFactorsStore._beta 는 cov/var 점추정만 주고 "
                            "회귀 표준오차를 노출하지 않는다")},
        "rf_g_correlation": {"value": RF_G_CORR, "measured": False,
                             "source": "가정 — rf 와 g 는 둘 다 명목이라 같이 움직인다"},
        "note": ("★이 폭 중 측정된 것은 하나도 없다★ 저장소가 이미 선언한 탐색 범위를 "
                 "90% 반폭으로 읽은 것이고, β 와 상관계수는 순수한 가정이다. "
                 "분포의 절대 폭이 아니라 **모델 간 불일치와의 상대 크기**를 보십시오."),
    }


def _models_for(fs, params: ValuationParams) -> list:
    return [compute_rim(fs, params), compute_dcf(fs, params), compute_ddm(fs, params)]


def _summary(values: np.ndarray, price: float | None = None) -> dict:
    if values.size == 0:
        return {"available": False, "reason": "유효한 표본이 없습니다", "n": 0}
    q = np.percentile(values, _PCTS)
    out = {
        "available": True, "n": int(values.size),
        **{f"p{p}": round(float(v), 0) for p, v in zip(_PCTS, q)},
        "mean": round(float(values.mean()), 0),
    }
    if price is not None and price > 0:
        # ★현재 주가가 이 분포의 몇 분위인가★ football field 를 그림에서 확률
        # 진술로 바꾸는 한 줄이다.
        out["price_percentile"] = round(
            float((values <= float(price)).mean() * 100.0), 1)
    return out


def _dominant_driver(fs, base: ValuationParams, widths: dict) -> dict:
    """어느 파라미터가 산포를 지배하는가 — 하나씩 ±1σ 로 흔들어 잰다.

    "왜 이렇게 넓은가" 에 답하는 필드다. ★실측에서는 β 가 가장 컸다(6,025 >
    erp 4,504 > rf 4,468 > g 2,225)★ — 그리고 β 는 폭이 **가정**인 유일한 항목이다.
    지배 파라미터와 `widths[*].measured` 를 함께 읽어야 하는 이유다.
    """
    spreads: dict[str, float] = {}
    for key in ("rf", "g", "erp", "beta"):
        sigma = float(widths[key]["sigma"])
        vals = []
        for sign in (-1.0, 1.0):
            kw = {"risk_free_rate": base.risk_free_rate, "market_premium": base.market_premium,
                  "beta": base.beta, "terminal_growth_rate": base.terminal_growth_rate,
                  "projection_years": base.projection_years}
            field = {"rf": "risk_free_rate", "g": "terminal_growth_rate",
                     "erp": "market_premium", "beta": "beta"}[key]
            kw[field] = kw[field] + sign * sigma
            if kw["terminal_growth_rate"] < 0 or kw["beta"] <= 0:
                continue
            p = ValuationParams(**kw)
            vals.append(weighted_intrinsic(_models_for(fs, p), p))
        spreads[key] = (max(vals) - min(vals)) if len(vals) == 2 else 0.0
    if not any(spreads.values()):
        return {"available": False, "reason": "±1σ 충격에서 값이 움직이지 않습니다"}
    top = max(spreads, key=lambda k: spreads[k])
    return {
        "available": True, "driver": top,
        "spread_by_param": {k: round(v, 0) for k, v in spreads.items()},
        "note": "각 파라미터를 홀로 ±1σ 흔들었을 때의 통합값 폭입니다(일변량).",
    }


def valuation_distribution(fs, base_params: ValuationParams | None = None,
                           current_price: float | None = None, *,
                           n: int = DEFAULT_N, seed: int = SEED,
                           widths: dict | None = None) -> dict:
    """파라미터 분포 → 적정가 분포. 순수 함수 — I/O 0.

    Args:
        fs: **평가 준비가 끝난** FinancialStatement (`load_statement` 의 결과).
        base_params: 분포의 중심.
        current_price: 있으면 `price_percentile` 을 함께 낸다.
        n: 표본 수. 실측 0.063 ms/표본이므로 2,000 이 ~126 ms 다.
        widths: 없으면 `repo_widths()`.
    """
    from src.engine.company_analytics import _TV_GAP

    if fs is None:
        return _unavailable("재무제표가 없습니다")
    n = max(1, min(int(n), MAX_N))
    base = base_params or ValuationParams()
    w = widths or repo_widths()

    base_models = _models_for(fs, base)
    if not any(m.available and m.intrinsic_value_per_share > 0 for m in base_models):
        return _unavailable(
            "기본 가정에서 어떤 모델도 적정가를 내지 못해 분포를 만들 수 없습니다",
            widths=w, seed=seed, n_requested=n)

    s_rf = float(w["rf"]["sigma"])
    s_g = float(w["g"]["sigma"])
    s_erp = float(w["erp"]["sigma"])
    s_beta = float(w["beta"]["sigma"])
    rho = float(w["rf_g_correlation"]["value"])

    rng = np.random.default_rng(seed)
    cov = [[s_rf ** 2, rho * s_rf * s_g], [rho * s_rf * s_g, s_g ** 2]]
    rf_g = rng.multivariate_normal([base.risk_free_rate, base.terminal_growth_rate],
                                   cov, size=n)
    erps = rng.normal(base.market_premium, s_erp, n)
    betas = rng.normal(base.beta, s_beta, n)

    rejections = {"negative_input": 0, "terminal_growth_above_ke": 0, "model_unavailable": 0}
    unified: list[float] = []
    per_model: dict[str, list[float]] = {m: [] for m in _MODELS}
    kes: list[float] = []

    for i in range(n):
        rf, g = float(rf_g[i, 0]), float(rf_g[i, 1])
        erp, beta = float(erps[i]), float(betas[i])
        if rf < 0 or g < 0 or erp < 0 or beta <= 0:
            rejections["negative_input"] += 1
            continue
        ke = rf + beta * erp
        # ★클램프가 아니라 기각★ 경계로 밀어 넣으면 경계에 질량이 쌓여 분포가
        # 인위적으로 좁아진다. `valuation_sandbox` 가 같은 조건의 칸을 None 으로
        # 두는 것과 같은 판단이다.
        if g >= ke - _TV_GAP:
            rejections["terminal_growth_above_ke"] += 1
            continue

        p = ValuationParams(risk_free_rate=rf, market_premium=erp, beta=beta,
                            terminal_growth_rate=g,
                            projection_years=base.projection_years)
        models = _models_for(fs, p)
        v = weighted_intrinsic(models, p)
        if v <= 0:
            rejections["model_unavailable"] += 1
            continue
        unified.append(v)
        kes.append(ke)
        for m in models:
            if m.available and m.intrinsic_value_per_share > 0:
                per_model[m.model].append(float(m.intrinsic_value_per_share))

    n_used = len(unified)
    n_rejected = n - n_used
    if n_used < max(1, int(n * _MIN_VALID_RATIO)):
        return _unavailable(
            f"유효 표본이 {n_used}개뿐이라({n}개 중) 분위수를 낼 수 없습니다 — "
            "적은 표본에서 뽑은 P10 은 분위수가 아니라 잡음입니다.",
            widths=w, seed=seed, n_requested=n, n_used=n_used,
            n_rejected=n_rejected, rejections=rejections)

    arr = np.asarray(unified, dtype=float)
    ke_arr = np.asarray(kes, dtype=float)

    # ★모델별 분포를 통합에 접지 않는다★ 실측상 모델 불일치가 파라미터 불확실성보다
    # 크므로, 통합값만 내면 더 큰 쪽이 사라진다.
    by_model = {m: _summary(np.asarray(per_model[m], dtype=float)) for m in _MODELS}
    base_vals = {m.model: float(m.intrinsic_value_per_share) for m in base_models
                 if m.available and m.intrinsic_value_per_share > 0}
    disagreement = {
        "at_base": {k: round(v, 0) for k, v in base_vals.items()},
        "spread_ratio": (round(max(base_vals.values()) / min(base_vals.values()), 2)
                         if len(base_vals) >= 2 and min(base_vals.values()) > 0 else None),
        "note": ("같은 파라미터에서 모델들이 얼마나 갈리는가. 이 비율이 통합 분포의 "
                 "폭보다 크면, 불확실성의 주된 출처는 파라미터가 아니라 **모델 선택**이다."),
    }

    return {
        "available": True,
        "method": "monte_carlo_parameters",
        "seed": seed,
        "n_requested": n,
        "n_used": n_used,
        "n_rejected": n_rejected,
        "rejections": rejections,
        "unified": _summary(arr, current_price),
        "by_model": by_model,
        "model_disagreement": disagreement,
        "widths": w,
        # ★일변량 격자는 결합 불확실성을 과소평가한다★ 유도된 ke 산포를 남겨 그 차이가
        # 눈에 보이게 한다.
        "induced_ke": {
            "p10": round(float(np.percentile(ke_arr, 10)) * 100, 3),
            "p90": round(float(np.percentile(ke_arr, 90)) * 100, 3),
            "base_pct": round((base.risk_free_rate + base.beta * base.market_premium) * 100, 3),
            "note": ("넷을 동시에 뽑으므로 유도된 ke 폭이 민감도 격자의 ±1%p 보다 "
                     "넓습니다 — 격자는 한 번에 하나씩만 흔들기 때문입니다."),
        },
        "dominant_driver": _dominant_driver(fs, base, w),
        "reason": None,
        "note": ("파라미터 불확실성만 반영한 분포입니다. 재무 자체의 오차·모델 설정 "
                 "위험은 포함되지 않으며, 폭 중 측정된 것은 하나도 없습니다."),
    }


#: ★as-of 로 바뀌는 것은 재무뿐이다★ 나머지가 오늘 값이라는 사실을 **이름으로**
#: 밝힌다 — 재무만 시점 정합으로 바꾸고 나머지를 말하지 않으면 "as-of 뷰" 라는
#: 이름이 거짓이 된다. 0단계의 `price_basis`·`universe` 와 같은 규율이고,
#: 화면과 뷰가 **같은 상수**를 보게 해 두 벌이 갈라지지 않게 한다.
AS_OF_INPUTS = {
    "financials": "vintage",    # `financials_vintages` 의 그 시점 최신 연간 빈티지
    "price": "caller",          # 호출자가 준 값 — 이 층은 그것이 언제 값인지 모른다
    "params": "today",          # rf · erp · beta · terminal growth (오늘 기준)
    "market_cap": "today",      # 시가총액 (오늘 기준)
}


def valuation_distribution_for(code: str, current_price: float, *,
                               n: int = DEFAULT_N, seed: int = SEED,
                               as_of: str | None = None) -> dict:
    """종목 코드로 분포. `load_statement` 를 타므로 **mock 게이트를 공짜로 받는다.**

    ★`as_of` 를 주면 재무만 **그 시점 빈티지**로 바꾼다★
    (`dart_history.statement_as_of`). 그 경로는 **DB 빈티지만** 읽으므로 합성이
    끼어들 자리가 없다 — `load_statement` 의 mock 게이트가 막던 "운영에서 DART
    실패 시 합성 재무로 조용히 폴백" 이 구조적으로 불가능하다. ★새 폴백을 만들지
    않는다★: 빈티지가 없으면 사유와 함께 `available:false` 다.

    ★오늘 표(`financials_history`)로 되돌아가지 않는다★ 그 표는 정정이 원본을
    덮은 결과라 as-of 를 답할 수 없다.
    """
    from src.data.dart_client import DARTClient
    from src.engine.company_analytics import _mcap, resolve_default_params
    from src.engine.valuation.valuation_models import ValuationEngine

    d = resolve_default_params(code)
    base = ValuationParams(risk_free_rate=d["rf"], market_premium=d["erp"],
                           beta=d["beta"], terminal_growth_rate=d["g"],
                           projection_years=int(d["years"]))

    if as_of:
        from src.data import dart_history as dh
        fs, why = dh.statement_as_of(str(code), str(as_of))
        if fs is None:
            # ★사유를 뭉개지 않는다★ 못 읽음·빈티지 없음·연간 없음이 그대로 올라간다.
            return _unavailable(why or "as-of 재무를 만들지 못했습니다")
        # ★손질을 복제하지 않고 같은 것을 부른다★ 이것을 빠뜨렸더니 `eps`·`bps` 가
        # 비어 정정 전/후 재무가 달라도 적정가가 한 자리도 안 바뀌었다(실측).
        ValuationEngine.prepare_statement(fs, current_price, market_cap=_mcap(code))
        from src.data.stock_master import get_stock_name
        loaded = {"fs": fs, "corp_name": get_stock_name(code) or str(code),
                  "is_mock": False}
    else:
        loaded = ValuationEngine(DARTClient()).load_statement(
            code, current_price, market_cap=_mcap(code))
        if not loaded["available"]:
            return _unavailable(loaded["reason"] or "재무제표를 가져오지 못했습니다")

    out = valuation_distribution(loaded["fs"], base, current_price, n=n, seed=seed)
    out["code"] = str(code)
    out["corp_name"] = loaded["corp_name"]
    out["is_mock"] = loaded["is_mock"]
    out["base_assumptions"] = d
    if as_of:
        out["as_of"] = str(as_of)
        out["as_of_inputs"] = dict(AS_OF_INPUTS)
    return out
