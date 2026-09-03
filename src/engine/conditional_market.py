"""
Conditional Cross-Asset Moments — 국면조건부 μ/Σ (P2.5)
==========================================================================
감사(`docs/specs/2026-08-22-dynamic-portfolio-audit.md`)가 줄 번호로 증명한 것:
**파이프는 깔렸는데 아무것도 흐르지 않는다.** `allocation_studio.optimize` 는
`S = _cov(R) * 252.0` 로 **무조건부 트레일링** 공분산을 쓰고, μ 는 트레일링
평균·BL 사후·EP 사후뿐이며 셋 다 사용자 뷰에서 온다. 국면 확률·축 점수가 μ 나 Σ 에
**한 번도 닿지 않는다.**

이 모듈이 그 자리를 채운다: 월별 국면 라벨로 일별 수익률을 나눠 **현재 국면의
표본만으로** μ 와 Σ 를 추정한다.

★왜 μ 를 optimizer 에 직접 대입하지 않는가★
그것이 이 슬라이스에서 가장 중요한 설계 결정이다. 국면조건부 μ 를 최적화기에 그냥
넣으면 "매크로 신호 → 비중" 이라는 지금 구조를 이름만 바꿔 되풀이한다. 호출부는 이
μ 를 **자산별 절대 뷰**로 바꿔 BL/EP 사후를 태운다 — 그러면 불확실성이 Ω 에 명시되고,
뷰가 사전분포보다 강하면 ENS 붕괴로 **드러난다**. 이 모듈은 숫자만 내고 그 정책은
호출부(`allocation_routes`)에 둔다.

★표본이 설계를 결정한다★
매크로 시계열 깊이는 mock 60개월 · 실 키 240개월이고 국면은 4개, 매크로 유니버스는
8자산이다. 국면당 **월** 관측은 mock ~15 · 실 키 ~60 이다. 일별 수익률로 잘라도
관측 **행 수**는 늘지만 독립적인 거시 관측이 늘지는 않는다 — 한 달의 21영업일은
같은 국면 라벨 하나를 공유한다. 그래서 이 모듈은 행 수(`n_obs`)와 **개월 수
(`n_months`)를 함께** 돌려준다. 개월 수를 숨기면 300개 관측처럼 보이는 15개월짜리
추정이 만들어진다.

그 위에 셋을 건다:
  1. **Ledoit-Wolf 수축을 기본값으로** — `risk_allocations._cov` 와 같은 추정량이되
     여기서는 **수축 강도 λ 를 함께 보고**한다. λ 가 크다는 것은 "표본이 얇아서
     대부분 목표행렬" 이라는 자백이다.
  2. **표본 하한 게이트** — 국면당 관측 < `min_obs_per_asset · n_assets` 이면 숫자를
     내지 않고 **사유와 국면별 관측 수**를 돌려준다. 국면별 μ 는 표본이 얇을수록
     매력적으로 보이는 방향으로 틀리기 쉽다.
  3. **조용한 폴백 금지** — `available: False` 면 호출부가 무조건부로 떨어지되
     **응답이 그 사실을 말한다**(M2-A 의 `feasible:false` 처리와 같은 원칙).

★하한은 충분성 보증이 아니라 특이(degenerate) 방지선이다★
p자산 공분산은 자유도 p(p+1)/2 를 요구하므로 3p 행으로 "충분" 해지지 않는다. 충분성을
말하는 숫자는 하한이 아니라 **`shrinkage_lambda` 와 `n_months`** 다. 하한은 표본이
자산 수보다도 적어 표본공분산이 확실히 특이해지는 구간만 막는다.

★EWMA·상관붕괴 진단을 새로 짓지 않는다★
`regime_adaptive_allocator._analyze_correlation_health` 가 이미 평균/최대 상관과
최대 고유값 비중·단일인자 지배 판정을 갖고 있다. 여기서는 그 **통계의 형태만** 가져와
`.tail(60)`(최근성) 대신 **국면 표본**에 대해 계산한다. 두 계통을 합치지는 않는다 —
소비자도 계약도 다르다(저쪽은 전략 행렬, 이쪽은 자산 행렬).
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

TRADING_DAYS = 252.0

# 국면당 자산 하나에 요구하는 최소 관측 행 수. 3.0 이면 8자산에 24행 —
# 표본공분산이 확실히 특이해지는 구간(n ≤ p)을 막는 선이지, 충분성 보증이 아니다.
MIN_OBS_PER_ASSET = 3.0

# 진단 임계값 — `regime_adaptive_allocator` 와 같은 값을 쓴다(같은 현상을 재는 자다).
_AVG_CORR_BREAKDOWN = 0.70
_SINGLE_FACTOR_RATIO = 0.60


def _month_key(ts) -> str:
    """`YYYY-MM` — `regime_transitions._month_labels` / `macro_visuals` 와 같은 규약."""
    try:
        return ts.strftime("%Y-%m")
    except Exception:
        return str(ts)[:7]


def _month_keys(index) -> np.ndarray:
    """인덱스 **전체**의 `YYYY-MM`. ★`_month_key` 를 행마다 부르는 것과 같은 답★

    ★낭비는 per-element 비용이 아니라 재계산이었다★ 워크포워드는 같은
    DatetimeIndex 의 확장창을 70번 훑는다 — 실측으로 고유 타임스탬프 1,764개인데
    `_month_key` 호출은 68,355회다(관문 plan 의 10%).

    ★`.strftime()` 벡터화는 더 느리다★(실측 0.4582s vs listcomp 0.4330s) —
    pandas 의 `strftime` 도 결국 Timestamp 를 도는 파이썬 루프다. `to_period` 는
    정수 월 서수로 내려가므로 **5.27배** 빠르고 값은 같다.

    ★단수형은 손대지 않는다★ 다른 다섯 모듈이 쓰고 `test_month_key_contract` 가
    계약을 건다. 이 함수는 그 위에 얹히고, 둘이 같은 답을 내는지는 테스트가 건다.
    """
    try:
        return index.to_period("M").astype(str).to_numpy()
    except (AttributeError, TypeError, ValueError):
        # ★폴백은 지름길이 아니라 같은 답이어야 한다★ 상류가 내보내는 형식이
        # 데이터에 따라 달라진다(아래 `_normalize_month` 가 적어 둔 사건).
        return np.array([_month_key(ts) for ts in index])


def _normalize_month(raw: str) -> str | None:
    """월 라벨을 정규형 `"YYYY-MM"` 으로. 날짜가 아니면 `None`.

    ★규약이 데이터에 의존한다 — 그래서 소비자에서 정규화한다★
    `regime_transitions._month_labels` 는 `str(t)[:7]` 이다. 수집기의 timestamps 가
    `"2021-09-01"` 이면 `"2021-09"` 가 나오지만, **이 저장소의 실제 수집기는
    `202109`** 라서 `"202109"` 가 나온다. 즉 상류가 내보내는 형식이 데이터에 따라
    달라진다.

    ★이것을 모르고 `"YYYY-MM"` 만 받았다가 P2.5 조건부 μ/Σ 가 운영에서 통째로
    죽어 있었다★ — `regime_path` 의 53개 점이 **전부** 버려져 `conditional_moments`
    가 항상 "월별 국면 라벨이 없다" 로 무조건부 폴백했다. 테스트가 전부 합성
    `"YYYY-MM"` 라벨을 써서 아무도 못 잡았다.

    상류(`_month_labels`)를 고치지 않는 이유: `macro_visuals` 등이 같은 규약을
    공유하므로 파급이 넓다. 두 형식을 다 받는 것이 이 함수의 계약이다.
    """
    t = str(raw or "").strip()
    if len(t) == 7 and t[4] == "-" and t[:4].isdigit() and t[5:].isdigit():
        month = int(t[5:])
        return t if 1 <= month <= 12 else None
    if len(t) == 6 and t.isdigit():
        month = int(t[4:])
        return f"{t[:4]}-{t[4:]}" if 1 <= month <= 12 else None
    return None


def regime_by_month_from_path(points: list[dict] | None) -> tuple[dict[str, str], int]:
    """`regime_transitions.regime_path()["points"]` → ({월: 국면}, 버린 개수).

    월 키는 정규형 `"YYYY-MM"` 으로 통일된다 — `_month_key` 가 수익률 인덱스에서
    만드는 것과 같은 형식이라 둘이 만난다.

    ★`T-k` 라벨은 버린다★ `_month_labels` 는 시계열이 요청보다 짧으면 앞을 `T-3`
    처럼 채운다. 그것은 **날짜가 아니라 자리표시자**이므로 수익률의 달과 맞출 수
    없다. 조용히 섞지 않고 버리고, 몇 개를 버렸는지 함께 돌려준다.
    """
    out: dict[str, str] = {}
    dropped = 0
    for p in points or []:
        regime = p.get("regime")
        month = _normalize_month(p.get("t"))
        if not regime or month is None:
            dropped += 1
            continue
        out[month] = str(regime)
    return out, dropped


def _shrink_to_identity(S: np.ndarray, lam: float) -> np.ndarray:
    """Ledoit-Wolf 와 같은 목표행렬(스케일 단위행렬)로 명시적 강도 수축."""
    p = S.shape[0]
    mu = float(np.trace(S)) / p if p else 0.0
    return (1.0 - lam) * S + lam * mu * np.eye(p)


def _shrunk_cov(R: np.ndarray, shrinkage) -> tuple[np.ndarray, float | None, str]:
    """(공분산, 수축강도, 방법). 일별 단위 그대로 — 연율화는 호출부에서 한 번만."""
    if shrinkage == "none":
        S = np.cov(R, rowvar=False)
        S = np.atleast_2d(S)
        return S + np.eye(S.shape[0]) * 1e-10, None, "sample"
    if isinstance(shrinkage, (int, float)) and not isinstance(shrinkage, bool):
        lam = min(max(float(shrinkage), 0.0), 1.0)
        S = np.atleast_2d(np.cov(R, rowvar=False))
        return _shrink_to_identity(S, lam), lam, "shrunk_fixed"
    # "auto" — `risk_allocations._cov` 와 같은 추정량이되 λ 를 함께 받는다.
    try:
        from sklearn.covariance import ledoit_wolf
        S, lam = ledoit_wolf(R)
        return np.atleast_2d(S), float(lam), "ledoit_wolf"
    except Exception as e:  # pragma: no cover - sklearn 부재/특이 표본
        logger.warning(f"Ledoit-Wolf 수축 실패, 표본공분산으로 진행: {e}")
        S = np.atleast_2d(np.cov(R, rowvar=False))
        return S + np.eye(S.shape[0]) * 1e-10, None, "sample"


def _correlation_health(R: np.ndarray) -> dict:
    """국면 표본의 상관 건강도 — 통계의 형태는 `regime_adaptive_allocator` 와 같다."""
    n = R.shape[1]
    blank = {
        "avg_correlation": None, "max_correlation": None,
        "max_eigenvalue_ratio": None,
        "single_factor_dominance": False, "breakdown_detected": False,
        "n_assets": n,
    }
    if n < 2 or R.shape[0] < 2:
        return blank
    try:
        C = np.corrcoef(R, rowvar=False)
        if not np.all(np.isfinite(C)):
            return blank
        mask = ~np.eye(n, dtype=bool)
        avg_corr = float(np.abs(C[mask]).mean())
        max_corr = float(np.abs(C[mask]).max())
        eig = np.linalg.eigvalsh(C)
        tot = float(eig.sum())
        ratio = float(eig[-1] / tot) if tot > 0 else None
        single = bool(ratio is not None and ratio > _SINGLE_FACTOR_RATIO)
        return {
            "avg_correlation": round(avg_corr, 3),
            "max_correlation": round(max_corr, 3),
            "max_eigenvalue_ratio": round(ratio, 3) if ratio is not None else None,
            "single_factor_dominance": single,
            "breakdown_detected": bool(avg_corr > _AVG_CORR_BREAKDOWN or single),
            "n_assets": n,
        }
    except Exception as e:  # pragma: no cover
        logger.warning(f"상관 진단 실패: {e}")
        return blank


def _unavailable(reason: str, **extra) -> dict:
    """숫자 대신 사유 — 필드 모양은 성공 응답과 같게 유지한다(호출부 분기 최소화)."""
    out = {
        "available": False, "method": None, "regime": None,
        "n_obs": 0, "n_months": 0, "n_obs_by_regime": {},
        "names": [], "mu": None, "sigma": None,
        "shrinkage_lambda": None, "min_obs_required": None,
        "unlabeled_obs": 0, "diagnostics": None, "degenerate": False,
        "reason": reason,
    }
    out.update(extra)
    return out


def conditional_moments(returns_df, regime_by_month: dict[str, str] | None,
                        current_regime: str | None, *,
                        min_obs_per_asset: float = MIN_OBS_PER_ASSET,
                        shrinkage="auto",
                        trading_days: float = TRADING_DAYS) -> dict:
    """현재 국면의 표본만으로 연율 μ/Σ 를 추정한다.

    Args:
        returns_df: **DatetimeIndex 를 가진 일별 수익률** DataFrame
            (`allocation_routes._load_clean_returns` 가 돌려주는 그것 —
            `returns.values` 로 numpy 가 되기 **직전**의 객체다).
        regime_by_month: `{"YYYY-MM": 국면}`. `regime_by_month_from_path` 로 만든다.
        current_regime: 지금 국면 라벨.
        min_obs_per_asset: 국면당 자산 하나에 요구하는 최소 관측 행 수.
        shrinkage: `"auto"`(Ledoit-Wolf) · `"none"`(표본) · `0.0~1.0`(명시 강도).
        trading_days: 연율화 계수 — 호출부의 무조건부 경로와 같은 252.

    Returns:
        `{available, method, regime, n_obs, n_months, n_obs_by_regime, names,
          mu, sigma, shrinkage_lambda, min_obs_required, unlabeled_obs,
          diagnostics, reason?}`
        μ 와 Σ 는 **연율** numpy 배열이고 열 순서는 `names` 와 같다.
    """
    if returns_df is None or getattr(returns_df, "empty", True):
        return _unavailable("수익률이 비어 있어 국면조건부 추정을 할 수 없습니다.")
    if not regime_by_month:
        return _unavailable("월별 국면 라벨이 없어 수익률을 국면으로 나눌 수 없습니다.")
    if not current_regime:
        return _unavailable("현재 국면을 알 수 없습니다.")

    names = [str(c) for c in returns_df.columns]
    n_assets = len(names)
    if n_assets < 1:
        return _unavailable("자산이 없습니다.")

    # ★행마다 다시 만들지 않는다★ 워크포워드가 같은 인덱스의 확장창을
    # 70번 훑어 `_month_key` 를 68,355회 부르고 있었다(실측, plan 의 10%).
    months = _month_keys(returns_df.index)
    labels = np.array([regime_by_month.get(m, "") for m in months])

    # ★라벨 없는 달은 버리고 그 수를 보고한다★ 조용히 섞으면 다른 국면의 수익률이
    # 현재 국면 추정에 들어간다 — 이 모듈이 존재하는 이유 자체가 무너진다.
    labeled = labels != ""
    unlabeled_obs = int((~labeled).sum())

    by_regime: dict[str, int] = {}
    months_by_regime: dict[str, set] = {}
    for reg, mo in zip(labels[labeled], months[labeled]):
        by_regime[reg] = by_regime.get(reg, 0) + 1
        months_by_regime.setdefault(reg, set()).add(mo)
    n_obs_by_regime = dict(sorted(by_regime.items()))
    n_months_by_regime = {k: len(v) for k, v in sorted(months_by_regime.items())}

    required = int(math.ceil(min_obs_per_asset * n_assets))
    sel = labeled & (labels == current_regime)
    block = returns_df.iloc[np.flatnonzero(sel)].dropna()
    n_obs = int(len(block))

    common = {
        "regime": current_regime,
        "n_obs": n_obs,
        "n_months": len(months_by_regime.get(current_regime, set())),
        "n_obs_by_regime": n_obs_by_regime,
        "n_months_by_regime": n_months_by_regime,
        "names": names,
        "min_obs_required": required,
        "unlabeled_obs": unlabeled_obs,
    }

    if n_obs < required:
        seen = "" if n_obs_by_regime else " (어떤 달도 국면 라벨과 맞지 않았습니다)"
        return _unavailable(
            f"'{current_regime}' 국면의 관측이 {n_obs}행뿐이라 "
            f"{n_assets}자산 공분산을 추정할 수 없습니다 (최소 {required}행){seen}. "
            "국면별 기대수익은 표본이 얇을수록 매력적으로 보이는 방향으로 틀립니다 — "
            "숫자를 지어내는 대신 무조건부 추정을 쓰십시오.",
            **common)

    R = block.values.astype(float)
    mu = R.mean(axis=0) * trading_days
    S_daily, lam, method = _shrunk_cov(R, shrinkage)
    sigma = S_daily * trading_days
    # 대칭성 복원 — 수치 오차로 깨진 대칭은 이후 고유분해(ENB·HRP)를 흔든다.
    sigma = (sigma + sigma.T) / 2.0

    # ★수축이 1.0 이면 Σ 는 스케일 단위행렬이다★ 실측에서 실제로 그렇게 나왔다
    # (mock 시세가 종목별로 독립 생성되므로 Ledoit-Wolf 의 목표가 **정확히 맞고**
    # λ→1 이 된다). 그러면 Σ 는 상수배 단위행렬이라 스케일 불변 모델
    # (min_var·ERC·HRP·max_div·고정 μ 의 max-sharpe)의 비중이 **국면과 무관하게
    # 같아진다.** 그 화면을 본 사람은 "조건부가 배선되지 않았다" 고 결론 내리는데,
    # 사실은 표본이 국면별 공분산 구조를 하나도 담고 있지 않다는 뜻이다.
    # 둘은 완전히 다른 사실이므로 값이 스스로 말하게 한다.
    degenerate = lam is not None and lam >= 0.999
    note = (f"'{current_regime}' 국면으로 분류된 {common['n_months']}개월"
            f"({n_obs}영업일)의 표본만으로 추정했습니다. 독립적인 거시 관측은 "
            f"영업일 수가 아니라 **개월 수**입니다.")
    if degenerate:
        note += (" ★수축 강도가 1.0 이라 Σ 가 스케일 단위행렬로 무너졌습니다★ — "
                 "이 표본에는 국면별 공분산 구조가 없습니다. 스케일 불변 모델의 "
                 "비중은 국면을 바꿔도 같게 나오며, 그것은 배선 문제가 아니라 "
                 "데이터가 할 말이 없다는 뜻입니다.")

    return {
        "available": True,
        "method": method,
        "mu": mu,
        "sigma": sigma,
        "shrinkage_lambda": (round(lam, 4) if lam is not None else None),
        "degenerate": bool(degenerate),
        "diagnostics": _correlation_health(R),
        "reason": None,
        "note": note,
        **common,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 국면혼합 적률 (MS1-a) — 하드 라벨을 확률 1 로 쓰는 것을 그만둔다
# ══════════════════════════════════════════════════════════════════════════════
# 계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.3
#
# ★위 `conditional_moments` 는 오늘의 **점 라벨** 하나로 조건부를 만든다.★ 그것은
# "보유기간 내내 오늘 국면일 확률 = 1" 을 가정한다. 실측은 정반대다 — 3개월 지평의
# 워크포워드 적중률 0.889 는 좋아 보이지만 **평균 예측집합 크기가 3.81/4** 다.
# 4국면 중 거의 전부를 담아야 맞힌다는 뜻이고, 그런 예측을 확률 1 로 쓰는 것은
# 데이터가 뒷받침하지 않는 확신이다.
#
# ★그리고 혼합은 "국면별 적률의 가중평균" 이 아니다.★ 전분산법칙의 두 번째 항 —
# 국면 **간** 평균의 산포 — 가 공분산에 더해진다. 국면을 모를수록 Σ 가 **커진다**.
# 불확실성을 평균으로 지우는 것이 아니라 리스크로 정직하게 옮기는 것이다.
#
#   μ̄_h = Σ_{j=1..h} Σ_s π_j(s)·μ_s,m            ★π_h 가 아니라 π_1..π_h 전부★
#   W_h = Σ_{j=1..h} Σ_s π_j(s)·Σ_s,m             국면 내 (시간가변 가중)
#   A_h = Σ_{j,k}   Cov(μ_{S_j}, μ_{S_k})         국면 간 누적 — **결합분포**
#         Cov = Σ_{s,s'} π_j(s)·[P^{k−j}]_{s,s'}·μ_s μ_{s'}ᵀ − E_j E_kᵀ   (k ≥ j)
#   Σ̄_h = W_h + A_h                              (월간 누적 → 연율 ×12/h)
#
# ★`h²·D` 로 근사하지 않는 이유★ 그것은 `P = I`(국면이 h개월 내내 유지)인 극한이고,
# 실측 전이행렬에서는 정확값을 **1.489배 과대추정**한다. 반대로 `h·D` 는 무기억
# 극한이고 2.01배 과소추정한다. 정확값은 둘 사이 어디든 되며 **어디인지는 전이행렬이
# 정한다** — 스칼라 계수로 대신할 수 없다. 두 극한은 테스트가 못박고 있다.
#
# ★일별로 내려가지 않는 이유★ 국면은 **월 단위로 인덱스된 상태**다. 일별 스텝으로
# 계산해도 한 달의 영업일이 같은 라벨을 공유하면 답은 같다(실측 차이 7.4e−18).
# 그러나 국면까지 매일 재추첨하면 국면 간 항이 **888.6배 지워져** 이 슬라이스가
# 통째로 no-op 이 된다. 그래서 이 함수는 지평을 **개월**로만 받는다 — 일별 해상도를
# 넣을 자리를 두지 않는 것이 가장 확실한 방어다.

MONTHS_PER_YEAR = 12.0

#: π_path 와 전이행렬의 정합 허용오차. 이보다 벌어지면 A_h 가 공분산이 아니게 되고
#: 음의 고유값이 나온다(실측 −3.94e−4) — 그 행렬이 최적화기로 가면 음의 분산을
#: 최소화하려 든다. 그래서 계산하지 않고 사유를 돌려준다.
PI_PATH_TOLERANCE = 1e-9

#: 추정 불가 국면이 어느 한 시점에서 이만큼을 넘게 차지하면 혼합하지 않는다.
#: 남은 국면으로 재정규화하는 것은 **근사**이고, 분포의 절반 이상을 지어낼 수는 없다.
DROPPED_MASS_LIMIT = 0.5

#: 대칭화 후 최소고유값이 이보다 작으면 클립하지 않고 실패로 보고한다.
_PSD_TOLERANCE = -1e-12

#: 생존 국면에 걸린 확률질량이 이보다 작으면 재정규화 자체가 0으로 나누기다.
_PI_MASS_EPS = 1e-9


def _pi_matrix(pi_path, regimes: list[str]) -> np.ndarray | None:
    """`[{국면: 확률}, …]` → `(h, R)` 배열. 모양이 어긋나면 `None`."""
    rows = []
    for step in pi_path or []:
        if not isinstance(step, dict):
            return None
        rows.append([float(step.get(r, 0.0)) for r in regimes])
    return np.asarray(rows, dtype=float) if rows else None


def _validate_path(pis: np.ndarray, P: np.ndarray, h_hold: int) -> str | None:
    """모양·정규화·π_path↔P 정합 검사. 문제가 없으면 `None`."""
    if not isinstance(h_hold, (int, np.integer)) or int(h_hold) < 1:
        return (f"홀딩 기간이 {h_hold} 개월입니다 — 1 이상의 정수여야 합니다. "
                "기대 지속기간(expected_duration_months)은 여기에 넣는 값이 아닙니다.")
    if pis is None or pis.shape[0] != int(h_hold):
        got = 0 if pis is None else pis.shape[0]
        return (f"국면확률 경로가 {got}단계인데 홀딩 기간은 {h_hold}개월입니다 — "
                "홀딩 기간의 매 달에 대한 확률이 있어야 합니다.")
    if P.ndim != 2 or P.shape[0] != P.shape[1] or P.shape[0] != pis.shape[1]:
        return "전이행렬의 모양이 국면 수와 맞지 않습니다."
    if not np.isfinite(pis).all() or not np.isfinite(P).all():
        return "국면확률 또는 전이행렬에 결측/무한값이 있습니다."
    if (pis < -1e-12).any():
        return "국면확률에 음수가 있습니다."
    if np.abs(pis.sum(axis=1) - 1.0).max() > 1e-6:
        return "국면확률의 합이 1이 아닙니다."
    if np.abs(P.sum(axis=1) - 1.0).max() > 1e-6:
        return "전이행렬의 행 합이 1이 아닙니다(행 = 출발 국면 규약)."
    # ★핵심 검사★ π_{j+1} = π_j·P 가 아니면 아래 이중합은 공분산이 아니다.
    for j in range(pis.shape[0] - 1):
        gap = float(np.abs(pis[j + 1] - pis[j] @ P).max())
        if gap > PI_PATH_TOLERANCE:
            return (f"국면확률 경로가 전이행렬과 일관되지 않습니다 "
                    f"(단계 {j + 1}→{j + 2} 에서 최대 {gap:.3e} 어긋남). "
                    "같은 사슬에서 나온 π 와 P 를 함께 넘겨야 합니다 — "
                    "어긋난 채로 계산하면 국면 간 항이 공분산이 아니게 됩니다.")
    return None


def _mix_core(M: np.ndarray, S: np.ndarray, pis: np.ndarray,
              P: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """월간 적률에서 h개월 누적 `(μ_cum, W_h, A_h)` — 검증 없음(호출자가 한다).

    Args:
        M: `(R, n)` 국면별 **월간** 평균.
        S: `(R, n, n)` 국면별 **월간** 공분산.
        pis: `(h, R)` 각 달의 국면확률.
        P: `(R, R)` 전이행렬(행 = 출발).
    """
    h = pis.shape[0]
    E = [pis[j] @ M for j in range(h)]
    W = sum(np.einsum("s,sij->ij", pis[j], S) for j in range(h))
    A = np.zeros((M.shape[1], M.shape[1]), dtype=float)
    # `P^m` 은 |k−j| 가 같으면 같으므로 한 번만 만든다(h ≤ 12 라 어차피 싸지만,
    # 이중합 안에서 거듭제곱하면 h⁴ 스케일이 된다).
    powers = [np.linalg.matrix_power(P, m) for m in range(h)]
    for j in range(h):
        for k in range(h):
            T = powers[abs(k - j)]
            # k ≥ j 면 j 에서 출발해 k 로 간다. 반대면 대칭으로 뒤집는다.
            J = (np.einsum("s,st->st", pis[j], T) if k >= j
                 else np.einsum("t,ts->st", pis[k], T))
            A += np.einsum("st,si,tj->ij", J, M, M) - np.outer(E[j], E[k])
    return sum(E), W, A


def _package_mixture(mu_cum, W, A, h_hold: int, names, pis, regimes,
                     **extra) -> dict:
    """누적 적률 → 연율 응답. ★PSD 실패는 클립하지 않고 사유로 돌려준다★."""
    ann = MONTHS_PER_YEAR / float(h_hold)
    sigma = (W + A) * ann
    sigma = (sigma + sigma.T) / 2.0             # 수치 대칭 복원
    min_eig = float(np.linalg.eigvalsh(sigma).min())
    if min_eig < _PSD_TOLERANCE:
        return _unavailable(
            f"혼합 공분산의 최소고유값이 {min_eig:.3e} 로 음수입니다 — 양정치가 "
            "아닙니다. 값을 잘라 내보내면 최적화기가 음의 분산을 최소화하려 들므로, "
            "고치지 않고 사실대로 알립니다.",
            names=list(names), h_hold=int(h_hold), **extra)

    tr_total = float(np.trace(sigma))
    a_pct = (float(np.trace(A * ann)) / tr_total * 100.0) if abs(tr_total) > 1e-18 else 0.0
    pi_bar = pis.mean(axis=0)
    return {
        "available": True,
        "method": "regime_mixture",
        "mu": mu_cum * ann,
        "sigma": sigma,
        "W_h": W,
        "A_h": A,
        "h_hold": int(h_hold),
        "pi_path": [dict(zip(regimes, row, strict=True)) for row in pis],
        "pi_bar": dict(zip(regimes, pi_bar, strict=True)),
        # ★국면 불확실성이 리스크의 몇 %인가★ — 사람이 이 숫자를 보고 혼합이
        # 실제로 무언가를 하고 있는지 판단할 수 있어야 한다.
        "A_contribution_pct": round(a_pct, 4),
        "min_eigenvalue": min_eig,
        "names": list(names),
        "reason": None,
        **extra,
    }


#: 혼합의 λ 집계 의미. ★값으로 선언한다★ — 소비자가 "평균이겠거니" 하지 않게.
LAMBDA_AGGREGATE_PI_WEIGHTED = "pi_weighted_mean"


def resolve_shrinkage_lambda(cond: dict) -> float:
    """조건부/혼합 응답에서 **스칼라** 수축강도를 읽는다. 못 읽으면 **올린다**.

    ★"모르면 0" 을 금지하는 것이 이 함수의 존재 이유다.★
    `λ = 0` 은 "수축이 전혀 필요 없다 = 표본이 완벽하다" 는 뜻이고, 뷰 신뢰도가
    `50 × (1 − λ)` 이므로 **읽지 못한 것이 확신을 최대로 올린다.** 실제로 그렇게
    됐다 — `regime_mixture_moments` 가 국면별 dict 를 내는데 소비자가
    `isinstance(lam, (int, float)) else 0.0` 으로 걸러 매 리밸런싱에 `conf = 50`
    (최대)을 박았고, 전달계층 감사가 그것을 찾았다.

    잔여 모델리스크의 `Ξ = 0` 과 정확히 같은 계열의 오류다 — **안 잰 것이 확신을
    키우는 방향으로 기본값을 두지 않는다.**
    """
    lam = cond.get("shrinkage_lambda")
    if isinstance(lam, bool) or not isinstance(lam, (int, float)):
        kind = type(lam).__name__
        raise ValueError(
            f"수축강도가 스칼라가 아닙니다 (받은 것: {kind}). 국면별 값을 낸다면 "
            f"`shrinkage_lambda` 에 **집계 스칼라**를, 상세는 "
            f"`shrinkage_lambda_by_regime` 에 두어야 합니다 — 0.0 으로 떨어뜨리면 "
            f"읽지 못한 것이 뷰 신뢰도를 최대로 올립니다.")
    v = float(lam)
    if not math.isfinite(v):
        raise ValueError("수축강도가 유한한 값이 아닙니다.")
    return max(0.0, min(1.0, v))


def mixture_from_moments(*, mu_by_regime: dict[str, Any],
                         sigma_by_regime: dict[str, Any],
                         pi_path: list[dict[str, float]],
                         transition, regimes: list[str],
                         h_hold: int, names: list[str] | None = None) -> dict:
    """국면별 **연율** 적률 + 국면확률 경로 → 혼합 연율 μ̄/Σ̄.

    순수 함수다 — 표본도 DB 도 보지 않는다. 그래서 §1.3 의 항등식(동일국면 환원 ·
    두 전이극한 · 연율화 정합)을 **기계 정밀도로** 테스트할 수 있다.

    Args:
        mu_by_regime: `{국면: (n,) 연율 평균}`.
        sigma_by_regime: `{국면: (n, n) 연율 공분산}`.
        pi_path: `[{국면: 확률}, …]` 길이 `h_hold`. **π_1 … π_h** (오늘이 아니다).
        transition: `(R, R)` 전이행렬. ★행이 출발★ — `regime_transitions` 의
            `rows[i]["mean"]` 규약과 같다.
        regimes: 국면 이름 순서. 모든 배열의 축 순서를 이것이 정한다.
        h_hold: 홀딩 기간(**개월**). 리밸런싱 주기에서 온다.
        names: 자산 이름(응답 전달용).

    Returns:
        `{available, mu, sigma, W_h, A_h, pi_path, pi_bar, A_contribution_pct, …}`
        또는 `{available: False, reason}`.
    """
    P = np.asarray(transition, dtype=float)
    pis = _pi_matrix(pi_path, regimes)
    bad = _validate_path(pis, P, h_hold)
    if bad:
        return _unavailable(bad, names=list(names or []), h_hold=h_hold)

    try:
        M = np.array([np.asarray(mu_by_regime[r], dtype=float) for r in regimes])
        S = np.array([np.asarray(sigma_by_regime[r], dtype=float) for r in regimes])
    except KeyError as e:
        return _unavailable(f"국면 {e} 의 적률이 없습니다.", names=list(names or []))
    if not (np.isfinite(M).all() and np.isfinite(S).all()):
        return _unavailable("국면별 적률에 결측/무한값이 있습니다.", names=list(names or []))

    # 연율 → 월간. ★일별로 내려가지 않는다★ (모듈 상단 주석 참조)
    mu_cum, W, A = _mix_core(M / MONTHS_PER_YEAR, S / MONTHS_PER_YEAR, pis, P)
    n = M.shape[1]
    return _package_mixture(mu_cum, W, A, h_hold,
                            names or [f"a{i}" for i in range(n)], pis, regimes,
                            dropped_regimes={})


def _aggregate_lambda(per: dict, keep: list[str], pis: np.ndarray,
                      *, regimes: list[str]) -> float:
    """국면별 수축강도 → **π̄ 가중평균**. `LAMBDA_AGGREGATE_PI_WEIGHTED` 의 정의다."""
    pi_bar = pis.mean(axis=0)
    w = np.array([float(pi_bar[regimes.index(r)]) for r in keep], dtype=float)
    lam = np.array([float(per[r]["shrinkage_lambda"] or 0.0) for r in keep], dtype=float)
    tot = float(w.sum())
    return float((w @ lam) / tot) if tot > 1e-12 else float(lam.mean())


def regime_mixture_moments(returns_df, regime_by_month: dict[str, str] | None,
                           pi_path: list[dict[str, float]], transition,
                           regimes: list[str], *, h_hold: int,
                           min_obs_per_asset: float = MIN_OBS_PER_ASSET,
                           shrinkage="auto",
                           trading_days: float = TRADING_DAYS) -> dict:
    """표본에서 국면별 적률을 뽑아 `mixture_from_moments` 에 넘긴다.

    ★새 추정기를 만들지 않는다★ 국면별 μ/Σ 는 전부 `conditional_moments` 가 낸다 —
    표본 하한 게이트 · Ledoit-Wolf 수축 · 상관건전성 진단이 그대로 적용되고, 그래서
    `π` 가 원핫이면 결과가 기존 하드 라벨 경로와 **바이트 단위로 같아진다**.

    추정 불가 국면은 π 에서 빼고 재정규화하되 ★뺐다는 사실을 응답에 적는다★.
    어느 한 달에서 빠진 질량이 `DROPPED_MASS_LIMIT` 을 넘으면 혼합하지 않는다 —
    분포의 절반 이상을 지어낼 수는 없다.
    """
    P_full = np.asarray(transition, dtype=float)
    pis_full = _pi_matrix(pi_path, regimes)
    bad = _validate_path(pis_full, P_full, h_hold)
    if bad:
        return _unavailable(bad, names=[], h_hold=h_hold)

    per: dict[str, dict] = {}
    dropped: dict[str, str] = {}
    for r in regimes:
        cond = conditional_moments(returns_df, regime_by_month, r,
                                   min_obs_per_asset=min_obs_per_asset,
                                   shrinkage=shrinkage, trading_days=trading_days)
        if cond.get("available"):
            per[r] = cond
        else:
            dropped[r] = cond.get("reason") or "추정 불가"

    if not per:
        return _unavailable(
            "어느 국면에서도 조건부 적률을 추정할 수 없었습니다 — 혼합할 대상이 "
            "없습니다. 무조건부 추정을 쓰십시오.",
            names=[], h_hold=h_hold, dropped_regimes=dropped)

    keep = [r for r in regimes if r in per]
    idx = [regimes.index(r) for r in keep]
    mass = pis_full[:, idx].sum(axis=1)
    dropped_mass = float((1.0 - mass).max())
    if dropped_mass > DROPPED_MASS_LIMIT:
        return _unavailable(
            f"추정 불가 국면이 어느 달에 확률질량의 {dropped_mass:.1%} 를 차지합니다 "
            f"(한도 {DROPPED_MASS_LIMIT:.0%}). 남은 국면으로 재정규화하는 것은 근사이며, "
            "분포의 절반 이상을 대신 채울 수는 없습니다.",
            names=list(per[keep[0]]["names"]), h_hold=h_hold,
            dropped_regimes=dropped)
    if float(mass.min()) <= _PI_MASS_EPS:
        return _unavailable(
            "어느 달의 국면확률이 추정 가능한 국면에 전혀 걸려 있지 않습니다.",
            names=list(per[keep[0]]["names"]), h_hold=h_hold,
            dropped_regimes=dropped)

    # ★축소는 근사다 — 그래서 재검증하지 않고, 근사했다는 사실을 응답에 남긴다★
    # 남은 국면으로 재정규화하면 π 와 P 의 정합은 정의상 깨진다. 원본 입력은 위에서
    # 이미 검증했으므로, 여기서는 조건부 사슬(생존 국면에 조건을 건 사슬)을 쓴다.
    pis = pis_full[:, idx] / mass[:, None]
    P = P_full[np.ix_(idx, idx)]
    rows = P.sum(axis=1, keepdims=True)
    P = np.divide(P, rows, out=np.full_like(P, 1.0 / len(keep)), where=rows > 1e-12)

    names = list(per[keep[0]]["names"])
    M = np.array([np.asarray(per[r]["mu"], dtype=float) for r in keep])
    S = np.array([np.asarray(per[r]["sigma"], dtype=float) for r in keep])

    mu_cum, W, A = _mix_core(M / MONTHS_PER_YEAR, S / MONTHS_PER_YEAR, pis, P)
    out = _package_mixture(
        mu_cum, W, A, h_hold, names, pis, keep,
        dropped_regimes=dropped,
        dropped_mass_max=round(dropped_mass, 6),
        n_months_by_regime={r: per[r]["n_months"] for r in keep},
        n_obs_by_regime={r: per[r]["n_obs"] for r in keep},
        # ★소비자는 스칼라를 본다★ 국면별 상세는 버리지 않되, 기본 필드는 집계값이다.
        # 집계는 π̄ 가중평균이다 — `W_h` 자체가 국면별 수축 공분산을 π 로 섞은 것이라
        # 같은 가중을 쓰는 것이 유일하게 일관된 선택이다.
        shrinkage_lambda=_aggregate_lambda(per, keep, pis, regimes=keep),
        shrinkage_lambda_by_regime={r: float(per[r]["shrinkage_lambda"] or 0.0)
                                    for r in keep},
        shrinkage_lambda_aggregate=LAMBDA_AGGREGATE_PI_WEIGHTED,
        degenerate=any(bool(per[r]["degenerate"]) for r in keep),
    )
    if out.get("available"):
        note = (f"{len(keep)}개 국면의 조건부 적률을 {h_hold}개월 홀딩 기간의 "
                f"국면확률 경로로 혼합했습니다. 국면 간 산포가 공분산의 "
                f"{out['A_contribution_pct']:.2f}% 를 차지합니다 — 국면을 모를수록 "
                "이 값이 커지며, 그것이 리스크로 정직하게 옮겨간 몫입니다.")
        if dropped:
            note += (f" ★{', '.join(dropped)} 국면은 표본이 없어 제외하고 "
                     f"재정규화했습니다(최대 {dropped_mass:.1%}) — 축소된 사슬은 근사입니다.")
        out["note"] = note
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 뷰 신뢰도 — ★스칼라 휴리스틱 대신 Ω 를 분해해 계산한다★ (MS1-a)
# ══════════════════════════════════════════════════════════════════════════════
# 계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.5.3 · §1.5.4
#
# 현행 프로덕션은 `conf = _CONDITIONAL_MAX_CONFIDENCE(50.0) × (1 − λ)` 다. 그런데
# `conf` 는 임의의 노브가 **아니다** — `allocation_studio.build_user_views` 가
#
#     scale = (100 − conf) / max(conf, 1)
#     Ω     = diag( diag(P (τΣ) Pᵀ) · scale )
#
# 로 쓰므로 **`conf = 50` 은 `scale = 1`, 즉 `Ω = diag(P τΣ Pᵀ)` — He–Litterman
# 중립점**이다. 앵커는 원칙적이고, 검증된 적 없는 것은 `(1 − λ)` 곱이다.
#
# ★그래서 추측하지 않고 구성한다.★ Ω 는 **뷰 오차의 공분산**이라는 정해진 의미가
# 있으므로 세 항으로 분해할 수 있다:
#
#     Ω = 국면 불확실성(D)  +  μ̂ 추정오차(Σ_within × 12/n_months)  +  잔여 모델리스크(Ξ)
#
# ★독립 관측은 영업일이 아니라 개월이다★ 한 달의 21영업일은 국면 라벨 하나를
# 공유한다 — `conditional_moments` 가 `n_obs` 와 `n_months` 를 따로 내는 이유가
# 그것이고, 여기서 쓰는 것은 `n_months` 다. 영업일로 나누면 추정오차가 21배 작아져
# 신뢰도가 터무니없이 높아진다.
#
# ★★그리고 `Ξ` 를 0 으로 두면 안 된다★★
# 앞선 설계에서 잔여 모델리스크의 초기값을 0 으로 두고 라벨만 붙이려 했는데,
# `Ω` 가 작아지면 `conf` 는 **올라간다** — 즉 **모델리스크를 재지 않을수록 뷰가 더
# 강해진다.** 정확히 거꾸로다. 미측정은 0이 아니라 **선언된 보수적 하한**으로
# 표현한다: 모델리스크(국면 라벨 오류·분류체계 오설정·구조변화)가 우리가 실제로 잰
# 항들 중 가장 큰 것보다 작을 이유가 없다. 추정이 아니라 **가정**이며, 응답이
# `residual_policy` 로 그렇게 말한다.

RESIDUAL_UNMEASURED = "unmeasured"
RESIDUAL_MEASURED = "measured"
RESIDUAL_POLICY_FLOOR = "conservative_floor"
RESIDUAL_POLICY_MEASURED = "measured"

#: `build_user_views` 가 받는 신뢰도 범위. 0 이면 0으로 나누므로 하한을 둔다.
_CONF_MIN, _CONF_MAX = 1e-6, 100.0


def view_omega_terms(*, regime_diag, sigma_within_diag, n_months: int,
                     residual_diag=None) -> dict[str, Any]:
    """뷰 오차분산 Ω 의 대각을 세 항으로 분해한다.

    Args:
        regime_diag: 국면 간 산포 `D` 의 대각 (연율). `mixture_from_moments` 의
            `A_h` 와 같은 재료에서 온다.
        sigma_within_diag: 국면 내 공분산의 대각 (연율).
        n_months: ★독립 관측 개월 수★ — 영업일 수가 아니다.
        residual_diag: 실측된 잔여 모델리스크. `None` 이면 **보수적 하한**을 쓴다.

    Returns:
        `{omega_diag, terms{regime, estimation, residual}, residual_risk,
          residual_policy, n_months, note}`
    """
    D = np.asarray(regime_diag, dtype=float)
    W = np.asarray(sigma_within_diag, dtype=float)
    if D.shape != W.shape:
        raise ValueError("국면 산포와 국면 내 분산의 길이가 다릅니다.")
    if not (np.isfinite(D).all() and np.isfinite(W).all()):
        raise ValueError("Ω 분해 입력에 결측/무한값이 있습니다.")
    if (D < 0).any() or (W < 0).any():
        # ★음수 분산을 절댓값으로 덮지 않는다★ 들어왔다면 상류가 깨진 것이고,
        # 여기서 고치면 그 사실이 사라진다.
        raise ValueError("분산 항에 음수가 있습니다 — 상류 추정이 깨졌습니다.")
    if int(n_months) < 1:
        raise ValueError("독립 관측 개월 수는 1 이상이어야 합니다.")

    estimation = W * (MONTHS_PER_YEAR / float(int(n_months)))
    if residual_diag is None:
        # ★미측정 = 0 이 아니다★ (모듈 상단 주석 참조)
        residual = np.maximum(D, estimation)
        risk, policy = RESIDUAL_UNMEASURED, RESIDUAL_POLICY_FLOOR
        note = ("잔여 모델리스크를 아직 측정하지 않았습니다. 0 으로 두면 **안 잰 것이 "
                "확신을 높이므로**, 실제로 측정된 항 중 최대값을 보수적 하한으로 "
                "씁니다. 이것은 추정이 아니라 선언된 가정이며, 워크포워드로 실현 뷰 "
                "오차를 재면 이 값을 대체합니다.")
    else:
        residual = np.asarray(residual_diag, dtype=float)
        if residual.shape != D.shape:
            raise ValueError("잔여 리스크의 길이가 다릅니다.")
        if (residual < 0).any():
            raise ValueError("잔여 리스크에 음수가 있습니다.")
        risk, policy = RESIDUAL_MEASURED, RESIDUAL_POLICY_MEASURED
        note = "잔여 모델리스크를 워크포워드 실현 뷰 오차로 측정했습니다."

    return {
        "omega_diag": D + estimation + residual,
        "terms": {"regime": D, "estimation": estimation, "residual": residual},
        "residual_risk": risk,
        "residual_policy": policy,
        "n_months": int(n_months),
        "note": note,
    }


def implied_confidence(omega_diag, sigma_diag, *, tau: float = 0.05):
    """Ω → `build_user_views` 가 받는 0~100 신뢰도.

    `build_user_views` 의 `scale = (100 − conf)/conf` 를 뒤집은 것이다:

        Ω = base · scale,  base = τ·Σ_ii   ⟹   conf = 100 / (1 + Ω/base)

    ★`Ω = τΣ` 이면 정확히 50 이 나온다★ — 현행 `_CONDITIONAL_MAX_CONFIDENCE = 50.0`
    이 임의의 상수가 아니라 He–Litterman 중립점이라는 사실이 여기 남는다.
    """
    om = np.asarray(omega_diag, dtype=float)
    base = np.maximum(np.asarray(sigma_diag, dtype=float) * float(tau), 1e-18)
    conf = 100.0 / (1.0 + om / base)
    return np.clip(conf, _CONF_MIN, _CONF_MAX)
