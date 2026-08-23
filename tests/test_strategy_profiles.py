"""전략 상세 카탈로그 — 22 프로파일 + 성과곡선 + 국면적합도 + 병합 (mock, 결정론적)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.strategy_profiles import (  # noqa: E402
    PROFILES,
    _regime_fit,
    backtest_strategy,
    build_detail,
    get_profile,
)
from src.engine.tactical_allocations import ALL_STRATEGIES  # noqa: E402

ALL_IDS = {s[0] for s in ALL_STRATEGIES}


def test_profiles_cover_all_22():
    assert set(PROFILES.keys()) == ALL_IDS
    assert len(PROFILES) == 22


def test_each_profile_complete():
    for sid, p in PROFILES.items():
        assert p.get("concept"), f"{sid} concept 누락"
        assert p.get("mechanism") and len(p["mechanism"]) >= 1, f"{sid} mechanism 누락"
        assert p.get("rationale"), f"{sid} rationale 누락"
        assert p.get("regime_note"), f"{sid} regime_note 누락"
        assert p.get("references") and len(p["references"]) >= 1, f"{sid} references 누락"
        for r in p["references"]:
            assert r.get("authors") and r.get("year") and r.get("title"), f"{sid} reference 불완전"


def test_get_profile_fallback():
    assert get_profile("classic_dm") is not None
    assert get_profile("__nope__") is None


def test_regime_fit():
    f = _regime_fit("risk_parity")
    assert len(f) == 4
    assert {x["quadrant"] for x in f} == {"Goldilocks", "Reflation", "Stagflation", "Disinflation"}
    for x in f:
        assert 0.0 <= x["fit"] <= 1.0
        assert x["quadrant_kr"]


def test_backtest_is_dynamic():
    # 동적 전략 백테스트: 월별 재선택·리밸런스로 곡선 산출 (buy&hold 아님)
    pc = backtest_strategy("classic_dm", "us", months=36)
    assert pc["curve"] and len(pc["curve"]) > 6
    assert abs(pc["curve"][0]["v"] - 100.0) < 0.01  # 시작 100
    s = pc["summary"]
    for k in ("total_return_pct", "cagr_pct", "mdd_pct", "vol_pct", "recent_12m_pct"):
        assert k in s


def test_backtest_unknown_empty():
    assert backtest_strategy("__nope__", "us")["curve"] == []


def test_as_of_truncates_point_in_time():
    # ★동적 백테스트의 핵심: as_of로 과거 시점 데이터만 보이게 절단★
    from src.data.etf_prices import as_of, cache_clear, monthly_closes
    cache_clear()
    full = monthly_closes("SPY", "us", 200)
    with as_of(6):
        past = monthly_closes("SPY", "us", 200)
    assert len(past) == len(full) - 6
    assert past[-1] == full[-7]  # 6개월 전이 마지막 관측치


def test_build_detail_all_22():
    for sid in ALL_IDS:
        d = build_detail(sid, "us")
        assert d is not None, f"{sid} detail None"
        assert d["id"] == sid
        assert d["holdings"], f"{sid} holdings 비어있음"
        assert d["profile"]["concept"], f"{sid} profile 누락"
        assert len(d["regime_fit"]) == 4
        assert d["perf"]["curve"], f"{sid} 성과곡선 비어있음"
        assert d["signal"] and d["archetype_kr"]


def test_build_detail_kr_toggle():
    d = build_detail("permanent", "kr")
    assert d is not None
    for h in d["holdings"]:
        assert h["us_ticker"]  # 원본 보존


def test_build_detail_unknown():
    assert build_detail("__nope__", "us") is None


def test_deterministic():
    a = build_detail("risk_parity", "us")
    b = build_detail("risk_parity", "us")
    assert a["perf"]["summary"] == b["perf"]["summary"]
    assert a["regime_fit"] == b["regime_fit"]
