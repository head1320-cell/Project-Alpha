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
from typing import Any

#: ★실측이 착지할 자리★ — 비어 있는 것이 정직한 현재 상태다(AS 선례).
EVIDENCE_PATH = "docs/specs/cost-rate-evidence.json"

# ── 축 ① 출처 — 누가 이 요율을 정했나 ────────────────────────────────────
RATE_REQUEST = "request"
RATE_DOOR_DEFAULT = "door_default"
#: ★문이 안 실어 보냈다 — 거짓이 아니라 미상이다★
RATE_UNKNOWN = "unknown"

RATE_ORIGINS = (RATE_REQUEST, RATE_DOOR_DEFAULT, RATE_UNKNOWN)

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


def _origin(door: Any, explicit: Any, part: str) -> tuple[str, str]:
    """(출처, 사유). ★안 이은 문은 미상이지 기본값이 아니다★"""
    if explicit is None or door is None:
        return RATE_UNKNOWN, _REASON_UNKNOWN
    if _FIELD_BY_PART[part] in set(explicit):
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
                    policy: Any = None) -> dict[str, Any]:
    """이 실행의 요율이 **어디서 왔는가**.

    Args:
        door: 요청을 받은 문의 이름(`"screener"`·`"stage11"` …).
            ★`None` 이면 안 이은 경로이고 결과는 미상이다.★
        explicit: 요청이 **명시한** 필드 이름 집합(pydantic `model_fields_set`).
            `None` 이면 미상 — 빈 집합(*"아무것도 안 줬다"*)과 다르다.
        policy: `cost_model.CostPolicy`. 적용된 요율을 **읽기만** 한다.

    Returns:
        성분별 `{origin, door, basis, bps, reason, basis_reason}` + `note`.
    """
    observed, floor = load_rate_evidence()
    out: dict[str, Any] = {"note": _NOTE, "min_grade_to_unify": floor}
    for part in _FIELD_BY_PART:
        origin, reason = _origin(door, explicit, part)
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
