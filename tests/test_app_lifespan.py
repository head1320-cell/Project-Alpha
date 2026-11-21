"""앱이 뜰 때·내려갈 때 해야 할 일 — 기동 시퀀스(`run_startup`)와 워커 풀 정리(`shutdown_pool`).

FastAPI 0.162(Starlette 1.x)에서 `app.add_event_handler` 가 없어졌다(`AttributeError` — 앱이 만들어지지도 않는다). 훅을 lifespan 으로
옮기면서, ★두 훅이 실제로 불리는지★를 처음으로 동작으로 건다(예전에는 등록 줄만 있고 부르는지 시험이 없었다).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402


def test_startup_runs_once_on_enter_and_the_pool_closes_once_on_exit(monkeypatch):
    import src.api.backtest_run_routes as brr
    from src.startup import lifecycle

    seen: list[str] = []

    async def _startup():
        seen.append("startup")

    monkeypatch.setattr(lifecycle, "run_startup", _startup)
    monkeypatch.setattr(brr, "shutdown_pool", lambda: seen.append("shutdown"))

    from src.app_factory import create_app
    app = create_app()
    assert seen == [], "앱을 만들기만 했는데 훅이 돌았다"
    with TestClient(app):
        assert seen == ["startup"], f"뜰 때 기동 시퀀스가 한 번 돌아야 한다: {seen}"
    assert seen == ["startup", "shutdown"], f"내려갈 때 워커 풀을 한 번 닫아야 한다: {seen}"


def test_without_entering_the_app_nothing_runs(monkeypatch):
    """★짝★ 만들기만 하고 띄우지 않으면 아무 훅도 돌지 않는다 — '늘 부른다' 구현을 배제."""
    import src.api.backtest_run_routes as brr
    from src.startup import lifecycle

    seen: list[str] = []

    async def _startup():
        seen.append("startup")

    monkeypatch.setattr(lifecycle, "run_startup", _startup)
    monkeypatch.setattr(brr, "shutdown_pool", lambda: seen.append("shutdown"))
    from src.app_factory import create_app
    create_app()
    assert seen == []
