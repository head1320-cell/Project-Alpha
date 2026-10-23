"""ECOS 좌표 — ★회사채를 국고채라고 부르지 않는다★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` §A.4(ECOS 클라이언트 둘)

## 이 파일이 막는 것

`factor_tokens` 가 통계표·항목코드를 **직접 들고** 있었고, `source_registry` 와
대조하니 갈라져 있었다(실측):

    "국고채(3년)"  → 817Y002/010200000 = 레지스트리의 ★회사채 3년(AA-)★
    "국고채(2년)"  → 817Y002/010195000 = 레지스트리의 ★국고채 3년★(verified_live)
    "국고채(10년)" → 817Y002/010210001 = 레지스트리에 없음(검증본은 817Y003/…)

★`국고채(3년)` 을 쓰는 전략이 AA- 회사채 수익률을 받고 있었다.★ 국채와 회사채는
신용스프레드만큼 다르고 그 차이는 조용하다.

그리고 레지스트리는 국고 5년·20년 코드를 **일부러 비워 두고** 이유를 적어 뒀다 —
*"코드를 지어내서 계열을 하나 더 세는 것은 확장이 아니라 그럴듯한 빈칸을 만드는
일이다."* 이 파일은 정확히 그 일을 하고 있었다(9개 중 5개가 근거 없는 코드).

## ★어느 쪽이 옳은지 단정하지 않는다★

오프라인이라 API 로 확인할 수 없다. 다만 증거가 비대칭이다 — 레지스트리는
`verified_live` / 미검증 표시로 **검증 상태를 기록**하고 `factor_tokens` 에는
그런 표시가 하나도 없었다. 그래서 "레지스트리가 옳다" 가 아니라
**"좌표는 검증 상태를 가진 곳에서 온다"** 를 못 박는다.

## 짝 검증

C1/C2 · C5/C6 · C9/C10 — 한쪽만 있으면 "전부 일치" · "전부 미지원" · "한도 무시"
구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.kis_strategies.factor_tokens as ft  # noqa: E402
from src.data.source_registry import ECOS, get_spec, specs_by_provider  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    ft._ecos_cache.clear()
    yield
    ft._ecos_cache.clear()


def _by_endpoint():
    return {s.endpoint: s for s in specs_by_provider(ECOS)}


# ══════════════════════════════════════════════════════════════════════════
# 1) ★좌표는 레지스트리에서 온다★
# ══════════════════════════════════════════════════════════════════════════
def test_every_token_coordinate_matches_a_registry_spec():
    """C1 — 토큰의 (통계표, 항목)이 레지스트리 spec 과 정확히 같다."""
    by_ep = _by_endpoint()
    for name, (stat, item) in ft.ECOS_TOKENS.items():
        key = ft._ECOS_TOKEN_KEYS[name]
        spec = get_spec(key)
        assert spec is not None, f"{name} 의 레지스트리 key({key}) 가 없다"
        assert f"{stat}/{item}" == spec.endpoint, f"{name} 좌표가 갈라졌다"
        assert f"{stat}/{item}" in by_ep


def test_no_token_uses_a_coordinate_absent_from_the_registry():
    """C2 ★짝★ — 없으면 "전부 일치" 구현으로도 C1 이 통과한다."""
    known = set(_by_endpoint())
    unknown = {n: f"{s}/{i}" for n, (s, i) in ft.ECOS_TOKENS.items()
               if f"{s}/{i}" not in known}
    assert unknown == {}, f"근거 없는 좌표를 쓰는 토큰: {unknown}"


def test_the_three_year_token_is_a_government_bond_not_a_corporate_one():
    """C3 ★회귀 고정★ — 이것이 이 작업의 이유다.

    예전 좌표 `817Y002/010200000` 은 레지스트리에서 **회사채 3년(AA-)** 이다.
    """
    stat, item = ft.ECOS_TOKENS["국고채(3년)"]
    spec = _by_endpoint()[f"{stat}/{item}"]
    assert spec.key == "KR_3Y", f"국고채(3년)이 {spec.key}({spec.label}) 를 가리킨다"
    assert "회사채" not in spec.label
    assert (stat, item) != ("817Y002", "010200000"), "옛 회사채 좌표로 되돌아갔다"


def test_the_ten_year_token_uses_the_verified_statistic_table():
    """C4 — 통계표까지 확인한다. 검증본은 `817Y003` 이고 예전 값은 `817Y002` 였다."""
    stat, item = ft.ECOS_TOKENS["국고채(10년)"]
    assert (stat, item) == ("817Y003", "010210000")
    assert _by_endpoint()[f"{stat}/{item}"].key == "KR_10Y"


def test_tokens_disappear_when_the_registry_spec_does(monkeypatch):
    """C8 — ★파생의 증명★ 하드코딩이면 이 테스트가 죽는다."""
    import src.data.source_registry as reg

    real = reg.get_spec
    monkeypatch.setattr(reg, "get_spec",
                        lambda k: None if k == "KR_3Y" else real(k))
    got = ft._ecos_token_coordinates()
    assert "국고채(3년)" not in got, "레지스트리에 없는데 토큰이 살아 있다"
    assert "국고채(1년)" in got, "무관한 토큰까지 사라졌다"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★근거 없는 토큰 — 목록에는 남기되 값을 내지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_unverified_tokens_declare_a_reason():
    """C5 — 기존 정직성 관례(`UNSUPPORTED_REASONS`)에 태운다."""
    for t in ft.ECOS_UNVERIFIED_TOKENS:
        assert t in ft.UNSUPPORTED_REASONS, f"{t} 에 사유가 없다"
        assert ft.UNSUPPORTED_REASONS[t] == ft.REASON_UNVERIFIED_CODE


def test_unverified_tokens_are_not_supported():
    """C6 ★짝★ — 사유만 달고 `supported` 에도 남기면 UI 가 계속 권한다."""
    support = ft.token_support()
    for t in ft.ECOS_UNVERIFIED_TOKENS:
        assert t not in support["supported"], f"{t} 가 여전히 지원으로 나온다"
        assert t in support["unsupported"], f"{t} 가 사유 목록에서 빠졌다"


def test_backed_tokens_are_still_supported():
    """C6 짝의 짝 — "전부 미지원" 구현을 배제한다."""
    support = ft.token_support()
    for t in ft.ECOS_TOKENS:
        assert t in support["supported"], f"{t} 가 지원에서 빠졌다"
        assert support["supported"][t] == "macro"


def test_an_unverified_token_resolves_to_none(monkeypatch):
    """C7 — ★추측한 코드로 값을 내지 않는다★"""
    monkeypatch.setenv("BOK_API_KEY", "x" * 32)
    df = pd.DataFrame({"close": [1.0, 2.0]},
                      index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    assert ft.resolve_macro_token(df, "국고채(5년)") is None
    assert ft.resolve_macro_token(df, "엔환율") is None


def test_the_registry_still_declines_the_five_and_twenty_year_codes():
    """★레지스트리 저자의 판단을 우리가 뒤집지 않았다★

    5년·20년 국고채 좌표를 레지스트리에 몰래 편입했다면 이 테스트가 죽는다.
    """
    labels = {s.label for s in specs_by_provider(ECOS)}
    assert "국고채 5년" not in labels and "국고채 20년" not in labels


# ══════════════════════════════════════════════════════════════════════════
# 3) ★조용한 절단을 막는다★
# ══════════════════════════════════════════════════════════════════════════
def test_collector_row_limit_default_is_unchanged():
    """C9 — ★기본값 1000 이 기존 동작이다★ 바꾸면 매크로 수집이 달라진다."""
    import inspect

    from src.services.macro_collector import BokClient

    assert inspect.signature(BokClient.fetch_series).parameters["limit"].default == 1000


def test_daily_fetch_is_not_truncated_at_one_thousand(monkeypatch):
    """C10 ★짝★ — 일별 20년은 5,000행이 넘는다. 1000 이면 4년으로 줄어든다."""
    seen: dict[str, str] = {}

    class _Resp:
        @staticmethod
        def json():
            return {"StatisticSearch": {"row": [
                {"TIME": "20260102", "DATA_VALUE": "3.5"}]}}

    def fake_get(url, timeout=None):
        seen["url"] = url
        return _Resp()

    monkeypatch.setenv("BOK_API_KEY", "x" * 32)
    import src.services.macro_collector as mc
    monkeypatch.setattr(mc.requests, "get", fake_get)
    monkeypatch.setattr(mc.BokClient, "_throttle", lambda self: None)

    ft._ecos_cache.clear()
    ft._ecos_series("국고채(3년)")
    assert f"/json/kr/1/{ft.ECOS_DAILY_LIMIT}/" in seen["url"], seen.get("url")
    assert "/json/kr/1/1000/" not in seen["url"], "1000 행에서 잘린다"
    assert "/D/" in seen["url"], "일별 조회가 아니다"


# ══════════════════════════════════════════════════════════════════════════
# 4) ★수집기 클라이언트를 통과한다★
# ══════════════════════════════════════════════════════════════════════════
def test_ecos_series_goes_through_the_collector_client(monkeypatch):
    """C11 — 직접 URL 을 만들면 스로틀·키 검증이 갈라진다."""
    calls: list[tuple] = []

    def spy(self, stat, item="0", start=None, end=None, period="M", limit=1000):
        calls.append((stat, item, period, limit))
        return ["20260102"], [3.5]

    monkeypatch.setenv("BOK_API_KEY", "x" * 32)
    import src.services.macro_collector as mc
    monkeypatch.setattr(mc.BokClient, "fetch_series", spy)

    ft._ecos_cache.clear()
    s = ft._ecos_series("국고채(3년)")
    assert calls, "`BokClient.fetch_series` 를 부르지 않았다 — 직접 호출 중이다"
    assert calls[0][:2] == ft.ECOS_TOKENS["국고채(3년)"]
    assert calls[0][2] == "D" and calls[0][3] == ft.ECOS_DAILY_LIMIT
    assert s is not None and float(s.iloc[0]) == pytest.approx(3.5)


def test_a_short_key_is_not_a_key(monkeypatch):
    """C12 — 수집기와 같은 판정(`len > 10`). 예전에는 `if key` 였다."""
    called: list[int] = []

    import src.services.macro_collector as mc
    monkeypatch.setenv("BOK_API_KEY", "abc")
    monkeypatch.setattr(mc.BokClient, "fetch_series",
                        lambda *a, **k: called.append(1) or ([], []))
    ft._ecos_cache.clear()
    assert ft._ecos_series("국고채(3년)") is None
    assert called == [], "짧은 키로 호출했다"


def test_no_key_still_returns_none(monkeypatch):
    """C14 — ★기존 계약 불변★ 키가 없으면 None 이고 엔진이 그 봉을 건너뛴다.

    이 환경에는 `BOK_API_KEY` 가 없으므로, 이번 변경으로 **숫자가 바뀌지 않는다**는
    근거가 바로 이것이다(골든 스냅샷은 `factor_tokens` 를 지나지 않는다).
    """
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    ft._ecos_cache.clear()
    assert ft._ecos_series("국고채(3년)") is None


# ══════════════════════════════════════════════════════════════════════════
# 5) 파서가 죽지 않았다
# ══════════════════════════════════════════════════════════════════════════
def test_parse_ecos_rows_shares_the_date_rule():
    """C13 — 죽은 코드를 테스트하는 상태를 만들지 않는다.

    `parse_ecos_rows`(원시 payload)와 `ecos_rows_to_series`(클라이언트 경로)가
    **같은 규칙**을 써야 한다. 각자 파싱하면 언젠가 갈라진다.
    """
    payload = {"StatisticSearch": {"row": [
        {"TIME": "20260102", "DATA_VALUE": "3.5"},
        {"TIME": "202601", "DATA_VALUE": "9.9"},     # 월별 — 일별 규칙에서 제외
        {"TIME": "20260105", "DATA_VALUE": ""},      # 결측
    ]}}
    a = ft.parse_ecos_rows(payload)
    b = ft.ecos_rows_to_series(["20260102", "202601", "20260105"], ["3.5", "9.9", ""])
    assert a is not None and b is not None
    assert list(a.index) == list(b.index) and list(a.values) == list(b.values)
    assert len(a) == 1 and float(a.iloc[0]) == pytest.approx(3.5)
