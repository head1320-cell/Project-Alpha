"""라이브 알파 스코어 — `score_alpha` (P2-S)
==============================================================================
★이 파일이 존재하는 이유★
`validate_alpha` 는 IC 를 재려고 **데이터 끝에서 21거래일 전**까지만 본다
(`rebal_idx` 가 forward 1개월 확보분을 뺀다). 그래서 그 리포트의 `latest_scores_top`
은 한 달 낡은 점수인데, 02 ALPHA LAB 의 "상위 10종목 → 포트폴리오" 버튼이 그것을
**현재 비중으로** 써 왔다. 실측: 오늘 2026-08-14 에 리포트의 `period_end` 는 2026-07-16.

`score_alpha` 는 as-of 시점의 **실제** 점수를 낸다. 그리고 그 구현에서 가장 쉬운 실수는
검증 루프를 그대로 재사용하는 것이다 — 그 루프의 `if not np.isfinite(fr[1]): continue`
는 최신 시점에서 **모든 종목을 탈락**시킨다(최신 시점엔 미래가 없으므로). 아래 첫 번째
단언이 정확히 그 함정을 잡는다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.alpha_lab import MIN_NAMES, score_alpha, validate_alpha

TICKERS = [f"{i:06d}" for i in range(1, 41)]


def _loader():
    """40종목 × 820일 합성 시계열 — `test_alpha_lab.py` 와 같은 관례(네트워크 불필요)."""
    def loader(tickers, start, end):
        import pandas as pd
        rng = np.random.default_rng(7)
        n_days = 820
        idx = pd.bdate_range("2023-01-02", periods=n_days)
        drifts = np.linspace(-0.0035, 0.0035, len(tickers[:40]))
        out = {}
        for k, t in enumerate(tickers[:40]):
            r = drifts[k] + rng.normal(0, 0.004, n_days)
            c = 10000 * np.cumprod(1 + r)
            df = pd.DataFrame({"close": c, "amount": np.full(n_days, 1e9)}, index=idx)
            out[t] = df
        return {tk: {"dates": np.array(v.index.values, dtype="datetime64[D]"),
                     "close": v["close"].values, "amount": v["amount"].values}
                for tk, v in out.items()}
    return loader


# ── 1. ★최신 시점에도 종목이 나온다 (forward 필터 함정)★ ────────────────────

def test_latest_scores_are_not_wiped_out_by_the_forward_return_filter():
    """검증 루프의 forward 필터를 물려받았다면 커버리지가 0 이 된다.

    그 상태의 빈 결과는 화면에서 "알파가 아무것도 못 골랐다" 로 읽히지만, 참인 것은
    "미래를 아직 모른다" 뿐이다. 둘은 다른 사실이다.
    """
    r = score_alpha("rank(mom_1m)", TICKERS, price_loader=_loader())
    assert r["available"] is True, r.get("reason")
    assert r["coverage"] >= MIN_NAMES, f"최신 시점 커버리지 {r['coverage']}"
    assert len(r["scores"]) == r["coverage"]
    assert all(np.isfinite(v) for v in r["scores"].values())


# ── 2. ★as_of 짝 단언★ ──────────────────────────────────────────────────────
# 하나만 있으면 as_of 를 무시해도 통과한다 — P1-A 에서 배운 형태 그대로.

def test_as_of_is_stamped_even_when_not_requested():
    r = score_alpha("rank(mom_1m)", TICKERS, price_loader=_loader())
    assert r["as_of_requested"] is None
    assert r["as_of_effective"], "서버가 실제로 쓴 절단일이 없다 — 재현 좌표가 없다"


def test_a_different_as_of_actually_uses_a_different_cut():
    late = score_alpha("rank(mom_1m)", TICKERS, price_loader=_loader())
    early = score_alpha("rank(mom_1m)", TICKERS, as_of="2024-06-28", price_loader=_loader())
    assert early["available"] is True, early.get("reason")
    assert early["as_of_effective"] < late["as_of_effective"]
    # 절단일이 다르면 점수도 달라야 한다 — 같으면 as_of 가 무시된 것이다.
    assert early["scores"] != late["scores"]


def test_as_of_before_any_history_is_refused_with_a_reason():
    """★모르는 것을 0 으로 답하지 않는다★ 252봉이 없으면 사유를 낸다."""
    r = score_alpha("rank(mom_1m)", TICKERS, as_of="2023-02-01", price_loader=_loader())
    assert r["available"] is False
    assert r["reason"] and "히스토리" in r["reason"]
    assert "scores" not in r, "미가용인데 점수를 냈다"


# ── 3. 표현식·유니버스 실패는 사유로 답한다 ─────────────────────────────────

def test_a_broken_expression_is_a_reason_not_a_crash():
    r = score_alpha("rank(does_not_exist)", TICKERS, price_loader=_loader())
    assert r["available"] is False
    assert r["reason"]


def test_too_small_a_universe_is_refused():
    r = score_alpha("rank(mom_1m)", TICKERS[:3], price_loader=_loader())
    assert r["available"] is False
    assert str(MIN_NAMES) in r["reason"]


# ── 4. ★리팩터링 불변 — `validate_alpha` 는 한 자리도 바뀌지 않는다★ ────────

def test_validation_report_is_unchanged_by_the_panel_extraction():
    """`_panel_at` 분리는 리팩터링이지 동작 변경이 아니다.

    검증 경로는 `require_forward=True` 로 예전 그대로 돌아야 한다. 이 단언이 없으면
    라이브 스코어링을 위해 검증을 조용히 바꿔 놓고도 모를 수 있다.
    """
    rep = validate_alpha("rank(mom_1m)", TICKERS, months=18, price_loader=_loader())
    assert rep["error"] is False, rep.get("message")
    # 합성 세계는 모멘텀이 지속되도록 만들었으므로 IC 가 뚜렷하게 양수여야 한다.
    assert rep["ic"]["mean"] is not None and rep["ic"]["mean"] > 0.3
    assert rep["quantiles"]["monotonicity"] is not None
    assert rep["n_periods"] >= 6


def test_the_validation_report_scores_are_older_than_the_live_scores():
    """★낡음의 크기를 숫자로 고정한다★

    리포트의 마지막 리밸런스 시점은 forward 확보 때문에 데이터 끝보다 이르다. 그래서
    `latest_scores_top` 을 현재 비중으로 쓰면 그만큼 낡은 값을 쓰는 것이고, 화면은 그
    사실을 말해야 한다(P2-U 가 문구를 넣는다).
    """
    rep = validate_alpha("rank(mom_1m)", TICKERS, months=18, price_loader=_loader())
    live = score_alpha("rank(mom_1m)", TICKERS, price_loader=_loader())
    assert rep["period_end"] < live["as_of_effective"], (
        "리포트 시점이 라이브 시점보다 이르지 않다 — 낡음 경고의 전제가 깨졌다")


# ── 5. 점수는 크로스섹션이다 (rank 는 [0,1] 안) ─────────────────────────────

@pytest.mark.parametrize("expr", ["rank(mom_1m)", "zscore(vol_20d)", "neg(rank(mom_3m))"])
def test_scores_are_finite_and_cross_sectional(expr):
    r = score_alpha(expr, TICKERS, price_loader=_loader())
    assert r["available"] is True, r.get("reason")
    vals = np.asarray(list(r["scores"].values()), dtype=float)
    assert np.isfinite(vals).all()
    if expr.startswith("rank("):
        assert vals.min() >= 0.0 and vals.max() <= 1.0
