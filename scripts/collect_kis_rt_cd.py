#!/usr/bin/env python3
"""KIS 업무 코드 관측을 수확한다 — ★관측만, 뜻은 사람이 적는다★ (AS5)
==============================================================================
증거 파일: `docs/specs/kis-rt-cd-evidence.json` · 표
`src/domain/kis_rt_cd.py` · 원료 `AuditTrail.kis_code_rows()`

## 무엇을 하나

AR 이 KIS 호출 실패를 일곱 종류로 갈랐지만 가장 많이 나오는 종류
(`business` = HTTP 200 + `rt_cd != "0"`)의 뜻을 저장소가 모른다. 장 종료 같은
정상 업무 응답과 KIS 장애가 **같은 breaker 카운터**에 들어가는 안전 역전이
거기서 나온다. 가르려면 `rt_cd`/`msg_cd` 를 뜻으로 옮기는 표가 필요하다.

이 스크립트는 그 표를 ★채우기 위한 목록★을 만든다: 감사 로그에 쌓인 관측을
접어 *"이 코드를 N번 봤고 뜻을 모른다"* 를 낸다.

## ★ECOS 스크립트와 결정적으로 다른 점★

`scripts/verify_ecos_meta.py` 는 API 를 **프로브**해 증거를 만든다. KIS 오류
코드는 일부러 일으킬 수 없다 — 장 종료를 만들 수도, 잔고를 비울 수도 없다.
그래서 이 수집기는 ★이미 일어난 것을 수확한다.★

## ★관측을 자동으로 사실로 만들지 않는다★

- `--write` 없이는 증거 파일을 **쓰지 않는다**(기본은 읽기 전용 리포트).
- 쓰더라도 등급은 `K1`(관측)이고, 적용선은 `K2` 다 — ★수집기가 아무리 돌아도
  책임 소재는 미상이다.★ 코드를 100번 본다고 그 뜻을 알게 되지 않는다.
- 병합은 ★사람이 적은 것을 덮지 않는다★ — `meaning`·`fault`·`grade`·
  `evidence_source`·`probed_at` 은 보존하고 `observed` 블록만 갱신한다.
- `first_seen` 은 ★UPDATE 하지 않는다★ — 같은 코드를 다시 봤다는 사실은 새
  정보가 아니고, 덮으면 "언제부터 알았나" 가 사라진다
  (`macro_observation_store` 가 `retrieved_at` 에 같은 규칙을 쓴다).
- `msg1` 은 표본 한 줄을 ★해석하지 않고 그대로★ 남긴다. 한국어 문구를 패턴
  매칭해 "이건 업무 거절" 이라고 단정하는 것은 어휘로 거는 일이다.

## 아무것도 못 봤으면 그렇게 말한다

`{"skipped": 사유}` 로 끝낸다. ★"0건 성공" 이라고 말하지 않는다★ — 0건 성공은
"확인했더니 문제가 없었다" 로 읽히고, 실제로는 아무것도 확인하지 않았다.

참고로 `MockKISClient` 는 언제나 `rt_cd="0"` 을 돌려주므로 ★mock 모드에서는 이
수집기가 영원히 빈손이다★ — CLAUDE.md §6 의 "mock 은 항상 흑자라 테스트를
통과한다" 와 같은 모양이다. 그래서 리포트가 어느 모드에서 돌았는지 라벨한다.

## 쓰는 법

    python3 scripts/collect_kis_rt_cd.py              # 읽기 전용 리포트
    python3 scripts/collect_kis_rt_cd.py --write      # 증거 파일에 병합

`--write` 뒤에는 ★사람이 diff 를 검토해 커밋한다.★
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.domain.kis_rt_cd import (  # noqa: E402
    OBSERVED_GRADE,
    fold_observations,
    gap_list,
    table_summary,
)

#: ★사람의 것★ — 병합이 절대 덮지 않는 칸.
CURATED_FIELDS = ("meaning", "fault", "grade", "evidence_source", "probed_at")

_NO_ROWS = (
    "감사 로그에 KIS 업무 응답(rt_cd != 0) 관측이 없습니다 — 확인한 것이 "
    "아니라 볼 것이 없었습니다. mock 모드라면 정상입니다: MockKISClient 는 "
    "언제나 rt_cd=0 을 돌려주므로 이 수집기는 영원히 빈손입니다.")

_NO_DB = (
    "감사 로그를 읽지 못했습니다 — 확인한 것이 아니라 읽지 못한 것입니다. "
    "DATABASE_URL 과 live_audit_trail 테이블을 확인하십시오.")

_NO_FILE = (
    "증거 파일을 읽지 못해 병합하지 않았습니다 — 없는 파일에 쓰면 헤더"
    "(min_grade_to_apply·why_empty)가 사라집니다.")


def _ran_under() -> dict:
    """★어느 환경에서 본 관측인지 라벨한다★ — 모드를 모르면 수치가 뜻을 잃는다."""
    from src.data.mock_gate import mock_allowed

    return {
        "mock_allowed": mock_allowed(),
        "kis_is_paper": os.getenv("KIS_IS_PAPER"),
    }


def _read_rows(limit: int):
    """감사 로그의 실패 행. 읽지 못하면 `None`(빈 목록과 구별한다)."""
    try:
        from src.database import get_engine
        from src.execution.audit_trail import AuditTrail

        return AuditTrail(get_engine()).kis_code_rows(limit=limit)
    except Exception:                                    # noqa: BLE001
        return None


def _collapse_modes(observed: list[dict]) -> dict[str, dict]:
    """리포트는 모드를 가르고, 파일은 코드 하나에 한 칸이다.

    ★한 칸에 접히더라도 어느 모드에서 왔는지 사라지지 않는다★ —
    `execution_modes` 로 남긴다.
    """
    merged: dict[str, dict] = {}
    for item in observed:
        key = item["key"]
        slot = merged.get(key)
        if slot is None:
            merged[key] = {
                "rt_cd": item["rt_cd"], "msg_cd": item["msg_cd"],
                "count": item["count"],
                "first_seen": item["first_seen"], "last_seen": item["last_seen"],
                "execution_modes": [item["execution_mode"]],
                "sample_msg1": item["sample_msg1"],
            }
            continue
        slot["count"] += item["count"]
        for field, better in (("first_seen", min), ("last_seen", max)):
            a, b = slot[field], item[field]
            slot[field] = better(a, b) if a and b else (a or b)
        if item["execution_mode"] not in slot["execution_modes"]:
            slot["execution_modes"].append(item["execution_mode"])
        if slot["sample_msg1"] is None:
            slot["sample_msg1"] = item["sample_msg1"]
    for slot in merged.values():
        slot["execution_modes"].sort()
    return merged


def _merge(doc: dict, observed: list[dict]) -> dict:
    """관측을 증거 파일에 병합한다. ★사람이 적은 칸은 건드리지 않는다★"""
    codes = doc.get("codes")
    if not isinstance(codes, dict):
        codes = {}
    for key, fresh in _collapse_modes(observed).items():
        entry = dict(codes.get(key) or {})
        entry["rt_cd"] = fresh["rt_cd"]
        entry["msg_cd"] = fresh["msg_cd"]
        # ★사람의 칸은 있으면 그대로 둔다★ — 없을 때만 관측 등급을 준다.
        if entry.get("grade") is None:
            entry["grade"] = OBSERVED_GRADE
        for field in CURATED_FIELDS:
            entry.setdefault(field, None)
        previous = entry.get("observed") or {}
        entry["observed"] = {
            "count": fresh["count"],
            # ★최초 관측 시각은 덮지 않는다★ — 덮으면 언제부터 알았는지 사라진다.
            "first_seen": previous.get("first_seen") or fresh["first_seen"],
            "last_seen": fresh["last_seen"],
            "execution_modes": fresh["execution_modes"],
            "sample_msg1": fresh["sample_msg1"],
        }
        codes[key] = entry
    # ★이번에 못 본 코드는 지우지 않는다★ — 못 본 것이 없어진 것은 아니다.
    doc["codes"] = dict(sorted(codes.items()))
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="증거 파일에 관측을 병합한다(기본은 읽기 전용)")
    ap.add_argument("--limit", type=int, default=20000,
                    help="감사 로그에서 읽을 최대 행 수")
    args = ap.parse_args()

    ran_under = _ran_under()
    rows = _read_rows(args.limit)
    if rows is None:
        print(json.dumps({"skipped": _NO_DB, "ran_under": ran_under},
                         ensure_ascii=False, indent=2))
        return 0

    observed = fold_observations(rows)
    if not observed:
        print(json.dumps({"skipped": _NO_ROWS, "ran_under": ran_under,
                          "rows_read": len(rows), "observed": []},
                         ensure_ascii=False, indent=2))
        return 0

    from src.domain.kis_rt_cd import _load_doc, _path

    report = {
        "ran_under": ran_under,
        "rows_read": len(rows),
        "observed": observed,
        "gaps": gap_list(observed),
        "table": table_summary(),
        "would_write": bool(args.write),
        "evidence_path": str(_path()),
    }

    if args.write:
        doc = _load_doc()
        if not doc:
            report["skipped"] = _NO_FILE
            report["would_write"] = False
        else:
            _path().write_text(
                json.dumps(_merge(doc, observed), ensure_ascii=False, indent=2)
                + "\n", encoding="utf-8")
            report["written"] = len(_collapse_modes(observed))

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
