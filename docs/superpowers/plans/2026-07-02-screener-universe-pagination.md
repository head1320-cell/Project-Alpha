# 스크리너 유니버스 실수치화 + 숫자 정직화 + 100행 페이지네이션 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 유니버스가 KRX 실제 상장 수에 도달하도록(그룹 확장 + 적재 가시화) 만들고, 헤더 숫자를 정직하게 재구성하며, 가상 스크롤을 100행/페이지 페이지네이션으로 교체한다.

**Architecture:** 백엔드는 KIS 마스터 그룹코드 포함 범위를 ST→(ST·RT·FS·MF·IF·SC·DR)로 넓히고, `/universes`와 스크리너 응답에 마스터 기준 실크기·적재 수·실평가 수·상한 발동 여부를 추가한다(기존 필드 유지 = 하위호환). 프론트는 유동성 게이트를 기본 OFF 토글로 바꾸고, 헤더를 "유니버스 M · 적재 A · 평가 E"로 재구성하며, 윈도잉 렌더를 클라이언트 페이지네이션으로 대체한다.

**Tech Stack:** FastAPI + pytest(mock: `KIS_USE_MOCK=1`), Next.js 14 + TypeScript. 스펙: `docs/superpowers/specs/2026-07-02-screener-universe-pagination-design.md`

**커밋 트레일러(모든 커밋 필수):**
```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA
```

**전역 규칙:** 브랜치 `claude/keen-thompson-bdk3e8` 외 푸시 금지. 백엔드 테스트는 항상 `KIS_USE_MOCK=1` 접두. 베이스라인 657 passed / 10 skipped 유지(회귀 금지).

---

### Task 1: 유니버스 그룹 확장 + master_composition (백엔드, TDD)

**Files:**
- Modify: `src/data/stock_master.py` (build_master_universe ≈455-490, 상수는 `_MASTER_FLAGS` 선언부 근처 ≈371)
- Test: `tests/test_universe_groups.py` (신규)

- [ ] **Step 1: Write the failing test**

`tests/test_universe_groups.py` 생성:

```python
"""유니버스 그룹 확장 — KRX 공식 상장 수 대응 (ST 외 리츠·외국주 등 포함, ETF/ETN/ELW 제외)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.stock_master as sm  # noqa: E402

SYMS = [
    {"ticker": "100001", "name": "코스피보통주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100002", "name": "코스피우선주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100003", "name": "코스피리츠",   "market": "KOSPI", "group_code": "RT"},
    {"ticker": "100004", "name": "코스피외국주", "market": "KOSPI", "group_code": "FS"},
    {"ticker": "100005", "name": "코스피ETF",   "market": "KOSPI", "group_code": "EF", "is_etf": True},
    {"ticker": "100006", "name": "코스피ETN",   "market": "KOSPI", "group_code": "EN"},
    {"ticker": "200001", "name": "코스닥주권",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200002", "name": "코스닥스팩",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200003", "name": "코스닥ELW",   "market": "KOSDAQ", "group_code": "EW"},
]


def _inject(monkeypatch, tmp_path):
    """합성 마스터 플래그 주입 — 파일 경로/전역 캐시를 임시로 대체."""
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "flags.json"))
    sm.save_master_flags(SYMS)
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)  # 지연 로드 강제


def test_kospi_includes_reits_and_foreign(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    u = set(sm.build_master_universe("kospi"))
    assert u == {"100001", "100002", "100003", "100004"}  # RT/FS 포함, EF/EN 제외


def test_kosdaq_and_all_listed(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    assert set(sm.build_master_universe("kosdaq")) == {"200001", "200002"}
    assert len(sm.build_master_universe("all_listed")) == 6  # 2시장 합, ETF/ETN/ELW 제외


def test_etf_universe_unchanged(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    assert set(sm.build_master_universe("etf")) == {"100005", "100006"}


def test_master_composition(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    comp = sm.master_composition()
    assert comp["KOSPI"] == {"ST": 2, "RT": 1, "FS": 1, "EF": 1, "EN": 1}
    assert comp["KOSDAQ"] == {"ST": 2, "EW": 1}


def test_composition_empty_without_master(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)
    assert sm.master_composition() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_universe_groups.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'master_composition'` 및 kospi 유니버스에 RT/FS 미포함 assert 실패.

- [ ] **Step 3: Write minimal implementation**

`src/data/stock_master.py` — `_MASTER_FLAGS` 선언(≈371) 근처에 상수 추가:

```python
# KRX 공식 상장 수 대응 유니버스 포함 그룹 (파생·펀드형 제외 — EF/EN/EW/SW/SR 등)
#   ST 주권(보통·우선) · RT 리츠 · FS 외국주권 · MF 투자회사 · IF 인프라투융자 · SC 선박투자 · DR 예탁증서
UNIVERSE_GROUP_CODES: tuple[str, ...] = ("ST", "RT", "FS", "MF", "IF", "SC", "DR")
```

`build_master_universe`의 세 분기 교체 (kospi200/kosdaq150/_topn/etf 분기는 그대로):

```python
    if kind == "kospi":
        return [c for c, f in items if mkt(f) == "KOSPI" and grp(f) in UNIVERSE_GROUP_CODES]
    if kind == "kosdaq":
        return [c for c, f in items if mkt(f) == "KOSDAQ" and grp(f) in UNIVERSE_GROUP_CODES]
    if kind in ("all", "all_listed"):
        return [c for c, f in items if grp(f) in UNIVERSE_GROUP_CODES]
```

`build_master_universe` 함수 바로 아래에 신규 함수:

```python
def master_composition() -> dict:
    """시장별×그룹코드별 종목 수 — KRX 공식 상장 수와의 잔차 원인 확인용(정직 리포트)."""
    flags = load_master_flags()
    out: dict[str, dict[str, int]] = {}
    for _c, f in flags.items():
        m = (f.get("market") or "?").upper()
        g = f.get("group_code") or "?"
        out.setdefault(m, {})
        out[m][g] = out[m].get(g, 0) + 1
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_universe_groups.py -q`
Expected: 5 passed.

- [ ] **Step 5: Regression + lint**

Run: `KIS_USE_MOCK=1 python -m pytest tests/ -q 2>&1 | tail -3 && ruff check src/data/stock_master.py tests/test_universe_groups.py`
Expected: 662 passed / 10 skipped (657+5), ruff All checks passed. (마스터 미적재 샌드박스에선 기존 경로가 프리셋 폴백이므로 기존 테스트 무영향.)

- [ ] **Step 6: Commit**

```bash
git add src/data/stock_master.py tests/test_universe_groups.py
git commit -m "feat(universe): KRX 공식 수 대응 그룹 확장(ST+RT+FS 등) + master_composition"
```
(트레일러 포함 — 이하 모든 커밋 동일.)

---

### Task 2: master-aware `/universes` (백엔드, TDD)

**Files:**
- Modify: `src/api/screener_routes.py` (`screener_universes` ≈180-205)
- Test: `tests/test_universes_endpoint.py` (신규)

- [ ] **Step 1: Write the failing test**

`tests/test_universes_endpoint.py` 생성:

```python
"""GET /universes — 마스터 적재 시 실크기, 미적재 시 프리셋 폴백 (199/130 분모 버그 수정 검증)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.stock_master as sm  # noqa: E402
from src.api.screener_routes import screener_universes  # noqa: E402

# 합성 마스터 (test_universe_groups.py와 동일 데이터 — 테스트 파일 간 import 없이 자립)
SYMS = [
    {"ticker": "100001", "name": "코스피보통주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100002", "name": "코스피우선주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100003", "name": "코스피리츠",   "market": "KOSPI", "group_code": "RT"},
    {"ticker": "100004", "name": "코스피외국주", "market": "KOSPI", "group_code": "FS"},
    {"ticker": "100005", "name": "코스피ETF",   "market": "KOSPI", "group_code": "EF", "is_etf": True},
    {"ticker": "100006", "name": "코스피ETN",   "market": "KOSPI", "group_code": "EN"},
    {"ticker": "200001", "name": "코스닥주권",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200002", "name": "코스닥스팩",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200003", "name": "코스닥ELW",   "market": "KOSDAQ", "group_code": "EW"},
]


def _inject(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "flags.json"))
    sm.save_master_flags(SYMS)
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)


def _sizes() -> dict:
    d = screener_universes()
    return {p["id"]: p["size"] for p in d["presets"]}


def test_fallback_to_presets_without_master(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)
    sizes = _sizes()
    assert sizes["kospi200"] == 130          # 하드코딩 프리셋 폴백 (샌드박스 = 마스터 없음)
    assert "kospi" not in sizes             # 마스터 없으면 시장 전체 항목 미노출


def test_master_aware_sizes(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    sizes = _sizes()
    assert sizes["kospi"] == 4               # ST2+RT1+FS1 (합성 마스터)
    assert sizes["kosdaq"] == 2
    assert sizes["all_listed"] == 6
    assert sizes["etf"] == 2                 # EF+EN — 프리셋 40 대신 마스터 실크기
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_universes_endpoint.py -q`
Expected: FAIL — `sizes["kospi"]` KeyError (현재 /universes는 UNIVERSE_PRESETS 5종만 반환).

- [ ] **Step 3: Write implementation**

`screener_universes()`의 `presets` 구성부를 교체 (`filter_dimensions` 이하 반환 필드는 그대로 유지):

```python
@router.get("/universes")
def screener_universes():
    """사용 가능한 universe 카탈로그 — 마스터 적재 시 실제 크기, 미적재 시 프리셋 폴백."""
    try:
        from src.engine.screener import UNIVERSE_PRESETS
        sizes = {k: len(v) for k, v in UNIVERSE_PRESETS.items()}
        samples = {k: v[:5] for k, v in UNIVERSE_PRESETS.items()}
        try:
            from src.data.stock_master import build_master_universe, load_master_flags
            if load_master_flags():
                for kind in ("kospi", "kosdaq", "kospi200", "kosdaq150", "etf", "all_listed"):
                    u = build_master_universe(kind)
                    if u:
                        sizes[kind] = len(u)
                        samples[kind] = u[:5]
        except Exception:
            pass
        return {
            "presets": [
                {"id": k, "size": sizes[k], "sample": samples.get(k, [])}
                for k in sizes
            ],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_universes_endpoint.py tests/test_universe_groups.py -q`
Expected: 7 passed.

- [ ] **Step 5: Regression + lint + commit**

Run: `KIS_USE_MOCK=1 python -m pytest tests/ -q 2>&1 | tail -3 && ruff check src/api/screener_routes.py tests/test_universes_endpoint.py`
Expected: 664 passed / 10 skipped, ruff 통과.

```bash
git add src/api/screener_routes.py tests/test_universes_endpoint.py
git commit -m "fix(screener): /universes 크기를 마스터 기준 실시간으로 — 199/130 분모 버그 해소"
```

---

### Task 3: 정직 카운터 — ScreenerResult + 응답 필드 (백엔드, TDD)

**Files:**
- Modify: `src/engine/screener.py` (ScreenerResult ≈235-246, `run()` ≈456-570, `_resolve_universe` ≈864-880, `__init__`에 `_universe_meta` 초기화)
- Modify: `src/api/screener_routes.py` (`_run_advanced_core` 반환 ≈475-488)
- Test: `tests/test_screener_honest_counts.py` (신규)

- [ ] **Step 1: Write the failing test**

`tests/test_screener_honest_counts.py` 생성:

```python
"""정직 카운터 — universe_size(유니버스 총원) / ingested_count / evaluated_actual(실평가) / capped(상한 발동)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.screener import ValuationScreener  # noqa: E402


def test_universe_size_and_evaluated_actual():
    sc = ValuationScreener()
    r = sc.run(universe="kospi50", filter_ast=None, liquidity_floor="off", limit=100)
    assert r.universe_size == 50                    # 프리셋 총원
    assert r.evaluated_actual == 50 - r.failures    # 실제 산출 아이템 수(게이트 전)
    assert r.capped is False
    assert r.total_passed == r.evaluated_actual     # 게이트 off + 무필터 → 표시==평가


def test_capped_flag_when_over_live_compute(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_LIVE_COMPUTE", "10")
    sc = ValuationScreener()
    codes = [f"90{i:04d}" for i in range(30)]       # 합성 30종목 (mock 결정론 평가)
    r = sc.run(universe=codes, filter_ast=None, liquidity_floor="off", limit=100)
    assert r.universe_size == 30
    assert r.capped is True
    assert r.evaluated_actual <= 10                 # 상한만큼만 실평가


def test_gate_on_reduces_passed_not_evaluated():
    sc = ValuationScreener()
    r = sc.run(universe="kospi50", filter_ast=None, liquidity_floor="relaxed", limit=100)
    assert r.evaluated_actual == 50 - r.failures    # 평가는 게이트와 무관
    assert r.total_passed <= r.evaluated_actual     # 게이트가 표시만 줄임
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_screener_honest_counts.py -q`
Expected: FAIL — `AttributeError: 'ScreenerResult' object has no attribute 'universe_size'`.

- [ ] **Step 3: Implement — ScreenerResult 필드**

`src/engine/screener.py` ScreenerResult(≈235)에 기본값 필드 4개 추가 (timestamp 위):

```python
@dataclass
class ScreenerResult:
    """스크리닝 전체 결과."""
    universe:           str
    total_evaluated:    int
    total_passed:       int
    items:              list[ScreenerItem]
    elapsed_seconds:    float
    cache_hits:         int
    cache_misses:       int
    failures:           int
    universe_size:      int = 0      # 마스터/프리셋 기준 유니버스 총원 (적재 교집합 前)
    ingested_count:     int = 0      # 유니버스 중 스냅샷 적재 종목 수
    evaluated_actual:   int = 0      # 실제 산출 아이템 수 (복원+평가 성공, 게이트 前)
    capped:             bool = False # SCREENER_MAX_LIVE_COMPUTE 상한 발동 여부
    timestamp:          str = field(default_factory=lambda: datetime.now().isoformat())
```

- [ ] **Step 4: Implement — `_resolve_universe` 메타 수집 (ingested_codes 1회 조회로 통합)**

`_resolve_universe`(≈864-880) 전체 교체:

```python
    def _resolve_universe(self, universe: str | list[str]) -> list[str]:
        if isinstance(universe, list):
            full = universe[:5000]  # 안전 제한 (관심그룹/커스텀)
        else:
            full = resolve_universe(universe)  # 마스터 멤버십(실 지수·시장·ETF) 또는 폴백
        # 적재 현황 (정직 카운터용) — 스냅샷 비활성/실패 시 None
        ing: set[str] | None = None
        try:
            from src.data.snapshot_db import enabled, ingested_codes
            if enabled():
                ing = set(ingested_codes())
        except Exception:
            ing = None
        self._universe_meta = {
            "universe_size": len(full),
            "ingested_count": sum(1 for c in full if c in ing) if ing is not None else 0,
        }
        # 대용량 유니버스(>250)는 적재 DB와 교집합 — 폭주방지·적재가 늘면 자동 확장
        if isinstance(universe, str) and len(full) > 250 and ing is not None:
            inter = [c for c in full if c in ing]
            return inter if inter else full[:250]  # 적재 전: 250개만(폭주 방지)
        return full
```

`ValuationScreener.__init__`(클래스 상단 — `self.cache` 초기화 근처)에 한 줄 추가:

```python
        self._universe_meta: dict = {"universe_size": 0, "ingested_count": 0}
```

- [ ] **Step 5: Implement — `run()`의 capped/evaluated_actual + 반환**

상한 절단부(≈474-477) 교체:

```python
        capped = False
        if not no_cap:
            import os
            max_eval = int(os.getenv("SCREENER_MAX_LIVE_COMPUTE", "400"))
            capped = len(to_eval) > max_eval
            to_eval = to_eval[:max_eval]
```

`cache_hits = ...` / `cache_misses = ...`(≈514-515) 직후, 게이트 적용 전에:

```python
        evaluated_actual = len(items)  # 복원+평가 성공분 (게이트 前) — 정직 평가 수
```

빈 유니버스 조기 반환(≈458-463)에 필드 추가:

```python
            return ScreenerResult(
                universe=str(universe), total_evaluated=0, total_passed=0,
                items=[], elapsed_seconds=0,
                cache_hits=0, cache_misses=0, failures=0,
                universe_size=self._universe_meta["universe_size"],
                ingested_count=self._universe_meta["ingested_count"],
            )
```

최종 반환(≈560-569)에 필드 추가:

```python
        return ScreenerResult(
            universe=str(universe) if isinstance(universe, str) else f"custom({len(tickers)})",
            total_evaluated=len(tickers),
            total_passed=len(filtered),
            items=filtered[:limit],
            elapsed_seconds=round(time.time() - start_ts, 3),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            failures=failures,
            universe_size=self._universe_meta["universe_size"],
            ingested_count=self._universe_meta["ingested_count"],
            evaluated_actual=evaluated_actual,
            capped=capped,
        )
```

- [ ] **Step 6: Implement — 응답 payload**

`src/api/screener_routes.py` `_run_advanced_core` 반환 dict(≈475-488)에 4필드 추가:

```python
        "failures":        result.failures,
        "universe_size":    result.universe_size,
        "ingested_count":   result.ingested_count,
        "evaluated_actual": result.evaluated_actual,
        "capped":           result.capped,
        "timestamp":       result.timestamp,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_screener_honest_counts.py -q`
Expected: 3 passed.

- [ ] **Step 8: Regression + lint + commit**

Run: `KIS_USE_MOCK=1 python -m pytest tests/ -q 2>&1 | tail -3 && ruff check src/engine/screener.py src/api/screener_routes.py tests/test_screener_honest_counts.py`
Expected: 667 passed / 10 skipped, ruff 통과. (기존 필드/동작 불변 — 신규 키만 추가.)

```bash
git add src/engine/screener.py src/api/screener_routes.py tests/test_screener_honest_counts.py
git commit -m "feat(screener): 정직 카운터 — universe_size/ingested_count/evaluated_actual/capped"
```

---

### Task 4: db-status 유니버스 적재 진행 + Data Infra 표시 (백엔드+프론트, TDD)

**Files:**
- Modify: `main_api.py` (`db_status` ≈468-500)
- Modify: `frontend/src/lib/api.ts` (dbStatus 타입 ≈115-122)
- Modify: `frontend/src/components/admin/DbStatusPanel.tsx` (TABLE COVERAGE 섹션 뒤, `SectionHead label="INGEST"` 앞 ≈154)
- Test: `tests/test_db_status_universe.py` (신규)

- [ ] **Step 1: Write the failing test**

`tests/test_db_status_universe.py` 생성:

```python
"""db-status universe_progress — 시장별 마스터 대비 적재 진행 (엔진 유무와 무관하게 키 존재)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from main_api import db_status  # noqa: E402


def test_universe_progress_key_present():
    out = db_status()
    up = out.get("universe_progress")
    assert isinstance(up, dict)
    assert "progress" in up and "composition" in up
    # 샌드박스(마스터 미적재): progress 는 빈 dict 이거나 master=0 항목 — 크래시 없이 정직
    for v in (up["progress"] or {}).values():
        assert set(v.keys()) == {"master", "ingested"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_db_status_universe.py -q`
Expected: FAIL — `universe_progress` None (키 없음).

- [ ] **Step 3: Implement — main_api.db_status**

`db_status()` 안 `out["config"] = {...}` 블록 직후에 추가:

```python
    # 유니버스 적재 진행 — 마스터(전 상장) 대비 factor_snapshot 적재 수 (스크리너 유니버스 크기의 근거)
    def _universe_progress() -> dict:
        try:
            from src.data.snapshot_db import enabled as _sn_en
            from src.data.snapshot_db import ingested_codes
            from src.data.stock_master import build_master_universe, master_composition
            ing = set(ingested_codes()) if _sn_en() else set()
            prog = {}
            for k in ("kospi", "kosdaq", "etf", "all_listed"):
                m = build_master_universe(k)
                if m:
                    prog[k] = {"master": len(m), "ingested": sum(1 for c in m if c in ing)}
            return {"progress": prog, "composition": master_composition()}
        except Exception:
            return {"progress": {}, "composition": {}}

    out["universe_progress"] = _universe_progress()
```

- [ ] **Step 4: Run backend test**

Run: `KIS_USE_MOCK=1 python -m pytest tests/test_db_status_universe.py -q`
Expected: 1 passed.

- [ ] **Step 5: Implement — 프론트 타입 + Data Infra 섹션**

`frontend/src/lib/api.ts` dbStatus 반환 타입(≈115-122)에 필드 추가:

```typescript
  dbStatus: () =>
    get<{
      available: boolean;
      config: Record<string, boolean>;
      tables: Record<string, Record<string, number | string | null>>;
      tools: Record<string, boolean>;
      ingest_running: Record<string, boolean>;
      universe_progress?: {
        progress: Record<string, { master: number; ingested: number }>;
        composition: Record<string, Record<string, number>>;
      };
    }>("/api/v1/data/db-status"),
```

`DbStatusPanel.tsx` — TABLE COVERAGE 테이블 닫힌 뒤, `<SectionHead label="INGEST"` 앞에 삽입:

```tsx
          {/* 유니버스 적재 진행 — 스크리너 유니버스가 마스터(전 상장) 대비 얼마나 채워졌는지 */}
          {st.universe_progress && Object.keys(st.universe_progress.progress ?? {}).length > 0 && (
            <>
              <SectionHead label="UNIVERSE COVERAGE" index="INGESTED / MASTER" />
              <table className="trisk-table">
                <thead>
                  <tr><th>유니버스</th><th className="num">마스터</th><th className="num">적재</th><th className="num">진행률</th></tr>
                </thead>
                <tbody>
                  {(["kospi", "kosdaq", "etf", "all_listed"] as const).map((k) => {
                    const p = st.universe_progress!.progress[k];
                    if (!p) return null;
                    const pct = p.master > 0 ? Math.round((p.ingested / p.master) * 100) : 0;
                    const label = { kospi: "KOSPI", kosdaq: "KOSDAQ", etf: "ETF", all_listed: "전체 (전종목)" }[k];
                    return (
                      <tr key={k}>
                        <td>{label}</td>
                        <td className="num">{p.master.toLocaleString()}</td>
                        <td className="num">{p.ingested.toLocaleString()}</td>
                        <td className="num" style={{ color: pct >= 100 ? "#16a34a" : pct >= 50 ? "var(--t-ink)" : "#dc2626" }}>{pct}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
```

- [ ] **Step 6: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit && cd ..`
Expected: 0 errors.

- [ ] **Step 7: Regression + commit**

Run: `KIS_USE_MOCK=1 python -m pytest tests/ -q 2>&1 | tail -3 && ruff check main_api.py tests/test_db_status_universe.py`
Expected: 668 passed / 10 skipped, ruff 통과.

```bash
git add main_api.py tests/test_db_status_universe.py frontend/src/lib/api.ts frontend/src/components/admin/DbStatusPanel.tsx
git commit -m "feat(data-infra): 유니버스 적재 진행(마스터 대비) — db-status + Data Infra 표시"
```

---

### Task 5: 유동성 게이트 기본 OFF 토글 + 정직 헤더 (프론트)

**Files:**
- Modify: `frontend/src/lib/screenerApi.ts` (ScreenerResponse ≈75-85)
- Modify: `frontend/src/components/screener/TerminalScreener.tsx` (state ≈100, 요청 3곳 ≈210/223/234, uniTotal ≈384, countbar ≈583-590, progress ≈608-614)
- Modify: `frontend/src/app/globals.css` (bsc- 스타일 근처)

- [ ] **Step 1: 타입 추가**

`screenerApi.ts` ScreenerResponse(≈75) 교체:

```typescript
export interface ScreenerResponse {
  universe: string;
  total_evaluated: number;
  total_passed: number;
  elapsed_seconds: number;
  cache_hits: number;
  cache_misses: number;
  failures: number;
  timestamp: string;
  items: ScreenerItem[];
  // 정직 카운터 (신규 — 옵셔널: 구버전 응답 호환)
  universe_size?: number;      // 마스터/프리셋 기준 유니버스 총원
  ingested_count?: number;     // 적재된 종목 수
  evaluated_actual?: number;   // 실제 산출 아이템 수 (게이트 전)
  capped?: boolean;            // 평가 상한(400) 발동
  liquidity_gate?: { before?: number; after?: number; filtered_out?: number };
}
```

- [ ] **Step 2: 게이트 토글 상태 + 요청 3곳 연결**

`TerminalScreener.tsx` state 영역(≈104 `mcapRange` 근처)에 추가:

```tsx
  // 유동성 게이트 — 기본 OFF (검색된 기업 == 평가 완료). ON 시 시총300억·거래대금3억·스프레드1% 필터
  const [gateOn, setGateOn] = useState(false);
```

3개 요청의 `liquidity_floor`를 모두 `gateOn ? "relaxed" : "off"`로 교체하고 각 effect deps에 `gateOn` 추가:
1. 메인 스트림(≈210): `{ universe, filter_ast: effectiveAst, sort_by: "composite_score", ascending: false, limit: 4000, liquidity_floor: gateOn ? "relaxed" : "off" }` — deps `[effectiveAst, universe, gateOn]`
2. 분포 표본(≈223): 동일 표현식 — deps `[universe, gateOn]`
3. 칩 카운트(≈234): 동일 표현식 — deps `[group, universe, gateOn]`

- [ ] **Step 3: uniTotal을 마스터 실크기 우선으로**

≈384 교체:

```tsx
  const uniTotal = results?.universe_size || universeSizes[universe] || results?.total_evaluated || 0;
```

- [ ] **Step 4: countbar에 게이트 토글**

≈584 `<span className="bsc-count">…` 바로 다음 줄에 추가:

```tsx
            <label className="bsc-gate-toggle" title="시가총액 300억↑ · 일평균 거래대금 3억↑ · 스프레드 1%↓ 종목만 포함">
              <input type="checkbox" checked={gateOn} onChange={(e) => setGateOn(e.target.checked)} />
              유동성 게이트
            </label>
```

- [ ] **Step 5: 정직 헤더 재구성**

`bsc-progress` 블록(≈608-614)의 results 분기 교체 + 아래 적재 힌트 추가:

```tsx
          <div className="bsc-progress">
            {loading
              ? <>데이터 확충 중… <b>{(prog?.done ?? 0).toLocaleString()}</b>/{(prog?.total ?? uniTotal).toLocaleString()} 종목 업데이트{prog && prog.misses > 0 ? ` · 신규 ${prog.misses.toLocaleString()}` : ""}</>
              : results
                ? <>
                    유니버스 <b>{uniTotal.toLocaleString()}</b>종목 · 적재 {(results.ingested_count ?? 0).toLocaleString()} · 평가 {(results.evaluated_actual ?? results.total_evaluated).toLocaleString()}
                    {gateOn && (results.liquidity_gate?.filtered_out ?? 0) > 0 ? <> · 유동성 제외 {(results.liquidity_gate?.filtered_out ?? 0).toLocaleString()}</> : null}
                    {" · 신규 "}{results.cache_misses.toLocaleString()} · 캐시 {results.cache_hits.toLocaleString()} · {results.elapsed_seconds.toFixed(2)}s
                    {results.capped ? <span className="bsc-capped-badge" title="미적재 종목이 많아 이번 실행에서 일부만 평가되었습니다. Data Infra에서 전체 적재를 실행하면 해소됩니다.">평가 상한 발동</span> : null}
                  </>
                : <>대기 중…</>}
          </div>

          {/* 적재 미완 안내 — 유니버스가 실제 상장 수보다 작게 보이는 이유를 명시 */}
          {results && !loading && (results.ingested_count ?? 0) < (results.universe_size ?? 0) && (
            <div className="bsc-ingest-hint">
              이 유니버스는 마스터 {(results.universe_size ?? 0).toLocaleString()}종목 중 <b>{(results.ingested_count ?? 0).toLocaleString()}</b>종목만 적재되어 있습니다 — Admin → Data Infra에서 <b>펀더멘털 적재</b>를 실행하면 전 종목으로 확장됩니다.
            </div>
          )}
```

주의: 이 시점에 기존 문구의 `` `· 가상 스크롤 …행` ``(windowing 참조)이 함께 제거됨 — `windowing` 변수 자체는 Task 6에서 정리.

- [ ] **Step 6: CSS**

`globals.css`의 `.bsc-progress` 정의 근처에 추가:

```css
.bsc-gate-toggle { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--t-muted); cursor: pointer; margin-left: 14px; }
.bsc-gate-toggle input { accent-color: var(--t-accent); }
.bsc-capped-badge { margin-left: 8px; padding: 1px 7px; border: 1px solid #f59e0b; color: #b45309; background: #fffbeb; border-radius: 2px; font-size: 10px; font-family: var(--t-mono); }
.bsc-ingest-hint { margin: 6px 0 10px; padding: 8px 12px; border: 1px dashed var(--t-border); background: var(--t-surface); color: var(--t-muted); font-size: 12px; border-radius: 2px; }
```

- [ ] **Step 7: Verify + commit**

Run: `cd frontend && npx tsc --noEmit && cd ..`
Expected: 0 errors.

```bash
git add frontend/src/lib/screenerApi.ts frontend/src/components/screener/TerminalScreener.tsx frontend/src/app/globals.css
git commit -m "feat(screener-ui): 유동성 게이트 기본 OFF 토글 + 정직 헤더(유니버스·적재·평가·제외·상한)"
```

---

### Task 6: 가상 스크롤 → 100행 페이지네이션 (프론트)

**Files:**
- Modify: `frontend/src/components/screener/TerminalScreener.tsx` (상수 ≈35-36, state ≈112-115, effect ≈241-248, 윈도잉 ≈389-395, 테이블 ≈621-644)
- Modify: `frontend/src/app/globals.css`

- [ ] **Step 1: 상수/상태 교체**

≈35-36의 두 상수 삭제:
```tsx
const ROW_H = 41;        // 가상 스크롤 행 높이(고정)
const WINDOW_MIN = 60;   // 결과가 이보다 많으면 윈도잉 활성
```
대신:
```tsx
const PAGE_SIZE = 100;   // 결과 테이블 페이지당 행 수
```

≈112-115의 가상 스크롤 state 교체 — `tableWrapRef`는 유지(페이지 전환 스크롤 리셋용), `scrollTop`/`viewH` 삭제:
```tsx
  // 결과 페이지네이션 (100행/페이지) — 렌더 행수 고정으로 렉 방지
  const tableWrapRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(0);
```

≈241-248의 "가상 스크롤 컨테이너 높이 측정" useEffect(ResizeObserver) 블록 전체 삭제.

- [ ] **Step 2: 윈도잉 → 페이지 계산**

≈389-395 (`// 가상 스크롤 윈도잉` ~ `topPad/botPad`) 블록 교체:

```tsx
  // 페이지네이션 계산 — 정렬/새 결과 시 1페이지로 리셋
  const pageCount = Math.max(1, Math.ceil(sortedItems.length / PAGE_SIZE));
  const curPage = Math.min(page, pageCount - 1);
  const pageItems = sortedItems.slice(curPage * PAGE_SIZE, (curPage + 1) * PAGE_SIZE);
  useEffect(() => { setPage(0); }, [results, sortCol, sortDir]);
  const gotoPage = (p: number) => {
    setPage(Math.max(0, Math.min(pageCount - 1, p)));
    tableWrapRef.current?.scrollTo({ top: 0 });
  };
  const pageNums = useMemo(() => {
    const out: (number | "…")[] = [];
    for (let i = 0; i < pageCount; i++) {
      if (i === 0 || i === pageCount - 1 || Math.abs(i - curPage) <= 2) out.push(i);
      else if (out[out.length - 1] !== "…") out.push("…");
    }
    return out;
  }, [pageCount, curPage]);
```

≈385의 `const colSpan = …` 은 패딩 행 제거 후 미사용이 되면 삭제 (`grep -n "colSpan" TerminalScreener.tsx`로 확인 후).

- [ ] **Step 3: 테이블 렌더 교체**

≈621 `bsc-table-wrap`의 `onScroll={…}` prop 삭제:
```tsx
          <div className="bsc-table-wrap" ref={tableWrapRef}>
```

tbody(≈637-641)의 패딩 행 2개 삭제, 본문 교체:
```tsx
              <tbody>
                {pageItems.map((it, vi) => renderRow(it, curPage * PAGE_SIZE + vi))}
              </tbody>
```

`</div>`(bsc-table-wrap 닫힘, ≈644) 바로 뒤에 페이지 바 추가:

```tsx
          {pageCount > 1 && (
            <div className="bsc-pager">
              <button onClick={() => gotoPage(curPage - 1)} disabled={curPage === 0}>◀ 이전</button>
              {pageNums.map((p, i) => p === "…"
                ? <span key={`e${i}`}>…</span>
                : <button key={p} className={p === curPage ? "on" : ""} onClick={() => gotoPage(p)}>{p + 1}</button>)}
              <button onClick={() => gotoPage(curPage + 1)} disabled={curPage >= pageCount - 1}>다음 ▶</button>
              <span className="bsc-pager-range">
                {(curPage * PAGE_SIZE + 1).toLocaleString()}–{Math.min(sortedItems.length, (curPage + 1) * PAGE_SIZE).toLocaleString()} / {sortedItems.length.toLocaleString()}
              </span>
            </div>
          )}
```

파일 상단 주석(≈7)의 "가상 스크롤" 언급을 "100행 페이지네이션"으로 갱신.

- [ ] **Step 4: CSS**

`globals.css`에 (Task 5 스타일 아래):

```css
.bsc-pager { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 12px 0 4px; font-family: var(--t-mono); font-size: 12px; }
.bsc-pager button { min-width: 30px; padding: 4px 8px; border: 1px solid var(--t-border); background: #fff; border-radius: 2px; cursor: pointer; font-family: var(--t-mono); font-size: 12px; color: var(--t-ink); }
.bsc-pager button:hover { border-color: var(--t-accent); color: var(--t-accent); }
.bsc-pager button.on { background: var(--t-accent); border-color: var(--t-accent); color: #fff; }
.bsc-pager button:disabled { opacity: 0.4; cursor: default; }
.bsc-pager .bsc-pager-range { margin-left: 10px; color: var(--t-muted); }
```

- [ ] **Step 5: Verify (tsc + build) + 미사용 잔재 확인**

Run: `cd frontend && npx tsc --noEmit && npx next build 2>&1 | tail -5 && cd ..`
Expected: 0 errors, build 성공(16/16).
Run: `grep -n "ROW_H\|WINDOW_MIN\|scrollTop\|viewH\|topPad\|botPad\|windowing" frontend/src/components/screener/TerminalScreener.tsx`
Expected: 매치 0건 (전부 제거됨).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/screener/TerminalScreener.tsx frontend/src/app/globals.css
git commit -m "feat(screener-ui): 가상 스크롤 → 100행 페이지네이션 (이전/다음·번호·범위 표시)"
```

---

### Task 7: 전체 검증 + 라이브 확인 + 푸시

**Files:**
- Modify: `CLAUDE.md` (세션 요약 블록 추가 — 프로젝트 관례)

- [ ] **Step 1: 백엔드 전체 회귀**

Run: `KIS_USE_MOCK=1 python -m pytest tests/ -q 2>&1 | tail -3 && ruff check .`
Expected: 668 passed / 10 skipped / 0 failed (657+11 신규), ruff All checks passed.

- [ ] **Step 2: 프론트 전체**

Run: `cd frontend && npx tsc --noEmit && npx next build 2>&1 | tail -5 && cd ..`
Expected: 0 errors, 16/16 pages.

- [ ] **Step 3: mock 라이브 렌더 확인**

백엔드(`KIS_USE_MOCK=1 uvicorn main_api:app --port 8000`) + 프론트(`npx next start`) 기동 후 `/screener`에서:
- 헤더가 "유니버스 N종목 · 적재 · 평가 …" 형식으로 표시
- 유동성 게이트 토글 OFF 기본 → 검색된 기업 == 평가 수 확인, ON 시 "유동성 제외 N" 표시
- 결과 100행 초과 시 페이지 바(이전/다음/번호/범위) 동작
(렌더 실패 시 stale `.next` 의심: `pkill -9 node && rm -rf .next && npx next build`)

- [ ] **Step 4: CLAUDE.md 세션 요약 추가**

CLAUDE.md 말미에 이번 작업 요약 블록(유니버스 그룹 확장 / 정직 카운터 / 게이트 토글 / 페이지네이션 / GCP 적재 런북) 추가.

- [ ] **Step 5: Commit + push (재시도 백오프)**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 세션 요약 — 스크리너 유니버스 실수치화+페이지네이션"
git push -u origin claude/keen-thompson-bdk3e8
# 네트워크 실패 시 2s/4s/8s/16s 백오프로 최대 4회 재시도
```

- [ ] **Step 6: 사용자 GCP 런북 안내 (구현 완료 보고에 포함)**

배포 후: ① Admin → Data Infra → "펀더멘털" 적재 실행(수 시간, 재개 가능) ② UNIVERSE COVERAGE에서 KOSPI/KOSDAQ 적재가 마스터 크기까지 차오르는지 확인 ③ 스크리너 유니버스가 실수치(≈946/≈1,822/≈2,768) 도달 확인 ④ 잔차가 있으면 db-status의 `master_composition`(그룹별 종목 수)으로 원인 보고.
