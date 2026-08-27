#!/usr/bin/env python3
"""ECOS 메타로 레지스트리의 **주기·단위**를 대조한다 — ★쓰지는 않는다★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` 부록 3 #5

## 무엇을 확인하나

`source_registry` 는 ECOS 37계열의 좌표(`통계표/항목`)와 단위를 **손으로** 들고
있다. 주기(`frequency`)는 아무것도 채워져 있지 않다 — 추측해 채우지 않기로 했기
때문이다. 이 스크립트가 `StatisticItemList` 로 실제 주기를 받아 그 표를 대조한다.

## ★발견한 값을 레지스트리에 쓰지 않는다★

`verified_live` 와 같은 규율이다. 한 번 응답이 왔다고 코드가 스스로 사실을 올리면
그 필드는 "확인됨" 이 아니라 "언젠가 한 번 그렇게 보였음" 이 되고, 둘은 다른
상태다. 이 스크립트는 **표를 찍고**, 올리는 것은 그 표를 본 사람이다.

## 키가 없으면 건너뛴다고 말한다

`{"skipped": 사유}` 로 끝낸다. ★"0건 성공" 이라고 말하지 않는다★ — 0건 성공은
"확인했더니 문제가 없었다" 로 읽히고, 실제로는 아무것도 확인하지 않았다.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.source_registry import (  # noqa: E402
    ECOS,
    REASON_NO_KEY,
    specs_by_provider,
)
from src.services.macro_collector import BokClient, cycle_from_meta_row  # noqa: E402


def _item_code_matches(row: dict, want: str) -> bool:
    """항목코드 일치 — ★필드명이 미검증이라 후보를 순회한다★"""
    for k in ("ITEM_CODE", "P_ITEM_CODE", "ITEM_CODE1"):
        v = row.get(k)
        if v is not None and str(v).strip() == want:
            return True
    return False


def collect() -> dict:
    client = BokClient()
    if not client.is_configured:
        return {"skipped": REASON_NO_KEY}

    targets = [s for s in specs_by_provider(ECOS) if not s.derived_from]
    rows: list[dict] = []
    by_table: dict[str, tuple[list[dict], str | None]] = {}

    for spec in targets:
        stat, _, item = spec.endpoint.partition("/")
        if stat not in by_table:                 # 통계표당 한 번만 부른다(쿼터)
            by_table[stat] = client.fetch_item_list(stat)
        meta_rows, err = by_table[stat]
        entry = {"key": spec.key, "label": spec.label, "endpoint": spec.endpoint,
                 "registry_unit": spec.unit, "registry_frequency": spec.frequency,
                 "verified_live": spec.verified_live}
        if err:
            entry["status"] = "meta_unavailable"
            entry["reason"] = err
            rows.append(entry)
            continue
        match = next((r for r in meta_rows if _item_code_matches(r, item)), None)
        if match is None:
            entry["status"] = "item_not_found"
            entry["reason"] = (f"통계표 {stat} 의 항목 목록에 {item!r} 이 없습니다 — "
                               f"★좌표가 틀렸을 수 있습니다★ (항목 {len(meta_rows)}개 확인)")
            rows.append(entry)
            continue
        cycle, why = cycle_from_meta_row(match)
        entry["status"] = "ok" if cycle else "cycle_unknown"
        entry["observed_frequency"] = cycle
        if why:
            entry["reason"] = why
        # ★수집기는 월별로 조회한다★ 주기가 다르면 그것이 빈 응답의 원인이다.
        if cycle and cycle != "M":
            entry["collector_mismatch"] = f"수집기는 M 으로 조회하는데 실제는 {cycle}"
        rows.append(entry)

    return {"checked": len(rows), "rows": rows,
            "mismatched": sum(1 for r in rows if r.get("collector_mismatch")),
            "note": "★발견한 주기를 레지스트리에 쓰지 않았습니다★ 사람이 올립니다."}


def main() -> int:
    out = collect()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
