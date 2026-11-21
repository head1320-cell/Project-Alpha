"""스크리너 mock 골든 — ★운영의 합성 바탕 가격을 걷어도(감사 F3) mock 의 결과는 한 자리도 바뀌지 않는다★ (2026-11-21)
==============================================================================================================
F3 고침은 운영(`KIS_USE_MOCK≠"1"`)의 가격 경로만 바꾼다. 고치기 ★전★(HEAD `ee4634a`)에 mock 의 `ValuationScreener.run()`
결과를 `tests/golden/screener_mock_run.json` 에 얼렸다 — 고친 뒤에도 같아야 한다(사용자 조건: "gate on unchanged").

얼리는 것(경우마다):
  · 결과 종목의 ★순서★(정렬 · 제한이 고른 것)
  · 항목의 ★기본 칸★(데이터클래스 필드 — 가격 · 괴리율 · 판정 · 점수 · 재무 · 라벨)
  · 항목 `to_dict()` 의 ★키 집합★ — mock 응답 모양이 그대로인지(새 라벨 키가 mock 에 새지 않는지)
  · 결과의 수(평가 · 통과 · 실패 · 상한 · as_of)

얼리지 않는 것: 붙이기가 다는 팩터의 ★값★(키는 얼린다) — F3 고침이 건드리지 않는 저장소 계산이다.

경우: 기본 정렬(종합 점수 내림) · 괴리율 오름 · PER 오름 · 예전 필터(`ScreenerFilters` 의 괴리율 범위) · 복원(`item:`) 경로.
mock 의 "오늘"은 고정한다(`ohlcv_loader._mock_today`). 값 비교는 상대 1e-9(같은 호스트에서는 정확히 같다).
얼리기: `UPDATE_SCREENER_MOCK_GOLDEN=1 KIS_USE_MOCK=1 pytest tests/test_screener_mock_golden.py`.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

GOLDEN = Path(__file__).parent / "golden" / "screener_mock_run.json"
U = ["005930", "000660", "035420", "123456", "999999"]   # 고정 표 셋 · 표 밖(해시 바탕) 둘
TODAY = datetime(2026, 11, 20, 12, 0, 0)
#: 결과(`ScreenerResult`)에서 얼리는 수 — 시간·캐시 적중처럼 실행마다 다른 것은 뺀다.
RESULT_KEYS = ("universe", "total_evaluated", "total_passed", "failures", "universe_size", "ingested_count",
               "evaluated_actual", "capped", "asof")


@pytest.fixture
def mock_world(monkeypatch):
    """mock · 오늘 고정 · 영속 캐시는 메모리(복원 경로를 보려고) · 저장소 캐시는 비운다(다른 시험의 순서에 흔들리지 않게)."""
    import src.data.ohlcv_loader as ol
    import src.data.snapshot_db as sdb
    from src.data.extended_factors_store import ExtendedFactorsStore
    from src.data.fundamentals_store import FundamentalsStore
    from src.data.price_factors_store import PriceFactorsStore
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(ol, "_mock_today", lambda: TODAY)
    for store in (FundamentalsStore.get_default(), PriceFactorsStore.get_default(), ExtendedFactorsStore.get_default()):
        store.cache_clear()
    mem: dict = {}
    monkeypatch.setattr(sdb, "enabled", lambda: True)
    monkeypatch.setattr(sdb, "bulk_read", lambda keys, ttl=None: {k: mem[k] for k in keys if k in mem})
    monkeypatch.setattr(sdb, "write_many", lambda payload: mem.update(json.loads(json.dumps(payload, default=str))))
    return mem


def _core(it) -> dict:
    from src.engine.screener import ScreenerItem
    return {f.name: getattr(it, f.name) for f in dataclasses.fields(ScreenerItem)}


def _snap(result) -> dict:
    return {
        "order": [it.stock_code for it in result.items],
        "items": {it.stock_code: _core(it) for it in result.items},
        "keys": {it.stock_code: sorted(it.to_dict().keys()) for it in result.items},
        "result": {k: getattr(result, k) for k in RESULT_KEYS},
    }


def _cases() -> dict:
    from src.engine.screener import ScreenerFilters, ValuationScreener

    def run(**kw):
        return ValuationScreener().run(universe=U, limit=10, liquidity_floor="off", **kw)

    out = {
        "default": _snap(run()),
        "gap_asc": _snap(run(sort_by="gap_pct", ascending=True)),
        "per_asc": _snap(run(sort_by="per", ascending=True)),
        "legacy_gap_filter": _snap(run(filters=ScreenerFilters(min_gap_pct=-80.0, max_gap_pct=50.0))),
    }
    # 복원 경로 — 위의 실행들이 `item:` 에 저장했다. 새 스크리너(빈 평가 캐시)가 같은 유니버스를 부르면 전부 복원된다.
    restored = run()
    assert restored.cache_misses == 0, "복원 경로를 보지 못했다 — 이 경우는 공허하다"
    out["restored"] = _snap(restored)
    return out


def _same(a, b, path: str = "") -> list[str]:
    """값 비교 — 실수는 상대 1e-9, 나머지는 정확히. 다른 자리를 경로와 함께 돌려준다."""
    if isinstance(a, dict) and isinstance(b, dict):
        diffs = [f"{path}: 키가 다르다 {sorted(set(a) ^ set(b))}"] if set(a) != set(b) else []
        for k in set(a) & set(b):
            diffs += _same(a[k], b[k], f"{path}.{k}")
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: 길이 {len(a)} ≠ {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in _same(x, y, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12):
            return [f"{path}: {a!r} ≠ {b!r}"]
        return []
    return [] if a == b else [f"{path}: {a!r} ≠ {b!r}"]


def test_the_mock_screener_output_is_unchanged(mock_world):
    got = json.loads(json.dumps(_cases(), ensure_ascii=False, default=str))
    if os.getenv("UPDATE_SCREENER_MOCK_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("골든을 얼렸다")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    diffs = _same(got, want)
    assert not diffs, "mock 결과가 골든과 다르다:\n" + "\n".join(sorted(diffs)[:40])


def test_the_golden_is_not_vacuous():
    """★짝★ 골든이 비었거나 한 경우로 뭉개졌으면 위 시험은 무엇도 걸지 않는다 — 경우마다 종목이 있고 순서가 실제로 갈린다."""
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(want) == {"default", "gap_asc", "per_asc", "legacy_gap_filter", "restored"}
    assert all(len(c["order"]) >= 3 for c in want.values())
    assert want["default"]["order"] != want["gap_asc"]["order"] or want["default"]["order"] != want["per_asc"]["order"]
    # mock 의 가격은 합성이다 — 라벨이 그렇게 말한다(고친 뒤에도 mock 은 그대로여야 한다).
    assert all(it["price_is_mock"] is True for it in want["default"]["items"].values())
    assert all(isinstance(it["current_price"], float) and it["current_price"] > 0 for it in want["default"]["items"].values())
