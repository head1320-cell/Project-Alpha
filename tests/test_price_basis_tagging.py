"""가격 정직화 — ★어느 경로로 받았든 그 `close` 가 무엇인지 말한다★
==============================================================================
우선순위 P0 · 감사 부록 2(가격 의미 계약) · 선행 `1e3226a`·`5fbf817`

## 무엇이 문제였나

`close` 는 **하나의 값이 아니다** — `source='krx'` 행은 원주가, `source='kis'` 행은
수정주가(`DAILY_ADJ_PRC_FLAG="0"` 로 요청)다. 그 사실은 `price_quality` 가 이미
판정할 수 있는데(`adj_status_of`·`adj_close_coverage`), ★로더가 그것을 호출자에게
전하지 않았다★.

정확히는 **일부만** 전했다(실측):

```python
if prefer == "mock": return _mock_ohlcv_df(...)   # source 만, adj_status 없음
if prefer == "db":   return _db_ohlcv_df(...)     # ★아무 태그도 없음★
if prefer == "kis":  ... return df                # ★아무 태그도 없음★
# auto 만 _tag_adj_status() 를 부르는데, 그것도 db/kis 가 성공했을 때만
```

이 환경에서는 `daily_prices` 가 없어 auto 가 mock 으로 떨어지므로 ★`adj_status` 가
붙는 관측 가능한 경로가 하나도 없다★.

## 이번 범위 — ★정직화만★

- 네 경로 **전부** 태깅한다.
- `basis_consistency`(원주가·수정주가 **혼합** 여부)를 새로 싣는다. `adj_status`
  하나로는 "섞였다" 를 말할 수 없다.
- ★반환 컬럼은 한 글자도 바꾸지 않는다★ — `load_ohlcv_unified` 호출부 19곳.
  `close → adj_close` 전환은 배분·백테스트 동작 변경이라 별도 승인 사항이다.

## 짝 검증

P1/P2 · P3/P4 — 한쪽만 있으면 "컬럼을 마구 늘린다" · "항상 mixed 라고 한다"
구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.ohlcv_loader as ol  # noqa: E402

#: 로더가 돌려주던 컬럼 — ★이 목록이 바뀌면 19개 호출부가 영향을 받는다★
BASE_COLS = ["open", "high", "low", "close", "volume"]
TAGS = ("source", "adj_status", "price_basis")


def _df(n: int = 30):
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({c: [100.0] * n for c in BASE_COLS}, index=idx)


@pytest.fixture
def stub(monkeypatch):
    """db·kis 경로가 값을 내도록 세운다 — 이 환경엔 `daily_prices` 가 없다."""
    monkeypatch.setattr(ol, "_db_ohlcv_df", lambda c, s, e: _df())
    monkeypatch.setattr(ol, "_kis_ohlcv_df", lambda c, s, e: _df())
    monkeypatch.setattr(ol, "ingest_df_to_db", lambda c, d: 0)
    monkeypatch.setattr("src.data.price_quality.adj_status_of", lambda code, **k: "adjusted")
    monkeypatch.setattr("src.data.price_quality.adj_close_coverage",
                        lambda **k: {"basis_consistency": "uniform_adjusted"})


# ══════════════════════════════════════════════════════════════════════════
# 1) ★네 경로가 전부 말한다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("prefer", ["mock", "db", "kis", "auto"])
def test_every_path_tags_what_the_close_means(stub, prefer):
    """P1 — 경로마다 태깅이 다르면 그 비대칭 자체가 함정이다.

    ★예전에는 `auto` 만, 그것도 db/kis 성공 시에만 `adj_status` 를 붙였다.★
    """
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer=prefer)
    assert not df.empty, f"{prefer} 경로가 비었다 — 시나리오가 성립하지 않는다"
    for t in TAGS:
        assert t in df.attrs, f"{prefer} 경로에 {t} 태그가 없다: {dict(df.attrs)}"
    assert df.attrs["source"] in ("mock", "db", "kis")


@pytest.mark.parametrize("prefer", ["mock", "db", "kis", "auto"])
def test_the_returned_columns_are_unchanged(stub, prefer):
    """P2 ★짝★ — ★이 단언이 19개 호출부의 불변 증거다★

    태깅은 `attrs` 로만 한다. 컬럼을 늘리면 `df[cols]` 를 쓰는 소비자가 깨지고,
    줄이면 조용히 KeyError 가 난다.
    """
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer=prefer)
    assert list(df.columns) == BASE_COLS, f"{prefer} 의 컬럼이 바뀌었다"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★"섞였다" 를 말할 수 있다★
# ══════════════════════════════════════════════════════════════════════════
def test_mixed_basis_is_visible(monkeypatch, stub):
    """P3 — `adj_status` 하나로는 혼합을 말할 수 없다.

    `close` 가 원주가 행과 수정주가 행을 함께 담고 있으면 그 계열로 계산한
    수익률은 **정의가 섞인 수익률**이다. 조용히 넘기면 아무도 모른다.
    """
    monkeypatch.setattr("src.data.price_quality.adj_close_coverage",
                        lambda **k: {"basis_consistency": "mixed"})
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer="db")
    assert df.attrs["price_basis"] == "mixed"


def test_uniform_basis_is_not_reported_as_mixed(stub):
    """P4 ★짝★ — "항상 mixed" 구현을 배제한다. 늘 경고하면 아무도 안 읽는다."""
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer="db")
    assert df.attrs["price_basis"] == "uniform_adjusted"


def test_unknown_basis_is_its_own_state(monkeypatch, stub):
    """P3 보강 — 레거시 행(전부 NULL)은 `unknown` 이지 `mixed` 도 균일도 아니다."""
    monkeypatch.setattr("src.data.price_quality.adj_close_coverage",
                        lambda **k: {"basis_consistency": "unknown"})
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer="db")
    assert df.attrs["price_basis"] == "unknown"


# ══════════════════════════════════════════════════════════════════════════
# 3) 태그는 ★힌트지 권위가 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_tagging_failure_does_not_kill_the_dataframe(monkeypatch, stub):
    """P5 — 판정이 터져도 가격은 돌려준다.

    ★게이트를 세울 때는 `price_quality` 를 직접 부를 것★ — 이 태그는
    `attrs["source"]` 와 같은 성격의 편의다. pandas 연산에서 `attrs` 보존은
    보장되지 않는다(슬라이스·merge 에서 사라진다).
    """
    def boom(*a, **k):
        raise RuntimeError("판정 실패")

    monkeypatch.setattr("src.data.price_quality.adj_status_of", boom)
    monkeypatch.setattr("src.data.price_quality.adj_close_coverage", boom)
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer="db")
    assert list(df.columns) == BASE_COLS and not df.empty
    assert df.attrs.get("source") == "db", "실패해도 아는 것은 말해야 한다"


def test_an_empty_result_still_says_where_it_came_from(monkeypatch):
    """P1 보강 — ★빈 결과에도 출처는 말한다★

    `_kis_ohlcv_df` 는 실패 시 `None` 을 낸다. 빈 df 로 바꾼 **뒤에** 태깅하지
    않으면 이 경로만 `attrs` 가 비어, 없애려던 비대칭이 그대로 남는다.
    호출자는 "kis 에서 왔는데 없었다" 와 "아무 데도 안 갔다" 를 구분해야 한다.
    """
    monkeypatch.setattr(ol, "_kis_ohlcv_df", lambda c, s_, e: None)
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01", prefer="kis")
    assert df.empty
    assert df.attrs.get("source") == "kis"


def test_production_without_data_returns_empty_not_synthetic(monkeypatch):
    """P6 — ★기존 계약 불변★ 운영에서 데이터가 없으면 빈 df 다(합성 금지).

    태깅을 더하면서 이 계약을 건드리지 않았다는 확인이다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(ol, "_db_ohlcv_df", lambda c, s, e: pd.DataFrame())
    monkeypatch.setattr(ol, "_kis_ohlcv_df", lambda c, s, e: None)
    df = ol.load_ohlcv_unified("005930", "2024-01-01", "2024-03-01")
    assert df.empty, "운영에서 합성값이 나왔다"
