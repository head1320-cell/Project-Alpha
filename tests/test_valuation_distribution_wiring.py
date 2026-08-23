"""확률적 밸류에이션 배선 — 스냅샷 컬럼 · 라이브 엔드포인트 (P2-3 커밋 ②)

★이 파일이 새로 거는 것: 후행 컬럼 플래그의 **독립성**★
P2-2 는 `_has_implied_col` 이라는 단일 bool 이었다. 둘째 컬럼이 붙는 순간 그 모양이
무너진다 — 두 컬럼은 독립적으로 붙거나 안 붙으므로 하나의 플래그로 가리면 조회 열
목록이 어긋난다. `regime_snapshots` 가 `regime`·MES·`regime_path` 를 세 개의 독립
플래그로 든 것과 같은 이유이고, 여기서 그 독립성을 직접 건다.
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
VD = f"/api/v1/company/{CODE}/valuation-distribution"


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
def test_the_route_is_registered_alongside_the_existing_four(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/company/{code}/valuation-distribution" in paths
    # ★가산이다★ 기존 넷은 그대로 있다.
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep",
              "/api/v1/company/{code}/reverse-dcf"):
        assert p in paths


def test_the_route_answers_with_quantiles_and_the_price_percentile(client):
    r = client.get(VD, params={"price": PRICE, "n": 400})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True, b["reason"]
    u = b["unified"]
    assert u["p10"] <= u["p25"] <= u["p50"] <= u["p75"] <= u["p90"]
    assert 0.0 <= u["price_percentile"] <= 100.0
    # 재현 좌표가 응답에 남는다.
    assert b["seed"] and b["n_requested"] == 400


def test_the_route_never_hides_the_model_disagreement(client):
    """★통합값만 내면 더 큰 쪽이 평균에 지워진다★"""
    b = client.get(VD, params={"price": PRICE, "n": 400}).json()
    assert set(b["by_model"]) == {"RIM", "DCF", "DDM"}
    assert b["model_disagreement"]["spread_ratio"] > 1.0
    # 폭이 가정임을 응답이 스스로 말한다.
    assert all(v["measured"] is False for k, v in b["widths"].items()
               if isinstance(v, dict) and "measured" in v)


def test_an_unavailable_result_passes_through_as_200(client, monkeypatch):
    """★산출 불가는 서버 장애가 아니라 그 종목에 대한 사실이다★

    500 으로 뭉개면 화면은 "서버 오류" 로 읽고, 사용자는 종목의 성질인지 시스템
    문제인지 구분할 수 없다.

    ★이 가지를 자연스러운 종목으로는 열 수 없다★ 처음에는 없는 코드(`999999`)로
    걸었는데 **mock DART 가 아무 코드에나 재무를 합성**해서 available:true 가 나왔다.
    실 키 환경이나 표본이 얇은 종목에서만 열리는 가지이므로, 엔진이 사유를 돌려줄 때
    라우트가 그것을 **그대로 통과시키는지**를 직접 건다.
    """
    monkeypatch.setattr(
        "src.engine.valuation.valuation_distribution.valuation_distribution_for",
        lambda code, price, n=2000, **kw: {
            "available": False, "unified": None,
            "reason": "유효 표본이 12개뿐이라(200개 중) 분위수를 낼 수 없습니다"})

    r = client.get(VD, params={"price": PRICE, "n": 200})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False
    assert b["unified"] is None
    assert "유효 표본" in b["reason"]


def test_the_sample_count_is_validated_before_any_work(client):
    assert client.get(VD, params={"price": PRICE, "n": 5}).status_code == 422
    assert client.get(VD, params={"price": PRICE, "n": 10**9}).status_code == 422
    assert client.get(VD, params={"price": -1}).status_code == 422


# ── 2. 스냅샷 컬럼 ─────────────────────────────────────────────────────────
def test_the_snapshot_carries_the_distribution(mem_cs):
    d = _snap()["valuation_dist"]
    assert d is not None
    assert d["available"] is True, d.get("reason")
    assert d["unified"]["p10"] <= d["unified"]["p90"]
    assert d["seed"]


def test_the_builder_calls_the_engine_rather_than_copying_it(mem_cs, monkeypatch):
    """★짝★ 원본을 갈아끼우면 스냅샷도 바뀐다 — 복제본이 아니라 호출이다."""
    monkeypatch.setattr(
        "src.engine.valuation.valuation_distribution.valuation_distribution",
        lambda fs, params, price, **kw: {"available": True, "marker": "재정의됨"})
    assert _snap()["valuation_dist"] == {"available": True, "marker": "재정의됨"}


def test_a_dead_engine_does_not_kill_the_snapshot(mem_cs, monkeypatch):
    def _boom(fs, params, price, **kw):
        raise RuntimeError("표본 실패")
    monkeypatch.setattr(
        "src.engine.valuation.valuation_distribution.valuation_distribution", _boom)

    snap = _snap()
    assert snap["valuation_dist"]["available"] is False
    assert "RuntimeError" in snap["valuation_dist"]["reason"]
    # 나머지는 굳는다 — 역DCF 도 멀쩡하다.
    assert snap["valuation"]["available"] is True
    assert snap["implied"]["available"] is True


def test_no_price_means_no_distribution_rather_than_a_fake_one(mem_cs, monkeypatch):
    monkeypatch.setattr(bld, "_resolve_price", lambda code, price: (None, "unavailable"))
    sid = bld.build_and_store(CODE)
    d = cs.get_snapshot(sid)["valuation_dist"]
    assert d["available"] is False
    assert "현재가" in d["reason"]


# ── 3. ★후행 컬럼 플래그가 서로 독립이다★ (이 파일이 새로 거는 것) ──────────
def test_each_late_column_has_its_own_flag(mem_cs):
    """플래그를 하나로 뭉치면 둘째 컬럼이 붙는 순간 조회 열이 어긋난다."""
    assert set(cs._LATE_COLUMNS) >= {"implied", "valuation_dist"}
    assert set(cs._late_ok) == set(cs._LATE_COLUMNS)
    assert all(isinstance(v, bool) for v in cs._late_ok.values())


@pytest.mark.parametrize("missing,present", [("implied", "valuation_dist"),
                                             ("valuation_dist", "implied")])
def test_one_missing_column_does_not_hide_the_other(mem_cs, monkeypatch,
                                                    missing, present):
    """★단일 플래그였다면 둘이 함께 사라진다★ 그것이 이 테스트의 존재 이유다."""
    sid = bld.build_and_store(CODE, price=PRICE)
    assert sid

    monkeypatch.setattr(cs, "_late_ok", {**cs._late_ok, missing: False})
    got = cs.get_snapshot(sid)
    assert got is not None, "컬럼이 없다고 조회가 죽으면 안 된다"
    assert missing not in got
    assert present in got, f"{missing} 가 없다고 {present} 까지 사라졌다"
    # 기본 섹션도 멀쩡하다.
    assert got["valuation"]["available"] is True

    rows = cs.list_snapshots(code=CODE)
    assert rows and missing not in rows[0]["sections_available"]


# ── 4. ★재무 읽기가 늘지 않는다★ (P2-2 가드의 확장) ────────────────────────
def test_the_distribution_shares_the_same_statement_read(mem_cs, monkeypatch):
    """밸류에이션·역DCF·분포 **셋이** 한 번의 재무 읽기를 나눠 쓴다.

    P2-1 이 실측한 "딥 탭 재무이력 3회 읽기" 를 스냅샷 안에서 되풀이하지 않는다.
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
    dist = bld._valuation_dist(prepared, PRICE)

    assert calls == [CODE], f"준비된 fs 를 나눠 쓰지 않는다: {calls}"
    assert val["available"] and imp["available"] and dist["available"]


# ── 5. 기존 엔드포인트 불변 ────────────────────────────────────────────────
def test_the_existing_company_endpoints_are_untouched(client):
    r = client.get(f"/api/v1/company/{CODE}/valuation-sandbox", params={"price": PRICE})
    assert r.status_code == 200
    body = r.json()
    # 분포는 별도 엔드포인트다 — 기존 응답에 키를 밀어 넣지 않았다.
    assert "unified" not in body or "p10" not in (body.get("unified") or {})
    assert "by_model" not in body
    assert client.get(f"/api/v1/company/{CODE}/reverse-dcf",
                      params={"price": PRICE}).status_code == 200
