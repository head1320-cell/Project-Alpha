"""정준 분류 계약 — ★미배정이 조용히 사라지지 않는다★
==============================================================================
계약: `docs/specs/2026-08-26-exposure-taxonomy-contract.md`

## 이 파일이 막는 것

기존 후보(`constrained_opt.sector_groups_for`)는 두 겹으로 조용했다:

    except Exception:            return {}          # ① 실패 → 통째로 사라짐
    return {t: assign[t] for t in names if t in assign}  # ② 부분 배정

②가 더 위험하다 — 아무 신호도 나지 않고, "EQ − FI 스프레드" 가 실제로는
"EQ 일부 − FI 일부" 가 된다. 그래서 이 계약의 핵심은 **빠진 것이 반드시
두 번째 반환값으로 나온다**는 것이다.

## ★반대 방향의 함정도 막는다★

"상장 개별주는 주식" 은 참이지만 **그것이 개별주라는 확인**이 필요하다. KIS master
플래그가 없으면(개발 환경의 기본) ETF 인지 알 수 없고, 그때 주식으로 추정하면
지수형·레버리지 상품이 조용히 EQUITY 가 된다. 규칙 배정은 **적극적 증거**를
요구해야 한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.exposure_taxonomy import (  # noqa: E402
    _SPECS,  # noqa: E402
    SOURCE_CURATED,
    SOURCE_RULE_LISTED_EQUITY,
    TAXONOMY_AS_OF,
    TAXONOMY_VERSION,
    UNASSIGNED_DIRECTIONAL,
    UNASSIGNED_NO_MAPPING,
    UNASSIGNED_NO_MASTER_FLAGS,
    UNASSIGNED_UNREGISTERED_ETF,
    AssetClass,
    TaxonomyIncomplete,
    asset_class_of,
    classify,
    coverage,
    exposures_of,
    known_exposures,
    registered_tickers,
    require_complete,
)


# ══════════════════════════════════════════════════════════════════════════
# 1) 레지스트리 자체의 불변식
# ══════════════════════════════════════════════════════════════════════════
def test_every_spec_is_complete():
    assert _SPECS, "레지스트리가 비어 있다"
    for s in _SPECS:
        assert s.instrument_id and s.ticker and s.name
        assert isinstance(s.asset_class, AssetClass)
        assert s.exposures, f"{s.ticker} 에 노출이 하나도 없다"
        assert s.listing in ("kr", "us")
        assert s.as_of == TAXONOMY_AS_OF and s.version == TAXONOMY_VERSION
        assert s.source == SOURCE_CURATED


def test_ids_and_tickers_are_unique():
    """★안정 ID★ — 중복이 있으면 인덱스가 조용히 하나를 덮는다."""
    ids = [s.instrument_id for s in _SPECS]
    ticks = [s.ticker for s in _SPECS]
    assert len(set(ids)) == len(ids)
    assert len(set(ticks)) == len(ticks)


def test_instrument_id_is_not_the_bare_ticker():
    """티커는 재사용·변경된다 — ID 는 상장 시장을 포함해 안정적이어야 한다."""
    for s in _SPECS:
        assert s.instrument_id != s.ticker
        assert s.instrument_id.startswith(("KR:", "US:"))


def test_exposure_vocabulary_is_a_subset_of_the_factor_model(recwarn):
    """★어휘 정합성 가드★ — 새 노출 어휘를 만들지 않는다.

    `instrument_selector` 는 독스트링으로 같은 어휘를 쓴다고 선언했지만 실제
    일치는 **4/13** 이었다(감사). 선언이 아니라 테스트로 묶는다.
    """
    from src.engine.factor_exposure import FACTORS
    unknown = set(known_exposures()) - set(FACTORS)
    assert not unknown, (
        f"팩터 모형에 없는 노출 이름을 만들었다: {sorted(unknown)} — "
        f"`factor_exposure.FACTOR_PROXIES` 에 먼저 추가하거나 이름을 맞출 것")


def test_registry_spans_at_least_four_asset_classes():
    """게이트 조건 5 와 직결 — 자산군이 하나뿐이면 상대 뷰가 성립하지 않는다."""
    classes = {s.asset_class for s in _SPECS}
    assert len(classes) >= 4, f"자산군이 {len(classes)}개뿐이다: {classes}"


def test_korean_listings_span_three_asset_classes():
    """★감사 정정을 고정한다★

    처음에는 `ticker_universe` 의 "Korea ETF" 8종만 보고 "국내는 주식뿐" 이라고
    보고했다. **틀렸다** — `stock_master.ETF_NAMES`(40종, 체크인)에 채권 3종과
    원자재 2종이 있다. 국내 상장만으로 EQUITY·RATES·COMMODITY 셋이 나온다.

    이 테스트가 red 가 되면 국내 자산군 구성이 바뀐 것이고, 게이트 조건 5 의
    판단(자산군 4개+)도 함께 갱신해야 한다.
    """
    kr = {s.asset_class for s in _SPECS if s.listing == "kr"}
    assert kr == {AssetClass.EQUITY, AssetClass.RATES, AssetClass.COMMODITY}, (
        f"국내 상장 자산군 구성이 바뀌었다: {kr} — 게이트 조건 5 재평가 필요")


def test_korean_bond_and_commodity_etfs_are_registered():
    """★놓쳤던 상품을 이름으로 못 박는다★ 다시 빠지면 red 가 된다."""
    kr_rates = {s.ticker for s in _SPECS
                if s.listing == "kr" and s.asset_class is AssetClass.RATES}
    kr_comm = {s.ticker for s in _SPECS
               if s.listing == "kr" and s.asset_class is AssetClass.COMMODITY}
    assert kr_rates == {"273130", "153130", "214980"}
    assert kr_comm == {"132030", "130680"}


# ══════════════════════════════════════════════════════════════════════════
# 2) ★미배정도 결과다★ — `None` 도 조용한 누락도 없다
# ══════════════════════════════════════════════════════════════════════════
def test_classify_always_returns_a_result():
    for t in ("069500", "TLT", "114800", "005930", "ZZZZZZ", ""):
        c = classify(t)
        assert c is not None and c.ticker == str(t).strip()
        assert isinstance(c.assigned, bool)


def test_unassigned_always_carries_a_reason_and_a_note():
    """★사유 없는 미배정은 블랙박스다★"""
    for t in ("ZZZZZZ", "114800", "005930"):
        c = classify(t)
        assert c.assigned is False
        assert c.unassigned_reason, f"{t} 미배정에 사유가 없다"
        assert c.unassigned_note, f"{t} 미배정에 설명이 없다"
        assert c.asset_class is None and c.exposures == ()


def test_assigned_carries_class_exposures_and_provenance():
    c = classify("HYG")
    assert c.assigned and c.asset_class is AssetClass.CREDIT
    assert set(c.exposures) == {"credit", "duration"}
    assert c.instrument_id == "US:HYG" and c.listing == "us"
    assert c.source == SOURCE_CURATED
    assert c.as_of == TAXONOMY_AS_OF and c.version == TAXONOMY_VERSION


def test_asset_class_of_reports_what_it_dropped():
    """★핵심 가드★ 빠진 것이 **두 번째 반환값**으로 나온다."""
    groups, missing = asset_class_of(["069500", "TLT", "ZZZZZZ", "114800"])
    assert groups == {"069500": "EQUITY", "TLT": "RATES"}
    assert {m["ticker"] for m in missing} == {"ZZZZZZ", "114800"}
    assert all(m["reason"] and m["note"] for m in missing)


def test_all_unknown_input_is_not_a_silent_empty_map():
    """★`sector_groups_for` 의 결함 그 자체★ — 전부 모르면 `{}` 지만 **조용하지 않다**."""
    groups, missing = asset_class_of(["AAA", "BBB", "CCC"])
    assert groups == {}
    assert len(missing) == 3, "전부 빠졌는데 미배정 목록이 비어 있다"


def test_empty_universe_is_not_an_error():
    groups, missing = asset_class_of([])
    assert groups == {} and missing == []


# ══════════════════════════════════════════════════════════════════════════
# 3) ★규칙 배정은 적극적 증거를 요구한다★
# ══════════════════════════════════════════════════════════════════════════
def test_listed_equity_is_not_assumed_without_master_flags():
    """★확인할 수 없으면 배정하지 않는다★

    이 환경에는 `master_flags_cache.json` 이 없다(감사에서 확인). 그 상태에서
    개별주를 EQUITY 로 추정하면 같은 경로로 지수형·레버리지 상품도 EQUITY 가 된다.
    """
    c = classify("005930")          # 삼성전자 — STOCK_MASTER 에는 있다
    assert c.assigned is False
    assert c.unassigned_reason == UNASSIGNED_NO_MASTER_FLAGS


def test_rule_assigns_equity_when_flags_confirm_it_is_not_an_etf(monkeypatch):
    """★짝★ 증거가 있으면 배정한다 — 아니면 위 테스트가 '늘 거부' 로도 통과한다."""
    import src.data.stock_master as sm
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {"005930": {"is_etf": False}})
    c = classify("005930")
    assert c.assigned is True
    assert c.asset_class is AssetClass.EQUITY
    assert c.exposures == ("equity",)
    assert c.source == SOURCE_RULE_LISTED_EQUITY, "규칙 배정임이 값으로 남아야 한다"


def test_every_checked_in_etf_is_registered_or_excluded():
    """★커버리지 보증★ `ETF_NAMES` 에 있는 상품은 하나도 미분류로 남지 않는다.

    새 ETF 를 `ETF_NAMES` 에 추가하면서 여기 등록을 빠뜨리면 red 가 된다 —
    그 종목은 조용히 `etf_not_registered` 로 떨어져 유니버스에서 사라졌을 것이다.
    """
    from src.data.exposure_taxonomy import _BY_TICKER, _EXCLUDED
    from src.data.stock_master import ETF_NAMES
    missing = set(ETF_NAMES) - set(_BY_TICKER) - set(_EXCLUDED)
    assert not missing, (
        f"체크인된 ETF 인데 분류도 제외도 안 된 종목: {sorted(missing)}")


def test_rule_refuses_an_etf_using_checked_in_evidence(monkeypatch):
    """★체크인 증거가 캐시보다 먼저다★

    `ETF_NAMES` 에 있으면 플래그가 "개별주" 라고 우겨도 개별주가 아니다.
    현재 레지스트리가 `ETF_NAMES` 를 전부 덮으므로 합성 종목으로 그 분기를 **강제**한다
    (실제 종목으로 하려다 후보가 없어 `StopIteration` 이 났다 — 공허할 뻔했다).
    """
    import src.data.stock_master as sm
    fake = "999999"
    monkeypatch.setitem(sm.ETF_NAMES, fake, "가상 ETF")
    monkeypatch.setitem(sm.STOCK_MASTER, fake, "가상 ETF")
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {fake: {"is_etf": False}})
    c = classify(fake)
    assert c.assigned is False, "ETF 인데 개별주로 배정됐다"
    assert c.unassigned_reason == UNASSIGNED_UNREGISTERED_ETF


def test_master_flag_path_still_works_for_a_non_etf(monkeypatch):
    """짝 — `ETF_NAMES` 가드가 **전부를** 막아버리지 않는다."""
    import src.data.stock_master as sm
    fake = "999998"
    monkeypatch.setitem(sm.STOCK_MASTER, fake, "가상 개별주")
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {fake: {"is_etf": False}})
    c = classify(fake)
    assert c.assigned is True and c.source == SOURCE_RULE_LISTED_EQUITY


def test_unknown_ticker_is_no_mapping_not_a_crash():
    c = classify("NOT_A_TICKER")
    assert c.assigned is False and c.unassigned_reason == UNASSIGNED_NO_MAPPING


# ══════════════════════════════════════════════════════════════════════════
# 4) ★레버리지·인버스는 자산군에 넣지 않는다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("code", ["114800", "252670", "122630"])
def test_directional_products_are_refused_with_a_reason(code):
    """`Σw=1` 에서 인버스를 EQUITY 로 세면 그룹 상한이 노출을 **반대로** 계산한다."""
    c = classify(code)
    assert c.assigned is False
    assert c.unassigned_reason == UNASSIGNED_DIRECTIONAL
    assert "인버스" in (c.unassigned_note or "") or "레버리지" in (c.unassigned_note or "")


def test_directional_refusal_beats_the_equity_rule(monkeypatch):
    """★순서 가드★ 플래그가 '개별주' 라고 해도 인버스는 배정되지 않는다."""
    import src.data.stock_master as sm
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {"114800": {"is_etf": False}})
    assert classify("114800").assigned is False


# ══════════════════════════════════════════════════════════════════════════
# 5) 전수 배정 관문
# ══════════════════════════════════════════════════════════════════════════
def test_require_complete_returns_the_map_when_everything_is_classified():
    got = require_complete(["069500", "TLT", "GLD"])
    assert got == {"069500": "EQUITY", "TLT": "RATES", "GLD": "COMMODITY"}


def test_require_complete_raises_and_names_the_missing():
    with pytest.raises(TaxonomyIncomplete) as e:
        require_complete(["069500", "ZZZZZZ"])
    assert "ZZZZZZ" in str(e.value)
    assert [m["ticker"] for m in e.value.unassigned] == ["ZZZZZZ"]


def test_require_complete_summarises_when_many_are_missing():
    with pytest.raises(TaxonomyIncomplete) as e:
        require_complete([f"X{i}" for i in range(9)])
    assert len(e.value.unassigned) == 9
    assert "외 4건" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════
# 6) 노출 조회 — ★빈 튜플과 '모른다' 를 구분한다★
# ══════════════════════════════════════════════════════════════════════════
def test_exposures_of_returns_none_for_unassigned_not_an_empty_tuple():
    assert exposures_of("ZZZZZZ") is None
    assert exposures_of("TLT") == ("duration",)


# ══════════════════════════════════════════════════════════════════════════
# 7) 커버리지 블록 — 빠진 분류가 화면에 남는다
# ══════════════════════════════════════════════════════════════════════════
def test_coverage_counts_add_up_and_name_the_gaps():
    u = ["069500", "TLT", "HYG", "GLD", "VNQ", "114800", "ZZZZZZ"]
    cov = coverage(u)
    assert cov["universe"] == len(u)
    assert cov["classified"] + cov["unassigned"] == cov["universe"]
    assert set(cov["unassigned_tickers"]) == {"114800", "ZZZZZZ"}
    assert cov["reasons"][UNASSIGNED_DIRECTIONAL] == 1
    assert cov["reasons"][UNASSIGNED_NO_MAPPING] == 1
    assert cov["distinct_asset_classes"] == len(cov["by_asset_class"])
    assert cov["version"] == TAXONOMY_VERSION and cov["as_of"] == TAXONOMY_AS_OF


def test_coverage_records_whether_a_class_came_from_a_rule(monkeypatch):
    """사람이 고른 것과 규칙이 고른 것이 섞이면 그 비율이 보여야 한다."""
    import src.data.stock_master as sm
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {"005930": {"is_etf": False}})
    cov = coverage(["069500", "005930"])
    assert cov["by_source"] == {SOURCE_CURATED: 1, SOURCE_RULE_LISTED_EQUITY: 1}


# ══════════════════════════════════════════════════════════════════════════
# 8) 결정성
# ══════════════════════════════════════════════════════════════════════════
def test_classification_is_deterministic():
    """외부 호출 실패가 분류를 바꾸지 않는다 — 같은 입력이면 같은 출력."""
    u = ["069500", "TLT", "ZZZZZZ", "005930"]
    assert coverage(u) == coverage(u)
    a, _ = asset_class_of(u)
    b, _ = asset_class_of(u)
    assert a == b


def test_registered_tickers_is_sorted_and_matches_the_registry():
    assert list(registered_tickers()) == sorted(s.ticker for s in _SPECS)
