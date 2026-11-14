"""분봉의 행 단위 출처와 운영 차단 (분봉 백테스트 설계 W4a · 관측 O1~O3 · O7).

고치기 전의 관측: 일파일에 출처 열이 없어 ★모의 모드로 수집한 합성 분봉을 운영 게이트의 프로세스가 라벨 없이 읽었다★
(기존 하이브리드 체결은 그것을 분봉 체결로 셌다). 여기서 거는 계약:

- 행마다 출처가 실린다(`kis` · `synthetic`). 출처 열이 없는 옛 파일은 `unknown` — 미상은 실데이터가 아니다.
- ★운영 게이트는 합성 행을 내주지 않는다.★ 짝: 같은 파일을 모의 게이트는 그대로 내준다 · 실 수집 행은 운영에서 그대로 나온다.
- 합성 분봉은 프로세스가 달라도 같은 값이다(씨앗이 `hash()` 가 아니다).

`load_minute_bars` 가 `None` 이면 기존 엔진이 일봉 모델로 떨어지고 그렇게 센다는 것은
`tests/test_minute_bars.py::test_intraday_fallback_matches_daily_and_reports` 가 이미 건다 — 여기서는 로더의 계약만 본다(엔진 0줄).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import src.data.minute_bars as mb

DAY = "2026-03-04"
ROOT = Path(__file__).resolve().parents[1]
LEGACY_COLUMNS = ["ticker", "time", "open", "high", "low", "close", "volume"]


@pytest.fixture
def bars_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path))
    mb.clear_cache()
    yield tmp_path
    mb.clear_cache()


class _FakeKis:
    """실 제공자 자리 — 봉 둘. 둘째 봉의 거래량은 float32 가 정확히 담지 못하는 수(2**24 + 1)다."""

    BARS = [
        {"time": "090000", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
        {"time": "090100", "open": 100.0, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 16_777_217.0},
    ]

    def get_minute_bars_dated(self, ticker, date):
        return [dict(b) for b in self.BARS]

    def get_minute_bars_today(self, ticker):
        return [dict(b) for b in self.BARS]


def collect_synthetic(monkeypatch, tickers, day=DAY):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    out = mb.collect_day(tickers, day)
    mb.clear_cache()
    return out


def collect_real(monkeypatch, tickers, day=DAY):
    import src.execution.kis_client as kc

    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(kc, "get_kis_client", lambda *a, **k: _FakeKis())
    out = mb.collect_day(tickers, day, throttle=0)
    mb.clear_cache()
    return out


def stored(day=DAY) -> pd.DataFrame:
    """디스크에 실제로 쓰인 것 — 로더를 거치지 않는다."""
    return mb._read_day_file(mb._existing_day_path(day))


def write_legacy(day=DAY, ticker="005930"):
    """출처 열이 생기기 전의 파일 모양."""
    rows = [{"ticker": ticker, **b} for b in _FakeKis.BARS]
    mb._write_day_file(pd.DataFrame(rows, columns=LEGACY_COLUMNS), day)
    mb.clear_cache()


# ── 출처가 행마다 실린다 ──────────────────────────────────────────────────────────────
def test_rows_collected_under_the_mock_gate_are_stored_as_synthetic(bars_dir, monkeypatch):
    collect_synthetic(monkeypatch, ["005930", "000660"])
    assert set(stored()["source"]) == {mb.SOURCE_SYNTHETIC}


def test_rows_collected_from_the_provider_are_stored_as_kis(bars_dir, monkeypatch):
    out = collect_real(monkeypatch, ["005930"])
    assert out["collected"] == 1
    assert set(stored()["source"]) == {mb.SOURCE_KIS}


def test_a_legacy_file_without_a_source_column_reads_as_unknown_not_as_real(bars_dir, monkeypatch):
    write_legacy()
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    day = mb.load_day_frame(DAY)
    assert day.reason is None and len(day.frame) == 2
    assert set(day.frame["source"]) == {mb.SOURCE_UNKNOWN}


def test_a_source_label_outside_the_vocabulary_reads_as_unknown(bars_dir, monkeypatch):
    """파일에 적힌 낱말을 그대로 믿지 않는다 — 아는 출처(`kis` · `synthetic`)가 아니면 미상이다."""
    rows = [{"ticker": "005930", **b, "source": label} for b, label in zip(_FakeKis.BARS, ["real", None])]
    mb._write_day_file(pd.DataFrame(rows, columns=[*LEGACY_COLUMNS, "source"]), DAY)
    mb.clear_cache()
    assert list(mb.load_day_frame(DAY).frame["source"]) == [mb.SOURCE_UNKNOWN, mb.SOURCE_UNKNOWN]


def test_adding_to_a_legacy_file_keeps_the_old_rows_unknown(bars_dir, monkeypatch):
    write_legacy(ticker="005930")
    collect_real(monkeypatch, ["000660"])
    by_ticker = stored().groupby("ticker")["source"].agg(lambda s: set(s)).to_dict()
    assert by_ticker == {"005930": {mb.SOURCE_UNKNOWN}, "000660": {mb.SOURCE_KIS}}


# ── 운영 게이트는 합성 분봉을 내주지 않는다 (짝 셋) ─────────────────────────────────────
def test_production_does_not_serve_synthetic_minute_bars(bars_dir, monkeypatch):
    collect_synthetic(monkeypatch, ["005930", "000660"])
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert mb.load_minute_bars("005930", DAY) is None
    day = mb.load_day_frame(DAY)
    assert day.frame is None
    assert day.reason == "synthetic_rows_blocked"
    assert day.blocked_rows == 780


def test_the_mock_gate_serves_the_same_file_with_the_columns_it_always_had(bars_dir, monkeypatch):
    collect_synthetic(monkeypatch, ["005930"])
    df = mb.load_minute_bars("005930", DAY)
    assert len(df) == 390
    assert list(df.columns) == LEGACY_COLUMNS            # 기존 소비자(하이브리드 체결)가 보는 모양은 그대로다
    day = mb.load_day_frame(DAY)
    assert day.reason is None and day.blocked_rows == 0
    assert set(day.frame["source"]) == {mb.SOURCE_SYNTHETIC}


def test_production_serves_provider_rows_unchanged(bars_dir, monkeypatch):
    collect_real(monkeypatch, ["005930"])
    df = mb.load_minute_bars("005930", DAY)
    assert list(df["time"]) == ["090000", "090100"]
    assert list(df["close"]) == [100.0, 101.0]
    day = mb.load_day_frame(DAY)
    assert day.reason is None and day.blocked_rows == 0
    assert set(day.frame["source"]) == {mb.SOURCE_KIS}


def test_a_mixed_day_file_serves_only_the_provider_rows_in_production(bars_dir, monkeypatch):
    collect_synthetic(monkeypatch, ["005930"])
    collect_real(monkeypatch, ["000660"])                 # 이어 받기 — 같은 일파일에 실 종목이 더해진다
    assert mb.load_minute_bars("005930", DAY) is None      # 운영 게이트(collect_real 이 닫아 두었다)
    assert len(mb.load_minute_bars("000660", DAY)) == 2
    day = mb.load_day_frame(DAY)
    assert set(day.frame["ticker"]) == {"000660"}
    assert day.blocked_rows == 390 and day.reason is None
    monkeypatch.setenv("KIS_USE_MOCK", "1")                # 짝: 모의 게이트는 둘 다 낸다
    assert len(mb.load_minute_bars("005930", DAY)) == 390
    assert set(mb.load_day_frame(DAY).frame["ticker"]) == {"005930", "000660"}


def test_unknown_origin_rows_are_served_in_production_but_stay_labelled(bars_dir, monkeypatch):
    """옛 파일은 실데이터일 수도 있다 — 막지 않는다. 그러나 라벨이 따라가서 소비자가 미상으로 다룰 수 있다."""
    write_legacy()
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert len(mb.load_minute_bars("005930", DAY)) == 2
    assert set(mb.load_day_frame(DAY).frame["source"]) == {mb.SOURCE_UNKNOWN}


def test_a_day_that_was_never_loaded_says_so(bars_dir, monkeypatch):
    day = mb.load_day_frame("2026-03-05")
    assert day.frame is None and day.reason == "not_loaded" and day.blocked_rows == 0


def test_every_reason_has_a_sentence(bars_dir):
    assert set(mb.DAY_REASONS) == {"not_loaded", "synthetic_rows_blocked", "unreadable"}
    assert all(text.endswith("니다.") for text in mb.DAY_REASONS.values())


# ── 합성 분봉은 어느 프로세스에서나 같다 ────────────────────────────────────────────────
def _first_and_last_close(hash_seed: str, ticker="005930", day=DAY) -> str:
    code = ("from src.data.minute_bars import _mock_minute_bars as f;"
            f"b = f({ticker!r}, {day!r}); print(repr(b[0]['close']), repr(b[-1]['close']), len(b))")
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "KIS_USE_MOCK": "1"}
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_synthetic_bars_are_the_same_in_every_process():
    assert _first_and_last_close("1") == _first_and_last_close("2")


def test_synthetic_bars_still_differ_by_ticker_and_by_day():
    base = mb._mock_minute_bars("005930", DAY)
    assert [b["close"] for b in base] != [b["close"] for b in mb._mock_minute_bars("000660", DAY)]
    assert [b["close"] for b in base] != [b["close"] for b in mb._mock_minute_bars("005930", "2026-03-05")]
    assert len({b["close"] for b in base}) > 300          # 상수로 박은 봉이 아니다


# ── 거래량은 깎이지 않는다 (관측 O7) ────────────────────────────────────────────────────
def test_a_volume_above_the_float32_integer_range_survives_storage(bars_dir, monkeypatch):
    collect_real(monkeypatch, ["005930"])
    assert list(mb.load_minute_bars("005930", DAY)["volume"]) == [10.0, 16_777_217.0]
