"""공용 퀀트 성과지표 (QuantStats / empyrical 표준 부분집합).

period-agnostic 순수함수 — daily(252)·monthly(12) 양 경로 공용.

- returns:          기간 수익률 시퀀스 (0.01 = +1%)
- equity:           자본곡선 (낙폭·회복·Ulcer 계산용)
- periods_per_year: 연율화 계수 (일봉 252, 월간 12)
- trades_pnl:       라운드트립 손익/수익률 시퀀스 (있으면 거래 통계)
- benchmark_returns:벤치마크 기간 수익률 (있으면 정보비율)

빈 입력·0분모를 전부 방어한다(None/0). 모든 키를 항상 반환하므로
프론트는 옵셔널 렌더(없으면 "—")만 하면 된다.

출처: ranaroussi/quantstats, quantopian/empyrical.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# ── ★관례는 선언되고, 산출과 함께 다닌다★ (P1) ────────────────────────────
#: 저장소 지배 관례. `regime_analyzer`·`cash_management.DEFAULT_RF_ANNUAL`·
#: `realism_engine.default_rf_annual`·`company_analytics`·`allocation_backtest._RF`
#: 가 전부 이 값을 쓴다. (`multi_strategy_backtest` 만 0.025 로 갈라져 있는데,
#: 그것은 레거시 경로라 이번 범위 밖이고 테스트가 그 사실을 못 박는다.)
DEFAULT_RISK_FREE = 0.035
#: 표본 표준편차. 추정량이므로 자유도를 보정한다.
DEFAULT_DDOF = 1
DEFAULT_PERIODS_PER_YEAR = 252
#: 연율화 관례. ★산술이 기본★ — 기존 호출부가 한 자도 바뀌지 않는다.
DEFAULT_ANNUALIZATION = "arithmetic"
ANNUALIZATIONS = ("arithmetic", "geometric")


def _arr(xs) -> np.ndarray:
    """리스트/pd.Series/None → 유한값만 남긴 1차원 float 배열."""
    if xs is None:
        return np.array([], dtype=float)
    if hasattr(xs, "values"):  # pd.Series / DataFrame 컬럼
        xs = xs.values
    try:
        a = np.asarray(list(xs), dtype=float).ravel()
    except (TypeError, ValueError):
        return np.array([], dtype=float)
    return a[np.isfinite(a)]


def _max_underwater(dd: np.ndarray) -> int:
    """최장 연속 수중(낙폭<0) 구간의 길이(기간 수)."""
    longest = cur = 0
    for x in dd:
        if x < 0:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return int(longest)


def risk_adjusted_ratios(
    returns,
    equity,
    *,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
    risk_free: float = DEFAULT_RISK_FREE,
    ddof: int = DEFAULT_DDOF,
    annualization: str = DEFAULT_ANNUALIZATION,
    starting_equity: float | None = None,
) -> dict[str, Any]:
    """Sharpe·Sortino·Calmar·연율수익·연율변동성 — ★단일 출처★ (P1).

    ★공식이 아니라 관례가 갈라져 있었다★ `allocation_backtest` 와
    `multi_strategy_backtest` 의 Sharpe 는 대수적으로 **동일**하다(rf·ddof 를
    맞추면 차이 1.4e-16). 그런데 실제 값은 66% 어긋나고 부호까지 뒤집혔다 —
    무위험이 0.035 / 0.025 / **없음** 으로, `ddof` 가 1 / 0 으로 갈렸기 때문이다.

    그래서 이 함수의 계약은 "정의 하나" 가 아니라 ★**관례를 인자로 받고 그 관례를
    산출에 함께 싣는다**★ 다(`convention` 블록). 어떤 리포트든 그 수를 만든 관례를
    달고 다녀야 한다.

    ★전정밀도를 낸다 — 반올림은 표시 계층에서만★ A3 에서 `round(_, 2)` 된
    Sharpe 가 비용 5→100bps 전 구간에서 0.42 로 고정이라 사전등록의 "비용 3수준
    전부" 절이 아무것도 요구하지 않게 됐다.

    ★미상은 0 이 아니다★ 표본이 모자라거나 분모가 0 이면 `None` + 사유다.
    `0.0` 을 내면 "위험조정 수익이 없다" 는 **하지 않은 진술**이 된다.

    ★연율화도 인자다 (P1 확장)★ 기본은 **산술**(`mean × ppy`)이고 그 사실을
    신고한다. `annualization="geometric"` 이면 자본곡선의 CAGR
    (`(eq[-1]/starting_equity)^(ppy/n) − 1`)을 쓴다 — `multi_strategy_backtest`
    가 쓰던 관례다. 그 선택지가 없어서 그 모듈의 calmar 는 단일 출처로 옮길 수
    없었고(옮기면 값이 바뀐다) 그것이 divergence 가 P1 이후에도 살아남은 이유다.

    ★기하인데 시작자본을 모르면 CAGR 을 지어내지 않는다★ — `None` + 사유.
    """
    r = _arr(returns)
    eq = _arr(equity)
    ppy = max(int(periods_per_year), 1)
    if annualization not in ANNUALIZATIONS:
        # ★조용히 산술로 떨어지지 않는다★ 그러면 리포트가 하지 않은 관례를
        # 신고하게 된다 — 관례를 싣는 목적 자체가 무너진다.
        raise ValueError(
            f"annualization 은 {ANNUALIZATIONS} 중 하나여야 합니다 — 받은 값 "
            f"{annualization!r}")
    rf_per = float(risk_free) / ppy
    root = math.sqrt(ppy)

    out: dict[str, Any] = {
        "sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None,
        "annualized_return": None, "annualized_volatility": None,
        "max_drawdown": None,
        "convention": {"risk_free": float(risk_free), "ddof": int(ddof),
                       "periods_per_year": ppy, "annualization": annualization,
                       "starting_equity": (None if starting_equity is None
                                           else float(starting_equity)),
                       "declared": True},
        "reasons": {},
    }
    why = out["reasons"]

    if r.size < 2:
        for k in ("sharpe_ratio", "sortino_ratio", "calmar_ratio",
                  "annualized_return", "annualized_volatility", "max_drawdown"):
            why[k] = f"관측이 {r.size}개뿐입니다 — 2개 미만이면 산출되지 않습니다"
        return out

    mean = float(r.mean())
    if annualization == "geometric":
        # ★규모를 모르면 CAGR 이 정의되지 않는다★ 자본곡선의 첫 값은 이미 첫
        # 기간 수익이 반영된 뒤라 시작자본의 대용이 될 수 없다.
        if starting_equity is None or float(starting_equity) <= 0 or not eq.size:
            why["annualized_return"] = (
                "기하 연율화에는 양수 `starting_equity` 가 필요합니다 — "
                "시작자본을 모르면 CAGR 을 지어내지 않습니다")
        else:
            out["annualized_return"] = (
                float(eq[-1]) / float(starting_equity)) ** (ppy / r.size) - 1.0
    else:
        out["annualized_return"] = mean * ppy
    sd = float(r.std(ddof=int(ddof)))
    excess = mean - rf_per

    # ★상수 계열의 표준편차는 정확히 0 이 아니다★ `np.full(100, 0.001).std()` 는
    # 부동소수 잔차로 ~1.6e-19 이고, 그대로 나누면 Sharpe 가 **6.3e16** 이 된다.
    # 유한한 수라 `isfinite` 검사도 통과한다 — 그래서 데이터 규모에 상대적인
    # 하한이 필요하다. 변동이 수준 대비 무시할 만하면 그 표본은 상수다.
    floor = max(1e-14, abs(mean) * 1e-9)

    if np.isfinite(sd) and sd > floor:
        out["annualized_volatility"] = sd * root
        out["sharpe_ratio"] = excess / sd * root
    else:
        why["sharpe_ratio"] = "표준편차가 0 입니다 — 비율이 정의되지 않습니다"
        why["annualized_volatility"] = "표준편차가 0 입니다"

    down = r[r < 0]
    dsd = float(down.std(ddof=int(ddof))) if down.size > int(ddof) else 0.0
    if np.isfinite(dsd) and dsd > floor:
        out["sortino_ratio"] = excess / dsd * root
    else:
        why["sortino_ratio"] = ("하방 관측이 없거나 하방편차가 0 입니다 — "
                                "분모가 없어 산출되지 않습니다")

    if eq.size:
        mdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
        out["max_drawdown"] = mdd
        if mdd < 0 and out["annualized_return"] is not None:
            out["calmar_ratio"] = out["annualized_return"] / abs(mdd)
        elif mdd < 0:
            why["calmar_ratio"] = "연율수익이 미상이라 산출되지 않습니다"
        else:
            why["calmar_ratio"] = "낙폭이 없습니다 — 분모가 0 이라 산출되지 않습니다"
    else:
        why["max_drawdown"] = "자본곡선이 비어 있습니다"
        why["calmar_ratio"] = "자본곡선이 없어 낙폭을 알 수 없습니다"

    return out


def compute_metrics(
    returns,
    equity,
    periods_per_year: int = 252,
    trades_pnl=None,
    benchmark_returns=None,
    risk_free: float = 0.035,
) -> dict:
    """QuantStats 표준 지표 묶음을 반환(기존 stats와 병합해 쓰는 보강 지표).

    ★`risk_free` 는 죽은 인자였다 (P1)★ 선언만 되고 한 번도 쓰이지 않았는데
    `allocation_backtest:495` 가 `_RF` 를 넘기며 뭔가 한다고 믿고 있었다. 이제
    `risk_adjusted_ratios` 로 흘러 **실제로 답을 바꾼다**.
    """
    r = _arr(returns)
    eq = _arr(equity)
    ppy = max(int(periods_per_year), 1)
    n = r.size

    out: dict = {
        # ── 위험 ──
        "volatility_pct": 0.0,
        "downside_deviation_pct": None,
        "var_pct": None,
        "cvar_pct": None,
        "ulcer_index": None,
        "max_drawdown_days": 0,
        "avg_drawdown_pct": None,
        # ── 위험조정 ──
        "omega": None,
        "recovery_factor": None,
        "gain_to_pain": None,
        "tail_ratio": None,
        # ── 분포 ──
        "skew": None,
        "kurtosis": None,
        "best_period_pct": None,
        "worst_period_pct": None,
        # ── 거래 ──
        "payoff_ratio": None,
        "avg_win": None,
        "avg_loss": None,
        "expectancy": None,
        "kelly_pct": None,
        # ── 벤치마크 ──
        "information_ratio": None,
    }

    if n == 0:
        return out

    # ── 변동성 / 분포 ──
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    out["volatility_pct"] = round(sd * math.sqrt(ppy) * 100, 2)

    downside = r[r < 0]
    if downside.size > 1:
        out["downside_deviation_pct"] = round(float(downside.std(ddof=1)) * math.sqrt(ppy) * 100, 2)
    else:
        out["downside_deviation_pct"] = 0.0

    out["best_period_pct"] = round(float(r.max()) * 100, 2)
    out["worst_period_pct"] = round(float(r.min()) * 100, 2)

    mean_r = float(r.mean())
    pop_sd = float(r.std(ddof=0))
    if pop_sd > 0:
        z = (r - mean_r) / pop_sd
        out["skew"] = round(float(np.mean(z ** 3)), 4)
        out["kurtosis"] = round(float(np.mean(z ** 4) - 3.0), 4)  # 초과첨도(정규=0)
    else:
        out["skew"] = 0.0
        out["kurtosis"] = 0.0

    # ── VaR / CVaR (95% 신뢰) ──
    var = float(np.quantile(r, 0.05))
    out["var_pct"] = round(var * 100, 2)
    tail = r[r <= var]
    cvar = float(tail.mean()) if tail.size > 0 else var
    out["cvar_pct"] = round(cvar * 100, 2)

    # ── Tail ratio = |q95 / q05| ──
    q95 = float(np.quantile(r, 0.95))
    q05 = float(np.quantile(r, 0.05))
    out["tail_ratio"] = round(abs(q95 / q05), 3) if q05 != 0 else None

    # ── Omega / Gain-to-Pain ──
    gains = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())  # 양수로
    out["omega"] = round(gains / losses, 3) if losses > 0 else None
    out["gain_to_pain"] = round(float(r.sum()) / losses, 3) if losses > 0 else None

    # ── 낙폭 계열 (equity 기반) ──
    if eq.size > 0:
        run_max = np.maximum.accumulate(eq)
        run_max[run_max == 0] = np.nan  # 0 분모 방어
        dd = (eq - run_max) / run_max
        dd = np.nan_to_num(dd, nan=0.0)
        dd_pct = dd * 100
        out["ulcer_index"] = round(math.sqrt(float(np.mean(dd_pct ** 2))), 3)
        neg = dd_pct[dd_pct < 0]
        out["avg_drawdown_pct"] = round(float(neg.mean()), 2) if neg.size > 0 else 0.0
        out["max_drawdown_days"] = _max_underwater(dd)
        max_dd = float(dd.min())  # 음수
        total_ret = float(eq[-1] / eq[0] - 1) if eq[0] != 0 else 0.0
        out["recovery_factor"] = round(total_ret / abs(max_dd), 3) if max_dd < 0 else None

    # ── 거래 통계 (trades_pnl 있을 때) ──
    t = _arr(trades_pnl)
    if t.size > 0:
        wins = t[t > 0]
        loss = t[t < 0]
        aw = float(wins.mean()) if wins.size > 0 else 0.0
        al = float(-loss.mean()) if loss.size > 0 else 0.0  # 양수
        out["avg_win"] = round(aw, 2)
        out["avg_loss"] = round(al, 2)
        payoff = aw / al if al > 0 else None
        out["payoff_ratio"] = round(payoff, 4) if payoff is not None else None
        wr = wins.size / t.size
        out["expectancy"] = round(wr * aw - (1 - wr) * al, 2)
        # 켈리는 손익비(payoff>0)가 정의될 때만. 승리 거래 0이면(payoff=0) 정의 불가.
        out["kelly_pct"] = round((wr - (1 - wr) / payoff) * 100, 2) if payoff else None

    # ── 벤치마크 정보비율 ──
    b = _arr(benchmark_returns)
    if b.size > 0:
        m = min(b.size, n)
        if m > 1:
            active = r[:m] - b[:m]
            te = float(active.std(ddof=1)) * math.sqrt(ppy)
            ann_active = float(active.mean()) * ppy
            out["information_ratio"] = round(ann_active / te, 3) if te > 0 else None

    # ★위험조정 지표를 여기서 합류시킨다 (P1)★ 예전에는 이 함수가 sharpe·
    # sortino·calmar 를 내지 않아서 호출부가 **바로 다음 줄에서 인라인으로 다시
    # 계산**했다 — 같은 함수 안에 지표가 두 벌이었고, 관례가 갈라진 지점이다.
    out.update(risk_adjusted_ratios(returns, equity,
                                    periods_per_year=periods_per_year,
                                    risk_free=risk_free))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 기간별 수익 · 큰 낙폭 사건 — 자본곡선에서 ★옮기기만★ 한다 (2026-11-09 · 캔버스 성과 그림 문법)
# ─────────────────────────────────────────────────────────────────────────────
# 설계: `docs/superpowers/specs/2026-11-09-canvas-performance-viz-design.md` §4.5. 화면은 새 수를 만들지 않으므로(BJ 원칙)
# 해마다·달마다 수익과 낙폭 사건은 서버가 낸다. 둘 다 같은 자본곡선의 두 수준을 나눈 것이라 ★연환산하지 않는다★ — 3개월짜리
# 해를 "연 수익" 처럼 보이면 거짓이다. 부분 기간은 `partial` 로 표시만 한다. 값을 모르는 날(None/NaN)은 건너뛴다 — 0 으로 두면
# −100% 낙폭을 지어낸다. 회복 못 한 낙폭의 회복일은 `None` 이다(오늘도 0 도 아니다). 시험: `tests/test_quant_periods.py`.
# ═══════════════════════════════════════════════════════════════════════════════
import datetime as _dt


def _as_date(d: Any) -> _dt.date | None:
    """날짜 문자열("YYYY-MM-DD…")·date·datetime·pandas Timestamp → date. 못 읽으면 None(그 점은 건너뛴다)."""
    if d is None:
        return None
    if isinstance(d, _dt.datetime):
        return d.date()
    if isinstance(d, _dt.date):
        return d
    if hasattr(d, "to_pydatetime"):
        return d.to_pydatetime().date()
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def _curve_points(dates: Any, equity: Any) -> list[tuple[_dt.date, float]]:
    """(날짜, 값) 중 날짜를 읽을 수 있고 값이 유한한 점만, 날짜순으로."""
    pts: list[tuple[_dt.date, float]] = []
    # numpy 배열은 `or` 에 넣으면 참·거짓이 모호하다 — None 만 빈 것으로 본다.
    for d, v in zip(list(dates) if dates is not None else [], list(equity) if equity is not None else []):
        day = _as_date(d)
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if day is None or not math.isfinite(x):
            continue
        pts.append((day, x))
    pts.sort(key=lambda p: p[0])
    return pts


def _period_rows(pts: list[tuple[_dt.date, float]], key) -> list[tuple[Any, float | None, list[tuple[_dt.date, float]]]]:
    """곡선을 `key(날짜)` 가 같은 구간으로 자른다 → (키, 직전 구간의 마지막 값, 그 구간의 점들)."""
    rows: list[tuple[Any, float | None, list[tuple[_dt.date, float]]]] = []
    prev_last: float | None = None
    cur_key: Any = None
    cur: list[tuple[_dt.date, float]] = []
    for d, v in pts:
        k = key(d)
        if k != cur_key and cur:
            rows.append((cur_key, prev_last, cur))
            prev_last = cur[-1][1]
            cur = []
        cur_key = k
        cur.append((d, v))
    if cur:
        rows.append((cur_key, prev_last, cur))
    return rows


def _period_return_pct(prev_last: float | None, group: list[tuple[_dt.date, float]]) -> float:
    """구간 수익 = 구간 마지막 값 ÷ (직전 구간의 마지막 값, 없으면 이 구간의 첫 값) − 1. 연환산 없음."""
    base = prev_last if prev_last is not None else group[0][1]
    return (group[-1][1] / base - 1.0) * 100.0 if base > 0 else 0.0


def _within_max_drawdown_pct(group: list[tuple[_dt.date, float]]) -> float:
    """그 구간 안의 최고점 대비 MDD(최대낙폭) — 다른 구간의 고점을 끌어오지 않는다."""
    peak = -math.inf
    worst = 0.0
    for _, v in group:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst * 100.0


def period_returns(dates: Any, equity: Any) -> dict[str, list[dict[str, Any]]]:
    """해마다·월별 수익률(%) — ★연환산하지 않는다★.

    yearly: `{year, return_pct, max_drawdown_pct, n_days, partial}` — `partial` 은 그 해에 1월과 12월 점이 모두 있지 않을 때.
    monthly: `{year, month, return_pct, n_days, partial}` — `partial` 은 곡선의 첫 달·마지막 달(가운데서 시작·끝났을 수 있는데
    거래 달력이 없어 더 정확히는 모른다). 점이 둘 미만이면 둘 다 빈 목록(0 이 아니다).
    """
    pts = _curve_points(dates, equity)
    if len(pts) < 2:
        return {"yearly": [], "monthly": []}
    yearly = []
    for year, prev_last, group in _period_rows(pts, lambda d: d.year):
        months = {d.month for d, _ in group}
        yearly.append({"year": int(year), "return_pct": round(_period_return_pct(prev_last, group), 4),
                       "max_drawdown_pct": round(_within_max_drawdown_pct(group), 4),
                       "n_days": len(group), "partial": not (1 in months and 12 in months)})
    month_rows = _period_rows(pts, lambda d: (d.year, d.month))
    monthly = []
    for i, ((year, month), prev_last, group) in enumerate(month_rows):
        monthly.append({"year": int(year), "month": int(month), "return_pct": round(_period_return_pct(prev_last, group), 4),
                        "n_days": len(group), "partial": i == 0 or i == len(month_rows) - 1})
    return {"yearly": yearly, "monthly": monthly}


def drawdown_episodes(dates: Any, equity: Any, top: int = 3) -> list[dict[str, Any]]:
    """주요 낙폭 구간 — 고점에서 바닥까지, 그리고 고점을 되찾은 날까지. 깊이순(같으면 먼저 일어난 것) 상위 `top` 개.

    `{peak_date, trough_date, recovery_date|None, depth_pct, days_to_trough, days_to_recover|None}` — 날짜는 ISO 문자열,
    일수는 달력일. 회복 못 했으면 `recovery_date`·`days_to_recover` 는 None.
    """
    pts = _curve_points(dates, equity)
    episodes: list[dict[str, Any]] = []
    peak: tuple[_dt.date, float] | None = None
    trough: tuple[_dt.date, float] | None = None

    def close(recovery: _dt.date | None) -> None:
        assert peak is not None and trough is not None
        episodes.append({
            "peak_date": peak[0].isoformat(), "trough_date": trough[0].isoformat(),
            "recovery_date": recovery.isoformat() if recovery else None,
            "depth_pct": round((trough[1] / peak[1] - 1.0) * 100.0, 4),
            "days_to_trough": (trough[0] - peak[0]).days,
            "days_to_recover": (recovery - peak[0]).days if recovery else None,
        })

    for d, v in pts:
        if peak is None or v >= peak[1]:
            if trough is not None:
                close(d)
                trough = None
            peak = (d, v)
        elif trough is None or v < trough[1]:
            trough = (d, v)
    if trough is not None:
        close(None)
    episodes.sort(key=lambda e: (e["depth_pct"], e["peak_date"]))
    return episodes[:max(0, int(top))]
