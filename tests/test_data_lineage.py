"""`DataLineage` (§3.4) — 감사 A3. 값을 보여줄 때 **출처와 빈티지 기준**이 함께 간다.

11a 감사: §3.4 의 `DataLineage` 가 코드에 없었다(타입·필드·UI 0건). §8.1 표는 Phase 6 이
배달했다고 적고 있었는데 거짓이었다 — 포커스 트랩 행과 같은 종류의 오류였다.

★이 파일이 지키는 것★ 계보가 **아는 것만** 말하는지. 특히 mock 은 "허용됐다" 와
"쓰였다" 가 다르고, 후자를 주장하려면 데이터 계층 계측이 필요하다.
"""
import pytest

from src.engine import timing_factors as tf
from src.engine.data_lineage import VINTAGE_BASES, lineage_for, lineage_for_factor


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 빈티지 기준이 팩터의 실제 읽기 경로와 일치하는가
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_as_of_series_reads_on_the_alfred_vintage_path():
    """★NFCI 는 주간·개정이다★ 빈티지로 읽지 않으면 과거 채점에 미래 정보가 섞인다."""
    lin = lineage_for_factor("financial_conditions")
    assert lin.source == "fred_alfred"
    assert lin.vintage_basis == "alfred_realtime"


def test_a_series_factor_without_as_of_admits_it_reads_the_latest_revision():
    """★`indicator` 는 as_of 를 요구하지 않는다★ 그래서 최신 개정본이고, 그렇게 적어야 한다.

    여기서 `alfred_realtime` 이라고 적으면 코드가 하지 않는 일을 문서가 주장하게 된다.
    """
    lin = lineage_for_factor("indicator")
    assert lin.vintage_basis == "latest_revision"
    assert any("개정 편향" in c for c in lin.caveats), (
        "최신 개정본으로 읽으면서 그 위험을 적지 않았습니다")


def test_price_factors_declare_the_truncation_basis():
    lin = lineage_for_factor("disparity")
    assert lin.source == "price_series"
    assert lin.vintage_basis == "price_truncation"


def test_every_catalogue_factor_has_a_known_vintage_basis():
    """오타 하나가 UI 를 조용히 빈칸으로 만든다 — 열거형 밖 값을 금지한다."""
    for c in tf.CATALOG:
        lin = lineage_for(c)
        assert lin.vintage_basis in VINTAGE_BASES, f"{c['id']}: {lin.vintage_basis}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. mock 은 "허용" 이지 "사용" 이 아니다
# ═══════════════════════════════════════════════════════════════════════════════
def test_mock_is_reported_as_permission_not_as_a_claim_of_use(monkeypatch):
    """★이 구분이 이 모듈의 정직성 축이다★

    실제로 어느 계층(DB/KIS/mock)이 답했는지는 읽기마다 다르고 추적하려면 데이터 계층
    전체에 계측이 필요하다. 아는 사실(게이트 상태)만 적는다.
    """
    import src.engine.data_lineage as dl

    lin = dl.lineage_for(tf.CATALOG_BY_ID["disparity"])
    # 필드 이름 자체가 주장의 범위를 말한다
    assert hasattr(lin, "mock_fallback_allowed")
    assert not hasattr(lin, "is_mock"), (
        "실제 사용 여부를 주장하는 필드가 생겼습니다 — 추적 없이는 알 수 없습니다")


def test_mock_gate_state_is_reflected(monkeypatch):
    import src.data.mock_gate as gate

    monkeypatch.setattr(gate, "mock_allowed", lambda: False)
    lin = lineage_for(tf.CATALOG_BY_ID["disparity"])
    assert lin.mock_fallback_allowed is False
    assert not any("mock" in c for c in lin.caveats), (
        "mock 이 꺼져 있는데 mock 경고를 남겼습니다")


def test_mock_caveat_appears_when_the_gate_is_open(monkeypatch):
    import src.data.mock_gate as gate

    monkeypatch.setattr(gate, "mock_allowed", lambda: True)
    lin = lineage_for(tf.CATALOG_BY_ID["disparity"])
    assert lin.mock_fallback_allowed is True
    assert any("mock" in c for c in lin.caveats)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 없는 것은 지어내지 않는다
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_unknown_factor_has_no_lineage_rather_than_an_empty_one():
    """★빈 계보는 '출처 없음' 처럼 보인다★ 실제로는 '그런 팩터가 없다' 인데."""
    assert lineage_for_factor("존재하지_않는_팩터") is None


def test_a_sourceless_factor_says_so_and_carries_its_reason():
    lin = lineage_for_factor("borrow_short_interest")
    assert lin.source == "none"
    assert lin.vintage_basis == "not_applicable"
    assert lin.caveats and any("피드" in c or "보유" in c for c in lin.caveats)


def test_lineage_never_reaches_the_network():
    """계보는 카탈로그 메타에서 유도된다 — 조회 한 번에 API 를 때리면 창이 느려진다."""
    import src.data.etf_prices as ep

    def boom(*a, **k):
        raise AssertionError("계보가 가격 조회를 호출했습니다")

    orig = ep.daily_closes
    ep.daily_closes = boom
    try:
        lineage_for_factor("disparity")
    finally:
        ep.daily_closes = orig


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 미리보기 페이로드에 실려 나간다 (§8.1 우측 패널)
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_history_payload_carries_lineage():
    from src.engine.timing_factor_history import factor_history

    out = factor_history("disparity", "SPY", "us", months=3).to_dict()
    assert "lineage" in out and out["lineage"], "미리보기가 계보 없이 값만 보여줍니다"
    assert out["lineage"]["factor_id"] == "disparity"


def test_an_empty_history_still_explains_where_the_data_would_come_from():
    """★값이 없을 때야말로 출처가 궁금하다★ 빈 그래프에 계보까지 없으면 진단할 수 없다."""
    from src.engine.timing_factor_history import factor_history

    out = factor_history("존재하지_않는_팩터", "SPY", "us", months=3).to_dict()
    assert out["limitations"], "사유가 없습니다"
    # 카탈로그에 없는 팩터이므로 계보는 None 이 정직하다 — 빈 dict 가 아니라.
    assert out["lineage"] is None


@pytest.mark.parametrize("fid", ["financial_conditions", "curve_slope", "vix_term_structure"])
def test_revised_or_lagged_sources_ship_their_caveat(fid):
    lin = lineage_for_factor(fid)
    assert lin.release_lag, f"{fid} 에 공표 지연이 없습니다"
    assert lin.revision_policy, f"{fid} 에 개정 정책이 없습니다"
