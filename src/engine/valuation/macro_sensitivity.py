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
