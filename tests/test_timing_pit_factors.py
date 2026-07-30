"""Phase 7 step 4 — 두 개의 PIT 팩터와 백테스트 적격 게이트 배선.

Phase 1 이 만든 `fetch_observations`/`assert_backtest_eligible` 는 여기까지 **호출자가
없었다**(테스트뿐). 이 파일이 그 배선을 검증한다.

핵심은 두 가지다:
  · 매크로 팩터는 `as_of` 시점 빈티지만 본다 — 오늘 개정판이 새면 과거 성과가 부풀려진다.
  · 키/데이터가 없으면 값이 없는 것이고, 값이 없으면 위험-오프로 접힌다. 0 으로 채우지 않는다.
"""
import pytest

from src.data.pit_macro import DataStatus, ForwardOnlyError, ResearchUsage
from src.engine import timing_rules_v2 as v2
from src.engine.timing_rules_v2 import SignalState


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _rows(*triples):
    """(관측기간, realtime_start, 값) → ALFRED 응답 행."""
    return {"observations": [
        {"date": d, "realtime_start": rs, "realtime_end": "9999-12-31", "value": str(v)}
        for d, rs, v in triples
    ]}


@pytest.fixture
def alfred(monkeypatch):
    """`_http_get` 단일 지점만 가로챈다 — 네트워크 0."""
    box = {"payload": _rows()}

    def fake(url, params=None, timeout=None):
        box["last_params"] = params or {}
        return _Resp(box["payload"])

    monkeypatch.setattr("src.data.pit_macro._http_get", fake)
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    return box


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 매크로 팩터 — 커브 기울기 (T10Y2Y)
# ═══════════════════════════════════════════════════════════════════════════════
def test_curve_slope_is_registered_in_the_catalogue():
    """카탈로그가 방향의 단일 진실이므로 등록되어 있어야 한다."""
    assert v2.direction_for("curve_slope") is not None
    assert v2.threshold_for("curve_slope") == 0.0


def test_curve_slope_reads_the_vintage_known_at_as_of(alfred):
    """★같은 기간에 빈티지가 둘이면 as_of 시점 최신본을 쓴다★"""
    alfred["payload"] = _rows(
        ("2020-03-02", "2020-03-03", 0.20),   # 최초 공표
        ("2020-03-02", "2020-03-05", 0.55),   # 나중 개정 — as_of 가 지나야 보인다
    )
    r = v2.read_curve_slope("2020-03-04")
    assert r.value == 0.20, "as_of 이후 개정본이 새면 과거를 오늘 값으로 채점한다"

    r2 = v2.read_curve_slope("2020-03-10")
    assert r2.value == 0.55


def test_curve_slope_pins_the_realtime_window(alfred):
    """빈티지 고정 파라미터가 실제로 전송되는가 — 없으면 조용히 최신판이 온다."""
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.20))
    v2.read_curve_slope("2020-03-04")
    p = alfred["last_params"]
    assert p["realtime_start"] == "2020-03-04"
    assert p["realtime_end"] == "2020-03-04"
    assert p["series_id"] == "T10Y2Y"


def test_curve_slope_direction_comes_from_the_catalogue(alfred):
    """양(+)의 기울기 = 정상 커브 = 위험-온, 역전(−)은 위험-오프."""
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.45))
    assert v2.state_for_factor("curve_slope", v2.read_curve_slope("2020-03-04").value) \
        is SignalState.RISK_ON

    alfred["payload"] = _rows(("2019-08-27", "2019-08-28", -0.05))
    assert v2.state_for_factor("curve_slope", v2.read_curve_slope("2019-08-29").value) \
        is SignalState.RISK_OFF


def test_curve_slope_without_a_key_is_unavailable_not_zero(monkeypatch):
    """★키가 없으면 0 이 아니라 unavailable★ — 0 은 '기울기 0'이라는 판단이 된다."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    r = v2.read_curve_slope("2020-03-04")
    assert r.value is None
    assert r.usage is ResearchUsage.UNAVAILABLE
    assert r.data_status is DataStatus.UNAVAILABLE
    assert v2.state_for_factor("curve_slope", r.value) is SignalState.UNAVAILABLE


def test_curve_slope_unavailable_folds_to_risk_off_in_composition(monkeypatch):
    """결측이 조합을 거쳐 위험-온이 되지 않는다."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    macro = v2.state_for_factor("curve_slope", v2.read_curve_slope("2020-03-04").value)
    out = v2.combine([SignalState.RISK_ON, macro], method="all")
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0
    assert out.unavailable_count == 1, "결측 건수는 따로 세어 설명에 남아야 한다"


def test_curve_slope_empty_response_is_unavailable(alfred):
    """키는 있는데 구간에 값이 없을 때도 정직하게 unavailable."""
    alfred["payload"] = _rows()
    r = v2.read_curve_slope("2020-03-04")
    assert r.value is None
    assert r.usage is ResearchUsage.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
# 2. usage 파생 — "가져올 수 있다" ≠ "백테스트에 쓸 수 있다"
# ═══════════════════════════════════════════════════════════════════════════════
def test_curve_slope_with_vintages_is_backtest_eligible(alfred):
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.20))
    r = v2.read_curve_slope("2020-03-04")
    assert r.usage is ResearchUsage.BACKTEST_ELIGIBLE
    assert r.data_status is DataStatus.REAL


def test_curve_slope_requested_depth_not_covered_is_forward_only(alfred):
    """요청 구간보다 이력이 짧으면 과거 시뮬레이션에 쓸 수 없다."""
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.20))
    r = v2.read_curve_slope("2020-03-04", start="2010-01-01")
    assert r.usage is ResearchUsage.FORWARD_ONLY, "2010 부터를 요청했는데 2020 이력만 있다"
    assert r.value == 0.20, "적격이 아니어도 값 자체는 forward 용으로 유효하다"


def test_release_timestamp_before_observation_period_is_not_trusted(alfred):
    """공표시각이 관측기간보다 앞서면 공표지연이 모델링된 것이 아니다 → forward_only."""
    alfred["payload"] = _rows(("2020-03-02", "2020-03-01", 0.20))
    r = v2.read_curve_slope("2020-03-04")
    assert r.usage is ResearchUsage.FORWARD_ONLY


def test_price_factor_under_mock_is_never_backtest_eligible(monkeypatch):
    """★합성 데이터가 백테스트 적격으로 통과하면 게이트가 거짓말을 한다★"""
    monkeypatch.setattr("src.engine.timing_rules_v2.mock_allowed", lambda: True)
    r = v2.read_price_factor("avg_abs_momentum", "069500", "kr")
    assert r.usage is not ResearchUsage.BACKTEST_ELIGIBLE
    assert r.data_status is DataStatus.MOCK


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 게이트 배선 — forward_only 는 과거 시뮬레이션에서 거부된다
# ═══════════════════════════════════════════════════════════════════════════════
def test_gate_rejects_a_forward_only_factor_by_name(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    readings = [v2.read_curve_slope("2020-03-04")]
    with pytest.raises(ForwardOnlyError) as e:
        v2.assert_readings_backtest_eligible(readings)
    assert "curve_slope" in str(e.value), "어느 팩터가 문제인지 이름으로 지목해야 한다"


def test_gate_passes_when_every_factor_is_eligible(alfred):
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.20))
    v2.assert_readings_backtest_eligible([v2.read_curve_slope("2020-03-04")])


def test_backtest_mode_evaluation_refuses_ineligible_data(monkeypatch):
    """★게이트가 실제로 호출되는가★ — 함수만 존재하고 안 불리면 의미가 없다."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    rs = v2.TimingRuleSetV2(set_id="s1", rules=[v2.TimingRuleV2(factor_id="curve_slope")])
    with pytest.raises(ForwardOnlyError):
        v2.evaluate_rule_set(rs, as_of="2020-03-04", mode="backtest")


def test_forward_mode_evaluation_allows_ineligible_data_but_stays_conservative(monkeypatch):
    """forward 모드는 거부하지 않는다 — 대신 결측이므로 위험-오프."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    rs = v2.TimingRuleSetV2(set_id="s1", rules=[v2.TimingRuleV2(factor_id="curve_slope")])
    out = v2.evaluate_rule_set(rs, as_of="2020-03-04", mode="forward")
    assert out.state is SignalState.RISK_OFF
    assert out.exposure == 0.0
    assert out.unavailable_count == 1


def test_backtest_mode_passes_with_vintage_backed_data(alfred):
    alfred["payload"] = _rows(("2020-03-02", "2020-03-03", 0.45))
    rs = v2.TimingRuleSetV2(set_id="s1", rules=[v2.TimingRuleV2(factor_id="curve_slope")])
    out = v2.evaluate_rule_set(rs, as_of="2020-03-04", mode="backtest")
    assert out.state is SignalState.RISK_ON
    assert out.exposure == 1.0


def test_unknown_mode_is_rejected():
    rs = v2.TimingRuleSetV2(set_id="s1", rules=[])
    with pytest.raises(ValueError):
        v2.evaluate_rule_set(rs, as_of="2020-03-04", mode="wishful")
