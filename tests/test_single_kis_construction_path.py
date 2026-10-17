"""BV2 — ★KIS 클라이언트를 만드는 길은 하나다★ (CLAUDE.md §6 "KIS 연동은 `get_kis_client()` 단일 경로").

BV0 감사가 찾은 것: 실거래 실행기(`src/api/stage13_routes.py::get_executor`)가 `KIS_USE_MOCK` 을 직접 읽고
`KISClient(KISCredentials(os.environ[...]))`·`MockKISClient(...)` 를 ★따로 만들었다★. 운영에서는 같은 앱 키로 토큰·
속도 제한·회로 차단기가 둘이 된다(KIS 토큰 발급은 분당 1회). 그 규칙을 지키는 테스트는 없었다
(`test_no_order_executor_bypass` 는 `kis_order_executor.OrderExecutor` import 만 본다).

여기서 고정하는 것:
  ① `KISClient(`·`MockKISClient(`·`KISCredentials(` 호출은 `src/execution/kis_client.py` 안에서만
  ② `KIS_USE_MOCK` 을 읽는 호출은 `src/data/mock_gate.py` 안에서만(mock 판정은 `mock_allowed()` 하나)
  ③ 실행기는 단일 경로의 클라이언트를 쓴다 · 운영에서 계좌번호가 없으면 실행기를 만들지 않고 사유를 말한다
  ④ 싱글턴은 동시 첫 호출에도 하나만 만든다
  ⑤ 자격 정보의 repr 에 비밀이 나오지 않는다
"""
from __future__ import annotations

import ast
import os
import pathlib
import tempfile
import threading
import time

import pytest

import src.database as dbmod
import src.execution.kis_client as kc

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY = ROOT / "src/execution/kis_client.py"
MOCK_GATE = ROOT / "src/data/mock_gate.py"
CONSTRUCTORS = {"KISClient", "MockKISClient", "KISCredentials"}


def _scanned_files() -> list[pathlib.Path]:
    files = list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))
    files += [p for p in (ROOT / "main_api.py", ROOT / "verify_connection.py") if p.exists()]
    return files


def _constructions(source: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in CONSTRUCTORS:
                out.append(f"{name}(… line {node.lineno})")
    return out


def _mock_flag_reads(source: str) -> list[str]:
    """`KIS_USE_MOCK` 을 ★읽는★ 코드만 — 주석·안내 문구는 대상이 아니다."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in {"getenv", "get"} and node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == "KIS_USE_MOCK":
                out.append(f"{name}('KIS_USE_MOCK') line {node.lineno}")
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value == "KIS_USE_MOCK":
            out.append(f"environ['KIS_USE_MOCK'] line {node.lineno}")
    return out


# ── ① 만드는 곳은 하나 ─────────────────────────────────────────────────────

def test_kis_clients_are_constructed_only_in_the_factory_module():
    offenders = []
    for path in _scanned_files():
        if path == FACTORY:
            continue
        found = _constructions(path.read_text(encoding="utf-8"))
        offenders += [f"{path.relative_to(ROOT)}: {f}" for f in found]
    assert not offenders, "KIS 클라이언트·자격을 단일 경로 밖에서 만든다:\n  " + "\n  ".join(offenders)


def test_the_detector_catches_a_planted_construction():
    """★짝★ — 항상-빈 목록을 내는 검출기를 배제한다."""
    planted = "from x import KISClient, KISCredentials\nc = KISClient(KISCredentials('a','b','c'))\n"
    assert len(_constructions(planted)) == 2
    assert _constructions("c = get_kis_client()\n") == []


def test_the_factory_itself_does_construct_clients():
    """★짝★ — 공장 파일을 빼는 것이 실제로 무언가를 빼고 있다(검사가 공허하지 않다)."""
    assert _constructions(FACTORY.read_text(encoding="utf-8"))


# ── ② mock 판정은 mock_allowed() 하나 ─────────────────────────────────────

def _app_files() -> list[pathlib.Path]:
    """앱이 실행하는 코드만 — `scripts/`·`verify_connection.py` 는 진단 도구라 환경변수 ★원래 값을 보여 주는★ 곳이
    있다(`bench_backtest`·`diag_fundamentals`·`verify_connection` 이 `KIS_USE_MOCK` 값을 출력한다). 그것은 판정이 아니다."""
    return list((ROOT / "src").rglob("*.py")) + [p for p in (ROOT / "main_api.py",) if p.exists()]


def test_only_the_mock_gate_reads_the_mock_flag():
    offenders = []
    for path in _app_files():
        if path == MOCK_GATE:
            continue
        offenders += [f"{path.relative_to(ROOT)}: {r}" for r in _mock_flag_reads(path.read_text(encoding="utf-8"))]
    assert not offenders, "KIS_USE_MOCK 을 mock_allowed() 밖에서 직접 읽는다:\n  " + "\n  ".join(offenders)


def test_the_flag_detector_sees_reads_but_not_comments():
    """★짝★ — 읽기는 잡고, 안내 문구는 잡지 않는다."""
    assert _mock_flag_reads("import os\nx = os.getenv('KIS_USE_MOCK', '1')\n")
    assert _mock_flag_reads("import os\nx = os.environ['KIS_USE_MOCK']\n")
    assert not _mock_flag_reads("# KIS_USE_MOCK=1 이면 합성\nmsg = 'KIS_USE_MOCK=1 — 합성'\n")
    assert _mock_flag_reads(MOCK_GATE.read_text(encoding="utf-8")), "mock 게이트가 플래그를 읽지 않는다?"


# ── ③ 실행기는 단일 경로의 클라이언트를 쓴다 ────────────────────────────────

@pytest.fixture()
def fresh(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    import src.api.stage13_routes as stage13
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    yield stage13
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_in_mock_mode_the_executor_uses_the_shared_client(fresh, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    executor = fresh.get_executor()
    assert executor.kis is kc.get_kis_client()


def test_rebuilding_the_executor_still_uses_the_same_client(fresh, monkeypatch):
    """★짝★ — 실행기를 다시 만들어도 클라이언트를 새로 만들지 않는다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    first = fresh.get_executor().kis
    monkeypatch.setattr(fresh, "_EXECUTOR", None, raising=False)
    assert fresh.get_executor().kis is first


def _production_env(monkeypatch, *, account: str | None):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setenv("KIS_APP_KEY", "test-app-key-not-real")
    monkeypatch.setenv("KIS_APP_SECRET", "test-app-secret-not-real")
    monkeypatch.setenv("KIS_IS_PAPER", "1")
    if account is None:
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
    else:
        monkeypatch.setenv("KIS_ACCOUNT_NO", account)


def test_in_production_without_an_account_number_no_executor_is_built(fresh, monkeypatch):
    _production_env(monkeypatch, account=None)
    with pytest.raises(kc.KISCredentialsMissing) as err:
        fresh.get_executor()
    assert "KIS_ACCOUNT_NO" in str(err.value)
    assert fresh._EXECUTOR is None, "실패했는데 실행기를 반쯤 만든 채 남겼다"


def test_in_production_with_an_account_number_the_executor_uses_the_shared_client(fresh, monkeypatch):
    """★짝★ — 계좌번호가 있으면 만든다(항상-거절 배제). `KISClient` 생성은 토큰을 받지 않는다(네트워크 0)."""
    _production_env(monkeypatch, account="12345678")
    executor = fresh.get_executor()
    assert executor.kis is kc.get_kis_client()
    assert type(executor.kis).__name__ == "KISClient"
    assert executor.kis.creds.is_paper is True


# ── ④ 동시 첫 호출에도 하나 ───────────────────────────────────────────────

def test_concurrent_first_calls_build_exactly_one_client(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    built: list[int] = []

    class SlowMock(kc.MockKISClient):
        def __init__(self, *a, **kw):
            time.sleep(0.05)   # 경쟁 창을 넓힌다 — 잠금이 없으면 여러 스레드가 이 안에 동시에 있다
            built.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(kc, "MockKISClient", SlowMock)
    barrier = threading.Barrier(8)
    got: list[object] = []

    def call():
        barrier.wait()
        got.append(kc.get_kis_client())

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)

    assert len(built) == 1, f"클라이언트를 {len(built)}번 만들었다"
    assert len({id(c) for c in got}) == 1


# ── ⑤ repr 에 비밀이 없다 ─────────────────────────────────────────────────

def test_credentials_repr_hides_the_secrets():
    creds = kc.KISCredentials(app_key="APPKEY-123456", app_secret="SECRET-abcdef",
                              account_no="87654321", account_prdt="01", is_paper=True)
    text = repr(creds) + str(creds)
    for secret in ("APPKEY-123456", "SECRET-abcdef", "87654321"):
        assert secret not in text, f"repr 에 {secret} 이 보인다"
    # ★짝★ — 빈 repr 이 아니다 · 값 접근은 그대로다.
    assert "is_paper=True" in text and "account_prdt='01'" in text
    assert creds.app_key == "APPKEY-123456" and creds.account_no == "87654321"
