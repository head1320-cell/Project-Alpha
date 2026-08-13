"""TargetPortfolioVersion — 실행·스트레스·귀인이 참조하는 **불변 목표 하나** (R0-T)
==============================================================================
왜 필요한가 (실측된 결함)
------------------------------------------------------------------------------
같은 "목표 포트폴리오"가 세 화면에서 세 값이었다:

  · `TimingOverlayPanel.tsx:58-61`  화면에서만 `after = before × exposure`
  · `ExecutionRoom.tsx:87`          오버레이 이전 `weights.optimized` 를 주문 목표로
  · `stress/page.tsx:61`            아예 `holdings`(현재 보유)

즉 타이밍 오버레이로 노출을 줄여도 **실행 계획에는 반영되지 않았다.** 화면이 보여 주는
목표와 주문이 향하는 목표가 다른 것은 이 플랫폼에서 가장 위험한 종류의 불일치다.

설계
------------------------------------------------------------------------------
  · 컴파일 산수는 **여기 한 곳**에만 둔다. 프론트는 계산하지 않고 표시한다 —
    같은 산수를 두 곳에 두면 반드시 갈라진다(A1 이 `currentSig`/`req` 에서 겪었다).
  · 비중 단위는 **퍼센트**다(`allocation_routes._w_dict` 가 `round(w*100, 2)` 로 낸다).
  · 저장은 `research_runs.py` 와 같은 방어적 raw-SQL idiom. DB 미가용 시 None 을 돌려
    호출자가 정직하게 보고한다 — 합성 목표를 만들지 않는다.
  · `status` 는 두 값뿐이다. `research_only` 는 **실행이 거부해야 하는 목표**이고,
    그 이유가 항상 `status_reason` 에 있다(사유 없는 차단은 하지 않는다).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "target_portfolio_versions"
_inited = False

STATUS_EXECUTABLE = "executable"
STATUS_RESEARCH_ONLY = "research_only"

MODE_LONG_ONLY = "long_only"          # v1 은 이것만. `long_short` 는 P3.


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited
    if _inited:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "tpv_id VARCHAR(40) PRIMARY KEY, "
            "created_at DOUBLE PRECISION, "
            "mode VARCHAR(20), "
            "base_weights TEXT, "
            "overlay TEXT, "
            "final_weights TEXT, "
            "cash_weight DOUBLE PRECISION, "
            "status VARCHAR(20), "
            "status_reason TEXT, "
            "run_id VARCHAR(40), "
            "snapshot_id VARCHAR(60), "
            "ruleset_version VARCHAR(60), "
            "pack_id VARCHAR(80), "
            "code_version VARCHAR(60), "
            "note TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_tpv_created ON {_TABLE} (created_at)"
        ))
    _inited = True


def _new_id() -> str:
    return f"tpv_{int(time.time())}_{secrets.token_hex(4)}"


def compile_target(
    base_weights: dict[str, float],
    overlay: dict[str, Any] | None,
    *,
    mode: str = MODE_LONG_ONLY,
    neutralized: bool = False,
    run_id: str | None = None,
    snapshot_id: str | None = None,
    ruleset_version: str | None = None,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """최적화 비중 + 타이밍 오버레이 → **실행이 볼 최종 목표**.

    `final[c] = base[c] × exposure`, `cash = Σbase × (1 − exposure)` (퍼센트 단위).
    현금을 함께 내는 것이 핵심이다 — 현금을 빼고 정규화하면 노출 축소가 사라진다.
    """
    exposure = 1.0
    source: str | None = None
    if overlay is not None:
        exposure = float(overlay.get("exposure", 1.0))
        source = overlay.get("source")
        if not (0.0 <= exposure <= 1.0):
            raise ValueError(f"exposure 는 0~1 이어야 합니다: {exposure}")

    final = {c: round(float(w) * exposure, 6) for c, w in base_weights.items()}
    cash = round(sum(float(w) for w in base_weights.values()) * (1.0 - exposure), 6)

    # ── status 판정 — 막을 때는 반드시 사유를 함께 낸다 ──
    reasons: list[str] = []
    if neutralized:
        reasons.append(
            "사후 중립화가 적용된 목표입니다 — 최적화 제약이 아니라 비중 변환이라 "
            "재최적화하면 사라집니다. 실행 목표로 쓸 수 없습니다."
        )
    if mode == MODE_LONG_ONLY and any(v < 0 for v in final.values()):
        # ★버리지 않고 거부한다★ `_w_dict` 는 음수를 조용히 제외해서, 롱숏이 아닌데
        # 롱온리처럼 보이게 만들었다. 값은 남기고 상태로 막는다.
        neg = sorted(c for c, v in final.items() if v < 0)
        reasons.append(f"롱온리 모드인데 음수 비중이 있습니다: {', '.join(neg)}")
    if overlay is not None and not source:
        reasons.append("타이밍 오버레이의 출처가 없습니다 — 근거 없는 노출 축소입니다.")

    return {
        "mode": mode,
        "base_weights": dict(base_weights),
        "overlay": ({"exposure": exposure, "source": source} if overlay is not None else None),
        "final_weights": final,
        "cash_weight": cash,
        "status": STATUS_RESEARCH_ONLY if reasons else STATUS_EXECUTABLE,
        "status_reason": " / ".join(reasons) if reasons else None,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "ruleset_version": ruleset_version,
        "pack_id": pack_id,
    }


def save_target(tv: dict[str, Any], note: str | None = None) -> str | None:
    """영속화. 성공 시 tpv_id, DB 미가용 시 None (호출자가 정직 보고)."""
    from src.data.research_runs import code_version

    tpv_id = _new_id()
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            c.execute(text(
                f"INSERT INTO {_TABLE} (tpv_id, created_at, mode, base_weights, overlay, "
                "final_weights, cash_weight, status, status_reason, run_id, snapshot_id, "
                "ruleset_version, pack_id, code_version, note) VALUES "
                "(:i, :t, :m, :b, :o, :f, :cw, :s, :sr, :r, :sn, :rv, :p, :cv, :n)"
            ), {
                "i": tpv_id, "t": time.time(), "m": tv["mode"],
                "b": json.dumps(tv["base_weights"], ensure_ascii=False),
                "o": json.dumps(tv["overlay"], ensure_ascii=False) if tv["overlay"] else None,
                "f": json.dumps(tv["final_weights"], ensure_ascii=False),
                "cw": tv["cash_weight"], "s": tv["status"], "sr": tv["status_reason"],
                "r": tv.get("run_id"), "sn": tv.get("snapshot_id"),
                "rv": tv.get("ruleset_version"), "p": tv.get("pack_id"),
                "cv": code_version(), "n": note,
            })
        return tpv_id
    except Exception as e:
        logger.warning(f"target version 저장 실패: {e}")
        return None


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "tpv_id": row[0], "created_at": row[1], "mode": row[2],
        "base_weights": json.loads(row[3]) if row[3] else {},
        "overlay": json.loads(row[4]) if row[4] else None,
        "final_weights": json.loads(row[5]) if row[5] else {},
        "cash_weight": row[6], "status": row[7], "status_reason": row[8],
        "run_id": row[9], "snapshot_id": row[10], "ruleset_version": row[11],
        "pack_id": row[12], "code_version": row[13], "note": row[14],
    }


_COLS = ("tpv_id, created_at, mode, base_weights, overlay, final_weights, cash_weight, "
         "status, status_reason, run_id, snapshot_id, ruleset_version, pack_id, "
         "code_version, note")


def get_target(tpv_id: str) -> dict[str, Any] | None:
    """없으면 None. **없는 것과 저장소 장애를 구분해야 하는 호출자는 `list_targets`
    처럼 예외를 받아야 하지만, 단건 조회는 라우트가 404 와 503 을 나눠 답한다.**"""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(
                text(f"SELECT {_COLS} FROM {_TABLE} WHERE tpv_id = :i"), {"i": tpv_id}
            ).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning(f"target version 조회 실패: {e}")
        return None


def list_targets(limit: int = 50) -> list[dict[str, Any]]:
    """최신순. **예외를 삼키지 않는다** — 빈 목록과 저장소 장애는 다른 사실이고,
    그 구분은 라우트가 응답으로 표현한다(R0-S)."""
    engine = _engine()
    _ensure_table(engine)
    from sqlalchemy import text
    with engine.connect() as c:
        rows = c.execute(
            text(f"SELECT {_COLS} FROM {_TABLE} ORDER BY created_at DESC LIMIT :l"),
            {"l": max(1, min(int(limit), 200))},
        ).fetchall()
    return [_row_to_dict(r) for r in rows]
