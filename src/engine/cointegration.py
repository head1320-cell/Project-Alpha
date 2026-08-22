"""공적분 → VECM / 차분 VAR 분기 (P4-M1)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
금리·물가·환율·주가는 **레벨이 비정상이고 장기균형을 공유**하는 전형적 조합이다.
그레인저를 레벨에 그대로 걸면 허위회귀(spurious regression)가 된다 — 두 랜덤워크는
아무 관계가 없어도 회귀계수가 유의하게 나온다. 실측으로 확인했다: 이 저장소에
`coint` 0곳 · `VECM` 0곳, 즉 그 검정을 한 번도 하지 않았다.

그래서 순서를 뒤집는다 — **먼저 장기관계가 있는지 묻고**, 있으면 VECM(오차수정),
없으면 차분 VAR 로 간다. 그리고 **어느 쪽을 왜 골랐는지 응답에 적는다**. 결론만
내면 화면은 그 숫자가 어떤 가정 위에 서 있는지 알 수 없다.

★코어 변수 상한 K ≤ 7 — 계산 전에 거부한다★
------------------------------------------------------------------------------
D1+D2 가 계열을 40+ 개로 늘렸다. VECM(K변수, p시차)의 모수는 대략 K²p 이므로
K=40·p=1 이면 **1,600 모수 vs 240 관측** — 공분산이 특이에 가까워지고 결과는
노이즈다. "돌긴 도는데 노이즈" 가 가장 위험하다: 숫자가 나오면 사람은 믿는다.
그래서 추정하지 않고 거부한다. K=7·p=2 면 98모수 vs 240관측으로 추정 가능한 구간이다.

★PCA/FAVAR 로 줄이지 않는다★ 외부 리뷰가 대안으로 제시했지만 요인은 **해석을
잃는다**. A8 이 정확 Shapley 로 "무엇이 국면을 움직였나" 를 지표 이름으로 답하게
만들어 놨고, "주성분 3번이 움직였다" 는 그 계약을 깬다. 게다가 `tsfm_latent`
스튜디오가 이미 요인 추출을 담당한다 — 거기서 하는 일을 VECM 앞단에 복제하지
않는다. **차원 축소가 아니라 변수 절제로 푼다.**

★코어 셋은 통계가 아니라 경제로 고른다★ 통계로 고르면 그 선택이 표본을 쓰고
(사후선택 편향) 이후 검정의 p값은 더 이상 p값이 아니다. 사전 지정이 정직하다.

나머지 30+ 계열을 버리는 것이 아니다 — 그레인저 선행관계 스캔 · 국면 드라이버 ·
스튜디오 입력으로 계속 쓰이고, **VECM 이라는 특정 추정기에만** 안 들어간다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: ★코어 변수 상한★ K²p 모수가 관측(240)의 절반을 넘지 않는 선에서 골랐다.
#: 이 숫자를 올리려면 표본을 먼저 늘려야 한다 — 상한을 올리는 것으로는 자유도가
#: 생기지 않는다.
MAX_CORE_VARS = 7

#: VECM 최소 관측. 시차 2·변수 7 이면 98모수라, 그 두 배 아래로는 추정이 무의미하다.
MIN_OBSERVATIONS = 60


class CoreVariableError(ValueError):
    """코어 변수가 상한을 넘었을 때. **경고가 아니라 거부다.**"""


#: 기본 코어 셋 — 데이터를 보지 않고 경제적으로 지정한다(사후선택 편향 회피).
#: 통화정책(기준금리) · 기간구조(장단기) · 물가 · 대외(환율) · 위험자산(주가) ·
#: 신용(스프레드) · 실물(산업생산). 한국 매크로의 최소 골격이다.
_DEFAULT_CORE: tuple[str, ...] = (
    "KR_BASE_RATE",
    "KR_TERM_SPREAD",
    "KR_CPI",
    "USD_KRW",
    "KOSPI",
    "KR_CREDIT_SPREAD",
    "KR_IP",
)


def default_core_variables() -> tuple[str, ...]:
    """VECM 에 넣을 기본 코어 셋. **입력과 무관하게 항상 같다.**

    데이터를 보고 고르면 그 선택 자체가 표본을 소비한다 — 이후 공적분 검정의
    p값은 더 이상 p값이 아니게 된다(사후선택 편향).
    """
    return _DEFAULT_CORE


def _clean(series: dict[str, list[float]]) -> tuple[list[str], list[list[float]], int]:
    """겹치는 구간만 남긴다 — 계열마다 길이가 다르면 짧은 쪽에 맞춘다."""
    names = sorted(series)
    lengths = [len(series[n] or []) for n in names]
    n = min(lengths) if lengths else 0
    return names, [list(series[k])[-n:] for k in names], n


def analyze_long_run(series: dict[str, list[float]], *,
                     det_order: int = 0, k_ar_diff: int = 1) -> dict[str, Any]:
    """장기관계 판정 → VECM 또는 차분 VAR.

    ★상한 초과는 예외로 중단한다★ 다른 실패(표본 부족·변수 1개)는 `available:false`
    + 사유로 답하는데, 상한 초과만 예외인 이유는 **호출자의 설정 실수**이기 때문이다.
    사유를 답하면 화면이 그것을 "데이터가 부족하다" 로 읽지만, 실제로는 데이터가
    아니라 요청이 잘못됐다.
    """
    if len(series) > MAX_CORE_VARS:
        raise CoreVariableError(
            f"코어 변수는 최대 {MAX_CORE_VARS}개입니다 — {len(series)}개가 들어왔습니다. "
            f"VECM 의 모수는 대략 K²p 라, K={len(series)} 면 관측 수를 크게 넘어 "
            "추정 결과가 노이즈가 됩니다. 차원 축소(PCA)로 줄이지 않는 이유는 요인이 "
            "해석을 잃기 때문입니다 — 코어 변수를 골라 주세요."
        )

    names, cols, n = _clean(series)
    if len(names) < 2:
        return {"available": False, "coint_rank": None,
                "reason": "공적분은 둘 이상의 계열 사이에서 정의됩니다 — "
                          f"{len(names)}개만 들어왔습니다."}
    if n < MIN_OBSERVATIONS:
        return {"available": False, "coint_rank": None,
                "reason": f"관측이 {n}개로 최소 {MIN_OBSERVATIONS}개에 못 미칩니다 — "
                          "짧은 표본의 VECM 은 그럴듯한 노이즈입니다."}

    try:
        import numpy as np
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
    except ImportError as e:            # pragma: no cover - 환경 의존
        return {"available": False, "coint_rank": None,
                "reason": f"statsmodels/numpy 를 불러올 수 없습니다: {e}"}

    y = np.column_stack([np.asarray(c, dtype=float) for c in cols])
    if not np.all(np.isfinite(y)):
        return {"available": False, "coint_rank": None,
                "reason": "결측·무한값이 있는 계열이 있습니다 — 채우지 않고 거부합니다."}

    try:
        jo = coint_johansen(y, det_order, k_ar_diff)
    except Exception as e:              # 특이행렬 등 — 숫자를 지어내지 않는다
        return {"available": False, "coint_rank": None,
                "reason": f"요한센 검정이 실패했습니다: {e}"}

    # ★trace 통계량이 95% 임계값을 넘는 개수가 공적분 랭크다★
    trace = [float(v) for v in jo.lr1]
    crit95 = [float(row[1]) for row in jo.cvt]      # cvt 열: 90% · 95% · 99%
    rank = 0
    for stat, crit in zip(trace, crit95, strict=True):
        if stat <= crit:
            break
        rank += 1

    evidence = {"test": "johansen_trace", "trace_stat": trace, "crit_95": crit95,
                "det_order": det_order, "k_ar_diff": k_ar_diff}

    if rank >= 1:
        reason = (f"요한센 trace 검정에서 공적분 랭크 {rank} 이 유의합니다(95%) — "
                  "레벨에 장기균형이 있으므로 오차수정항을 갖는 VECM 을 씁니다. "
                  "차분 VAR 를 쓰면 그 장기정보를 버리게 됩니다.")
        model = "vecm"
    else:
        reason = ("요한센 trace 검정에서 공적분이 유의하지 않습니다(95%) — "
                  "장기균형이 없으므로 차분 VAR 를 씁니다. 없는 균형에 VECM 을 "
                  "물리면 존재하지 않는 오차수정을 추정하게 됩니다.")
        model = "diff_var"

    return {
        "available": True,
        "model": model,
        "coint_rank": rank,
        "variables": names,
        "reason": reason,
        "evidence": evidence,
        "span": {"n": n, "k": len(names), "requested": max(
            (len(v or []) for v in series.values()), default=0)},
    }
