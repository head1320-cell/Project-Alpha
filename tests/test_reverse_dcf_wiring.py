"""역DCF 배선 — 스냅샷 컬럼 · 라이브 엔드포인트 (P2-2 커밋 ②)

엔진만 짓고 소비자를 안 만들면 이 저장소의 재발 패턴을 하나 더 만드는 것이다
(`attach_evidence` 는 M1-V 전까지 호출자 0 · `portfolio_rebalancer.py` 는 오늘도 0).
그래서 스냅샷 컬럼과 라이브 라우트를 함께 낸다.

그리고 P2-1 이 실측한 결함 하나를 여기서 되풀이하지 않는지 본다 — **딥 탭이 같은
재무이력을 3번 읽던 것.** 스냅샷 하나를 만들면서 밸류에이션과 역DCF 가 각자 재무를
불러오면 같은 잘못을 안에서 반복하는 것이다.
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
RD = f"/api/v1/company/{CODE}/reverse-dcf"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def mem_cs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(cs, "_engine", lambda: eng)
    monkeypatch.setattr(cs, "_inited", False)
    yield eng
    eng.dispose()


def _snap(**kw) -> dict:
    sid = bld.build_and_store(CODE, price=PRICE, **kw)
    assert sid
    out = cs.get_snapshot(sid)
    assert out is not None
    return out


# ── 1. 라이브 라우트 ────────────────────────────────────────────────────────
def test_the_route_is_registered_alongside_the_existing_three(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/company/{code}/reverse-dcf" in paths
    # ★가산이다★ 기존 셋은 그대로 있다.
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep"):
        assert p in paths


def test_the_route_answers_with_the_implied_assumption(client):
    r = client.get(RD, params={"price": PRICE})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True, b["reason"]
    assert b["code"] == CODE
    assert isinstance(b["implied_growth_pct"], float)
    # 우리 가정과의 격차가 곧 논지다 — 셋이 함께 나온다.
    assert b["current_growth_pct"] is not None
    assert b["gap_pp"] == pytest.approx(
        b["implied_growth_pct"] - b["current_growth_pct"], abs=0.02)


def test_an_unsolvable_case_is_200_with_a_reason_not_an_error(client):
    """★근이 없는 것은 서버 장애가 아니라 그 기업에 대한 사실이다★

    500 이나 422 로 뭉개면 화면이 "서버 오류" 로 읽고, 사용자는 그것이 기업의 성질인지
    시스템 문제인지 구분할 수 없다.
    """
    r = client.get(RD, params={"price": 50_000_000})
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is False
    assert b["direction"] == "above_bracket"
    assert b["reason"]


def test_the_bracket_is_validated_before_any_work(client):
    # -1 이하는 (1+g) 가 0 이하가 되어 FCF 궤적이 의미를 잃는다.
    assert client.get(RD, params={"price": PRICE, "bracket_lo": -1.5}).status_code == 422
    assert client.get(RD, params={"price": -1}).status_code == 422


# ── 2. 스냅샷 컬럼 ─────────────────────────────────────────────────────────
def test_the_snapshot_carries_the_implied_assumptions(mem_cs):
    imp = _snap()["implied"]
    assert imp is not None
    assert imp["available"] is True, imp.get("reason")
    assert isinstance(imp["implied_growth_pct"], float)
    assert imp["implied_fcf_margin_pct"]["assumes_flat_revenue"] is True


def test_the_builder_calls_reverse_dcf_rather_than_copying_it(mem_cs, monkeypatch):
    """★짝★ 원본을 갈아끼우면 스냅샷도 바뀐다 — 복제본이 아니라 호출이다."""
    monkeypatch.setattr("src.engine.valuation.reverse_dcf.reverse_dcf",
                        lambda fs, params, price, **kw: {"available": True,
                                                         "marker": "재정의됨"})
    assert _snap()["implied"] == {"available": True, "marker": "재정의됨"}


def test_a_dead_reverse_dcf_does_not_kill_the_snapshot(mem_cs, monkeypatch):
    def _boom(fs, params, price, **kw):
        raise RuntimeError("역산 실패")
    monkeypatch.setattr("src.engine.valuation.reverse_dcf.reverse_dcf", _boom)

    snap = _snap()
    assert snap["implied"]["available"] is False
    assert "RuntimeError" in snap["implied"]["reason"]
    # 나머지는 굳는다.
    assert snap["valuation"]["available"] is True
    assert "implied" in snap["provenance"]["unavailable_sections"]


def test_no_price_means_no_implied_section_rather_than_a_fake_one(mem_cs, monkeypatch):
    monkeypatch.setattr(bld, "_resolve_price", lambda code, price: (None, "unavailable"))
    sid = bld.build_and_store(CODE)
    imp = cs.get_snapshot(sid)["implied"]
    assert imp["available"] is False
    assert "현재가" in imp["reason"]


# ── 3. ★컬럼 플래그가 False 여도 조회가 안 깨진다★ (`add_columns` 계약) ─────
def test_a_missing_column_makes_the_section_vanish_not_the_query(mem_cs, monkeypatch):
    """있는 척하고 SELECT 하면 조회 **전체**가 깨진다 — 컬럼이 없는 것보다 나쁘다."""
    sid = bld.build_and_store(CODE, price=PRICE)
    assert sid

    monkeypatch.setattr(cs, "_has_implied_col", False)
    got = cs.get_snapshot(sid)
    assert got is not None, "컬럼이 없다고 조회가 죽으면 안 된다"
    assert "implied" not in got
    # 나머지 섹션은 멀쩡히 나온다.
    assert got["valuation"]["available"] is True
    rows = cs.list_snapshots(code=CODE)
    assert rows and "implied" not in rows[0]["sections_available"]


# ── 4. ★재무를 한 번만 읽는다★ (P2-1 이 실측한 3회 읽기를 반복하지 않는다) ──
def test_the_valuation_and_reverse_dcf_share_one_statement_read(mem_cs, monkeypatch):
    """밸류에이션과 역DCF 가 **같은 준비된 `fs`** 를 쓴다.

    ★처음에는 "스냅샷 하나에 재무를 한 번만 읽는다" 로 걸었다가 9번이 나왔다.★
    코드를 보니 대부분이 `comps_table` 의 피어 밸류에이션이었다(`000660`·`042700`·
    `011070`…) — 피어마다 재무를 읽는 것은 comps 표가 **하는 일**이지 이 슬라이스가
    만든 중복이 아니다. 내가 지을 수 있는 주장으로 범위를 좁힌다: `_valuation` 과
    `_implied` 는 한 번의 읽기를 나눠 쓴다.

    (스냅샷 전체의 읽기 횟수를 줄이는 것은 `comps_table` 의 48쿼리를 다루는 별개
    슬라이스다 — P2-1 이 그 숫자를 실측해 두었다.)
    """
    from src.engine.valuation.valuation_models import ValuationEngine

    calls = []
    real = ValuationEngine.load_statement

    def _spy(self, code, price, **kw):
        calls.append(code)
        return real(self, code, price, **kw)
    monkeypatch.setattr(ValuationEngine, "load_statement", _spy)

    prepared = bld._valuation_inputs(CODE, PRICE)
    val = bld._valuation(CODE, PRICE, prepared)
    imp = bld._implied(prepared, PRICE)

    assert calls == [CODE], f"준비된 fs 를 나눠 쓰지 않는다: {calls}"
    assert val["available"] is True
    assert imp["available"] is True
    # 같은 fs 를 썼으므로 두 결과의 기준 가격이 일치한다.
    assert imp["market_price"] == val["current_price"] == PRICE


# ── 5. 기존 세 엔드포인트 불변 ──────────────────────────────────────────────
def test_the_existing_company_endpoints_still_answer(client):
    assert client.get(f"/api/v1/company/{CODE}/financial-deep").status_code == 200
    assert client.get(f"/api/v1/company/{CODE}/risk-deep",
                      params={"price": PRICE}).status_code == 200
    r = client.get(f"/api/v1/company/{CODE}/valuation-sandbox", params={"price": PRICE})
    assert r.status_code == 200
    # 역DCF 는 별도 엔드포인트다 — 기존 응답에 키를 밀어 넣지 않았다.
    assert "implied_growth_pct" not in r.json()
