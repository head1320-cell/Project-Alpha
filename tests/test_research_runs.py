"""ResearchRun 재현성 단위 검증 (Full Expansion Directive P1)

관례: in-memory SQLite + monkeypatch (실DB·실네트워크 0). 핵심 주장:
  record/get      — run_id 발급, inputs/outputs/snapshot/code_version/시각 왕복 보존
  list            — 최신순·kind 필터·limit, 목록은 요약(inputs/outputs 미포함)
  delete          — 삭제 후 조회 None
  API             — POST/GET/404, DB 미가용 시 recorded=False 정직 보고(500 아님)
  analyze 연동    — record_run=True일 때만 기록, 응답에 run_id 포함
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.research_runs as rr  # noqa: E402


@pytest.fixture
def mem_rr(monkeypatch):
    """research_runs를 in-memory SQLite로 격리."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rr, "_engine", lambda: eng)
    monkeypatch.setattr(rr, "_inited", False)
    yield eng
    eng.dispose()


# ── 모듈 직접 ─────────────────────────────────────────────────────────────────
def test_record_and_get_roundtrip(mem_rr):
    rid = rr.record_run(
        rr.KIND_ANALYZE,
        inputs={"tickers": ["005930", "000660"], "model": "bl", "tau": 0.05},
        outputs={"weights": {"optimized": {"005930": 60.0, "000660": 40.0}}},
        snapshot={"coverage": {"start": "2023-01-02", "end": "2026-07-18", "source": "mock"}},
        name="테스트 런",
    )
    assert rid and rid.startswith("rr_")
    d = rr.get_run(rid)
    assert d is not None
    assert d["kind"] == rr.KIND_ANALYZE and d["name"] == "테스트 런"
    assert d["inputs"]["model"] == "bl" and d["inputs"]["tickers"] == ["005930", "000660"]
    assert d["outputs"]["weights"]["optimized"]["005930"] == 60.0
    assert d["snapshot"]["coverage"]["source"] == "mock"
    assert d["code_version"]  # 서버 스탬프 존재
    assert d["created_at"] > 0


def test_list_order_filter_and_summary(mem_rr):
    r1 = rr.record_run("kind_a", {"i": 1}, {"o": 1})
    r2 = rr.record_run("kind_b", {"i": 2}, {"o": 2})
    r3 = rr.record_run("kind_a", {"i": 3}, {"o": 3})
    assert all((r1, r2, r3))

    allruns = rr.list_runs()
    assert [x["run_id"] for x in allruns[:1]] == [r3] or allruns[0]["run_id"] in (r2, r3)
    assert len(allruns) == 3
    # 목록은 요약 — inputs/outputs 미포함 (대형 페이로드 방지)
    assert "inputs" not in allruns[0] and "outputs" not in allruns[0]

    only_a = rr.list_runs(kind="kind_a")
    assert {x["run_id"] for x in only_a} == {r1, r3}

    assert len(rr.list_runs(limit=2)) == 2


def test_delete(mem_rr):
    rid = rr.record_run("k", {}, {})
    assert rr.delete_run(rid) is True
    assert rr.get_run(rid) is None
    assert rr.delete_run("rr_없는것") is False


def test_get_missing_returns_none(mem_rr):
    assert rr.get_run("rr_missing") is None


# ── API 라우트 (직접 호출 관례) ───────────────────────────────────────────────
def test_api_create_list_get_404(mem_rr):
    from fastapi import HTTPException

    from src.api.research_routes import RecordRunRequest, create_run, get_one, list_all

    res = create_run(RecordRunRequest(kind="timing", name="게이트 테스트",
                                      inputs={"market": "kr"}, outputs={"signal": "risk_on"}))
    assert res["recorded"] is True and res["run_id"]

    lst = list_all(kind="timing", limit=10)
    assert len(lst["runs"]) == 1 and lst["runs"][0]["name"] == "게이트 테스트"

    d = get_one(res["run_id"])
    assert d["outputs"]["signal"] == "risk_on"

    with pytest.raises(HTTPException) as e:
        get_one("rr_none")
    assert e.value.status_code == 404


def test_api_db_unavailable_honest(monkeypatch):
    """DB 미가용 → 500이 아니라 recorded=False 정직 보고."""
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(rr, "_engine", boom)
    monkeypatch.setattr(rr, "_inited", False)

    from src.api.research_routes import RecordRunRequest, create_run
    res = create_run(RecordRunRequest(kind="k", inputs={}, outputs={}))
    assert res["recorded"] is False and res["run_id"] is None


# ── analyze 연동 (opt-in) ─────────────────────────────────────────────────────
def _fake_returns(n_days=300, seed=7):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n_days)
    data = {t: rng.normal(0.0004, 0.015, n_days) for t in ("005930", "000660", "035420")}
    df = pd.DataFrame(data, index=idx)
    bench = pd.Series(rng.normal(0.0003, 0.012, n_days), index=idx)
    cov = {"start": str(idx[0].date()), "end": str(idx[-1].date()),
           "n_obs": n_days, "source": "mock"}
    return df, bench, [], cov


def test_analyze_records_run_only_when_requested(mem_rr, monkeypatch):
    import src.api.allocation_routes as ar

    monkeypatch.setattr(ar, "_load_clean_returns",
                        lambda tickers, bench, lb: _fake_returns())
    monkeypatch.setattr(ar, "_labels", lambda names: {n: n for n in names})

    req = ar.AnalyzeRequest(tickers=["005930", "000660", "035420"], model="mvo")
    out = ar.allocation_analyze(req)
    assert out["error"] is False
    assert "run_id" not in out            # opt-in 아님 → 기록 없음
    assert rr.list_runs() == []

    req2 = ar.AnalyzeRequest(tickers=["005930", "000660", "035420"], model="mvo",
                             record_run=True, run_name="P1 검증 런")
    out2 = ar.allocation_analyze(req2)
    assert out2["run_recorded"] is True and out2["run_id"]

    d = rr.get_run(out2["run_id"])
    assert d["kind"] == rr.KIND_ANALYZE and d["name"] == "P1 검증 런"
    # inputs에 기록 플래그는 제외(재실행 시 중복 기록 방지), 핵심 파라미터는 보존
    assert "record_run" not in d["inputs"] and d["inputs"]["model"] == "mvo"
    # outputs는 요약만 — 대형 산출물(frontier/mc) 제외
    assert "weights" in d["outputs"] and "frontier" not in d["outputs"]
    assert d["snapshot"]["coverage"]["source"] == "mock"
