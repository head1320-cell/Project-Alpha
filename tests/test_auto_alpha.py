"""AutoAlpha 후보 생성 샌드박스 검증 (Full Expansion P6 — Experimental)

핵심 주장(거버넌스):
  · 생성 후보는 전부 파싱·린트 통과(유효 알파). 결정론적(seed 고정).
  · 유전 모드는 씨앗에서 변이/교배. 중복·기존과 겹침 제거.
  · ★스테이징은 experimental 상태로만★ — 절대 validated/approved로 올리지 않음(자동 채택 금지).
  · 선택편향(다중검정) 경고가 후보 수에 따라 증가(정직한 과적합 경고).
  · 카탈로그: 대체데이터·텍스트·RL은 미연결(정직), AutoAlpha만 연결.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")
import pytest  # noqa: E402

from src.engine import auto_alpha as aa  # noqa: E402
from src.engine.alpha_lab import parse_alpha  # noqa: E402


def test_generated_candidates_are_valid_and_deterministic():
    r1 = aa.generate_candidates(n=10, seed=42, mode="random")
    r2 = aa.generate_candidates(n=10, seed=42, mode="random")
    assert r1["generated"] >= 1
    # 결정론(같은 seed → 같은 후보)
    assert [c["expr"] for c in r1["candidates"]] == [c["expr"] for c in r2["candidates"]]
    # 전부 파싱 성공(유효 알파)
    for c in r1["candidates"]:
        parse_alpha(c["expr"])   # raise 없으면 통과
    # 자동 채택 금지 거버넌스 노출
    assert r1["governance"]["auto_adopt"] is False
    assert r1["governance"]["status_ceiling"] == "experimental"


def test_no_duplicates_and_respects_existing():
    existing = ["rank(mom_12_1)", "zscore(roe)"]
    r = aa.generate_candidates(n=12, seed=1, mode="random", existing=existing)
    exprs = [c["expr"].replace(" ", "") for c in r["candidates"]]
    assert len(exprs) == len(set(exprs))                      # 내부 중복 없음
    for e in existing:
        assert e.replace(" ", "") not in exprs                # 기존과 안 겹침


def test_genetic_mode_mutates_from_seeds():
    seeds = ["rank(mom_12m)", "zscore(roe)"]
    r = aa.generate_candidates(n=8, seed=7, mode="genetic", seeds=seeds)
    assert r["mode"] == "genetic"
    assert r["generated"] >= 1
    for c in r["candidates"]:
        parse_alpha(c["expr"])
    # 씨앗이 없으면 random으로 폴백(정직)
    r0 = aa.generate_candidates(n=5, seed=7, mode="genetic", seeds=[])
    assert r0["mode"] == "random"


def test_selection_bias_note_grows_with_n():
    small = aa.selection_bias_note(4)
    big = aa.selection_bias_note(100)
    assert big["expected_max_z"] > small["expected_max_z"]    # 더 많이 탐색 → 편향 큼
    assert big["n_trials"] == 100


def test_stage_clamps_to_experimental_only():
    """★거버넌스 핵심★: 스테이징은 무슨 일이 있어도 experimental 이상으로 안 올라간다."""
    seen_status = []

    def fake_upsert(alpha_id, name, expr, description, universe="kospi200",
                    status="draft", tags=None, **kw):
        seen_status.append(status)
        return {"alpha_id": f"al_fake_{len(seen_status)}", "expr": expr, "status": status}

    res = aa.stage_candidates(["rank(mom_12m)", "zscore(roe)"], upsert=fake_upsert)
    assert res["n_staged"] == 2
    # upsert에 넘어간 status가 전부 experimental (validated/approved 절대 아님)
    assert seen_status == ["experimental", "experimental"]
    assert all(s["status"] == "experimental" for s in res["staged"])
    assert res["governance"]["auto_adopt"] is False


def test_stage_rejects_lint_errors():
    calls = []

    def fake_upsert(*a, **k):
        calls.append(1)
        return {"alpha_id": "x", "expr": a[2], "status": "experimental"}

    # "mom_12m / 0" → 0나누기 error 린트 → 스테이징 거부(upsert 미호출)
    res = aa.stage_candidates(["rank(mom_12m)", "mom_12m / 0"], upsert=fake_upsert)
    assert res["n_staged"] == 1 and len(res["rejected"]) == 1
    assert len(calls) == 1


def test_catalog_honest_connected_flags():
    cat = {f["id"]: f for f in aa.experimental_catalog()}
    assert cat["auto_alpha"]["connected"] is True
    assert cat["genetic_search"]["connected"] is True
    # 대체데이터·텍스트·RL은 미연결(정직 — 데이터/인프라 부재)
    for fid in ("alt_data_events", "text_disclosure", "rl_allocation"):
        assert cat[fid]["connected"] is False
        assert cat[fid]["kind"] == "not_connected"


# ═══════════════════════════════════════════════════════════════════════════
# AJ1 ★골든★ — `selection_bias_note` 를 `multiplicity.expected_max_z` 로
# 위임했다. 산수는 한 곳에만 있어야 하는데, 그 이동이 **응답 계약을 건드리면
# 안 된다**: 프런트(`entities/experimental/api.ts:26`)가 세 키를 그대로 읽고
# `AutoAlphaLab.tsx:76` 이 `note` 를 화면에 찍는다.
# ═══════════════════════════════════════════════════════════════════════════

_BIAS_GOLDEN = {
    1: (0.0, "1개 후보를 탐색해 최고를 고르면 최고 IC의 t-stat은 약 +0.0σ"),
    4: (1.67, "4개 후보를 탐색해 최고를 고르면 최고 IC의 t-stat은 약 +1.67σ"),
    100: (3.03, "100개 후보를 탐색해 최고를 고르면 최고 IC의 t-stat은 약 +3.03σ"),
}


@pytest.mark.parametrize("n", sorted(_BIAS_GOLDEN))
def test_selection_bias_note_keeps_its_contract(n):
    """★위임해도 모양·값이 그대로★ — 키 셋, 반올림, 문장 머리."""
    z, head = _BIAS_GOLDEN[n]
    got = aa.selection_bias_note(n)
    assert set(got) == {"n_trials", "expected_max_z", "note"}
    assert got["n_trials"] == n
    assert got["expected_max_z"] == z
    assert got["note"].startswith(head)
    assert "자동 보정되지 않습니다" in got["note"]


def test_selection_bias_note_agrees_with_the_shared_arithmetic():
    """★산수가 두 곳에 있으면 한쪽만 고쳐도 아무 테스트가 안 깨진다★"""
    from src.domain.multiplicity import expected_max_z
    for n in (2, 7, 50, 1000):
        assert aa.selection_bias_note(n)["expected_max_z"] == round(expected_max_z(n), 2)
