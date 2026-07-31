"""Phase 8b — 새 매크로 시리즈(NFCI·VXVCLS)와 시점 기반 리더.

Phase 8 은 **이미 가진 데이터**로 카탈로그를 채웠다. 여기서부터는 새 데이터를 들인다.
어려운 부분은 가져오는 것이 아니라 **개정(NFCI)과 시차(VIX 쌍)** 를 올바로 다루는 것이다.
둘 다 룩어헤드 벡터이고, 틀리면 백테스트가 **더 좋아 보이며** 출력 어디에도 이유가 남지 않는다.

`indicator` 배선도 여기서 한다 — Phase 8 에서 "카탈로그에 있는데 evaluate 분기가 없어 V2
경로에서 영원히 unavailable" 이라고 기록해 둔 기존 결함이고, 그 수리에 필요한 시점 기반
매크로 리더를 이 단계가 어차피 만든다.
"""
import pytest

from src.data.pit_macro import ResearchUsage
from src.engine import timing_rules_v2 as v2


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
    """`_http_get` 단일 지점만 가로챈다 — 네트워크 0 (test_timing_pit_factors 와 동일 idiom)."""
    box = {"payload": _rows(), "calls": []}

    def fake(url, params=None, timeout=None):
        box["calls"].append(dict(params or {}))
        p = box["payload"]
        # 시리즈별로 다른 응답을 주고 싶을 때 dict 로 넘긴다.
        if isinstance(p, dict) and "observations" not in p:
            return _Resp(p.get((params or {}).get("series_id"), _rows()))
        return _Resp(p)

    monkeypatch.setattr("src.data.pit_macro._http_get", fake)
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    return box


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 새 시리즈가 수집기에 등록됐는가
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", ["NFCI", "VXVCLS"])
def test_new_series_are_registered_in_the_collector(sid):
    from src.services.macro_collector import FRED_INDICATORS
    assert sid in FRED_INDICATORS, f"{sid} 가 수집 대상에 없다"
    assert FRED_INDICATORS[sid].get("name"), f"{sid} 에 표시 이름이 없다"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 범용 매크로 시리즈 리더 — `indicator` 배선
# ═══════════════════════════════════════════════════════════════════════════════
def test_indicator_is_reachable_and_no_longer_permanently_unavailable(alfred):
    """★Phase 8 이 기록한 기존 결함의 수리★

    카탈로그에 있는데 리더가 없으면 사용자에겐 "데이터가 없다" 로 보이지만 실제로는 배선이
    없는 것이다. 이제 as_of 를 주면 값이 나와야 한다.
    """
    alfred["payload"] = _rows(("2026-01-05", "2026-01-06", 18.4))
    r = v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "VIXCLS"})
    assert r.value == pytest.approx(18.4)
    assert r.usage is not ResearchUsage.UNAVAILABLE


def test_indicator_without_an_as_of_is_unavailable_but_stays_addable(alfred):
    """as_of 없이 부르면 값을 지어내지 않는다 — 다만 **카탈로그 플래그는 붙이지 않는다.**

    ★`requires_as_of` 를 붙이면 팩터 창이 "추가 불가" 로 막아 지금 되는 흐름이 사라진다★
    이 팩터는 레거시 카나리 경로(`macro_analytics`)로 평가되고 있고 그 경로는 시점이 필요
    없다. 그래서 플래그 대신 `read_factor` 가 as_of 유무로 분기한다 — V2 는 빈티지를 제대로
    읽고, 사용자가 쓰던 기능은 그대로다.
    """
    assert v2.requires_as_of("indicator") is False, (
        "플래그를 붙이면 팩터 창에서 추가할 수 없게 된다(기존 기능 제거)")
    r = v2.read_factor("indicator", ticker="SPY", params={"series_id": "VIXCLS"})
    assert r.usage is ResearchUsage.UNAVAILABLE
    assert "as_of" in r.detail


def test_indicator_reads_the_vintage_known_at_as_of(alfred):
    """같은 기간에 빈티지가 둘이면 as_of 시점 최신본 — 오늘 개정판이 새면 안 된다."""
    alfred["payload"] = _rows(
        ("2026-01-05", "2026-01-06", 18.4),     # 최초 공표
        ("2026-01-05", "2026-03-01", 25.0),     # 나중 개정
    )
    r = v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "VIXCLS"})
    assert r.value == pytest.approx(18.4), "as_of 이후의 개정값이 샜다"


def test_indicator_without_an_api_key_is_unavailable_not_zero(monkeypatch):
    """★0 은 '값 없음' 이 아니라 '지표가 0' 이라는 판단이다★"""
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    r = v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "VIXCLS"})
    assert r.value is None
    assert r.usage is ResearchUsage.UNAVAILABLE


def test_a_transport_failure_is_unavailable_not_an_exception(monkeypatch):
    """레이트리밋·네트워크 실패가 예외로 새어나가면 창 전체가 죽는다."""
    def boom(url, params=None, timeout=None):
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setattr("src.data.pit_macro._http_get", boom)
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    r = v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "VIXCLS"})
    assert r.value is None and r.usage is ResearchUsage.UNAVAILABLE


def test_the_series_id_is_passed_through_to_the_request(alfred):
    """파라미터의 series_id 가 실제 호출에 반영되는가 — 아니면 늘 같은 시리즈를 읽는다."""
    alfred["payload"] = _rows(("2026-01-05", "2026-01-06", 1.0))
    v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "DGS10"})
    assert alfred["calls"], "요청이 나가지 않았다"
    assert alfred["calls"][-1].get("series_id") == "DGS10"


def test_indicator_usage_is_derived_not_asserted(alfred):
    """★usage 를 손으로 지정하면 게이트가 거짓말을 한다★

    빈티지 식별자가 없는 응답은 backtest_eligible 일 수 없다.
    """
    alfred["payload"] = {"observations": [
        {"date": "2026-01-05", "value": "18.4"},        # realtime_* 없음 = 빈티지 불명
    ]}
    r = v2.read_factor("indicator", as_of="2026-02-01", params={"series_id": "VIXCLS"})
    assert r.usage is not ResearchUsage.BACKTEST_ELIGIBLE


# ═══════════════════════════════════════════════════════════════════════════════
# 3. NFCI — 주간·개정되는 시리즈
# ═══════════════════════════════════════════════════════════════════════════════
def test_financial_conditions_reads_nfci(alfred):
    alfred["payload"] = _rows(("2026-01-02", "2026-01-08", -0.35))
    r = v2.read_financial_conditions("2026-02-01")
    assert r.value == pytest.approx(-0.35)


def test_financial_conditions_uses_the_vintage_not_the_revision(alfred):
    """NFCI 는 **개정된다** — §6.1 이 빈티지를 요구하는 이유다."""
    alfred["payload"] = _rows(
        ("2026-01-02", "2026-01-08", -0.35),
        ("2026-01-02", "2026-03-15", -0.90),   # 나중 개정
    )
    assert v2.read_financial_conditions("2026-02-01").value == pytest.approx(-0.35)


def test_financial_conditions_without_a_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    r = v2.read_financial_conditions("2026-02-01")
    assert r.value is None and r.usage is ResearchUsage.UNAVAILABLE


def test_financial_conditions_is_in_the_catalogue_and_declares_as_of():
    assert "financial_conditions" in v2.CATALOG_BY_ID
    assert v2.requires_as_of("financial_conditions") is True
    assert v2.direction_for("financial_conditions") in ("above", "below")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 레거시 카나리 경로 회귀 (Drift D7-1)
# ═══════════════════════════════════════════════════════════════════════════════
def test_legacy_canary_path_for_indicator_is_untouched():
    """★`indicator` 에 requires_as_of 를 붙여도 레거시 `/timing` 경로는 그대로여야 한다★

    D7-1 이 `passes()` 를 건드리지 않기로 한 이유와 같다 — 라이브 카나리 경로에 회귀가 나면
    사용자가 쓰던 화면이 조용히 깨진다.
    """
    from src.api.allocation_routes import CanarySpec, _canary_eval

    c = CanarySpec(kind="indicator", id="VIXCLS", signal="indicator",
                   lookback=1, threshold=20.0, direction="below")
    ok, val = _canary_eval(c, "kr")
    assert isinstance(ok, bool)          # 예외 없이 판정을 돌려준다
    assert val is None or isinstance(val, (int, float))
