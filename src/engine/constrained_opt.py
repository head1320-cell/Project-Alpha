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
    min_weight_pct: float = 0.0                  # 종목당 하한. **음수면 롱숏** (P3)
    group_caps_pct: dict[str, float] = field(default_factory=dict)   # 그룹명 → 상한%
    turnover_cap_pct: float | None = None        # 0.5·Σ|w−w_cur| ≤ cap%
    beta_min: float | None = None
    beta_max: float | None = None
    cash_min_pct: float = 0.0
    cash_max_pct: float = 0.0                    # 0이면 완전투자 (기존 동작 보존)
    # ── 노출 제약 (P3) ──────────────────────────────────────────────────────
    # ★롱숏에서 `Σw` 하나로는 포지션 크기를 말할 수 없다★ 롱 100/숏 0 과
    # 롱 150/숏 50 은 넷이 똑같이 100% 지만 전혀 다른 포트폴리오다.
    #   · gross_max_pct — Σ|w| 상한. 130/30 을 표현하는 유일한 방법(=160).
    #   · net_min/max_pct — Σw 범위. **음수 허용**. 달러중립은 0±tol.
    # `cash_min/max_pct` 도 Σw 를 제약하지만 "현금" 이라는 롱온리 어휘이고
    # 음수를 표현할 수 없다. 롱숏에서는 net 을 쓰고, 둘 다 주면 net 이 이긴다.
    gross_max_pct: float | None = None
    net_min_pct: float | None = None
    net_max_pct: float | None = None

    def any_active(self) -> bool:
        # ★`!= 0` 이다 (P3)★ 예전에는 `min_weight_pct > 0` 이라, 음수 하한만 준 요청은
        # "제약 없음" 으로 판정돼 `constrained_solve` 를 아예 타지 않았다 — 롱숏을
        # 지시했는데 조용히 롱온리 무제약 해가 나가는 경로였다.
        return (self.max_weight_pct is not None or self.min_weight_pct != 0
                or bool(self.group_caps_pct) or self.turnover_cap_pct is not None
                or self.beta_min is not None or self.beta_max is not None
                or self.cash_min_pct > 0 or self.cash_max_pct > 0
                or self.gross_max_pct is not None
                or self.net_min_pct is not None or self.net_max_pct is not None)

    def allows_short(self) -> bool:
        """음수 하한이 곧 롱숏 의사표시다 — 별도 플래그를 만들지 않는다.

        플래그를 따로 두면 `allow_short=True, min_weight_pct=0` 같은 모순 상태가
        생기고, 둘 중 무엇이 진실인지 물어야 한다. 하한 하나가 단일 진실이다.
        """
        return self.min_weight_pct < 0


def asset_betas(R: np.ndarray, bench: np.ndarray | None) -> np.ndarray | None:
    """자산별 시장 베타 (bench 일수익률 대비 OLS). bench 없으면 None."""
    if bench is None or len(bench) != R.shape[0] or np.std(bench) < 1e-12:
        return None
    b = np.asarray(bench, dtype=float)
    var = float(np.var(b, ddof=1))
    return np.array([float(np.cov(R[:, i], b, ddof=1)[0, 1]) / var for i in range(R.shape[1])])


def _precheck(n: int, c: Constraints, groups: dict[str, list[int]]) -> str | None:
    """구조적 infeasible을 사람 언어로. None이면 통과."""
    if c.net_min_pct is not None or c.net_max_pct is not None:
        invest_min = (c.net_min_pct / 100.0) if c.net_min_pct is not None else -1e9
        invest_max = (c.net_max_pct / 100.0) if c.net_max_pct is not None else 1e9
        if invest_min > invest_max + _EPS:
            return "넷 노출 밴드가 뒤집혀 있습니다 (min > max)."
    else:
        invest_min = 1.0 - c.cash_max_pct / 100.0
        invest_max = 1.0 - c.cash_min_pct / 100.0
        if invest_min > invest_max + _EPS:
            return "현금 밴드가 뒤집혀 있습니다 (min > max)."

    if c.gross_max_pct is not None:
        gross_cap = c.gross_max_pct / 100.0
        if gross_cap <= _EPS:
            return "gross 노출 상한이 0 입니다 — 아무것도 보유할 수 없습니다."
        # Σ|w| ≥ |Σw| 는 항등식이다. 넷 밴드가 통째로 gross 상한 밖이면 구조적 불능.
        need = min(abs(invest_min), abs(invest_max)) if invest_min * invest_max > 0 else 0.0
        if need > gross_cap + _EPS:
            return (f"gross 상한 {c.gross_max_pct}% 로는 요구 넷 노출을 만들 수 없습니다 "
                    f"(Σ|w| ≥ |Σw| 이므로 gross 는 넷의 절대값 이상이어야 합니다).")
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
    # ── 넷 노출 (P3) ────────────────────────────────────────────────────────
    # `net_min/max_pct` 가 주어지면 그것이 이긴다 — 현금 어휘는 롱온리 전용이고
    # 음수 넷(숏 우위)을 표현할 수 없다. 안 주면 기존 현금 밴드 그대로(동작 불변).
    if c.net_min_pct is not None or c.net_max_pct is not None:
        invest_min = (c.net_min_pct / 100.0) if c.net_min_pct is not None else -np.inf
        invest_max = (c.net_max_pct / 100.0) if c.net_max_pct is not None else np.inf
    else:
        invest_min = 1.0 - c.cash_max_pct / 100.0
        invest_max = 1.0 - c.cash_min_pct / 100.0
    if np.isfinite(invest_min):
        cons.append({"type": "ineq", "fun": lambda w, lo=invest_min: np.sum(w) - lo})
    if np.isfinite(invest_max):
        cons.append({"type": "ineq", "fun": lambda w, hi=invest_max: hi - np.sum(w)})

    # ── gross 노출 Σ|w| ≤ cap (P3) ─────────────────────────────────────────
    # ★|·| 는 0 에서 미분 불가라 SLSQP 가 죽는다★ 회전율 제약이 이미 쓰는
    # 평활화 √(x²+δ) 를 그대로 따른다(같은 파일 아래 turnover 항 참고) —
    # 새 기법이 아니라 이 파일의 기존 관례다.
    if c.gross_max_pct is not None:
        cons.append({"type": "ineq",
                     "fun": (lambda w, cap=c.gross_max_pct / 100.0:
                             cap - float(np.sum(np.sqrt(w ** 2 + 1e-10))))})
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
    # ★부호를 가리지 않는다 (P3)★ 예전에는 `lb > 0` 일 때만 검사해서, 음수 하한을
    # 준 롱숏 요청은 하한을 뚫어도 위반이 보고되지 않았다 — 가드가 없는 제약이었다.
    if np.any(w < lb - _BIND_TOL):
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

    # ── 노출 제약 (P3) ──────────────────────────────────────────────────────
    # ★보고되지 않는 제약은 제약이 아니다★ `_build_slsqp` 이 거는 것은 전부 여기서
    # 위반이 잡혀야 한다. 완화 사다리가 제약을 스킵했을 때 그 사실이 드러나는 곳도 여기다.
    net = float(np.sum(w)) * 100
    gross = float(np.sum(np.abs(w))) * 100

    if c.gross_max_pct is not None:
        if gross > c.gross_max_pct + _BIND_TOL * 100:
            viol.append({"kind": "gross", "detail": f"gross 노출 {round(gross, 1)}% > 상한 {c.gross_max_pct}%",
                         "amount_pct": round(gross - c.gross_max_pct, 2)})
        elif abs(gross - c.gross_max_pct) < _BIND_TOL * 100:
            binding.append(f"gross 상한 {c.gross_max_pct}%")

    if c.net_min_pct is not None or c.net_max_pct is not None:
        # 넷 밴드를 쓰면 현금 어휘는 적용하지 않는다 — 같은 Σw 를 두 번 판정하면
        # 롱숏에서 "현금이 밴드 밖" 이라는 뜻 없는 위반이 항상 붙는다.
        if c.net_max_pct is not None and net > c.net_max_pct + _BIND_TOL * 100:
            viol.append({"kind": "net", "detail": f"넷 노출 {round(net, 1)}% > 상한 {c.net_max_pct}%",
                         "amount_pct": round(net - c.net_max_pct, 2)})
        elif c.net_max_pct is not None and abs(net - c.net_max_pct) < _BIND_TOL * 100:
            binding.append(f"넷 상한 {c.net_max_pct}%")
        if c.net_min_pct is not None and net < c.net_min_pct - _BIND_TOL * 100:
            viol.append({"kind": "net", "detail": f"넷 노출 {round(net, 1)}% < 하한 {c.net_min_pct}%",
                         "amount_pct": round(c.net_min_pct - net, 2)})
    else:
        cash = 100.0 - net
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

    short_ok = constraints.allows_short()

    w_cur = None
    if w_current:
        # ★롱숏에서는 현재 비중의 숏을 지우지 않는다 (P3)★ 예전에는 항상
        # `max(w, 0.0)` 이라, 숏을 들고 있는 상태에서 회전율 제약이 "그 숏은 원래
        # 없었다" 고 보고 회전율을 과소 계산했다. 정규화도 넷 합으로 나누면
        # 달러중립(Σw≈0)에서 폭발하므로 gross 로 나눈다.
        raw = np.array([float(w_current.get(t, 0.0)) for t in names])
        if short_ok:
            gross = float(np.abs(raw).sum())
            w_cur = raw / gross if gross > 0 else None
        else:
            raw = np.maximum(raw, 0.0)
            tot = raw.sum()
            w_cur = raw / tot if tot > 0 else None

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
        # ★롱숏을 요청받았는데 이 두 모델은 구조적으로 못 한다 — 조용히 롱온리를
        # 돌려주지 않고 거부한다 (P3)★ ERC 는 각 자산의 위험기여가 양수여야 정의되고
        # (음수 비중이면 기여 부호가 뒤집혀 "균등 기여" 가 뜻을 잃는다), HRP 는 트리를
        # 따라 **양의 예산**을 쪼개 내려간다. 여기서 `_project_box_group` 이 어차피
        # `clip(w, 0, None)` 을 하므로, 거부하지 않으면 사용자는 롱숏을 지시하고
        # 롱온리 결과를 받으면서 그 사실을 모른다.
        if short_ok:
            return {"status": "infeasible", "weights": None, "violations": [], "binding": [],
                    "relaxed": [], "notes": [n for n in [beta_note] if n],
                    "reason": (f"{model} 는 공분산 전용 모델이라 롱숏(음수 하한)을 지원하지 않습니다 — "
                               "ERC 는 위험기여가 양수여야 정의되고 HRP 는 양의 예산을 분할합니다. "
                               "롱숏이 필요하면 mvo · bl · min_var · max_div · min_cvar 를 쓰세요.")}
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
            # ★이 클램프가 P3 의 핵심 결함이었다★ `np.clip(res.x, 0.0, None)` 은
            # 음수를 **거르는** 게 아니라 해를 **망가뜨린다**. SLSQP 는 하한이
            # 음수일 때 Σw=1 을 정확히 지키는 롱숏 해를 내는데(실측: lb=-10% →
            # w=[.6,-.1,-.1,.1,.6,-.1], Σw=1.0000), 음수를 0 으로 올리면 그 합이
            # 1.3 으로 깨진다. 그러면 `_violations` 가 현금 위반을 잡아 `approx` 를
            # 찍는다 — **클램프가 스스로 만든 위반을 클램프가 보고**하고 있었다.
            # 롱온리(하한 ≥ 0)에서는 SLSQP 해가 이미 bounds 안이라 클립이 무의미한
            # 방어였고, 지금도 수치 잔차만 정리하도록 그대로 둔다.
            w = res.x if short_ok else np.clip(res.x, 0.0, None)
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
