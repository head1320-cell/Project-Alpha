"""배분 API 응답 계약 — ★서비스 추출 **전에** 못 박는다★ (P8 ①)

이 파일은 `tests/test_route_parity.py` 와 같은 규율로 존재한다. 그 파일 첫머리가
`timing_routes.py` 분리 때 적어 둔 문장이 여기에도 그대로 적용된다:

    "이동한 뒤에 스냅샷을 뜨면 '지금 상태' 를 기록할 뿐이고, 그 사이에 사라진
     것은 영원히 안 보인다."

그래서 P8 의 **첫 커밋은 소스를 한 줄도 바꾸지 않는다.** 여기서 뜬 키 집합과 관문
동작이 추출·분리 뒤에도 같아야 한다 — 그것이 "행동 불변" 의 뜻이다.

★키는 서버에서 뜬다★ 프론트의 `AnalyzeResult`(`frontend/src/entities/allocation/
api.ts:105`) 타입에서 뜨지 않는다. 그 타입에는 서버가 실제로 보내는
`risk_contributions_basis` · `risk_contribution_optimized` · `unknown_tickers` ·
`conditional` · `target_range` · `company_views` 가 없다. 타입에서 뜨면 그 여섯
개는 골든 밖으로 사라지고, 사라진 줄도 모른 채 통과한다.

★키를 **정확히** 건다(부분집합이 아니라)★ 빠진 키만 잡으면 추출 중에 늘어난 키를
못 본다. 의도해서 키를 늘렸다면 **그 커밋에서 이 목록도 같이 고치는 것**이 맞다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

ANALYZE = "/api/v1/allocation/analyze"
DECIDE = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _analyze(client, **kw) -> dict:
    body = {"tickers": TICKERS, "lookback_days": 500, "mc_paths": 100}
    body.update(kw)
    r = client.post(ANALYZE, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _decide(client, **kw) -> dict:
    body = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000.0, "model": "mvo"}
    body.update(kw)
    r = client.post(DECIDE, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── 골든 키 집합 (추출 전 서버 실측) ──────────────────────────────────────
ANALYZE_KEYS = {
    "cap_missing", "constraints_report", "correlation", "coverage", "enb", "ep",
    "error", "excluded", "flow", "frontier", "labels", "mc", "mes", "model",
    "mu_engine", "names", "params", "points", "risk_contribution_optimized",
    "risk_contributions", "risk_contributions_basis", "skipped_views", "summary",
    "unknown_tickers", "views_applied", "weights",
}
#: ★요청했을 때만 키가 늘어난다★ — 라우트가 스스로 그렇게 적고 있다.
ANALYZE_CONDITIONAL_EXTRA = {"conditional", "target_range"}
ANALYZE_COMPANY_EXTRA = {"company_views"}
ANALYZE_ERROR_KEYS = {"error", "excluded", "message"}

DECIDE_KEYS = {
    "available", "band", "benefit", "conditional", "cost", "coverage", "dec_id",
    "decision", "excluded", "factors", "gradual", "hysteresis_mult",
    "max_gap_pct", "model", "mu_uncertainty", "net_pct", "persist_reason",
    "persisted", "reason", "research_context", "risk_model", "target_source",
    "target_weights", "threshold_pct", "triggers", "unknown_tickers",
}
#: 자산 <2 조기반환. ★모든 분기가 같은 키를 낸다★ 는 규율이 여기에도 있다
#: (`dec_id`·`persisted`·`persist_reason` — `test_decision_route_delegation` 참고).
DECIDE_EARLY_KEYS = {
    "available", "dec_id", "decision", "excluded", "persist_reason", "persisted",
    "reason", "research_context",
}

CONDITIONAL_KEYS = {
    "A_contribution_pct", "applied_to", "available", "confidence_model",
    "degenerate", "diagnostics", "dropped_regimes", "h_hold", "method",
    "min_obs_required", "mixture_note", "mode", "n_months", "n_months_by_regime",
    "n_obs", "n_obs_by_regime", "not_applied_to", "note", "path_note",
    "path_source", "pi_bar", "pi_path", "pit", "probability_source", "reason",
    "regime", "regime_weighting", "requested", "sharpness", "shrinkage_lambda",
    "unlabeled_obs", "verification", "view_confidence",
}
VERIFICATION_KEYS = {
    "adjudicated", "blocked", "blocked_reason", "code_version_matches",
    "evidence", "evidence_grade", "evidence_grade_reason", "mechanism_verdict",
    "passed", "reason", "scope", "this_request_verified", "why",
}


def test_analyze_top_level_keys(client):
    assert set(_analyze(client)) == ANALYZE_KEYS


def test_analyze_conditional_adds_exactly_two_keys(client):
    """★짝★ 조건부를 켜면 정확히 두 개가 늘어난다 — 더도 덜도 아니다."""
    assert set(_analyze(client, conditional=True)) == \
        ANALYZE_KEYS | ANALYZE_CONDITIONAL_EXTRA


def test_analyze_company_views_add_exactly_one_key(client):
    assert set(_analyze(client, use_company_views=True)) == \
        ANALYZE_KEYS | ANALYZE_COMPANY_EXTRA


def test_analyze_below_two_assets_returns_the_honest_error_shape(client):
    b = _analyze(client, tickers=["005930"])
    assert set(b) == ANALYZE_ERROR_KEYS
    assert b["error"] is True and b["message"]


def test_decide_top_level_keys(client):
    assert set(_decide(client)) == DECIDE_KEYS


def test_decide_keys_do_not_change_with_conditional(client):
    """이 라우트는 `conditional` 키를 **언제나** 낸다(끄면 `None`).

    ★모든 분기가 같은 키를 낸다★ 는 이 라우트의 규율이라, 조건부 스위치가 키
    집합을 바꾸면 그 규율이 깨진 것이다.
    """
    b = _decide(client, model="bl", conditional=True)
    assert set(b) == DECIDE_KEYS
    assert b["conditional"] is not None
    assert _decide(client)["conditional"] is None


def test_decide_below_two_assets_keeps_the_decision_keys(client):
    b = _decide(client, tickers=["005930"], holdings={"005930": 100.0})
    assert set(b) == DECIDE_EARLY_KEYS
    assert b["available"] is False and b["persist_reason"]


def test_the_conditional_block_shape_is_pinned_on_both_routes(client):
    """조건부 블록은 두 라우트가 **같은 헬퍼**로 만든다 — 모양이 갈리면 안 된다."""
    a = _analyze(client, model="bl", conditional=True)["conditional"]
    d = _decide(client, model="bl", conditional=True)["conditional"]
    for blk in (a, d):
        assert set(blk) == CONDITIONAL_KEYS
        assert set(blk["verification"]) == VERIFICATION_KEYS
    assert set(a) == set(d), "두 화면의 조건부 블록이 갈렸다"


# ══════════════════════════════════════════════════════════════════════════
# ★관문을 값으로 잰다★ (P8 ① — AST 검사를 대체하는 것이 아니라 **위에 얹는다**)
# ══════════════════════════════════════════════════════════════════════════
#
# `test_research_manifest.py` 의 두 가드는 `run_analyze`·`rebalance_decision_route`
# 의 **소스를 AST 로** 뜯어본다. 그때는 값으로 잴 방법이 없어 구조로 건 차선책이었다
# (그 테스트 주석이 그렇게 적고 있다). P5 ③ 의 플래그가 생긴 지금은 값으로 잴 수
# 있고, 값으로 재면 ★파일을 어디로 옮기든 살아남는다★.
#
# 전제: 커밋된 판정 메니페스트(`docs/specs/macro_gate_verdict.json`)가 통과가
# 아니라는 것. 언젠가 통과로 바뀌면 이 테스트들은 **크게 실패**하고, 그때는 전제를
# 다시 세워야 한다 — 조용히 공허해지지 않는다.

def _gate_pair(fn, client, **kw) -> tuple[dict, dict]:
    """관문 끈 응답, 켠 응답."""
    return (fn(client, model="bl", conditional=True,
               require_verified_macro=False, **kw),
            fn(client, model="bl", conditional=True,
               require_verified_macro=True, **kw))


def _assert_gate_premise(open_body: dict) -> None:
    """★공허 방지★ 차단 안 한 실행이 조건부를 **실제로 적용**했어야 한다.

    적용된 것이 없으면 "차단하니 숫자가 달라졌다" 를 잴 수 없고, 그런데도 통과하는
    테스트는 아무것도 막지 않는다.
    """
    ap = open_body["conditional"]["applied_to"]
    assert ap["sigma"] is True or ap["mu_as_views"] > 0, (
        "조건부가 애초에 적용되지 않아 이 테스트는 공허하다 — "
        f"applied_to={ap}, reason={open_body['conditional'].get('reason')}")


def test_the_gate_actually_changes_the_analyze_weights(client):
    """★차단했다고 **말만** 하고 그대로 쓰면 응답이 거짓말을 한다★ (변이 X7)

    순수 규칙 테스트로는 잡히지 않는다 — 규칙은 옳게 답하기 때문이다. 숫자를 본다.
    """
    opened, gated = _gate_pair(_analyze, client)
    _assert_gate_premise(opened)
    assert opened["conditional"]["verification"]["blocked"] is False
    v = gated["conditional"]["verification"]
    assert v["blocked"] is True, "판정이 통과로 바뀌었다면 이 전제를 다시 세우라"
    assert v["blocked_reason"]
    assert gated["conditional"]["applied_to"] == {"sigma": False, "mu_as_views": 0}
    assert gated["weights"]["optimized"] != opened["weights"]["optimized"], \
        "차단했다는데 가중치가 같다 — 조건부 입력이 실제로 버려지지 않았다"


def test_the_gate_actually_changes_the_decision_targets(client):
    """★두 라우트 모두★ — 한쪽만 막으면 두 화면이 다른 근거로 판단한다."""
    opened, gated = _gate_pair(_decide, client)
    _assert_gate_premise(opened)
    assert opened["conditional"]["verification"]["blocked"] is False
    v = gated["conditional"]["verification"]
    assert v["blocked"] is True, "판정이 통과로 바뀌었다면 이 전제를 다시 세우라"
    assert gated["conditional"]["applied_to"] == {"sigma": False, "mu_as_views": 0}
    assert gated["target_weights"] != opened["target_weights"], \
        "차단했다는데 목표 비중이 같다 — 조건부 입력이 실제로 버려지지 않았다"


def test_the_flag_is_off_by_default_on_both_routes(client):
    """★짝★ 항상 차단하면 그것은 관문이 아니라 차단기다. 기본은 라벨링뿐이다."""
    for body in (_analyze(client, model="bl", conditional=True),
                 _decide(client, model="bl", conditional=True)):
        v = body["conditional"]["verification"]
        assert v["blocked"] is False
        assert v["blocked_reason"] is None
