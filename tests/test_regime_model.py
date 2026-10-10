"""BH3 · 백테스트 국면 (R4-a) — ★새 분류기를 짜지 않는다, 엄격 PIT, KR·US 둘 다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-bh-safety-attribution-regime-design.md` §4.3 ·
대상 `src/engine/regime_model.py` · 엔진 `multi_strategy_backtest`·`realism_engine`

## 사용자가 정한 것

- `hrp_macro` 는 계속 거절(기울기 규칙은 새 배분 정책).
- `regime_change` 에서 국면이 미상인 날은 **트리거하지 않고 센다**.
- 국면은 **KR·US 둘 다** — *"나중에 KR 도 데이터 적재할 거야"* → 시장별 하드코딩 없이
  빈티지 스토어의 **실제 행**으로 가용성이 정해진다.

## 거는 것

- 판정은 `regime_axes`(단일 정의)와 **같은 답**(골든) · 룩어헤드 짝 · 성분 부족 → None + 사유 ·
  KR 을 막는 하드코딩 없음(재료가 있으면 KR 라벨) · `systemic_risk_score` 는 **항상 None**.
- 엔진 `regime_change`: 전부 미상 → 초기 배분 1회뿐 · 알려진 라벨 전환 때만 트리거 ·
  "None 이면 매일" 이 돌아오면 죽는다.
- 어휘는 `regime_axes.QUADRANTS` 하나(대문자 `DEFLATION` 이 소스에 없다).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.regime_axes import AXES, QUADRANTS, compute_axis_detail, quadrant  # noqa: E402
from tests.test_strategy_registry import _registry, _req, _stored_run, db, market  # noqa: E402,F401


def _monthly(n: int, f) -> tuple[list[str], list[float]]:
    periods = [str(p.date()) for p in pd.date_range("2016-01-01", periods=n, freq="MS")]
    return periods, [float(f(i)) for i in range(n)]


def _goldilocks_store(n: int = 99) -> dict:
    """성장 가속(지수 YoY ↑) · 물가 둔화(YoY ↓) — Goldilocks 가 나와야 하는 재료."""
    grow = lambda i: 100 * math.exp(0.0005 * i * i / 10 + 0.001 * i)          # noqa: E731
    slow = lambda i: 100 * math.exp(0.004 * i - 0.00003 * i * i)              # noqa: E731
    return {
        "INDPRO": _monthly(n, grow), "PAYEMS": _monthly(n, grow),
        "UNRATE": _monthly(n, lambda i: 6.0 - 0.03 * i),
        "GDPC1": _monthly(n, grow),
        "CPIAUCSL": _monthly(n, slow),
        "T10YIE": _monthly(n, lambda i: 2.5 - 0.01 * i),
        "KR_LEADING_CYCLE": _monthly(n, lambda i: 99 + 0.05 * i),
        "KR_IP": _monthly(n, grow), "KOSPI": _monthly(n, grow),
        "KR_CPI": _monthly(n, slow),
    }


def _loader(store: dict):
    def load(key, as_of):
        got = store.get(key)
        if not got:
            return None
        periods, values = got
        keep = [(p, v) for p, v in zip(periods, values) if p <= str(as_of)[:10]]
        if not keep:
            return None
        return [p for p, _ in keep], [v for _, v in keep]
    return load


class _S:
    def __init__(self, values):
        self.values = values


# ── 판정 — regime_axes 와 같은 답 ─────────────────────────────────────

@pytest.mark.parametrize("market", ["us", "kr"])
def test_the_label_is_the_same_as_regime_axes(market):
    from src.engine.regime_model import MultiRegimeModel
    store = _goldilocks_store()
    call = MultiRegimeModel.classify_at("2024-03-31", market, series_loader=_loader(store))
    g_def, i_def = AXES[market]
    series_map = {k: _S(v[1]) for k, v in store.items()}
    g = compute_axis_detail(series_map, g_def)["score"]
    i = compute_axis_detail(series_map, i_def)["score"]
    assert call["regime"] == quadrant(g, i)
    assert call["regime"] in QUADRANTS
    assert call["growth_signal"] == pytest.approx(g) and call["inflation_signal"] == pytest.approx(i)
    assert call["market"] == market and call["as_of"] == "2024-03-31"
    assert sum(call["probs"].values()) == pytest.approx(1.0, abs=1e-3)


def test_kr_is_not_hardcoded_off():
    """★KR 을 막는 코드가 없다★ — 재료(빈티지)가 있으면 KR 라벨이 나온다."""
    from src.engine.regime_model import MultiRegimeModel
    call = MultiRegimeModel.classify_at("2024-03-31", "kr",
                                        series_loader=_loader(_goldilocks_store()))
    assert call["regime"] in QUADRANTS and call["reason"] is None


def test_missing_material_is_unknown_with_a_reason():
    """성분 부족 → None + 무엇이 없는지. ★'데이터 부족' 문자열을 라벨로 쓰지 않는다★."""
    from src.engine.regime_model import MultiRegimeModel
    store = {k: v for k, v in _goldilocks_store().items() if k in ("INDPRO", "CPIAUCSL")}
    call = MultiRegimeModel.classify_at("2024-03-31", "us", series_loader=_loader(store))
    assert call["regime"] is None
    assert call["reason"] and "GDPC1" in call["reason"]


def test_an_empty_store_is_unknown_for_both_markets():
    from src.engine.regime_model import MultiRegimeModel
    for m in ("kr", "us"):
        call = MultiRegimeModel.classify_at("2024-03-31", m, series_loader=lambda k, a: None)
        assert call["regime"] is None and call["reason"]


def test_a_later_release_does_not_change_an_earlier_label():
    """★룩어헤드 짝★ — as_of 이후 공표분이 끼어들어도 그 날의 라벨은 같다."""
    from src.engine.regime_model import MultiRegimeModel
    base = _goldilocks_store(100)
    periods = base["CPIAUCSL"][0]
    cut = periods.index("2024-03-01")
    shocked = dict(base)
    shocked["CPIAUCSL"] = (periods, base["CPIAUCSL"][1][:cut + 1]
                           + [v * 3 for v in base["CPIAUCSL"][1][cut + 1:]])
    a = MultiRegimeModel.classify_at("2024-03-31", "us", series_loader=_loader(base))
    b = MultiRegimeModel.classify_at("2024-03-31", "us", series_loader=_loader(shocked))
    assert a["regime"] == b["regime"] and a["inflation_signal"] == b["inflation_signal"]
    later = MultiRegimeModel.classify_at("2024-12-31", "us", series_loader=_loader(shocked))
    assert later["inflation_signal"] != a["inflation_signal"], "★짝★ 공표된 뒤엔 달라진다"


def test_the_model_never_produces_a_systemic_risk_score():
    """★D 는 하지 않는다★ — 이 점수는 킬스위치 auto_risk 의 재료다."""
    from src.engine.regime_model import MultiRegimeModel
    call = MultiRegimeModel.classify_at("2024-03-31", "us",
                                        series_loader=_loader(_goldilocks_store()))
    assert call["systemic_risk_score"] is None and call["systemic_risk_reason"]


def test_the_panel_uses_only_the_previous_day_and_fills_forward():
    """결정일 t 는 **전날까지** 공표분 · 월 단위로 판정해 거래일에 앞으로 채운다."""
    from src.engine.regime_model import MultiRegimeModel
    seen = []

    def spy(key, as_of):
        seen.append(str(as_of)[:10])
        return _loader(_goldilocks_store())(key, as_of)

    days = list(pd.bdate_range("2024-03-01", "2024-04-30"))
    panel = MultiRegimeModel.panel(days, markets=("us",), series_loader=spy)
    assert set(panel["us"]) == set(days)
    assert set(seen) == {"2024-02-29", "2024-03-31"}, sorted(set(seen))
    assert all(c["as_of"] < str(d.date()) for d, c in panel["us"].items())


# ── 엔진 — regime_change ─────────────────────────────────────────────

def _two(db):
    reg = _registry(db)
    a = reg.register(_stored_run(_req()), "A")["id"]
    b = reg.register(_stored_run(_req(sell_conditions=[
        {"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 3}])), "B")["id"]
    return [a, b]


def _fake_panel(monkeypatch, by_market):
    """시장 → (날짜 → 라벨 | None) 함수. 판정 기계를 건너뛰고 엔진만 본다."""
    from src.engine import regime_model

    def panel(days, markets=("kr", "us"), *, series_loader=None, engine=None):
        out = {}
        for m in markets:
            f = by_market.get(m, lambda d: None)
            out[m] = {d: {"regime": f(d), "market": m, "as_of": str(d.date()),
                          "growth_signal": None, "inflation_signal": None,
                          "systemic_risk_score": None,
                          "reason": None if f(d) else "빈티지 없음(테스트)",
                          "series_used": []}
                      for d in days}
        return out

    monkeypatch.setattr(regime_model.MultiRegimeModel, "panel", staticmethod(panel))


def _run(db, sids, **over):
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    cfg = dict(strategy_ids=sids, start_date="2023-06-01", end_date="2024-03-01",
               allocation_method="hrp", rebalance_policy="regime_change",
               macro_overlay_enabled=False, lookback_days=60, max_weight=0.8,
               min_weight=0.0)
    cfg.update(over)
    out = MultiStrategyBacktester(db).run(BacktestConfig(**cfg))
    assert out.get("success"), out.get("message")
    return out


def test_all_unknown_means_one_initial_allocation_only(db, market, monkeypatch):
    """★미상인 날은 트리거하지 않는다★ — 예전엔 "None 이면 매일" 이었다."""
    _fake_panel(monkeypatch, {})
    out = _run(db, _two(db), regime_market="kr")
    assert out["summary"]["n_rebalances"] == 1
    rb = out["summary"]["regime_rebalance"]
    assert rb["market"] == "kr" and rb["n_triggers"] == 0
    assert rb["n_known_days"] == 0 and rb["n_unknown_days"] > 0
    assert rb["reason"] and "초기 배분" in rb["reason"]


def test_only_a_known_to_known_change_triggers(db, market, monkeypatch):
    cut = pd.Timestamp("2023-11-15")
    _fake_panel(monkeypatch, {
        "us": lambda d: "Goldilocks" if d < cut else "Stagflation",
        "kr": lambda d: None})
    out = _run(db, _two(db), regime_market="us")
    rb = out["summary"]["regime_rebalance"]
    assert rb["n_triggers"] == 1
    assert out["summary"]["n_rebalances"] == 2          # 초기 1 + 전환 1
    rebal_days = [r["date"] for r in out["daily_records"] if r["rebalanced"]]
    assert rebal_days[-1] == "2023-11-15"


def test_an_unknown_gap_between_the_same_label_does_not_trigger(db, market, monkeypatch):
    """Goldilocks → 미상 → Goldilocks 는 전환이 아니다."""
    lo, hi = pd.Timestamp("2023-10-01"), pd.Timestamp("2023-11-01")
    _fake_panel(monkeypatch, {"us": lambda d: None if lo <= d < hi else "Goldilocks"})
    out = _run(db, _two(db), regime_market="us")
    assert out["summary"]["regime_rebalance"]["n_triggers"] == 0


def test_records_carry_both_markets_and_the_decision_label(db, market, monkeypatch):
    _fake_panel(monkeypatch, {"us": lambda d: "Reflation", "kr": lambda d: None})
    out = _run(db, _two(db), regime_market="us", rebalance_policy="monthly")
    rec = out["daily_records"][30]
    assert rec["regime"] == "Reflation"
    assert rec["regimes"] == {"kr": None, "us": "Reflation"}
    labels = out["summary"]["regime_labels"]
    assert labels["us"]["n_known_days"] == len(out["daily_records"])
    assert labels["kr"]["n_known_days"] == 0 and labels["kr"]["first_unknown_reason"]
    assert all(r["systemic_risk"] is None for r in out["daily_records"])


def test_monthly_policy_is_unaffected_by_regimes(db, market, monkeypatch):
    """★짝★ — 국면은 관측이다. regime_change 가 아니면 리밸런싱 날이 같다."""
    sids = _two(db)
    _fake_panel(monkeypatch, {"us": lambda d: "Goldilocks"})
    a = _run(db, sids, regime_market="us", rebalance_policy="monthly")
    _fake_panel(monkeypatch, {"us": lambda d: "Stagflation" if d.day % 2 else "Goldilocks"})
    b = _run(db, sids, regime_market="us", rebalance_policy="monthly")
    assert a["summary"]["total_return_pct"] == b["summary"]["total_return_pct"]
    assert a["summary"]["n_rebalances"] == b["summary"]["n_rebalances"]


def test_the_attribution_speaks_the_single_vocabulary():
    """★어휘 하나★ — 엔진·분해기 **코드**(문자열 리터럴)에 옛 대문자 사분면이 없다.

    주석은 보지 않는다 — 옛 어휘를 설명하는 주석은 역사이지 동작이 아니다.
    """
    import ast
    import pathlib
    old = {"GOLDILOCKS", "REFLATION", "STAGFLATION", "DEFLATION"}
    for f in ("src/engine/multi_strategy_backtest.py", "src/engine/attribution_decomposer.py",
              "src/engine/realism_engine.py"):
        tree = ast.parse(pathlib.Path(f).read_text(encoding="utf-8"))
        lits = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not (lits & old), (f, lits & old)


def test_the_regime_breakdown_uses_the_quadrants_and_counts_unknown_days():
    """국면별 표 — 사분면 라벨로 묶고, 미상인 날은 "미상" 한 줄로 센다."""
    from src.engine.attribution_decomposer import AttributionDecomposer
    df = pd.DataFrame({
        "portfolio_return": [0.01, -0.01, 0.02, 0.0],
        "regime": ["Goldilocks", "Goldilocks", None, "Disinflation"],
        "systemic_risk": [None] * 4,
        **{c: [0.0] * 4 for c in ("baseline_effect", "allocation_effect", "macro_effect",
                                  "netting_effect", "cost_effect")},
    })
    rows = {r["regime"]: r for r in AttributionDecomposer._regime_breakdown(df)}
    assert set(rows) == {"Goldilocks", "Disinflation", "미상"}
    assert sum(r["n_days"] for r in rows.values()) == len(df)
    assert rows["미상"]["regime_known"] is False


def test_a_label_outside_the_vocabulary_is_not_silently_dropped():
    """★조용히 버리지 않는다★ — 옛 대문자 라벨은 제 줄로 세고 어휘 밖이라고 말한다."""
    from src.engine.attribution_decomposer import AttributionDecomposer
    df = pd.DataFrame({"portfolio_return": [0.01, 0.02], "regime": ["GOLDILOCKS", "Goldilocks"],
                       "systemic_risk": [None, None]})
    rows = {r["regime"]: r for r in AttributionDecomposer._regime_breakdown(df)}
    assert rows["GOLDILOCKS"]["regime_known"] is False and rows["GOLDILOCKS"]["regime_note"]
    assert rows["Goldilocks"]["regime_known"] is True


def test_counterfactual_scenarios_keep_the_regime_market():
    """★시나리오가 국면 시장을 잃지 않는다★ — 기준과 대안이 같은 시장의 국면을 본다."""
    from src.engine.counterfactual_analyzer import PRESET_SCENARIOS, CounterfactualAnalyzer
    from src.engine.multi_strategy_backtest import BacktestConfig
    base = BacktestConfig(strategy_ids=[1], start_date="2024-01-02", end_date="2024-06-28",
                          allocation_method="hrp", rebalance_policy="regime_change",
                          regime_market="us")
    for sc in PRESET_SCENARIOS.values():
        assert CounterfactualAnalyzer._apply_override(base, sc).regime_market == "us", sc.name


def test_the_run_door_accepts_and_validates_the_regime_market():
    import pydantic

    from src.api.stage11_routes import MultiBacktestRunRequest
    body = {"strategy_ids": [1], "start_date": "2024-01-02", "end_date": "2024-06-28"}
    assert MultiBacktestRunRequest(**body).regime_market == "kr"
    assert MultiBacktestRunRequest(**body, regime_market="us").regime_market == "us"
    with pytest.raises(pydantic.ValidationError):
        MultiBacktestRunRequest(**body, regime_market="jp")


def test_realism_regime_change_follows_the_same_rule(db, market, monkeypatch):
    """★두 엔진이 같은 규칙★ — realism 도 미상인 날 트리거하지 않고, 전환 때만 한다."""
    from src.engine.realism_engine import RealismConfig, RealisticBacktester
    sids = _two(db)
    cut = pd.Timestamp("2023-11-15")

    def _r(panel_spec, mkt):
        _fake_panel(monkeypatch, panel_spec)
        out = RealisticBacktester(db).run(RealismConfig(
            strategy_ids=sids, start_date="2023-06-01", end_date="2024-03-01",
            allocation_method="hrp", rebalance_policy="regime_change",
            macro_overlay_enabled=False, lookback_days=60, max_weight=0.8, min_weight=0.0,
            enable_cash_yield=False, enable_regime_adaptive=False, regime_market=mkt))
        assert out.get("success"), out.get("message")
        return out

    a = _r({}, "kr")
    assert a["summary"]["n_rebalances"] == 1
    b = _r({"us": lambda d: "Goldilocks" if d < cut else "Stagflation"}, "us")
    assert b["summary"]["n_rebalances"] == 2
    assert b["daily_records"][-1]["regime"] == "Stagflation"
