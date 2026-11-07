"""룰셋 과거 시뮬레이션 — 이중 절단 · 적격성 거부 · 히스테리시스 전파 (스펙 §7).

이 파일이 고정하는 것은 네 가지다.

1. **각 시점이 두 겹으로 절단된다** — 시세는 `etf_prices.as_of(m)`, 매크로는 `as_of` 날짜
   문자열. 하나만 걸면 카탈로그의 나머지 절반에서 룩어헤드가 되살아나는데, 그건 결과가
   좋아지는 방향의 오류라 눈으로는 절대 안 보인다.
2. **`mode="backtest"` 는 걷기 전에 거부한다** — 리스크 레지스터가 이 엔드포인트에 배정한
   `forward_only` 차단 지점. 거부는 팩터 이름을 지목한다.
3. **`mode="forward"` 는 걷되 숨기지 않는다** — `backtest_eligible=False` 와 부적격 팩터 목록.
4. **히스테리시스가 walk 를 타고 흐른다** — 시점마다 previous 를 비우면 히스테리시스가 없는
   룰셋을 시뮬레이션하는 셈이고, 전환 횟수는 규칙에 **유리한** 방향으로 틀린다.
"""
import pytest
from fastapi.testclient import TestClient

import src.data.etf_prices as ep
from src.app_factory import create_app
from src.data.pit_macro import DataStatus, ForwardOnlyError, ResearchUsage
from src.engine import timing_rules_v2 as v2
from src.engine import timing_simulation as sim

URL = "/api/v1/allocation/timing/simulate"


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _rset(**kw):
    specs = kw.pop("specs", [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]}])
    return v2.rule_set_from_specs(specs, market="kr", set_id="s", **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 이중 절단 — 시세 오프셋과 매크로 as_of 가 **함께** 걸린다
# ═══════════════════════════════════════════════════════════════════════════════
def test_each_point_applies_both_price_truncation_and_an_as_of_date(monkeypatch):
    """★한 겹만 걸면 통과하지 못해야 한다★

    시점마다 `etf_prices` 의 스레드 로컬 오프셋과 `rule_set_states` 로 넘어간 `as_of` 를
    **동시에** 기록한다. `with price_as_of(m)` 를 지우면 오프셋이 전부 0 이 되어 첫 단언이,
    `as_of=stamp` 를 지우면 두 번째 단언이 깨진다.
    """
    seen: list[tuple[int, str | None]] = []
    real = sim.rule_set_states

    def spy(rule_set, *, as_of=None, mode="forward", market=None, previous=None):
        seen.append((ep._month_off(), as_of))
        return real(rule_set, as_of=as_of, mode=mode, market=market, previous=previous)

    monkeypatch.setattr(sim, "rule_set_states", spy)
    sim.simulate_rule_set(_rset(), months=5, mode="forward", anchor="2026-06-15")

    offsets = [o for o, _ in seen]
    assert offsets == [5, 4, 3, 2, 1, 0], (
        f"시세 절단이 시점마다 걸리지 않았습니다: {offsets}")

    stamps = [a for _, a in seen]
    assert all(s is not None for s in stamps), "매크로 as_of 가 비어 있습니다 — 빈티지가 고정되지 않습니다"
    assert stamps == sorted(stamps), f"as_of 가 단조 증가하지 않습니다: {stamps}"
    assert stamps[0] == "2026-01-15" and stamps[-1] == "2026-06-15"


def test_points_carry_the_as_of_they_were_evaluated_at():
    """점마다 그 시점이 적혀 있어야 한다 — 외부 파이프라인이 축을 다시 추측하면 안 된다."""
    out = sim.simulate_rule_set(_rset(), months=3, mode="forward", anchor="2026-06-30")
    assert [p.as_of for p in out.points] == [
        "2026-03-30", "2026-04-30", "2026-05-30", "2026-06-30"]
    assert [p.months_back for p in out.points] == [3, 2, 1, 0]


def test_month_shift_clamps_to_the_last_day_of_a_short_month():
    """3월 31일의 1개월 전은 2월 31일이 아니다 — 없는 날짜로 빈티지를 조회하면 안 된다."""
    import datetime as dt
    assert sim._shift_months(dt.date(2026, 3, 31), 1) == "2026-02-28"
    assert sim._shift_months(dt.date(2026, 1, 15), 1) == "2025-12-15"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. backtest 모드 — 걷기 **전에** 거부하고, 팩터를 이름으로 지목한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_backtest_mode_refuses_under_mock_and_names_the_factor():
    """이 환경은 `KIS_USE_MOCK=1` 이라 가격 팩터가 `forward_only` 다 — 그러면 백테스트는 없다."""
    with pytest.raises(ForwardOnlyError) as e:
        sim.simulate_rule_set(_rset(), months=3, mode="backtest", anchor="2026-06-15")
    assert "avg_abs_momentum" in str(e.value), "부적격 팩터를 이름으로 지목하지 않았습니다"


def test_backtest_refusal_happens_before_any_point_is_computed(monkeypatch):
    """★거부가 walk 뒤에 오면 안 된다★ 부적격 데이터로 만든 숫자는 남는 것 자체가 오염이다."""
    calls: list[str] = []
    real = sim.combine
    monkeypatch.setattr(sim, "combine", lambda *a, **k: calls.append("x") or real(*a, **k))
    with pytest.raises(ForwardOnlyError):
        sim.simulate_rule_set(_rset(), months=6, mode="backtest", anchor="2026-06-15")
    assert calls == [], f"거부 전에 {len(calls)}개 시점이 이미 계산됐습니다"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. forward 모드 — 걷되 부적격을 **가리지 않는다**
# ═══════════════════════════════════════════════════════════════════════════════
def test_forward_mode_walks_and_discloses_ineligibility():
    out = sim.simulate_rule_set(_rset(), months=4, mode="forward", anchor="2026-06-15")
    assert len(out.points) == 5
    assert out.backtest_eligible is False
    ids = {f["factor_id"] for f in out.ineligible_factors}
    assert "avg_abs_momentum" in ids, "부적격 팩터가 보고되지 않았습니다"
    assert any(f["usage"] == ResearchUsage.FORWARD_ONLY.value for f in out.ineligible_factors)
    assert any("백테스트가 아닙니다" in x for x in out.limitations), (
        "forward 결과가 백테스트로 오해될 수 있습니다 — 그 사실이 limitations 에 없습니다")


def test_a_failing_point_is_unavailable_not_risk_off(monkeypatch):
    """★평가 실패는 판정이 아니다★ 위험-오프로 적으면 "신호가 꺼졌다" 로 읽힌다."""
    def boom(*a, **k):
        raise RuntimeError("시세 조회 실패")

    monkeypatch.setattr(sim, "rule_set_states", boom)
    out = sim.simulate_rule_set(_rset(), months=2, mode="forward", anchor="2026-06-15")
    assert {p.state for p in out.points} == {v2.SignalState.UNAVAILABLE.value}
    assert out.available_count == 0
    assert out.state_changes == 0, "결측만으로 상태 전환이 집계됐습니다"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 히스테리시스 — walk 를 타고 흐른다
# ═══════════════════════════════════════════════════════════════════════════════
def _oscillating(values: list[float]):
    """임계 근처에서 흔들리는 값들을 시점 순서대로 먹이는 가짜 리더."""
    seq = iter(values)

    def fake(factor_id, *, as_of=None, ticker=None, market="kr", params=None):
        return v2.FactorReading(factor_id, next(seq), ResearchUsage.BACKTEST_ELIGIBLE,
                                DataStatus.REAL, None, "test")
    return fake


def test_hysteresis_threads_through_the_walk(monkeypatch):
    """★밴드 안의 흔들림은 전환이 아니다★

    임계 0 근처에서 ±0.4 로 흔들리는 값. 히스테리시스 0 이면 매 시점 뒤집히고(전환 6회),
    밴드 0.5 면 직전 상태가 유지되어 전환이 **사라진다**. previous 를 시점마다 비우면
    두 결과가 같아져 이 테스트가 깨진다.
    """
    vals = [0.4, -0.4, 0.4, -0.4, 0.4, -0.4, 0.4]

    monkeypatch.setattr(v2, "read_factor", _oscillating(list(vals)))
    naive = sim.simulate_rule_set(
        _rset(specs=[{"factor_id": "avg_abs_momentum", "universe": ["SPY"], "threshold": 0.0}]),
        months=6, mode="forward", anchor="2026-06-15")

    monkeypatch.setattr(v2, "read_factor", _oscillating(list(vals)))
    hyst = sim.simulate_rule_set(
        _rset(specs=[{"factor_id": "avg_abs_momentum", "universe": ["SPY"],
                      "threshold": 0.0, "hysteresis": 0.5}]),
        months=6, mode="forward", anchor="2026-06-15")

    assert naive.state_changes == 6, f"기준선이 예상과 다릅니다: {naive.state_changes}"
    assert hyst.state_changes < naive.state_changes, (
        f"히스테리시스가 walk 에 반영되지 않았습니다 ({hyst.state_changes} vs "
        f"{naive.state_changes}) — 시점마다 previous 가 비워지고 있습니다")
    assert hyst.state_changes == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HTTP 표면
# ═══════════════════════════════════════════════════════════════════════════════
def test_endpoint_defaults_to_backtest_and_refuses_with_the_named_factor(client):
    r = client.post(URL, json={"market": "kr", "months": 3,
                               "rules": [{"factor_id": "avg_abs_momentum",
                                          "universe": ["SPY"]}]})
    assert r.status_code == 422, r.text
    assert "avg_abs_momentum" in r.json()["detail"]


def test_endpoint_forward_mode_returns_points_and_the_eligibility_verdict(client):
    r = client.post(URL, json={"market": "kr", "months": 3, "mode": "forward",
                               "anchor": "2026-06-15",
                               "rules": [{"factor_id": "avg_abs_momentum",
                                          "universe": ["SPY"]}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["points"]) == 4
    assert body["backtest_eligible"] is False
    assert body["ineligible_factors"], "부적격 목록이 비어 있습니다"
    assert body["step"] == "month"
    assert body["points"][0]["as_of"] == "2026-03-15"


@pytest.mark.parametrize("payload,needle", [
    ({"rules": [], "set_id": None}, "둘 다 비어"),
    ({"rules": [{"factor_id": "disparity", "universe": ["SPY"]}], "set_id": "abc"}, "둘 다 주어"),
])
def test_endpoint_requires_exactly_one_of_rules_or_set_id(client, payload, needle):
    """★두 실패를 같은 말로 보고하지 않는다★ 고쳐야 할 것이 서로 다르다."""
    r = client.post(URL, json={"market": "kr", "mode": "forward", **payload})
    assert r.status_code == 422, r.text
    assert needle in r.json()["detail"]


def test_endpoint_rejects_a_missing_set_id_as_422_not_500(client):
    r = client.post(URL, json={"market": "kr", "mode": "forward",
                               "set_id": "does-not-exist"})
    assert r.status_code == 422, r.text
    assert "does-not-exist" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 최상위 경고 · 시간 예산
# ═══════════════════════════════════════════════════════════════════════════════
def test_forward_mode_puts_the_warning_at_the_top_level_not_only_in_a_list():
    """★외부 파이프라인은 limitations 를 훑지 않는다★

    "이 숫자는 백테스트가 아니다" 가 문자열 목록 안에만 있으면 소비자가 건너뛰기 쉽다.
    최상위 `warning` 에 팩터 이름까지 담아 눈에 걸리게 둔다.
    """
    out = sim.simulate_rule_set(_rset(), months=2, mode="forward", anchor="2026-06-15")
    assert out.warning and "백테스트가 아닙니다" in out.warning
    assert "avg_abs_momentum" in out.warning, "어떤 팩터 때문인지 경고가 말하지 않습니다"


def test_a_passing_backtest_carries_no_warning(monkeypatch):
    """경고가 없는 것과 빈 경고는 다르다 — 게이트를 통과한 결과에는 `None` 이다.

    이 환경은 mock 이라 가격 팩터가 전부 forward_only 다. 통과하는 경우를 실제로 만들려면
    적격한 읽기를 주입해야 한다 — 주입하지 않으면 이 단언은 도달조차 못 한다.
    """
    monkeypatch.setattr(v2, "read_factor", lambda fid, **kw: v2.FactorReading(
        fid, 1.0, ResearchUsage.BACKTEST_ELIGIBLE, DataStatus.REAL, None, "test"))
    out = sim.simulate_rule_set(_rset(), months=2, mode="backtest", anchor="2026-06-15")
    assert out.backtest_eligible is True
    assert out.warning is None, f"통과한 백테스트에 경고가 붙었습니다: {out.warning}"
    assert out.ineligible_factors == []


def test_the_walk_stops_at_the_time_budget_and_says_so():
    """★예산을 넘기면 남은 구간을 채우지 않는다★

    마지막 값이나 0 으로 이어 붙이면 짧게 끝난 시뮬레이션이 요청한 길이만큼 돈 것처럼 보인다.
    예산 0 이 아니라 아주 작은 값을 준다 — 0 은 "무제한" 이라는 다른 뜻이다.
    """
    out = sim.simulate_rule_set(_rset(), months=240, mode="forward",
                                anchor="2026-06-15", deadline_seconds=1e-9)
    assert len(out.points) < 241, "예산을 넘겼는데 전 구간을 걸었습니다"
    assert any("중단" in x for x in out.limitations), (
        f"중단 사실이 limitations 에 없습니다: {out.limitations}")


def test_a_zero_budget_means_unlimited_not_instant_stop():
    """0 은 "예산 없음" 이다 — 즉시 중단으로 읽으면 walk 가 조용히 비어 나간다."""
    out = sim.simulate_rule_set(_rset(), months=2, mode="forward",
                                anchor="2026-06-15", deadline_seconds=0)
    assert len(out.points) == 3
    assert not any("중단" in x for x in out.limitations)
