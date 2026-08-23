"""실제 생산자 → 실제 소비자 계약 (P2-4 준비 중 발견한 결함 둘)

★두 결함이 같은 원인에서 나왔다★
합성 입력으로만 테스트해서, 상류가 **실제로 무엇을 내보내는지** 아무도 확인하지
않았다. 그래서 이 파일의 규칙은 하나다 — **손으로 만든 입력을 쓰지 않는다.**
진짜 수집기·진짜 로더를 진짜 소비자에 물린다.

결함 A — P2.5 조건부 μ/Σ 가 운영에서 죽어 있었다
──────────────────────────────────────────────────────────────────────────────
`regime_path()` 는 `t = "202204"`(6자, 하이픈 없음)를 내는데
`regime_by_month_from_path` 는 `"YYYY-MM"`(7자)만 받았다. 실측으로 53개 점이
**전부** 버려져 `conditional_moments` 가 언제나 "월별 국면 라벨이 없다" 로
무조건부 폴백했다. P2.5 테스트 25개가 전부 합성 `"YYYY-MM"` 라벨을 썼다.

결함 B — 가격을 안 주면 2099년 mock 가격이 잡혔다
──────────────────────────────────────────────────────────────────────────────
`_resolve_price` 가 `load_ohlcv_unified(code, "2024-01-01", "2099-12-31")` 로 불러
mock 이 74년치를 생성하고 그 마지막 종가(409원)를 썼다. 실제 최근 종가는 40,263원.
내 테스트가 전부 가격을 명시해서 이 경로를 한 번도 안 밟았다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import date  # noqa: E402

import pytest  # noqa: E402

import src.engine.company_snapshot_builder as bld  # noqa: E402
from src.engine.conditional_market import (  # noqa: E402
    _normalize_month,
    conditional_moments,
    regime_by_month_from_path,
)

CODE = "005930"


@pytest.fixture(scope="module")
def live_path():
    """★합성이 아니라 실제 `regime_path` 출력★ 이것이 이 파일의 요점이다."""
    from src.engine.regime_analyzer import RegimeAnalyzer
    from src.engine.regime_transitions import regime_path

    snap = RegimeAnalyzer().collector.collect_all(use_cache=True)
    points = regime_path(snap.series, "kr", months=60).get("points") or []
    if not points:
        pytest.skip("이 환경에서 국면 경로를 만들 수 없다")
    return points


# ── 결함 A ─────────────────────────────────────────────────────────────────
def test_the_real_regime_path_survives_the_consumer(live_path):
    """★고치기 전에는 53개 중 53개가 버려졌다★"""
    by_month, dropped = regime_by_month_from_path(live_path)

    assert by_month, "실제 경로가 통째로 버려진다 — 결함 A 가 돌아왔다"
    assert len(by_month) == len(live_path) - dropped
    assert dropped == 0, f"실제 생산자 출력인데 {dropped}개가 버려졌다"
    # 정규형으로 통일된다 — `_month_key` 가 수익률에서 만드는 형식과 같아야 만난다.
    for key in by_month:
        assert len(key) == 7 and key[4] == "-", key


def test_the_real_labels_are_not_already_in_canonical_form(live_path):
    """★이 테스트가 결함의 존재 이유를 고정한다★

    실제 상류가 이미 `"YYYY-MM"` 을 낸다면 정규화는 죽은 코드다. 실측은 `"202204"`
    이므로 정규화가 실제로 일하고 있다. 상류가 형식을 바꾸면 여기서 먼저 알게 된다.
    """
    raw = {str(p.get("t")) for p in live_path}
    assert raw, "경로가 비었다"
    non_canonical = {t for t in raw if not (len(t) == 7 and t[4] == "-")}
    assert non_canonical, (
        "상류가 이미 정규형을 낸다 — 정규화가 죽은 코드가 됐거나 규약이 바뀌었다. "
        f"샘플: {sorted(raw)[:3]}")


@pytest.mark.parametrize("raw,expect", [
    ("202204", "2022-04"),      # 실제 수집기가 내는 형식
    ("2022-04", "2022-04"),     # 합성 테스트가 쓰던 형식 — 둘 다 받는다
    ("T-3", None),              # 자리표시자는 날짜가 아니다
    ("2022-13", None),          # 월이 아니다
    ("202213", None),
    ("", None), (None, None), ("20220", None), ("2022-4", None),
])
def test_both_month_formats_are_accepted_and_junk_is_not(raw, expect):
    assert _normalize_month(raw) == expect


def test_the_conditional_engine_actually_runs_on_live_inputs(live_path):
    """★배선이 운영에서 실제로 도는가★ 고치기 전에는 항상 무조건부로 떨어졌다."""
    import numpy as np
    import pandas as pd

    by_month, _ = regime_by_month_from_path(live_path)
    months = sorted(by_month)
    current = by_month[months[-1]]

    # 실제 월 라벨이 덮는 구간에 걸쳐 일별 수익률을 만든다(합성 값이지만 **인덱스는
    # 실제 라벨과 맞춰야** 정렬이 시험된다 — 그것이 결함 A 가 숨어 있던 자리다).
    idx = pd.bdate_range(f"{months[0]}-01", f"{months[-1]}-28")
    rng = np.random.default_rng(11)
    df = pd.DataFrame(rng.normal(0.0, 0.01, size=(len(idx), 3)),
                      index=idx, columns=["A", "B", "C"])

    out = conditional_moments(df, by_month, current)
    assert out["available"] is True, out["reason"]
    assert out["n_months"] > 0
    assert out["unlabeled_obs"] < len(df), "실제 라벨과 하나도 안 맞았다"


# ── 결함 B ─────────────────────────────────────────────────────────────────
def test_the_resolved_price_is_the_last_close_of_the_window_it_asked_for(monkeypatch):
    """★2099년 가격을 잡지 않는다★ 실측: 409원(2099) vs 40,263원(오늘).

    ★두 창을 비교하면 안 된다★ 처음에는 별도로 "오늘까지" 를 불러 비교했는데
    red 였다 — mock 로더는 **요청한 범위에 따라 다른 난수 경로**를 만들기 때문에
    창이 조금만 달라도 종가가 달라진다(36,895 vs 40,786). 창 계산을 테스트에
    복제하지 않고, **실제로 요청한 창**을 붙잡아 그 마지막 종가와 맞춘다.
    """
    from src.data.ohlcv_loader import load_ohlcv_unified as real

    seen = {}

    def _spy(code, start, end, prefer="auto"):
        seen["start"], seen["end"] = start, end
        return real(code, start, end, prefer=prefer)
    monkeypatch.setattr("src.data.ohlcv_loader.load_ohlcv_unified", _spy)

    price, source = bld._resolve_price(CODE, None)
    assert price is not None and source == "ohlcv_loader"

    d = real(CODE, seen["start"], seen["end"], prefer="auto")
    assert d is not None and not d.empty
    assert price == pytest.approx(float(d["close"].iloc[-1]), rel=1e-9)
    # 그리고 그 마지막 날이 오늘을 넘지 않는다 — 결함 B 의 본질.
    assert str(d.index[-1])[:10] <= date.today().isoformat()


def test_the_price_window_never_asks_for_the_future(monkeypatch):
    """★원인을 직접 건다★ mock 로더는 요청한 범위를 **그대로 생성**한다 —
    미래를 물으면 미래를 지어내 준다. 그래서 창의 끝을 본다."""
    seen = {}

    def _spy(code, start, end, prefer="auto"):
        seen["start"], seen["end"] = start, end
        from src.data.ohlcv_loader import load_ohlcv_unified as real
        return real(code, start, end, prefer=prefer)
    monkeypatch.setattr("src.data.ohlcv_loader.load_ohlcv_unified", _spy)

    bld._resolve_price(CODE, None)
    today = date.today().isoformat()
    assert seen["end"] <= today, f"미래를 요청했다: {seen['end']}"
    assert seen["start"] < seen["end"]


def test_an_explicit_price_still_wins_and_is_labelled():
    assert bld._resolve_price(CODE, 71000.0) == (71000.0, "caller")
    # 0·음수는 가격이 아니다 — 해석 경로로 넘어간다.
    price, source = bld._resolve_price(CODE, 0.0)
    assert source in ("ohlcv_loader", "unavailable")
    assert price != 0.0


def test_a_dead_loader_says_unavailable_rather_than_inventing(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("로더 없음")
    monkeypatch.setattr("src.data.ohlcv_loader.load_ohlcv_unified", _boom)
    assert bld._resolve_price(CODE, None) == (None, "unavailable")
