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

#: 대리계열 **표**의 판본. ★어휘를 새로 만들지 않는다★ —
#: `exposure_taxonomy.TAXONOMY_VERSION`/`TAXONOMY_AS_OF` 와 같은 모양이다.
PROXY_TABLE_VERSION = "2026.1"
#: 이 표가 마지막으로 바뀐 날. ★손으로 유지하되 근거를 적는다★ —
#: `git log -L` 로 잰 `FACTOR_PROXIES` 의 마지막 변경은 `b4b6042`(2026-08-23)다.
#: 후보 목록이나 우선순위를 바꾸면 **여기도 올린다**(테스트가 미래 날짜를 막는다).
PROXY_TABLE_AS_OF = "2026-08-23"


def proxy_table_block(as_of: str | None) -> dict:
    """이 표가 요청 시점에 유효했는가. ★미상이면 `None` 이지 `True` 가 아니다★

    ★`as_of_honored` 와 다른 질문이다★ 그 필드는 **계열**을 그 시점까지 잘랐는지를
    말한다. 자르는 것은 데이터이고, 어느 후보를 어떤 우선순위로 고르는가는 **표**다.
    표는 2026년의 판단이라 그전 시점에 소급하면 그때 없던 지식을 쓴 것이 된다 —
    수치를 바꾸지는 않지만, 응답이 그 사실을 말하지 않으면 그것이 침묵 폴백이다.
    """
    base = {"version": PROXY_TABLE_VERSION, "as_of": PROXY_TABLE_AS_OF}
    if not as_of:
        return {**base, "covers_as_of": None,
                "reason": ("요청에 as_of 가 없어 이 표가 그 시점에 유효했는지 "
                           "알 수 없습니다 — ★미상은 통과가 아닙니다★.")}
    if str(as_of) < PROXY_TABLE_AS_OF:
        return {**base, "covers_as_of": False,
                "reason": (f"대리계열 표는 {PROXY_TABLE_AS_OF} 판인데 요청 시점은 "
                           f"{as_of} 입니다 — 그때는 이 표가 없었으므로 후보와 "
                           "우선순위는 사후 지식입니다. 계열은 잘렸어도 **선택**은 "
                           "그렇지 않습니다.")}
    return {**base, "covers_as_of": True, "reason": None}


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

#: BH 의 FDR 수준. ★관례이지 측정치가 아니다★ — 바꾸면 판정이 바뀌므로 함께 싣는다.
BH_ALPHA = 0.05


def _bh_over_assets(assets: dict, *, alpha: float = BH_ALPHA) -> dict:
    """자산 × 팩터 전부를 **한 가족**으로 보고 BH 보정한다 (AJ3).

    ★가족은 자산 하나가 아니다★ — 자산 K개를 넣으면 검정이 K×F 개이고, 그중
    최대 t 를 골라 읽으면 선택편향이 K 배로 커진다. 그래서 `family_size` 는
    시도한 (자산, 팩터) 쌍의 수이지 `n_tested`(자산당 팩터 수)가 아니다.

    ★이 값은 `resolvable` 을 바꾸지 않는다★ — 그 판정은 단일검정 임계 2.0 그대로이고,
    이 블록은 그 옆에 붙는 관측이다.
    """
    from src.domain.multiplicity import FAMILY_DECLARED, bh_block

    t_by_name: dict[str, float | None] = {}
    for code, a in assets.items():
        if not a.get("available"):
            continue
        for factor, fit in (a.get("betas") or {}).items():
            t_by_name[f"{code}:{factor}"] = (fit.get("t_stat")
                                             if fit.get("available") else None)
    return bh_block(t_by_name, family_size=(len(t_by_name) or None),
                    family_source=FAMILY_DECLARED, alpha=alpha,
                    scope="자산 × 팩터")



def _macro_series_map() -> tuple[dict | None, str | None]:
    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        return RegimeAnalyzer().collector.collect_all(use_cache=True).series, None
    except Exception as e:  # noqa: BLE001
        logger.warning("매크로 수집 실패: %s", e)
        return None, f"매크로 계열을 수집하지 못했습니다 ({type(e).__name__})"


def truncate_series(series, as_of: str | None):
    """매크로 계열을 `as_of` 까지로 자른다. ★자를 수 없으면 원본을 그대로 돌려준다★

    계열 객체는 `timestamps`/`values` 를 갖는다(`_series_monthly_change` 와 같은
    가정). 그 모양이 아니면 **조용히 오늘 값을 쓰면서 과거를 주장하지 않도록**
    호출자가 `truncated` 로 판별할 수 있게 원본을 그대로 돌려준다.
    """
    if not as_of:
        return series, True
    ts = list(getattr(series, "timestamps", None) or [])
    vals = list(getattr(series, "values", None) or [])
    if not ts:
        # ★빈 계열은 자를 것이 없다★ 미래 관측이 없으므로 공허하게 지켜진 것이다.
        # (실측: 61계열 중 31개가 빈 계열이었고, 이것을 실패로 세면 실제로는
        #  전부 잘린 경우에도 "못 지켰다" 고 보고하게 된다.)
        return series, True
    if len(ts) != len(vals):
        return series, False
    keep = [i for i, t in enumerate(ts) if str(t)[:10] <= as_of]
    if len(keep) == len(ts):
        return series, True          # 이미 as_of 이전 — 자를 것이 없다
    try:
        import copy
        cut = copy.copy(series)
        cut.timestamps = [ts[i] for i in keep]
        cut.values = [vals[i] for i in keep]
        return cut, True
    except Exception:  # noqa: BLE001
        return series, False


def resolve_proxies(series_map: dict | None = None,
                    min_months: int = MIN_MONTHS,
                    as_of: str | None = None) -> dict:
    """팩터 → 실제로 쓸 대리계열. ★있는 것이 아니라 쓸 수 있는 것을 고른다★

    ★`as_of` 를 지키거나, 못 지켰다고 말한다★ 계열을 그 시점까지 자른다. 자를 수
    없는 계열이 있으면 `as_of_honored=False` 로 보고한다 — 조용히 오늘 값을 쓰면서
    과거 시점을 주장하는 것이 이 슬라이스가 고치는 결함이다.
    """
    if series_map is None:
        series_map, err = _macro_series_map()
        if series_map is None:
            return {"available": False, "reason": err, "resolved": {}, "unresolved": {},
                    "as_of": as_of, "as_of_honored": not as_of,
                    # ★모든 분기가 같은 키를 낸다★ 실패 응답에도 판본이 있어야
                    # 소비자가 `.get()` 으로 읽다가 `None` 을 "덮였다" 로 읽지 않는다.
                    "proxy_table": proxy_table_block(as_of)}

    # ★자른 결과와 성공 여부를 계열별로 들고 간다★ 최종 판정은 **실제로 쓰인**
    # 계열만 본다 — 쓰지도 않은 계열 때문에 "못 지켰다" 고 말하면 그것도 거짓이다.
    cut_ok: dict[str, bool] = {}
    if as_of:
        cut_map = {}
        for k, v in series_map.items():
            c, ok = truncate_series(v, as_of)
            cut_map[k], cut_ok[k] = c, ok
        series_map = cut_map

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
            # ★지켰는지를 사실로 싣는다★ 못 지켰으면 상류가 declared 에 넣지 않는다.
            "as_of": as_of,
            # 쓰인 계열이 **있고** 그것들이 전부 잘렸을 때만 지켰다고 말한다.
            # ★`all([])` 은 True 다★ resolved 가 비면 공허하게 "지켰다" 가 되는데,
            # 아무것도 쓰지 않고 절단을 주장하는 것이 이 슬라이스가 고치는 결함
            # 그 자체다. 비어 있음을 먼저 배제한다(변이 프로브가 잡았다).
            "as_of_honored": (bool(resolved) and all(
                cut_ok.get(d.get("series"), True) for d in resolved.values()))
            if as_of else True,
            # ★두 축을 가른다★ 위 `as_of_honored` 는 **계열 절단**만 말한다.
            # 표가 그 시점에 유효했는지는 다른 질문이고, 다른 필드가 답한다.
            "proxy_table": proxy_table_block(as_of),
            "reason": None if resolved else "어떤 팩터도 대리계열을 찾지 못했습니다"}


def asset_factor_betas(codes: list[str], *, series_map: dict | None = None,
                       min_months: int = MIN_MONTHS,
                       months: int = 60, as_of: str | None = None) -> dict:
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

    prox = resolve_proxies(series_map, min_months, as_of=as_of)
    if not prox["available"]:
        return {"available": False, "reason": prox["reason"],
                "unresolved": prox["unresolved"]}

    assets: dict[str, dict] = {}
    for code in codes:
        rets = _monthly_returns(str(code), months=months, as_of=as_of)
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
            # ★경고는 보정이 아니다★ (AJ3) — 위 문장은 이 자리가 처음부터 적고
            # 있었지만 보정은 하지 않았다. 가족은 **자산 × 팩터** 전부다:
            # `n_tested` 는 자산 하나가 본 팩터 수이고, 자산 K개를 넣으면 검정은
            # K×F 개다. 두 수를 같은 칸에 적지 않는다.
            "bh": _bh_over_assets(assets, alpha=BH_ALPHA),
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

    # ★부호를 잃지 않는다★ 예전에는 `max(w,0)/Σmax(w,0)` 이라 숏 다리가 통째로
    # 사라졌다. 숏의 팩터 노출은 **부호가 반대**이므로 그것은 값이 부정확한 것이
    # 아니라 결론이 뒤집히는 것이었다 — 시장중립 페어(A +100/B −100, 둘 다 β=1.0)가
    # 참값 0.0 대신 1.0 을, 그것도 `coverage_pct: 100` 과 함께 보고했다.
    # gross 로 나눈다(net 은 달러중립에서 0 이라 폭발한다). 롱온리는 값까지 동일.
    from src.engine.portfolio_weights import exposure_basis, signed_fractions
    fractions = signed_fractions(weights)
    if not fractions:
        return {"available": False, "reason": "비중이 없습니다 (gross = 0)"}

    out: dict[str, dict] = {}
    for factor in betas["factors"]:
        acc = 0.0
        covered = 0.0
        resolved_w = 0.0
        missing: list[str] = []
        for code, wf in fractions.items():
            row = (betas["assets"].get(str(code)) or {})
            fit = ((row.get("betas") or {}).get(factor) or {}) if row.get("available") else {}
            if fit.get("available") and fit.get("beta") is not None:
                acc += wf * float(fit["beta"])
                # ★커버리지는 gross 기준★ 부호대로 더하면 중립 북에서 상쇄돼
                # "아무것도 못 덮었다" 가 되고, 숏을 빼면 절반을 버리고도 100% 가 된다.
                covered += abs(wf)
                if fit.get("resolvable"):
                    resolved_w += abs(wf)
            else:
                missing.append(str(code))
        out[factor] = {
            "available": covered > 0,
            "exposure": round(acc, 4) if covered > 0 else None,
            "coverage_pct": round(covered * 100.0, 2),
            # ★|t| < 2 인 베타로 만든 노출은 잡음이다★ 그 비중을 함께 낸다.
            "resolvable_pct": round(resolved_w * 100.0, 2),
            "missing": missing,
            "series": betas["proxies"].get(factor),
            "transform": (betas.get("transforms") or {}).get(factor),
            "reason": None if covered > 0 else "이 팩터의 베타를 가진 자산이 없습니다",
        }
    return {"available": True, "reason": None, "by_factor": out,
            # ★이 숫자가 어느 기준인지 말한다★ 130/30 은 gross 기준 0.625 다.
            "basis": exposure_basis(weights),
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
