"""
Regime Transitions — 국면 **전환 위험**을 베이지안으로 (A8)
==========================================================================
A7 이 0M 에 세 도구를 나란히 붙였지만 화면이 말하는 것은 결론뿐이었다:
"골디락스 91%". 다음 달에 다른 국면으로 넘어갈 위험이 얼마인지는 없었다.
동적 자산배분에 실제로 쓰이는 숫자가 바로 그것이다
(Kritzman·Page·Turkington 이 쓰는 지속성/전이 위험의 형태).

★왜 경험적 카운트(MLE)가 아닌가★
축으로 분류한 월별 국면 경로에서 i→j 를 그냥 세면 편향은 없지만 분산이 크다.
이 저장소의 실측 표본은 **월 60개, YoY 변환 후 실사용 48개**이고 한 국면이
대부분을 차지한다. 그러면 희소한 행은 관측이 1~2개뿐이라 MLE 가 100% 같은
점추정을 내놓는다 — 그 숫자는 정보가 아니라 잡음이다.

★왜 4상태 HMM(hmmlearn)이 아닌가 — 재서 기각했다★
4상태 Gaussian HMM 은 평균 8 + 공분산 12 + 전이 12 ≈ **32개 모수**다. 실사용
관측 48개에 32개 모수는 과적합이고, `regime_ensemble._markov_probs` 의 주석이
이미 "4상태는 월 데이터 수십 개로는 거의 항상 미수렴하거나 한 상태가 빈다"를
기록해 두고 있다. 수렴한 것처럼 보이는 4×4 행렬이 이 화면에서 가장 위험한 종류의
거짓이다 — 그럴듯할수록 그렇다. 표본이 늘면(실키로 FRED/ECOS 를 받으면) 재검토할
문제로 남긴다. hmmlearn 은 이 저장소에 설치돼 있지도 않다.

★그래서 Dirichlet-multinomial 사후분포★
각 행 i 는 `Dir(α_i + n_i)` 의 사후를 갖는다.
  · 표본이 얇으면 사후평균이 **사전분포로 수축**하고, 두꺼우면 MLE 로 간다 — 자동으로.
  · 셀마다 **신용구간**이 나온다. 모르는 만큼 구간이 넓어진다 — 점추정 하나를
    내놓고 침묵하는 것보다 정직하고, 실은 더 쓸모 있다.
  · k개월 후 분포를 사후예측으로 뽑으면 불확실성이 그대로 전파된다.
  · 행별 관측 수를 함께 돌려주므로 **수축이 감사 가능**하다.

주변분포가 Beta 이므로 신용구간은 `scipy.stats.beta.ppf` 로 **정확히** 구한다
(표본추출 근사가 아니다). k-step 만 Dirichlet 표본을 쓰고, 시드를 고정해 재현된다.
"""

from __future__ import annotations

import logging

from src.engine.regime_axes import AXES, compute_axis_detail, quadrant

logger = logging.getLogger(__name__)

REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]

# ── 사전분포 (약정보) ────────────────────────────────────────────────────────
# 대각에 더 큰 α — "국면은 지속되는 편" 이라는 잘 알려진 경험칙만 넣는다.
# 행 합 = 4+1+1+1 = 7 이므로 **사전 표본크기가 7개월**에 해당한다: 관측이 수십 개인
# 행에서는 데이터가 이기고, 관측이 0인 행에서는 사전분포가 그대로 남는다(그리고
# 그 사실을 `shrunk` 로 말한다). 사전평균 대각 = 4/7 ≈ 0.571.
ALPHA_DIAG = 4.0
ALPHA_OFF = 1.0

# 이 값 미만의 관측으로 만들어진 행은 "데이터가 말했다" 고 하지 않는다.
MIN_ROW_OBS = 5

CI = 0.90          # 신용구간 폭
FORECAST_DRAWS = 4000
SEED = 20260808    # 고정 — 같은 입력이면 같은 그림이 나와야 한다


def regime_path(series_map: dict, market: str = "kr", months: int = 60) -> dict:
    """월별 국면 경로 — 축이 **둘 다** 계산 가능한 달만.

    ★한쪽 축만 되는 달을 버리는 이유★
    `compute_axis_detail` 은 지표가 하나도 없으면 `score 0.0` 을 돌려준다. 그 0 을
    그대로 쓰면 `quadrant(0, i)` 가 "성장 ≥ 0" 으로 읽혀 Goldilocks/Reflation 으로
    **찍힌다**. 계산되지 않은 축을 중립값으로 오해하는 것이고, 그렇게 만든 라벨로
    전이를 세면 행렬 전체가 오염된다. 그래서 둘 다 성분이 있는 달만 남기고,
    몇 달을 왜 버렸는지 함께 돌려준다.
    """
    g_def, i_def = AXES.get(market, AXES["kr"])
    labels = _month_labels(series_map, months)

    points: list[dict] = []
    dropped = 0
    for idx, k in enumerate(range(months - 1, -1, -1)):
        g = compute_axis_detail(series_map, g_def, back=k)
        i = compute_axis_detail(series_map, i_def, back=k)
        if not g["components"] or not i["components"]:
            dropped += 1
            continue
        points.append({
            "t": labels[idx] if idx < len(labels) else f"T-{k}",
            "growth": g["score"], "inflation": i["score"],
            "regime": quadrant(g["score"], i["score"]),
        })

    first = points[0]["t"] if points else None
    last = points[-1]["t"] if points else None
    return {
        "market": market,
        "points": points,
        "span": {
            "first": first, "last": last,
            "n_months": len(points),
            "requested": months,
            # ★요청보다 짧으면 응답이 그 사실을 말한다★ 화면이 "10년" 이라고 쓰지
            # 못하게 하는 것이 이 필드의 목적이다.
            "truncated": len(points) < months,
            "dropped_incomplete": dropped,
        },
        "note": ("성장·물가 축이 **둘 다** 산출된 달만 분류했습니다. "
                 "한쪽만 있는 달은 나머지 축을 0(중립)으로 오해하게 되므로 제외합니다."),
    }


def _month_labels(series_map: dict, months: int) -> list[str]:
    """`macro_visuals._month_labels` 와 같은 규약 — 가장 긴 시계열의 마지막 months개."""
    best: list[str] = []
    for s in series_map.values():
        ts = [str(t)[:7] for t in (getattr(s, "timestamps", None) or [])]
        if len(ts) > len(best):
            best = ts
    if len(best) >= months:
        return best[-months:]
    # 시계열이 요청보다 짧다 — 있는 것을 뒤에 붙이고 앞은 T-k 로 둔다. 라벨을
    # 지어내지 않는다(날짜처럼 보이는 가짜 라벨이 span 정직성을 무너뜨린다).
    pad = months - len(best)
    return [f"T-{months - 1 - k}" for k in range(pad)] + best


def count_transitions(points: list[dict]) -> list[list[int]]:
    """i→j 전이 횟수 (연속한 두 달)."""
    idx = {r: n for n, r in enumerate(REGIMES)}
    counts = [[0] * 4 for _ in range(4)]
    for a, b in zip(points, points[1:]):
        ra, rb = idx.get(a["regime"]), idx.get(b["regime"])
        if ra is None or rb is None:
            continue
        counts[ra][rb] += 1
    return counts


def transition_posterior(counts: list[list[int]],
                         alpha_diag: float = ALPHA_DIAG,
                         alpha_off: float = ALPHA_OFF) -> list[dict]:
    """행별 Dirichlet 사후 — 평균 · 신용구간 · 관측수 · 수축 여부.

    주변분포가 Beta(a_j, A−a_j) 이므로 구간은 `beta.ppf` 로 정확히 구한다.
    """
    from scipy.stats import beta as beta_dist

    lo_q, hi_q = (1 - CI) / 2, 1 - (1 - CI) / 2
    rows: list[dict] = []
    for i, regime in enumerate(REGIMES):
        n_row = sum(counts[i])
        alphas = [(alpha_diag if j == i else alpha_off) + counts[i][j] for j in range(4)]
        A = sum(alphas)
        mean = [a / A for a in alphas]
        ci = [[float(beta_dist.ppf(lo_q, a, A - a)),
               float(beta_dist.ppf(hi_q, a, A - a))] for a in alphas]

        p_stay = mean[i]
        # 기대 지속기간 — 기하분포 평균. p_stay→1 이면 발산하므로 상한을 둔다.
        dur = None if p_stay >= 0.999 else 1.0 / (1.0 - p_stay)

        shrunk = n_row < MIN_ROW_OBS
        rows.append({
            "from": regime,
            "counts": counts[i],
            "n": n_row,
            # ★확률분포는 6자리로 낸다★ 4자리로 반올림했더니 행 합이 0.9999 가 되어
            # "행 합 = 1" 이 공개된 값에서 깨졌다. 테스트 허용오차를 늘리는 대신
            # 데이터가 불변식을 만족하게 한다 — 표시 정밀도(0~1자리 %)보다 훨씬
            # 촘촘하므로 화면에는 아무 차이가 없고, 스택 막대가 정확히 채워진다.
            "mean": {REGIMES[j]: round(mean[j], 6) for j in range(4)},
            "ci90": {REGIMES[j]: [round(ci[j][0], 4), round(ci[j][1], 4)] for j in range(4)},
            "expected_duration_months": round(dur, 1) if dur is not None else None,
            # ★사전분포를 데이터인 척 하지 않는다★
            "shrunk": shrunk,
            "reason": (f"이 국면에서 출발한 관측이 {n_row}개뿐입니다 "
                       f"(최소 {MIN_ROW_OBS}개). 값은 대부분 사전분포이며 "
                       f"구간이 넓은 것이 그 표시입니다." if shrunk else None),
        })
    return rows


def k_step_forecast(rows: list[dict], current: str, k: int = 3,
                    draws: int = FORECAST_DRAWS, seed: int = SEED) -> dict:
    """k개월 후 국면 분포 — 사후예측(불확실성 전파).

    행렬을 사후평균으로 한 번 거듭제곱하면 "모수를 안다" 고 가정하는 것이다.
    Dirichlet 사후에서 행렬 자체를 뽑아 매번 거듭제곱해야 얇은 행의 불확실성이
    k개월 뒤 분포까지 전달된다.
    """
    try:
        import numpy as np
    except Exception:
        return {"available": False, "reason": "numpy 미설치 — 사후예측을 계산할 수 없습니다"}
    if current not in REGIMES:
        return {"available": False, "reason": f"현재 국면 '{current}' 를 알 수 없습니다"}
    if k < 1:
        return {"available": False, "reason": "예측 기간은 1개월 이상이어야 합니다"}

    rng = np.random.default_rng(seed)
    # 사후 α 를 복원한다 (mean = α/Σα 이고 Σα 는 행마다 다르므로 counts 로 되짚는다).
    alphas = np.array([[(ALPHA_DIAG if j == i else ALPHA_OFF) + rows[i]["counts"][j]
                        for j in range(4)] for i in range(4)], dtype=float)

    start = np.zeros(4)
    start[REGIMES.index(current)] = 1.0
    out = np.zeros((draws, 4))
    for d in range(draws):
        P = np.vstack([rng.dirichlet(alphas[i]) for i in range(4)])
        v = start
        for _ in range(k):
            v = v @ P
        out[d] = v

    lo_q, hi_q = (1 - CI) / 2, 1 - (1 - CI) / 2
    mean = out.mean(axis=0)
    lo = np.quantile(out, lo_q, axis=0)
    hi = np.quantile(out, hi_q, axis=0)
    return {
        "available": True, "k": k, "from": current, "draws": draws,
        # 위와 같은 이유로 6자리 — 이것도 합이 1인 분포다.
        "mean": {REGIMES[j]: round(float(mean[j]), 6) for j in range(4)},
        "ci90": {REGIMES[j]: [round(float(lo[j]), 4), round(float(hi[j]), 4)] for j in range(4)},
        "note": (f"{k}개월 뒤 분포 — 전이행렬을 사후분포에서 {draws}회 뽑아 거듭제곱한 "
                 "사후예측입니다. 얇은 행의 불확실성이 여기까지 전달됩니다."),
    }


def current_run_length(points: list[dict]) -> int:
    """현재 국면이 몇 달째 연속인지 — 지속성의 가장 직관적인 표현."""
    if not points:
        return 0
    cur = points[-1]["regime"]
    n = 0
    for p in reversed(points):
        if p["regime"] != cur:
            break
        n += 1
    return n


def regime_occupancy(points: list[dict]) -> dict:
    """역사적 점유율 — 지금 국면이 희귀한지 흔한지."""
    if not points:
        return {r: 0.0 for r in REGIMES}
    total = len(points)
    out = {r: 0 for r in REGIMES}
    for p in points:
        if p["regime"] in out:
            out[p["regime"]] += 1
    return {r: round(c / total, 4) for r, c in out.items()}


def regime_transitions(series_map: dict, market: str = "kr", months: int = 60,
                       forecast_k: int = 3) -> dict:
    """전환 위험 한 묶음 — 경로 · 전이 사후 · k개월 예측 · 지속성 맥락."""
    path = regime_path(series_map, market, months)
    points = path["points"]
    if len(points) < 2:
        return {
            "available": False,
            "reason": (f"국면을 분류할 수 있는 달이 {len(points)}개뿐이라 "
                       "전이를 하나도 셀 수 없습니다"),
            "span": path["span"], "path": points,
        }

    counts = count_transitions(points)
    rows = transition_posterior(counts)
    current = points[-1]["regime"]
    return {
        "available": True,
        "market": market,
        "span": path["span"],
        "path": points,
        "current": current,
        "run_length_months": current_run_length(points),
        "occupancy": regime_occupancy(points),
        "regimes": REGIMES,
        "rows": rows,
        "n_transitions": sum(sum(r) for r in counts),
        "forecast": k_step_forecast(rows, current, k=forecast_k),
        "prior": {"alpha_diag": ALPHA_DIAG, "alpha_off": ALPHA_OFF,
                  "note": ("지속성을 약하게 선호하는 사전분포 — 행 합 7 은 '사전 표본 7개월' "
                           "에 해당합니다. 관측이 많은 행은 데이터가 이기고, 없는 행은 "
                           "사전분포가 남으며 그 사실을 shrunk 로 표시합니다.")},
        "note": ("행별 Dirichlet 사후. 신용구간은 Beta 주변분포에서 정확히 구했고(표본추출 "
                 "근사 아님), 관측이 부족한 행은 값을 지어내는 대신 구간이 넓어집니다."),
    }
