#!/usr/bin/env python3
"""백테스트 계측 하네스 — vNext 1차 감사 0단계.

★프로덕션 코드를 한 줄도 고치지 않는다★ 이 파일은 `src/` 를 **임포트만** 하고,
실행 형상을 밖에서 잰다. 마스터 프롬프트의 "가정하지 말고 증명하라" 를 따르기 위한
물건이므로, 재지 못한 것은 재지 못했다고 출력한다.

  python3 scripts/bench_backtest.py --suite small
  python3 scripts/bench_backtest.py --suite all --profile
  python3 scripts/bench_backtest.py --race          # 몽키패치 경쟁만

★이 환경의 한계를 출력에 박아 둔다★ 이 컨테이너는 Postgres 가 안 붙어 SQLite 로
폴백되고 `daily_prices` 가 없다. 따라서 커넥션 풀 경합(pool_size=5+overflow=10)과
실데이터 쿼리 시간은 **여기서 잴 수 없다**. 쿼리 '수' 는 셀 수 있고, 파이썬 핫루프·
메모리·스레드·단계 지연은 전부 잴 수 있다. 표마다 어느 쪽인지 라벨한다.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import resource
import sys
import threading
import time
import tracemalloc
from dataclasses import asdict, dataclass, field

os.environ.setdefault("KIS_USE_MOCK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# 규모 정의 — custom_tickers 로 유니버스 크기를 정확히 통제한다(스크리너 변동성 제거).
# ─────────────────────────────────────────────────────────────────────────────
SUITES: dict[str, dict] = {
    "small":  {"n_symbols": 20,  "start": "2023-01-01", "end": "2023-12-31"},
    "medium": {"n_symbols": 100, "start": "2021-01-01", "end": "2023-12-31"},
    "large":  {"n_symbols": 400, "start": "2017-01-01", "end": "2023-12-31"},
}


def _universe(n: int) -> list[str]:
    """실 종목코드 n개. 프리셋에서 뽑고 모자라면 있는 만큼만 쓴다(지어내지 않는다)."""
    from src.engine.screener import UNIVERSE_PRESETS
    pool: list[str] = []
    for key in ("kospi200", "kospi50", "kosdaq150"):
        for c in UNIVERSE_PRESETS.get(key, []):
            if c not in pool:
                pool.append(c)
    return pool[:n]


def _make_request(n_symbols: int, start: str, end: str, strategy: str = "GoldenCross"):
    from src.api.screener_routes import ScreenToBacktestRequest
    tickers = _universe(n_symbols)
    return ScreenToBacktestRequest(
        custom_tickers=tickers,
        filter_ast={"logic": "AND", "conditions": [], "groups": []},
        strategy_name=strategy,
        start_date=start, end_date=end,
        max_tickers=min(30, max(1, n_symbols // 4)),
        max_positions=min(20, max(1, n_symbols // 4)),
        universe_eval_cap=max(1, n_symbols),
        replenishment_pool_cap=0,
    ), tickers


# ─────────────────────────────────────────────────────────────────────────────
# 계측
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Measure:
    label: str
    n_symbols: int
    trading_days: int | None = None
    wall_s: float = 0.0
    cpu_s: float = 0.0
    cpu_util_pct: float = 0.0
    peak_traced_mb: float = 0.0
    rss_delta_mb: float = 0.0
    max_threads: int = 0
    db_queries: int = 0
    payload_bytes: int = 0
    phases: dict[str, float] = field(default_factory=dict)
    error: str | None = None


class _QueryCounter:
    """SQLAlchemy 커서 실행 횟수. ★시간이 아니라 '수'만 신뢰한다★ — SQLite 위에서 잰
    시간은 Postgres 를 말해 주지 않는다."""

    def __init__(self):
        self.n = 0
        self._engine = None

    def __enter__(self):
        try:
            from sqlalchemy import event

            from src.database import get_engine
            self._engine = get_engine()

            def _on(conn, cursor, statement, params, context, executemany):
                self.n += 1

            event.listen(self._engine, "before_cursor_execute", _on)
            self._on = _on
        except Exception:
            self._engine = None
        return self

    def __exit__(self, *a):
        if self._engine is not None:
            try:
                from sqlalchemy import event
                event.remove(self._engine, "before_cursor_execute", self._on)
            except Exception:
                pass
        return False


class _ThreadWatch:
    """활성 스레드 최대치 — '실행당 daemon 1개 + 로더 10개' 가 실제로 몇 개가 되는지."""

    def __init__(self, hz: float = 50.0):
        self.max_threads = 0
        self._stop = threading.Event()
        self._t = None
        self._dt = 1.0 / hz

    def __enter__(self):
        def loop():
            while not self._stop.is_set():
                self.max_threads = max(self.max_threads, threading.active_count())
                time.sleep(self._dt)
        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)
        return False


def _rss_mb() -> float:
    # Linux ru_maxrss 는 KiB
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def run_one(label: str, n_symbols: int, start: str, end: str,
            profile: bool = False, strategy: str = "GoldenCross") -> Measure:
    from src.api.screener_routes import _screen_to_backtest_core

    req, tickers = _make_request(n_symbols, start, end, strategy)
    m = Measure(label=label, n_symbols=len(tickers))

    phase_first: dict[str, float] = {}
    t0 = time.perf_counter()

    def cb(evt: dict) -> None:
        ph = evt.get("phase")
        if ph and ph not in phase_first:
            phase_first[ph] = time.perf_counter() - t0
        if ph == "simulating" and evt.get("total"):
            m.trading_days = evt["total"]

    rss0 = _rss_mb()
    tracemalloc.start()
    cpu0 = time.process_time()

    prof = cProfile.Profile() if profile else None
    try:
        with _QueryCounter() as qc, _ThreadWatch() as tw:
            if prof:
                prof.enable()
            result = _screen_to_backtest_core(req, progress_cb=cb)
            if prof:
                prof.disable()
            m.db_queries = qc.n
            m.max_threads = tw.max_threads
        m.payload_bytes = len(json.dumps(result, default=str))
        if isinstance(result, dict) and result.get("error"):
            m.error = str(result.get("message"))[:200]
    except Exception as e:  # 하네스는 실패도 정직하게 기록한다
        if prof:
            prof.disable()
        m.error = f"{type(e).__name__}: {e}"[:200]

    m.cpu_s = time.process_time() - cpu0
    m.wall_s = time.perf_counter() - t0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    m.peak_traced_mb = peak / 1024 / 1024
    m.rss_delta_mb = _rss_mb() - rss0
    m.cpu_util_pct = (m.cpu_s / m.wall_s * 100) if m.wall_s > 0 else 0.0

    # 단계 경계 → 구간 소요
    order = ["screening", "screened", "loading", "simulating", "done"]
    seen = [(p, phase_first[p]) for p in order if p in phase_first]
    for i, (p, t) in enumerate(seen):
        nxt = seen[i + 1][1] if i + 1 < len(seen) else m.wall_s
        m.phases[p] = round(nxt - t, 3)

    if prof:
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(30)
        print(f"\n──── cProfile 상위 30 ({label}) ────\n{s.getvalue()}")
    return m


# ─────────────────────────────────────────────────────────────────────────────
# ★몽키패치 경쟁 — 이 단계에서 가장 중요한 계측★
#
# `_generate_signal_as_of`(kis_backtest_engine.py:675) 는 모듈 전역
# `fetcher.get_daily_prices` 를 패치하고 finally 에서 되돌린다. 되돌릴 값은
# 진입 시점의 전역이다(:677). 두 스레드가 겹치면 A 가 **B 의 람다를 '원본'으로
# 저장**하고 그걸 복원한다 → 두 실행이 다 끝난 뒤에도 전역이 원본이 아니다.
#
# 이건 확률적 관찰이 아니라 **끝난 뒤 한 번 비교하면 끝나는 결정적 증거**다.
# ─────────────────────────────────────────────────────────────────────────────
def race_probe(n_symbols: int = 30, start: str = "2023-01-01",
               end: str = "2023-06-30", n_runs: int = 2) -> dict:
    import src.kis_data_fetcher as fetcher
    from src.api.screener_routes import _screen_to_backtest_core

    pristine_daily = fetcher.get_daily_prices
    pristine_price = fetcher.get_current_price

    observed_tickers: set[str] = set()
    patched_samples = 0
    total_samples = 0
    stop = threading.Event()

    def watcher():
        nonlocal patched_samples, total_samples
        while not stop.is_set():
            total_samples += 1
            fn = fetcher.get_daily_prices
            if fn is not pristine_daily:
                patched_samples += 1
                try:
                    df = fn()
                    tk = (getattr(df, "attrs", {}) or {}).get("ticker")
                    if tk:
                        observed_tickers.add(str(tk))
                except Exception:
                    pass
            time.sleep(0.0005)

    # 실행마다 서로 겹치지 않는 종목 집합 — 관측된 티커가 어느 실행 것인지 가른다.
    pool = _universe(n_symbols * n_runs)
    groups = [pool[i * n_symbols:(i + 1) * n_symbols] for i in range(n_runs)]
    groups = [g for g in groups if g]

    from src.api.screener_routes import ScreenToBacktestRequest

    def make(tks):
        return ScreenToBacktestRequest(
            custom_tickers=tks,
            filter_ast={"logic": "AND", "conditions": [], "groups": []},
            strategy_name="GoldenCross",
            start_date=start, end_date=end,
            max_tickers=10, max_positions=10,
            universe_eval_cap=len(tks), replenishment_pool_cap=0,
        )

    errors: list[str] = []

    def worker(tks):
        try:
            _screen_to_backtest_core(make(tks))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}"[:160])

    w = threading.Thread(target=watcher, daemon=True)
    w.start()
    threads = [threading.Thread(target=worker, args=(g,), daemon=True) for g in groups]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    w.join(timeout=2)
    wall = time.perf_counter() - t0

    leaked_daily = fetcher.get_daily_prices is not pristine_daily
    leaked_price = fetcher.get_current_price is not pristine_price
    # 복구 — 하네스가 프로세스를 오염시킨 채 끝나지 않게.
    fetcher.get_daily_prices = pristine_daily
    fetcher.get_current_price = pristine_price

    cross = {}
    for i, g in enumerate(groups):
        hit = observed_tickers & set(g)
        if hit:
            cross[f"run{i}"] = sorted(hit)[:5]

    return {
        "n_concurrent_runs": len(groups),
        "wall_s": round(wall, 2),
        "samples": total_samples,
        "samples_while_patched": patched_samples,
        "distinct_tickers_seen_on_global": len(observed_tickers),
        "tickers_by_run": cross,
        "runs_whose_data_appeared_on_shared_global": len(cross),
        "GLOBAL_LEAKED_AFTER_ALL_RUNS_FINISHED": leaked_daily or leaked_price,
        "leaked_get_daily_prices": leaked_daily,
        "leaked_get_current_price": leaked_price,
        "engine_errors": errors,
    }


def stress(concurrency: list[int], n_symbols: int, start: str, end: str) -> list[dict]:
    """동시 실행 처리량 — 스레드가 늘수록 총 처리량이 어떻게 되는가."""
    from src.api.screener_routes import _screen_to_backtest_core
    out = []
    for c in concurrency:
        reqs = [_make_request(n_symbols, start, end)[0] for _ in range(c)]
        errs: list[str] = []

        def run(r):
            try:
                _screen_to_backtest_core(r)
            except Exception as e:
                errs.append(f"{type(e).__name__}: {e}"[:120])

        with _ThreadWatch() as tw:
            cpu0 = time.process_time()
            t0 = time.perf_counter()
            ths = [threading.Thread(target=run, args=(r,), daemon=True) for r in reqs]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            wall = time.perf_counter() - t0
            cpu = time.process_time() - cpu0
        out.append({
            "concurrency": c, "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
            "cpu_util_pct": round(cpu / wall * 100, 1) if wall > 0 else 0.0,
            "sec_per_run": round(wall / c, 2), "max_threads": tw.max_threads,
            "errors": errs[:3],
        })
    return out


def _env_note() -> dict:
    from src.database import get_engine
    e = get_engine()
    daily_prices = None
    try:
        from sqlalchemy import text
        with e.connect() as c:
            daily_prices = c.execute(text("SELECT COUNT(*) FROM daily_prices")).scalar()
    except Exception:
        daily_prices = None
    return {
        "db_dialect": e.dialect.name,
        "daily_prices_rows": daily_prices,
        "KIS_USE_MOCK": os.getenv("KIS_USE_MOCK"),
        "cpu_count": os.cpu_count(),
        "caveat": ("SQLite 폴백 + daily_prices 부재 → 커넥션 풀 경합과 실데이터 쿼리 "
                   "시간은 잴 수 없다. 쿼리 '수'·파이썬 핫루프·메모리·스레드·단계 지연만 유효."
                   if e.dialect.name != "postgresql" or not daily_prices else "실 DB 형상"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="small",
                    choices=[*SUITES.keys(), "all", "none"])
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--race", action="store_true", help="몽키패치 경쟁만 측정")
    ap.add_argument("--stress", default="", help="예: 1,2,4")
    ap.add_argument("--json", default="", help="결과를 이 경로에 JSON 으로")
    a = ap.parse_args()

    report: dict = {"env": _env_note(), "measures": [], "stress": [], "race": None}
    print("═══ 환경 ═══")
    print(json.dumps(report["env"], ensure_ascii=False, indent=2))

    if a.race:
        print("\n═══ 몽키패치 경쟁 프로브 ═══")
        report["race"] = race_probe()
        print(json.dumps(report["race"], ensure_ascii=False, indent=2))

    names = list(SUITES) if a.suite == "all" else ([] if a.suite == "none" else [a.suite])
    for name in names:
        cfg = SUITES[name]
        print(f"\n═══ {name} ═══")
        m = run_one(name, cfg["n_symbols"], cfg["start"], cfg["end"], profile=a.profile)
        report["measures"].append(asdict(m))
        print(json.dumps(asdict(m), ensure_ascii=False, indent=2))

    if a.stress:
        cs = [int(x) for x in a.stress.split(",") if x.strip()]
        print(f"\n═══ 동시 실행 {cs} ═══")
        report["stress"] = stress(cs, 20, "2023-01-01", "2023-12-31")
        print(json.dumps(report["stress"], ensure_ascii=False, indent=2))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n→ {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
