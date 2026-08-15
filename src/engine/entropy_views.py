"""Entropy Pooling 을 **이 앱의 뷰**로 돌린다 — 세 번째 μ 엔진 (M2-A)
==============================================================================
M1-T 가 `entropy_pooling.py` 를 지었지만 배분 경로에는 소비자가 **0건**이었다. 화면에서
고를 수 있는 μ 엔진은 트레일링 평균(`mvo`)과 Black-Litterman(`bl`) 둘뿐이고, KL 최소화
사후분포는 어디로도 가지 않았다. 이 모듈이 그 간극만 닫는다.

★`pool_weights` 를 쓰지 않는 이유 (실측)★
------------------------------------------------------------------------------
`entropy_pooling.pool_weights` 의 뷰 스키마는 `{"asset": int, "direction", "value"}` —
**단일 자산**이다. 그런데 이 앱의 뷰는

    {"assets": ["005930", "000660"], "direction": 1,
     "magnitude_pct": 10.0, "confidence": 60}

인 **그룹 뷰**이고, `allocation_studio.build_user_views` 가 균등가중 피킹 행으로 P 를
만든다. 단일 자산 API 로는 그룹 뷰를 표현할 수 없다.

그래서 `entropy_pool(prior, ineq=(G, b))` 을 **직접** 부르되, `G` 를 BL 과 **같은 피커**
로 만든다. 그래야 두 엔진이 같은 뷰를 먹고 나란히 비교된다 — 나란히 놓는 것이 요점인데
입력이 다르면 그 비교 자체가 거짓이 된다.

★단위 함정 — 이 파일에서 가장 틀리기 쉬운 곳★
------------------------------------------------------------------------------
`build_user_views` 의 Q 는 **연간**(`magnitude_pct / 100`)이고 `optimize()` 는 공분산을
×252 로 연율화해 뷰와 단위를 맞춘다. 반면 `entropy_pool` 의 제약 `E_q[G] ≤ b` 는
**시나리오 행** 위에서 걸리는데 `R` 의 행은 **일간 수익률**이다.

그대로 넣으면 "연 10%" 뷰가 "일 10%" 제약이 되어 항상 실현 불가이거나 자명 충족이다.
그리고 실현 불가 쪽 실패는 화면에서 *"EP 가 사전분포를 그대로 돌려줬다"* 로 보여
**동작하는 것처럼 읽힌다.** 그래서 `G` 는 **연율화 시나리오**로 만든다:

    g_j = -d · (R @ p_j) · 252 ,   b_j = -mag

  · `d = +1` → `E_q[연율 수익] ≥ +mag`
  · `d = -1` → `E_q[연율 수익] ≤ -mag`

두 경우 모두 `b_j = -mag` 로 떨어지는 것이 부호 규약의 검산이다.

★confidence 는 쓰지 않는다 — 매핑을 지어내지 않는다★
------------------------------------------------------------------------------
BL 은 `confidence` 를 Ω(뷰 불확실성)로 매핑한다. EP 의 부등식 뷰는 **경성 제약**이라
대응하는 손잡이가 없다. 그럴듯한 변환을 만들어 붙이면 화면은 신뢰도가 반영된 것처럼
읽지만 실제로는 임의의 산수다. 대신 EP 자신의 정직성 신호를 그대로 낸다 —
`feasible` · `violations` · **ENS 붕괴**(사후 유효 시나리오 수가 무너지면 "뷰가
사전분포보다 강하다"). `confidence_used: False` 를 반환에 명시한다.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.engine.entropy_pooling import entropy_pool

logger = logging.getLogger(__name__)

# 일간 시나리오 → 연율. `allocation_studio.optimize` 가 공분산에 쓰는 값과 같아야 한다.
TRADING_DAYS = 252.0


class EPUnavailable(ValueError):
    """EP 가 μ 를 낼 수 없다.

    ★조용한 폴백 대신 예외를 던지는 이유★ 사용자가 EP 엔진을 **명시적으로 골랐다**.
    사전분포나 트레일링 평균으로 몰래 돌아가면 화면에는 "뷰가 반영된 EP 포트폴리오"가
    뜨는데 실제로는 뷰가 무시된 것이다 — 이 단계가 막으려는 결함 그 자체다.
    라우트가 사유와 함께 422 로 돌려준다(`compile_target` 의 ValueError→422 선례와 동일).
    """

    def __init__(self, reason: str, report: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.report = report or {}


def _pickers(views: list[dict] | None, names: list[str]):
    """뷰 → (피커행, 방향, 크기, 라벨) + 스킵 사유.

    `build_user_views`(allocation_studio.py:62)와 **같은 규칙**이다: 유니버스에 없는
    자산은 버리고, 남은 자산에 균등가중을 주고, 대상이 없거나 크기가 0 이면 조용히
    버리지 않고 스킵 목록으로 보고한다.
    """
    idx = {t: i for i, t in enumerate(names)}
    out: list[tuple[np.ndarray, float, float, str]] = []
    skipped: list[dict[str, Any]] = []
    for v in views or []:
        assets = [a for a in (v.get("assets") or []) if a in idx]
        mag = abs(float(v.get("magnitude_pct") or 0.0)) / 100.0
        if not assets or mag == 0.0:
            skipped.append({"view": v, "reason": "대상 자산 없음 또는 크기 0"})
            continue
        d = 1.0 if float(v.get("direction", 1)) >= 0 else -1.0
        row = np.zeros(len(names))
        for a in assets:
            row[idx[a]] = 1.0 / len(assets)
        out.append((row, d, mag, " · ".join(assets)))
    return out, skipped


def ep_posterior_mu(views: list[dict] | None, names: list[str],
                    R: np.ndarray) -> dict[str, Any]:
    """뷰 + 일간 수익률 시나리오 → **연율 사후 기대수익**.

    Returns:
        `{available, feasible, mu_annual, prior_mu_annual, kl, ens, ens_prior,
          n_views, skipped, violations, confidence_used, note}`
        또는 `{available: False, reason}`.

    뷰가 하나도 없으면 사후 = 사전이고 그것은 **정답**이다(실패가 아니다) — 그 경우
    `mu_annual` 은 균등가중 시나리오 평균, 즉 트레일링 평균과 같다.
    """
    Rm = np.atleast_2d(np.asarray(R, dtype=float))
    n_scen, m = Rm.shape
    if m != len(names):
        return {"available": False,
                "reason": f"수익률 행렬의 자산 수가 이름 수와 다릅니다: {m} vs {len(names)}"}
    if n_scen < 2:
        return {"available": False,
                "reason": f"시나리오가 {n_scen}개뿐입니다 — 사후분포를 정의할 수 없습니다."}

    picks, skipped = _pickers(views, names)
    p = np.full(n_scen, 1.0 / n_scen)
    prior_mu = (p @ Rm) * TRADING_DAYS

    if not picks:
        return {
            "available": True, "feasible": True,
            "mu_annual": prior_mu.tolist(), "prior_mu_annual": prior_mu.tolist(),
            "kl": 0.0, "ens": float(n_scen), "ens_prior": float(n_scen),
            "n_views": 0, "skipped": skipped, "violations": [],
            "confidence_used": False,
            "note": ("유효한 뷰가 없어 사후분포가 사전분포와 같습니다 — "
                     "기대수익은 트레일링 평균과 동일합니다."),
        }

    # ★연율화해서 제약을 건다★ 파일 상단의 단위 함정 참조.
    cols = [-d * (Rm @ row) * TRADING_DAYS for row, d, _mag, _lab in picks]
    b = np.array([-mag for _row, _d, mag, _lab in picks], dtype=float)

    res = entropy_pool(p, ineq=(np.column_stack(cols), b))
    if not res.get("available"):
        return res

    q = np.asarray(res["posterior"], dtype=float)
    mu = (q @ Rm) * TRADING_DAYS

    # ★위반을 사용자 용어로 번역한다★ `entropy_pool` 의 target/achieved 는 `-d·연율`
    # 변환 공간의 값이라 화면에 그대로 내면 부호가 뒤집힌 숫자가 보인다. 어느 뷰가,
    # 무엇을 요구했고, 실제로 얼마가 나왔는지로 되돌려 적는다.
    violations: list[dict[str, Any]] = []
    for v in res.get("violations", []):
        i = int(v["index"])
        row, d, mag, label = picks[i]
        violations.append({
            "view_index": i, "assets": label,
            "direction": int(d),
            "requested_pct": round(d * mag * 100.0, 4),
            "achieved_pct": round(float(q @ (Rm @ row)) * TRADING_DAYS * 100.0, 4),
            "gap_pct": round(float(v["gap"]) * 100.0, 4),
        })

    return {
        "available": True,
        "feasible": bool(res.get("feasible")),
        "mu_annual": mu.tolist(),
        "prior_mu_annual": prior_mu.tolist(),
        "kl": res.get("kl"),
        "ens": res.get("ens"),
        "ens_prior": res.get("ens_prior"),
        "n_views": len(picks),
        "skipped": skipped,
        "violations": violations,
        # ★신뢰도는 EP 가 쓰지 않는다★ 화면이 이 사실을 말할 수 있도록 플래그로 낸다.
        "confidence_used": False,
        "note": res.get("note"),
    }


def ep_mu_or_raise(views: list[dict] | None, names: list[str],
                   R: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """`ep_posterior_mu` + **실현 불가를 성공으로 넘기지 않는 관문**.

    Returns: `(mu_annual, report)`. 산출 불가·실현 불가면 `EPUnavailable`.
    """
    rep = ep_posterior_mu(views, names, R)
    if not rep.get("available"):
        raise EPUnavailable(
            f"엔트로피 풀링을 계산할 수 없습니다: {rep.get('reason') or '사유 미상'}", rep)
    if not rep.get("feasible"):
        detail = "; ".join(
            f"{v['assets']}: 요청 {v['requested_pct']:+.2f}% → 실제 {v['achieved_pct']:+.2f}%"
            for v in rep.get("violations", [])) or "위반 내역 없음"
        raise EPUnavailable(
            "뷰를 동시에 만족시키는 분포가 없습니다 — 이 배합으로는 배분하지 않습니다. "
            f"({detail})", rep)
    return np.asarray(rep["mu_annual"], dtype=float), rep
