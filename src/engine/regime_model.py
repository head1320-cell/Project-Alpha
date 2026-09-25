"""백테스트 국면 — ★새 분류기를 짜지 않는다, 엄격 PIT, KR·US 둘 다★ (BH3 · R4-a)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-bh-safety-attribution-regime-design.md` §4.3 ·
판정 `src/engine/regime_axes.py`(단일 정의) · 재료 `src/data/pit_macro.series_as_of`
(빈티지 스토어, 공표 ≤ as_of) · 소비자 `multi_strategy_backtest` · `realism_engine`

## 왜 이 모듈이 생겼나

`multi_strategy_backtest` 는 2026-06-10 스냅샷 이식 때부터 `MultiRegimeModel` 을 import
했는데 저장소에 없었다(BF). 저장소에는 이미 국면 축의 단일 정의(`regime_axes` —
성장×물가 z, 사분면, 사분면 확률)가 있다. ★그것을 쓴다★ — 두 번째 분류기를 만들면
헤더 배지와 백테스트가 다른 국면을 말하게 된다.

## ★엄격 PIT★

`classify_at(as_of, market)` 은 각 계열을 `series_as_of(key, as_of)` 로 읽는다 — **그
시점에 공표된 빈티지만**. 결정일 t 의 라벨은 **전날까지** 공표분으로 만든다(`panel`).
빈티지가 없는 계열은 없는 것이다 — 현재 개정값으로 과거를 채우지 않는다.

## ★시장별 하드코딩이 없다★ (사용자 결정)

KR 계열(ECOS)은 지금 빈티지가 없어 KR 국면은 대부분 미상이다. 그러나 여기에는 KR 을 막는
코드가 없다 — 사용자가 KR 데이터를 빈티지와 함께 적재하면 **코드 변경 없이** KR 라벨이
나온다. 가용성은 선언이 아니라 스토어의 실제 행이 정한다.

## ★이 모듈이 하지 않는 것★

- **`systemic_risk_score` 를 만들지 않는다** — 킬스위치 `auto_risk` 의 재료이고(실거래
  안전), `stress_score` 를 그 이름으로 부르는 것은 금지돼 있다. 항상 `None` + 사유.
- **`hrp_macro` 의 기울기를 만들지 않는다** — 배분 정책이고 사용자가 계속 거절하기로 했다.
- **"데이터 부족" 을 라벨로 쓰지 않는다** — 미상은 `regime=None` + 사유다.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from src.engine.regime_axes import (
    AXES,
    QUADRANTS,
    compute_axis_detail,
    quadrant,
    quadrant_probs,
)

#: 라벨을 붙이려면 두 축 모두 성분 ≥ 1, 합계 ≥ 3 — 분석기(`regime_analyzer`)의
#: `real_count < 3 → 데이터 부족` 과 같은 문턱이다.
MIN_COMPONENTS = 3

SYSTEMIC_RISK_REASON = (
    "systemic_risk_score 는 생산하지 않습니다 — 킬스위치 auto_risk 의 재료라 실거래 안전 "
    "경로이고(별도 승인), stress_score 를 이 이름으로 부르는 것은 금지돼 있습니다.")

Loader = Callable[[str, str], Any]


class _Series:
    """`compute_axis_detail` 이 읽는 모양(`.values`) — 스토어의 값 목록을 그대로 싣는다."""

    def __init__(self, values):
        self.values = list(values)


def _default_loader(engine=None) -> Loader:
    from src.data.pit_macro import series_as_of

    def load(key: str, as_of: str):
        return series_as_of(key, as_of, engine=engine)
    return load


class MultiRegimeModel:
    """시장별 성장×물가 사분면을 **그 시점에 알 수 있던 것**으로 판정한다."""

    @staticmethod
    def classify_at(as_of: str, market: str, *, series_loader: Loader | None = None,
                    engine=None) -> dict:
        if market not in AXES:
            raise ValueError(f"알 수 없는 시장 '{market}' — 가능한 것: {', '.join(AXES)}")
        load = series_loader or _default_loader(engine)
        as_of = str(as_of)[:10]
        g_def, i_def = AXES[market]
        keys = list(dict.fromkeys(k for k, *_ in (*g_def, *i_def)))

        series_map: dict[str, _Series] = {}
        absent: list[str] = []
        for key in keys:
            got = load(key, as_of)
            if got and got[1]:
                series_map[key] = _Series(got[1])
            else:
                absent.append(key)

        g = compute_axis_detail(series_map, g_def)
        i = compute_axis_detail(series_map, i_def)
        n_g, n_i = len(g["components"]), len(i["components"])
        known = n_g >= 1 and n_i >= 1 and (n_g + n_i) >= MIN_COMPONENTS

        if known:
            regime = quadrant(g["score"], i["score"])
            probs = quadrant_probs(g["score"], i["score"], g["se"], i["se"])
            reason = None
        else:
            regime, probs = None, None
            short = [k for k, *_ in (*g_def, *i_def)
                     if k not in {c["key"] for c in (*g["components"], *i["components"])}]
            reason = (f"{market.upper()} 국면을 판정할 재료가 부족합니다 — 성장 성분 {n_g} · "
                      f"물가 성분 {n_i}(두 축 모두 ≥1, 합계 ≥{MIN_COMPONENTS} 필요). "
                      f"{as_of} 에 공표된 빈티지가 없거나 이력이 짧은 계열: "
                      f"{', '.join(dict.fromkeys(short))}")
        return {
            "regime": regime, "market": market, "as_of": as_of,
            "growth_signal": g["score"] if known else None,
            "inflation_signal": i["score"] if known else None,
            "probs": probs,
            "n_components": n_g + n_i,
            "series_used": sorted(series_map),
            "reason": reason,
            "systemic_risk_score": None,
            "systemic_risk_reason": SYSTEMIC_RISK_REASON,
        }

    @staticmethod
    def panel(trading_days, markets=("kr", "us"), *,
              series_loader: Loader | None = None, engine=None) -> dict[str, dict]:
        """거래일 → 판정. ★결정일의 라벨은 전날까지 공표분으로★

        월마다 한 번, **그 달 첫 거래일의 전날**을 as-of 로 판정해 그 달 거래일에 앞으로
        채운다. 라벨은 "그 시점까지 알 수 있던 것" 이라 앞채움이 룩어헤드가 아니다
        (월중 공표분은 다음 달 첫 거래일부터 반영된다 — 보수적 지연).
        """
        days = [pd.Timestamp(d) for d in trading_days]
        out: dict[str, dict] = {}
        for m in markets:
            calls: dict = {}
            by_month: dict = {}
            for d in days:
                key = (d.year, d.month)
                if key not in by_month:
                    as_of = (d - pd.Timedelta(days=1)).date().isoformat()
                    by_month[key] = MultiRegimeModel.classify_at(
                        as_of, m, series_loader=series_loader, engine=engine)
                calls[d] = by_month[key]
            out[m] = calls
        return out


__all__ = ["MultiRegimeModel", "QUADRANTS", "MIN_COMPONENTS"]
