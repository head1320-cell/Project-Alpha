"""CompanySnapshot 영속 저장 — 증권 언더라이팅의 **불변·버전화된** 그릇 (P2-1)

메우는 구멍
──────────────────────────────────────────────────────────────────────────────
Company 탭은 지금 **매번 다시 계산한다.** 밸류에이션·이익의 질·리스크·피어가
화면을 그릴 때마다 산출되고, 그 값이 어떤 가정·어떤 시점의 재무로 나왔는지는
어디에도 남지 않는다. "그때 무엇을 보고 그 판단을 내렸는가" 에 답할 수 없다는 뜻이고,
그게 대시보드와 **언더라이팅 엔진**을 가르는 선이다.

남은 업그레이드 넷(역DCF · 확률적 밸류에이션 · 매크로 민감도 · 논지/kill 조건)은
전부 **저장할 곳이 없어서** 못 얹힌다. 이 모듈이 그 그릇이다.

★새 모델을 하나도 짓지 않는다★
이 저장소는 계산하지 않는다. `company_analytics.financial_deep` · `risk_deep` ·
`comps_table` · `ValuationEngine.evaluate` 가 이미 내는 값을 **담기만** 한다.
같은 산수를 두 곳에 두면 반드시 갈라진다 — 이 저장소가 A1(`currentSig`/`req`)과
R0(오버레이 컴파일)에서 두 번 값을 치른 실수다.

설계 (`regime_snapshots.py` 의 MES 관례를 **그대로 복제**한다 — 새 규약 0개)
──────────────────────────────────────────────────────────────────────────────
  · `_engine()` → `_ensure_table()` → raw SQL, DB 미가용 시 조용히 `None`/`[]`
    (앱은 계속 동작하고, 정직 보고는 API 가 한다)
  · `_inited_for` 로 **어느 DB 에 대해** 초기화했는지 함께 기억한다 — `_inited` 만
    보면 `DATABASE_URL` 이 바뀌었을 때 `_ensure_table` 이 그대로 빠져나가 INSERT 가
    "no such table" 로 죽는다(regime_snapshots 가 실측으로 겪은 결함).
  · 열 이름 목록에서 인덱스를 **파생**시킨다. `row[15]` 같은 상수 인덱스는 후행 열이
    둘 이상 되는 순간 통째로 밀린다(M1-S 의 교훈).
  · `cs_` + 시각 + 난수 hex

★후행 열은 `schema_add_columns.add_columns` 로★
슬라이스가 자기 컬럼을 `add_columns` + **가용성 플래그**로 붙인다 —
`regime_snapshots` 의 `regime`·MES·`regime_path` 세 블록이 그렇게 붙었다.
빈 컬럼을 미리 깔지 않는 것이 규칙이다(스키마가 있는 척한다).

  · `implied` (P2-2 역DCF) — **붙었다.** `_has_implied_col` 이 그 성공 여부다.
  · `valuation_dist`(P2-3) · `macro_sensitivity`(P2-4) · `thesis`(P2-5) — 아직.

플래그가 False 면 그 섹션은 **없는 것처럼** 동작해야 한다(`_sections()`). 있는 척하고
SELECT 하면 조회 전체가 깨지고, 그것은 컬럼이 없는 것보다 나쁘다.

불변식
──────────────────────────────────────────────────────────────────────────────
1. **불변** — 갱신 경로를 제공하지 않는다. 같은 종목·같은 as_of 라도 새 스냅샷이
   만들어진다. (재무가 정정되었다면 그것은 **새로운 사실**이지 기존 기록의 수정이
   아니다.) 삭제만 허용한다(오기재 정리용).
2. **PIT 정직성** — ★우리는 DART 재무의 실제 공표일을 모른다.★ `pit_store` 는
   가용성을 **정적 시차 규칙**(분기 45일 · 연간 90일, `pit_store.py:33-35`)으로
   판정하고, `dart_history.load_history` 행에는 접수일이 없으며(`year/reprt/month/seq`
   뿐), `rcept_dt` 는 내부자 공시에만 파싱된다(`dart_client.py:570`). 정정공시 이력도
   없다. 그러므로 이 스냅샷은 `backtest_eligible` 을 **주장하지 않는다** —
   `pit_macro.derive_usage(has_vintage=False, …)` 를 태워 `forward_only` 로 떨어진다.
   빌더가 그 판정을 하고, 이 모듈은 받은 값을 그대로 굳힌다.
3. **미가용은 사유** — 키는 값이 없어도 존재하고, 없으면 `{available:false, reason}`
   이 들어간다. 0 으로 채우지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TABLE = "company_snapshots"
_inited = False
# ★어느 DB 에 대해 초기화했는지 함께 기억한다★ (`regime_snapshots.py:47-56` 과 같은 이유)
# `_inited` 는 bool 로 남긴다 — 저장소 모듈의 공통 관례이고, 다수의 테스트가
# `monkeypatch.setattr(mod, "_inited", False)` 로 재초기화를 강제한다.
_inited_for: str | None = None
# ★후행 컬럼은 슬라이스마다 자기 것을 붙인다★ P2-1 이 예고한 대로다 — 빈 컬럼을 미리
# 깔면 스키마가 있는 척한다. `implied`(P2-2 역DCF)가 그 첫 사례이고, 성공 여부를
# 반드시 따로 들고 있어야 한다: ALTER 가 권한 등으로 실패했는데 SELECT 가 그 컬럼을
# 참조하면 스냅샷 조회가 통째로 깨진다(수정 전보다 나쁨).
_has_implied_col = False

# 스냅샷 스키마 버전 — 섹션의 모양이 바뀌면 올린다.
SNAPSHOT_VERSION = 1

# 언더라이팅 산출 로직 버전 (밸류에이션 가정·품질 지표 정의가 바뀌면 올린다).
MODEL_VERSION = "company-underwriting-v1"
ENGINE_VERSION = "cs-pit-v1"

# ★JSON 으로 굳히는 큰 섹션★ 목록 조회에서는 빼고 요약만 준다(payload 비대 방지 —
# MES 가 `observations` 에 대해 하는 것과 같다).
_BASE_SECTIONS = ("financials", "publication_dates", "valuation", "quality",
                  "factors", "peers", "risk", "provenance")
# 후행 컬럼으로 붙는 섹션 — 컬럼이 실제로 붙었을 때만 목록에 들어간다.
_LATE_SECTIONS = ("implied",)


def _sections() -> tuple[str, ...]:
    """이 DB 에서 **실제로 쓸 수 있는** 섹션 이름.

    후행 컬럼이 안 붙었으면 그 섹션은 없는 것처럼 동작한다 — 있는 척하고 SELECT 하면
    조회 전체가 깨지고, 그것은 컬럼이 없는 것보다 나쁘다(`add_columns` 계약).
    """
    return _BASE_SECTIONS + (_LATE_SECTIONS if _has_implied_col else ())


def _engine():
    from src.database import get_engine
    return get_engine()


def _ensure_table(engine) -> None:
    global _inited, _inited_for, _has_implied_col
    url = str(getattr(engine, "url", ""))
    if _inited and _inited_for == url:
        return
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
            "snapshot_id VARCHAR(40) PRIMARY KEY, "
            "code VARCHAR(20), "
            "created_at DOUBLE PRECISION, "
            "as_of VARCHAR(32), "
            "price DOUBLE PRECISION, "
            "price_source VARCHAR(40), "
            "data_status VARCHAR(20), "
            "research_usage VARCHAR(24), "
            "model_version VARCHAR(40), "
            "engine_version VARCHAR(40), "
            "code_version VARCHAR(60), "
            "snapshot_version INTEGER, "
            "financials TEXT, "
            "publication_dates TEXT, "
            "valuation TEXT, "
            "quality TEXT, "
            "factors TEXT, "
            "peers TEXT, "
            "risk TEXT, "
            "provenance TEXT)"
        ))
        c.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_cs_code_created ON {_TABLE} (code, created_at)"
        ))
    # ── 역DCF (P2-2) ────────────────────────────────────────────────────────
    # 시장가를 정당화하는 가정. 값이 아니라 **가정**을 굳히는 것이 언더라이팅이다.
    from src.data.schema_add_columns import add_columns
    _has_implied_col = add_columns(
        engine, _TABLE, [("implied", "TEXT")],
        label="company_snapshots.implied(역DCF 시장내재 가정)",
    )

    _inited = True
    _inited_for = url


def code_version() -> str:
    return os.getenv("GIT_SHA") or os.getenv("APP_VERSION") or "dev"


def _new_id() -> str:
    return f"cs_{int(time.time())}_{secrets.token_hex(4)}"


def create_snapshot(
    *,
    code: str,
    as_of: str,
    price: float | None,
    price_source: str,
    data_status: str,
    research_usage: str,
    financials: Any = None,
    publication_dates: Any = None,
    valuation: Any = None,
    quality: Any = None,
    factors: Any = None,
    peers: Any = None,
    risk: Any = None,
    provenance: Any = None,
    implied: Any = None,
) -> str | None:
    """불변 스냅샷을 만든다. 성공 시 snapshot_id, DB 미가용 시 `None`.

    ★갱신 함수가 없는 것이 불변식이다★ 이 모듈에는 `update_*`/`set_*` 이 없다.
    같은 종목을 다시 굳히면 **새 ID** 가 나오고 기존 행은 그대로 남는다.
    """
    sid = _new_id()
    sections = {
        "financials": financials, "publication_dates": publication_dates,
        "valuation": valuation, "quality": quality, "factors": factors,
        "peers": peers, "risk": risk, "provenance": provenance,
        "implied": implied,
    }
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        # ★열 목록과 `:name` 바인딩을 **같은 순회에서** 만든다★ 둘을 따로 적으면
        # 한쪽만 고쳐졌을 때 값이 다른 컬럼에 들어간다(P2-1 의 프로브가 실제로 재현했다).
        names = _sections()
        cols = ("snapshot_id, code, created_at, as_of, price, price_source, "
                "data_status, research_usage, model_version, engine_version, "
                "code_version, snapshot_version, " + ", ".join(names))
        vals = (":sid, :code, :ts, :asof, :price, :psrc, :status, :usage, "
                ":mver, :ever, :cver, :sver, " + ", ".join(f":{n}" for n in names))
        params: dict[str, Any] = {
            "sid": sid, "code": str(code), "ts": time.time(), "asof": as_of,
            "price": (float(price) if price is not None else None),
            "psrc": price_source, "status": data_status, "usage": research_usage,
            "mver": MODEL_VERSION, "ever": ENGINE_VERSION, "cver": code_version(),
            "sver": SNAPSHOT_VERSION,
        }
        for name in names:
            value = sections.get(name)
            params[name] = (None if value is None
                            else json.dumps(value, ensure_ascii=False, default=str))
        with engine.begin() as c:
            c.execute(text(f"INSERT INTO {_TABLE} ({cols}) VALUES ({vals})"), params)
        return sid
    except Exception as e:  # noqa: BLE001
        logger.warning("company snapshot 저장 실패: %s", e)
        return None


_BASE_COL_LIST = ["snapshot_id", "code", "created_at", "as_of", "price", "price_source",
                  "data_status", "research_usage", "model_version", "engine_version",
                  "code_version", "snapshot_version"]


def _col_list() -> list[str]:
    """실제로 SELECT 할 열 이름.

    ★위치 인덱스를 손으로 세지 않는다★ 후행 블록이 붙기 시작하면(P2-2~P2-5) 손으로
    센 `row[15]` 는 통째로 밀린다. 이름 목록에서 인덱스를 파생시키면 그 함정이
    구조적으로 사라진다 — `regime_snapshots._col_list` 가 같은 이유로 그렇게 한다.
    """
    return _BASE_COL_LIST + list(_sections())


def _cols() -> str:
    return ", ".join(_col_list())


def _row_to_dict(row, *, full: bool) -> dict[str, Any]:
    def _j(raw, default):
        try:
            return json.loads(raw) if raw else default
        except Exception:
            return default

    g = dict(zip(_col_list(), row, strict=False))
    d: dict[str, Any] = {
        "snapshot_id": g.get("snapshot_id"), "code": g.get("code"),
        "created_at": g.get("created_at"), "as_of": g.get("as_of"),
        "price": g.get("price"), "price_source": g.get("price_source"),
        "data_status": g.get("data_status"), "research_usage": g.get("research_usage"),
        "model_version": g.get("model_version"), "engine_version": g.get("engine_version"),
        "code_version": g.get("code_version"),
        "snapshot_version": g.get("snapshot_version"),
    }
    if full:
        # ★키는 값이 없어도 존재한다★ `None` = 이 섹션을 담지 않았다(빌더가 굳히기
        # 전이거나 산출 불가). 섹션 **내부**의 미가용은 그 안의
        # `{available:false, reason}` 이 말한다 — 둘은 다른 사실이다.
        for s in _sections():
            d[s] = _j(g.get(s), None)
    else:
        # 목록에서는 큰 섹션을 빼고 이름만 (MES 의 observation_count 와 같은 이유).
        #
        # ★"담겼다" 와 "값이 있다" 를 나눈다★ 처음에는 `sections_present` 하나로
        # 저장된 블롭 이름을 줬는데, 라이브로 재 보니 재무 미적재 종목에서
        # `financials` 가 present 로 나왔다 — 블롭은 있지만 내용은
        # `{available:false, reason}` 이다. 목록만 보는 소비자에게 그것은 거짓말이다.
        avail, unavail = [], []
        for s in _sections():
            raw = g.get(s)
            if not raw:
                continue
            body = _j(raw, None)
            # ★`available` 을 말하지 않는 섹션은 내용이 있는 것으로 본다★ 빌더는 항상
            # dict 를 넣지만 저장소가 그것을 가정하면 목록 조회 전체가 죽는다(리스트를
            # 넣은 테스트에서 실제로 그랬다). 형태를 강제하는 것은 저장소의 일이 아니다.
            ok = body.get("available", True) if isinstance(body, dict) else body is not None
            (avail if ok else unavail).append(s)
        d["sections_available"] = avail
        d["sections_unavailable"] = unavail
    return d


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as c:
            row = c.execute(text(f"SELECT {_cols()} FROM {_TABLE} WHERE snapshot_id = :sid"),
                            {"sid": snapshot_id}).fetchone()
        return _row_to_dict(row, full=True) if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning("company snapshot 조회 실패: %s", e)
        return None


def list_snapshots(code: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """최신순 요약 목록 (큰 섹션 제외 — 담긴 섹션 이름만). `code` 로 종목 한정."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        where = " WHERE code = :code" if code else ""
        params: dict[str, Any] = {"lim": max(1, min(int(limit), 200))}
        if code:
            params["code"] = str(code)
        with engine.connect() as c:
            rows = c.execute(text(
                f"SELECT {_cols()} FROM {_TABLE}{where} "  # noqa: S608
                "ORDER BY created_at DESC, snapshot_id DESC LIMIT :lim"), params).fetchall()
        return [_row_to_dict(r, full=False) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("company snapshot 목록 실패: %s", e)
        return []


def delete_snapshot(snapshot_id: str) -> bool:
    """오기재 정리용. 내용 수정이 아니라 삭제만 허용한다(불변식 유지)."""
    try:
        engine = _engine()
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as c:
            res = c.execute(text(f"DELETE FROM {_TABLE} WHERE snapshot_id = :sid"),
                            {"sid": snapshot_id})
        return bool(res.rowcount)
    except Exception as e:  # noqa: BLE001
        logger.warning("company snapshot 삭제 실패: %s", e)
        return False
