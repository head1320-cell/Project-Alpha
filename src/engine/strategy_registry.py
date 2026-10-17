"""전략 레지스트리 — ★저장된 백테스트 실행을 전략으로 등록한다★ (BG1 · R1 복원)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-24-multistrategy-restore-r1-r3-design.md` §4.1 ·
원천 `src/data/backtest_runs.py` · 재실행 경로 `src/api/screener_routes._backtest_kwargs` ·
소비자 `multi_strategy_backtest` · `realism_engine` · `stage12_routes`(상관 건강도)

## 왜 이 모듈이 생겼나

`multi_strategy_backtest` 는 2026-06-10 스냅샷 이식 때부터 이 모듈을 import 했는데
저장소에 한 번도 없었다(BF). 원래 설계는 캔버스 그래프 전략(`strategies.graph_json`)
이었지만 저장 경로가 없다. 사용자가 **저장된 백테스트 실행을 등록**하는 쪽을 골랐다.

## ★등록은 재실행 + 재현 검증이다★

저장된 실행은 거래를 **앞 500건만**(표시 없이) 남긴다 — 완전한 보유를 저장본에서
복원할 수 없다. 그래서 등록 때 **같은 경로로 다시 돌려** 완전한 거래를 얻고, 재실행
자산곡선이 저장본과 **전부 같을 때만** 등록한다. 다르면 거절하고 첫 불일치를 말한다
— 같은 전략이라고 말할 수 없기 때문이다.

★다시 스크리닝하지 않는다★ — 스크리닝은 **현재** 데이터로 돈다. 저장된
`screened_tickers` 로 재실행한다. 그 목록에 없는 재료(평가 상한보다 큰 재편입 풀 ·
tactical 전략)는 재현할 수 없으므로 **미리** 거절한다.

## ★이 모듈이 주장하지 않는 것★

- **전략이 좋다고 말하지 않는다.** 원천 실행의 mock·PIT 표시를 그대로 옮길 뿐이다.
- **보유를 지어내지 않는다.** 종가가 없는 종목이 있는 날은 그날 보유를 `None` 으로
  둔다(네팅이 그날을 미상으로 센다).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

_REG = "strategy_registry"
_DAILY = "strategy_daily"


class RegistrationRefused(Exception):
    """등록 거절 — ★사유와 근거를 함께 싣는다★"""

    def __init__(self, reason: str, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _loads(v, default):
    if v is None:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


class StrategyRegistry:
    """등록된 전략 — 정수 id · 일별 수익률 · 일별 종목 보유(등록 시점 스냅샷)."""

    def __init__(self, db_engine=None):
        if db_engine is None:
            from src.database import get_sync_engine
            db_engine = get_sync_engine()
        self.engine = db_engine
        self._ensure()

    # ── 스키마 ────────────────────────────────────────────────────────
    def _ensure(self) -> None:
        pg = self.engine.dialect.name == "postgresql"
        pk = "id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        with self.engine.begin() as c:
            c.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_REG} ("
                f"{pk}, name VARCHAR(200) NOT NULL, "
                "source_run_id VARCHAR(64) NOT NULL UNIQUE, "
                "is_active INTEGER NOT NULL DEFAULT 1, "
                "is_mock_data INTEGER, is_pit_verified INTEGER, "
                "symbols TEXT, registered_at DOUBLE PRECISION, repro TEXT)"))
            c.execute(text(
                f"CREATE TABLE IF NOT EXISTS {_DAILY} ("
                "strategy_id INTEGER NOT NULL, trade_date VARCHAR(10) NOT NULL, "
                "daily_return DOUBLE PRECISION, holdings TEXT, "
                "PRIMARY KEY (strategy_id, trade_date))"))

    # ── 등록 ──────────────────────────────────────────────────────────
    def register(self, run_id: str, name: str | None = None) -> dict:
        """저장된 실행 → 전략. ★재현되지 않으면 거절한다★"""
        from src.data import backtest_runs as br

        run = br.get_run(run_id)
        if not run:
            raise RegistrationRefused(f"실행 {run_id} 를 찾을 수 없습니다.",
                                      {"run_id": run_id})
        if run.get("status") != "completed":
            raise RegistrationRefused(
                f"completed 실행만 등록할 수 있습니다 — 이 실행은 {run.get('status')} 입니다.",
                {"run_id": run_id, "status": run.get("status")})
        if self._by_source(run_id) is not None:
            raise RegistrationRefused("이미 등록된 실행입니다.", {"run_id": run_id})

        stored = run.get("result") or {}
        snap = run.get("input_snapshot") or {}
        curve, dates = self._stored_curve(stored)
        if not curve:
            raise RegistrationRefused("저장된 결과에 자산곡선이 없습니다 — 비교할 것이 없습니다.",
                                      {"run_id": run_id})

        req, tickers, pool, fw, eff = self._rebuild(snap, stored)
        from src.api.screener_routes import _backtest_kwargs
        from src.kis_backtest_engine import run_backtest

        captured: list = []
        rerun = run_backtest(**_backtest_kwargs(req, tickers, pool, fw, eff[0], eff[1]),
                             on_engine=captured.append)
        r_curve = ((rerun.get("result") or {}).get("equity_curve")) or []
        r_dates = ((rerun.get("result") or {}).get("equity_dates")) or []
        repro = self._compare(curve, dates, r_curve, r_dates)
        if not repro["equal"]:
            raise RegistrationRefused(
                "재실행 자산곡선이 저장본과 다릅니다 — 같은 전략이라고 말할 수 없습니다 "
                "(데이터가 바뀌었거나 재현할 수 없는 설정입니다).",
                {"run_id": run_id, **repro})
        eng = captured[0]

        rows = self._daily_rows(eng)
        with self.engine.begin() as c:
            sid = c.execute(text(
                f"INSERT INTO {_REG} (name, source_run_id, is_active, is_mock_data, "
                "is_pit_verified, symbols, registered_at, repro) VALUES "
                "(:n, :r, 1, :m, :p, :s, :t, :rp) RETURNING id"),
                {"n": name or run.get("strategy_name") or run_id, "r": run_id,
                 "m": None if run.get("is_mock_data") is None else int(run["is_mock_data"]),
                 "p": None if run.get("is_pit_verified") is None else int(run["is_pit_verified"]),
                 "s": json.dumps(tickers), "t": time.time(),
                 "rp": json.dumps(repro)}).scalar()
            c.execute(text(
                f"INSERT INTO {_DAILY} (strategy_id, trade_date, daily_return, holdings) "
                "VALUES (:sid, :d, :r, :h)"),
                [{"sid": sid, "d": d, "r": r,
                  "h": None if h is None else json.dumps(h)} for d, r, h in rows])
        return self.get(int(sid))

    @staticmethod
    def _stored_curve(stored: dict) -> tuple[list, list]:
        bt = stored.get("backtest") or {}
        return list(bt.get("equity_curve") or []), list(bt.get("equity_dates") or [])

    @staticmethod
    def _rebuild(snap: dict, stored: dict):
        """저장된 요청·스크리닝 결과 → 재실행 재료. ★스크리너를 부르지 않는다★"""
        from src.api.screener_routes import (
            ScreenToBacktestRequest,
            _effective_strategy,
            _factor_weights,
        )
        try:
            req = ScreenToBacktestRequest(**snap)
        except Exception as e:  # noqa: BLE001
            raise RegistrationRefused(f"저장된 요청을 복원할 수 없습니다: {e}") from e
        if (req.strategy_name or "").startswith("tactical:"):
            raise RegistrationRefused(
                "tactical 전략은 스크리너 경로를 타지 않아 이 방식으로 재현할 수 없습니다.")
        if req.replenishment_pool_cap > req.universe_eval_cap:
            raise RegistrationRefused(
                "replenishment_pool_cap 이 universe_eval_cap 보다 커서 재편입 풀이 평가 "
                "종목보다 넓었습니다 — 그 풀은 저장되지 않아 재현할 수 없습니다.",
                {"replenishment_pool_cap": req.replenishment_pool_cap,
                 "universe_eval_cap": req.universe_eval_cap})
        screened = [x for x in (stored.get("screened_tickers") or [])
                    if isinstance(x, dict) and x.get("stock_code")]
        if not screened:
            raise RegistrationRefused("저장된 결과에 스크리닝 종목(screened_tickers)이 없습니다.")
        tickers = [x["stock_code"] for x in screened]
        # 코어와 같다: 풀 ≤ 평가 상한이면 풀 == 평가 종목, 0 이면 재편입 없음.
        pool = list(tickers) if req.replenishment_pool_cap > 0 else []
        fw = _factor_weights(req, {x["stock_code"]: float(x.get("composite_score") or 0)
                                   for x in screened})
        return req, tickers, pool, fw, _effective_strategy(req)

    @staticmethod
    def _compare(curve, dates, r_curve, r_dates) -> dict:
        """★전부 같아야 한다★ — 첫 불일치를 근거로 싣는다."""
        n = max(len(curve), len(r_curve))
        for i in range(n):
            a = curve[i] if i < len(curve) else None
            b = r_curve[i] if i < len(r_curve) else None
            da = dates[i] if i < len(dates) else None
            db = r_dates[i] if i < len(r_dates) else None
            if a != b or da != db:
                return {"equal": False, "compared_points": n,
                        "first_mismatch": {"index": i, "date": da or db,
                                           "stored": a, "rerun": b,
                                           "stored_date": da, "rerun_date": db}}
        return {"equal": True, "compared_points": n, "first_mismatch": None}

    @staticmethod
    def _daily_rows(eng) -> list[tuple[str, float | None, dict | None]]:
        """완전한 거래 + 종가 → `(날짜, 일별 수익률, 종목 비중 | None)`.

        ★종가를 못 구한 보유 종목이 있는 날은 `None`★ — 그날 보유를 지어내지 않는다.
        """
        hist = [(str(d)[:10], float(v)) for d, v in eng.equity_history]
        trades = sorted(eng.trades, key=lambda t: str(t.date)[:10])
        closes = {tk: df["close"] for tk, df in (eng.ohlcv_all or {}).items()
                  if df is not None and not df.empty and "close" in df}
        qty: dict[str, float] = {}
        ti = 0
        rows = []
        prev = None
        for d, eq in hist:
            while ti < len(trades) and str(trades[ti].date)[:10] <= d:
                t = trades[ti]
                q = float(t.quantity) * (1 if t.side == "buy" else -1)
                qty[t.ticker] = qty.get(t.ticker, 0.0) + q
                if abs(qty[t.ticker]) < 1e-9:
                    del qty[t.ticker]
                ti += 1
            holdings: dict | None = {}
            if eq > 0:
                ts = pd.Timestamp(d)
                for tk, q in qty.items():
                    s = closes.get(tk)
                    px = None
                    if s is not None:
                        part = s[s.index <= ts].dropna()
                        if not part.empty:
                            px = float(part.iloc[-1])
                    if px is None:
                        holdings = None
                        break
                    holdings[tk] = round(q * px / eq, 10)
            else:
                holdings = None
            ret = None if prev in (None, 0) else eq / prev - 1.0
            rows.append((d, ret, holdings))
            prev = eq
        return rows

    # ── 읽기 ──────────────────────────────────────────────────────────
    def _by_source(self, run_id: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(text(f"SELECT id FROM {_REG} WHERE source_run_id = :r"),
                          {"r": run_id}).fetchone()
        return self.get(int(r[0])) if r else None

    @staticmethod
    def _row(r) -> dict:
        return {"id": int(r[0]), "name": r[1], "source_run_id": r[2],
                "is_active": bool(r[3]),
                "is_mock_data": None if r[4] is None else bool(r[4]),
                "is_pit_verified": None if r[5] is None else bool(r[5]),
                "symbols": _loads(r[6], []), "registered_at": r[7],
                "repro": _loads(r[8], None)}

    _COLS = ("id, name, source_run_id, is_active, is_mock_data, is_pit_verified, "
             "symbols, registered_at, repro")

    def get(self, sid) -> dict | None:
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return None
        with self.engine.connect() as c:
            r = c.execute(text(f"SELECT {self._COLS} FROM {_REG} WHERE id = :i"),
                          {"i": sid}).fetchone()
        return self._row(r) if r else None

    def list(self, active_only: bool = True) -> list[dict]:
        q = f"SELECT {self._COLS} FROM {_REG}"
        if active_only:
            q += " WHERE is_active = 1"
        with self.engine.connect() as c:
            return [self._row(r) for r in c.execute(text(q + " ORDER BY id")).fetchall()]

    def deactivate(self, sid) -> bool:
        with self.engine.begin() as c:
            n = c.execute(text(f"UPDATE {_REG} SET is_active = 0 WHERE id = :i"),
                          {"i": int(sid)}).rowcount
        return bool(n)

    def _daily(self, strategy_ids, start_date, end_date) -> list:
        ids = [int(s) for s in strategy_ids]
        if not ids:
            return []
        marks = ", ".join(f":s{i}" for i in range(len(ids)))
        params: dict[str, Any] = {f"s{i}": s for i, s in enumerate(ids)}
        q = (f"SELECT strategy_id, trade_date, daily_return, holdings FROM {_DAILY} "
             f"WHERE strategy_id IN ({marks})")
        if start_date:
            q += " AND trade_date >= :sd"
            params["sd"] = str(start_date)[:10]
        if end_date:
            q += " AND trade_date <= :ed"
            params["ed"] = str(end_date)[:10]
        with self.engine.connect() as c:
            return c.execute(text(q + " ORDER BY trade_date"), params).fetchall()

    def load_returns_matrix(self, strategy_ids, start_date=None, end_date=None,
                            drop_na_rows: bool = True) -> pd.DataFrame:
        """행 = 날짜(DatetimeIndex), 열 = **정수** 전략 id. 수익률이 없는 칸은 NaN."""
        ids = [int(s) for s in strategy_ids]
        rows = self._daily(ids, start_date, end_date)
        if not rows:
            return pd.DataFrame(columns=ids)
        df = pd.DataFrame(rows, columns=["sid", "date", "ret", "h"])
        m = df.pivot(index="date", columns="sid", values="ret")
        m.index = pd.to_datetime(m.index)
        m = m.reindex(columns=ids).astype(float)
        return m.dropna(how="any") if drop_na_rows else m

    def load_holdings(self, strategy_ids, start_date=None,
                      end_date=None) -> dict[int, dict[str, dict | None]]:
        """`{전략 id: {날짜: {종목: 비중} | None}}` — `None` 은 ★그날 보유 미상★."""
        out: dict[int, dict[str, dict | None]] = {int(s): {} for s in strategy_ids}
        for sid, d, _r, h in self._daily(strategy_ids, start_date, end_date):
            out[int(sid)][str(d)[:10]] = _loads(h, None) if h is not None else None
        return out
