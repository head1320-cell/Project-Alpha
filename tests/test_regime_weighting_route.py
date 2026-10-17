"""`regime_weighting` 배선 + PIT 3필드 — ★기본값은 바이트 동일★ (MS1-a 커밋 4)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.9 · §1.10.0 I5·I6

이 파일이 고정하는 것 셋:

1. ★`regime_weighting` 을 안 보내면 응답이 **현행과 바이트 동일**★ — 새 경로가
   기존 화면을 건드리지 않는다는 것이 이 슬라이스의 전제다.
2. ★`"probabilistic"` 이면 **결정이 실제로 바뀐다**★ — 응답만 바뀌고 비중이 그대로면
   Level 4 로 아무것도 잰 것이 없다. `bl` 에서 잰다(공분산 전용 모델은 μ 효과를
   못 보므로 과소평가한다).
3. ★PIT 는 3필드이고 단일 불리언이 없다★ (I6).

`test_conditional_wiring.py` 의 fixture 전략을 그대로 쓴다 — 이 컨테이너에는
`daily_prices` 가 없어 mock 수익률이 무상관·등분산이 되고 그러면 λ→1.0 이라
스케일 불변 모델의 비중이 국면과 무관하게 같아진다. 배선을 우회하는 것이 아니라
**배선이 구분할 수 있는 데이터**를 경계에서 준다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import json  # noqa: E402
from datetime import date  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

TICKERS = ["005930", "000660", "035420", "051910"]
REG_A, REG_B = "Goldilocks", "Stagflation"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _recent_months(n: int = 36) -> list[str]:
    y, m = date.today().year, date.today().month
    out = []
    for k in range(n - 1, -1, -1):
        mm = m - k
        out.append(f"{y + (mm - 1) // 12:04d}-{(mm - 1) % 12 + 1:02d}")
    return out


def _alternating_path(last: str = REG_A, n: int = 36) -> list[dict]:
    """월이 번갈아 두 국면인 경로 — 전이가 실제로 세어진다."""
    other = REG_B if last == REG_A else REG_A
    ms = _recent_months(n)
    return [{"t": mo, "growth": 0.1, "inflation": 0.1,
             "regime": last if (len(ms) - 1 - i) % 2 == 0 else other}
            for i, mo in enumerate(ms)]


def _regime_split_returns(path_points, seed: int = 5) -> pd.DataFrame:
    """국면별로 다른 상관구조·평균 — A 는 공통인자 강함+양의 드리프트, B 는 반대."""
    rng = np.random.default_rng(seed)
    by_month = {p["t"]: p["regime"] for p in path_points}
    idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=len(by_month) * 21)
    n = len(TICKERS)
    beta = np.linspace(1.2, 0.6, n)
    rows = []
    for ts in idx:
        if by_month.get(ts.strftime("%Y-%m")) == REG_A:
            f = rng.normal(0.0006, 0.014)
            rows.append(f * beta + rng.normal(0.0, 0.004, n))
        else:
            rows.append(rng.normal(-0.0004, 0.013, n))
    return pd.DataFrame(np.array(rows), index=idx, columns=list(TICKERS))


@pytest.fixture
def wired(monkeypatch):
    def install(path_points, *, returns=None):
        snap = {"as_of": "2026-08-01", "capability_level": "L1",
                "capability_reason": None, "regime_path": path_points}
        monkeypatch.setattr("src.data.regime_snapshots.get_snapshot",
                            lambda sid: dict(snap))
        df = returns if returns is not None else _regime_split_returns(path_points)
        cov = {"start": str(df.index.min().date()), "end": str(df.index.max().date()),
               "n_obs": len(df), "as_of": None, "source": "test"}
        monkeypatch.setattr("src.api.allocation_routes._load_clean_returns",
                            lambda *a, **k: (df, None, [], cov))
        return df
    return install


def _body(**kw):
    b = {"tickers": list(TICKERS), "lookback_days": 500, "mc_paths": 100,
         "record_run": False, "conditional": True, "model": "bl",
         "mes_id": "rgs_x"}
    b.update(kw)
    return b


def _post(client, **kw):
    r = client.post("/api/v1/allocation/analyze", json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def _weights(js) -> dict:
    return js["weights"]["optimized"]


# ══════════════════════════════════════════════════════════════════════════
# 1) 기본값은 현행 그대로
# ══════════════════════════════════════════════════════════════════════════
def test_default_is_hard_and_response_is_unchanged(client, wired):
    """★`regime_weighting` 을 안 보내면 명시적 `"hard"` 와 **완전히 같은 응답**★"""
    path = _alternating_path()
    wired(path)
    absent = _post(client)
    wired(path)
    explicit = _post(client, regime_weighting="hard")

    # run_id 등 실행마다 달라지는 필드를 빼고 비교한다.
    for js in (absent, explicit):
        js.pop("run_id", None)
        js.pop("generated_at", None)
    assert (json.dumps(absent, sort_keys=True, default=str)
            == json.dumps(explicit, sort_keys=True, default=str))


def test_hard_path_declares_legacy_confidence_model(client, wired):
    """하드 경로는 legacy 스칼라 신뢰도를 그대로 쓴다 — 회귀 0."""
    wired(_alternating_path())
    js = _post(client, regime_weighting="hard")
    cond = js["conditional"]
    assert cond["available"] is True
    assert cond["regime_weighting"] == "hard"
    assert cond["confidence_model"]["kind"] == "legacy_scalar"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★확률 혼합은 결정을 바꾼다★ (Level 4)
# ══════════════════════════════════════════════════════════════════════════
def test_probabilistic_changes_the_weights(client, wired):
    """★핵심★ 하드와 확률 혼합의 **최적 가중치가 다르다**.

    응답만 바뀌고 비중이 그대로면 이 슬라이스는 아무것도 하지 않은 것이다.
    `bl` 에서 잰다 — 공분산 전용 모델은 μ 효과를 못 보므로 과소평가한다.
    """
    path = _alternating_path()
    wired(path)
    hard = _weights(_post(client, regime_weighting="hard"))
    wired(path)
    prob = _weights(_post(client, regime_weighting="probabilistic"))

    l1 = sum(abs(hard[t] - prob.get(t, 0.0)) for t in hard)
    assert l1 > 1e-6, f"결정이 바뀌지 않았다: {hard} vs {prob}"


def test_probabilistic_block_carries_the_contract_fields(client, wired):
    wired(_alternating_path())
    cond = _post(client, regime_weighting="probabilistic")["conditional"]

    assert cond["available"] is True
    assert cond["regime_weighting"] == "probabilistic"
    assert cond["h_hold"] == 1                       # rebalance="M" 기본값
    assert len(cond["pi_path"]) == 1
    assert abs(sum(cond["pi_path"][0].values()) - 1.0) < 1e-6
    assert set(cond["pi_bar"]) == set(cond["pi_path"][0])
    assert cond["A_contribution_pct"] is not None
    assert cond["sharpness"] is not None
    assert cond["confidence_model"]["kind"] == "decomposed_omega"
    assert cond["confidence_model"]["residual_risk"] == "unmeasured"
    # ★사후평균 전파 경로를 쓴다★ — π 와 P 가 같은 사슬에서 나와야 국면 간 항이
    # 공분산이 된다. 표집 예측(E[P^j])은 사후평균 행렬((E[P])^j)과 Jensen 격차만큼
    # 어긋나므로 Σ̄ 계산에 쓸 수 없고, 그 불확실성은 아래 `sampled_forecast` 가 따로 낸다.
    assert cond["probability_source"]["source"] == "k_step_forecast_mean"
    assert cond["probability_source"]["usage"] == "portfolio"
    assert cond["probability_source"]["sampled_forecast"]["ci90"] is not None
    assert "전파되지 않" in cond["probability_source"]["uncertainty_note"]


def test_quarterly_rebalance_lengthens_the_horizon(client, wired):
    """`rebalance="Q"` 면 `h_hold = 3` 이고 π 경로가 3단계다.

    ★`h_hold` 는 리밸런싱 주기에서 파생된다★ — 자유 입력이 아니고, 기대
    지속기간(2.5~5.0개월)을 흘려 넣는 자리도 아니다.
    """
    wired(_alternating_path())
    cond = _post(client, regime_weighting="probabilistic",
                 rebalance="Q")["conditional"]
    assert cond["h_hold"] == 3
    assert len(cond["pi_path"]) == 3


def test_longer_horizon_lowers_sharpness(client, wired):
    """지평이 길수록 국면 분포가 퍼져 날카로움이 떨어진다 — 방향을 고정한다."""
    path = _alternating_path()
    wired(path)
    m = _post(client, regime_weighting="probabilistic", rebalance="M")["conditional"]
    wired(path)
    q = _post(client, regime_weighting="probabilistic", rebalance="Q")["conditional"]
    assert q["sharpness"] < m["sharpness"] + 1e-9


# ══════════════════════════════════════════════════════════════════════════
# 3) ★I6★ PIT 는 3필드 · 단일 불리언 금지
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("weighting", ["hard", "probabilistic"])
def test_pit_status_is_three_fields(client, wired, weighting):
    wired(_alternating_path())
    cond = _post(client, regime_weighting=weighting)["conditional"]
    pit = cond["pit"]
    assert set(pit) >= {"look_ahead_free", "publication_lag", "revision_bias"}
    assert isinstance(pit["look_ahead_free"], bool)
    # ★ECOS 는 빈티지를 주지 않는다 — 영구 라벨★
    assert pit["revision_bias"] == "unmanaged"
    assert pit["publication_lag"] in ("declared", "unspecified")


def test_no_single_pit_boolean_anywhere_in_response(client, wired):
    """★I6★ `pit_verified` 류 단일 플래그가 응답 어디에도 없다.

    만드는 순간 revision bias 가 그 안에 숨고 "PIT 통과" 가 거짓말이 된다.
    """
    wired(_alternating_path())
    blob = json.dumps(_post(client, regime_weighting="probabilistic"), default=str)
    for banned in ("pit_verified", "pit_ok", "is_pit", "pitVerified"):
        assert banned not in blob, f"단일 PIT 플래그가 생겼다: {banned}"


def test_backtest_mode_is_unavailable_with_a_reason(client, wired):
    """MS1-b 는 아직 열리지 않았다 — 라이브 수치를 백테스트인 척 쓰지 못하게 한다."""
    wired(_alternating_path())
    cond = _post(client, regime_weighting="probabilistic",
                 regime_mode="backtest")["conditional"]
    assert cond["available"] is False
    assert cond["mode"] == "backtest"
    assert "정책" in (cond["reason"] or "") or "빈티지" in (cond["reason"] or "")


# ══════════════════════════════════════════════════════════════════════════
# 4) 진단 확률은 함께 실리되 배분에는 닿지 않는다 (I5)
# ══════════════════════════════════════════════════════════════════════════
def test_smoothed_never_appears_in_the_conditional_block(client, wired):
    wired(_alternating_path())
    cond = _post(client, regime_weighting="probabilistic")["conditional"]
    assert "smoothed" not in json.dumps(cond, default=str)


def test_unavailable_forecast_falls_back_and_says_so(client, wired, monkeypatch):
    """예측을 못 만들면 하드로 떨어지되 **조용히 떨어지지 않는다**."""
    wired(_alternating_path())

    def boom(*a, **k):
        raise ValueError("테스트: 예측 불가")
    monkeypatch.setattr("src.engine.regime_probability.from_k_step_forecast", boom)

    cond = _post(client, regime_weighting="probabilistic")["conditional"]
    assert cond["regime_weighting"] == "hard"
    assert "예측" in (cond["mixture_note"] or "") or cond["mixture_note"]
