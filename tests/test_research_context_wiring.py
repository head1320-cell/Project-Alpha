"""ResearchContext 배선 — 복사본 제거 + 최소 노출 (벤치마크 §4)

★이 파일이 거는 것★
  1. ★네 저장소가 같은 출처를 쓴다★ 세 벌 복사가 사라지고, 갈라졌던
     `backtest_runs` 의 `APP_VERSION` 폴백이 복구된다.
  2. 라우트의 `as_of` 422 동작 **불변** — 정책만 단일화한다.
  3. 응답이 **선언하지 않은 절단일**을 그렇다고 말한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402

URL = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _body(**kw) -> dict:
    base = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000, "model": "mvo"}
    base.update(kw)
    return base


# ── 1. ★단일 출처★ ───────────────────────────────────────────────────────
def test_the_stores_share_one_code_version():
    """★세 벌 복사가 사라졌다★ 같은 함수 객체여야 한다."""
    from src.data.company_snapshots import code_version as cs_cv
    from src.data.regime_snapshots import code_version as rgs_cv
    from src.data.research_runs import code_version as rr_cv
    from src.engine.research_context import code_version as canonical

    assert rgs_cv is canonical
    assert cs_cv is canonical
    assert rr_cv is canonical


def test_the_borrowed_import_still_works():
    """★공개 표면 유지★ `target_versions` 가 `research_runs` 에서 빌려 쓴다."""
    from src.data.research_runs import code_version
    assert callable(code_version) and isinstance(code_version(), str)


def test_the_backtest_engine_version_recovers_the_app_version_fallback(monkeypatch):
    """★갈라졌던 폴백이 복구된다★ (교정 전 코드에서 red)

    `backtest_runs.engine_version` 은 `BACKTEST_ENGINE_VERSION or GIT_SHA or "dev"`
    였다 — `APP_VERSION` 만 설정한 환경에서 **백테스트 기록만** "dev" 가 됐다.
    """
    monkeypatch.delenv("BACKTEST_ENGINE_VERSION", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("APP_VERSION", "app-42")

    import src.data.backtest_runs as br
    from src.engine.research_context import code_version
    assert code_version() == "app-42"
    assert br.engine_version() == "app-42", "백테스트만 다른 값을 쓰면 안 된다"


def test_the_backtest_override_still_wins(monkeypatch):
    """★짝★ `BACKTEST_ENGINE_VERSION` 의 우선순위는 그대로다."""
    monkeypatch.setenv("BACKTEST_ENGINE_VERSION", "bt-9")
    monkeypatch.setenv("APP_VERSION", "app-42")
    monkeypatch.setenv("GIT_SHA", "sha-1")
    import src.data.backtest_runs as br
    assert br.engine_version() == "bt-9"


def test_all_four_agree_when_no_override(monkeypatch):
    monkeypatch.delenv("BACKTEST_ENGINE_VERSION", raising=False)
    monkeypatch.setenv("GIT_SHA", "sha-777")
    import src.data.backtest_runs as br
    from src.data.company_snapshots import code_version as cs_cv
    from src.data.regime_snapshots import code_version as rgs_cv
    from src.data.research_runs import code_version as rr_cv
    assert {rgs_cv(), cs_cv(), rr_cv(), br.engine_version()} == {"sha-777"}


# ── 2. ★as_of 정책은 단일화하되 동작은 불변★ ────────────────────────────
def test_a_future_as_of_is_still_a_422(client):
    future = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(URL, json=_body(as_of=future))
    assert r.status_code == 422, r.text


def test_a_past_as_of_is_accepted(client):
    r = client.post(URL, json=_body(as_of="2025-06-30"))
    assert r.status_code == 200, r.text


def test_the_route_policy_comes_from_the_engine(monkeypatch, client):
    """★정책이 하나다★ 엔진 규칙을 바꾸면 라우트가 따라온다."""
    import src.api.allocation_routes as ar
    monkeypatch.setattr(ar, "validate_as_of", lambda a: "엔진이 거부함")
    r = client.post(URL, json=_body(as_of="2025-06-30"))
    assert r.status_code == 422
    assert "엔진이 거부함" in r.text


# ── 3. ★응답이 무엇을 선언했는지 말한다★ ────────────────────────────────
def _post(client, **kw) -> dict:
    r = client.post(URL, json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


def test_the_response_carries_a_research_context(client):
    rc = _post(client)["research_context"]
    assert rc["fingerprint"] and len(rc["fingerprint"]) == 16
    assert rc["code_version"] and rc["data_source"] in ("mock", "db", "unknown")


def test_it_says_which_cutoffs_were_never_declared(client):
    """★§4 의 hidden date★ 비어 있음은 '자른 적이 없다' 는 뜻이다."""
    rc = _post(client)["research_context"]
    assert set(rc["cutoffs_unspecified"]) == {
        "market_data_as_of", "fundamental_data_as_of", "macro_data_as_of"}
    assert rc["cutoffs_declared"] == {}
    assert "자른 적이 없다" in rc["note"]


def test_the_as_of_reaches_the_context(client):
    rc = _post(client, as_of="2025-06-30")["research_context"]
    assert rc["as_of"] == "2025-06-30"
    assert rc["information_cutoff"] == "2025-06-30"


def test_the_same_request_gives_the_same_fingerprint(client):
    """§36 — 같은 Context → 같은 지문."""
    a = _post(client, as_of="2025-06-30")["research_context"]["fingerprint"]
    b = _post(client, as_of="2025-06-30")["research_context"]["fingerprint"]
    assert a == b


def test_a_different_as_of_gives_a_different_fingerprint(client):
    """★짝★ 항상 같으면 지문이 아무것도 말하지 않는다."""
    a = _post(client, as_of="2025-06-30")["research_context"]["fingerprint"]
    b = _post(client, as_of="2024-06-30")["research_context"]["fingerprint"]
    assert a != b


def test_the_neighbours_are_untouched(client):
    paths = {r.path for r in client.app.routes}
    for p in ("/api/v1/allocation/analyze", "/api/v1/allocation/exposures",
              "/api/v1/allocation/implement", URL):
        assert p in paths, p
