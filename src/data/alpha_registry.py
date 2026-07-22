"""Alpha Registry — 알파 정의·버전·상태 라이프사이클 영속 (Full Expansion P2)
============================================================================
AlphaDefinition의 저장소. 상태: draft → experimental → validated → approved → retired.
  · validated 승격은 검증 리포트(ResearchRun run_id) 필수
  · approved 승격은 승인 노트 필수 (경량 — 정식 ApprovalRecord·역할은 P4)
  · 6개 기본 슬리브 템플릿을 최초 1회 시드 — 데이터 미보유 신호는 정직 라벨.
research_runs와 동일한 방어적 raw-SQL idiom.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "alpha_registry"
_inited = False

STATUSES = ("draft", "experimental", "validated", "approved", "retired")

# 승격 규칙: (from, to) 허용 + 요건. retired는 어디서든 가능, draft로 강등도 허용.
_PROMOTE_NEXT = {"draft": "experimental", "experimental": "validated", "validated": "approved"}


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
            "alpha_id VARCHAR(40) PRIMARY KEY, "
            "name TEXT, "
            "expr TEXT, "
            "description TEXT, "
            "universe TEXT, "
            "tags TEXT, "
            "status VARCHAR(20), "
            "version INTEGER, "
            "is_template INTEGER, "
            "last_run_id VARCHAR(40), "
            "parent_id VARCHAR(40), "
            "notes TEXT, "
            "created_at DOUBLE PRECISION, "
            "updated_at DOUBLE PRECISION)"
        ))
    _inited = True


def _row(r) -> dict[str, Any]:
    d = {
        "alpha_id": r[0], "name": r[1], "expr": r[2], "description": r[3],
        "universe": r[4], "status": r[6], "version": r[7],
        "is_template": bool(r[8]), "last_run_id": r[9], "parent_id": r[10],
        "notes": r[11], "created_at": r[12], "updated_at": r[13],
    }
    try:
        d["tags"] = json.loads(r[5]) if r[5] else []
    except Exception:
        d["tags"] = []
    return d


_COLS = ("alpha_id, name, expr, description, universe, tags, status, version, "
         "is_template, last_run_id, parent_id, notes, created_at, updated_at")


def upsert_alpha(alpha_id: str | None, name: str, expr: str, description: str = "",
                 universe: str = "kospi200", tags: list[str] | None = None,
                 is_template: bool = False, status: str = "draft",
                 notes: str = "", parent_id: str | None = None) -> dict | None:
    """생성(alpha_id=None) 또는 수정. 수정 시 expr 변경이면 version+1, 상태는 draft로
    강등(재검증 강제 — 검증 결과가 낡은 식을 대변하지 않도록)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        now = time.time()
        with engine.begin() as c:
            if alpha_id:
                cur = c.execute(text(
                    f"SELECT {_COLS} FROM {_TABLE} WHERE alpha_id = :a"), {"a": alpha_id}).fetchone()
                if cur is None:
                    return None
                prev = _row(cur)
                expr_changed = (prev["expr"] or "").strip() != expr.strip()
                new_version = prev["version"] + (1 if expr_changed else 0)
                new_status = "draft" if expr_changed and not prev["is_template"] else prev["status"]
                c.execute(text(
                    f"UPDATE {_TABLE} SET name=:n, expr=:e, description=:d, universe=:u, "
                    "tags=:t, version=:v, status=:s, notes=:no, updated_at=:ts WHERE alpha_id=:a"),
                    {"n": name, "e": expr, "d": description, "u": universe,
                     "t": json.dumps(tags or prev["tags"], ensure_ascii=False),
                     "v": new_version, "s": new_status, "no": notes or prev["notes"],
                     "ts": now, "a": alpha_id})
                return get_alpha(alpha_id)
            aid = f"al_{secrets.token_hex(5)}"
            c.execute(text(
                f"INSERT INTO {_TABLE} ({_COLS}) VALUES "
                "(:a, :n, :e, :d, :u, :t, :s, 1, :tpl, NULL, :p, :no, :ts, :ts)"),
                {"a": aid, "n": name, "e": expr, "d": description, "u": universe,
                 "t": json.dumps(tags or [], ensure_ascii=False),
                 "s": status if status in STATUSES else "draft",
                 "tpl": 1 if is_template else 0, "p": parent_id, "no": notes, "ts": now})
        return get_alpha(aid)
    except Exception as e:
        logger.warning(f"alpha upsert 실패: {e}")
        return None


def get_alpha(alpha_id: str) -> dict | None:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            r = c.execute(text(f"SELECT {_COLS} FROM {_TABLE} WHERE alpha_id = :a"),
                          {"a": alpha_id}).fetchone()
        return _row(r) if r else None
    except Exception as e:
        logger.warning(f"alpha 조회 실패: {e}")
        return None


def list_alphas(status: str | None = None, limit: int = 100) -> list[dict]:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        q = f"SELECT {_COLS} FROM {_TABLE} "
        params: dict[str, Any] = {"lim": max(1, min(int(limit), 300))}
        if status:
            q += "WHERE status = :s "
            params["s"] = status
        q += "ORDER BY is_template DESC, updated_at DESC LIMIT :lim"
        with engine.connect() as c:
            rows = c.execute(text(q), params).fetchall()
        return [_row(r) for r in rows]
    except Exception as e:
        logger.warning(f"alpha 목록 실패: {e}")
        return []


def attach_validation(alpha_id: str, run_id: str) -> bool:
    """검증 리포트(ResearchRun) 연결 — validated 승격의 전제."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(
                f"UPDATE {_TABLE} SET last_run_id = :r, updated_at = :ts WHERE alpha_id = :a"),
                {"r": run_id, "ts": time.time(), "a": alpha_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"alpha 검증 연결 실패: {e}")
        return False


def promote_alpha(alpha_id: str, to_status: str, note: str = "") -> dict:
    """상태 전이 — 요건 미충족 시 정직한 사유 반환 (조용한 무시 금지)."""
    if to_status not in STATUSES:
        return {"ok": False, "reason": f"알 수 없는 상태: {to_status}"}
    a = get_alpha(alpha_id)
    if a is None:
        return {"ok": False, "reason": "알파를 찾을 수 없습니다."}
    cur = a["status"]
    if to_status == cur:
        return {"ok": False, "reason": f"이미 {cur} 상태입니다."}
    # retired·draft(강등)는 자유. 전진은 순차 + 요건.
    if to_status not in ("retired", "draft"):
        if _PROMOTE_NEXT.get(cur) != to_status:
            return {"ok": False,
                    "reason": f"{cur} → {to_status} 직행 불가 — 순서: draft → experimental → validated → approved."}
        if to_status == "validated" and not a["last_run_id"]:
            return {"ok": False, "reason": "검증 리포트(run) 없이 validated 승격 불가 — 먼저 검증을 실행하세요."}
        if to_status == "approved" and not note.strip():
            return {"ok": False, "reason": "approved 승격에는 승인 노트가 필요합니다 (정식 승인 워크플로는 P4)."}
    try:
        engine = _engine()
        from sqlalchemy import text
        note_add = f"[{cur}→{to_status}] {note}".strip()
        merged = (a["notes"] + "\n" + note_add).strip() if a["notes"] else note_add
        with engine.begin() as c:
            c.execute(text(
                f"UPDATE {_TABLE} SET status = :s, notes = :n, updated_at = :ts WHERE alpha_id = :a"),
                {"s": to_status, "n": merged, "ts": time.time(), "a": alpha_id})
        return {"ok": True, "alpha": get_alpha(alpha_id)}
    except Exception as e:
        logger.warning(f"alpha 승격 실패: {e}")
        return {"ok": False, "reason": "DB 오류로 승격 실패."}


def delete_alpha(alpha_id: str) -> bool:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE alpha_id = :a"), {"a": alpha_id})
        return bool(res.rowcount)
    except Exception as e:
        logger.warning(f"alpha 삭제 실패: {e}")
        return False


# ── 6개 기본 슬리브 템플릿 (정직 라벨 — 데이터 미보유는 명시) ──────────────────
SLEEVE_TEMPLATES: list[dict] = [
    {
        "key": "quality_lowvol", "name": "Quality-LowVol",
        "expr": "zscore(roe) + zscore(net_margin) - zscore(vol_60d) - zscore(debt_ratio)",
        "description": "수익성·안정성·저변동 결합 — 시장/섹터 중립 옵션은 sector_neutralize()로.",
        "status": "experimental", "tags": ["quality", "low_vol", "template"],
        "notes": "template/experimental — 실데이터 검증 후 승격.",
    },
    {
        "key": "shareholder_return", "name": "주주환원 (배당 프록시)",
        "expr": "zscore(dividend_yield_f)",
        "description": "배당수익률 기반. 자사주 매입·소각·밸류업 공시 이벤트 데이터 미보유 — 배당 프록시만.",
        "status": "experimental", "tags": ["shareholder_return", "template"],
        "notes": "template/experimental — 이벤트(자사주·밸류업) 데이터 미보유. 배당 프록시의 한계 명시.",
    },
    {
        "key": "earnings_revision", "name": "어닝 리비전 (EPS YoY 대용)",
        "expr": "zscore(eps_yoy)",
        "description": "컨센서스·가이던스 데이터 미보유 — 연간 EPS 증감(YoY)을 대용 사용 (서프라이즈 아님).",
        "status": "experimental", "tags": ["earnings", "template"],
        "notes": "template/experimental — 컨센서스 부재로 진짜 리비전이 아닌 대용 지표. 유료 데이터 연동 시 교체.",
    },
    {
        "key": "sector_rel_momentum", "name": "섹터 상대 모멘텀",
        "expr": "sector_neutralize(zscore(mom_6m))",
        "description": "섹터 내 상대 강도 — 시장·섹터 스큐 통제(그룹 demean).",
        "status": "experimental", "tags": ["momentum", "sector_neutral", "template"],
        "notes": "template/experimental — 섹터 분류는 KRX 마스터+테마 그룹 기준.",
    },
    {
        "key": "pair_spread", "name": "베타중립 페어/스프레드",
        "expr": "",
        "description": "동일 업종 내 상대가치 페어 — 헤지비율·공적분·중단 규칙이 필요한 별도 엔진 (P3 스코프).",
        "status": "draft", "tags": ["pair", "market_neutral", "template"],
        "notes": "template — 페어 엔진 미구현 (P3). 표현식 알파로는 표현 불가.",
    },
    {
        "key": "canary_overlay", "name": "카나리 Risk-On/Off 오버레이",
        "expr": "",
        "description": "변동성·신용·시장폭 기반 방어 오버레이 — 수익원이 아닌 리스크 조절. 03 Timing에서 구성.",
        "status": "experimental", "tags": ["overlay", "defensive", "template"],
        "notes": "template — 알파가 아닌 오버레이. AAS 03 Timing 스테이지가 구현체.",
    },
]


def seed_templates() -> int:
    """템플릿 6종 시드 (이름 기준 멱등 — 이미 있으면 스킵). 시드 수 반환."""
    try:
        existing = {a["name"] for a in list_alphas(limit=300) if a["is_template"]}
        n = 0
        for t in SLEEVE_TEMPLATES:
            if t["name"] in existing:
                continue
            if upsert_alpha(None, t["name"], t["expr"], description=t["description"],
                            tags=t["tags"], is_template=True, status=t["status"],
                            notes=t["notes"]) is not None:
                n += 1
        return n
    except Exception as e:
        logger.warning(f"템플릿 시드 실패: {e}")
        return 0
