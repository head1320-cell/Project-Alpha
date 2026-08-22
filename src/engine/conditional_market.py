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


def regime_by_month_from_path(points: list[dict] | None) -> tuple[dict[str, str], int]:
    """`regime_transitions.regime_path()["points"]` → ({월: 국면}, 버린 개수).

    ★`T-k` 라벨은 버린다★ `_month_labels` 는 시계열이 요청보다 짧으면 앞을 `T-3`
    처럼 채운다. 그것은 **날짜가 아니라 자리표시자**이므로 수익률의 달과 맞출 수
    없다. 조용히 섞지 않고 버리고, 몇 개를 버렸는지 함께 돌려준다.
    """
    out: dict[str, str] = {}
    dropped = 0
    for p in points or []:
        t = str(p.get("t") or "")
        regime = p.get("regime")
        if not regime or len(t) != 7 or t[4] != "-" or not t[:4].isdigit():
            dropped += 1
            continue
        out[t] = str(regime)
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
        "unlabeled_obs": 0, "diagnostics": None,
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

    months = np.array([_month_key(ts) for ts in returns_df.index])
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

    return {
        "available": True,
        "method": method,
        "mu": mu,
        "sigma": sigma,
        "shrinkage_lambda": (round(lam, 4) if lam is not None else None),
        "diagnostics": _correlation_health(R),
        "reason": None,
        "note": (f"'{current_regime}' 국면으로 분류된 {common['n_months']}개월"
                 f"({n_obs}영업일)의 표본만으로 추정했습니다. 독립적인 거시 관측은 "
                 f"영업일 수가 아니라 **개월 수**입니다."),
        **common,
    }
