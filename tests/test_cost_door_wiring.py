"""BA · ★문이 세 종류였다★ — 남은 문을 잇고 못 잇는 것을 이름 붙인다
==============================================================================
대상: `src/domain/cost_provenance.py`(`RATE_NO_FIELD`·`UNWIRED_SITES`) ·
`src/api/strategy_routes.py` · 정적 축(읽기만) `src/engine/cost_model_registry.py`

## "남은 문 열셋" 은 틀린 숫자였다 (실측 2026-09-22)

AZ 가 `screener` 한 문을 잇고 *"남은 문 열셋"* 이라고 적었다. 재 보니:

    pydantic 요청 · kis_backtest_engine 을 부름     2  ← 이을 수 있다
    pydantic 요청 · 다른 엔진                        3  ← cost_model 블록이 없다
    dataclass·함수 기본값                            6  ← 요청이 없다
    DB DDL DEFAULT                                   1  ← 저장 시점, 축이 다르다
    market_rules 계열                                2  ← 이미 설정 단일 출처

★`cost_model` 블록을 내는 엔진은 `kis_backtest_engine` 하나뿐이다★(전수).

## ★문이 세 종류였다★

요청 모델을 열어 보니 `ImportAndBacktestRequest` 에는 요율 **칸 자체가
없고**, `OptimizeRequest` 에는 `slippage_rate` 만 없다. 칸이 없으면 요청자가
★줄 방법이 없다★ — 그것을 `door_default`(*"요청이 안 실어서"*)라 부르면
**사유가 거짓**이 된다. AZ 가 `unknown ≠ door_default` 를 가른 것과 같은
모양의 실수이고 한 단계 더 안쪽에 있었다.
"""
from __future__ import annotations

import pytest

from src.domain.cost_provenance import (
    RATE_DOOR_DEFAULT,
    RATE_NO_FIELD,
    RATE_REQUEST,
    RATE_UNKNOWN,
    UNWIRED_KINDS,
    UNWIRED_SITES,
    WIRED_SITE_KEYS,
    UnwiredCostSite,
    rate_provenance,
)


class _Policy:
    commission_bps = 15.0
    slippage_bps = 5.0


# ── ★세 번째 값 — 문이 묻지 않는다★ ─────────────────────────────────────

def test_a_field_the_door_does_not_have_is_not_a_door_default():
    """변이 a — ★안 준 것 ≠ 줄 수 없는 것★

    `door_default` 의 사유는 *"요청이 안 실어서"* 인데, 칸이 없으면 실을
    방법이 없었다. 그 사유는 거짓이다.
    """
    out = rate_provenance(door="import_and_backtest", explicit=frozenset(),
                          available=frozenset({"symbols"}), policy=_Policy())
    assert out["commission"]["origin"] == RATE_NO_FIELD
    assert out["commission"]["reason"]
    assert "안 실어서" not in out["commission"]["reason"]


def test_a_field_the_door_has_is_still_a_door_default():
    """변이 b — ★반대 방향★(짝). 칸이 있는데 안 준 것은 여전히 기본값이다."""
    out = rate_provenance(door="kis_backtest", explicit=frozenset(),
                          available=frozenset({"commission_rate"}),
                          policy=_Policy())
    assert out["commission"]["origin"] == RATE_DOOR_DEFAULT


def test_the_request_still_wins_when_it_answered():
    out = rate_provenance(door="kis_backtest",
                          explicit=frozenset({"commission_rate"}),
                          available=frozenset({"commission_rate"}),
                          policy=_Policy())
    assert out["commission"]["origin"] == RATE_REQUEST


def test_one_request_can_mix_two_kinds():
    """변이 e — ★한 요청 안에서도 성분마다 다르다★ (실측: `OptimizeRequest`).

    `commission_rate` 는 있고 `slippage_rate` 는 없다. 한 값으로 접으면
    둘 중 하나가 거짓이 된다.
    """
    out = rate_provenance(door="optimize", explicit=frozenset(),
                          available=frozenset({"commission_rate"}),
                          policy=_Policy())
    assert out["commission"]["origin"] == RATE_DOOR_DEFAULT
    assert out["slippage"]["origin"] == RATE_NO_FIELD


def test_an_unwired_path_is_still_unknown():
    """★미상은 그대로 미상이다★ — 새 값이 그것을 잡아먹지 않는다."""
    out = rate_provenance(policy=_Policy())
    assert out["commission"]["origin"] == RATE_UNKNOWN


def test_omitting_available_keeps_the_old_behaviour():
    """변이 c — ★하위호환★ AZ 가 이은 `screener` 가 안 깨진다.

    `available` 를 안 주면 *"문이 그 칸을 갖는지 모른다"* 이고, 그때는
    **예전 판정 그대로**여야 한다.
    """
    out = rate_provenance(door="screener", explicit=frozenset(),
                          policy=_Policy())
    assert out["commission"]["origin"] == RATE_DOOR_DEFAULT
    out2 = rate_provenance(door="screener",
                           explicit=frozenset({"commission_rate"}),
                           policy=_Policy())
    assert out2["commission"]["origin"] == RATE_REQUEST


def test_the_four_origins_give_four_different_reasons():
    """변이 l — ★처방이 다르면 다르게 말한다★"""
    reasons = {
        rate_provenance(policy=_Policy())["commission"]["reason"],
        rate_provenance(door="d", explicit=frozenset({"commission_rate"}),
                        available=frozenset({"commission_rate"}),
                        policy=_Policy())["commission"]["reason"],
        rate_provenance(door="d", explicit=frozenset(),
                        available=frozenset({"commission_rate"}),
                        policy=_Policy())["commission"]["reason"],
        rate_provenance(door="d", explicit=frozenset(),
                        available=frozenset(),
                        policy=_Policy())["commission"]["reason"],
    }
    assert len(reasons) == 4, reasons


# ── ★못 잇는 자리를 종류별로★ ───────────────────────────────────────────

def test_every_unwired_entry_is_complete():
    for e in UNWIRED_SITES:
        assert isinstance(e, UnwiredCostSite)
        assert e.key and e.kind in UNWIRED_KINDS
        assert len(e.reason) > 30, e.key
        assert len(e.promotes_when) > 20, e.key


def test_the_kinds_are_actually_used():
    """★공허한 어휘 금지★ — 쓰이지 않는 종류를 만들지 않는다."""
    used = {e.kind for e in UNWIRED_SITES}
    assert used == set(UNWIRED_KINDS), (used, UNWIRED_KINDS)


def test_the_wired_and_unwired_keys_cover_the_registry_exactly():
    """변이 f·g — ★빠짐도 겹침도 없다★ · ★열넷을 손으로 세지 않는다★

    개수를 적으면 반드시 낡는다(CLAUDE.md). 정적 레지스트리에서 **읽어**
    대조한다 — 누가 자리를 하나 더하면 여기가 red 가 된다.
    """
    from src.engine.cost_model_registry import COST_SITES

    known = {s.key for s in COST_SITES}
    wired = set(WIRED_SITE_KEYS)
    unwired = {e.key for e in UNWIRED_SITES}
    assert wired & unwired == set(), wired & unwired
    assert wired | unwired == known, {
        "등록 안 된 자리": known - (wired | unwired),
        "레지스트리에 없는 키": (wired | unwired) - known,
    }


def test_the_permanent_kinds_are_marked_permanent():
    """변이 h — ★영구적인 것을 임시라 부르지 않는다★

    `no_request`·`db_default`·`config_layer` 는 *"아직 안 한 일"* 이 아니라
    **영구적으로 맞는 답**이다. 임시라고 적으면 갚을 수 없는 부채가 된다.

    ★처음 쓴 이 테스트는 `promotes_when` 문자열에서 "영구"·"아니" 를
    찾았고, 그래서 *"해당 없습니다"* 라고 적은 항목을 잡지 못했다★ —
    어휘로 건 것이다. 구조(`permanent` 칸)로 고쳤다.
    """
    permanent_kinds = {"no_request", "db_default", "config_layer"}
    for e in UNWIRED_SITES:
        assert e.permanent == (e.kind in permanent_kinds), (e.key, e.kind)


def test_the_other_engine_kind_is_not_permanent():
    """★짝★ — 전부 영구적이라고 말하면 그것도 거짓이다."""
    movable = [e for e in UNWIRED_SITES if not e.permanent]
    assert movable
    for e in movable:
        assert e.kind == "other_engine", e.key
        # 움직일 수 있는 자리는 ★무엇이 참이 되면★ 이을 수 있는지 적는다.
        assert "cost_model" in e.promotes_when, e.key


@pytest.mark.parametrize("key", ["screener_routes", "legacy_schemas"])
def test_the_wired_keys_are_the_ones_that_reach_the_engine(key):
    """★`cost_model` 을 내는 엔진에 닿는 자리만 이었다★(실측)."""
    assert key in WIRED_SITE_KEYS


# ── ★문 이름은 서로 달라야 한다 — 그게 이 축의 존재 이유다★ ─────────────

def _door_constants(rel: str) -> dict[str, str]:
    """모듈 최상위의 `_DOOR_* = "문자열"`. ★AST 로 읽는다★"""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(rel).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id.startswith(("_DOOR_", "_COST_DOOR")):
                    out[t.id] = n.value.value
    return out


def test_every_door_name_is_distinct():
    """변이 d — ★두 문이 같은 이름을 쓰면 "어느 문" 을 못 답한다★

    ★이 테스트가 없어서 변이가 살아남았다★ — `door` 칸의 존재 이유가
    *"어느 문으로 불렀나"* 인데, 그것을 아무도 걸고 있지 않았다.
    """
    names: dict[str, str] = {}
    for rel in ("src/api/strategy_routes.py", "src/api/screener_routes.py"):
        for const, value in _door_constants(rel).items():
            assert value not in names, (
                f"문 이름이 겹친다: {value!r} — {names[value]} · {rel}:{const}")
            names[value] = f"{rel}:{const}"
    # ★공허 방지★ — 하나도 못 읽었으면 위 전칭은 아무것도 안 본 것이다.
    assert len(names) >= 5, names


def test_the_wired_call_sites_all_pass_a_door():
    """★이은 자리마다 문 이름이 함께 간다★ — 하나라도 빠지면 미상이 된다."""
    import pathlib

    src = pathlib.Path("src/api/strategy_routes.py").read_text(encoding="utf-8")
    n_door = src.count("cost_door=")
    n_explicit = src.count("cost_explicit_fields=")
    n_available = src.count("cost_available_fields=")
    assert n_door >= 4, n_door
    assert n_door == n_explicit == n_available, (n_door, n_explicit, n_available)
