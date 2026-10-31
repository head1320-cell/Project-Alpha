"""배분 벨리프 파이프라인 — ★조건부 μ/Σ → 검증 관문 → 배분 입력★ (P8 ②)

검토서: `docs/specs/2026-09-02-deepseek-concept-review.md` §3·§4 P8 (`3125001`)

왜 이 모듈이 있는가
──────────────────────────────────────────────────────────────────────────────
`/analyze` 와 `/rebalance-decision` 은 **같은 순서로 같은 것을 만들었다** —
조건부 스택 → 매크로 관문 → (차단 시 입력 버리기) → 기업 뷰 → `optimize`.
두 벌이 나란히 있었고, ★그 자리는 과거에 실제로 갈라진 자리다★:
`_conditional_stack` 의 주석이 그 사건을 적고 있다 — *"예전에는 같은 코드가 두 번
복사돼 있어, 한쪽만 고치면 화면에 따라 다르게 동작했다."*

P5 는 그 대가를 이미 치렀다: 미검증 매크로 관문을 **두 곳에** 배선해야 했고,
소비자가 하나 더 생기면 세 곳이 된다. 검토서 §3 이 그린 사슬

    … → Belief(μ/Σ) → ★Verification Gate★ → Portfolio Construction → …

은 새 계층을 세우자는 말이 아니라 ★이미 있는 노드에 이름을 주자★ 는 말이다.
`build_belief` 가 그 이름이고, 관문은 **여기 한 곳**에서만 지난다.

★행동은 바뀌지 않는다★ 아래 함수들의 본문은 `allocation_routes.py` 에서 그대로
옮겨 왔다. 단 하나 바꾼 것은 `_regime_path_for` 의 `req` 타입 주석이다 —
`AnalyzeRequest` 는 라우트 모듈에 있어 여기서 import 하면 순환이 된다. 이 모듈은
`req` 를 **덕 타이핑**으로 받는다(기존 `_conditional_stack(req, returns)` ·
`_company_view_stack(req, names)` 가 이미 그 관용구다).

왜 `src/api/` 인가
──────────────────────────────────────────────────────────────────────────────
`src/engine` 은 `src/api` 를 **한 번도** import 하지 않는다(방향은
`api → engine → services/data`, 테스트가 정적으로 강제한다). `src/services` 는
use-case 층이 아니라 engine **아래**의 수집·IO 층이다. 그래서 두 라우트가 함께
쓰는 것은 `src/api/` 에 둔다 — `json_safe.py` 가 같은 자리의 선례다.

★재수출 주의★ `allocation_routes` 가 이 이름들을 모듈 수준으로 다시 내보낸다.
`scripts/`·테스트 여러 곳이 그 경로로 import 하거나 monkeypatch 하기 때문이다.
다만 **호출부가 여기 있으면 `allocation_routes` 쪽 패치는 아무 일도 하지 않는다**
— 조용히. 패치는 이 모듈을 겨눠야 한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger("api.allocation")


# ── P2.5: 국면조건부 μ/Σ 배선 ────────────────────────────────────────────────
#
# 감사가 줄 번호로 증명한 것은 "파이프는 깔렸는데 아무것도 흐르지 않는다" 였다 —
# `optimize()` 의 Σ 는 무조건부 트레일링이고 μ 는 전부 사용자 뷰에서 온다. 아래 세
# 함수가 매크로를 그 숫자에 닿게 하는 배선이다.

# 국면 경로를 굳혀 둔 스냅샷이 없을 때 재계산하는 길이 — 빌더와 같은 값.
_PATH_MONTHS = 60

# 조건부 뷰의 신뢰도 상한. ★매크로가 최종 비중을 정하지 않는다★(Brief §17)
# 50 은 `build_user_views` 의 Idzorek 기본값(스케일 1.0)이므로, 조건부 뷰는 아무리
# 표본이 두꺼워도 사용자 뷰보다 세질 수 없다. 표본이 얇으면(수축 λ→1) 신뢰도가
# 0 으로 내려가 뷰가 사실상 무시되고 시장균형이 남는다 — λ 를 신뢰도로 번역하는
# 것이지 새 하이퍼파라미터를 발명하는 것이 아니다.
_CONDITIONAL_MAX_CONFIDENCE = 50.0

# 조건부 μ 를 **뷰로** 받는 모델. 나머지는 공분산 전용이므로 Σ 만 바뀐다 —
# 그것이 맞다(μ 를 안 받는 모델에 μ 를 몰래 태우면 모델이 다른 것이 된다).
_VIEW_MODELS = ("bl", "ep")


def _regime_path_for(req) -> dict:            # req: AnalyzeRequest (덕 타이핑)
    """월별 국면 경로 — **저장된 것 우선, 없으면 재계산 + 라벨**.

    ★Brief §16 이 금지하는 것이 "과거 결정을 현재 데이터로 다시 계산" 이다.★
    스냅샷에 굳혀 둔 경로가 있으면 그것이 그 시점에 알 수 있었던 분류다. 없으면
    재계산할 수밖에 없지만, 그때는 `path_source: "recomputed"` 와 함께 그 사실을
    응답에 적는다 — 하되 숨기지 않는다.
    """
    from src.data.regime_snapshots import get_snapshot
    for sid, label in ((req.mes_id, "mes"), (req.regime_snapshot_id, "regime_snapshot")):
        if not sid:
            continue
        pts = (get_snapshot(sid) or {}).get("regime_path")
        if pts:
            return {"points": pts, "path_source": label, "path_note": None, "reason": None}

    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        from src.engine.regime_transitions import regime_path
        macro_snap = RegimeAnalyzer().collector.collect_all(use_cache=True)
        pts = regime_path(getattr(macro_snap, "series", None) or {}, "kr",
                          months=_PATH_MONTHS).get("points") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("국면 경로 재계산 실패: %s", e)
        return {"points": [], "path_source": None, "path_note": None,
                "reason": f"국면 경로를 만들 수 없습니다 ({type(e).__name__}) — "
                          "무조건부 추정으로 계산했습니다."}
    if not pts:
        return {"points": [], "path_source": None, "path_note": None,
                "reason": "성장·물가 축이 둘 다 산출된 달이 없어 국면 경로가 비었습니다 — "
                          "무조건부 추정으로 계산했습니다."}
    return {
        "points": pts, "path_source": "recomputed", "reason": None,
        "path_note": ("이 경로는 **현재 데이터로** 다시 계산했습니다 — 결정 시점에 "
                      "알 수 있었던 분류가 아닙니다. 고정된 국면 경로를 쓰려면 "
                      "경로가 함께 굳혀진 스냅샷(mes_id)을 지정하십시오."),
    }


def _conditional_views(cond: dict, model: str) -> tuple[list[dict] | None, float | None]:
    """조건부 μ → 자산별 **절대 뷰**. (뷰 목록, 적용 신뢰도).

    ★μ 를 optimizer 에 직접 대입하지 않는 이유가 이 함수의 존재 이유다.★ 직접
    대입하면 "매크로 신호 → 비중" 이라는 기존 구조를 이름만 바꿔 되풀이한다.
    자산 하나짜리 절대 뷰로 표현하면 `P` 행이 `e_i` 가 되므로 **새 뷰 스키마를
    만들지 않고** 기존 `build_user_views` 를 그대로 탄다.
    """
    if model not in _VIEW_MODELS:
        return None, None
    lam = cond.get("shrinkage_lambda")
    conf = (_CONDITIONAL_MAX_CONFIDENCE * (1.0 - float(lam))) if lam is not None \
        else _CONDITIONAL_MAX_CONFIDENCE
    conf = round(max(0.0, min(conf, _CONDITIONAL_MAX_CONFIDENCE)), 2)
    views = [
        {"assets": [name], "direction": 1 if float(m) >= 0 else -1,
         "magnitude_pct": abs(float(m)) * 100.0, "confidence": conf,
         "source": "conditional", "regime": cond.get("regime")}
        for name, m in zip(cond["names"], cond["mu"]) if float(m) != 0.0
    ]
    return (views or None), conf


#: 리밸런싱 주기 → 홀딩 기간(개월). ★`h_hold` 는 여기서만 나온다★ — 자유 입력이
#: 아니고, 국면 기대 지속기간(실측 2.5~5.0개월)을 흘려 넣는 자리도 아니다.
_HOLD_MONTHS = {"M": 1, "Q": 3}

#: 국면 축이 실제로 읽는 시장. `regime_path(..., "kr", ...)` 와 맞춰 둔다 —
#: 두 곳이 갈라지면 PIT 블록이 **다른 축의 계열**을 보고 판정하게 된다.
_PIT_MARKET = "kr"


def _pit_block(mode: str, market: str = _PIT_MARKET) -> dict:
    """★PIT 상태는 3차원이다 — 단일 `pit_verified` 를 만들지 않는다★ (계획 §1.6.1).

    셋을 한 불리언으로 접는 순간 revision bias 가 그 안에 숨고 "PIT 통과" 라는
    표시가 거짓말이 된다. 셋은 서로 독립이며 하나가 참이라고 나머지가 참이 되지 않는다.

    ★`revision_bias` 를 전역 상수로 박지 않는다★ 예전에는 `_REVISION_BIAS =
    "unmanaged"` 였다. 값은 맞았지만 **어느 계열 때문인지**를 말하지 못했고, 그래서
    두 종류의 차단이 같은 라벨을 달고 있었다:

      · ECOS·KRX 계열 — 제공자가 빈티지 엔드포인트를 주지 않는다. ★영구★
      · FRED 계열 — 소스에는 빈티지가 있고 수집 경로만 현재값을 쓴다. ★고칠 수 있다★

    판정은 `regime_axes.axis_revision_status()` 하나가 한다(제공자 사실은
    `source_registry`, 경로 사실은 `AXIS_PATH_USES_VINTAGE`). 여기서 다시 판정하면
    같은 판단이 두 곳에 생기고 반드시 갈라진다.
    """
    from src.engine.regime_axes import axis_revision_status
    rev = axis_revision_status(market)
    return {
        # 국면 라벨의 뿌리인 `regime_axes.zscore_at` 이 후행 윈도우만 본다.
        "look_ahead_free": True,
        # 계열별 공표지연은 아직 선언돼 있지 않다(MS2 · 정책문서에서 붙는다).
        "publication_lag": "unspecified",
        "revision_bias": rev["revision_bias"],
        # ★계열별 근거를 함께 낸다★ 라벨만 내면 무엇을 고쳐야 하는지 알 수 없다.
        "revision_detail": {
            "market": rev["market"],
            "path_uses_vintage": rev["path_uses_vintage"],
            "blocked_permanently": rev["blocked_permanently"],
            "blocked_by_path": rev["blocked_by_path"],
            "series": rev["series"],
        },
        "mode": mode,
        "note": ("세 속성은 서로 독립입니다. " + rev["note"] +
                 " 공표지연을 선언해도 개정 편향은 해소되지 않습니다 — 값 자체가 "
                 "사후 수정본이기 때문입니다."),
    }


def _freshness(coverage: dict | None) -> dict:
    """★이 결정이 얼마나 낡은 데이터 위에 섰는가★ — `coverage` 에서 **파생**한다.

    라우트는 이미 `end`(마지막 관측일)와 `as_of_effective`(서버가 실제로 쓴 절단일)를
    갖고 있는데 결정 기록에는 담기지 않았다. 지어내지 않고 있는 것을 옮긴다.

    ★못 구하면 `None` + 사유★ 0 으로 채우면 "오늘 데이터다" 로 읽히는데, 그것은
    **모른다**와 다른 진술이다(이 저장소의 `미상 ≠ 0` 규율).
    """
    cov = coverage or {}
    end, eff = cov.get("end"), cov.get("as_of_effective")
    out = {"last_observation": end, "as_of_effective": eff,
           "source": cov.get("source"), "n_obs": cov.get("n_obs"),
           "stale_days": None, "reason": None,
           "note": ("절단일과 마지막 관측일의 차이입니다 — 휴장일이면 자연히 0 보다 "
                    "큽니다. 이 값 하나로 '낡았다' 를 판정하지 마십시오.")}
    if not end or not eff:
        out["reason"] = ("마지막 관측일 또는 절단일을 알 수 없어 신선도를 잴 수 "
                         "없습니다 — 미상은 0 이 아닙니다.")
        return out
    try:
        out["stale_days"] = (date.fromisoformat(str(eff))
                             - date.fromisoformat(str(end))).days
    except ValueError as e:
        out["reason"] = f"날짜를 해석할 수 없습니다: {e}"
    return out


def _company_view_stack(req, names: list[str]) -> dict | None:
    """기업 밸류에이션 뷰 — ★두 화면이 갈리지 않게 한 곳에서★

    `/analyze` 와 `/rebalance-decision` 이 **같은 헬퍼**를 탄다(`_conditional_stack`
    이 이미 같은 이유로 존재한다: *"예전에는 같은 코드가 두 번 복사돼 있어, 한쪽만
    고치면 화면에 따라 다르게 동작했다"*).

    Returns:
        요청하지 않았으면 `None` — 그때 라우트는 **응답 키를 만들지 않는다**.
        요청했으면 `{"views", "block"}`.
    """
    if not getattr(req, "use_company_views", False):
        return None

    from src.engine.company_views import company_views, prices_for

    prices, price_source = prices_for(names)
    views, reasons = company_views(names, prices, as_of=req.as_of)
    return {
        "views": views or None,
        "block": {
            "requested": True,
            "applied": len(views),
            "views": views,
            "reasons": reasons,
            "price_source": price_source,
            # ★등급을 적는다★ 이 뷰는 빈티지 재무가 없어 과거로 못 간다.
            "research_usage": (views[0]["research_usage"] if views else
                               _forward_only()),
            "any_mock": any(v.get("is_mock") for v in views),
            "saturated": sum(1 for v in views if v.get("confidence_saturated")),
            "note": ("밸류에이션 분포의 p50 갭을 수렴 기간으로 편 연간 뷰입니다. "
                     "폭 중 측정된 것은 하나도 없고 신뢰도는 BL 의 Ω 에만 닿습니다"
                     "(EP 는 confidence_used:false). as_of 를 고정하면 빈티지 재무가 "
                     "없어 뷰를 내지 않습니다 — 그 사유가 reasons 에 있습니다."),
        },
    }


def _forward_only() -> str:
    """뷰가 하나도 없을 때도 등급은 **파생**해서 답한다 — 손으로 적지 않는다."""
    from src.data.pit_macro import derive_usage
    return derive_usage(has_vintage=False, depth_ok=True, lag_known=True).value


def _conditional_stack(req, returns) -> dict:
    """★조건부 μ/Σ 의 단일 출처★ — `/analyze` 와 `/optimize` 가 같은 것을 쓴다.

    두 라우트에 같은 코드가 복사돼 있었다. 한쪽만 고치면 화면에 따라 다르게 동작하고,
    그 차이는 응답을 나란히 놓고 보기 전에는 드러나지 않는다.

    Returns:
        `{cond, path, s_override, extra_views, view_conf, meta}` — `meta` 는
        응답의 `conditional` 블록이 그대로 실을 조각이다.
    """
    from src.engine.conditional_market import regime_by_month_from_path

    path = _regime_path_for(req)
    by_month, _dropped = regime_by_month_from_path(path["points"])
    current = path["points"][-1].get("regime") if path["points"] else None
    weighting = getattr(req, "regime_weighting", "hard")
    mode = getattr(req, "regime_mode", "live")
    h_hold = _HOLD_MONTHS.get(getattr(req, "rebalance", "M"), 1)
    meta: dict = {"regime_weighting": "hard", "mode": mode,
                  "h_hold": None, "pi_path": None, "pi_bar": None,
                  "A_contribution_pct": None, "sharpness": None,
                  "probability_source": None, "mixture_note": None,
                  "dropped_regimes": None, "pit": _pit_block(mode)}

    # ★백테스트 모드는 아직 열려 있지 않다★ 라이브 수치를 백테스트인 척 쓰지
    # 못하게, 계산하지 않고 사유를 돌려준다(계획 §1.6.2 의 3단계 전).
    if mode == "backtest":
        blocked = _unavailable_conditional(
            "백테스트 모드는 아직 열려 있지 않습니다 — ECOS revision 정책 문서와 "
            "계열별 공표지연 선언이 선행조건입니다(계획 §1.6.2). 빈티지가 없는 채로 "
            "과거를 재현하면 값 자체가 미래를 알기 때문에, 못 한다고 말합니다.")
        return {"cond": blocked, "path": path, "s_override": None,
                "extra_views": None, "view_conf": None, "meta": meta}

    cond = _hard_conditional(returns, by_month, current)

    if weighting == "probabilistic":
        mixed, meta = _mixture_conditional(req, returns, by_month, current,
                                           path, h_hold, mode, meta)
        if mixed is not None:
            cond = mixed

    s_override = extra_views = view_conf = None
    if cond.get("available"):
        s_override = cond["sigma"]
        extra_views, view_conf = _conditional_views(cond, req.model)
        meta["confidence_model"] = cond.get("confidence_model") or {
            "kind": "legacy_scalar",
            "note": ("수축 강도만으로 정한 스칼라 신뢰도입니다 — Ω 를 분해해 계산한 "
                     "값이 아니므로 승격 근거로 쓰지 마십시오(계획 §1.5.3)."),
        }
    return {"cond": cond, "path": path, "s_override": s_override,
            "extra_views": extra_views, "view_conf": view_conf, "meta": meta}


def _hard_conditional(returns, by_month, current) -> dict:
    """현행 경로 — 오늘의 점 라벨 하나로 조건부를 만든다."""
    from src.engine.conditional_market import conditional_moments
    return conditional_moments(returns, by_month, current)


def _unavailable_conditional(reason: str) -> dict:
    from src.engine.conditional_market import _unavailable
    return _unavailable(reason)


def _mixture_conditional(req, returns, by_month, current, path,
                         h_hold: int, mode: str, meta: dict):
    """확률 혼합 경로. 실패하면 `(None, meta)` 로 돌려 하드로 떨어지되 **사유를 남긴다**."""
    import numpy as _np

    from src.engine.conditional_market import (
        implied_confidence,
        regime_mixture_moments,
        view_omega_terms,
    )
    from src.engine.regime_probability import (
        from_k_step_forecast,
        from_posterior_mean_path,
        require_portfolio_source,
    )
    from src.engine.regime_transitions import (
        REGIMES,
        count_transitions,
        transition_posterior,
    )

    try:
        rows = transition_posterior(count_transitions(path["points"]))
        # ★π_1 … π_h — 종단 분포 하나가 아니다★ 홀딩 기간 동안 **매 달의** 국면이
        # 수익에 관여하므로 경로 전체가 필요하다(계획 §1.3.3).
        #
        # ★그리고 π 와 P 는 같은 사슬에서 나와야 한다★ 국면 간 항은 결합분포를
        # 쓰므로, `k_step_forecast` 의 표집 평균(E[P^j])을 사후평균 행렬((E[P])^j)과
        # 섞으면 Jensen 격차 때문에 결과가 공분산이 아니게 된다(실측 j=3 에서
        # 8.9e−3 어긋남 — 혼합 함수의 일관성 검사가 실제로 이것을 잡았다).
        probs = [require_portfolio_source(p) for p in
                 from_posterior_mean_path(rows, current, h_hold, list(REGIMES),
                                          mode=mode)[0]]
        P = from_posterior_mean_path(rows, current, h_hold, list(REGIMES),
                                     mode=mode)[1]
        # 표집 기반 예측은 **신용구간을 보고하기 위해** 따로 부른다 — Σ̄ 에는
        # 전파되지 않으며, 그 몫은 잔여 모델리스크(Ξ)가 흡수한다.
        sampled = from_k_step_forecast(rows, current, k=h_hold, mode=mode)
        mix = regime_mixture_moments(returns, by_month,
                                     [p.probs for p in probs], P, list(REGIMES),
                                     h_hold=h_hold)
    except Exception as e:  # noqa: BLE001
        meta["mixture_note"] = (f"국면 예측을 만들지 못해 하드 라벨로 계산했습니다 "
                                f"({type(e).__name__}: {e}).")
        return None, meta

    if not mix.get("available"):
        meta["mixture_note"] = (f"국면 혼합을 하지 못해 하드 라벨로 계산했습니다 — "
                                f"{mix.get('reason')}")
        meta["dropped_regimes"] = mix.get("dropped_regimes")
        return None, meta

    # ★신뢰도는 Ω 를 분해해 계산한다★ 스칼라 휴리스틱을 표준으로 굳히지 않는다.
    sig = _np.asarray(mix["sigma"], dtype=float)
    W_ann = _np.asarray(mix["W_h"], dtype=float) * (12.0 / h_hold)
    A_ann = _np.asarray(mix["A_h"], dtype=float) * (12.0 / h_hold)
    n_months = max(1, min(mix.get("n_months_by_regime", {}).values(), default=1))
    terms = view_omega_terms(regime_diag=_np.maximum(_np.diag(A_ann), 0.0),
                             sigma_within_diag=_np.maximum(_np.diag(W_ann), 0.0),
                             n_months=n_months)
    conf = implied_confidence(terms["omega_diag"], _np.diag(sig))

    mix["confidence_model"] = {
        "kind": "decomposed_omega", "version": 1,
        "terms": {k: [float(x) for x in v] for k, v in terms["terms"].items()},
        "omega_diag": [float(x) for x in terms["omega_diag"]],
        "implied_confidence": [round(float(x), 4) for x in conf],
        "residual_risk": terms["residual_risk"],
        "residual_policy": terms["residual_policy"],
        "n_months": terms["n_months"],
        "note": terms["note"],
    }
    # 자산별 신뢰도를 하나로 줄여 뷰에 넘긴다 — ★가장 약한 쪽을 따른다★.
    mix["shrinkage_lambda"] = 1.0 - float(_np.min(conf)) / 100.0
    mix["regime"] = current

    from src.engine.regime_probability import RegimeProbabilities
    sharp = RegimeProbabilities(source="k_step_forecast_mean", step_months=h_hold,
                                probs=mix["pi_bar"], usage="portfolio",
                                mode=mode).sharpness
    prob0 = {
        "source": probs[-1].source, "usage": probs[-1].usage,
        "step_months": h_hold, "mode": mode,
        "probs": mix["pi_path"][-1],
        "sharpness": sharp,
        # ★파라미터 불확실성은 Σ̄ 에 전파되지 않는다 — 여기서 따로 보고한다★
        "sampled_forecast": {"probs": sampled.probs, "ci90": sampled.ci90,
                             "note": sampled.note},
        "uncertainty_note": ("Σ̄ 는 사후평균 전이행렬로 계산했습니다 — π 와 P 가 같은 "
                             "사슬에서 나와야 국면 간 항이 공분산이 되기 때문입니다. "
                             "전이행렬 **파라미터**의 불확실성(위 `sampled_forecast` 의 "
                             "구간)은 Σ̄ 에 전파되지 않았고, 잔여 모델리스크로 남습니다."),
    }

    meta.update({
        "regime_weighting": "probabilistic",
        "h_hold": h_hold,
        "pi_path": mix["pi_path"],
        "pi_bar": mix["pi_bar"],
        "A_contribution_pct": mix["A_contribution_pct"],
        "sharpness": sharp,
        "probability_source": prob0,
        "dropped_regimes": mix.get("dropped_regimes"),
        "mixture_note": mix.get("note"),
    })
    return mix, meta


def _months_span(returns) -> int | None:
    """표본 기간의 개월 수 — 판정 패널과 비교하기 위한 값.

    ★모르면 `None` 이다★ 0 으로 채우면 "0개월짜리 표본" 이라는 하지 않은 진술이
    되고, 범위 비교가 조용히 거짓이 된다.
    """
    try:
        idx = getattr(returns, "index", returns)
        if idx is None or len(idx) < 2:
            return None
        a, b = idx[0], idx[-1]
        return int((b.year - a.year) * 12 + (b.month - a.month))
    except Exception:                              # noqa: BLE001
        return None


def _macro_verification(*, universe, months, model) -> dict:
    """이 매크로 조건부 경로의 ★검증 상태★ — 단일 출처 (P5 ②).

    ★"계산할 수 있었는가" 와 "스킬을 보인 적 있는가" 는 다른 질문이다★
    `_conditional_block` 은 전자에 정직했지만 후자에는 침묵했다. A4 가
    `underpowered`, A3 이 `inconclusive` 로 판정한 신호를 그 판정을 한 번도 읽지
    않고 최적화기에 태우고 있었다.

    ★메커니즘 판정을 요청 판정으로 옮기지 않는다★ — `research_manifest` 의
    `this_request_verified` 가 그 선을 긋는다.
    """
    from src.engine.build_probe import current_identity
    from src.engine.research_manifest import load_manifest, verification_label

    manifest, why = load_manifest()
    # ★값이 아니라 식별자를 넘긴다★ 문자열만 넘기면 트리 상태를 잃고, 그러면
    # 노후화 검사가 다시 **대답할 수 없는 질문**이 된다 (AM3).
    lab = verification_label(manifest, universe=universe, months=months,
                             model=model, code_version=current_identity())
    if manifest is None:
        lab = {**lab, "manifest_reason": why}
    return lab


def macro_gate_decision(verification: dict | None, *,
                        require_verified: bool) -> tuple[bool, str | None]:
    """검증 라벨 + 플래그 → `(차단할 것인가, 사유)`. ★순수 함수다.★

    판정은 규칙이지 데이터가 아니므로 라우트 밖에서 데이터 없이 걸 수 있어야
    한다(`decide_verdict`·`summarize_capacity`·`decisive_diff` 와 같은 형태).

    ★미상은 통과가 아니다★ 라벨이 없거나 망가져도 통과시키지 않는다 — 켜 둔
    플래그가 조용히 무력해지는 것이 가장 나쁜 결과다.
    """
    if not require_verified:
        return False, None
    v = verification or {}
    if v.get("this_request_verified") is True:
        return False, None
    verdict = v.get("mechanism_verdict")
    why = v.get("reason")
    return True, (
        "require_verified_macro=true 인데 이 경로는 검증되지 않았습니다 — "
        f"메커니즘 판정 {verdict!r}"
        + (f": {why}" if why else
           " (검증 라벨을 읽지 못했습니다 — 미상은 통과가 아닙니다)")
        + ". 조건부 μ/Σ 를 적용하지 않고 무조건부로 계산했습니다.")


def _conditional_block(cond: dict, path: dict, *, sigma_applied: bool,
                       mu_as_views: int, view_confidence: float | None,
                       model: str, meta: dict | None = None,
                       universe=None, months=None,
                       blocked_reason: str | None = None) -> dict:
    """응답의 `conditional` 조각 — ★조용한 폴백 금지★.

    조건부를 못 쓴 경우 계산은 무조건부로 떨어지되 **응답이 그 사실을 말한다**
    (M2-A 의 `feasible:false` 처리와 같은 원칙). 숫자만 보고 "국면이 반영됐다" 고
    믿을 수 있는 상태를 만들지 않는 것이 이 블록의 목적이다.
    """
    ok = bool(cond.get("available"))
    if ok and model not in _VIEW_MODELS:
        mu_note = (f"'{model}' 은 공분산 전용 모델이라 μ 를 받지 않습니다 — Σ 만 "
                   "국면조건부로 바뀌었습니다. 조건부 μ 까지 반영하려면 bl 또는 ep 를 "
                   "선택하십시오.")
    elif ok and view_confidence == 0.0:
        # ★뷰를 넘겼다는 것과 뷰가 힘을 가졌다는 것은 다른 사실이다★ 신뢰도 0 이면
        # Ω 가 매우 커져 뷰가 사실상 무시되고 μ 는 시장균형으로 남는다. `mu_as_views`
        # 만 보고 "매크로가 반영됐다" 고 읽지 못하게 여기서 못을 박는다.
        mu_note = (f"조건부 μ 를 자산 {mu_as_views}개의 절대 뷰로 넘겼지만 **신뢰도가 "
                   "0 이라 사실상 반영되지 않았습니다** — 수축 강도가 1.0 이어서 "
                   "표본이 사전분포 이상을 말하지 못했다는 뜻이고, μ 는 시장균형으로 "
                   "남았습니다.")
    elif ok:
        mu_note = (f"조건부 μ 를 자산 {mu_as_views}개의 절대 뷰로 태웠습니다 "
                   f"(신뢰도 {view_confidence}). 최적화기에 직접 대입하지 않는 것은 "
                   "불확실성을 Ω 에 남기기 위해서입니다.")
    else:
        mu_note = "국면조건부 추정을 쓰지 못해 **무조건부 트레일링 μ/Σ 로 계산했습니다.**"

    return {
        "requested": True,
        "available": ok,
        "method": cond.get("method"),
        "regime": cond.get("regime"),
        "n_obs": cond.get("n_obs"),
        "n_months": cond.get("n_months"),
        "n_obs_by_regime": cond.get("n_obs_by_regime"),
        "n_months_by_regime": cond.get("n_months_by_regime"),
        "min_obs_required": cond.get("min_obs_required"),
        "unlabeled_obs": cond.get("unlabeled_obs"),
        "shrinkage_lambda": cond.get("shrinkage_lambda"),
        # ★λ=1.0 이면 Σ 가 스케일 단위행렬로 무너져 스케일 불변 모델의 비중이
        # 국면과 무관하게 같아진다★ 그 화면을 "배선이 안 됐다" 로 읽지 못하게 한다.
        "degenerate": bool(cond.get("degenerate")),
        "diagnostics": cond.get("diagnostics"),
        "path_source": path.get("path_source"),
        "path_note": path.get("path_note"),
        "applied_to": {"sigma": sigma_applied, "mu_as_views": mu_as_views},
        "view_confidence": view_confidence,
        # ★근본 원인을 먼저 적는다★ 경로를 못 만들면 엔진은 "월별 라벨이 없다" 고
        # 답하는데, 그것은 결과이지 원인이 아니다. 경로 사유가 있으면 그것이 앞선다 —
        # 순서를 반대로 뒀더니 "수집이 실패했다" 가 응답에서 사라졌다.
        "reason": path.get("reason") or cond.get("reason"),
        "note": mu_note,
        # ★반쯤 조건부인 차트를 만들지 않는다★ 프론티어 곡선·MC 클라우드·1년 분포는
        # 전체 표본에서 계산되므로 조건부가 아니다. 같은 화면에 조건부 비중과
        # 무조건부 프론티어가 나란히 서 있다는 사실을 서버가 먼저 말한다.
        "not_applied_to": ["frontier.curve", "frontier.cloud", "mc", "mu_annual"],
        # ★모든 분기가 낸다 (P5)★ `available` 여부와 무관하다 — 어떤 응답에만
        # 있으면 소비자가 `.get()` 으로 읽다가 `None` 을 거짓으로 취급한다(이
        # 모듈의 `prob_*` 규율과 같은 이유). 그리고 조건부를 **쓴** 응답에만
        # 검증을 실으면, 쓰지 못한 응답은 검증 상태를 물어볼 수도 없게 된다.
        "verification": {**_macro_verification(universe=universe, months=months,
                                               model=model),
                         "blocked": blocked_reason is not None,
                         "blocked_reason": blocked_reason},
        # ★MS1-a 계약 필드★ — 가중 방식 · 지평 · π 경로 · 날카로움 · 신뢰도 모델 ·
        # PIT 3필드. `meta` 가 없으면(구 호출부) 하드 경로의 기본값을 적는다.
        **(meta or {"regime_weighting": "hard", "mode": "live",
                    "pit": _pit_block("live")}),
    }

# ══════════════════════════════════════════════════════════════════════════
# ★단 하나의 문★ — 두 라우트가 벨리프를 얻는 유일한 경로
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Belief:
    """조건부 μ/Σ 와 ★그것을 써도 되는가★ 를 함께 들고 다닌다.

    `s_override`·`extra_views`·`view_confidence` 는 **관문을 통과한 뒤의 값**이다
    — 차단되면 `None` 이다. 그래서 이 객체를 받은 쪽은 "막혔는지" 를 따로 챙기지
    않아도 막힌 대로 계산하게 된다. ★차단했다고 말만 하고 그대로 쓰는 것★ 이
    구조적으로 불가능하다(그것이 변이 X7 이었다).

    `cond`·`path`·`meta` 는 **보고용**이라 차단돼도 남는다 — 응답이 "무엇을
    계산할 수 있었는데 왜 안 썼는지" 를 말해야 하기 때문이다.
    """
    cond: dict | None
    path: dict | None
    meta: dict | None
    s_override: Any
    extra_views: list[dict] | None
    view_confidence: float | None
    blocked: bool
    blocked_reason: str | None


#: 조건부를 요청하지 않았을 때. ★없음을 지어내지 않는다★ — 전부 `None` 이고
#: `blocked` 는 거짓이다(막힌 것이 아니라 **묻지 않은** 것이다).
_NO_BELIEF = Belief(None, None, None, None, None, None, False, None)


def build_belief(req, returns, names: list[str]) -> Belief:
    """조건부 μ/Σ → ★검증 관문★ → 배분에 넘길 입력.

    ★관문은 여기 한 곳이다★ 예전에는 두 라우트가 각자 이 순서를 반복했고, P5 가
    관문을 넣을 때 **두 곳에** 배선해야 했다. 소비자가 늘면 그만큼 늘어난다.

    `req` 는 덕 타이핑이다 — `AnalyzeRequest` 와 그 자손
    `RebalanceDecisionRequest` 가 들어온다.
    """
    if not getattr(req, "conditional", False):
        return _NO_BELIEF

    stack = _conditional_stack(req, returns)
    # ★미검증이면 적용하지 않는다 (P5 ③)★ 기본 OFF 라 동작 불변이다.
    blocked, why = macro_gate_decision(
        _macro_verification(universe=names, months=_months_span(returns),
                            model=req.model),
        require_verified=req.require_verified_macro)
    if blocked:
        # ★버리는 것은 **적용 입력**뿐이다★ 진단(cond·path·meta)은 남겨야
        # 응답이 무엇을 왜 안 썼는지 말할 수 있다.
        return Belief(stack["cond"], stack["path"], stack["meta"],
                      None, None, None, True, why)
    return Belief(stack["cond"], stack["path"], stack["meta"],
                  stack["s_override"], stack["extra_views"], stack["view_conf"],
                  False, why)
