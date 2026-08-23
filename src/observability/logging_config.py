"""
구조화 로깅 설정 — 운영 관측성(observability) 기반.
==================================================
- 일관된 포맷 (시각·레벨·모듈·요청ID·메시지)
- 요청별 추적 ID (contextvar로 전파)
- 환경변수로 레벨/포맷 제어 (LOG_LEVEL, LOG_JSON)
- JSON 모드 지원 (로그 수집 시스템 연동용)

사용:
    from src.observability.logging_config import setup_logging, get_logger
    setup_logging()                 # 앱 시작 시 1회
    logger = get_logger(__name__)
    logger.info("메시지", extra={"key": "value"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar

# 요청별 추적 ID (미들웨어가 설정, 로그에 자동 포함)
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(rid: str | None = None) -> str:
    """현재 컨텍스트의 요청 ID 설정 (없으면 생성)."""
    rid = rid or uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()


class _ContextFilter(logging.Filter):
    """모든 로그 레코드에 request_id 주입."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class _JsonFormatter(logging.Formatter):
    """JSON 라인 포맷 (로그 수집기 연동용)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # extra 필드 병합 (표준 속성 제외)
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"request_id", "taskName"}

_TEXT_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | [%(request_id)s] | %(message)s"


def setup_logging(level: str | None = None, json_mode: bool | None = None) -> None:
    """앱 전역 로깅 설정. 멱등(여러 번 호출해도 핸들러 중복 없음)."""
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    use_json = json_mode if json_mode is not None else (os.getenv("LOG_JSON", "0") == "1")

    root = logging.getLogger()
    root.setLevel(lvl)

    # 기존 핸들러 제거 (멱등)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(_JsonFormatter() if use_json else logging.Formatter(_TEXT_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)

    # 시끄러운 서드파티 로거 진정
    for noisy in ("urllib3", "httpx", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
