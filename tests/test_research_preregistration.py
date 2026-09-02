"""사전등록 지문 — ★결정규칙과 널 **행동**을 해시로 묶는다★ (P6 ①)
==============================================================================
검토서: `docs/specs/2026-09-02-deepseek-concept-review.md` §4 P6 (격차 G2)

`run()` 은 `cost_levels`·`threshold_pct` 를 **파라미터**로 받고 리포트의
`preregistered` 블록은 그때 쓴 값을 그대로 적는다. 즉 그 블록은 ★자기
서술이지 자기 구속이 아니다★ — `cost_levels=(5.0,)` 로 돌리면 리포트가 `[5.0]`
을 "사전등록됨" 이라고 충실히 적는다. 사전등록의 요점은 "무엇을 썼는지" 가
아니라 ★"결과를 보고 바꾸지 않았음"★ 인데 그 증명이 없었다.

그리고 더 큰 구멍: ★널을 **어떻게 만드는가** 는 상수가 아니라 코드다.★
`surrogate_path`·`shifts_for` 가 바뀌면 "널 밖" 의 뜻이 통째로 달라지는데 어떤
상수 해시도 그것을 보지 못한다. 그래서 소스가 아니라 **행동**을 해시한다 —
주석·리팩터에는 반응하지 않고 생성 규칙이 바뀔 때만 바뀐다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.research_preregistration import (  # noqa: E402
    NULL_PROBE,
    compare,
    decision_rule,
    load_registration,
    null_behaviour_fingerprint,
    rule_fingerprint,
)

RULE = dict(primary="sharpe_diff",
            secondary=("cagr_diff", "max_drawdown_pct"),
            cost_levels=(5.0, 10.0, 25.0), threshold_pct=(5.0, 95.0),
            spa_alpha=0.05, decision_rule_text="널 밖 그리고 SPA",
            candidate_arms=("regime-on", "regime-on-prob", "regime-const"),
            primary_null="shift")


# ── 규칙 지문 — ★정준화★ ─────────────────────────────────────────────────
def test_the_same_rule_gives_the_same_fingerprint():
    assert rule_fingerprint(decision_rule(**RULE)) == \
           rule_fingerprint(decision_rule(**RULE))


def test_tuples_and_lists_are_the_same_rule():
    """★정준화★ `(5.0, 10.0)` 과 `[5.0, 10.0]` 은 같은 등록이다 — 직렬화 왕복이
    지문을 깨면 등록 파일을 읽는 순간 드리프트로 오인된다."""
    a = decision_rule(**RULE)
    b = decision_rule(**{**RULE, "cost_levels": [5.0, 10.0, 25.0],
                         "secondary": ["cagr_diff", "max_drawdown_pct"],
                         "candidate_arms": ["regime-on", "regime-on-prob",
                                            "regime-const"]})
    assert rule_fingerprint(a) == rule_fingerprint(b)


def test_a_round_trip_through_json_keeps_the_fingerprint():
    r = decision_rule(**RULE)
    assert rule_fingerprint(json.loads(json.dumps(r))) == rule_fingerprint(r)


def test_integers_and_floats_are_the_same_rule():
    """`5` 와 `5.0` 은 같은 비용 수준이다."""
    a = decision_rule(**{**RULE, "cost_levels": (5, 10, 25)})
    b = decision_rule(**{**RULE, "cost_levels": (5.0, 10.0, 25.0)})
    assert rule_fingerprint(a) == rule_fingerprint(b)


@pytest.mark.parametrize("field,value", [
    ("primary", "cagr_diff"),
    ("cost_levels", (5.0, 10.0)),
    ("threshold_pct", (1.0, 99.0)),
    ("spa_alpha", 0.10),
    ("decision_rule_text", "아무거나"),
    ("candidate_arms", ("regime-on",)),
    ("primary_null", "markov"),
    ("secondary", ("cagr_diff",)),
])
def test_changing_any_registered_field_changes_the_fingerprint(field, value):
    """★짝★ 지문이 무엇에도 반응하지 않으면 그것은 상수다."""
    assert rule_fingerprint(decision_rule(**{**RULE, field: value})) != \
           rule_fingerprint(decision_rule(**RULE))


def test_key_order_does_not_matter():
    r = decision_rule(**RULE)
    assert rule_fingerprint(dict(reversed(list(r.items())))) == rule_fingerprint(r)


# ── 널 **행동** 지문 ─────────────────────────────────────────────────────
def test_the_null_fingerprint_is_stable_within_a_process():
    assert null_behaviour_fingerprint()["fingerprint"] == \
           null_behaviour_fingerprint()["fingerprint"]


def test_the_null_fingerprint_describes_what_it_probed():
    """★지문만 있고 무엇을 쟀는지 없으면 재현할 수 없다★"""
    fp = null_behaviour_fingerprint()
    assert len(fp["fingerprint"]) == 64
    assert fp["probe"]["methods"], "어떤 널을 돌렸는지 안 적었다"
    assert fp["probe"]["seeds"], "어떤 시드로 돌렸는지 안 적었다"
    assert fp["probe"]["n_points"] > 0


def test_the_null_fingerprint_follows_the_generator_not_its_source(monkeypatch):
    """★소스가 아니라 행동을 해시한다★

    주석·이름을 고쳐도 지문이 안 바뀌어야 리팩터가 사전등록을 깨지 않는다.
    반대로 **산출**이 바뀌면 반드시 바뀌어야 한다.
    """
    import src.engine.regime_surrogates as rs
    before = null_behaviour_fingerprint()["fingerprint"]
    real = rs.surrogate_path

    def tweaked(points, method, rng, k=None):
        out = real(points, method, rng, k=k)
        return list(reversed(out))                 # 생성 규칙을 바꾼다

    monkeypatch.setattr(rs, "surrogate_path", tweaked)
    assert null_behaviour_fingerprint()["fingerprint"] != before


def test_the_probe_is_declared_as_a_constant_not_computed_from_results():
    """프로브가 결과에 따라 달라지면 지문이 지문이 아니다."""
    assert isinstance(NULL_PROBE, dict)
    assert NULL_PROBE["seeds"] and NULL_PROBE["methods"]


# ── 등록 로딩과 비교 ─────────────────────────────────────────────────────
def _reg(tmp_path: Path, **over) -> Path:
    reg = {"schema": 1, "rule": decision_rule(**RULE),
           "rule_fingerprint": rule_fingerprint(decision_rule(**RULE)),
           "null_fingerprint": null_behaviour_fingerprint()["fingerprint"],
           "null_probe": NULL_PROBE, "code_version": "test",
           "registered_at": "2026-09-02T00:00:00+00:00", **over}
    p = tmp_path / "prereg.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return p


def test_a_matching_run_reports_no_drift(tmp_path):
    reg, why = load_registration(_reg(tmp_path))
    assert reg is not None and why is None
    out = compare(reg, rule=decision_rule(**RULE),
                  null_fp=null_behaviour_fingerprint()["fingerprint"])
    assert out["matches"] is True
    assert out["drift"] == []


def test_a_changed_cost_grid_is_drift_and_says_so(tmp_path):
    """★이것이 P6 의 존재 이유다★ 다른 격자로 돌린 것이 잡혀야 한다."""
    reg, _ = load_registration(_reg(tmp_path))
    out = compare(reg, rule=decision_rule(**{**RULE, "cost_levels": (5.0,)}),
                  null_fp=null_behaviour_fingerprint()["fingerprint"])
    assert out["matches"] is False
    assert any("결정규칙" in d or "rule" in d for d in out["drift"])


def test_a_changed_null_generator_is_drift(tmp_path):
    reg, _ = load_registration(_reg(tmp_path))
    out = compare(reg, rule=decision_rule(**RULE), null_fp="0" * 64)
    assert out["matches"] is False
    assert any("널" in d for d in out["drift"])


def test_the_drift_names_both_axes_when_both_changed(tmp_path):
    reg, _ = load_registration(_reg(tmp_path))
    out = compare(reg, rule=decision_rule(**{**RULE, "spa_alpha": 0.5}),
                  null_fp="0" * 64)
    assert len(out["drift"]) == 2


def test_a_missing_registration_is_unknown_not_a_match(tmp_path):
    """★미상은 일치가 아니다★"""
    reg, why = load_registration(tmp_path / "nope.json")
    assert reg is None and why and why.strip()
    out = compare(None, rule=decision_rule(**RULE), null_fp="x")
    assert out["matches"] is None
    assert out["reason"] and out["reason"].strip()


def test_a_registration_whose_fingerprint_disagrees_with_its_rule_is_refused(tmp_path):
    """★P5 와 같은 규율★ 기록된 지문이 기록된 규칙에서 안 나오면 위조다."""
    reg, why = load_registration(_reg(tmp_path, rule_fingerprint="0" * 64))
    assert reg is None and why and why.strip()


# ── 커밋된 등록 ──────────────────────────────────────────────────────────
def test_the_committed_registration_matches_the_current_constants():
    """★조용한 재생성을 막는다★ 규칙을 바꾸면 이 테스트가 red 가 되고, 등록
    파일을 다시 만들어 커밋해야 한다 — 그 커밋이 diff 로 검토된다."""
    from src.engine.research_preregistration import REGISTRATION_PATH
    if not REGISTRATION_PATH.exists():
        pytest.skip("등록 파일이 아직 생성되지 않았습니다")
    import scripts.regime_control as rc
    reg, why = load_registration(REGISTRATION_PATH)
    assert reg is not None, f"커밋된 등록이 거부됐다: {why}"
    out = compare(reg, rule=rc.effective_decision_rule(),
                  null_fp=null_behaviour_fingerprint()["fingerprint"])
    assert out["matches"] is True, f"등록이 현재 상수와 다르다: {out['drift']}"


# ── ★정준화 자체를 건다★ ────────────────────────────────────────────────
# 위의 `test_tuples_and_lists_are_the_same_rule` 은 `decision_rule()` 을 거치는데
# 그 함수가 이미 `list(...)`·`float(...)` 로 정규화한다. 그래서 `_canon` 의
# 튜플·정수 분기가 **한 번도 실행되지 않았고** 변이 Y2·Y3 가 살아남았다.
# `rule_fingerprint` 는 공개 함수라 정규화되지 않은 dict 로도 불릴 수 있다.

def _raw(**over) -> dict:
    r = {"primary": "sharpe_diff", "secondary": ["a", "b"],
         "cost_levels": [5.0, 10.0], "threshold_pct": [5.0, 95.0],
         "spa_alpha": 0.05, "decision_rule_text": "t",
         "candidate_arms": ["x"], "primary_null": "shift"}
    r.update(over)
    return r


def test_the_canonicaliser_treats_a_tuple_like_a_list():
    """★`decision_rule` 을 우회해 `_canon` 을 직접 건다★"""
    assert rule_fingerprint(_raw(cost_levels=(5.0, 10.0))) == \
           rule_fingerprint(_raw(cost_levels=[5.0, 10.0]))
    assert rule_fingerprint(_raw(secondary=("a", "b"))) == \
           rule_fingerprint(_raw(secondary=["a", "b"]))


def test_the_canonicaliser_treats_an_int_like_a_float():
    assert rule_fingerprint(_raw(cost_levels=[5, 10])) == \
           rule_fingerprint(_raw(cost_levels=[5.0, 10.0]))
    assert rule_fingerprint(_raw(spa_alpha=1)) == rule_fingerprint(_raw(spa_alpha=1.0))


def test_the_canonicaliser_sorts_nested_dict_keys():
    """중첩 dict 의 키 순서에도 흔들리면 안 된다."""
    a = _raw(decision_rule_text={"b": 1, "a": 2})
    b = _raw(decision_rule_text={"a": 2, "b": 1})
    assert rule_fingerprint(a) == rule_fingerprint(b)


def test_the_canonicaliser_still_separates_genuinely_different_values():
    """★짝★ 모든 것을 같게 만드는 정준화는 정준화가 아니라 지우개다."""
    assert rule_fingerprint(_raw(cost_levels=[5.0, 10.0])) != \
           rule_fingerprint(_raw(cost_levels=[10.0, 5.0]))       # 순서는 뜻이 있다
    assert rule_fingerprint(_raw(spa_alpha=0.05)) != \
           rule_fingerprint(_raw(spa_alpha=0.06))


# ── ★유효 규칙은 실행이 쓴 값에서 온다★ (P6 의 핵심 기제) ────────────────
def test_the_effective_rule_follows_the_parameters_actually_used():
    """★이것이 P6 가 존재하는 이유다★

    예전 `preregistered` 블록은 쓴 값을 그대로 "사전등록됨" 이라 적었다. 유효
    규칙이 모듈 상수만 본다면 다른 격자로 돌려도 드리프트가 안 잡히고, 그러면
    이 작업 전체가 장식이 된다(변이 Y10 이 정확히 그것이다).
    """
    import scripts.regime_control as rc
    default = rc.effective_decision_rule()
    narrowed = rc.effective_decision_rule(cost_levels=(5.0,))
    assert narrowed["cost_levels"] == [5.0]
    assert rule_fingerprint(narrowed) != rule_fingerprint(default)

    widened = rc.effective_decision_rule(threshold_pct=(1.0, 99.0))
    assert widened["threshold_pct"] == [1.0, 99.0]
    assert rule_fingerprint(widened) != rule_fingerprint(default)


def test_a_run_with_a_narrowed_cost_grid_is_detected_as_drift(tmp_path):
    """등록 대비 **실제 실행**이 다르면 잡힌다 — 끝에서 끝까지."""
    import scripts.regime_control as rc
    reg, why = load_registration(
        __import__("src.engine.research_preregistration", fromlist=["x"]
                   ).REGISTRATION_PATH)
    if reg is None:
        pytest.skip(f"등록 파일 없음: {why}")
    out = compare(reg, rule=rc.effective_decision_rule(cost_levels=(5.0,)),
                  null_fp=null_behaviour_fingerprint()["fingerprint"])
    assert out["matches"] is False
    assert any("결정규칙" in d for d in out["drift"])
