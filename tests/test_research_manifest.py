"""판정 메니페스트 — ★증거와 어긋난 판정은 런타임이 거부한다★ (P5 ①)
==============================================================================
검토서: `docs/specs/2026-09-02-deepseek-concept-review.md` §4 P5

Alpha 는 검증기를 이미 갖고 있는데(`research_verdict`·`research_power`·
`research_panel`·`null_stats`) ★판정이 생산 소비자에게 돌아오는 간선이 없었다★.
그리고 관문 판정은 **어디에도 영속화되지 않았다** — `regime_control` 은 JSON
리포트 파일로만 내고 `src/api` 어디에도 그것을 읽는 경로가 없다.

★메니페스트는 생성물이지 손으로 쓰는 것이 아니다★ M9 의 Q14 에서 배운 것이다:
합성 픽스처는 **하드코딩된 주장과 파생된 값을 구분하지 못한다**. 그래서 로더가
메니페스트에 적힌 **증거로 `classify` 를 다시 돌려** 기록된 판정과 대조하고,
어긋나면 거부한다 — 테스트가 잡는 것이 아니라 런타임이 막는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.research_manifest import (  # noqa: E402
    load_manifest,
    verification_label,
)
from src.engine.research_verdict import (  # noqa: E402
    VERDICT_INCONCLUSIVE,
    VERDICT_NO_EVIDENCE,
    VERDICT_POSITIVE,
)

#: A3 이 실제로 낸 판정(`4279f1e`) — 널은 넘었고 SPA 는 못 넘었다.
A3 = {
    "schema": 2,
    "preregistration": {"rule_fingerprint": "a" * 64,
                        "null_fingerprint": "b" * 64, "matches": True},
    "verdict": VERDICT_INCONCLUSIVE,
    "passed": False,
    "evidence": {"null_outside": True, "spa_ok": False,
                 "power": 0.2, "target_power": 0.8},
    "evidence_grade": "E0",
    "evidence_grade_reason": "합성 패널",
    "adjudicated": {"panel": "synthetic", "n_assets": 6, "months": 84,
                    "model": "bl", "arms": ["regime-on", "regime-on-prob",
                                            "regime-const"],
                    "cost_levels_bps": [5.0, 10.0, 25.0],
                    "n_shift": 81, "spa_alpha": 0.05,
                    "provenance": {"price_source": "synthetic",
                                   "regime_source": "synthetic"}},
    "code_version": "test-version",
    "generated_at": "2026-09-02T00:00:00+00:00",
    "report_sha256": "0" * 64,
}


def _write(tmp_path: Path, obj: dict) -> Path:
    p = tmp_path / "macro_gate_verdict.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


# ── 로더 — ★위조를 런타임이 막는다★ ──────────────────────────────────────
def test_a_manifest_whose_verdict_matches_its_evidence_is_accepted(tmp_path):
    m, why = load_manifest(_write(tmp_path, A3))
    assert m is not None and why is None
    assert m["verdict"] == VERDICT_INCONCLUSIVE
    assert m["passed"] is False


def test_a_verdict_edited_to_positive_is_refused(tmp_path):
    """★손으로 고쳐도 증거가 따라오지 않으면 통하지 않는다★

    이것이 메니페스트를 저장소 산물로 두면서도 안전한 이유다. 재계산 대조가
    없으면 메니페스트는 그냥 **주장을 적어 둔 파일**이다.
    """
    forged = {**A3, "verdict": VERDICT_POSITIVE, "passed": True}
    m, why = load_manifest(_write(tmp_path, forged))
    assert m is None
    assert why and "일치" in why or "어긋" in why or why.strip()


def test_evidence_edited_to_agree_with_a_forged_verdict_is_accepted(tmp_path):
    """★짝★ 재계산이 진짜 재계산인지 본다 — 증거까지 바꾸면 그것은 다른 판정이다.

    (위조를 허용한다는 뜻이 아니라, 로더가 **증거를 읽고** 판정하지 텍스트를
    비교하지 않는다는 뜻이다. 증거가 바뀌면 그것은 다른 관문 결과다.)
    """
    consistent = {**A3, "verdict": VERDICT_POSITIVE, "passed": True,
                  "evidence": {**A3["evidence"], "spa_ok": True}}
    m, why = load_manifest(_write(tmp_path, consistent))
    assert m is not None and why is None
    assert m["verdict"] == VERDICT_POSITIVE


def test_a_missing_manifest_is_unknown_not_a_pass(tmp_path):
    """★미상은 통과가 아니다★"""
    m, why = load_manifest(tmp_path / "nope.json")
    assert m is None
    assert why and why.strip()


def test_a_manifest_missing_its_evidence_is_refused(tmp_path):
    m, why = load_manifest(_write(tmp_path, {k: v for k, v in A3.items()
                                             if k != "evidence"}))
    assert m is None and why and why.strip()


def test_a_corrupt_manifest_is_refused_with_a_reason(tmp_path):
    p = tmp_path / "macro_gate_verdict.json"
    p.write_text("{ not json", encoding="utf-8")
    m, why = load_manifest(p)
    assert m is None and why and why.strip()


# ── 라벨 — ★메커니즘 판정을 요청 판정으로 옮기지 않는다★ ─────────────────
def test_without_a_manifest_the_label_is_no_evidence(tmp_path):
    lab = verification_label(None, universe=["005930"], months=60, model="bl")
    assert lab["mechanism_verdict"] == VERDICT_NO_EVIDENCE
    assert lab["passed"] is False
    assert lab["this_request_verified"] is False
    assert lab["reason"] and lab["reason"].strip()


def test_the_label_carries_the_mechanism_verdict_and_what_it_judged(tmp_path):
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=["005930", "000660"], months=60,
                             model="bl")
    assert lab["mechanism_verdict"] == VERDICT_INCONCLUSIVE
    assert lab["passed"] is False
    assert lab["adjudicated"]["n_assets"] == 6
    assert lab["adjudicated"]["months"] == 84
    assert lab["evidence_grade"] == "E0"


def test_a_real_universe_is_never_reported_as_verified(tmp_path):
    """★이 작업의 정직성 핵심★

    A3 은 **E0 합성 6자산 84개월 패널**을 판정했다. 사용자의 KOSPI 포트폴리오는
    그 패널이 아니다. 메커니즘 판정을 요청에 옮겨 붙이면 **하지 않은 이전**을
    주장하게 된다.
    """
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=["005930", "000660"], months=60,
                             model="bl")
    assert lab["this_request_verified"] is False
    assert lab["scope"]["mismatches"], "범위 차이를 하나도 안 적었다"
    joined = " ".join(lab["scope"]["mismatches"])
    assert "자산" in joined or "패널" in joined or "기간" in joined


def test_the_scope_is_clean_when_the_request_matches_the_adjudicated_panel(tmp_path):
    """★짝★ 항상 불일치를 적는 구현을 배제한다 — 그러면 공시가 장식이 된다."""
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=["a", "b", "c", "d", "e", "f"],
                             months=84, model="bl", panel="synthetic")
    assert lab["scope"]["mismatches"] == []


def test_a_matching_scope_still_is_not_verified_when_the_verdict_failed(tmp_path):
    """★범위가 같아도 판정이 통과가 아니면 검증된 것이 아니다★

    범위 일치는 필요조건이지 충분조건이 아니다.
    """
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic")
    assert lab["scope"]["mismatches"] == []
    assert lab["this_request_verified"] is False
    assert lab["reason"].strip()


def test_a_passing_verdict_on_a_matching_scope_is_verified(tmp_path):
    """★짝★ 항상 `False` 를 내는 구현을 배제한다 — 그러면 라벨이 정보가 없다."""
    passing = {**A3, "verdict": VERDICT_POSITIVE, "passed": True,
               "evidence": {**A3["evidence"], "spa_ok": True}}
    m, _ = load_manifest(_write(tmp_path, passing))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic")
    assert lab["this_request_verified"] is True


def test_a_different_model_is_a_scope_mismatch(tmp_path):
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="mvo",
                             panel="synthetic")
    assert any("모델" in s for s in lab["scope"]["mismatches"])
    assert lab["this_request_verified"] is False


# ── AM3 · ★노후화 검사가 실제로 발동한다★ ────────────────────────────────
#
# 옛 구현은 `code_version == mv` 였다. 그런데 실측 결과 **양쪽이 언제나
# `"dev"`** 여서(701행) 이 비교가 **항상 참**이었다 — 가드는 있는데 도달할 수
# 없었다. AL 의 하드코딩 `0` 이 `coverage_complete` 를 이긴 것과 같은 모양이다.
#
# 이제 `versions_comparable` 이 판정한다: **양쪽이 진짜 버전이고 양쪽 트리가
# 깨끗할 때만** `True/False`, 아니면 `None`(비교 불가).

_CLEAN = {"code_tree": "clean", "code_version_method": "measured"}


def _ident(value, tree="clean"):
    from src.domain.build_identity import BuildIdentity
    return BuildIdentity(value=value, method="measured", tree=tree)


def test_a_stale_code_version_is_disclosed_but_does_not_block(tmp_path):
    """노후화는 **적되 막지 않는다** — 막는 것은 플래그의 몫이다."""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic", code_version=_ident("다른-버전"))
    assert lab["code_version_matches"] is False
    assert lab["adjudicated"]["code_version"] == "test-version"
    assert lab["this_request_verified"] is False or lab["passed"] is False


def test_the_same_clean_code_version_matches(tmp_path):
    """★짝★ — 항상 `False`/항상 `None` 인 구현을 배제한다."""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic",
                             code_version=_ident("test-version"))
    assert lab["code_version_matches"] is True


def test_two_dev_versions_no_longer_match(tmp_path):
    """★이것이 버그였다★ 실측 701행이 전부 `"dev"` 라 항상 참이었다."""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN,
                                           "code_version": "dev"}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic", code_version=_ident("dev"))
    assert lab["code_version_matches"] is None, "`\"dev\"` 는 버전이 아니다"


@pytest.mark.parametrize("tree", ["dirty", "unknown"])
def test_an_unclean_tree_makes_the_staleness_check_unknown(tmp_path, tree):
    """★SHA 는 커밋을 식별하지 트리를 식별하지 않는다★"""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic",
                             code_version=_ident("test-version", tree=tree))
    assert lab["code_version_matches"] is None


def test_a_manifest_without_a_tree_record_cannot_be_compared(tmp_path):
    """★커밋된 메니페스트가 정확히 이 상태다★ 트리를 기록한 적이 없다.

    옛 기록을 깨끗하다고 가정하면 지금 고치려는 거짓 일치가 그대로 돌아온다.
    """
    m, _ = load_manifest(_write(tmp_path, A3))  # code_tree 없음
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic",
                             code_version=_ident("test-version"))
    assert lab["code_version_matches"] is None


def test_a_bare_string_request_version_is_not_comparable(tmp_path):
    """문자열만 넘기면 트리를 모르므로 미상이다 — ★미상은 통과가 아니다★"""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic", code_version="test-version")
    assert lab["code_version_matches"] is None


def test_the_label_reports_how_the_request_version_was_known(tmp_path):
    """★값과 그 값을 어떻게 알았는지를 함께 낸다★"""
    m, _ = load_manifest(_write(tmp_path, {**A3, **_CLEAN}))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic",
                             code_version=_ident("test-version"))
    assert lab["code_version_method"] == "measured"
    assert lab["code_tree"] == "clean"
    assert lab["adjudicated"]["code_tree"] == "clean"


def test_the_committed_manifest_cannot_claim_a_version_match():
    """★실물 확인★ 저장소에 커밋된 메니페스트는 `"dev"` 를 담고 있다.

    이 프로그램이 고치는 사건 자체를 못 박는다 — 그 파일로는 노후화 검사가
    참이 될 수 없다.
    """
    from src.domain.build_identity import is_version
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("메니페스트가 없습니다")
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    recorded = raw.get("code_version")
    assert not is_version(recorded) or raw.get("code_tree") != "clean", (
        "메니페스트가 깨끗한 트리의 진짜 버전을 기록했다면 이 테스트를 "
        "갱신하십시오 — 그때는 노후화 검사가 실제로 참/거짓을 냅니다")


def test_the_evidence_grade_comes_from_provenance_not_a_constant(tmp_path):
    """★등급은 파생이다★ (M9) — provenance 를 바꾸면 등급이 따라와야 한다."""
    m, _ = load_manifest(_write(tmp_path, A3))
    base = verification_label(m, universe=list("abcdef"), months=84, model="bl")
    unknown = {**A3, "adjudicated": {**A3["adjudicated"], "provenance": {}}}
    m2, _ = load_manifest(_write(tmp_path, unknown))
    lab2 = verification_label(m2, universe=list("abcdef"), months=84, model="bl")
    assert base["evidence_grade"] == "E0"
    assert lab2["evidence_grade"] is None
    assert lab2["evidence_grade_reason"].strip()


# ── ★저장소에 실제로 커밋된 메니페스트★ ──────────────────────────────────
def test_the_committed_manifest_survives_its_own_recompute_check():
    """★생성된 것이지 손으로 쓴 것이 아님을 실물로 확인한다★

    이 테스트가 red 면 둘 중 하나다: 누가 판정을 손으로 고쳤거나, 관문 규칙
    (`classify`)이 바뀌어 메니페스트가 낡았다. 어느 쪽이든 알아야 한다.
    """
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("판정 메니페스트가 아직 생성되지 않았습니다")
    m, why = load_manifest(MANIFEST_PATH)
    assert m is not None, f"커밋된 메니페스트가 거부됐다: {why}"
    assert m["verdict"] in ("no_evidence", "underpowered", "inconclusive",
                            "evidence_of_no_effect", "positive")
    # ★A3 이 낸 판정과 같아야 한다★ (`4279f1e` · 널은 넘고 SPA 는 못 넘었다)
    assert m["verdict"] == VERDICT_INCONCLUSIVE
    assert m["passed"] is False
    assert m["evidence"]["null_outside"] is True
    assert m["evidence"]["spa_ok"] is False


def test_the_committed_manifest_declares_what_it_adjudicated():
    """판정만 있고 **무엇을 상대로** 판정했는지 없으면 범위를 말할 수 없다."""
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("판정 메니페스트가 아직 생성되지 않았습니다")
    m, _ = load_manifest(MANIFEST_PATH)
    adj = m["adjudicated"]
    for k in ("panel", "n_assets", "months", "model", "cost_levels_bps",
              "n_shift", "spa_alpha", "provenance"):
        assert adj.get(k) is not None, f"{k} 가 비어 있다"
    assert m["report_sha256"] and len(m["report_sha256"]) == 64


def test_the_committed_manifest_does_not_claim_a_real_portfolio_is_verified():
    """★실 유니버스에는 절대 검증을 주장하지 않는다★ — 이 작업의 존재 이유다."""
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("판정 메니페스트가 아직 생성되지 않았습니다")
    m, _ = load_manifest(MANIFEST_PATH)
    lab = verification_label(m, universe=["005930", "000660", "035420"],
                             months=60, model="bl")
    assert lab["this_request_verified"] is False
    assert lab["reason"].strip()


# ── ★통과한 판정도 다른 대상으로 옮겨지지 않는다★ ────────────────────────
def _passing(tmp_path: Path):
    ok = {**A3, "verdict": VERDICT_POSITIVE, "passed": True,
          "evidence": {**A3["evidence"], "spa_ok": True}}
    m, why = load_manifest(_write(tmp_path, ok))
    assert m is not None and why is None
    return m


def test_a_passing_verdict_does_not_transfer_to_a_different_universe(tmp_path):
    """★가장 위험한 경우다★ 판정이 `positive` 여도 **판정된 대상이 아니면**
    검증된 것이 아니다.

    변이 V6(범위를 무시하고 판정만으로 판단)이 이 테스트가 없어서 살아남았다 —
    기존 테스트는 전부 `passed=False` 이거나 범위가 일치해서 둘을 구분하지
    못했다. 관문이 언젠가 통과하는 날 이 구멍이 그대로 열린다.
    """
    m = _passing(tmp_path)
    lab = verification_label(m, universe=["005930", "000660"], months=60,
                             model="bl")
    assert lab["passed"] is True
    assert lab["mechanism_verdict"] == VERDICT_POSITIVE
    assert lab["this_request_verified"] is False
    assert lab["scope"]["mismatches"]
    assert "판정된 대상이 아닙니다" in lab["reason"]


@pytest.mark.parametrize("kw,needle", [
    ({"universe": list("abcde")}, "자산 수"),          # 5 ≠ 6
    ({"months": 60}, "기간"),
    ({"model": "mvo"}, "모델"),
    ({"panel": "real"}, "패널"),
])
def test_each_scope_dimension_is_detected_on_its_own(tmp_path, kw, needle):
    """★차원마다 따로 건다★ 한 테스트가 네 차원을 한꺼번에 흔들면 어느 하나를
    지워도 통과한다(변이 V9 가 그렇게 살아남았다)."""
    m = _passing(tmp_path)
    base = {"universe": list("abcdef"), "months": 84, "model": "bl",
            "panel": "synthetic"}
    lab = verification_label(m, **{**base, **kw})
    assert len(lab["scope"]["mismatches"]) == 1, lab["scope"]["mismatches"]
    assert needle in lab["scope"]["mismatches"][0]
    assert lab["this_request_verified"] is False


def test_no_mismatch_is_reported_when_every_dimension_agrees(tmp_path):
    """★짝★ 위 파라미터 테스트가 항상-불일치 구현을 통과시키지 않게 못 박는다."""
    m = _passing(tmp_path)
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic")
    assert lab["scope"]["mismatches"] == []
    assert lab["this_request_verified"] is True


# ══════════════════════════════════════════════════════════════════════════
# ★라벨이 생산 응답에 닿는다★ (P5 ②)
# ══════════════════════════════════════════════════════════════════════════

def test_the_conditional_block_always_carries_verification():
    """★모든 분기가 낸다★ — `available` 여부와 무관하다.

    어떤 응답에만 있으면 소비자가 `.get()` 으로 읽다가 `None` 을 거짓으로
    취급한다(이 모듈의 `prob_*` 규율과 같은 이유). 그리고 조건부를 **쓴** 응답에만
    검증을 실으면, 쓰지 못한 응답은 검증 상태를 물어볼 수조차 없게 된다.
    """
    from src.api.allocation_routes import _conditional_block
    for cond in ({"available": False, "reason": "표본 부족"},
                 {"available": True, "method": "hard", "regime": "GOLDILOCKS",
                  "sigma": None}):
        blk = _conditional_block(cond, {"path_source": "test"},
                                 sigma_applied=bool(cond.get("available")),
                                 mu_as_views=0, view_confidence=None,
                                 model="bl", universe=["005930"], months=60)
        v = blk["verification"]
        assert v is not None
        assert "mechanism_verdict" in v and "this_request_verified" in v
        assert v["this_request_verified"] is False


def test_the_conditional_block_reports_the_real_committed_verdict():
    """실물 메니페스트가 응답에 그대로 닿는지 — 배선을 값으로 건다."""
    from src.api.allocation_routes import _conditional_block
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("판정 메니페스트가 아직 생성되지 않았습니다")
    blk = _conditional_block({"available": True}, {}, sigma_applied=True,
                             mu_as_views=6, view_confidence=0.5, model="bl",
                             universe=["005930", "000660"], months=60)
    v = blk["verification"]
    assert v["mechanism_verdict"] == VERDICT_INCONCLUSIVE
    assert v["passed"] is False
    assert v["this_request_verified"] is False
    # ★"목록이 비어 있지 않다" 는 너무 약하다★ — 유니버스·기간을 아예 안 넘겨도
    # "패널 미선언" 항목 하나 때문에 통과한다(변이 W3 가 그렇게 살아남았다).
    # 요청의 값이 **실제로 라벨까지 갔는지**를 차원별로 건다.
    joined = " ".join(v["scope"]["mismatches"])
    assert "자산 수 2" in joined, f"유니버스가 라벨에 안 갔다: {joined}"
    assert "기간 60개월" in joined, f"기간이 라벨에 안 갔다: {joined}"


def test_the_months_span_is_unknown_rather_than_zero():
    """★미상 ≠ 0★ 기간을 모르면 0개월이 아니라 미상이다 — 0 이면 범위 비교가
    조용히 거짓이 된다(84 ≠ 0 이 '기간 불일치' 로 보고된다)."""
    from src.api.allocation_routes import _months_span
    assert _months_span(None) is None
    assert _months_span([]) is None
    assert _months_span(object()) is None


def test_the_months_span_reads_a_real_index():
    """★짝★ 항상 `None` 을 내면 위 테스트가 공허하다."""
    import pandas as pd

    from src.api.allocation_routes import _months_span
    idx = pd.date_range("2020-01-31", periods=25, freq="ME")
    assert _months_span(pd.DataFrame(index=idx)) == 24


# ══════════════════════════════════════════════════════════════════════════
# ★미검증 차단 플래그 — 기본 OFF★ (P5 ③)
# ══════════════════════════════════════════════════════════════════════════

def test_the_gate_does_not_block_by_default():
    """★기본은 라벨링이다★ (사용자 결정) — 동작이 바뀌지 않는다."""
    from src.api.allocation_routes import macro_gate_decision
    v = {"this_request_verified": False, "mechanism_verdict": "inconclusive",
         "reason": "통과한 적이 없습니다"}
    blocked, why = macro_gate_decision(v, require_verified=False)
    assert blocked is False and why is None


def test_the_gate_blocks_an_unverified_path_when_asked():
    from src.api.allocation_routes import macro_gate_decision
    v = {"this_request_verified": False, "mechanism_verdict": "inconclusive",
         "reason": "통과한 적이 없습니다"}
    blocked, why = macro_gate_decision(v, require_verified=True)
    assert blocked is True
    assert why and "inconclusive" in why


def test_the_gate_lets_a_verified_path_through():
    """★짝★ 항상 막는 구현을 배제한다 — 그러면 플래그가 스위치가 아니라 차단기다."""
    from src.api.allocation_routes import macro_gate_decision
    v = {"this_request_verified": True, "mechanism_verdict": "positive",
         "reason": None}
    blocked, why = macro_gate_decision(v, require_verified=True)
    assert blocked is False and why is None


def test_an_unknown_verification_is_blocked_not_passed():
    """★미상은 통과가 아니다★ — 라벨이 없거나 망가져도 통과시키지 않는다."""
    from src.api.allocation_routes import macro_gate_decision
    for v in ({}, {"this_request_verified": None}, None):
        blocked, why = macro_gate_decision(v, require_verified=True)
        assert blocked is True, v
        assert why and why.strip()


def test_the_block_reason_names_the_verdict_not_just_that_it_failed():
    """사유가 '검증 안 됨' 뿐이면 쓸모가 없다 — 무엇이 문제인지 말해야 한다."""
    from src.api.allocation_routes import macro_gate_decision
    v = {"this_request_verified": False, "mechanism_verdict": "underpowered",
         "reason": "검정력이 목표에 못 미칩니다"}
    _, why = macro_gate_decision(v, require_verified=True)
    assert "underpowered" in why
    assert "검정력이 목표에 못 미칩니다" in why


def test_both_conditional_routes_get_their_belief_from_the_one_door():
    """★규칙과 배선은 다른 일이다★ (N6·R5·S1·W3·X7·Y16 에서 여섯 번 겪었다)

    P8 ② 이전에는 두 라우트가 각자 `macro_gate_decision` 을 부르는지 소스로 봤다.
    이제 관문은 `build_belief` **안에 한 번만** 있으므로, 여기서 볼 것은 두 가지다:
    두 라우트가 그 문을 지나는가, 그리고 ★그 문을 우회하지 않는가★.

    검토서가 P8 에 지정한 변이가 정확히 "추출한 서비스를 우회" 다.
    """
    import ast
    import inspect
    import textwrap

    import src.api.allocation_routes as ar
    # ★본문이 있는 함수를 본다★ `allocation_analyze` 는 `run_analyze` 로
    # 위임하는 얇은 껍데기라, 껍데기를 검사하면 이 테스트가 공허해진다
    # (실제로 처음에 그렇게 썼고 이 테스트가 잡았다).
    for fn in (ar.run_analyze, ar.rebalance_decision_route):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "build_belief" in called, f"{fn.__name__} 이 벨리프 문을 안 지난다"
        # ★짝 — 우회 금지★ 조립을 직접 하면 관문이 다시 두 곳(또는 0곳)이 된다.
        for bypass in ("_conditional_stack", "macro_gate_decision",
                       "_macro_verification"):
            assert bypass not in called, (
                f"{fn.__name__} 이 {bypass} 를 직접 부른다 — 서비스를 우회하면 "
                "관문이 다시 갈라진다")


def _stub_stack(sigma="Σ", views=(1, 2, 3), conf=42.0) -> dict:
    return {"cond": {"available": True}, "path": {"path_source": "stub"},
            "meta": {"mode": "live"}, "s_override": sigma,
            "extra_views": list(views), "view_conf": conf}


class _StubReq:
    conditional = True
    model = "bl"
    require_verified_macro = True


def _returns_frame():
    import pandas as pd
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    return pd.DataFrame({"a": range(200), "b": range(200)}, index=idx)


def test_the_one_door_drops_the_conditional_inputs_when_it_blocks(monkeypatch):
    """★차단했다고 **말만** 하고 그대로 쓰면 리포트가 거짓말을 한다★ (변이 X7)

    P8 ② 이전에는 두 라우트의 소스에서 `if macro_blocked:` 분기를 찾아 확인했다.
    이제는 **값으로** 잰다 — 문을 직접 불러 돌려받은 것을 본다. 소스가 어떻게
    생겼든 상관없고, 파일을 어디로 옮기든 살아남는다.
    """
    import src.api.allocation_pipeline as ap
    monkeypatch.setattr(ap, "_conditional_stack", lambda req, r: _stub_stack())
    monkeypatch.setattr(ap, "_macro_verification",
                        lambda **kw: {"this_request_verified": False,
                                      "mechanism_verdict": "inconclusive",
                                      "reason": "시험용"})
    b = ap.build_belief(_StubReq(), _returns_frame(), ["005930", "000660"])
    assert b.blocked is True and b.blocked_reason
    assert b.s_override is None and b.extra_views is None
    assert b.view_confidence is None
    # ★진단은 남는다★ 응답이 "무엇을 계산할 수 있었는데 왜 안 썼는지" 를 말해야 한다.
    assert b.cond == {"available": True} and b.path == {"path_source": "stub"}


def test_the_one_door_passes_the_inputs_through_when_it_does_not_block(monkeypatch):
    """★짝★ 항상 비우면 그것은 관문이 아니라 차단기다."""
    import src.api.allocation_pipeline as ap
    monkeypatch.setattr(ap, "_conditional_stack", lambda req, r: _stub_stack())
    monkeypatch.setattr(ap, "_macro_verification",
                        lambda **kw: {"this_request_verified": True})
    b = ap.build_belief(_StubReq(), _returns_frame(), ["005930", "000660"])
    assert b.blocked is False and b.blocked_reason is None
    assert b.s_override == "Σ" and b.extra_views == [1, 2, 3]
    assert b.view_confidence == 42.0


def test_asking_no_question_is_not_a_block(monkeypatch):
    """조건부를 요청하지 않은 것과 차단된 것은 ★다른 상태★ 다."""
    import src.api.allocation_pipeline as ap

    def _boom(*a, **k):                       # noqa: ANN002, ANN003
        raise AssertionError("조건부를 요청하지 않았는데 스택을 만들었다")
    monkeypatch.setattr(ap, "_conditional_stack", _boom)

    class _Off(_StubReq):
        conditional = False
    b = ap.build_belief(_Off(), _returns_frame(), ["005930"])
    assert b.blocked is False and b.blocked_reason is None
    assert b.cond is None and b.s_override is None


def test_both_request_models_expose_the_flag_defaulting_off():
    from src.api.allocation_routes import AnalyzeRequest, RebalanceDecisionRequest
    # `RebalanceDecisionRequest` 는 `AnalyzeRequest` 를 상속하므로 둘 다 갖는다.
    for model in (AnalyzeRequest, RebalanceDecisionRequest):
        f = model.model_fields.get("require_verified_macro")
        assert f is not None, f"{model.__name__} 에 플래그가 없다"
        assert f.default is False, "기본값이 OFF 가 아니다 — 동작이 바뀐다"


def test_the_gate_lives_in_exactly_one_place():
    """★관문이 두 곳이면 언젠가 한 곳만 고쳐진다★ — 그것이 이 추출의 이유다.

    P5 는 관문을 두 라우트에 각각 배선해야 했고, 소비자가 하나 더 생기면 세 곳이
    된다. 배선 지점이 하나임을 구조로 못 박는다.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    sites = []
    for f in sorted(root.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id == "macro_gate_decision":
                sites.append(f"{f.relative_to(root)}:{n.lineno}")
    assert len(sites) == 1, f"관문 호출 지점이 {len(sites)}곳이다: {sites}"
    assert sites[0].startswith("api/allocation_pipeline.py"), sites


def test_the_response_declares_that_it_was_blocked():
    from src.api.allocation_routes import _conditional_block
    blk = _conditional_block({"available": True}, {}, sigma_applied=False,
                             mu_as_views=0, view_confidence=None, model="bl",
                             universe=["005930"], months=60,
                             blocked_reason="판정이 inconclusive 입니다")
    v = blk["verification"]
    assert v["blocked"] is True
    assert v["blocked_reason"] == "판정이 inconclusive 입니다"


def test_the_response_does_not_claim_a_block_that_did_not_happen():
    """★짝★ 항상 `blocked: True` 면 그 필드는 정보가 없다."""
    from src.api.allocation_routes import _conditional_block
    v = _conditional_block({"available": True}, {}, sigma_applied=True,
                           mu_as_views=6, view_confidence=0.5, model="bl",
                           universe=["005930"], months=60)["verification"]
    assert v["blocked"] is False
    assert v["blocked_reason"] is None


# ── ★사전등록 출처가 없는 판정은 증거가 아니다★ (P6 합성) ────────────────
def test_a_schema_one_manifest_is_no_longer_evidence(tmp_path):
    """P6 이전 메니페스트는 어느 결정규칙 아래 나왔는지 말할 수 없다."""
    old = {k: v for k, v in A3.items() if k != "preregistration"}
    m, why = load_manifest(_write(tmp_path, {**old, "schema": 1}))
    assert m is None
    assert why and "schema" in why


def test_a_manifest_without_preregistration_is_refused(tmp_path):
    m, why = load_manifest(_write(tmp_path, {k: v for k, v in A3.items()
                                             if k != "preregistration"}))
    assert m is None and why and why.strip()


def test_a_manifest_from_a_drifted_run_is_refused(tmp_path):
    """★어긋난 실행의 판정은 증거가 아니다★"""
    drifted = {**A3, "preregistration": {**A3["preregistration"],
                                         "matches": False}}
    m, why = load_manifest(_write(tmp_path, drifted))
    assert m is None and why and why.strip()


def test_a_matching_run_is_accepted(tmp_path):
    """★짝★ 항상 거부하면 그것은 관문이 아니라 차단기다."""
    m, why = load_manifest(_write(tmp_path, A3))
    assert m is not None and why is None
    assert m["preregistration"]["matches"] is True


def test_the_manifest_records_the_actual_fingerprints_not_just_a_claim():
    """★속 빈 주장을 막는다★

    처음 구현에서 `write_verdict_manifest` 의 지역변수 `pre` 가 리포트의 서술용
    `preregistered` 블록을 읽는 **기존 같은 이름 변수**에 가려져, 메니페스트가
    지문 없이 `matches: true` 만 적었다. `matches` 를 하드코딩했기 때문에 그
    모순이 드러나지 않았다 — 지문이 비어 있는데 "일치" 라고 적힌 것이다.
    """
    from src.engine.research_manifest import MANIFEST_PATH
    if not MANIFEST_PATH.exists():
        pytest.skip("판정 메니페스트가 아직 생성되지 않았습니다")
    m, why = load_manifest(MANIFEST_PATH)
    assert m is not None, f"거부됨: {why}"
    pre = m["preregistration"]
    assert pre["matches"] is True
    for k in ("rule_fingerprint", "null_fingerprint"):
        assert pre.get(k), f"{k} 가 비어 있다 — 일치를 주장할 근거가 없다"
        assert len(pre[k]) == 64


def test_the_manifest_fingerprints_match_the_committed_registration():
    """★판정이 **어느 등록** 아래 나왔는지 실제로 대조된다★"""
    from src.engine.research_manifest import MANIFEST_PATH
    from src.engine.research_preregistration import (
        REGISTRATION_PATH,
        load_registration,
    )
    if not (MANIFEST_PATH.exists() and REGISTRATION_PATH.exists()):
        pytest.skip("메니페스트 또는 등록이 없습니다")
    m, _ = load_manifest(MANIFEST_PATH)
    reg, why = load_registration(REGISTRATION_PATH)
    assert reg is not None, why
    assert m["preregistration"]["rule_fingerprint"] == reg["rule_fingerprint"]
    assert m["preregistration"]["null_fingerprint"] == reg["null_fingerprint"]
