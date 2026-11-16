"""
Regime Ensemble — 국면 확률을 **여러 도구로 따로** 산출한다 (A7)
==========================================================================
지금까지 국면 확률의 출처는 하나였다: `regime_axes.quadrant_probs` —
성장·물가 축에 독립 가우시안 CDF 를 씌운 파라메트릭 방법. 잘 동작하지만
**한 가지 가정만** 본다(축이 정규분포이고 서로 독립이다).

여기서는 산업 표준 도구를 나란히 붙인다:

  · axis     기존 `quadrant_probs` — 축 z + 불확실성 se
  · markov   `statsmodels.tsa.regime_switching.MarkovRegression`
             Hamilton(1989) 상태전환 모형. **전이확률 행렬**을 준다 — 국면이
             얼마나 지속되는지, 어디로 갈 확률이 높은지가 여기서 나온다.
  · cluster  `sklearn.mixture.GaussianMixture`
             (성장, 물가) 좌표를 라벨 없이 군집화 — 사전에 정한 사분면 경계를
             쓰지 않고 데이터가 스스로 뭉치는 모양을 본다.
  · kmeans   `sklearn.cluster.KMeans` (M1 · 2026-11-16)
             같은 좌표를 딱딱한 군집으로 — 소속 확률이 없어 ★값은 시드 비율★이다.

★방법끼리는 하나로 합치지 않는다★
평균을 내면 "어느 모형이 무슨 말을 했는가" 가 사라진다. 방법이 갈릴 때
그 불일치 자체가 정보다 — 축은 Goldilocks 인데 상태전환 모형은 아직
Reflation 에 머물러 있다면, 그건 "국면 전환 초입" 이라는 뜻이지 평균값이
가리키는 어중간한 지점이 아니다. 그래서 병렬로 돌려주고 `agreement` 로
일치 여부만 계산한다.

★한 방법 안의 시드는 모은다(설계 D5)★
군집 두 팔은 시작점이 난수라 같은 자료에서도 시드마다 답이 갈린다 — 재 본 것(설계 §2): mock 축 kr
60개월에서 GMM 은 시드 0 이 Goldilocks, 30개 가운데 24개는 Reflation 이었다. 시드 하나의 답은
우연이라, 시드 `0 … SEEDS−1` 의 평균(GMM) · 비율(k-평균)을 팔의 답으로 내고 시드마다의 답이 얼마나
모이는지를 `stability` 로 함께 낸다. ★이것은 같은 자료에서 같은 답이 나오는가(전달 안정성)에 답할 뿐,
어느 팔이 맞는지는 말하지 않는다.★

★미가용은 날조하지 않는다★
statsmodels/sklearn 미설치, 표본 부족, 미수렴은 각각
`{"available": False, "reason": ...}` 로 돌려준다 — `causal_graph.py:52` 가
statsmodels 미가용에 쓰는 것과 같은 규약. 0 이나 균등분포로 채우지 않는다.
"""

from __future__ import annotations

import logging
import warnings

from src.engine.regime_axes import AXES, compute_axis_detail, quadrant, quadrant_probs
from src.engine.regime_probability import USAGE_DIAGNOSTIC
from src.engine.regime_transitions import regime_path

#: ★이 앙상블은 배분에 흘러들지 않는다 — 그 사실을 페이로드가 직접 말한다★
#:
#: 그 사실은 `regime_probability.from_axis`/`from_markov` 의 독스트링에만 있었고,
#: 라우트 응답만 보는 사람에게는 보이지 않았다. 그래서 "Markov 팔이 포트폴리오를
#: 움직인다" 는 오해가 실제로 생겼다 — 하중을 받는 것은 `regime_path` 다.
USAGE_NOTE = (
    "★배분에 쓰이지 않습니다 — 진단 전용입니다★ 포트폴리오로 가는 국면은 "
    "`regime_transitions.regime_path()` 이고, 그 산출이 "
    "`conditional_market.conditional_moments` 로 들어갑니다. 여기 네 팔(축·Markov·"
    "GMM·k-평균)은 '지금 어디인가' 에 답하지 '보유기간 동안 어디일까' 에 답하지 않습니다."
)

logger = logging.getLogger(__name__)

# 4국면 고정 순서 — 전이행렬의 행/열 순서이자 UI 의 노드 순서다.
REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]

# 상태전환·군집 모형이 신뢰할 만한 최소 표본. 이보다 적으면 적합하지 않고
# 그 사실을 적는다 — 6개월치로 4국면을 추정하면 숫자는 나오지만 의미가 없다.
MIN_OBS = 36

#: 군집 두 팔(GMM · k-평균)을 다시 적합하는 난수 시드 수 — ★설정값이다(재 본 값이 아니다)★.
#: 바꾸면 `tests/test_regime_seed_stability.py` 의 손 계산도 함께 바뀐다.
SEEDS = 10

#: 합의(`macro_routes.regime_consensus_view`)가 군집 두 팔이 함께 답했을 때 붙이는 문장.
CLUSTER_DEPENDENCE_NOTE = ("군집 두 방법(GMM · k-평균)은 같은 좌표를 묶는 방법이라 서로 독립이 아닙니다. "
                           "다수의 수를 독립된 표의 수로 읽지 않습니다.")

#: 서버가 화면으로 보내는 문장의 팔 이름 — 캔버스 해설 둘(국면 앙상블 · 국면 합의도)과 합의 문장이 이 표 하나를 쓴다.
TOOL_NAMES = {"axis": "성장·물가 축", "markov": "상태 전환 모형",
              "cluster": "군집 모형(GMM)", "kmeans": "군집 모형(k-평균)"}

#: ★흔들리는 팔 위의 만장일치★ 답이 모두 같아도(`unanimous` 는 사실 그대로 참) 시드별 최다 답이 과반이 아닌 팔이
#: 있으면 그 만장일치는 시드 하나만 바꿔도 깨질 수 있다 — 문장이 그 단서를 단다(M1 · 개발 자료 us 60개월에서 관측).
UNSTABLE_QUALIFIER = "다만 난수 시드에 따라 답이 갈리는 방법이 있습니다"


def unstable_arms(tools: dict) -> list[str]:
    """시드로 다시 적합한 팔 가운데 시드별 최다 답이 과반이 아닌 것(가용한 것만 · 도구 순서대로)."""
    return [k for k, t in tools.items()
            if t.get("available") and (t.get("stability") or {}).get("stable") is False]


def _complete_history(series_map: dict, market: str, months: int) -> tuple[list[float], list[float], int]:
    """성장·물가 축의 월별 시계열 (과거 → 현재) — ★두 축이 다 계산된 달만★ + 뺀 달의 수.

    `regime_transitions.regime_path` 의 점을 그대로 쓴다(같은 `back=k` 계산 · 국면 예측 비교 M2 와 같은 입력).
    ★0 으로 채우지 않는다(M1b)★ 예전에는 성분이 없는 달의 점수(`compute_axis_detail` 의 빈 값 0.0)를 그대로 넣어
    (0, 0) — 사분면으로 Reflation — 이 Markov · 군집 두 팔의 적합에 들어갔다. 계산되지 않은 달은 미상이지 중립값이 아니다.
    """
    rp = regime_path(series_map, market=market, months=months)
    points = rp.get("points") or []
    dropped = int((rp.get("span") or {}).get("dropped_incomplete") or 0)
    return [float(p["growth"]) for p in points], [float(p["inflation"]) for p in points], dropped


def _axis_probs(series_map: dict, market: str) -> dict:
    """도구 1 — 기존 축-확률. 새로 만들지 않고 그대로 쓴다."""
    g_def, i_def = AXES.get(market, AXES["kr"])
    g = compute_axis_detail(series_map, g_def)
    i = compute_axis_detail(series_map, i_def)
    if not g["components"] and not i["components"]:
        return {"available": False,
                "reason": "성장·물가 축을 구성할 지표가 없습니다"}
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
                # ★방향에 주의★ statsmodels 의 `regime_transition` 은 **열이 출발**이다:
                # `P[j][i] = 상태 i → j`. 그래서 합이 1인 것은 행이 아니라 **열**이고,
                # `test_transition_matrix_is_a_probability_matrix` 가 그걸 못박고 있다.
                # (이 주석은 한때 `P[i][j] = i → j` 라고 반대로 적혀 있었고, 그걸 읽은
                #  프론트가 전이 방향을 뒤집어 그렸다 — 대각은 어느 쪽이든 같아서
                #  화면으로는 티가 나지 않는 종류의 결함이다.)
                "transition": [[round(float(tm[a][b]), 4) for b in range(2)] for a in range(2)],
                "expansion_state": exp_s,
                "persistence": round(float(tm[exp_s][exp_s]), 4),
                # 방향이 헷갈릴 수 없는 이름으로 한 번 더 준다 — 소비자가 열/행 규약을
                # 다시 추론하지 않아도 되도록. 위 행렬에서 파생되므로 진실은 하나다.
                "p_exp_to_con": round(float(tm[1 - exp_s][exp_s]), 4),
                "p_con_to_exp": round(float(tm[exp_s][1 - exp_s]), 4),
            },
            "note": "Hamilton 상태전환(2상태, 성장축) × 물가축 부호. 전이확률은 성장 상태 기준.",
        }
    except Exception as e:                                   # noqa: BLE001
        logger.info("markov 국면 적합 실패: %s", e)
        return {"available": False, "reason": f"상태전환 모형이 수렴하지 않았습니다 ({type(e).__name__})"}


def _cluster_k(n: int) -> int:
    """성분(군집) 수 — 표본이 적으면 줄인다. 군집 두 팔이 같은 규칙을 쓴다."""
    return min(4, max(2, n // 12))


def _centers(means) -> list[dict]:
    return [{"growth": round(float(m[0]), 3), "inflation": round(float(m[1]), 3),
             "regime": quadrant(float(m[0]), float(m[1]))} for m in means]


def _stability(picks: list[str]) -> dict:
    """시드마다의 답 → 얼마나 모이는가.

    `modal` 은 가장 많이 나온 국면(동수면 `REGIMES` 순서의 앞 — `max` 는 동수에서 앞의 것을 돌려준다) ·
    `agree` 는 그 수 · `shares` 는 국면별 비율 · `stable` 은 ★엄격한 과반★(`agree × 2 > seeds` — 10개 중
    5개는 과반이 아니다).

    ★재는 것은 난수 시드에 대한 민감도뿐이다★ — 자료가 조금 달라질 때(측정 오차 · 개정) 같은 답이 나오는지는
    재지 않는다. 답을 반올림이 정하는 자료(원 위의 점 + 가운데 점)를 1e-12 만큼 흔든 30개에서 '과반'이 GMM 10개 ·
    k-평균 14개였고, 흔들지 않은 원 하나는 BLAS 커널에 따라 4/10 과 6/10 으로 갈렸다(M1c · 잰 값 ·
    `tests/test_regime_seed_stability.py` 가 그 한계를 건다). 캔버스 해설은 이것을 '재지 않은 것'으로 적는다.
    """
    seeds = len(picks)
    counts = {r: picks.count(r) for r in REGIMES}
    modal = max(REGIMES, key=counts.__getitem__)
    return {"seeds": seeds, "modal": modal, "agree": counts[modal],
            "shares": {r: round(counts[r] / seeds, 4) for r in REGIMES},
            "stable": counts[modal] * 2 > seeds}


def _cluster_probs(g_hist: list[float], i_hist: list[float]) -> dict:
    """도구 3 — 가우시안 혼합 군집.

    (성장, 물가) 좌표를 4개 성분으로 군집화하고, 각 성분의 **중심 좌표**로 국면
    이름을 붙인다. 사분면 경계(0)를 미리 긋지 않고 데이터가 뭉치는 곳을 본다 —
    축이 0 근처에서 흔들릴 때 축-확률과 갈라지는 지점이 여기다.

    ★시드 평균(설계 D5)★ 시드 `0 … SEEDS−1` 로 같은 설정(성분 수 규칙 · full · n_init 3)을 다시 적합해
    시드마다 마지막 점의 소속 확률을 사분면으로 모은 뒤 **평균**한다. 성분 번호가 아니라 중심의 사분면으로
    모으므로 시드마다 성분 순서가 달라도(라벨 뒤바뀜) 평균이 섞이지 않는다. `detail` 의 중심은 시드 0 의 것이라
    이름에 그렇게 적는다.
    """
    n = len(g_hist)
    if n < MIN_OBS:
        return {"available": False,
                "reason": f"표본 {n}개월 — 군집 추정에는 최소 {MIN_OBS}개월이 필요합니다"}
    try:
        # threadpoolctl 은 scikit-learn 의 의존성이다(함께 깔린다).
        import numpy as np
        from sklearn.mixture import GaussianMixture
        from threadpoolctl import threadpool_limits
    except Exception:
        return {"available": False, "reason": "scikit-learn 미설치 — 군집 모형을 돌릴 수 없습니다"}

    try:
        X = np.column_stack([np.asarray(g_hist, float), np.asarray(i_hist, float)])
        if not np.isfinite(X).all():
            return {"available": False, "reason": "축 시계열에 결측이 있어 군집화할 수 없습니다"}
        k = _cluster_k(n)                    # 표본이 적으면 성분도 줄인다
        per_seed: list[dict[str, float]] = []
        picks: list[str] = []
        converged = True
        centers0: list[dict] = []
        # ★스레드 하나로★ 2차원 작은 자료에서는 BLAS·OpenMP 스레드가 일보다 비싸다(잰 것: 60개월 한 번 적합
        # 약 55ms → 약 20ms · 반복 횟수는 같다). 스레드 수를 고정하면 기계마다 합산 순서도 같아진다.
        # 이 제한은 프로세스 전체에 걸린다 — 그 사이(수백 ms) 다른 요청의 행렬 계산도 한 스레드로 돈다(값은 같고 속도만).
        with threadpool_limits(limits=1):
            for s in range(SEEDS):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    gm = GaussianMixture(n_components=k, covariance_type="full",
                                         random_state=s, n_init=3).fit(X)
                resp = gm.predict_proba(X[-1].reshape(1, -1))[0]
                p = dict.fromkeys(REGIMES, 0.0)
                for c in range(k):
                    p[quadrant(float(gm.means_[c][0]), float(gm.means_[c][1]))] += float(resp[c])
                tot = sum(p.values()) or 1.0
                p = {r: v / tot for r, v in p.items()}
                per_seed.append(p)
                picks.append(max(REGIMES, key=p.__getitem__))
                converged = converged and bool(gm.converged_)
                if s == 0:
                    centers0 = _centers(gm.means_)
        probs = {r: round(sum(p[r] for p in per_seed) / SEEDS, 4) for r in REGIMES}
        return {
            "available": True, "method": "cluster", "probs_kind": "probability",
            "probs": probs,
            "argmax": max(REGIMES, key=probs.__getitem__),
            "stability": _stability(picks),
            "detail": {
                "n_components": k, "n_obs": n,
                "centers_seed0": centers0,
                "converged": converged,
            },
            "note": f"가우시안 혼합 — 성분 중심의 사분면으로 라벨링, 현재 좌표의 소속확률을 난수 시드 {SEEDS}개로 평균",
        }
    except Exception as e:                                   # noqa: BLE001
        logger.info("cluster 국면 적합 실패: %s", e)
        return {"available": False, "reason": f"군집 모형 적합 실패 ({type(e).__name__})"}


def _kmeans_probs(g_hist: list[float], i_hist: list[float]) -> dict:
    """도구 4 — k-평균(Lloyd · 시작점 `n_init` 10)을 시드마다 → 마지막 점이 속한 중심의 사분면 (M1).

    ★값은 확률이 아니라 시드 비율이다★ 한 번의 k-평균은 점을 한 군집에 딱 붙일 뿐 소속 확률을 내지 않는다.
    그래서 시드 `0 … SEEDS−1` 가운데 그 국면을 고른 비율을 내고 `probs_kind: "seed_share"` 로 적는다 —
    화면도 확률이라고 부르지 않는다. GMM 팔과 같은 좌표를 묶으므로 두 팔은 서로 독립이 아니다
    (합의가 그 사실을 함께 적는다 — `CLUSTER_DEPENDENCE_NOTE`).
    """
    n = len(g_hist)
    if n < MIN_OBS:
        return {"available": False,
                "reason": f"표본 {n}개월 — k-평균 군집에는 최소 {MIN_OBS}개월이 필요합니다"}
    try:
        # threadpoolctl 은 scikit-learn 의 의존성이다(함께 깔린다).
        import numpy as np
        from sklearn.cluster import KMeans
        from threadpoolctl import threadpool_limits
    except Exception:
        return {"available": False, "reason": "scikit-learn 미설치 — k-평균 군집을 돌릴 수 없습니다"}

    try:
        X = np.column_stack([np.asarray(g_hist, float), np.asarray(i_hist, float)])
        if not np.isfinite(X).all():
            return {"available": False, "reason": "축 시계열에 결측이 있어 군집화할 수 없습니다"}
        k = _cluster_k(n)
        picks: list[str] = []
        centers0: list[dict] = []
        with threadpool_limits(limits=1):                # GMM 팔과 같은 까닭
            for s in range(SEEDS):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    km = KMeans(n_clusters=k, n_init=10, random_state=s).fit(X)
                c = km.cluster_centers_[int(km.predict(X[-1].reshape(1, -1))[0])]
                picks.append(quadrant(float(c[0]), float(c[1])))
                if s == 0:
                    centers0 = _centers(km.cluster_centers_)
        st = _stability(picks)
        return {
            "available": True, "method": "kmeans", "probs_kind": "seed_share",
            "probs": dict(st["shares"]),
            "argmax": st["modal"],
            "stability": st,
            "detail": {"n_clusters": k, "n_obs": n, "centers_seed0": centers0},
            "note": (f"k-평균(시작점 10개) — 현재 좌표가 속한 중심의 사분면을 난수 시드 {SEEDS}개로 센 비율입니다. "
                     "확률이 아닙니다."),
        }
    except Exception as e:                                   # noqa: BLE001
        logger.info("kmeans 국면 적합 실패: %s", e)
        return {"available": False, "reason": f"k-평균 군집 적합 실패 ({type(e).__name__})"}


def regime_ensemble(series_map: dict, market: str = "kr", months: int = 60) -> dict:
    """네 도구를 나란히 — 방법끼리 합치지 않는다.

    반환의 `agreement` 는 **합의된 답이 아니라** 가용한 argmax 가 모두 같은지 여부다.
    갈릴 때 어느 쪽을 믿을지는 사람이 정한다.
    """
    g_hist, i_hist, dropped = _complete_history(series_map, market, months)
    tools = {
        "axis": _axis_probs(series_map, market),
        "markov": _markov_probs(g_hist, i_hist),
        "cluster": _cluster_probs(g_hist, i_hist),
        "kmeans": _kmeans_probs(g_hist, i_hist),
    }
    picks = {k: v.get("argmax") for k, v in tools.items() if v.get("available")}
    agree = len(set(picks.values())) == 1 if picks else None
    unanimous_note = "모든 방법이 같은 국면을 가리킵니다"
    if agree and unstable_arms(tools):
        unanimous_note = f"{unanimous_note} — {UNSTABLE_QUALIFIER}"
    return {
        "market": market, "months": months, "n_obs": len(g_hist), "dropped_incomplete": dropped,
        "regimes": REGIMES,
        "tools": tools,
        "agreement": {
            "unanimous": agree,
            "picks": picks,
            "note": (unanimous_note if agree
                     else "방법마다 다른 국면을 가리킵니다 — 전환 초입일 수 있습니다"
                     if picks else "사용 가능한 도구가 없습니다"),
        },
        "note": ("방법끼리는 평균하지 않습니다. 불일치 자체가 정보이며, 하나로 결합하면 모형별 판정이 드러나지 않습니다. "
                 f"군집 두 방법은 한 방법 안에서만 난수 시드 {SEEDS}개의 답을 모읍니다."
                 + (f" 축이 둘 다 계산되지 않은 {dropped}개월은 빼고 셉니다(0 으로 채우지 않습니다)." if dropped else "")),
        # ★어휘를 두 벌 만들지 않는다★ `regime_probability` 의 상수를 그대로 쓴다.
        "usage": USAGE_DIAGNOSTIC,
        "usage_note": USAGE_NOTE,
    }
