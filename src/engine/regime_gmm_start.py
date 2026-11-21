"""GMM 시작 분포 — 배분의 셋째 국면 가중 (M3 · 설계 `docs/superpowers/specs/2026-11-16-emeans-gmm-strategy-design.md` §M3).
==============================================================================
답하는 물음은 ② 전달이다: ★보유 기간의 국면 분포를 'GMM 시작 분포 × 전이'로 잡으면 배분 입력 π 가 그렇게 바뀐다.★
예측력(③)은 이 모듈이 주장하지 않는다 — 같은 경로 · 같은 보유 기간의 워크포워드 점수(M2 `regime_skill` 의 후보
`gmm_start`)를 ★결과에 함께 싣는 것★이 계약이고(`regime_probability.from_gmm_start_path`), 점수가 없으면 세우지 않는다.
경제적 가치(④)는 재지 않는다.

    π₀  = 그 경로 전체의 성장·물가 축으로 적합한 GMM 의 시드 평균 소속 확률(`regime_skill.cached_arms` — 앙상블 · M2 와 같은 함수 · 같은 기억)
    π_j = π₀ · P̄^j   (j = 1 … 보유 기간 · P̄ 는 전이 예측과 같은 사후평균 전이행렬 — 같은 사슬)
    점수 = `regime_skill(points, k = 보유 기간)` 의 `gmm_start` 후보 — 배분에 쓰는 바로 그 예측(π₀ · P̄^k)을 각 시점 이전 자료로 다시 세워 채점한 것

★자료 흔들기에 대한 강건성은 관측만 한다(M1c 에서 넘긴 것)★ 달을 복원 추출해 다시 적합했을 때 지금 점의 최다 국면이 같은 비율
(`bootstrap_agreement`). π₀ 를 그 평균으로 바꾸지 않고 문턱도 두지 않는다 — 배분 입력을 바꾸는 정교화는 이 조각의 범위 밖이다.

세우지 못하면 `available: False` + 사유다(경로가 짧다 · 축 값이 없다 · GMM 적합 실패 · 점수 없음). 부르는 쪽(배분 파이프라인 ·
백테스트)이 그 사유를 달고 ★명시적으로★ 전이 예측으로 열화한다 — 이 모듈은 다른 방식으로 몰래 바꿔 내지 않는다.

★근거 관문(M4 · 받은 결정 D1-b)★ `evidence_gate` — 기본 배분 경로가 받는 출처를 같은 경로 · k = 보유 기간의 워크포워드 브라이어로
고른다: GMM 시작 분포 × 전이가 '오늘 국면 유지'와 '전이 예측'보다 엄격히 낮을 때만 이 방식, 아니면 전이 예측 + 사유.
고르는 규칙은 받은 결정이고 점수는 그 규칙의 입력일 뿐이다 — 같은 자료로 견줘 고른 쪽의 점수는 낙관적이다(응답이 그렇게 적는다).
"""
from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Sequence
from typing import Any

from src.engine import regime_skill as rs
from src.engine.regime_transitions import REGIMES

#: 부트스트랩 다시 뽑기 횟수 — 지금 점 하나의 답이 같은지 세는 데 쓴다(잰 값: 120개월 20회 0.36초 · 계획 §3.0).
BOOT_RESAMPLES = 20
#: 다시 뽑기의 씨앗 — 고정(같은 입력이면 같은 비율). 다시 뽑기 s 의 표본은 `default_rng([BOOT_SEED, s])` 가 정한다.
BOOT_SEED = 20261116
BOOT_METHOD = "bootstrap_months"
BOOT_NOTE = ("달을 복원 추출로 다시 뽑아 GMM 을 다시 적합했을 때 지금 점이 같은 국면에 가장 크게 속한 비율입니다 · 관측이며 "
             "π 를 바꾸지 않습니다. 성분 수 · 공분산 · 시작점 수는 시작 분포의 적합과 같고, 다시 뽑기마다 난수 시드 하나로 적합합니다.")
#: 백테스트의 재조정 달마다는 다시 뽑기를 돌리지 않는다(계획 §3.3) — 그 사실을 값 없음의 사유로 적는다.
BOOT_SKIPPED_REASON = "백테스트의 재조정 달마다는 다시 뽑기를 돌리지 않습니다(달마다 약 0.4초 · 라이브 경로에서만 잽니다)."

SKILL_NOTE = ("배분에 쓰는 이 예측(GMM 시작 분포 × 전이)을 각 시점 이전 자료만으로 다시 세워 보유 기간 뒤의 국면과 견준 점수입니다(워크포워드). "
              "합성 축에서 나온 점수는 장치가 뜻대로 도는지를 보일 뿐 실제로 더 맞힌다는 증거가 아닙니다.")

Arms = Callable[[Sequence[float], Sequence[float]], dict]
Bootstrap = Callable[[list[float], list[float], str], dict]


def _why(head: str, detail: str) -> str:
    """'머리 — 사유' 한 문장. 사유에 줄표가 이미 있으면 두 문장으로 잇는다 — 한 문장에 줄표 둘을 두지 않는다(M2 와 같은 규칙)."""
    detail = str(detail).strip()
    return f"{head} — {detail}" if " — " not in detail else f"{head}. {detail}"


def _no(reason: str, **extra: Any) -> dict[str, Any]:
    return {"available": False, "reason": reason, **extra}


def _axes(points: Sequence[dict]) -> tuple[tuple[float, ...], tuple[float, ...]] | str:
    """두 축의 튜플 — 한 달이라도 축 값이 없거나 숫자가 아니면 그 달을 적은 사유(문자열)."""
    g: list[float] = []
    i: list[float] = []
    for p in points:
        try:
            gv, iv = float(p["growth"]), float(p["inflation"])
        except (KeyError, TypeError, ValueError):
            return (f"{p.get('t') or '어느'} 달의 성장·물가 축 값이 없습니다(축 값 없이 굳혀진 경로). "
                    "GMM 은 축 값으로 적합하므로 축이 함께 굳혀진 경로가 필요합니다.")
        if not (math.isfinite(gv) and math.isfinite(iv)):
            return f"{p.get('t') or '어느'} 달의 성장·물가 축 값이 숫자가 아닙니다(결측 · 무한)."
        g.append(gv)
        i.append(iv)
    return tuple(g), tuple(i)


def skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
    """`regime_skill` 의 답 → 배분 출처에 싣는 점수(후보 `gmm_start` · 기준선 · 증거). 점수가 없으면 사유."""
    k = int(skill.get("k") or 0)
    if not skill.get("available"):
        return {"available": False, "reason": str(skill.get("reason") or "사유 미상"), "k": k}
    by_key = {c["key"]: c for c in skill.get("candidates") or []}
    cand, base = by_key.get("gmm_start"), by_key.get(rs.BASELINE)
    if not cand or not cand.get("available"):
        return {"available": False, "k": k,
                "reason": str((cand or {}).get("reason") or "GMM 시작 분포 후보의 점수가 없습니다.")}
    ev = skill.get("evidence") or {}
    return {
        "available": True, "candidate": "gmm_start", "name": rs.CANDIDATE_NAMES["gmm_start"],
        "k": k, "n_eval": int(skill["n_eval"]), "scored": dict(skill.get("scored") or {}),
        "hits": cand["hits"], "hit_rate": cand["hit_rate"], "brier": cand["brier"], "gain": cand["gain"],
        "baseline": {"key": rs.BASELINE, "name": rs.CANDIDATE_NAMES[rs.BASELINE],
                     "hits": (base or {}).get("hits"), "hit_rate": (base or {}).get("hit_rate"),
                     "brier": (base or {}).get("brier")},
        "evidence": cand.get("evidence"),
        "evidence_reason": ev.get("reason"),
        "threshold": ev.get("threshold"),
        "note": SKILL_NOTE,
    }


def bootstrap_agreement(g_hist: Sequence[float], i_hist: Sequence[float], label: str, *,
                        resamples: int = BOOT_RESAMPLES, seed: int = BOOT_SEED) -> dict[str, Any]:
    """달을 복원 추출해 GMM 을 다시 적합 → 지금 점(마지막 달)의 최다 국면이 `label` 과 같은 비율 — ★관측만★.

    적합 설정은 시작 분포와 같다(성분 수 규칙 · full · n_init 3 · 성분 중심의 사분면으로 모음). 다시 뽑기 s 는 난수 시드 s 하나로
    적합한다(시드 평균까지 하면 열 배가 든다 — 시드에 대한 민감도는 `stability` 가 따로 잰다). 실패한 다시 뽑기는 세지 않고 그 수를 적는다.
    """
    from src.engine.regime_axes import quadrant
    from src.engine.regime_ensemble import MIN_OBS, _cluster_k

    n = len(g_hist)
    if n < MIN_OBS:
        return _no(f"표본 {n}개월로 다시 뽑기에 필요한 {MIN_OBS}개월에 못 미칩니다.", method=BOOT_METHOD)
    try:
        # threadpoolctl 은 scikit-learn 의 의존성이다(함께 깔린다).
        import numpy as np
        from sklearn.mixture import GaussianMixture
        from threadpoolctl import threadpool_limits
    except Exception:  # noqa: BLE001
        return _no("scikit-learn 이 없어 다시 뽑기를 할 수 없습니다.", method=BOOT_METHOD)

    X = np.column_stack([np.asarray(g_hist, float), np.asarray(i_hist, float)])
    if not np.isfinite(X).all():
        return _no("축 시계열에 결측이 있어 다시 뽑을 수 없습니다.", method=BOOT_METHOD)
    now = X[-1].reshape(1, -1)
    k = _cluster_k(n)
    agree = failed = 0
    with threadpool_limits(limits=1):            # 시작 분포의 적합과 같은 까닭(작은 자료 · 기계마다 같은 합산 순서)
        for s in range(resamples):
            idx = np.random.default_rng([seed, s]).integers(0, n, size=n)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    gm = GaussianMixture(n_components=k, covariance_type="full", random_state=s, n_init=3).fit(X[idx])
                resp = gm.predict_proba(now)[0]
            except Exception:  # noqa: BLE001 — 세지 않고 수를 적는다
                failed += 1
                continue
            p = dict.fromkeys(REGIMES, 0.0)
            for c in range(k):
                p[quadrant(float(gm.means_[c][0]), float(gm.means_[c][1]))] += float(resp[c])
            agree += int(rs.top(p) == label)
    done = resamples - failed
    if done == 0:
        return _no(f"다시 뽑기 {resamples}회가 모두 실패했습니다.", method=BOOT_METHOD, failed=failed)
    return {"available": True, "method": BOOT_METHOD, "requested": resamples, "resamples": done, "failed": failed,
            "agree": agree, "share": round(agree / done, 4), "label": label, "seed": seed, "note": BOOT_NOTE}


SAMPLED_NOTE = ("{k}개월 뒤 분포 — GMM 시작 분포에서 출발해 전이행렬을 사후분포에서 {draws}회 뽑아 거듭제곱한 사후예측입니다 "
                "(전이 예측의 구간과 같은 뽑기 · 시작 분포만 다릅니다). 얇은 행의 불확실성이 여기까지 전달됩니다.")


def sampled_forecast(rows: list[dict], pi0: dict[str, float], k: int) -> dict[str, Any]:
    """π₀ 에서 출발하는 사후예측 — `regime_transitions.k_step_forecast` 와 같은 씨앗 · 같은 뽑기 · 같은 셈(시작 벡터만 다르다).

    배분의 Σ̄ 는 사후평균 행렬로 계산하므로 전이행렬 **파라미터**의 불확실성은 거기 전파되지 않는다 — 그 몫을 이 구간이 따로 보고한다
    (전이 예측의 `sampled_forecast` 와 같은 자리). 구간은 뽑은 값의 분위수이지 국면별 구간의 가중 평균이 아니다.
    """
    import numpy as np

    from src.engine.regime_probability import _start_vector
    from src.engine.regime_transitions import ALPHA_DIAG, ALPHA_OFF, CI, FORECAST_DRAWS, SEED

    if int(k) < 1:
        raise ValueError("예측 기간은 1개월 이상이어야 합니다.")
    start = _start_vector(pi0, list(REGIMES))
    rng = np.random.default_rng(SEED)
    alphas = np.array([[(ALPHA_DIAG if j == i else ALPHA_OFF) + rows[i]["counts"][j] for j in range(4)]
                       for i in range(4)], dtype=float)
    out = np.zeros((FORECAST_DRAWS, 4))
    for d in range(FORECAST_DRAWS):
        P = np.vstack([rng.dirichlet(alphas[i]) for i in range(4)])
        v = start
        for _ in range(int(k)):
            v = v @ P
        out[d] = v
    lo_q, hi_q = (1 - CI) / 2, 1 - (1 - CI) / 2
    mean, lo, hi = out.mean(axis=0), np.quantile(out, lo_q, axis=0), np.quantile(out, hi_q, axis=0)
    return {
        "available": True, "k": int(k), "from": "gmm_start", "draws": FORECAST_DRAWS,
        "mean": {REGIMES[j]: round(float(mean[j]), 6) for j in range(4)},
        "ci90": {REGIMES[j]: [round(float(lo[j]), 4), round(float(hi[j]), 4)] for j in range(4)},
        "note": SAMPLED_NOTE.format(k=int(k), draws=FORECAST_DRAWS),
    }


def gmm_start_path(points: Sequence[dict], h_hold: int, *, mode: str = "live", arms: Arms | None = None,
                   bootstrap: Bootstrap | None = None, with_robustness: bool = True) -> dict[str, Any]:
    """국면 경로(과거 → 지금) → `π_1 … π_h`(출처 `gmm_start_forecast`) + 행렬 · π₀ · 점수 · 시드 안정성 · 부트스트랩 안정성.

    세우지 못하면 `{available: False, reason, skill?}` — 점수가 없다는 사실도 싣는다. 받은 경로 밖의 자료는 보지 않는다(앞보기 0 —
    백테스트는 그 달까지 자른 경로를 넘긴다). `arms` · `bootstrap` 은 시험이 가짜를 넣는 자리다.
    """
    from src.engine.regime_ensemble import MIN_OBS
    from src.engine.regime_probability import from_gmm_start_path
    from src.engine.regime_transitions import count_transitions, transition_posterior

    h = int(h_hold)
    if h < 1:
        return _no("보유 기간은 1개월 이상이어야 합니다.")
    pts = list(points)
    unknown = sorted({str(p.get("regime")) for p in pts} - set(REGIMES))
    if unknown:
        return _no(f"알 수 없는 국면 라벨이 있습니다({', '.join(unknown)}).")
    if len(pts) < MIN_OBS:
        return _no(f"국면 경로가 {len(pts)}개월로 GMM 적합에 필요한 {MIN_OBS}개월에 못 미칩니다.")
    axes = _axes(pts)
    if isinstance(axes, str):
        return _no(axes)
    g, i = axes
    use_arms = arms or rs.cached_arms

    gmm = (use_arms(g, i) or {}).get("gmm") or {}
    if not gmm.get("available") or not isinstance(gmm.get("probs"), dict):
        return _no(_why("GMM 을 세우지 못했습니다", gmm.get("reason") or "사유 미상"))
    pi0 = {r: float(gmm["probs"].get(r, 0.0)) for r in REGIMES}

    skill = skill_summary(rs.regime_skill(pts, k=h, arms=use_arms))
    if not skill["available"]:
        return _no(_why("같은 경로의 워크포워드 점수가 없습니다", skill["reason"]), skill=skill)

    label = rs.top(pi0)
    if not with_robustness:
        robustness = _no(BOOT_SKIPPED_REASON, method=BOOT_METHOD)
    else:
        robustness = (bootstrap or bootstrap_agreement)(list(g), list(i), label)
    stability = gmm.get("stability")
    rows = transition_posterior(count_transitions(pts))
    try:
        probs, P = from_gmm_start_path(pi0, rows, h, list(REGIMES), skill=skill, mode=mode,
                                       stability=stability, robustness=robustness)
    except ValueError as e:
        return _no(_why("GMM 시작 분포를 만들지 못했습니다", str(e)), skill=skill)
    return {"available": True, "probs": probs, "P": P, "pi0": pi0, "label": label, "skill": skill,
            "stability": stability, "robustness": robustness, "n_months": len(pts), "h_hold": h}


#: 근거 관문(M4)의 화면 이름 — 캔버스 선택지 · 해설 · 결과 판이 이 이름을 쓴다(용어집 §3.16 · M2 후보가 아니라 고르는 규칙의 이름).
GATE_NAME = "근거 관문"
#: 근거 관문(M4) — 기본 배분 경로가 견주는 세 후보(고정 순서 · M2 후보 열쇠). 고르는 것은 GMM 시작 분포 × 전이와 전이 예측 둘뿐이다.
GATE_CANDIDATES: tuple[str, ...] = ("gmm_start", "persistence", "transition")
GATE_NOTE = ("같은 자료로 세 후보의 점수를 견줘 고른 값이라 고른 쪽의 점수는 낙관적입니다(견준 후보 셋). "
             "합성 축에서 나온 점수는 장치가 뜻대로 도는지를 보일 뿐 실제로 더 맞힌다는 증거가 아닙니다.")


def _gate_digits(values: Sequence[float]) -> int:
    """서로 다른 값이 같게 보이지 않는 가장 작은 자릿수(3 ~ 6) — 3자리에서 같아 보이는데 '낮아'라고 쓰지 않게.
    같은 값(동률)은 같게 보이는 것이 맞다. 점수표가 6자리로 반올림해 싣는 값이라 6 이면 늘 가른다."""
    for digits in range(3, 6):
        seen: dict[str, float] = {}
        if all(seen.setdefault(f"{v:.{digits}f}", v) == v for v in values):
            return digits
    return 6


def evidence_gate(points: Sequence[dict], h_hold: int, *, arms: Arms | None = None) -> dict[str, Any]:
    """근거 관문 (M4 · D1-b) → `{available, chosen, chosen_name, reason, k, n_eval, n_compared, compared, digits, note}`.

    `chosen` 은 배분의 국면 가중 코드다 — GMM 시작 분포 × 전이의 브라이어가 '오늘 국면 유지'와 '전이 예측'보다 ★엄격히★ 낮으면 `gmm`,
    아니면 `probabilistic`(전이 예측). 오늘 국면 유지가 가장 낮아도 전이 예측이다(기본 경로의 후보는 둘 — 사유가 그 사실을 적는다).
    점수가 없거나 세 후보 가운데 하나라도 못 섰으면 `available: False` · 전이 예측 + 사유(견주지 못했다는 사실).
    점수는 M2 의 `regime_skill` 그대로(같은 기억 · 한 번 묻는다) — 다시 셈하지 않고 ★실린 값(6자리)★으로 견준다(같으면 낮지 않다).
    받은 경로 밖의 자료는 보지 않는다 — 백테스트는 그 달까지 자른 경로를 넘긴다(앞보기 0). 사유 문장에는 숫자를 넣지 않는다
    (숫자는 `compared[*].shown` — `digits` 자리로 한 번 지은 글자를 표와 해설이 함께 쓴다).
    """
    k = int(h_hold)
    gm, pe, tr = (rs.CANDIDATE_NAMES[key] for key in GATE_CANDIDATES)

    def block(available: bool, chosen: str, reason: str, n_eval: int | None, compared: list[dict],
              digits: int | None = None) -> dict[str, Any]:
        return {"available": available, "chosen": chosen, "chosen_name": gm if chosen == "gmm" else tr, "reason": reason,
                "k": k, "n_eval": n_eval, "n_compared": len(GATE_CANDIDATES), "compared": compared,
                "digits": digits, "note": GATE_NOTE if available else None}

    pts = list(points)
    axes = _axes(pts)
    if isinstance(axes, str):          # 점수는 축으로 적합한다 — 축 없이 굳혀진 경로에서 예외를 내지 않고 사유로(`gmm_start_path` 와 같은 검사)
        return block(False, "probabilistic", f"같은 경로의 워크포워드 점수를 낼 수 없어 ‘{tr}’을 씁니다. {axes}", None, [])
    skill = rs.regime_skill(pts, k=k, arms=arms)
    if not skill.get("available"):
        return block(False, "probabilistic",
                     f"같은 경로의 워크포워드 점수가 없어 ‘{tr}’을 씁니다. {skill.get('reason') or '사유 미상'}", None, [])
    by_key = {c["key"]: c for c in skill.get("candidates") or []}
    compared = []
    for key in GATE_CANDIDATES:
        c = by_key.get(key) or {}
        ok = bool(c.get("available")) and c.get("brier") is not None
        compared.append({"key": key, "name": rs.CANDIDATE_NAMES[key], "brier": c.get("brier") if ok else None,
                         "available": ok, "shown": None})
    n_eval = int(skill["n_eval"])
    missing = next((c for c in compared if not c["available"]), None)
    if missing is not None:
        why = (by_key.get(missing["key"]) or {}).get("reason") or "사유 미상"
        return block(False, "probabilistic", f"‘{missing['name']}’ 후보의 점수가 없어 ‘{tr}’을 씁니다. {why}", n_eval, compared)

    g, p, t = (float(c["brier"]) for c in compared)
    digits = _gate_digits((g, p, t))
    for c in compared:          # 보이는 글은 여기서 한 번 — 해설과 화면이 같은 글자를 쓴다(반올림 규칙이 둘로 갈리지 않게)
        c["shown"] = f"{float(c['brier']):.{digits}f}"
    if g < p and g < t:
        return block(True, "gmm", f"브라이어 점수에서 ‘{gm}’가 ‘{pe}’와 ‘{tr}’보다 모두 낮아 ‘{gm}’를 씁니다.",
                     n_eval, compared, digits)
    unbeaten = "와 ".join(f"‘{name}’" for name, v in ((pe, p), (tr, t)) if not g < v)
    reason = f"브라이어 점수에서 ‘{gm}’가 {unbeaten}보다 낮지 않아 ‘{tr}’을 씁니다."
    if t > min(g, p):
        reason += (f" 셋 가운데 가장 낮은 점수는 ‘{tr}’이 아닙니다 — 기본 경로는 ‘{gm}’가 다른 둘보다 낮을 때만 그것을 쓰고 "
                   f"그 밖에는 ‘{tr}’을 씁니다(‘{pe}’는 기본 경로의 후보가 아닙니다).")
    return block(True, "probabilistic", reason, n_eval, compared, digits)
