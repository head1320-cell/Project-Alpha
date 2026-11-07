"""리밸런스 사유를 ★이름으로★ 부른다 — 두 축 (AA1·AA2)

설계: `docs/plans` AA · 애드덤 합격기준 #8 · 도메인 아키텍처 §4.

## ★두 축을 섞지 않는다★

    trigger          왜 **검토**했는가   calendar · drift · regime_change · vol_spike
    decision reason  왜 **거래/보류/미정**인가

`rebalance_policy.detect_triggers` 의 주석이 이미 그 구분을 적어 두었다 —
*"트리거는 검토 시점을 알릴 뿐 거래 근거가 아닙니다"*. 한 목록에 넣으면
"국면이 바뀌어 **거래했다**" 와 "국면이 바뀌어 **들여다봤다**" 가 같은 값이 된다.
Z 에서 `kind`(무슨 성과) ⟂ `data_real`(무슨 데이터) 을 가른 규율과 같다.

## ★설계 문서의 목록을 실측이 고쳤다★

도메인 문서 §4 는 9개 상수를 제안했다. 코드와 대조하니 결정 사유는 **둘뿐**이고
셋은 트리거 축이며 **넷은 생산자가 없었다**(`band_breach`·`constraint_binding`·
`contribution`·`glide_path`). 반대로 코드에는 있는데 목록에 **없는** 사유가 넷이다
(`inside_band` + `undetermined` 3종). 이 파일은 **실측한 쪽**을 고정한다.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from src.domain.rebalance_reason import (
    DECISION_REASONS,
    REASON_BELOW_COST,
    REASON_BENEFIT_UNKNOWN,
    REASON_COST_UNKNOWN,
    REASON_DECISION,
    REASON_INSIDE_BAND,
    REASON_NO_PORTFOLIO_VALUE,
    REASON_UTILITY_GAIN,
    REBALANCE_TRIGGERS,
)


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 두 축은 독립이다
# ═══════════════════════════════════════════════════════════════════════════
def test_the_two_axes_share_no_value():
    """★한 값이 두 축에 있으면 둘은 축이 아니라 한 자루다★"""
    overlap = set(REBALANCE_TRIGGERS) & set(DECISION_REASONS)
    assert not overlap, f"트리거와 결정 사유가 같은 값을 씁니다: {sorted(overlap)}"


def test_triggers_match_the_producer_verbatim():
    """★`portfolio_rebalancer` 가 내는 문자열 그대로다★

    이름을 `volatility_spike` 로 "고치면" 일곱 번째 모드 어휘가 생긴다(채점표 §5-1).
    생산자 소스에서 직접 읽어 대조한다 — 손으로 옮겨 적으면 낡는다.
    """
    src = pathlib.Path("src/engine/portfolio_rebalancer.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    produced = {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "append" and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "triggers" and n.args
        and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
    }
    assert produced, "생산자에서 트리거 문자열을 하나도 못 찾았습니다 — 스캐너가 죽었습니다"
    assert produced == set(REBALANCE_TRIGGERS), (
        f"어휘가 생산자와 갈라졌습니다 — 생산자 {sorted(produced)} / "
        f"어휘 {sorted(REBALANCE_TRIGGERS)}")


def test_every_reason_maps_to_exactly_one_decision():
    """★한 사유가 두 결정에 걸치지 않는다★"""
    assert set(REASON_DECISION) == set(DECISION_REASONS)
    for reason, decision in REASON_DECISION.items():
        assert decision in ("trade", "hold", "undetermined"), (reason, decision)


def test_no_producerless_constant_was_invented():
    """★설계 문서가 제안했지만 생산자가 없어 만들지 않은 넷★

    `band_breach`(밴드 이탈은 TRADE 사유가 아니다) · `constraint_binding`
    (`_legs_from` 이 `[]` 고정) · `contribution`·`glide_path`(코드 자체가 없다).
    누가 나중에 "문서에 있으니" 되살리면 이 테스트가 그 사실을 되짚어 준다.
    """
    for ghost in ("band_breach", "constraint_binding", "contribution", "glide_path"):
        assert ghost not in DECISION_REASONS, (
            f"`{ghost}` 는 생산자가 없습니다 — 만들려면 **만드는 코드부터** 필요합니다")
        assert ghost not in REBALANCE_TRIGGERS


# ═══════════════════════════════════════════════════════════════════════════
# ①③ 6분기가 각자의 코드를 낸다
# ═══════════════════════════════════════════════════════════════════════════
#: ★이 테스트들은 가격 로더를 타면 안 된다★
#: `rebalance_decision` → `_cost_block` → `build_plan` 의 기본 `price_of` 는
#: `date.today()` 로 최근 30일을 읽는데, 이 환경엔 `daily_prices` 가 없어 **날짜로
#: 시드된 mock 가격**이 나온다. 그러면 `cost_pct` 가 날마다 달라지고 → 동적 밴드가
#: 달라지고 → `utility_gain` 과 `inside_band` 가 **달력에 따라 뒤바뀐다**.
#: 실제로 2026-09-14 에 밴드 반폭이 1.029pp 로 나와 1.0pp 괴리를 삼켰다.
#: ★분기 이름을 거는 테스트가 오늘 며칠인지에 달려 있으면 그것은 증거가 아니다.★
#: (AG 범위 밖에서 발견 — 기본값 변경과 무관하고, 변경 전 트리에서도 실패한다.)
_PRICE = 50_000.0
_ADV = 5e10


def _decide(**kw):
    from src.engine.rebalance_policy import rebalance_decision
    base = {"current_weights": {"A": 50.0, "B": 50.0},
            "target_weights": {"A": 50.0, "B": 50.0},
            "portfolio_value": 100_000_000.0,
            "price_of": lambda c: _PRICE, "adv_of": lambda c: _ADV}
    base.update(kw)
    cur = base.pop("current_weights")
    tgt = base.pop("target_weights")
    return rebalance_decision(cur, tgt, **base)


def test_a_nonpositive_portfolio_value_is_named():
    out = _decide(portfolio_value=0.0)
    assert out["reason_code"] == REASON_NO_PORTFOLIO_VALUE
    assert out["decision"] == "undetermined"


def test_an_unknown_benefit_is_named():
    """μ/Σ 없이 부르면 편익을 못 잰다 — ★그것이 실패가 아니라 답이다★"""
    out = _decide(target_weights={"A": 70.0, "B": 30.0})
    assert out["reason_code"] == REASON_BENEFIT_UNKNOWN
    assert out["decision"] == "undetermined"


def test_all_inside_band_is_named():
    """★변이 a 가 이 테스트를 요구했다★

    처음에는 여섯 분기 중 **셋만** 실제로 탔다 — μ/Σ 없이 부르면 그 전에
    `benefit_unknown` 으로 빠져서 `inside_band`·`utility_gain`·`none_below_cost`
    가 한 번도 실행되지 않았고, 변이 배터리가 그것을 드러냈다.
    """
    import numpy as np
    names = ["A", "B"]
    w = {"A": 50.0, "B": 50.0}
    out = _decide(current_weights=dict(w), target_weights=dict(w), names=names,
                  mu=np.array([0.05, 0.05]), sigma=np.eye(2) * 0.04)
    assert out["decision"] == "hold"
    assert out["reason_code"] == REASON_INSIDE_BAND, out.get("reason")


def test_a_gain_above_the_threshold_is_named():
    """`trade` 분기 — ★변이 a 와 같은 구멍을 utility_gain 쪽에도 막는다★"""
    import numpy as np
    out = _decide(current_weights={"A": 60.0, "B": 40.0},
                  target_weights={"A": 59.0, "B": 41.0}, names=["A", "B"],
                  mu=np.array([0.001, 0.001]), sigma=np.eye(2) * 0.40)
    assert out["decision"] == "trade"
    assert out["reason_code"] == REASON_UTILITY_GAIN, out.get("reason")


def test_a_gain_below_the_threshold_is_named():
    """`none_below_cost` — ★가장 자주 일어나는 결정이 이름을 갖는다★

    괴리는 크지만(밴드 밖) μ 가 거의 같아 효용 개선이 비용 문턱을 못 넘는 경우다.
    ★거래하지 않기로 한 것도 결정이고, 이름이 없으면 기록되지 않는다.★
    """
    import numpy as np
    out = _decide(current_weights={"A": 90.0, "B": 10.0},
                  target_weights={"A": 10.0, "B": 90.0}, names=["A", "B"],
                  mu=np.array([0.05, 0.05]), sigma=np.eye(2) * 0.04)
    assert out["decision"] == "hold"
    assert out["reason_code"] == REASON_BELOW_COST, out.get("reason")


def test_every_branch_that_exists_is_exercised_somewhere():
    """★공허 배제★ 여섯 사유 중 테스트가 실제로 관측한 것이 몇 개인가.

    상수 목록만 보고 통과하는 테스트는 분기가 도달 불가여도 초록이다. 이 테스트는
    **실행해서** 나온 코드를 센다.
    """
    import numpy as np
    seen = {
        _decide(portfolio_value=0.0)["reason_code"],
        _decide(target_weights={"A": 70.0, "B": 30.0})["reason_code"],
        _decide(current_weights={"A": 50.0, "B": 50.0},
                target_weights={"A": 50.0, "B": 50.0}, names=["A", "B"],
                mu=np.array([0.05, 0.05]), sigma=np.eye(2) * 0.04)["reason_code"],
        _decide(current_weights={"A": 90.0, "B": 10.0},
                target_weights={"A": 10.0, "B": 90.0}, names=["A", "B"],
                mu=np.array([0.05, 0.05]), sigma=np.eye(2) * 0.04)["reason_code"],
        _decide(current_weights={"A": 60.0, "B": 40.0},
                target_weights={"A": 59.0, "B": 41.0}, names=["A", "B"],
                mu=np.array([0.001, 0.001]), sigma=np.eye(2) * 0.40)["reason_code"],
    }
    assert len(seen) >= 5, f"서로 다른 사유를 {len(seen)}개만 관측했습니다: {seen}"
    assert seen <= set(DECISION_REASONS)


def test_every_named_reason_is_enumerated():
    """③ 자유 문자열 0건 — 나온 코드는 전부 목록 안이다."""
    for out in (_decide(portfolio_value=0.0),
                _decide(target_weights={"A": 70.0, "B": 30.0})):
        assert out["reason_code"] in DECISION_REASONS


def test_the_free_text_reason_survives_untouched():
    """② ★기존 `reason` 문자열은 한 글자도 바뀌지 않는다★ — 코드는 **덧붙임**이다."""
    out = _decide(portfolio_value=0.0)
    assert out["reason"] == "포트폴리오 평가액이 0 이하입니다"


# ═══════════════════════════════════════════════════════════════════════════
# ④⑤ ★AST 전수★ — 분기가 늘면 잡는다
# ═══════════════════════════════════════════════════════════════════════════
def _exit_paths_without_code(source: str) -> list[int]:
    """`rebalance_decision` 의 **결정을 내는 종료 경로** 중 사유 코드가 없는 줄.

    둘을 센다:
      · `return {...}` 리터럴에 `decision` 이 있는데 `reason_code` 가 없다
      · `out.update(decision=…)` 에 `reason_code=` 가 없다
    """
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "rebalance_decision")
    bad: list[int] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "decision" in keys and "reason_code" not in keys:
                bad.append(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "out"):
            kw = {k.arg for k in node.keywords}
            if "decision" in kw and "reason_code" not in kw:
                bad.append(node.lineno)
    return bad


def test_every_exit_path_names_its_reason():
    """④ ★7번째 분기가 사유 없이 생기면 여기서 멈춘다★"""
    from src.engine import rebalance_policy
    src = pathlib.Path(inspect.getsourcefile(rebalance_policy)).read_text(encoding="utf-8")
    bad = _exit_paths_without_code(src)
    assert not bad, f"사유 코드 없는 종료 경로(줄): {bad}"


def test_the_ast_scan_actually_scans():
    """⑤ ★테스트의 테스트★ — 가짜 소스에서 코드를 지우면 잡는가."""
    fake = '''
def rebalance_decision(a, b):
    if a:
        return {"decision": "undetermined", "reason": "x"}
    out = {}
    out.update(decision="hold", reason="y")
    return out
'''
    assert _exit_paths_without_code(fake), "스캐너가 명백한 누락을 놓쳤습니다"

    good = '''
def rebalance_decision(a, b):
    if a:
        return {"decision": "undetermined", "reason": "x", "reason_code": "c"}
    out = {}
    out.update(decision="hold", reason="y", reason_code="d")
    return out
'''
    assert not _exit_paths_without_code(good), "짝: 멀쩡한 소스를 잡으면 안 됩니다"


def test_the_scan_is_not_vacuous():
    """★공허 배제★ 종료 경로가 0개면 ④는 아무 말도 하지 않는다."""
    from src.engine import rebalance_policy
    src = pathlib.Path(inspect.getsourcefile(rebalance_policy)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "rebalance_decision")
    exits = sum(
        1 for node in ast.walk(fn)
        if (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict))
        or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "out"))
    assert exits >= 6, f"결정 종료 경로가 {exits}개뿐입니다 — 스캐너를 의심하세요"


@pytest.mark.parametrize("reason", DECISION_REASONS)
def test_no_reason_is_an_empty_or_spacey_string(reason):
    assert reason and reason == reason.strip() and " " not in reason


# ═══════════════════════════════════════════════════════════════════════════
# 기록까지 — ★감사가 문구가 아니라 이름으로 같은 사건을 부른다★
# ═══════════════════════════════════════════════════════════════════════════
def test_the_saved_record_carries_the_code(tmp_path):
    """`decide(persist=True)` 가 남긴 행에 `reason_code` 가 있다.

    ★컬럼을 못 붙인 DB 에서도 저장은 된다★ — 그때는 값이 빠질 뿐이고, 이
    테스트는 붙는 경우를 본다(인메모리 SQLite 는 항상 붙는다).
    """
    from sqlalchemy import create_engine, text

    from src.data import investment_decisions as ids
    from src.engine.investment_decision import decide

    engine = create_engine(f"sqlite:///{tmp_path}/dec.db")
    ids._inited = False
    out = decide({"A": 50.0, "B": 50.0}, {"A": 50.0, "B": 50.0},
                 portfolio_value=0.0, persist=True, engine=engine)
    assert out["reason_code"] == REASON_NO_PORTFOLIO_VALUE
    if not out["persisted"]:
        pytest.skip(f"저장되지 않았습니다: {out['persist_reason']}")
    with engine.begin() as c:
        row = c.execute(text("SELECT reason_code FROM investment_decisions "
                             "WHERE dec_id = :i"), {"i": out["dec_id"]}).fetchone()
    assert row and row[0] == REASON_NO_PORTFOLIO_VALUE


def test_persistence_survives_a_missing_column(tmp_path, monkeypatch):
    """⑫ ★컬럼을 못 붙여도 결정 저장이 깨지지 않는다★

    권한 등으로 `ALTER` 가 막힌 배포를 흉내 낸다. 사유 코드가 기록에서 빠지는
    것은 **열화**이고, 결정을 통째로 잃는 것과는 다르다.
    """
    from sqlalchemy import create_engine

    from src.data import investment_decisions as ids
    from src.engine.investment_decision import decide

    engine = create_engine(f"sqlite:///{tmp_path}/nocol.db")
    ids._inited = False
    monkeypatch.setattr("src.data.schema_add_columns.add_columns",
                        lambda *a, **k: False)
    out = decide({"A": 50.0, "B": 50.0}, {"A": 50.0, "B": 50.0},
                 portfolio_value=0.0, persist=True, engine=engine)
    assert out["reason_code"] == REASON_NO_PORTFOLIO_VALUE, "응답에는 그대로 실린다"
    assert out["persisted"] is True, f"저장이 깨졌습니다: {out['persist_reason']}"
    # ★이 테스트가 정말 열화 경로를 탔는지 확인한다★ — 안 그러면 위 두 단정은
    # 정상 경로를 재는 것이고 ⑫는 아무것도 막지 못한다.
    assert ids._has_reason_code is False, "열화 경로를 타지 않았습니다"


def test_the_reason_tests_never_touch_the_price_loader(monkeypatch):
    """★테스트의 테스트★ — 위 단언들이 주변 환경(날짜·DB)에 안 기댄다.

    실제 로더가 터지게 만들어도 분기 이름들이 그대로 나와야 한다. 그렇지 않으면
    이 파일의 초록은 *오늘 mock 가격이 우연히 그랬다* 는 뜻일 뿐이다.
    """
    import numpy as np

    import src.engine.execution_plan as ep

    def boom(_code):
        raise AssertionError("테스트가 실제 가격 로더를 탔다")

    monkeypatch.setattr(ep, "_last_close", boom)
    monkeypatch.setattr(ep, "_adv_won", boom)
    gain = _decide(current_weights={"A": 60.0, "B": 40.0},
                   target_weights={"A": 59.0, "B": 41.0}, names=["A", "B"],
                   mu=np.array([0.001, 0.001]), sigma=np.eye(2) * 0.40)
    assert gain["reason_code"] == REASON_UTILITY_GAIN, gain.get("reason")
    band = _decide(current_weights={"A": 50.0, "B": 50.0},
                   target_weights={"A": 50.0, "B": 50.0}, names=["A", "B"],
                   mu=np.array([0.05, 0.05]), sigma=np.eye(2) * 0.04)
    assert band["reason_code"] == REASON_INSIDE_BAND, band.get("reason")
