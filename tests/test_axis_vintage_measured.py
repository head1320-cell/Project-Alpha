"""국면 축 빈티지 — ★선언을 측정으로, 단 **두 사실**을 함께 잰다★
==============================================================================
우선순위 P2 · 선행 `ac938c4`(판정 배선) · `0ffe083`(관측 스토어) · ALFRED 백필

## 왜 상수를 없애나

`AXIS_PATH_USES_VINTAGE = False` 는 **사람이 유지하는 선언**이었다. 그런 값은
코드가 바뀌면 조용히 거짓이 된다 — 이 저장소가 `verified_live` 에서 이미 겪은 일이다.

## ★그런데 스토어만 보면 안 된다★

`ac938c4` 의 HISTORY 가 이유를 적어 뒀다:

> 레지스트리만 보고 배선했다면 미국 축을 `managed` 로 올렸을 것이다 — **현재
> 개정본으로 과거를 채점하면서 "PIT 통과" 라고 표시하는 상태.**

`macro_collector` 에는 `pit_macro`·`vintage` 참조가 **하나도 없다**. 스토어에
빈티지가 아무리 쌓여도 국면 축은 여전히 **현재값**을 읽는다. 그러므로 판정은
세 사실의 논리곱이다:

| | 사실 | 어디서 |
|---|---|---|
| ⑴ | 제공자가 빈티지를 주는가 | `source_registry` (기존) |
| ⑵ | **수집 경로가 그것을 가져오는가** | `macro_collector.COLLECTOR_READS_VINTAGE` |
| ⑶ | 그 계열에 실제 빈티지가 있는가 | `macro_observation_store.coverage()` ★관측★ |

오늘은 ⑵⑶ 이 거짓이라 **결과가 이전과 동일**하다 — 정책 변경이 아니다.

## 짝 검증

V2 가 이 파일의 핵심이다 — ⑶만 보고 판정하는 구현을 배제한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.engine.regime_axes as ra  # noqa: E402

US_AXIS_KEYS = ("INDPRO", "PAYEMS", "UNRATE", "GDPC1", "CPIAUCSL", "T10YIE")


def _by_blocked(market: str) -> dict:
    st = ra.axis_revision_status(market)
    out: dict = {}
    for r in st["series"]:
        out.setdefault(r["blocked_by"], []).append(r["key"])
    return {"bias": st["revision_bias"], **out}


@pytest.fixture
def no_vintage(monkeypatch):
    """관측 스토어에 빈티지가 없다 — ★오늘의 실제 상태★"""
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: False)
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", False)


# ══════════════════════════════════════════════════════════════════════════
# 1) ★오늘 결과가 이전과 동일하다★ (정책 변경 아님)
# ══════════════════════════════════════════════════════════════════════════
def test_todays_output_is_unchanged():
    """V1 — 상수를 없앴는데 출력은 그대로. ★이것이 무해함의 증거다.★

    기준: `unmanaged` · KR = ECOS 4 `source` + FRED 1 `path` · US = FRED 6 `path`.
    """
    kr, us = _by_blocked("kr"), _by_blocked("us")
    assert kr["bias"] == "unmanaged" and us["bias"] == "unmanaged"
    assert len(kr.get("source", [])) == 4, kr
    assert len(kr.get("path", [])) == 1, kr
    assert sorted(us.get("path", [])) == sorted(US_AXIS_KEYS), us
    assert not us.get("source"), "FRED 는 제공자 차단이 아니다"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★핵심 짝 — 스토어에 있어도 경로가 안 읽으면 managed 가 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_stored_vintages_alone_do_not_make_it_managed(monkeypatch):
    """V2 — ★`ac938c4` 가 막은 거짓 "PIT 통과" 의 재발을 막는다★

    빈티지가 스토어에 가득 차 있어도, 수집기가 그것을 읽지 않으면 국면 축은
    현재 개정본으로 과거를 채점한다. 그 상태를 `managed` 라고 부르면 백테스트가
    미래를 훔쳐보면서 "PIT 통과" 배지를 단다.
    """
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: True)   # ⑶ 참
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", False)  # ⑵ 거짓
    us = _by_blocked("us")
    assert us["bias"] == "unmanaged", "스토어만 보고 managed 로 올렸다"
    assert sorted(us.get("path", [])) == sorted(US_AXIS_KEYS)


def test_a_reading_path_alone_does_not_make_it_managed(monkeypatch):
    """V5 짝 — 반대도 마찬가지. 경로가 있어도 **데이터가 없으면** 못 쓴다."""
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: False)  # ⑶ 거짓
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", True)  # ⑵ 참
    assert _by_blocked("us")["bias"] == "unmanaged"


def test_both_facts_true_makes_it_managed(monkeypatch):
    """V3 — 둘 다 참이면 풀린다. "항상 차단" 구현을 배제한다."""
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: True)
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", True)
    us = _by_blocked("us")
    assert us["bias"] == "managed", us
    assert not us.get("path") and not us.get("source")


# ══════════════════════════════════════════════════════════════════════════
# 3) 계열별 판정 · 제공자 한계는 영구
# ══════════════════════════════════════════════════════════════════════════
def test_the_judgement_is_per_series(monkeypatch):
    """V4 — 한 계열만 빈티지가 있으면 **그 계열만** 풀린다.

    일괄 판정이면 하나가 다른 다섯을 끌고 올라간다.
    """
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: k == "INDPRO")
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", True)
    us = _by_blocked("us")
    assert us["bias"] == "unmanaged"
    assert "INDPRO" not in us.get("path", []), "풀린 계열이 아직 막혀 있다"
    assert len(us.get("path", [])) == len(US_AXIS_KEYS) - 1, us


def test_ecos_stays_blocked_by_source_forever(monkeypatch):
    """V5 — ★제공자 한계는 우리가 못 고친다★

    ECOS 에 빈티지 엔드포인트가 없다. 스토어에 무엇이 있든, 경로가 무엇을 하든
    `source` 차단이어야 한다 — 아니면 없는 빈티지를 있다고 말하는 것이다.
    """
    monkeypatch.setattr(ra, "_series_has_vintage", lambda k: True)
    monkeypatch.setattr("src.services.macro_collector.COLLECTOR_READS_VINTAGE", True)
    kr = _by_blocked("kr")
    assert len(kr.get("source", [])) == 4, f"ECOS 가 풀렸다: {kr}"
    assert kr["bias"] == "unmanaged"


# ══════════════════════════════════════════════════════════════════════════
# 4) 선언이 두 곳에 남지 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_the_hardcoded_constant_is_gone():
    """V6 — `regime_axes` 에 손으로 유지하는 선언이 남아 있으면 안 된다.

    사실은 **수집기 쪽**(`COLLECTOR_READS_VINTAGE`)에 하나만 둔다. 두 곳에 두면
    갈라지고, 갈라진 선언은 틀린 선언이다.
    """
    assert not hasattr(ra, "AXIS_PATH_USES_VINTAGE"), \
        "하드코딩 상수가 아직 있다 — 선언이 두 곳에 남았다"


def test_path_flag_is_read_from_the_collector():
    """V6 짝 — 그 사실은 수집기에 하나만 있다.

    ★이 테스트는 뒤집혔다★ 예전에는 `is False` 를 못 박고 *"수집기가 빈티지를
    읽는다고 선언됐다 — 실제로 배선됐는가?"* 라고 물었다. **배선됐다** —
    `collect_all()` 이 `_from_vintage_store` 로 관측 스토어를 as-of 조회한다
    (Track B4, 별도 승인). 그래서 이제 얼어붙은 값이 아니라 **선언과 코드가
    일치하는가**를 본다. 그 대조는 `test_axis_revision_status.py` 가 `tokenize`
    로 수행하므로, 여기서는 ★막는 것이 이제 ⑶ 이라는 사실★ 을 못 박는다.
    """
    from src.services.macro_collector import COLLECTOR_READS_VINTAGE

    assert COLLECTOR_READS_VINTAGE is True, "배선이 사라졌다면 선언도 내려야 한다"


def test_the_remaining_block_is_the_observed_one(no_vintage):
    """★승인의 범위★ ⑵ 가 열려도 ⑶ 이 관측으로 막는다.

    빈티지 행이 0건인 오늘, 축은 여전히 `unmanaged` 여야 한다 — 승인은 "데이터
    없이도 PIT 라고 하자" 가 아니라 "빈티지가 실제로 쌓이면 인정한다" 였다.
    """
    st = ra.axis_revision_status("us")
    assert st["revision_bias"] == "unmanaged"
    assert st["path_uses_vintage"] is False
    assert all(r["blocked_by"] == "path" for r in st["series"])


def test_status_still_reports_the_path_fact(no_vintage):
    """V1 보강 — 반환 모양이 그대로다(`path_uses_vintage` 키가 살아 있다)."""
    st = ra.axis_revision_status("us")
    assert st["path_uses_vintage"] is False
    assert set(st) >= {"market", "revision_bias", "path_uses_vintage", "series",
                       "blocked_permanently", "blocked_by_path", "note"}
