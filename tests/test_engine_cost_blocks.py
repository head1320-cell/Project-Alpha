"""BB · ★비용을 부과하면서 말하지 않던 엔진 셋★이 `cost_model` 을 낸다
==============================================================================
대상: `src/domain/cost_model.py::policy_only_block` · 문
`src/api/stage11_routes.py`·`stage12_routes.py`·`strategy_routes.py`(graph) ·
레지스트리 `src/domain/cost_provenance.py`

## 왜 (실측 2026-09-24)

BA 가 *"`cost_model` 블록을 내는 엔진은 `kis_backtest_engine` 하나뿐"* 을 쟀다.
`multi_strategy_backtest`·`realism_engine`·`dag_runner` 는 수수료를 **부과하면서**
블록을 안 냈다 — 앞의 둘은 ★합계조차 없다★.

★세 엔진은 같은 모양이 아니다★ — `realism_engine` 은 시장충격을 **기본으로**
부과한다(ADV 가정값·변동성 고정의 다른 모델). 셋을 한 모양으로 접으면
`realism` 의 충격이 *"이 엔진엔 없다"* 로 거짓말을 한다.

## ★세 상태를 가른다★

    charged      부과했다
    off          ★있는데 껐다★ (선택)
    unsupported  ★그 성분이 이 엔진에 아예 없다★ (선택이 아니다)

`off` 로 적으면 *"켤 수 있었는데 안 켰다"* 로 읽히고, 켤 문이 없는 사용자는
문을 찾아 헤맨다. `unmeasurable` 로 적으면 *"비용이 싸게 나왔다"* 는 **경고**가
되는데 이 엔진들에서 그것은 사실이 아니라 **설계**다.
"""
from __future__ import annotations

import pytest

from src.domain.cost_model import (
    COMPONENTS,
    STATE_CHARGED,
    STATE_OFF,
    STATE_UNMEASURABLE,
    STATE_UNSUPPORTED,
    CostPolicy,
    policy_only_block,
    policy_version,
)
from src.domain.cost_provenance import rate_provenance

_BASIC = ("commission", "slippage")


def _block(**kw):
    policy = kw.pop("policy", CostPolicy(commission_bps=1.5, slippage_bps=5.0))
    kw.setdefault("engine", "multi_strategy_backtest")
    kw.setdefault("supported", _BASIC)
    kw.setdefault("provenance", rate_provenance(policy=policy))
    return policy_only_block(policy, **kw)


def _main_engine_block_keys() -> set[str]:
    """★메인 엔진이 실제로 내는 키★ — 손으로 적지 않고 엔진을 돌려 읽는다."""
    from src.kis_backtest_engine import BacktestConfig, BacktestEngine

    cfg = BacktestConfig(symbols=["000111"], strategy_name="Condition",
                         strategy_params={}, start_date="2024-01-02",
                         end_date="2024-06-28")
    eng = BacktestEngine(cfg)
    return set(eng._cost_model_block())


# ── 핵심 키 — 소비자가 어느 엔진이든 같게 읽는다 ─────────────────────────

def test_the_block_carries_every_key_the_main_engine_carries():
    """변이 a — ★공용 빌더★ 엔진마다 다른 키면 소비자가 엔진마다 달리 읽는다.

    메인 엔진의 키 집합을 **실제로 읽어** 부분집합임을 건다. 손으로 적은
    목록이면 메인 엔진이 키를 하나 더할 때 조용히 갈린다.
    """
    main = _main_engine_block_keys()
    assert main, "메인 엔진 블록을 못 읽었다 — 아래 전칭이 공허하다"
    assert main <= set(_block()), main - set(_block())


def test_the_shared_core_is_the_same_function_output():
    """★같은 이름에 같은 값★ — `policy`·`version`·`round_trip_bps`."""
    p = CostPolicy(commission_bps=1.5, slippage_bps=5.0)
    b = _block(policy=p)
    assert b["version"] == policy_version(p)
    assert b["round_trip_bps"] == pytest.approx(2 * (1.5 + 5.0))
    assert b["policy"]["commission_bps"] == 1.5
    assert b["policy"]["slippage_bps"] == 5.0


def test_the_engine_is_named():
    assert _block(engine="dag_runner")["engine"] == "dag_runner"


# ── ★미상 ≠ 0★ — 거래별로 재지 않는 엔진 ───────────────────────────────

def test_an_engine_that_does_not_count_per_trade_says_unknown_not_zero():
    """변이 b — ★`n_unmeasured_trades` 를 0 으로 적으면 "다 쟀다" 가 된다★

    이 엔진들은 거래별 분해를 **하지 않는다**. 0 은 *"못 잰 거래가 없었다"*
    는 관측이고, 실제로는 **센 적이 없다**.
    """
    b = _block()
    assert b["n_unmeasured_trades"] is None
    assert b["breakdown"] is None
    assert b["breakdown_reason"] and len(b["breakdown_reason"]) > 20


def test_the_per_component_krw_is_unknown_without_a_count():
    """★금액을 센 적이 없으면 `krw` 는 None★ — 0 이면 "비용이 없었다" 가 된다."""
    b = _block()
    for name in _BASIC:
        assert b["components"][name]["krw"] is None, name
    assert b["total_krw"] is None


# ── ★세 상태를 가른다★ ────────────────────────────────────────────────

def test_a_component_the_engine_lacks_is_unsupported_not_off():
    """변이 c — ★없는 것 ≠ 끈 것 ≠ 못 잰 것★"""
    b = _block()
    for name in ("tax", "spread", "impact"):
        c = b["components"][name]
        assert c["state"] == STATE_UNSUPPORTED, (name, c)
        assert c["state"] not in (STATE_OFF, STATE_UNMEASURABLE)
        assert c["reason"] and "multi_strategy_backtest" in c["reason"], name


def test_a_supported_component_is_charged_at_the_policy_rate():
    b = _block(policy=CostPolicy(commission_bps=1.5, slippage_bps=5.0))
    assert b["components"]["commission"] == {
        **b["components"]["commission"], "state": STATE_CHARGED, "bps": 1.5}
    assert b["components"]["slippage"]["bps"] == 5.0


def test_a_supported_component_that_was_switched_off_is_off():
    """★짝★ — `realism` 의 충격은 **있는데** 끌 수 있다. 끄면 `off` 다."""
    on = _block(engine="realism_engine",
                supported=(*_BASIC, "impact"),
                policy=CostPolicy(commission_bps=1.5, slippage_bps=5.0,
                                  charge_impact=True))
    off = _block(engine="realism_engine",
                 supported=(*_BASIC, "impact"),
                 policy=CostPolicy(commission_bps=1.5, slippage_bps=5.0,
                                   charge_impact=False))
    assert on["components"]["impact"]["state"] == STATE_CHARGED
    assert off["components"]["impact"]["state"] == STATE_OFF
    # ★세금은 여전히 없다★ — 충격을 지원한다고 나머지가 따라오지 않는다.
    assert on["components"]["tax"]["state"] == STATE_UNSUPPORTED


def test_a_charged_component_without_a_policy_rate_does_not_invent_one():
    """★다른 모델의 충격에 메인 엔진의 bps 를 적지 않는다★

    `realism` 의 충격은 `k·√참여율` 이 아니라 회전율·ADV 가정값 모델이다.
    요율이 없으면 `bps` 는 None + 사유 — 0 이면 "충격이 공짜였다" 가 된다.
    """
    b = _block(engine="realism_engine", supported=(*_BASIC, "impact"),
               policy=CostPolicy(commission_bps=1.5, slippage_bps=5.0,
                                 charge_impact=True),
               notes={"impact": "회전율·ADV 가정값 모델 — 참여율을 잰 것이 아니다"})
    c = b["components"]["impact"]
    assert c["bps"] is None
    assert "ADV" in c["reason"]


def test_every_component_is_always_present():
    """★다섯이 언제나 실린다★ — 빠진 성분은 0 이 아니라 부재이고 부재는 안 보인다."""
    assert set(_block()["components"]) == set(COMPONENTS)


def test_an_unknown_supported_name_is_refused():
    """★오타가 조용히 `unsupported` 가 되지 않는다★"""
    with pytest.raises(ValueError):
        _block(supported=("commision", "slippage"))


# ── 합계 — ★엔진이 실제로 센 것만★ ──────────────────────────────────────

def test_totals_the_engine_counted_are_carried():
    b = _block(engine="dag_runner",
               totals={"commission": 1500.0, "slippage": 500.0})
    assert b["components"]["commission"]["krw"] == 1500.0
    assert b["components"]["slippage"]["krw"] == 500.0
    assert b["total_krw"] == 2000.0


def test_a_partial_count_does_not_make_a_total():
    """★일부만 셌으면 합계는 미상★ — 센 것만 더하면 싼 합계가 된다."""
    b = _block(engine="realism_engine", supported=(*_BASIC, "impact"),
               policy=CostPolicy(commission_bps=1.5, slippage_bps=5.0,
                                 charge_impact=True),
               totals={"impact": 12345.0})
    assert b["components"]["impact"]["krw"] == 12345.0
    assert b["components"]["commission"]["krw"] is None
    assert b["total_krw"] is None


def test_a_total_for_an_unsupported_component_is_refused():
    """★없는 성분의 금액★은 모순이다 — 조용히 싣지 않는다."""
    with pytest.raises(ValueError):
        _block(totals={"tax": 1.0})


def test_the_rate_provenance_is_carried_verbatim():
    p = CostPolicy(commission_bps=1.5, slippage_bps=5.0)
    prov = rate_provenance(door="stage11_run", explicit=frozenset(),
                           available=frozenset({"commission_rate", "slippage_rate"}),
                           policy=p)
    assert _block(policy=p, provenance=prov)["rate_provenance"] == prov


# ═══════════════════════════════════════════════════════════════════════════
# BB2 · 문이 블록을 붙인다 — ★엔진 내부는 한 줄도 안 건드린다★
# ═══════════════════════════════════════════════════════════════════════════

class _Captured:
    config = None


def _fake_engine(monkeypatch, module: str, cls: str, result: dict,
                 method: str = "run"):
    """엔진을 가짜로 바꾸고 ★엔진이 실제로 받은 config★ 를 잡는다."""
    import importlib

    cap = _Captured()

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def _go(self, config, *a, **k):
            cap.config = config
            return dict(result)

    setattr(_Fake, method, _Fake._go)
    if method == "run":
        _Fake.run_and_save = _Fake._go
    monkeypatch.setattr(importlib.import_module(module), cls, _Fake)
    import src.database as db
    monkeypatch.setattr(db, "get_sync_engine", lambda: None)
    return cap


_BASE = {"strategy_ids": [1, 2], "start_date": "2024-01-02",
         "end_date": "2024-06-28"}


def _stage11_run(monkeypatch, **body):
    from src.api import stage11_routes as r
    cap = _fake_engine(monkeypatch, "src.engine.multi_strategy_backtest",
                       "MultiStrategyBacktester", {"success": True})
    out = r.multibacktest_run(r.MultiBacktestRunRequest(**{**_BASE, **body}))
    return out, cap.config


def _stage11_cf(monkeypatch, **body):
    from src.api import stage11_routes as r
    cap = _fake_engine(monkeypatch, "src.engine.counterfactual_analyzer",
                       "CounterfactualAnalyzer", {"scenarios": {}},
                       method="compare")
    out = r.multibacktest_counterfactual(r.CounterfactualRequest(**{**_BASE, **body}))
    return out, cap.config


def _stage12(monkeypatch, **body):
    from src.api import stage12_routes as r
    cap = _fake_engine(monkeypatch, "src.engine.realism_engine",
                       "RealisticBacktester",
                       {"success": True,
                        "realism_stats": {"total_market_impact_cost": 4321.0}})
    out = r.realism_backtest(r.RealismBacktestRequest(**{**_BASE, **body}))
    return out, cap.config


def _graph(monkeypatch, **body):
    import src.engine.dag_runner as dag
    from src.api import strategy_routes as r
    from src.models.graph_schema import BacktestStatistics, GraphBacktestResponse

    cap = _Captured()

    def _fake(req):
        cap.config = req
        return GraphBacktestResponse(
            success=True, statistics=BacktestStatistics(
                total_commission=1500.0, total_slippage=500.0))

    monkeypatch.setattr(dag, "execute_dag_backtest", _fake)
    req = {"nodes": [{"id": "n1", "type": "dataSource",
                      "position": {"x": 0.0, "y": 0.0},
                      "data": {"symbol": "005930"}}], **body}
    return r.graph_backtest(req), cap.config


_DOORS = [
    ("stage11_run", _stage11_run, "multi_strategy_backtest"),
    ("stage11_counterfactual", _stage11_cf, "multi_strategy_backtest"),
    ("stage12", _stage12, "realism_engine"),
    ("graph", _graph, "dag_runner"),
]


@pytest.mark.parametrize("name,call,engine", _DOORS, ids=[d[0] for d in _DOORS])
def test_each_door_attaches_a_cost_model_block(monkeypatch, name, call, engine):
    out, _ = call(monkeypatch)
    block = out["cost_model"]
    assert block["engine"] == engine
    assert block["rate_provenance"]["commission"]["door"], name


@pytest.mark.parametrize("name,call,engine", _DOORS, ids=[d[0] for d in _DOORS])
def test_the_block_rate_is_the_rate_the_engine_received(monkeypatch, name, call,
                                                        engine):
    """변이 d — ★라벨이 엔진이 받은 값과 다르면 거짓 라벨이다★

    요청 값이 아니라 **엔진이 실제로 받은 config** 와 대조한다 — 문이 중간에
    값을 바꿔도 잡힌다.
    """
    out, cfg = call(monkeypatch, commission_rate=0.0007, slippage_rate=0.0003)
    comps = out["cost_model"]["components"]
    assert cfg is not None, "엔진이 호출되지 않았다 — 대조가 공허하다"
    assert comps["commission"]["bps"] == pytest.approx(cfg.commission_rate * 1e4)
    assert comps["slippage"]["bps"] == pytest.approx(cfg.slippage_rate * 1e4)
    assert comps["commission"]["bps"] == pytest.approx(7.0)


@pytest.mark.parametrize("name,call,engine", _DOORS, ids=[d[0] for d in _DOORS])
def test_the_origin_distinguishes_request_from_door_default(monkeypatch, name,
                                                            call, engine):
    """★준 것과 안 준 것이 다르게 나온다★ (네 문 전부 두 칸을 **가진다** — 실측)."""
    given, _ = call(monkeypatch, commission_rate=0.0007)
    prov = given["cost_model"]["rate_provenance"]
    assert prov["commission"]["origin"] == "request"
    assert prov["slippage"]["origin"] == "door_default"


def test_the_door_names_are_distinct_across_the_new_doors(monkeypatch):
    doors = set()
    for _, call, _ in _DOORS:
        out, _ = call(monkeypatch)
        doors.add(out["cost_model"]["rate_provenance"]["commission"]["door"])
    assert len(doors) == len(_DOORS), doors


def test_realism_charges_impact_and_carries_its_counted_total(monkeypatch):
    """★realism 의 충격은 있다★ — `unsupported` 로 적으면 거짓이다."""
    out, _ = _stage12(monkeypatch)
    impact = out["cost_model"]["components"]["impact"]
    assert impact["state"] == STATE_CHARGED
    assert impact["krw"] == 4321.0
    assert "ADV" in impact["reason"] and "0.018" in impact["reason"]
    assert out["cost_model"]["components"]["tax"]["state"] == STATE_UNSUPPORTED


def test_realism_with_impact_switched_off_says_off(monkeypatch):
    """★짝★ — 끈 것은 `off` 이지 `unsupported` 가 아니다."""
    out, _ = _stage12(monkeypatch, enable_market_impact=False)
    assert out["cost_model"]["components"]["impact"]["state"] == STATE_OFF


def test_multi_strategy_has_no_impact(monkeypatch):
    out, _ = _stage11_run(monkeypatch)
    assert out["cost_model"]["components"]["impact"]["state"] == STATE_UNSUPPORTED


def test_dag_runner_carries_the_totals_it_counted(monkeypatch):
    out, _ = _graph(monkeypatch)
    b = out["cost_model"]
    assert b["components"]["commission"]["krw"] == 1500.0
    assert b["components"]["slippage"]["krw"] == 500.0
    assert b["total_krw"] == 2000.0


def test_a_failed_run_gets_no_block(monkeypatch):
    """★돌지 않은 실행에 "부과했다" 를 붙이지 않는다★"""
    from src.api import stage11_routes as r
    _fake_engine(monkeypatch, "src.engine.multi_strategy_backtest",
                 "MultiStrategyBacktester",
                 {"success": False, "message": "데이터 없음"})
    out = r.multibacktest_run(r.MultiBacktestRunRequest(**_BASE))
    assert "cost_model" not in out


# ═══════════════════════════════════════════════════════════════════════════
# ★골든 — 문의 기본 요율이 정적 레지스트리와 같다★ (변이 h 가 살아남아서 더했다)
# ═══════════════════════════════════════════════════════════════════════════

def _door_models():
    from src.api import stage11_routes as s11
    from src.api import stage12_routes as s12
    from src.models.graph_schema import GraphBacktestRequest
    return [("stage11_routes", s11.MultiBacktestRunRequest),
            ("stage11_routes", s11.CounterfactualRequest),
            ("stage12_routes", s12.RealismBacktestRequest),
            ("graph_schema", GraphBacktestRequest)]


#: ★체크인된 절대값★ — 상대 비교는 전부 함께 바뀌는 변이를 못 잡는다(AZ).
GOLDEN_DOOR_DEFAULT_BPS = {
    "stage11_routes": (1.5, 5.0),
    "stage12_routes": (1.5, 5.0),
    "graph_schema": (15.0, 5.0),
}


@pytest.mark.parametrize("key,model", _door_models(),
                         ids=[f"{k}:{m.__name__}" for k, m in _door_models()])
def test_the_door_default_rate_is_pinned(key, model):
    """변이 h — ★요율 값이 바뀌면 red★ (동작 보존)

    처음엔 이 테스트가 없었고 `stage11` 기본 수수료를 10배로 바꾼 변이가
    **살아남았다**. 정적 레지스트리도 값을 적어만 두고 실제 기본값과 대조하지
    않았다.
    """
    f = model.model_fields
    got = (round(f["commission_rate"].default * 1e4, 6),
           round(f["slippage_rate"].default * 1e4, 6))
    assert got == GOLDEN_DOOR_DEFAULT_BPS[key], (key, model.__name__, got)


@pytest.mark.parametrize("key,model", _door_models(),
                         ids=[f"{k}:{m.__name__}" for k, m in _door_models()])
def test_the_static_registry_says_what_the_door_really_defaults_to(key, model):
    """★정적 레지스트리가 실제 기본값을 말한다★

    BB 실측 — `graph_schema` 는 `commission_bps=None`(슬리피지만)으로 적혀
    있었는데 요청 모델은 수수료 **15bp** 를 기본으로 갖는다. 레지스트리의
    왕복 표가 그 문을 10bp 로 낮춰 보고하고 있었다.
    """
    from src.engine.cost_model_registry import COST_SITES
    site = {s.key: s for s in COST_SITES}[key]
    f = model.model_fields
    assert site.commission_bps == pytest.approx(f["commission_rate"].default * 1e4)
    assert site.slippage_bps == pytest.approx(f["slippage_rate"].default * 1e4)


def test_the_registry_knows_stage12_charges_impact_by_default():
    """★문 기본값이 충격을 켠다★ — 레지스트리가 그것을 `charged` 로 적는다."""
    from src.api.stage12_routes import RealismBacktestRequest
    from src.engine.cost_model_registry import COST_SITES
    assert RealismBacktestRequest.model_fields["enable_market_impact"].default is True
    site = {s.key: s for s in COST_SITES}["stage12_routes"]
    assert site.components["impact"] == STATE_CHARGED
