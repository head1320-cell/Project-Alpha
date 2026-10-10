"""AS1 · ★열쇠부터 잡는다★ — `msg_cd` 와 실행 모드가 기록에 남는가
==============================================================================
설계: `docs/superpowers/specs/2026-09-21-kis-rt-cd-table-design.md`

## 왜 이 파일이 생겼나

AR 이 실패의 종류를 갈랐지만 가장 많이 나오는 종류(`business`)의 뜻을 모른다.
뜻을 옮기려면 표가 필요하고, 표에는 **열쇠**가 필요하다. 그런데 실측하니
`msg_cd` 는 저장소 전체에서 0건이었다 — `_request` 는 `rt_cd` 와 `msg1` 만
읽고 응답의 나머지를 버렸다. ★표를 받아와도 join 할 것이 없었다.★

여기서 재는 것은 **두 가지**다:

1. `msg_cd` 가 응답에서 예외로, 예외에서 라벨로, 라벨에서 감사 기록으로
   **끝까지 간다**.
2. 실패 기록이 **어느 실행 모드에서 나왔는지** 말한다 — `live_audit_trail`
   에는 모드 칸이 없어서, 나중에 모의와 실계좌 관측이 조용히 합쳐진다.

## ★이 파일이 주장하지 않는 것★

- **`msg_cd` 가 KIS 응답에 있다고 말하지 않는다.** 이 저장소는 그 봉투를
  확인한 적이 없다(실계좌에 닿지 못한다). 있으면 싣고 없으면 `None` 이며,
  `None` 은 "KIS 가 주지 않는다" 가 아니라 **미상**이다.
- **코드의 뜻을 말하지 않는다.** 열쇠를 잡을 뿐이다.
"""
from __future__ import annotations

import pathlib

import pytest

from src.domain.kis_failure import (
    FAULT_UNKNOWN,
    KIND_BUSINESS,
    failure_label,
)
from src.execution.kis_client import KISCallError

_CLIENT_SRC = pathlib.Path("src/execution/kis_client.py")
_EXECUTOR_SRC = pathlib.Path("src/execution/order_executor.py")


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {"rt_cd": "0"}
        self.status_code = status_code
        self.text = "(본문)"

    def json(self):
        return self._payload


@pytest.fixture()
def client(monkeypatch):
    from src.execution import kis_client as kc

    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")
    c = kc.KISClient.__new__(kc.KISClient)
    c.circuit_breaker = kc.CircuitBreaker()
    c.rate_limiter = kc.RateLimiter()
    c.base_url = "https://example.invalid"
    c.timeout = 1
    c.last_failure_kind = None
    c.last_failure_rt_cd = None
    c.last_failure_status = None
    c.last_failure_msg_cd = None
    return c


def _send(monkeypatch, fn):
    from src.execution import kis_client as kc

    monkeypatch.setattr(kc.requests, "request", lambda **kw: fn(**kw))


# ── ★열쇠가 끝까지 간다★ ────────────────────────────────────────────────

def test_a_business_outcome_carries_msg_cd(client, monkeypatch):
    """★응답 → 예외★ — 버려지던 칸이 기록된다."""
    _send(monkeypatch, lambda **kw: _Resp(
        {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    assert ei.value.msg_cd == "APBK0013"


def test_the_label_carries_msg_cd_too(client, monkeypatch):
    """★예외 → 라벨★ — 라벨이 감사 기록에 그대로 실린다."""
    _send(monkeypatch, lambda **kw: _Resp(
        {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    label = ei.value.label()
    assert label["msg_cd"] == "APBK0013"
    assert label["rt_cd"] == "1"


def test_the_client_records_the_last_msg_cd(client, monkeypatch):
    """★한 칸짜리 기록이지 카운터가 아니다★(AR4 의 관용구를 잇는다)."""
    _send(monkeypatch, lambda **kw: _Resp(
        {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "장 종료"}))
    with pytest.raises(KISCallError):
        client._request("POST", "/order", {})
    assert client.last_failure_msg_cd == "APBK0013"


def test_a_missing_msg_cd_is_unknown_not_unsupported(client, monkeypatch):
    """★짝 — 미상 ≠ 미지원★

    이 저장소는 KIS 응답 봉투에 `msg_cd` 가 있는지 **확인한 적이 없다**.
    없으면 `None` 이고, `None` 을 "KIS 가 주지 않는다" 로 읽으면 확인한 적
    없는 것을 주장하게 된다.
    """
    _send(monkeypatch, lambda **kw: _Resp({"rt_cd": "1", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    assert ei.value.msg_cd is None
    assert ei.value.label()["msg_cd"] is None


def test_msg_cd_does_not_change_the_message_wording(client, monkeypatch):
    """★문구 불변★ — `tests/test_ingest_doctor.py` 의 부분문자열 계약."""
    _send(monkeypatch, lambda **kw: _Resp(
        {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    text = str(ei.value)
    assert "KIS API 실패" in text and "rt_cd=1" in text
    assert "APBK0013" not in text        # 문구에 새 값이 끼어들지 않는다


def test_msg_cd_does_not_make_the_repo_claim_a_fault(client, monkeypatch):
    """★열쇠를 잡은 것이지 뜻을 안 것이 아니다★ — 표가 비어 있다."""
    _send(monkeypatch, lambda **kw: _Resp(
        {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "장 종료"}))
    with pytest.raises(KISCallError) as ei:
        client._request("POST", "/order", {})
    assert ei.value.label()["fault"] == FAULT_UNKNOWN


def test_failure_label_defaults_msg_cd_to_none():
    """비-KIS 예외 경로도 같은 칸을 갖는다 — 키가 사라지지 않는다."""
    assert failure_label(KIND_BUSINESS)["msg_cd"] is None
    assert "msg_cd" in failure_label(None)


# ── ★모드를 섞지 않는다★ ────────────────────────────────────────────────

def test_the_failure_context_records_the_execution_mode():
    """★모의와 실계좌 관측을 합치면 그 수치는 아무것도 뜻하지 않는다★

    `live_audit_trail` 에는 모드 칸이 없다. 그래서 `_fail_order` 가 이미
    인자로 받고 있는 `mode` 를 `context` 에 남긴다 — DDL 변경 0줄.
    """
    src = _EXECUTOR_SRC.read_text(encoding="utf-8")
    import ast

    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_fail_order")
    # `context={...}` 딕셔너리에 execution_mode 키가 있고, 그 값이 인자 `mode` 다.
    found = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "execution_mode" not in keys:
            continue
        value = node.values[keys.index("execution_mode")]
        assert isinstance(value, ast.Name) and value.id == "mode", (
            "★상수가 관측 행세를 한다★ — 실행 모드는 인자에서 와야 한다")
        found = True
    assert found, "_fail_order 의 감사 context 에 execution_mode 가 없다"


def test_the_client_source_reads_msg_cd_from_the_response():
    """★트립와이어★ — 열쇠를 다시 버리면 죽는다(변이 c)."""
    src = _CLIENT_SRC.read_text(encoding="utf-8")
    assert 'data.get("msg_cd")' in src, (
        "응답에서 msg_cd 를 읽지 않으면 표에 붙일 열쇠가 없다")
