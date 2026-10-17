"""AO4 — 글라이드패스 표면의 계약.

★눈으로 볼 것을 테스트가 대신 본다★ — 곡선을 선언하지 않으면 **숫자가 하나도
나오지 않고**, 넷을 다 선언하면 목표·격차·개월 수가 나오며, ★실적을 주면 지금까지
도달할 수 없던 납입 한도 판정이 처음으로 `pass`/`breach` 를 낸다★.
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from src.domain.account_policy import (
    ACCOUNT_IRP,
    LIMIT_ANNUAL_CONTRIB_KRW,
    LIMIT_RISKY_ASSET_MAX_PCT,
    VERDICT_BREACH,
    VERDICT_PASS,
    VERDICT_UNDETERMINED,
)
from src.domain.contribution import DIRECTION_WIDENS
from src.engine.glide_evidence import (
    AXIS_CONTRIBUTION,
    AXIS_CURVE,
    AXIS_HORIZON,
    AXIS_RISKY_CLASS,
)
from src.engine.run_evidence import AXIS_OK, AXIS_UNKNOWN, STATUS_VERIFIED

_EQUITY = "069500"      # KODEX 200 → EQUITY
_RATES = "153130"       # 단기채 ETF → RATES
_UNASSIGNED = "005930"  # 개별주 — master 플래그 없이는 미배정

#: 5~15년 구간에서 평평한 곡선. ★프리셋이 아니라 이 테스트의 선언이다★
FLAT_50 = [{"years_to_target": 5.0, "risky_target_pct": 50.0},
           {"years_to_target": 15.0, "risky_target_pct": 50.0}]

PLAN_SAFE = {"monthly_krw": 1_000_000, "bucket": "safe",
             "portfolio_value_krw": 100_000_000}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    # ★`with TestClient(...)` 를 쓰지 않는다★ — AD4 가 실측으로 적어 둔 이유와 같다
    # (모듈 스코프에서 컨텍스트를 닫으면 공용 백테스트 워커 풀이 세션 내내 닫힌다).
    return TestClient(create_app())


def _post(client, **kw):
    body = {
        "account_type": ACCOUNT_IRP,
        "holdings": {_EQUITY: 70.0, _RATES: 30.0},
        "risky_asset_classes": ["EQUITY"],
        "horizon_days": 3650,
        "curve": FLAT_50,
        "contribution": PLAN_SAFE,
    }
    return client.post("/api/v1/accounts/glidepath", json={**body, **kw})


def _verdict(body, kind):
    return next((v for v in body["limits"]["verdicts"] if v["kind"] == kind), None)


# ── 인증 없이 동작한다 (레지스트리 면제) ──────────────────────────────────

def test_the_surface_answers_without_a_token(client):
    assert _post(client).status_code == 200


def test_the_exemption_is_registered_with_a_reason():
    """★면제는 사유와 함께★ — 조용히 열린 문을 만들지 않는다."""
    from src.api.protected_routes import OPEN_WITH_REASON
    reason = OPEN_WITH_REASON[("POST", "/api/v1/accounts/glidepath")]
    assert reason and len(reason) > 20


# ── 실물 ① ★곡선을 선언하지 않으면 숫자가 없다★ ─────────────────────────

def test_without_a_declared_curve_no_number_is_produced(client):
    body = _post(client, curve=None).json()
    assert body["glide"]["target_pct"] is None
    assert body["glide"]["gap"]["state"] == "unknown"
    assert body["contribution"]["months"] is None
    axis = body["evidence"]["axes"][AXIS_CURVE]
    assert axis["state"] == AXIS_UNKNOWN and axis["reason"]
    assert body["evidence"]["status"] != STATUS_VERIFIED


# ── 실물 ② ★짝 — 넷을 다 선언하면 나온다★ ──────────────────────────────

def test_with_all_four_declared_the_numbers_appear(client):
    body = _post(client).json()
    assert body["glide"]["target_pct"] == pytest.approx(50.0)
    assert body["glide"]["gap"]["state"] == "above"
    assert body["contribution"]["months"]["lo"] == pytest.approx(40.0)
    assert body["contribution"]["months"]["hi"] == pytest.approx(40.0)
    ev = body["evidence"]
    assert all(ev["axes"][a]["state"] == AXIS_OK
               for a in (AXIS_HORIZON, AXIS_CURVE, AXIS_RISKY_CLASS,
                         AXIS_CONTRIBUTION))
    assert ev["status"] == STATUS_VERIFIED


# ── ★기간이 미상이면 지점이 없다★ (변이 f) ─────────────────────────────

def test_without_a_declared_period_no_point_on_the_curve(client):
    """★미상 ≠ 0★ — 잔여 기간을 지어내면 곡선 위 아무 데나 찍게 된다."""
    body = _post(client, horizon_days=None).json()
    assert body["glide"]["years_remaining"] is None
    assert body["glide"]["target_pct"] is None
    assert body["evidence"]["axes"][AXIS_HORIZON]["state"] == AXIS_UNKNOWN
    # ★곡선 축은 멀쩡하다★ — 곡선 ⟂ 기간. 미상을 옆 축으로 번지게 하지 않는다.
    assert body["evidence"]["axes"][AXIS_CURVE]["state"] == AXIS_OK


def test_two_disagreeing_period_inputs_produce_no_point(client):
    body = _post(client, horizon_days=365, target_retirement_year=2046).json()
    assert body["glide"]["years_remaining"] is None
    assert "어긋" in body["evidence"]["axes"][AXIS_HORIZON]["reason"]


# ── 실물 ③ ★미배정분은 격차와 개월 수를 구간으로 벌린다★ ────────────────

def test_unassigned_holdings_widen_the_gap_and_the_months(client):
    body = _post(client, holdings={_EQUITY: 70.0, _RATES: 20.0,
                                   _UNASSIGNED: 10.0}).json()
    gap = body["glide"]["gap"]
    assert gap["lo"] == pytest.approx(20.0) and gap["hi"] == pytest.approx(30.0)
    months = body["contribution"]["months"]
    assert months["lo"] < months["hi"]
    # ★미배정은 사라지지 않는다★ — 분류 축이 그 사실을 들고 있다.
    assert body["evidence"]["axes"][AXIS_RISKY_CLASS]["unassigned_pct"] > 0


# ── 실물 ④ ★대상을 잘못 고르면 개월 수 대신 사유★ ──────────────────────

def test_contributing_to_the_wrong_bucket_widens_the_gap(client):
    body = _post(client, contribution={**PLAN_SAFE, "bucket": "risky"}).json()
    assert body["contribution"]["direction"] == DIRECTION_WIDENS
    assert body["contribution"]["months"] is None
    assert body["contribution"]["reason"]
    assert body["evidence"]["status"] != STATUS_VERIFIED


# ── ★대상을 모르면 개월 수를 내지 않는다★ (변이 d — 실측으로 찾은 구멍) ──

@pytest.mark.parametrize("plan", [
    None,                                        # 계획 자체가 없다
    {"monthly_krw": 1_000_000, "portfolio_value_krw": 100_000_000},  # 대상만 없다
])
def test_without_a_declared_bucket_no_months_are_produced(client, plan):
    """★적립은 방향을 모르면 숫자가 아니다★ — 기본값 `safe` 로 채우면 이것이 죽는다.

    같은 적립액이 대상에 따라 격차를 좁히기도 벌리기도 하므로, 대상 미선언에
    개월 수를 내는 것은 **반반의 확률로 거짓말**이다.
    """
    body = _post(client, contribution=plan).json()
    assert body["contribution"]["months"] is None
    assert body["contribution"]["reason"]
    assert body["evidence"]["axes"][AXIS_CONTRIBUTION]["state"] == AXIS_UNKNOWN
    assert body["evidence"]["status"] != STATUS_VERIFIED


# ── 실물 ⑤ ★도달할 수 없던 한도 가드가 살아난다★ ───────────────────────

_ANNUAL = {"kind": LIMIT_ANNUAL_CONTRIB_KRW, "value": 7_000_000,
           "source": "운영자 선언(테스트)", "as_of": "2026-09-19"}


def test_the_annual_limit_is_undetermined_without_an_actual_contribution(client):
    body = _post(client, limits=[_ANNUAL]).json()
    assert _verdict(body, LIMIT_ANNUAL_CONTRIB_KRW)["verdict"] == VERDICT_UNDETERMINED


def test_an_actual_contribution_makes_the_annual_limit_judgeable(client):
    """★실적이 관측이다★ — AM 의 `"dev"` 처럼 도달 불가였던 가드가 처음으로 판정한다."""
    passing = _post(client, limits=[_ANNUAL], contributed_ytd_krw=1_000_000).json()
    assert _verdict(passing, LIMIT_ANNUAL_CONTRIB_KRW)["verdict"] == VERDICT_PASS

    breaching = _post(client, limits=[_ANNUAL], contributed_ytd_krw=9_000_000).json()
    assert _verdict(breaching, LIMIT_ANNUAL_CONTRIB_KRW)["verdict"] == VERDICT_BREACH


def test_the_plan_is_never_read_as_an_actual_contribution(client):
    """★실적 ⟂ 계획★ (변이 h) — 월 적립 계획이 한도 판정을 건드리면 그 판정은 거짓이다.

    계획만 있고 실적이 없는 요청에서 연간 납입 한도는 **미판정**이어야 한다.
    """
    body = _post(client, limits=[_ANNUAL],
                 contribution={**PLAN_SAFE, "monthly_krw": 99_000_000}).json()
    v = _verdict(body, LIMIT_ANNUAL_CONTRIB_KRW)
    assert v["verdict"] == VERDICT_UNDETERMINED
    assert v["observed"] is None


# ── 위험자산 한도는 AD4 와 **같은 관측**을 쓴다 ──────────────────────────

def test_the_risky_limit_reuses_the_same_interval(client):
    body = _post(client, limits=[{"kind": LIMIT_RISKY_ASSET_MAX_PCT, "value": 60.0,
                                  "source": "운영자 선언(테스트)",
                                  "as_of": "2026-09-19"}]).json()
    v = _verdict(body, LIMIT_RISKY_ASSET_MAX_PCT)
    assert v["verdict"] == VERDICT_BREACH          # 관측 70% > 60%
    assert v["observed"] == {"lo": 70.0, "hi": 70.0}
    assert body["risky_share"]["interval"]["lo"] == 70.0


# ── 경계 ────────────────────────────────────────────────────────────────

def test_an_unknown_account_type_is_rejected(client):
    assert _post(client, account_type="크립토지갑").status_code == 400


def test_an_unknown_bucket_is_rejected(client):
    assert _post(client, contribution={**PLAN_SAFE, "bucket": "현금"}).status_code == 400


def test_the_response_says_the_optimizer_does_not_know_this_target(client):
    body = _post(client).json()
    assert "최적화기" in body["optimizer_note"]
    assert "저장" in body["scope_note"] or "조회" in body["scope_note"]


def test_the_horizon_can_come_from_the_retirement_year_instead(client):
    body = _post(client, horizon_days=None, target_retirement_year=2036).json()
    assert body["evidence"]["axes"][AXIS_HORIZON]["state"] == AXIS_OK
    assert body["glide"]["years_remaining"] > 9


# ── ★프런트 타입과 응답이 어긋나면 화면이 조용히 빈다★ (AO5) ─────────────

#: 응답 최상위 키 **골든**. 늘거나 줄면 이 테스트가 먼저 말한다.
RESPONSE_KEYS = {"account_type", "glide", "contribution", "risky_share",
                 "evidence", "limits", "scope_note", "optimizer_note"}

_TYPES_TS = pathlib.Path("frontend/src/entities/glidepath/types.ts")


def test_the_response_shape_is_pinned(client):
    assert set(_post(client).json()) == RESPONSE_KEYS


def test_the_frontend_type_declares_every_response_key():
    """★타입은 화면이 없어도 계약이다★ — 키가 빠지면 나중에 `undefined` 로 샌다."""
    src = _TYPES_TS.read_text(encoding="utf-8")
    block = src.split("export interface GlidePathResponse {", 1)[1].split("}", 1)[0]
    declared = {line.split(":", 1)[0].strip()
                for line in block.splitlines()
                if ":" in line and not line.strip().startswith(("*", "/"))}
    assert RESPONSE_KEYS <= declared, RESPONSE_KEYS - declared
