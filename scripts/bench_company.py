#!/usr/bin/env python3
"""Company 계측 하네스 — vNext 감사 0단계 (`.md` §30 Company 관측성).

★프로덕션 코드를 한 줄도 고치지 않는다★ `src/` 를 **임포트만** 하고 밖에서 잰다.

  python3 scripts/bench_company.py --code 005930
  python3 scripts/bench_company.py --code 005930 --json out.json

무엇을 재는가 (`.md` §30 목록):
  콜드/웜 지연 · DART 호출/캐시 적중 · DB 읽기 수 · 밸류에이션 계산 시간 ·
  페이로드 크기 · **미가용 조각 수**.

그리고 이 하네스의 존재 이유인 한 가지 —
★프론트가 `evaluate` 를 3번(base/bull/bear) 부르는 비용★.
셋은 `terminal_growth` 와 `market_premium` 만 다르고 **재무 데이터는 동일**하다
(`entities/company/data.ts:167-169`). CompanySnapshot 이 한 번 읽어 담으면 사라질
비용이 얼마인지 숫자로 낸다.

★계측을 위해 모듈 함수를 감싼다 — 엔진의 몽키패치와 무엇이 다른가★
이 하네스는 **단일 스레드**이고, 감싼 것을 `finally` 에서 되돌리며, 프로덕션
프로세스가 아니다. 백테스트 엔진의 문제는 감싼다는 것 자체가 아니라 **동시 실행
스레드가 같은 전역을 통신 채널로 쓴다**는 것이었다(감사 §3.1). 여기서는 그 조건이
성립하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

os.environ.setdefault("KIS_USE_MOCK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# 계측기
# ─────────────────────────────────────────────────────────────────────────────
class Counters:
    """DART 캐시 적중/미스 · 재무이력 읽기 · DB 쿼리 수를 한 번에 센다."""

    def __init__(self):
        self.dart_cache_hit = 0
        self.dart_cache_miss = 0
        self.dart_cache_set = 0
        self.annual_rows_reads = 0
        self.history_loads = 0
        self.db_queries = 0
        self._undo: list = []

    def __enter__(self):
        import src.data.dart_client as dc
        orig_get, orig_set = dc._dart_cache_get, dc._dart_cache_set

        def get(key):
            r = orig_get(key)
            if r is None:
                self.dart_cache_miss += 1
            else:
                self.dart_cache_hit += 1
            return r

        def st(key, data):
            self.dart_cache_set += 1
            return orig_set(key, data)

        dc._dart_cache_get, dc._dart_cache_set = get, st
        self._undo.append(lambda: setattr(dc, "_dart_cache_get", orig_get))
        self._undo.append(lambda: setattr(dc, "_dart_cache_set", orig_set))

        try:
            import src.engine.company_analytics as ca
            orig_rows = ca._annual_rows

            def rows(code):
                self.annual_rows_reads += 1
                return orig_rows(code)

            ca._annual_rows = rows
            self._undo.append(lambda: setattr(ca, "_annual_rows", orig_rows))
        except Exception:
            pass

        try:
            import src.data.dart_history as dh
            orig_hist = dh.load_history

            def hist(*a, **kw):
                self.history_loads += 1
                return orig_hist(*a, **kw)

            dh.load_history = hist
            self._undo.append(lambda: setattr(dh, "load_history", orig_hist))
        except Exception:
            pass

        try:
            from sqlalchemy import event

            from src.database import get_engine
            self._eng = get_engine()

            def on_q(conn, cur, stmt, params, ctx, many):
                self.db_queries += 1

            event.listen(self._eng, "before_cursor_execute", on_q)
            self._on_q = on_q
        except Exception:
            self._eng = None
        return self

    def __exit__(self, *a):
        for fn in reversed(self._undo):
            try:
                fn()
            except Exception:
                pass
        if getattr(self, "_eng", None) is not None:
            try:
                from sqlalchemy import event
                event.remove(self._eng, "before_cursor_execute", self._on_q)
            except Exception:
                pass
        return False

    def snapshot(self) -> dict:
        return {"dart_cache_hit": self.dart_cache_hit,
                "dart_cache_miss": self.dart_cache_miss,
                "dart_cache_set": self.dart_cache_set,
                "annual_rows_reads": self.annual_rows_reads,
                "history_loads": self.history_loads,
                "db_queries": self.db_queries}


def _delta(a: dict, b: dict) -> dict:
    return {k: b[k] - a[k] for k in b}


def _unavailable(obj, path="") -> list[str]:
    """`{available: false}` 조각을 이름으로 센다 — 화면이 조용히 비어 가는 정도."""
    out: list[str] = []
    if isinstance(obj, dict):
        if obj.get("available") is False:
            out.append(path or "<root>")
        for k, v in obj.items():
            out.extend(_unavailable(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            out.extend(_unavailable(v, f"{path}[{i}]"))
    return out


@dataclass
class Step:
    name: str
    wall_s: float = 0.0
    payload_bytes: int = 0
    counters: dict = field(default_factory=dict)
    unavailable: list = field(default_factory=list)
    error: str | None = None


def timed(name: str, c: Counters, fn) -> Step:
    s = Step(name=name)
    before = c.snapshot()
    t0 = time.perf_counter()
    try:
        r = fn()
        s.wall_s = time.perf_counter() - t0
        s.payload_bytes = len(json.dumps(r, default=str))
        s.unavailable = _unavailable(r)[:12]
    except Exception as e:
        s.wall_s = time.perf_counter() - t0
        s.error = f"{type(e).__name__}: {e}"[:200]
    s.counters = _delta(before, c.snapshot())
    return s


# ─────────────────────────────────────────────────────────────────────────────
def _price_for(code: str, fallback: float) -> tuple[float, str]:
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
        d = load_ohlcv_unified(code, "2024-01-01", "2026-12-31", prefer="auto")
        if d is not None and not d.empty:
            return float(d["close"].iloc[-1]), "ohlcv_loader"
    except Exception:
        pass
    return fallback, "fallback(--price)"


def _dart_cache_state() -> dict:
    from src.data.dart_client import _DART_CACHE_DIR
    try:
        n = len([f for f in os.listdir(_DART_CACHE_DIR) if f.endswith(".json")])
    except Exception:
        n = 0
    return {"dir": _DART_CACHE_DIR, "files": n}


def page_load(code: str, price: float, client, c: Counters, tag: str) -> list[Step]:
    """★프론트가 부르는 순서 그대로★ 실제 엔드포인트를 때린다.

    `entities/company/data.ts:152 loadCompanyCore` 의 wave1/wave2 를 그대로 따른다 —
    이 순서와 횟수가 곧 사용자가 기다리는 시간이다. TestClient 를 쓰므로 Pydantic
    직렬화까지 포함된 실제 페이로드가 나온다(§30 의 payload size).
    """
    FLT = {"logic": "AND", "conditions": [], "groups": []}
    steps: list[Step] = []

    def post(path, body):
        return lambda: client.post(path, json=body).json()

    def get(path):
        return lambda: client.get(path).json()

    # wave 1
    steps.append(timed(f"{tag}/w1:byTicker", c, post(
        "/api/v1/screener/run-advanced",
        {"universe": "all_listed", "custom_tickers": [code], "filter_ast": FLT,
         "limit": 1, "liquidity_floor": "off"})))
    steps.append(timed(f"{tag}/w1:factorSample(600)", c,
                       get("/api/v1/screener/factor-sample?limit=600")))
    steps.append(timed(f"{tag}/w1:fieldsCatalog", c,
                       get("/api/v1/screener/fields-catalog")))

    # wave 2 — evaluate 가 3번이다(base/bull/bear). 재무 데이터는 셋이 동일하다.
    for label, g, mp in (("base", 0.02, 0.06), ("bull", 0.03, 0.05), ("bear", 0.01, 0.07)):
        steps.append(timed(f"{tag}/w2:evaluate:{label}", c, post(
            "/api/v1/valuation/evaluate",
            {"stock_code": code, "current_price": price, "terminal_growth": g,
             "market_premium": mp})))
    for per in ("annual", "quarter"):
        steps.append(timed(f"{tag}/w2:financial:{per}", c,
                           get(f"/api/v1/valuation/financial/{code}?years=8&period={per}")))
    return steps


def run(code: str, price_fallback: float) -> dict:
    from src.data.dart_client import DARTClient
    from src.engine import company_analytics as ca
    from src.engine.valuation.valuation_models import ValuationEngine, ValuationParams

    price, price_src = _price_for(code, price_fallback)
    report: dict = {
        "code": code, "price": price, "price_source": price_src,
        "dart_cache_before": _dart_cache_state(),
        "steps": [],
    }

    # ── 페이지 로드 콜드/웜 (§30) ────────────────────────────────────────────
    # ★반드시 가장 먼저 돌린다★ 아래 분석 구간이 모듈 임포트와 첫 쿼리 비용을 먼저
    # 치러 버리면 "콜드" 가 콜드가 아니게 된다. 첫 시도에서 factor-sample 이
    # 8ms 로 나왔는데 단독 실행에서는 2,066ms 였다 — 그 차이가 오염의 크기다.
    try:
        from fastapi.testclient import TestClient
        from main_api import app
        client = TestClient(app)
        with Counters() as c2:
            cold = page_load(code, price, client, c2, "cold")
            cold_ctr = c2.snapshot()
            warm = page_load(code, price, client, c2, "warm")
        report["page_load"] = {
            "cold": [asdict(s) for s in cold],
            "warm": [asdict(s) for s in warm],
            "cold_wall_s": round(sum(s.wall_s for s in cold), 4),
            "warm_wall_s": round(sum(s.wall_s for s in warm), 4),
            "cold_bytes": sum(s.payload_bytes for s in cold),
            "cold_counters": cold_ctr,
            "n_calls": len(cold),
        }
    except Exception as e:
        report["page_load"] = {"error": f"{type(e).__name__}: {e}"[:200]}

    with Counters() as c:
        eng = ValuationEngine(DARTClient())

        # ── wave 2 의 3회 중복: base / bull / bear ────────────────────────────
        # 세 호출은 terminal_growth·market_premium 만 다르다(프론트 data.ts:167-169).
        scen = [("base", 0.02, 0.06), ("bull", 0.03, 0.05), ("bear", 0.01, 0.07)]
        val_steps = []
        for label, g, mp in scen:
            p = ValuationParams(terminal_growth_rate=g, market_premium=mp)
            val_steps.append(timed(
                f"evaluate:{label}", c,
                lambda p=p: _uv_to_dict(eng.evaluate(code, price, params=p))))
        report["steps"].extend(asdict(s) for s in val_steps)
        report["valuation_x3"] = {
            "total_wall_s": round(sum(s.wall_s for s in val_steps), 4),
            "first_wall_s": round(val_steps[0].wall_s, 4),
            "repeat_wall_s": round(sum(s.wall_s for s in val_steps[1:]), 4),
            "note": ("bull/bear 는 재무 데이터가 base 와 동일하다 — repeat_wall_s 가 "
                     "CompanySnapshot 이 제거할 수 있는 몫이다(가정이 아니라 실측)."),
        }

        # ── 딥 탭들: 같은 재무이력을 다시 읽는가 ──────────────────────────────
        for name, fn in (
            ("financial_deep", lambda: ca.financial_deep(code)),
            ("risk_deep", lambda: ca.risk_deep(code, price)),
            ("comps_table", lambda: ca.comps_table(code)),
            ("football_field", lambda: ca.football_field(code, price)),
            ("valuation_sandbox", lambda: ca.valuation_sandbox(code, price, {})),
        ):
            report["steps"].append(asdict(timed(name, c, fn)))

        report["totals_analytics"] = c.snapshot()

    report["dart_cache_after"] = _dart_cache_state()
    return report


def _uv_to_dict(u) -> dict:
    """UnifiedValuation → 라우트가 내보내는 모양(직렬화 비용을 같은 조건으로)."""
    return {
        "ticker": u.ticker, "corp_name": u.corp_name,
        "current_price": u.current_price, "intrinsic_value": u.intrinsic_value,
        "gap_pct": u.gap_pct, "verdict": u.verdict, "is_mock": u.is_mock,
        "models": [{"model": m.model, "intrinsic_value": m.intrinsic_value_per_share,
                    "available": m.available, "error": m.error,
                    "components": m.components, "assumptions": m.assumptions}
                   for m in u.models],
        "financial_summary": u.financial_summary, "params": u.params,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="005930")
    ap.add_argument("--price", type=float, default=70000.0,
                    help="시세를 못 얻을 때만 쓰는 폴백")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    rep = run(a.code, a.price)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"\n→ {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
