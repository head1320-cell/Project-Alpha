"""CF3 골든 — ★선을 점검해도 계산한 숫자는 한 자리도 바뀌지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §CF3. 사용자 결정(2026-10-17): 최적화의
역변동성 대체·백테스트의 λ 누락·민감도의 방식 무시는 ★드러내기만★ 한다 — 고치는 일은 따로 승인받는다.

CF3 는 수익률 불러오기·옵티마이저·점수→비중에 **관측**(잃은 날 · 대체 기록 · 빠진 생각 다리 · 공분산이 빠진 사유)을 더한다.
관측을 더하기 **전**(HEAD `e66e04c`) 에 이 노드들의 출력을 `tests/golden/cf3_weights.json` 에 얼렸다. 바뀐 뒤에도 같아야 한다.
더해도 되는 것은 `NEW_KEYS`(관측 키)뿐이고, 그 값은 다른 테스트가 건다.

★데이터는 이 파일이 만든다★ — 다른 테스트 모듈의 전역 RNG 는 테스트 순서에 따라 값이 달라진다. 정규분포 표본을 6자리로 반올림해
`np.exp` 같은 CPU 마다 끝자리가 갈리는 연산을 거치지 않는다(`a687c2d` 의 교훈). 늦게 시작하는 종목 · 중간에 빈 날이 있는 종목 ·
빈 날이 있는 벤치마크를 일부러 넣는다 — CF3 가 드러낼 바로 그 경우다.

비교는 상대 1e-9 로 한다(최적화기의 마지막 비트는 BLAS 에 따라 갈릴 수 있다). `CF3_GOLDEN_EXACT=1` 이면 정확히 같아야 한다 —
관측을 더하기 전·후에 로컬에서 이 모드로 한 번씩 돌린다. 얼리기: `UPDATE_CF3_GOLDEN=1`.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "cf3_weights.json"
#: CF3 가 더하는 관측 키 — 비교에서 뺀다(어느 깊이에 있든).
NEW_KEYS = {"alignment", "fallbacks", "view_legs_dropped", "sigma_missing", "dropped_zero"}

T5 = ["005930", "000660", "035420", "051910", "068270"]
LATE, HOLEY = "068270", "051910"
AS_OF = "2026-07-15"

#: 절대 생각 · 유니버스 밖 종목이 섞인 절대 생각 · 한쪽 다리가 유니버스 밖인 스프레드 생각.
VIEWS = [
    {"assets": ["005930"], "direction": 1, "magnitude_pct": 4.0, "confidence": 60},
    {"assets": ["000660", "999999"], "direction": 1, "magnitude_pct": 3.0, "confidence": 50},
    {"weights": {"035420": 1.0, "999998": -1.0}, "direction": 1, "magnitude_pct": 2.0, "confidence": 40},
]


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(20261017)
    n = 1100
    idx = pd.bdate_range(end=AS_OF, periods=n)
    common = rng.normal(0.0003, 0.009, n)
    cols = {}
    for i, t in enumerate(T5):
        own = rng.normal(0.0002 + 0.0001 * i, 0.010 + 0.002 * i, n)
        cols[t] = np.round((0.4 + 0.1 * i) * common + own, 6)
    cols["KOSPI"] = np.round(common + rng.normal(0.0, 0.002, n), 6)
    df = pd.DataFrame(cols, index=idx)
    df.loc[df.index[:300], LATE] = np.nan                       # 늦게 상장한 종목
    for k in (700, 820, 905, 1010):                             # 중간에 빈 날
        df.loc[df.index[k], HOLEY] = np.nan
    for k in (650, 760, 880, 960, 1040, 1090):                  # 벤치마크 빈 날
        df.loc[df.index[k], "KOSPI"] = np.nan
    return df


@pytest.fixture()
def market(monkeypatch):
    df = _frame()
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns", lambda tickers, start, end: df)
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 400000.0, "000660": 120000.0, "035420": 30000.0}.get(code, 50000.0))
    return df


def _node(id_, type_, **params):
    return {"id": id_, "type": type_, "params": params, "position": {"x": 0, "y": 0}}


def _edge(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


def _chain(model="mvo", *, views=None, lookback=756, opt=None, backtest=None) -> dict:
    nodes = [_node("u", "universe", tickers=T5, benchmark="KOSPI"),
             _node("r", "returns", lookback_days=lookback, as_of=AS_OF),
             _node("e", "estimate"),
             _node("o", "optimizer", model=model, **(opt or {})),
             _node("k", "risk")]
    edges = [_edge("u", "universe", "r", "universe"), _edge("r", "returns", "e", "returns"),
             _edge("r", "returns", "o", "returns"), _edge("e", "belief", "o", "belief"),
             _edge("o", "weights", "k", "weights")]
    if views is not None:
        nodes.append(_node("v", "views", views=views))
        edges.append(_edge("v", "views", "o", "views"))
    if backtest is not None:
        nodes.append(_node("b", "backtest", **backtest))
        edges += [_edge("r", "returns", "b", "returns"), _edge("o", "weights", "b", "weights")]
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _plain(x):
    """JSON 으로 왕복 — numpy 수는 float 로."""
    return json.loads(json.dumps(x, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def _views(report: dict, ids: tuple[str, ...]) -> dict:
    out = {}
    for i in ids:
        n = report["nodes"][i]
        out[i] = {"status": n["status"], "reason": n["reason"], "view": n["view"]}
    return _plain(out)


# ── 사례 ─────────────────────────────────────────────────────────────────────

def _loader(lookback: int) -> dict:
    from src.api.allocation_routes import _load_clean_returns
    returns, bench, excluded, coverage = _load_clean_returns(T5, "KOSPI", lookback, as_of=AS_OF)
    return _plain({"index": [str(d.date()) for d in returns.index[[0, -1]]], "shape": list(returns.shape),
                   "columns": list(returns.columns), "sum": returns.to_numpy().sum(axis=0).tolist(),
                   "bench_len": None if bench is None else int(len(bench)),
                   "bench_sum": None if bench is None else float(bench.sum()),
                   "excluded": excluded, "coverage": coverage})


def _chain_case(model, **kw) -> dict:
    ids = ("r", "o", "k") + (("b",) if kw.get("backtest") else ())
    return _views(pg.run(_chain(model, **kw), gn.REGISTRY), ids)


def _scores_case(weighting: str, with_missing: bool) -> dict:
    from src.api.allocation_graph_nodes_signal import ScoresToWeightsParams, _scores_to_weights
    _, values, _ = pg._execute(_chain("mvo"), gn.REGISTRY)
    scores = {"005930": 3.0, "000660": 2.5, "035420": 2.0, "051910": 1.0, LATE: 0.5}
    if with_missing:
        scores["999999"] = 2.8
    try:
        out = _scores_to_weights({"scores": {"scores": scores, "kind": "factor"}, "returns": values["r"]["returns"]},
                                 ScoresToWeightsParams(top_k=4, weighting=weighting))
    except pg.NodeFailure as e:
        return {"failed": e.reason}
    w = out.values["weights"]
    sig = w.get("sigma_annual")
    return _plain({"view": out.view, "names": w["names"], "weights": np.asarray(w["weights"]).tolist(),
                   "sigma_sum": None if sig is None else float(np.asarray(sig).sum())})


def _opt_none(*a, **k):
    return None


def _raise(*a, **k):
    raise np.linalg.LinAlgError("CF3 골든 — 강제로 낸 실패")


#: 이름 → (만드는 함수, 바꿔 끼울 것 [(대상, 값)]).
CASES: dict[str, tuple] = {
    "loader_756": (lambda: _loader(756), []),
    "loader_900": (lambda: _loader(900), []),
    "mvo": (lambda: _chain_case("mvo"), []),
    "bl_views": (lambda: _chain_case("bl", views=VIEWS), []),
    "risk_parity": (lambda: _chain_case("risk_parity"), []),
    "hrp": (lambda: _chain_case("hrp"), []),
    "min_var_cap40": (lambda: _chain_case("min_var", opt={"constraints": {"max_weight_pct": 40}}), []),
    "mv_utility_1_5": (lambda: _chain_case("mv_utility", opt={"risk_aversion": 1.5}), []),
    "max_div": (lambda: _chain_case("max_div"), []),
    "min_cvar": (lambda: _chain_case("min_cvar"), []),
    "robust": (lambda: _chain_case("robust"), []),
    "mvo_900": (lambda: _chain_case("mvo", lookback=900), []),
    "bl_backtest": (lambda: _chain_case("bl", views=VIEWS, backtest={"rebalance": "Q", "cost_bps": 15}), []),
    "fallback_opt_mvo": (lambda: _chain_case("mvo"), [("src.engine.allocation_studio._opt", _opt_none)]),
    "fallback_opt_bl": (lambda: _chain_case("bl", views=VIEWS), [("src.engine.allocation_studio._opt", _opt_none)]),
    "fallback_opt_mv_utility": (lambda: _chain_case("mv_utility", opt={"risk_aversion": 1.5}),
                                [("src.engine.allocation_studio._opt", _opt_none)]),
    "fallback_bl_posterior": (lambda: _chain_case("bl", views=VIEWS),
                              [("src.engine.allocation_studio.bl_posterior", _raise)]),
    "fallback_hrp": (lambda: _chain_case("hrp"), [("src.engine.risk_allocations._hrp_weights", _raise)]),
    "scores_equal": (lambda: _scores_case("equal", False), []),
    "scores_equal_missing": (lambda: _scores_case("equal", True), []),
    "scores_tilt_missing": (lambda: _scores_case("factor_tilt", True), []),
    "scores_inverse_vol": (lambda: _scores_case("inverse_vol", False), []),
    "scores_min_var": (lambda: _scores_case("min_var", False), []),
    "scores_min_var_missing": (lambda: _scores_case("min_var", True), []),
}


def _make(name: str, monkeypatch) -> dict:
    fn, patches = CASES[name]
    for target, value in patches:
        monkeypatch.setattr(target, value)
    return fn()


# ── 비교 ─────────────────────────────────────────────────────────────────────

def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in NEW_KEYS}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def _diff(a, b, path="$") -> str | None:
    """첫 차이의 위치 — 없으면 None."""
    exact = os.environ.get("CF3_GOLDEN_EXACT") == "1"
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: 키 {sorted(set(a) ^ set(b))}"
        for k in a:
            d = _diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: 길이 {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = _diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if isinstance(a, float) and isinstance(b, float) and not exact:
        if math.isnan(a) and math.isnan(b):
            return None
        return None if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12) else f"{path}: {a!r} ≠ {b!r}"
    return None if a == b else f"{path}: {a!r} ≠ {b!r}"


@pytest.fixture(scope="module")
def frozen() -> dict:
    if os.environ.get("UPDATE_CF3_GOLDEN") == "1":
        return {}
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(CASES))
def test_outputs_equal_the_frozen_ones(name, market, monkeypatch, frozen):
    got = _make(name, monkeypatch)
    if os.environ.get("UPDATE_CF3_GOLDEN") == "1":
        data = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
        data[name] = got
        GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert name in frozen, f"골든에 {name} 이 없어요 — UPDATE_CF3_GOLDEN=1 로 먼저 얼려요."
    d = _diff(_strip(got), _strip(frozen[name]))
    assert d is None, d


def test_the_frame_has_the_cases_cf3_will_surface():
    """공허 배제 — 늦은 상장·빈 날·벤치 빈 날이 실제로 데이터에 있다."""
    df = _frame()
    assert int(df[LATE].isna().sum()) == 300
    assert int(df[HOLEY].isna().sum()) == 4
    assert int(df["KOSPI"].isna().sum()) == 6


def test_the_fallback_cases_actually_fall_back(market, monkeypatch):
    """공허 배제 — 강제 실패 사례의 비중이 보통 사례와 다르다(바꿔 끼우기가 실제로 닿는다)."""
    plain = _make("mvo", monkeypatch)["o"]["view"]["weights"]
    forced = _make("fallback_opt_mvo", monkeypatch)["o"]["view"]["weights"]
    assert plain != forced


def test_the_comparison_is_not_vacuous():
    """짝 — 값 하나를 바꾸면 비교가 잡는다 · 관측 키만 다르면 잡지 않는다."""
    a = {"o": {"view": {"weights": {"005930": 40.0}, "flow": [1.0, 2.0]}}}
    assert _diff(_strip(a), _strip({"o": {"view": {"weights": {"005930": 40.01}, "flow": [1.0, 2.0]}}}))
    assert _diff(_strip(a), _strip({"o": {"view": {"weights": {"005930": 40.0}, "flow": [1.0, 2.0],
                                                   "fallbacks": [{"stage": "optimized"}]}}})) is None
