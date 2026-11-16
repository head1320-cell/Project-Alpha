"""M3 골든 — ★`hard` · `probabilistic` 의 조건부 스택은 'GMM 시작 분포'를 더해도 한 자리도 바뀌지 않는다★
==============================================================================
계획 `docs/superpowers/plans/2026-11-16-emeans-gmm-strategy.md` §3.5 — "★`hard` · `probabilistic` 의 응답은 한 바이트도 바뀌지 않는다★(고정 입력의 골든)".

`allocation_pipeline._conditional_stack` 은 `/analyze` · `/optimize` · `/rebalance-decision` · 캔버스 최적화 노드가 조건부 μ/Σ 를 얻는
단일 출처다 — 그 출력(조건부 추정 · 경로 · Σ 대체 · 조건부 뷰 · 신뢰도 · 메타)이 같으면 그 아래(비중 · 위험 · 해설)는 같은 함수의 같은 입력이다.
M3 가 이 함수에 'GMM 시작 분포' 분기를 더하기 **전**(HEAD `65b39bb` 의 깨끗한 worktree)에 `tests/golden/regime_weighting_stack.json` 에 얼렸다.

★입력은 날짜에 기대지 않는다★ 국면 경로 60개월(2020-11 ~ 2025-10)과 일별 수익률을 이 파일이 고정 씨앗으로 짓는다(6자리 반올림 —
`test_cf3_golden` 과 같은 까닭). 비교는 `test_cf3_golden` 의 값 종류별 허용 오차(`_diffs` — 인쇄된 마지막 자리 1단위 · 원값 상대 1e-7)이고,
`REGIME_WEIGHTING_GOLDEN_EXACT=1` 이면 정확히 같아야 한다(같은 호스트에서 고치기 전 · 후 한 번씩). 얼리기: `UPDATE_REGIME_WEIGHTING_GOLDEN=1`.

★백테스트의 기존 팔(B0 · B1 · N)도 같다★ — M3 가 `allocation_backtest` 에 팔 G 를 더하기 전에 84개월 패널의 워크포워드
(리밸런싱 · 국면 감사 · 요약)를 `tests/golden/regime_arms_walk_forward.json` 에 얼렸다. 얼리기: `UPDATE_REGIME_ARMS_GOLDEN=1`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from tests.test_cf3_golden import SHOW, _diffs  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "regime_weighting_stack.json"
TICKERS = ["005930", "000660", "035420", "051910"]
UPDATE = os.environ.get("UPDATE_REGIME_WEIGHTING_GOLDEN") == "1"
EXACT = os.environ.get("REGIME_WEIGHTING_GOLDEN_EXACT") == "1"


def _months(first: tuple[int, int] = (2020, 11), n: int = 60) -> list[str]:
    y, m = first
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out


def _path(n: int = 60, first: tuple[int, int] = (2020, 11)) -> list[dict]:
    """n개월(기본 60 · 2020-11 부터) · 축 값은 고정 씨앗(6자리) · 국면은 그 사분면 — 전이가 실제로 세어지는 경로."""
    from src.engine.regime_axes import quadrant

    rng = np.random.default_rng(20261116)
    pts = []
    for mo in _months(first, n):
        g, i = round(float(rng.normal(0.0, 1.0)), 6), round(float(rng.normal(0.0, 1.0)), 6)
        pts.append({"t": mo, "growth": g, "inflation": i, "regime": quadrant(g, i)})
    return pts


def _returns(path: list[dict]) -> pd.DataFrame:
    """국면마다 다른 평균 · 상관(국면 넷) — 일별 · 영업일 · 6자리 반올림 · 날짜 고정."""
    rng = np.random.default_rng(5)
    regime_of = {p["t"]: p["regime"] for p in path}
    idx = pd.bdate_range(f"{path[0]['t']}-01", pd.Period(path[-1]["t"], "M").end_time.normalize())
    beta = np.linspace(1.2, 0.6, len(TICKERS))
    drift = {"Goldilocks": 0.0006, "Reflation": 0.0003, "Stagflation": -0.0005, "Disinflation": -0.0001}
    rows = []
    for ts in idx:
        r = regime_of[ts.strftime("%Y-%m")]
        f = rng.normal(drift[r], 0.014 if r in ("Goldilocks", "Stagflation") else 0.009)
        rows.append(f * beta + rng.normal(0.0, 0.004, len(TICKERS)))
    return pd.DataFrame(np.round(np.array(rows), 6), index=idx, columns=list(TICKERS))


def _jsonable(x):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    return x


#: 경우 — (가중 방식, 리밸런싱 주기, 모형, 덧댈 것). 전이 예측의 실패 경우는 하드로 떨어지며 남기는 사유 문장까지 얼린다.
def _boom(*a, **k):
    raise ValueError("골든: 예측 불가")


CASES = {
    "hard_M_bl": ("hard", "M", "bl", ()),
    "hard_Q_bl": ("hard", "Q", "bl", ()),
    "probabilistic_M_bl": ("probabilistic", "M", "bl", ()),
    "probabilistic_Q_bl": ("probabilistic", "Q", "bl", ()),
    "probabilistic_M_min_var": ("probabilistic", "M", "min_var", ()),
    "probabilistic_M_forecast_fails": ("probabilistic", "M", "bl",
                                       (("src.engine.regime_probability.from_k_step_forecast", _boom),)),
}


def _stack(name: str, monkeypatch) -> dict:
    from src.api import allocation_pipeline as ap

    weighting, rebalance, model, patches = CASES[name]
    path = _path()
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot",
                        lambda sid: {"as_of": "2025-10-31", "regime_path": [dict(p) for p in path]})
    for target, value in patches:
        monkeypatch.setattr(target, value)
    req = SimpleNamespace(mes_id="rgs_golden", regime_snapshot_id=None, regime_weighting=weighting,
                          regime_mode="live", rebalance=rebalance, model=model)
    return _jsonable(ap._conditional_stack(req, _returns(path)))


@pytest.fixture(scope="module")
def frozen() -> dict:
    if UPDATE:
        return {}
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(CASES))
def test_the_stack_equals_the_frozen_one(name, monkeypatch, frozen):
    got = _stack(name, monkeypatch)
    if UPDATE:
        data = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
        data[name] = got
        GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert name in frozen, f"골든에 {name} 이 없습니다 — UPDATE_REGIME_WEIGHTING_GOLDEN=1 로 먼저 얼립니다."
    out: list[str] = []
    _diffs(got, frozen[name], "$", out, EXACT)
    more = f"\n… 외 {len(out) - SHOW}곳" if len(out) > SHOW else ""
    assert not out, f"{len(out)}곳 다름:\n" + "\n".join(out[:SHOW]) + more


def test_the_cases_are_not_vacuous():
    """공허 배제 — 경로에 네 국면과 전이가 있고, 확률 경우는 실제로 혼합했고, 실패 경우는 실제로 떨어졌다(얼린 값 기준)."""
    path = _path()
    assert {p["regime"] for p in path} == {"Goldilocks", "Reflation", "Stagflation", "Disinflation"}
    assert sum(a["regime"] != b["regime"] for a, b in zip(path, path[1:])) >= 20
    if UPDATE:
        pytest.skip("얼리는 중")
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert data["hard_M_bl"]["meta"]["regime_weighting"] == "hard"
    assert data["probabilistic_M_bl"]["meta"]["regime_weighting"] == "probabilistic"
    assert data["probabilistic_Q_bl"]["meta"]["h_hold"] == 3 and len(data["probabilistic_Q_bl"]["meta"]["pi_path"]) == 3
    assert data["probabilistic_M_bl"]["cond"]["available"] is True and data["probabilistic_M_bl"]["extra_views"]
    assert data["probabilistic_M_min_var"]["extra_views"] is None, "공분산 전용 모형은 뷰를 받지 않는다"
    assert data["probabilistic_M_forecast_fails"]["meta"]["regime_weighting"] == "hard"
    assert "골든: 예측 불가" in data["probabilistic_M_forecast_fails"]["meta"]["mixture_note"]


# ══ 백테스트의 기존 팔 — B0 · B1 · N (계획 §3.5 "다른 팔 골든 불변") ═══════════════════

GOLDEN_ARMS = Path(__file__).parent / "golden" / "regime_arms_walk_forward.json"
UPDATE_ARMS = os.environ.get("UPDATE_REGIME_ARMS_GOLDEN") == "1"

#: 팔 — 국면 설정(없으면 B0) · 리밸런싱 주기.
ARMS = {
    "B0_M": (None, "M"),
    "B1_M": ({"weighting": "hard"}, "M"),
    "N_M": ({"weighting": "probabilistic"}, "M"),
    "N_Q": ({"weighting": "probabilistic", "h_hold": 3}, "Q"),
    "N_M_legacy": ({"weighting": "probabilistic", "confidence": "legacy"}, "M"),
}
ARM_KEYS = ("rebalances", "n_rebalances", "regime_audit", "summary", "turnover_avg_pct")


def arm_panel() -> tuple[list[dict], pd.DataFrame]:
    """84개월(2018-11 ~ 2025-10) — 팔 G 의 시험도 같은 패널을 쓴다(뒤쪽 달에서 점수가 선다)."""
    path = _path(84, (2018, 11))
    return path, _returns(path)


def _walk(name: str) -> dict:
    from src.engine.allocation_backtest import walk_forward

    regime, rebalance = ARMS[name]
    path, df = arm_panel()
    out = walk_forward(list(df.columns), df.to_numpy(), list(df.index), model="bl", rebalance=rebalance,
                       cost_bps=10.0, regime=({"points": [dict(p) for p in path], **regime} if regime else None))
    assert not out.get("error"), out.get("message")
    return _jsonable({k: out[k] for k in ARM_KEYS})


@pytest.fixture(scope="module")
def frozen_arms() -> dict:
    if UPDATE_ARMS:
        return {}
    return json.loads(GOLDEN_ARMS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(ARMS))
def test_the_existing_arms_equal_the_frozen_ones(name, frozen_arms):
    got = _walk(name)
    if UPDATE_ARMS:
        data = json.loads(GOLDEN_ARMS.read_text(encoding="utf-8")) if GOLDEN_ARMS.exists() else {}
        data[name] = got
        GOLDEN_ARMS.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    assert name in frozen_arms, f"골든에 {name} 이 없습니다 — UPDATE_REGIME_ARMS_GOLDEN=1 로 먼저 얼립니다."
    out: list[str] = []
    _diffs(got, frozen_arms[name], "$", out, EXACT)
    more = f"\n… 외 {len(out) - SHOW}곳" if len(out) > SHOW else ""
    assert not out, f"{len(out)}곳 다름:\n" + "\n".join(out[:SHOW]) + more


def test_the_arm_cases_are_not_vacuous():
    if UPDATE_ARMS:
        pytest.skip("얼리는 중")
    data = json.loads(GOLDEN_ARMS.read_text(encoding="utf-8"))
    assert [data[k]["regime_audit"]["arm"] for k in ARMS] == ["B0", "B1", "N", "N", "N"]
    for k in ("B1_M", "N_M", "N_Q"):
        assert data[k]["regime_audit"]["s_override_used"] > 10, k
    assert data["N_M"]["rebalances"] != data["B1_M"]["rebalances"], "확률 혼합이 하드와 같으면 골든이 아무것도 가르지 않는다"
