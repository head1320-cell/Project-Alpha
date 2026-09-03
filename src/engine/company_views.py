"""기업 밸류에이션 → 자산별 절대 뷰 — ★분포가 화면에만 있었다★ (S4)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.2

`valuation_distribution_for` 는 이미 종목별 P10~P90 을 낸다. 그런데 그 산출은
Company 탭에서 **그림**으로 끝나고 배분에는 한 방울도 닿지 않았다. 이 모듈이 그
다리 한 칸이다 — 분포를 **기존 뷰 스키마**(`{assets, direction, magnitude_pct,
confidence, ...}`)로 번역해서 기존 `build_view_rows` → 기존 Ω → BL 을 그대로 탄다.

★새 밸류에이션 모델·새 뷰 스키마·새 P 빌더·새 Ω·새 최적화기를 만들지 않는다.★
선례는 `allocation_routes._conditional_views` 다 — 조건부 μ 를 자산 하나짜리 절대
뷰로 표현해 `P` 행이 `e_i` 가 되게 하는 바로 그 수법을 재사용한다.

★이 모듈은 아직 아무도 부르지 않는다★ 활성화(`use_company_views`)는 S5 다. 그래서
이 커밋에서는 배분 동작이 바뀌지 않는다.

────────────────────────────────────────────────────────────────────────────
★실측이 설계를 세 번 뒤집었다★ (mock 3종, `--n 800`)

| 종목 | 가격 | p50 | 총 갭 | 상대폭 | `price_percentile` |
|---|---|---|---|---|---|
| 005930 | 70,000 | 35,534 | −49.2% | 32.7% | **100.0** |
| 000660 | 130,000 | 404,322 | +211.0% | 56.3% | **0.0** |
| 035420 | 200,000 | 108,792 | −45.6% | 45.7% | **100.0** |

**⑴ 단위가 맞지 않는다.** 밸류에이션 갭은 **호라이즌이 없는 총 갭**인데 뷰의
`magnitude_pct` 는 **연간**이다(`build_user_views` 주석 · μ 는 `R.mean×252`).
`+211` 을 그대로 넘기면 "연 211% 기대수익" 으로 읽혀 BL 사후를 지배한다 — S2 가
`benefit_bps` 로 치를 뻔한 100배 오류와 **같은 계열**이다. 그래서 기하 연율화하고
그때 쓴 기간을 뷰에 함께 싣는다.

**⑵ `price_percentile` 은 포화한다.** 셋 다 정확히 0.0/100.0 — 가격이 분포 **밖**에
있다. 그래서 신뢰도를 분위로 만들 수 없다. 스펙 원안의 "폭의 함수" 도 절반만 맞다:
폭만으로는 **방향 확신**을 못 잰다(가격이 p50 에 딱 붙은 좁은 분포는 폭이 작아도
확신이 0). 갭과 폭을 **함께** 쓰는 표준화 갭 `z` 가 답이다.

**⑶ 이 재무는 backtest_eligible 이 될 수 없다.** `company_snapshot_builder.
publication_dates()` 가 이미 그렇게 적어 뒀다 — 실제 DART 접수일과 정정공시 이력이
저장소에 없어 `has_vintage: False`. 그리고 `valuation_distribution_for` 에는 `as_of`
인자 자체가 없다. **오늘 재무로 과거 뷰를 만들면 그것이 룩어헤드다** → `as_of` 가
오면 뷰를 내지 않고 사유를 돌려준다.
────────────────────────────────────────────────────────────────────────────

★상수를 발명하지 않는다★ 세 경계는 전부 저장소가 이미 고른 값이다:
`MAX_CONFIDENCE` ← `_CONDITIONAL_MAX_CONFIDENCE` · `MAX_MAGNITUDE_PCT` ←
`AllocationView.magnitude_pct` 의 `le=50` · 수렴 기간 ← 밸류에이션 자신의
`projection_years`.

★불확실성 전달은 BL 전용이다★ `entropy_views` 가 `confidence_used: False` 를 이미
선언한다 — EP 의 부등식 뷰는 경성 제약이라 신뢰도를 쓰지 않는다. 즉 여기서 만든
신뢰도는 EP 경로에서는 **아무 일도 하지 않는다**. 그 사실을 뷰의 `note` 가 말한다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 뷰 출처 라벨 — `_conditional_views` 의 `"conditional"` 과 같은 자리.
SOURCE = "company_valuation"

#: ★사용자 뷰보다 세질 수 없다★ `_CONDITIONAL_MAX_CONFIDENCE` 와 같은 이유이고
#: 같은 값이다. 폭 중 측정된 것이 하나도 없는 분포(`repo_widths()[*].measured` 가
#: 전부 false)에서 나온 뷰가 사람이 손으로 넣은 뷰보다 강해질 이유가 없다.
MAX_CONFIDENCE = 50.0

#: ★`|z|=1` 은 "가격이 90% 구간의 가장자리에 있다" 는 뜻★ — 앵커를 새로 고르지
#: 않고 분포가 이미 발표하는 구간을 그대로 쓴다. 여기서 신뢰도가 상한에 닿는다.
Z_FULL = 1.0

#: `AllocationView.magnitude_pct` 가 `le=50` 으로 이미 그은 바깥 경계.
MAX_MAGNITUDE_PCT = 50.0

# ── 뷰를 내지 못한 사유 ──────────────────────────────────────────────────────
KIND_NO_VINTAGE = "no_vintage_financials"
KIND_NO_PRICE = "no_price"
KIND_NO_DISTRIBUTION = "no_distribution"
KIND_NO_WIDTH = "no_width"
KIND_NON_POSITIVE_VALUE = "non_positive_fair_value"
KIND_OUT_OF_RANGE = "magnitude_out_of_range"

_NOTE = ("밸류에이션 분포의 p50 갭을 수렴 기간으로 편 **연간** 크기입니다. 폭 중 "
         "측정된 것은 하나도 없고(valuation_distribution.repo_widths), 수렴 기간은 "
         "밸류에이션 자신의 projection_years 를 재사용한 **가정**입니다. 신뢰도는 "
         "BL 의 Ω 에만 닿습니다 — EP 는 confidence_used:false 입니다.")


def _reason(kind: str, reason: str, **extra: Any) -> dict[str, Any]:
    """★사유는 기계가 읽을 수 있어야 한다★ 문자열만 두면 호출자가 문면을 파싱한다."""
    return {"kind": kind, "reason": reason, **extra}


def _annualize(gap: float, years: float) -> float:
    """총 갭 → 연간 크기(%). ★분수승 가드★

    `1 + gap ≤ 0`(p50 ≤ 0) 이면 실수 분수승이 의미를 잃는다 — 적자기업 실데이터
    에서만 열리는 가지이고 mock 은 항상 흑자라 통과한다(CLAUDE.md 수치 안전).
    """
    base = 1.0 + gap
    if base <= 0.0 or years <= 0.0:
        raise ValueError("연율화할 수 없는 갭")
    return (base ** (1.0 / years) - 1.0) * 100.0


def _usage() -> str:
    """★손으로 적지 않고 파생한다★ 손으로 넣으면 게이트가 거짓말을 할 수 있다
    (`timing_rules_v2:411` 이 같은 말을 한다).

    `has_vintage=False` 는 `publication_dates()` 가 이미 보고하는 사실이다 —
    실제 DART 접수일과 정정공시 이력이 저장소에 없다.
    """
    from src.data.pit_macro import derive_usage
    return derive_usage(has_vintage=False, depth_ok=True, lag_known=True).value


def company_views(codes: list[str], prices: dict[str, float], *,
                  as_of: str | None = None,
                  convergence_years: float | None = None,
                  n: int | None = None, seed: int | None = None,
                  ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """밸류에이션 분포 → 자산별 절대 뷰.

    Args:
        codes: 종목 코드. 뷰의 `assets` 는 이 코드 그대로다(유니버스 이름과 같아야
            `build_view_rows` 가 행을 만든다).
        prices: 코드 → 현재가. 없는 코드는 뷰가 아니라 **사유**가 된다.
        as_of: ★주면 뷰를 하나도 내지 않는다★ — 밑단에 빈티지 재무가 없다.
        convergence_years: 갭이 닫히는 데 걸린다고 **가정**하는 기간. 기본은
            밸류에이션 자신의 `projection_years`(현재 10).
        n, seed: `valuation_distribution_for` 로 그대로 넘긴다(주면).

    Returns:
        `(뷰 목록, 사유 맵)`. ★두 집합이 입력 코드를 정확히 덮는다★ — 조용히
        빠지는 종목이 없다.
    """
    from src.engine.valuation import valuation_distribution as vd

    views: list[dict[str, Any]] = []
    reasons: dict[str, dict[str, Any]] = {}

    if as_of:
        # ★흉내내지 않는다★ 오늘 재무로 과거 뷰를 만들면 그것이 룩어헤드다.
        # `publication_dates()` 가 이미 "이 스냅샷은 backtest_eligible 이 될 수
        # 없습니다" 라고 적어 뒀고, 이 함수가 그 선언을 집행한다.
        for c in codes:
            reasons[str(c)] = _reason(
                KIND_NO_VINTAGE,
                f"as_of={as_of} 시점의 **빈티지 재무**가 없습니다 — DART 접수일과 "
                f"정정공시 이력이 저장소에 없어(has_vintage=false) 오늘 재무로 과거 "
                f"뷰를 만들면 룩어헤드가 됩니다.",
                as_of=str(as_of), research_usage=_usage())
        return views, reasons

    kw: dict[str, Any] = {}
    if n is not None:
        kw["n"] = int(n)
    if seed is not None:
        kw["seed"] = int(seed)

    for raw in codes:
        code = str(raw)
        price = prices.get(code)
        if price is None or float(price) <= 0.0:
            reasons[code] = _reason(KIND_NO_PRICE,
                                    "현재가가 없어 갭을 잴 수 없습니다")
            continue
        price = float(price)

        try:
            dist = vd.valuation_distribution_for(code, price, **kw)
        except Exception as e:  # noqa: BLE001
            logger.warning("밸류에이션 분포 실패 %s: %s: %s", code, type(e).__name__, e)
            reasons[code] = _reason(KIND_NO_DISTRIBUTION,
                                    f"{type(e).__name__}: {e}")
            continue

        unified = dist.get("unified") or {}
        if not dist.get("available") or not unified.get("available"):
            reasons[code] = _reason(
                KIND_NO_DISTRIBUTION,
                str(dist.get("reason") or unified.get("reason")
                    or "분포를 만들 수 없습니다"))
            continue

        p10 = float(unified["p10"])
        p50 = float(unified["p50"])
        p90 = float(unified["p90"])

        half = (p90 - p10) / 2.0
        if half <= 0.0:
            # ★신뢰도를 지어내지 않는다★ 폭이 없으면 `z` 가 정의되지 않는다.
            reasons[code] = _reason(
                KIND_NO_WIDTH,
                "P10~P90 폭이 0 이라 표준화 갭을 만들 수 없습니다 — 신뢰도를 "
                "지어내지 않습니다")
            continue

        gap = (p50 - price) / price
        years = float(convergence_years if convergence_years is not None
                      else (dist.get("base_assumptions") or {}).get("years") or 0.0)
        try:
            ann = _annualize(gap, years)
        except ValueError:
            reasons[code] = _reason(
                KIND_NON_POSITIVE_VALUE,
                f"적정가 p50={p50:,.0f} 이 0 이하이거나 수렴 기간이 0 이라 연율화할 "
                f"수 없습니다 — 크기를 지어내지 않습니다")
            continue

        if abs(ann) > MAX_MAGNITUDE_PCT:
            # ★조용히 조이지 않는다★ 상한으로 자르면 50%/yr 짜리 뷰가 '정상 뷰' 로
            # 위장한다. `build_view_rows` 가 크기 0 뷰를 다루는 방식과 같은 규율이다.
            reasons[code] = _reason(
                KIND_OUT_OF_RANGE,
                f"연율 크기 {ann:.1f}% 가 상한 {MAX_MAGNITUDE_PCT:.0f}% 를 넘습니다 "
                f"— 잘라서 정상 뷰처럼 보이게 하지 않습니다",
                magnitude_pct=round(abs(ann), 4),
                total_gap_pct=round(gap * 100.0, 4), horizon_years=years)
            continue

        z = (p50 - price) / half
        conf = round(MAX_CONFIDENCE * min(abs(z), Z_FULL) / Z_FULL, 4)

        views.append({
            # ── 소비자가 실제로 읽는 칸 (`build_view_rows` · `build_user_views`)
            "assets": [code],
            "direction": 1 if ann >= 0 else -1,
            "magnitude_pct": round(abs(ann), 4),
            "confidence": conf,
            "source": SOURCE,
            "label": f"{dist.get('corp_name') or code} 밸류에이션 갭",
            # ── 아래는 관측용이다. 두 소비자 모두 읽지 않으므로 계산을 바꾸지
            #    않고, 대신 "이 뷰가 어디서 왜 나왔는지" 를 응답에 실을 수 있게 한다.
            "horizon_years": years,
            "total_gap_pct": round(gap * 100.0, 4),
            "z": round(z, 4),
            "confidence_saturated": bool(abs(z) >= Z_FULL),
            "relative_width_pct": round((p90 - p10) / abs(p50) * 100.0, 4)
                                  if p50 else None,
            "is_mock": bool(dist.get("is_mock")),
            "measured": False,
            "research_usage": _usage(),
            "note": _NOTE,
        })

    return views, reasons


def prices_for(codes: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    """코드 → `(가격 맵, 출처 맵)`. ★가격 해석을 재구현하지 않는다★

    저장소에 이미 두 벌이 있다(`execution_plan._last_close` ·
    `company_snapshot_builder._resolve_price`). 세 번째를 만들면 반드시 갈라지고
    갈라져도 타입 에러가 나지 않는다. 기업 도메인의 것을 쓴다 — 그 함수가
    ★"창의 끝은 **오늘**이어야 한다"★ 는 실측 교훈(2099년 종가 409원을 잡던
    버그)을 이미 담고 있고 **출처 라벨**까지 함께 준다.

    ★가격을 못 구한 코드는 맵에 넣지 않는다★ — 지어내지 않고, `company_views()`
    가 `KIND_NO_PRICE` 사유로 보고하게 둔다. 그래서 이 함수는 S4 가 못 박은
    계약을 바꾸지 않는다.
    """
    from src.engine import company_snapshot_builder as csb

    prices: dict[str, float] = {}
    source: dict[str, str] = {}
    for raw in codes:
        code = str(raw)
        try:
            px, src = csb._resolve_price(code, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("가격 해석 실패 %s: %s: %s", code, type(e).__name__, e)
            px, src = None, "unavailable"
        source[code] = src
        if px is not None and float(px) > 0:
            prices[code] = float(px)
    return prices, source
