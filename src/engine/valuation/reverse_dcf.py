"""역DCF — 시장은 무엇을 믿고 있는가 (P2-2)

`compute_dcf` 는 **가정 → 내재가치**다. 이 모듈은 그 반대다 — **현재 주가를
정당화하려면 어떤 가정이 필요한가.**

이것이 언더라이팅의 출발점이다. "적정가 83,000원" 은 우리 가정의 결과일 뿐이지만,
"시장은 향후 10년 FCF 연 11.3% 성장을 믿고 있다" 는 **반증 가능한 명제**이고, 그
숫자가 우리 가정과 얼마나 벌어져 있는지가 곧 논지다.

★새 모델을 짓지 않는다★
`compute_dcf` 는 이미 `fcf_growth_rates: list[float] | None` 을 인자로 받는다
(`valuation_models.py:216-219`). 역DCF 는 **그 함수의 역함수**이고 1차원 근 찾기
하나면 된다. 밸류에이션 엔진은 한 줄도 고치지 않았다.

★설계 문서 §2 의 불연속 주장을 격자로 재서 정정했다★
──────────────────────────────────────────────────────────────────────────────
설계 문서는 "`wacc = max(wacc, 0.03)` 클램프와 `(wacc - g) > 0.001` 가드가 만드는
불연속이 실재한다" 고 적었다. **FCF 성장률을 미지수로 두면 그 둘은 불연속을 만들지
않는다** — 코드로도 격자 실측으로도 확인했다:

  · `wacc` 는 `params.ke`·자본구조·`tax_rate` 에서만 나온다. `fcf_growth_rates` 가
    들어가지 않는다 → 미지수에 대해 **상수**(실측: g=-0.30 과 g=+0.40 에서 둘 다 8.27%)
  · `(wacc - g) > 0.001` 의 `g` 는 `params.terminal_growth_rate` → **역시 상수**(2.0%)

**진짜 불연속은 셋이고, 셋 다 실측으로 확인했다**(mock 삼성전자, 가격 71,000원):

  1. `per_share = max(0, equity_value/shares)` — **g ≤ -0.125 에서 0 으로 평평**하다.
  2. `round(per_share, 0)` — 반환값이 원 단위 **계단함수**다. 실측 계단 폭은
     Δg ≈ 1.7e-6 당 1원. 그래서 허용오차를 **가격이 아니라 성장률**에 걸고(`xtol`),
     달성된 내재가와 시장가의 격차를 함께 보고한다. "정확히 풀었다" 고 말하지 않는다.
  3. `fcf_base <= 0 or shares <= 0` → 모든 g 에서 `available=False`.
     **근이 아예 존재하지 않는다.** ★적자·마이너스 FCF 기업이 정확히 여기다★
     (CLAUDE.md: 적자기업 실데이터에서만 터지고 mock 은 항상 흑자다.)

`(wacc - g) > 0.001` 은 **두 번째 축**(영구성장률을 미지수로 둘 때) 진짜 절벽이 된다 —
TV 가 통째로 0 으로 떨어진다. 그 축의 브래킷 상한이 `wacc` 아래에 있는 근거다.

★시장내재 '마진' 은 이 함수로 낼 수 없다★
`compute_dcf` 는 FCF 를 **수준**으로 받지 매출×마진으로 받지 않는다 — 매출과의 연결이
함수 안에 없다. 진짜 내재 마진은 매출 구동 DCF 라는 **새 모델**을 요구하고 이 슬라이스는
그것을 하지 않는다. 대신 이미 푼 해에서 파생되는 것만 낸다: FCF 궤적(새 가정 0)과,
**오늘 매출을 고정했을 때**의 비율을 `assumes_flat_revenue` 라벨과 **함께만**.
라벨 없이 "내재 마진" 이라고 부르면 그것이 조용한 날조다.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from src.engine.valuation.valuation_models import ValuationParams, compute_dcf

logger = logging.getLogger(__name__)

try:
    from scipy.optimize import brentq as _brentq
    _HAS_BRENTQ = True
except Exception:  # pragma: no cover - scipy 부재 환경
    _HAS_BRENTQ = False

# 실측 계단 폭이 Δg ≈ 1.7e-6 당 1원이므로, 1e-7 이면 가격 해상도가 1원 아래다.
XTOL = 1e-7
# ★브래킷 하한은 -1 보다 위여야 한다★ (1+g) 가 0 이하가 되면 FCF 궤적이 부호를 뒤집어
# 의미를 잃는다. 분수승·로그가 음수를 받는 자리를 브래킷 자체로 막는다.
_G_FLOOR = -0.99
DEFAULT_BRACKET = (-0.50, 0.50)
DEFAULT_GRID = 25


def _unavailable(reason: str, **extra) -> dict:
    out = {
        "available": False, "method": "reverse_dcf_constant_growth",
        "implied_growth_pct": None, "current_growth_pct": None, "gap_pp": None,
        "implied_terminal_growth_pct": None, "implied_fcf_path": None,
        "implied_fcf_margin_pct": None, "achieved_price": None,
        "price_gap_won": None, "monotonic": None, "bracket": None,
        "reason": reason,
    }
    out.update(extra)
    return out


def _per_share(fs, params: ValuationParams, g: float) -> float | None:
    """상수 성장률 `g` 를 넣었을 때의 DCF 주당가치. 산출 불가면 `None`."""
    r = compute_dcf(fs, params, fcf_growth_rates=[g] * params.projection_years)
    if not r.available:
        return None
    return float(r.intrinsic_value_per_share)


def _solve(f, target: float, bracket: tuple[float, float], grid: int,
           label: str) -> dict:
    """`f(x) == target` 을 푼다 — ★단조성을 가정하지 않고 잰다★

    brentq 는 부호변화만 요구한다. 단조가 아닌 함수에서 나온 근은 "시장이 믿는
    **유일한** 값" 이 아니므로, 격자에서 **비감소**를 먼저 확인한다(계단함수라
    국소적으로 평평할 수 있으므로 '증가' 가 아니라 '비감소').

    근이 없으면 빈 답이 아니라 **어느 쪽으로 벗어났는지**를 돌려준다 — 그 방향이
    언더라이팅의 정보다.
    """
    lo, hi = bracket
    xs = [lo + (hi - lo) * i / (grid - 1) for i in range(grid)]
    ys = [f(x) for x in xs]
    if any(y is None for y in ys):
        return {"ok": False, "monotonic": None,
                "reason": f"{label}: 브래킷 안에서 DCF 를 산출할 수 없는 지점이 있습니다 "
                          "(FCF 또는 발행주식수 없음)"}

    monotonic = all(b >= a for a, b in zip(ys, ys[1:]))
    if not monotonic:
        return {"ok": False, "monotonic": False,
                "reason": f"{label}: 브래킷 안에서 가치가 단조증가하지 않습니다 — "
                          "근이 유일하지 않으므로 숫자를 내지 않습니다"}

    if ys[-1] < target:
        return {"ok": False, "monotonic": True, "direction": "above_bracket",
                "reason": f"{label}: 브래킷 상단({hi:+.1%})에서도 목표가에 미치지 "
                          f"못합니다 — 시장은 그보다 높은 값을 함의합니다"}
    if ys[0] > target:
        return {"ok": False, "monotonic": True, "direction": "below_bracket",
                "reason": f"{label}: 브래킷 하단({lo:+.1%})에서도 목표가를 넘습니다 — "
                          "시장은 그보다 낮은 값을 함의합니다"}

    try:
        root = float(_brentq(lambda x: f(x) - target, lo, hi, xtol=XTOL))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "monotonic": True,
                "reason": f"{label}: 근을 찾지 못했습니다 ({type(e).__name__})"}
    return {"ok": True, "monotonic": True, "root": root, "achieved": f(root)}


def reverse_dcf(fs, params: ValuationParams | None = None,
                current_price: float | None = None, *,
                bracket: tuple[float, float] = DEFAULT_BRACKET,
                grid: int = DEFAULT_GRID) -> dict:
    """시장가를 정당화하는 **상수 FCF 성장률**. 순수 함수 — I/O 0.

    Args:
        fs: **평가 준비가 끝난** FinancialStatement
            (`ValuationEngine.load_statement` 가 돌려주는 그것).
        params: 없으면 기본 가정.
        current_price: 정당화 대상 주가.
    """
    if not _HAS_BRENTQ:
        return _unavailable("scipy.optimize 가 없어 근 찾기를 할 수 없습니다")
    if fs is None:
        return _unavailable("재무제표가 없습니다")
    if not current_price or float(current_price) <= 0:
        return _unavailable("현재가가 없어 정당화 대상이 없습니다")

    params = params or ValuationParams()
    price = float(current_price)
    lo = max(float(bracket[0]), _G_FLOOR)
    hi = float(bracket[1])
    if hi <= lo:
        return _unavailable(f"브래킷이 뒤집혔습니다: ({lo}, {hi})")

    # ★적자·마이너스 FCF 는 여기서 걸린다★ 근이 존재하지 않는 경우이므로 숫자를
    # 내지 않고 사유를 낸다. mock 은 항상 흑자라 이 경로는 실데이터에서만 열린다.
    base = compute_dcf(fs, params)
    if not base.available:
        return _unavailable(
            f"DCF 를 산출할 수 없어 역산의 대상이 없습니다: {base.error}",
            bracket=[lo, hi])

    sol = _solve(lambda g: _per_share(fs, params, g), price, (lo, hi), grid,
                 "FCF 성장률")
    if not sol["ok"]:
        return _unavailable(sol["reason"], bracket=[lo, hi],
                            monotonic=sol.get("monotonic"),
                            direction=sol.get("direction"))

    g_impl = sol["root"]
    achieved = sol["achieved"]

    # ★현재 가정의 '상수 등가' 를 같은 solver 로 구한다★
    # `compute_dcf` 의 기본 성장 경로는 스칼라가 아니라 궤적이고, 그 궤적을 여기서
    # 다시 쓰면 산수가 두 곳에 있게 된다. 대신 **기본 경로가 낸 주가를 재현하는
    # 상수 성장률**을 푼다 — 같은 함수, 같은 solver, 사과 대 사과다.
    cur_sol = _solve(lambda g: _per_share(fs, params, g),
                     float(base.intrinsic_value_per_share), (lo, hi), grid,
                     "현재 가정의 상수 등가")
    g_cur = cur_sol["root"] if cur_sol["ok"] else None

    # 두 번째 축 — 영구성장률. ★여기서는 `(wacc - g) > 0.001` 이 진짜 절벽이다★
    tg = _implied_terminal_growth(fs, params, price, base, grid)

    n = params.projection_years
    fcf_base = float(fs.fcf)
    path = [round(fcf_base * (1.0 + g_impl) ** t / 1e8, 1) for t in range(1, n + 1)]

    margin = None
    revenue = getattr(fs, "revenue", None)
    if revenue and float(revenue) > 0:
        margin = {
            "value_pct": round(fcf_base * (1.0 + g_impl) ** n / float(revenue) * 100, 2),
            # ★라벨 없이는 이 숫자를 내지 않는다★ 매출이 고정이라는 것은 우리가
            # 넣은 가정이지 시장이 함의한 것이 아니다.
            "assumes_flat_revenue": True,
            "note": ("오늘 매출을 그대로 고정했을 때 마지막 해 FCF 의 비율입니다. "
                     "매출 성장이 반영된 '시장내재 마진' 이 아닙니다 — 그것은 매출 "
                     "구동 DCF 라는 별도 모델을 요구합니다."),
        }

    return {
        "available": True,
        "method": "reverse_dcf_constant_growth",
        "implied_growth_pct": round(g_impl * 100, 2),
        "current_growth_pct": (round(g_cur * 100, 2) if g_cur is not None else None),
        "gap_pp": (round((g_impl - g_cur) * 100, 2) if g_cur is not None else None),
        "current_growth_reason": None if cur_sol["ok"] else cur_sol["reason"],
        "implied_terminal_growth_pct": tg.get("value_pct"),
        "terminal_growth_reason": tg.get("reason"),
        "implied_fcf_path": {"unit": "억원", "values": path},
        "implied_fcf_margin_pct": margin,
        # ★"정확히 풀었다" 고 말하지 않는다★ 반환값이 원 단위로 반올림되어 있으므로
        # 달성 가능한 최선과 시장가의 격차를 함께 싣는다.
        "achieved_price": achieved,
        "price_gap_won": round(achieved - price, 2),
        "market_price": price,
        "base_dcf_price": float(base.intrinsic_value_per_share),
        "monotonic": True,
        "bracket": [lo, hi],
        "wacc_pct": base.assumptions.get("wacc_pct"),
        "reason": None,
        "note": ("시장가를 정당화하는 **상수** FCF 성장률입니다. 허용오차는 가격이 "
                 "아니라 성장률에 걸려 있습니다 — DCF 가 주당가치를 원 단위로 "
                 "반올림하므로 price_gap_won 이 남을 수 있습니다."),
    }


def _implied_terminal_growth(fs, params: ValuationParams, price: float,
                             base, grid: int) -> dict:
    """시장내재 **영구성장률** — FCF 성장은 기본 경로에 고정.

    ★이 축에서는 `(wacc - g) > 0.001` 이 진짜 절벽이다★ 그 위에서는 TV 가 통째로
    0 으로 떨어져 가치가 급락한다. 그래서 브래킷 상한을 wacc 아래로 잡는다.
    `wacc_pct` 는 소수 둘째 자리로 반올림된 값이므로 여유를 0.2%p 둔다.
    """
    wacc_pct = base.assumptions.get("wacc_pct")
    if wacc_pct is None:
        return {"reason": "WACC 를 알 수 없어 영구성장률을 역산하지 않았습니다"}
    hi = wacc_pct / 100.0 - 0.002
    lo = -0.02
    if hi <= lo:
        return {"reason": f"WACC({wacc_pct}%)가 낮아 영구성장률 브래킷이 비었습니다"}

    def f(tg: float) -> float | None:
        r = compute_dcf(fs, replace(params, terminal_growth_rate=tg))
        return float(r.intrinsic_value_per_share) if r.available else None

    sol = _solve(f, price, (lo, hi), grid, "영구성장률")
    if not sol["ok"]:
        return {"reason": sol["reason"]}
    return {"value_pct": round(sol["root"] * 100, 2)}


def reverse_dcf_for(code: str, current_price: float,
                    params: ValuationParams | None = None, *,
                    market_cap: float | None = None,
                    bracket: tuple[float, float] = DEFAULT_BRACKET) -> dict:
    """종목 코드로 역DCF. `load_statement` 를 타므로 **mock 게이트를 공짜로 받는다.**"""
    from src.data.dart_client import DARTClient
    from src.engine.valuation.valuation_models import ValuationEngine

    loaded = ValuationEngine(DARTClient()).load_statement(
        code, current_price, market_cap=market_cap)
    if not loaded["available"]:
        return _unavailable(loaded["reason"] or "재무제표를 가져오지 못했습니다")
    out = reverse_dcf(loaded["fs"], params, current_price, bracket=bracket)
    out["code"] = str(code)
    out["corp_name"] = loaded["corp_name"]
    out["is_mock"] = loaded["is_mock"]
    return out
