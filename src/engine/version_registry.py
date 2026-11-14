"""버전 레지스트리 — ★아홉이 아니라 열둘이었다★ (AM4)
==============================================================================
설계: `docs/plans` AM · 어휘 `src/domain/build_identity.py` · 측정
`src/engine/build_probe.py` · 롤업 `src/engine/run_evidence.rollup`
(★`pit_evidence`·`decision_evidence`·`estimator_evidence`·`multiplicity_evidence`
·`cost_model_registry`·`attribution_evidence` 와 **같은 함수**★ — 일곱 번째 호출자)

## 왜 이 모듈이 생겼나

채점표 #7 은 *"`code_version`(git SHA)이 `research_runs`·`backtest_runs`·
`target_versions`·`regime_snapshots` 에 박힌다"* 고 적었다. **두 군데 틀렸다**:

1. **git SHA 가 아니었다.** `GIT_SHA or APP_VERSION or "dev"` 인데 두 환경변수가
   어디에도 설정돼 있지 않아 실측 701행이 전부 `"dev"` 였다(AM2 가 고쳤다).
2. **`backtest_runs` 에는 `code_version` 열이 없다.** `engine_version` 과
   `result_version` 이 있고, 뜻이 다르다.

그리고 이름을 세면서 한 번 더 틀렸다. `MODEL_VERSION` 과 `ENGINE_VERSION` 이
**각각 두 벌**이고(`regime_snapshots` · `company_snapshots`) 값이 서로 다르다.
AK 가 비용 자리를 "넷" 으로 알고 열넷을 찾은 것과 같은 패턴이다 —
★이름을 세지 말고 자리를 읽어야 한다.★

## 이 레지스트리가 답하는 질문

*"이 저장소는 어디서 버전을 정하고, 그중 무엇이 실제로 실행을 구별하는가."*

★대부분은 구별하지 않는다★ — 소스에 박힌 상수는 실행마다 같으므로 두 실행을
가를 수 없다. 레코드 형식의 판본은 원래 그래도 되지만, **재현성을 그 위에
세울 수는 없다.**

## ★이 모듈이 주장하지 않는 것★

- **재현 가능하다고 말하지 않는다.** 실행을 구별할 수 있는지만 본다.
- **버전 축을 통일해야 한다고 말하지 않는다.** `DECISION_LOGIC_VERSION` 은
  `investment_decisions.py` 가 **명시적으로 다른 축**이라고 적어 두었고, 그
  판단은 옳다 — 빌드가 바뀌어도 결정 로직은 그대로일 수 있다.
- **다 찾았다고 말하지 않는다.** 여기 있는 것은 **판본을 스스로 정하거나
  기록하는** 자리이고, 값을 그냥 넘겨받는 자리는 세지 않았다.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from src.domain.build_identity import (
    KIND_CODE,
    KIND_COST_MODEL,
    KIND_DECISION,
    KIND_ENGINE,
    KIND_MODEL,
    KIND_PACK,
    KIND_RESULT,
    KIND_RULESET,
    KIND_SNAPSHOT,
    METHOD_DECLARED,
    METHOD_INJECTED,
    METHOD_MEASURED,
    METHOD_UNKNOWN,
    TREE_UNKNOWN,
    BuildIdentity,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN, rollup

_NOTE = (
    "이 판정은 **이 저장소가 어디서 판본을 정하고 그중 무엇이 실행을 구별하는가**"
    "만 말합니다. ★재현 가능하다는 뜻이 아닙니다★ — 같은 빌드라도 데이터·시각·"
    "외부 응답이 달라지면 결과는 달라집니다. 소스에 박힌 상수는 실행마다 같아서 "
    "두 실행을 가르지 못하며, 그것은 결함이라기보다 **그 위에 재현성을 세울 수 "
    "없다**는 뜻입니다.")

_DECLARED_REASON = ("소스에 박힌 상수입니다 — 코드가 바뀌어도 따라 바뀌지 않고, "
                    "실행마다 같으므로 두 실행을 **구별하지 못합니다**. 올리려면 "
                    "사람이 손으로 올려야 합니다.")


@dataclass(frozen=True)
class VersionAxis:
    """판본을 **스스로 정하거나 기록하는** 한 자리."""

    key: str
    label: str
    kind: str
    method: str
    #: 값을 **읽어 올** 곳. ★박지 않는다★ — 박으면 반드시 낡는다.
    module: str | None
    attr: str | None
    #: 어느 테이블·필드에 남는가.
    where: tuple[str, ...]
    note: str


#: ★값을 여기 적지 않는다★ `module`/`attr` 로 읽는다 — 상수를 옮기면
#: `test_every_declared_location_actually_exists` 가 red 가 된다.
VERSION_AXES: tuple[VersionAxis, ...] = (
    VersionAxis(
        key="code_version", label="빌드 식별자", kind=KIND_CODE,
        method=METHOD_MEASURED,  # 실제 상태는 `axis_identity` 가 환경에서 읽는다
        module="src.engine.build_probe", attr="current_identity",
        where=("research_runs.code_version", "regime_snapshots.code_version",
               "company_snapshots.code_version", "target_versions.code_version",
               "research_cases.code_version",
               "investment_decisions.code_version"),
        note=("AM2 이전에는 언제나 `\"dev\"` 였다 — 실측 701행이 전부 같은 값이라 "
              "어떤 실행도 구별하지 못했고 `research_manifest` 의 노후화 검사가 "
              "항상 참이었다. 지금은 git 을 읽고, 못 읽으면 미상이다.")),
    VersionAxis(
        key="backtest_engine_version", label="백테스트 엔진", kind=KIND_ENGINE,
        method=METHOD_MEASURED,
        module="src.data.backtest_runs", attr="engine_version",
        where=("backtest_runs.engine_version",),
        note=("`BACKTEST_ENGINE_VERSION` 오버라이드가 없으면 `code_version` 에 "
              "위임한다. 실측 39행이 전부 `\"dev\"` 였다.")),
    VersionAxis(
        key="cost_model_version", label="비용 정책 판본", kind=KIND_COST_MODEL,
        method=METHOD_MEASURED,
        module="src.domain.cost_model", attr="policy_version",
        where=("백테스트 결과 `cost_model.version`",),
        note=("AM5 가 만들었다 — `CostPolicy` 에서 결정론적으로 파생된다. "
              "★설정의 해시이지 코드 버전이 아니다★ 고정값이 없고 실행마다 "
              "정책에서 계산된다. DB 열은 아직 없다.")),
    VersionAxis(
        key="regime_model_version", label="국면 모델", kind=KIND_MODEL,
        method=METHOD_DECLARED,
        module="src.data.regime_snapshots", attr="MODEL_VERSION",
        where=("regime_snapshots.model_version",),
        note="`company_snapshots.MODEL_VERSION` 과 **다른 값의 같은 이름**이다."),
    VersionAxis(
        key="regime_engine_version", label="국면 엔진", kind=KIND_ENGINE,
        method=METHOD_DECLARED,
        module="src.data.regime_snapshots", attr="ENGINE_VERSION",
        where=("regime_snapshots.engine_version",),
        note="`company_snapshots.ENGINE_VERSION` 과 **다른 값의 같은 이름**이다."),
    VersionAxis(
        key="company_model_version", label="기업 모델", kind=KIND_MODEL,
        method=METHOD_DECLARED,
        module="src.data.company_snapshots", attr="MODEL_VERSION",
        where=("company_snapshots.model_version",),
        note="국면 쪽과 이름만 같다 — 한 축으로 접으면 저장소를 잘못 그린다."),
    VersionAxis(
        key="company_engine_version", label="기업 엔진", kind=KIND_ENGINE,
        method=METHOD_DECLARED,
        module="src.data.company_snapshots", attr="ENGINE_VERSION",
        where=("company_snapshots.engine_version",),
        note="국면 쪽과 이름만 같다."),
    VersionAxis(
        key="company_snapshot_version", label="기업 스냅샷 형식",
        kind=KIND_SNAPSHOT, method=METHOD_DECLARED,
        module="src.data.company_snapshots", attr="SNAPSHOT_VERSION",
        where=("company_snapshots.snapshot_version",),
        note="레코드 **형식**의 판본이다 — 실행을 구별하는 용도가 아니다."),
    VersionAxis(
        key="decision_logic_version", label="결정 로직", kind=KIND_DECISION,
        method=METHOD_DECLARED,
        module="src.data.investment_decisions", attr="DECISION_LOGIC_VERSION",
        where=("investment_decisions.decision_version",),
        note=("★`code_version` 과 **다른 축**이다★ — `investment_decisions.py` 가 "
              "명시적으로 그렇게 적어 두었고 그 판단은 옳다. 빌드가 바뀌어도 "
              "결정 로직은 그대로일 수 있다. 섞지 않는다.")),
    VersionAxis(
        key="backtest_result_version", label="백테스트 결과 형식",
        kind=KIND_RESULT, method=METHOD_DECLARED,
        module=None, attr=None,
        where=("backtest_runs.result_version",),
        note=("★상수조차 없다★ — `create_run` 안에 `\"rv\": \"1\"` 로 인라인 "
              "리터럴이 박혀 있다. 실측 39행 전부 `\"1\"` 이다. 올릴 사람도 "
              "올릴 자리도 없다.")),
    VersionAxis(
        key="target_ruleset_version", label="타이밍 규칙 집합",
        kind=KIND_RULESET, method=METHOD_DECLARED,
        module="src.data.target_versions", attr="compile_target",
        where=("target_versions.ruleset_version",),
        note=("호출자(요청 본문)가 선언한다 — 아무것도 측정하지 않으며 보통 "
              "`None` 이다. ★미상과 부재를 가르는 것은 이 열이 아니다.★")),
    VersionAxis(
        key="scenario_pack_id", label="시나리오 팩", kind=KIND_PACK,
        method=METHOD_DECLARED,
        module="src.data.scenario_packs_store", attr="get_pack_version",
        where=("target_versions.pack_id", "scenario_pack_versions"),
        note="팩은 내용까지 버전별로 보존된다 — 이 저장소에서 가장 튼튼한 축이다."),
)


@dataclass(frozen=True)
class MissingAxis:
    """**없는** 축. ★사유 없이 '없다' 고만 적으면 갚을 수 없는 부채다★ (AJ 선례)"""

    key: str
    label: str
    reason: str
    #: 이것이 없어서 **답할 수 없는 질문**.
    blocks: str


MISSING_AXES: tuple[MissingAxis, ...] = (
    MissingAxis(
        key="strategy_version", label="전략 정의 판본",
        reason=("전략은 요청 본문의 dict 로 들어와 `input_snapshot` 에 통째로 "
                "저장된다 — 내용은 남지만 **이름 붙은 판본이 없다**."),
        blocks="*\"이 두 실행이 같은 전략인가\"* 를 스냅샷 전체를 비교하지 않고는 못 답한다."),
    MissingAxis(
        key="feature_version", label="피처 계산 판본",
        reason=("피처 계산식이 코드에 흩어져 있고 그것을 묶어 부르는 이름이 "
                "없다. ★무엇을 해시할지부터 설계가 필요하다★ — 지금 만들면 "
                "정교함을 위한 정교함이 된다."),
        blocks="*\"피처 정의가 바뀐 뒤의 결과인가\"* 를 답할 수 없다."),
    MissingAxis(
        key="universe_version", label="유니버스 구성 판본",
        reason=("유니버스는 매 실행 질의로 만들어지고 그 결과를 판본으로 고정한 "
                "적이 없다. 생존편향 라벨(R3)은 있지만 그것은 **다른 축**이다."),
        blocks="*\"같은 종목 집합이었나\"* 를 답할 수 없다."),
    MissingAxis(
        key="model_registry", label="모델 등록·승인 기록",
        reason=("`model-governance.md` 가 이미 *승인자·승인시각·롤백 기록 부재* "
                "라고 적어 두었다. `alpha_registry`(5단계)와 "
                "`strategy_health`(5상태)는 있지만 **누가 언제 승인했는가**는 없다."),
        blocks="*\"이 모델을 누가 승인했고 언제 되돌렸나\"* 를 답할 수 없다."),
)


def axis_identity(axis: VersionAxis) -> BuildIdentity:
    """축의 **현재 값**. ★읽는다 — 박지 않는다★

    · `code_version` 계열은 환경을 읽으므로 컨테이너에서는 미상으로 보고된다.
    · 박힌 상수는 그 모듈에서 실제로 읽는다 — 상수를 고치면 여기가 따라온다.
    · 고정값이 없는 축(`cost_model_version`)은 값이 `None` 이고 **사유를 적는다**.
    """
    if axis.key == "code_version":
        from src.engine.build_probe import current_identity
        return current_identity()
    if axis.key == "backtest_engine_version":
        from src.data.backtest_runs import engine_version
        from src.engine.build_probe import current_identity
        live = current_identity()
        value = engine_version()
        # 오버라이드가 걸려 있으면 그것은 **주입**이고 트리를 모른다.
        if value == live.value:
            return live
        return BuildIdentity(value=value, method=METHOD_DECLARED,
                             tree=TREE_UNKNOWN, kind=axis.kind,
                             reason="`BACKTEST_ENGINE_VERSION` 오버라이드입니다.")
    if axis.key == "cost_model_version":
        return BuildIdentity(
            value=None, method=METHOD_MEASURED, tree=TREE_UNKNOWN,
            kind=axis.kind,
            reason=("고정값이 없습니다 — 실행마다 그 실행의 `CostPolicy` 에서 "
                    "계산되어 결과의 `cost_model.version` 에 실립니다."))
    if axis.key == "backtest_result_version":
        return BuildIdentity(value="1", method=METHOD_DECLARED,
                             tree=TREE_UNKNOWN, kind=axis.kind,
                             reason=_DECLARED_REASON)
    if axis.module is None or axis.attr is None:
        return BuildIdentity(value=None, method=METHOD_UNKNOWN,
                             tree=TREE_UNKNOWN, kind=axis.kind,
                             reason="값을 읽어 올 자리를 등록하지 않았습니다.")

    value: Any = None
    try:
        mod = importlib.import_module(axis.module)
        raw = getattr(mod, axis.attr, None)
        value = None if callable(raw) else raw
    except Exception as e:  # noqa: BLE001 — ★못 읽으면 미상이지 통과가 아니다★
        return BuildIdentity(value=None, method=METHOD_UNKNOWN,
                             tree=TREE_UNKNOWN, kind=axis.kind,
                             reason=(f"`{axis.module}.{axis.attr}` 를 읽지 "
                                     f"못했습니다 — {type(e).__name__}"))
    return BuildIdentity(
        value=None if value is None else str(value),
        method=axis.method, tree=TREE_UNKNOWN, kind=axis.kind,
        reason=(_DECLARED_REASON if axis.method == METHOD_DECLARED
                else "호출 가능한 이름이라 고정값이 없습니다."))


def identifies_runs(axis: VersionAxis) -> bool:
    """이 축이 **실행마다 달라져 두 실행을 구별하는가**. ★파생이다 — 선언이 아니다★

    처음에는 `VersionAxis` 에 손으로 적는 `identifies_runs` 불리언을 두었다.
    ★변이 배터리가 그것을 죽이지 못했다★ — 아무도 그 주장을 관측과 대조하지
    않아서, `True` 를 `False` 로 뒤집어도 전 테스트가 초록이었다. AL 의
    하드코딩 `0` 과 같은 모양이다: **선언이 관측 행세를 한다.**

    실제 관계는 단순하다. 소스에 박힌 상수(`declared`)는 실행마다 같으므로
    두 실행을 가를 수 없고, 값을 모르면(`unknown`) 더욱 가를 수 없다. 재거나
    주입된 값만이 실행을 구별한다 — 그래서 여기서 **읽어서** 판정한다.
    """
    return axis_identity(axis).method in (METHOD_MEASURED, METHOD_INJECTED)


def axis_state(axis: VersionAxis) -> dict[str, Any]:
    """한 축 → 축 판정. ★박힌 상수는 `degraded`(관측된 결함)다★

    · `measured`/`injected` → `ok`
    · `declared` → `degraded` — 손으로 올려야 하고 실행을 구별하지 못한다
    · `unknown` → `unknown` — ★통과가 아니다★
    """
    ident = axis_identity(axis)
    common = {"key": axis.key, "label": axis.label, "kind": axis.kind,
              "method": ident.method, "value": ident.value,
              "identifies_runs": identifies_runs(axis),
              "where": list(axis.where), "note": axis.note}
    if ident.method == METHOD_UNKNOWN:
        return {"state": AXIS_UNKNOWN,
                "reason": ident.reason or "값을 알 수 없습니다.", **common}
    if ident.method == METHOD_DECLARED:
        return {"state": AXIS_DEGRADED,
                "reason": ident.reason or _DECLARED_REASON, **common}
    return {"state": AXIS_OK, "reason": ident.reason, **common}


def registry_evidence() -> dict[str, Any]:
    """저장소 전체의 버전 추적 상태 한 장.

    ★실행 하나에 대한 판정이 아니다★ — *"이 저장소가 어디서 판본을 정하고
    무엇을 빠뜨리는가"* 라는 **구조**에 대한 관측이다.
    """
    axes = {a.key: axis_state(a) for a in VERSION_AXES}
    labels = {a.key: a.label for a in VERSION_AXES}
    return {
        **rollup(axes, labels),
        "axes": axes,
        "missing": [{"key": m.key, "label": m.label, "reason": m.reason,
                     "blocks": m.blocks} for m in MISSING_AXES],
        # ★열둘 중 실행을 구별하는 축★ 재현성을 세울 수 있는 자리는 여기뿐이다.
        "identifying": [a.key for a in VERSION_AXES if identifies_runs(a)],
        "declared_constants": [a.key for a in VERSION_AXES
                               if a.method == METHOD_DECLARED],
        "note": _NOTE,
    }
