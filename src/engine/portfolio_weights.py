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
