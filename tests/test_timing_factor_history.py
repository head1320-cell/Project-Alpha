"""Phase 6b-2 — 팩터 과거 미리보기 (스펙 §8.1 요구 4). **룩어헤드 안전성이 핵심.**

미리보기는 "과거 각 시점에 이 팩터가 무슨 신호였나" 를 보여준다. 각 점을 **그 시점에 알 수
있었던 데이터만으로** 채점하지 않으면, 미리보기는 실제로는 불가능했던 판단을 그럴듯하게
보여주는 장치가 된다 — Phase 1 이 막으려던 바로 그 오류를 UI 에서 되살리는 셈이다.

`etf_prices.as_of(months_back)` 가 이미 그 절단을 제공하므로 새로 만들지 않고 쓴다.
아래 테스트는 **시세 캐시에 합성 시리즈를 심어** 실제 절단 경로를 그대로 통과시킨다
(가짜 monthly_closes 를 끼우면 절단 자체를 검증하지 못한다).
"""
import pytest

from src.data import etf_prices
from src.engine.timing_factor_history import factor_history
from src.engine.timing_rules_v2 import SignalState

TICKER = "SPY"
MARKET = "kr"

# 36개월 꾸준한 상승 뒤 **마지막 3개월 급락**.
# 룩어헤드가 있으면 오래된 점들까지 급락을 반영해 버린다 — 그게 이 시리즈의 존재 이유다.
RISING = [100.0 + i for i in range(36)]
CRASH = [60.0, 55.0, 50.0]


@pytest.fixture
def prices():
    """월봉 캐시에 합성 시리즈를 심는다 — as_of 절단은 실제 코드가 수행한다."""
    key = (f"m:{MARKET}", TICKER)
    saved = etf_prices._CACHE.get(key)
    etf_prices._CACHE[key] = list(RISING + CRASH)
    yield etf_prices._CACHE[key]
    if saved is None:
        etf_prices._CACHE.pop(key, None)
    else:
        etf_prices._CACHE[key] = saved


def _hist(**kw):
    return factor_history("avg_abs_momentum", TICKER, MARKET, months=12, **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ★룩어헤드 안전성★ — 이 파일에서 가장 중요한 테스트
# ═══════════════════════════════════════════════════════════════════════════════
def test_old_points_do_not_see_the_recent_crash(prices):
    """오래된 점은 급락 이전 상태여야 한다. 전부 같은 값이면 절단이 안 된 것이다."""
    h = _hist()
    by_back = {p.months_back: p.value for p in h.points}

    # 급락 훨씬 이전(9개월 전) — 상승 구간만 보이므로 전 구간 양(+) 비율 = 1.0
    assert by_back[9] == pytest.approx(1.0), "9개월 전 시점이 급락을 보고 있다 → 룩어헤드"
    # 현재 시점 — 급락이 반영되어 비율이 떨어진다
    assert by_back[0] < 1.0, "현재 시점이 급락을 반영하지 않는다 → 절단 오류"


def test_the_series_is_not_flat(prices):
    """★모든 점이 같으면 절단이 무력화된 것★ — 룩어헤드의 가장 흔한 증상이다."""
    vals = [p.value for p in _hist().points if p.value is not None]
    assert len(set(vals)) > 1, "모든 시점의 값이 동일하다 — as_of 절단이 적용되지 않았다"


def test_as_of_context_is_restored_after_the_call(prices):
    """스레드 로컬 오프셋이 남으면 **이후 모든 조회가 과거를 보게 된다** — 조용한 오염."""
    before = etf_prices._month_off()
    _hist()
    assert etf_prices._month_off() == before == 0


def test_points_are_ordered_oldest_to_newest(prices):
    backs = [p.months_back for p in _hist().points]
    assert backs == sorted(backs, reverse=True), "오래된 → 최신 순서여야 차트가 뒤집히지 않는다"
    assert backs[-1] == 0, "마지막 점은 현재 시점"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 3-상태 판정 — Phase 7 의 규칙을 그대로 쓴다(재구현 금지)
# ═══════════════════════════════════════════════════════════════════════════════
def test_states_use_the_three_state_enum(prices):
    states = {p.state for p in _hist().points}
    assert states <= {s.value for s in SignalState}


def test_direction_comes_from_the_catalogue_not_a_guess(prices):
    """defense_first 같은 역방향 팩터가 여기서도 갈린다 — 방향은 카탈로그가 진실."""
    h = factor_history("defense_first", TICKER, MARKET, months=3)
    assert h.direction == "below"


def test_threshold_override_changes_the_states(prices):
    """사용자가 창에서 임계를 바꾸면 미리보기도 그 임계로 다시 채점되어야 한다."""
    lo = _hist(threshold=0.0)      # 거의 항상 통과
    hi = _hist(threshold=1.5)      # 절대 통과 불가(비율은 0~1)
    assert any(p.state == SignalState.RISK_ON.value for p in lo.points)
    assert all(p.state != SignalState.RISK_ON.value for p in hi.points)


def test_direction_override_is_honoured(prices):
    a = _hist(threshold=0.5, direction="above")
    b = _hist(threshold=0.5, direction="below")
    assert [p.state for p in a.points] != [p.state for p in b.points]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 상태 전환 횟수 — 스펙이 명시적으로 요구한 숫자
# ═══════════════════════════════════════════════════════════════════════════════
def test_state_changes_counts_flips_between_available_points(prices):
    h = _hist(threshold=0.99)   # 상승 구간=1.0(온) → 급락 후 하락(오프)
    seq = [p.state for p in h.points if p.state != SignalState.UNAVAILABLE.value]
    expected = sum(1 for x, y in zip(seq, seq[1:]) if x != y)
    assert h.state_changes == expected
    assert h.state_changes >= 1, "상승→급락 구간에 전환이 최소 1회 있어야 한다"


def test_missing_points_do_not_count_as_flips(prices):
    """★결측을 전환으로 세면 데이터 구멍이 '신호가 요동쳤다' 로 보인다★"""
    h = factor_history("avg_abs_momentum", TICKER, MARKET, months=200)
    assert h.unavailable_count > 0, "시리즈보다 긴 구간을 요청했으니 결측이 있어야 한다"
    seq = [p.state for p in h.points if p.state != SignalState.UNAVAILABLE.value]
    assert h.state_changes == sum(1 for x, y in zip(seq, seq[1:]) if x != y)


def test_counts_add_up(prices):
    h = _hist()
    assert h.available_count + h.unavailable_count == len(h.points)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 정직한 미가용 — 그럴듯한 그림을 만들지 않는다
# ═══════════════════════════════════════════════════════════════════════════════
def test_as_of_factor_is_refused_with_a_reason():
    """curve_slope 는 카나리 평가기로 값이 안 나온다 — 빈 그래프 대신 사유를 준다."""
    h = factor_history("curve_slope", TICKER, MARKET, months=6)
    assert h.available_count == 0
    assert h.limitations, "왜 비었는지 설명이 없으면 고장으로 보인다"
    assert any("as_of" in x or "시점" in x for x in h.limitations)


def test_unknown_factor_is_refused_not_guessed():
    h = factor_history("no_such_factor", TICKER, MARKET, months=6)
    assert h.available_count == 0
    assert h.points == []
    assert h.limitations


def test_history_declares_its_sampling_step(prices):
    """★월 단위 표본임을 밝힌다★ — 일간 팩터의 전환 횟수는 과소집계된다."""
    h = _hist()
    assert h.step == "month"
    assert any("월" in x for x in h.limitations)


def test_daily_factor_says_its_count_is_undersampled(prices):
    """일간 팩터를 월 표본으로 그리면 전환 횟수가 실제보다 적다 — 그 사실을 적는다."""
    h = factor_history("ma_day", TICKER, MARKET, months=6)
    assert any("과소" in x for x in h.limitations)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 엔드포인트 — 경로 충돌 없이, 실패도 200 + 사유로
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c


_BASE = "/api/v1/allocation/timing-factors"


def test_history_endpoint_returns_the_payload(client, prices):
    r = client.get(f"{_BASE}/avg_abs_momentum/history", params={"months": 6, "ticker": TICKER})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["factor_id"] == "avg_abs_momentum"
    assert len(body["points"]) == 7          # 6개월 전 … 현재
    assert body["step"] == "month"


def test_the_new_route_does_not_shadow_the_catalogue_route(client):
    """★/timing-factors 가 계속 카탈로그를 주는가★ 경로가 가려지면 창 전체가 빈다."""
    r = client.get(_BASE)
    assert r.status_code == 200, r.text
    assert "groups" in r.json()


def test_unavailable_history_is_200_with_a_reason_not_an_error(client):
    """미리보기 실패는 요청 오류가 아니다 — 4xx/5xx 로 답하면 UI 가 에러 배너를 띄운다."""
    r = client.get(f"{_BASE}/curve_slope/history", params={"months": 6})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["points"] == []
    assert body["limitations"]


def test_threshold_and_direction_query_params_are_applied(client, prices):
    r = client.get(f"{_BASE}/avg_abs_momentum/history",
                   params={"months": 6, "ticker": TICKER, "threshold": 1.5, "direction": "above"})
    body = r.json()
    assert body["threshold"] == 1.5
    assert all(p["state"] != "risk_on" for p in body["points"])


def test_bad_direction_is_rejected(client):
    r = client.get(f"{_BASE}/avg_abs_momentum/history", params={"direction": "sideways"})
    assert r.status_code == 422


def test_months_is_bounded(client):
    assert client.get(f"{_BASE}/avg_abs_momentum/history",
                      params={"months": 0}).status_code == 422
    assert client.get(f"{_BASE}/avg_abs_momentum/history",
                      params={"months": 9999}).status_code == 422


def test_to_dict_is_json_shaped(prices):
    d = _hist().to_dict()
    assert d["factor_id"] == "avg_abs_momentum"
    assert d["step"] == "month"
    assert isinstance(d["points"], list) and isinstance(d["points"][0], dict)
    assert set(d["points"][0]) == {"months_back", "value", "state"}
    assert isinstance(d["state_changes"], int)
