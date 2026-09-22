#!/usr/bin/env python3
"""실제로 낸 거래비용을 수확한다 — ★관측만, 계약 요율은 사람이 적는다★ (AZ4)
==============================================================================
증거 파일: `docs/specs/cost-rate-evidence.json` · 어휘
`src/domain/cost_provenance.py` · 원료 `live_fills`(체결 기록)

## 무엇을 하나

채점표 #6 이 *"수수료 기본값이 문마다 10배 다르다"* 를 적고 멈췄다. 이유는
분명했다 — ★15bp 도 1.5bp 도 이 저장소가 재본 적이 없다★. 안 재본 값으로
통일하면 불일치가 **거짓 합의**가 된다.

이 스크립트는 그 값을 ★재기 위한 원료★를 만든다: 실체결에 남은
`commission_krw / fill_value_krw × 10000` 을 접어 *"실제로 N bp 를 냈다"* 를 낸다.

## ★프로브가 아니라 수확이다★ (AS 선례)

수수료를 알아보려고 주문을 낼 수는 없다. 그래서 ★이미 일어난 체결을 읽는다.★
`scripts/collect_kis_rt_cd.py` 와 같은 모양이고 같은 규율을 따른다.

## ★관측을 자동으로 계약 요율로 만들지 않는다★

- `--write` 없이는 증거 파일을 **쓰지 않는다**(기본은 읽기 전용 리포트).
- 쓰더라도 등급은 `C1`(관측)이고 통일 적용선은 `C2`(수수료표 근거)다 —
  ★수집기가 아무리 돌아도 기본값을 통일할 수는 없다.★ 체결에서 계산한 bp 는
  우대·이벤트·최소수수료에 흔들려서, 100번 본다고 계약 요율을 알게 되지 않는다.
- 병합은 ★사람이 적은 것을 덮지 않는다★ — `bps`·`grade`·`evidence_source`·
  `account_kind`·`probed_at` 은 보존하고 `observed` 만 갱신한다.
- `first_seen` 은 ★UPDATE 하지 않는다★ — 같은 성분을 다시 봤다는 사실은 새
  정보가 아니고, 덮으면 "언제부터 알았나" 가 사라진다.
- ★중앙값을 쓴다★ — 평균은 최소수수료가 걸린 소액 체결 하나에 끌려간다.
  최소·최대도 함께 남겨 **퍼진 정도가 보이게** 한다.

## 아무것도 못 봤으면 그렇게 말한다

`{"skipped": 사유}` 로 끝낸다. ★"0건 성공" 이라고 말하지 않는다★ — 0건 성공은
*"확인했더니 문제가 없었다"* 로 읽히고, 실제로는 아무것도 확인하지 않았다.

이 환경에는 ★`live_fills` 테이블 자체가 없다★(2026-09-22 실측) — 브로커가
연결된 배포에서만 채워진다.

## 쓰는 법

    python3 scripts/collect_cost_rates.py              # 읽기 전용 리포트
    python3 scripts/collect_cost_rates.py --write      # 증거 파일에 병합

`--write` 뒤에는 ★사람이 diff 를 검토해 커밋한다.★
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.domain.cost_provenance import EVIDENCE_PATH  # noqa: E402

#: ★사람의 것★ — 병합이 절대 덮지 않는 칸.
CURATED_FIELDS = ("bps", "grade", "evidence_source", "account_kind", "probed_at")

#: 수집기가 만드는 등급. ★적용선(`C2`)보다 아래다★ — 그것이 설계다.
OBSERVED_GRADE = "C1"

_NO_TABLE = (
    "live_fills 테이블이 없습니다 — 확인한 것이 아니라 볼 것이 없었습니다. "
    "브로커가 연결된 배포에서만 체결이 쌓입니다. 0 으로 대체하지 않습니다.")

_NO_ROWS = (
    "live_fills 에 체결이 없습니다 — 확인한 것이 아니라 볼 것이 없었습니다. "
    "mock/shadow 모드에서는 실체결이 남지 않으므로 정상입니다.")

_NO_VALUE = (
    "체결은 있으나 fill_value_krw 가 0 이거나 commission_krw 가 비어 있어 "
    "bp 를 계산할 수 없습니다 — ★미상이지 0 이 아닙니다.★")


def _read_fills(limit: int) -> tuple[list[dict], str | None]:
    """(체결 행, 건너뛴 사유). ★테이블이 없으면 사유와 함께 빈손★"""
    try:
        from sqlalchemy import text

        from src.database import get_engine
        with get_engine().connect() as c:
            rows = c.execute(text(
                "SELECT fill_value_krw, commission_krw, filled_at "
                "FROM live_fills ORDER BY filled_at DESC LIMIT :n"
            ), {"n": int(limit)}).fetchall()
    except Exception as e:
        if "no such table" in str(e) or "does not exist" in str(e):
            return [], _NO_TABLE
        return [], f"live_fills 를 읽지 못했습니다: {type(e).__name__}"
    if not rows:
        return [], _NO_ROWS
    return [{"value": v, "commission": cm, "at": at} for v, cm, at in rows], None


def _fold(rows: list[dict]) -> tuple[dict | None, str | None]:
    """체결 → 수수료 bp 요약. ★중앙값이 대표값이다★ (평균은 소액에 끌린다)."""
    bps: list[float] = []
    stamps: list[str] = []
    for r in rows:
        try:
            value = float(r["value"] or 0)
            comm = float(r["commission"] or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        bps.append(comm / value * 10_000)
        if r["at"]:
            stamps.append(str(r["at"]))
    if not bps:
        return None, _NO_VALUE
    return {
        "n_fills": len(bps),
        "bps_median": round(statistics.median(bps), 4),
        "bps_min": round(min(bps), 4),
        "bps_max": round(max(bps), 4),
        # ★퍼진 정도를 숨기지 않는다★ — 한 값으로 접으면 우대·최소수수료가 안 보인다.
        "first_seen": min(stamps) if stamps else None,
        "last_seen": max(stamps) if stamps else None,
    }, None


def _merge(doc: dict, folded: dict) -> dict:
    """★사람이 적은 것을 덮지 않는다★ · ★`first_seen` 을 UPDATE 하지 않는다★"""
    observed = doc.get("observed")
    if not isinstance(observed, dict):
        observed = {}
    prev = observed.get("commission")
    prev = prev if isinstance(prev, dict) else {}
    merged = {k: prev[k] for k in CURATED_FIELDS if k in prev}
    merged.update(folded)
    if prev.get("first_seen"):
        # 같은 성분을 다시 봤다는 사실은 새 정보가 아니다.
        merged["first_seen"] = prev["first_seen"]
    merged.setdefault("grade", OBSERVED_GRADE)
    observed["commission"] = merged
    doc["observed"] = observed
    return doc


def _report(skipped: str | None, folded: dict | None) -> dict:
    out: dict = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "evidence_path": EVIDENCE_PATH,
        "grade_made_here": OBSERVED_GRADE,
        "note": ("★관측은 계약 요율이 아닙니다★ — 이 수집기가 만드는 등급은 "
                 "C1 이고 기본값 통일 적용선은 C2(증권사 수수료표 근거)입니다. "
                 "수집기가 아무리 돌아도 통일은 사람이 수수료표를 적어야 합니다."),
    }
    if skipped:
        out["skipped"] = skipped
    else:
        out["observed"] = folded
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="실체결에서 거래비용 bp 를 수확한다")
    ap.add_argument("--write", action="store_true",
                    help="증거 파일에 병합한다(기본은 읽기 전용)")
    ap.add_argument("--limit", type=int, default=5000,
                    help="읽을 최근 체결 수 (기본 5000)")
    args = ap.parse_args()

    rows, skipped = _read_fills(args.limit)
    folded = None
    if not skipped:
        folded, skipped = _fold(rows)

    report = _report(skipped, folded)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not args.write:
        return 0
    if folded is None:
        # ★아무것도 못 봤으면 파일을 건드리지 않는다★
        print("\n증거 파일을 쓰지 않았습니다 — 관측이 없습니다.", file=sys.stderr)
        return 0
    try:
        doc = json.loads(open(EVIDENCE_PATH, encoding="utf-8").read())
    except Exception as e:
        print(f"증거 파일을 읽지 못했습니다: {e}", file=sys.stderr)
        return 1
    with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(_merge(doc, folded), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n{EVIDENCE_PATH} 에 병합했습니다 — ★diff 를 검토하고 커밋하세요.★",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
