"""DART 재무시계열 정체 수정 — 마스터캐시 경쟁 시 짧은 재시도 + 수동트리거 1회성화.

GCP 로그로 확정된 원인: 부팅 시 KIS 마스터 수집과 백필이 동시 시작 → 백필이 먼저 돌면
SEED 30종목 폴백 → '완료'로 오판 → 24h sleep. last_fetch가 이틀째 정지된 근거."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from main_api import _dart_backfill_sleep_seconds, _ingest_run  # noqa: E402


def test_sleep_quota_exhausted_waits_for_reset():
    assert _dart_backfill_sleep_seconds({"stopped_at_quota": True}) == 3 * 3600


def test_sleep_fallback_retries_soon(monkeypatch):
    """마스터 캐시 경쟁으로 SEED 폴백됐으면 24h가 아니라 짧게 재시도 — 정체의 핵심 수정."""
    monkeypatch.delenv("DART_HISTORY_RETRY_SEC", raising=False)
    assert _dart_backfill_sleep_seconds({"fallback_to_seed": True, "tickers": 30}) == 300


def test_sleep_fallback_respects_env_override(monkeypatch):
    monkeypatch.setenv("DART_HISTORY_RETRY_SEC", "60")
    assert _dart_backfill_sleep_seconds({"fallback_to_seed": True}) == 60


def test_sleep_normal_completion_waits_a_day():
    assert _dart_backfill_sleep_seconds({"tickers": 2562, "saved": 10, "fallback_to_seed": False}) == 24 * 3600


def test_sleep_error_dict_defaults_to_daily():
    assert _dart_backfill_sleep_seconds({"error": True}) == 24 * 3600


def test_manual_financials_trigger_completes_once_and_reports(monkeypatch):
    """수동 '재무시계열' 버튼이 무한루프 대신 1회 실행되고 결과를 반환하는지
    (이전엔 _dart_history_backfill_bg 무한루프를 그대로 재사용 — 버튼이 영원히 안 끝남)."""
    import src.data.dart_history as dh

    calls: list[tuple] = []

    def fake_backfill(**kwargs):
        cb = kwargs.get("progress_cb")
        if cb:
            cb(1, 1, 5, 5)
        calls.append(kwargs)
        return {"tickers": 1, "calls": 5, "saved": 5, "skipped": 0, "empty": 0,
                "no_corp": 0, "fallback_to_seed": False}

    monkeypatch.setattr(dh, "backfill_financials", fake_backfill)
    result = _ingest_run("financials")
    assert result["saved"] == 5                      # 실제 결과가 즉시 반환됨(무한루프 아님)
    assert calls[0].get("all_listed") is True
    assert callable(calls[0].get("progress_cb"))
