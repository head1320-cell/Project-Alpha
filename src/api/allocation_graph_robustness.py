"""그래프 노드의 견고성 보기 (BR R1) — 엔진 블록 + 상관 급등 충격 + 한 줄 이야기.

`src/engine/strategy_robustness.py` 의 관측 블록에 두 가지를 붙인다.
- **시장 대용 위기일** — KODEX 200(`timing_factors._KOSPI_ETF`, 타이밍 신호와 같은 대용)의 일별 수익을 같은 길이로 끝을
  맞춰 가져온다. 없으면 엔진이 전략 평균으로 고르고 그렇다고 라벨을 단다(라벨 붙은 열화).
- **상관 급등 충격** — `stress_correlation_report`(상관이 치솟으면 노드·`/stress-correlation` 과 같은 함수)를 전략 흐름에.
  정한 값(가정)과 **실제로 본 가장 높은 평균 창 상관**(관측) 둘. 지금 상관이 이미 그 이상이면 올리지 않고 사유.

전략 합치기(`portfolio_combine`)와 견고성 비교(`sleeve_analytics`) 노드가 같이 쓴다. 배분은 바꾸지 않는다.
스펙: docs/superpowers/specs/2026-09-28-br-robustness-profile-design.md
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np

from src.data.mock_gate import mock_allowed
from src.domain.perf_kind import backtest_label

logger = logging.getLogger(__name__)

#: 충격 목표 상관 선택지 — 상관이 치솟으면 노드(`CorrParams`)와 같은 눈금.
SHOCK_RHOS = (0.7, 0.8, 0.9)
#: VaR 을 % 로 읽으려고 쓰는 기준 금액(보고서가 금액을 정수로 반올림한다 — 1 로 두면 0 이 된다).
_VALUE = 100_000_000.0


def market_series(T: int, market: str = "kr") -> tuple[np.ndarray | None, str | None]:
    """시장 대용 일별 수익 T개(끝 맞춤). 없으면 (None, 사유)."""
    if market != "kr":
        return None, "이 시장의 시장 대용 시세는 아직 없어요"
    from src.data.etf_prices import daily_closes
    from src.engine.timing_factors import _KOSPI_ETF
    try:
        c = daily_closes(_KOSPI_ETF, "kr", T + 1)
    except Exception as e:  # noqa: BLE001 — 사유로 남긴다
        logger.warning("시장 대용 시세 불러오기 실패", exc_info=True)
        return None, f"시장 대용(KODEX 200) 시세를 불러오지 못했어요 — {type(e).__name__}"
    if len(c) < T + 1:
        return None, f"시장 대용(KODEX 200) 시세가 {max(len(c) - 1, 0)}거래일뿐이라 {T}거래일 흐름과 맞출 수 없어요"
    arr = np.asarray(c[-(T + 1):], dtype=float)
    r = arr[1:] / arr[:-1] - 1.0
    if not np.all(np.isfinite(r)):
        return None, "시장 대용 시세에 빈 값이 있어요"
    return r, None


def shock_block(names: Sequence[str], S: np.ndarray, shares: Sequence[float] | None, target_rho: float,
                observed_max: float | None) -> dict[str, Any]:
    import pandas as pd

    from src.api.allocation_stress_routes import stress_correlation_report
    n = len(names)
    if any(float(np.var(S[:, j])) <= 1e-16 for j in range(n)):
        return {"available": False, "reason": "흔들림이 없는 흐름이 있어 상관 충격을 넣을 수 없어요"}
    w = np.ones(n) / n if shares is None else np.asarray([float(x) for x in shares], dtype=float)
    df = pd.DataFrame(S, columns=list(names))
    C = np.corrcoef(S.T)
    off = ~np.eye(n, dtype=bool)
    now = float(C[off].mean())
    out: dict[str, Any] = {"available": True, "from_avg_rho": round(now, 3), "scenarios": []}
    wanted = [("assumed", float(target_rho))]
    if observed_max is not None:
        wanted.append(("observed", float(observed_max)))
    for kind, rho in wanted:
        row: dict[str, Any] = {"kind": kind, "rho": round(rho, 3)}
        if now >= rho:
            # 이름·숫자 뒤 조사는 소리에 따라 달라진다 — 괄호로 두어 조사를 붙이지 않는다(스크린샷에서 "1.00 라" 를 찾았다).
            row.update(available=False,
                       reason=f"지금 평균 상관({now:.2f})이 이미 정한 값({rho:.2f}) 이상이라 올려도 흔들림이 커지지 않아요")
        else:
            rep = stress_correlation_report(df, w, target_rho=rho, intensity=1.0, confidence_level=0.95,
                                            portfolio_value=_VALUE)
            row.update(available=True, base_vol_pct=rep["base"]["port_vol_pct"],
                       stressed_vol_pct=rep["stressed"]["port_vol_pct"], delta_vol_pct=rep["delta_vol_pct"],
                       base_var_pct=round(rep["base"]["var_amount"] / _VALUE * 100, 2),
                       stressed_var_pct=round(rep["stressed"]["var_amount"] / _VALUE * 100, 2),
                       delta_var_pct=rep["delta_var_pct"])
        out["scenarios"].append(row)
    return out


def story(rep: dict[str, Any]) -> list[str]:
    """쉬운 말 몇 줄 — 수는 블록 그대로. 판정 어휘(CLAUDE.md 의 금지 목록)는 쓰지 않는다."""
    lines: list[str] = []
    eff = rep.get("effective_n") or {}
    if eff.get("value") is not None:
        lines.append(f"{eff['n']}개가 실제로는 약 {eff['value']:.1f}개처럼 움직였어요 — 적을수록 서로 같이 움직인 거예요.")
    crisis = rep.get("crisis") or {}
    rows = [p for p in crisis.get("pairs") or [] if p.get("co_drops") is not None and p.get("expected_co_drops")]
    if rows:
        top = max(rows, key=lambda p: p["co_drops"] / p["expected_co_drops"])
        more = top["co_drops"] >= 1.5 * top["expected_co_drops"] and top["co_drops"] - top["expected_co_drops"] >= 3
        small = " 날이 적어 흔들리는 값이에요." if crisis.get("small_sample") else ""
        # 사용자가 지은 이름 뒤에는 조사를 붙이지 않는다('충격 점검가' 처럼 어긋난다) — 쌍은 문장 끝에 둔다.
        pair = f"{top['a']}·{top['b']} {top['co_drops']}일 대 약 {top['expected_co_drops']:.0f}일"
        if more:
            lines.append(f"가장 나빴던 날에 같이 떨어진 날이 평소 관계로 기대되는 것보다 많았어요 — {pair}.{small}")
        else:
            lines.append(f"가장 나빴던 날에 같이 떨어진 날은 평소 관계로 기대되는 만큼이었어요 — 가장 많은 쌍 {pair}.{small}")
    shock = rep.get("shock") or {}
    first = next((s for s in shock.get("scenarios") or [] if s.get("kind") == "assumed"), None)
    if first and first.get("available") and first.get("delta_vol_pct") is not None:
        lines.append(f"상관이 {first['rho']:.1f}로 치솟는다고 가정하면 합친 흔들림이 {first['delta_vol_pct']:+.0f}% 달라져요.")
    dd = rep.get("drawdown") or {}
    pairs = [p for p in dd.get("pairs") or [] if p.get("overlap") is not None]
    if pairs:
        top = max(pairs, key=lambda p: p["overlap"])
        lines.append(f"가장 크게 잃은 구간이 가장 많이 겹친 쌍은 {top['a']}·{top['b']} — {top['overlap'] * 100:.0f}% 겹쳐요.")
    return lines


def robustness_view(names: Sequence[str], S: np.ndarray, shares: Sequence[float] | None, *, market: str = "kr",
                    window: int = 60, target_rho: float = 0.8, shorts_dropped: int = 0) -> dict[str, Any]:
    """엔진 보고서 + 시장 대용 + 충격 + 이야기. 계산이 깨지면 조용히 넘기지 않고 사유와 함께 `available: False`."""
    from src.engine.strategy_robustness import robustness_report
    try:
        T = int(np.asarray(S).shape[0])
        mk, mk_reason = market_series(T, market)
        rep = robustness_report(names, S, shares, market=mk, window=window)
        if not rep.get("available"):
            return rep
        if mk is None:
            rep["crisis"]["market_reason"] = mk_reason
        roll = rep["rolling"]
        rep["shock"] = shock_block(names, np.asarray(S, dtype=float), shares, target_rho,
                                   roll.get("avg_max") if roll.get("available") else None)
        rep["shorts_dropped"] = int(shorts_dropped)
        rep["story"] = story(rep)
        # 낙폭·흔들림은 '지금 비중을 과거에 들고 있었다면'의 과거 데이터 위 시뮬레이션이다 — 성과 종류를 응답이 선언한다
        # (PerfLabel 계약 · 화면은 그리기만). 데이터 축은 mock 게이트가 정한다.
        rep["perf_label"] = {**backtest_label(is_mock_data=mock_allowed()).to_dict(),
                             "kind_reason": f"지금 비중을 지난 {rep['n_days']}거래일 들고 있었다고 본 과거 데이터 위 "
                                            "시뮬레이션이에요 — 실제 운용 기록이 아니에요."}
        return rep
    except Exception as e:  # noqa: BLE001 — 배분은 그대로 두고 이 절만 모른다고 말한다
        logger.exception("견고성 계산 실패")
        return {"available": False, "reason": f"견고성을 계산하지 못했어요 — {type(e).__name__}: {e}"}


def count_shorts(sleeves: Sequence[dict]) -> int:
    """흐름을 만들 때 빠지는 숏 비중 수(`_sleeve_return_series` 는 음수 비중을 0 으로 본다)."""
    return sum(1 for s in sleeves for v in (s.get("weights") or {}).values() if float(v) < 0)
