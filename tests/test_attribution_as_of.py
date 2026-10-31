"""귀인의 **기준일(as-of)** — 라우트가 엔진까지 실제로 전달하는가 (A7-4).

★왜 이 파일이 필요한가★
`compute_attribution(run, as_of=...)` 은 처음부터 기준일을 받았다. 그런데 라우트가
넘기지 않았고, 프론트는 늘 `activeRunId`(= 그 세션에서 방금 만든 런)만 봤다. 결과는
`2026-08-07 → 2026-08-07 · 0일` — 0일 구간의 실현수익은 **구조적으로** 계산할 수 없으니
사후 항목이 전부 미측정으로 나왔다. 데이터가 없어서가 아니라 **기준일을 고를 방법이
없어서**였고, 그 사실은 화면 어디에도 적혀 있지 않았다.

여기서 못박는 것은 둘이다:

  1. 라우트가 `as_of` 를 엔진까지 전달한다 — 전달을 지우면 이 파일이 red 다.
     (전달이 끊겨도 응답은 200 이고 표도 그려진다. 그래서 눈으로는 못 잡는다.)
  2. 경과 0일은 **미측정이지 0 이 아니다**. `portfolio_pct` 가 `0.0` 으로 채워지면
     "본전이었다" 로 읽히는데, 실제로는 아무것도 재지 않은 것이다.
"""
import os
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.api.attribution_routes as ar  # noqa: E402
from src.app_factory import create_app  # noqa: E402
from src.engine.attribution import compute_attribution  # noqa: E402

DECIDED_DAYS_AGO = 30


def _run() -> dict:
    return {
        "run_id": "rr_asof_1", "kind": "allocation_analyze", "name": "as-of 테스트 런",
        "created_at": time.time() - DECIDED_DAYS_AGO * 86400,
        "inputs": {"tickers": ["005930"], "weights": {"005930": 100}},
        "outputs": {
            "weights": {"optimized": {"005930": 100}},
            "summary": {"portfolio": {"expected_return_pct": 8.0, "volatility_pct": 15.0}},
        },
    }


def _rising(code, s, e):
    return [100.0 + 0.4 * i for i in range(40)]


@pytest.fixture
def client(monkeypatch):
    """`get_run` 만 갈아끼운다 — DB 없이 라우트의 배선을 본다."""
    monkeypatch.setattr("src.data.research_runs.get_run", lambda rid: _run() if rid == "rr_asof_1" else None)
    # 실로더를 타면 네트워크·시세 가용성에 결과가 흔들린다. 경로는 주입한다.
    monkeypatch.setattr("src.engine.attribution._load_path", _rising)
    with TestClient(create_app()) as c:
        yield c


def test_route_passes_as_of_through_to_the_engine(client):
    """★기준일을 넘기면 구간이 그만큼 바뀐다★

    라우트에서 `as_of=as_of` 를 지워도 200 이 나오고 화면도 그려진다 — 다만 언제나
    '오늘' 로 계산될 뿐이다. 그래서 경과일을 직접 비교한다.
    """
    decided = date.today() - timedelta(days=DECIDED_DAYS_AGO)
    mid = (decided + timedelta(days=10)).isoformat()

    r = client.get(f"/api/v1/allocation/attribution/rr_asof_1?as_of={mid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == mid, "기준일이 응답에 반영되지 않았다 — 라우트가 삼켰다"
    assert body["elapsed_days"] == 10, (
        f"기준일을 넘겼는데 구간이 {body['elapsed_days']}일이다 — "
        "10 이 아니면 라우트가 as_of 를 엔진까지 전달하지 않은 것이다"
    )

    # 기준일을 빼면 오늘까지 — 같은 런인데 구간이 더 길어야 한다.
    r2 = client.get("/api/v1/allocation/attribution/rr_asof_1")
    assert r2.status_code == 200, r2.text
    assert r2.json()["elapsed_days"] == DECIDED_DAYS_AGO
    assert r2.json()["elapsed_days"] > body["elapsed_days"]


def test_elapsed_days_with_history_is_actually_measured(client):
    """경과일이 있는 런은 **실측**이 된다 — 07 이 미측정 화면이던 이유가 사라진다."""
    r = client.get("/api/v1/allocation/attribution/rr_asof_1")
    body = r.json()
    assert body["coverage"]["has_expost"] is True
    assert body["returns"]["basis"] == "real"
    assert body["returns"]["portfolio_pct"] is not None


def test_zero_elapsed_is_unmeasured_not_zero():
    """★0일은 '본전' 이 아니라 '재지 않음' 이다★

    구간이 없으면 수익률은 산출 불가다. 여기서 `0.0` 을 돌려주면 화면은 성실하게
    `+0.00%` 를 그리고, 그건 "손익이 없었다" 라는 **하지 않은 주장**이 된다.
    """
    decided = date.fromtimestamp(_run()["created_at"]).isoformat()
    rep = compute_attribution(_run(), as_of=decided, path_of=_rising)

    assert rep["elapsed_days"] == 0
    assert rep["coverage"]["has_expost"] is False
    assert rep["returns"]["portfolio_pct"] is None, "0일 구간인데 수익률 숫자를 만들었다"
    assert rep["returns"]["basis"] != "real"
    assert rep["expected_vs_actual"]["actual_return_pct"] is None


def test_brinson_stays_unavailable_even_with_full_history(client):
    """★닿을 수 없는 것은 경과일이 생겨도 여전히 닿을 수 없다★

    실측 전환이 '전부 실측' 으로 번지면 안 된다. Brinson 은 벤치마크 **구성종목
    가중**이 저장소에 없어서 막힌 것이고, 시간이 지난다고 생기지 않는다. 프록시로
    채우는 순간 이 화면의 나머지 숫자들까지 믿을 수 없게 된다.
    """
    body = client.get("/api/v1/allocation/attribution/rr_asof_1").json()
    br = body["brinson_effects"]
    assert br["basis"] == "unavailable"
    assert br["note"], "미가용인데 사유가 비어 있다"
    for k in ("selection", "allocation", "factor"):
        assert br[k] is None, f"{k} 를 지어냈다"
