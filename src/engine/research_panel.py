"""연구 패널과 그 출처 — ★등급은 주장이 아니라 파생이다★ (M9)
==============================================================================
지금까지 증거 등급은 `regime_control.run(panel_is_synthetic=...)` 이라는
**호출자가 주는 검증되지 않은 불리언**이 정했다. 합성 패널에 `False` 를 넘기면
그대로 `E3` 가 찍혔고, `regime_signal_gate` 는 아예 `"E0"` 하드코딩이라 실데이터가
들어와도 계속 E0 라고 말했을 것이다. 두 경우 다 **하지 않은 검증을 주장**한다.

★여기서는 등급을 출처에서 파생한다★ — 찍는 것이 아니라 읽는 것이다. 규칙은 셋:

| 규칙 | 뜻 |
|---|---|
| **약한 고리가 지배한다** | 실가격 + 합성 국면 = E0. 한쪽이 합성이면 실증거가 아니다 |
| **미상은 등급이 아니다** | 출처를 모르면 `None` + 사유. 모르는 것에 E3 를 찍으면 그것이 과대주장이다 |
| **주입하면 강등된다** | 반합성은 검정력을 재는 **도구**이지 증거가 아니다 |

★가장 중요한 불변식★ 실데이터가 없을 때 **합성으로 대체하지 않는다**.
운영에서 합성값을 만들지 않는다는 CLAUDE.md §6 이 연구 경로에도 그대로 적용된다.
`real_panel` 은 개발 모드에서도 실데이터 아니면 `None` 을 낸다 — `mock_allowed()`
는 **호출자가 합성으로 갈아탈 수 있는가**를 정하지, 실 공급자가 몰래 합성을 내도
되는가를 정하지 않는다. 두 개념을 섞으면 개발에서 통과한 경로가 운영에서 다르게
동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.data.mock_gate import mock_allowed

# ── 출처 어휘 ──────────────────────────────────────────────────────────────
SOURCE_SYNTHETIC = "synthetic"
PRICE_SOURCE_KRX = "krx_daily_prices"
REGIME_SOURCE_AXES = "regime_axes"

BASIS_ADJ = "adj_close"
BASIS_CLOSE = "close"

# ── 등급 ───────────────────────────────────────────────────────────────────
# `source_registry.EVIDENCE_GRADES` 를 단일 출처로 쓰고 E4(시점 고정)를 더한다 —
# CLAUDE.md §2 가 E0~E5 를 정의하는데 레지스트리는 E0~E3 까지만 안다.
GRADE_E0 = "E0"      # 합성
GRADE_E3 = "E3"      # 실 과거
GRADE_E4 = "E4"      # 시점 고정(빈티지 재현)

REVISION_MANAGED = "managed"


@dataclass(frozen=True)
class Panel:
    """연구 패널 — 수익·날짜·국면 라벨, 그리고 ★그것들이 어디서 왔는지★."""

    names: list[str]
    returns: Any                 # np.ndarray (T×N) 일수익
    dates: list
    points: list[dict]           # 월별 국면 라벨 `{t, growth, inflation, regime}`
    provenance: dict = field(default_factory=dict)


# ── ★등급 파생 — 규칙이지 데이터가 아니다★ ─────────────────────────────────
def evidence_grade(provenance: dict | None) -> tuple[str | None, str]:
    """출처 → `(등급, 사유)`. 출처를 모르면 `(None, 사유)`.

    ★순수 함수다★ 데이터를 만들어 규칙을 확인하려 하면 픽스처의 우연을 계약으로
    착각한다(S6 에서 치른 값).
    """
    prov = provenance or {}
    ps, rs = prov.get("price_source"), prov.get("regime_source")

    if not ps or not rs:
        missing = [n for n, v in (("가격", ps), ("국면", rs)) if not v]
        return None, (f"{' · '.join(missing)} 출처를 모릅니다 — 등급을 찍지 "
                      f"않습니다(미상은 E3 가 아닙니다)")

    injected = prov.get("injected_scale")
    if injected is not None:
        return GRADE_E0, (f"신호를 주입한 반합성 패널입니다(척도 {injected}) — "
                          f"검정력을 재는 도구이지 증거가 아닙니다")

    if ps == SOURCE_SYNTHETIC or rs == SOURCE_SYNTHETIC:
        both = ps == SOURCE_SYNTHETIC and rs == SOURCE_SYNTHETIC
        return GRADE_E0, ("합성 패널입니다" if both else
                          "★약한 고리가 지배합니다★ 한쪽이 합성이면 실증거가 "
                          "아닙니다")

    basis = prov.get("price_basis")
    if basis != BASIS_ADJ:
        return GRADE_E0, (f"가격 기준이 `{basis}` 입니다 — 원주가 ≠ 수정주가라 "
                          f"기업행위가 조정되지 않았습니다")

    vintage = prov.get("vintage") or {}
    if vintage.get("revision_bias") == REVISION_MANAGED:
        return GRADE_E4, "실 과거 + 빈티지 재현 — 시점 고정입니다"
    blocked = vintage.get("blocked_permanently") or []
    return GRADE_E3, ("실 과거이지만 빈티지를 재현하지 못합니다 — 개정 편향이 "
                      f"남습니다{f' (영구 부재: {len(blocked)}계열)' if blocked else ''}")


# ── 합성 공급자 ────────────────────────────────────────────────────────────
def synthetic_panel(*, months: int = 84, seed: int = 20260825,
                    scale: float = 1.0) -> Panel:
    """`t3_transmission.build_panel` 을 감싼다. ★비트 동일★(동결 해시가 건다)."""
    from scripts.t3_transmission import build_panel

    names, R, dates, points, _beta = build_panel(months=months, seed=seed,
                                                 scale=scale)
    return Panel(names=list(names), returns=R, dates=list(dates),
                 points=list(points),
                 provenance={"price_source": SOURCE_SYNTHETIC,
                             "regime_source": SOURCE_SYNTHETIC,
                             "price_basis": None, "vintage": None,
                             "injected_scale": None,
                             "synthetic_scale": float(scale),
                             "seed": int(seed),
                             "coverage": {"requested": len(names),
                                          "used": len(names)}})


# ── 실데이터 공급자 — ★없으면 거부한다★ ────────────────────────────────────
def _default_price_loader(codes, *, months, as_of=None):
    """`daily_prices.adj_close` — ★`close` 로 조용히 갈아타지 않는다★.

    기업행위가 조정되지 않은 원주가로 낸 수익은 실증거가 아니다(CLAUDE.md §4).
    빠진 종목은 **사유와 함께** 빠지고, 전부 없으면 빈 dict 를 낸다.
    """
    import pandas as pd
    from sqlalchemy import text

    from src.database import get_engine

    out: dict[str, Any] = {}
    reasons: list[str] = []
    sql = ("SELECT trade_date, adj_close FROM daily_prices "
           "WHERE ticker = :t AND adj_close IS NOT NULL"
           + (" AND trade_date <= :a" if as_of else "")
           + " ORDER BY trade_date")
    try:
        engine = get_engine()
        with engine.connect() as c:
            for code in codes:
                p = {"t": code, **({"a": as_of} if as_of else {})}
                rows = c.execute(text(sql), p).fetchall()
                if len(rows) < 2:
                    reasons.append(f"{code}: 수정주가(adj_close) 행이 없습니다")
                    continue
                s = pd.Series([float(r[1]) for r in rows],
                              index=pd.DatetimeIndex([r[0] for r in rows]))
                out[code] = s.pct_change().dropna()
    except Exception as e:  # noqa: BLE001
        return {}, None, [f"가격 조회 실패: {type(e).__name__}: {e}"]
    return out, (BASIS_ADJ if out else None), reasons


def _default_regime_loader(*, months, market="kr", as_of=None):
    """`regime_transitions.regime_path` + `regime_axes.axis_revision_status`."""
    try:
        from src.engine.regime_axes import axis_revision_status
        from src.engine.regime_snapshot_builder import observations_from_series
        from src.engine.regime_transitions import regime_path
        from src.services.macro_collector import get_macro_snapshot

        snap = get_macro_snapshot()
        series_map = getattr(snap, "series", None) or {}
        _ = observations_from_series  # 계약 확인용(경로가 살아 있는지)
        path = regime_path(series_map, market=market, months=int(months))
        return list(path.get("points") or []), axis_revision_status(market)
    except Exception:  # noqa: BLE001
        return [], None


def real_panel(codes: list[str], *, months: int = 84, as_of: str | None = None,
               market: str = "kr", price_loader=None,
               regime_loader=None) -> tuple[Panel | None, list[str]]:
    """실 가격 + 실 국면 라벨로 패널을 만든다. 못 만들면 `(None, 사유들)`.

    ★합성으로 대체하지 않는다★ 개발 모드에서도 그렇다. `mock_allowed()` 는
    **호출자가** 합성으로 갈아탈 수 있는가를 정하지(→ `panel_for`), 이 함수가
    몰래 합성을 내도 되는가를 정하지 않는다.
    """
    import numpy as np
    import pandas as pd

    pl = price_loader or _default_price_loader
    rl = regime_loader or _default_regime_loader

    series, basis, reasons = pl(list(codes), months=months, as_of=as_of)
    reasons = list(reasons or [])
    if not series:
        reasons.append("사용할 수 있는 실 가격이 없습니다 — 합성으로 대체하지 않습니다")
        return None, reasons

    points, vintage = rl(months=months, market=market, as_of=as_of)
    if not points:
        reasons.append("실 국면 라벨을 얻지 못했습니다 — 합성으로 대체하지 않습니다")
        return None, reasons

    names = [c for c in codes if c in series]
    df = pd.DataFrame({c: series[c] for c in names}).dropna(how="any")
    if df.empty:
        reasons.append("가격 계열이 겹치는 구간이 없습니다")
        return None, reasons

    # ★국면 월과 가격 월이 겹치는 구간만★ — 없는 달을 중립으로 메우지 않는다.
    price_months = {d.strftime("%Y-%m") for d in df.index}
    kept = [q for q in points if q.get("t") in price_months]
    if not kept:
        reasons.append("가격 구간과 국면 라벨 구간이 겹치지 않습니다")
        return None, reasons
    keep_m = {q["t"] for q in kept}
    df = df[[d.strftime("%Y-%m") in keep_m for d in df.index]]

    prov = {
        "price_source": PRICE_SOURCE_KRX, "regime_source": REGIME_SOURCE_AXES,
        "price_basis": basis, "vintage": vintage, "injected_scale": None,
        "as_of": as_of, "market": market,
        "coverage": {"requested": len(codes), "used": len(names),
                     "n_months": len(kept), "n_obs": int(len(df)),
                     "dropped": [c for c in codes if c not in series]},
    }
    return Panel(names=names, returns=np.asarray(df.values, dtype=float),
                 dates=list(df.index), points=kept, provenance=prov), reasons


def panel_for(*, real: bool, codes: list[str] | None = None, months: int = 84,
              seed: int = 20260825, scale: float = 1.0, as_of: str | None = None,
              market: str = "kr", **kw) -> tuple[Panel | None, list[str]]:
    """하네스가 쓰는 단일 진입점 — ★mock 게이트가 여기서 하중이 된다★.

    운영(`mock_allowed()` False)에서는 **합성 연구 패널을 돌리지 않는다**.
    합성 결과가 운영 화면·기록에 실증거인 척 남는 경로를 구조로 막는다.
    """
    if real:
        return real_panel(list(codes or []), months=months, as_of=as_of,
                          market=market, **kw)
    if not mock_allowed():
        return None, ["운영 환경(KIS_USE_MOCK≠1)에서는 합성 연구 패널을 "
                      "돌리지 않습니다 — 실 패널(--real)을 쓰십시오"]
    return synthetic_panel(months=months, seed=seed, scale=scale), []


# ── 반합성 양성 통제 ───────────────────────────────────────────────────────
def inject_regime_drift(panel: Panel, scale: float) -> Panel:
    """국면조건부 드리프트를 `scale` 배 한 **새** 패널. ★원본을 바꾸지 않는다★.

    `r'_{t,i} = r_{t,i} + (scale − 1)·(μ̂_{regime(t),i} − μ̂_i)`
    — μ̂ 는 **그 패널에서 추정한** 국면별 월평균이다.

    ★실 공분산·꼬리·자기상관은 그대로 둔다★ 이것이 반합성의 요점이다. 주입은 월
    단위 **수준 이동**이라 각 달 안의 일별 편차가 변하지 않는다.

    - `scale = 1` → 항등 · `scale = 0` → 국면 정보 제거(음성 통제)
    - `scale > 1` → 양성 통제

    합성 패널에서 `t3_transmission.scaled_profiles` 가 하는 일과 **같은 계약**이라
    `research_power.power_curve` 가 양쪽에서 그대로 돈다.
    """
    import numpy as np
    import pandas as pd

    R = np.asarray(panel.returns, dtype=float)
    idx = pd.DatetimeIndex(panel.dates)
    mo = pd.Series(idx).dt.strftime("%Y-%m").values
    by_month = {q["t"]: q.get("regime") for q in panel.points}
    lab = np.array([by_month.get(m) for m in mo], dtype=object)

    # 월평균 → 국면별 평균 → 전체 평균. ★일별이 아니라 월 수준에서 잰다★
    monthly = np.array([R[mo == m].sum(axis=0) for m in sorted(set(mo))])
    mlab = np.array([by_month.get(m) for m in sorted(set(mo))], dtype=object)
    grand = monthly.mean(axis=0)

    shift = np.zeros_like(R)
    k = float(scale) - 1.0
    for g in {x for x in mlab if x is not None}:
        sel = mlab == g
        if not sel.any():
            continue
        delta = monthly[sel].mean(axis=0) - grand          # 국면 효과(월 단위)
        rows = lab == g
        n_days = np.array([int((mo == m).sum()) for m in mo[rows]], dtype=float)
        shift[rows] = k * delta / n_days[:, None]          # 일별로 고르게 나눈다

    prov = {**dict(panel.provenance), "injected_scale": float(scale),
            "semi_synthetic": True}
    return Panel(names=list(panel.names), returns=R + shift,
                 dates=list(panel.dates), points=list(panel.points),
                 provenance=prov)
