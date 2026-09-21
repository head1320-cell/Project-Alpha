"""KIS 업무 코드의 표 — ★관측은 뜻을 주지 않는다★ (AS2)
==============================================================================
증거 파일: `docs/specs/kis-rt-cd-evidence.json` · 수집기
`scripts/collect_kis_rt_cd.py` · 종류·책임 소재 어휘 `src/domain/kis_failure.py`

## 왜 이 모듈이 생겼나

AR 이 KIS 호출 실패를 일곱 종류로 갈랐지만, 가장 많이 나오는 종류
(`business` = HTTP 200 + `rt_cd != "0"`)의 ★뜻을 모른다★. 장 종료 같은 정상
업무 응답과 KIS 장애가 **같은 breaker 카운터**에 들어가는데, 둘을 가르려면
코드를 뜻으로 옮기는 표가 있어야 하고 그 표가 저장소 어디에도 없었다.

이 모듈은 ★표를 확보하지 않는다 — 표의 자리를 만든다.★ 실측(2026-09-21):
이 환경은 `apiportal`·`openapi.koreainvestment.com` 에 프록시 CONNECT 403 이라
공식 문서도 실계좌 응답도 얻을 수 없다. 표를 얻는 것은 접근 권한이 있는
사람의 일이고, 여기서 하는 일은 그 사람이 채울 자리와 ★채워야 할 목록★을
만들어 두는 것이다.

## ★정직성 핵심 — 코드를 100번 봐도 뜻은 모른다★

그래서 등급을 하나로 두되 **관측 등급이 적용선 아래**에 있게 한다:

    K0  증거 없음 — 추측. 이 파일에 쓰지 않는다
    K1  관측 — 이 코드를 응답에서 봤다. ★뜻은 모른다★     ← 수집기가 만든다
    K2  KIS 공식 문서에 근거                              ← 사람이 적는다
    K3  문서 + 실계좌 응답 교차 확인                      ← 사람이 적는다

`min_grade_to_apply` 가 `K2` 이므로 수집기가 아무리 돌아도 책임 소재는
`unknown` 이다. `src/data/source_registry.py` 가
`docs/specs/ecos-frequency-evidence.json` 을 읽는 구조를 그대로 잇는다 —
사실은 코드에, ★그 사실의 증거★는 체크인된 JSON 에, 그리고 ★확신이 모자라면
적용하지 않는다★.

## ★이 모듈이 주장하지 않는 것★

- **코드의 뜻을 말하지 않는다.** 표는 비어 있고, 비어 있는 것이 정직한
  상태다 — 채워진 척하면 추측이 검증된 사실과 구분되지 않는다.
- **`msg1` 을 해석하지 않는다.** 한국어 문구를 패턴 매칭해 "이건 업무 거절"
  이라고 단정하는 것은 ★어휘로 걸기★이고, 이 저장소가 확인한 적 없는 것을
  주장하는 일이다(AR 이 같은 이유로 거부했다).
- **breaker 가 무엇을 세는지 바꾸지 않는다.** 표가 채워져도 세는 것은
  그대로다 — `COUNTED_BY_BREAKER` 는 종류 단위이고, 바꾸는 것은 실거래 호출
  경로 동작 변경이라 별도 승인 사항이다(CLAUDE.md §6).
- **`kis_failure.fault_of(kind)` 를 건드리지 않는다.** 그것은 종류에 대한
  총함수이고, 표 참조는 `enriched_label()` 이 따로 한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.domain.kis_failure import (
    FAULT_UNKNOWN,
    FAULTS,
    KIND_BUSINESS,
)

#: 등급 순서 — 낮은 확신이 조용히 사실이 되는 경로를 막는다(ECOS 선례).
CODE_GRADES = ("K0", "K1", "K2", "K3")

#: 수집기가 만드는 등급. ★적용선 아래여야 한다★ — 관측이 뜻이 되면 안 된다.
OBSERVED_GRADE = "K1"

#: 증거 파일이 등급을 말하지 않을 때의 적용선.
DEFAULT_MIN_GRADE = "K2"

#: 체크인된 증거 파일. 환경변수로 덮어쓸 수 있다 — 갓 수집한 파일을 운영
#: 파일을 건드리지 않고 시험해 보기 위한 것이다(ECOS 의 관용구와 같다).
EVIDENCE_PATH = (Path(__file__).resolve().parents[2]
                 / "docs" / "specs" / "kis-rt-cd-evidence.json")

_ENV_PATH = "KIS_RT_CD_EVIDENCE_PATH"

#: `msg_cd` 를 못 받았을 때의 열쇠 조각. ★미상 ≠ 미지원★ — 이 저장소는 KIS
#: 응답 봉투에 그 필드가 있는지 확인한 적이 없다.
MSG_CD_UNKNOWN = "미상"

#: 실행 모드를 모르는 관측. ★모의와 실계좌를 합치면 수치가 뜻을 잃는다★
MODE_UNKNOWN = "미상"

_NO_ENTRY = (
    "이 코드는 표에 없습니다 — 저장소가 뜻을 모릅니다. ★본 적이 있다는 것과 "
    "뜻을 안다는 것은 다릅니다★: 관측은 코드가 존재한다는 사실만 주고, "
    "책임 소재는 KIS 문서나 실계좌 응답이 있어야 정할 수 있습니다.")

_BELOW_FLOOR = (
    "이 코드의 증거가 적용선에 못 미칩니다(관측만 있고 뜻이 확인되지 "
    "않았습니다). ★확신이 모자라면 적용하지 않습니다★ — 미상은 통과가 "
    "아닙니다.")

_BAD_FAULT = (
    "이 코드의 책임 소재가 어휘 밖의 값입니다 — 어휘 밖의 값은 사실이 "
    "아닙니다. 쓸 수 있는 값: provider · self · unknown.")

_NOTE = (
    "이 판정은 ★표에 무엇이 적혀 있는가★만 말합니다. 표가 비어 있으면 모든 "
    "코드가 미상이고, 그것이 이 저장소의 정직한 현재 상태입니다 — KIS 에 "
    "닿지 못해 문서도 실계좌 응답도 없습니다. 관측 횟수는 뜻의 증거가 "
    "아닙니다.")


def _path() -> Path:
    """★호출 시점에 환경을 읽는다★ — 임포트 시점에 굳히면 덮어쓸 수 없다."""
    override = os.getenv(_ENV_PATH, "").strip()
    return Path(override) if override else EVIDENCE_PATH


def _load_doc() -> dict[str, Any]:
    """증거 파일 전체. ★없거나 깨져도 예외를 내지 않는다★

    증거가 없는 것은 오류가 아니라 **정상 상태**다(지금이 그렇다). 여기서
    터지면 이 모듈을 임포트하는 모든 경로가 함께 죽고, 그것은 "코드의 뜻을
    모른다" 보다 훨씬 나쁜 결과다.
    """
    try:
        doc = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def load_evidence() -> tuple[dict[str, dict], str]:
    """(코드별 증거, 적용선). 깨진 파일은 빈 표로 접힌다."""
    doc = _load_doc()
    codes = doc.get("codes")
    if not isinstance(codes, dict):
        codes = {}
    floor = doc.get("min_grade_to_apply")
    return codes, (floor if floor in CODE_GRADES else DEFAULT_MIN_GRADE)


def code_key(rt_cd: Any, msg_cd: Any) -> str:
    """표의 열쇠. ★둘이 필요하다★

    `rt_cd` 는 이 저장소에서 `!= "0"` 이분법으로만 쓰이는 거친 값이라 혼자서는
    서로 다른 업무 응답을 가르지 못한다. `msg_cd` 가 없으면 그 사실을 열쇠에
    남긴다 — ★빠뜨리면 서로 다른 사실이 한 칸에 합쳐진다★.
    """
    left = "" if rt_cd is None else str(rt_cd).strip()
    right = "" if msg_cd is None else str(msg_cd).strip()
    return f"{left}/{right or MSG_CD_UNKNOWN}"


def _applies(entry: Any, floor: str) -> bool:
    """★등급이 적용선 이상일 때만 사실이 된다★ — 어휘 밖의 등급은 사실이 아니다."""
    if not isinstance(entry, dict):
        return False
    grade = entry.get("grade")
    if grade not in CODE_GRADES:
        return False
    return CODE_GRADES.index(grade) >= CODE_GRADES.index(floor)


def meaning_of(rt_cd: Any, msg_cd: Any) -> dict[str, Any] | None:
    """코드의 뜻. ★증거가 충분할 때만★ — 그 외에는 `None`(미상)."""
    codes, floor = load_evidence()
    entry = codes.get(code_key(rt_cd, msg_cd))
    if not _applies(entry, floor):
        return None
    return {
        "meaning": entry.get("meaning"),
        "fault": entry.get("fault"),
        "grade": entry.get("grade"),
        "evidence_source": entry.get("evidence_source"),
        "probed_at": entry.get("probed_at"),
    }


def fault_from_table(rt_cd: Any, msg_cd: Any) -> dict[str, Any]:
    """표가 말하는 책임 소재. ★모르면 사유를 함께 낸다★ (사유 없는 미상 금지)."""
    codes, floor = load_evidence()
    key = code_key(rt_cd, msg_cd)
    entry = codes.get(key)
    if not isinstance(entry, dict):
        return {"fault": FAULT_UNKNOWN, "reason": _NO_ENTRY, "key": key}
    if not _applies(entry, floor):
        return {"fault": FAULT_UNKNOWN, "reason": _BELOW_FLOOR, "key": key}
    fault = entry.get("fault")
    if fault not in FAULTS:
        return {"fault": FAULT_UNKNOWN, "reason": _BAD_FAULT, "key": key}
    return {"fault": fault, "reason": None, "key": key}


def enriched_label(label: dict[str, Any]) -> dict[str, Any]:
    """`kis_failure.failure_label` 결과에 표를 입힌다. ★입력을 바꾸지 않는다★

    ★업무 응답에만 입힌다★ — 이것은 `rt_cd` 의 표이지 전송 오류의 표가
    아니다. 표가 비어 있으면 아무것도 바뀌지 않고, 그것이 지금의 동작이다.
    """
    out = dict(label)
    rt_cd, msg_cd = out.get("rt_cd"), out.get("msg_cd")
    if out.get("kind") != KIND_BUSINESS:
        out["table"] = {"meaning": None, "fault": None, "grade": None,
                        "evidence_source": None, "reason": None,
                        "key": None, "note": _NOTE}
        return out

    decided = fault_from_table(rt_cd, msg_cd)
    known = meaning_of(rt_cd, msg_cd) or {}
    out["table"] = {
        "meaning": known.get("meaning"),
        "fault": known.get("fault"),
        "grade": known.get("grade"),
        "evidence_source": known.get("evidence_source"),
        "reason": decided["reason"],
        "key": decided["key"],
        "note": _NOTE,
    }
    if decided["fault"] != FAULT_UNKNOWN:
        out["fault"] = decided["fault"]
        out["fault_reason"] = None
    return out


def _as_text(value: Any) -> str | None:
    """타임스탬프를 문자열로. DB 는 `datetime` 을, JSON 은 문자열을 준다."""
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def fold_observations(rows: Any) -> list[dict[str, Any]]:
    """감사 행을 `(rt_cd, msg_cd, 실행 모드)` 별로 접는다. ★순수★

    ★실행 모드를 열쇠에 넣는다★ — 모의와 실계좌 관측을 합치면 그 수치는
    아무것도 뜻하지 않는다. 모드를 모르는 행은 버리지 않고 미상으로 남긴다.
    `msg1` 은 ★해석하지 않고 그대로★ 한 줄만 표본으로 남긴다.
    """
    folded: dict[tuple, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        failure = row.get("failure")
        if not isinstance(failure, dict):
            continue
        if failure.get("kind") != KIND_BUSINESS:
            continue
        rt_cd = failure.get("rt_cd")
        msg_cd = failure.get("msg_cd")
        mode = row.get("execution_mode") or MODE_UNKNOWN
        key = (str(rt_cd) if rt_cd is not None else None,
               str(msg_cd) if msg_cd is not None else None, str(mode))
        ts = _as_text(row.get("timestamp"))
        slot = folded.get(key)
        if slot is None:
            folded[key] = {
                "rt_cd": key[0], "msg_cd": key[1], "execution_mode": key[2],
                "count": 1, "first_seen": ts, "last_seen": ts,
                "sample_msg1": failure.get("kis_msg"),
                "key": code_key(key[0], key[1]),
            }
            continue
        slot["count"] += 1
        if ts is not None:
            if slot["first_seen"] is None or ts < slot["first_seen"]:
                slot["first_seen"] = ts
            if slot["last_seen"] is None or ts > slot["last_seen"]:
                slot["last_seen"] = ts
        if slot["sample_msg1"] is None:
            slot["sample_msg1"] = failure.get("kis_msg")
    return sorted(folded.values(),
                  key=lambda d: (-d["count"], d["key"], d["execution_mode"]))


def gap_list(folded: Any) -> list[dict[str, Any]]:
    """본 적은 있으나 뜻을 모르는 코드. ★이 프로그램의 산출물★

    접근 권한이 있는 사람이 채울 **작업 목록**이다. 많이 본 것이 먼저 온다 —
    표를 채우는 순서가 곧 안전 역전을 줄이는 순서이기 때문이다.
    ★관측해 둔 것(`K1`)은 아는 것이 아니므로 여전히 목록에 남는다.★
    """
    gaps = [dict(item) for item in (folded or [])
            if meaning_of(item.get("rt_cd"), item.get("msg_cd")) is None]
    for gap in gaps:
        gap["reason"] = fault_from_table(gap.get("rt_cd"),
                                         gap.get("msg_cd"))["reason"]
    return gaps


def table_summary() -> dict[str, Any]:
    """표의 현재 상태. ★관측만 있는 항목은 표의 크기가 아니다★

    세어 두면 채워진 것처럼 보인다 — `size` 는 **적용되는** 항목만 센다.
    """
    codes, floor = load_evidence()
    doc = _load_doc()
    applied = sum(1 for entry in codes.values() if _applies(entry, floor))
    return {
        "size": applied,
        "observed_only": len(codes) - applied,
        "min_grade": floor,
        "grades": list(CODE_GRADES),
        "why_empty": doc.get("why_empty"),
        "path": str(_path()),
        "note": _NOTE,
    }
