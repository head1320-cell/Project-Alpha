"""빌드 식별자 — ★`"dev"` 는 버전이 아니라 미상이다★ (AM1)
==============================================================================
설계: `docs/plans` AM · 측정 `src/engine/build_probe.py` · 레지스트리
`src/engine/version_registry.py` · 소비 `src/engine/research_manifest.py`

## 왜 이 모듈이 생겼나

실측(2026-09-18):

1. `code_version()` 은 `GIT_SHA or APP_VERSION or "dev"` 인데 **두 환경변수가
   어디에도 설정돼 있지 않다** — Dockerfile·compose·Makefile·CI·`.env.example`
   전부 0건. 그래서 `research_runs` 6행 · `regime_snapshots` 656행 ·
   `backtest_runs.engine_version` 39행 = ★701행이 전부 `"dev"`★ 다.
2. 그 결과 `research_manifest` 의 재현성 검사가 `"dev" == "dev"` 로 **항상
   참**이었다. ★가드는 있는데 도달할 수 없었다.★
3. `.dockerignore` 가 `.git` 을 빼므로 컨테이너 안에서는 측정 자체가 불가능하다.

★AL 의 하드코딩 `0` 과 **같은 모양**★ 이다 — `pd.notna(0)` 이 참이라 상수가
`coverage_complete` 를 통과시켰듯, `"dev" == "dev"` 가 참이라 노후화 검사가 한
번도 발동하지 못했다. **상수가 관측 행세를 한다.**

## ★두 축을 섞지 않는다★

    무엇의 버전인가(kind)  ⟂  그 값을 어떻게 알았나(method)

Z·AA·AG·AH·AI·AJ·AK·AL 과 같은 규율이다. 그리고 method 와도 다른 셋째 사실이
있다 — **작업 트리가 깨끗한가**(tree).

## ★SHA 는 커밋을 식별하지 트리를 식별하지 않는다★

커밋 안 된 수정이 있으면 같은 SHA 두 개는 **같은 코드가 아니다**. 개발 중에는
거의 항상 그렇다. 그래서 `versions_comparable` 은 **양쪽이 모두 깨끗할 때만**
`True/False` 를 내고, 아니면 `None`(비교 불가)을 낸다 — 미상을 일치로 읽지
않기 위해서다.

## ★이 모듈이 주장하지 않는 것★

- **재현성을 주장하지 않는다.** 같은 SHA 가 같은 결과를 준다는 증거는 이
  저장소에 없다(데이터·시각·외부 API 가 전부 움직인다). 이 모듈이 하는 일은
  실행을 **구별 가능하게** 만드는 것뿐이다.
- **`"dev"` 가 적힌 과거 701행을 해석하지 않는다.** 소급해서 알 방법이 없으므로
  `is_version()` 이 그것들을 **미상으로 읽을** 뿐이다.
- **`APP_VERSION` 이 커밋을 식별한다고 말하지 않는다.** 라벨이 거칠어서
  `v1.0` 두 개가 같은 코드라는 보장이 없다.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ── 축 ①  무엇의 버전인가 ─────────────────────────────────────────────────
#: 저장소 전체의 빌드(git 커밋).
KIND_CODE = "code"
#: 계산 엔진의 판본(`ENGINE_VERSION`·`BACKTEST_ENGINE_VERSION`).
KIND_ENGINE = "engine"
#: 모델·룰의 판본(`MODEL_VERSION`).
KIND_MODEL = "model"
#: 결정 로직의 판본(`DECISION_LOGIC_VERSION`). ★`code` 와 다른 축이다★
KIND_DECISION = "decision"
#: 스냅샷 레코드 형식(`snapshot_version`).
KIND_SNAPSHOT = "snapshot"
#: 결과 레코드 형식(`result_version`).
KIND_RESULT = "result"
#: 타이밍 규칙 집합(`ruleset_version`).
KIND_RULESET = "ruleset"
#: 시나리오 팩(`pack_id`).
KIND_PACK = "pack"
#: 비용 정책의 해시(AM5). ★설정의 해시이지 코드 버전이 아니다★
KIND_COST_MODEL = "cost_model"

KINDS = (KIND_CODE, KIND_ENGINE, KIND_MODEL, KIND_DECISION, KIND_SNAPSHOT,
         KIND_RESULT, KIND_RULESET, KIND_PACK, KIND_COST_MODEL)

# ── 축 ②  그 값을 어떻게 알았나 ───────────────────────────────────────────
#: git 에서 **실제로 읽었다**. 가장 강한 근거.
METHOD_MEASURED = "measured"
#: 빌드·배포가 환경변수로 **주입했다**. 운영자의 명시적 선언.
METHOD_INJECTED = "injected"
#: 소스에 **박힌 상수**. ★코드가 바뀌어도 안 바뀐다★ — 손으로 올려야 한다.
METHOD_DECLARED = "declared"
#: 모른다. ★사유를 반드시 동반한다★
METHOD_UNKNOWN = "unknown"

METHODS = (METHOD_MEASURED, METHOD_INJECTED, METHOD_DECLARED, METHOD_UNKNOWN)

# ── 작업 트리 ─────────────────────────────────────────────────────────────
#: 커밋 안 된 수정이 없다. ★이때만 SHA 가 코드를 식별한다★
TREE_CLEAN = "clean"
#: 커밋 안 된 수정이 있다. SHA 가 같아도 코드는 다를 수 있다.
TREE_DIRTY = "dirty"
#: 깨끗한지 모른다(측정 못 했거나 값이 주입만 됐다).
TREE_UNKNOWN = "unknown"

TREES = (TREE_CLEAN, TREE_DIRTY, TREE_UNKNOWN)

#: ★버전 행세를 하는 값들★ — 이 저장소의 701행이 전부 첫 항목이다.
#: 비교하면 서로 같아 보이지만 **무엇도 식별하지 않는다**.
NON_VERSIONS = frozenset({"", "dev", "development", "unknown", "unspecified",
                          "none", "null", "n/a", "na", "latest", "head", "-"})

_REASON_NO_PROBE = ("빌드 식별자를 알 수 없습니다 — 환경변수 주입(`GIT_SHA`/"
                    "`APP_VERSION`)도 없고 git 측정 결과도 받지 못했습니다. "
                    "★미상은 `\"dev\"` 가 아닙니다★")
_REASON_APP = ("`APP_VERSION` 은 커밋을 식별하지 않습니다 — 같은 라벨이 서로 "
               "다른 코드를 가리킬 수 있어 트리 상태를 주장하지 않습니다.")
_REASON_DIRTY = ("작업 트리에 커밋되지 않은 수정이 있습니다 — ★SHA 는 커밋을 "
                 "식별하지 트리를 식별하지 않습니다★. 같은 SHA 의 두 실행이 "
                 "같은 코드라고 말할 수 없습니다.")
_REASON_NO_TREE = ("작업 트리가 깨끗한지 측정하지 못했습니다 — 이 식별자는 "
                   "다른 식별자와 **비교할 수 없습니다**.")

_LABEL_NOTE = (
    "이 블록은 **이 실행을 다른 실행과 구별할 수 있는가**만 말합니다. "
    "★재현 가능하다는 뜻이 아닙니다★ — 같은 빌드라도 데이터·시각·외부 응답이 "
    "달라지면 결과는 달라집니다. 그리고 `\"dev\"` 처럼 버전이 아닌 값은 서로 "
    "같아 보여도 일치로 읽지 않습니다.")


@dataclass(frozen=True)
class BuildIdentity:
    """한 축의 버전과 **그 값을 얼마나 믿을 수 있는지**. ★동결★"""

    value: str | None
    method: str
    tree: str
    reason: str | None = None
    kind: str = KIND_CODE

    def __post_init__(self) -> None:
        # ★축을 섞으면 거부한다★ `clean` 은 방법이 아니고 `measured` 는 트리
        # 상태가 아니다. 문자열이라 조용히 들어가는 것을 여기서 막는다.
        if self.method not in METHODS:
            raise ValueError(f"알 수 없는 method 입니다: {self.method!r} "
                             f"(가능: {', '.join(METHODS)})")
        if self.tree not in TREES:
            raise ValueError(f"알 수 없는 tree 입니다: {self.tree!r} "
                             f"(가능: {', '.join(TREES)})")
        if self.kind not in KINDS:
            raise ValueError(f"알 수 없는 kind 입니다: {self.kind!r} "
                             f"(가능: {', '.join(KINDS)})")

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "method": self.method, "tree": self.tree,
                "kind": self.kind, "reason": self.reason}


def is_version(value: object) -> bool:
    """이 값이 **무엇인가를 식별하는가**. ★`"dev"` 는 아니다★

    701행을 미상으로 읽게 하는 것이 이 함수의 유일한 목적이다. 마이그레이션이
    아니라 **판독**이다 — 과거를 소급해서 아는 척하지 않는다.
    """
    if not isinstance(value, str):
        return False
    return value.strip().casefold() not in NON_VERSIONS


def identity_from(*, env_sha: str | None = None, env_app: str | None = None,
                  measured_sha: str | None = None,
                  measured_dirty: bool | None = None,
                  probe_reason: str | None = None,
                  kind: str = KIND_CODE) -> BuildIdentity:
    """측정값과 주입값을 하나의 식별자로. ★순수 함수★ — 아무것도 읽지 않는다.

    **우선순위** `GIT_SHA` → `APP_VERSION` → 측정 → 미상. 주입이 이기는 이유는
    운영자의 명시적 선언이고, 컨테이너에서는 `.git` 이 없어 **그것이 유일한
    진실**이기 때문이다(`.dockerignore` 가 `.git` 을 뺀다).

    ★그래도 측정이 가능하면 측정해서 대조한다★ — 주입값과 측정 SHA 가 같고
    트리가 깨끗하면 트리 상태를 **승격**하고, 어긋나면 `reason` 에 남긴다.
    조용히 삼키면 "배포된 이미지가 사실 다른 커밋" 이라는 사건을 놓친다.
    """
    tree, reasons = TREE_UNKNOWN, []

    if measured_dirty is True:
        tree = TREE_DIRTY
        reasons.append(_REASON_DIRTY)
    elif measured_dirty is False and measured_sha is not None:
        tree = TREE_CLEAN

    if is_version(env_sha):
        assert env_sha is not None  # is_version 이 보장한다 (mypy 용)
        if measured_sha is not None and measured_sha != env_sha:
            # ★주입과 측정이 어긋났다★ 승격하지 않고 사실을 적는다.
            return BuildIdentity(
                value=env_sha, method=METHOD_INJECTED, tree=TREE_UNKNOWN,
                kind=kind,
                reason=(f"주입된 빌드 식별자({env_sha})가 측정된 git "
                        f"커밋({measured_sha})과 ★어긋납니다★ — 어느 코드가 "
                        "도는지 말할 수 없어 트리 상태를 주장하지 않습니다."))
        if tree == TREE_UNKNOWN:
            reasons.append(_REASON_NO_TREE)
        return BuildIdentity(value=env_sha, method=METHOD_INJECTED, tree=tree,
                             kind=kind, reason=_join(reasons))

    if is_version(env_app):
        # ★`APP_VERSION` 은 커밋을 식별하지 않는다★ 트리를 재도 승격하지 않는다.
        return BuildIdentity(value=env_app, method=METHOD_INJECTED,
                             tree=TREE_UNKNOWN, kind=kind, reason=_REASON_APP)

    if is_version(measured_sha):
        if tree == TREE_UNKNOWN:
            reasons.append(_REASON_NO_TREE)
        return BuildIdentity(value=measured_sha, method=METHOD_MEASURED,
                             tree=tree, kind=kind, reason=_join(reasons))

    # ★여기서 `"dev"` 를 만들지 않는다★ — 이 프로그램의 전부다.
    return BuildIdentity(value=None, method=METHOD_UNKNOWN, tree=TREE_UNKNOWN,
                         kind=kind, reason=probe_reason or _REASON_NO_PROBE)


def _join(reasons: list[str]) -> str | None:
    return " · ".join(reasons) if reasons else None


def as_identity(x: BuildIdentity | str | None) -> BuildIdentity:
    """문자열도 받는다 — 단 ★트리를 기록하지 않은 값은 미상★ 이다.

    메니페스트 파일의 `code_version` 처럼 옛 기록은 문자열 하나뿐이다. 그것을
    깨끗하다고 가정하면 지금 고치려는 바로 그 거짓 일치가 돌아온다.
    """
    if isinstance(x, BuildIdentity):
        return x
    return BuildIdentity(value=x if isinstance(x, str) else None,
                         method=METHOD_UNKNOWN, tree=TREE_UNKNOWN,
                         reason=_REASON_NO_TREE)


def versions_comparable(a: BuildIdentity | str | None,
                        b: BuildIdentity | str | None) -> bool | None:
    """두 빌드가 같은가. ★대답할 수 없으면 `None` 이다★

    `True`/`False` 는 **양쪽이 모두 깨끗한 트리에서 온 진짜 버전일 때만** 낸다.

    · 한쪽이라도 버전이 아니면(`"dev"`·`None`·빈 문자열) → `None`
    · 한쪽이라도 트리가 깨끗하지 않거나 미상이면 → `None`

    ★둘째 규칙이 이 함수의 존재 이유다★ — 같은 dirty SHA 두 개는 같은 코드가
    아니다. 옛 구현은 `"dev" == "dev"` 로 **항상 참**을 냈고, 그래서 노후화
    검사가 한 번도 발동하지 못했다.
    """
    ia, ib = as_identity(a), as_identity(b)
    if not (is_version(ia.value) and is_version(ib.value)):
        return None
    if ia.tree != TREE_CLEAN or ib.tree != TREE_CLEAN:
        return None
    return ia.value == ib.value


def identity_label(idents: Mapping[str, BuildIdentity]) -> dict[str, Any]:
    """응답에 싣는 정직 블록 — **이 실행을 구별할 수 있는가**.

    ★`identifiable` 은 재현 가능성이 아니다★ 세 상태를 쓴다:

    · `True`  — 모든 축이 진짜 버전이고 트리가 깨끗하다
    · `False` — ★관측된 결함★ 버전이 없거나(`"dev"`) 트리가 더럽다
    · `None`  — 미상. 트리를 재지 못했다. **통과가 아니다**
    """
    versions = {name: i.as_dict() for name, i in idents.items()}
    known = sorted(n for n, i in idents.items() if is_version(i.value))
    unknown = sorted(n for n, i in idents.items() if not is_version(i.value))
    dirty = sorted(n for n, i in idents.items() if i.tree == TREE_DIRTY)
    foggy = sorted(n for n, i in idents.items() if i.tree == TREE_UNKNOWN)

    if not idents:
        identifiable: bool | None = None
    elif unknown or dirty:
        identifiable = False
    elif foggy:
        identifiable = None
    else:
        identifiable = True

    return {"versions": versions, "known": known, "unknown": unknown,
            "dirty": dirty, "tree_unknown": foggy,
            "identifiable": identifiable, "note": _LABEL_NOTE}
