"""난수를 쓰는 자리는 전부 등록돼 있고, ★합성 자리는 운영 게이트에서 한 번도 난수를 뽑지 않는다★ (2026-11-14)

등록부: `src/data/synthetic_registry.py` · 감사: `docs/specs/2026-11-14-synthetic-generation-audit.md`.

## 세 겹

① **정적 — 소스와 등록부가 같다.** 난수 기계를 가리키는 함수가 등록부에 없으면 실패한다(새 자리 검출).
   등록부에 있는데 소스에 없으면 실패한다(낡은 등록 검출). 스캐너 자체는 심은 파일로 시험한다.
② **동적 — 자리마다 직접 부른다.** 합성 자리마다 '문'(그 자리로 가는 공개 진입점)을 하나씩 두고,
   운영 게이트에서 부르면 어떤 합성 자리도 난수를 뽑지 않고, mock 게이트에서 부르면 바로 그 자리가 뽑는다(짝 — 문이 진짜 그 자리로 간다는 증거).
③ **동적 — GET 라우트를 훑는다.** 재는 도구(`scripts/probe_synthetic_draws.py`)를 하위 프로세스로 돌린다.
   문이 놓친 경로(라우트 → 스토어 → 다른 스토어)를 잡는다 — 감사 때의 재무 원천 누수가 이 모양이었다.

## ★이 시험이 말하지 않는 것★

- "운영에 합성값이 없다"는 증명이 아니다. ②는 등록된 문, ③은 훑은 GET 까지다(POST·웹소켓·인자가 더 필요한 경로는 문으로만 본다).
- 난수 없이 해시·상수로 만든 값은 스캐너가 못 본다. 실데이터가 정확한지는 전혀 다른 물음이다.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from src.data.synthetic_registry import (  # noqa: E402
    KINDS,
    PRIMITIVE,
    SIMULATION,
    SITES,
    SYNTHETIC,
    UNREFERENCED,
    keys_of,
)
from synthetic_scan import ROOT, importers_of, install_tripwire, scan_file, scan_sources  # noqa: E402

CODE = "005930"


# ══ ① 정적 — 소스와 등록부 ════════════════════════════════════════════════════

def test_every_function_that_names_a_random_generator_is_registered():
    """새 함수가 난수를 쓰면 여기서 멈춘다 — 계산(simulation)인지 합성(synthetic)인지 정하고 등록한다."""
    missing = sorted(set(scan_sources()) - set(SITES))
    assert missing == [], ("등록부에 없는 자리 — `src/data/synthetic_registry.py` 에 분류해 적으십시오. "
                           f"합성 데이터라면 mock 게이트 뒤에 두고 이 파일의 DOORS 에 문을 더합니다: {missing}")


def test_the_registry_has_no_entry_the_source_no_longer_has():
    stale = sorted(set(SITES) - set(scan_sources()))
    assert stale == [], f"소스에 없는 등록 — 함수가 사라졌거나 이름이 바뀌었다: {stale}"


def test_every_entry_says_what_and_synthetic_entries_say_what_prod_gets_instead():
    for key, site in SITES.items():
        assert site.kind in KINDS, key
        assert site.what.strip(), f"{key}: 무엇을 만드는지 비어 있다"
        if site.kind == SYNTHETIC:
            assert site.prod and site.prod.strip(), f"{key}: 운영에서 대신 나가는 것이 비어 있다"
        else:
            assert site.prod is None, f"{key}: `prod` 는 합성 자리에만 쓴다"


def test_the_vocabulary_is_all_in_use():
    """쓰지 않는 분류가 생기면 어휘에서 지운다 — 빈 분류는 '있는 줄 아는' 구멍이 된다."""
    assert {s.kind for s in SITES.values()} == set(KINDS)


_PLANTED = '''
import random as rnd
import numpy as np
from random import gauss
from numpy.random import default_rng

TABLE = [rnd.random() for _ in range(3)]

def plain():
    return 1 + 1

def uses_module():
    return rnd.Random(7).random()

def uses_numpy(n):
    return np.random.normal(0, 1, n)

def uses_from_import():
    return gauss(0, 1) + default_rng(1).random()

def seeds_torch(torch):
    torch.manual_seed(3)

class Store:
    def build(self, code):
        return self._uniform(code, "x")
    def clean(self, code):
        return len(code)

def outer():
    def inner():
        return rnd.choice([1, 2])
    return inner()
'''


def test_the_scanner_finds_each_idiom_in_a_planted_file(tmp_path):
    """★스캐너가 아무것도 못 찾아도 '등록부와 같다'는 통과한다★ — 스캐너가 실제로 찾는지 따로 본다."""
    f = tmp_path / "planted.py"
    f.write_text(_PLANTED, encoding="utf-8")
    found = scan_file(f)
    assert set(found) == {"<module>", "uses_module", "uses_numpy", "uses_from_import", "seeds_torch",
                          "Store.build", "outer.inner"}
    assert "plain" not in found and "Store.clean" not in found and "outer" not in found
    assert found["uses_numpy"] == ["np.random.normal"] and found["Store.build"] == ["self._uniform"]


def test_a_planted_unregistered_site_is_reported(tmp_path):
    """등록부 대조가 진짜 대조인지 — 가짜 저장소에 자리 하나를 심으면 '없는 자리'로 나와야 한다."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "leak.py").write_text("import random\n\ndef make_price():\n    return random.gauss(100, 5)\n",
                                               encoding="utf-8")
    assert sorted(set(scan_sources(tmp_path)) - set(SITES)) == ["src/leak.py::make_price"]


@pytest.mark.parametrize("key", keys_of(UNREFERENCED))
def test_an_unreferenced_site_really_has_no_importer(key):
    """'아무도 안 쓴다'는 분류는 사실이어야 한다 — 누가 임포트하기 시작하면 계산인지 합성인지 다시 정한다."""
    module = key.split("::")[0][:-3].replace("/", ".")
    assert importers_of(module) == [], f"{module} 을 임포트하는 곳이 생겼다 — 등록부에서 다시 분류하십시오"


def test_the_importer_lookup_is_not_vacuous():
    assert "src/api/strategy_routes.py" in importers_of("src.engine.dag_runner")
    assert len(importers_of("src.data.mock_base")) >= 5


# ══ ② 동적 — 자리마다 문을 연다 ═══════════════════════════════════════════════

@pytest.fixture
def world(tmp_path, monkeypatch):
    """문을 열 준비 — 빈 임시 DB · 외부 연결 차단 · 영속 캐시 끔 · 키 없음. 돌려주는 것은 '난수를 뽑은 자리'의 집합."""
    import probe_external_calls as ext

    from src.data import mock_base

    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    monkeypatch.setattr("src.database.get_sync_engine", lambda: eng)
    monkeypatch.setattr(mock_base.DeterministicMockStore, "_persist_on", lambda self: False)
    ext.install(lambda host, where: None, monkeypatch.setattr)
    drew: set[str] = set()
    install_tripwire(lambda frames: drew.update(frames), monkeypatch.setattr)
    return drew


def _live_risk():
    from starlette.websockets import WebSocketDisconnect

    import src.api.system_routes as sr

    class Sock:
        sent = 0

        async def accept(self): ...
        async def close(self, code=1000): ...

        async def send_json(self, payload):
            Sock.sent += 1
            raise WebSocketDisconnect()

    asyncio.run(asyncio.wait_for(sr.live_risk(Sock(), CODE), timeout=10))


def _item():
    return SimpleNamespace(stock_code=CODE, per=10.0, pbr=1.0, roe_pct=8.0, roa_pct=3.0, debt_ratio_pct=50.0,
                           dividend_yield_pct=2.0, gap_pct=5.0, market_cap_억=1_000.0)


def _kis_daily():
    from src.execution import kis_client
    try:
        kis_client.get_kis_client(force_reload=True).get_daily_ohlcv(CODE)
    finally:
        kis_client._kis_singleton = None      # 다음 시험이 이 모드의 클라이언트를 물려받지 않게


def _events():
    """공개 진입점이 둘이다 — 하나만 열면 다른 쪽의 게이트가 빠져도 모른다(변이로 확인했다)."""
    cal = _fresh("src.data.event_calendar:EventCalendar")
    return cal.get_events(CODE), cal.days_until(CODE, "earnings")


def _mock_bars(fresh_walk: bool = False):
    from src.data import ohlcv_loader
    if fresh_walk:
        ohlcv_loader._mock_walk.cache_clear()     # 걸음은 프로세스에 한 번만 만든다 — 비우지 않으면 앞 시험의 것을 읽는다
    return ohlcv_loader.load_ohlcv_unified(CODE, "2026-09-01", "2026-10-30")


def _fresh(path: str):
    """`모듈:클래스` 의 새 인스턴스 — 싱글톤의 캐시가 앞 시험의 값을 들고 있지 않게."""
    mod, cls = path.split(":")
    return getattr(__import__(mod, fromlist=[cls]), cls)()


#: 합성 자리 → 그 자리로 가는 공개 진입점(인자 없는 호출). 운영에서 거절(예외)로 끝나도 된다 — 보는 것은 '뽑았는가'다.
#: ★한 자리로 가는 공개 진입점이 여럿이면 전부 연다★ — 문이 놓친 진입점은 ③(GET 훑기)과 자리별 전용 시험이 받친다.
DOORS = {
    "src/api/system_routes.py::live_risk": _live_risk,
    "src/data/consensus_store.py::ConsensusStore._build_estimates":
        lambda: _fresh("src.data.consensus_store:ConsensusStore").get_estimates(CODE),
    "src/data/event_calendar.py::_mock_event_date": lambda: _events(),
    "src/data/extended_factors_store.py::ExtendedFactorsStore._build":
        lambda: _fresh("src.data.extended_factors_store:ExtendedFactorsStore").get_factors(CODE),
    "src/data/fundamentals_store.py::FundamentalsStore._mock_raw_financials":
        lambda: _fresh("src.data.fundamentals_store:FundamentalsStore").get_raw_financials(CODE),
    "src/data/fundamentals_store.py::FundamentalsStore._derive_factors":
        lambda: _fresh("src.data.fundamentals_store:FundamentalsStore").get_factors(CODE),
    "src/data/market_data.py::_mock_prices":
        lambda: _fresh("src.data.market_data:MarketDataProvider").get_indicators(CODE),
    "src/data/market_data.py::_mock_ohlcv":
        lambda: _fresh("src.data.market_data:MarketDataProvider").get_indicators(CODE),
    "src/data/market_data.py::_mock_supply":
        lambda: _fresh("src.data.market_data:MarketDataProvider").get_indicators(CODE),
    "src/data/minute_bars.py::_mock_minute_bars":
        lambda: __import__("src.data.minute_bars", fromlist=["x"]).collect_day([CODE], "2026-11-13"),
    "src/data/ohlcv_loader.py::_mock_walk": lambda: _mock_bars(fresh_walk=True),
    "src/data/ohlcv_loader.py::_mock_ohlcv_df._noise": lambda: _mock_bars(),
    "src/data/price_factors_store.py::PriceFactorsStore._mock_factors":
        lambda: _fresh("src.data.price_factors_store:PriceFactorsStore").get_factors(CODE),
    "src/engine/dag_runner.py::_generate_gbm":
        lambda: __import__("src.engine.dag_runner", fromlist=["x"])._load_ohlcv(CODE, 60),
    "src/engine/graph_store.py::GraphStore._build_graph":
        lambda: _fresh("src.engine.graph_store:GraphStore").get_relations(CODE),
    "src/engine/liquidity_gate.py::LiquidityStore._mock_liquidity":
        lambda: _fresh("src.engine.liquidity_gate:LiquidityStore").get_liquidity(CODE),
    "src/engine/pit_store.py::PITStore.get_financials_asof":
        lambda: _fresh("src.engine.pit_store:PITStore").get_financials_asof(CODE, "2024-06-30", {"roe_pct": 10.0, "per": 12.0}),
    "src/engine/pit_store.py::PITStore._mock_price_before_the_walk":
        lambda: _fresh("src.engine.pit_store:PITStore").price_asof_detail(CODE, "1995-06-30", 70_000.0),
    "src/engine/vector_store.py::VectorStore.get_embedding":
        lambda: _fresh("src.engine.vector_store:VectorStore").get_embedding(CODE),
    "src/engine/vector_store.py::VectorStore._embed_from_financials":
        lambda: _fresh("src.engine.vector_store:VectorStore").get_embedding(CODE, item=_item()),
    "src/engine/z_score.py::compute_rolling_stats":
        lambda: __import__("src.engine.z_score", fromlist=["x"]).compute_rolling_stats(CODE, "per", 20, 12.3, {}),
    "src/execution/kis_client.py::MockKISClient.get_daily_ohlcv": _kis_daily,
    "src/screener_pipeline.py::_generate_mock_equity_data":
        lambda: asyncio.run(__import__("src.screener_pipeline", fromlist=["x"]).fetch_equity_snapshot()),
    "src/screener_pipeline.py::fetch_ficc_snapshot":
        lambda: asyncio.run(__import__("src.screener_pipeline", fromlist=["x"]).fetch_ficc_snapshot()),
    "src/services/macro_collector.py::_generate_mock_series":
        lambda: _fresh("src.services.macro_collector:MacroCollector").collect_all(use_cache=False),
    "src/services/sentiment_worker.py::SentimentWorker._build_sentiment":
        lambda: _fresh("src.services.sentiment_worker:SentimentWorker").get_sentiment(CODE),
}

_GUARDED = set(keys_of(SYNTHETIC)) | set(keys_of(PRIMITIVE))


def test_every_synthetic_site_has_a_door():
    """문 없는 합성 자리는 '게이트 뒤'라는 등록이 말뿐이다."""
    assert set(DOORS) == set(keys_of(SYNTHETIC))


def _open(door) -> None:
    try:
        door()
    except Exception:  # noqa: BLE001 — 운영에서의 명시적 거절도 정상이다. 보는 것은 난수를 뽑았는가다.
        pass


@pytest.mark.parametrize("site", sorted(DOORS))
def test_no_synthetic_site_draws_when_the_gate_is_closed(world, monkeypatch, site):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    _open(DOORS[site])
    assert sorted(world & _GUARDED) == [], f"운영 게이트에서 합성 자리가 난수를 뽑았다(문: {site})"


@pytest.mark.parametrize("site", sorted(DOORS))
def test_the_door_really_reaches_its_site_when_the_gate_is_open(world, monkeypatch, site):
    """짝 — 문이 엉뚱한 곳으로 가면 위 시험은 영원히 초록이다. mock 에서는 바로 그 자리가 뽑아야 한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    DOORS[site]()
    assert site in world, f"mock 게이트인데 이 자리가 난수를 뽑지 않았다 — 문이 이 자리로 가지 않는다(뽑은 곳: {sorted(world & _GUARDED)})"


def test_the_tripwire_ignores_draws_outside_src(world):
    """덫은 `src/` 의 호출 사슬만 적는다 — 시험·라이브러리의 난수는 소음이다."""
    import random
    random.Random(1).random()
    random.random()
    assert world == set()


# ══ ③ 동적 — GET 라우트를 훑는다(하위 프로세스) ═══════════════════════════════

def _probe(tmp_path: Path, mock: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("KIS_APP_KEY", "KIS_APP_SECRET", "DART_API_KEY", "ECOS_API_KEY", "FRED_API_KEY")}
    env.update({"KIS_USE_MOCK": mock, "LIFECYCLE_DAEMONS": "0", "DATABASE_URL": f"sqlite:///{tmp_path / 'probe.db'}"})
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "probe_synthetic_draws.py"), "--json"],
                       capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=600)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("PROBE_JSON ")]
    assert lines, f"재는 도구가 결과를 내지 않았다: {r.stderr[-600:]}"
    return json.loads(lines[-1][len("PROBE_JSON "):])


def test_the_get_sweep_draws_nothing_synthetic_under_the_prod_gate(tmp_path):
    out = _probe(tmp_path, "0")
    assert out["mock_allowed"] is False and out["routes_called"] >= 100
    bad = {d["site"]: d["routes"] for d in out["draws"] if d["kind"] in (SYNTHETIC, PRIMITIVE)}
    assert bad == {}, f"운영 게이트의 GET 에서 합성 자리가 난수를 뽑았다: {bad}"


def test_the_get_sweep_sees_synthetic_draws_under_the_mock_gate(tmp_path):
    """짝 — 덫이 죽어 있으면 위 시험은 영원히 초록이다. mock 에서는 합성 자리가 여럿 보여야 한다."""
    out = _probe(tmp_path, "1")
    assert out["mock_allowed"] is True
    seen = {d["site"] for d in out["draws"] if d["kind"] == SYNTHETIC}
    assert len(seen) >= 5, f"mock 게이트인데 합성 자리가 거의 보이지 않는다: {sorted(seen)}"
    assert "src/data/fundamentals_store.py::FundamentalsStore._mock_raw_financials" in seen


def test_simulation_sites_are_not_treated_as_leaks():
    """계산 자리(몬테카를로 등)는 운영에서도 난수를 뽑는다 — 그것을 누수로 세면 이 가드는 쓸 수 없게 된다."""
    assert not (set(keys_of(SIMULATION)) & _GUARDED)
    assert len(keys_of(SIMULATION)) >= 10

