"""DB 적재가 ★요청 구간을 덮는지★ 검사한다 (②)

## 무엇이 문제였나 — "데이터 부족" 의 진짜 얼굴

`load_ohlcv_unified` 의 DB 채택 조건은 **행 개수뿐**이었다:

```python
    df = _db_ohlcv_df(code, start_date, end_date)
    if df is not None and not df.empty and len(df) >= 20:
        _tag(df, code, "db")
        return df
```

`df.index.min()/max()` 를 요청 구간과 대조하는 코드가 파일 전체에 없다. 그래서
2023–2026 을 요청했는데 DB 에 2023–2024 만 적재돼 있으면 ~250행 → `>= 20` 통과 →
**잘린 시계열을 그대로 돌려주고 KIS 에 묻지 않는다.** 백테스트는 조용히 짧아지고,
사용자는 "왜 결과가 이상하지" 만 남는다.

★부족한 것이 아니라 부족한 줄 모르는 것이다★ — CLAUDE.md ★침묵 폴백 금지★ 위반.

## 이 슬라이스가 바꾸는 것 / 바꾸지 않는 것

**바꾸지 않는다** — 기본 동작은 지금처럼 "있는 데이터로 돈다". 절단·거절은
플래그 뒤에 둔다(P5 ③ 이 세운 규율: 라벨 기본).

**바꾼다** — ⑴ 부분 커버면 **KIS 로 보강을 시도**하고, ⑵ 보강이 안 되면 채택하되
**커버리지 사실을 라벨로 싣고**, ⑶ `_db_ohlcv_df` 가 DB 장애와 "데이터 없음" 을
**구분**한다(예전엔 예외를 삼켜 둘이 같은 답이었다).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as L  # noqa: E402

REQ_START, REQ_END = "2023-07-26", "2026-07-26"


def _frame(start: str, end: str) -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(11)
    c = 10000 * np.exp(np.cumsum(rng.normal(0, .015, len(idx))))
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * .99,
                         "close": c, "volume": np.full(len(idx), 10_000)}, index=idx)


@pytest.fixture(autouse=True)
def _no_kis(monkeypatch):
    """기본은 KIS 미가용 — 각 테스트가 필요하면 덮는다."""
    monkeypatch.setattr(L, "_kis_ohlcv_df", lambda *a, **k: None)


# ── 커버리지 판정 ───────────────────────────────────────────────────────────

def test_a_fully_covering_db_is_accepted_unchanged(monkeypatch):
    """★기존 동작 불변★ 온전히 덮으면 예전처럼 그대로 채택한다."""
    full = _frame(REQ_START, REQ_END)
    monkeypatch.setattr(L, "_db_ohlcv_df", lambda *a, **k: full)
    out = L.load_ohlcv_unified("005930", REQ_START, REQ_END, prefer="auto")
    assert len(out) == len(full)
    assert out.attrs.get("source") == "db"
    assert out.attrs.get("coverage_ok") is True, out.attrs


def test_a_partially_covered_range_is_not_silently_accepted(monkeypatch):
    """★핵심★ DB 에 2024년까지만 있는데 2026년까지 요청 — 조용히 넘어가면 안 된다.

    행 수는 380개라 예전 조건 `len(df) >= 20` 을 여유롭게 통과한다.
    """
    short = _frame(REQ_START, "2024-12-31")
    assert len(short) >= 20, "이 테스트의 전제가 깨졌다 — 예전 조건을 통과해야 한다"
    monkeypatch.setattr(L, "_db_ohlcv_df", lambda *a, **k: short)
    out = L.load_ohlcv_unified("005930", REQ_START, REQ_END, prefer="auto")
    assert out is not None and not out.empty, "정책은 그대로 — 있는 데이터로 돈다"
    assert out.attrs.get("coverage_ok") is False, (
        f"부분 커버를 온전한 것처럼 실었다: {out.attrs}")
    assert out.attrs.get("coverage_reason"), "왜 부족한지 말하지 않는다"


def test_a_partial_range_asks_kis_before_giving_up(monkeypatch):
    """★보강을 시도한다★ 예전에는 KIS 에 묻지도 않았다."""
    short = _frame(REQ_START, "2024-12-31")
    monkeypatch.setattr(L, "_db_ohlcv_df", lambda *a, **k: short)
    asked: list = []

    def _kis(code, s, e):
        asked.append((s, e))
        return _frame(REQ_START, REQ_END)

    monkeypatch.setattr(L, "_kis_ohlcv_df", _kis)
    monkeypatch.setattr(L, "ingest_df_to_db", lambda *a, **k: None)
    out = L.load_ohlcv_unified("005930", REQ_START, REQ_END, prefer="auto")
    assert asked, "부분 커버인데 KIS 에 묻지 않았다"
    assert out.attrs.get("coverage_ok") is True, out.attrs
    assert out.index.max() >= pd.Timestamp("2026-07-01"), "보강 결과가 반영되지 않았다"


def test_the_short_row_count_path_still_falls_through(monkeypatch):
    """예전부터 있던 `len < 20` 폴백을 깨지 않는다."""
    tiny = _frame(REQ_START, "2023-08-05")
    monkeypatch.setattr(L, "_db_ohlcv_df", lambda *a, **k: tiny)
    got = {"n": 0}

    def _kis(code, s, e):
        got["n"] += 1
        return _frame(REQ_START, REQ_END)

    monkeypatch.setattr(L, "_kis_ohlcv_df", _kis)
    monkeypatch.setattr(L, "ingest_df_to_db", lambda *a, **k: None)
    out = L.load_ohlcv_unified("005930", REQ_START, REQ_END, prefer="auto")
    assert got["n"] == 1 and out.attrs.get("source") == "kis"


# ── 없음과 못 읽음의 구분 ───────────────────────────────────────────────────

def test_a_db_outage_is_not_reported_as_no_data(monkeypatch):
    """★없음과 못 읽음은 다르다★

    `_db_ohlcv_df` 는 예외를 전부 삼켜 빈 프레임을 돌려줬다 — DB 장애와 "이 종목은
    적재된 적이 없다" 가 **같은 답**이 된다. 그러면 상류가 "실데이터 없음" 이라고
    단언하는 순간 그것이 거짓일 수 있다.
    """
    def _boom(ticker, s, e, strict=False):
        if strict:
            raise L.OhlcvStoreError("커넥션 풀 고갈")
        import pandas as _pd
        return _pd.DataFrame()

    monkeypatch.setattr(L, "_db_ohlcv_df", _boom)
    out = L.load_ohlcv_unified("005930", REQ_START, REQ_END, prefer="auto")
    assert out.attrs.get("db_error") is not None, (
        f"DB 장애가 '데이터 없음' 과 구별되지 않는다: {out.attrs}")


def test_the_store_reader_can_be_strict(monkeypatch):
    """저장소 계층 계약 — `backtest_runs.get_status(strict=)` 와 같은 어휘."""
    import src.kis_backtest_engine as E
    monkeypatch.setattr(E, "load_ohlcv",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB 다운")))
    assert L._db_ohlcv_df("005930", REQ_START, REQ_END).empty, "관대 모드는 기존대로"
    with pytest.raises(L.OhlcvStoreError):
        L._db_ohlcv_df("005930", REQ_START, REQ_END, strict=True)


# ── 엔진이 커버리지를 세어 텔레메트리로 올린다 ──────────────────────────────

def test_the_engine_counts_partial_coverage_so_the_user_can_see_it(monkeypatch):
    """★사용자가 볼 수 있어야 관측이다★

    로더가 `attrs["coverage_ok"]` 를 붙여도 아무도 세지 않으면 응답에 안 나타난다.
    직전 커밋이 `symbols_by_source` 를 실은 그 통로(`_count_source`)에 함께 싣는다.
    """
    from src.kis_backtest_engine import _count_coverage
    counts: dict = {}
    ok = _frame(REQ_START, REQ_END); ok.attrs["coverage_ok"] = True
    bad = _frame(REQ_START, "2024-12-31"); bad.attrs["coverage_ok"] = False
    plain = _frame(REQ_START, REQ_END)          # 라벨 없음
    for d in (ok, ok, bad, plain):
        _count_coverage(counts, d)
    assert counts == {"ok": 2, "partial": 1, "unknown": 1}, counts


def test_an_unlabelled_frame_is_unknown_not_ok():
    """★미상은 통과가 아니다★ 라벨이 없는 프레임을 'ok' 로 세면 커버리지 보고가
    거짓이 된다 — 로더를 안 거친 경로가 전부 '덮었다' 로 둔갑한다."""
    from src.kis_backtest_engine import _count_coverage
    counts: dict = {}
    _count_coverage(counts, _frame(REQ_START, REQ_END))
    assert counts.get("ok", 0) == 0 and counts.get("unknown") == 1, counts
