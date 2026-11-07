"""국면조건부 μ/Σ 가 실제로 optimizer 에 닿는다 (P2.5 커밋 ②)

감사가 증명한 결함은 "지었는데 안 배선됨" 이었다 — M2 가 이은 `mes_id` 는
`capability_level` 을 **스탬프만** 하고, 국면 확률·축 점수는 μ 나 Σ 에 한 번도
닿지 않았다. 그러므로 이 파일의 첫 테스트는 응답 형태가 아니라 **비중이 실제로
달라지는가** 다.

★데이터에 대해 배운 것 (이 파일이 상관 있는 합성 수익률을 주입하는 이유)★
------------------------------------------------------------------------------
이 컨테이너에는 `daily_prices` 가 없어 `/analyze` 가 mock 폴백을 탄다. 그 mock 은
**종목별로 독립 생성**되므로 수익률이 무상관·등분산에 가깝고, 그러면 Ledoit-Wolf 의
목표(스케일 단위행렬)가 **정확히 맞아** λ→1.0 이 된다. Σ 가 상수배 단위행렬이 되면
스케일 불변 모델의 비중은 국면을 바꿔도 **수학적으로 같을 수밖에 없다.**

즉 mock 위에서 "국면을 바꿔도 비중이 같다" 는 배선 결함의 증거가 아니다. 그것을
모르고 첫 프로브를 짰다가 정확히 그 함정에 빠졌다(λ=1.0 · 신뢰도 0.0 · 두 국면의
비중이 소수점까지 동일). 그래서 여기서는 `_load_clean_returns` 를 **경계에서**
갈아끼워 국면별로 다른 공분산·평균을 심는다 — 배선을 우회하는 것이 아니라, 배선이
구분할 수 있는 데이터를 준다.

그리고 그 mock 상황 자체는 결함이 아니라 보고 대상이므로 `degenerate` 플래그로
응답에 남는다 — 마지막 테스트가 그것을 고정한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

TICKERS = ["005930", "000660", "035420", "051910"]
# ★자산 수가 하한을 정한다★ 기본 하한은 자산당 3행이므로 4자산이면 12행인데
# 한 달은 15~23영업일이라 **한 달짜리 국면도 통과한다.** 표본 부족을 재려면
# 자산을 늘려 하한을 관측보다 위로 올려야 한다(8자산 → 24행 > 한 달).
TICKERS_8 = TICKERS + ["005380", "068270", "005490", "012330"]
REG_A, REG_B = "Goldilocks", "Stagflation"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _body(**kw):
    b = {"tickers": list(TICKERS), "lookback_days": 500, "mc_paths": 100,
         "record_run": False}
    b.update(kw)
    return b


def _recent_months(n: int = 24) -> list[str]:
    y, m = date.today().year, date.today().month
    out = []
    for k in range(n - 1, -1, -1):
        mm = m - k
        out.append(f"{y + (mm - 1) // 12:04d}-{(mm - 1) % 12 + 1:02d}")
    return out


def _alternating_path(last: str = REG_A, n: int = 24) -> list[dict]:
    """월이 번갈아 두 국면인 경로. 마지막 달이 **현재 국면**이다."""
    other = REG_B if last == REG_A else REG_A
    ms = _recent_months(n)
    return [{"t": mo, "growth": 0.1, "inflation": 0.1,
             "regime": last if (len(ms) - 1 - i) % 2 == 0 else other}
            for i, mo in enumerate(ms)]


def _regime_split_returns(path_points: list[dict], seed: int = 5,
                          tickers: list[str] | None = None) -> pd.DataFrame:
    """국면별로 **다른 상관구조·평균**을 심은 일별 수익률.

    A 국면: 공통인자가 강하다(상관↑) + 양의 드리프트.
    B 국면: 특이위험이 지배한다(상관↓) + 음의 드리프트.
    """
    rng = np.random.default_rng(seed)
    cols = list(tickers or TICKERS)
    by_month = {p["t"]: p["regime"] for p in path_points}
    idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=len(by_month) * 21)
    n = len(cols)
    beta = np.linspace(1.2, 0.6, n)
    rows = []
    for ts in idx:
        reg = by_month.get(ts.strftime("%Y-%m"))
        if reg == REG_A:
            f = rng.normal(0.0006, 0.014)
            rows.append(f * beta + rng.normal(0.0, 0.004, n))
        else:
            rows.append(rng.normal(-0.0004, 0.013, n))
    return pd.DataFrame(np.array(rows), index=idx, columns=cols)


@pytest.fixture
def wired(monkeypatch):
    """스냅샷의 국면 경로 + 그 경로에 맞춘 수익률을 함께 갈아끼운다."""
    def install(path_points, *, returns=None, store_path=True):
        snap = {"as_of": "2026-08-01", "capability_level": "L1",
                "capability_reason": None,
                "regime_path": path_points if store_path else None}
        monkeypatch.setattr("src.data.regime_snapshots.get_snapshot",
                            lambda sid: dict(snap))
        df = returns if returns is not None else _regime_split_returns(path_points)
        cov = {"start": str(df.index.min().date()), "end": str(df.index.max().date()),
               "n_obs": len(df), "as_of": None, "source": "test"}
        monkeypatch.setattr("src.api.allocation_routes._load_clean_returns",
                            lambda *a, **k: (df, None, [], cov))
        return df
    return install


def _weights(resp) -> dict:
    return resp.json()["weights"]["optimized"]


# ── 1. ★국면을 바꾸면 비중이 실제로 달라진다★ ───────────────────────────────
def test_changing_the_regime_actually_changes_the_weights(client, wired):
    """이것이 빨갛지 않으면 배선은 M2 처럼 도장만 찍는 것이다."""
    out = {}
    for last in (REG_A, REG_B):
        path = _alternating_path(last)
        wired(path)
        r = client.post("/api/v1/allocation/analyze",
                        json=_body(model="bl", conditional=True, mes_id="rgs_x"))
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["conditional"]["available"] is True, b["conditional"]["reason"]
        assert b["conditional"]["regime"] == last
        out[last] = _weights(r)

    assert out[REG_A] != out[REG_B], (
        "국면을 바꿨는데 비중이 소수점까지 같다 — 조건부가 optimizer 에 닿지 않았거나 "
        "표본이 국면별 구조를 담고 있지 않다(그 경우 degenerate 가 True 여야 한다)")


def test_the_regime_reaches_sigma_even_for_covariance_only_models(client, wired):
    """μ 를 안 받는 모델도 Σ 는 조건부로 바뀐다 — 그리고 응답이 그렇게 말한다."""
    out = {}
    for last in (REG_A, REG_B):
        wired(_alternating_path(last))
        r = client.post("/api/v1/allocation/analyze",
                        json=_body(model="min_var", conditional=True, mes_id="rgs_x"))
        assert r.status_code == 200, r.text
        c = r.json()["conditional"]
        assert c["applied_to"]["sigma"] is True
        # 공분산 전용 모델에는 μ 를 몰래 태우지 않는다.
        assert c["applied_to"]["mu_as_views"] == 0
        assert "공분산 전용" in c["note"]
        out[last] = _weights(r)
    assert out[REG_A] != out[REG_B]


# ── 2. ★짝★ 조건부를 끄면 응답이 이전과 완전히 같다 ─────────────────────────
def test_turning_it_off_leaves_the_response_untouched(client, wired):
    """★1번과 반드시 함께 건다★ '달라진다' 가 잡음이 아님은 이 짝이 증명한다."""
    path = _alternating_path(REG_A)

    wired(path)
    off = client.post("/api/v1/allocation/analyze", json=_body(model="bl")).json()
    wired(path)
    off2 = client.post("/api/v1/allocation/analyze",
                       json=_body(model="bl", conditional=False)).json()

    assert off == off2
    # ★키조차 늘지 않는다★ 기존 소비자가 보는 응답이 바이트 단위로 같아야 한다.
    assert "conditional" not in off
    assert "target_range" not in off

    wired(path)
    on = client.post("/api/v1/allocation/analyze",
                     json=_body(model="bl", conditional=True, mes_id="rgs_x")).json()
    assert "conditional" in on and "target_range" in on
    assert on["weights"]["optimized"] != off["weights"]["optimized"]


# ── 3. ★표본이 얇으면 숫자가 아니라 사유★ ───────────────────────────────────
def test_a_thin_regime_answers_with_a_reason_and_the_counts(client, wired):
    path = _alternating_path(REG_A)
    # 마지막 한 달만 희귀 국면 — 8자산이면 하한 24행이라 한 달(~15영업일)로는 못 넘는다.
    path[-1] = dict(path[-1], regime="Reflation")
    wired(path, returns=_regime_split_returns(path, tickers=TICKERS_8))

    r = client.post("/api/v1/allocation/analyze",
                    json=_body(model="bl", conditional=True, mes_id="rgs_x",
                               tickers=list(TICKERS_8)))
    assert r.status_code == 200, r.text
    c = r.json()["conditional"]

    assert c["available"] is False
    assert c["regime"] == "Reflation"
    assert c["reason"]
    # ★몇 개였는지 안 적으면 왜 막혔는지 되짚을 수 없다★
    assert c["n_obs_by_regime"]["Reflation"] == c["n_obs"] > 0
    assert c["min_obs_required"] > c["n_obs"]


# ── 4. ★조용한 폴백 금지★ 무조건부로 떨어지면 응답이 말한다 ─────────────────
def test_falling_back_to_unconditional_is_announced_not_silent(client, wired):
    path = _alternating_path(REG_A)
    path[-1] = dict(path[-1], regime="Reflation")
    df = _regime_split_returns(path, tickers=TICKERS_8)
    wired(path, returns=df)

    body = _body(model="bl", tickers=list(TICKERS_8))
    on = client.post("/api/v1/allocation/analyze",
                     json={**body, "conditional": True, "mes_id": "rgs_x"}).json()
    wired(path, returns=df)
    off = client.post("/api/v1/allocation/analyze", json=body).json()

    c = on["conditional"]
    assert c["available"] is False
    assert c["applied_to"] == {"sigma": False, "mu_as_views": 0}
    assert "무조건부" in c["note"]
    # 사유만 다르고 숫자는 무조건부와 같아야 한다 — 반쯤 적용된 상태가 없다.
    assert on["weights"]["optimized"] == off["weights"]["optimized"]


def test_a_missing_path_is_reported_rather_than_guessed(client, wired, monkeypatch):
    """경로를 만들 수도 없고 굳혀 둔 것도 없으면 사유를 적는다(빈 경로를 지어내지 않는다)."""
    wired(_alternating_path(REG_A), store_path=False)

    class _Boom:
        def __init__(self): raise RuntimeError("수집 불가")
    monkeypatch.setattr("src.engine.regime_analyzer.RegimeAnalyzer", _Boom)

    c = client.post("/api/v1/allocation/analyze",
                    json=_body(model="bl", conditional=True,
                               mes_id="rgs_x")).json()["conditional"]
    assert c["available"] is False
    assert c["path_source"] is None
    assert c["reason"] and "무조건부" in c["reason"]


# ── 5. PIT 라벨 — 저장된 경로 우선, 재계산이면 숨기지 않는다 ─────────────────
def test_a_stored_path_is_preferred_and_labelled_as_such(client, wired):
    wired(_alternating_path(REG_A))
    c = client.post("/api/v1/allocation/analyze",
                    json=_body(model="bl", conditional=True,
                               mes_id="rgs_x")).json()["conditional"]
    assert c["path_source"] == "mes"
    # 굳혀 둔 경로에는 "현재 데이터로 다시 계산했다" 라벨이 붙지 않는다.
    assert c["path_note"] is None


def test_a_recomputed_path_says_so(client, wired, monkeypatch):
    """★Brief §16 이 금지한 것을 하되 숨기지 않는다★"""
    path = _alternating_path(REG_A)
    wired(path, store_path=False)

    class _Collector:
        def collect_all(self, use_cache=True):
            return type("S", (), {"series": {"x": object()}})()

    class _Analyzer:
        def __init__(self): self.collector = _Collector()
    monkeypatch.setattr("src.engine.regime_analyzer.RegimeAnalyzer", _Analyzer)
    monkeypatch.setattr("src.engine.regime_transitions.regime_path",
                        lambda series, market, months=60: {"points": path})

    c = client.post("/api/v1/allocation/analyze",
                    json=_body(model="bl", conditional=True,
                               mes_id="rgs_x")).json()["conditional"]
    assert c["available"] is True
    assert c["path_source"] == "recomputed"
    assert c["path_note"] and "현재 데이터로" in c["path_note"]


# ── 6. 목표 구간 — 모델이 하나면 구간을 지어내지 않는다 ─────────────────────
def test_target_range_reports_min_max_per_asset(client, wired):
    wired(_alternating_path(REG_A))
    tr = client.post("/api/v1/allocation/analyze",
                     json=_body(model="bl", conditional=True,
                                mes_id="rgs_x")).json()["target_range"]
    assert tr["available"] is True
    assert len(tr["models_used"]) >= 2
    assert {row["name"] for row in tr["range"]} == set(TICKERS)
    for row in tr["range"]:
        assert row["min_pct"] <= row["max_pct"]
        assert row["spread_pct"] == pytest.approx(row["max_pct"] - row["min_pct"], abs=0.01)
    # ★평균으로 접지 않는다★ 모델별 원값이 함께 남는다.
    assert set(tr["by_model"]) == set(tr["models_used"])


def test_a_single_model_gets_no_range_only_the_fact(client, wired, monkeypatch):
    """★한 점에서 뽑은 폭 0 구간은 '합의' 로 잘못 읽힌다★"""
    from src.engine import allocation_studio as st

    real = st.model_availability
    monkeypatch.setattr(st, "model_availability", lambda: {
        **{k: {"available": False, "reason": "테스트에서 비활성화"} for k in real()},
        "risk_parity": {"available": True, "reason": None},
    })
    wired(_alternating_path(REG_A))
    tr = client.post("/api/v1/allocation/analyze",
                     json=_body(model="bl", conditional=True,
                                mes_id="rgs_x")).json()["target_range"]

    assert tr["available"] is False
    assert tr["range"] == [] and tr["dispersion_pct"] is None
    assert tr["models_used"] == ["risk_parity"]
    assert tr["reason"] and "합의" in tr["reason"]
    assert len(tr["skipped"]) >= 1


# ── 7. mock 폴백에서 Σ 가 무너지는 것은 결함이 아니라 보고 대상 ─────────────
def test_a_degenerate_sample_is_flagged_instead_of_looking_like_a_broken_wire(
        client, wired):
    """★이 저장소의 mock 시세가 실제로 만드는 상태다★

    종목별 독립 생성 → 무상관·등분산 → Ledoit-Wolf 목표가 정확히 맞음 → λ=1.0 →
    Σ 가 스케일 단위행렬. 스케일 불변 모델의 비중은 국면과 무관하게 같아진다.
    응답이 그 사실을 말하지 않으면 사용자는 배선이 죽었다고 결론 내린다.
    """
    path = _alternating_path(REG_A)
    rng = np.random.default_rng(3)
    idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=len(path) * 21)
    iid = pd.DataFrame(rng.normal(0.0, 0.01, size=(len(idx), len(TICKERS))),
                       index=idx, columns=TICKERS)
    wired(path, returns=iid)

    b = client.post("/api/v1/allocation/analyze",
                    json=_body(model="min_var", conditional=True,
                               mes_id="rgs_x")).json()
    c = b["conditional"]
    assert c["available"] is True
    assert c["shrinkage_lambda"] == 1.0
    assert c["degenerate"] is True
    assert c["applied_to"]["sigma"] is True
