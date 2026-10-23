"""AJ2 — 다중검정이 일어나는 자리의 레지스트리와 롤업.

AH2(`estimator_evidence`)의 관용구 그대로이고, ★판정은 `run_evidence.rollup`
한 곳에만 있다★ — `pit_evidence`·`decision_evidence`·`estimator_evidence` 와 **같은
함수**다. 두 곳에 복사하면 한쪽만 고쳐도 타입 에러가 나지 않고 화면마다 다른
판정이 나온다.

## 이 파일이 거는 계약

  · 보정이 **실제로 적용**됐으면 `ok`
  · 가족 크기는 아는데 ★보정이 없으면 `degraded`★ — 관측된 결함이지 미상이 아니다
  · 가족 크기를 모르면 `unknown` — ★통과가 아니다★
  · ★미이행 사전등록 표는 비어 있지 않고★, 각 항목에 사유가 있다
"""
from __future__ import annotations

import pathlib

import pytest

from src.domain.multiplicity import (
    CORRECTION_BH,
    CORRECTION_NONE,
    CORRECTION_SPA,
    CORRECTIONS,
    FAMILY_DECLARED,
    FAMILY_PREREGISTERED,
    FAMILY_SOURCES,
    FAMILY_UNKNOWN,
)
from src.engine.multiplicity_evidence import (
    EXCLUDED_SITES,
    SEARCH_SITES,
    UNIMPLEMENTED_PREREGISTRATIONS,
    SearchSite,
    registry_evidence,
    site_axis,
)
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    STATUS_UNKNOWN,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _site(**kw) -> SearchSite:
    base = dict(key="x", site="src/engine/x.py:f", label="시험",
                family_source=FAMILY_DECLARED, correction=CORRECTION_NONE,
                decision_touching=False, note="…")
    base.update(kw)
    return SearchSite(**base)


# ═══════════════════════════════════════════════════════════════════════════
# ⑫⑬ 축 상태 — 세 갈래가 **실제로** 나온다
# ═══════════════════════════════════════════════════════════════════════════

def test_an_applied_correction_is_ok():
    assert site_axis(_site(correction=CORRECTION_BH))["state"] == AXIS_OK


def test_a_known_family_without_a_correction_is_degraded():
    """★관측된 결함이지 미상이 아니다★

    `factor_exposure`·`macro_sensitivity` 가 정확히 이 상태였다 — 몇 개를 봤는지
    적고 "보정 없이 유의하다고 말하는 것은 거짓" 이라고 **경고만** 했다.
    """
    axis = site_axis(_site(family_source=FAMILY_DECLARED, correction=CORRECTION_NONE))
    assert axis["state"] == AXIS_DEGRADED
    assert axis["reason"]


def test_an_unknown_family_is_unknown_not_degraded():
    """★못 잰 것과 재서 나쁜 것은 다르다★"""
    axis = site_axis(_site(family_source=FAMILY_UNKNOWN, correction=CORRECTION_NONE))
    assert axis["state"] == AXIS_UNKNOWN
    assert axis["reason"]


def test_a_preregistered_but_unapplied_correction_is_not_ok():
    """★사전등록은 적용이 아니다★ — 이름이 적혔다고 보정이 된 것이 아니다."""
    axis = site_axis(_site(family_source=FAMILY_PREREGISTERED,
                           correction=CORRECTION_BH, applied=False))
    assert axis["state"] != AXIS_OK
    assert axis["reason"]


def test_the_three_states_all_occur():
    """★짝★ 언제나 한 상태인 구현을 배제한다."""
    states = {
        site_axis(_site(correction=CORRECTION_SPA))["state"],
        site_axis(_site(correction=CORRECTION_NONE))["state"],
        site_axis(_site(family_source=FAMILY_UNKNOWN))["state"],
    }
    assert states == {AXIS_OK, AXIS_DEGRADED, AXIS_UNKNOWN}


def test_an_all_unknown_registry_rolls_up_to_unknown():
    """축이 전부 미상이면 판정도 미상이다 — ★깨끗함으로 접히지 않는다★"""
    from src.engine.multiplicity_evidence import rollup_sites
    sites = (_site(key="a", family_source=FAMILY_UNKNOWN),
             _site(key="b", family_source=FAMILY_UNKNOWN))
    assert rollup_sites(sites)["status"] == STATUS_UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# 레지스트리 자체 — ★실측을 못 박는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_is_not_empty():
    """★빈 레지스트리는 모든 검사를 공허하게 만든다★ (AG 의 사고)"""
    assert len(SEARCH_SITES) >= 5


def test_every_site_uses_the_shared_vocabulary():
    for s in SEARCH_SITES:
        assert s.family_source in FAMILY_SOURCES, s.site
        assert s.correction in CORRECTIONS, s.site
        assert s.note, f"{s.site} 에 설명이 없다"


def test_site_keys_are_unique():
    keys = [s.key for s in SEARCH_SITES]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("s", SEARCH_SITES, ids=lambda s: getattr(s, "key", "?"))
def test_every_registered_site_really_exists(s):
    """★레지스트리가 유령을 가리키면 그 항목은 증거가 아니다★"""
    path = _ROOT / s.site.split(":")[0]
    assert path.exists(), f"{s.site} 파일이 없다"
    symbol = s.site.split(":")[-1]
    assert symbol in path.read_text(encoding="utf-8"), f"{s.site} 심볼이 없다"


def test_at_least_one_site_touches_decisions():
    """★결정에 닿는 다중검정이 있다는 사실 자체가 발견이었다★

    `robust_opt` 의 `|μ|/SE ≥ 2` 가 자산마다 **동시에** 판정되고 그 결과가
    리밸런싱 밴드로 간다.
    """
    touching = [s for s in SEARCH_SITES if s.decision_touching]
    assert touching, "결정 경로 자리가 레지스트리에서 사라졌다"
    assert all(s.note for s in touching)


def test_the_registry_does_not_claim_everything_is_corrected():
    """★지금 상태를 낙관적으로 적지 않는다★ — 보정 없는 자리가 실제로 있다."""
    assert any(s.correction == CORRECTION_NONE for s in SEARCH_SITES)


def test_hansen_spa_is_named_not_reinvented():
    """★이미 있는 보정을 새 이름으로 덮지 않는다★"""
    assert any(s.correction == CORRECTION_SPA for s in SEARCH_SITES)


def test_excluded_sites_all_carry_a_reason():
    """★안 잰 것을 사유와 함께 적는다★ — 없으면 '다 봤다' 로 읽힌다."""
    assert EXCLUDED_SITES
    for e in EXCLUDED_SITES:
        assert e.get("site") and e.get("reason")


# ═══════════════════════════════════════════════════════════════════════════
# ⑭ ★미이행 사전등록★ — 깨진 등록은 단순 부재보다 나쁘다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_unimplemented_preregistration_table_is_not_empty():
    """★표가 비면 이 검사 전체가 공허하다★ (AG 의 `_DECLARATION_SITES` 사고)

    지금 하나가 있다: 매크로 타깃 검증이 Benjamini–Hochberg 를 동결 표에
    사전등록했는데 BH 구현도, 그 검증 하네스도 저장소에 없다.
    """
    assert UNIMPLEMENTED_PREREGISTRATIONS


@pytest.mark.parametrize("p", UNIMPLEMENTED_PREREGISTRATIONS,
                         ids=lambda p: getattr(p, "get", lambda _k: "?")("doc"))
def test_every_unimplemented_preregistration_names_a_real_document(p):
    doc = _ROOT / p["doc"]
    assert doc.exists(), f"{p['doc']} 가 없다"
    assert p["reason"], "사유 없는 미이행은 기록이 아니다"
    assert p["method"] in CORRECTIONS
    text = doc.read_text(encoding="utf-8")
    assert p["evidence"] in text, (
        f"{p['doc']} 에 사전등록 문구가 없다 — 문서가 바뀌었으면 표도 바꾼다")


def test_the_macro_bh_preregistration_is_listed():
    """★채점표가 적지 않았던 사실★ — BH 는 '없음' 이 아니라 '등록했는데 미이행' 이었다."""
    docs = [p["doc"] for p in UNIMPLEMENTED_PREREGISTRATIONS]
    assert any("macro-target-validation" in d for d in docs)


# ═══════════════════════════════════════════════════════════════════════════
# ⑮ ★문서가 보정을 사전등록하면 레지스트리에 있어야 한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_no_spec_preregisters_a_correction_outside_the_registry():
    """문서를 새로 쓰고 레지스트리를 잊는 것을 막는다.

    ★구현이 생기면 이 표에서 **빼야** 한다★ — 그때 이 검사가 그 사실을 알려준다.
    """
    listed = {p["doc"] for p in UNIMPLEMENTED_PREREGISTRATIONS}
    implemented_docs = {"docs/specs/2026-09-12-addendum-scorecard.md"}
    offenders = []
    for path in sorted((_ROOT / "docs" / "specs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "사전등록" not in text and "동결" not in text:
            continue
        if "Benjamini" not in text:
            continue
        rel = str(path.relative_to(_ROOT))
        if rel not in listed and rel not in implemented_docs:
            offenders.append(rel)
    assert not offenders, (
        f"보정을 사전등록한 문서가 레지스트리에 없다: {offenders}")


# ═══════════════════════════════════════════════════════════════════════════
# 롤업 표면
# ═══════════════════════════════════════════════════════════════════════════

def test_the_registry_rollup_reports_the_broken_axes():
    got = registry_evidence()
    assert got["broken_axes"], "보정 없는 자리가 결함으로 안 잡힌다"
    assert got["summary"]
    assert got["unimplemented_preregistrations"]
    assert got["excluded"]
    assert got["note"]


def test_the_rollup_does_not_claim_pbo_or_dsr():
    """★없는 것은 없다고 적는다★ — N 을 세는 자리가 없어 만들 수 없다."""
    note = registry_evidence()["note"]
    assert "deflated" in note.lower() or "PBO" in note


def test_the_preregistration_scan_actually_finds_something():
    """★검사의 검사★ — 위 스캔이 아무 문서도 못 찾으면 그 통과는 공허하다."""
    hits = [p for p in sorted((_ROOT / "docs" / "specs").glob("*.md"))
            if "Benjamini" in p.read_text(encoding="utf-8")]
    assert hits, "스캔이 후보를 하나도 못 찾았다 — 검사가 공허하다"
