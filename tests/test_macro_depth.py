"""P4 — 매크로 표본 깊이와 **출처 조건** (D3·D4)

이 파일이 지키는 것은 하나다: ★합성 데이터로 프론티어 모델을 열지 않는다.★

왜 이 가드가 필요한가
------------------------------------------------------------------------------
P4 는 적재 깊이를 20년(240개월)으로 올리고 mock 길이도 그 깊이에서 유도하게 바꾼다.
파이프라인이 깊이를 감당하는지 mock 으로 검증해야 하기 때문이다. 그런데 그 변경만
하면 **관측 240개가 전부 합성인데 `frontier_sample` 이 통과**해, 지어낸 데이터 위에서
L0(Full Frontier)이 열린다. 그러면 이 사다리는 M1 이 막으려던 바로 그것 —
"그럴듯한 숫자를 만드는 기계" — 이 된다.

착수 0단계 실측(이 파일이 고정하는 사실):
  · `MACRO_HISTORY_YEARS` 는 읽히지만(15→20 반영) `frontier_sample` 이 세는 관측은
    mock 의 `length=60` 하드코딩에서 와서 깊이와 무관했다.
  · 선언 계열은 33개, 실측 계열 0개(전부 MOCK), 관측 60개.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.engine import capability as cap


class _FakeSeries:
    def __init__(self, n: int, source: str) -> None:
        self.values = [0.0] * n
        self.source = source


class _FakeSnap:
    def __init__(self, series: dict) -> None:
        self.series = series


def _probe_with(n: int, source: str, *, k: int = 10, required: int = 240,
                require_real: bool = True):
    """관측 n개 · 출처 source 인 계열 k개로 프로브를 돌린다."""
    snap = _FakeSnap({f"s{i}": _FakeSeries(n, source) for i in range(k)})
    with patch("src.services.macro_collector.MacroCollector") as MC:
        MC.return_value.collect_all.return_value = snap
        return cap._min_observations(required, require_real_source=require_real)()


# ─────────────────────────────────────────────────────────────────────────────
# 1. ★핵심 짝 단언 — 관측만으로는 열리지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
def test_mock_data_never_opens_the_frontier_even_at_full_depth():
    """★이것이 P4 의 정직성 급소다★

    깊이를 올리면 mock 도 240개를 만든다. 그때 열리면 안 된다.
    """
    p = _probe_with(240, "MOCK")
    assert p.ok is False, "합성 데이터 240개로 프론티어가 열렸다"
    assert "합성" in p.reason, p.reason
    assert p.detail["observed"] == 240 and p.detail["real_share"] == 0.0


def test_real_data_at_full_depth_does_open():
    """짝 — 실측이면 열린다. 이게 없으면 게이트를 상수 False 로 둬도 통과한다."""
    p = _probe_with(240, "BOK")
    assert p.ok is True, f"실측 240개인데 안 열렸다: {p.reason}"
    assert p.detail["real_share"] == 1.0


def test_real_data_but_too_short_does_not_open():
    """짝 — 출처가 실측이어도 표본이 모자라면 안 열린다(두 조건이 독립)."""
    p = _probe_with(60, "BOK")
    assert p.ok is False
    assert "표본이 부족" in p.reason, p.reason


@pytest.mark.parametrize("source", ["BOK", "FRED", "KRX", "DART", "KIS"])
def test_all_five_sources_count_as_real(source):
    """사용자가 지정한 다섯 소스는 전부 실측으로 인정된다."""
    assert _probe_with(240, source).ok is True, f"{source} 가 실측으로 인정되지 않았다"


@pytest.mark.parametrize("source", ["MOCK", "unavailable", "", "SYNTHETIC"])
def test_non_real_sources_do_not_count(source):
    """짝 — 실측이 아닌 것은 인정되지 않는다(화이트리스트가 실제로 좁은지)."""
    assert _probe_with(240, source).ok is False, f"{source} 가 실측으로 인정됐다"


def test_mixed_sources_need_a_majority_to_open():
    """절반 미만이면 안 열리고, 절반 이상이면 열린다 — 경계가 상수가 아닌지."""
    snap = _FakeSnap({
        **{f"r{i}": _FakeSeries(240, "FRED") for i in range(4)},
        **{f"m{i}": _FakeSeries(240, "MOCK") for i in range(6)},
    })
    with patch("src.services.macro_collector.MacroCollector") as MC:
        MC.return_value.collect_all.return_value = snap
        low = cap._min_observations(240, require_real_source=True)()
    assert low.ok is False and low.detail["real_share"] == 0.4

    snap2 = _FakeSnap({
        **{f"r{i}": _FakeSeries(240, "FRED") for i in range(6)},
        **{f"m{i}": _FakeSeries(240, "MOCK") for i in range(4)},
    })
    with patch("src.services.macro_collector.MacroCollector") as MC:
        MC.return_value.collect_all.return_value = snap2
        high = cap._min_observations(240, require_real_source=True)()
    assert high.ok is True and high.detail["real_share"] == 0.6


# ─────────────────────────────────────────────────────────────────────────────
# 2. L1 은 이 조건에 걸리지 않는다 — 개발 환경을 죽이지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_causal_sample_still_passes_on_mock():
    """★L1 까지 막으면 개발 환경에서 매크로가 통째로 죽는다★

    막아야 하는 것은 **프론티어를 여는 주장**이지 개발용 계산이 아니다.
    L1 대체 엔진은 이미 `span`·`note` 로 자기 출처를 밝힌다.
    """
    p = _probe_with(60, "MOCK", required=36, require_real=False)
    assert p.ok is True, "mock 에서 L1 표본 요건이 막혔다 — 개발 환경이 죽는다"


def test_live_ladder_stays_at_l1_on_mock():
    """실제 사다리 — mock 환경에서 L1 을 유지한다(회귀 방지)."""
    r = cap.resolve()
    assert r["level"] == "L1", f"mock 환경 도달 레벨이 바뀌었다: {r}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 사유가 두 수치를 함께 말한다 — 무엇이 모자란지 사람이 알아야 한다
# ─────────────────────────────────────────────────────────────────────────────
def test_reason_names_both_numbers_so_the_gap_is_actionable():
    p = _probe_with(240, "MOCK")
    assert "0/10" in p.reason or "0%" in p.reason, p.reason
    assert "50%" in p.reason, "필요 임계가 사유에 없다"
    # 키를 넣으면 열린다는 것을 사람이 알 수 있어야 한다
    assert "BOK" in p.reason and "FRED" in p.reason, p.reason


def test_detail_carries_the_numbers_for_the_ui():
    """화면이 '관측 240 ✓ / 실측 0% ✗' 를 그리려면 detail 에 둘 다 있어야 한다."""
    d = _probe_with(240, "MOCK").detail
    for k in ("observed", "required", "real_series", "total_series", "real_share"):
        assert k in d, f"detail 에 {k} 가 없다 — 화면이 사유를 그릴 수 없다"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 적재 깊이 (D3) — 저장 상한이 깊이를 따라간다
# ─────────────────────────────────────────────────────────────────────────────
#
# ★D3 은 두 번 좁혀졌다 — 그 과정을 여기 적는다★
#
# 처음엔 세 곳을 다 열려 했다: (a) 깊이 기본값 15→20, (b) mock 길이를 깊이에서
# 유도, (c) 저장 상한 `[-72:]` 를 깊이에서 유도.
#
# (b)를 넣자 `test_three_way_endpoint::test_a_real_snapshot_does_not_zero_out_exposure`
# 가 깨졌다. mock 은 드리프트 있는 랜덤워크라 구간이 3배가 되면 합성 국면이
# DEFENSIVE·고스트레스로 치우치고 타이밍 노출이 0 이 된다. 그 테스트는 과거 실제
# 사고(단위/어휘 불일치로 포트폴리오가 전액 위험-오프)를 막는 가드라 약화시킬 수
# 없다. **얻는 것("mock 으로도 240 경로를 밟는다")보다 잃는 것(합성 국면 안정성)이
# 컸으므로 (b)를 되돌렸다.** 깊이가 실제로 필요한 곳은 실 데이터 경로다.
#
# 그 과정에서 (c)를 파다가 별개 결함이 하나 나왔고, 그건 고쳤다 — 아래 5번.

import os
from unittest.mock import patch as _patch


def test_store_cap_follows_depth_so_deep_real_data_is_not_truncated():
    """★실 데이터가 들어와도 저장에서 잘리면 깊이가 무의미하다★

    예전 `MacroSeries(timestamps=timestamps[-72:], values=clean[-72:])` 는
    **상한**이었는데, 주석에 적힌 사유("YoY 변환 후에도 5년 z-표본 확보")는
    **하한**의 근거였다. 그래서 키를 넣어 20년치가 와도 저장에서 72개월로 잘려
    `frontier_sample`(240)은 **어떤 설정으로도 열릴 수 없었다.**
    """
    from src.services.macro_collector import _store_cap
    with _patch.dict(os.environ, {"MACRO_HISTORY_YEARS": "20"}):
        assert _store_cap() == 240, "깊이 20년인데 저장 상한이 240이 아니다"
    with _patch.dict(os.environ, {"MACRO_HISTORY_YEARS": "25"}):
        assert _store_cap() == 300


def test_store_cap_never_goes_below_the_z_sample_floor():
    """짝 — 깊이를 낮춰도 z-표본 하한(72)은 지킨다(기존 가정 보호)."""
    from src.services.macro_collector import _store_cap
    with _patch.dict(os.environ, {"MACRO_HISTORY_YEARS": "1"}):
        assert _store_cap() == 72, "저장 하한이 무너졌다 — 5년 z-표본 가정이 깨진다"


def test_default_depth_meets_the_frontier_sample_requirement():
    """★기본값이 요건을 채운다★ — 설정을 따로 만져야만 열리는 천장은 닫힌 천장이다."""
    from src.services.macro_collector import _history_years
    with _patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MACRO_HISTORY_YEARS", None)
        assert _history_years() * 12 >= 240, "기본 깊이가 frontier_sample(240)에 못 미친다"


def test_mock_length_deliberately_does_not_follow_depth():
    """★mock 은 깊이를 따라가지 않는다 — 의도된 것이고, 이유가 있다★

    되돌린 결정이 조용히 되살아나지 않게 고정한다. mock 을 깊게 만들면 합성 국면이
    치우쳐 `test_three_way_endpoint` 의 노출 가드가 깨진다.
    """
    from src.services import macro_collector as mc
    with _patch.dict(os.environ, {"MACRO_HISTORY_YEARS": "25"}):
        snap = mc.MacroCollector().collect_all(use_cache=False)
        n = max((len(s.values) for s in snap.series.values()), default=0)
    assert n == 60, f"mock 길이가 깊이를 따라갔다({n}) — 되돌린 결정이 되살아났다"


# ─────────────────────────────────────────────────────────────────────────────
# 5. z-표본 창이 이름대로 5년이다 (D3 이 파다가 나온 별개 결함)
# ─────────────────────────────────────────────────────────────────────────────
def test_z_window_is_five_years_as_the_field_names_promise():
    """★`mean_5y`·`std_5y` 라는 이름으로 전 구간을 계산하고 있었다★

    저장이 72개월이던 시절엔 "대략 5년" 이라 티가 안 났지만 이름과 값이 달랐다.
    깊이를 열면 이 불일치가 커진다(실 데이터 20년이면 z 가 20년 창으로 계산됨).
    창을 고정하면 z 는 적재 깊이와 무관해진다 — 하류 국면 로직이 가정하던 바다.
    """
    from src.services.macro_collector import _Z_WINDOW_MONTHS, _normalize
    assert _Z_WINDOW_MONTHS == 60

    # 앞 180개월은 전혀 다른 수준, 뒤 60개월만 최근 창 — 창이 고정이면 앞이 무시된다
    old_regime = [1000.0] * 180
    recent = [100.0 + i * 0.01 for i in range(60)]
    out = _normalize(old_regime + recent)
    assert out["mean_5y"] < 200, (
        f"z 창이 전 구간을 쓰고 있다 — mean_5y={out['mean_5y']} (최근 60개월은 ~100)")


def test_z_window_shorter_series_still_works():
    """짝 — 60개월보다 짧아도 있는 만큼으로 계산한다(죽지 않는다)."""
    from src.services.macro_collector import _normalize
    out = _normalize([100.0 + i for i in range(24)])
    assert out["z_score"] is not None and out["mean_5y"] is not None
