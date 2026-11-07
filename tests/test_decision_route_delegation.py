"""라우트 위임 — ★판단이 응답과 함께 사라지고 있었다★ (S3)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md`
선행: S1 스토어(`da39c27`) · S2 `decide()` 합성(`2b963b4`)

S1·S2 를 만들었지만 **부르는 곳이 없었다.** 라우트가 여전히 `rebalance_decision`
을 직접 불렀고 그 판단은 응답과 함께 사라졌다. 이 파일이 그 마지막 한 칸을 건다.

## ★기본값에서는 DB 에 한 줄도 쓰지 않는다★

`AnalyzeRequest.record_run` 이 같은 우려를 이미 풀어 뒀다 — *"슬라이더 드래그마다
DB에 쓰지 않도록 명시 요청 시에만"*. 리밸런스 결정도 UI 상호작용마다 불릴 수
있으므로 **같은 모양**을 쓴다(`record_decision: bool = False`).

## ★`legs` 는 응답에 싣지 않는다★

저장 관심사다. 화면에는 `band.by_asset` 이 이미 같은 정보를 준다 — 두 벌을 실으면
화면이 어느 쪽을 믿을지 갈린다(이 저장소가 목표 포트폴리오에서 이미 치른 값이다).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.investment_decisions as idec  # noqa: E402
import src.engine.investment_decision as dec_mod  # noqa: E402

URL = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def eng():
    """★`StaticPool` 이 필요하다★

    TestClient 는 동기 엔드포인트를 **워커 스레드**에서 돌린다. `sqlite://`
    메모리 DB 는 기본 풀이 스레드마다 **다른 DB** 를 주므로, 라우트가 쓴 행을
    테스트 스레드가 읽지 못한다(실제로 겪었다 — `persisted:True` 인데 조회가
    `None`). `test_krx_mdc.py` 가 같은 이유로 이미 쓰는 관례다.
    """
    return create_engine("sqlite://", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    """★프로세스 공용 DB 를 건드리지 않는다★"""
    monkeypatch.setattr(idec, "_engine", lambda engine=None: eng)
    yield


def _body(**kw) -> dict:
    base = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000, "model": "mvo", "horizon_days": 63}
    base.update(kw)
    return base


def _post(client, **kw) -> dict:
    r = client.post(URL, json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ══════════════════════════════════════════════════════════════════════════
# W1·W2 ★기록은 opt-in★ — `record_run` 과 같은 이유
# ══════════════════════════════════════════════════════════════════════════
def test_by_default_nothing_is_written_to_the_database(client, eng):
    """★핵심★ 슬라이더 드래그마다 DB 에 쓰지 않는다 — 저장소가 이미 정한 규율."""
    body = _post(client)
    assert body["persisted"] is False
    assert body["dec_id"] is None
    assert body["persist_reason"], "왜 저장하지 않았는지 말하지 않는다"
    assert idec.list_decisions(engine=eng) == []


def test_asking_for_a_record_actually_records_it(client, eng):
    """★짝★ 없으면 W1 이 '아무것도 저장하지 않는다' 구현으로도 통과한다."""
    body = _post(client, record_decision=True)
    assert body["persisted"] is True
    assert body["dec_id"] and body["dec_id"].startswith("dec_")

    stored = idec.get_decision(body["dec_id"], engine=eng)
    assert stored is not None
    assert stored["decision_status"] == body["decision"]
    assert stored["reason"] == body["reason"]


# ══════════════════════════════════════════════════════════════════════════
# W3·W4 응답 계약
# ══════════════════════════════════════════════════════════════════════════
def test_the_existing_response_keys_are_untouched(client):
    """★기존 키는 하나도 바뀌지 않는다★ 98개 기존 테스트가 이 계약 위에 있다."""
    body = _post(client)
    for key in ("decision", "reason", "cost", "benefit", "band", "triggers",
                "gradual", "target_weights", "target_source", "model",
                "max_gap_pct", "hysteresis_mult", "coverage", "research_context"):
        assert key in body, key
    assert body["cost"]["available"] is True
    assert body["band"]["by_asset"], "자산별 밴드가 사라졌다"


def test_legs_are_a_storage_concern_not_a_response_field(client, eng):
    """★두 벌을 실지 않는다★ 화면에는 `band.by_asset` 이 이미 있다.

    그래도 leg 는 **저장돼 있어야** 한다 — 결정 간 집계가 두 테이블의 존재 이유다.
    """
    body = _post(client, record_decision=True)
    assert "legs" not in body, "저장 관심사가 응답으로 샜다"

    legs = idec.legs_of(body["dec_id"], engine=eng)
    assert {leg["ticker"] for leg in legs} == set(HOLDINGS)


# ══════════════════════════════════════════════════════════════════════════
# W5·W6 사슬과 증거
# ══════════════════════════════════════════════════════════════════════════
def test_the_decision_can_be_hung_on_a_case(client, eng):
    body = _post(client, record_decision=True, case_id="rc_s3")
    assert idec.get_decision(body["dec_id"], engine=eng)["case_id"] == "rc_s3"
    assert len(idec.list_decisions(case_id="rc_s3", engine=eng)) == 1


def test_the_evidence_references_are_recorded(client, eng):
    """결정이 **무엇 위에 섰는지** 남지 않으면 나중에 되짚을 수 없다."""
    body = _post(client, record_decision=True, as_of="2026-06-30")
    stored = idec.get_decision(body["dec_id"], engine=eng)
    assert stored["as_of"] == "2026-06-30"
    ev = stored["evidence"] or {}
    assert "target_source" in ev, "목표가 어디서 왔는지 남지 않았다"
    assert ev["target_source"] == body["target_source"]


def test_the_belief_records_where_mu_came_from(client, eng):
    body = _post(client, record_decision=True)
    belief = idec.get_decision(body["dec_id"], engine=eng)["belief"] or {}
    assert belief.get("mu_source"), "μ 출처가 남지 않았다"


# ══════════════════════════════════════════════════════════════════════════
# W7 ★라우트가 판단을 다시 구현하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_route_delegates_instead_of_reimplementing(client, monkeypatch):
    """★기록 스파이★ 라우트가 `rebalance_decision` 을 직접 부르면 위임이 아니다."""
    seen: list[dict] = []
    real = dec_mod.decide

    def spy(cur, tgt, **kw):
        seen.append(kw)
        return real(cur, tgt, **kw)

    monkeypatch.setattr(dec_mod, "decide", spy)
    _post(client, record_decision=True, case_id="rc_spy")

    assert len(seen) == 1, "결정 합성을 거치지 않았다"
    assert seen[0]["persist"] is True
    assert seen[0]["case_id"] == "rc_spy"


def test_the_persist_flag_follows_the_request(client, monkeypatch):
    """★짝★ 항상 `persist=True` 로 넘기면 W1 의 규율이 무너진다."""
    seen: list[dict] = []
    real = dec_mod.decide
    monkeypatch.setattr(dec_mod, "decide",
                        lambda c, t, **kw: (seen.append(kw), real(c, t, **kw))[1])
    _post(client)
    assert seen[0]["persist"] is False


# ══════════════════════════════════════════════════════════════════════════
# W8·W9 실패와 미결정
# ══════════════════════════════════════════════════════════════════════════
def test_a_storage_failure_does_not_break_the_response(client, monkeypatch):
    """★판단은 이미 났다★ 저장에 실패했다고 500 을 내면 그 판단까지 잃는다."""
    monkeypatch.setattr(idec, "_engine", lambda engine=None: None)
    body = _post(client, record_decision=True)
    assert body["decision"] in ("trade", "hold", "undetermined")
    assert body["persisted"] is False and body["persist_reason"]
    assert body["dec_id"] is None


def test_a_raising_store_does_not_become_a_500(client, monkeypatch):
    """★짝★ 스토어가 `None` 을 돌려주는 실패와 **예외를 던지는** 실패는 다르다.

    앞 테스트는 `_engine` 이 `None` 인 경로만 지난다 — 그때 스토어는 방어적으로
    `None` 을 돌려주므로 `decide()` 의 `try/except` 는 **한 번도 실행되지 않는다**.
    그 `except` 를 지워도 앞 테스트는 그대로 통과했다(변이 V6 생존). 그런데 이
    라우트의 바깥 `except` 는 예외를 **500** 으로 바꾼다 — 이미 난 판단까지 잃는다.
    """
    def boom(*a, **kw):
        raise RuntimeError("디스크가 가득 찼습니다")

    monkeypatch.setattr(idec, "save_decision", boom)
    body = _post(client, record_decision=True)   # ★200 이어야 한다★
    assert body["decision"] in ("trade", "hold", "undetermined")
    assert body["persisted"] is False and body["dec_id"] is None
    assert "RuntimeError" in body["persist_reason"], body["persist_reason"]


def test_the_pre_universe_branch_reports_the_same_keys(client, eng):
    """★모든 분기가 같은 키를 낸다★

    자산이 2개 미만이면 라우트는 **결정 계층에 닿기 전에** 조기 반환한다. 그 응답이
    `dec_id`/`persisted` 를 빼먹으면 소비자가 `.get()` 으로 읽다가 `None` 을 거짓으로
    취급한다(레지스트리 `not_ingested` 가 같은 이유로 모든 분기에서 나온다).

    ★그리고 이 분기는 기록되지 않는 것이 맞다★ — 문제를 세울 수조차 없었으므로
    기록할 **판단**이 없다. 그 사실을 `persist_reason` 이 말한다.
    """
    r = client.post(URL, json=_body(tickers=["005930"], holdings={"005930": 100.0},
                                    record_decision=True))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["available"] is False and body["decision"] == "undetermined"
    for key in ("dec_id", "persisted", "persist_reason"):
        assert key in body, f"조기 반환이 {key} 를 빼먹었다"
    assert body["persisted"] is False and body["dec_id"] is None
    assert "결정 계층" in body["persist_reason"]
    assert idec.list_decisions(engine=eng) == []


def test_the_normal_branch_still_carries_those_keys(client):
    """★짝★ 조기 반환에만 키를 붙이고 정상 경로에서 빠지면 같은 결함이다."""
    body = _post(client)
    for key in ("dec_id", "persisted", "persist_reason"):
        assert key in body, key
