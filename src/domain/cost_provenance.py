"""비용 요율의 **런타임 출처** — ★문이 정한 수수료를 문이 밝힌다★ (AZ, 순수)
==============================================================================
증거 `docs/specs/cost-rate-evidence.json` · 수집기 `scripts/collect_cost_rates.py` ·
소비자 `src/kis_backtest_engine._cost_model_block` · 검증
`tests/test_cost_provenance.py` · 선례 `src/domain/kis_rt_cd.py`(AS 의 증거 파일)

## 1. 무엇이 없었나 (실측 2026-09-22)

같은 전략·같은 데이터인데 왕복 비용이 갈린다:

    15bp 진영(screener·메인엔진·graph·legacy)      round_trip = 40.0bp
    1.5bp 진영(stage11·stage12·realism·multi)      round_trip = 13.0bp

차이를 만드는 것은 ★어느 문으로 들어왔는가★ 뿐이다. 요청이 값을 안 실으면
**문이 수수료를 정하는데**, `cost_model` 블록은 적용된 요율만 말하고 ★그 값이
어디서 왔는지는 말하지 않았다★.

CLAUDE.md 4절이 폴백을 허용하는 조건은 넷이다 — *"⑴ 의미가 알려져 있고
⑵ **라벨이 붙고** ⑶ 동등 품질로 위장할 수 없고 ⑷ **관측·테스트 가능**할 때"*.
⑵⑷ 가 없었다. 이 모듈이 그 둘을 채운다.

## 2. ★이미 있는 것과 다른 축이다★

`src/engine/cost_model_registry.py`(AK2)가 **열넷 자리**를 이미 등록했다.
그것은 **정적** 축이다 — *"이 자리의 기본값은 무엇이고 어디 박혀 있나"*.
이 모듈은 **런타임** 축이다 — *"이 **실행**의 요율을 요청이 줬나 문이 채웠나"*.

★두 모듈은 서로를 임포트하지 않는다★(테스트가 AST 로 건다). 섞으면 다음
사람이 어느 쪽을 고쳐야 하는지 모른다.

## 3. ★출처 ⟂ 근거 — 여기서도 두 축이다★

| 축 | 값 | 무엇 |
|---|---|---|
| **출처** | `request`·`door_default`·`unknown` | 이 실행의 요율을 **누가 정했나** |
| **근거** | `never_measured`·`observed` | 그 요율을 **재본 적이 있나** |

★`unknown` 은 `door_default` 가 아니다★ — 문을 안 이었으면 *"요청이 안 줬다"*
를 **알 수 없다**. 낙관적으로 기본값이라 부르면 *안 이은 것*과 *안 준 것*이 한
칸에 합쳐진다.

## 4. ★이 모듈이 하지 않는 것★

- **기본값을 통일하지 않는다.** 15bp 도 1.5bp 도 이 저장소가 재본 적이 없다 —
  안 재본 값으로 수렴시키면 ★거짓 합의★ 다. 대신 **무엇이 참이 되면 통일할
  수 있는지**를 증거 파일의 `min_grade_to_unify` 가 적는다.
- **요율 값을 한 자리도 바꾸지 않는다.** 읽기만 한다.
- **어느 요율이 옳다고 말하지 않는다.**
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

#: ★실측이 착지할 자리★ — 비어 있는 것이 정직한 현재 상태다(AS 선례).
EVIDENCE_PATH = "docs/specs/cost-rate-evidence.json"

# ── 축 ① 출처 — 누가 이 요율을 정했나 ────────────────────────────────────
RATE_REQUEST = "request"
RATE_DOOR_DEFAULT = "door_default"
#: ★문이 안 실어 보냈다 — 거짓이 아니라 미상이다★
RATE_UNKNOWN = "unknown"
#: ★문에 이 요율 칸이 **없다**★(BA) — 요청자가 줄 방법이 없었으므로
#: `door_default`(*"요청이 안 실어서"*)라고 부르면 사유가 거짓이 된다.
#: 실측: `ImportAndBacktestRequest` 는 두 칸 다 없고 `OptimizeRequest` 는
#: `slippage_rate` 만 없다 — ★한 요청 안에서도 성분마다 다르다★.
RATE_NO_FIELD = "door_has_no_field"

RATE_ORIGINS = (RATE_REQUEST, RATE_DOOR_DEFAULT, RATE_NO_FIELD, RATE_UNKNOWN)

# ── 축 ② 근거 — 그 요율을 재본 적이 있나 (다른 축) ───────────────────────
BASIS_NEVER_MEASURED = "never_measured"
BASIS_OBSERVED = "observed"

#: 증거 파일의 등급. ★`C1`(관측)은 적용선 아래다★ — 체결을 100번 본다고
#: 증권사 수수료표를 알게 되지는 않는다(AS 가 `rt_cd` 에서 세운 논리).
UNIFY_GRADES = ("C0", "C1", "C2", "C3")
DEFAULT_MIN_GRADE_TO_UNIFY = "C2"

#: 요청 필드 이름 → 이 모듈이 쓰는 성분 이름. ★문마다 필드 이름이 같다★(실측).
_FIELD_BY_PART = {"commission": "commission_rate", "slippage": "slippage_rate"}

_NOTE = (
    "이 블록은 요율이 ★어디서 왔는가★만 말합니다 — 그 요율이 옳은지는 "
    "말하지 않습니다. 실측(2026-09-22): 요청이 요율을 안 실으면 문이 정하고, "
    "왕복 비용이 screener 계열 40.0bp 와 stage11 계열 13.0bp 로 갈립니다. "
    "★두 값 모두 이 저장소가 재본 적이 없어 통일하지 않았습니다★ — 안 재본 "
    "값으로 수렴시키면 불일치가 거짓 합의가 됩니다.")

_REASON_REQUEST = (
    "요청이 이 요율을 명시했습니다 — 문의 기본값이 쓰이지 않았습니다.")

_REASON_DOOR = (
    "요청이 이 요율을 안 실어서 문({door})의 기본값이 채웠습니다. "
    "★같은 백테스트를 다른 문으로 부르면 값이 달라집니다.★")

_REASON_NO_FIELD = (
    "문({door})에 이 요율 칸이 없습니다 — ★요청자가 줄 방법이 없고★ 호출부의 "
    "함수 기본값이 채웁니다. 안 준 것과 줄 수 없는 것은 다릅니다.")

_REASON_UNKNOWN = (
    "이 실행 경로는 요청이 요율을 명시했는지를 실어 나르지 않습니다 — "
    "요청이 준 값인지 문의 기본값인지 ★알 수 없습니다★. "
    "기본값이라고 단정하지 않습니다.")

_BASIS_REASON_NEVER = (
    "이 요율을 이 저장소가 재본 적이 없습니다 — {path} 의 관측이 비어 "
    "있습니다. 통일은 그 파일이 {floor} 이상으로 채워진 뒤의 일입니다.")

_BASIS_REASON_OBSERVED = (
    "{path} 에 이 성분의 관측이 있습니다. ★관측은 계약 요율이 아닙니다★ — "
    "체결에서 계산한 bp 는 우대·이벤트·최소수수료에 흔들립니다.")


# ── ★못 잇는 자리 — 종류가 다르면 처방이 다르다★ (BA) ───────────────────
#: `cost_model_registry.COST_SITES`(정적 축)의 열넷 중 런타임 출처를 **물을 수
#: 없는** 자리들. ★"아직 안 한 일" 과 "영구적으로 맞는 답" 을 가른다.★
#: ★BA 에 있던 `other_engine`(다른 엔진이라 블록이 없다)은 BB 가 세 엔진에
#: 블록을 주면서 비었다 — 쓰는 곳 없는 어휘를 남기지 않으려고 뺐다.★
UNWIRED_NO_REQUEST = "no_request"
UNWIRED_DB_DEFAULT = "db_default"
UNWIRED_CONFIG_LAYER = "config_layer"

UNWIRED_KINDS = (UNWIRED_NO_REQUEST, UNWIRED_DB_DEFAULT, UNWIRED_CONFIG_LAYER)

#: 런타임 출처를 **싣는** 자리(`cost_model` 블록을 내는 엔진에 닿는다).
#: ★손으로 센 개수를 적지 않는다★ — 테스트가 레지스트리와 대조한다.
#: 뒤의 셋은 BB — 거래별로 재지 않는 엔진이라 `door_cost_block` 이 정책만 싣는다.
WIRED_SITE_KEYS = ("screener_routes", "legacy_schemas",
                   "stage11_routes", "stage12_routes", "graph_schema")

_PERMANENT = ("이 자리는 ★영구적으로 미상이 맞다★ — 승급 조건이 없다.")


@dataclass(frozen=True)
class UnwiredCostSite:
    """런타임 출처를 물을 수 없는 자리. ★왜 못 묻는지가 종류마다 다르다★

    `version_registry.MissingAxis`·`signal_supply.UnsuppliedSignal` 과 같은
    모양이다. `promotes_when` 이 ★"언제 이을 수 있나" 또는 "영구적이다"★ 를
    적는다 — 영구적인 것을 임시라고 적으면 갚을 수 없는 부채가 된다.
    """

    key: str            # `cost_model_registry.COST_SITES` 의 key
    kind: str
    reason: str
    promotes_when: str
    #: ★이 자리가 **영구적으로** 미상인가★ — "아직 안 한 일" 과 구조로
    #: 가른다. 문자열을 읽어 판정하면 문구를 고칠 때마다 판정이 흔들린다
    #: (어휘로 걸지 않는다 — 이 저장소가 반복해 확인한 규율이다).
    permanent: bool = False


UNWIRED_SITES: tuple[UnwiredCostSite, ...] = (
    # ── 요청이 없다 — ★호출부가 값을 정하는 것이 설계다★ ───────────────
    UnwiredCostSite(
        key="kis_backtest_engine", kind=UNWIRED_NO_REQUEST,
        reason=("dataclass 기본값입니다 — 요청이 없으므로 \"요청이 "
                "명시했는가\" 라는 질문 자체가 성립하지 않습니다. 이 자리의 "
                "런타임 출처는 이 자리를 부른 문이 답합니다."),
        promotes_when=_PERMANENT, permanent=True),
    UnwiredCostSite(
        key="kis_backtest_engine_fn", kind=UNWIRED_NO_REQUEST,
        reason=("함수 기본값입니다 — 요청이 없습니다. 문이 요율을 안 넘기면 "
                "여기가 채우고, 그 사실은 문 쪽의 door_has_no_field 가 "
                "말합니다."),
        promotes_when=_PERMANENT, permanent=True),
    UnwiredCostSite(
        key="kis_portfolio_analyzer", kind=UNWIRED_NO_REQUEST,
        reason=("함수 기본값입니다 — 요청이 없으므로 \"요청이 명시했는가\" 가 "
                "성립하지 않습니다."),
        promotes_when=_PERMANENT, permanent=True),
    UnwiredCostSite(
        key="graph_runner", kind=UNWIRED_NO_REQUEST,
        reason=("함수 기본값입니다 — 요청이 없습니다. ★이 러너는 호출자가 "
                "0건입니다★(BB 실측: src/ 에 import 하는 곳이 없다) — "
                "graph 문은 dag_runner 로 갑니다. 쓸 곳이 없으므로 블록을 "
                "만들지 않았습니다."),
        promotes_when=_PERMANENT, permanent=True),
    UnwiredCostSite(
        key="realism_engine", kind=UNWIRED_NO_REQUEST,
        reason=("dataclass 기본값입니다 — 요청이 없으므로 \"요청이 "
                "명시했는가\" 가 성립하지 않습니다."),
        promotes_when=_PERMANENT, permanent=True),
    UnwiredCostSite(
        key="multi_strategy_backtest", kind=UNWIRED_NO_REQUEST,
        reason=("dataclass 기본값입니다 — 요청이 없으므로 \"요청이 "
                "명시했는가\" 가 성립하지 않습니다."),
        promotes_when=_PERMANENT, permanent=True),
    # ── DB 기본값 — ★저장 시점이라 축이 다르다★ ────────────────────────
    UnwiredCostSite(
        key="multibacktest_schema", kind=UNWIRED_DB_DEFAULT,
        reason=("DDL 의 DEFAULT 입니다 — 요청이 아니라 ★저장 시점에 DB 가★ "
                "채웁니다. 런타임 출처 질문(요청이 줬나)이 성립하지 "
                "않습니다."),
        promotes_when=("★축이 다르므로 승급이 아니라 별개 질문입니다★ — "
                       "\"이 행의 값을 누가 썼나\" 는 감사 축이 답할 일입니다."),
        permanent=True),
    # ── 설정 계층 — ★이미 단일 출처다★ ─────────────────────────────────
    UnwiredCostSite(
        key="execution_plan", kind=UNWIRED_CONFIG_LAYER,
        reason=("이 자리는 리터럴이 아니라 market_rules 설정 계층을 읽습니다 "
                "(rate_source=\"market_rules\") — 한 곳에서 고쳐지므로 문마다 "
                "갈리는 문제가 애초에 없습니다."),
        promotes_when=("★해당 없습니다★ — 이미 단일 출처라 이을 대상이 "
                       "아닙니다."),
        permanent=True),
    UnwiredCostSite(
        key="market_rules", kind=UNWIRED_CONFIG_LAYER,
        reason=("요율 **단일 출처 자체**입니다 — 문이 아니라 설정입니다."),
        promotes_when=("★해당 없습니다★ — 이 자리가 곧 기준입니다."),
        permanent=True),
)

UNWIRED_BY_KEY = {e.key: e for e in UNWIRED_SITES}


def _load_doc() -> dict[str, Any]:
    """증거 파일. ★깨진 파일이 예외로 번지지 않는다★ — 빈 문서로 접힌다."""
    try:
        raw = pathlib.Path(EVIDENCE_PATH).read_text(encoding="utf-8")
        doc = json.loads(raw)
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def load_rate_evidence() -> tuple[dict[str, Any], str]:
    """(성분별 관측, 통일 적용선). 없거나 깨졌으면 빈 표 + 기본 적용선."""
    doc = _load_doc()
    observed = doc.get("observed")
    if not isinstance(observed, dict):
        observed = {}
    floor = doc.get("min_grade_to_unify")
    if floor not in UNIFY_GRADES:
        floor = DEFAULT_MIN_GRADE_TO_UNIFY
    return observed, floor


def _origin(door: Any, explicit: Any, available: Any,
            part: str) -> tuple[str, str]:
    """(출처, 사유). ★세 가지가 다르다★

    ⑴ 안 이은 경로 → 미상 ⑵ 문이 묻지 않는다 → 줄 방법이 없었다
    ⑶ 문이 묻는데 안 줬다 → 문의 기본값. ★셋을 한 칸에 넣으면 처방이 섞인다.★
    """
    if explicit is None or door is None:
        return RATE_UNKNOWN, _REASON_UNKNOWN
    field = _FIELD_BY_PART[part]
    # ★`available` 이 `None` 이면 "문이 그 칸을 갖는지 모른다"★ — 예전
    #   판정 그대로 둔다(AZ 가 이은 자리가 안 깨진다).
    if available is not None and field not in set(available):
        return RATE_NO_FIELD, _REASON_NO_FIELD.format(door=door)
    if field in set(explicit):
        return RATE_REQUEST, _REASON_REQUEST
    return RATE_DOOR_DEFAULT, _REASON_DOOR.format(door=door)


def _basis(observed: dict[str, Any], floor: str, part: str) -> tuple[str, str]:
    """(근거, 사유). ★출처와 다른 축이다★ — 누가 정했나 ⟂ 재봤나."""
    entry = observed.get(part)
    if isinstance(entry, dict) and entry:
        return BASIS_OBSERVED, _BASIS_REASON_OBSERVED.format(path=EVIDENCE_PATH)
    return BASIS_NEVER_MEASURED, _BASIS_REASON_NEVER.format(
        path=EVIDENCE_PATH, floor=floor)


def rate_provenance(*, door: Any = None, explicit: Any = None,
                    available: Any = None,
                    policy: Any = None) -> dict[str, Any]:
    """이 실행의 요율이 **어디서 왔는가**.

    Args:
        door: 요청을 받은 문의 이름(`"screener"`·`"stage11"` …).
            ★`None` 이면 안 이은 경로이고 결과는 미상이다.★
        explicit: 요청이 **명시한** 필드 이름 집합(pydantic `model_fields_set`).
            `None` 이면 미상 — 빈 집합(*"아무것도 안 줬다"*)과 다르다.
        available: 문이 **가진** 필드 이름 집합(pydantic `model_fields`).
            ★`None` 이면 "문이 그 칸을 갖는지 모른다"★ 이고 예전 판정 그대로다.
        policy: `cost_model.CostPolicy`. 적용된 요율을 **읽기만** 한다.

    Returns:
        성분별 `{origin, door, basis, bps, reason, basis_reason}` + `note`.
    """
    observed, floor = load_rate_evidence()
    out: dict[str, Any] = {"note": _NOTE, "min_grade_to_unify": floor}
    for part in _FIELD_BY_PART:
        origin, reason = _origin(door, explicit, available, part)
        basis, basis_reason = _basis(observed, floor, part)
        out[part] = {
            "origin": origin,
            "door": door if origin != RATE_UNKNOWN else None,
            # ★적용된 값은 읽기만 한다 — 정하지 않는다★
            "bps": getattr(policy, f"{part}_bps", None),
            "basis": basis,
            "reason": reason,
            "basis_reason": basis_reason,
        }
    return out


def door_cost_block(*, commission_rate: Any, slippage_rate: Any,
                    cost_door: str, cost_explicit_fields: Any,
                    cost_available_fields: Any, engine: str, supported: Any,
                    charge_impact: bool = False,
                    notes: dict[str, str] | None = None,
                    totals: dict[str, Any] | None = None) -> dict[str, Any]:
    """거래별로 재지 않는 엔진의 `cost_model` 블록을 **문에서** 만든다 (BB2).

    ★엔진 내부는 건드리지 않는다★ — 엔진에 넘긴 **그 요율**로 정책을 만들고,
    요율의 출처는 메인 엔진과 같은 `rate_provenance` 가 답한다. 요율 → bp
    환산은 메인 엔진(`policy_from_config`)과 같은 `× 1e4` 다.
    """
    from src.domain.cost_model import CostPolicy, policy_only_block

    policy = CostPolicy(commission_bps=float(commission_rate) * 1e4,
                        slippage_bps=float(slippage_rate) * 1e4,
                        charge_impact=bool(charge_impact))
    return policy_only_block(
        policy, engine=engine, supported=supported, notes=notes, totals=totals,
        provenance=rate_provenance(door=cost_door, explicit=cost_explicit_fields,
                                   available=cost_available_fields,
                                   policy=policy))
