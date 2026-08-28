"""국면 축 개정 상태 — ★"빈티지가 있다" 와 "빈티지를 쓴다" 는 다르다★
==============================================================================
계획: 아키텍처 패스 후속 — 실계열 게이트 조건 2.

## 무엇이 문제였나

`allocation_routes._pit_block()` 이 전역 상수 `_REVISION_BIAS = "unmanaged"` 를
박고 있었다. ★값은 맞았지만 판정을 하지 않았다.★ 그래서 두 종류의 차단이 같은
라벨을 달고 구분되지 않았다:

| 차단 | 예 | 성격 |
|---|---|---|
| **소스** | ECOS·KRX — 빈티지 엔드포인트가 없다 | ★영구★ |
| **경로** | FRED — 소스엔 빈티지가 있고 우리가 안 가져온다 | ★고칠 수 있다★ |

`us` 축은 6계열 **전부** 경로 차단이다. 즉 수집기만 고치면 백테스트 적격이 되는데,
전역 상수는 그 사실을 지웠다.

## ★반대 방향의 함정 — 레지스트리만 보면 과대주장한다★

`source_registry.has_vintage=True` 는 **API 가 줄 수 있다**는 뜻이지 **우리가
가져온다**는 뜻이 아니다. 국면 축은 `macro_collector.collect_all()` 을 읽고 그 경로는
현재값만 가져온다. 레지스트리만 보고 `managed` 라고 적으면, 현재 개정본으로 과거를
채점하면서 "PIT 통과" 라고 표시하게 된다.

`pit_macro` 자신이 같은 계열의 오류를 이미 겪었다 — 빈 `realtime_start` 를 `as_of`
로 채워 `has_vintage` 를 참으로 만들었던 버그.

## ★선언과 현실을 대조한다★

`macro_collector.COLLECTOR_READS_VINTAGE` 는 **선언**이다. 아래
`test_declared_path_fact_matches_the_actual_collector` 가 그 선언을 **같은 파일의**
실제 코드와 대조하므로, 빈티지를 배선하면 red 가 되어 선언을 함께 고치게 한다.

★예전에는 그 선언이 `regime_axes.AXIS_PATH_USES_VINTAGE` 였다★ — 사실이 있는 곳
(수집기)과 선언이 있는 곳이 달라 갈라지기 쉬웠다. 지금은 수집기 쪽에 하나만 두고
`regime_axes._path_uses_vintage()` 가 그것과 **관측된 빈티지 유무**를 함께 본다.
"""

from __future__ import annotations

import os
import pathlib

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.regime_axes import (  # noqa: E402
    AXES,
    BLOCKED_BY_PATH,
    BLOCKED_BY_SOURCE,
    REVISION_MANAGED,
    REVISION_UNMANAGED,
    axis_revision_status,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ══════════════════════════════════════════════════════════════════════════
# 1) 판정이 **계열에서** 나온다
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("market", sorted(AXES))
def test_every_axis_series_is_accounted_for(market):
    """축을 이루는 계열이 **하나도 빠짐없이** 판정에 들어간다.

    빠진 계열은 보이지 않는 개정 편향이다 — 그 계열이 ECOS 여도 라벨은 managed 가 된다.
    """
    g_def, i_def = AXES[market]
    expected = [k for k, *_ in g_def] + [k for k, *_ in i_def]
    got = [r["key"] for r in axis_revision_status(market)["series"]]
    assert got == expected


@pytest.mark.parametrize("market", sorted(AXES))
def test_each_series_declares_provider_and_vintage_and_why_blocked(market):
    for r in axis_revision_status(market)["series"]:
        assert r["axis"] in ("growth", "inflation")
        assert isinstance(r["source_has_vintage"], bool)
        assert r["blocked_by"] in (None, BLOCKED_BY_SOURCE, BLOCKED_BY_PATH)
        # ★막혔는데 이유가 없거나, 안 막혔는데 이유가 있으면 안 된다★
        if r["blocked_by"] is None:
            from src.engine.regime_axes import _path_uses_vintage
            assert r["source_has_vintage"] and _path_uses_vintage(r["key"])
        if r["blocked_by"] == BLOCKED_BY_SOURCE:
            assert r["source_has_vintage"] is False


def test_kr_axis_is_blocked_permanently_by_ecos():
    """★영구 차단★ — 한국 계열은 제공자가 빈티지를 주지 않는다."""
    st = axis_revision_status("kr")
    assert st["revision_bias"] == REVISION_UNMANAGED
    assert set(st["blocked_permanently"]) >= {"KR_CPI", "KR_IP", "KR_LEADING_CYCLE"}


def test_us_axis_is_blocked_only_by_the_collection_path():
    """★고칠 수 있는 차단★ — 미국 계열은 전부 FRED 라 소스에 빈티지가 있다.

    이 구분이 이 모듈의 존재 이유다. 전역 상수는 kr 과 us 를 똑같이 unmanaged 로
    적었고, 그래서 "수집기만 고치면 되는" 축이 있다는 사실이 보이지 않았다.
    """
    st = axis_revision_status("us")
    assert st["blocked_permanently"] == [], "미국 축에 영구 차단 계열이 생겼다"
    assert len(st["blocked_by_path"]) == 6
    assert st["revision_bias"] == REVISION_UNMANAGED, \
        "소스에 빈티지가 있다고 managed 로 올리면 과대주장이다"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★두 사실이 모두 참일 때만 managed★
# ══════════════════════════════════════════════════════════════════════════
def test_source_vintage_alone_does_not_make_it_managed():
    """레지스트리만 보고 판정하면 과대주장 — 현재 상태가 그 반례다."""
    st = axis_revision_status("us")
    assert all(r["source_has_vintage"] for r in st["series"])
    assert st["path_uses_vintage"] is False
    assert st["revision_bias"] == REVISION_UNMANAGED


def test_managed_requires_the_path_too(monkeypatch):
    """★짝★ 경로가 빈티지를 쓰면 미국 축은 `managed` 가 **되어야** 한다.

    이것이 없으면 "언제나 unmanaged 를 반환" 하는 구현도 위 테스트를 통과한다.
    """
    import src.engine.regime_axes as ra
    # ★두 사실을 다 켜야 managed 다★ — 하나만으로는 거짓 "PIT 통과" 가 된다.
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", True)
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: True)
    us = ra.axis_revision_status("us")
    assert us["revision_bias"] == REVISION_MANAGED
    assert us["blocked_by_path"] == []
    # 한국 축은 경로를 고쳐도 **여전히** 막혀 있다 — 소스의 한계다
    kr = ra.axis_revision_status("kr")
    assert kr["revision_bias"] == REVISION_UNMANAGED
    assert kr["blocked_permanently"]


def _calls_vintage(src: str) -> bool:
    """소스가 빈티지 경로를 **실제로 부르는가**. ★코드 토큰만 본다★

    주석·문자열(독스트링 포함)은 걷어낸다 — 설명은 배선이 아니다.
    """
    import io as _io
    import tokenize

    try:
        toks = list(tokenize.generate_tokens(_io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return False
    for tok in toks:
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        if tok.string in ("pit_macro", "observations_as_of"):
            return True
    return False


def test_declared_path_fact_matches_the_actual_collector():
    """★선언과 현실의 대조★

    `COLLECTOR_READS_VINTAGE` 는 사람이 적은 값이라 코드가 바뀌면 조용히 거짓이 된다.
    수집기가 빈티지 조회(`pit_macro`)를 부르는지 **같은 파일의 소스에서** 확인해
    선언과 맞춘다. 빈티지를 배선하면 이 테스트가 red 가 되어 선언을 함께 고치게 한다.

    ★선언과 사실이 같은 파일에 있다★ — 예전에는 선언이 `regime_axes` 에, 사실이
    `macro_collector` 에 있어 둘이 갈라지기 쉬웠다.

    ★산문이 아니라 코드 토큰만 본다★ 예전에는 파일 전체를 `in` 으로 훑었다. 그러다
    수집기 독스트링이 *"`pit_macro` 가 같은 이유로 frequency 를 보내지 않는다"* 라고
    **설명**하자 거짓 양성이 났다 — 배선이 없는데 있다고 보고했다. 설명은 얼마든지
    할 수 있어야 하므로, 주석·문자열을 걷어내고 식별자에서만 찾는다.
    """
    from src.services.macro_collector import COLLECTOR_READS_VINTAGE

    src = (_ROOT / "src" / "services" / "macro_collector.py").read_text(encoding="utf-8")
    assert _calls_vintage(src) == COLLECTOR_READS_VINTAGE, (
        f"수집기의 빈티지 사용({_calls_vintage(src)})과 "
        f"선언({COLLECTOR_READS_VINTAGE})이 어긋난다 — "
        f"`macro_collector.COLLECTOR_READS_VINTAGE` 를 고칠 것")


def test_prose_about_the_vintage_path_is_not_mistaken_for_wiring():
    """★짝★ 독스트링이 `pit_macro` 를 언급해도 배선으로 세지 않는다."""
    assert not _calls_vintage('"""`pit_macro` 를 설명하는 독스트링."""\nx = 1\n')
    assert not _calls_vintage("# pit_macro 를 언급하는 주석\nx = 1\n")


def test_real_vintage_wiring_is_still_detected():
    """★짝의 짝★ 실제 import 는 반드시 잡는다 — 아니면 가드가 공허해진다."""
    assert _calls_vintage("from src.data.pit_macro import fetch_observations\n")
    assert _calls_vintage("obs = observations_as_of(sid, day)\n")


def test_unregistered_series_is_treated_as_no_vintage(monkeypatch):
    """★등록을 빠뜨린 계열이 조용히 적격이 되지 않는다★"""
    import src.engine.regime_axes as ra
    monkeypatch.setitem(ra.AXES, "probe",
                        ([("NOT_A_REAL_SERIES", "level", 1, 1.0)],
                         [("CPIAUCSL", "level", 1, 1.0)]))
    st = ra.axis_revision_status("probe")
    row = next(r for r in st["series"] if r["key"] == "NOT_A_REAL_SERIES")
    assert row["registered"] is False
    assert row["source_has_vintage"] is False
    assert row["blocked_by"] == BLOCKED_BY_SOURCE
    assert "NOT_A_REAL_SERIES" in st["blocked_permanently"]


# ══════════════════════════════════════════════════════════════════════════
# 3) 라우트가 이 판정을 **그대로** 싣는다 (판정이 두 곳에 생기지 않는다)
# ══════════════════════════════════════════════════════════════════════════
def test_pit_block_reports_the_same_verdict_as_the_axis_module():
    from src.api.allocation_routes import _PIT_MARKET, _pit_block
    pit = _pit_block("live")
    rev = axis_revision_status(_PIT_MARKET)
    assert pit["revision_bias"] == rev["revision_bias"]
    d = pit["revision_detail"]
    assert d["blocked_permanently"] == rev["blocked_permanently"]
    assert d["blocked_by_path"] == rev["blocked_by_path"]
    assert d["path_uses_vintage"] == rev["path_uses_vintage"]
    assert d["market"] == _PIT_MARKET


def test_pit_block_does_not_re_decide_the_verdict(monkeypatch):
    """★핵심 가드★ 라우트가 라벨을 **다시 정하지 않는다**.

    앞의 비교 테스트만으로는 부족하다 — 지금은 참값이 `unmanaged` 라서, 라우트가
    `"unmanaged"` 를 **상수로 박아도** 두 값이 일치해 통과한다(실제로 그 변이가
    살아남았다). 판정을 뒤집어 놓고 라우트가 따라오는지 본다.
    """
    import src.api.allocation_routes as ar
    monkeypatch.setattr(ar, "axis_revision_status", None, raising=False)

    def fake(market: str = "kr") -> dict:
        return {"market": market, "revision_bias": REVISION_MANAGED,
                "path_uses_vintage": True, "series": [],
                "blocked_permanently": [], "blocked_by_path": [],
                "note": "탐침"}

    import src.engine.regime_axes as ra
    monkeypatch.setattr(ra, "axis_revision_status", fake)
    pit = ar._pit_block("live")
    assert pit["revision_bias"] == REVISION_MANAGED, \
        "축 모듈이 managed 라는데 라우트가 따라오지 않는다 — 상수를 박고 있다"
    assert pit["revision_detail"]["path_uses_vintage"] is True


def test_pit_block_keeps_the_three_independent_fields():
    """PIT 3필드 계약은 그대로 — 새 필드가 기존 계약을 대체하지 않는다."""
    from src.api.allocation_routes import _pit_block
    pit = _pit_block("live")
    assert set(pit) >= {"look_ahead_free", "publication_lag", "revision_bias",
                        "revision_detail", "mode", "note"}
    assert pit["look_ahead_free"] is True
    assert pit["publication_lag"] == "unspecified"
    assert pit["revision_bias"] == REVISION_UNMANAGED


def test_pit_note_names_the_blocking_series():
    """★라벨만 내면 무엇을 고쳐야 하는지 알 수 없다★"""
    from src.api.allocation_routes import _pit_block
    note = _pit_block("live")["note"]
    assert "KR_CPI" in note or "영구" in note
    assert "공표지연" in note


def test_pit_block_follows_the_market_it_is_given():
    """가드 — 시장을 무시하고 상수를 반환하면 두 시장이 같은 답을 낸다."""
    from src.api.allocation_routes import _pit_block
    kr = _pit_block("live", "kr")["revision_detail"]
    us = _pit_block("live", "us")["revision_detail"]
    assert kr["blocked_permanently"] != us["blocked_permanently"]
    assert us["blocked_permanently"] == []
