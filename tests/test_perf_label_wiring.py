"""응답이 ★스스로★ 성과의 종류를 말한다 (Z2)

화면이 "백테스트 페이지니까 BACKTEST" 를 그리면 그것은 사실이 아니라 **배치**다.
이 파일은 **응답에 `perf_label` 이 실려 나가는지**, 그리고 ★기존 키가 하나도
사라지지 않는지★(골든)를 못 박는다.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.perf_kind import (  # noqa: E402
    KIND_BACKTEST,
    KIND_LIVE,
    KIND_PAPER,
    KIND_SHADOW,
    KIND_UNKNOWN,
)

# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 백테스트 런 조회 — 라벨이 실리고 기존 키가 그대로다
# ═══════════════════════════════════════════════════════════════════════════

_RUN_ROW = {
    "run_id": "R-1", "status": "completed", "strategy_name": "테스트",
    "is_mock_data": True, "is_pit_verified": None, "result": {"total_return_pct": 12.3},
}


def test_the_run_response_declares_its_kind(monkeypatch):
    from src.api import backtest_run_routes as rr
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(_RUN_ROW))
    body = rr.run_full("R-1")
    assert body["perf_label"]["kind"] == KIND_BACKTEST
    assert body["perf_label"]["data_real"] is False, "mock 실행인데 실데이터라고 했다"


def test_the_run_response_keeps_every_existing_key(monkeypatch):
    """★골든★ 라벨을 더한 것이지 무언가를 치운 것이 아니다."""
    from src.api import backtest_run_routes as rr
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(_RUN_ROW))
    body = rr.run_full("R-1")
    for k, v in _RUN_ROW.items():
        assert body[k] == v, f"{k} 가 바뀌었다"


def test_an_unrecorded_data_source_stays_unknown(monkeypatch):
    """★`None` 을 `False` 로 접지 않는다★"""
    from src.api import backtest_run_routes as rr
    row = dict(_RUN_ROW, is_mock_data=None)
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: row)
    lb = rr.run_full("R-1")["perf_label"]
    assert lb["kind"] == KIND_BACKTEST
    assert lb["data_real"] is None
    assert lb["data_reason"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑨ 일별 손익 — ★행마다★ 실행 모드에서 파생, NULL 은 unknown
# ═══════════════════════════════════════════════════════════════════════════

class _FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **kw):
        return self

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_pnl(monkeypatch, rows):
    from src.api import stage13_routes as s13

    class _Eng:
        def connect(self):
            return _FakeConn([_FakeRow(r) for r in rows])

    import src.database as db
    monkeypatch.setattr(db, "get_sync_engine", lambda: _Eng())
    return s13


@pytest.mark.parametrize("mode,expected", [
    ("SHADOW", KIND_SHADOW), ("PAPER", KIND_PAPER), ("LIVE", KIND_LIVE),
])
def test_each_pnl_row_declares_its_mode(monkeypatch, mode, expected):
    s13 = _patch_pnl(monkeypatch, [{"trade_date": "2026-09-01",
                                    "execution_mode": mode,
                                    "daily_return_pct": 0.5}])
    body = s13.live_daily_pnl(limit=10)
    assert body["pnl_history"][0]["perf_label"]["kind"] == expected


def test_a_pnl_row_without_a_mode_is_unknown(monkeypatch):
    """★기록이 없으면 `live` 로도 `paper` 로도 기울지 않는다★"""
    s13 = _patch_pnl(monkeypatch, [{"trade_date": "2026-09-01",
                                    "execution_mode": None,
                                    "daily_return_pct": 0.5}])
    lb = s13.live_daily_pnl(limit=10)["pnl_history"][0]["perf_label"]
    assert lb["kind"] == KIND_UNKNOWN
    assert lb["kind_reason"]


def test_pnl_rows_keep_their_original_columns(monkeypatch):
    """★골든★"""
    row = {"trade_date": "2026-09-01", "execution_mode": "PAPER",
           "daily_return_pct": 0.5, "realized_pnl_krw": 1234.0}
    s13 = _patch_pnl(monkeypatch, [row])
    got = s13.live_daily_pnl(limit=10)["pnl_history"][0]
    for k, v in row.items():
        assert got[k] == v


# ═══════════════════════════════════════════════════════════════════════════
# ★전수★ — 성과를 내려보내는 경로가 라벨을 붙이는가
# ═══════════════════════════════════════════════════════════════════════════

_MUST_DECLARE = (
    "src/api/backtest_run_routes.py",
    "src/api/screener_routes.py",
    "src/api/allocation_routes.py",
    "src/api/stage11_routes.py",
    "src/api/stage13_routes.py",
    # ★계획에 없던 경로 — 프런트 트립와이어를 먼저 돌려 보고 찾았다 (Z4)★
    # 전략 상세 모달이 총수익·CAGR 을 라벨 없이 그리고 있었다.
    "src/api/macro_routes.py",
)


def test_every_performance_route_imports_the_vocabulary():
    """★라벨을 각자 문자열로 지어내지 않는다★ — 단일 어휘를 쓴다."""
    import pathlib
    missing = [p for p in _MUST_DECLARE
               if "perf_kind" not in pathlib.Path(p).read_text(encoding="utf-8")]
    assert not missing, f"성과를 내려보내면서 라벨 어휘를 안 쓰는 경로: {missing}"


def test_the_scan_targets_exist():
    """★공허 배제★"""
    import pathlib
    for p in _MUST_DECLARE:
        assert pathlib.Path(p).exists(), p


# ═══════════════════════════════════════════════════════════════════════════
# ★계획을 실측이 넓혔다★ — 프런트 부착 대상을 좇아 다섯 경로를 더 배선했다
# ─────────────────────────────────────────────────────────────────────────────
# Z2 는 다섯 엔드포인트만 배선했는데, Z3 에서 **그 화면들이 실제로 부르는 곳**을
# 따라가 보니 넷이 더 있었다: `/screen-to-backtest`(전략 비교·커스텀 러너) ·
# `/multibacktest/{id}/attribution`(국면별 알파) · `/multibacktest/counterfactual` ·
# `/macro/strategy/{sid}`(전략 상세). 여기에 `/allocation/analyze` 가 더해진다
# (`MetricsTable`·`ResearchRunsPanel` 이 그 `summary` 를 그린다).
#
# ★배선하지 않았으면 그 화면들은 영원히 `unknown` 을 그렸을 것이다★ — 그것도
# 정직하긴 하지만, 사실이 바로 옆에 있는데 모른다고 적는 것은 정직이 아니라 태만이다.
# ═══════════════════════════════════════════════════════════════════════════


def _is_backtest_label(lb: dict) -> bool:
    return (isinstance(lb, dict) and lb.get("kind") == KIND_BACKTEST
            and "data_real" in lb and "data_reason" in lb)


def test_the_attribution_response_declares_its_kind(monkeypatch):
    from src.api import stage11_routes as s11

    class _Fake:
        def __init__(self, engine): pass
        def decompose(self, run_id, include_daily=False):
            return {"available": True, "regime_breakdown": [{"regime": "GOLDILOCKS"}]}

    monkeypatch.setattr("src.database.get_sync_engine", lambda: object())
    monkeypatch.setattr("src.engine.attribution_decomposer.AttributionDecomposer", _Fake)
    body = s11.multibacktest_attribution(1)
    assert _is_backtest_label(body["perf_label"])
    assert body["regime_breakdown"], "기존 키가 사라졌다"


def test_the_counterfactual_response_declares_its_kind(monkeypatch):
    from src.api import stage11_routes as s11

    class _Fake:
        def __init__(self, engine): pass
        def compare(self, cfg, scenarios):
            return {"available": True, "n_scenarios": len(scenarios), "scenarios": []}

    monkeypatch.setattr("src.database.get_sync_engine", lambda: object())
    monkeypatch.setattr("src.engine.counterfactual_analyzer.CounterfactualAnalyzer", _Fake)
    # ★분석기가 "있다" 고 가정하는 테스트다★ (BF) — 실제 저장소에서는 그 엔진이 쓰는
    # 모듈 다섯이 없어 이 문이 503 을 낸다(`test_multistrategy_availability`).
    monkeypatch.setattr("src.engine.multistrategy_availability._spec_exists",
                        lambda name: True)
    req = s11.CounterfactualRequest(strategy_ids=[1], start_date="2023-01-01",
                                    end_date="2023-06-30")
    body = s11.multibacktest_counterfactual(req)
    assert _is_backtest_label(body["perf_label"])
    assert body["n_scenarios"] == 4, "기존 키가 바뀌었다"


def test_the_strategy_detail_response_declares_its_kind(monkeypatch):
    """전략 상세 모달의 총수익·CAGR — ★`perf` **안에** 붙인다★

    화면이 `detail.perf.summary` 를 그리므로 라벨도 그 옆에 있어야 같은 것을
    말한다는 사실이 읽힌다. 최상위에 두면 어느 숫자를 가리키는지 흐려진다.
    """
    from src.api import macro_routes as mr
    detail = {"id": "s1", "name": "전략",
              "perf": {"curve": [], "summary": {"total_return_pct": 3.0}}}
    monkeypatch.setattr("src.engine.strategy_profiles.build_detail",
                        lambda sid, market: detail)
    body = mr.macro_strategy_detail("s1")
    assert _is_backtest_label(body["perf"]["perf_label"])
    assert body["perf"]["summary"]["total_return_pct"] == 3.0, "기존 키가 바뀌었다"
    assert "perf_label" not in body, "최상위가 아니라 `perf` 안에 붙는다"


def test_the_screen_to_backtest_response_declares_its_kind():
    """★소스 수준 확인★ — 이 코어를 돌리려면 OHLCV 적재가 필요해 단위로 못 돈다.

    그래서 "데이터 축을 `data_source` 에서 파생한다" 는 **배선 자체**를 본다.
    동작은 `/screen-to-backtest` 를 타는 E2E(`backtest.spec.ts`)가 지킨다.
    """
    import pathlib
    src = pathlib.Path("src/api/screener_routes.py").read_text(encoding="utf-8")
    assert '"perf_label": backtest_label(is_mock_data=not _ds["fully_real"]).to_dict()' in src, (
        "screen-to-backtest 가 `data_source` 에서 라벨을 파생하지 않습니다")


def test_the_screener_run_does_not_claim_to_be_a_backtest():
    """★붙였다가 되물린 자리★ — 스크리닝은 시뮬레이션이 아니다.

    `_run_advanced_core` 는 한 시점의 **횡단면 통과 종목**을 낸다. 거기에
    `backtest` 라벨을 달면 "이 숫자는 과거 데이터 위의 시뮬레이션에서 나왔다" 는
    없는 사실이 생긴다. 데이터 축(`data_source`)은 그 응답에 원래 있고 그대로다.

    ★"라벨을 붙이는 것" 자체가 목적이 되면 이런 실수가 생긴다★ — 그래서 되물린
    자리에 테스트를 남긴다.
    """
    import inspect

    from src.api import screener_routes as sr
    src = inspect.getsource(sr._run_advanced_core)
    assert 'payload["perf_label"]' not in src, (
        "스크리닝 결과에 성과 종류 라벨이 다시 붙었습니다 — "
        "이 응답은 시뮬레이션 결과가 아닙니다")
    assert '"data_source"' in src, "데이터 축까지 지우면 안 됩니다"


def test_the_analyze_response_declares_its_kind():
    """`/analyze` 의 `summary` 는 과거 수익률 위의 시뮬레이션 통계다."""
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    client = TestClient(create_app())
    r = client.post("/api/v1/allocation/analyze",
                    json={"tickers": ["005930", "000660", "035420"],
                          "lookback_days": 300, "mc_paths": 100})
    assert r.status_code == 200, r.text
    assert _is_backtest_label(r.json()["perf_label"])


#: ★상수 **정의** 한 줄은 생산이 아니다★ — `perf_kind.py` 자신은 제외한다.
_RA_TESTBED_RE = re.compile(r"""KIND_RA_TESTBED|["']ra_testbed["']""")


def _ra_testbed_producers() -> list[str]:
    out: list[str] = []
    for path in sorted(pathlib.Path("src").rglob("*.py")):
        if path.name == "perf_kind.py":
            continue
        text = path.read_text(encoding="utf-8")
        for m in _RA_TESTBED_RE.finditer(text):
            out.append(f"{path}:{text[: m.start()].count(chr(10)) + 1}")
    return out


def test_unused_vocabulary_has_no_producer():
    """★`ra_testbed` 는 어휘일 뿐 생산자가 없다★ — 저장소는 제출한 적이 없다.

    이 테스트가 빨개지는 날은 둘 중 하나다: 정말로 테스트베드에 제출했거나(그러면
    이 테스트를 고치는 것이 맞다), 아무도 만들지 않는 값을 누가 지어냈거나.
    """
    from src.domain.perf_kind import KIND_RA_TESTBED

    producers = _ra_testbed_producers()
    assert not producers, (
        f"아무도 만들지 않기로 한 `{KIND_RA_TESTBED}` 를 만드는 곳이 생겼습니다: {producers}")


def test_the_ra_testbed_scan_actually_scans():
    """★테스트의 테스트★ "생산자 0" 은 스캐너가 고장 났을 때도 나오는 값이다."""
    fake = "label = {'kind': 'ra_testbed'}\n"
    assert _RA_TESTBED_RE.search(fake), "가짜 생산자를 못 잡습니다 — 스캐너가 죽었습니다"
    assert not _RA_TESTBED_RE.search("label = {'kind': 'backtest'}"), (
        "관계없는 종류를 잡습니다 — 항상-거부 구현입니다")
    assert len(list(pathlib.Path("src").rglob("*.py"))) > 100, "스캔 범위가 비었습니다"
