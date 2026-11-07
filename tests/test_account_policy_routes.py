"""AD4 — 계좌 판정 표면의 계약.

★눈으로 볼 것을 테스트가 대신 본다★ — 한도 없이 부르면 `undetermined` 와
"운영자가 선언해야 합니다" 가 나오고, 한도를 넣으면 판정이 바뀌며, 응답이
**어느 한도로 쟀는지**를 말한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.domain.account_policy import (
    ACCOUNT_GENERAL,
    ACCOUNT_IRP,
    LIMIT_RISKY_ASSET_MAX_PCT,
    VERDICT_BREACH,
    VERDICT_PASS,
    VERDICT_UNDETERMINED,
)

_EQUITY = "069500"     # KODEX 200 → EQUITY
_RATES = "153130"      # 단기채 ETF → RATES


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    # ★`with TestClient(...)` 를 쓰지 않는다★ — 모듈 스코프에서 컨텍스트를 닫으면
    # 앱 **shutdown 이벤트**가 발화해 공용 백테스트 워커 풀이 세션 내내 닫힌다
    # (실측: 뒤따르는 backtest 테스트 2개 실패 + 12개가 "실행 저장소를 쓸 수 없다"
    # 로 스킵). 이 표면은 startup 이벤트가 필요 없으므로 집 관용구
    # (`test_holdings_diagnostics.py`)대로 컨텍스트 없이 만든다.
    return TestClient(create_app())


def _post(client, **kw):
    body = {"account_type": ACCOUNT_IRP, "holdings": {_EQUITY: 50.0, _RATES: 50.0}}
    return client.post("/api/v1/accounts/diagnose", json={**body, **kw})


def _verdict(body, kind=LIMIT_RISKY_ASSET_MAX_PCT):
    return next(v for v in body["verdicts"] if v["kind"] == kind)


# ── 인증 없이 동작한다 (레지스트리 면제) ──────────────────────────────────

def test_the_surface_answers_without_a_token(client):
    """요청 본문으로만 도는 표면이라 P-1 이 필요 없다 — 면제 사유가 레지스트리에 있다."""
    assert _post(client).status_code == 200


# ── ★한도 없이 부르면 미판정★ ───────────────────────────────────────────

def test_without_declared_limits_everything_is_undetermined(client):
    body = _post(client, risky_asset_classes=["EQUITY"]).json()
    assert all(v["verdict"] == VERDICT_UNDETERMINED for v in body["verdicts"])
    assert body["summary"][VERDICT_PASS] == 0


def test_the_undetermined_reason_names_who_must_declare(client):
    body = _post(client, risky_asset_classes=["EQUITY"]).json()
    assert "운영자" in _verdict(body)["reason"]


def test_the_response_says_the_optimizer_does_not_know_about_accounts(client):
    """★사후 관측이라는 사실을 응답이 적는다★ — 배분이 계좌를 반영했다고 오해하지 않도록."""
    body = _post(client).json()
    assert body["optimizer_note"]
    assert "최적화기" in body["optimizer_note"]


# ── 한도를 선언하면 판정이 선다 ──────────────────────────────────────────

def _limit(value, as_of="2026-01-01"):
    return [{"kind": LIMIT_RISKY_ASSET_MAX_PCT, "value": value,
             "source": "운영자 선언(테스트)", "as_of": as_of}]


def test_a_declared_limit_with_room_passes(client):
    body = _post(client, risky_asset_classes=["EQUITY"],
                 limits=_limit(70.0)).json()
    assert _verdict(body)["verdict"] == VERDICT_PASS


def test_a_declared_limit_that_is_exceeded_breaches(client):
    """★짝★ — 보유의 EQUITY 가 50% 이므로 한도 30% 면 위반이다."""
    body = _post(client, risky_asset_classes=["EQUITY"],
                 limits=_limit(30.0)).json()
    assert _verdict(body)["verdict"] == VERDICT_BREACH


def test_the_verdict_reports_which_limit_it_used(client):
    body = _post(client, risky_asset_classes=["EQUITY"],
                 limits=_limit(70.0, "2026-01-01")).json()
    used = _verdict(body)["limit"]
    assert used["value"] == 70.0
    assert used["as_of"] == "2026-01-01"
    assert used["source"]


def test_revising_the_limit_flips_the_verdict(client):
    """★개정 대비★ — 같은 보유, 다른 한도, 다른 판정. 각자 자기 기준일을 든다."""
    strict = _post(client, risky_asset_classes=["EQUITY"], limits=_limit(30.0, "2026-01-01")).json()
    loose = _post(client, risky_asset_classes=["EQUITY"], limits=_limit(70.0, "2027-01-01")).json()
    assert _verdict(strict)["verdict"] == VERDICT_BREACH
    assert _verdict(loose)["verdict"] == VERDICT_PASS
    assert _verdict(strict)["limit"]["as_of"] == "2026-01-01"
    assert _verdict(loose)["limit"]["as_of"] == "2027-01-01"


# ── 위험자산 분류 선언 ────────────────────────────────────────────────────

def test_without_a_declared_classification_the_share_is_not_measured(client):
    body = _post(client, limits=_limit(70.0)).json()
    assert body["risky_share"]["available"] is False
    assert body["risky_share"]["reason"]
    # 한도는 있는데 관측이 없으므로 여전히 통과가 아니다.
    assert _verdict(body)["verdict"] == VERDICT_UNDETERMINED


def test_an_unassigned_holding_widens_the_interval_and_can_block_a_verdict(client):
    """★미배정이 판정을 막는다★ — 개별주는 이 환경에서 미배정이라 구간이 넓다."""
    body = _post(client, holdings={_EQUITY: 50.0, "005930": 50.0},
                 risky_asset_classes=["EQUITY"], limits=_limit(70.0)).json()
    interval = body["risky_share"]["interval"]
    assert interval["hi"] > interval["lo"]
    assert _verdict(body)["verdict"] == VERDICT_UNDETERMINED
    assert "구간" in _verdict(body)["reason"]


def test_both_interval_bounds_explain_what_they_assume(client):
    body = _post(client, holdings={_EQUITY: 50.0, "005930": 50.0},
                 risky_asset_classes=["EQUITY"]).json()
    interval = body["risky_share"]["interval"]
    assert interval["lo_assumes"] and interval["hi_assumes"]


# ── 거부 ──────────────────────────────────────────────────────────────────

def test_an_unknown_account_type_is_refused_with_a_reason(client):
    res = _post(client, account_type="crypto_wallet")
    assert res.status_code == 400
    assert "crypto_wallet" in res.json()["detail"]


def test_an_unknown_limit_kind_is_refused(client):
    res = _post(client, limits=[{"kind": "vibes_max", "value": 1.0}])
    assert res.status_code == 400
    assert "vibes_max" in res.json()["detail"]


def test_a_general_account_says_it_has_nothing_to_judge(client):
    body = _post(client, account_type=ACCOUNT_GENERAL).json()
    assert body["verdicts"] == []
    assert "묻지 않았다" in body["note"]
