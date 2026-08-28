"""ALFRED 빈티지 백필의 ★도달 가능성★ — 만들어 놓고 부르지 않았다
==============================================================================
워크플로우: 감사문 `2026-08-28-macro-model-stack-audit.md` 부록 A.5 Track A2
패턴: `krx_ingest.auto_backfill` + `startup/lifecycle._krx_backfill_bg`

## 이 파일이 막는 것

`macro_vintage_backfill.backfill()` 은 ALFRED 를 `as_of` 별로 조회해 스토어에
**빈티지 있는 행**을 넣는 유일한 경로다. 그런데 실측 호출부가 **CLI `main()` 하나**
였다 — 즉 키를 넣어도 **아무도 부르지 않으므로** 빈티지는 영원히 0건이고,
관측 스토어는 영원히 `forward_only` 다. `krx_ingest` 는 같은 문제를
`auto_backfill` + startup 데몬으로 이미 풀어 두었다.

## ★적재가 판정을 자동으로 열어서는 안 된다★

국면 축의 PIT 판정은 **두 사실의 논리곱**이다(P2):

    ⑵ 수집 경로가 빈티지를 읽는가   `macro_collector.COLLECTOR_READS_VINTAGE`
    ⑶ 그 계열에 실제 빈티지 행이 있는가  `macro_observation_store.coverage`

이 작업은 ⑶ 만 채운다. ★⑵ 를 함께 올리면 키가 들어오는 순간 축이 `managed` 로
**저절로** 뒤집히고, 그것은 사람의 결정 없이 일어나는 Macro → Allocation 정책
변경이다★(CLAUDE.md §3). ⑵ 는 별도 승인으로 사람이 올린다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.macro_observation_store as mos  # noqa: E402
import src.data.macro_vintage_backfill as mvb  # noqa: E402


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    monkeypatch.setattr(mos, "_engine", lambda engine=None: eng)
    monkeypatch.delenv("MACRO_VINTAGE_AUTOBACKFILL", raising=False)
    monkeypatch.delenv("MACRO_VINTAGE_BACKFILL_START", raising=False)
    monkeypatch.delenv("MACRO_VINTAGE_MAX_CALLS", raising=False)
    yield


def _spy(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(mvb, "backfill",
                        lambda **kw: (calls.append(kw), {"rows": 3, "calls": 1})[1])
    return calls


# ══════════════════════════════════════════════════════════════════════════
# X1·X2 ★두 no-op 은 사유가 다르다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_missing_key_is_a_skip_with_a_reason_not_a_success(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    calls = _spy(monkeypatch)
    out = mvb.auto_vintage_backfill()
    assert "skipped" in out and "FRED_API_KEY" in out["skipped"]
    assert calls == [], "키도 없이 ALFRED 를 불렀다"


def test_the_env_switch_is_a_different_skip(monkeypatch):
    """★짝★ 두 사유가 같으면 '왜 안 돌았나' 에 답할 수 없다 — 고치는 사람이 다르다."""
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setenv("MACRO_VINTAGE_AUTOBACKFILL", "0")
    calls = _spy(monkeypatch)
    out = mvb.auto_vintage_backfill()
    assert "skipped" in out and "FRED_API_KEY" not in out["skipped"]
    assert "MACRO_VINTAGE_AUTOBACKFILL" in out["skipped"]
    assert calls == []


# ══════════════════════════════════════════════════════════════════════════
# X3 키가 있으면 실제로 부른다
# ══════════════════════════════════════════════════════════════════════════
def test_a_configured_key_actually_runs_the_backfill(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    calls = _spy(monkeypatch)
    out = mvb.auto_vintage_backfill()
    assert "skipped" not in out
    assert len(calls) == 1
    assert calls[0]["start"] and calls[0]["skip_covered"] is True


def test_the_call_budget_is_bounded_by_default(monkeypatch):
    """★쿼터를 통째로 태우지 않는다★ 21계열 × 월별 as_of 는 수천 콜이다."""
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    calls = _spy(monkeypatch)
    mvb.auto_vintage_backfill()
    assert calls[0]["max_calls"] is not None and calls[0]["max_calls"] > 0


def test_the_budget_can_be_lifted_explicitly(monkeypatch):
    """★짝★ 상한이 고정이면 실제 적재를 끝낼 방법이 없다."""
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setenv("MACRO_VINTAGE_MAX_CALLS", "0")
    calls = _spy(monkeypatch)
    mvb.auto_vintage_backfill()
    assert calls[0]["max_calls"] is None


def test_a_failing_backfill_does_not_raise(monkeypatch):
    """데몬에서 돈다 — 예외가 올라가면 startup 이 죽는다."""
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)

    def boom(**_kw):
        raise RuntimeError("ALFRED 503")

    monkeypatch.setattr(mvb, "backfill", boom)
    out = mvb.auto_vintage_backfill()
    assert out.get("error") and "RuntimeError" in str(out["error"])


# ══════════════════════════════════════════════════════════════════════════
# X4 ★핵심 불변 — 적재가 판정을 자동으로 열지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_loaded_vintages_do_not_open_the_axis_by_themselves(eng, monkeypatch):
    """★이 작업의 안전 계약★

    빈티지가 실제로 쌓여도(⑶ 참) 수집 경로가 그것을 읽지 않으면(⑵ 거짓) 축은
    `managed` 가 되면 **안 된다**. ⑵ 를 함께 올리면 키가 들어오는 순간 배분
    입력이 사람의 결정 없이 바뀐다.
    """
    from src.data.pit_macro import DataStatus, MacroObservation
    from src.engine.regime_axes import axis_revision_status

    before = {m: axis_revision_status(m) for m in ("kr", "us")}

    obs = [MacroObservation(
        series_id="DGS10", observation_period="2024-01", release_timestamp="",
        vintage_id=f"2024-0{i}-01..2024-0{i}-01", retrieved_at="2026-08-28T00:00:00Z",
        value=3.9 + i * 0.01, data_status=DataStatus.REAL) for i in (1, 2, 3)]
    assert mos.save(obs, source=mos.SOURCE_ALFRED, engine=eng) == 3
    cov = mos.coverage(["DGS10"], engine=eng)
    assert cov["by_series"]["DGS10"]["with_vintage"] > 0, "빈티지가 안 쌓였다"

    after = {m: axis_revision_status(m) for m in ("kr", "us")}
    assert after == before, "빈티지 적재만으로 축 판정이 움직였다"
    for m in ("kr", "us"):
        assert after[m]["revision_bias"] == "unmanaged"


def test_the_collector_flag_stays_a_human_gate():
    """⑵ 는 이 작업이 올리지 않는다 — 별도 승인 사항이다."""
    from src.services.macro_collector import COLLECTOR_READS_VINTAGE

    assert COLLECTOR_READS_VINTAGE is False, (
        "수집 경로 플래그가 올라갔다 — 축 개방은 별도 승인 사항이다")


# ══════════════════════════════════════════════════════════════════════════
# X5 ★도달 가능해졌는가★ — 그것이 이 작업의 전부다
# ══════════════════════════════════════════════════════════════════════════
def test_the_backfill_is_reachable_from_startup():
    """예전에는 호출부가 CLI `main()` 하나였다 — 키를 넣어도 아무도 부르지 않았다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src" / "startup" / "lifecycle.py").read_text(encoding="utf-8")
    assert "auto_vintage_backfill" in src, "startup 에서 도달할 수 없다"
    assert "_macro_vintage_backfill_bg" in src

    from src.startup import lifecycle
    assert callable(lifecycle._macro_vintage_backfill_bg)


def _enclosing_conditions(src: str, target: str) -> list[str]:
    """`target` 을 스레드로 띄우는 호출을 감싸는 **모든 `if` 조건**의 소스."""
    import ast

    tree = ast.parse(src)
    found: list[str] = []

    def walk(node, conds: list[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                walk(child, [*conds, ast.get_source_segment(src, child.test) or ""])
                for h in child.orelse:
                    walk(h, conds)
                continue
            if isinstance(child, ast.Call):
                seg = ast.get_source_segment(src, child) or ""
                if "Thread(" in seg and target in seg:
                    found.extend(conds)
            walk(child, conds)

    walk(tree, [])
    return found


def test_the_startup_daemon_is_registered_as_a_thread():
    """★짝★ 함수만 있고 등록이 없으면 여전히 아무도 부르지 않는다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src" / "startup" / "lifecycle.py").read_text(encoding="utf-8")
    hits = [ln for ln in src.splitlines()
            if "Thread(" in ln and "_macro_vintage_backfill_bg" in ln
            and not ln.lstrip().startswith("#")]
    assert hits, "데몬이 스레드로 등록되지 않았다"


def test_the_vintage_daemon_is_not_gated_on_an_unrelated_key():
    """★실제로 저지른 실수★ 이 데몬은 **FRED** 키가 필요한데 처음에 **KRX** 키
    게이트 안에 넣었다. 그러면 KRX 키가 없는 환경에서는 영원히 안 돈다 —
    "만들어 놓고 부르지 않는다" 를 고치려던 작업이 같은 결함을 다시 만든다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src" / "startup" / "lifecycle.py").read_text(encoding="utf-8")
    conds = _enclosing_conditions(src, "_macro_vintage_backfill_bg")
    joined = " ".join(conds)
    for unrelated in ("KRX_API_KEY", "KIS_APP_KEY", "DART_API_KEY"):
        assert unrelated not in joined, (
            f"빈티지 데몬이 무관한 키({unrelated}) 게이트 안에 있다: {conds}")


def test_the_krx_daemon_is_still_gated_on_its_own_key():
    """★짝★ 위 검사가 '조건을 다 지웠다' 로도 통과하면 안 된다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src" / "startup" / "lifecycle.py").read_text(encoding="utf-8")
    conds = " ".join(_enclosing_conditions(src, "_krx_backfill_bg"))
    assert "KRX_API_KEY" in conds, "KRX 데몬의 키 게이트가 사라졌다"
