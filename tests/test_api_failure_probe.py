"""AQ2 — ★클라이언트를 만들지 않고 읽는다★

`kis_client.CircuitBreaker` 는 이미 연속 실패를 센다. 이 프로브는 그것을 **읽기만**
한다 — 세지도, 고치지도, ★만들지도★ 않는다.

★`get_kis_client()` 를 부르지 않는 것이 핵심★ — 부르면 감시 루프가 KIS 클라이언트를
만들게 되고, 그것은 AI 가 세운 *"감시는 브로커를 부르지 않는다"* 경계를 깬다
(`startup/lifecycle._monitor_account_state` 의 docstring 이 그 경계를 적는다).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.api_health import (
    BREAKER_CLOSED,
    BREAKER_HALF_OPEN,
    BREAKER_OPEN,
    BREAKER_UNKNOWN,
    OBSERVED,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_NO_CLIENT,
    SOURCE_UNKNOWN,
    UNOBSERVED,
)
from src.execution.api_failure_probe import probe

_MODULE = pathlib.Path("src/execution/api_failure_probe.py")


class _Breaker:
    """실물과 같은 모양의 breaker — `kis_client.CircuitBreaker` 의 공개 속성."""

    def __init__(self, failure_count=0, state=BREAKER_CLOSED):
        self.failure_count = failure_count
        self.state = {"closed": "CLOSED", "open": "OPEN",
                      "half_open": "HALF_OPEN"}.get(state, state)


class _BrokerClient:
    def __init__(self, breaker):
        self.circuit_breaker = breaker


class _MockLike:
    """`MockKISClient` 처럼 breaker 속성이 **없는** 클라이언트."""

    def get_balance(self):
        return {}


# ── 브로커 클라이언트 ──────────────────────────────────────────────────────

def test_a_broker_client_yields_the_count_and_state():
    obs = probe(_BrokerClient(_Breaker(failure_count=3)))
    assert obs["source"] == SOURCE_BROKER
    assert obs["count"] == 3 and obs["state"] == OBSERVED
    assert obs["breaker_state"] == BREAKER_CLOSED


def test_an_open_breaker_is_reported_as_blocking():
    obs = probe(_BrokerClient(_Breaker(failure_count=5, state=BREAKER_OPEN)))
    assert obs["breaker_state"] == BREAKER_OPEN
    assert obs["blocking"] is True


def test_a_half_open_zero_keeps_its_state():
    """★장애 중에도 0 이 나온다★ — 상태가 그 사실을 들고 있다."""
    obs = probe(_BrokerClient(_Breaker(failure_count=0, state=BREAKER_HALF_OPEN)))
    assert obs["count"] == 0
    assert obs["breaker_state"] == BREAKER_HALF_OPEN
    assert obs["recently_tripped"] is True


def test_an_unrecognised_breaker_state_is_not_taken_at_face_value():
    obs = probe(_BrokerClient(_Breaker(failure_count=1, state="정상")))
    assert obs["breaker_state"] == BREAKER_UNKNOWN


# ── ★mock 은 잴 대상이 아니다★ ──────────────────────────────────────────

def test_a_client_without_a_breaker_is_mock_sourced():
    obs = probe(_MockLike())
    assert obs["source"] == SOURCE_MOCK
    assert obs["count"] is None and obs["state"] == UNOBSERVED
    assert obs["reason"]


def test_the_real_mock_client_is_also_mock_sourced():
    """★실물로 확인한다★ — 가짜가 아니라 저장소의 `MockKISClient` 로."""
    from src.execution.kis_client import MockKISClient
    obs = probe(MockKISClient())
    assert obs["source"] == SOURCE_MOCK and obs["count"] is None


# ── 클라이언트가 없을 때 ───────────────────────────────────────────────────

def test_no_singleton_means_no_client_not_zero(monkeypatch):
    """★미상 ≠ 0★ — 잴 대상이 없으면 0 회 실패가 아니다."""
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    obs = probe()
    assert obs["source"] == SOURCE_NO_CLIENT
    assert obs["count"] is None and obs["reason"]


def test_an_existing_singleton_is_read_without_being_created(monkeypatch):
    """★짝★ — 싱글턴이 있으면 그것을 읽는다(만들지는 않는다)."""
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc, "_kis_singleton", _BrokerClient(_Breaker(2)),
                        raising=False)
    assert probe()["count"] == 2


def test_a_probe_failure_is_a_reason_not_a_crash():
    """★삼키되 사유를 남긴다★ — `{}` 나 사유 없는 미상은 금지(§4)."""
    class _Explodes:
        @property
        def circuit_breaker(self):
            raise RuntimeError("터졌다")

    obs = probe(_Explodes())
    assert obs["source"] == SOURCE_UNKNOWN
    assert obs["count"] is None and "터졌다" in obs["reason"]


# ── ★전수 트립와이어 — 클라이언트를 만들지 않는다★ ──────────────────────

def _called_names() -> set[str]:
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


def test_the_probe_never_creates_a_kis_client():
    """★감시는 브로커를 부르지 않는다★(AI 의 경계) — 구조로 건다."""
    called = _called_names()
    assert "get_kis_client" not in called
    assert "KISClient" not in called and "MockKISClient" not in called


def test_the_scanner_actually_sees_calls():
    """★테스트의 테스트★ — 0건이면 위 검사는 언제나 통과한다."""
    assert len(_called_names()) >= 3, _called_names()


def test_the_probe_does_not_mutate_the_breaker():
    """★읽기만 한다★ — 세는 로직 0줄이 이 프로그램의 경계다."""
    called = _called_names()
    assert not (called & {"record_failure", "record_success", "call_allowed"})


def test_the_probe_reads_the_singleton_without_importing_the_getter():
    """모듈이 `get_kis_client` 를 **이름으로도** 들이지 않는지."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.name for a in node.names)
    assert "get_kis_client" not in names


@pytest.mark.parametrize("obj", [object(), 42, "client"])
def test_a_shapeless_client_is_unknown_not_broker(obj):
    """★모르는 모양을 브로커로 읽지 않는다★ (`None` 은 싱글턴 경로에서 따로 잰다)"""
    assert probe(obj)["source"] != SOURCE_BROKER


# ── AR4 · ★마지막 실패의 종류가 관측과 함께 온다★ ───────────────────────

from src.domain.kis_failure import (  # noqa: E402
    FAULT_PROVIDER,
    FAULT_UNKNOWN,
    KIND_BUSINESS,
    KIND_TRANSPORT,
)

PROBE_KEYS = {"count", "state", "source", "breaker_state", "blocking",
              "recently_tripped", "streak", "reason", "note", "last_failure"}


class _BrokerWithHistory(_BrokerClient):
    def __init__(self, breaker, kind=None, rt_cd=None, status=None):
        super().__init__(breaker)
        self.last_failure_kind = kind
        self.last_failure_rt_cd = rt_cd
        self.last_failure_status = status


def test_the_probe_shape_is_pinned():
    assert set(probe(_BrokerClient(_Breaker(1)))) == PROBE_KEYS


def test_a_client_with_no_failure_yet_reports_none():
    """★아직 실패가 없으면 `None` 이다★ — 종류를 지어내지 않는다."""
    assert probe(_BrokerWithHistory(_Breaker(0)))["last_failure"] is None


def test_the_last_failure_kind_travels_with_the_count():
    obs = probe(_BrokerWithHistory(_Breaker(3), kind=KIND_TRANSPORT))
    assert obs["last_failure"]["kind"] == KIND_TRANSPORT
    assert obs["last_failure"]["fault"] == FAULT_PROVIDER


def test_a_business_last_failure_does_not_claim_fault():
    """★짝★ — `rt_cd` 의 뜻을 모르므로 책임 소재를 단정하지 않는다."""
    obs = probe(_BrokerWithHistory(_Breaker(5), kind=KIND_BUSINESS,
                                   rt_cd="1", status=200))
    lf = obs["last_failure"]
    assert lf["fault"] == FAULT_UNKNOWN and lf["fault_reason"]
    assert lf["rt_cd"] == "1" and lf["status"] == 200
    # ★지금은 업무 응답도 카운터에 들어간다는 사실이 보인다★
    assert lf["counted_by_breaker"] is True


def test_a_mock_client_has_no_last_failure():
    from src.execution.kis_client import MockKISClient
    assert probe(MockKISClient())["last_failure"] is None


_TYPES_TS = pathlib.Path("frontend/src/entities/kill-switch/types.ts")


def test_the_frontend_type_declares_every_probe_key():
    """★타입은 화면이 없어도 계약이다★ — 키가 빠지면 `undefined` 로 샌다."""
    src = _TYPES_TS.read_text(encoding="utf-8")
    block = src.split("export interface ApiFailureObservation {", 1)[1].split("\n}", 1)[0]
    declared = {line.split(":", 1)[0].strip()
                for line in block.splitlines()
                if ":" in line and not line.strip().startswith(("*", "/"))}
    assert PROBE_KEYS <= declared, PROBE_KEYS - declared


def test_the_frontend_type_declares_the_failure_label():
    src = _TYPES_TS.read_text(encoding="utf-8")
    block = src.split("export interface KisFailureLabel {", 1)[1].split("\n}", 1)[0]
    declared = {line.split(":", 1)[0].strip()
                for line in block.splitlines()
                if ":" in line and not line.strip().startswith(("*", "/"))}
    expected = {"kind", "label", "fault", "fault_reason", "counted_by_breaker",
                "rt_cd", "msg_cd", "status", "kis_msg", "note"}
    assert expected <= declared, expected - declared
