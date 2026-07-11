"""중앙은행 커뮤니케이션 센티먼트 (Text-as-Data) — 매파/비둘기 강도 -1.0~+1.0.

Fed 성명·BOK 통화정책방향 텍스트를 렉시콘(Apel-Grimaldi 사상: hawkish/dovish 용어 사전)
으로 스코어링. LLM 인프라 없이 결정론·검증 가능(정직) — ANTHROPIC_API_KEY가 있으면
기존 narrative 클라이언트로 보정 요약을 덧붙일 수 있는 구조(현재는 렉시콘 단독).

수집: Fed(federalreserve.gov 최신 FOMC statement)·BOK(통화정책방향 의결문) — 네트워크
실패/차단 시 available:false + 사유(허위 점수 금지). 6시간 캐시.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

# ── 렉시콘 (EN + KR) — 긴축(hawkish, +) / 완화(dovish, −) ──
_HAWK_EN = ("raise rates", "rate hike", "hikes", "tighten", "tightening", "restrictive",
            "inflation remains elevated", "elevated inflation", "upside risks to inflation",
            "further firming", "reduce the balance sheet", "quantitative tightening",
            "price pressures", "overheating", "strong labor market")
_DOVE_EN = ("cut rates", "rate cut", "cuts", "easing", "accommodative", "lower rates",
            "downside risks", "slowing growth", "weakening", "recession", "support the economy",
            "patient", "pause", "disinflation progress", "inflation has eased")
_HAWK_KR = ("금리 인상", "긴축", "물가 상승 압력", "인플레이션 우려", "물가 불안", "추가 인상",
            "유동성 회수", "과열", "물가안정에 중점")
_DOVE_KR = ("금리 인하", "완화", "경기 둔화", "하방 위험", "성장세 약화", "부양",
            "인하 가능성", "물가 오름세 둔화", "동결")

_INTENSIFIERS = ("significantly", "substantially", "strongly", "대폭", "크게", "상당히")


def score_text(text: str) -> dict:
    """텍스트 → {score(-1~+1), hawkish_hits, dovish_hits, terms}. 결정론(렉시콘)."""
    t = (text or "").lower()
    hawk_terms = [w for w in (_HAWK_EN + _HAWK_KR) if w.lower() in t]
    dove_terms = [w for w in (_DOVE_EN + _DOVE_KR) if w.lower() in t]
    h, d = len(hawk_terms), len(dove_terms)
    if h + d == 0:
        return {"score": 0.0, "hawkish_hits": 0, "dovish_hits": 0, "terms": [],
                "label": "중립 (시그널 없음)"}
    raw = (h - d) / (h + d)
    boost = 1.0 + 0.15 * sum(1 for w in _INTENSIFIERS if w in t)
    score = max(-1.0, min(1.0, raw * min(1.5, boost)))
    label = ("매파 (긴축)" if score > 0.2 else "비둘기 (완화)" if score < -0.2 else "중립")
    return {"score": round(score, 3), "hawkish_hits": h, "dovish_hits": d,
            "terms": (hawk_terms + dove_terms)[:12], "label": label}


def _fetch(url: str, timeout: float = 8.0) -> str | None:
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        # 아주 단순한 태그 제거 (의존성 없이) — 스코어링엔 충분
        return re.sub(r"<[^>]+>", " ", r.text)
    except Exception as e:
        logger.debug(f"CB 텍스트 수집 실패 [{url}]: {e}")
        return None


# 최신 정책문 인덱스 페이지 (여기서 본문 텍스트 추출 — 구조 변경 시 unavailable로 정직 강등)
_FED_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary-latest.htm"
_BOK_URL = "https://www.bok.or.kr/portal/singl/newsData/listCont.do?menuNo=200761"

_CACHE: dict = {}
_TTL = 6 * 3600


def cb_sentiment(use_cache: bool = True) -> dict:
    """Fed/BOK 센티먼트 게이지 데이터. 수집 실패 시 available:false(정직 — 합성 금지)."""
    now = time.time()
    if use_cache and _CACHE.get("t", 0) > now - _TTL:
        return _CACHE["v"]
    out: dict = {"as_of": time.strftime("%Y-%m-%d %H:%M"), "banks": {}}
    for bank, url in (("fed", _FED_URL), ("bok", _BOK_URL)):
        txt = _fetch(url)
        if txt and len(txt) > 500:
            s = score_text(txt)
            out["banks"][bank] = {"available": True, "source": url, **s}
        else:
            out["banks"][bank] = {"available": False,
                                  "note": "정책문 수집 실패(네트워크/구조 변경) — 점수 미산출(정직)"}
    out["method"] = "렉시콘 기반(Apel-Grimaldi 사상) 매파/비둘기 용어 밀도 — 결정론·검증 가능"
    _CACHE.update(t=now, v=out)
    return out
