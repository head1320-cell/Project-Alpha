"""Attribution 엔진 — 사전(ex-ante) 기대 vs 사후(ex-post) 실측 (Full Expansion P5)
==============================================================================
지시서: "Explain 화면을 Attribution으로 재정의 — '왜 좋아 보이나'가 아니라 결정
시점의 사전 기대와 사후 실측을 비교한다." 저장된 ResearchRun(결정 시점의 가중치·
기대수익·기대리스크)을 결정일 이후 실제 가격 경로와 대조한다.

★정직 원칙(지시서 §8: 실데이터/시뮬/미연결을 절대 혼동하지 않는다)★
  · 사후(ex-post) 실측은 "결정일 이후 시장이 실제로 알 수 있었던" 가격에서만 나온다
    (look-ahead 없음). 경과 시간이 없거나 시세가 없으면 날조하지 않고 basis="unavailable".
  · 섹터/팩터/타이밍/헤지 Brinson 효과는 벤치마크 구성종목 가중·섹터수익 데이터가
    있어야 정확 — 미보유 시 basis="unavailable"(근사 날조 금지). 대신 실제로 근거가
    있는 것(총수익·초과수익·종목별 기여·비용·슬리피지·리스크 사전/사후)은 실측한다.
  · 체결 품질·슬리피지는 연결된 실행계획의 실제 체결(fills)이 있을 때만 실측.

순수 함수 — 가격 경로/체결은 주입 가능(테스트), 미주입 시 실로더(ohlcv_loader).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 벤치마크 프록시 (지수 미보유 시 대형주 폴백 — analyze 벤치마크 관례와 동일)
_BENCH_PROXY = "KOSPI"


def _to_frac(weights: dict[str, float]) -> dict[str, float]:
    """% 또는 소수 가중을 소수(sum≈1)로 정규화. 빈/0합이면 그대로."""
    tot = sum(v for v in weights.values() if isinstance(v, (int, float)) and v > 0)
    if tot <= 0:
        return {}
    return {k: max(float(v), 0.0) / tot for k, v in weights.items() if v and v > 0}


def _load_path(code: str, start_iso: str, end_iso: str) -> list[float] | None:
    """결정일~as-of 종가 경로. ohlcv_loader(DB→KIS→mock). 실패 시 None(정직 결측)."""
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
        df = load_ohlcv_unified(code, start_iso, end_iso)
        if df is not None and len(df) >= 2 and "close" in df.columns:
            return [float(x) for x in df["close"].tolist() if x and x > 0]
    except Exception:
        pass
    return None


def _path_source() -> str:
    """가격 경로 출처 라벨 — 운영은 실데이터, mock 모드는 'mock'(정직)."""
    try:
        from src.data.mock_gate import mock_allowed
        return "mock" if mock_allowed() else "db"
    except Exception:
        return "unknown"


def _series_return(path: list[float]) -> float:
    return path[-1] / path[0] - 1.0 if path and path[0] > 0 else 0.0


def _daily_returns(path: list[float]) -> list[float]:
    return [path[i] / path[i - 1] - 1.0 for i in range(1, len(path)) if path[i - 1] > 0]


def _annualized_vol(daily: list[float]) -> float | None:
    if len(daily) < 2:
        return None
    m = sum(daily) / len(daily)
    var = sum((x - m) ** 2 for x in daily) / (len(daily) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def _cov_beta(port_daily: list[float], bench_daily: list[float]) -> float | None:
    n = min(len(port_daily), len(bench_daily))
    if n < 3:
        return None
    p = port_daily[-n:]
    b = bench_daily[-n:]
    mb = sum(b) / n
    mp = sum(p) / n
    cov = sum((p[i] - mp) * (b[i] - mb) for i in range(n)) / (n - 1)
    varb = sum((b[i] - mb) ** 2 for i in range(n)) / (n - 1)
    return cov / varb if varb > 0 else None


def timing_effect(
    run: dict[str, Any],
    port_daily: list[float],
    start_dt: date,
    end_dt: date,
    simulate: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """타이밍 오버레이가 실현수익에 미친 효과 (Phase 10d).

    스펙 §9 의 6분해(allocation·timing·selection·factor·cost·residual) 중 **timing 만**
    새로 계산 가능해졌다 — Phase 9 의 `/timing/simulate` 가 시점별 노출 경로를 주기 때문이다.
    나머지 셋(allocation·selection·factor)은 벤치마크 **구성종목 가중과 섹터수익**이 있어야
    하고 이 저장소에는 그 데이터가 없다. 없는 것을 프록시로 채우지 않는다.

    효과 = (노출 경로를 적용한 실현수익) − (전액 투자 실현수익).
    타이밍이 하락 구간에서 위험-오프였다면 **양수**(손실을 피했다), 상승 구간에서
    위험-오프였다면 **음수**(수익을 놓쳤다)다.

    ★두 가지 근사를 숨기지 않는다★
      1. `simulate_rule_set` 의 표본 간격이 **월**이다(as_of 절단이 월 단위). 일간 보유
         구간에 월 표본 노출을 입히므로 크기는 근사이고 방향이 주된 정보다.
      2. 일별 수익 인덱스 → 날짜 매핑은 구간을 **선형 분할**한 것이다(가격 경로에 날짜가
         함께 저장되지 않는다). 거래일 분포가 고르지 않으면 경계가 하루 이틀 어긋난다.

    런에 룰셋이 기록돼 있지 않으면 `0.0` 이 아니라 **unavailable** 이다 — 타이밍을 하지
    않은 것과 타이밍 기록이 없는 것은 다른 사실이고, 0 은 전자를 뜻한다.
    """
    snap = run.get("snapshot") or {}
    inputs = run.get("inputs") or {}
    set_id = inputs.get("timing_rule_set_id") or snap.get("timing_rule_set_id")
    version = inputs.get("timing_rule_set_version") or snap.get("timing_rule_set_version")
    if not set_id:
        return {"value": None, "basis": "unavailable",
                "reason": "이 런에는 타이밍 룰셋이 기록되지 않았습니다 — 타이밍을 적용하지 "
                          "않은 것과 기록이 없는 것은 다른 사실이라 0 으로 적지 않습니다."}
    if not port_daily:
        return {"value": None, "basis": "unavailable",
                "reason": "결정일 이후 일별 수익이 없어 타이밍 효과를 잴 수 없습니다."}

    try:
        from src.data.timing_rules import get_rule_set, get_rule_set_version
        stored = (get_rule_set_version(set_id, int(version)) if version is not None
                  else get_rule_set(set_id))
        if stored is None:
            return {"value": None, "basis": "unavailable",
                    "reason": f"룰셋 {set_id}"
                              + (f" v{version}" if version is not None else "")
                              + " 을 복원할 수 없습니다 — 삭제되었을 수 있습니다. 현재 "
                                "버전으로 대신 계산하지 않습니다."}
        specs = list(stored.get("rules") or [])
        if not specs:
            return {"value": None, "basis": "unavailable",
                    "reason": f"룰셋 {set_id} 에 규칙이 없습니다."}

        from src.engine.timing_rules_v2 import rule_set_from_specs
        gate = stored.get("gate") or {}
        rule_set = rule_set_from_specs(
            specs, market=str(stored.get("market") or "kr"),
            combination=str(gate.get("combination") or "all"), set_id=set_id)

        sim = simulate
        if sim is None:
            from src.engine.timing_simulation import simulate_rule_set as sim
        days = max((end_dt - start_dt).days, 1)
        months = max(1, min(240, (days // 30) + 1))
        walk = sim(rule_set, months=months, mode="forward",
                   anchor=end_dt.isoformat())
        points = sorted(
            ((p.as_of, float(p.exposure)) for p in walk.points), key=lambda x: x[0])
        if not points:
            return {"value": None, "basis": "unavailable",
                    "reason": "노출 경로를 만들지 못했습니다."}
    except Exception as e:                      # noqa: BLE001 — 귀인 전체를 깨지 않는다
        logger.warning(f"timing effect 계산 실패: {e}")
        return {"value": None, "basis": "unavailable",
                "reason": f"타이밍 효과 계산에 실패했습니다: {e}"}

    # 일별 인덱스 → 날짜(선형) → 그 시점에 유효한 노출
    T = len(port_daily)
    timed = 1.0
    plain = 1.0
    exposures: list[float] = []
    for t, r in enumerate(port_daily):
        frac = (t + 1) / T
        d = (start_dt + timedelta(days=int(round(days * frac)))).isoformat()
        e = points[0][1]
        for as_of, ex in points:
            if as_of <= d:
                e = ex
            else:
                break
        e = max(0.0, min(1.0, e))       # 오버레이는 노출을 키우지 않는다(일방향)
        exposures.append(e)
        timed *= 1 + e * r
        plain *= 1 + r

    effect = timed - plain
    avg_e = sum(exposures) / len(exposures) if exposures else None
    return {
        "value": round(effect * 100, 3),
        "basis": "real",
        "timed_return_pct": round((timed - 1) * 100, 2),
        "full_invested_return_pct": round((plain - 1) * 100, 2),
        "avg_exposure_pct": round(avg_e * 100, 1) if avg_e is not None else None,
        "rule_set_id": set_id, "rule_set_version": version,
        "note": "타이밍 노출 경로를 적용한 실현수익 − 전액 투자 실현수익. "
                "★노출 표본은 **월** 간격이고(as_of 절단 단위), 일별 인덱스→날짜 매핑은 "
                "구간 선형 분할입니다 — 방향은 신뢰할 수 있고 크기는 근사입니다.★",
    }


def compute_attribution(
    run: dict[str, Any],
    as_of: str | None = None,
    path_of: Callable[[str, str, str], list[float] | None] | None = None,
    benchmark_path: list[float] | None = None,
    fills: list[dict] | None = None,
    expected_cost_bp: float | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """저장된 analyze run + 결정일 이후 실제 가격 → Attribution 리포트.

    path_of(code, start_iso, end_iso) -> 종가 리스트 | None (테스트 주입, 미주입 시 실로더).
    """
    path_of = path_of or _load_path
    outputs = run.get("outputs") or {}
    inputs = run.get("inputs") or {}
    weights_pct = (outputs.get("weights") or {}).get("optimized") or inputs.get("weights") or {}
    w = _to_frac(weights_pct)
    tickers = list(w.keys())

    # ── 결정 시점 ~ as-of 구간 ──
    created = run.get("created_at")
    start_dt = datetime.fromtimestamp(created).date() if created else (date.today() - timedelta(days=90))
    end_dt = date.fromisoformat(as_of) if as_of else date.today()
    start_iso, end_iso = start_dt.isoformat(), end_dt.isoformat()
    elapsed_days = (end_dt - start_dt).days
    period_years = max(elapsed_days, 0) / 365.0
    src = source or _path_source()

    # ── 사후 실측: 종목별 가격 경로 ──
    paths: dict[str, list[float]] = {}
    missing: list[str] = []
    for c in tickers:
        p = path_of(c, start_iso, end_iso)
        if p and len(p) >= 2:
            paths[c] = p
        else:
            missing.append(c)

    have_expost = bool(paths) and elapsed_days >= 1
    # 커버된 종목만으로 가중 재정규화
    cov_w = {c: w[c] for c in paths}
    covw_tot = sum(cov_w.values())
    cov_w = {c: v / covw_tot for c, v in cov_w.items()} if covw_tot > 0 else {}

    # 종목별 실현수익 + 기여
    per_asset = []
    contrib_map: dict[str, float] = {}
    if have_expost:
        for c, p in paths.items():
            r = _series_return(p)
            contrib = cov_w.get(c, 0.0) * r
            contrib_map[c] = contrib
            per_asset.append({
                "code": c, "weight_pct": round(cov_w.get(c, 0.0) * 100, 2),
                "return_pct": round(r * 100, 2), "contribution_pct": round(contrib * 100, 2),
            })
        per_asset.sort(key=lambda x: x["contribution_pct"], reverse=True)

    # 포트폴리오 일별수익 (정렬 최소길이)
    port_daily: list[float] = []
    realized_return = None
    realized_vol = None
    if have_expost:
        min_len = min(len(p) for p in paths.values())
        if min_len >= 2:
            dailies = {c: _daily_returns(p[-min_len:]) for c, p in paths.items()}
            T = min(len(d) for d in dailies.values())
            for t in range(T):
                port_daily.append(sum(cov_w.get(c, 0.0) * dailies[c][t] for c in paths))
            realized_return = (math.prod(1 + x for x in port_daily) - 1.0) if port_daily else \
                sum(cov_w.get(c, 0.0) * _series_return(p) for c, p in paths.items())
            realized_vol = _annualized_vol(port_daily)

    # ── 벤치마크 ──
    bpath = benchmark_path if benchmark_path is not None else path_of(_BENCH_PROXY, start_iso, end_iso)
    bench_return = _series_return(bpath) if bpath and len(bpath) >= 2 else None
    bench_daily = _daily_returns(bpath) if bpath and len(bpath) >= 2 else []
    realized_beta = _cov_beta(port_daily, bench_daily) if port_daily and bench_daily else None

    excess = (realized_return - bench_return) if (realized_return is not None and bench_return is not None) else None

    # ── 사전(ex-ante) — 저장된 run 요약 ──
    summary = (outputs.get("summary") or {})
    pf = summary.get("portfolio") or {}
    extra = summary.get("extra") or {}
    exp_ret_annual = pf.get("expected_return_pct")
    exp_vol_annual = pf.get("volatility_pct")
    exp_ret_period = (exp_ret_annual / 100.0 * period_years) if isinstance(exp_ret_annual, (int, float)) else None

    # ── 비용/슬리피지 (연결된 실행계획 실체결이 있을 때만) ──
    cost_drag = None
    slippage = None
    fill_quality = None
    if fills:
        fq_rows = []
        tot_slip_notional = 0.0
        tot_notional = 0.0
        for f in fills:
            code = f.get("stock_code")
            filled = float(f.get("filled_qty", 0) or 0)
            avg = float(f.get("avg_price", 0) or 0)
            tgt = float(f.get("target_price", avg) or avg)
            notional = filled * avg
            slip = (avg - tgt) * filled           # 체결가-목표가 (매수 기준 +면 불리)
            tot_slip_notional += slip
            tot_notional += notional
            fq_rows.append({
                "stock_code": code, "filled_qty": filled,
                "avg_price": round(avg, 2), "target_price": round(tgt, 2),
                "slippage_bp": round((avg / tgt - 1) * 1e4, 1) if tgt > 0 else None,
            })
        slippage = -(tot_slip_notional / tot_notional) if tot_notional > 0 else None  # 수익 관점 부호
        fill_quality = {"rows": fq_rows, "avg_slippage_bp":
                        round(tot_slip_notional / tot_notional * 1e4, 1) if tot_notional > 0 else None,
                        "basis": "real"}
    if expected_cost_bp is not None:
        cost_drag = -expected_cost_bp / 1e4

    # 잔차 = 실현 - 기대 - 비용 - 슬리피지 (있는 항만)
    residual = None
    if realized_return is not None and exp_ret_period is not None:
        residual = realized_return - exp_ret_period - (cost_drag or 0.0) - (slippage or 0.0)

    # ── 의존도 분석 (특정 종목/팩터 과의존) ──
    dependency = None
    if contrib_map:
        pos = {k: abs(v) for k, v in contrib_map.items()}
        tot = sum(pos.values()) or 1.0
        shares = sorted((v / tot for v in pos.values()), reverse=True)
        hhi = sum(s * s for s in shares)
        top = per_asset[0] if per_asset else None
        dependency = {
            "hhi": round(hhi, 3),
            "effective_n": round(1.0 / hhi, 1) if hhi > 0 else None,
            "top_name_share_pct": round(shares[0] * 100, 1) if shares else None,
            "top_name": (top["code"] if top else None),
            "concentrated": hhi > 0.4,
            "note": "기여도 허핀달 지수(HHI) — 0.4 초과면 소수 종목 과의존(정직 경고).",
            "basis": "real",
        }

    def _basis(v):
        return "real" if v is not None else ("mock" if src == "mock" and have_expost else "unavailable")

    tim = timing_effect(run, port_daily, start_dt, end_dt)

    return {
        "run_id": run.get("run_id"),
        "kind": run.get("kind"),
        "name": run.get("name"),
        "decision_date": start_iso,
        "as_of": end_iso,
        "elapsed_days": elapsed_days,
        "period_years": round(period_years, 3),
        "coverage": {"tickers": len(tickers), "covered": len(paths), "missing": missing,
                     "source": src, "has_expost": have_expost},
        "returns": {
            "portfolio_pct": round(realized_return * 100, 2) if realized_return is not None else None,
            "benchmark_pct": round(bench_return * 100, 2) if bench_return is not None else None,
            "excess_pct": round(excess * 100, 2) if excess is not None else None,
            "benchmark_label": _BENCH_PROXY,
            "basis": _basis(realized_return),
        },
        "expected_vs_actual": {
            "expected_return_pct": round(exp_ret_period * 100, 2) if exp_ret_period is not None else None,
            "expected_return_annual_pct": exp_ret_annual,
            "actual_return_pct": round(realized_return * 100, 2) if realized_return is not None else None,
            "gap_pct": round((realized_return - exp_ret_period) * 100, 2)
                       if (realized_return is not None and exp_ret_period is not None) else None,
            "basis": _basis(exp_ret_period if exp_ret_period is not None else None),
        },
        "decomposition": {
            "model_alpha_pct": round(exp_ret_period * 100, 2) if exp_ret_period is not None else None,
            "execution_slippage_pct": round(slippage * 100, 3) if slippage is not None else None,
            "cost_pct": round(cost_drag * 100, 3) if cost_drag is not None else None,
            "residual_pct": round(residual * 100, 2) if residual is not None else None,
            "basis": {
                "model_alpha": _basis(exp_ret_period),
                "slippage": "real" if slippage is not None else "unavailable",
                "cost": "real" if cost_drag is not None else "unavailable",
                "residual": _basis(residual),
            },
            "note": "실현수익 = 모델 알파(사전 기대) + 슬리피지 + 비용 + 잔차. 슬리피지·비용은 "
                    "연결된 실행계획 실체결이 있을 때만 실측(없으면 미측정).",
        },
        "risk_compare": {
            "ex_ante": {"vol_pct": exp_vol_annual, "var_pct": extra.get("var_pct"),
                        "cvar_pct": extra.get("cvar_pct")},
            "ex_post": {"vol_pct": round(realized_vol, 2) if realized_vol is not None else None,
                        "beta": round(realized_beta, 2) if realized_beta is not None else None},
            "vol_gap_pct": round(realized_vol - exp_vol_annual, 2)
                           if (realized_vol is not None and isinstance(exp_vol_annual, (int, float))) else None,
            "basis": _basis(realized_vol),
        },
        "contribution": {"assets": per_asset, "basis": _basis(realized_return if per_asset else None)},
        "fill_quality": fill_quality or {"basis": "unavailable",
                                         "note": "연결된 실행계획의 실체결(fills) 없음 — 체결 품질 미측정."},
        "dependency": dependency or {"basis": "unavailable"},
        # 정직: 벤치마크 구성종목·섹터수익 미보유 → selection/allocation/factor 는 여전히 불가.
        # ★timing 만 계산 가능해졌다★ (Phase 10d) — 룰셋이 기록된 런이면 시점별 노출 경로를
        # 재현할 수 있기 때문이고, 나머지 셋과 달리 벤치마크 구성종목이 필요 없다.
        "brinson_effects": {
            "selection": None, "allocation": None, "factor": None, "hedge": None,
            "timing": tim.get("value"),
            "timing_detail": tim,
            "basis": tim.get("basis", "unavailable"),
            "note": "selection·allocation·factor·hedge 분해는 **벤치마크 구성종목 가중과 "
                    "섹터수익**이 있어야 하고 이 저장소에는 없습니다 — 프록시로 채우지 않습니다. "
                    "timing 은 기록된 룰셋의 노출 경로로 실측합니다(룰셋이 없으면 0 이 아니라 "
                    "unavailable).",
        },
        "note": "사후 실측은 결정일 이후 '시장이 실제로 알 수 있었던' 가격에서만 산출(look-ahead 없음). "
                + ("합성(mock) 가격 기준 — 참고용." if src == "mock" else "실 가격 기준."),
    }
