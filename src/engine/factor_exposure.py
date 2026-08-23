"""팩터 인지 — ★자산 개수가 아니라 팩터 개수를 본다★ (Brief §8.4)

    "asset count 가 아니라 factor count 를 본다."

`effective_number_of_bets`(Meucci ENB)는 이미 있고 로버스트 최적화가 쓴다. 다만
그것은 **통계적** 팩터다 — Σ 의 주성분이라 이름이 없다. "우리 포트폴리오가
듀레이션에 얼마나 노출됐는가" 에는 답하지 못한다. 이 모듈이 채우는 것이 그 칸이다.

★실측이 팩터 목록을 정했다★ 수집기 61계열 중 월별 관측을 실제로 내는 것만 쓴다:

    팩터        대리계열              월수
    equity      KOSPI                 59
    duration    KR_10Y                59
    inflation   KR_CPI                59
    growth      KR_LEADING_CYCLE      59
    credit      KR_TERM_SPREAD        59   (KR_CREDIT_SPREAD 는 **0** — 못 쓴다)
    commodity   DCOILWTICO            59
    usd         USD_KRW               59
    volatility  VIXCLS                59
    liquidity   NFCI                  59

`KR_CREDIT_SPREAD`·`KR_CORE_CPI`·`KR_M2` 는 수집기에 **있지만** 월별 관측이 0이라
쓸 수 없다 — 있고 없고가 아니라 **쓸 수 있고 없고**를 봐야 한다.

★차원의 저주를 숨기지 않는다★ 월 관측이 59개인데 팩터가 9개면 다변량 회귀는
자유도가 위태롭다. 그래서 P2-4 와 같은 **단변량** 베타를 쓰고, 관측/모수 비율을
출력에 적는다. 여러 팩터를 동시에 봤다는 사실도 함께 적는다(다중검정).
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# 팩터 → 대리계열 후보(우선순위). 앞의 것이 쓸 수 있으면 그것을 쓴다.
# ★후보를 여럿 두는 이유★ 수집기에 있어도 월별 관측이 0인 계열이 있다(실측).
FACTOR_PROXIES: dict[str, tuple[str, ...]] = {
    "equity": ("KOSPI",),
    "duration": ("KR_10Y", "DGS10"),
    "inflation": ("KR_CPI", "T10YIE"),
    "growth": ("KR_LEADING_CYCLE", "KR_IP", "INDPRO"),
    "credit": ("KR_CREDIT_SPREAD", "KR_TERM_SPREAD", "BAMLH0A0HYM2"),
    "commodity": ("DCOILWTICO",),
    "usd": ("USD_KRW", "DTWEXBGS"),
    "volatility": ("VIXCLS",),
    "liquidity": ("KR_M2", "NFCI", "M2SL"),
}

# ★계열마다 변화의 단위가 다르다★ 가격·지수는 **비율**이 맞지만 금리·스프레드·
# 표준화지수는 **차분**이어야 한다. 0 을 지나거나 0 근처인 계열에 `cur/prev − 1` 을
# 쓰면 값이 폭발한다 — 실측에서 `VIXCLS` 가 음수(최소 −5.09)를 지나며 한 달 변화가
# **6730%** 로 튀었고, 그 이상치 하나가 Ledoit-Wolf 를 λ=1.0(항등행렬)로 밀어
# 상관구조를 통째로 지웠다. CLAUDE.md 의 "음수가 들어갈 수 있는 파생식은 가드하라"
# 와 같은 부류다.
_CHANGE_KIND: dict[str, str] = {
    # 가격·지수·물가 — 항상 양수인 수준값이라 비율이 뜻을 갖는다.
    "KOSPI": "pct", "USD_KRW": "pct", "DTWEXBGS": "pct", "DCOILWTICO": "pct",
    "KR_CPI": "pct", "KR_CORE_CPI": "pct", "KR_LEADING_CYCLE": "pct",
    "KR_IP": "pct", "INDPRO": "pct", "KR_M2": "pct", "M2SL": "pct",
    # 금리·스프레드·표준화지수 — 차분(%p·포인트)이 경제적 단위다.
    "KR_10Y": "diff", "DGS10": "diff", "T10YIE": "diff",
    "KR_TERM_SPREAD": "diff", "KR_CREDIT_SPREAD": "diff", "BAMLH0A0HYM2": "diff",
    "VIXCLS": "diff", "NFCI": "diff",
}
_DEFAULT_KIND = "diff"      # 모르는 계열은 안전한 쪽(차분)으로
_ZERO_GUARD = 1e-6          # |prev| 가 이보다 작으면 비율을 쓰지 않는다


def series_changes(series, name: str = "") -> tuple[dict[str, float], str, str | None]:
    """매크로 계열 → ({월: 변화}, 사용한 변환, 사유).

    ★어느 변환을 썼는지 반드시 돌려준다★ 비율과 차분은 **단위가 다른 숫자**라,
    무엇을 썼는지 모르면 베타를 해석할 수 없다.
    """
    from src.engine.conditional_market import _normalize_month

    kind = _CHANGE_KIND.get(name, _DEFAULT_KIND)
    ts = list(getattr(series, "timestamps", None) or [])
    vals = list(getattr(series, "values", None) or [])
    pairs = []
    for t, v in zip(ts, vals, strict=False):
        m = _normalize_month(str(t)[:7])
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if m is not None:
            pairs.append((m, fv))
    pairs.sort()

    note = None
    if kind == "pct":
        # ★0 을 지나거나 0 근처면 비율을 쓰지 않는다★ 조용히 폭발시키지 않는다.
        levels = [v for _, v in pairs]
        if any(abs(v) < _ZERO_GUARD for v in levels) or (
                any(v > 0 for v in levels) and any(v < 0 for v in levels)):
            kind = "diff"
            note = (f"'{name}' 은 비율 변환 대상이지만 0 을 지나거나 0 근처라 "
                    "차분으로 바꿨습니다 — 비율이면 값이 폭발합니다")

    out: dict[str, float] = {}
    for (_, prev), (m, cur) in zip(pairs, pairs[1:], strict=False):
        if kind == "diff":
            out[m] = cur - prev
        elif abs(prev) >= _ZERO_GUARD:
            out[m] = cur / prev - 1.0
    return out, kind, note


FACTORS = tuple(FACTOR_PROXIES)
MIN_MONTHS = 24          # P2-4 와 같은 하한 — 얇은 베타는 부호도 못 믿는다
_RESOLVABLE_T = 2.0


def _macro_series_map() -> tuple[dict | None, str | None]:
    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        return RegimeAnalyzer().collector.collect_all(use_cache=True).series, None
    except Exception as e:  # noqa: BLE001
        logger.warning("매크로 수집 실패: %s", e)
        return None, f"매크로 계열을 수집하지 못했습니다 ({type(e).__name__})"


def resolve_proxies(series_map: dict | None = None,
                    min_months: int = MIN_MONTHS) -> dict:
    """팩터 → 실제로 쓸 대리계열. ★있는 것이 아니라 쓸 수 있는 것을 고른다★"""
    if series_map is None:
        series_map, err = _macro_series_map()
        if series_map is None:
            return {"available": False, "reason": err, "resolved": {}, "unresolved": {}}

    resolved: dict[str, dict] = {}
    unresolved: dict[str, str] = {}
    for factor, candidates in FACTOR_PROXIES.items():
        tried = []
        for name in candidates:
            s = series_map.get(name)
            if s is None:
                tried.append(f"{name}(수집기에 없음)")
                continue
            changes, kind, note = series_changes(s, name)
            if len(changes) < min_months:
                tried.append(f"{name}(월 관측 {len(changes)}개)")
                continue
            resolved[factor] = {"series": name, "n_months": len(changes),
                                "changes": changes, "transform": kind,
                                "transform_note": note}
            break
        else:
            unresolved[factor] = (f"쓸 수 있는 대리계열이 없습니다 — 시도: "
                                  f"{', '.join(tried)}")
    return {"available": bool(resolved), "resolved": resolved,
            "unresolved": unresolved,
            "reason": None if resolved else "어떤 팩터도 대리계열을 찾지 못했습니다"}


def asset_factor_betas(codes: list[str], *, series_map: dict | None = None,
                       min_months: int = MIN_MONTHS,
                       months: int = 60) -> dict:
    """자산별 · 팩터별 **단변량** 베타.

    ★다변량으로 한 번에 풀지 않는다★ 월 관측 59개에 팩터 9개면 자유도가 위태롭고
    매크로 계열끼리 상관이 높아 계수가 불안정해진다. P2-4 가 쓴 단변량 방식을
    그대로 쓰고, **몇 개를 동시에 봤는지**를 출력에 적는다.
    """
    from src.engine.conditional_market import _month_key
    from src.engine.valuation.macro_sensitivity import (
        _monthly_returns,
        _ols_beta,
    )

    prox = resolve_proxies(series_map, min_months)
    if not prox["available"]:
        return {"available": False, "reason": prox["reason"],
                "unresolved": prox["unresolved"]}

    assets: dict[str, dict] = {}
    for code in codes:
        rets = _monthly_returns(str(code), months=months)
        if rets is None or rets.empty:
            assets[str(code)] = {"available": False,
                                 "reason": "월별 수익률을 만들 수 없습니다"}
            continue
        stock = {_month_key(ts): float(v) for ts, v in rets.items()}

        betas: dict[str, dict] = {}
        for factor, info in prox["resolved"].items():
            macro = info["changes"]
            shared = sorted(set(macro) & set(stock))
            if len(shared) < min_months:
                betas[factor] = {"available": False, "n_obs": len(shared),
                                 "reason": (f"겹치는 달이 {len(shared)}개뿐이라 "
                                            f"기울기를 내지 않았습니다 "
                                            f"(최소 {min_months}개)")}
                continue
            fit = _ols_beta([macro[m] for m in shared], [stock[m] for m in shared])
            fit["series"] = info["series"]
            fit["transform"] = info["transform"]
            fit["span"] = [shared[0], shared[-1]]
            if fit.get("available") and fit.get("t_stat") is not None:
                fit["resolvable"] = bool(abs(fit["t_stat"]) >= _RESOLVABLE_T)
            betas[factor] = fit
        assets[str(code)] = {"available": True, "reason": None, "betas": betas}

    ok = [a for a in assets.values() if a.get("available")]
    n_factors = len(prox["resolved"])
    n_obs = min((i["n_months"] for i in prox["resolved"].values()), default=0)
    return {
        "available": bool(ok), "assets": assets,
        "factors": list(prox["resolved"]),
        "proxies": {f: i["series"] for f, i in prox["resolved"].items()},
        # ★비율과 차분은 단위가 다른 숫자다★ 무엇을 썼는지 밝혀야 베타를 읽을 수 있다.
        "transforms": {f: i["transform"] for f, i in prox["resolved"].items()},
        "unresolved": prox["unresolved"],
        # ★차원의 저주를 숨기지 않는다★
        "sample": {"n_months": n_obs, "n_factors": n_factors,
                   "obs_per_factor": (round(n_obs / n_factors, 2)
                                      if n_factors else None)},
        "multiple_testing": {
            "n_tested": n_factors,
            "note": (f"팩터 {n_factors}개를 동시에 봤습니다 — 개별 t값을 그 사실과 "
                     "함께 읽으십시오. 유의한 것만 골라 내면 데이터 마이닝입니다."),
        },
        "method": "univariate_ols_monthly",
        "causality": ("상관·회귀는 인과가 아닙니다. 동시대 월별 상관이며 "
                      "방향·매개·공통요인을 구분하지 못합니다."),
        "reason": None if ok else "어떤 자산도 베타를 내지 못했습니다",
    }


def portfolio_factor_exposure(weights: dict[str, float], betas: dict) -> dict:
    """포트폴리오 팩터 노출 `w'β` — ★쓸 수 있는 자산만으로 계산하고 그 사실을 적는다★

    베타를 못 낸 자산을 0 으로 채우면 노출이 실제보다 작게 보인다. 그래서 커버된
    비중(`coverage_pct`)을 함께 낸다 — 30% 만 덮은 노출은 다른 숫자다.
    """
    if not betas.get("available"):
        return {"available": False, "reason": betas.get("reason") or "베타가 없습니다"}

    total = sum(max(float(v), 0.0) for v in weights.values())
    if total <= 0:
        return {"available": False, "reason": "비중 합이 0 이하입니다"}

    out: dict[str, dict] = {}
    for factor in betas["factors"]:
        acc = 0.0
        covered = 0.0
        missing: list[str] = []
        for code, w in weights.items():
            wf = max(float(w), 0.0) / total
            row = (betas["assets"].get(str(code)) or {})
            fit = ((row.get("betas") or {}).get(factor) or {}) if row.get("available") else {}
            if fit.get("available") and fit.get("beta") is not None:
                acc += wf * float(fit["beta"])
                covered += wf
            elif wf > 0:
                missing.append(str(code))
        out[factor] = {
            "available": covered > 0,
            "exposure": round(acc, 4) if covered > 0 else None,
            "coverage_pct": round(covered * 100.0, 2),
            "missing": missing,
            "series": betas["proxies"].get(factor),
            "transform": (betas.get("transforms") or {}).get(factor),
            "reason": None if covered > 0 else "이 팩터의 베타를 가진 자산이 없습니다",
        }
    return {"available": True, "reason": None, "by_factor": out,
            "unresolved": betas.get("unresolved", {}),
            "sample": betas.get("sample"),
            "note": ("노출은 커버된 비중에 대한 가중합입니다 — 베타를 못 낸 자산을 "
                     "0 으로 채우지 않습니다(그러면 노출이 실제보다 작아 보입니다)"),
            "causality": betas.get("causality")}


def factor_concentration(exposure: dict) -> dict:
    """팩터 수준 집중도 — ★자산이 분산돼도 팩터가 하나면 분산이 아니다★"""
    if not exposure.get("available"):
        return {"available": False, "reason": exposure.get("reason")}
    vals = [abs(float(v["exposure"])) for v in exposure["by_factor"].values()
            if v.get("available") and v.get("exposure") is not None]
    if not vals:
        return {"available": False, "reason": "산출된 노출이 없습니다"}
    arr = np.asarray(vals, dtype=float)
    tot = float(arr.sum())
    if tot <= 0:
        return {"available": False, "reason": "노출 크기의 합이 0입니다"}
    p = arr / tot
    p = p[p > 1e-12]
    ent = float(-(p * np.log(p)).sum())
    return {
        "available": True, "reason": None,
        "n_factors": int(arr.size),
        "hhi": round(float((p ** 2).sum()), 4),
        # 팩터 수준 유효 베팅 개수 — 자산 ENB(Meucci)와 **다른 물건**이다.
        "effective_factors": round(float(np.exp(ent)), 4),
        "share": {f: round(float(abs(v["exposure"])) / tot, 4)
                  for f, v in exposure["by_factor"].items()
                  if v.get("available") and v.get("exposure") is not None},
        "note": ("이것은 **팩터** 수준 집중도입니다 — 자산 ENB(Σ 주성분)와 다른 "
                 "숫자이니 한 표에 섞지 마십시오"),
    }
