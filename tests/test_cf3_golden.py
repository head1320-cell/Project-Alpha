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

비교는 ★값 종류별 허용 오차★(`_close`, 2026-10-23 사용자 결정): 반올림해 낸 값은 인쇄된 마지막 자리 1단위까지, 반올림하지 않은 최적화 원값은
상대 1e-7(풀이기 수렴 정밀도 — SLSQP ftol 1e-9)까지. 호스트 CPU 가 바뀌면 numpy 의 OpenBLAS(DYNAMIC_ARCH)가 다른 커널을 골라
끝자리가 갈린다(`docs/HISTORY.md` 2026-10-23 — 이 호스트는 Prescott 커널, 골든은 AVX-512 커널에서 얼림). `CF3_GOLDEN_EXACT=1` 이면
정확히 같아야 한다 — 관측을 더하기 전·후에 같은 호스트에서 이 모드로 한 번씩 돌린다. 얼리기: `UPDATE_CF3_GOLDEN=1`.
"""
from __future__ import annotations

import json
import math
import os
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from scripts.golden_compare import _unit_of  # noqa: E402

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


#: 반올림하지 않은 원값의 상대 허용 — 실측 최대 2.6e-8(커널 Prescott ↔ SkylakeX), 풀이기 수렴 정밀도 수준.
RAW_REL = 1e-7
#: 유효숫자가 이만큼 이상이면 반올림하지 않은 원값으로 본다(반올림한 값은 짧게 인쇄된다).
RAW_DIGITS = 10
#: 차이를 이만큼까지 줄로 보인다(나머지는 수만).
SHOW = 20


def _close(a: float, b: float) -> bool:
    """값 종류별 허용 오차. ① 두 값을 최단 표기(`repr`)로 읽어 ★더 엄격한★ 마지막 자리 1단위 안이면 같다
    (`scripts/golden_compare.py::_unit_of` — 반올림 경계의 끝자리 하나) ② 둘 다 원값(유효숫자 10+)이면 상대 1e-7 까지 같다.
    우연히 짧은 원값(0.25)이 바뀌면 바뀐 쪽 표기가 길어져 ①이 엄격해지고 ②도 걸리지 않는다."""
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    da, db = Decimal(repr(a)), Decimal(repr(b))
    unit = _unit_of(da, db)
    if unit < 1 and abs(da - db) <= unit:
        return True
    raw = min(len(da.as_tuple().digits), len(db.as_tuple().digits)) >= RAW_DIGITS
    return raw and math.isclose(a, b, rel_tol=RAW_REL, abs_tol=1e-12)


def _diffs(a, b, path: str, out: list[str], exact: bool) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append(f"{path}: 키 {sorted(set(a) ^ set(b))}")
            return
        for k in a:
            _diffs(a[k], b[k], f"{path}.{k}", out, exact)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 길이 {len(a)} ≠ {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _diffs(x, y, f"{path}[{i}]", out, exact)
        return
    if isinstance(a, float) and isinstance(b, float) and not exact:
        if not _close(a, b):
            out.append(f"{path}: {a!r} ≠ {b!r}")
        return
    if a != b:
        out.append(f"{path}: {a!r} ≠ {b!r}")


def _diff(a, b, path="$") -> str | None:
    """차이 ★전부★ — 없으면 None. 첫 차이만 보이면 같은 원인의 다른 자리를 놓친다."""
    out: list[str] = []
    _diffs(a, b, path, out, os.environ.get("CF3_GOLDEN_EXACT") == "1")
    if not out:
        return None
    more = f"\n… 외 {len(out) - SHOW}곳" if len(out) > SHOW else ""
    return f"{len(out)}곳 다름:\n" + "\n".join(out[:SHOW]) + more


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
    """짝 — 값 하나를 바꾸면 비교가 잡는다 · 관측 키만 다르면 잡지 않는다.
    (2026-10-23: 반올림 값의 마지막 자리 1단위는 허용이 되어 예시를 40.01 → 40.02 로 — 1단위는 위 `_close` 짝들이 건다.)"""
    a = {"o": {"view": {"weights": {"005930": 40.0}, "flow": [1.0, 2.0]}}}
    assert _diff(_strip(a), _strip({"o": {"view": {"weights": {"005930": 40.02}, "flow": [1.0, 2.0]}}}))
    assert _diff(_strip(a), _strip({"o": {"view": {"weights": {"005930": 40.0}, "flow": [1.0, 2.0],
                                                   "fallbacks": [{"stage": "optimized"}]}}})) is None


# ── 비교 규칙(2026-10-23 · 사용자 결정: 값 종류별 허용 오차) ─────────────────────
# 호스트 CPU 가 바뀌면 numpy 의 OpenBLAS 가 다른 커널을 고른다(DYNAMIC_ARCH). 반올림한 값은 반올림 경계에서 마지막 자리 하나가,
# 최적화 원값은 풀이기 수렴 정밀도(SLSQP ftol 1e-9) 안에서 끝자리가 갈린다. 그보다 큰 변화는 잡아야 한다 — 아래 짝들.

def test_rounded_values_may_differ_by_one_last_place_but_not_two():
    assert _close(40.1493, 40.1492)
    assert not _close(40.1494, 40.1492)
    assert not _close(40.15, 40.1492)          # 짧은 쪽이 더 굵어도 ★더 엄격한 쪽★ 자리로 잰다


def test_raw_optimizer_values_allow_solver_noise_but_not_a_real_change():
    assert _close(0.4218052769699755, 0.4218052785731531)        # 실측 3.8e-9
    assert _close(0.11375430662, 0.11375430368)                  # 실측 최대 2.6e-8
    w = 0.4218052785731531
    assert not _close(w * (1 + 1e-6), w)
    assert not _close(w * (1 + 2e-7), w)


def test_a_short_raw_value_does_not_borrow_a_coarse_last_place():
    """0.25 는 반올림한 값이 아니라 우연히 짧은 원값일 수 있다 — 0.255 는 다르다."""
    assert not _close(0.25, 0.255)
    assert not _close(0.25, 0.2500003)         # 바뀐 쪽 표기의 마지막 자리로 3단위 · 원값으로 보면 상대 1.2e-6


def test_a_rounded_large_value_gets_no_relative_slack():
    """짧게 인쇄된(반올림한) 큰 값은 상대 허용을 받지 않는다 — 마지막 자리 2단위면 다르다."""
    assert not _close(98765.43, 98765.4302)
    assert _close(98765.43, 98765.4301)


def test_special_values():
    nan = float("nan")
    assert _close(nan, nan)
    assert not _close(nan, 1.0) and not _close(1.0, nan)
    assert _close(float("inf"), float("inf"))
    assert not _close(float("inf"), 1e308)
    assert not _close(1e20, 1.1e20)


def test_exact_mode_still_demands_bit_equality(monkeypatch):
    monkeypatch.setenv("CF3_GOLDEN_EXACT", "1")
    assert _diff({"x": 40.1493}, {"x": 40.1492})
    monkeypatch.delenv("CF3_GOLDEN_EXACT")
    assert _diff({"x": 40.1493}, {"x": 40.1492}) is None


def test_every_difference_is_reported_not_just_the_first():
    a = {"a": 1.0, "b": [1, 2, 3], "c": {"d": "x"}}
    b = {"a": 2.0, "b": [1, 9, 3], "c": {"d": "y"}}
    d = _diff(a, b)
    assert d and "$.a" in d and "$.b[1]" in d and "$.c.d" in d and "3곳" in d


def test_the_rule_catches_real_changes_on_the_frozen_outputs(frozen):
    """골든 위에서의 변이 — 원값 비중을 상대 1e-6 흔들면 · 반올림 값을 마지막 자리 2 바꾸면 잡힌다(짝: 1이면 통과)."""
    import copy
    base = frozen["scores_min_var"]
    bumped = copy.deepcopy(base)
    bumped["weights"][0] *= 1 + 1e-6
    assert _diff(_strip(bumped), _strip(base))
    rc = frozen["min_cvar"]["k"]["view"]["risk_contribution_optimized"]["pct"]
    for step, caught in ((0.0002, True), (0.0001, False)):
        m = copy.deepcopy(frozen["min_cvar"])
        m["k"]["view"]["risk_contribution_optimized"]["pct"]["005930"] = round(rc["005930"] + step, 4)
        assert bool(_diff(_strip(m), _strip(frozen["min_cvar"]))) is caught, step
