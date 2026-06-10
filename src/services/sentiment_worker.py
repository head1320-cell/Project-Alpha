"""
Sentiment Worker — Screener V3 Milestone 5 (NLP Alternative Data)
==========================================================================
뉴스/경영진 콜의 AI 긍정·부정 스코어 필터.

★ 핵심 설계 — 무거운 AI 연산 격리 ★
  · 스크리닝 시점에는 "사전 계산된 DB(Mock)"만 조회 (Claude 호출 없음)
  · 실제로는 sentiment_worker가 백그라운드 배치로 뉴스/콜 요약 후 DB 적재
  · 스크리닝은 DB 조회만 → <0.1s 유지

★ Gemini 비평 ④ 명시적 수용 ★
  센티먼트는 HFT 알파 소스가 아니라 "정성적 맥락 필터"다.
  (예: "경영진 콜 톤이 부정적인 종목 제외" — 투자 결정 보조 신호)
  밀리초 경쟁의 알파가 아님을 문서화한다.

센티먼트 소스:
  · news          — 최근 뉴스 긍정/부정 (-1 ~ +1)
  · earnings_call — 경영진 콜 톤 (-1 ~ +1)
"""

from __future__ import annotations

import logging

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


# 센티먼트 소스 정의
SENTIMENT_SOURCES = {
    "news_score": {
        "label": "뉴스 센티먼트",
        "unit": "",
        "typical_min": -1.0,
        "typical_max": 1.0,
        "description": "최근 뉴스의 AI 긍정/부정 스코어 (-1 부정 ~ +1 긍정). 정성적 맥락 필터.",
    },
    "call_tone": {
        "label": "경영진 콜 톤",
        "unit": "",
        "typical_min": -1.0,
        "typical_max": 1.0,
        "description": "최근 실적 발표 콜의 경영진 어조 (-1 방어적 ~ +1 자신감). 보조 신호.",
    },
}


class SentimentWorker(DeterministicMockStore):
    """
    NLP 센티먼트 제공.

    ★ 스크리닝 시점엔 사전 계산된 mock DB만 조회 (Claude 미호출).
      실 운영 시 precompute_batch()를 백그라운드 cron으로 돌려 DB 적재.
    """

    _singleton: SentimentWorker | None = None

    @classmethod
    def get_default(cls) -> SentimentWorker:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def get_sentiment(self, stock_code: str) -> dict:
        """
        단일 종목의 사전 계산된 센티먼트 조회 (DB 조회 흉내, AI 호출 없음).
        """
        return self.cached(
            f"sentiment:{stock_code}",
            lambda: self._build_sentiment(stock_code),
        )

    def _build_sentiment(self, stock_code: str) -> dict:
        # 사전 계산 결과를 흉내 내는 결정론적 mock
        news = round(self._normal(stock_code, "news", mu=0.05, sigma=0.4), 3)
        news = max(-1.0, min(1.0, news))
        call = round(self._normal(stock_code, "call", mu=0.10, sigma=0.35), 3)
        call = max(-1.0, min(1.0, call))

        # 일부 종목은 커버리지 없음 (결측 — 실데이터 정합성)
        return {
            "news_score": self._maybe_missing(stock_code, "m_news", value=news, missing_rate=0.12),
            "call_tone":  self._maybe_missing(stock_code, "m_call", value=call, missing_rate=0.20),  # 콜은 분기별 → 결측 잦음
            "_source":    "sentiment_precomputed_mock",
            "_note":      "정성적 맥락 필터 (HFT 알파 아님)",
        }

    def precompute_batch(self, stock_codes: list[str]) -> int:
        """
        [실 운영용 골격] 백그라운드 배치 — Claude로 뉴스/콜 요약 후 DB 적재.
        현재는 mock이므로 캐시 워밍만 수행. 스크리닝 경로와 분리됨.
        """
        count = 0
        for code in stock_codes:
            self.get_sentiment(code)
            count += 1
        logger.info(f"센티먼트 배치 사전계산 완료: {count}종목 (mock)")
        return count


# ═══════════════════════════════════════════════════════════════════════════════
# 평가기 + lazy 컨텍스트 빌더 (register_kind)
# ═══════════════════════════════════════════════════════════════════════════════

def eval_sentiment(item, cond, ctx: dict) -> bool:
    """센티먼트 평가 — lazy 주입된 _sentiment 컨텍스트(사전계산 DB) 조회."""
    from src.engine.filter_ast import FilterCondition, _eval_absolute
    sctx = ctx.get("_sentiment", {})
    code = getattr(item, "stock_code", None)
    data = sctx.get(code)
    if not data:
        return False
    val = data.get(cond.sentiment_source)
    if val is None:
        return False
    tmp = FilterCondition(field="__sent__", op=cond.op, value=cond.value, value2=cond.value2)
    return _eval_absolute(val, tmp)


def build_sentiment_context(group, items) -> dict:
    """lazy: 통과 후보의 사전계산 센티먼트 일괄 조회 (AI 호출 없음)."""
    worker = SentimentWorker.get_default()
    sctx = {}
    for it in items:
        code = getattr(it, "stock_code", None)
        if code:
            sctx[code] = worker.get_sentiment(code)
    return {"_sentiment": sctx}


def sentiment_catalog() -> dict:
    """API용 센티먼트 카탈로그."""
    return {
        "sources": [
            {"id": k, "label": v["label"], "unit": v["unit"],
             "typical_min": v["typical_min"], "typical_max": v["typical_max"],
             "description": v["description"]}
            for k, v in SENTIMENT_SOURCES.items()
        ],
        "note": "센티먼트는 정성적 맥락 필터입니다 (HFT 알파 소스 아님). 사전 계산된 DB를 조회하여 스크리닝 성능을 유지합니다.",
    }
