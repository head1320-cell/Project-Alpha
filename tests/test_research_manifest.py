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
    "schema": 1,
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


def test_a_stale_code_version_is_disclosed_but_does_not_block(tmp_path):
    """노후화는 **적되 막지 않는다** — 막는 것은 플래그의 몫이다."""
    m, _ = load_manifest(_write(tmp_path, A3))
    lab = verification_label(m, universe=list("abcdef"), months=84, model="bl",
                             panel="synthetic", code_version="다른-버전")
    assert lab["code_version_matches"] is False
    assert lab["adjudicated"]["code_version"] == "test-version"


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
