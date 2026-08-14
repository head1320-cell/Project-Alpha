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
