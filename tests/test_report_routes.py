"""AD5 — 리포트의 계약: ★값을 옮기기만 한다★.

리포트가 숫자를 하나라도 새로 만들면 그 숫자에는 **출처가 없다**. 출처 없는 수치가
한 장에 정리돼 있으면 그것이 가장 설득력 있는 거짓말이므로, 이 파일은 리포트의
**모든 수치 리프**가 출처 응답에 그대로 있는지 전수로 확인한다.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.report_routes import (
    BLOCK_ACCOUNT,
    BLOCK_DIAGNOSTICS,
    BLOCK_EXPLANATION,
    BLOCK_REBALANCE,
    REPORT_BLOCKS,
)
from src.domain.account_policy import ACCOUNT_IRP

_MODULE = pathlib.Path(__file__).resolve().parents[1] / "src" / "api" / "report_routes.py"

_EQUITY = "069500"
_RATES = "153130"
_HOLDINGS = {_EQUITY: 60.0, _RATES: 40.0}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    # ★`with TestClient(...)` 를 쓰지 않는다★ — 모듈 스코프에서 컨텍스트를 닫으면
    # 앱 **shutdown 이벤트**가 발화해 공용 백테스트 워커 풀이 세션 내내 닫힌다
    # (실측: 뒤따르는 backtest 테스트 2개 실패 + 12개가 "실행 저장소를 쓸 수 없다"
    # 로 스킵). 이 표면은 startup 이벤트가 필요 없으므로 집 관용구
    # (`test_holdings_diagnostics.py`)대로 컨텍스트 없이 만든다.
    return TestClient(create_app())


def _report(client, **kw):
    body = {"holdings": _HOLDINGS, "weight_unit": "percent"}
    return client.post("/api/v1/report/portfolio", json={**body, **kw})


def _numeric_leaves(node: Any, out: set[float] | None = None) -> set[float]:
    """중첩 구조의 모든 수치 리프를 모은다. ★bool 은 수치가 아니다★"""
    if out is None:
        out = set()
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.add(round(float(node), 9))
    elif isinstance(node, dict):
        for v in node.values():
            _numeric_leaves(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _numeric_leaves(v, out)
    return out


# ── 구조 ────────────────────────────────────────────────────────────────────

def test_the_report_always_carries_every_block(client):
    body = _report(client).json()
    assert set(body["blocks"]) == set(REPORT_BLOCKS)


def test_a_missing_block_is_reported_not_dropped(client):
    """★조용히 빠지면 '문제 없었나 보다' 로 읽힌다★."""
    body = _report(client).json()
    account = body["blocks"][BLOCK_ACCOUNT]
    assert account["available"] is False
    assert account["reason"]
    assert BLOCK_ACCOUNT in body["unavailable_blocks"]


def test_an_unrequested_block_says_it_was_not_asked(client):
    """★"결과가 없다" 와 "묻지 않았다" 를 가른다★."""
    body = _report(client).json()
    assert "묻지 않았다" in body["blocks"][BLOCK_REBALANCE]["reason"]


def test_supplying_the_account_makes_that_block_available(client):
    """★짝★ — 언제나 available:false 를 내는 구현을 배제한다."""
    body = _report(client, account_type=ACCOUNT_IRP,
                   risky_asset_classes=["EQUITY"]).json()
    assert body["blocks"][BLOCK_ACCOUNT]["available"] is True
    assert BLOCK_ACCOUNT not in body["unavailable_blocks"]


def test_one_failing_block_does_not_swallow_the_report(client):
    """한 블록이 거부돼도 나머지는 나온다."""
    body = _report(client, account_type="crypto_wallet").json()
    assert body["blocks"][BLOCK_ACCOUNT]["available"] is False
    assert body["blocks"][BLOCK_EXPLANATION]["available"] is True


# ── ★핵심 계약★ — 새 숫자가 없다 ────────────────────────────────────────

def test_every_number_in_the_report_exists_in_a_source_response(client):
    """★전수★ — 리포트의 수치 리프가 출처 응답의 수치 리프에 모두 들어 있다.

    합계·평균·재계산을 넣는 순간 출처에 없는 값이 생겨 실패한다.
    """
    report = _report(client, account_type=ACCOUNT_IRP,
                     risky_asset_classes=["EQUITY"]).json()

    sources: list[dict] = []
    sources.append(client.post("/api/v1/diagnostics/holdings", json={
        "holdings": _HOLDINGS, "weight_unit": "percent"}).json())
    sources.append(client.post("/api/v1/explain/daily", json={
        "holdings": _HOLDINGS, "weight_unit": "percent"}).json())
    sources.append(client.post("/api/v1/accounts/diagnose", json={
        "account_type": ACCOUNT_IRP, "holdings": _HOLDINGS,
        "risky_asset_classes": ["EQUITY"]}).json())

    source_numbers = set()
    for s in sources:
        source_numbers |= _numeric_leaves(s)

    # ★응답 **전체**를 훑는다★ — 변이 배터리에서 `blocks` 안만 보는 판본이
    # 최상위에 끼운 가짜 합계를 놓쳤다. 리포트가 숫자를 만들 수 있는 자리는
    # 블록 안만이 아니다.
    report_numbers = _numeric_leaves(report)

    invented = report_numbers - source_numbers
    assert not invented, f"리포트가 출처에 없는 수치를 만들었다: {sorted(invented)[:20]}"


def test_the_report_has_no_numbers_of_its_own_outside_the_blocks(client):
    """★최상위에도 수치가 없다★ — 블록 밖은 구조와 사유 문자열뿐이어야 한다."""
    report = _report(client).json()
    shell = {k: v for k, v in report.items() if k != "blocks"}
    assert _numeric_leaves(shell) == set(), f"블록 밖에 수치가 있다: {shell}"


def test_the_leaf_detector_actually_detects():
    """★테스트의 테스트★ — 검출기가 빈 집합을 내면 위 검사가 무력해진다."""
    assert _numeric_leaves({"a": 1, "b": [2.5, {"c": 3}]}) == {1.0, 2.5, 3.0}
    assert _numeric_leaves({"flag": True}) == set(), "bool 을 수치로 셌다"


def test_a_fabricated_total_would_be_caught():
    """가짜 합계를 끼우면 위 계약이 잡는지 직접 확인한다."""
    source = {"a": 1.0, "b": 2.0}
    faked = {"a": 1.0, "b": 2.0, "total": 3.0}
    invented = _numeric_leaves(faked) - _numeric_leaves(source)
    assert invented == {3.0}


def test_the_report_module_contains_no_arithmetic():
    """★소스 전수★ — 조립기에 산술 연산이 생기면 실패한다.

    값을 옮기기만 하는 모듈에는 `+ - * /` 가 필요 없다. 생기는 순간 그것이
    "새 숫자" 의 입구다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    ops = [
        type(node.op).__name__
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv))
    ]
    # 문자열 결합(f-string 이 아닌 `+`)도 여기 걸리지만, 그것도 쓰지 않는 편이 낫다.
    assert not ops, f"리포트 조립기에 산술 연산이 있다: {ops}"


# ── 결정론 ──────────────────────────────────────────────────────────────────

def test_the_same_request_yields_the_same_report(client):
    """같은 입력 → 같은 응답. 리포트가 시각·난수를 끼워 넣지 않는다."""
    a = _report(client, account_type=ACCOUNT_IRP, risky_asset_classes=["EQUITY"]).json()
    b = _report(client, account_type=ACCOUNT_IRP, risky_asset_classes=["EQUITY"]).json()
    assert a == b


def test_the_report_declares_what_it_is(client):
    body = _report(client).json()
    assert "조립" in body["note"]


# ── 인증 경계 ──────────────────────────────────────────────────────────────

def test_the_report_answers_without_a_token(client):
    assert _report(client).status_code == 200


# ── ★평문 응답에 마크다운·중복 서술어가 없다★ ──────────────────────────

#: ★같은 결함(평문 응답의 마크다운)이 AB·AD·AF 에서 세 번 났다★ — 모듈을 하나씩
#: 더하는 대신 **API 가 문장을 내는 모듈**을 넓게 잡는다.
_PLAINTEXT_MODULES = (
    "src/api/report_routes.py",
    "src/api/account_policy_routes.py",
    "src/api/scorecard_routes.py",
    "src/api/stage13_routes.py",
    "src/engine/risky_share.py",
    "src/domain/account_policy.py",
    "src/domain/distribution_gate.py",
    "src/domain/strategy_scorecard.py",
    "src/execution/kill_switch.py",
    # AP — 조치 사유·note 가 `/kill-switch/*` 응답으로 그대로 나간다.
    "src/domain/kill_action.py",
    # AQ — 관측 사유·note 가 `/kill-switch/readiness` 응답으로 나간다.
    "src/domain/api_health.py",
    # AR — 실패 종류의 책임 사유·note 가 같은 응답에 실려 나간다.
    "src/domain/kis_failure.py",
    # AS — 표의 미상 사유·note 가 `/kill-switch/kis-codes` 응답으로 나간다.
    "src/domain/kis_rt_cd.py",
    # AT — 구성 사유·문장이 `auto_api` 발동 사유로 `live_kill_events` 에 남는다.
    "src/domain/failure_streak.py",
    # AU — 관문의 미충족 사유가 `/kill-switch/kis-codes` 응답으로 나간다.
    "src/domain/breaker_change_gate.py",
    # AV — 신호 출처 등급의 사유·note 가 `GET /signals` 응답으로 나간다.
    "src/domain/signal_evidence.py",
    # AX — §6.1 "소스 없음" 사유·설명이 타이밍 팩터 카탈로그 응답으로 나간다.
    "src/engine/timing_factor_meta.py",
    # AY — 공급 모듈이 없는 묶음의 사유·막는 질문이 `GET /signals` 로 나간다.
    "src/domain/signal_supply.py",
    # AZ — 요율 출처의 사유·note 가 백테스트 `cost_model` 블록으로 나간다.
    "src/domain/cost_provenance.py",
)


def _response_strings(rel: str) -> list[str]:
    """모듈의 **모듈 수준 문자열 상수**만 (docstring 은 사람이 읽는 주석이라 제외)."""
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / rel)
                     .read_text(encoding="utf-8"))
    out: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for value in ast.walk(node.value):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.append(value.value)
    return out


def test_no_markdown_leaks_into_plaintext_responses():
    """★AB 에서 세운 규율★ — API 가 내는 문장은 평문이다. `**` 가 그대로 보인다."""
    offenders = [
        (rel, text) for rel in _PLAINTEXT_MODULES
        for text in _response_strings(rel) if "**" in text
    ]
    assert not offenders, f"평문 응답에 마크다운이 있다: {offenders}"


def test_the_not_requested_tail_has_no_predicate_of_its_own(client):
    """★눈으로 찾은 결함★ — 앞 절과 서술어가 겹쳐 "요청하지 않았습니다 —
    요청하지 않았습니다" 가 되던 문장. 꼬리말은 의미만 확정하고 동사를 갖지 않는다."""
    body = _report(client).json()
    reason = body["blocks"][BLOCK_REBALANCE]["reason"]
    assert reason.count("요청하지 않았습니다") == 1, reason
    assert reason.count("—") == 1, f"이중 대시: {reason}"


def test_every_unavailable_block_reason_reads_as_one_sentence(client):
    """전수 — 막힌 블록의 사유가 전부 중복 서술어·이중 대시 없이 나온다."""
    body = _report(client, account_type="crypto_wallet").json()
    for name, blk in body["blocks"].items():
        if blk["available"]:
            continue
        assert blk["reason"].count("—") <= 1, f"{name}: {blk['reason']}"
        assert "**" not in blk["reason"], f"{name}: 마크다운"
