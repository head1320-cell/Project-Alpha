"""캐시가 mock 과 운영을 가른다 — ★합성값이 영속 DB 로 새고 있었다★
==============================================================================
감사: `docs/specs/2026-08-27-feature-layer-mock-audit.md` §7 · 선행: `2aff832`

## 두 개의 서로 다른 누수

`2aff832` 가 유동성 게이트의 운영 합성을 고치면서, **상류에 같은 종류의 결함**이
있다는 것을 트립와이어로 기록해 뒀다. 그것을 실측했더니 누수가 **둘**이었다.

**① 메모리 누수** — `mock_base.cached()` 의 키에 모드가 없다. 그래서
`KIS_USE_MOCK=1` 에서 만든 값이 `=0` 으로 바뀐 뒤에도 그대로 서빙된다(재현 확인:
`amount_20d_avg=908.9` 가 `mock_allowed()=False` 에서 나왔다).

**② ★영속 누수 — 트립와이어의 위험 평가가 틀렸다★** 그 메모는 *"운영에서의 위험은
낮다 — 프로세스는 한 모드로 시작해 끝난다"* 고 적었다. 그러나:

```python
# snapshot_db.enabled()
return bool(os.getenv("DART_API_KEY")) or not mock_allowed()
```

`KIS_USE_MOCK=1` + `DART_API_KEY` 설정은 **정당한 부분 연동 개발 조합**인데, 이때
`mock_allowed()=True` 이면서 `_persist_on()=True` 다. 즉 합성값이 `factor_snapshot`
에 **기록되고 재시작을 넘어** 운영에서 실값처럼 읽힌다. 프로세스 수명 안의 문제가
아니었다.

## 그래서 둘 다 고친다

- `_persist_on()` 에 mock 게이트 — 합성값은 DB 에 들어가지 않는다.
- `cached()` 키에 모드 — 메모리에서도 두 모드가 섞이지 않는다.

★하나만 고치면 다른 쪽이 남는다★ — 서로 다른 누수이기 때문이다.

## 짝 검증

N1/N2 · N3/N4 · N5/N6 — 한쪽만 있으면 "캐시를 아예 안 쓴다" · "영속을 아예 끈다" ·
"write 를 아예 안 부른다" 구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data import snapshot_db  # noqa: E402
from src.data.mock_base import DeterministicMockStore  # noqa: E402


class _Store(DeterministicMockStore):
    """계수기가 달린 최소 스토어 — 빌더 호출 횟수로 캐시 적중을 관찰한다."""

    PERSIST = True

    def __init__(self):
        super().__init__()
        self.builds = 0

    def value(self, code: str):
        def build():
            self.builds += 1
            from src.data.mock_gate import mock_allowed
            return {"v": "MOCK" if mock_allowed() else "REAL"}
        return self.cached(f"v:{code}", build)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("SNAPSHOT_DB", "0")      # 기본은 DB 끔 — 켜는 시험은 따로
    return _Store()


# ══════════════════════════════════════════════════════════════════════════
# 1) 메모리 누수 — ★모드가 바뀌면 다시 만든다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_mock_warmed_entry_does_not_serve_the_real_path(store, monkeypatch):
    """N1 — ★이것이 결함의 본체다★

    재현: `KIS_USE_MOCK=1` 에서 데운 `amount_20d_avg=908.9` 가 `=0` 에서 그대로
    나왔다. 운영 경로가 합성값을 받는다는 뜻이다.
    """
    assert store.value("A")["v"] == "MOCK"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert store.value("A")["v"] == "REAL", "mock 값이 운영 경로로 샜다"


def test_the_cache_still_works_within_one_mode(store):
    """N2 ★짝★ — "캐시를 아예 안 쓴다" 를 배제한다.

    모드가 같으면 빌더는 한 번만 돌아야 한다. 안 그러면 이 수정이 캐시를 없앤 것과
    같고, 스크리닝이 종목마다 재계산하게 된다.
    """
    store.value("B"); store.value("B"); store.value("B")
    assert store.builds == 1, f"같은 모드인데 {store.builds}회 재계산했다"


def test_both_modes_keep_their_own_entry(store, monkeypatch):
    """N1 보강 — 서로 덮어쓰지 않는다. 오가도 각자 값을 유지한다."""
    assert store.value("C")["v"] == "MOCK"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert store.value("C")["v"] == "REAL"
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert store.value("C")["v"] == "MOCK", "운영 값이 mock 항목을 덮었다"
    assert store.builds == 2, f"모드당 한 번씩이어야 한다: {store.builds}"


# ══════════════════════════════════════════════════════════════════════════
# 2) ★영속 누수 — 합성값은 DB 에 들어가지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_mock_mode_never_persists(monkeypatch):
    """N3 — ★`DART_API_KEY` 가 있어도 mock 이면 영속하지 않는다★

    이 조합(`KIS_USE_MOCK=1` + 실 DART 키)이 정당한 개발 설정이면서 동시에
    합성값을 DB 로 밀어 넣던 경로다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("DART_API_KEY", "x" * 40)
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    assert snapshot_db.enabled() is True, "이 시나리오가 성립하려면 DB 는 켜져 있어야 한다"
    assert _Store()._persist_on() is False, "mock 인데 영속이 켜져 있다"


def test_real_mode_still_persists(monkeypatch):
    """N4 ★짝★ — "영속을 아예 껐다" 를 배제한다. 운영에서는 여전히 켜져야 한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    assert _Store()._persist_on() is True, "운영에서 영속이 꺼졌다 — 캐시가 무의미해진다"


def test_mock_mode_does_not_write_to_the_snapshot_db(monkeypatch):
    """N5 — 판정이 아니라 **동작**으로 본다. `write` 가 불리면 안 된다."""
    writes: list = []
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("DART_API_KEY", "x" * 40)
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(snapshot_db, "write", lambda k, v: writes.append(k))
    monkeypatch.setattr(snapshot_db, "bulk_read", lambda ks, ttl: {})
    _Store().value("D")
    assert writes == [], f"mock 값이 DB 에 기록됐다: {writes}"


def test_real_mode_does_write(monkeypatch):
    """N6 ★짝★ — "write 를 아예 안 부른다" 를 배제한다."""
    writes: list = []
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(snapshot_db, "write", lambda k, v: writes.append(k))
    monkeypatch.setattr(snapshot_db, "bulk_read", lambda ks, ttl: {})
    _Store().value("E")
    assert len(writes) == 1, "운영에서 영속 write 가 사라졌다"


# ══════════════════════════════════════════════════════════════════════════
# 3) DB 키도 모드로 갈린다
# ══════════════════════════════════════════════════════════════════════════
def test_the_persisted_key_is_namespaced_by_mode(monkeypatch):
    """N7 — 영속 키가 모드를 담아야 옛 오염분을 되읽지 않는다.

    ★`factor_snapshot` 은 지금 0행이다★ — 무효화 비용이 0인 지금이 고칠 때다.
    """
    reads: list = []
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(snapshot_db, "write", lambda k, v: None)
    monkeypatch.setattr(snapshot_db, "bulk_read",
                        lambda ks, ttl: reads.extend(ks) or {})
    _Store().value("F")
    assert reads, "DB 를 읽지 않았다"
    assert all("v:F" in k and k != "v:F" for k in reads), \
        f"영속 키에 모드가 없다: {reads}"


def test_prime_is_namespaced_too(monkeypatch):
    """N7 짝 — 벌크 로드 경로도 같은 규칙을 쓴다(경로가 둘이면 갈라진다)."""
    reads: list = []
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(snapshot_db, "bulk_read",
                        lambda ks, ttl: reads.extend(ks) or {})
    _Store().prime(["v:G", "v:H"])
    assert reads and all(k not in ("v:G", "v:H") for k in reads), \
        f"prime 이 원시 키로 읽는다: {reads}"


def test_prime_result_is_visible_to_cached(monkeypatch):
    """N7 보강 — `prime` 이 채운 항목을 `cached` 가 **찾을 수 있어야** 한다.

    두 경로가 서로 다른 네임스페이스를 쓰면 벌크 로드가 조용히 무효가 된다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("SNAPSHOT_DB", raising=False)
    monkeypatch.setattr(snapshot_db, "bulk_read",
                        lambda ks, ttl: {k: {"v": "FROM_DB"} for k in ks})
    s = _Store()
    assert s.prime(["v:I"]) == 1
    assert s.value("I")["v"] == "FROM_DB", "prime 이 채운 값을 cached 가 못 찾는다"
    assert s.builds == 0, "prime 했는데 다시 만들었다"


# ══════════════════════════════════════════════════════════════════════════
# 4) ★실제 스토어에서 누수가 사라졌다★ (트립와이어 뒤집기)
# ══════════════════════════════════════════════════════════════════════════
def test_the_price_factor_leak_is_gone(monkeypatch):
    """N8 — `2aff832` 가 기록한 시나리오를 그대로 밟는다.

    그 커밋의 트립와이어는 *"이 테스트가 빨개지면 결함이 고쳐진 것"* 이라고 적었다.
    여기가 그 뒤집힌 짝이다.
    """
    from src.data.price_factors_store import PriceFactorsStore

    s = PriceFactorsStore.get_default()
    s._cache.clear()
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("SNAPSHOT_DB", "0")
    warmed = s.get_factors("005930").get("amount_20d_avg")
    assert warmed is not None, "mock 에서 값이 나와야 시나리오가 성립한다"

    monkeypatch.setenv("KIS_USE_MOCK", "0")
    leaked = s.get_factors("005930").get("amount_20d_avg")
    assert leaked is None, f"mock 값 {warmed} 가 운영 경로로 샜다 (받은 값 {leaked})"
    s._cache.clear()
