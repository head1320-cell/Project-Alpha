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
