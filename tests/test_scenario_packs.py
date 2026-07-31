"""ScenarioPackV2 — model_type · 12 패밀리 · 정체성 · 노출 합성 (스펙 §5, Phase 9).

이 파일이 고정하는 것

1. **모든 팩이 `model_type` 을 선언한다.** 스펙 §5 가 막으려는 실패는 하나다 —
   가상 충격이 역사적 사실처럼 제시되는 것. 역사 리플레이만 `historical_replay` 다.
2. **12 패밀리가 전부 목록에 있다.** 비어 있는 패밀리도 사유와 함께 남는다 — 빠지면
   "채운 것" 과 "없는 것" 이 화면에서 구별되지 않는다.
3. **정체성이 충격 정의를 따라간다.** 계수가 바뀌면 해시가 바뀐다. 안 그러면 재현되지 않는
   런이 재현 가능한 것처럼 보인다.
4. **합성은 곱셈이고, 근사라는 사실이 함께 나간다.**
"""
import pytest

from src.engine import scenario_packs as sp
from src.engine.kr_scenario_pack import FACTORS, SCENARIOS, run_scenario


# ═══════════════════════════════════════════════════════════════════════════════
# 1. model_type — 두 축이 분리돼 있다
# ═══════════════════════════════════════════════════════════════════════════════
def test_every_pack_declares_a_model_type():
    assert sp.PACKS, "레지스트리가 비어 있습니다"
    for pack in sp.PACKS.values():
        assert isinstance(pack.model_type, sp.ModelType), (
            f"{pack.pack_id} 의 model_type 이 enum 이 아닙니다: {pack.model_type!r}")


def test_only_historical_windows_claim_to_be_historical():
    """★가정 충격이 역사적 사실을 주장하면 안 된다★ 이것이 §5 의 존재 이유다."""
    replay = {p.pack_id for p in sp.PACKS.values()
              if p.model_type is sp.ModelType.HISTORICAL_REPLAY}
    assert replay == set(sp.HIST_WINDOWS), (
        f"역사 리플레이를 주장하는 팩이 실제 시세 윈도우와 다릅니다: {replay}")


def test_the_korean_packs_are_hypothetical_not_a_family_label():
    """`mode: "kr_pack"` 은 패밀리이지 인식론적 주장이 아니었다 — 그 구멍을 막는다."""
    for key in SCENARIOS:
        assert sp.PACKS[key].model_type is sp.ModelType.HYPOTHETICAL


def test_severity_applies_follows_model_type_not_a_hand_set_flag():
    for pack in sp.PACKS.values():
        expected = pack.model_type is not sp.ModelType.HISTORICAL_REPLAY
        assert pack.severity_applies is expected, pack.pack_id


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 12 패밀리 — 비어 있어도 사라지지 않는다
# ═══════════════════════════════════════════════════════════════════════════════
def test_all_twelve_spec_families_are_declared():
    assert len(sp.FAMILIES) == 12, f"패밀리가 {len(sp.FAMILIES)}개 — 스펙 §5 는 12개를 요구합니다"
    ids = [f["id"] for f in sp.families()]
    assert ids == [fid for fid, _ in sp.FAMILIES]


def test_an_empty_family_stays_listed_with_a_reason():
    """★빈 패밀리를 숨기면 없는 것과 채운 것이 구별되지 않는다★"""
    rows = {f["id"]: f for f in sp.families()}
    ua = rows["user_authored"]
    assert ua["covered"] is False and ua["count"] == 0
    assert len(ua.get("reason", "")) > 10, "비어 있는 이유가 없습니다"


@pytest.mark.parametrize("family", [
    "correlation_hedge_failure", "volatility_liquidity", "credit_tightening",
])
def test_the_three_previously_empty_families_now_have_a_pack(family):
    rows = {f["id"]: f for f in sp.families()}
    assert rows[family]["covered"] is True, f"{family} 가 여전히 비어 있습니다"


def test_every_pack_belongs_to_a_declared_family():
    known = {fid for fid, _ in sp.FAMILIES}
    for pack in sp.PACKS.values():
        assert pack.family in known, f"{pack.pack_id} 의 패밀리 {pack.family} 가 §5 목록에 없습니다"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 정체성 — 충격이 바뀌면 해시가 바뀐다
# ═══════════════════════════════════════════════════════════════════════════════
def test_identity_is_pack_id_at_content_hash():
    p = sp.PACKS["semi_selloff"]
    assert p.identity == f"semi_selloff@{p.content_hash}"
    assert len(p.content_hash) == 12


def test_the_hash_moves_when_a_coefficient_moves(monkeypatch):
    """★계수가 바뀌었는데 해시가 그대로면 정체성이 거짓말이다★"""
    before = sp.PACKS["semi_selloff"].content_hash
    mutated = {k: (dict(v) if k != "semi_selloff" else
                   {**v, "factors": {**v["factors"], "semi": -99.0}})
               for k, v in SCENARIOS.items()}
    monkeypatch.setattr("src.engine.kr_scenario_pack.SCENARIOS", mutated)
    after = sp._build()["semi_selloff"].content_hash
    assert after != before, "충격 계수를 바꿨는데 content_hash 가 그대로입니다"


def test_the_hash_ignores_presentation_only_changes(monkeypatch):
    """정체성은 표현이 아니라 **모델**을 가리켜야 한다 — 라벨을 고쳐도 같은 팩이다."""
    before = sp.PACKS["semi_selloff"].content_hash
    renamed = {k: ({**v, "label": "다른 이름"} if k == "semi_selloff" else v)
               for k, v in SCENARIOS.items()}
    monkeypatch.setattr("src.engine.kr_scenario_pack.SCENARIOS", renamed)
    assert sp._build()["semi_selloff"].content_hash == before


def test_the_m8_hash_tracks_the_shock_function_not_just_the_catalogue():
    """★M8 은 계수가 데이터가 아니라 코드에 있다★

    `STRESS_SCENARIOS` 항목에는 label·description 뿐이고 실제 충격은 `_stock_shock()` 안에
    있다. 카탈로그만 해싱하면 충격 모델을 통째로 바꿔도 해시가 그대로다.
    """
    d = sp._m8_definition("rate_hike_200bp")
    assert "shock_fn" in d and "def _stock_shock" in d["shock_fn"], (
        "M8 해시가 충격 함수를 포함하지 않습니다 — 계수 변경을 추적하지 못합니다")


def test_pack_ids_do_not_collide_across_the_three_sources():
    from src.engine.stress_test_analyzer import STRESS_SCENARIOS
    total = len(sp.HIST_WINDOWS) + len(STRESS_SCENARIOS) + len(SCENARIOS)
    assert len(sp.PACKS) == total, (
        f"팩 {len(sp.PACKS)}개 vs 출처 합계 {total}개 — id 가 겹쳐 하나가 덮였습니다")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 새 팩 4종 — 기존 노출 행렬로 실제 실행된다
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("key", [
    "vol_shock_liquidity_vacuum", "credit_conditions_tightening",
    "corr_convergence_hedge_failure", "stagflation_regime",
])
def test_new_packs_run_on_the_existing_seven_factor_matrix(key):
    """★새 노출 로더를 만들지 않았다★ 계수 키가 기존 FACTORS 밖이면 KeyError 로 터진다."""
    assert set(SCENARIOS[key]["factors"]) <= set(FACTORS), (
        f"{key} 가 알 수 없는 팩터를 참조합니다: "
        f"{set(SCENARIOS[key]['factors']) - set(FACTORS)}")
    out = run_scenario(["005930", "000660"], {"005930": 0.6, "000660": 0.4}, key)
    assert out["error"] is False, out.get("message")
    assert isinstance(out["portfolio_shock_pct"], float)


def test_the_shortsell_pack_says_its_data_is_not_measured():
    """§5 는 이 패밀리에 "데이터가 신뢰할 수 있는 경우에만" 단서를 단다 — 침묵하지 않는다."""
    src = SCENARIOS["shortsell_regulation"]["source"]
    assert "가정" in src and "없음" in src, f"대차 데이터 부재가 출처에 없습니다: {src}"


def test_the_credit_pack_is_not_confused_with_the_nfci_factor():
    """가정 계수 모델과 NFCI 실측 팩터는 **다른 물건**이다 — 하나로 읽히면 안 된다."""
    note = SCENARIOS["credit_conditions_tightening"].get("data_note", "")
    assert "financial_conditions" in note, "NFCI 실측 팩터와의 구별이 적혀 있지 않습니다"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 합성 — 손실 × 노출, 그리고 근사라는 고백
# ═══════════════════════════════════════════════════════════════════════════════
def test_compose_scales_the_shock_by_each_leg_exposure():
    out = sp.compose_with_exposure(-10.0, {"baseline": 1.0, "timing_only": 0.5,
                                           "timing_macro": 0.0})
    assert out["baseline"]["shock_pct"] == -10.0
    assert out["timing_only"]["shock_pct"] == -5.0
    assert out["timing_macro"]["shock_pct"] == 0.0
    assert out["timing_macro"]["cash_pct"] == 100.0


def test_compose_clamps_exposure_into_zero_one():
    out = sp.compose_with_exposure(-10.0, {"a": 1.7, "b": -0.3})
    assert out["a"]["exposure"] == 1.0 and out["b"]["exposure"] == 0.0


def test_compose_reports_cash_as_the_unexposed_remainder():
    """현금 비중은 노출의 여집합이다 — 이 관계가 깨지면 두 숫자가 서로를 부정한다."""
    out = sp.compose_with_exposure(-10.0, {"full": 1.0, "half": 0.5, "none": 0.0})
    assert out["full"]["cash_pct"] == 0.0
    assert out["half"]["cash_pct"] == 50.0
    assert out["none"]["cash_pct"] == 100.0
    # 충격을 받지 않은 부분이 곧 현금이다: 손실은 노출분에만 걸린다.
    assert out["none"]["shock_pct"] == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), None, "x"])
def test_a_non_finite_exposure_is_not_silently_clamped_to_full(bad):
    """★NaN 은 클램프를 통과한다★

    `max(0.0, min(1.0, nan))` 는 **1.0** 이다 — NaN 비교가 전부 False 라 `min` 이 첫 인자를
    그대로 내보낸다. 그러면 값을 얻지 못한 다리가 조용히 **전액 노출**로 채점돼 손실이 가장
    크게 찍힌다. 게다가 NaN/inf 는 JSON 에 그대로 나가 엄격한 파서를 깨뜨린다.
    """
    out = sp.compose_with_exposure(-10.0, {"broken": bad})["broken"]
    assert out["exposure"] is None, f"{bad!r} 가 노출 {out['exposure']} 로 대체됐습니다"
    assert out["shock_pct"] is None and out["cash_pct"] is None
    assert out.get("reason"), "수치를 못 만든 사유가 없습니다"


def test_a_non_finite_shock_composes_nothing():
    out = sp.compose_with_exposure(float("nan"), {"a": 0.5})["a"]
    assert out["shock_pct"] is None and out["exposure"] is None


def test_the_linear_approximation_is_stated_not_hidden():
    assert "선형" in sp.COMPOSITION_NOTE and "근사" in sp.COMPOSITION_NOTE


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 인라인(사용자 정의) 팩 — 역사적 사실을 주장할 수 없다
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_inline_pack_cannot_claim_to_be_historical():
    """★클라이언트가 model_type 을 정하면 §5 가 무의미해진다★"""
    p = sp.inline_pack({"label": "내 시나리오", "model_type": "historical_replay",
                        "market": -5.0, "factors": {"size": -3.0},
                        "assumptions": {"corr_rise": 0.1}})
    assert p.model_type is sp.ModelType.HYPOTHETICAL
    assert p.family == "user_authored"
    assert "저장되지 않" in p.source


def test_inline_packs_with_the_same_shock_get_the_same_identity():
    spec = {"market": -5.0, "factors": {"size": -3.0}, "assumptions": {"corr_rise": 0.1}}
    assert sp.inline_pack(spec).identity == sp.inline_pack(dict(spec)).identity


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 이동 — 역사 윈도우 정의가 사라지지 않았다
# ═══════════════════════════════════════════════════════════════════════════════
def test_hist_windows_moved_without_losing_a_window():
    from src.api.allocation_routes import _HIST_WINDOWS
    assert _HIST_WINDOWS is sp.HIST_WINDOWS
    assert set(sp.HIST_WINDOWS) == {"hist_2008_gfc", "hist_2018_trade",
                                    "hist_2020_covid", "hist_2022_rates"}
