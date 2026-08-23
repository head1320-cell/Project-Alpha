"""백테스트 신호 경로의 스레드 격리 (P0-1).

감사 `docs/specs/2026-08-22-project-alpha-vnext-audit.md` §3.1 이 측정으로 증명한
결함을 닫은 뒤, 그것이 **되돌아오지 못하게** 잠근다.

예전 구조: `_generate_signal_as_of` 가 `src.kis_data_fetcher` 의 모듈 전역 두 개를
**대입으로 덮어쓰고** finally 에서 "진입 시점의 값" 으로 되돌렸다. 되돌릴 값이 이미
다른 스레드의 람다일 수 있어, 동시 실행이 서로의 데이터를 읽고 **두 실행이 정상
종료한 뒤에도 전역이 오염된 채 남았다**(실측: 샘플의 95.9% 가 패치 상태, 두 실행의
데이터가 모두 같은 전역에 관측, 엔진 오류 0건 — 조용히 틀렸다).

★이 파일의 가드는 전부 구 코드에서 red 여야 한다★ 그래야 가드다.
"""
import threading

import pandas as pd

import src.kis_data_fetcher as fetcher


def _bars(tag: str) -> pd.DataFrame:
    df = pd.DataFrame({
        "date": ["20230103", "20230104"],
        "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
        "close": [1.0, 2.0], "volume": [10, 20],
    })
    df.attrs["ticker"] = tag
    return df


def test_bar_context_is_isolated_per_thread():
    """★스레드 격리★ 두 스레드가 각자 자기 봉만 본다.

    구 코드(전역 대입)에서는 나중에 민 쪽이 먼저 민 쪽을 덮어써 서로의 데이터를 읽었다.
    """
    seen: dict[str, str] = {}
    both_pushed = threading.Barrier(2, timeout=5)

    def worker(tag: str):
        token = fetcher.push_bar_context(_bars(tag), {"price": tag})
        try:
            both_pushed.wait()          # 두 스레드가 동시에 밀어 넣은 상태를 만든다
            seen[tag] = fetcher.get_daily_prices("000000").attrs["ticker"]
        finally:
            fetcher.pop_bar_context(token)

    ts = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert seen == {"A": "A", "B": "B"}, f"스레드가 남의 봉을 읽었다: {seen}"


def test_no_permanent_leak_after_threads_finish():
    """★영구 누수 없음★ 스레드가 끝난 뒤 모듈 함수 객체가 그대로다.

    구 코드에서는 완료된 실행의 람다가 전역에 남아, 이후 **모든** 조회가 얼어붙은
    DataFrame 을 받았다(`uvicorn --workers 1` 이라 프로세스는 하나다).
    """
    before_daily = fetcher.get_daily_prices
    before_price = fetcher.get_current_price

    def worker(tag: str):
        token = fetcher.push_bar_context(_bars(tag), {"price": tag})
        try:
            fetcher.get_daily_prices("000000")
        finally:
            fetcher.pop_bar_context(token)

    ts = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert fetcher.get_daily_prices is before_daily
    assert fetcher.get_current_price is before_price


def test_nested_push_restores_exactly():
    """중첩 복원 — `set(None)` 이 아니라 `reset(token)` 이어야 성립한다."""
    outer = fetcher.push_bar_context(_bars("outer"), {"price": "outer"})
    try:
        assert fetcher.get_daily_prices("x").attrs["ticker"] == "outer"
        inner = fetcher.push_bar_context(_bars("inner"), {"price": "inner"})
        try:
            assert fetcher.get_daily_prices("x").attrs["ticker"] == "inner"
        finally:
            fetcher.pop_bar_context(inner)
        assert fetcher.get_daily_prices("x").attrs["ticker"] == "outer", \
            "안쪽을 닫았더니 바깥 컨텍스트가 사라졌다"
    finally:
        fetcher.pop_bar_context(outer)


def test_live_path_is_untouched_without_context():
    """★라이브 경로 불변★ 컨텍스트가 없으면 오버라이드가 새지 않는다.

    백테스트가 도는 동안에도 같은 프로세스에서 라이브 신호 요청이 들어온다
    (`uvicorn --workers 1`). 그 경로가 백테스트의 봉을 받으면 안 된다.

    ★그래서 "컨텍스트 없으면 예외" 로 막지 않는다★ 프로세스 전역 플래그로 거부하면
    바로 이 라이브 요청이 깨진다. 대신 조용히 기존 DB 경로를 탄다.
    """
    token = fetcher.push_bar_context(_bars("bt"), {"price": "bt"})
    fetcher.pop_bar_context(token)

    out = fetcher.get_daily_prices("005930", days=5)
    assert isinstance(out, pd.DataFrame)
    # DB(=이 환경에선 daily_prices 부재)로 갔다는 증거: 백테스트 봉의 표식이 없다.
    assert out.attrs.get("ticker") != "bt", "라이브 조회가 백테스트 봉을 받았다"


def test_signal_generation_runs_in_the_pushing_thread():
    """★알려진 한계를 명시적으로 고정한다★

    컨텍스트는 **민 스레드**에서만 보인다. 지금 시뮬 루프는 순차라 성립한다
    (`BacktestEngine.run()` 단일 스레드). 나중에 신호 생성을 스레드풀로 병렬화하면
    컨텍스트가 따라가지 않아 **조용히 라이브 DB(=룩어헤드)로 떨어진다.**

    이 테스트는 그 동작을 바람직하다고 말하는 것이 아니라, **깨질 때 알아채도록**
    적어 두는 것이다. 진짜 해법은 실행을 별도 프로세스로 빼는 것(P0-2)이다.
    """
    got: list = []
    token = fetcher.push_bar_context(_bars("main"), {"price": "main"})
    try:
        t = threading.Thread(
            target=lambda: got.append(fetcher.get_daily_prices("005930", days=5)))
        t.start()
        t.join()
    finally:
        fetcher.pop_bar_context(token)

    assert got[0].attrs.get("ticker") != "main", \
        "다른 스레드에 컨텍스트가 새어 나갔다 — 격리가 깨졌다"
