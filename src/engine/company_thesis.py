"""구조화된 논지 + kill 조건 → 백테스트 다리 (P2-5 커밋 ①)

Company 언더라이팅 트랙의 마지막 칸이다. 논지(주장·근거·촉매·kill 조건)를
**검증 가능한 형식**으로 만들고, kill 조건을 그대로 백테스트 조건으로 올린다.

★자유 텍스트로 두면 검증할 수 없다★ 그래서 kill 조건은 `filter_ast` 의
`FIELD_BY_ID` 레지스트리로 표현한다 — 스크리너·백테스트가 **이미 쓰는** 단일 필드
계약이다. **새 DSL 을 만들지 않는다**(CLAUDE.md).

★실측이 정한 것 — 다리는 있지만 좁다★

    FIELD_BY_ID                      157
    조건식 토큰으로 도달 가능          92   (수동 별칭 29 + 스토어 라벨 별칭 63)
    도달 불가                          65
    PIT 토큰(_PIT_FUND_TOKENS)         12
      그중 FIELD_BY_ID id 와 맞물림     5   per · pbr · psr · pcr · roe

게다가 그 5개도 `financials_history` 가 적재돼야 PIT 로 돈다
(`condition_strategy.py:864-874` — ①PIT 우선 → ②스냅샷 상수 폴백, 폴백은 코드가
직접 "look-ahead 근사" 라고 적어 둔 것). 그래서 이 모듈의 산출물은 "된다/안 된다"
가 아니라 조건마다의 **3단 분류**다.

★수치를 문서가 아니라 코드에서 읽는다★ 위 숫자는 기록이지 상수가 아니다 —
분류는 매번 상류 레지스트리를 실제로 읽어서 판정한다.
"""
from __future__ import annotations

from datetime import date, datetime

from src.engine.filter_ast import FIELD_BY_ID, parse_condition

# ── 3단 분류 ────────────────────────────────────────────────────────────────
TIER_BACKTESTABLE = "backtestable"
"""PIT 토큰 + 재무 시계열 적재됨 → 룩어헤드 없이 백테스트 가능."""

TIER_LOOKAHEAD = "screen_only_backtest_lookahead"
"""조건식으로 올릴 수는 있으나 스냅샷 상수라 **룩어헤드 근사**(opt-in 필요)."""

TIER_SCREEN_ONLY = "screen_only"
"""조건식 토큰으로 도달 불가 → 백테스트에 못 올린다."""

BRIDGEABLE_TIERS = (TIER_BACKTESTABLE, TIER_LOOKAHEAD)

OPT_IN_FLAG = "allow_snapshot_fundamentals"

# filter_ast op → condition_strategy op. lt/gt(엄격)는 정확한 대응이 없다 —
# 바꾸되 ★그 사실을 라벨로 남긴다★ (임계값과 정확히 같은 값에서 판정이 갈린다).
_OP_MAP = {"lt": "lte", "lte": "lte", "gt": "gte", "gte": "gte",
           "eq": "eq", "between": "between"}
_STRICT_OPS = ("lt", "gt")

_IDENTITY_FUNCTION = "base"   # condition_strategy 의 항등 함수(현재값)

_CATALYST_DATE_FMT = "%Y-%m-%d"


# ── 상류 레지스트리 실측 ─────────────────────────────────────────────────────
def token_maps() -> tuple[dict[str, str], dict[str, str]]:
    """(PIT 필드→토큰, 도달가능 필드→토큰).

    ★캐시하지 않는다★ 상류가 바뀌면 분류도 바뀌어야 한다. 비용은 dict 순회뿐이다.
    """
    from src.kis_strategies.condition_strategy import _PIT_FUND_TOKENS
    from src.kis_strategies.factor_tokens import (
        FUNDAMENTAL_ALIASES,
        _label_aliases,
        fundamental_field_for,
    )

    pit: dict[str, str] = {}
    for tok in sorted(_PIT_FUND_TOKENS):
        fid = fundamental_field_for(tok)
        if fid in FIELD_BY_ID and fid not in pit:
            pit[fid] = tok

    reach: dict[str, str] = dict(pit)
    for alias_map in (FUNDAMENTAL_ALIASES, _label_aliases()):
        for tok, fid in sorted(alias_map.items()):
            if fid in FIELD_BY_ID and fid not in reach:
                reach[fid] = tok
    return pit, reach


def history_loaded(code: str | None) -> bool:
    """재무 시계열 적재 여부 — ★가정하지 않고 실제로 확인한다★

    이것이 False 면 PIT 토큰조차 스냅샷 상수로 떨어진다(= 룩어헤드 근사).
    """
    if not code:
        return False
    try:
        from src.data.dart_history import load_history
        return bool(load_history(str(code)))
    except Exception:
        return False


# ── 조건 하나의 분류 ─────────────────────────────────────────────────────────
def _classify(cond: dict, pit: dict[str, str], reach: dict[str, str],
              hist: bool) -> dict:
    parsed = parse_condition(cond if isinstance(cond, dict) else {})
    err = parsed.validate()          # ★레지스트리가 내는 사유를 그대로 쓴다★
    row: dict = {
        "condition": cond, "kind": parsed.kind, "field": parsed.field or None,
        "valid": err is None, "reason": err, "tier": None, "token": None,
        "pit_supported": False, "history_loaded": hist, "lookahead": False,
    }
    if err is not None:
        return row

    if parsed.kind != "field":
        row["tier"] = TIER_SCREEN_ONLY
        row["reason"] = (f"kind={parsed.kind} 는 조건식 토큰으로 표현할 수 없습니다 "
                         "— 스크리너 전용입니다")
        return row

    if parsed.rank_mode is not None:
        row["tier"] = TIER_SCREEN_ONLY
        row["reason"] = (f"rank_mode={parsed.rank_mode} 는 횡단면 순위입니다 — "
                         "종목 하나의 조건식으로 표현할 수 없습니다")
        return row

    fid = parsed.field
    token = pit.get(fid) or reach.get(fid)
    if token is None:
        row["tier"] = TIER_SCREEN_ONLY
        row["reason"] = (f"'{fid}' 에 대응하는 조건식 토큰이 없습니다 "
                         "— 백테스트에 올릴 수 없습니다")
        return row

    row["token"] = token
    row["pit_supported"] = fid in pit
    if row["pit_supported"] and hist:
        row["tier"] = TIER_BACKTESTABLE
        row["reason"] = None
        return row

    row["tier"] = TIER_LOOKAHEAD
    row["lookahead"] = True
    row["requires_opt_in"] = OPT_IN_FLAG
    row["reason"] = (
        f"'{fid}' 는 PIT 토큰이지만 financials_history 가 적재되지 않았습니다 — "
        "스냅샷 상수 폴백은 look-ahead 근사입니다"
        if row["pit_supported"] else
        f"'{fid}' 는 PIT 지원 토큰이 아닙니다 — 스냅샷 상수로 평가되며 "
        "look-ahead 근사입니다"
    )
    return row


def kill_condition_bridge(conditions: list[dict], *,
                          code: str | None = None) -> dict:
    """kill 조건들을 검증하고 3단으로 분류한다.

    "kill if ROE < 8%" 를 쓴 사람과 "kill if 12-1 모멘텀 < 0" 을 쓴 사람이
    ★백테스트에 올릴 수 있는지를 미리 안다★ — 그것이 이 함수가 주는 정보다.
    """
    pit, reach = token_maps()
    hist = history_loaded(code)
    rows = [_classify(c, pit, reach, hist) for c in (conditions or [])]

    invalid = [r for r in rows if not r["valid"]]
    counts = {t: sum(1 for r in rows if r["tier"] == t)
              for t in (TIER_BACKTESTABLE, TIER_LOOKAHEAD, TIER_SCREEN_ONLY)}
    if invalid:
        reason = invalid[0]["reason"]
    elif not rows:
        reason = "kill 조건이 없습니다"
    else:
        reason = None
    return {
        "available": bool(rows) and not invalid,
        "reason": reason,
        "code": code,
        "history_loaded": hist,
        "rows": rows,
        "counts": counts,
        "registry": {"fields": len(FIELD_BY_ID), "reachable": len(reach),
                     "pit": len(pit)},
        "note": ("tier 2 는 스냅샷 상수 폴백이라 look-ahead 근사입니다 — "
                 "라벨을 지우지 마십시오"),
    }


# ── 논지 검증 ────────────────────────────────────────────────────────────────
def known_sections() -> set[str]:
    """근거가 가리킬 수 있는 스냅샷 섹션 — ★코드에서 읽는다★

    `thesis` 자신은 제외한다. 논지가 자기를 근거로 드는 것은 순환이다.
    """
    from src.data import company_snapshots as cs
    return (set(cs._BASE_SECTIONS) | set(cs._LATE_COLUMNS)) - {"thesis"}


def _check_evidence(items, sections: set[str], errors: list) -> list[dict]:
    out = []
    for i, ev in enumerate(items or []):
        if not isinstance(ev, dict):
            errors.append(f"근거[{i}]: dict 가 아닙니다")
            continue
        section = str(ev.get("section") or "").strip()
        row = {"section": section or None, "path": ev.get("path"),
               "note": ev.get("note"), "valid": True, "reason": None}
        if not section:
            row.update(valid=False, reason="근거가 가리키는 섹션(section)이 없습니다")
        elif section not in sections:
            row.update(valid=False,
                       reason=(f"'{section}' 은 스냅샷 섹션이 아닙니다 — "
                               f"가능한 섹션: {', '.join(sorted(sections))}"))
        if not row["valid"]:
            errors.append(f"근거[{i}]: {row['reason']}")
        out.append(row)
    return out


def _check_catalysts(items, today: date, errors: list) -> list[dict]:
    out = []
    for i, ca in enumerate(items or []):
        if not isinstance(ca, dict):
            errors.append(f"촉매[{i}]: dict 가 아닙니다")
            continue
        what = str(ca.get("what") or "").strip()
        raw_by = str(ca.get("by") or "").strip()
        row = {"what": what or None, "by": raw_by or None, "note": ca.get("note"),
               "valid": True, "reason": None, "overdue": None, "days_left": None}
        if not what:
            row.update(valid=False, reason="촉매 내용(what)이 비어 있습니다")
        elif not raw_by:
            # ★기한 없는 촉매는 촉매가 아니다★ 반증 시점이 없으면 영원히 유예된다.
            row.update(valid=False, reason="촉매에 기한(by)이 없습니다 — 기한 없는 촉매는 반증되지 않습니다")
        else:
            try:
                due = datetime.strptime(raw_by, _CATALYST_DATE_FMT).date()
            except ValueError:
                row.update(valid=False,
                           reason=f"기한 '{raw_by}' 을 YYYY-MM-DD 로 읽을 수 없습니다")
            else:
                # ★기한 지난 촉매를 조용히 두는 것이 논지가 썩는 방식이다★
                row["overdue"] = due < today
                row["days_left"] = (due - today).days
        if not row["valid"]:
            errors.append(f"촉매[{i}]: {row['reason']}")
        out.append(row)
    return out


def validate_thesis(thesis: dict, *, code: str | None = None,
                    today: date | None = None) -> dict:
    """논지를 검증하고 kill 조건을 3단으로 분류한다.

    검증 실패는 예외가 아니라 `{available: False, reason, errors}` 다 — 스냅샷을
    죽이지 않고 "그때 이 논지가 왜 검증되지 않았는가" 로 남는다.
    """
    today = today or date.today()
    if not isinstance(thesis, dict):
        return {"available": False, "reason": "논지는 dict 여야 합니다",
                "errors": ["논지는 dict 여야 합니다"], "claim": None,
                "evidence": [], "catalysts": [],
                "kill_conditions": kill_condition_bridge([], code=code),
                "code": code, "as_of": today.isoformat()}

    errors: list[str] = []
    claim = str(thesis.get("claim") or "").strip()
    if not claim:
        # ★빈 논지는 논지가 아니다★
        errors.append("주장(claim)이 비어 있습니다 — 빈 논지는 논지가 아닙니다")

    evidence = _check_evidence(thesis.get("evidence"), known_sections(), errors)
    catalysts = _check_catalysts(thesis.get("catalysts"), today, errors)

    raw_kills = thesis.get("kill_conditions") or []
    bridge = kill_condition_bridge(raw_kills, code=code)
    if not raw_kills:
        # 반증할 수 없는 논지는 검증할 수 없다 — 이 슬라이스가 존재하는 이유다.
        errors.append("kill 조건이 없습니다 — 반증할 수 없는 논지는 검증할 수 없습니다")
    else:
        for i, r in enumerate(bridge["rows"]):
            if not r["valid"]:
                errors.append(f"kill 조건[{i}]: {r['reason']}")

    return {
        "available": not errors,
        "reason": "; ".join(errors) if errors else None,
        "errors": errors,
        "claim": claim or None,
        "evidence": evidence,
        "catalysts": catalysts,
        "kill_conditions": bridge,
        "overdue_catalysts": [c["what"] for c in catalysts if c.get("overdue")],
        "code": code,
        "as_of": today.isoformat(),
    }


# ── 백테스트 다리 ────────────────────────────────────────────────────────────
def _to_sell_condition(row: dict) -> dict:
    parsed = parse_condition(row["condition"])
    op = _OP_MAP.get(parsed.op, parsed.op)
    out: dict = {"factor_token": row["token"], "function_id": _IDENTITY_FUNCTION,
                 "op": op, "rhs": parsed.value}
    if parsed.op == "between":
        out["rhs2"] = parsed.value2
    if parsed.op in _STRICT_OPS:
        # ★경계 의미가 달라진 것을 숨기지 않는다★
        out["boundary_note"] = (
            f"원 조건 op={parsed.op}(엄격) → 조건식 op={op}(경계 포함) — "
            "임계값과 정확히 같은 값에서 판정이 달라집니다")
    if row["tier"] == TIER_LOOKAHEAD:
        out["lookahead"] = True
        out["requires_opt_in"] = OPT_IN_FLAG
    return out


def thesis_to_sell_conditions(thesis: dict, *, code: str | None = None) -> dict:
    """kill 조건 → 백테스트 매도 조건.

    ★list 가 아니라 dict 를 돌려준다★ 올리지 못한 조건의 **사유**가 언더라이팅의
    정보이기 때문이다 — 조용히 빠진 kill 조건은 없는 kill 조건보다 나쁘다.
    """
    bridge = kill_condition_bridge(thesis.get("kill_conditions") or [], code=code) \
        if isinstance(thesis, dict) else kill_condition_bridge([], code=code)

    lifted: list[dict] = []
    excluded: list[dict] = []
    for r in bridge["rows"]:
        if not r["valid"] or r["tier"] not in BRIDGEABLE_TIERS:
            excluded.append({"condition": r["condition"], "field": r["field"],
                             "tier": r["tier"], "reason": r["reason"]})
            continue
        lifted.append(_to_sell_condition(r))

    lookahead = any(c.get("lookahead") for c in lifted)
    return {
        "available": bool(lifted),
        "reason": None if lifted else (bridge["reason"]
                                       or "올릴 수 있는 kill 조건이 없습니다"),
        "conditions": lifted,
        "excluded": excluded,
        "lookahead": lookahead,
        "requires_opt_in": OPT_IN_FLAG if lookahead else None,
        "counts": bridge["counts"],
        "history_loaded": bridge["history_loaded"],
        "note": ("look-ahead 조건을 포함하면 백테스트 성과는 근사입니다 — "
                 f"{OPT_IN_FLAG} 를 켜야 평가됩니다") if lookahead else None,
    }
