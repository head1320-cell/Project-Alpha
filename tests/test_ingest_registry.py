"""적재 레지스트리 — ★백엔드가 스스로 열거한다★ (②)

## 무엇이 문제였나

적재 대상이 **세 곳에 따로** 적혀 있었고 서로 어긋났다:

  · `src/state/ingest_state.py::INGEST_TARGETS` — 6개
  · `src/api/data_routes.py::_ingest_run` — 6개 분기(if 문)
  · `frontend/.../DbStatusPanel.tsx` — `TABLE_LABELS` 6개 + `INGEST_TARGETS` 6개
    **하드코딩**

그래서 ★적재 대상을 추가하려면 백엔드와 프런트를 따로 고쳐야 했고★, 실제로
빠진 것들이 있었다:

  · **`macro`** — 적재 대상 자체가 없다. 조건식의 ECOS/FRED 토큰은 프로세스마다
    라이브 호출인데, `macro_observations` 테이블과 백필(`auto_vintage_backfill`)은
    **이미 존재**한다 — 연결만 안 됐다.
  · **`instrument_master`** — 종목 식별의 단일 진실인데 적재 현황이 안 보인다.

## 이 레지스트리가 모델링하는 것은 '테이블' 이 아니라 '데이터셋' 이다

★감사 중 발견★ — `db-status` 가 테이블처럼 보여주던 `index_kospi_kosdaq` 과
`etf_cross_asset` 은 **실제 테이블이 아니다.** 둘 다 `daily_prices` 의 슬라이스다:

    index : WHERE ticker IN ('KOSPI','KOSDAQ')
    etf   : WHERE ticker IN (크로스에셋 화이트리스트)

그래서 키를 '테이블명' 으로 잡으면 모델이 틀린다. **데이터셋**이 단위다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data import ingest_registry as reg  # noqa: E402

# ── 레지스트리가 갖춰야 할 것 ────────────────────────────────────────────────

def test_every_dataset_declares_what_it_needs_to_answer_for():
    """★선언이 비어 있으면 UI 가 그릴 것이 없다★"""
    assert reg.DATASETS, "레지스트리가 비어 있다"
    for d in reg.DATASETS:
        assert d.key and d.label, f"{d!r}: key/label 누락"
        assert d.source, f"{d.key}: 출처(DART/KRX/KIS/ECOS/FRED)를 말하지 않는다"
        assert d.table, f"{d.key}: 어느 테이블에 쌓이는지 말하지 않는다"
        assert isinstance(d.tools, tuple), f"{d.key}: 이 데이터가 없으면 못 도는 도구"


def test_the_previously_missing_targets_are_registered():
    """★감사에서 빠져 있던 것들★ — 특히 macro."""
    keys = {d.key for d in reg.DATASETS}
    for k in ("macro", "instrument_master"):
        assert k in keys, f"{k} 가 등록되지 않았다 — 적재 현황이 보이지 않는다"


def test_macro_is_dispatchable_and_reuses_the_existing_backfill(monkeypatch):
    """★적재 함수를 새로 만들지 않는다★

    `macro_observations` 백필은 `macro_vintage_backfill.auto_vintage_backfill` 로
    이미 존재하고 `lifecycle.py` 가 주기 실행한다. 라우터는 **연결만** 한다.

    ★실행 방법은 레지스트리가 갖지 않는다★ — 초안에서 레지스트리에 적재 함수를
    복제했다가 함수 이름을 **두 번** 틀렸다(테스트가 잡았다). `_ingest_run` 이
    대상마다 간단하지 않으므로(factors 유니버스 dedup, financials 2단계+쿼터),
    레지스트리는 "무엇이 있는가", 라우터는 "어떻게 돌리는가" 로 나눈다.
    """
    called: list = []
    import src.data.macro_vintage_backfill as mvb
    monkeypatch.setattr(mvb, "auto_vintage_backfill",
                        lambda **kw: called.append(kw) or {"ok": True})
    from src.api.data_routes import _ingest_run
    _ingest_run("macro")
    assert called, "기존 백필(auto_vintage_backfill)이 불리지 않았다"
    assert called[0].get("loop") is False, "수동 버튼이 무한 루프로 돈다"


def test_a_dataset_without_a_trigger_says_so_rather_than_showing_a_dead_button():
    """★없는 버튼을 만들면 눌러도 아무 일이 없어 더 나쁘다★

    `instrument_master` 는 심볼 마스터 갱신의 **부수 효과**로 쓰이는 파일의 DB
    사본이다 — 별도 적재 경로가 없다. 그 사실을 선언한다.
    """
    d = reg.get("instrument_master")
    assert d.triggerable is False, "없는 적재 경로에 버튼을 광고한다"
    assert d.note, "왜 버튼이 없는지 말하지 않는다"
    from src.state.ingest_state import INGEST_TARGETS
    assert "instrument_master" not in INGEST_TARGETS


def test_the_legacy_target_tuple_is_derived_not_duplicated():
    """★목록이 두 곳에 있으면 반드시 어긋난다★

    `INGEST_TARGETS` 는 기존 호출부(라우터·데몬)가 쓰므로 이름은 유지하되,
    레지스트리에서 **파생**되어야 한다.
    """
    from src.state.ingest_state import INGEST_TARGETS
    assert set(INGEST_TARGETS) <= {d.key for d in reg.DATASETS}, (
        "INGEST_TARGETS 에 레지스트리에 없는 키가 있다 — 목록이 갈라졌다")
    for legacy in ("index", "etf", "stocks", "factors", "financials", "flows"):
        assert legacy in INGEST_TARGETS, f"기존 타깃 {legacy} 가 사라졌다(호출부 파손)"


def test_a_dataset_that_is_a_slice_says_so():
    """★`index`·`etf` 는 테이블이 아니라 `daily_prices` 의 슬라이스다★

    이것을 모르면 UI 가 "테이블 3개" 로 그려 사용자가 저장소 구조를 오해한다.
    """
    for k in ("index", "etf", "stocks"):
        assert reg.get(k).table == "daily_prices", f"{k} 의 테이블이 틀렸다"
    assert reg.get("index").slice_of is not None, "index 가 슬라이스임을 말하지 않는다"
    assert reg.get("stocks").slice_of is None, "stocks 는 슬라이스가 아니다"


def test_required_env_is_declared_so_the_ui_can_explain_a_gap():
    """★"키가 없어서 못 받는다" 와 "받았는데 비었다" 는 다르다★"""
    assert "DART_API_KEY" in reg.get("financials").required_env
    assert reg.get("macro").required_env, "매크로는 BOK/FRED 키가 필요하다"


def test_unknown_key_refuses_rather_than_inventing():
    """★미상은 빈 데이터셋이 아니다★"""
    with pytest.raises(KeyError):
        reg.get("존재하지 않는 대상")


# ── 짝: 레지스트리가 실제와 어긋나면 잡는다 ─────────────────────────────────

def test_every_triggerable_dataset_is_actually_dispatchable():
    """★버튼이 보이는데 눌러도 아무 일이 없으면 안 된다★

    레지스트리가 광고하는 대상을 라우터가 모르면 그런 일이 생긴다. `_ingest_run`
    의 알려진-대상 분기를 실제로 통과하는지 본다(실행은 하지 않는다).
    """
    import src.api.data_routes as dr
    src = dr._ingest_run.__code__.co_consts
    known = {c for c in src if isinstance(c, str)}
    for d in reg.DATASETS:
        if d.triggerable:
            assert d.key in known, (
                f"{d.key}: 레지스트리는 광고하는데 _ingest_run 이 모른다 — 죽은 버튼")


def test_the_legacy_targets_all_survive_as_triggerable():
    """★기존 호출부를 깨지 않는다★ 라우터·데몬·테스트가 이 6개를 이름으로 쓴다."""
    from src.state.ingest_state import INGEST_TARGETS
    for legacy in ("index", "etf", "stocks", "factors", "financials", "flows"):
        assert legacy in INGEST_TARGETS, f"기존 타깃 {legacy} 가 사라졌다(호출부 파손)"
        assert reg.get(legacy).triggerable is True


# ── db-status 가 레지스트리를 실어 보낸다 ───────────────────────────────────

def test_db_status_publishes_the_registry_so_the_ui_need_not_hardcode_it():
    """★UI 가 테이블 목록을 알 필요가 없다★

    프런트가 `TABLE_LABELS` 6개와 버튼 6개를 하드코딩하던 것이 `macro` 누락의
    직접 원인이었다 — 백엔드에 추가해도 UI 가 안 그리면 없는 것과 같다.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.data_routes import router
    app = FastAPI()
    app.include_router(router)
    b = TestClient(app).get("/api/v1/data/db-status").json()
    ds = b.get("datasets")
    assert ds, f"db-status 가 레지스트리를 싣지 않는다: {b.get('datasets_error')}"
    keys = {d["key"] for d in ds}
    assert "macro" in keys and "instrument_master" in keys
    for d in ds:
        assert d["label"] and d["source"] and d["table"], f"불완전한 항목: {d}"
        assert "triggerable" in d, "버튼을 그릴지 UI 가 알 수 없다"


def test_a_registry_failure_reports_a_reason_rather_than_an_empty_list():
    """★빈 목록은 '적재 대상이 없다' 로 읽힌다★ (미상 ≠ 없음)"""
    import builtins

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.api.data_routes as dr
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "src.data.ingest_registry":
            raise RuntimeError("레지스트리 파손")
        return real_import(name, *a, **k)

    app = FastAPI()
    app.include_router(dr.router)
    builtins.__import__ = boom
    try:
        b = TestClient(app).get("/api/v1/data/db-status").json()
    finally:
        builtins.__import__ = real_import
    assert b["datasets"] is None, "실패인데 빈 목록을 냈다"
    assert b.get("datasets_error"), "왜 못 읽었는지 말하지 않는다"
