"""BG5 · 멀티전략 문 — 등록 · 출처 · ★실물 E2E(mock)★ (R1~R3 을 문으로 잇는다)
==============================================================================
스펙 §4.4·§4.5 · 대상 `src/api/stage11_routes.py` · `src/api/stage12_routes.py` ·
`src/engine/multi_strategy_backtest.py`(저장) · `src/engine/attribution_decomposer.py`(이름)

## 거는 것

- `GET/POST /api/v1/multibacktest/strategies` · `DELETE .../strategies/{id}` —
  ★`/{run_id}` 보다 먼저★ 등록돼야 `strategies` 가 정수 파싱 422 로 새지 않는다.
- 등록 거절은 **409 + 사유**(재현 불일치면 첫 불일치 날짜까지). 없는 id 비활성은 404.
- 결과에 `sources` 블록 — 전략별 원천 실행 · mock · PIT · 재현. ★`perf_label` 은
  원천 실행들의 mock 여부로★ (하나라도 mock → mock, 모르는 것이 섞이면 미상).
- ★실물 E2E(mock)★ — 저장된 백테스트 둘 → 문으로 등록 → 멀티백테스트
  inverse_vol·hrp 완주·저장 → 조회 · 기여도 분해(이름이 레지스트리에서 온다).
- 반사실: 기준 구성에서 **같은 계산**이 되는 비교(매크로 오버레이 · HRP 가치)는
  구조적 0 이라 `None` + 사유.

★숫자는 아무것도 말하지 않는다★ — 결정적 합성 계열이다(`tests/test_strategy_registry.py`).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_strategy_registry import _registry, _req, _stored_run, db, market  # noqa: F401

_S = "/api/v1/multibacktest"


@pytest.fixture
def client(db, market, monkeypatch):
    """문이 쓰는 DB 를 픽스처 DB 로 — 레지스트리·멀티백테스트·귀인이 같은 엔진을 본다."""
    import src.database as database
    monkeypatch.setattr(database, "get_sync_engine", lambda: db)
    from src.app_factory import create_app
    return TestClient(create_app())


def _two_runs():
    a = _stored_run(_req())
    b = _stored_run(_req(sell_conditions=[
        {"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 3}]))
    return a, b


_RUN = {"start_date": "2023-06-01", "end_date": "2024-03-01",
        "allocation_method": "hrp", "rebalance_policy": "monthly",
        "macro_overlay_enabled": False, "lookback_days": 60}


# ── 등록 문 ──────────────────────────────────────────────────────────

def test_the_strategies_path_is_not_swallowed_by_run_id(client):
    """★라우트 순서★ — `/{run_id}` 가 먼저면 `strategies` 가 정수 파싱 422 가 된다."""
    r = client.get(f"{_S}/strategies")
    assert r.status_code == 200, r.text[:300]
    assert r.json() == {"count": 0, "strategies": []}


def test_register_list_and_deactivate(client):
    rid, _ = _two_runs()
    r = client.post(f"{_S}/strategies", json={"run_id": rid, "name": "역추세 A"})
    assert r.status_code == 200, r.text[:300]
    s = r.json()
    assert isinstance(s["id"], int) and s["name"] == "역추세 A"
    assert s["source_run_id"] == rid and s["repro"]["equal"] is True
    assert s["is_mock_data"] is True
    listed = client.get(f"{_S}/strategies").json()
    assert [x["id"] for x in listed["strategies"]] == [s["id"]]
    assert client.delete(f"{_S}/strategies/{s['id']}").status_code == 200
    assert client.get(f"{_S}/strategies").json()["count"] == 0
    everything = client.get(f"{_S}/strategies", params={"active_only": False}).json()
    assert everything["count"] == 1


def test_deactivating_an_unknown_strategy_is_404(client):
    assert client.delete(f"{_S}/strategies/999").status_code == 404


def test_a_refused_registration_is_409_with_the_reason(client):
    rid, _ = _two_runs()
    assert client.post(f"{_S}/strategies", json={"run_id": rid}).status_code == 200
    r = client.post(f"{_S}/strategies", json={"run_id": rid})
    assert r.status_code == 409, r.text[:300]
    d = r.json()["detail"]
    assert d["reason"] and d["run_id"] == rid


def test_a_curve_that_no_longer_reproduces_is_409_with_the_first_mismatch(client):
    def _tamper(result):
        result["backtest"]["equity_curve"][150] += 1.0

    rid = _stored_run(_req(), mutate=_tamper)
    r = client.post(f"{_S}/strategies", json={"run_id": rid})
    assert r.status_code == 409
    assert r.json()["detail"]["first_mismatch"]["index"] == 150


def test_an_unknown_run_is_409_not_500(client):
    r = client.post(f"{_S}/strategies", json={"run_id": "bt_nope"})
    assert r.status_code == 409 and r.json()["detail"]["reason"]


# ── 출처 · 라벨 (순수) ────────────────────────────────────────────────

def test_the_label_comes_from_the_sources():
    """★하나라도 mock → mock · 전부 실데이터 → 실데이터 · 모르는 것이 섞이면 미상★"""
    from src.api.stage11_routes import _label_from_sources
    mock = {"is_mock_data": True}
    real = {"is_mock_data": False}
    unk = {"is_mock_data": None}
    assert _label_from_sources([real, mock])["data_real"] is False
    assert _label_from_sources([real, real])["data_real"] is True
    assert _label_from_sources([real, unk])["data_real"] is None
    assert _label_from_sources([mock, unk])["data_real"] is False
    assert _label_from_sources([])["data_real"] is None


def test_sources_say_so_when_a_strategy_is_not_registered(db, market):
    from src.api.stage11_routes import _sources
    out = _sources(db, [424242])
    assert out["available"] is True
    [s] = out["strategies"]
    assert s["registered"] is False and s["reason"] and s["is_mock_data"] is None


def test_sources_are_unavailable_with_a_reason_when_the_registry_cannot_be_read():
    from src.api.stage11_routes import _sources
    out = _sources(object(), [1])
    assert out["available"] is False and out["reason"]
    assert out["strategies"] == []


# ── ★실물 E2E(mock)★ ─────────────────────────────────────────────────

def test_end_to_end_register_then_run_both_methods_and_read_back(client):
    a, b = _two_runs()
    ids = [client.post(f"{_S}/strategies", json={"run_id": r}).json()["id"] for r in (a, b)]

    for method in ("inverse_vol", "hrp"):
        r = client.post(f"{_S}/run", json={**_RUN, "strategy_ids": ids,
                                             "allocation_method": method, "save": True})
        assert r.status_code == 200, r.text[:300]
        out = r.json()
        assert out["success"] is True, out.get("message")
        assert isinstance(out["run_id"], int) and out["run_id"] > 0
        assert out["summary"]["netting"]["basis"] == "measured_holdings"
        src = out["sources"]
        assert src["available"] is True
        assert [s["strategy_id"] for s in src["strategies"]] == ids
        assert all(s["source_run_id"] in (a, b) and s["repro_equal"] is True
                   for s in src["strategies"])
        # ★원천이 mock 이면 결과도 mock★
        assert out["perf_label"]["data_real"] is False
        assert out["cost_model"]

        got = client.get(f"{_S}/{out['run_id']}").json()
        assert got["run"]["allocation_method"] == method
        assert got["perf_label"]["data_real"] is False
        assert [s["strategy_id"] for s in got["sources"]["strategies"]] == ids

        attr = client.get(f"{_S}/{out['run_id']}/attribution").json()
        assert attr["perf_label"]["data_real"] is False
        names = {c["strategy_id"]: c["strategy_name"]
                 for c in attr["strategy_contribution"]}
        assert set(names) == set(ids) and all(names.values()), names

    runs = client.get(f"{_S}/runs").json()["runs"]
    assert len(runs) == 2


def test_end_to_end_realism_carries_sources_and_the_regime_adaptive_block(client):
    a, b = _two_runs()
    ids = [client.post(f"{_S}/strategies", json={"run_id": r}).json()["id"] for r in (a, b)]
    r = client.post("/api/v1/realism/backtest",
                    json={**_RUN, "strategy_ids": ids, "enable_cash_yield": False})
    assert r.status_code == 200, r.text[:300]
    out = r.json()
    assert out["success"] is True, out.get("message")
    assert out["perf_label"]["data_real"] is False
    assert len(out["sources"]["strategies"]) == 2
    ra = out["regime_adaptive"]
    assert ra["enabled"] is True
    # ★systemic_risk 를 한 번도 못 봤다 — 모드는 상관붕괴 진단만으로 정해졌다★
    assert ra["n_days_with_systemic_risk"] == 0
    assert ra["basis"] == "correlation_only" and ra["reason"]


def test_realism_regime_adaptive_off_says_off(client):
    """★짝★ — 꺼 두면 "상관붕괴로 정했다" 고 말하지 않는다."""
    a, b = _two_runs()
    ids = [client.post(f"{_S}/strategies", json={"run_id": r}).json()["id"] for r in (a, b)]
    out = client.post("/api/v1/realism/backtest",
                      json={**_RUN, "strategy_ids": ids, "enable_cash_yield": False,
                            "enable_regime_adaptive": False}).json()
    assert out["success"] is True, out.get("message")
    assert out["regime_adaptive"]["enabled"] is False
    assert out["regime_adaptive"]["basis"] == "off"


def test_end_to_end_counterfactual_does_not_value_structural_zeros(client):
    a, b = _two_runs()
    ids = [client.post(f"{_S}/strategies", json={"run_id": r}).json()["id"] for r in (a, b)]
    r = client.post(f"{_S}/counterfactual", json={
        "strategy_ids": ids, "start_date": _RUN["start_date"], "end_date": _RUN["end_date"],
        "base_allocation_method": "hrp", "lookback_days": 60,
        "scenarios": ["baseline", "no_macro_overlay", "no_netting", "inverse_vol"]})
    assert r.status_code == 200, r.text[:300]
    out = r.json()
    dv = out["decision_values"]
    # 기준이 hrp 라 매크로 오버레이는 켜든 끄든 같은 계산이다 — 가치가 아니다.
    assert dv["macro_overlay_value_pct"] is None and dv["macro_overlay_value_reason"]
    assert dv["netting_value_pct"] is None and dv["netting_measured_savings"] > 0
    # ★짝★ HRP vs 역변동은 다른 계산이라 수가 있다.
    assert isinstance(dv["hrp_vs_inverse_vol_value_pct"], float)
    assert out["perf_label"]["data_real"] is False
    assert len(out["sources"]["strategies"]) == 2


def test_decision_values_between_identical_computations_are_not_values():
    """★같은 계산의 차이는 구조적 0★ — 기준 구성에 따라 어느 비교가 무의미한지 다르다."""
    from src.engine.counterfactual_analyzer import CounterfactualAnalyzer as CA

    def _dv(base_method):
        return CA._compute_decision_values([
            {"name": "baseline", "n_trading_days": 252,
             "summary": {"total_return_pct": 10.0, "sharpe_ratio": 1.0},
             "config_used": {"allocation_method": base_method}},
            {"name": "no_macro_overlay",
             "summary": {"total_return_pct": 9.0, "sharpe_ratio": .9}},
            {"name": "inverse_vol",
             "summary": {"total_return_pct": 8.0, "sharpe_ratio": .8}},
        ])

    iv = _dv("inverse_vol")
    assert iv["hrp_vs_inverse_vol_value_pct"] is None
    assert iv["hrp_vs_inverse_vol_value_reason"]
    assert iv["macro_overlay_value_pct"] is None

    h = _dv("hrp")
    assert h["hrp_vs_inverse_vol_value_pct"] == pytest.approx(2.0)   # ★짝★
    assert h["macro_overlay_value_pct"] is None

    hm = _dv("hrp_macro")                                              # ★짝★
    assert hm["macro_overlay_value_pct"] == pytest.approx(1.0)


# ── 저장 표 (방언) ────────────────────────────────────────────────────

def test_postgresql_gets_a_serial_key_not_autoincrement():
    """★PostgreSQL 에는 AUTOINCREMENT 가 없다★ — 예전에는 표 생성이 실패해 저장이 죽었다."""
    from src.engine.multibacktest_schema import MULTIBACKTEST_SCHEMA_DDL, schema_ddls
    pg = schema_ddls("postgresql")
    assert not any("AUTOINCREMENT" in d for d in pg)
    assert any("id SERIAL PRIMARY KEY" in d for d in pg)
    # ★짝★ SQLite 는 그대로 — 칸은 같고 키만 다르다.
    assert schema_ddls("sqlite") == list(MULTIBACKTEST_SCHEMA_DDL)
    assert len(pg) == len(MULTIBACKTEST_SCHEMA_DDL)


def test_the_saved_run_id_comes_from_returning_not_lastrowid():
    """`lastrowid` 는 psycopg2 에서 새 id 가 아니다 — 두 방언 다 되는 RETURNING 을 쓴다."""
    import pathlib
    src = pathlib.Path("src/engine/multi_strategy_backtest.py").read_text(encoding="utf-8")
    assert "ins.lastrowid" not in src and ") RETURNING id" in src


# ── 가용성 문 (화면이 옵션을 끄는 근거) ───────────────────────────────

def test_the_availability_route_says_what_is_unsupported(client):
    """★화면이 사유를 지어내지 않게★ — 비활성 옵션의 사유를 서버가 준다."""
    r = client.get(f"{_S}/availability")
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["available"] is True
    assert {u["feature"] for u in d["unsupported_features"]} == {"hrp_macro", "regime_change"}
    assert all(u["reason"] for u in d["unsupported_features"])


def test_the_availability_route_answers_even_when_the_core_is_missing(client, monkeypatch):
    """★짝★ — 503 을 내는 대신 "없다" 를 200 으로 말한다(화면이 그걸 그린다)."""
    from src.engine import multistrategy_availability as ma
    fake = ma.MissingModule(module="src.engine._fake_core_for_test", needed_by=("x",),
                            role="가짜 코어 모듈", reason="코어가 빠졌을 때를 흉내 내는 항목입니다.")
    monkeypatch.setattr(ma, "MISSING", (*ma.MISSING, fake))
    d = client.get(f"{_S}/availability").json()
    assert d["available"] is False and d["reason"]
