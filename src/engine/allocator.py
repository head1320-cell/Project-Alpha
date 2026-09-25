"""전략 배분기 — ★새로 짜지 않는다, 이미 있는 계산을 쓴다★ (BG2 · R2 복원)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-24-multistrategy-restore-r1-r3-design.md` §4.2 ·
소비자 `multi_strategy_backtest` · `RegimeAdaptiveAllocator`(realism) ·
재사용 `allocation_studio._inverse_vol_w` · `risk_allocations._hrp_weights` ·
`RegimeAdaptiveAllocator._cap_and_redistribute`

## 왜 이 모듈이 생겼나

`multi_strategy_backtest` 는 2026-06-10 스냅샷 이식 때부터 이 모듈을 import 했는데
저장소에 한 번도 없었다(BF). 시그니처는 엔진과 `RegimeAdaptiveAllocator` 가 이미 쓰는
그대로다 — 호출부를 바꾸지 않는다.

## ★이 모듈이 하지 않는 것★

- **`hrp_macro` 를 하지 않는다** — 매크로 기울기는 배분 정책이고 국면 분류기가 R4 다.
  `available: False` + 사유를 낸다.
- **조용히 실패하지 않는다** — 표본 부족·변동성 0·불가능한 하한은 `available:
  False` + 사유. ★엔진은 이것을 말없이 삼키고 직전 가중을 쓰므로★ 문이 따로 막는다.
- **상한을 재정규화하지 않는다**(B2) — 여유가 없으면 남는 몫은 현금이다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: 공분산을 추정하기 위한 최소 관측 수.
MIN_OBS = 20

METHODS = ("inverse_vol", "hrp")

_MACRO_REASON = ("hrp_macro 는 매크로 국면 기울기를 얹는 배분 정책인데 국면 분류기"
                 "(regime_model)·매크로 피드(macro_feed)가 아직 없습니다 — R4 에서 "
                 "별도 승인 후 다룹니다.")


def _unavailable(method: str, reason: str, **extra) -> dict:
    return {"available": False, "reason": reason, "method": method,
            "weights": {}, "base_weights": {}, "macro_adjustments": {},
            "regime": None, **extra}


def _apply_floor(w: dict, floor: float) -> dict:
    """하한 — 하한 미만을 올리고 그만큼 하한 위 전략에서 **비중 비례로** 덜어낸다."""
    w = dict(w)
    for _ in range(50):
        low = [c for c in w if w[c] < floor - 1e-12]
        if not low:
            break
        need = sum(floor - w[c] for c in low)
        for c in low:
            w[c] = floor
        high = [c for c in w if c not in low and w[c] > floor + 1e-12]
        pool = sum(w[c] - floor for c in high)
        if pool <= 1e-12:
            break
        for c in high:
            w[c] -= need * (w[c] - floor) / pool
    return w


class MultiStrategyAllocator:
    """전략 수익률 행렬 → 전략 비중."""

    def __init__(self, db_engine=None):
        self.engine = db_engine

    def compute(self, returns_matrix: pd.DataFrame, method: str = "hrp",
                strategies: list | None = None, as_of_date: str | None = None,
                lookback_days: int = 252, max_weight: float = 0.50,
                min_weight: float = 0.02) -> dict:
        """엔진·`RegimeAdaptiveAllocator` 가 이미 쓰는 시그니처 그대로."""
        if method == "hrp_macro":
            return _unavailable(method, _MACRO_REASON)
        if method not in METHODS:
            return _unavailable(method, f"알 수 없는 배분 방법 '{method}' — "
                                        f"가능한 것: {', '.join(METHODS)}")
        R = returns_matrix.tail(int(lookback_days)).dropna(how="any")
        cols = [int(c) for c in R.columns]
        n_obs = len(R)
        if n_obs < MIN_OBS:
            return _unavailable(method, f"관측이 {n_obs}개로 {MIN_OBS}개 미만이라 공분산을 "
                                        "추정할 수 없습니다.", n_obs=n_obs)
        if not cols:
            return _unavailable(method, "전략이 없습니다.", n_obs=n_obs)
        if min_weight * len(cols) > 1.0 + 1e-9:
            return _unavailable(method, f"min_weight {min_weight} × 전략 {len(cols)}개가 "
                                        "1 을 넘어 하한을 지킬 수 없습니다.", n_obs=n_obs)
        vals = R.values.astype(float)
        vol = vals.std(axis=0)
        flat = [cols[i] for i, v in enumerate(vol) if not np.isfinite(v) or v <= 1e-12]
        if flat:
            return _unavailable(method, f"변동성이 0 인 전략 {flat} — 역변동성·HRP 가 그 "
                                        "전략에 거의 전부를 줍니다. 가중을 지어내지 않습니다.",
                                n_obs=n_obs)

        if len(cols) == 1:
            raw = np.array([1.0])
        elif method == "inverse_vol":
            from src.engine.allocation_studio import _inverse_vol_w
            raw = _inverse_vol_w(vals)
        else:
            from src.engine.risk_allocations import _hrp_weights
            raw = _hrp_weights(np.cov(vals, rowvar=False))
            raw = raw / raw.sum()
        if not np.all(np.isfinite(raw)):
            return _unavailable(method, "가중 계산이 유한한 값을 내지 못했습니다.", n_obs=n_obs)

        w = {c: float(v) for c, v in zip(cols, raw)}
        if min_weight > 0:
            w = _apply_floor(w, float(min_weight))
        from src.engine.regime_adaptive_allocator import RegimeAdaptiveAllocator
        w, moved, binding = RegimeAdaptiveAllocator._cap_and_redistribute(
            w, float(max_weight))
        invested = sum(w.values())
        return {
            "available": True, "method": method, "weights": w,
            "base_weights": dict(w),
            # ★매크로가 없는 방법이라 구조적으로 0★ — 미상이 아니다.
            "macro_adjustments": {},
            "regime": None, "n_obs": n_obs,
            "cap_binding": binding, "cap_moved": round(moved, 10),
            # ★재정규화하지 않는다(B2)★ — 상한 때문에 못 넣은 몫은 현금이다.
            "cash_weight": round(max(0.0, 1.0 - invested), 10),
            "as_of_date": as_of_date,
        }
