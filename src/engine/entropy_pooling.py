"""Entropy Pooling — 사전분포에 뷰를 **최소한으로** 반영한다 (M1-T)
==============================================================================
Meucci 의 Entropy Pooling: 시장 사전분포 `p` 를 유지하면서 뷰 제약만 만족시키는
사후분포 `q` 를 찾는다. 목적은 KL 발산 최소화 —

    min_q  Σ q_j ln(q_j / p_j)
    s.t.   E_q[G x] ≤ b   (부등식 뷰)
           E_q[H x] = c   (등식 뷰)
           Σ q_j = 1,  q ≥ 0

**왜 이것을 쓰는가** — Black-Litterman 은 정규성을 가정하고 μ 만 섞는다. Entropy
Pooling 은 분포 전체를 다루면서 "뷰가 요구하는 것 이상은 바꾸지 않는다" 를 수학적으로
보장한다. 뷰의 신뢰도가 낮으면 사후는 사전에 가깝고, 회전율이 그만큼 작다.

★cvxpy 없이 짓는다★
------------------------------------------------------------------------------
요청받은 스택은 cvxpylayers 를 쓰지만 이 환경에 cvxpy·cvxpylayers 는 없다. 그런데
Entropy Pooling 은 **쌍대에서 저차원 볼록 문제**라 numpy/scipy 로 충분하다:

    q(λ) ∝ p · exp(-λᵀg)          (사후는 λ 의 지수족)
    최소화 f(λ) = ln Z(λ) + λᵀb   (Z = Σ p exp(-λᵀg))
    ∇f = b − E_q[g],  ∇²f = Cov_q[g]

미지수는 시나리오 수가 아니라 **제약 수**다(보통 한 자릿수). 부등식 뷰는 λ ≥ 0 으로
묶는다. 즉 cvxpy 도입은 이 문제를 위해서는 필요하지 않다 — 그 사실을 재서 적는다.

★정직성 — 실현 불가능을 성공으로 위장하지 않는다★
------------------------------------------------------------------------------
뷰가 서로 모순이면 최적화는 λ 를 무한대로 밀며 "수렴한 것처럼" 끝난다. 그 결과를
그대로 돌려주면 화면에는 그럴듯한 사후분포가 뜬다. 그래서 **풀고 나서 제약을 실제로
검사**하고, 위반이면 `feasible: false` + 어느 제약이 얼마나 어긋났는지 답한다.

그리고 유효 시나리오 수(ENS = exp(엔트로피))를 함께 낸다. ENS 가 붕괴하면 사후가
소수 시나리오에 몰린 것이고, 그건 "뷰가 사전분포보다 강하다" 는 신호다 — 숫자는
멀쩡해 보여도 통계적으로는 표본 하나에 기대는 상태다.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 제약 위반 허용치 (절대). 수치 최적화의 잔차와 진짜 위반을 가른다.
_FEAS_TOL = 1e-6


def _posterior(p: np.ndarray, g: np.ndarray, lam: np.ndarray) -> np.ndarray:
    """q(λ) ∝ p · exp(-λᵀg). log-sum-exp 로 안정화한다."""
    z = -(g @ lam)                      # (n,)
    z -= z.max()                        # 오버플로 방지 — 정규화로 상쇄된다
    w = p * np.exp(z)
    s = w.sum()
    if not np.isfinite(s) or s <= 0:
        # 수치가 무너진 경우. 사전분포를 돌려주고 호출자가 판정하게 한다.
        return p.copy()
    return w / s


def entropy_pool(
    prior: np.ndarray,
    *,
    ineq: tuple[np.ndarray, np.ndarray] | None = None,
    eq: tuple[np.ndarray, np.ndarray] | None = None,
    max_iter: int = 500,
) -> dict[str, Any]:
    """사전분포 + 뷰 → 사후분포.

    Args:
        prior: (n,) 시나리오 확률. 합이 1 이 아니면 정규화한다.
        ineq:  (G, b) — `G` 는 (n, k) 시나리오별 뷰 함수값, `E_q[G] ≤ b`.
        eq:    (H, c) — `E_q[H] = c`.

    Returns:
        `{available, feasible, posterior, kl, ens, ens_prior, violations, note}`.
        실현 불가능이면 `posterior` 는 **가장 가까운 시도**이고 `feasible: false` 와
        위반 목록이 함께 온다 — 조용히 성공으로 바꾸지 않는다.
    """
    p = np.asarray(prior, dtype=float).ravel()
    n = p.size
    if n == 0:
        return {"available": False, "reason": "사전분포가 비어 있습니다."}
    if np.any(p < 0):
        return {"available": False, "reason": "사전분포에 음수 확률이 있습니다."}
    tot = p.sum()
    if not np.isfinite(tot) or tot <= 0:
        return {"available": False, "reason": "사전분포의 합이 0 이거나 유한하지 않습니다."}
    p = p / tot

    blocks: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    lower: list[float] = []
    n_ineq = 0
    if ineq is not None:
        G = np.atleast_2d(np.asarray(ineq[0], dtype=float))
        if G.shape[0] != n:
            G = G.T
        b = np.asarray(ineq[1], dtype=float).ravel()
        if G.shape[0] != n or G.shape[1] != b.size:
            return {"available": False,
                    "reason": f"부등식 뷰의 모양이 맞지 않습니다: G{G.shape}, b{b.shape}"}
        blocks.append(G); targets.append(b)
        lower += [0.0] * b.size          # λ ≥ 0 — 부등식은 한쪽으로만 민다
        n_ineq = b.size
    if eq is not None:
        H = np.atleast_2d(np.asarray(eq[0], dtype=float))
        if H.shape[0] != n:
            H = H.T
        c = np.asarray(eq[1], dtype=float).ravel()
        if H.shape[0] != n or H.shape[1] != c.size:
            return {"available": False,
                    "reason": f"등식 뷰의 모양이 맞지 않습니다: H{H.shape}, c{c.shape}"}
        blocks.append(H); targets.append(c)
        lower += [-np.inf] * c.size      # 등식은 양방향

    ens_prior = float(np.exp(-np.sum(p * np.log(np.maximum(p, 1e-300)))))
    if not blocks:
        # 뷰가 없으면 사후 = 사전. 이것은 실패가 아니라 **정답**이다.
        return {"available": True, "feasible": True, "posterior": p.tolist(),
                "kl": 0.0, "ens": ens_prior, "ens_prior": ens_prior,
                "violations": [], "n_views": 0,
                "note": "뷰가 없어 사후분포가 사전분포와 같습니다."}

    g = np.hstack(blocks)                # (n, k)
    t = np.concatenate(targets)          # (k,)
    k = t.size

    def dual(lam: np.ndarray) -> tuple[float, np.ndarray]:
        z = -(g @ lam)
        m = z.max()
        w = p * np.exp(z - m)
        s = w.sum()
        if not np.isfinite(s) or s <= 0:
            return 1e18, np.zeros(k)
        logZ = float(np.log(s) + m)
        q = w / s
        return logZ + float(lam @ t), t - (q @ g)

    try:
        from scipy.optimize import minimize
        res = minimize(dual, np.zeros(k), jac=True, method="L-BFGS-B",
                       bounds=[(lo, None) for lo in lower],
                       options={"maxiter": max_iter, "ftol": 1e-12, "gtol": 1e-10})
        lam = np.asarray(res.x, dtype=float)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"쌍대 최적화가 실패했습니다: {e}"}

    q = _posterior(p, g, lam)
    achieved = q @ g

    # ★풀고 나서 실제로 검사한다★ 모순된 뷰는 λ 를 밀며 "수렴한 것처럼" 끝난다.
    violations: list[dict[str, Any]] = []
    for i in range(k):
        is_ineq = i < n_ineq
        gap = float(achieved[i] - t[i])
        bad = gap > _FEAS_TOL if is_ineq else abs(gap) > _FEAS_TOL
        if bad:
            violations.append({
                "index": i, "kind": "ineq" if is_ineq else "eq",
                "target": float(t[i]), "achieved": float(achieved[i]),
                "gap": gap,
            })

    kl = float(np.sum(q * np.log(np.maximum(q, 1e-300) / np.maximum(p, 1e-300))))
    ens = float(np.exp(-np.sum(q * np.log(np.maximum(q, 1e-300)))))

    note = None
    if violations:
        note = ("뷰를 동시에 만족시키는 분포가 없습니다 — 아래 제약이 어긋난 채로 "
                "가장 가까운 해를 돌려줍니다. 이 사후분포로 배분하지 마세요.")
    elif ens < 0.1 * ens_prior:
        # ★숫자가 멀쩡해도 통계적으로는 표본 몇 개에 기대는 상태다★
        note = (f"유효 시나리오 수가 {ens_prior:.0f} → {ens:.0f} 로 붕괴했습니다 — "
                "뷰가 사전분포보다 강합니다. 신뢰도를 낮추거나 뷰를 완화하세요.")

    return {
        "available": True,
        "feasible": not violations,
        "posterior": q.tolist(),
        "kl": kl,
        "ens": ens,
        "ens_prior": ens_prior,
        "violations": violations,
        "n_views": k,
        "converged": bool(getattr(res, "success", False)),
        "note": note,
    }


def pool_weights(prior_scenarios: np.ndarray, prior: np.ndarray | None = None,
                 *, views: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """자산 수익률 시나리오 + "자산 i 의 기대수익 ≥ x" 형태의 뷰 → 사후 기대수익.

    `views` 항목: `{"asset": int, "direction": +1|-1, "value": float}`
      · `+1` → `E_q[r_i] ≥ value`  (내부적으로 `-r_i ≤ -value`)
      · `-1` → `E_q[r_i] ≤ value`

    ★뷰를 부등식으로 두는 이유★ "기대수익이 정확히 8%" 라고 말할 수 있는 사람은 없다.
    등식 뷰는 그 주장을 강제해 사후를 과하게 비튼다. 방향과 하한/상한이 실제로
    말할 수 있는 것이다.
    """
    R = np.atleast_2d(np.asarray(prior_scenarios, dtype=float))
    n, m = R.shape
    p = (np.full(n, 1.0 / n) if prior is None
         else np.asarray(prior, dtype=float).ravel())

    rows: list[np.ndarray] = []
    tgts: list[float] = []
    for v in views or []:
        i = int(v["asset"])
        if not (0 <= i < m):
            return {"available": False, "reason": f"뷰가 없는 자산을 가리킵니다: {i}"}
        d = 1 if int(v.get("direction", 1)) >= 0 else -1
        val = float(v["value"])
        # d=+1 → E[r_i] ≥ val → -E[r_i] ≤ -val
        rows.append(-d * R[:, i])
        tgts.append(-d * val)

    out = entropy_pool(p, ineq=(np.column_stack(rows), np.array(tgts)) if rows else None)
    if not out.get("available"):
        return out
    q = np.asarray(out["posterior"], dtype=float)
    out["prior_mean"] = (p @ R).tolist()
    out["posterior_mean"] = (q @ R).tolist()
    return out
