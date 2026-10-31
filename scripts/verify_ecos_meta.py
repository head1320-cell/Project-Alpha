#!/usr/bin/env python3
"""ECOS 메타로 레지스트리의 **주기·TIME 포맷**을 확인한다 — ★관측만, 추론 금지★
==============================================================================
감사: `docs/specs/2026-08-27-ecos-data-contract-audit.md`

## 무엇을 확인하나

`source_registry` 는 ECOS 37계열의 좌표(`통계표/항목`)와 단위를 **손으로** 들고
있고, 주기(`frequency`)는 아무것도 채워져 있지 않다 — 추측해 채우지 않기로 했기
때문이다. 이 스크립트가 실제 응답에서 그것을 **관측**한다.

| 단계 | 질문 | 방법 |
|---|---|---|
| 1 | 좌표가 유효한가 | `StatisticItemList` 에 항목코드가 있는가 |
| 2 | 공표 주기는 무엇인가 | 메타 행의 주기 필드 (`cycle_from_meta_row`) |
| 3 | ★TIME 포맷은 무엇인가★ | `StatisticSearch` 응답의 `TIME` 값을 **그대로** |
| 4 | 그 주기로 실제 오는가 | 같은 프로브의 행 수 |

★3번이 메타만으로는 안 되는 이유★ — 메타는 "주기가 Q 다" 라고 말할 수 있어도
그 Q 를 요청·응답에서 **어떻게 표기하는지**(`2024Q1`? `20241`?)는 말해 주지
않는다. 표기는 관측해야 한다. 그래서 `BokClient.probe_series` 로 실제 행을 몇 줄
받아 `TIME` 문자열을 해석하지 않고 그대로 남긴다.

## ★발견한 값을 자동으로 사실로 만들지 않는다★

- `--write` 없이는 증거 파일을 **쓰지 않는다**(기본은 읽기 전용 리포트).
- `--write` 를 줘도 쓰는 것은 `docs/specs/ecos-frequency-evidence.json` 이고,
  레지스트리는 그 파일을 읽을 뿐이다. **diff 를 사람이 검토해 커밋한다.**
- `verified_live` 는 여기서 **건드리지 않는다** — 그것은 별개의 사실이다.

## 키가 없으면 건너뛴다고 말한다

`{"skipped": 사유}` 로 끝낸다. ★"0건 성공" 이라고 말하지 않는다★ — 0건 성공은
"확인했더니 문제가 없었다" 로 읽히고, 실제로는 아무것도 확인하지 않았다.

## 쿼터

서로 다른 통계표 23개 → 메타 23회(0.7초/회 ≈ 16초). 기간 변형은 **메타가 주기를
주지 못한 계열에만** 걸고 `--max-calls` 로 상한을 둔다. ★대량 적재가 아니다.★
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.source_registry import (  # noqa: E402
    ECOS,
    ECOS_CYCLES,
    FREQ_EVIDENCE_PATH,
    REASON_NO_KEY,
    specs_by_provider,
)
from src.services.macro_collector import BokClient, cycle_from_meta_row  # noqa: E402

#: 기간 변형 프로브의 조회 창 — 주기별 **요청** 표기. ★`Q` 는 없다★
#: 분기 표기가 바로 이 스크립트가 알아내려는 것이므로, 여기 적으면 순환이 된다.
#: 대신 `D`·`M`·`A` 로 걸어 보고 어느 것이 응답하는지를 관측한다.
_PROBE_WINDOWS: dict[str, tuple[str, str]] = {
    "D": ("20240101", "20240131"),
    "M": ("202401", "202403"),
    "A": ("2020", "2024"),
}
_DEFAULT_MAX_CALLS = 60


def _item_code_matches(row: dict, want: str) -> bool:
    """항목코드 일치 — ★필드명이 미검증이라 후보를 순회한다★"""
    for k in ("ITEM_CODE", "P_ITEM_CODE", "ITEM_CODE1"):
        v = row.get(k)
        if v is not None and str(v).strip() == want:
            return True
    return False


def _grade_for(entry: dict) -> str:
    """증거 등급 — ★관측한 만큼만★

    E3 메타 주기 + 실제 TIME 값 교차 확인
    E2 메타 응답에서 주기 관측
    E1 값이 오는 것은 봤으나 주기를 확정하지 못함
    E0 아무것도 관측하지 못함
    """
    has_cycle = entry.get("observed_frequency") in ECOS_CYCLES
    has_time = bool(entry.get("time_sample"))
    if has_cycle and has_time:
        return "E3"
    if has_cycle:
        return "E2"
    if has_time:
        return "E1"
    return "E0"


def collect(*, probe_time: bool = True, max_calls: int = _DEFAULT_MAX_CALLS) -> dict:
    client = BokClient()
    if not client.is_configured:
        return {"skipped": REASON_NO_KEY}

    targets = [s for s in specs_by_provider(ECOS) if not s.derived_from]
    rows: list[dict] = []
    by_table: dict[str, tuple[list[dict], str | None]] = {}
    budget = {"used": 0, "max": max_calls}

    def _spend() -> bool:
        if budget["used"] >= budget["max"]:
            return False
        budget["used"] += 1
        return True

    for spec in targets:
        stat, _, item = spec.endpoint.partition("/")
        entry: dict = {
            "key": spec.key, "label": spec.label, "endpoint": spec.endpoint,
            "registry_unit": spec.unit, "registry_frequency": spec.frequency,
            "verified_live": spec.verified_live,
        }

        # ── 1·2단계: 좌표 유효성 + 메타 주기 (통계표당 1회) ──────────────
        if stat not in by_table:
            by_table[stat] = client.fetch_item_list(stat) if _spend() \
                else ([], "쿼터 상한(--max-calls)에 걸려 조회하지 않았습니다.")
        meta_rows, err = by_table[stat]
        if err:
            entry["status"] = "meta_unavailable"
            entry["reason"] = err
        else:
            match = next((r for r in meta_rows if _item_code_matches(r, item)), None)
            if match is None:
                entry["status"] = "item_not_found"
                entry["reason"] = (f"통계표 {stat} 의 항목 목록에 {item!r} 이 없습니다 — "
                                   f"★좌표가 틀렸을 수 있습니다★ (항목 {len(meta_rows)}개 확인)")
            else:
                cycle, why = cycle_from_meta_row(match)
                entry["observed_frequency"] = cycle
                entry["evidence_source"] = "StatisticItemList"
                entry["status"] = "ok" if cycle else "cycle_unknown"
                if why:
                    entry["reason"] = why

        # ── 3·4단계: TIME 포맷 관측 ──────────────────────────────────────
        # 메타가 준 주기부터 걸어 본다. 못 줬으면 D→M→A 순으로 훑어 **어느 것이
        # 응답하는지**를 관측한다. 첫 성공에서 멈춘다(쿼터).
        if probe_time and entry.get("status") in ("ok", "cycle_unknown"):
            order = [entry.get("observed_frequency")] if entry.get("observed_frequency") \
                else ["D", "M", "A"]
            attempts: list[dict] = []
            for period in order:
                win = _PROBE_WINDOWS.get(period)
                if win is None:
                    attempts.append({"period": period, "status": "no_window",
                                     "reason": f"{period} 의 요청 표기가 검증되지 않아 "
                                               f"거는 것 자체를 하지 않았습니다(부록 9)."})
                    continue
                if not _spend():
                    attempts.append({"period": period, "status": "budget_exhausted"})
                    break
                r = client.probe_series(stat, item, period, win[0], win[1])
                attempts.append({k: v for k, v in r.items()
                                 if k in ("period", "status", "http_status", "row_count",
                                          "time_sample", "row_keys", "ecos_code",
                                          "ecos_message", "reason")})
                if r.get("status") == "ok":
                    entry["time_sample"] = r["time_sample"]
                    entry["responding_period"] = period
                    if not entry.get("observed_frequency"):
                        # ★메타가 못 준 주기를 응답으로 **추정**했다★ 등급이 낮다.
                        entry["evidence_source"] = "StatisticSearch(응답으로 추정)"
                    break
            entry["probe_attempts"] = attempts

        entry["grade"] = _grade_for(entry)
        # ★수집기는 월별로 조회한다★ 주기가 다르면 그것이 빈 응답의 원인이다.
        f = entry.get("observed_frequency")
        if f and f != "M":
            entry["collector_mismatch"] = f"수집기는 M 으로 조회하는데 실제는 {f}"
        rows.append(entry)

    return {
        "checked": len(rows), "rows": rows,
        "calls_used": budget["used"], "calls_max": budget["max"],
        "mismatched": sum(1 for r in rows if r.get("collector_mismatch")),
        "applicable": sum(1 for r in rows if r["grade"] in ("E2", "E3")),
        "note": "★레지스트리를 직접 고치지 않았습니다★ --write 로 증거 파일에만 "
                "기록하고, diff 를 사람이 검토해 커밋합니다.",
    }


def write_evidence(out: dict) -> dict:
    """관측을 증거 파일에 기록한다. ★E2 이상만★ · 기존 항목은 병합한다."""
    doc = json.loads(FREQ_EVIDENCE_PATH.read_text(encoding="utf-8"))
    series = dict(doc.get("series") or {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = []
    for r in out.get("rows", []):
        if r["grade"] not in ("E2", "E3"):
            continue
        series[r["key"]] = {
            "frequency": r["observed_frequency"],
            "time_sample": r.get("time_sample"),
            "responding_period": r.get("responding_period"),
            "evidence_source": r.get("evidence_source"),
            "probed_at": now,
            "grade": r["grade"],
        }
        written.append(r["key"])
    doc["series"] = series
    FREQ_EVIDENCE_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"written": written, "path": str(FREQ_EVIDENCE_PATH)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="관측을 증거 파일에 기록한다(기본은 읽기 전용 리포트)")
    ap.add_argument("--no-probe", action="store_true",
                    help="메타만 본다 — TIME 포맷 프로브를 걸지 않는다(쿼터 절약)")
    ap.add_argument("--max-calls", type=int, default=_DEFAULT_MAX_CALLS,
                    help=f"ECOS 호출 상한 (기본 {_DEFAULT_MAX_CALLS})")
    a = ap.parse_args(argv)

    out = collect(probe_time=not a.no_probe, max_calls=a.max_calls)
    if a.write and "skipped" not in out:
        out["evidence"] = write_evidence(out)
    elif a.write:
        out["evidence"] = {"written": [],
                           "reason": "건너뛴 실행은 기록하지 않습니다 — 관측이 없습니다."}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
