"""CompanySnapshot 빌더 — ★계산을 옮기지 않고 호출해서 담는다★ (P2-1 커밋 ②)

이 빌더의 존재 이유는 값을 **복제**하는 것이 아니라 **참조**하는 것이다. 같은 산수를
두 곳에 두면 반드시 갈라지고, 갈라져도 타입 에러가 나지 않는다(A1 `currentSig`/`req` ·
R0 오버레이 컴파일에서 두 번 치른 값). 그래서 첫 두 테스트는 짝이다 —
"스냅샷 값이 라이브 계산과 같다" 와 "원본을 갈아끼우면 스냅샷도 바뀐다".

그리고 PIT: ★우리는 DART 재무의 실제 공표일을 모른다.★ `pit_store` 는 정적 시차
규칙으로 가용성을 판정하고, `load_history` 행에는 접수일이 없으며, 정정공시 이력도
없다. 그러므로 이 스냅샷은 `backtest_eligible` 을 주장할 수 없다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.company_snapshots as cs  # noqa: E402
import src.engine.company_snapshot_builder as bld  # noqa: E402

CODE = "005930"
PRICE = 71000.0


@pytest.fixture
def mem_cs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(cs, "_engine", lambda: eng)
    monkeypatch.setattr(cs, "_inited", False)
    yield eng
    eng.dispose()


def _build(**kw) -> dict:
    sid = bld.build_and_store(CODE, price=PRICE, **kw)
    assert sid, "스냅샷이 저장되지 않았다"
    snap = cs.get_snapshot(sid)
    assert snap is not None
    return snap


# ── 1. ★스냅샷 값이 라이브 계산과 일치한다★ ────────────────────────────────
def test_the_snapshot_carries_the_live_computation_not_a_copy(mem_cs):
    """`financial_deep` 을 직접 부른 것과 스냅샷의 `quality` 가 같다."""
    from src.engine.company_analytics import financial_deep

    snap = _build()
    assert snap["quality"] == financial_deep(CODE)


def _payload(section: dict, original: dict) -> dict:
    """빌더가 덧붙인 `available` 만 벗긴다.

    ★원본이 이미 `available` 을 말하면 아무것도 덮지 않는다★ `financial_deep` 은 재무
    미적재를 `available:false` + note 로 이미 정직하게 답하므로, 거기에 True 를 씌우면
    그 정직함이 지워진다. `comps_table`·`risk_deep` 처럼 안 말하는 엔진에만 붙는다.
    """
    if "available" in original:
        return section
    return {k: v for k, v in section.items() if k != "available"}


def test_every_section_is_a_call_into_an_existing_engine(mem_cs):
    from src.engine.company_analytics import comps_table, risk_deep

    snap = _build()
    peers, risk = comps_table(CODE), risk_deep(CODE, PRICE)
    assert _payload(snap["peers"], peers) == peers
    assert _payload(snap["risk"], risk) == risk


# ── 2. ★짝★ 원본을 갈아끼우면 스냅샷도 바뀐다 (복제본이 아니라 호출이다) ────
def test_changing_the_source_function_changes_the_snapshot(mem_cs, monkeypatch):
    """이것이 red 면 빌더가 값을 베껴 들고 있다는 뜻이다."""
    monkeypatch.setattr("src.engine.company_analytics.financial_deep",
                        lambda code: {"available": True, "marker": "재정의됨"})
    snap = _build()
    assert snap["quality"] == {"available": True, "marker": "재정의됨"}


# ── 3. ★`backtest_eligible` 을 주장하지 않는다★ ─────────────────────────────
def test_the_snapshot_never_claims_backtest_eligibility(mem_cs):
    """빈티지가 없으므로 `derive_usage` 가 forward_only 로 떨어뜨린다.

    손으로 지정한 값이 아니라 **파생된** 값이라는 것이 요점이다.
    """
    snap = _build()
    assert snap["research_usage"] == "forward_only"
    # real 도 주장하지 않는다 — 공표시각을 확정할 수 없으면 partial(또는 mock)이다.
    assert snap["data_status"] in ("mock", "partial", "unavailable")
    assert snap["data_status"] != "real"


def test_publication_dates_admit_they_are_a_rule_not_a_filing_date(mem_cs, monkeypatch):
    """★이 경고문이 이 블록의 존재 이유다★

    DART 접수일과 정정공시 이력이 없다는 사실을 값 옆에 싣지 않으면, 규칙으로
    만든 날짜가 실제 공표일처럼 읽힌다.
    """
    from src.data.dart_history import REPRT_ANNUAL

    monkeypatch.setattr("src.data.dart_history.load_history", lambda t, engine=None: [
        {"year": 2024, "reprt": REPRT_ANNUAL, "month": 12, "seq": 2024 * 12 + 12},
        {"year": 2025, "reprt": REPRT_ANNUAL, "month": 12, "seq": 2025 * 12 + 12},
    ])
    pub = _build()["publication_dates"]

    assert pub["available"] is True
    assert pub["method"] == "static_lag_rule"
    assert pub["has_vintage"] is False
    assert "실제 공표일이 아니라" in pub["warning"]
    assert "backtest_eligible" in pub["warning"]
    # 연간은 결산일 + 90일 — pit_store 의 상수를 그대로 쓴다(두 곳에 두지 않는다).
    row = next(r for r in pub["rows"] if r["year"] == 2024)
    assert row["period_end"] == "2024-12-31"
    assert row["estimated_available_from"] == "2025-03-31"
    assert row["lag_days"] == 90


def test_the_lag_constants_come_from_pit_store(mem_cs, monkeypatch):
    """상수를 베끼지 않았다는 짝 단언 — pit_store 를 바꾸면 스냅샷도 따라간다."""
    from src.data.dart_history import REPRT_ANNUAL

    monkeypatch.setattr("src.data.dart_history.load_history", lambda t, engine=None: [
        {"year": 2024, "reprt": REPRT_ANNUAL, "month": 12, "seq": 2024 * 12 + 12},
    ])
    monkeypatch.setattr("src.engine.pit_store.ANNUAL_LAG_DAYS", 120)
    pub = _build()["publication_dates"]
    assert pub["lag_days"]["annual"] == 120
    assert pub["rows"][0]["estimated_available_from"] == "2025-04-30"


# ── 4. 미가용은 사유 — 0 이 아니다 ──────────────────────────────────────────
def test_an_unloaded_financial_series_is_a_reason_not_a_zero(mem_cs, monkeypatch):
    monkeypatch.setattr("src.data.dart_history.load_history", lambda t, engine=None: [])
    snap = _build()

    assert snap["financials"]["available"] is False
    assert snap["financials"]["reason"]
    assert "rows" not in snap["financials"], "값을 지어내지 않는다"
    assert snap["publication_dates"]["available"] is False
    # provenance 가 어느 섹션이 왜 비었는지 한 곳에 모아 말한다.
    prov = snap["provenance"]
    assert "financials" in prov["unavailable_sections"]
    assert prov["reasons"]["financials"]


def test_a_dead_section_does_not_kill_the_snapshot(mem_cs, monkeypatch):
    """★한 섹션이 죽어도 스냅샷은 산다★ 실패는 사유가 되고 나머지는 굳는다."""
    def _boom(code):
        raise RuntimeError("피어 조회 실패")
    monkeypatch.setattr("src.engine.company_analytics.comps_table", _boom)

    snap = _build()
    assert snap["peers"]["available"] is False
    assert "RuntimeError" in snap["peers"]["reason"]
    # 나머지는 멀쩡하다.
    assert snap["risk"]["available"] is not None
    assert snap["provenance"]["available"] is True


def test_no_price_means_no_price_dependent_sections_not_a_fake_price(mem_cs, monkeypatch):
    """가격을 못 구하면 지어내지 않는다 — 그 섹션을 산출하지 않고 사유를 남긴다."""
    monkeypatch.setattr(bld, "_resolve_price", lambda code, price: (None, "unavailable"))
    sid = bld.build_and_store(CODE)
    snap = cs.get_snapshot(sid)

    assert snap["price"] is None and snap["price_source"] == "unavailable"
    assert snap["valuation"]["available"] is False
    assert snap["risk"]["available"] is False
    assert "현재가" in snap["valuation"]["reason"]


# ── 5. mock 재무로 계산되면 그렇게 말한다 ───────────────────────────────────
def test_mock_financials_are_labelled_mock(mem_cs):
    """DART 키가 없는 이 환경에서는 `evaluate` 가 `is_mock=True` 를 돌려준다."""
    snap = _build()
    if not snap["valuation"].get("available"):
        pytest.skip("이 환경에서 밸류에이션이 산출되지 않는다")
    assert snap["valuation"]["is_mock"] is True
    assert snap["data_status"] == "mock"


def test_the_valuation_freezes_its_assumptions_with_the_number(mem_cs):
    """★가정 없는 적정가는 나중에 되짚을 수 없다★ 출처 라벨까지 함께 굳힌다."""
    snap = _build()
    if not snap["valuation"].get("available"):
        pytest.skip("이 환경에서 밸류에이션이 산출되지 않는다")
    a = snap["valuation"]["assumptions"]
    assert {"rf", "beta", "erp", "g", "years"} <= set(a)
    assert a["rf_source"] and a["beta_source"]


# ── 6. 가격 출처를 서버가 스탬프한다 ────────────────────────────────────────
def test_a_caller_supplied_price_is_labelled_as_such(mem_cs):
    assert _build()["price_source"] == "caller"
    assert _build()["price"] == PRICE
