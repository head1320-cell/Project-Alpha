"""KIS 콜드 로딩의 ★콜 예산★ — 필요한 만큼만 받는다 (①)

## 무엇이 문제였나

`get_daily_ohlcv` 의 페이지네이션 종료조건이 두 군데서 어긋나 있었다.

★단위 불일치★ `kis_client.py` 의 `len(collected) >= days` 에서 `collected` 는
**영업일 행**인데 `days` 는 `ohlcv_loader.py` 가 만든 **달력일**이다(≈1.45배 크다).
그래서 목표에 도달하지 못하고 `max_pages` 까지 돈다 — 3년 요청에 필요한 봉은
756 인데 ~1,148 봉을 받았다(**1.52배**).

★`end_date` 가 전달되지 않는다★ `end_cursor = datetime.now()` 라, 과거로 끝나는
백테스트도 오늘부터 거슬러 받고 초과분을 뒤에서 버렸다.

고치는 방법은 환산 계수를 더 정교하게 맞추는 것이 **아니다** — 우리는 요청 구간을
알고 있으므로 **"가장 오래된 수집 봉이 start_date 이하" 를 종료조건**으로 쓰면
추정이 아예 필요 없다.

★기존 호출부는 불변★ 새 인자는 선택이고, 안 주면 예전 동작 그대로다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from src.execution.kis_client import KISClient, RateLimiter  # noqa: E402


class _Spy(KISClient):
    """실제 HTTP 대신 페이지 요청을 세고 합성 봉을 돌려준다.

    ★계약을 테스트한다★ — KIS 가 하는 일(요청 윈도의 영업일 봉을 최대 100건)을
    그대로 흉내 내고, 우리가 **몇 번 물었는지**와 **어느 구간을 물었는지**를 잰다.
    """

    def __init__(self, first_listed: str = "2000-01-01"):
        self.calls: list[tuple[str, str]] = []
        self.first_listed = datetime.strptime(first_listed, "%Y-%m-%d")
        self.rate_limiter = RateLimiter(calls_per_second=1e9)   # 페이싱은 여기 관심 밖

    def _headers(self, tr_id: str) -> dict:     # 토큰 발급(네트워크) 우회
        return {"tr_id": tr_id}

    def _request(self, *a, **kw):                     # noqa: D401
        params = kw.get("params") or (a[2] if len(a) > 2 else {})
        d1, d2 = params["FID_INPUT_DATE_1"], params["FID_INPUT_DATE_2"]
        self.calls.append((d1, d2))
        lo = max(datetime.strptime(d1, "%Y%m%d"), self.first_listed)
        hi = datetime.strptime(d2, "%Y%m%d")
        out, cur = [], lo
        while cur <= hi and len(out) < 100:
            if cur.weekday() < 5:
                out.append({"stck_bsop_date": cur.strftime("%Y%m%d"),
                            "stck_oprc": "100", "stck_hgpr": "110",
                            "stck_lwpr": "90", "stck_clpr": "105",
                            "acml_vol": "1000", "acml_tr_pbmn": "1000"})
            cur += timedelta(days=1)
        return {"output2": out}


def _bars(rows) -> int:
    return len(rows)


def test_it_stops_once_it_has_reached_the_requested_start(monkeypatch):
    """★필요한 만큼만 받는다★

    2023-07-26 ~ 2026-07-26 (영업일 ~783봉). 예전에는 달력일 1,106 을 행 목표로 써서
    ~1,148봉(1.52배)을 받았다. start_date 를 알려주면 그 지점에서 멈춰야 한다.
    """
    c = _Spy()
    rows = c.get_daily_ohlcv("005930", days=1106,
                             start_date="2023-07-26", end_date="2026-07-26")
    got = _bars(rows)
    assert 700 <= got <= 900, f"받은 봉이 요청 구간과 안 맞는다: {got}"

    # ★진짜 성질은 "얼마나 과거까지 물었나" 다★ (변이 D6)
    # 처음엔 `len(calls) <= 12` 만 걸었는데, 내가 `max_pages` 도 구간 기반으로
    # 바꿔놨기 때문에 "종료조건을 달력일 비교로 되돌린" 변이가 **상한에 막혀**
    # 12회를 못 넘었다 — 두 변경이 서로를 가린 것이다. 걸어야 하는 것은
    # **요청 시작일보다 한 윈도 이상 과거를 묻지 않는다** 이다.
    oldest_asked = min(d1 for d1, _d2 in c.calls)
    assert oldest_asked >= "20230301", (
        f"요청 시작일(2023-07-26)보다 한참 과거를 물었다: {oldest_asked} — 과다 페치")


def test_it_does_not_page_backward_from_today_when_an_end_date_is_given(monkeypatch):
    """★end_date 가 전달된다★ 과거로 끝나는 백테스트가 오늘부터 긁지 않는다."""
    c = _Spy()
    c.get_daily_ohlcv("005930", days=400,
                      start_date="2019-01-01", end_date="2020-01-01")
    newest = max(d2 for _d1, d2 in c.calls)
    assert newest <= "20200102", f"end_date 이후를 물었다: {newest}"


def test_the_old_call_shape_still_works(monkeypatch):
    """★기존 호출부 불변★ 인자를 안 주면 예전처럼 오늘부터 days 만큼 거슬러 받는다."""
    c = _Spy()
    rows = c.get_daily_ohlcv("005930", days=120)
    assert rows, "인자 없는 호출이 빈 결과를 냈다"
    newest = max(d2 for _d1, d2 in c.calls)
    assert newest >= (datetime.now() - timedelta(days=2)).strftime("%Y%m%d"), (
        f"기본 동작이 오늘 기준이 아니다: {newest}")


def test_a_short_listing_history_stops_early_instead_of_burning_max_pages(monkeypatch):
    """상장이 늦은 종목은 상장일에서 멈춘다 — 예전에도 되던 동작을 깨지 않는다."""
    c = _Spy(first_listed="2025-01-02")
    c.get_daily_ohlcv("999999", days=3000,
                      start_date="2018-01-01", end_date="2026-07-26")
    assert len(c.calls) <= 12, f"상장 시작에 도달했는데 계속 물었다: {len(c.calls)}회"


# ── 리미터: 페이싱은 지키되 락은 잡고 자지 않는다 ────────────────────────────

def test_the_limiter_does_not_sleep_while_holding_the_lock():
    """★스로틀된 스레드가 나머지를 멈춰 세우지 않는다★

    `acquire()` 는 락 안에서 `time.sleep()` 을 했다. 로더 스레드 10개가 도는데
    한 스레드가 자는 동안 나머지 9개의 `acquire()` 가 전부 막혔다 — 페이싱이
    아니라 직렬화다. 슬롯 예약은 락 안, 대기는 락 밖이어야 한다.
    """
    import threading
    lim = RateLimiter(calls_per_second=2)
    for _ in range(2):
        lim.acquire()                      # 예산 소진 — 다음 acquire 는 대기해야 한다

    holder_saw_lock_free = threading.Event()

    def prober():
        # 다른 스레드가 대기하는 동안 락을 잡을 수 있어야 한다.
        if lim._lock.acquire(timeout=0.5):
            lim._lock.release()
            holder_saw_lock_free.set()

    t = threading.Thread(target=lambda: lim.acquire())
    t.start()
    p = threading.Thread(target=prober)
    p.start()
    p.join(); t.join()
    assert holder_saw_lock_free.is_set(), (
        "대기 중인 스레드가 락을 쥐고 있다 — 다른 로더 스레드가 전부 막힌다")


def test_the_limiter_still_paces():
    """★짝★ 위 테스트만 있으면 '락을 아예 안 쓴다'(페이싱 포기)로도 통과한다."""
    import time
    lim = RateLimiter(calls_per_second=5)
    t0 = time.perf_counter()
    for _ in range(11):                    # 5/s 면 11콜에 최소 2초
        lim.acquire()
    el = time.perf_counter() - t0
    assert el >= 1.8, f"페이싱이 사라졌다: 11콜에 {el:.2f}초 (5/s 면 ≥2초)"


# ── 스키마 확인은 프로세스당 1회 ────────────────────────────────────────────

def test_the_schema_check_runs_once_per_process_not_once_per_ticker(monkeypatch):
    """★종목당 5 트랜잭션을 없앤다★

    write-back 이 종목마다 `ensure_table` 을 불렀고, 그것은 CREATE + ALTER×4 를
    각각 별도 트랜잭션으로 실행한다 → 콜드 200종목이면 1,000 트랜잭션이 낭비다.
    """
    import src.data.ohlcv_loader as L
    calls = {"n": 0}
    monkeypatch.setattr(L, "_schema_inited", False)
    import src.data.krx_ingest as K
    monkeypatch.setattr(K, "ensure_table", lambda eng: calls.__setitem__("n", calls["n"] + 1))
    for _ in range(50):
        L._ensure_daily_prices_schema(object())
    assert calls["n"] == 1, f"스키마 확인이 {calls['n']}회 돌았다 — 1회여야 한다"


def test_a_failed_schema_check_is_retried_rather_than_remembered(monkeypatch):
    """★짝★ 실패를 기억하면 이후 write-back 이 전부 스키마 없이 돌아 조용히 실패한다.

    "1회만 부른다" 만 거는 테스트는 `_schema_inited = True` 를 무조건 세우는
    구현으로도 통과한다 — 성공했을 때만 세우는지 함께 걸어야 한다.
    """
    import src.data.krx_ingest as K
    import src.data.ohlcv_loader as L
    monkeypatch.setattr(L, "_schema_inited", False)
    n = {"i": 0}

    def flaky(eng):
        n["i"] += 1
        if n["i"] < 3:
            raise RuntimeError("DB 일시 오류")

    monkeypatch.setattr(K, "ensure_table", flaky)
    for _ in range(10):
        L._ensure_daily_prices_schema(object())
    assert n["i"] == 3, f"실패를 기억해 재시도를 멈췄다(호출 {n['i']}회)"
