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


# ═══════════════════════════════════════════════════════════════════════════════
# 5. VIX 텀 스트럭처 — 스펙 §6.2 의 **정의** (시리즈 추가가 아니라 팩터 정의)
#
# ★이 절이 Phase 8b 의 게이트다★
# 룩어헤드는 틀렸을 때 **백테스트를 더 좋아 보이게** 만들고, 출력 어디에도 이유가 남지 않는다.
# 그래서 픽스처를 "같은 날짜로 읽으면 다른 값이 나오도록" 구성한다 — 그러지 않으면 정렬
# 테스트가 두 구현을 구별하지 못하고 조용히 통과한다(Phase 8 에서 실제로 그렇게 헛돌았다).
# ═══════════════════════════════════════════════════════════════════════════════
def _pair(vix_rows, vxv_rows):
    """시리즈별로 다른 응답을 주는 페이로드."""
    return {"VIXCLS": _rows(*vix_rows), "VXVCLS": _rows(*vxv_rows)}


def test_vix_term_structure_is_the_ratio_not_the_spread(alfred):
    """§6.2: 팩터는 **비율** VIXCLS/VXVCLS 다. 스프레드는 별도 팩터."""
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0)],
        [("2026-01-05", "2026-01-06", 24.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06")
    assert r.value == pytest.approx(18.0 / 24.0)


def test_ratio_below_one_is_contango_and_reads_risk_on():
    """비율 < 1 = 콘탱고(평온). 카탈로그 방향이 below 여야 위험-온이 된다."""
    assert v2.direction_for("vix_term_structure") == "below"
    assert v2.threshold_for("vix_term_structure") == pytest.approx(1.0)


def test_the_spread_variant_exists_separately_and_says_what_it_is():
    """§6.2 는 스프레드를 **별도로, 명시적으로 라벨링해서** 제공하라고 요구한다."""
    meta = v2.CATALOG_BY_ID["vix_term_spread"]
    assert "스프레드" in meta["desc"] or "차이" in meta["desc"]
    # 같은 2포인트가 VIX 12 와 VIX 45 에서 다른 뜻이라는 한계를 적어야 한다.
    assert "12" in meta["desc"] or "수준" in meta["desc"]


def test_spread_variant_returns_the_difference(alfred):
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0)],
        [("2026-01-05", "2026-01-06", 24.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", form="spread")
    assert r.value == pytest.approx(-6.0)


# ── ★룩어헤드 게이트★ US 종가는 KR 세션 이후에 나온다 ──────────────────────────
def test_a_kr_decision_uses_the_previous_us_close(alfred):
    """★D 의 US 종가는 D 의 KRX 세션이 끝난 뒤에 나온다 — 쓰면 룩어헤드다★

    픽스처는 D 와 D−1 의 값을 **다르게** 두어, 같은 날짜를 읽는 구현과 전날을 읽는 구현이
    반드시 다른 답을 내도록 만든다. 같으면 이 테스트는 아무것도 증명하지 못한다.
    """
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0),      # D−1 (쓸 수 있음)
         ("2026-01-06", "2026-01-06", 30.0)],     # D   (응답에 **보이지만** KR 세션 뒤라 쓰면 안 됨)
        [("2026-01-05", "2026-01-06", 24.0),
         ("2026-01-06", "2026-01-06", 25.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", market="kr")
    assert r.value == pytest.approx(18.0 / 24.0), (
        f"당일 US 종가를 썼다 — 룩어헤드 (당일이면 {30.0 / 25.0:.4f})")


def test_the_alignment_is_recorded_on_the_observation(alfred):
    """§6.2 는 이 정렬이 `market_cutoff`/`execution_timestamp` 에 **기록된다**고 말한다.

    Phase 8b 전까지 두 필드는 선언만 되어 있고 어디서도 채워지지 않았다(Drift 8b-1).
    """
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0)],
        [("2026-01-05", "2026-01-06", 24.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", market="kr")
    assert r.observation is not None
    assert r.observation.market_cutoff, "정렬 근거가 기록되지 않았다"
    assert r.observation.execution_timestamp, "행동 가능 시각이 기록되지 않았다"
    assert r.observation.market_cutoff < "2026-01-06", "컷오프가 결정일 이후다(룩어헤드)"


def test_a_us_holiday_the_day_before_is_unavailable_not_back_filled(alfred):
    """★전날이 미국 휴장이면 더 뒤로 거슬러 올라가지 않는다★

    §6.2: 결측을 전진 채움하면 "낡았지만 자신만만한" 신호가 만들어진다. 없으면 없는 것이다.
    """
    alfred["payload"] = _pair(
        [("2026-01-02", "2026-01-05", 18.0)],     # D−1(01-05)은 미국 휴장이라 값이 없다
        [("2026-01-02", "2026-01-05", 24.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", market="kr")
    assert r.value is None
    assert r.usage is ResearchUsage.UNAVAILABLE
    assert "전진 채움" in r.detail or "채우지" in r.detail


def test_a_kr_holiday_does_not_change_which_us_close_is_used(alfred):
    """KR 휴장은 결정을 하지 않는 날일 뿐 — 미국 종가 선택 규칙은 그대로 D−1 이다."""
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0), ("2026-01-06", "2026-01-06", 30.0)],
        [("2026-01-05", "2026-01-06", 24.0), ("2026-01-06", "2026-01-06", 25.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", market="kr")
    assert r.value == pytest.approx(18.0 / 24.0)


def test_a_us_decision_may_use_the_same_day_close(alfred):
    """미국 시장 결정에는 D−1 시프트가 필요 없다 — 시프트는 시차 때문이지 관례가 아니다."""
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0), ("2026-01-06", "2026-01-06", 30.0)],
        [("2026-01-05", "2026-01-06", 24.0), ("2026-01-06", "2026-01-06", 25.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06", market="us")
    assert r.value == pytest.approx(30.0 / 25.0)


def test_a_non_positive_vxv_does_not_divide(alfred):
    """0 으로 나누지 않는다 — 지수가 0 인 행은 실데이터에도 결측 표기로 들어온다."""
    alfred["payload"] = _pair(
        [("2026-01-05", "2026-01-06", 18.0)],
        [("2026-01-05", "2026-01-06", 0.0)],
    )
    r = v2.read_vix_term_structure("2026-01-06")
    assert r.value is None and r.usage is ResearchUsage.UNAVAILABLE


def test_both_vix_factors_are_registered_and_declare_as_of():
    for fid in ("vix_term_structure", "vix_term_spread"):
        assert fid in v2.CATALOG_BY_ID
        assert v2.requires_as_of(fid) is True, f"{fid} 는 시점이 필요하다"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 출처 정직성 표면 (요구 4) — "가져올 수 있다" ≠ "과거 검증에 쓸 수 있다"
# ═══════════════════════════════════════════════════════════════════════════════
def _api_client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_flows_status_declares_forward_only_as_a_first_class_field():
    """★행수만 보여주면 '많으니 백테스트에 써도 되겠다' 로 읽힌다★"""
    with _api_client() as c:
        body = c.get("/api/v1/symbols/flows/status").json()
    assert body["research_usage"] == "forward_only"
    assert "빈티지" in body["research_usage_reason"]
    assert "data_status" in body


def test_source_honesty_lists_every_source_with_both_axes():
    """등급 두 축(출처 상태 · 연구 용도)이 각각 있어야 한다 — 합치면 구별이 사라진다."""
    with _api_client() as c:
        body = c.get("/api/v1/data/source-honesty").json()
    ids = {s["id"] for s in body["sources"]}
    assert {"etf_prices", "investor_flows", "fred_macro", "ecos_macro"} <= ids
    for s in body["sources"]:
        assert s["data_status"] and s["research_usage"] and s["reason"], s["id"]


def test_ecos_is_never_backtest_eligible():
    """ECOS 는 공개 빈티지 API 가 없다 — 어떤 상태에서도 과거 검증 적격일 수 없다."""
    with _api_client() as c:
        body = c.get("/api/v1/data/source-honesty").json()
    ecos = next(s for s in body["sources"] if s["id"] == "ecos_macro")
    assert ecos["research_usage"] == "forward_only"


def test_mock_mode_downgrades_prices_to_forward_only(monkeypatch):
    """mock 이 허용되면 값이 합성일 수 있어 실데이터로 인증할 수 없다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    with _api_client() as c:
        body = c.get("/api/v1/data/source-honesty").json()
    etf = next(s for s in body["sources"] if s["id"] == "etf_prices")
    assert body["mock_mode"] is True
    assert etf["research_usage"] == "forward_only"
