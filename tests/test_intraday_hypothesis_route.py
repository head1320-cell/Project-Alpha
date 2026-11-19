"""실행(`/simulate`) · 판정(`/validate`)의 실행 전 가설 · 판정의 자유도 공시(G3 · 구현 계획 §4) — 문이 저장소와 계산을 ★옳게 잇는지★.

- 가설은 선택 칸이다. 처음 적은 것만 시행 줄에 남고, 적을 때의 실행 횟수로 '결과를 보기 전'인지를 가른다. 열쇠에 들지 않는다.
- 화면에서는 판정이 늘 실행 뒤에 온다 — 그래서 실행도 가설을 받는다(실행과 판정은 같은 설정이면 같은 시행이다).
- 개인정보 모양 · 500자 넘는 글은 ★아무것도 읽거나 계산하거나 남기기 전에★ 400 + 사유다. 빈 글은 가설이 없는 것이다.
- 가설을 남기지 못하면 실행은 그대로 답하고 남기지 못했다고 적는다(남긴 것처럼 꾸미지 않는다).
- 자유도 공시는 요청의 규칙 · 포지션과 그 실행의 거래 수로 만든다(`freedom.disclose` 그대로).
- 괴리 보고는 가설을 받지 않는다(모르는 칸은 422 — 조용히 버리지 않는다).
"""
from __future__ import annotations

from src.data import intraday_trials as trials
from src.engine.intraday import freedom
from tests.test_intraday_validate_route import (  # noqa: F401
    BODY,
    SIM,
    VAL,
    auth,
    break_store,
    client,
    login,
    made_days,
    stored_rows,
    with_days,
)

TRIALS = "/api/v1/intraday/trials"
IDEA = "장 초반 5분 고가를 넘으면 그날 매수세가 이어진다고 봅니다."
FIRST = "이 설정의 첫 실행과 함께 적은 가설입니다. 결과를 보기 전에 적었습니다."


def run(client, auth, **extra):
    r = client.post(VAL, json={**BODY, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_hypothesis_sent_with_the_first_run_is_kept_and_said_to_be_written_before_results(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, auth, hypothesis=f"  {IDEA}  ")                          # 앞뒤 공백은 걷는다
    assert out["trial"]["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": True, "message": FIRST}


def test_a_hypothesis_sent_again_does_not_replace_the_first(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    run(client, auth, hypothesis=IDEA)
    again = run(client, auth, hypothesis="결과를 보고 고친 다른 기제")
    assert again["trial"]["runs"] == 2
    assert again["trial"]["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": False,
                                             "message": FIRST + " 처음 적은 가설이 남아 있어 이번에 보낸 글은 저장하지 않았습니다."}


def test_sending_the_same_hypothesis_again_is_not_said_to_be_dropped(client, auth, monkeypatch):
    """짝: 다른 글을 보내면 '저장하지 않았습니다'를 붙인다 ↔ 남은 것과 같은 글이면 잃은 것이 없어 붙이지 않는다(칸을 채운 채 다시 돌리는 흔한 경우)."""
    with_days(monkeypatch, made_days())
    run(client, auth, hypothesis=IDEA)
    again = run(client, auth, hypothesis=f" {IDEA} ")["trial"]["hypothesis"]
    assert again == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": False, "message": FIRST}


def test_an_unknown_writing_run_is_said_to_be_unknown_not_before_results(client, auth, monkeypatch):
    """미상 ≠ 첫 실행 — 적을 때의 실행 횟수 칸이 비어 있으면 '결과를 보기 전'이라고 말하지 않는다."""
    with_days(monkeypatch, made_days())
    key = run(client, auth, hypothesis=IDEA)["trial"]["trial_key"]
    from sqlalchemy import text
    with trials._engine().begin() as c:
        c.execute(text(f"UPDATE {trials._TABLE} SET hypothesis_run = NULL WHERE trial_key = :k"), {"k": key})
    shown = run(client, auth)["trial"]["hypothesis"]
    assert shown == {"text": IDEA, "at_run": None, "before_results": None, "kept_now": False,
                     "message": "가설을 적은 때의 실행 횟수를 알 수 없습니다. 결과를 보기 전에 적었는지 알 수 없습니다."}


def test_a_hypothesis_first_written_after_two_runs_says_it_was_written_after_results(client, auth, monkeypatch):
    """짝: 첫 실행과 함께 적으면 '결과를 보기 전' ↔ 두 번 돌려 본 뒤 처음 적으면 '앞선 실행의 결과를 본 뒤'."""
    with_days(monkeypatch, made_days())
    assert run(client, auth)["trial"]["hypothesis"] is None                      # 가설이 없으면 줄이 없다
    run(client, auth)
    late = run(client, auth, hypothesis=IDEA)["trial"]["hypothesis"]
    assert late == {"text": IDEA, "at_run": 3, "before_results": False, "kept_now": True,
                    "message": "2회 실행한 뒤에 처음 적은 가설입니다. 앞선 실행의 결과를 본 뒤에 적었습니다."}


def test_a_hypothesis_first_written_on_the_second_run_is_already_after_results(client, auth, monkeypatch):
    """경계: '결과를 보기 전'은 적을 때의 실행 횟수가 ★1★ 일 때뿐이다 — 한 번 돌려 본 뒤(2회째)에 처음 적은 글은 이미 결과를 본 뒤다
    (짝: 첫 실행과 함께 적은 글은 '결과를 보기 전' — 위의 첫 시험)."""
    with_days(monkeypatch, made_days())
    run(client, auth)
    second = run(client, auth, hypothesis=IDEA)["trial"]["hypothesis"]
    assert second == {"text": IDEA, "at_run": 2, "before_results": False, "kept_now": True,
                      "message": "1회 실행한 뒤에 처음 적은 가설입니다. 앞선 실행의 결과를 본 뒤에 적었습니다."}


def test_the_hypothesis_is_not_part_of_the_trial__a_run_without_it_still_shows_it(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    first = run(client, auth, hypothesis=IDEA)["trial"]
    plain = run(client, auth)["trial"]
    assert (plain["trial_key"], plain["new"], plain["runs"]) == (first["trial_key"], False, 2)
    assert plain["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": False, "message": FIRST}
    assert stored_rows() == 1


def test_a_pii_shaped_or_too_long_hypothesis_is_refused_before_anything_runs(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    calls: list[int] = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: calls.append(1) or [])
    phone = client.post(VAL, json={**BODY, "hypothesis": "문의 010-1234-5678 로 연락"}, headers=auth)
    assert phone.status_code == 400
    assert phone.json()["detail"]["code"] == "hypothesis_pii" and "전화번호" in phone.json()["detail"]["reason"]
    long_ = client.post(VAL, json={**BODY, "hypothesis": "가" * 501}, headers=auth)
    assert long_.status_code == 400
    assert long_.json()["detail"] == {"code": "hypothesis_too_long", "limit": 500, "length": 501,
                                      "reason": "가설은 500자까지입니다(501자). 기제를 짧게 적어 주십시오."}
    assert calls == [] and stored_rows() == 0
    exactly = client.post(VAL, json={**BODY, "hypothesis": "가" * 500}, headers=auth)     # 짝: 500자는 받는다
    assert exactly.status_code == 200


def test_a_blank_hypothesis_is_no_hypothesis(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    out = run(client, auth, hypothesis="   ")
    assert out["trial"]["hypothesis"] is None
    assert trials.hypotheses_of("alice") == {}


def test_the_trial_list_carries_the_hypothesis_of_each_trial(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    with_idea = run(client, auth, hypothesis=IDEA)["trial"]["trial_key"]
    bare = run(client, auth, position={"amount": 1_000_000, "stop_pct": 1.0})["trial"]["trial_key"]
    listed = {t["trial_key"]: t for t in client.get(TRIALS, headers=auth).json()["trials"]}
    assert listed[with_idea]["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": False, "message": FIRST}
    assert listed[bare]["hypothesis"] is None
    assert client.get(TRIALS, headers=login(client, "bob")).json()["trials"] == []           # 남의 가설은 보이지 않는다


def test_when_the_hypothesis_cannot_be_kept_the_run_still_answers_and_says_so(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    monkeypatch.setattr(trials, "keep_hypothesis", lambda *a, **k: None)
    out = run(client, auth, hypothesis=IDEA)
    assert out["trial"]["recorded"] is True                                       # 시행은 그대로 센다
    assert out["trial"]["hypothesis"] == {"text": None, "at_run": None, "before_results": None, "kept_now": False,
                                          "message": "가설을 저장하지 못했습니다. 시행 기록에 가설 칸이 없거나 읽고 쓰지 못했습니다."}


def test_a_trial_row_that_cannot_be_found_when_keeping_is_said_not_kept(client, auth, monkeypatch):
    """방금 남긴 시행 줄을 가설을 남길 때 찾지 못하면(그사이 지워짐 등) 남겼다고 꾸미지 않는다 — 남기지 못한 것과 같은 줄이다."""
    with_days(monkeypatch, made_days())
    monkeypatch.setattr(trials, "keep_hypothesis", lambda *a, **k: {"found": False})
    out = run(client, auth, hypothesis=IDEA)
    assert out["trial"]["hypothesis"]["text"] is None
    assert out["trial"]["hypothesis"]["message"].startswith("가설을 저장하지 못했습니다.")


def test_an_unreadable_hypothesis_is_not_the_same_as_no_hypothesis(client, auth, monkeypatch):
    """짝: 가설 칸을 읽지 못하면 '없음'(None)이 아니라 읽지 못했다는 줄이다."""
    with_days(monkeypatch, made_days())
    monkeypatch.setattr(trials, "hypotheses_of", lambda *a, **k: None)
    out = run(client, auth)
    assert out["trial"]["hypothesis"] == {"text": None, "at_run": None, "before_results": None, "kept_now": False,
                                          "message": "실행 전 가설을 읽지 못했습니다. 시행 기록에 가설 칸이 없거나 읽지 못했습니다."}
    listed = client.get(TRIALS, headers=auth).json()["trials"]
    assert listed and all(t["hypothesis"]["message"].startswith("실행 전 가설을 읽지 못했습니다.") for t in listed)


def test_a_hypothesis_sent_with_the_first_simulate_run_is_before_results_in_the_later_verdict(client, auth, monkeypatch):
    """화면의 흐름 — 설정 칸에 가설을 적고 '실행'(1회) → 결과를 본 뒤 '판정'(2회). 판정이 보이는 가설은 실행과 함께 적은 것이다."""
    with_days(monkeypatch, made_days())
    r = client.post(SIM, json={**BODY, "hypothesis": IDEA}, headers=auth)
    assert r.status_code == 200, r.text
    sim = r.json()["trial"]
    assert sim["runs"] == 1
    assert sim["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": True, "message": FIRST}
    verdict = run(client, auth)["trial"]
    assert (verdict["trial_key"], verdict["runs"]) == (sim["trial_key"], 2)          # 실행과 판정은 같은 시행
    assert verdict["hypothesis"] == {"text": IDEA, "at_run": 1, "before_results": True, "kept_now": False, "message": FIRST}


def test_a_simulate_run_without_a_hypothesis_says_none_and_a_broken_store_says_unknown(client, auth, monkeypatch):
    """짝: 가설이 없으면 `None` ↔ 시행을 남기지 못하면(가설도 읽지 못했다) `None` 이 아니라 읽지 못했다는 줄."""
    with_days(monkeypatch, made_days())
    assert client.post(SIM, json=BODY, headers=auth).json()["trial"]["hypothesis"] is None
    break_store(monkeypatch)
    broken = client.post(SIM, json={**BODY, "hypothesis": IDEA}, headers=auth).json()["trial"]
    assert broken["recorded"] is False
    assert broken["hypothesis"] == {"text": None, "at_run": None, "before_results": None, "kept_now": False,
                                    "message": "가설을 저장하지 못했습니다. 시행 기록에 가설 칸이 없거나 읽고 쓰지 못했습니다."}


def test_a_pii_shaped_hypothesis_on_a_simulate_run_is_refused_before_anything_runs(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    calls: list[int] = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: calls.append(1) or [])
    r = client.post(SIM, json={**BODY, "hypothesis": "메일 trader@example.com 으로"}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "hypothesis_pii"
    assert "이메일" in r.json()["detail"]["reason"]
    assert calls == [] and stored_rows() == 0


def test_the_divergence_report_does_not_take_a_hypothesis(client, auth, monkeypatch):
    """괴리 보고는 이미 있는 시행과 실제 체결을 견준다 — 가설 칸이 없다. 보내면 모르는 칸으로 거절한다(조용히 버리지 않는다)."""
    r = client.post("/api/v1/intraday/divergence", json={**BODY, "fills": [], "hypothesis": IDEA}, headers=auth)
    assert r.status_code == 422
    assert any(e["type"] == "extra_forbidden" and e["loc"][-1] == "hypothesis" for e in r.json()["detail"])


def test_the_freedom_message_is_the_last_fact_of_the_multiplicity_gate(client, auth, monkeypatch):
    """판정의 관문 표가 공시를 싣는다(캔버스의 결과 판도 같은 표를 보인다) — 상태는 확률(DSR)의 것 그대로다."""
    with_days(monkeypatch, made_days())
    out = run(client, auth)
    gate = next(g for g in out["gates"]["gates"] if g["key"] == "multiplicity")
    assert gate["facts"][-1] == out["freedom"]["message"]


def test_the_templates_route_tells_the_screen_the_hypothesis_limit(client, auth):
    """화면의 글자 수 상한은 서버의 것이다(화면이 500 을 지어내지 않는다)."""
    import src.api.intraday_routes as mod
    limits = client.get("/api/v1/intraday/templates", headers=auth).json()["limits"]
    assert limits["hypothesis_chars"] == mod.HYPOTHESIS_MAX == 500


def test_the_freedom_disclosure_is_built_from_the_request_and_the_trades(client, auth, monkeypatch):
    """시가 범위 돌파(값 1) + 포지션의 정한 칸(종목당 진입 수 기본값 1) = 둘 · 거래는 그 실행의 요약과 같은 수."""
    with_days(monkeypatch, made_days())
    out = run(client, auth)
    trades = out["summary"]["trades"]
    assert trades == 10
    want = freedom.disclose("opening_range_breakout", {"minutes": 5},
                            {"amount": 1_000_000, "max_entries_per_ticker": 1}, trades=trades)
    assert out["freedom"] == want
    assert out["freedom"]["message"] == "조정 가능한 값 2개(규칙 1 · 포지션 1) · 거래 10건 · 값 하나당 거래 5.0건입니다."
