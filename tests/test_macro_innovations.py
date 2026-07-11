"""매크로 혁신 과제 — CB 센티먼트(렉시콘)·그레인저 인과 그래프 TDD."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402


# ── CB 센티먼트 (Text-as-Data) ──

def test_hawkish_text_scores_positive():
    from src.engine.cb_sentiment import score_text
    txt = ("The Committee decided to raise rates given elevated inflation. "
           "Further tightening and restrictive policy may be appropriate. "
           "Upside risks to inflation remain.")
    s = score_text(txt)
    assert s["score"] > 0.3 and s["hawkish_hits"] >= 3
    assert "매파" in s["label"]


def test_dovish_korean_text_scores_negative():
    from src.engine.cb_sentiment import score_text
    txt = "위원회는 경기 둔화와 하방 위험을 고려해 금리 인하 가능성을 열어두고 완화 기조를 유지했다. 물가 오름세 둔화가 이어지고 있다."
    s = score_text(txt)
    assert s["score"] < -0.3 and s["dovish_hits"] >= 3
    assert "비둘기" in s["label"]


def test_neutral_text_scores_zero():
    from src.engine.cb_sentiment import score_text
    s = score_text("오늘 날씨가 맑습니다. 회의는 예정대로 진행됐습니다.")
    assert s["score"] == 0.0 and "중립" in s["label"]


def test_cb_sentiment_honest_when_fetch_fails(monkeypatch):
    import src.engine.cb_sentiment as cbs
    monkeypatch.setattr(cbs, "_fetch", lambda url, timeout=8.0: None)
    cbs._CACHE.clear()
    out = cbs.cb_sentiment(use_cache=False)
    assert out["banks"]["fed"]["available"] is False   # 합성 점수 금지(정직)
    assert "note" in out["banks"]["fed"]


# ── 그레인저 인과 그래프 ──

class _S:
    def __init__(self, values):
        self.values = values
        self.source = "mock"


def test_granger_detects_lagged_dependency():
    """y[t] = 0.9·x[t-1] + 잡음 → x→y 엣지가 검출돼야 (역방향은 약해야)."""
    from src.engine.causal_graph import granger_edges
    rng = __import__("random").Random(7)
    x = [math.sin(i / 5) + rng.gauss(0, 0.3) for i in range(72)]
    y = [0.0] + [0.9 * x[i - 1] + rng.gauss(0, 0.1) for i in range(1, 72)]
    smap = {"KR_10Y": _S(x), "USD_KRW": _S(y)}
    out = granger_edges(smap)
    assert out["available"] is True
    pairs = {(e["from"], e["to"]) for e in out["edges"]}
    assert ("KR_10Y", "USD_KRW") in pairs, f"선행 의존이 검출 안 됨: {out['edges']}"


def test_granger_honest_labels():
    from src.engine.causal_graph import granger_edges
    out = granger_edges({})
    # 데이터 없음 → 노드/엣지 빈 목록 (크래시·허위 금지)
    assert out["nodes"] == [] and out["edges"] == []
