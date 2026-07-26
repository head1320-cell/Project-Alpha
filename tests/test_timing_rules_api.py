"""타이밍 팩터 카탈로그 API + 신규 시그널 카나리 라우팅 + TimingRule 세트 영속."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.api.allocation_routes as ar  # noqa: E402
import src.data.timing_rules as tr  # noqa: E402
from src.api.allocation_routes import (  # noqa: E402
    CanarySpec,
    TimingRequest,
    TimingRuleSetRequest,
    allocation_timing,
    allocation_timing_factors,
    allocation_timing_rules_delete,
    allocation_timing_rules_list,
    allocation_timing_rules_save,
)


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(tr, "_engine", lambda: eng)
    monkeypatch.setattr(tr, "_inited", False)
    yield eng
    eng.dispose()


def _patch_timing(monkeypatch):
    monkeypatch.setattr("src.engine.macro_analytics.timing_panel",
                        lambda mk: {"composite": None, "components": [], "assets": []})
    monkeypatch.setattr(ar, "_timing_holding", lambda t, mk: (t, t))


# ── 카탈로그 ─────────────────────────────────────────────────────────────────
def test_catalog_endpoint_shape():
    cat = allocation_timing_factors()
    assert {g["family"] for g in cat["groups"]} == {
        "momentum", "deviation", "breakout", "overnight", "regime"}
    ids = {f["id"] for g in cat["groups"] for f in g["factors"]}
    # 기존 4종 + 신규 팩터가 하나의 창에 통합됨
    assert {"score_13612", "abs_mom", "ma_month", "ma_day"} <= ids          # 기존 AAS 카나리
    assert {"avg_abs_momentum", "accel_momentum", "disparity", "vol_breakout",
            "channel_breakout", "overnight_return", "defense_first"} <= ids  # 신규
    assert "point_in_time_data_timestamp" in cat["schema"]
    assert "유료" in cat["note"]      # 정직성 노트 존재


# ── 신규 시그널이 카나리 평가 경로로 라우팅 ──────────────────────────────────
def test_new_factor_signal_routes_through_canary_eval(monkeypatch):
    _patch_timing(monkeypatch)
    monkeypatch.setattr("src.engine.timing_factors.evaluate",
                        lambda fid, tk, mk, p=None: 103.0 if fid == "disparity" else None)
    # 이격도 103 < 임계 105 → below 방향이므로 통과
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="disparity",
                                             threshold=105.0, direction="below",
                                             params={"ma_days": 20})],
                        risk_on_assets=["QQQ"], risk_off_assets=["IEF"])
    out = allocation_timing(req)
    assert out["canary"]["signal"] == "risk_on"
    assert out["canary"]["details"][0]["value"] == 103.0


def test_defense_first_contrarian_direction(monkeypatch):
    """방어자산이 현금보다 강함(양수) + below 임계 → 위험-오프(역발상 부호 유지)."""
    _patch_timing(monkeypatch)
    monkeypatch.setattr("src.engine.timing_factors.evaluate", lambda fid, tk, mk, p=None: 4.0)
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="defense_first",
                                             threshold=0.0, direction="below")],
                        risk_on_assets=["QQQ"], risk_off_assets=["IEF"])
    out = allocation_timing(req)
    assert out["canary"]["signal"] == "risk_off"


def test_legacy_signals_unchanged(monkeypatch):
    """기존 4종은 그대로 기존 경로 — 신규 라우팅이 회귀를 만들지 않는다."""
    _patch_timing(monkeypatch)
    monkeypatch.setattr("src.engine.tactical_allocations._score_13612", lambda t, mk: 1.0)
    req = TimingRequest(market="kr",
                        canaries=[CanarySpec(kind="asset", id="SPY", signal="score_13612")],
                        risk_on_assets=["QQQ"], risk_off_assets=["IEF"])
    out = allocation_timing(req)
    assert out["canary"]["signal"] == "risk_on"


# ── 규칙 세트 영속 ───────────────────────────────────────────────────────────
def test_rule_set_save_normalizes_to_schema_and_roundtrips(db):
    r = allocation_timing_rules_save(TimingRuleSetRequest(
        name="가속모멘텀 + 이격도", market="kr",
        rules=[{"factor_id": "accel_momentum", "universe": ["SPY"]},
               {"factor_id": "disparity", "params": {"ma_days": 60},
                "risk_off_asset": ["SHY"], "leverage_cap": 1.0}],
        gate={"min_breadth": 1}, notes="테스트"))
    sid = r["set_id"]
    assert sid.startswith("tr_")
    # 저장 시 TimingRule 공통 스키마로 정규화 + PIT 각인
    for rule in r["rules"]:
        assert rule["point_in_time_data_timestamp"]
        assert rule["signal_family"] in ("momentum", "deviation", "breakout", "overnight", "regime")
        assert "transaction_cost_and_slippage" in rule
    assert r["rules"][1]["observation_window"]["ma_days"] == 60

    sets = allocation_timing_rules_list(limit=50)["sets"]
    got = next(s for s in sets if s["set_id"] == sid)
    assert got["name"] == "가속모멘텀 + 이격도" and got["gate"]["min_breadth"] == 1
    assert len(got["rules"]) == 2

    assert allocation_timing_rules_delete(sid)["deleted"] is True
    assert all(s["set_id"] != sid for s in allocation_timing_rules_list(limit=50)["sets"])


def test_rule_set_update_in_place(db):
    sid = allocation_timing_rules_save(TimingRuleSetRequest(
        name="v1", market="kr", rules=[{"factor_id": "abs_mom"}]))["set_id"]
    again = allocation_timing_rules_save(TimingRuleSetRequest(
        name="v2", market="us", rules=[{"factor_id": "abs_mom"}, {"factor_id": "ma_day"}],
        set_id=sid))
    assert again["set_id"] == sid
    sets = allocation_timing_rules_list(limit=50)["sets"]
    got = next(s for s in sets if s["set_id"] == sid)
    assert got["name"] == "v2" and got["market"] == "us" and len(got["rules"]) == 2
