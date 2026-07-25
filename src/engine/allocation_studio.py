"""Allocation Studio 엔진 — 사용자 뷰 Black-Litterman + 모델 스위치
==================================================================
Two Sigma Venn 벤치마킹 "Allocation Studio" 탭의 순수 함수 엔진.

기존 재사용 (신규 수학 최소화):
  - risk_allocations의 _cov(Ledoit-Wolf)/_opt(SLSQP)/_hrp_weights/_pct 헬퍼를
    커스텀 수익률 행렬 R로 호출 — 8-ETF 하드와이어는 s_* 래퍼에만 있고
    헬퍼 자체는 행렬 인자를 받는다.
  - BL posterior 공식은 risk_allocations.s_black_litterman(331-333행)과 동일:
    μ_bl = ((τΣ)⁻¹ + PᵀΩ⁻¹P)⁻¹ ((τΣ)⁻¹π + PᵀΩ⁻¹Q), π = δ·Σ·w_mkt
  - 시가총액 prior: stock_master.get_market_cap (KIS master, 억원)

이 모듈의 실제 신규 내용:
  - 사용자 뷰({assets, direction, magnitude_pct, confidence 0~100}) → P/Q/Ω
    행렬 구성. Ω는 Idzorek 관례(diag(P·τΣ·Pᵀ))에 신뢰도 스케일
    (100-conf)/max(conf,1)을 곱함 — conf 50이면 기본 Idzorek, conf→100이면
    Ω→0(뷰 강제), conf→0이면 Ω→∞(뷰 무시, 시장균형 복귀).
  - 임의 유니버스(한국 주식+ETF) 모델 스위치. 뷰는 BL 모델에서만 기대수익에
    반영(risk_parity/hrp/min_var는 공분산 전용 — UI에 명시).
"""

from __future__ import annotations

import logging

import numpy as np

from src.engine.risk_allocations import _cov, _opt

logger = logging.getLogger(__name__)

DELTA_DEFAULT = 2.5   # 위험회피(균형 기대수익 스케일) — risk_allocations와 동일
TAU_DEFAULT = 0.05    # prior 불확실성 — risk_allocations와 동일

MODELS = ("mvo", "bl", "risk_parity", "hrp", "min_var", "max_div", "min_cvar")


# ── 시가총액 prior ────────────────────────────────────────────────────────────
def market_cap_weights(names: list[str]) -> tuple[np.ndarray, list[str]]:
    """KIS master 시총(억) 캡가중 w_mkt. 결측 자산은 가용 시총의 중앙값으로
    채우고 결측 티커 목록을 함께 반환(정직 라벨용). 전부 결측이면 균등가중."""
    from src.data.stock_master import get_market_cap
    caps: list[float | None] = []
    missing: list[str] = []
    for t in names:
        v = get_market_cap(t)
        if v is not None and v > 0:
            caps.append(float(v))
        else:
            caps.append(None)
            missing.append(t)
    avail = [c for c in caps if c is not None]
    n = len(names)
    if not avail:
        return np.ones(n) / n, missing
    med = float(np.median(avail))
    arr = np.array([c if c is not None else med for c in caps], dtype=float)
    return arr / arr.sum(), missing


# ── 사용자 뷰 → P/Q/Ω ────────────────────────────────────────────────────────
def build_user_views(views: list[dict] | None, names: list[str],
                     sigma: np.ndarray, tau: float = TAU_DEFAULT):
    """사용자 뷰 목록 → (P, Q, Ω, skipped). 유효한 뷰가 없으면 (None, None, None, skipped).

    뷰 스키마: {"assets": [코드...], "direction": 1|-1,
               "magnitude_pct": 연간 기대수익 크기(%), "confidence": 0~100}
    P행은 대상 자산 균등가중 피킹(그룹 뷰 지원). 유니버스에 없는 자산만
    지정한 뷰·크기 0 뷰는 조용히 버리지 않고 스킵 목록으로 보고.
    """
    idx = {t: i for i, t in enumerate(names)}
    rows, q, scales, skipped = [], [], [], []
    for v in views or []:
        assets = [a for a in (v.get("assets") or []) if a in idx]
        mag = abs(float(v.get("magnitude_pct") or 0.0)) / 100.0
        if not assets or mag == 0.0:
            skipped.append({"view": v, "reason": "대상 자산 없음 또는 크기 0"})
            continue
        direction = 1.0 if float(v.get("direction", 1)) >= 0 else -1.0
        conf = min(max(float(v.get("confidence", 50)), 0.0), 100.0)
        row = np.zeros(len(names))
        for a in assets:
            row[idx[a]] = 1.0 / len(assets)
        rows.append(row)
        q.append(direction * mag)
        # conf 50 → 1.0(Idzorek 기본) · conf→100 → ~0(뷰 강제) · conf→0 → 매우 큼(뷰 무시)
        scales.append((100.0 - conf) / max(conf, 1.0))
    if not rows:
        return None, None, None, skipped
    P = np.array(rows)
    Q = np.array(q)
    base = np.maximum(np.diag(P @ (tau * sigma) @ P.T).copy(), 1e-10)
    omega = np.diag(base * np.maximum(np.array(scales), 1e-4)) + np.eye(len(q)) * 1e-10
    return P, Q, omega, skipped


def bl_posterior(pi: np.ndarray, sigma: np.ndarray, P: np.ndarray,
                 Q: np.ndarray, omega: np.ndarray, tau: float = TAU_DEFAULT) -> np.ndarray:
    """BL posterior 기대수익 — risk_allocations.s_black_litterman과 동일 공식."""
    tauS = tau * sigma
    inv_tauS = np.linalg.inv(tauS)
    inv_om = np.linalg.inv(omega)
    return np.linalg.solve(inv_tauS + P.T @ inv_om @ P,
                           inv_tauS @ pi + P.T @ inv_om @ Q)


# ── 모델 스위치 ───────────────────────────────────────────────────────────────
def effective_number_of_bets(w: np.ndarray, S: np.ndarray) -> float:
    """Meucci ENB — 상관을 고려한 실질 분산도. Σ의 고유분해로 주성분 포트폴리오의
    분산 기여 분포 엔트로피 = exp(-Σ pᵢ ln pᵢ). HHI/Neff와 달리 상관을 반영한다.
    무상관·등리스크면 ENB=N, 완전집중이면 →1. (1 ≤ ENB ≤ N)"""
    w = np.asarray(w, dtype=float)
    n = w.size
    try:
        vals, vecs = np.linalg.eigh(S)          # Σ = V Λ Vᵀ (대칭)
        vals = np.maximum(vals, 1e-16)
        expo = vecs.T @ w                        # 주성분 노출
        contrib = (expo ** 2) * vals            # 주성분별 분산 기여
        tot = contrib.sum()
        if not np.isfinite(tot) or tot <= 0:
            return float(n)
        p = contrib / tot
        p = p[p > 1e-12]
        ent = -float(np.sum(p * np.log(p)))
        return float(np.exp(ent))
    except Exception:
        return float(n)


def _inverse_vol_w(R: np.ndarray) -> np.ndarray:
    vol = R.std(axis=0)
    vol = np.where(vol > 1e-9, vol, 1e-9)
    w = 1.0 / vol
    return w / w.sum()


def _erc_weights(S: np.ndarray) -> np.ndarray:
    """동일 리스크 기여(ERC) — risk_allocations.s_risk_parity의 반복을 행렬 인자화."""
    n = S.shape[0]
    w = 1.0 / np.sqrt(np.maximum(np.diag(S), 1e-12))
    w = w / w.sum()
    for _ in range(200):
        mrc = S @ w
        rc = w * mrc
        target = (w @ S @ w) / n
        w = w * np.sqrt(target / (rc + 1e-12))
        w = np.maximum(w, 0.0)
        tot = w.sum()
        if tot <= 0:
            break
        w = w / tot
    return w


def _max_sharpe_w(mu: np.ndarray, S: np.ndarray, n: int) -> np.ndarray | None:
    def neg_sharpe(x):
        pv = np.sqrt(x @ S @ x)
        return -(x @ mu) / (pv + 1e-12)
    return _opt(neg_sharpe, n)


def weights_for_model(model: str, R: np.ndarray, mu_override: np.ndarray | None = None,
                      S_annual: np.ndarray | None = None) -> np.ndarray:
    """모델 → long-only 합1 가중치 벡터. 최적화 실패/부재 시 inverse-vol 폴백.

    mvo: 트레일링 평균 max-sharpe · bl: mu_override(BL posterior) max-sharpe ·
    risk_parity: ERC · hrp: 계층적 · min_var: 최소분산.
    """
    n = R.shape[1]
    S = S_annual if S_annual is not None else _cov(R) * 252.0
    if model == "min_var":
        w = _opt(lambda x: float(x @ S @ x), n)
    elif model == "risk_parity":
        w = _erc_weights(S)
    elif model == "hrp":
        try:
            from src.engine.risk_allocations import _HAS_HCLUST, _hrp_weights
            w = _hrp_weights(S) if _HAS_HCLUST else None
        except Exception:
            w = None
    elif model == "max_div":
        # 최대분산(TOBAM): maximize (wᵀσ)/√(wᵀΣw) — risk_allocations.s_max_div 로직 재사용
        sig = np.sqrt(np.maximum(np.diag(S), 1e-12))
        w = _opt(lambda x: -(x @ sig) / (np.sqrt(x @ S @ x) + 1e-12), n)
    elif model == "min_cvar":
        # 최소 CVaR (Rockafellar-Uryasev) — 히스토리컬 최악 α% 평균손실 최소화
        alpha = 0.05
        k = max(1, int(np.ceil(alpha * R.shape[0])))

        def _cvar(x):
            pl = R @ x                        # 포트 일별 수익
            worst = np.sort(pl)[:k]           # 최악 α%
            return -float(worst.mean())       # 손실(음수수익)의 크기 최소화
        w = _opt(_cvar, n)
    else:  # "mvo" | "bl"
        mu = mu_override if mu_override is not None else R.mean(axis=0) * 252.0
        w = _max_sharpe_w(mu, S, n)
    if w is None or not np.all(np.isfinite(w)) or w.sum() <= 0:
        return _inverse_vol_w(R)
    w = np.maximum(np.asarray(w, dtype=float), 0.0)
    return w / w.sum()


# ── 전체 파이프라인 (API가 호출하는 단일 진입점) ──────────────────────────────
def optimize(model: str, names: list[str], R: np.ndarray,
             views: list[dict] | None = None,
             delta: float = DELTA_DEFAULT, tau: float = TAU_DEFAULT) -> dict:
    """모델+뷰 → 최종 가중치 + Sankey 3단계(시장→뷰반영→최적화) + 메타.

    flow 의미: market = 시가총액 캡가중 · view_applied = 뷰가 있으면 BL
    posterior max-sharpe(없으면 market과 동일) · optimized = 선택 모델 출력.
    뷰는 BL 경로에서만 기대수익에 반영 — 공분산 전용 모델(risk_parity/hrp/
    min_var)을 선택한 경우에도 view_applied 열은 참고용으로 계산해 보여준다.
    """
    if model not in MODELS:
        model = "mvo"
    n = len(names)
    S = _cov(R) * 252.0  # 연율화 — 뷰(연간 %)·μ와 단위 일치
    w_mkt, cap_missing = market_cap_weights(names)

    mu_bl = None
    skipped_views: list[dict] = []
    w_view = w_mkt
    if views:
        pi = delta * S @ w_mkt
        P, Q, omega, skipped_views = build_user_views(views, names, S, tau)
        if P is not None:
            try:
                mu_bl = bl_posterior(pi, S, P, Q, omega, tau)
                wv = _max_sharpe_w(mu_bl, S, n)
                if wv is not None and np.all(np.isfinite(wv)) and wv.sum() > 0:
                    w_view = np.maximum(wv, 0.0)
                    w_view = w_view / w_view.sum()
            except Exception as e:  # 특이 공분산 등 — prior 폴백(정직 보고)
                logger.warning(f"BL posterior 실패, prior 폴백: {e}")
                mu_bl = None

    if model == "bl":
        # BL 모델: 뷰 있으면 posterior max-sharpe(=w_view), 뷰 없으면 시장균형
        # (레퍼런스 s_black_litterman과 동일 — 뷰 없는 BL은 캡가중 prior 그대로)
        w_final = w_view if mu_bl is not None else w_mkt
    else:
        w_final = weights_for_model(model, R, mu_override=None, S_annual=S)

    return {
        "names": names,
        "weights": w_final,
        "flow": {"market": w_mkt, "view_applied": w_view, "optimized": w_final},
        "views_applied": mu_bl is not None,
        "skipped_views": skipped_views,
        "cap_missing": cap_missing,
        "mu_annual": (R.mean(axis=0) * 252.0),
        "mu_used": (mu_bl if mu_bl is not None else R.mean(axis=0) * 252.0),
        "sigma_annual": S,
    }


# ── Sensitivity Heatmap (Robustness 재정의 — 기댓값 변동 → Weight 민감도) ──────
def sensitivity_matrix(names: list[str], R: np.ndarray,
                       views: list[dict] | None = None,
                       delta: float = DELTA_DEFAULT, tau: float = TAU_DEFAULT,
                       bump_pct: float = 2.0) -> dict:
    """자산 i의 기대수익 μ_i에 +bump(연 %p) 충격 → max-sharpe 재최적화 →
    matrix[i][j] = w_j(shock i) − w_j(base) (%p, N×N).

    base μ는 optimize()와 동일 경로(뷰 있으면 BL posterior, 없으면 히스토리컬
    연율 평균) — Robustness가 검증하는 대상이 실제 사용 중인 기대수익이 되도록.
    행별 Δ 합은 합1 제약으로 ≈0. SLSQP N회(N≤30)라 수 초 내.
    """
    n = len(names)
    base = optimize("bl" if views else "mvo", names, R, views=views,
                    delta=delta, tau=tau)
    S = base["sigma_annual"]
    mu0 = np.asarray(base["mu_used"], dtype=float)
    w0 = np.asarray(base["weights"], dtype=float)
    bump = float(bump_pct) / 100.0

    matrix: list[list[float]] = []
    for i in range(n):
        mu = mu0.copy()
        mu[i] += bump
        w = _max_sharpe_w(mu, S, n)
        if w is None or not np.all(np.isfinite(w)) or w.sum() <= 0:
            w = w0  # 최적화 실패 시 base 유지(Δ=0 행 — 정직한 무반응)
        else:
            w = np.maximum(np.asarray(w, dtype=float), 0.0)
            w = w / w.sum()
        matrix.append([round(float((w[j] - w0[j]) * 100.0), 2) for j in range(n)])

    return {
        "names": names,
        "base_weights": [round(float(x) * 100.0, 2) for x in w0],
        "matrix": matrix,           # 행=충격 자산, 열=반응 비중 Δ%p
        "bump_pct": bump_pct,
        "views_applied": base["views_applied"],
    }
