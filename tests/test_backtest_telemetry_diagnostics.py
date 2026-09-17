"""진단이 **텔레메트리와 저장 컬럼까지** 간다 (R5·R4)

## 왜 이 파일이 있나

`_worker` 는 예전부터 `result["signal_path"]`·`result["macro_lookahead"]`·
`result["fundamentals_pit"]` 을 텔레메트리에 실으려고 **시도**하고 있었다.
그런데 라우트가 그 키들을 응답에 넣지 않았으므로 `isinstance(..., dict)` 가
언제나 거짓이었고, **키가 아예 생기지 않았다** — 코드는 멀쩡한데 결과가 없는,
R1 이 고친 것과 정확히 같은 단선의 하류다.

같은 자리에서 둘째 결함도 실측했다: `backtest_runs` 의 `is_pit_verified` 컬럼은
**아무도 쓰지 않았다.** 그래서 화면의 `PIT 검증 / PIT 미검증` 배지가 모든
실행에서 항상 "미검증" 이었다.

## 못 박는 것

  ㉘ 결과에 진단이 있으면 텔레메트리에 집계가 실린다
  ㉙ ★짝★ 결과에 없으면 텔레메트리에도 **키를 만들지 않는다**
     (`None` 을 넣으면 "재봤더니 없음" 이 되고, 그것은 하지 않은 진술이다)
  ㉚ 판정이 저장 컬럼으로 옮겨진다 — `verified`→True · 나머지→False · 미상→None
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.api.backtest_run_routes as BR  # noqa: E402
from src.api.backtest_run_routes import _diagnostic_telemetry  # noqa: E402
from src.engine.run_evidence import STATUS_PARTIAL, STATUS_VERIFIED  # noqa: E402

_FULL = {
    "signal_path": {"vectorized": 9, "per_bar": 1, "failed": 0, "vectorized_pct": 90.0},
    "macro_lookahead": {"pit": 2, "live": 1, "blocked": 0, "pit_pct": 66.7,
                        "tokens": {}, "note": "…"},
    "fundamentals_pit": {"measured": 4, "estimated": 6, "unknown": 0,
                         "measured_pct": 40.0, "reasons": {}, "tickers": {}},
    "price_basis": {"state": "degraded", "uniform_adjusted_pct": 75.0,
                    "mixed_tickers": ["000660"], "reason": "…"},
    "universe": {"survivorship": "not_corrected", "effective": "all_listed",
                 "requested": "all_asof", "fell_back": True, "reason": "…"},
    "pit_evidence": {"status": STATUS_PARTIAL, "broken_axes": ["universe"],
                     "unknown_axes": [], "axes": {}},
}


# ═══════════════════════════════════════════════════════════════════════════
# ㉘ 집계가 실린다 — ★사유 원본은 결과에 있고 여기에는 수치만★
# ═══════════════════════════════════════════════════════════════════════════

def test_all_five_diagnostics_are_aggregated():
    tele = _diagnostic_telemetry(_FULL)
    assert tele["signal_path"]["vectorized_pct"] == 90.0, tele
    assert tele["macro_lookahead"] == {"pit": 2, "live": 1, "blocked": 0,
                                       "pit_pct": 66.7}, tele
    assert tele["fundamentals_pit"]["measured_pct"] == 40.0, tele
    assert tele["price_basis"] == {"state": "degraded",
                                   "uniform_adjusted_pct": 75.0}, tele
    assert tele["universe"] == {"survivorship": "not_corrected",
                                "effective": "all_listed", "fell_back": True}, tele
    assert tele["pit_status"] == STATUS_PARTIAL, tele


def test_the_bulky_parts_are_left_in_the_result():
    """토큰별 사유·종목 목록은 결과에 그대로 있다 — 텔레메트리를 부풀리지 않는다."""
    tele = _diagnostic_telemetry(_FULL)
    assert "tokens" not in tele["macro_lookahead"], tele
    assert "reasons" not in tele["fundamentals_pit"], tele
    assert "mixed_tickers" not in tele["price_basis"], tele


# ═══════════════════════════════════════════════════════════════════════════
# ㉙ ★짝★ 없으면 만들지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_absent_diagnostics_create_no_keys():
    """★`None` 을 넣으면 '재봤더니 없음' 이 된다★ — 하지 않은 진술이다."""
    assert _diagnostic_telemetry({}) == {}


def test_a_null_diagnostic_creates_no_key():
    """매크로를 안 쓴 실행은 `macro_lookahead: None` 이다 — 그것도 키를 안 만든다."""
    tele = _diagnostic_telemetry({"macro_lookahead": None, "price_basis": None,
                                  "universe": None, "pit_evidence": None})
    assert tele == {}, tele


def test_a_partial_result_only_carries_what_it_has():
    tele = _diagnostic_telemetry({"price_basis": _FULL["price_basis"]})
    assert set(tele) == {"price_basis"}, tele


def test_a_non_dict_diagnostic_is_ignored_not_guessed():
    """★모양이 다르면 지어내지 않는다★"""
    assert _diagnostic_telemetry({"macro_lookahead": "이상한 값"}) == {}


# ═══════════════════════════════════════════════════════════════════════════
# ㉚ 판정이 저장 컬럼까지 — ★배지가 드디어 무언가를 읽는다★
# ═══════════════════════════════════════════════════════════════════════════

class _FakeBR:
    """`backtest_runs` 대역 — DB 없이 `_worker` 를 돌린다."""

    def __init__(self):
        self.result_calls: list[dict] = []
        self.telemetry: dict = {}
        self.errors: list[tuple] = []

    def transition(self, run_id, stage):
        return {"ok": True}

    def advance(self, run_id, stage, message=None, progress=None):
        return {}

    def touch_progress(self, run_id, pct, msg):
        return "ok"

    def get_status(self, run_id):
        return {"status": "running"}

    def set_result(self, run_id, result, is_mock_data=None, is_pit_verified=None):
        self.result_calls.append({"is_mock_data": is_mock_data,
                                  "is_pit_verified": is_pit_verified})
        return {"ok": True}

    def set_error(self, run_id, code, message):
        self.errors.append((code, message))

    def engine_version(self):
        return "test"

    def set_telemetry(self, run_id, tele):
        self.telemetry = dict(tele)


def _run_worker(monkeypatch, result: dict) -> _FakeBR:
    fake = _FakeBR()
    monkeypatch.setattr(BR, "br", fake)
    monkeypatch.setattr("src.api.screener_routes._screen_to_backtest_core",
                        lambda req, progress_cb=None: result)
    BR._worker("run-1", {"filter_ast": {"logic": "AND", "conditions": [],
                                        "groups": []}})
    return fake


@pytest.mark.parametrize(("status", "expected"), [
    (STATUS_VERIFIED, True),
    (STATUS_PARTIAL, False),
    ("unverified", False),
    ("unknown", None),
])
def test_the_verdict_reaches_the_stored_column(monkeypatch, status, expected):
    fake = _run_worker(monkeypatch, {**_FULL, "pit_evidence": {"status": status}})
    assert fake.result_calls, "결과가 저장되지 않았다"
    assert fake.result_calls[0]["is_pit_verified"] is expected, fake.result_calls


def test_a_result_without_a_verdict_stores_none(monkeypatch):
    """★판정이 없으면 거짓이 아니라 미상이다★"""
    fake = _run_worker(monkeypatch, {"error": False})
    assert fake.result_calls[0]["is_pit_verified"] is None, fake.result_calls


def test_the_worker_actually_records_the_aggregates(monkeypatch):
    """★배선했다고 실린 것은 아니다★ 워커를 돌려 텔레메트리를 본다."""
    fake = _run_worker(monkeypatch, _FULL)
    assert fake.telemetry.get("pit_status") == STATUS_PARTIAL, fake.telemetry
    assert fake.telemetry.get("universe", {}).get("fell_back") is True, fake.telemetry
