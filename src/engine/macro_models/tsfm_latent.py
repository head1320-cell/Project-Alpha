"""01 LATENT — 다변량 잠재 매크로 상태 $h_t$ (M1-M)
==============================================================================
프론티어: TSFM / TSMixer — 시계열 파운데이션 모델 임베딩.
대체:     동적 요인모형 `statsmodels.tsa.statespace.dynamic_factor.DynamicFactor`.

★대체가 프론티어의 축소판이 아니라 다른 모델이라는 점을 적는다★
DFM 은 **선형 가우시안 상태공간**이다. TSFM 임베딩과 달리 비선형 상호작용을 못 잡는다.
대신 60개월 표본에서 과적합하지 않고, 요인 적재(loading)가 해석 가능하다 —
"이 잠재 요인이 무엇인가" 를 사람이 읽을 수 있다는 것은 이 화면에서 큰 장점이다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.engine.macro_models.base import Engine, Studio, load_series, ok, span_of, unavailable

# ECOS(국내) + 성장·물가 축 — 브리프의 "ECOS M2·신용스프레드" 는 M1-I 에서 붙는다.
_INPUTS = ("KR_LEADING_CYCLE", "KR_IP", "KOSPI", "KR_CPI", "KR_3Y", "KR_10Y", "USD_KRW")

_MIN_OBS = 36          # 요인 하나 + 관측식 7개를 추정하기 위한 최소치
_MAX_FACTORS = 2

STUDIO = Studio(
    id="tsfm-latent",
    label="LATENT",
    question="여러 매크로 지표가 공유하는 잠재 상태는 무엇인가?",
    frontier=Engine(
        name="TSFM / TSMixer 임베딩",
        kind="frontier",
        summary="시계열 파운데이션 모델 — 비선형 다변량 임베딩 $h_t$",
        requires=("torch", "frontier_sample"),
    ),
    substitute=Engine(
        name="동적 요인모형 (DFM)",
        kind="substitute",
        summary="선형 가우시안 상태공간 — 해석 가능한 요인 적재, 소표본에 안전",
        requires=("statsmodels", "causal_sample"),
    ),
    inputs=_INPUTS,
)


def run(months: int = 60, n_factors: int = 1, **_: Any) -> dict[str, Any]:
    n_factors = max(1, min(int(n_factors), _MAX_FACTORS))
    series = load_series(_INPUTS, months)
    if len(series) < 3:
        return unavailable(
            STUDIO.substitute.name,
            f"잠재 요인을 뽑으려면 시리즈가 3개 이상 필요합니다 — 지금 {len(series)}개.")

    n = min(len(v) for v in series.values())
    if n < _MIN_OBS:
        return unavailable(
            STUDIO.substitute.name,
            f"관측이 {n}개뿐입니다 — 요인 추정에 최소 {_MIN_OBS}개가 필요합니다.")

    names = sorted(series)
    X = np.column_stack([np.asarray(series[k][-n:], dtype=float) for k in names])

    # 차분 후 표준화 — 수준 변수를 그대로 넣으면 공적분/추세가 요인을 지배한다.
    D = np.diff(X, axis=0)
    sd = D.std(axis=0, ddof=1)
    keep = sd > 1e-12
    if int(keep.sum()) < 3:
        dropped = [names[i] for i in range(len(names)) if not keep[i]]
        return unavailable(
            STUDIO.substitute.name,
            f"변동이 없는 시리즈를 빼고 나니 3개 미만입니다 (제외: {', '.join(dropped)}).")
    Z = (D[:, keep] - D[:, keep].mean(axis=0)) / sd[keep]
    kept = [names[i] for i in range(len(names)) if keep[i]]

    try:
        from statsmodels.tsa.statespace.dynamic_factor import DynamicFactor
        res = DynamicFactor(Z, k_factors=n_factors, factor_order=1).fit(disp=False, maxiter=200)
    except Exception as e:  # noqa: BLE001
        return unavailable(STUDIO.substitute.name, f"요인모형이 수렴하지 않았습니다: {e}")

    factors = np.asarray(res.factors.filtered).T      # (T, k)
    if factors.ndim == 1:
        factors = factors.reshape(-1, 1)

    # 적재 — 부호는 임의라 "가장 큰 적재를 양수로" 고정한다. 이렇게 하지 않으면
    # 같은 데이터로 두 번 돌렸을 때 요인이 뒤집혀 화면의 방향이 달라 보인다.
    load = np.zeros((len(kept), n_factors))
    for j in range(n_factors):
        for i, nm in enumerate(kept):
            load[i, j] = float(res.params.get(f"loading.f{j + 1}.y{i + 1}", np.nan)) \
                if hasattr(res.params, "get") else np.nan
        col = load[:, j]
        if np.all(np.isnan(col)):
            # 파라미터 이름 규약이 버전마다 달라 못 읽을 수 있다 — 상관으로 대체하고 그 사실을 적는다.
            col = np.array([float(np.corrcoef(Z[:, i], factors[:, j])[0, 1]) for i in range(len(kept))])
            load[:, j] = col
        if np.nanmax(np.abs(col)) > 0 and col[int(np.nanargmax(np.abs(col)))] < 0:
            load[:, j] = -col
            factors[:, j] = -factors[:, j]

    explained = None
    try:
        # 요인이 설명하는 분산 비율 — 주장하지 않고 잔차에서 계산한다.
        resid = np.asarray(res.resid)
        explained = float(1.0 - np.nanvar(resid) / np.nanvar(Z))
    except Exception:  # noqa: BLE001
        explained = None

    return ok(
        STUDIO.substitute.name,
        {
            "series": kept,
            "factors": factors.round(4).tolist(),
            "loadings": {kept[i]: [round(float(load[i, j]), 4) for j in range(n_factors)]
                         for i in range(len(kept))},
            "latest": [round(float(v), 4) for v in factors[-1]],
            "k_factors": n_factors,
            "explained_var": (round(explained, 4) if explained is not None else None),
        },
        note=("차분 후 표준화한 시리즈에 선형 가우시안 동적 요인모형을 적합했습니다. "
              "TSFM 임베딩과 달리 **비선형 상호작용은 잡지 못합니다** — 대신 적재를 읽어 "
              "요인이 무엇인지 확인할 수 있고, 소표본에서 과적합하지 않습니다. "
              "요인 부호는 최대 적재가 양수가 되도록 고정했습니다(부호 자체는 임의)."),
        span=span_of(int(Z.shape[0]), months),
    )
