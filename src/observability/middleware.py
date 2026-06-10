"""
요청 로깅 + 일관된 에러 핸들링 미들웨어.
=========================================
- 모든 요청에 추적 ID 부여 + 응답 헤더(X-Request-ID)로 노출
- 요청 시작/완료 로깅 (메서드·경로·상태·소요시간)
- 처리되지 않은 예외를 일관된 JSON으로 변환 (내부 상세는 로그에만, 클라이언트엔 일반 메시지)

main_api.py에서:
    from src.observability.middleware import install_observability
    install_observability(app)
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.observability.logging_config import get_logger, get_request_id, set_request_id

logger = get_logger("api.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """요청별 추적 ID + 접근 로깅 + 예외 안전망."""

    async def dispatch(self, request: Request, call_next):
        # 클라이언트가 X-Request-ID를 보내면 이어받고, 아니면 생성
        set_request_id(request.headers.get("X-Request-ID"))
        start = time.perf_counter()
        method, path = request.method, request.url.path

        try:
            response = await call_next(request)
        except Exception:
            # 처리되지 않은 예외 → 500, 상세는 로그에만 기록 (클라이언트엔 노출 안 함)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                f"{method} {path} → 500 UNHANDLED ({elapsed_ms:.0f}ms)",
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "서버 내부 오류가 발생했습니다.",
                    "request_id": get_request_id(),
                },
                headers={"X-Request-ID": get_request_id()},
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        # 상태 코드별 로그 레벨
        level = logger.warning if response.status_code >= 500 else (
            logger.info if response.status_code >= 400 else logger.info
        )
        level(f"{method} {path} → {response.status_code} ({elapsed_ms:.0f}ms)")
        response.headers["X-Request-ID"] = get_request_id()
        return response


def install_observability(app) -> None:
    """앱에 관측성 미들웨어 + 예외 핸들러 설치."""
    app.add_middleware(RequestContextMiddleware)

    # HTTPException은 그대로 통과(의도된 에러), 그 외 검증되지 않은 예외만 위 미들웨어가 처리.
    logger.info("관측성 미들웨어 설치 완료 (요청 로깅 + 추적 ID + 예외 안전망)")
