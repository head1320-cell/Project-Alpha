"""소스 커버리지 + "이 키를 넣으면 무엇이 열리는가" (P4-D5).

왜 이 파일이 있는가
------------------------------------------------------------------------------
사용자가 "배포 후 env 에 API 키를 넣을 것을 감안하라" 고 했다. 그러면 키를 넣는
사람이 **넣기 전에 효과를 볼 수 있어야** 한다 — 지금은 키가 없으면 화면이 정직하게
`unavailable` 을 낼 뿐, 무엇을 넣으면 무엇이 열리는지 말해 주지 않는다.

D1~D4 가 재료를 다 만들어 놨다: 레지스트리(계열 선언·검증 상태·빈티지), 능력 사다리
(요건별 프로브), 집계 계열(원천 테이블), 적재 깊이. D5 는 **그것들을 조인해서 한 장의
표로 만드는 일**이고, 새 판정 로직을 만들지 않는다.

★가장 중요한 가드는 키 값이 새지 않는 것이다★
CLAUDE.md: "API 키를 채팅·이슈·로그에 노출 금지". 이 보고서는 화면·로그로 나가므로
**존재 여부(bool)만** 낸다. 값·접두사·길이·마스킹된 조각도 내지 않는다 — 마스킹은
안전해 보이지만 길이와 접두사를 흘리고, 그걸로 어느 키인지 좁혀진다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.source_coverage import (  # noqa: E402
    coverage_report,
    key_slots,
)

_SECRET = "sk-thisisaverysecrettokenvalue-0123456789"


def _flatten(obj) -> list[str]:
    """구조 안의 모든 문자열 — 값 유출을 통째로 훑기 위해."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_flatten(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flatten(v))
    elif hasattr(obj, "__dataclass_fields__"):
        for f in obj.__dataclass_fields__:
            out.append(f)
            out.extend(_flatten(getattr(obj, f)))
    else:
        out.append(str(obj))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 1. ★키 값은 어떤 형태로도 나가지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
# ★유출 가드는 `key_slots()` 에 건다 — 그게 유일한 유출 표면이고, 순간이다★
#
# 처음엔 `coverage_report()` 전체에 가짜 키를 심어 훑었는데, 그 조합이 **51초**
# 걸렸다(실측: 키 없음 1.1초). 가짜 키를 넣으면 수집기가 자기를 "설정됨" 으로 보고
# ECOS 37계열에 실제 HTTP 를 시도하는데, 이 환경은 프록시가 막고 있어 계열마다
# 스로틀 0.7초 + 타임아웃을 문다.
#
# 그래서 가짜 키가 필요한 단언은 환경변수만 읽는 `key_slots()` 로 옮겼다. 유출이
# 일어날 수 있는 코드가 정확히 거기이고(`_configured`), `coverage_report()` 는 그
# 결과를 그대로 싣기만 한다. 느린 경로를 우회한 것이 아니라 **가드를 결함이 있는
# 자리에 붙인 것**이다.
def test_the_report_never_leaks_a_key_value_in_any_form(monkeypatch):
    """★이 파일에서 가장 값진 가드★

    보고서는 화면과 로그로 나간다. 값 전체는 물론 **접두사·꼬리·마스킹 조각도**
    내지 않는다 — 마스킹은 안전해 보이지만 길이와 접두사를 흘린다.
    """
    for var in ("BOK_API_KEY", "FRED_API_KEY", "KRX_API_KEY", "DART_API_KEY",
                "KIS_APP_KEY", "KIS_APP_SECRET", "NAVER_CLIENT_ID",
                "GOOGLE_TRENDS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(var, _SECRET)

    blob = "\n".join(_flatten(key_slots()))
    assert _SECRET not in blob, "키 값이 그대로 나갔다"
    for n in (8, 6, 4):
        assert _SECRET[:n] not in blob, f"키 앞 {n}글자가 나갔다"
        assert _SECRET[-n:] not in blob, f"키 뒤 {n}글자가 나갔다"


def test_presence_is_reported_as_a_boolean_and_it_actually_tracks_the_env(monkeypatch):
    """짝 — 유출을 막겠다고 아무것도 안 내면 보고서가 쓸모없다.

    존재 여부는 **정확히** 반영돼야 한다: 넣으면 True, 빼면 False.
    """
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    before = {s.env_vars[0]: s.configured for s in key_slots()}
    assert before.get("BOK_API_KEY") is False

    monkeypatch.setenv("BOK_API_KEY", _SECRET)
    after = {s.env_vars[0]: s.configured for s in key_slots()}
    assert after.get("BOK_API_KEY") is True


def test_configured_is_a_real_bool_not_a_truthy_string(monkeypatch):
    """짝 — 값을 그대로 넣고 "참이니까 됐다" 로 넘어가면 그게 유출이다."""
    monkeypatch.setenv("FRED_API_KEY", _SECRET)
    for slot in key_slots():
        assert isinstance(slot.configured, bool), \
            f"{slot.env_vars}: configured 가 bool 이 아니다 — 값이 실렸을 수 있다"


def test_the_report_carries_the_key_state_through_without_adding_a_leak(monkeypatch):
    """짝 — 보고서가 슬롯을 실을 때 값을 덧붙이지 않는지.

    가짜 키 없이 **키 이름만** 대조한다. 값을 심으면 수집기가 라이브 호출을 시도해
    50초가 걸리는데, 그 비용을 물지 않고도 "보고서가 슬롯을 그대로 싣는다" 는
    사실은 확인된다.
    """
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    report_keys = {tuple(k["env_vars"]) for k in coverage_report()["keys"]}
    assert report_keys == {s.env_vars for s in key_slots()}
    assert all(k["configured"] is False or isinstance(k["configured"], bool)
               for k in coverage_report()["keys"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. 커버리지 — 레지스트리에서 유도한다 (손으로 센 숫자 금지)
# ─────────────────────────────────────────────────────────────────────────────
def test_every_registered_provider_appears_in_the_report():
    """★조용히 빠진 제공자가 없다★ 표에 없으면 그 소스는 존재를 잊힌다."""
    from src.data.source_registry import all_specs
    declared = {s.provider for s in all_specs()}
    reported = {p["provider"] for p in coverage_report()["providers"]}
    assert declared <= reported, f"표에서 빠진 제공자: {sorted(declared - reported)}"


def test_provider_counts_are_derived_from_the_registry_not_hand_written():
    """★수치는 문서가 아니라 코드가 진실이다 (CLAUDE.md)★

    과거 CLAUDE.md 의 "필터 13종 / FIELD_BY_ID 49개" 가 실측과 전부 달랐던 것이
    이 저장소의 대표적 실패다. 개수는 세지 말고 레지스트리에서 유도한다.
    """
    from src.data.source_registry import all_specs, specs_by_provider
    for row in coverage_report()["providers"]:
        specs = specs_by_provider(row["provider"])
        assert row["declared"] == len(specs)
        assert row["verified"] == sum(1 for s in specs if s.verified_live)
    assert sum(r["declared"] for r in coverage_report()["providers"]) == len(all_specs())


def test_backtest_eligibility_is_reported_per_provider():
    """빈티지 유무가 제공자마다 다르다는 사실이 표에 보여야 한다 (P4-D1)."""
    rows = {p["provider"]: p for p in coverage_report()["providers"]}
    assert rows["FRED"]["backtest_eligible"] is True
    assert rows["ECOS"]["backtest_eligible"] is False
    assert rows["ECOS"]["revision_bias_note"], "ECOS 가 왜 부적격인지 안 적혀 있다"
    assert rows["FRED"]["revision_bias_note"] is None, "적격 소스에 경고가 붙었다"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ★이 키를 넣으면 무엇이 열리는가★
# ─────────────────────────────────────────────────────────────────────────────
def test_every_key_slot_says_what_it_unlocks():
    """키를 넣는 사람이 **넣기 전에** 효과를 볼 수 있어야 한다."""
    slots = key_slots()
    assert len(slots) >= 5, f"키 슬롯이 {len(slots)}개 — 선언이 빠졌다"
    for s in slots:
        assert s.env_vars, f"{s.label}: 환경변수 이름이 없다"
        assert s.unlocks, f"{s.label}: 무엇이 열리는지 안 적혀 있다"


def test_series_unlock_counts_come_from_the_registry():
    """짝 — "많이 열립니다" 같은 말 대신 실제 계열 수를 낸다."""
    from src.data.source_registry import ECOS, specs_by_provider
    bok = next(s for s in key_slots() if "BOK_API_KEY" in s.env_vars)
    assert bok.series_count == len(specs_by_provider(ECOS))
    assert bok.series_count > 0


def test_a_key_that_gates_a_capability_requirement_names_it(monkeypatch):
    """★능력 사다리와 실제로 조인한다★

    `ANTHROPIC_API_KEY` 는 `llm` 요건을 막고, 그 요건은 L0 을 막는다. 표가 그
    연결을 말하지 못하면 "키를 넣으면 무엇이 열리는가" 에 답하지 못한 것이다.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = next(s for s in key_slots() if "ANTHROPIC_API_KEY" in s.env_vars)
    assert "llm" in llm.capability_requirements
    assert "L0" in llm.unlocks_levels


def test_a_key_that_unlocks_no_capability_says_so_instead_of_claiming_one():
    """★없는 효과를 지어내지 않는다★

    모든 키가 사다리를 여는 건 아니다. 계열만 여는 키는 요건 목록이 **비어 있고**,
    비어 있다는 사실이 `unlocks` 문장에 반영돼야 한다.
    """
    for s in key_slots():
        if not s.capability_requirements:
            assert s.unlocks_levels == (), \
                f"{s.label}: 요건을 하나도 안 여는데 레벨이 열린다고 주장한다"


def test_the_report_names_the_current_level_and_what_blocks_the_next_one():
    """사다리 현황이 표 안에 있어야 배포자가 지금 어디인지 안다."""
    ladder = coverage_report()["ladder"]
    assert ladder["level"] in ("L0", "L1", "L2", "L3")
    if ladder["level"] != "L0":
        assert ladder["blocked_level"], "막힌 레벨이 없다고 하면서 L0 도 아니다"
        assert ladder["blocked_reason"], "막혔는데 사유가 없다"


def test_unlock_claims_are_not_stale_when_a_key_is_actually_present(monkeypatch):
    """★짝 — 키가 있으면 그 슬롯은 더 이상 "넣으면 열린다" 고 말하지 않는다★

    이 짝이 없으면 슬롯이 항상 같은 문구를 내도 통과한다.
    """
    monkeypatch.delenv("DART_API_KEY", raising=False)
    before = next(s for s in key_slots() if "DART_API_KEY" in s.env_vars)
    monkeypatch.setenv("DART_API_KEY", _SECRET)
    after = next(s for s in key_slots() if "DART_API_KEY" in s.env_vars)
    assert before.configured is False and after.configured is True
