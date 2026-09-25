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
#: BG1 에서 `src.engine.strategy_registry` 가 복원됐다.
FIVE = {"src.engine.allocator",
        "src.execution.order_netting", "src.data.macro_feed",
        "src.engine.regime_model"}


# ── 레지스트리 · 실측 ─────────────────────────────────────────────────

def test_the_five_are_missing_right_now():
    """★선언이 아니라 실측★ — `find_spec` 이 지금 못 찾는다."""
    assert set(ma.missing_now()) == FIVE


def test_every_entry_says_what_it_was_for_and_why():
    for m in ma.MISSING:
        assert m.module and m.needed_by
        assert len(m.role) >= 4, m.module
        assert len(m.reason) > 20, m.module


def test_the_status_names_the_modules_and_the_data_gap():
    s = ma.status()
    assert s["available"] is False
    assert {m["module"] for m in s["missing"]} == FIVE
    assert all(m["role"] for m in s["missing"])
    assert s["reason"] and len(s["reason"]) > 30
    assert s["data_gap"] and "수익률" in s["data_gap"]
    assert s["since"]


def test_restoring_everything_makes_it_available(monkeypatch):
    """★짝★ — 항상-불가 구현을 배제한다. 모듈이 생기면 스스로 풀린다."""
    monkeypatch.setattr(ma, "_spec_exists", lambda name: True)
    assert ma.missing_now() == []
    assert ma.status()["available"] is True
    assert ma.http_unavailable() is None


def test_restoring_one_shrinks_the_list(monkeypatch):
    monkeypatch.setattr(ma, "_spec_exists",
                        lambda name: name == "src.engine.allocator")
    assert "src.engine.allocator" not in ma.missing_now()
    assert len(ma.missing_now()) == len(FIVE) - 1


def test_the_http_error_is_503_with_the_status():
    exc = ma.http_unavailable()
    assert exc is not None and exc.status_code == 503
    assert exc.detail["available"] is False
    assert exc.detail["reason"]


# ── ★라우트가 503 + 사유를 낸다★ ─────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


_BODY = {"strategy_ids": [1, 2], "start_date": "2024-01-02",
         "end_date": "2024-06-28"}

GUARDED = [
    ("post", "/api/v1/multibacktest/run", _BODY),
    ("get", "/api/v1/multibacktest/runs", None),
    ("get", "/api/v1/multibacktest/7", None),
    ("delete", "/api/v1/multibacktest/7", None),
    ("post", "/api/v1/multibacktest/counterfactual", _BODY),
    ("post", "/api/v1/realism/backtest", _BODY),
    ("post", "/api/v1/realism/correlation-health", {"strategy_ids": [1, 2]}),
]


@pytest.mark.parametrize("method,path,body", GUARDED,
                         ids=[f"{m.upper()} {p}" for m, p, _ in GUARDED])
def test_the_guarded_routes_say_503_with_the_missing_modules(client, method,
                                                             path, body):
    """변이 — 가드를 빼거나 `try:` 안으로 넣으면 500 이 된다."""
    r = getattr(client, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 503, (r.status_code, r.text[:300])
    d = r.json()["detail"]
    assert {m["module"] for m in d["missing"]} == FIVE
    assert d["reason"]


UNGUARDED = [
    ("get", "/api/v1/multibacktest/counterfactual/scenarios"),
    ("get", "/api/v1/realism/market-impact/calibration"),
]


@pytest.mark.parametrize("method,path", UNGUARDED)
def test_routes_that_do_not_need_the_subsystem_still_work(client, method, path):
    """★짝★ — 필요 없는 문까지 막지 않는다."""
    r = getattr(client, method)(path)
    assert r.status_code == 200, (r.status_code, r.text[:300])
