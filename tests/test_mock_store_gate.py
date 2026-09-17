"""★운영에서는 합성값을 만들지 않는다★ — mock 게이트 불변식 (G)

## 무엇이 문제였나

`CLAUDE.md` 절대 불변식:

    `mock_allowed()` 가 유일한 판정 기준이며 `KIS_USE_MOCK` 이 정확히 "1" 일 때만
    mock. ★운영에서는 합성값을 만들지 않습니다★ — 실패하면 None/빈값 + 사유.
    **새 스토어는 반드시 이 게이트를 통과시킬 것.**

마지막 문장을 **검사하는 것이 아무것도 없었다.** 그래서 새어 나갔다 —
`DeterministicMockStore` 서브클래스 여덟 중 셋(`SentimentWorker` · `GraphStore` ·
`VectorStore`)이 운영에서도 합성값을 만들었고, 그 값이 스크리너 필터에 노출됐다.

`mock_base` 는 **캐시·영속만** 게이트한다(모드별 네임스페이스 · 합성값 미영속).
빌더는 막지 않는다 — 그것이 각 스토어의 몫인데 다섯만 하고 있었다.

## 세 스토어의 성격이 다르다 — ★통째로 막으면 실기능을 없앤다★

    GraphStore._build_graph        순수 합성 (관계를 셔플로 지어낸다)      → 차단
    SentimentWorker._build_sentiment  순수 합성 (결정론적 난수)            → 차단
    VectorStore.get_embedding      ★혼종★ — 후보는 **실 재무**로 만든다   → 합성 성분만 제거

벡터의 합성 성분은 둘뿐이다: ⑴ 더해지는 노이즈 ⑵ `item=None` 완전합성 폴백.

## 차단이 안전한 이유

`eval_sentiment` · `eval_graph` · `eval_vector_sim` 이 전부 데이터 없으면
`return False` 다 ⇒ 그 필터는 **아무 종목도 매칭하지 않는다**(전부 매칭이 아니다).
`consensus_store` 가 같은 판단을 이미 적어 뒀다 — *"데이터 없음으로 매칭 안 됨"*.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import importlib  # noqa: E402
import pathlib  # noqa: E402

import pytest  # noqa: E402

from src.data.mock_base import DeterministicMockStore  # noqa: E402

CODE = "005930"


# ═══════════════════════════════════════════════════════════════════════════════
# 서브클래스 전수 — ★목록을 손으로 적지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════

def _import_all_store_modules() -> None:
    """`src/` 를 훑어 `DeterministicMockStore` 서브클래스가 선언된 모듈을 임포트.

    ★모듈 목록을 손으로 적지 않는 이유★ — `__subclasses__()` 는 **임포트된**
    것만 본다. 목록을 적으면 다음에 생기는 스토어가 조용히 빠지고, 이 파일이
    "전수" 라고 주장하면서 실제로는 아니게 된다. 정확히 그 부류의 실수가
    이 작업을 만든 원인이다.
    """
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    for path in root.rglob("*.py"):
        try:
            if "(DeterministicMockStore)" not in path.read_text(encoding="utf-8"):
                continue
        except Exception:  # noqa: BLE001
            continue
        mod = ".".join(path.relative_to(root.parent).with_suffix("").parts)
        importlib.import_module(mod)


_import_all_store_modules()


def _stores() -> dict[str, type]:
    """★운영 스토어만★ — 불변식은 `src/` 의 스토어에 대한 것이다.

    다른 테스트 파일이 `DeterministicMockStore` 를 상속한 **픽스처**를 정의한다
    (`test_cache_mode_isolation.py` · `test_cached_empty.py` 의 `_Store`).
    그것까지 세면 전체 스위트에서만 오탐이 난다 — 실제로 그렇게 걸렸고, 단독
    실행에서는 안 보였다(그 모듈들이 임포트되지 않아서).
    """
    return {c.__name__: c for c in DeterministicMockStore.__subclasses__()
            if c.__module__.startswith("src.")}


#: 스토어 → 운영 모드에서 부를 **공개 조회**. 새 스토어가 생기면 여기 없어서 실패한다.
PROBES: dict[str, callable] = {
    "SentimentWorker":     lambda c: c.get_default().get_sentiment(CODE),
    "GraphStore":          lambda c: c.get_default().neighbors(CODE, "supplier", 1),
    "VectorStore":         lambda c: c.get_default().get_embedding(CODE),
    "LiquidityStore":      lambda c: c.get_default().get_liquidity(CODE, 10000.0),
    "ConsensusStore":      lambda c: c.get_default().get_estimates(CODE),
    "ExtendedFactorsStore": lambda c: c.get_default().get_factors(CODE),
    "PriceFactorsStore":   lambda c: c.get_default().get_factors(CODE),
    "FundamentalsStore":   lambda c: c.get_default().get_factors(CODE),
}


@pytest.fixture(autouse=True)
def _fresh_singletons():
    """★모드를 바꾸면 싱글톤을 새로 만든다★

    `GraphStore._build_graph` 는 **싱글톤 생성 시 1회**만 돈다. 재사용하면 앞
    테스트의 모드로 만들어진 인스턴스를 보게 되어 이 파일이 통째로 공허해진다.
    """
    for cls in _stores().values():
        if hasattr(cls, "_singleton"):
            cls._singleton = None
        if hasattr(cls, "_cache"):
            try:
                cls._cache.clear()
            except Exception:  # noqa: BLE001
                pass
    yield


@pytest.fixture
def prod(monkeypatch):
    """운영 모드 — ★전체 스위트는 `=1` 로만 돌아 이 경로를 안 밟는다★"""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    from src.data.mock_gate import mock_allowed
    assert not mock_allowed(), "전제가 깨졌다 — 운영 모드가 아니다"


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")


# ═══════════════════════════════════════════════════════════════════════════════
# ① 감성 — 순수 합성이므로 차단
# ═══════════════════════════════════════════════════════════════════════════════

def test_sentiment_yields_no_synthetic_score_in_production(prod):
    """★알맹이★ 운영에서 뉴스·콜 점수를 지어내지 않는다."""
    from src.services.sentiment_worker import SENTIMENT_SOURCES, SentimentWorker
    got = SentimentWorker.get_default().get_sentiment(CODE)
    for src_id in SENTIMENT_SOURCES:
        assert got.get(src_id) is None, f"운영에서 {src_id} 를 지어냈다: {got}"


def test_sentiment_still_works_in_mock_mode(dev):
    """★짝★ 개발 화면이 죽으면 안 된다 — 이것이 없으면 "항상 차단" 도 통과한다."""
    from src.services.sentiment_worker import SentimentWorker
    got = SentimentWorker.get_default().get_sentiment(CODE)
    assert any(got.get(k) is not None for k in ("news_score", "call_tone")), got


# ═══════════════════════════════════════════════════════════════════════════════
# ② 그래프 — 관계를 셔플로 지어내므로 차단
# ═══════════════════════════════════════════════════════════════════════════════

def test_graph_relations_are_empty_in_production(prod):
    """★공급망을 지어내지 않는다★ 이건 스크리너가 종목을 고르는 근거가 된다."""
    from src.engine.graph_store import GraphStore
    store = GraphStore.get_default()
    assert store.neighbors(CODE, "supplier", 1) == set(), "공급사를 지어냈다"
    assert store.neighbors(CODE, "competitor", 2) == set(), "경쟁사를 지어냈다"
    rel = store.get_relations(CODE)
    assert all(not v for v in rel.values()), f"관계를 지어냈다: {rel}"


def test_graph_still_works_in_mock_mode(dev):
    """★짝★"""
    from src.engine.graph_store import GraphStore
    assert GraphStore.get_default().neighbors(CODE, "supplier", 1), "개발 모드에서 관계가 비었다"


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 벡터 — ★통째로 막지 않는다★ 합성 성분만 제거
# ═══════════════════════════════════════════════════════════════════════════════

class _Item:
    """스크리너 후보 종목 — 실 재무가 담긴다."""
    def __init__(self, per=12.0, pbr=1.1, roe_pct=9.0):
        self.per, self.pbr, self.roe_pct = per, pbr, roe_pct
        self.roa_pct, self.debt_ratio_pct = 5.0, 80.0
        self.dividend_yield_pct, self.gap_pct, self.market_cap_억 = 2.0, -3.0, 5000.0


def test_vector_still_works_from_real_financials_in_production(prod):
    """★통째 차단을 배제하는 짝★ 후보 임베딩은 **실 재무**에서 나온다 — 살려야 한다.

    `_embed_from_financials` 는 per·pbr·roe·roa·부채비율·배당·괴리·시총을 쓴다.
    이걸 막으면 동작하는 실기능이 사라진다. 정책은 "합성값 금지" 이지
    "이 기능 금지" 가 아니다.
    """
    from src.engine.vector_store import VectorStore
    vec = VectorStore.get_default().get_embedding(CODE, _Item())
    assert vec is not None and len(vec) == 8, vec
    assert any(abs(x) > 1e-9 for x in vec), "실 재무를 줬는데 영벡터다"


def test_vector_has_no_synthetic_noise_in_production(prod):
    """★같은 재무면 같은 벡터★ 노이즈는 유사도 점수의 **지어낸 성분**이다.

    8차원 정규화 벡터에 `sigma=0.15` 노이즈는 임계값 근처 판정을 실제로 뒤집는다.
    종목코드가 다르면 노이즈가 달라지므로, **재무가 같은 두 종목**을 비교하면
    노이즈가 남아 있는지 바로 드러난다.
    """
    from src.engine.vector_store import VectorStore
    store = VectorStore.get_default()
    a = store.get_embedding("005930", _Item())
    b = store.get_embedding("000660", _Item())      # 코드만 다르고 재무는 동일
    assert a == pytest.approx(b), f"재무가 같은데 벡터가 다르다 — 합성 노이즈가 남아 있다\n{a}\n{b}"


def test_vector_noise_is_kept_in_mock_mode(dev):
    """★짝★ 개발 모드의 기존 동작(종목 고유 미세차)은 유지한다."""
    from src.engine.vector_store import VectorStore
    store = VectorStore.get_default()
    a = store.get_embedding("005930", _Item())
    b = store.get_embedding("000660", _Item())
    assert a != pytest.approx(b), "개발 모드에서 노이즈가 사라졌다"


def test_vector_refuses_the_fully_synthetic_fallback_in_production(prod):
    """`item` 이 없으면 코드 해시로 벡터를 지어내던 경로 — 운영에서는 `None`.

    ★"지어낸 벡터와 비교" 보다 "비교 못 함" 이 정직하다★ — `eval_vector_sim` 이
    `None` 을 받으면 매칭하지 않는다.
    """
    from src.engine.vector_store import VectorStore
    assert VectorStore.get_default().get_embedding(CODE) is None


def test_vector_embedding_cache_is_mode_scoped(prod, monkeypatch):
    """★`_scoped()` 를 우회하면 모드 간 누수가 생긴다★

    `get_embedding` 은 `self._cache` 를 직접 쓰며 캐시 키에 모드를 안 붙였다.
    그래서 개발 모드에서 만든 합성 벡터가 운영 모드에서 그대로 서빙될 수 있었다 —
    `mock_base._scoped` 독스트링이 기록한 **바로 그 결함**이다.
    """
    from src.engine.vector_store import VectorStore
    store = VectorStore.get_default()
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    dev_vec = store.get_embedding(CODE)                 # 합성 — 캐시에 들어간다
    assert dev_vec is not None, "개발 모드 전제가 깨졌다"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert store.get_embedding(CODE) is None, "개발 모드 합성 벡터가 운영에서 서빙됐다"


# ═══════════════════════════════════════════════════════════════════════════════
# ④ 사유 — ★사유 없는 unavailable 금지★
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_blocked_stores_say_why(prod):
    """`{}` 나 사유 없는 `None` 은 금지다 — 처방이 달라진다(미연결 vs 장애)."""
    from src.services.sentiment_worker import SentimentWorker
    got = SentimentWorker.get_default().get_sentiment(CODE)
    assert got.get("_source") == "unavailable", got
    assert got.get("_note"), "차단하면서 사유를 안 줬다"


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ 필터 의미 — ★차단이 "전부 매칭" 이 되면 안 된다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_blocked_filters_match_nothing_rather_than_everything(prod):
    """fail-closed 확인 — 차단의 안전성이 여기 걸려 있다."""
    from src.engine.graph_store import eval_graph
    from src.engine.vector_store import eval_vector_sim
    from src.services.sentiment_worker import eval_sentiment

    class _C:
        stock_code = CODE
    cond = type("Cond", (), {"graph_target": CODE, "graph_relation": "supplier",
                             "graph_depth": 1, "sentiment_source": "news_score",
                             "op": "gte", "value": -999, "value2": None,
                             "vector_threshold": 0.0})()
    assert eval_graph(_C(), cond, {"_graph": {}}) is False
    assert eval_sentiment(_C(), cond, {"_sentiment": {}}) is False
    assert eval_vector_sim(_C(), cond, {"_vector": {}}) is False


# ═══════════════════════════════════════════════════════════════════════════════
# ⑥ ★전수 트립와이어★ — 다음 스토어가 같은 실수를 못 하게
# ═══════════════════════════════════════════════════════════════════════════════

def _missing_probes() -> set[str]:
    """프로브가 없는 mock 스토어. ★아래 두 테스트가 **이 함수를** 함께 쓴다★

    테스트-의-테스트가 같은 계산을 **재구현**하면, 진짜 검사를 무력화하는 변이를
    잡지 못한다(변이 배터리에서 실제로 살아남았다). 한 곳만 두면 둘 다 죽는다.
    """
    return set(_stores()) - set(PROBES)


def test_every_mock_store_has_a_probe():
    """새 스토어가 생기면 **여기서 먼저 실패한다.**

    ★목록을 손으로 적는 대신 서브클래스를 열거한다★ — 적으면 다음 스토어가
    조용히 빠지고, 이 파일이 "전수" 라고 주장하면서 실제로는 아니게 된다.
    """
    missing = _missing_probes()
    assert not missing, (
        f"프로브가 없는 mock 스토어: {sorted(missing)} — "
        f"운영에서 합성값을 내는지 아무도 검사하지 않는다")


def test_no_store_synthesizes_in_production(prod, monkeypatch):
    """★동작으로 본다★ 운영 조회 중 **합성 생성기가 한 번도 불리면 안 된다.**

    소스에 `mock_allowed` 가 있는지 보는 것으로는 부족하다 — 불러 놓고 결과를
    안 쓰는 구현도 통과한다. 생성기 자체를 폭발시켜 **도달하는지**를 본다.
    """
    def _boom(*a, **k):
        raise AssertionError("운영 모드에서 합성 생성기가 호출됐다")

    for name in ("_normal", "_uniform", "_rng"):
        monkeypatch.setattr(DeterministicMockStore, name, _boom, raising=False)

    stores = _stores()
    for name, probe in PROBES.items():
        cls = stores.get(name)
        if cls is None:
            continue
        probe(cls)          # 합성 생성기에 닿으면 AssertionError


def test_the_tripwire_would_catch_an_ungated_store(prod, monkeypatch):
    """★테스트의 테스트★ 항상 통과하는 검사를 배제한다."""
    class _Leaky(DeterministicMockStore):
        _singleton = None

        @classmethod
        def get_default(cls):
            return cls()

        def value(self):
            return self._normal("x", "y", mu=0.0, sigma=1.0)   # ★게이트 없음★

    # ★운영 모듈인 척한다★ `_stores()` 가 `src.` 만 세므로, 위장하지 않으면
    # 이 테스트가 통째로 공허해진다(제외 대상이라 아무것도 안 잡힌다).
    _Leaky.__module__ = "src.engine.fake_leaky_store"

    # ⑴ 프로브 완전성 검사가 새 서브클래스를 잡는가
    #    ★재구현하지 않고 `_missing_probes()` 를 그대로 부른다★ — 그래야 그
    #    함수를 무력화하는 변이가 여기서도 죽는다.
    assert "_Leaky" in _stores(), "새 서브클래스가 열거되지 않는다"
    assert "_Leaky" not in PROBES
    assert _missing_probes() == {"_Leaky"}, "완전성 검사가 새 스토어를 놓친다"

    # ⑵ 합성 생성기 폭발이 실제로 걸리는가
    def _boom(*a, **k):
        raise AssertionError("합성 생성기 호출")
    monkeypatch.setattr(DeterministicMockStore, "_normal", _boom, raising=False)
    with pytest.raises(AssertionError):
        _Leaky.get_default().value()
