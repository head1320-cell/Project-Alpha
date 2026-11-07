"""PIT 매크로 — ALFRED 빈티지 기반 look-ahead 차단 단위 테스트.

배경(실측): 기존 src/services/macro_collector.py::FredClient.fetch_series 는
  · realtime_start/realtime_end 를 보내지 않아 FRED 가 **오늘 시점 최신 개정판**을 준다
  · o["realtime_start"] 를 버려서 관측치별 공표시각이 남지 않는다
  · frequency="m" 서버측 집계로 월중 공표 타이밍이 뭉개진다
→ 2020년 관측치를 요청해도 "2020년에 공표된 값"이 아니라 "지금까지 개정된 값"이 온다.
   GDPC1·CPIAUCSL·PAYEMS 처럼 개정이 큰 시리즈에서는 미래가 그대로 샌다.

이 테스트는 그 세 가지를 각각 고정한다. 네트워크 불필요(요청 함수 스텁).

★핵심★ observation_period <= as_of 만 보는 테스트는 이 버그를 통과시킨다.
   반드시 **공표시각(release_timestamp)** 과 **값 자체**를 봐야 한다.
"""
from __future__ import annotations

import pytest

from src.data import pit_macro as pm

# ── GDPC1 2020Q1: 속보→잠정→확정으로 값이 크게 바뀐 실제 개정 패턴을 모사 ──────────
#   observation_period 는 셋 다 2020-01-01 로 동일하다. 구분은 realtime_start 뿐이다.
GDPC1_VINTAGES = [
    {"date": "2020-01-01", "value": "-4.8", "realtime_start": "2020-04-29", "realtime_end": "2020-05-27"},
    {"date": "2020-01-01", "value": "-5.0", "realtime_start": "2020-05-28", "realtime_end": "2020-06-24"},
    {"date": "2020-01-01", "value": "-5.1", "realtime_start": "2020-06-25", "realtime_end": "9999-12-31"},
]


@pytest.fixture
def stub_alfred(monkeypatch):
    """ALFRED 응답을 스텁하고, 실제로 보낸 params 를 캡처한다."""
    sent: dict = {}

    def fake_get(url, params=None, timeout=None):
        sent.clear()
        sent.update(params or {})
        rs = (params or {}).get("realtime_start")
        # ALFRED 의미론: realtime_start <= as_of 인 빈티지만 반환
        rows = [o for o in GDPC1_VINTAGES if rs is None or o["realtime_start"] <= rs]

        class _R:
            status_code = 200
            @staticmethod
            def json():
                return {"observations": rows}
        return _R()

    monkeypatch.setattr(pm, "_http_get", fake_get)
    return sent


# ─── 1. 요청이 빈티지를 지정하는가 ─────────────────────────────────────────────
def test_request_pins_a_vintage_and_does_not_aggregate(stub_alfred):
    pm.fetch_observations("GDPC1", as_of="2020-05-01", api_key="k" * 20)
    assert stub_alfred.get("realtime_start") == "2020-05-01", "as_of 를 realtime_start 로 보내야 한다"
    assert stub_alfred.get("realtime_end") == "2020-05-01"
    assert "frequency" not in stub_alfred, "서버측 집계는 공표 타이밍을 뭉갠다 — 보내면 안 된다"


# ─── 2. 개정 전 시점에는 최초 공표값이 나와야 한다 (이 버그의 핵심) ──────────────
def test_as_of_before_revision_returns_originally_published_value(stub_alfred):
    obs = pm.fetch_observations("GDPC1", as_of="2020-05-01", api_key="k" * 20)
    assert len(obs) == 1
    assert obs[0].value == pytest.approx(-4.8), (
        "2020-05-01 시점에 알 수 있던 값은 속보치 -4.8 이다. "
        "-5.1(현재 확정치)이 나오면 미래가 샌 것이다."
    )
    assert obs[0].observation_period == "2020-01-01"
    assert obs[0].release_timestamp == "2020-04-29"


def test_as_of_after_revision_returns_revised_value(stub_alfred):
    obs = pm.fetch_observations("GDPC1", as_of="2020-07-01", api_key="k" * 20)
    assert obs[-1].value == pytest.approx(-5.1)


# ─── 3. as_of 이후에 공표된 관측치는 도달 불가여야 한다 ────────────────────────
def test_no_observation_released_after_as_of_is_reachable(stub_alfred):
    as_of = "2020-05-01"
    obs = pm.fetch_observations("GDPC1", as_of=as_of, api_key="k" * 20)
    assert obs, "빈 결과면 이 단언은 공허하다"
    for o in obs:
        assert o.release_timestamp <= as_of, f"{o.release_timestamp} 는 as_of 이후 공표분이다"


def test_observation_period_filter_alone_is_insufficient():
    """관측기간만 보는 필터는 세 빈티지를 모두 통과시킨다 — 그래서 부족하다."""
    passing = [o for o in GDPC1_VINTAGES if o["date"] <= "2020-05-01"]
    assert len(passing) == 3, "관측기간 기준으론 개정판까지 전부 통과한다(=룩어헤드)"


# ─── 4. 관측치 신원 6종이 모두 채워지는가 ──────────────────────────────────────
def test_observation_carries_full_identity(stub_alfred):
    o = pm.fetch_observations("GDPC1", as_of="2020-07-01", api_key="k" * 20)[0]
    for field in ("series_id", "observation_period", "release_timestamp",
                  "vintage_id", "retrieved_at", "value", "data_status"):
        assert getattr(o, field) is not None, f"{field} 가 비어 있다"


# ─── 5. 키가 없으면 조용히 0 이 아니라 unavailable ─────────────────────────────
def test_missing_api_key_yields_unavailable_not_zero(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    obs = pm.fetch_observations("GDPC1", as_of="2020-05-01", api_key="")
    assert obs == [], "키가 없으면 빈 결과 — 합성값으로 채우면 안 된다"


def test_http_failure_yields_unavailable_not_zero(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr(pm, "_http_get", boom)
    assert pm.fetch_observations("GDPC1", as_of="2020-05-01", api_key="k" * 20) == []


# ─── 6. ResearchUsage 파생 — 손으로 지정하지 않는다 ────────────────────────────
@pytest.mark.parametrize("has_vintage,depth_ok,lag_known,expected", [
    (True,  True,  True,  pm.ResearchUsage.BACKTEST_ELIGIBLE),
    (False, True,  True,  pm.ResearchUsage.FORWARD_ONLY),   # 개정 재구성 불가
    (True,  False, True,  pm.ResearchUsage.FORWARD_ONLY),   # 이력 부족
    (True,  True,  False, pm.ResearchUsage.FORWARD_ONLY),   # 공표지연 미모델링
])
def test_research_usage_is_derived(has_vintage, depth_ok, lag_known, expected):
    assert pm.derive_usage(
        has_vintage=has_vintage, depth_ok=depth_ok, lag_known=lag_known
    ) is expected


def test_no_source_is_unavailable():
    assert pm.derive_usage(
        has_vintage=False, depth_ok=False, lag_known=False, has_source=False
    ) is pm.ResearchUsage.UNAVAILABLE


# ─── 7. forward_only 는 과거 시뮬레이션에서 **거부**된다(경고 후 진행 아님) ──────
def test_historical_simulation_rejects_forward_only_by_name():
    with pytest.raises(pm.ForwardOnlyError) as ei:
        pm.assert_backtest_eligible({
            "tsmom_spy": pm.ResearchUsage.BACKTEST_ELIGIBLE,
            "kis_foreign_flow": pm.ResearchUsage.FORWARD_ONLY,
        })
    msg = str(ei.value)
    assert "kis_foreign_flow" in msg, "어떤 팩터가 문제인지 이름이 나와야 한다"
    assert "tsmom_spy" not in msg, "멀쩡한 팩터를 지목하면 안 된다"


def test_all_eligible_passes():
    pm.assert_backtest_eligible({"a": pm.ResearchUsage.BACKTEST_ELIGIBLE})
