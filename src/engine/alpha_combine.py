"""다중 알파 결합 + **중복 진단** (P2-C)
==============================================================================
알파 팩토리가 공장이려면 알파 하나를 돌리는 것만으로는 부족하다 — 여러 알파를 섞을 수
있어야 하고, 섞을 때 **그것들이 사실상 같은 베팅인지** 말해 줘야 한다.

★왜 상관을 함께 내는가★
알파 3개를 25/25/50 으로 배합했는데 셋이 전부 모멘텀 계열이면, 사용자는 분산했다고
믿지만 실제로는 한 베팅에 100% 를 건 것이다. 이 저장소에는 `collinearity_analyzer` 가
있지만 그것은 스크리너 후처리용이고 **팩터 필드**의 상관을 본다 — 알파끼리 겹치는지는
아무도 묻지 않았다.

★합치지 않고 나란히 낸다★
A8 이 세 국면 도구(축·Markov·GMM)를 하나의 점수로 평균 내지 않은 것과 같은 원칙이다.
결합 점수도 내고, 상관행렬도 내고, 유효 알파 수도 낸다. 불일치가 정보다.

★커버리지 부족 알파는 조용히 빼지 않는다★
빼고 나머지 가중치를 재정규화하면 사용자가 지정한 배합과 **다른 것**이 계산된다.
제외된 알파와 사유를 함께 내고, 남은 가중치는 **원래 값 그대로** 쓴다.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.engine.alpha_lab import MIN_NAMES, _cs_rank, score_alpha

logger = logging.getLogger(__name__)

# 이 이상이면 "사실상 같은 베팅" 으로 경고한다. 0.8 은 관례적 임계이고, 임계 자체보다
# **값과 쌍을 함께 보여 주는 것**이 요점이다 — 사용자가 자기 기준으로 판단할 수 있게.
DUP_RHO = 0.8


def _rank_map(scores: dict[str, float], names: list[str]) -> np.ndarray:
    """공통 종목 축 위에서 크로스섹션 rank([0,1]) 로 정규화.

    ★스케일이 다른 알파를 그냥 더하지 않는다★ `zscore(...)` 와 `rank(...)` 를 그대로
    합하면 분산이 큰 쪽이 배합을 먹는다 — 사용자가 준 가중치가 무의미해진다.
    """
    return _cs_rank(np.array([scores[n] for n in names], dtype=float))


def pairwise_rank_corr(rank_by_alpha: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """모든 알파 쌍의 순위상관. 표본이 모자라거나 분산이 0 이면 **사유와 함께 None**."""
    ids = list(rank_by_alpha)
    out: list[dict[str, Any]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = rank_by_alpha[ids[i]], rank_by_alpha[ids[j]]
            if len(a) < 3 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
                out.append({"a": ids[i], "b": ids[j], "rho": None,
                            "reason": "분산이 0 이거나 표본이 3 미만이라 상관을 정의할 수 없습니다."})
                continue
            rho = float(np.corrcoef(a, b)[0, 1])
            out.append({"a": ids[i], "b": ids[j], "rho": round(rho, 4),
                        "duplicate": abs(rho) >= DUP_RHO})
    return out


def effective_n_alphas(rank_by_alpha: dict[str, np.ndarray]) -> float | None:
    """유효 알파 수 — 상관행렬 고유값의 참여율 (participation ratio).

        n_eff = (Σλ)² / Σλ²

    완전 무상관 k개면 k, 완전히 같은 k개면 1. "3개를 넣었는데 유효 1.2" 라는 문장이
    가능해지는 것이 이 숫자의 목적이다.
    """
    ids = list(rank_by_alpha)
    if len(ids) < 2:
        return float(len(ids))
    M = np.vstack([rank_by_alpha[i] for i in ids])
    if M.shape[1] < 3:
        return None
    if any(np.std(M[k]) < 1e-12 for k in range(M.shape[0])):
        return None
    C = np.corrcoef(M)
    ev = np.linalg.eigvalsh(C)
    ev = np.clip(ev, 0.0, None)
    denom = float((ev ** 2).sum())
    if denom <= 0:
        return None
    return round(float(ev.sum() ** 2 / denom), 2)


def combine_alphas(specs: list[dict[str, Any]], tickers: list[str],
                   as_of: str | None = None, price_loader=None) -> dict[str, Any]:
    """여러 알파 → 결합 점수 + 상관 진단.

    Args:
        specs: `[{alpha_id, expr, weight}]` — weight 는 상대값(합이 1일 필요 없음).

    Returns:
        `{available, as_of_effective, scores, used, excluded, pairwise,
          effective_n, warnings}` 또는 `{available: False, reason}`.
    """
    if not specs:
        return {"available": False, "reason": "결합할 알파가 없습니다."}

    # ★같은 알파를 두 번 받으면 거부한다 (실측으로 찾은 결함)★
    # `scored` 는 alpha_id 로 키를 잡으므로 중복이 들어오면 **뒤엣것이 앞엣것을 덮어**
    # 조용히 하나로 합쳐졌다. 가중치 1+1 을 지정했는데 실제로는 1 로 계산되고, 화면은
    # 그 사실을 알 길이 없다 — 방금 가드를 세운 "조용한 재정규화" 와 같은 결함 계열이다.
    # 의도를 추측해 합치지 않고, 무엇이 중복인지 적어 되돌려 준다.
    ids_seen = [str(s.get("alpha_id") or s.get("expr", "")) for s in specs]
    dup_ids = sorted({i for i in ids_seen if ids_seen.count(i) > 1})
    if dup_ids:
        return {"available": False,
                "reason": (f"같은 알파가 여러 번 들어 있습니다: {', '.join(dup_ids)} — "
                           "가중치를 합칠지 하나로 볼지는 추측하지 않습니다. "
                           "한 항목으로 정리한 뒤 다시 시도하세요.")}

    scored: dict[str, dict] = {}
    excluded: list[dict[str, Any]] = []
    as_of_eff: str | None = None

    for sp in specs:
        aid = str(sp.get("alpha_id") or sp.get("expr", ""))
        res = score_alpha(str(sp.get("expr", "")), tickers, as_of=as_of,
                          price_loader=price_loader)
        as_of_eff = res.get("as_of_effective") or as_of_eff
        if not res.get("available"):
            # ★제외하되 사유를 남기고, 나머지 가중치는 재정규화하지 않는다★
            excluded.append({"alpha_id": aid, "reason": res.get("reason") or "산출 불가"})
            continue
        scored[aid] = {"scores": res["scores"], "weight": float(sp.get("weight", 1.0))}

    if not scored:
        return {"available": False, "as_of_effective": as_of_eff,
                "reason": "모든 알파가 산출 불가입니다.", "excluded": excluded}

    # 공통 종목 = 살아남은 알파 전부가 점수를 가진 종목. 교집합을 쓰는 이유는, 어떤
    # 알파에만 있는 종목을 0 으로 채우면 그 알파가 "최하위" 라고 말한 것이 되기 때문이다.
    common = set.intersection(*[set(v["scores"]) for v in scored.values()])
    names = sorted(common)
    if len(names) < MIN_NAMES:
        return {"available": False, "as_of_effective": as_of_eff, "excluded": excluded,
                "reason": (f"알파들이 공통으로 점수를 가진 종목이 {len(names)}개 "
                           f"(<{MIN_NAMES}) — 유니버스나 필드 커버리지가 부족합니다.")}

    rank_by_alpha = {aid: _rank_map(v["scores"], names) for aid, v in scored.items()}

    # 가중합 — ★재정규화하지 않는다★ 지정한 배합 그대로 쓰되, 합이 0 이면 거부한다.
    wsum = sum(v["weight"] for v in scored.values())
    if abs(wsum) < 1e-12:
        return {"available": False, "as_of_effective": as_of_eff, "excluded": excluded,
                "reason": "가중치 합이 0 입니다 — 배합을 정의할 수 없습니다."}
    combo = np.zeros(len(names), dtype=float)
    for aid, v in scored.items():
        combo += rank_by_alpha[aid] * v["weight"]
    combo /= wsum

    pw = pairwise_rank_corr(rank_by_alpha)
    n_eff = effective_n_alphas(rank_by_alpha)

    warnings: list[str] = []
    dups = [p for p in pw if p.get("duplicate")]
    for p in dups:
        warnings.append(
            f"{p['a']} 와 {p['b']} 의 순위상관이 {p['rho']:+.2f} 입니다 — "
            "사실상 같은 베팅이라 분산 효과가 거의 없습니다.")
    if n_eff is not None and len(scored) >= 2 and n_eff < len(scored) * 0.7:
        warnings.append(
            f"알파 {len(scored)}개를 넣었지만 유효 알파 수는 {n_eff} 입니다 — "
            "겹치는 만큼 실제 분산은 그보다 적습니다.")
    if excluded:
        warnings.append(
            f"{len(excluded)}개 알파가 산출 불가로 제외됐습니다 — "
            "남은 가중치는 재정규화하지 않았으므로 배합 비율이 의도와 다를 수 있습니다.")

    return {
        "available": True,
        "as_of_requested": as_of,
        "as_of_effective": as_of_eff,
        "scores": {n: float(v) for n, v in zip(names, combo)},
        "used": [{"alpha_id": aid, "weight": v["weight"]} for aid, v in scored.items()],
        "excluded": excluded,
        "universe": names,
        "pairwise": pw,
        "effective_n": n_eff,
        "warnings": warnings,
    }
