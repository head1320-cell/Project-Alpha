"""BF · ★없는 것을 없다고 말한다★ — 멀티전략 서브시스템
==============================================================================
대상: `src/engine/multistrategy_availability.py` · `src/api/stage11_routes.py` ·
`src/api/stage12_routes.py`

## 실측 (2026-09-24)

`multibacktest`·`realism` 백테스트는 모듈 **다섯**이 없다(allocator ·
strategy_registry · order_netting · macro_feed · regime_model). 돌릴 데이터(등록
전략의 일별 수익률 테이블)도 없다. 2026-06-10 스냅샷 이식 때 import 가 이미 끊긴
채 들어왔고 저장소 이력에 한 번도 존재한 적이 없다. 그래서 요청마다
`500 No module named 'src.engine.allocator'` 가 났다 — ★무엇이 왜 없는지 아무도
말하지 않았다★.

## ★503 + 사유 — 500 이 아니다★

500 은 *"서버가 고장 났다"* 이고 503 은 *"이 기능이 지금 없다"* 다. 다섯 모듈과
데이터 공백을 이름으로 말한다. 엔진 내부는 한 줄도 안 건드린다(§6).
"""
from __future__ import annotations

import pytest

from src.engine import multistrategy_availability as ma

#: ★지금 없는 것★ — 복원될 때마다 줄어든다(트립와이어가 그것을 요구한다).
#: BG1 에서 `src.engine.strategy_registry`, BG2 에서 `src.engine.allocator`, BG3 에서
#: `src.execution.order_netting`, BH3 에서 `src.engine.regime_model` 이 복원됐다. 남은
#: 하나는 hrp_macro 용 매크로 피드 — ★기능 단위로만 막는다★(BG4).
FIVE = {"src.data.macro_feed"}


# ── 레지스트리 · 실측 ─────────────────────────────────────────────────

def test_the_five_are_missing_right_now():
    """★선언이 아니라 실측★ — `find_spec` 이 지금 못 찾는다."""
    assert set(ma.missing_now()) == FIVE


def test_every_entry_says_what_it_was_for_and_why():
    for m in ma.MISSING:
        assert m.module and m.needed_by
        assert len(m.role) >= 4, m.module
        assert len(m.reason) > 20, m.module


# ── BG4 · ★기능 단위로 막는다★ ───────────────────────────────────────
# 코어(레지스트리·배분기·네팅)가 복원됐다. 남은 둘(macro_feed·regime_model)은
# `hrp_macro`·`regime_change` **만** 필요로 한다 — 그 요청만 422, 나머지는 돈다.

def test_the_remaining_modules_block_only_their_features():
    for m in ma.MISSING:
        assert m.features, f"{m.module} 는 기능이 없는 코어로 등록됐다 — 전부 503 이 된다"
        assert set(m.features) <= set(ma.FEATURES), m.features


def test_the_core_is_available_now():
    s = ma.status()
    assert s["available"] is True
    assert s["reason"] is None
    assert ma.http_unavailable() is None
    # ★없는 것은 여전히 이름으로 말한다★ — 가용이라고 숨기지 않는다.
    assert {m["module"] for m in s["missing"]} == FIVE
    assert s["data_gap"] and "수익률" in s["data_gap"]
    assert s["since"]


def test_the_status_names_the_unsupported_features_with_reasons():
    feats = {f["feature"]: f for f in ma.status()["unsupported_features"]}
    assert set(feats) == {"hrp_macro"}, "regime_change 는 BH3 에서 풀렸다"
    assert feats["hrp_macro"]["field"] == "allocation_method"
    for f in feats.values():
        assert len(f["reason"]) > 20 and f["missing"]
        assert set(f["missing"]) <= FIVE


def test_restoring_everything_makes_it_available(monkeypatch):
    """★짝★ — 항상-불가 구현을 배제한다. 모듈이 생기면 스스로 풀린다."""
    monkeypatch.setattr(ma, "_spec_exists", lambda name: True)
    assert ma.missing_now() == []
    s = ma.status()
    assert s["available"] is True and s["unsupported_features"] == []
    assert ma.http_unsupported(allocation_method="hrp_macro",
                               rebalance_policy="regime_change") is None


def test_restoring_one_shrinks_the_list(monkeypatch):
    victim = sorted(FIVE)[0]          # ★아직 없는 것 하나★ — 복원이 진행되면 바뀐다
    monkeypatch.setattr(ma, "_spec_exists", lambda name: name == victim)
    assert victim not in ma.missing_now()
    assert len(ma.missing_now()) == len(FIVE) - 1


@pytest.mark.parametrize("fields", [
    {"allocation_method": "hrp_macro"},
    {"allocation_method": "hrp_macro", "rebalance_policy": "regime_change"},
])
def test_an_unsupported_request_is_422_with_the_reason(fields):
    exc = ma.http_unsupported(**fields)
    assert exc is not None and exc.status_code == 422
    assert [u["feature"] for u in exc.detail["unsupported"]] == ["hrp_macro"]
    assert exc.detail["reason"]


@pytest.mark.parametrize("fields", [
    {"allocation_method": "hrp", "rebalance_policy": "monthly"},
    {"allocation_method": "inverse_vol", "rebalance_policy": "daily"},
    {"allocation_method": "hrp", "rebalance_policy": "regime_change"},
    {},
])
def test_a_supported_request_passes(fields):
    """★짝★ — 항상-거부 구현 배제."""
    assert ma.http_unsupported(**fields) is None


def _fake_core_missing(monkeypatch):
    """코어가 빠진 저장소를 흉내 낸다 — 503 경로가 죽은 코드가 되지 않게."""
    fake = ma.MissingModule(module="src.engine._fake_core_for_test",
                            needed_by=("x",), role="가짜 코어 모듈",
                            reason="코어가 빠졌을 때 문이 503 을 내는지 보는 가짜 항목입니다.")
    monkeypatch.setattr(ma, "MISSING", (*ma.MISSING, fake))
    return fake


def test_a_missing_core_module_is_503(monkeypatch):
    fake = _fake_core_missing(monkeypatch)
    exc = ma.http_unavailable()
    assert exc is not None and exc.status_code == 503
    assert exc.detail["available"] is False and exc.detail["reason"]
    assert fake.module in {m["module"] for m in exc.detail["missing"]}


# ── ★라우트★ ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


_BODY = {"strategy_ids": [1, 2], "start_date": "2024-01-02",
         "end_date": "2024-06-28", "allocation_method": "hrp"}

GUARDED = [
    ("post", "/api/v1/multibacktest/run", _BODY),
    ("get", "/api/v1/multibacktest/runs", None),
    ("get", "/api/v1/multibacktest/7", None),
    ("delete", "/api/v1/multibacktest/7", None),
    ("post", "/api/v1/multibacktest/counterfactual",
     {**_BODY, "base_allocation_method": "hrp"}),
    ("get", "/api/v1/multibacktest/strategies", None),
    ("post", "/api/v1/multibacktest/strategies", {"run_id": "bt_x", "name": "x"}),
    ("delete", "/api/v1/multibacktest/strategies/7", None),
    ("post", "/api/v1/realism/backtest", _BODY),
    ("post", "/api/v1/realism/correlation-health", {"strategy_ids": [1, 2]}),
]


@pytest.mark.parametrize("method,path,body", GUARDED,
                         ids=[f"{m.upper()} {p}" for m, p, _ in GUARDED])
def test_the_guarded_routes_say_503_when_the_core_is_missing(client, monkeypatch,
                                                             method, path, body):
    """변이 — 가드를 빼거나 `try:` 안으로 넣으면 500 이 된다."""
    fake = _fake_core_missing(monkeypatch)
    r = getattr(client, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 503, (r.status_code, r.text[:300])
    d = r.json()["detail"]
    assert fake.module in {m["module"] for m in d["missing"]}
    assert d["reason"]


@pytest.mark.parametrize("method,path,body", GUARDED,
                         ids=[f"{m.upper()} {p}" for m, p, _ in GUARDED])
def test_the_guarded_routes_are_not_503_now(client, method, path, body):
    """★짝★ — 코어가 복원된 지금은 503 이 아니다(다른 결과는 각 문의 몫)."""
    r = getattr(client, method)(path, **({"json": body} if body else {}))
    assert r.status_code != 503, r.text[:300]


UNSUPPORTED = [
    ("/api/v1/multibacktest/run", {**_BODY, "allocation_method": "hrp_macro"}, "hrp_macro"),
    ("/api/v1/multibacktest/counterfactual",
     {**_BODY, "base_allocation_method": "hrp_macro"}, "hrp_macro"),
    ("/api/v1/realism/backtest", {**_BODY, "allocation_method": "hrp_macro"}, "hrp_macro"),
]

@pytest.mark.parametrize("path,body,feature", UNSUPPORTED,
                         ids=[f"{p} {f}" for p, _, f in UNSUPPORTED])
def test_r4_features_are_422_with_the_reason(client, path, body, feature):
    """★422 — 요청이 이 저장소에 없는 기능을 골랐다★ (500 도 503 도 아니다)."""
    r = client.post(path, json=body)
    assert r.status_code == 422, (r.status_code, r.text[:300])
    d = r.json()["detail"]
    assert [u["feature"] for u in d["unsupported"]] == [feature]
    assert d["reason"] and d["unsupported"][0]["missing"]


REGIME_CHANGE = [
    ("/api/v1/multibacktest/run", {**_BODY, "rebalance_policy": "regime_change"}),
    ("/api/v1/multibacktest/counterfactual",
     {**_BODY, "base_allocation_method": "hrp", "base_rebalance_policy": "regime_change"}),
    ("/api/v1/realism/backtest", {**_BODY, "rebalance_policy": "regime_change"}),
]


@pytest.mark.parametrize("path,body", REGIME_CHANGE, ids=[p for p, _ in REGIME_CHANGE])
def test_regime_change_is_no_longer_refused(client, path, body):
    """★짝★ — BH3 에서 국면 모델이 복원돼 regime_change 는 422 가 아니다."""
    r = client.post(path, json=body)
    assert r.status_code not in (422, 503), (r.status_code, r.text[:300])


UNGUARDED = [
    ("get", "/api/v1/multibacktest/counterfactual/scenarios"),
    ("get", "/api/v1/realism/market-impact/calibration"),
]


@pytest.mark.parametrize("method,path", UNGUARDED)
def test_routes_that_do_not_need_the_subsystem_still_work(client, method, path):
    """★짝★ — 필요 없는 문까지 막지 않는다."""
    r = getattr(client, method)(path)
    assert r.status_code == 200, (r.status_code, r.text[:300])
