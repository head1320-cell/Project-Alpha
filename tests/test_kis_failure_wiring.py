"""AR2·AR3 — 실패에 종류가 붙고, 기록이 그 종류를 말한다. ★세는 것은 0줄★

이 파일이 못 박는 것 셋:

    ① `_request`/`_fetch_token` 이 `KISCallError` 를 던지고 **메시지 문구는
       예전 그대로**다(`tests/test_ingest_doctor.py` 가 부분문자열을 단언한다).
    ② ★`record_failure()` 를 부르는 자리의 개수·위치가 바뀌지 않았다★ —
       `COUNTED_BY_BREAKER` 는 정책이 아니라 **지금 동작의 기술**이고, AST 가
       기술과 코드를 대조한다.
    ③ `_fail_order` 의 `reason_code` 가 상수 `"api_error"` 를 벗고 **종류**가 된다.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.kis_failure import (  # noqa: E402
    COUNTED_BY_BREAKER,
    FAULT_PROVIDER,
    FAULT_SELF,
    FAULT_UNKNOWN,
    KIND_BLOCKED,
    KIND_BUSINESS,
    KIND_MALFORMED,
    KIND_TOKEN,
    KIND_TRANSPORT,
)
from src.execution.kis_client import (  # noqa: E402
    KISCallError,
    KISClient,
    KISCredentials,
)
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402

_CLIENT_SRC = pathlib.Path("src/execution/kis_client.py")
_EXECUTOR_SRC = pathlib.Path("src/execution/order_executor.py")


class _Resp:
    """`requests.Response` 흉내 — 본문이 JSON 이 아닐 수도 있다."""

    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload = payload if payload is not None else {"rt_cd": "0"}
        self.status_code = status_code
        self._bad_json = bad_json
        self.text = "(본문)"

    def json(self):
        if self._bad_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


@pytest.fixture()
def client(monkeypatch):
    c = KISClient(KISCredentials(app_key="k", app_secret="s", account_no="5012",
                                 is_paper=True))
    # 토큰 발급을 타지 않게 — `_request` 만 재는 테스트다.
    monkeypatch.setattr(c, "_ensure_token", lambda: None)
    monkeypatch.setattr(c, "_headers", lambda *a, **k: {})
    return c


def _send(monkeypatch, responder):
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc.requests, "request", responder)


# ── ★차단은 실패가 아니다★ ──────────────────────────────────────────────

def test_a_blocked_call_is_labelled_and_not_counted(client, monkeypatch):
    client.circuit_breaker.state = "OPEN"
    from datetime import datetime
    client.circuit_breaker.last_failure_time = datetime.now()
    client.circuit_breaker.failure_count = 5

    with pytest.raises(KISCallError) as ei:
        client._request("GET", "/x", {})
    assert ei.value.kind == KIND_BLOCKED
    # ★차단은 카운트를 올리지 않는다★ (지금과 같은 동작)
    assert client.circuit_breaker.failure_count == 5
    assert "Circuit breaker OPEN" in str(ei.value)      # 문구 불변


# ── 전송 ───────────────────────────────────────────────────────────────────

def test_a_transport_error_is_transport_and_is_counted(client, monkeypatch):
    import src.execution.kis_client as kc

    def _boom(**kw):
        raise kc.requests.exceptions.ConnectTimeout("연결 시간 초과")

    _send(monkeypatch, _boom)
    before = client.circuit_breaker.failure_count
    with pytest.raises(KISCallError) as ei:
        client._request("GET", "/x", {})
    assert ei.value.kind == KIND_TRANSPORT
    assert client.circuit_breaker.failure_count == before + 1
    assert "네트워크 오류" in str(ei.value)              # 문구 불변


# ── ★업무 응답 — 세어지지만 뜻은 미상★ ─────────────────────────────────

def test_a_business_outcome_carries_its_code_and_is_still_counted(client, monkeypatch):
    """★안전 역전이 보인다★ — 장 종료가 장애와 같은 카운터에 들어간다."""
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "1", "msg1": "장 종료"}))
    before = client.circuit_breaker.failure_count
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    err = ei.value
    assert err.kind == KIND_BUSINESS
    assert err.rt_cd == "1" and err.kis_msg == "장 종료" and err.status == 200
    assert client.circuit_breaker.failure_count == before + 1   # 지금과 같은 동작
    assert "KIS API 실패" in str(err)                    # 문구 불변


def test_a_business_outcome_does_not_claim_who_is_at_fault(client, monkeypatch):
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "1", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    assert ei.value.label()["fault"] == FAULT_UNKNOWN
    assert ei.value.label()["fault_reason"]


def test_a_success_resets_the_counter(client, monkeypatch):
    """★짝★ — 성공을 실패로 분류하지 않고, 연속 카운트를 0 으로 되돌린다."""
    client.circuit_breaker.failure_count = 3
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "0", "output": {}}))
    assert client._request("GET", "/x", {})["rt_cd"] == "0"
    assert client.circuit_breaker.failure_count == 0


# ── ★본문이 JSON 이 아니면 — 이름은 주되 세지는 않는다★ ────────────────

def test_a_non_json_body_gets_a_kind_but_is_not_counted(client, monkeypatch):
    """지금은 이 실패가 **분류도 기록도 없이** 샌다. 이름만 준다."""
    _send(monkeypatch, lambda **kw: _Resp(bad_json=True, status_code=502))
    before = client.circuit_breaker.failure_count
    with pytest.raises(KISCallError) as ei:
        client._request("GET", "/x", {})
    assert ei.value.kind == KIND_MALFORMED
    assert ei.value.status == 502
    # ★세는 것은 바꾸지 않았다★
    assert client.circuit_breaker.failure_count == before


# ── 토큰 ───────────────────────────────────────────────────────────────────

def test_a_token_failure_keeps_its_wording_and_is_not_counted(monkeypatch):
    """`tests/test_ingest_doctor.py` 가 이 문구의 부분문자열을 단언한다."""
    import src.execution.kis_client as kc
    c = KISClient(KISCredentials(app_key="k", app_secret="s", account_no="5012",
                                 is_paper=True))
    monkeypatch.setattr(kc.requests, "post",
                        lambda *a, **kw: _Resp({"msg": "nope"}, status_code=403))
    before = c.circuit_breaker.failure_count
    with pytest.raises(KISCallError) as ei:
        c._fetch_token()
    assert ei.value.kind == KIND_TOKEN
    assert "토큰 발급 실패" in str(ei.value)
    assert c.circuit_breaker.failure_count == before


# ── 하위호환 ───────────────────────────────────────────────────────────────

def test_the_error_is_still_a_runtime_error(client, monkeypatch):
    """★소비자는 전부 `except Exception` 이지만, 하위형이라 어느 쪽도 깨지지 않는다★"""
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "7"}))
    with pytest.raises(RuntimeError):
        client._request("GET", "/x", {})


def test_the_label_is_available_from_the_exception(client, monkeypatch):
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "7", "msg1": "거부"}))
    with pytest.raises(KISCallError) as ei:
        client._request("GET", "/x", {})
    label = ei.value.label()
    assert label["kind"] == KIND_BUSINESS and label["rt_cd"] == "7"
    assert label["counted_by_breaker"] is True


# ── ★AST ① — 기술이 코드와 어긋나면 죽는다★ ────────────────────────────

def _request_fn() -> ast.FunctionDef:
    tree = ast.parse(_CLIENT_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_request":
            return node
    raise AssertionError("`_request` 를 찾지 못했습니다")


def _statement_lists(node) -> list[list]:
    """트리 안의 모든 **문장 목록**(형제 문장 묶음)을 모은다."""
    out: list[list] = []
    for n in ast.walk(node):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(n, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                out.append(block)
    return out


def _kinds_recorded_in(fn: ast.FunctionDef) -> set[str]:
    """`record_failure()` 와 **같은 블록**에서 raise 되는 `kind=` 값만 모은다.

    ★형제 문장으로 좁히는 이유★ — 바깥 `try` 로 훑으면 그 안의 다른 분기(본문
    파싱 실패 등)까지 빨려 들어가, 세지 않는 종류가 세는 것처럼 보인다.
    """
    kinds: set[str] = set()
    for block in _statement_lists(fn):
        records = any(
            isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Attribute)
            and st.value.func.attr == "record_failure"
            for st in block)
        if not records:
            continue
        for st in block:
            if not isinstance(st, ast.Raise) or not isinstance(st.exc, ast.Call):
                continue
            for kw in st.exc.keywords:
                if kw.arg == "kind" and isinstance(kw.value, ast.Name):
                    kinds.add(kw.value.id)
    return kinds


def test_the_counted_kinds_match_what_the_code_actually_records():
    """★`COUNTED_BY_BREAKER` 는 기술이다★ — 코드와 어긋나면 기술이 거짓이 된다."""
    names = _kinds_recorded_in(_request_fn())
    expected = {"KIND_TRANSPORT", "KIND_BUSINESS"}
    assert names == expected, names
    assert {"KIND_TRANSPORT", "KIND_BUSINESS"} == {
        f"KIND_{k.upper()}" for k in COUNTED_BY_BREAKER}


def test_the_number_of_record_failure_sites_is_unchanged():
    """★동작 0줄★ — 새 분기에서 몰래 세기 시작하는 것을 막는다."""
    fn = _request_fn()
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "record_failure"]
    assert len(calls) == 2, len(calls)


def test_the_scanner_actually_finds_the_function():
    """★테스트의 테스트★"""
    assert len(_request_fn().body) > 3


# ── ★AST ② — reason_code 가 상수를 벗었다★ ────────────────────────────

def test_fail_order_does_not_hardcode_a_reason_code():
    """★상수가 관측 행세를 하지 못하게★ (AA2 관용구)"""
    src = _EXECUTOR_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_fail_order")
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "api_error" not in consts, "reason_code 가 다시 상수로 박혔다"


def test_fail_order_takes_the_exception():
    fn_src = _EXECUTOR_SRC.read_text(encoding="utf-8")
    tree = ast.parse(fn_src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_fail_order")
    args = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    assert "exc" in args, args


# ── 실물 — 기록이 종류를 말한다 ───────────────────────────────────────────

class _RejectingKIS:
    """주문을 업무 거절하는 가짜 브로커."""

    def __init__(self):
        self.circuit_breaker = None

    def get_balance(self):
        return {"positions": [], "evaluated_total": 1_000_000, "cash_krw": 1_000_000}

    def place_order(self, **kw):
        raise KISCallError("KIS API 실패: rt_cd=1, msg=장 종료",
                           kind=KIND_BUSINESS, rt_cd="1", status=200, kis_msg="장 종료")


def _executor(kis):
    from src.execution.audit_trail import AuditTrail
    from src.execution.kill_switch import KillSwitch
    from src.execution.order_executor import OrderExecutor
    from src.execution.risk_gateway import RiskGateway
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng, OrderExecutor(engine=eng, kis_client=kis,
                              risk_gateway=RiskGateway(eng),
                              audit_trail=AuditTrail(eng),
                              kill_switch=KillSwitch(eng, None))


def test_the_failed_order_row_names_the_kind_not_api_error():
    """★실물★ — `reason_code` 가 `"api_error"` 가 아니라 종류다."""
    eng, ex = _executor(_RejectingKIS())
    out = ex._fail_order("COID-1", {"ticker": "005930"}, "KIS API 실패: rt_cd=1",
                         [], mode="PAPER",
                         exc=KISCallError("KIS API 실패: rt_cd=1, msg=장 종료",
                                          kind=KIND_BUSINESS, rt_cd="1", status=200,
                                          kis_msg="장 종료"))
    assert out["status"] == "FAILED"
    with eng.begin() as c:
        c.execute(text("INSERT INTO live_orders (client_order_id, strategy_id, "
                       "ticker, side, quantity, status, execution_mode) VALUES "
                       "('COID-2', 1, '005930', 'BUY', 1, 'PENDING', 'PAPER')"))
    ex._fail_order("COID-2", {"ticker": "005930"}, "err", [], mode="PAPER",
                   exc=KISCallError("x", kind=KIND_TRANSPORT))
    with eng.connect() as c:
        row = c.execute(text("SELECT reason_code FROM live_orders "
                             "WHERE client_order_id='COID-2'")).fetchone()
    assert row[0] == KIND_TRANSPORT


def test_an_unclassified_failure_still_records_something():
    """★짝★ — 예외가 종류를 모르면 `unknown` 이지 `api_error` 가 아니다."""
    eng, ex = _executor(_RejectingKIS())
    with eng.begin() as c:
        c.execute(text("INSERT INTO live_orders (client_order_id, strategy_id, "
                       "ticker, side, quantity, status, execution_mode) VALUES "
                       "('COID-3', 1, '005930', 'BUY', 1, 'PENDING', 'PAPER')"))
    ex._fail_order("COID-3", {"ticker": "005930"}, "boom", [], mode="PAPER",
                   exc=ValueError("생판 다른 예외"))
    with eng.connect() as c:
        row = c.execute(text("SELECT reason_code FROM live_orders "
                             "WHERE client_order_id='COID-3'")).fetchone()
    assert row[0] == "unknown"


def test_the_fault_of_a_transport_failure_is_the_provider():
    err = KISCallError("x", kind=KIND_TRANSPORT)
    assert err.label()["fault"] == FAULT_PROVIDER


def test_the_fault_of_a_blocked_call_is_ourselves():
    err = KISCallError("x", kind=KIND_BLOCKED)
    assert err.label()["fault"] == FAULT_SELF
