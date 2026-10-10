"""매크로·시장 실패를 ★영구히 기억하지 않는다★ + 커버리지를 노출한다 (⑥)

## 무엇이 문제였나

조건식의 ECOS/FRED 매크로 토큰과 해외지수 토큰은 **프로세스마다 라이브 네트워크**
호출이다(`INGEST_TARGETS` 에 macro 가 아예 없다 — `macro_observations` 빈티지
스토어는 있지만 `factor_tokens` 가 읽지 않는다).

그 자체는 사용자가 유지하기로 한 설계다. 문제는 **실패를 영구히 기억한다**는 것:

```python
            except Exception:
                s = None
    _ecos_cache[token] = s      # ← None 이 그대로 캐시된다. TTL 없음.
```

`uvicorn --workers 1` 이라 캐시가 프로세스 로컬이고 프로세스는 오래 산다. 즉
**기동 직후 네트워크가 한 번 흔들리면 그 매크로 토큰은 서버를 재시작할 때까지
계속 평가 불가**다. 그리고 조건식은 평가 불가를 **조용히 건너뛴다** — 사용자는
매크로 조건이 걸린 줄 알지만 실제로는 무시된 백테스트를 본다.

★성공은 오래 캐시해도 된다★(빈티지는 잘 안 바뀐다). **실패만** 시효를 둔다.
그리고 왜 실패했는지 사유를 남겨 `db-status` 가 보고할 수 있게 한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.kis_strategies.factor_tokens as FT  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    FT._ecos_cache.clear()
    FT._fred_cache.clear()
    FT._market_cache.clear()
    if hasattr(FT, "_macro_failures"):
        FT._macro_failures.clear()
    yield


def test_a_successful_series_is_cached_and_not_refetched(monkeypatch):
    """★성공은 그대로 캐시한다★ 이 슬라이스가 네트워크를 더 쓰게 만들면 안 된다."""
    calls = {"n": 0}
    idx = pd.date_range("2020-01-01", periods=50, freq="D")

    def fake(token):
        calls["n"] += 1
        return pd.Series(range(50), index=idx, dtype="float64")

    monkeypatch.setattr(FT, "_ecos_fetch", fake, raising=False)
    a = FT._ecos_series("기준금리")
    b = FT._ecos_series("기준금리")
    assert a is not None and b is not None
    assert calls["n"] == 1, f"성공을 캐시하지 않는다: {calls['n']}회 호출"


def test_a_failure_is_retried_after_the_ttl_not_remembered_forever(monkeypatch):
    """★핵심★ 한 번 실패했다고 프로세스가 죽을 때까지 포기하면 안 된다."""
    calls = {"n": 0}

    def flaky(token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("네트워크 일시 오류")
        idx = pd.date_range("2020-01-01", periods=50, freq="D")
        return pd.Series(range(50), index=idx, dtype="float64")

    monkeypatch.setattr(FT, "_ecos_fetch", flaky, raising=False)
    assert FT._ecos_series("기준금리") is None, "첫 호출은 실패해야 한다"
    assert FT._ecos_series("기준금리") is None, "TTL 안에서는 재시도하지 않는다"
    assert calls["n"] == 1, "TTL 안인데 다시 물었다 — 네트워크를 태운다"

    monkeypatch.setattr(FT, "_MACRO_FAIL_TTL_SEC", 0.0)
    got = FT._ecos_series("기준금리")
    assert got is not None, "TTL 이 지났는데도 실패를 기억하고 있다"
    assert calls["n"] == 2


def test_a_failure_records_a_reason_rather_than_just_none(monkeypatch):
    """★사유 없는 실패는 금지★ 어떤 토큰이 왜 못 쓰이는지 말할 수 있어야 한다."""
    monkeypatch.setattr(
        FT, "_ecos_fetch",
        lambda token: (_ for _ in ()).throw(RuntimeError("BOK 응답 코드 INFO-200")),
        raising=False)
    FT._ecos_series("기준금리")
    rep = FT.macro_availability()
    assert "기준금리" in rep["unavailable"], rep
    assert rep["unavailable"]["기준금리"]["reason"], "사유를 남기지 않았다"


def test_availability_distinguishes_unavailable_from_never_asked():
    """★미상은 실패가 아니다★ 아무도 안 물어본 토큰을 '사용 불가' 로 보고하면
    사용자가 없는 문제를 쫓는다."""
    rep = FT.macro_availability()
    assert rep["unavailable"] == {}, rep
    assert rep["ok"] == [], rep
    assert rep["note"], "이 보고서가 무엇인지 말하지 않는다"


def test_a_market_index_failure_is_also_retried(monkeypatch):
    """해외지수(_market_cache)도 같은 병을 앓는다 — 같은 처방."""
    calls = {"n": 0}

    def flaky(prefix):
        calls["n"] += 1
        raise RuntimeError("yfinance 접속 실패")

    monkeypatch.setattr(FT, "_market_fetch", flaky, raising=False)
    assert FT._market_df("DOW") is None
    assert FT._market_df("DOW") is None
    assert calls["n"] == 1, "TTL 안인데 다시 물었다"
    monkeypatch.setattr(FT, "_MACRO_FAIL_TTL_SEC", 0.0)
    FT._market_df("DOW")
    assert calls["n"] == 2, "TTL 이 지났는데 재시도하지 않는다"


# ── db-status 가 매크로 상태를 보고한다 ─────────────────────────────────────

def test_db_status_reports_macro_availability(monkeypatch):
    """★적재 대상에 없는 데이터도 상태를 말해야 한다★

    `INGEST_TARGETS` 에 macro 가 없어 `db-status` 의 테이블 블록에는 매크로가
    잡히지 않는다. `config` 에 `bok_key`/`fred_key` 불리언만 있는데
    **키가 있다 ≠ 시계열이 온다** 이다. 그 간극이 사용자에게 안 보였다.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.data_routes import router
    monkeypatch.setattr(
        FT, "_ecos_fetch",
        lambda token: (_ for _ in ()).throw(RuntimeError("BOK 응답 코드 INFO-200")),
        raising=False)
    FT._ecos_series("기준금리")

    app = FastAPI()
    app.include_router(router)
    b = TestClient(app).get("/api/v1/data/db-status").json()
    macro = b.get("macro")
    assert macro is not None, "db-status 에 매크로 상태가 없다"
    assert "기준금리" in macro["unavailable"], macro
    assert macro["unavailable"]["기준금리"]["reason"], "사유가 없다"
    assert macro["note"], "이 보고서가 무엇인지 말하지 않는다"
