"""AAS 스테이지 통합 카탈로그 — Alpha Lab 필드/함수 그룹 + Stress 시나리오 3패밀리 통합.

타이밍 팩터 창(test_timing_rules_api.py)과 동일한 계약:
  groups[{family,label,items}] + families[{id,label}] + note(정직성).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.allocation_routes import allocation_stress_scenarios  # noqa: E402
from src.api.alpha_routes import alpha_fields  # noqa: E402


# ── Alpha Lab 표현식 카탈로그 ────────────────────────────────────────────────
def test_alpha_fields_exposes_family_groups():
    cat = alpha_fields()
    # 기존 평탄 키는 하위호환으로 유지 (기존 UI/클라이언트가 계속 동작)
    assert cat["fields"] and cat["functions"]

    fams = {g["family"] for g in cat["groups"]}
    assert fams == {"price", "fund", "transform", "combine"}
    for g in cat["groups"]:
        assert g["label"] and isinstance(g["items"], list) and g["items"]
        for it in g["items"]:
            assert it["id"] and it["label"] and it["desc"]
            assert it["kind"] in ("field", "function")
            assert it["insert"] in ("append", "wrap", "wrap2")


def test_alpha_catalog_ids_match_engine_and_are_unique():
    from src.engine.alpha_lab import FIELD_IDS, FUNCS_1, FUNCS_2

    cat = alpha_fields()
    items = [it for g in cat["groups"] for it in g["items"]]
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)), "카탈로그 항목 id 중복 금지"

    field_ids = {it["id"] for it in items if it["kind"] == "field"}
    assert field_ids == FIELD_IDS, "필드 그룹은 엔진 FIELD_IDS와 정확히 일치해야 함"

    # 노출된 함수는 전부 파서가 실제로 허용하는 것만 (죽은 버튼 금지)
    for it in items:
        if it["kind"] == "function":
            assert it["id"] in set(FUNCS_1) | set(FUNCS_2)
        if it["insert"] == "wrap2":
            assert it["id"] in FUNCS_2


def test_alpha_catalog_marks_pit_limits_honestly():
    cat = alpha_fields()
    fund = next(g for g in cat["groups"] if g["family"] == "fund")
    # 펀더멘털은 공시랙 근사 — 필드마다 정직 라벨이 있어야 한다
    assert all(it.get("provenance") for it in fund["items"])
    assert any("공시" in it["provenance"] or "PIT" in it["provenance"] for it in fund["items"])
    assert cat["note"]


# ── Stress 통합 시나리오 카탈로그 ────────────────────────────────────────────
def test_stress_scenarios_merges_three_families():
    cat = allocation_stress_scenarios()
    fams = {g["family"] for g in cat["groups"]}
    assert fams == {"hypothetical", "historical", "kr_pack"}

    items = [s for g in cat["groups"] for s in g["items"]]
    ids = {s["id"] for s in items}
    # 세 소스가 한 창에 통합 — 각 소스의 대표 항목이 모두 존재
    assert {"rate_hike_200bp", "recession"} <= ids                 # 가상(M8)
    assert {"hist_2020_covid", "hist_2022_rates"} <= ids           # 역사 리플레이
    assert {"semi_selloff", "shortsell_regulation"} <= ids          # 국내 팩

    for s in items:
        assert s["label"] and s["description"]
        assert isinstance(s["available"], bool)
        assert isinstance(s["severity_applies"], bool)
        assert s["source"]
        if not s["available"]:
            assert s["reason"], "미가용 시나리오는 사유를 정직하게 밝혀야 함"


def test_stress_scenarios_severity_only_for_shock_models():
    """역사 리플레이는 실제 시세 재생 — severity 배율이 적용되지 않는다(정직)."""
    cat = allocation_stress_scenarios()
    by_id = {s["id"]: s for g in cat["groups"] for s in g["items"]}
    assert by_id["hist_2020_covid"]["severity_applies"] is False
    assert by_id["rate_hike_200bp"]["severity_applies"] is True
    assert by_id["semi_selloff"]["severity_applies"] is True


def test_stress_scenarios_ids_unique_and_match_legacy_catalogs():
    """통합 카탈로그가 기존 두 엔드포인트의 상위집합 — 항목 유실 금지."""
    from src.api.allocation_routes import allocation_kr_scenario_catalog, allocation_stress_catalog

    cat = allocation_stress_scenarios()
    ids = [s["id"] for g in cat["groups"] for s in g["items"]]
    assert len(ids) == len(set(ids))

    legacy = {s["id"] for s in allocation_stress_catalog()["scenarios"]}
    kr = {s["id"] for s in allocation_kr_scenario_catalog()["scenarios"]}
    assert legacy | kr <= set(ids)
