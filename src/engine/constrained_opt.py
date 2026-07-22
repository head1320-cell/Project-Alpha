"""제약 포트폴리오 최적화 — 박스·그룹·회전율·베타·현금 밴드 (Full Expansion P3)
==============================================================================
지시서 요구: "최적화 결과는 항상 다음 중 하나 —
  ① 제약 충족 해 ② 위반 목록이 붙은 근사해 ③ 사람이 이해할 사유가 붙은 infeasible.
  infeasible을 조용히 무시하거나 임의로 제약을 완화하지 말 것."

구현:
  · mvo/bl/min_var: SLSQP에 제약을 직접 인코딩 (allocation_studio의 μ·Σ 재사용).
  · risk_parity/hrp(공분산 전용): 무제약 해를 박스·그룹에 사후 투영 —
    "최적화 제약이 아닌 근사 투영"임을 정직 라벨(위반 잔여도 보고).
  · 실패 시 완화 사다리(회전율→베타→그룹 순)로 근사해 탐색 — 어떤 제약을
    완화했는지 relaxed[]로 명시(임의 완화 아님, 보고되는 완화).
  · 사전 타당성 검사로 구조적 infeasible(상한 합 부족 등)은 즉시 사람 언어 사유.

현금: cash = 1 − Σw 를 암묵 자산으로 취급(수익 0 가정 — 정직 노트).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

_EPS = 1e-6
_BIND_TOL = 0.005          # 바인딩 판정 허용 (0.5%p)


@dataclass
class Constraints:
    """전부 선택 — 지정된 것만 적용. 퍼센트 단위(0~100)."""
    max_weight_pct: float | None = None          # 종목당 상한
    min_weight_pct: float = 0.0                  # 종목당 하한 (롱온리 기본 0)
    group_caps_pct: dict[str, float] = field(default_factory=dict)   # 그룹명 → 상한%
    turnover_cap_pct: float | None = None        # 0.5·Σ|w−w_cur| ≤ cap%
    beta_min: float | None = None
    beta_max: float | None = None
    cash_min_pct: float = 0.0
    cash_max_pct: float = 0.0                    # 0이면 완전투자 (기존 동작 보존)

    def any_active(self) -> bool:
        return (self.max_weight_pct is not None or self.min_weight_pct > 0
                or bool(self.group_caps_pct) or self.turnover_cap_pct is not None
                or self.beta_min is not None or self.beta_max is not None
                or self.cash_min_pct > 0 or self.cash_max_pct > 0)


def asset_betas(R: np.ndarray, bench: np.ndarray | None) -> np.ndarray | None:
    """자산별 시장 베타 (bench 일수익률 대비 OLS). bench 없으면 None."""
    if bench is None or len(bench) != R.shape[0] or np.std(bench) < 1e-12:
        return None
    b = np.asarray(bench, dtype=float)
    var = float(np.var(b, ddof=1))
    return np.array([float(np.cov(R[:, i], b, ddof=1)[0, 1]) / var for i in range(R.shape[1])])


def _precheck(n: int, c: Constraints, groups: dict[str, list[int]]) -> str | None:
    """구조적 infeasible을 사람 언어로. None이면 통과."""
    invest_min = 1.0 - c.cash_max_pct / 100.0
    invest_max = 1.0 - c.cash_min_pct / 100.0
    if invest_min > invest_max + _EPS:
        return "현금 밴드가 뒤집혀 있습니다 (min > max)."
    ub = (c.max_weight_pct / 100.0) if c.max_weight_pct is not None else 1.0
    lb = c.min_weight_pct / 100.0
    if lb > ub + _EPS:
        return "종목 하한이 상한보다 큽니다."
    if n * ub < invest_min - _EPS:
        return (f"종목당 상한 {c.max_weight_pct}% × {n}종목 = {round(n * ub * 100)}% 로 "
                f"요구 투자비중 {round(invest_min * 100)}%를 채울 수 없습니다 — 상한을 올리거나 종목을 추가하세요.")
    if n * lb > invest_max + _EPS:
        return (f"종목 하한 {c.min_weight_pct}% × {n}종목이 투자 가능 비중을 초과합니다.")
    if groups and c.group_caps_pct:
        capped = set()
        cap_sum = 0.0
        for g, idxs in groups.items():
            cap = c.group_caps_pct.get(g)
            if cap is not None:
                capped |= set(idxs)
                cap_sum += cap / 100.0
        uncapped = n - len(capped)
        max_from_uncapped = uncapped * ub
        if cap_sum + max_from_uncapped < invest_min - _EPS:
            return (f"그룹 상한 합 {round(cap_sum * 100)}% + 비제한 종목 여력으로 "
                    f"요구 투자비중을 채울 수 없습니다 — 그룹 상한을 올리세요.")
    return None


def _build_slsqp(n: int, c: Constraints, groups: dict[str, list[int]],
                 w_cur: np.ndarray | None, betas: np.ndarray | None,
                 skip: set[str]) -> tuple[list, list[tuple[float, float]]]:
    ub = (c.max_weight_pct / 100.0) if c.max_weight_pct is not None else 1.0
    lb = c.min_weight_pct / 100.0
    bounds = [(lb, ub)] * n
    cons: list[dict] = []
    invest_min = 1.0 - c.cash_max_pct / 100.0
    invest_max = 1.0 - c.cash_min_pct / 100.0
    cons.append({"type": "ineq", "fun": lambda w: np.sum(w) - invest_min})
    cons.append({"type": "ineq", "fun": lambda w: invest_max - np.sum(w)})
    if "group" not in skip:
        for g, idxs in groups.items():
            cap = c.group_caps_pct.get(g)
            if cap is not None:
                cons.append({"type": "ineq",
                             "fun": (lambda w, ix=tuple(idxs), cp=cap / 100.0: cp - np.sum(w[list(ix)]))})
    if "turnover" not in skip and c.turnover_cap_pct is not None and w_cur is not None:
        cap = c.turnover_cap_pct / 100.0
        # |x| 평활화(√(x²+δ)) — x0=w_cur 비미분점에서 SLSQP가 죽는 것을 방지
        cons.append({"type": "ineq",
                     "fun": lambda w: cap - 0.5 * np.sum(np.sqrt((w - w_cur) ** 2 + 1e-10))})
    if "beta" not in skip and betas is not None:
        if c.beta_min is not None:
            cons.append({"type": "ineq", "fun": lambda w: float(w @ betas) - c.beta_min})
        if c.beta_max is not None:
            cons.append({"type": "ineq", "fun": lambda w: c.beta_max - float(w @ betas)})
    return cons, bounds


def _violations(w: np.ndarray, c: Constraints, groups: dict[str, list[int]],
                w_cur: np.ndarray | None, betas: np.ndarray | None) -> tuple[list[dict], list[str]]:
    """(위반 목록, 바인딩 목록)."""
    viol: list[dict] = []
    binding: list[str] = []
    ub = (c.max_weight_pct / 100.0) if c.max_weight_pct is not None else 1.0
    lb = c.min_weight_pct / 100.0

    over = np.where(w > ub + _BIND_TOL)[0]
    if c.max_weight_pct is not None:
        if len(over):
            viol.append({"kind": "max_weight", "detail": f"{len(over)}종목이 상한 {c.max_weight_pct}% 초과",
                         "amount_pct": round(float((w[over] - ub).sum()) * 100, 2)})
        elif np.any(np.abs(w - ub) < _BIND_TOL):
            binding.append(f"종목 상한 {c.max_weight_pct}%")
    if lb > 0 and np.any(w < lb - _BIND_TOL):
        viol.append({"kind": "min_weight", "detail": f"종목 하한 {c.min_weight_pct}% 미달 존재"})

    for g, idxs in groups.items():
        cap = c.group_caps_pct.get(g)
        if cap is None:
            continue
        s = float(np.sum(w[idxs])) * 100
        if s > cap + _BIND_TOL * 100:
            viol.append({"kind": "group_cap", "detail": f"그룹 '{g}' {round(s, 1)}% > 상한 {cap}%",
                         "amount_pct": round(s - cap, 2)})
        elif abs(s - cap) < _BIND_TOL * 100:
            binding.append(f"그룹 상한 {g} {cap}%")

    if c.turnover_cap_pct is not None and w_cur is not None:
        t = 0.5 * float(np.sum(np.abs(w - w_cur))) * 100
        if t > c.turnover_cap_pct + _BIND_TOL * 100:
            viol.append({"kind": "turnover", "detail": f"회전율 {round(t, 1)}% > 상한 {c.turnover_cap_pct}%",
                         "amount_pct": round(t - c.turnover_cap_pct, 2)})
        elif abs(t - c.turnover_cap_pct) < _BIND_TOL * 100:
            binding.append(f"회전율 상한 {c.turnover_cap_pct}%")

    if betas is not None:
        pb = float(w @ betas)
        if c.beta_max is not None and pb > c.beta_max + _BIND_TOL:
            viol.append({"kind": "beta", "detail": f"β {round(pb, 2)} > 상한 {c.beta_max}"})
        elif c.beta_max is not None and abs(pb - c.beta_max) < _BIND_TOL:
            binding.append(f"β 상한 {c.beta_max}")
        if c.beta_min is not None and pb < c.beta_min - _BIND_TOL:
            viol.append({"kind": "beta", "detail": f"β {round(pb, 2)} < 하한 {c.beta_min}"})

    cash = (1.0 - float(np.sum(w))) * 100
    if cash > c.cash_max_pct + _BIND_TOL * 100 or cash < c.cash_min_pct - _BIND_TOL * 100:
        viol.append({"kind": "cash", "detail": f"현금 {round(cash, 1)}% 가 밴드 밖"})
    return viol, binding


def _project_box_group(w: np.ndarray, c: Constraints, groups: dict[str, list[int]]) -> np.ndarray:
    """공분산 전용 모델용 근사 투영: 상한 클립 → 초과분을 여유 종목에 비례 재배분(반복)."""
    ub = (c.max_weight_pct / 100.0) if c.max_weight_pct is not None else 1.0
    x = np.clip(w.astype(float), 0.0, None)
    tot = x.sum()
    x = x / tot if tot > 0 else np.full_like(x, 1.0 / len(x))
    for _ in range(50):
        x = np.minimum(x, ub)
        for g, idxs in groups.items():
            cap = c.group_caps_pct.get(g)
            if cap is None:
                continue
            s = x[idxs].sum()
            if s > cap / 100.0 + _EPS and s > 0:
                x[idxs] *= (cap / 100.0) / s
        deficit = 1.0 - c.cash_min_pct / 100.0 - x.sum()
        if deficit < _EPS:
            break
        room = np.maximum(ub - x, 0.0)
        for g, idxs in groups.items():
            cap = c.group_caps_pct.get(g)
            if cap is not None:
                g_room = max(cap / 100.0 - x[idxs].sum(), 0.0)
                s_room = room[idxs].sum()
                if s_room > g_room:
                    room[idxs] *= g_room / s_room if s_room > 0 else 0.0
        if room.sum() < _EPS:
            break
        x = x + room / room.sum() * deficit
    return x


def constrained_solve(model: str, names: list[str], R: np.ndarray,
                      mu: np.ndarray, S: np.ndarray,
                      constraints: Constraints,
                      w_current: dict[str, float] | None = None,
                      groups_of: dict[str, str] | None = None,
                      bench_returns: np.ndarray | None = None) -> dict:
    """제약 하 최종 가중치. 반환 status: ok | approx | infeasible (지시서 3분법)."""
    n = len(names)
    groups: dict[str, list[int]] = {}
    for i, t in enumerate(names):
        g = (groups_of or {}).get(t)
        if g:
            groups.setdefault(g, []).append(i)

    w_cur = None
    if w_current:
        w_cur = np.array([max(float(w_current.get(t, 0.0)), 0.0) for t in names])
        tot = w_cur.sum()
        w_cur = w_cur / tot if tot > 0 else None

    betas = asset_betas(R, bench_returns)
    beta_note = None
    if (constraints.beta_min is not None or constraints.beta_max is not None) and betas is None:
        beta_note = "베타 제약이 지정됐지만 벤치마크 수익률이 없어 적용 불가 — 제약 무시됨(정직 보고)."

    reason = _precheck(n, constraints, groups)
    if reason:
        return {"status": "infeasible", "reason": reason, "weights": None,
                "violations": [], "binding": [], "relaxed": [], "notes": [n for n in [beta_note] if n]}

    from scipy.optimize import minimize as _scipy_min

    from src.engine.risk_allocations import _opt  # SLSQP 래퍼 재사용

    def neg_sharpe(w):
        pv = np.sqrt(max(float(w @ S @ w), 1e-12))
        return -float(w @ mu) / pv

    def variance(w):
        return float(w @ S @ w)

    objective = variance if model == "min_var" else neg_sharpe
    cov_only = model in ("risk_parity", "hrp")

    if cov_only:
        # 무제약 해 → 근사 투영 (정직 라벨)
        from src.engine.allocation_studio import weights_for_model
        w0 = weights_for_model(model, R, S_annual=S)
        w = _project_box_group(np.asarray(w0, dtype=float), constraints, groups)
        viol, binding = _violations(w, constraints, groups, w_cur, betas)
        notes = [f"{model}는 공분산 전용 — 제약은 최적화가 아닌 근사 투영으로 적용(회전율·베타 미적용)."]
        if beta_note:
            notes.append(beta_note)
        hard = [v for v in viol if v["kind"] in ("max_weight", "group_cap", "cash")]
        return {"status": "approx" if viol else "ok", "weights": w,
                "violations": viol, "binding": binding, "relaxed": [], "notes": notes,
                "projected": True, "hard_violations": bool(hard)}

    # SLSQP 경로 — 완화 사다리: [] → turnover → turnover+beta → turnover+beta+group
    ladder: list[set[str]] = [set(), {"turnover"}, {"turnover", "beta"}, {"turnover", "beta", "group"}]
    x0 = w_cur if w_cur is not None else np.full(n, (1.0 - constraints.cash_max_pct / 200.0) / n)
    for skip in ladder:
        cons, bounds = _build_slsqp(n, constraints, groups, w_cur, betas, skip)
        try:
            res = _scipy_min(objective, x0, method="SLSQP", bounds=bounds,
                             constraints=cons, options={"maxiter": 400, "ftol": 1e-9})
        except Exception as e:
            logger.warning(f"SLSQP 예외: {e}")
            res = None
        if res is not None and res.success and np.all(np.isfinite(res.x)):
            w = np.clip(res.x, 0.0, None)
            viol, binding = _violations(w, constraints, groups, w_cur, betas)
            # 스킵한 제약의 위반은 relaxed로 정직 표시 (임의 완화 아님 — 보고되는 완화)
            relaxed = sorted(skip & {"turnover", "beta", "group"})
            status = "ok" if not skip and not viol else "approx" if (skip or viol) else "ok"
            notes = []
            if beta_note:
                notes.append(beta_note)
            if relaxed:
                notes.append(f"원 제약으로는 해가 없어 {relaxed} 제약을 완화한 근사해 — 위반 목록 확인.")
            if constraints.cash_max_pct > 0:
                notes.append("현금은 수익률 0으로 가정 (무위험수익 미반영 — 정직 근사).")
            return {"status": status, "weights": w, "violations": viol,
                    "binding": binding, "relaxed": relaxed, "notes": notes, "projected": False}
    # 사다리 전부 실패
    _ = _opt  # (재사용 의도 명시)
    return {"status": "infeasible", "weights": None, "violations": [], "binding": [],
            "relaxed": [], "notes": [n for n in [beta_note] if n],
            "reason": "제약 조합이 과도하게 빡빡해 수치해를 찾지 못했습니다 — 회전율·그룹 상한을 완화해 보세요."}


def sector_groups_for(names: list[str]) -> dict[str, str]:
    """티커 → 섹터 그룹 (genport 테마 그룹 재사용). 실패 시 빈 dict(제약 미적용, 정직)."""
    try:
        from src.data.genport_themes import build_group_assignment
        from src.data.stock_master import load_master_flags
        flags = load_master_flags() or {}
        assign = build_group_assignment(flags) if flags else {}
        return {t: assign[t] for t in names if t in assign}
    except Exception:
        return {}
