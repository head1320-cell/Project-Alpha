"""사용 시점 사다리 게이트 (P2-G)
==============================================================================
`auto_alpha.py` 도크스트링은 "레지스트리 승급 사다리를 그대로 통과해야 실전 사용" 이라고
적어 두었다. 그런데 실측하니 그 검사는 **승격할 때만** 있었다:

  · `promote_alpha` — 순서·요건 검사 있음
  · "이 알파로 포트폴리오를 만들어도 되는가" — **아무 데서도 묻지 않음**

그래서 `alphalab/page.tsx` 의 "상위 10종목 → 포트폴리오" 버튼은 검증 리포트만 있으면
`draft` 표현식으로도 보유 종목을 만들 수 있었다. 이 파일이 그 구멍을 지킨다.
"""

from __future__ import annotations

import pytest

from src.data.alpha_registry import (
    USABLE_STATUS,
    promote_alpha,
    upsert_alpha,
    usable_for_portfolio,
)


def _alpha(status: str) -> dict:
    return {"alpha_id": "a1", "name": "t", "expr": "rank(mom_1m)", "status": status}


# ── 1. ★approved 만 통과한다★ ───────────────────────────────────────────────

def test_only_approved_may_build_a_portfolio():
    ok, reason = usable_for_portfolio(_alpha(USABLE_STATUS))
    assert ok is True and reason is None


@pytest.mark.parametrize("status", ["draft", "experimental", "validated", "retired"])
def test_every_other_status_is_refused(status):
    ok, reason = usable_for_portfolio(_alpha(status))
    assert ok is False, f"{status} 가 통과했다"
    assert reason, "사유 없는 거부"
    assert status in reason or "폐기" in reason, reason


def test_the_refusal_names_the_next_step_not_just_the_wall():
    """막힌 사람이 무엇을 해야 하는지 알 수 없으면 그 거부는 절반만 정직하다."""
    _, reason = usable_for_portfolio(_alpha("experimental"))
    assert "validated" in reason, reason
    assert "draft → experimental → validated → approved" in reason


def test_a_missing_alpha_is_refused_not_treated_as_draft():
    ok, reason = usable_for_portfolio(None)
    assert ok is False and "찾을 수 없" in reason


# ── 2. 사다리를 실제로 올라가야 approved 가 된다 (레지스트리 왕복) ──────────

def test_the_ladder_must_actually_be_climbed_to_become_usable():
    """★한 번에 approved 로 뛸 수 없다★ 그리고 각 단계마다 요건이 있다.

    이 테스트가 도는 환경에는 approved 알파가 하나도 없다(실측 0건). 그래서 사용
    가능한 알파를 만들려면 사다리를 실제로 올라야 하고, 이 단언이 그 경로가 살아
    있는지 함께 확인한다.
    """
    # ★`upsert_alpha` 는 id 가 아니라 **알파 dict** 를 돌려준다★ (실측)
    # id 문자열로 착각하면 SQLite 가 dict 를 바인딩하려다 죽는다 — 조용히 통과하지
    # 않고 바로 터지는 쪽이라 다행이지만, 반환 계약을 읽고 쓰는 것이 먼저다.
    created = upsert_alpha(None, "게이트 테스트", "rank(mom_1m)", status="draft")
    if not created:
        pytest.skip("레지스트리 저장소를 쓸 수 없는 환경")
    aid = created["alpha_id"]

    from src.data.alpha_registry import delete_alpha, get_alpha
    try:
        # 직행 금지
        jump = promote_alpha(aid, "approved", note="바로 승인")
        assert jump["ok"] is False and "직행 불가" in jump["reason"]
        assert usable_for_portfolio(get_alpha(aid))[0] is False

        assert promote_alpha(aid, "experimental")["ok"] is True
        assert usable_for_portfolio(get_alpha(aid))[0] is False

        # validated 는 검증 런이 있어야 한다 — 없으면 사유와 함께 막힌다.
        no_run = promote_alpha(aid, "validated")
        assert no_run["ok"] is False and "검증" in no_run["reason"]

        from src.data.alpha_registry import attach_validation
        attach_validation(aid, "rr_stub_gate_0001")
        assert promote_alpha(aid, "validated")["ok"] is True
        assert usable_for_portfolio(get_alpha(aid))[0] is False, "validated 가 통과했다"

        # approved 는 승인 노트가 필수 — 사람의 판단이 기록에 남는다.
        no_note = promote_alpha(aid, "approved")
        assert no_note["ok"] is False and "노트" in no_note["reason"]

        assert promote_alpha(aid, "approved", note="P2-G 게이트 테스트")["ok"] is True
        ok, reason = usable_for_portfolio(get_alpha(aid))
        assert ok is True and reason is None
    finally:
        delete_alpha(aid)


# ── 3. 라우트 — 게이트가 화면 요청에도 적용된다 ─────────────────────────────

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture()
def approved_alpha():
    """사다리를 실제로 올려 approved 알파를 하나 만든다 (테스트 후 삭제)."""
    from src.data.alpha_registry import attach_validation, delete_alpha
    created = upsert_alpha(None, "P2-R 라우트", "rank(mom_12_1)", status="draft")
    if not created:
        pytest.skip("레지스트리 저장소를 쓸 수 없는 환경")
    aid = created["alpha_id"]
    promote_alpha(aid, "experimental")
    attach_validation(aid, "rr_stub_route_0001")
    promote_alpha(aid, "validated")
    promote_alpha(aid, "approved", note="P2-R 라우트 테스트")
    yield aid
    delete_alpha(aid)


@pytest.fixture()
def twin_alpha():
    """`approved_alpha` 와 **같은 식**을 가진 별개의 approved 알파 — ρ=1 을 만든다."""
    from src.data.alpha_registry import attach_validation, delete_alpha
    created = upsert_alpha(None, "P2-R 쌍둥이", "rank(mom_12_1)", status="draft")
    if not created:
        pytest.skip("레지스트리 저장소를 쓸 수 없는 환경")
    aid = created["alpha_id"]
    promote_alpha(aid, "experimental")
    attach_validation(aid, "rr_stub_twin_0001")
    promote_alpha(aid, "validated")
    promote_alpha(aid, "approved", note="쌍둥이 테스트")
    yield aid
    delete_alpha(aid)


@pytest.fixture()
def draft_alpha():
    from src.data.alpha_registry import delete_alpha
    created = upsert_alpha(None, "P2-R 초안", "rank(mom_1m)", status="draft")
    if not created:
        pytest.skip("레지스트리 저장소를 쓸 수 없는 환경")
    yield created["alpha_id"]
    delete_alpha(created["alpha_id"])


def _post(client, **kw):
    body = {"universe": "kospi50", "top_k": 8, "record_run": False}
    body.update(kw)
    return client.post("/api/v1/alpha-lab/portfolio", json=body)


def test_an_unapproved_alpha_blocks_the_whole_portfolio(client, draft_alpha):
    """★하나라도 막히면 계획을 만들지 않는다★ 나머지로 조용히 진행하지 않는다."""
    r = _post(client, alphas=[{"alpha_id": draft_alpha, "weight": 1.0}])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False
    assert b["blocked"][0]["alpha_id"] == draft_alpha
    assert "approved" in b["blocked"][0]["reason"]
    assert "base_weights" not in b, "막혔는데 비중을 냈다"


def test_an_approved_alpha_produces_base_weights_that_close(client, approved_alpha):
    r = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0}])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is True, b.get("reason")
    w = b["base_weights"]
    assert len(w) == 8
    assert sum(w.values()) == pytest.approx(100.0, abs=0.5)
    assert all(v > 0 for v in w.values()), "롱온리 목표에 음수/0 이 있다"
    # 실행으로 바로 가지 않는다 — 목표(base)까지다.
    assert "tpv_id" not in b and "final_weights" not in b


def test_the_route_stamps_as_of_even_when_not_requested(client, approved_alpha):
    r = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0}])
    b = r.json()
    assert b["as_of_requested"] is None
    assert b["as_of_effective"], "as_of 스탬프가 없다 — 재현 좌표가 없다"


def test_a_past_as_of_changes_the_portfolio(client, approved_alpha):
    """★짝 단언★ 스탬프만 있고 실제로 안 쓰이면 재현은 거짓이다."""
    late = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0}]).json()
    early = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0}],
                  as_of="2025-06-30").json()
    assert early["available"] is True, early.get("reason")
    assert early["as_of_effective"] < late["as_of_effective"]
    assert early["holdings"] != late["holdings"], "as_of 가 결과를 바꾸지 않는다"


def test_the_same_alpha_id_twice_is_refused_not_silently_merged(client, approved_alpha):
    """★같은 알파를 두 번 넣으면 거부한다★ (이 단언이 실제 결함을 찾아냈다)

    첫 구현은 `alpha_id` 로 키를 잡아 **뒤엣것이 앞엣것을 덮었다**. 가중치 1+1 을
    지정했는데 실제로는 1 로 계산되고 화면은 알 길이 없었다 — 조용한 재정규화와 같은
    결함 계열이다. 의도를 추측해 합치지 않고 무엇이 중복인지 적어 되돌려 준다.
    """
    r = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0},
                              {"alpha_id": approved_alpha, "weight": 1.0}])
    b = r.json()
    assert b["available"] is False
    assert approved_alpha in b["reason"] and "여러 번" in b["reason"]


def test_two_equivalent_alphas_are_reported_as_one_effective_bet(client, approved_alpha,
                                                                 twin_alpha):
    """서로 다른 id 인데 같은 식이면 ρ=1 — 분산했다고 믿는 배합이 한 베팅이다."""
    r = _post(client, alphas=[{"alpha_id": approved_alpha, "weight": 1.0},
                              {"alpha_id": twin_alpha, "weight": 1.0}])
    b = r.json()
    assert b["available"] is True, b.get("reason")
    assert b["effective_n"] == pytest.approx(1.0, abs=0.05)
    assert any("같은 베팅" in w for w in b["warnings"]), b["warnings"]


def test_an_unknown_alpha_id_is_blocked_not_ignored(client):
    r = _post(client, alphas=[{"alpha_id": "al_does_not_exist", "weight": 1.0}])
    b = r.json()
    assert b["available"] is False
    assert "찾을 수 없" in b["blocked"][0]["reason"]
