"""신규 데이터 소스 — 미검증을 일급으로 (M1-I)
==============================================================================
ECOS 3지표 · KRX 4엔드포인트 · Naver DataLab · Google Trends 를 붙였다. 그런데 이
환경에서는 다섯 호스트가 전부 프록시 403 이라 **실호출로 확인할 수 없다.**

★그래서 이 파일이 지키는 것은 "값이 맞다" 가 아니라 "모른다는 것을 안다" 이다★
  1. 미검증 소스는 **mock 으로 채워지지 않는다** — 기존 지표의 mock 은 그대로.
  2. 사유 없는 미가용이 없다.
  3. 파서는 공식 응답 모양(픽스처)으로 검증한다 — 네트워크·실키 불필요.
     (`tests/test_krx_ingest.py` 가 세운 관례. 실수신은 `verify_connection.py`.)
  4. **필드를 못 찾은 행은 버린다** — 0 으로 채우면 "값이 0" 과 구분할 수 없다.
"""

from __future__ import annotations

import pytest

from src.data import source_registry as sr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. 레지스트리 — 미검증이 일급 상태다
# ═══════════════════════════════════════════════════════════════════════════════


def test_every_new_source_is_declared_unverified_with_a_reason():
    """★사유 없는 미가용은 만들지 않는다★"""
    specs = sr.all_specs()
    assert len(specs) >= 10, "신규 소스가 예상보다 적다"
    for s in specs:
        assert s.note, f"{s.key}: 왜 미검증인지 적혀 있지 않다"
        assert s.verified_live is False, (
            f"{s.key}: 실호출로 확인한 적이 없는데 verified_live=True 다 — "
            "이 플래그는 verify_connection 결과를 본 사람이 올린다")


def test_an_unverified_source_reports_no_value_even_if_one_is_passed():
    """★검증되지 않은 코드가 만든 값은 실데이터인지 mock 인지 구분할 수 없다★"""
    st = sr.status("VKOSPI", value=17.3, as_of="2026-08-01")
    assert st["available"] is False
    assert st["value"] is None, "미검증인데 값을 냈다"
    assert "미검증" in st["reason"]
    assert st["verified_live"] is False


def test_an_unknown_key_says_so():
    st = sr.status("NO_SUCH_KEY")
    assert st["available"] is False and "레지스트리에 없는" in st["reason"]


def test_the_indicator_block_keeps_keys_that_have_no_value():
    """★키가 사라지면 화면은 '그 지표를 안 본다' 로 읽는다★ (M1-S 계약)"""
    block = sr.indicator_block()
    for key in ("VKOSPI", "KR_M2", "KR_CREDIT_SPREAD", "TRENDS_KR", "TRENDS_GLOBAL"):
        assert key in block, f"{key} 키가 사라졌다"
        assert block[key]["available"] is False
        assert block[key]["reason"]


def test_mock_is_blocked_for_new_sources_but_not_for_existing_ones():
    """★기존 지표의 mock 폴백은 건드리지 않는다★ 그 코드들은 실호출로 검증된 적이
    있고 개발 환경에서 화면이 도는 근거다. 새 소스만 다르게 대우한다."""
    assert sr.new_source_mock_allowed("KR_M2") is False
    assert sr.new_source_mock_allowed("VKOSPI") is False
    # 레지스트리 밖 = 기존 지표 → 기존 동작 유지
    assert sr.new_source_mock_allowed("KR_3Y") is True
    assert sr.new_source_mock_allowed("VIXCLS") is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 수집기 — 새 지표가 mock 으로 채워지지 않는다
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def snap():
    from src.services.macro_collector import MacroCollector
    return MacroCollector().collect_all(use_cache=False)


def test_new_ecos_indicators_stay_unavailable_instead_of_being_mocked(snap):
    """★이것이 이 단계의 핵심 가드다★ 통계표 코드가 틀리면 시리즈가 조용히 빈다.
    mock 이 그 빈 값을 덮으면 코드가 맞았는지 틀렸는지 영원히 알 수 없다."""
    for key in ("KR_M2", "KR_GDP", "KR_CORP3Y"):
        s = snap.series[key]
        assert s.source == "unavailable", f"{key}: 미검증인데 {s.source} 로 채워졌다"
        assert s.values == [] and s.latest is None


def test_existing_indicators_still_get_their_mock(snap):
    """회귀 0 — 기존 지표는 예전과 똑같이 동작한다."""
    for key in ("KR_3Y", "KR_CPI", "VIXCLS"):
        s = snap.series[key]
        assert s.source == "MOCK" and len(s.values) > 0


def test_the_credit_spread_is_not_synthesised_from_one_leg(snap):
    """★한쪽만으로 스프레드를 만들지 않는다★ 지금 KR_CORP3Y 가 미검증이므로
    KR_3Y 가 있어도 스프레드는 나오지 않아야 한다."""
    s = snap.series["KR_CREDIT_SPREAD"]
    assert snap.series["KR_3Y"].values, "전제: 국고3Y 는 있다"
    assert not snap.series["KR_CORP3Y"].values, "전제: 회사채3Y 는 없다"
    assert s.values == [], "원계열 하나가 없는데 스프레드를 만들었다"
    assert s.source == "unavailable"


def test_the_credit_spread_is_computed_when_both_legs_exist():
    """둘 다 있으면 실제로 뺀다 — 계산이 없는 게 아니라 재료가 없는 것이다."""
    from src.services.macro_collector import MacroCollector, MacroSeries

    corp = MacroSeries(indicator="KR_CORP3Y", name="회사채", unit="%", source="BOK",
                       timestamps=["202601", "202602"], values=[4.5, 4.8])
    govt = MacroSeries(indicator="KR_3Y", name="국고", unit="%", source="BOK",
                       timestamps=["202601", "202602"], values=[3.2, 3.3])
    out = MacroCollector()._derive_spread(corp, govt)
    assert out.values == [1.3, 1.5]
    assert out.latest == pytest.approx(1.5)
    assert out.source == "BOK", "원계열 출처를 승격시키면 안 된다"


def test_the_bok_loop_binds_each_stat_code_to_its_own_lambda():
    """★잠재 결함을 직접 잰다 (M1-I)★

    BOK 루프는 `lambda: fetch(stat, item)` 이라 **늦은 바인딩**이었다. 지금은
    `_collect_one` 이 같은 반복 안에서 동기로 부르므로 값이 맞아 살아 있는 버그는
    아니었다 — 그래서 "지금 값이 맞다" 로는 증명이 안 된다. **호출을 지연시켜**
    각 람다가 자기 코드를 들고 있는지 본다.
    """
    from src.services.macro_collector import MacroCollector

    captured: list[tuple] = []
    deferred: list = []

    col = MacroCollector()
    col.bok.fetch_series = lambda s, i: captured.append((s, i)) or ([], [])  # type: ignore[assignment]

    # `_collect_one` 을 가로채 fetcher 를 **모아 두었다가 나중에** 부른다.
    def defer(key, name, unit, fetcher, use_cache, source):
        from src.services.macro_collector import MacroSeries
        deferred.append(fetcher)
        return MacroSeries(indicator=key, name=name, unit=unit,
                           source="unavailable", timestamps=[], values=[])

    col._collect_one = defer  # type: ignore[assignment]
    col.collect_all(use_cache=False)

    for f in deferred:
        f()

    bok_calls = [c for c in captured]
    assert len(bok_calls) >= 8, "BOK 페처가 모이지 않았다"
    assert len(set(bok_calls)) == len(bok_calls), (
        f"지연 호출 시 같은 stat 코드가 반복된다 — 늦은 바인딩이다: {bok_calls}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 파서 — 픽스처로 검증 (네트워크·실키 불필요)
# ═══════════════════════════════════════════════════════════════════════════════


def test_krx_extra_parser_reads_comma_numbers():
    from src.data.krx_client import parse_extra_rows

    rows = [{"BAS_DD": "20260801", "CLSPRC_IDX": "17.32"},
            {"BAS_DD": "20260802", "CLSPRC_IDX": "18.05"}]
    out = parse_extra_rows(rows, "VKOSPI")
    assert [r["date"] for r in out] == ["2026-08-01", "2026-08-02"]
    assert out[0]["value"] == pytest.approx(17.32)

    margin = parse_extra_rows(
        [{"BAS_DD": "20260801", "MGN_BAL_AMT": "18,432,110,000"}], "MARGIN")
    assert margin[0]["value"] == pytest.approx(18_432_110_000)


def test_krx_extra_parser_drops_rows_whose_field_is_missing():
    """★0 으로 채우지 않는다★ 잘못된 필드명으로 만든 0 이 실측치로 읽히면 안 된다."""
    from src.data.krx_client import parse_extra_rows

    out = parse_extra_rows([{"BAS_DD": "20260801", "UNEXPECTED_FIELD": "123"}], "VKOSPI")
    assert out == [], "필드를 못 찾았는데 행을 냈다"


def test_krx_extra_parser_filters_by_name_when_asked():
    from src.data.krx_client import parse_extra_rows

    rows = [{"BAS_DD": "20260801", "IDX_NM": "코스피 200 변동성지수", "CLSPRC_IDX": "17.3"},
            {"BAS_DD": "20260801", "IDX_NM": "다른지수", "CLSPRC_IDX": "99.9"}]
    out = parse_extra_rows(rows, "VKOSPI", name_field="IDX_NM",
                           name_match="코스피 200 변동성지수")
    assert len(out) == 1 and out[0]["value"] == pytest.approx(17.3)


def test_naver_parser_reads_the_official_shape():
    from src.data.naver_datalab import parse_search_response

    out = parse_search_response({
        "startDate": "2026-01-01", "endDate": "2026-06-30", "timeUnit": "month",
        "results": [{"title": "반도체", "keywords": ["반도체", "HBM"],
                     "data": [{"period": "2026-01-01", "ratio": 42.1},
                              {"period": "2026-02-01", "ratio": 100.0}]}],
    })
    assert out["available"] is True
    assert [r["ratio"] for r in out["series"]["반도체"]] == [42.1, 100.0]
    # ★상대 지수라는 사실을 말한다★ 안 적으면 화면이 검색 건수로 읽는다.
    assert "상대 지수" in out["note"]


def test_naver_parser_skips_points_without_a_value():
    from src.data.naver_datalab import parse_search_response

    out = parse_search_response({"results": [
        {"title": "A", "data": [{"period": "2026-01-01", "ratio": None},
                                {"period": "2026-02-01", "ratio": 5.0}]}]})
    assert len(out["series"]["A"]) == 1


def test_google_parser_reads_the_official_shape():
    from src.data.google_trends import parse_timeseries_response

    out = parse_timeseries_response({"timelineData": [
        {"date": "2026-01-01", "values": [{"term": "AI", "value": 73},
                                          {"term": "반도체", "value": 41}]},
        {"date": "2026-02-01", "values": [{"term": "AI", "value": 88}]},
    ]})
    assert out["available"] is True
    assert [r["value"] for r in out["series"]["AI"]] == [73.0, 88.0]
    assert len(out["series"]["반도체"]) == 1
    assert "상대 지수" in out["note"]


def test_google_parser_reports_an_empty_response_instead_of_an_empty_series():
    from src.data.google_trends import parse_timeseries_response

    out = parse_timeseries_response({"timelineData": []})
    assert out["available"] is False and out["reason"]


def test_trend_clients_do_not_call_without_keys(monkeypatch):
    """★키가 없으면 호출하지 않는다★ 실패가 아니라 '시도하지 않았다' 이고,
    그 둘은 사유가 다르다."""
    from src.data.google_trends import GoogleTrendsClient
    from src.data.naver_datalab import NaverDataLabClient

    n = NaverDataLabClient(client_id="", client_secret="")
    assert n.is_configured is False
    out = n.fetch_trends([{"groupName": "A", "keywords": ["A"]}],
                         start="2026-01-01", end="2026-06-30")
    assert out["available"] is False and "호출하지 않았습니다" in out["reason"]

    g = GoogleTrendsClient(api_key="")
    assert g.is_configured is False
    out = g.fetch_trends(["AI"], start="2026-01-01", end="2026-06-30")
    assert out["available"] is False and "호출하지 않았습니다" in out["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 능력 사다리 — 트렌드는 둘 중 하나면 열린다
# ═══════════════════════════════════════════════════════════════════════════════


def test_either_trends_source_opens_the_requirement(monkeypatch):
    from src.engine.capability import probe_all

    for k in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "GOOGLE_TRENDS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert probe_all()["trends_api"]["ok"] is False

    monkeypatch.setenv("GOOGLE_TRENDS_API_KEY", "x")
    p = probe_all()["trends_api"]
    assert p["ok"] is True, "구글만 있어도 열려야 한다"
    assert p["detail"]["google"] is True and p["detail"]["naver"] is False

    monkeypatch.delenv("GOOGLE_TRENDS_API_KEY")
    monkeypatch.setenv("NAVER_CLIENT_ID", "a")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "b")
    p = probe_all()["trends_api"]
    assert p["ok"] is True and p["detail"]["naver"] is True
