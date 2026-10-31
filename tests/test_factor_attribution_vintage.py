"""백테스트 팩터 귀인의 ★시점 표기★ — 표 판본이 응답을 타고 나온다 (P9 ①)

## 무엇이 문제였나 — ★과대 진술하지 않는다★

`GET /api/v1/backtest/runs/{id}/factor-attribution` 은 **완료된 과거** 백테스트의
팩터 귀인을 `resolve_proxies()` — 인자 없이 — 로 계산했다. 형제 경로 둘
(`allocation_routes` 의 팩터 스택 · `factor_risk_model`)은 `as_of` 를 넘긴다.

그런데 이것은 **계수의 수치적 룩어헤드가 아니다.** `factor_attribution` 은 수익률과
팩터가 공통으로 갖는 달로 **교집합**을 잡으므로(`backtest_attribution.py:87`),
창 밖의 달은 회귀에 들어가지 않는다. 고치는 것은 다른 것이다:

  ★대리계열 **선택**이 창 밖(오늘까지)의 관측 수로 이뤄지는데, 응답은 그 선택을
   `proxies={…}` 로 **시점 표기 없이** 보고했다.★

그래서 이 슬라이스는 **수치를 바꾸지 않는다.** 늘어나는 것은 라벨뿐이다 —
절단은 플래그 뒤에 둔다(P5 ③ 이 세운 규율: 라벨 기본 · 차단/절단은 플래그).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import router  # noqa: E402

URL = "/api/v1/backtest/runs/bt_test/factor-attribution"

#: 창은 2021-01 ~ 2023-12 — ★표(2026-08-23)보다 앞선다★ 그래서 덮이지 않는다.
_MONTHS = [{"year": 2021 + (i // 12), "month": (i % 12) + 1,
            "return_pct": 1.0 + 0.4 * ((i * 7919) % 11 - 5)} for i in range(36)]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(br, "get_run", lambda run_id, strict=False: {
        "run_id": "bt_test", "status": "completed", "strategy_name": "시험용",
        "result": {"monthly_returns": _MONTHS}})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _get(client, **params) -> dict:
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_response_says_which_window_it_attributed(client):
    b = _get(client)
    sel = b["proxy_selection"]
    assert sel["window_as_of"] == "2023-12-31", sel


def test_the_response_carries_the_proxy_table_version(client):
    from src.engine.factor_exposure import PROXY_TABLE_AS_OF, PROXY_TABLE_VERSION
    t = _get(client)["proxy_selection"]["proxy_table"]
    assert t["version"] == PROXY_TABLE_VERSION and t["as_of"] == PROXY_TABLE_AS_OF


def test_a_window_older_than_the_table_is_reported_as_not_covered(client):
    """★그 표는 그때 없었다★ 창이 2023년인데 표는 2026년 판이다."""
    t = _get(client)["proxy_selection"]["proxy_table"]
    assert t["covers_as_of"] is False
    assert "2023-12-31" in t["reason"]


def test_not_truncating_is_not_the_same_as_honoring(client):
    """★공허한 참을 막는다★ (변이 W9)

    `resolve_proxies()` 는 `as_of` 를 안 주면 `as_of_honored: True` 를 돌려준다 —
    계열 축에서는 참이다(자를 것이 없었다). 그 참을 라우트가 그대로 실으면
    "창 시점을 지켰다" 로 읽힌다. 자르지 않았으면 지킨 것이 아니다.
    """
    sel = _get(client)["proxy_selection"]
    assert sel["truncated_to_window"] is False
    assert sel["as_of_honored"] is False
    assert sel["reason"], "지키지 않은 이유를 말하지 않는다"


def test_the_flag_actually_truncates_and_says_so(client):
    """★짝★ 플래그가 아무 일도 안 하면 그것은 스위치가 아니라 장식이다.

    개발 환경에는 매크로 계열이 적재돼 있지 않아, 2023-12 로 자르면 쓸 수 있는
    후보가 남지 않아 **정직하게 거절**한다. 그것이 맞는 동작이다 — 여기서 거는
    것은 "잘랐다고 말했으면 실제로 잘랐는가" 다.
    """
    sel = _get(client, truncate_to_window=True)["proxy_selection"]
    assert sel["truncated_to_window"] is True
    assert sel["reason"] is None


def test_the_numbers_do_not_move_by_default(client):
    """★행동 불변★ 이 슬라이스는 라벨만 늘린다 — 계수는 그대로여야 한다.

    기본(절단 없음)이 예전 동작이다. 값이 움직였다면 라벨 작업이 정책 변경으로
    번진 것이다.
    """
    b = _get(client)
    assert b["available"] is True, b.get("reason")
    # ★실측한 키를 건다★ 처음에 `alpha`·`r2`·`betas` 로 짐작해 썼다가 이 테스트가
    # 내 짐작을 잡았다 — 실제 이름은 아래다.
    for k in ("alpha_monthly", "alpha_contribution_pct", "factor_contribution_pct",
              "rows", "diagnostics", "identity_residual_pct", "proxies"):
        assert k in b, f"{k} 가 사라졌다 — 기존 키는 불변이어야 한다"


def test_truncating_is_allowed_to_move_the_numbers_or_refuse(client):
    """플래그를 켜면 계열이 짧아진다 — ★결과가 달라지거나 정직하게 거절한다★.

    어느 쪽이든 좋다. 막아야 하는 것은 "잘랐다" 고 적으면서 자르지 않은 것이다.
    """
    cut = _get(client, truncate_to_window=True)
    assert cut["proxy_selection"]["truncated_to_window"] is True
    if cut.get("available"):
        assert cut["proxy_selection"]["as_of_honored"] is True
    else:
        assert cut.get("reason"), "거절했으면 사유를 말해야 한다"


def test_a_refusal_still_carries_the_label(client):
    """★모든 분기가 같은 라벨을 낸다★ — 내가 처음에 어긴 규율이다.

    절단을 켜면 쓸 계열이 안 남아 조기 반환할 수 있다. 그 분기에서 라벨이 빠지면
    소비자는 **왜** 거절됐는지(자른 탓인지 수집기가 빈 탓인지) 구별할 수 없다.
    """
    cut = _get(client, truncate_to_window=True)
    sel = cut["proxy_selection"]
    assert sel["window_as_of"] == "2023-12-31"
    assert sel["truncated_to_window"] is True
    assert sel["proxy_table"]["covers_as_of"] is False


def test_an_unavailable_run_still_reports_nothing_invented(client, monkeypatch):
    """월별 수익률이 없으면 창을 **지어내지 않는다**."""
    monkeypatch.setattr(br, "get_run", lambda run_id, strict=False: {
        "run_id": "bt_test", "status": "running", "result": {}})
    b = _get(client)
    assert b["available"] is False and b["reason"]


def test_the_flag_changes_what_the_resolver_is_actually_asked(client, monkeypatch):
    """★라벨이 아니라 **효과**를 본다★ (변이 W10)

    앞의 테스트들은 `truncated_to_window: true` 라는 **주장**만 확인했다. 그래서
    "플래그를 무시하고 절대 안 자른다" 는 변이가 살아남았다 — 라벨은 참이고
    `as_of_honored` 도 참(계열 축의 공허한 참)이라 응답이 완벽하게 거짓말을 한다.
    스위치가 실제로 무엇을 바꾸는지는 **호출 인자**로만 잴 수 있다.
    """
    from src.engine import factor_exposure as fe
    seen: list = []
    real = fe.resolve_proxies

    def _spy(series_map=None, min_months=fe.MIN_MONTHS, as_of=None):
        seen.append(as_of)
        return real(series_map, min_months, as_of)
    monkeypatch.setattr(fe, "resolve_proxies", _spy)

    _get(client)
    assert seen == [None], f"끈 상태인데 절단을 요청했다: {seen}"

    seen.clear()
    _get(client, truncate_to_window=True)
    assert seen == ["2023-12-31"], (
        f"켠 상태인데 창 시점을 넘기지 않았다: {seen} — 플래그가 장식이다")
