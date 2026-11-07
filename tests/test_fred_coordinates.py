"""FRED 토큰 경로 — ★일별 금리를 월별로 뭉개지 않는다★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` §A.3 · 선행: `1fa4fbd`(ECOS)

## ECOS 와 처방이 다르다 — 그 이유를 먼저 적는다

ECOS 에서는 근거 없는 항목코드를 **미지원으로 선언**했다. FRED 에는 **그 결함이
없다** — `US국채(5년) → DGS5` 는 자기서술적이고 자기일관적이며, 레지스트리에도
`DGS2`·`DGS10`·`DGS30`·`DGS3MO` 가 같은 패턴으로 라벨과 맞게 들어 있다.
★같은 처방을 기계적으로 적용하면 정상 작동하는 계열을 지우게 된다.★

## 이 파일이 막는 것

1. ★일별 → 월별 조용한 붕괴★ — 이 파일에서 **가장 위험한 결함**이다.
   `FredClient.fetch_series` 는 `frequency="m"`(대시보드용 월별)이 기본인데,
   이 토큰들은 **일별 종목 봉**에 정렬된다. 월별로 받으면 ffill 되어 그럴듯해
   보이지만 해상도가 사라진다. 저장소는 이미 그 해악을 안다 —
   `pit_macro` 모듈 독스트링 3번: *"frequency=\"m\" 서버측 집계가 월중 공표
   타이밍을 뭉갠다."*
2. ★기존 수집기 동작 변경★ — 기본값을 건드리면 대시보드 수집이 달라진다.
3. ★스로틀 없는 경로★ — FRED 는 분당 한도가 있다. 스로틀이 없으면 호출이
   실패하고, 실패는 `None` → 건너뛴 봉 → **쓸 수 있는 데이터가 줄어든다**.
4. ★레지스트리 등록이 새어 들어가는 것★ — `DGS1·3·5·7·20` 을 등록하면
   `collect_all()` 이 61→66계열이 되고 capability 프로브 분모와 골든 스냅샷이
   바뀐다. 소비자가 없고 DGS 는 개정되지도 않아 값이 없다.

## 짝 검증

F1/F2 — 한쪽만 있으면 "전부 월별" 이나 "전부 원본" 구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.kis_strategies.factor_tokens as ft  # noqa: E402
import src.services.macro_collector as mc  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    ft._fred_cache.clear()
    yield
    ft._fred_cache.clear()


class _Resp:
    @staticmethod
    def json():
        return {"observations": [
            {"date": "2026-01-02", "value": "4.25"},
            {"date": "2026-01-05", "value": "."},      # FRED 결측 관례
            {"date": "2026-01-06", "value": "4.31"},
        ]}


@pytest.fixture
def captured(monkeypatch):
    """`requests.get` 을 가로채 params 를 본다."""
    seen: dict = {}

    def fake_get(url, params=None, timeout=None):
        seen["url"] = url
        seen["params"] = dict(params or {})
        return _Resp()

    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setattr(mc.requests, "get", fake_get)
    monkeypatch.setattr(mc.FredClient, "_throttle", lambda self: None)
    return seen


# ══════════════════════════════════════════════════════════════════════════
# 1) ★frequency — 가장 위험한 곳★
# ══════════════════════════════════════════════════════════════════════════
def test_collector_frequency_default_is_monthly():
    """F1 — ★기본값 `"m"` 이 기존 동작이다★ 바꾸면 대시보드 수집이 달라진다."""
    import inspect

    sig = inspect.signature(mc.FredClient.fetch_series)
    assert sig.parameters["frequency"].default == "m"


def test_token_path_does_not_request_monthly_aggregation(captured):
    """F2 ★짝★ — 일별 금리가 월별로 뭉개지면 ffill 되어 그럴듯해 보인다."""
    ft._fred_series("US국채(10년)")
    assert "frequency" not in captured["params"], \
        f"월별 집계를 요청했다: {captured['params'].get('frequency')!r}"


def test_none_frequency_omits_the_parameter_entirely(captured):
    """F3 — 빈 문자열을 보내면 FRED 가 거부한다. 키 자체가 없어야 한다."""
    mc.FredClient().fetch_series("DGS10", frequency=None)
    assert "frequency" not in captured["params"]


def test_explicit_frequency_is_still_sent(captured):
    """F3 짝 — "항상 생략" 구현을 배제한다."""
    mc.FredClient().fetch_series("DGS10", frequency="m")
    assert captured["params"].get("frequency") == "m"


# ══════════════════════════════════════════════════════════════════════════
# 2) 수집기 클라이언트를 통과한다
# ══════════════════════════════════════════════════════════════════════════
def test_fred_series_goes_through_the_collector_client(monkeypatch):
    """F4 — 직접 URL 을 만들면 스로틀·키 검증이 갈라진다."""
    calls: list[tuple] = []

    def spy(self, series_id, start=None, end=None, frequency="m"):
        calls.append((series_id, start, frequency))
        return ["2026-01-02"], [4.25]

    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setattr(mc.FredClient, "fetch_series", spy)

    s = ft._fred_series("US국채(5년)")
    assert calls, "`FredClient.fetch_series` 를 부르지 않았다 — 직접 호출 중이다"
    assert calls[0][0] == "DGS5"
    assert calls[0][1] == ft.FRED_DAILY_START
    assert calls[0][2] is None, "월별 집계를 요청했다"
    assert s is not None and float(s.iloc[0]) == pytest.approx(4.25)


def test_a_short_key_is_not_a_key(monkeypatch):
    """F5 — 수집기와 같은 판정(`len > 10`). 예전에는 `if key` 였다."""
    called: list[int] = []
    monkeypatch.setenv("FRED_API_KEY", "abc")
    monkeypatch.setattr(mc.FredClient, "fetch_series",
                        lambda *a, **k: called.append(1) or ([], []))
    assert ft._fred_series("US국채(10년)") is None
    assert called == [], "짧은 키로 호출했다"


def test_no_key_still_returns_none(monkeypatch):
    """F6 — ★기존 계약 불변★

    이 환경에는 `FRED_API_KEY` 가 없으므로 이번 변경으로 **숫자가 바뀌지 않는다**.
    골든 스냅샷은 `factor_tokens` 를 지나지 않으니, 그 근거가 바로 이것이다.
    """
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert ft._fred_series("US국채(10년)") is None


def test_observation_start_is_preserved(captured):
    """F7 — 기존 동작(2005-01-01)을 그대로 옮겼다."""
    ft._fred_series("US국채(10년)")
    assert captured["params"].get("observation_start") == ft.FRED_DAILY_START
    assert ft.FRED_DAILY_START == "2005-01-01"


# ══════════════════════════════════════════════════════════════════════════
# 3) 파서가 죽지 않았고 규칙을 공유한다
# ══════════════════════════════════════════════════════════════════════════
def test_parse_fred_rows_shares_the_parse_rule():
    """F8 — 죽은 코드를 테스트하는 상태를 만들지 않는다."""
    payload = {"observations": [
        {"date": "2026-01-02", "value": "4.25"},
        {"date": "2026-01-05", "value": "."},
        {"date": "2026-01-06", "value": "4.31"},
    ]}
    a = ft.parse_fred_rows(payload)
    b = ft.fred_rows_to_series(["2026-01-02", "2026-01-05", "2026-01-06"],
                               ["4.25", ".", "4.31"])
    assert a is not None and b is not None
    assert list(a.index) == list(b.index)
    assert list(a.values) == list(b.values)


def test_missing_dot_is_never_a_value():
    """F9 — ★FRED 결측은 `"."` 이다★ 숫자로 새어 들어가면 계열이 오염된다."""
    s = ft.fred_rows_to_series(["2026-01-02", "2026-01-05"], ["4.25", "."])
    assert len(s) == 1 and float(s.iloc[0]) == pytest.approx(4.25)
    assert ft.fred_rows_to_series(["2026-01-05"], ["."]) is None


def test_series_is_sorted_by_date():
    s = ft.fred_rows_to_series(["2026-01-06", "2026-01-02"], ["4.31", "4.25"])
    assert list(s.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-06")]


# ══════════════════════════════════════════════════════════════════════════
# 4) 토큰 매핑 — 결함은 없지만 드리프트는 막는다
# ══════════════════════════════════════════════════════════════════════════
def test_token_maturity_matches_the_series_id():
    """F10 — 지금은 컴프리헨션이라 자동 일치한다. 손 예외가 들어오면 잡는다."""
    import re

    for name, sid in ft.FRED_TOKENS.items():
        m = re.fullmatch(r"US국채\((\d+)년\)", name)
        assert m, f"예상 밖 토큰명: {name}"
        assert sid == f"DGS{m.group(1)}", f"{name} 이 {sid} 를 가리킨다"


def test_registry_backed_tokens_agree_with_the_registry():
    """레지스트리에 있는 3종은 라벨까지 맞는지 확인한다."""
    from src.data.source_registry import get_spec

    for name, sid in ft.FRED_TOKENS.items():
        spec = get_spec(sid)
        if spec is None:
            continue                      # 미등록 — F11 이 그 상태를 고정한다
        years = name.removeprefix("US국채(").removesuffix("년)")
        assert years in spec.label, f"{name} ↔ {spec.label} 이 어긋난다"


# ══════════════════════════════════════════════════════════════════════════
# 5) ★레지스트리를 건드리지 않았다★
# ══════════════════════════════════════════════════════════════════════════
def test_fred_collection_targets_count_is_unchanged():
    """F11 — ★등록이 새어 들어가면 골든 스냅샷이 깨진다★

    `fred_collection_targets()` 는 `macro_collector.FRED_INDICATORS` 이고,
    `collect_all()` 결과 개수가 `capability.py` 의 `total_series` 이며, 그 값이
    골든 스냅샷 `frontier_sample` 에 들어 있다. `DGS1·3·5·7·20` 을 등록하면
    61→66 이 되어 6커밋 동안 지켜온 바이트 동일성이 깨진다.

    등록하지 않기로 한 이유: 소비자가 없고(`term_structure` 요건은 scipy 라이브러리
    프로브다), DGS 는 일별 시장 관측치라 개정되지 않아 빈티지 연구에도 보탬이 안 된다.
    """
    from src.data.source_registry import fred_collection_targets

    assert len(fred_collection_targets()) == 21, "FRED 레지스트리 계열 수가 바뀌었다"


def test_the_unregistered_treasury_series_stay_unregistered():
    """F11 짝 — 어느 계열이 미등록인지 이름으로 고정한다."""
    from src.data.source_registry import get_spec

    for n in (1, 3, 5, 7, 20):
        assert get_spec(f"DGS{n}") is None, f"DGS{n} 이 등록됐다 — 수집이 늘어난다"
    for n in (2, 10, 30):
        assert get_spec(f"DGS{n}") is not None, f"DGS{n} 등록이 사라졌다"
