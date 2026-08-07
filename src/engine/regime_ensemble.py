"""
Regime Ensemble — 국면 확률을 **여러 도구로 따로** 산출한다 (A7)
==========================================================================
지금까지 국면 확률의 출처는 하나였다: `regime_axes.quadrant_probs` —
성장·물가 축에 독립 가우시안 CDF 를 씌운 파라메트릭 방법. 잘 동작하지만
**한 가지 가정만** 본다(축이 정규분포이고 서로 독립이다).

여기서는 산업 표준 도구 둘을 나란히 붙인다:

  · axis     기존 `quadrant_probs` — 축 z + 불확실성 se
  · markov   `statsmodels.tsa.regime_switching.MarkovRegression`
             Hamilton(1989) 상태전환 모형. **전이확률 행렬**을 준다 — 국면이
             얼마나 지속되는지, 어디로 갈 확률이 높은지가 여기서 나온다.
  · cluster  `sklearn.mixture.GaussianMixture`
             (성장, 물가) 좌표를 라벨 없이 군집화 — 사전에 정한 사분면 경계를
             쓰지 않고 데이터가 스스로 뭉치는 모양을 본다.

★세 결과를 하나로 합치지 않는다★
평균을 내면 "어느 모형이 무슨 말을 했는가" 가 사라진다. 세 방법이 갈릴 때
그 불일치 자체가 정보다 — 축은 Goldilocks 인데 상태전환 모형은 아직
Reflation 에 머물러 있다면, 그건 "국면 전환 초입" 이라는 뜻이지 평균값이
가리키는 어중간한 지점이 아니다. 그래서 병렬로 돌려주고 `agreement` 로
일치 여부만 계산한다.

★미가용은 날조하지 않는다★
statsmodels/sklearn 미설치, 표본 부족, 미수렴은 각각
`{"available": False, "reason": ...}` 로 돌려준다 — `causal_graph.py:52` 가
statsmodels 미가용에 쓰는 것과 같은 규약. 0 이나 균등분포로 채우지 않는다.
"""

from __future__ import annotations

import logging
import warnings

from src.engine.regime_axes import AXES, compute_axis_detail, quadrant, quadrant_probs

logger = logging.getLogger(__name__)

# 4국면 고정 순서 — 전이행렬의 행/열 순서이자 UI 의 노드 순서다.
REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]

# 상태전환·군집 모형이 신뢰할 만한 최소 표본. 이보다 적으면 적합하지 않고
# 그 사실을 적는다 — 6개월치로 4국면을 추정하면 숫자는 나오지만 의미가 없다.
MIN_OBS = 36


def _axis_history(series_map: dict, market: str, months: int) -> tuple[list[float], list[float]]:
    """성장·물가 축의 월별 시계열 (과거 → 현재).

    `macro_visuals.axis_history` 와 같은 방식(`back=k`)이다. 그쪽은 지표별 기여
    스택을 만들고 여기서는 스코어만 필요해서 축 두 줄만 뽑는다.
    """
    g_def, i_def = AXES.get(market, AXES["kr"])
    g_hist: list[float] = []
    i_hist: list[float] = []
    for k in range(months - 1, -1, -1):
        g_hist.append(compute_axis_detail(series_map, g_def, back=k)["score"])
        i_hist.append(compute_axis_detail(series_map, i_def, back=k)["score"])
    return g_hist, i_hist


def _axis_probs(series_map: dict, market: str) -> dict:
    """도구 1 — 기존 축-확률. 새로 만들지 않고 그대로 쓴다."""
    g_def, i_def = AXES.get(market, AXES["kr"])
    g = compute_axis_detail(series_map, g_def)
    i = compute_axis_detail(series_map, i_def)
    if not g["components"] and not i["components"]:
        return {"available": False,
                "reason": "성장·물가 축을 만들 지표가 하나도 없습니다"}
    probs = quadrant_probs(g["score"], i["score"], g["se"], i["se"])
    return {
        "available": True, "method": "axis",
        "probs": probs,
        "argmax": max(probs, key=probs.get),
        "detail": {"growth": g["score"], "inflation": i["score"],
                   "se_growth": g["se"], "se_inflation": i["se"]},
        "note": "성장·물가 축 z 와 그 불확실성(se)에 독립 가우시안 CDF — 사분면 곱",
    }


def _markov_probs(g_hist: list[float], i_hist: list[float]) -> dict:
    """도구 2 — Hamilton 상태전환 모형.

    성장축을 관측 계열로 두고 2-상태 MarkovRegression 을 적합한다. 2상태를 쓰는
    이유: 4상태는 월 데이터 수십 개로는 거의 항상 미수렴하거나 한 상태가 비고,
    그러면 '나온 숫자' 가 노이즈다. 2상태(확장/수축)를 추정한 뒤 물가축의 부호와
    교차해 4국면으로 편다 — 상태전환이 실제로 말해 주는 것은 **성장 국면의
    지속성**이고, 물가는 축이 이미 잘 재고 있다.

    전이행렬은 그대로 돌려준다 — UI 의 전이 그래프가 이걸 그린다.
    """
    n = len(g_hist)
    if n < MIN_OBS:
        return {"available": False,
                "reason": f"표본 {n}개월 — 상태전환 추정에는 최소 {MIN_OBS}개월이 필요합니다"}
    try:
        import numpy as np
        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    except Exception:
        return {"available": False, "reason": "statsmodels 미설치 — 상태전환 모형을 돌릴 수 없습니다"}

    try:
        y = np.asarray(g_hist, dtype=float)
        if not np.isfinite(y).all() or float(np.std(y)) < 1e-9:
            return {"available": False,
                    "reason": "성장축이 상수이거나 결측 — 상태를 구분할 변동이 없습니다"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = MarkovRegression(y, k_regimes=2, trend="c", switching_variance=True).fit(disp=False)
        smoothed = np.asarray(res.smoothed_marginal_probabilities)   # (T, k)
        p_state = [float(smoothed[-1, s]) for s in range(2)]
        # 평균이 높은 상태를 '확장' 으로 — 라벨은 데이터가 정한다(순서 가정 금지).
        #
        # ★`res.params` 를 이름으로 찾지 않는다★ 입력이 numpy 배열이면 statsmodels 는
        # params 를 **ndarray** 로 준다(pandas Series 가 아니다) — `.index` 가 없어서
        # AttributeError 가 났다. 어느 쪽이든 통하도록, 상태별 평균은 평활확률로 가중한
        # y 의 가중평균으로 직접 구한다. 모형 내부 파라미터 이름에 기대지 않는 편이
        # statsmodels 버전이 바뀌어도 안전하다.
        means = []
        for s in range(2):
            w = smoothed[:, s]
            wsum = float(w.sum())
            means.append(float((y * w).sum() / wsum) if wsum > 1e-9 else 0.0)
        exp_s = int(means[1] > means[0])
        p_expand = p_state[exp_s]
        # 물가 방향은 축이 이미 재고 있다 — 마지막 값의 부호를 쓴다.
        infl_up = (i_hist[-1] if i_hist else 0.0) >= 0
        probs = {
            "Reflation":    p_expand if infl_up else 0.0,
            "Goldilocks":   0.0 if infl_up else p_expand,
            "Stagflation":  (1 - p_expand) if infl_up else 0.0,
            "Disinflation": 0.0 if infl_up else (1 - p_expand),
        }
        trans = res.regime_transition
        # (k, k, 1) 또는 (k, k) — 시간불변이면 마지막 축이 1이다.
        tm = trans[:, :, -1] if getattr(trans, "ndim", 2) == 3 else trans
        return {
            "available": True, "method": "markov",
            "probs": {k: round(v, 4) for k, v in probs.items()},
            "argmax": max(probs, key=probs.get),
            "detail": {
                "k_regimes": 2, "n_obs": n,
                "p_expansion": round(p_expand, 4),
                "inflation_up": bool(infl_up),
                # 전이행렬 P[i][j] = 상태 i → j. 지속성 = 대각.
                "transition": [[round(float(tm[a][b]), 4) for b in range(2)] for a in range(2)],
                "expansion_state": exp_s,
                "persistence": round(float(tm[exp_s][exp_s]), 4),
            },
            "note": "Hamilton 상태전환(2상태, 성장축) × 물가축 부호. 전이확률은 성장 상태 기준.",
        }
    except Exception as e:                                   # noqa: BLE001
        logger.info("markov 국면 적합 실패: %s", e)
        return {"available": False, "reason": f"상태전환 모형이 수렴하지 않았습니다 ({type(e).__name__})"}


def _cluster_probs(g_hist: list[float], i_hist: list[float]) -> dict:
    """도구 3 — 가우시안 혼합 군집.

    (성장, 물가) 좌표를 4개 성분으로 군집화하고, 각 성분의 **중심 좌표**로 국면
    이름을 붙인다. 사분면 경계(0)를 미리 긋지 않고 데이터가 뭉치는 곳을 본다 —
    축이 0 근처에서 흔들릴 때 축-확률과 갈라지는 지점이 여기다.
    """
    n = len(g_hist)
    if n < MIN_OBS:
        return {"available": False,
                "reason": f"표본 {n}개월 — 군집 추정에는 최소 {MIN_OBS}개월이 필요합니다"}
    try:
        import numpy as np
        from sklearn.mixture import GaussianMixture
    except Exception:
        return {"available": False, "reason": "scikit-learn 미설치 — 군집 모형을 돌릴 수 없습니다"}

    try:
        X = np.column_stack([np.asarray(g_hist, float), np.asarray(i_hist, float)])
        if not np.isfinite(X).all():
            return {"available": False, "reason": "축 시계열에 결측이 있어 군집화할 수 없습니다"}
        k = min(4, max(2, n // 12))          # 표본이 적으면 성분도 줄인다
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gm = GaussianMixture(n_components=k, covariance_type="full",
                                 random_state=0, n_init=3).fit(X)
        resp = gm.predict_proba(X[-1].reshape(1, -1))[0]
        probs = dict.fromkeys(REGIMES, 0.0)
        for c in range(k):
            gc, ic = float(gm.means_[c][0]), float(gm.means_[c][1])
            probs[quadrant(gc, ic)] += float(resp[c])
        tot = sum(probs.values()) or 1.0
        probs = {kk: round(v / tot, 4) for kk, v in probs.items()}
        return {
            "available": True, "method": "cluster",
            "probs": probs,
            "argmax": max(probs, key=probs.get),
            "detail": {
                "n_components": k, "n_obs": n,
                "centers": [{"growth": round(float(m[0]), 3), "inflation": round(float(m[1]), 3),
                             "regime": quadrant(float(m[0]), float(m[1]))} for m in gm.means_],
                "converged": bool(gm.converged_),
            },
            "note": "가우시안 혼합 — 성분 중심의 사분면으로 라벨링, 현재 좌표의 소속확률",
        }
    except Exception as e:                                   # noqa: BLE001
        logger.info("cluster 국면 적합 실패: %s", e)
        return {"available": False, "reason": f"군집 모형 적합 실패 ({type(e).__name__})"}


def regime_ensemble(series_map: dict, market: str = "kr", months: int = 60) -> dict:
    """세 도구를 나란히 — 합치지 않는다.

    반환의 `agreement` 는 **합의된 답이 아니라** 세 argmax 가 같은지 여부다.
    갈릴 때 어느 쪽을 믿을지는 사람이 정한다.
    """
    g_hist, i_hist = _axis_history(series_map, market, months)
    tools = {
        "axis": _axis_probs(series_map, market),
        "markov": _markov_probs(g_hist, i_hist),
        "cluster": _cluster_probs(g_hist, i_hist),
    }
    picks = {k: v.get("argmax") for k, v in tools.items() if v.get("available")}
    agree = len(set(picks.values())) == 1 if picks else None
    return {
        "market": market, "months": months, "n_obs": len(g_hist),
        "regimes": REGIMES,
        "tools": tools,
        "agreement": {
            "unanimous": agree,
            "picks": picks,
            "note": ("세 방법이 같은 국면을 가리킵니다" if agree
                     else "방법마다 다른 국면을 가리킵니다 — 전환 초입일 수 있습니다"
                     if picks else "사용 가능한 도구가 없습니다"),
        },
        "note": "세 방법을 평균내지 않습니다. 불일치 자체가 정보이며, 하나로 합치면 어느 모형이 무엇을 말했는지 사라집니다.",
    }
