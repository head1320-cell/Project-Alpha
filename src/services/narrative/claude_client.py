"""
Claude API Client — Phase 3 AI Narrative Intelligence
========================================================
Anthropic Claude API 통합 클라이언트.

기능:
  · Streaming response (SSE 호환)
  · 자동 재시도 (지수 백오프)
  · Circuit Breaker (연속 실패 → 일시 차단)
  · LRU + TTL 캐싱 (동일 입력 → 캐시)
  · 토큰 사용량 + 비용 추적
  · Anthropic SDK 미설치 시 graceful fallback (Mock 응답)

환경변수:
  ANTHROPIC_API_KEY — Anthropic 콘솔에서 발급
  CLAUDE_MODEL     — claude-sonnet-4-6 등 (default)

방어적 프로그래밍:
  · 모든 API 호출 try/except
  · API key 없으면 Mock 응답 (시스템 정상 동작)
  · Network timeout 60초
  · 동시 호출 제한 (semaphore 3)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Anthropic SDK는 optional dependency
try:
    from anthropic import Anthropic, APIError, RateLimitError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    Anthropic = None
    APIError = Exception
    RateLimitError = Exception
    ANTHROPIC_AVAILABLE = False
    logger.info("anthropic SDK 미설치 — Mock 모드로 동작 (pip install anthropic)")


# ═══════════════════════════════════════════════════════════════════════════════
# Pricing (USD per 1M tokens) — 2025년 기준 Claude Sonnet 4
# ═══════════════════════════════════════════════════════════════════════════════

MODEL_PRICING = {
    "claude-sonnet-4-6":      {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-5":      {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":        {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5":       {"input": 0.80,  "output": 4.00},
}

DEFAULT_MODEL = "claude-sonnet-4-6"
USD_TO_KRW = 1400


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NarrativeRequest:
    """단일 Claude 호출 요청."""
    system_prompt:   str
    user_prompt:     str
    max_tokens:      int = 2000
    temperature:     float = 0.3       # 분석용 → 보수적
    model:           str | None = None
    metadata:        dict = field(default_factory=dict)


@dataclass
class NarrativeResponse:
    """Claude 응답 + 메타데이터."""
    content:         str
    model:           str
    input_tokens:    int = 0
    output_tokens:   int = 0
    total_tokens:    int = 0
    cost_usd:        float = 0.0
    cost_krw:        float = 0.0
    elapsed_seconds: float = 0.0
    cached:          bool = False
    error:           str | None = None
    timestamp:       str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UsageStats:
    """누적 사용량 통계."""
    total_calls:       int = 0
    total_cached:      int = 0
    total_failures:    int = 0
    total_input_tokens:  int = 0
    total_output_tokens: int = 0
    total_cost_usd:    float = 0.0
    total_cost_krw:    float = 0.0
    last_call_at:      str | None = None
    by_model:          dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# LRU + TTL Cache
# ═══════════════════════════════════════════════════════════════════════════════

class _NarrativeCache:
    """동일 입력 → 캐시된 응답."""

    def __init__(self, max_size: int = 200, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, NarrativeResponse]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(req: NarrativeRequest) -> str:
        payload = f"{req.system_prompt}||{req.user_prompt}||{req.model}||{req.temperature}||{req.max_tokens}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def get(self, req: NarrativeRequest) -> NarrativeResponse | None:
        key = self._key(req)
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            ts, resp = entry
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            # 캐시된 응답 복사 + cached=True
            cached_resp = NarrativeResponse(
                **{**resp.__dict__, "cached": True}
            )
            return cached_resp

    def set(self, req: NarrativeRequest, resp: NarrativeResponse):
        key = self._key(req)
        with self._lock:
            if len(self._data) >= self.max_size:
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time(), resp)

    def clear(self):
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl,
            }


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════════

class _CircuitBreaker:
    def __init__(self, threshold: int = 5, reset_seconds: int = 60):
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure: float | None = None
        self.lock = threading.Lock()

    def call_allowed(self) -> bool:
        with self.lock:
            if self.state == "OPEN":
                if self.last_failure and \
                   time.time() - self.last_failure > self.reset_seconds:
                    self.state = "HALF_OPEN"
                    return True
                return False
            return True

    def record_success(self):
        with self.lock:
            self.failures = 0
            self.state = "CLOSED"

    def record_failure(self):
        with self.lock:
            self.failures += 1
            self.last_failure = time.time()
            if self.failures >= self.threshold:
                self.state = "OPEN"


# ═══════════════════════════════════════════════════════════════════════════════
# Claude Client
# ═══════════════════════════════════════════════════════════════════════════════

class ClaudeClient:
    """
    Anthropic Claude API 통합 클라이언트.

    Usage:
        client = ClaudeClient()    # API key는 ANTHROPIC_API_KEY 환경변수

        # 비스트리밍
        resp = client.invoke(NarrativeRequest(
            system_prompt="너는 퀀트 분석가다.",
            user_prompt="삼성전자가 저평가된 이유를 설명해.",
        ))
        print(resp.content)
        print(f"비용: {resp.cost_krw:.0f}원")

        # 스트리밍 (SSE)
        for chunk in client.stream(req):
            print(chunk, end="", flush=True)

        # 사용량 통계
        stats = client.get_usage()
        print(f"총 비용: {stats.total_cost_krw:.0f}원")
    """

    _singleton: ClaudeClient | None = None

    @classmethod
    def get_default(cls) -> ClaudeClient:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        cache_ttl: int = 3600,
        timeout: float = 60.0,
        max_concurrent: int = 3,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("CLAUDE_MODEL", DEFAULT_MODEL)
        self.max_retries = max_retries
        self.timeout = timeout
        self.cache = _NarrativeCache(ttl_seconds=cache_ttl)
        self.circuit = _CircuitBreaker(threshold=5, reset_seconds=60)
        self.usage = UsageStats()
        self._usage_lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)

        # Anthropic 클라이언트 초기화
        self._client = None
        if ANTHROPIC_AVAILABLE and self.api_key:
            try:
                self._client = Anthropic(api_key=self.api_key, timeout=timeout)
            except Exception as e:
                logger.error(f"Anthropic 클라이언트 초기화 실패: {e}")

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    # ─────────────────────────────────────────────────────────────────────
    # invoke (non-streaming)
    # ─────────────────────────────────────────────────────────────────────

    def invoke(self, req: NarrativeRequest) -> NarrativeResponse:
        """일반 호출 (블로킹). 캐시 적중 시 즉시 반환."""
        start = time.time()
        model = req.model or self.model

        # 캐시 체크
        cached = self.cache.get(req)
        if cached:
            with self._usage_lock:
                self.usage.total_cached += 1
                self.usage.last_call_at = datetime.now().isoformat()
            return cached

        # Circuit breaker
        if not self.circuit.call_allowed():
            return self._mock_response(
                req, model,
                error="circuit_open",
                start=start,
            )

        # Mock fallback (API key 없거나 SDK 미설치)
        if not self.is_configured:
            return self._mock_response(req, model, start=start)

        # 실제 API 호출
        with self._semaphore:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = self._client.messages.create(
                        model=model,
                        max_tokens=req.max_tokens,
                        temperature=req.temperature,
                        system=req.system_prompt,
                        messages=[{"role": "user", "content": req.user_prompt}],
                    )
                    self.circuit.record_success()

                    content = "\n".join(
                        block.text for block in response.content
                        if hasattr(block, "text")
                    )

                    input_tok = response.usage.input_tokens
                    output_tok = response.usage.output_tokens
                    cost_usd = self._compute_cost(model, input_tok, output_tok)

                    resp = NarrativeResponse(
                        content=content,
                        model=model,
                        input_tokens=input_tok,
                        output_tokens=output_tok,
                        total_tokens=input_tok + output_tok,
                        cost_usd=cost_usd,
                        cost_krw=cost_usd * USD_TO_KRW,
                        elapsed_seconds=round(time.time() - start, 3),
                    )

                    self.cache.set(req, resp)
                    self._update_usage(resp)
                    return resp

                except RateLimitError as e:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limit (시도 {attempt}/{self.max_retries}): {e}, {wait}초 대기")
                    time.sleep(wait)
                except APIError as e:
                    logger.error(f"API 오류 (시도 {attempt}): {e}")
                    if attempt == self.max_retries:
                        self.circuit.record_failure()
                        return self._error_response(req, model, str(e), start)
                    time.sleep(1.5 * attempt)
                except Exception as e:
                    logger.error(f"예상치 못한 오류: {e}", exc_info=True)
                    self.circuit.record_failure()
                    return self._error_response(req, model, str(e), start)

        self.circuit.record_failure()
        return self._error_response(req, model, "All retries exhausted", start)

    # ─────────────────────────────────────────────────────────────────────
    # stream (SSE-compatible)
    # ─────────────────────────────────────────────────────────────────────

    def stream(self, req: NarrativeRequest) -> Generator[str, None, NarrativeResponse]:
        """
        스트리밍 generator. 사용:
            for chunk in client.stream(req):
                print(chunk, end="", flush=True)
        """
        start = time.time()
        model = req.model or self.model

        # 캐시 적중 시 한 번에 yield
        cached = self.cache.get(req)
        if cached:
            with self._usage_lock:
                self.usage.total_cached += 1
            yield cached.content
            return cached

        if not self.circuit.call_allowed():
            mock = self._mock_response(req, model, error="circuit_open", start=start)
            yield mock.content
            return mock

        if not self.is_configured:
            mock = self._mock_response(req, model, start=start)
            yield mock.content
            return mock

        with self._semaphore:
            full_content = []
            input_tok = output_tok = 0
            try:
                with self._client.messages.stream(
                    model=model,
                    max_tokens=req.max_tokens,
                    temperature=req.temperature,
                    system=req.system_prompt,
                    messages=[{"role": "user", "content": req.user_prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        full_content.append(text)
                        yield text
                    final = stream.get_final_message()
                    input_tok = final.usage.input_tokens
                    output_tok = final.usage.output_tokens

                self.circuit.record_success()
                content = "".join(full_content)
                cost_usd = self._compute_cost(model, input_tok, output_tok)
                resp = NarrativeResponse(
                    content=content, model=model,
                    input_tokens=input_tok, output_tokens=output_tok,
                    total_tokens=input_tok + output_tok,
                    cost_usd=cost_usd, cost_krw=cost_usd * USD_TO_KRW,
                    elapsed_seconds=round(time.time() - start, 3),
                )
                self.cache.set(req, resp)
                self._update_usage(resp)
                return resp
            except Exception as e:
                logger.error(f"Streaming 오류: {e}")
                self.circuit.record_failure()
                err_resp = self._error_response(req, model, str(e), start)
                yield f"\n\n⚠ 스트리밍 중단: {e}"
                return err_resp

    # ─────────────────────────────────────────────────────────────────────
    # Usage tracking
    # ─────────────────────────────────────────────────────────────────────

    def _update_usage(self, resp: NarrativeResponse):
        with self._usage_lock:
            self.usage.total_calls += 1
            self.usage.total_input_tokens += resp.input_tokens
            self.usage.total_output_tokens += resp.output_tokens
            self.usage.total_cost_usd += resp.cost_usd
            self.usage.total_cost_krw += resp.cost_krw
            self.usage.last_call_at = resp.timestamp

            if resp.model not in self.usage.by_model:
                self.usage.by_model[resp.model] = {"calls": 0, "cost_usd": 0.0}
            self.usage.by_model[resp.model]["calls"] += 1
            self.usage.by_model[resp.model]["cost_usd"] += resp.cost_usd

    def get_usage(self) -> UsageStats:
        with self._usage_lock:
            return UsageStats(**self.usage.__dict__)

    def reset_usage(self):
        with self._usage_lock:
            self.usage = UsageStats()

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_cost(model: str, input_tok: int, output_tok: int) -> float:
        pricing = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
        return (input_tok * pricing["input"] + output_tok * pricing["output"]) / 1_000_000

    def _mock_response(
        self, req: NarrativeRequest, model: str,
        error: str | None = None, start: float = 0,
    ) -> NarrativeResponse:
        """API key 없거나 circuit open 시 Mock 응답."""
        if error == "circuit_open":
            content = (
                "⚠ Claude API 일시 차단 (Circuit Breaker OPEN)\n\n"
                "연속 호출 실패로 일시 차단되었습니다. 잠시 후 자동 해제됩니다."
            )
        else:
            content = self._generate_mock_narrative(req)

        return NarrativeResponse(
            content=content, model=model,
            input_tokens=0, output_tokens=0, total_tokens=0,
            cost_usd=0, cost_krw=0,
            elapsed_seconds=round(time.time() - start, 3) if start else 0,
            error=error or ("Mock 모드 (API key 미설정)" if not self.api_key else None),
        )

    def _error_response(
        self, req: NarrativeRequest, model: str, error: str, start: float,
    ) -> NarrativeResponse:
        return NarrativeResponse(
            content=f"⚠ API 호출 실패: {error}\n\nMock 응답을 사용해 계속 진행할 수 있습니다.",
            model=model,
            error=error,
            elapsed_seconds=round(time.time() - start, 3),
        )

    @staticmethod
    def _generate_mock_narrative(req: NarrativeRequest) -> str:
        """API 미설정 시 데모용 narrative 생성."""
        # User prompt에서 키워드 추출
        prompt_lower = req.user_prompt.lower()

        if "종목" in req.user_prompt or "stock" in prompt_lower:
            return MOCK_STOCK_NARRATIVE
        elif "포트폴리오" in req.user_prompt or "portfolio" in prompt_lower or "백테스트" in req.user_prompt:
            return MOCK_PORTFOLIO_NARRATIVE
        elif "매크로" in req.user_prompt or "regime" in prompt_lower:
            return MOCK_MACRO_NARRATIVE
        elif "kill" in prompt_lower or "운영" in req.user_prompt:
            return MOCK_OPS_NARRATIVE
        else:
            return MOCK_GENERAL_NARRATIVE


# ═══════════════════════════════════════════════════════════════════════════════
# Mock narratives (Claude API 미설정 시 데모용)
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_STOCK_NARRATIVE = """# 종목 분석 — Mock 데모

## 핵심 평가
현재가는 적정가 대비 약 25% 할인된 수준으로 거래되고 있습니다. 3가지 가치평가 모델 모두 일관되게 저평가 신호를 보내고 있으며, 특히 RIM(잔여이익모델)에서 가장 두드러진 차이를 보입니다.

## 저평가 요인 분해
1. **수익성 우위**: ROE 12.5%로 자기자본비용(약 9.5%)을 큰 폭으로 초과 — 잔여이익 누적 효과
2. **현금흐름 안정성**: 최근 5년 FCF 누적 흑자 유지, CapEx 통제 양호
3. **재무 건전성**: 부채비율 38%로 업종 평균(65%) 대비 매우 보수적

## 위험 요인
- 매출 성장률 둔화 (YoY +3.2% vs 5년 평균 +8%)
- 환율 노출도 60%로 KRW 강세 시 영업이익 압박

## 결론
**저평가 우량주 등급.** 단, 진입 시점은 매크로 PANIC 국면 해제 확인 후 권장.

> ⚠ 본 분석은 Anthropic API 키 미설정 시 표시되는 Mock 응답입니다.
> 실제 분석을 위해서는 `.env`에 `ANTHROPIC_API_KEY`를 설정하세요.
"""

MOCK_PORTFOLIO_NARRATIVE = """# 포트폴리오 백테스트 보고서 — Mock 데모

## 종합 성과
- **누적 수익률**: +77.6% (522일)
- **연환산 수익률**: 24.3%
- **Sharpe 비율**: 2.56 (우수)
- **최대 낙폭**: -6.27% (양호)

## 5-Factor Attribution 분석
| 요인 | 기여도 | 해석 |
|---|---|---|
| Allocation (전략 가중치) | +18.4%p | 모멘텀 전략 비중 적절 |
| Selection (종목 선정) | +12.7%p | 반도체 sector 정확한 타이밍 |
| Macro Regime | +5.2%p | Goldilocks 국면 활용 |
| Netting (Long/Short) | +1.8%p | 페어 트레이딩 효과 |
| Cost (거래비용) | -2.1%p | Square Root Law 임팩트 |

## 핵심 관찰
2024년 3월 매크로 STAGFLATION 진입 시점에 자동 defensive mode가 발동되어 -8% 손실을 -3.5%로 줄였습니다. Stage 12 Regime-Adaptive Allocator의 효과가 명확히 입증된 사례입니다.

## Counterfactual 분석
이 시기에 regime adjustment를 비활성화했다면 누적 수익률은 **+62%로 감소** (현재 대비 -15.6%p)했을 것입니다.

> ⚠ Mock 응답 — 실제 분석은 ANTHROPIC_API_KEY 설정 필요.
"""

MOCK_MACRO_NARRATIVE = """# 매크로 브리핑 — Mock 데모

## 현재 국면: GOLDILOCKS
- **Systemic Risk Score**: 38 / 100 (정상 수준)
- **VIX**: 14.2 (낮음, 안정)
- **T10Y2Y Spread**: +18bp (정상화 진행)
- **DXY Trend**: 약세 전환 (-2.4% MoM)
- **Gold**: 횡보, 안전자산 수요 제한적

## 시사점
1. 위험자산 비중 확대 적기 — Stage 11 strategy의 매수 신호 신뢰도 높음
2. T10Y2Y 정상화 → 금융주 sector 모멘텀 양호
3. DXY 약세 → 수출주 환차익 기대

## 모니터링 포인트
- VIX 20 돌파 시 → CAUTIOUS mode 자동 전환
- T10Y2Y 다시 역전 → 침체 위험 재점화 신호

> ⚠ Mock 응답
"""

MOCK_OPS_NARRATIVE = """# 운영 사건 분석 — Mock 데모

## Kill Switch 이벤트 — 2025-XX-XX 14:23
- **트리거**: `auto_dd` (누적 drawdown -10.3% 초과)
- **자산**: 발동 시점 90,200,000원 (시작 100M 대비)
- **청산 모드**: `hold` (미체결 취소만, 포지션 유지)

## 원인 분석
1. **직접 트리거**: 누적 DD 한도 -10% 초과 (실제 -10.3%)
2. **선행 신호**: 5거래일 연속 일일 손실, Stage 9 systemic risk 78점 도달
3. **시장 환경**: VIX 28 (CAUTIOUS 임계값 25 초과)

## 사후 검증
- 미체결 12건 즉시 취소 ✓
- Slack 알림 발송 성공 ✓
- Audit log 28개 이벤트 영구 기록 ✓

## 권고사항
- 향후 systemic_risk_score ≥ 70 시 점진적 비중 축소 룰 추가 검토
- Trailing stop 도입 (각 포지션 -5% 시 자동 매도)

> ⚠ Mock 응답
"""

MOCK_GENERAL_NARRATIVE = """# AI 분석 — Mock 응답

본 시스템은 Anthropic Claude API를 통해 다음 영역의 자연어 분석을 제공합니다:

1. **종목 분석** — 가치평가 + 재무 + 매크로 통합 해석
2. **포트폴리오 보고서** — 백테스트 결과 + 5-Factor Attribution
3. **매크로 브리핑** — Regime 판정 + 시장 시사점
4. **운영 사건 분석** — Kill switch / drift / audit 사후 해석
5. **Counterfactual** — "이 결정이 없었다면?" 시나리오
6. **일일 요약** — 모든 활동 통합 요약

> ⚠ 실제 분석을 위해 `.env`에 `ANTHROPIC_API_KEY`를 설정하세요.
"""
