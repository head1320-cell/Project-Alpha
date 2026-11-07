"""포트폴리오 비중 — ★부호를 잃지 않는다★ (P3 후속)

P3 는 롱숏을 **연구·백테스트 전용**으로 열었다. `optimize → backtest → target` 까지
숏이 살아남고, 실행에서는 의도적으로 막힌다(`execution_plan` 의 클램프는 P3 가
검토하고 **유지하기로 한** 두 번째 방어선이다 — 이 모듈은 거기 관여하지 않는다).

그런데 포트폴리오를 **되읽는** 분석 계층은 P3 이전 가정 위에 그대로 있었다.

★이 모듈이 존재하는 이유 — 실측★

    시장중립 페어: A +100%, B −100% (둘 다 growth 베타 1.0)
        참값 노출  = 1.0·(+1.0) + 1.0·(−1.0) = 0.0
        보고된 노출 = 1.0     coverage_pct: 100.0   missing: []

`coverage_pct: 100`·`missing: []` — **아무 문제 없다고 말하면서** 숏 다리를 통째로
버렸다. 100% 롱 북과 똑같은 숫자가 나온다. 숏의 팩터 노출은 부호가 반대이므로
이것은 값이 부정확한 것이 아니라 **결론이 뒤집히는** 것이다.

★이 저장소는 같은 버그를 이미 한 번 고쳤다★ `constrained_opt.py` 의 회전율 계산이
그랬고, 거기 적힌 결론이 이 모듈의 핵심 규칙이다:

    정규화도 넷 합으로 나누면 달러중립(Σw≈0)에서 폭발하므로 **gross 로 나눈다.**

★규칙 3개★

  1. **gross(Σ|w|)로 나눈다, net(Σw)으로 나누지 않는다.** 달러중립에서 폭발한다.
  2. **롱온리는 비트 동일.** 모든 `w ≥ 0` 이면 `Σ|w| ≡ Σmax(w,0)` 이므로 기존
     출력이 값까지 그대로다 — 이 성질이 없으면 이 리팩터는 회귀 위험이다.
  3. **커버리지도 gross 기준.** 숏을 뺀 커버리지는 "덮었다" 고 말하면서 절반을
     버린다. 위 실측의 `coverage_pct: 100` 이 정확히 그것이다.

★NAV 기준 노출은 여기 넣지 않는다★ 130/30 은 gross 기준 0.625, NAV 기준 1.00 이다.
두 숫자를 다 내면 "어느 쪽이 진실인가" 를 묻게 되므로, 하나만 내되 `exposure_basis`
로 **어느 기준인지 말한다**. 그것이 P3 의 관례이기도 하다 — 롱숏에서 `Σw` 하나로는
포지션 크기를 말할 수 없어 gross 와 net 을 함께 낸다.
"""
from __future__ import annotations

# gross 가 이보다 작으면 "비중이 없다" 로 본다. 0 으로 나누는 것을 막는 유일한 문턱.
GROSS_EPS = 1e-9


def _values(weights: dict) -> list[float]:
    """숫자만 골라 float 로. 문자열·None 이 섞여 들어와도 터지지 않는다."""
    out = []
    for v in weights.values():
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def gross(weights: dict) -> float:
    """Σ|w| — ★포지션 크기★ 롱 100/숏 0 과 롱 150/숏 50 을 가르는 유일한 숫자."""
    return float(sum(abs(v) for v in _values(weights)))


def net(weights: dict) -> float:
    """Σw — 방향. ★이것으로 나누지 말 것★ 달러중립에서 0 이 된다."""
    return float(sum(_values(weights)))


def has_short(weights: dict) -> bool:
    return any(v < 0 for v in _values(weights))


def signed_fractions(weights: dict) -> dict[str, float]:
    """비중 dict → **gross 정규화 · 부호 보존** 분수. `Σ|out| == 1`.

    ★롱온리 비트 동일★ 모든 `w ≥ 0` 이면 `Σ|w| == Σw` 이므로 예전
    `max(w,0)/Σmax(w,0)` 와 값이 같다.

    0 과 숫자가 아닌 값은 버린다(예전 동작). ★음수는 버리지 않는다★ — 그것이
    이 함수의 존재 이유다. gross 가 0 이면 빈 dict(정직한 "비중 없음").
    """
    g = gross(weights)
    if g <= GROSS_EPS:
        return {}
    out: dict[str, float] = {}
    for k, v in weights.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == 0.0:
            continue
        out[str(k)] = f / g
    return out


def exposure_basis(weights: dict) -> dict:
    """★어느 기준의 숫자인지 말한다★ 노출·리스크 응답에 함께 싣는 블록.

    롱숏에서 `Σw` 하나로는 포지션 크기를 말할 수 없다 — 롱 100/숏 0 과
    롱 150/숏 50 은 넷이 똑같이 100% 지만 전혀 다른 포트폴리오다.
    """
    vals = _values(weights)
    long_pct = float(sum(v for v in vals if v > 0))
    short_pct = float(sum(-v for v in vals if v < 0))
    return {
        "gross_pct": round(long_pct + short_pct, 6),
        "net_pct": round(long_pct - short_pct, 6),
        "long_pct": round(long_pct, 6),
        "short_pct": round(short_pct, 6),
        "long_short": short_pct > 0.0,
        "normalized_by": "gross",
        "note": ("노출은 gross(Σ|w|) 기준입니다 — 달러중립(Σw≈0)에서 net 으로 "
                 "나누면 폭발하기 때문입니다. NAV 기준으로 환산하려면 gross_pct/100 "
                 "을 곱하십시오."),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 비중의 **단위** — ★`dict[str, float]` 는 자기 단위를 말하지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════
#
# ★실측 — 같은 지시가 100배 다른 주문을 낸다★
#
#     build_plan(현재 0, 목표 {"005930": 60.0, "000660": 40.0}, PV=10억)
#         → 매수 999,970,000원 · 회전율 100.0%
#     build_plan(현재 0, 목표 {"005930":  0.60, "000660":  0.40}, PV=10억)
#         → 매수   9,950,000원 · 회전율   1.0%      ← 경고 없음
#
# 저장소 안에 **서로 다른 두 관례**가 공존한다:
#   · 돈을 세는 계층(`execution_plan`·`rebalance_policy`·`instrument_selector`)은
#     `/100.0` 으로 **퍼센트를 가정**한다.
#   · 비율을 세는 계층(`factor_exposure`·`factor_risk`·`attribution`…)은 gross 로
#     정규화해 **단위와 무관**하다.
# 그래서 한 응답 안에서 절반은 옳고 절반은 100배 틀릴 수 있고, 아무도 그것을 말하지
# 않는다. 라우트의 선언된 관례는 **퍼센트**다(`# {code: weight_pct}`).
#
# ★추측하지 않는다★ 합이 1 근처면 "분수로 준 100%" 인지 "퍼센트로 준 1%(현금 99%)"
# 인지 **알 수 없다.** 둘 다 정당한 포트폴리오다. 조용히 골라 주는 것이 바로 이
# 결함을 만든 행동이므로, 모호하면 사유를 돌려주고 호출자가 선언하게 한다.

PERCENT = "percent"
FRACTION = "fraction"

#: 이 구간의 gross 합은 두 가지로 읽힌다 — 분수로 준 만액, 또는 퍼센트로 준 소액.
_AMBIGUOUS_LO, _AMBIGUOUS_HI = 0.5, 4.0


def unit_reason(weights: dict, declared: str | None = None) -> str | None:
    """단위가 모호하면 **사유 문자열**, 아니면 `None`.

    ★엔진은 HTTP 를 모른다★ `validate_as_of` 와 같은 관례 — 라우트가 422 로 바꾼다.
    """
    if declared in (PERCENT, FRACTION):
        return None
    if declared is not None:
        return (f"weight_unit 은 '{PERCENT}' 또는 '{FRACTION}' 이어야 합니다: {declared!r}")
    g = gross(weights)
    if _AMBIGUOUS_LO <= g <= _AMBIGUOUS_HI:
        return (f"비중의 단위를 알 수 없습니다 (합 {g:g}). 분수로 주신 만액 포트폴리오"
                f"(합 1.0)일 수도, 퍼센트로 주신 소액 포트폴리오(합 {g:g}%, 현금 "
                f"{100 - g:g}%)일 수도 있습니다 — 둘은 주문 금액이 100배 다릅니다. "
                f"weight_unit 에 '{PERCENT}' 또는 '{FRACTION}' 을 지정해 주십시오.")
    return None


def as_percent(weights: dict, declared: str | None = None) -> dict[str, float]:
    """돈을 세는 계층이 쓰는 형태(퍼센트)로 통일한다.

    선언이 있으면 그대로 따르고, 없으면 gross 합으로 판정한다. ★모호 구간은
    `unit_reason` 이 먼저 막는 것을 전제로 한다★ — 여기까지 왔다면 판정이 가능한
    입력이다(그래도 방어적으로 퍼센트로 본다: 라우트의 선언된 관례가 퍼센트다).
    """
    if declared == PERCENT:
        return {str(k): float(v) for k, v in weights.items()}
    if declared == FRACTION:
        return {str(k): float(v) * 100.0 for k, v in weights.items()}
    g = gross(weights)
    if g < _AMBIGUOUS_LO:                      # 합이 0.5 미만 — 분수로 준 소액
        return {str(k): float(v) * 100.0 for k, v in weights.items()}
    return {str(k): float(v) for k, v in weights.items()}
