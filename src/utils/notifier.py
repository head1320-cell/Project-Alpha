"""
Real-time Notifier — Slack/Discord 알림 시스템
===================================================
실거래 운영 중 critical 이벤트를 즉시 사용자에게 전달.

설계 원칙 (방어적 프로그래밍):
  · 네트워크 호출은 절대 메인 흐름을 막지 않음 (background thread)
  · Webhook 실패 시 graceful degradation (로컬 로그로 fallback)
  · 동일 메시지 throttle (60초 dedup, 폭주 방지)
  · 큐 max_size 제한 (메모리 폭주 방지)
  · 모든 외부 호출 try/except
  · Secret은 환경변수에서만 읽기

등급별 처리:
  CRITICAL — 🚨 빨강, Slack+Discord 모두 발송, dedup 30초
  WARN     — ⚠️  노랑, Slack+Discord, dedup 120초
  INFO     — ℹ️  초록, Slack만, dedup 300초

Webhook 미설정 시:
  · 모든 호출은 로컬 로그로만 (시스템 정상 동작)
  · 환경변수 SLACK_WEBHOOK_URL / DISCORD_WEBHOOK_URL
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

class NotificationSeverity(IntEnum):
    INFO     = 0
    WARN     = 1
    CRITICAL = 2


SEVERITY_CONFIG = {
    NotificationSeverity.CRITICAL: {
        "emoji":        "🚨",
        "color":        "#FF6B6B",
        "discord_color": 0xFF6B6B,
        "label":        "CRITICAL",
        "dedup_seconds": 30,
        "channels":     ["slack", "discord"],
    },
    NotificationSeverity.WARN: {
        "emoji":        "⚠️",
        "color":        "#FFC857",
        "discord_color": 0xFFC857,
        "label":        "WARN",
        "dedup_seconds": 120,
        "channels":     ["slack", "discord"],
    },
    NotificationSeverity.INFO: {
        "emoji":        "ℹ️",
        "color":        "#DEFF9A",
        "discord_color": 0xDEFF9A,
        "label":        "INFO",
        "dedup_seconds": 300,
        "channels":     ["slack"],
    },
}


@dataclass
class NotifierConfig:
    """알림 시스템 설정."""
    slack_webhook_url:   str | None = None
    discord_webhook_url: str | None = None
    max_queue_size:      int = 1000
    worker_count:        int = 1
    request_timeout:     float = 5.0
    max_retries:         int = 2
    retry_backoff:       float = 1.5
    enable_dedup:        bool = True
    fallback_to_log:     bool = True


@dataclass
class _NotificationMessage:
    """내부 큐 메시지."""
    severity:  int
    title:     str
    message:   str
    context:   dict = field(default_factory=dict)
    timestamp: float = 0
    msg_hash:  str = ""


@dataclass
class NotifierStats:
    """알림 시스템 통계 (모니터링용)."""
    total_enqueued:    int = 0
    total_sent:        int = 0
    total_failed:      int = 0
    total_dedup_skip:  int = 0
    queue_full_drops:  int = 0
    by_severity: dict = field(default_factory=lambda: {
        "INFO": 0, "WARN": 0, "CRITICAL": 0,
    })
    last_sent_at:      str | None = None
    last_error:        str | None = None
    worker_alive:      bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# Notifier
# ═══════════════════════════════════════════════════════════════════════════════

class Notifier:
    """
    실시간 알림 시스템.

    Usage:
        notifier = Notifier(NotifierConfig(
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
        ))
        notifier.start()

        # Critical (Kill switch 등)
        notifier.critical(
            title="Kill Switch Triggered",
            message="누적 drawdown -10% 초과",
            context={"equity": 90_000_000, "dd_pct": -10.2},
        )

        # Warn (Risk warnings)
        notifier.warn(
            title="Market Impact 경고",
            message="삼성전자 주문 임팩트 75bp 추정",
        )

        # Info (Order fills)
        notifier.info(
            title="체결 완료",
            message="005930 100주 @ 70,000원",
        )

        # 종료
        notifier.stop()
    """

    _singleton: Notifier | None = None

    @classmethod
    def get_default(cls) -> Notifier:
        """싱글톤 인스턴스 (편의용)."""
        if cls._singleton is None:
            cls._singleton = cls(NotifierConfig(
                slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
                discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
            ))
            cls._singleton.start()
        return cls._singleton

    def __init__(self, config: NotifierConfig | None = None):
        self.config = config or NotifierConfig()
        self._queue: queue.Queue = queue.Queue(maxsize=self.config.max_queue_size)
        self._dedup_cache: dict = {}
        self._dedup_lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self.stats = NotifierStats()

    # ─────────────────────────────────────────────────────────────────────
    # 공개 API
    # ─────────────────────────────────────────────────────────────────────

    def start(self):
        """백그라운드 worker 시작."""
        if self._workers:
            return
        for i in range(max(1, self.config.worker_count)):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"NotifierWorker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)
        self.stats.worker_alive = True

    def stop(self, timeout: float = 5.0):
        """알림 큐 비우고 worker 종료."""
        self._stop_event.set()
        for t in self._workers:
            t.join(timeout=timeout)
        self._workers.clear()
        self.stats.worker_alive = False

    def critical(self, title: str, message: str, context: dict | None = None):
        self._enqueue(NotificationSeverity.CRITICAL, title, message, context or {})

    def warn(self, title: str, message: str, context: dict | None = None):
        self._enqueue(NotificationSeverity.WARN, title, message, context or {})

    def info(self, title: str, message: str, context: dict | None = None):
        self._enqueue(NotificationSeverity.INFO, title, message, context or {})

    def get_stats(self) -> dict:
        """현재 큐 + 워커 상태."""
        return {
            **self.stats.__dict__,
            "queue_size":      self._queue.qsize(),
            "queue_max":       self.config.max_queue_size,
            "workers_running": sum(1 for t in self._workers if t.is_alive()),
            "slack_configured":   bool(self.config.slack_webhook_url),
            "discord_configured": bool(self.config.discord_webhook_url),
        }

    def test_send(self) -> dict:
        """수동 테스트 알림."""
        ts = datetime.now().isoformat()
        self.info(
            title="알림 시스템 테스트",
            message=f"테스트 메시지 ({ts})",
            context={"test": True},
        )
        return {"sent": True, "timestamp": ts}

    # ─────────────────────────────────────────────────────────────────────
    # 내부: enqueue (방어적)
    # ─────────────────────────────────────────────────────────────────────

    def _enqueue(self, severity: int, title: str, message: str, context: dict):
        """안전한 큐 삽입 (예외 절대 전파 X)."""
        try:
            # 입력 sanitize
            title = str(title)[:200]
            message = str(message)[:2000]

            # Dedup 처리
            if self.config.enable_dedup:
                msg_hash = self._compute_hash(severity, title, message)
                if self._is_duplicate(msg_hash, severity):
                    self.stats.total_dedup_skip += 1
                    return

            now = time.time()
            msg = _NotificationMessage(
                severity=severity, title=title, message=message,
                context=context or {}, timestamp=now,
                msg_hash=self._compute_hash(severity, title, message),
            )

            try:
                self._queue.put_nowait(msg)
                self.stats.total_enqueued += 1
                label = SEVERITY_CONFIG[severity]["label"]
                self.stats.by_severity[label] = self.stats.by_severity.get(label, 0) + 1
            except queue.Full:
                self.stats.queue_full_drops += 1
                logger.error(
                    f"Notifier queue 가득 참 — 메시지 drop "
                    f"(severity={severity}, title={title!r})"
                )
                # Fallback: 로컬 로그
                self._log_fallback(severity, title, message)
        except Exception as e:
            # _enqueue 자체가 절대 예외 던지지 않도록
            logger.error(f"Notifier enqueue 오류: {e}", exc_info=True)

    def _compute_hash(self, severity, title, message) -> str:
        key = f"{severity}|{title[:80]}|{message[:120]}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    def _is_duplicate(self, msg_hash: str, severity: int) -> bool:
        """동일 메시지 throttle window 내 발송 여부."""
        with self._dedup_lock:
            now = time.time()
            last = self._dedup_cache.get(msg_hash, 0)
            dedup_seconds = SEVERITY_CONFIG[severity]["dedup_seconds"]

            if now - last < dedup_seconds:
                return True

            self._dedup_cache[msg_hash] = now

            # 캐시 사이즈 제한 (LRU 대신 단순 truncate)
            if len(self._dedup_cache) > 1000:
                # 가장 오래된 절반 제거
                sorted_items = sorted(self._dedup_cache.items(), key=lambda x: x[1])
                self._dedup_cache = dict(sorted_items[500:])
            return False

    # ─────────────────────────────────────────────────────────────────────
    # 내부: worker loop
    # ─────────────────────────────────────────────────────────────────────

    def _worker_loop(self):
        """백그라운드 dispatch 루프."""
        while not self._stop_event.is_set():
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker queue.get 오류: {e}")
                continue

            try:
                self._dispatch(msg)
            except Exception as e:
                logger.error(f"Notification dispatch 오류: {e}", exc_info=True)
                self.stats.total_failed += 1
                self.stats.last_error = str(e)[:200]
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────────
    # 내부: 실제 전송
    # ─────────────────────────────────────────────────────────────────────

    def _dispatch(self, msg: _NotificationMessage):
        """메시지를 등급에 맞는 채널들로 전송."""
        cfg = SEVERITY_CONFIG[msg.severity]
        channels = cfg["channels"]

        sent_any = False

        if "slack" in channels and self.config.slack_webhook_url:
            ok = self._send_slack(msg, cfg)
            sent_any = sent_any or ok

        if "discord" in channels and self.config.discord_webhook_url:
            ok = self._send_discord(msg, cfg)
            sent_any = sent_any or ok

        if sent_any:
            self.stats.total_sent += 1
            self.stats.last_sent_at = datetime.now().isoformat()
        else:
            # 모든 채널 비활성 또는 실패 시 fallback
            if self.config.fallback_to_log:
                self._log_fallback(msg.severity, msg.title, msg.message)

    def _send_slack(self, msg: _NotificationMessage, cfg: dict) -> bool:
        """Slack incoming webhook 전송."""
        if requests is None:
            return False

        payload = {
            "attachments": [{
                "color": cfg["color"],
                "title": f"{cfg['emoji']} [{cfg['label']}] {msg.title}",
                "text":  msg.message,
                "fields": [
                    {"title": k, "value": str(v)[:200], "short": True}
                    for k, v in list(msg.context.items())[:8]
                ] if msg.context else [],
                "footer": "FICC Risk Platform · Stage 13",
                "ts":     int(msg.timestamp),
            }]
        }

        return self._post_webhook(self.config.slack_webhook_url, payload, "slack")

    def _send_discord(self, msg: _NotificationMessage, cfg: dict) -> bool:
        """Discord webhook 전송."""
        if requests is None:
            return False

        embed = {
            "title":       f"{cfg['emoji']} [{cfg['label']}] {msg.title}"[:256],
            "description": msg.message[:2000],
            "color":       cfg["discord_color"],
            "timestamp":   datetime.fromtimestamp(msg.timestamp).isoformat(),
            "footer":      {"text": "FICC Risk Platform · Stage 13"},
        }
        if msg.context:
            embed["fields"] = [
                {"name": str(k)[:80], "value": str(v)[:200], "inline": True}
                for k, v in list(msg.context.items())[:6]
            ]

        payload = {"embeds": [embed]}
        return self._post_webhook(self.config.discord_webhook_url, payload, "discord")

    def _post_webhook(self, url: str, payload: dict, channel: str) -> bool:
        """Webhook POST with retries."""
        attempts = 0
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                resp = requests.post(
                    url, json=payload, timeout=self.config.request_timeout,
                )
                # Slack returns 200, Discord 204
                if resp.status_code in (200, 204):
                    return True
                logger.warning(
                    f"{channel} webhook HTTP {resp.status_code} "
                    f"(attempt {attempts}/{self.config.max_retries + 1})"
                )
            except requests.RequestException as e:
                logger.warning(f"{channel} webhook 요청 실패 (시도 {attempts}): {e}")
            except Exception as e:
                logger.error(f"{channel} webhook 예외: {e}")
                return False

            if attempts <= self.config.max_retries:
                time.sleep(self.config.retry_backoff * attempts)

        return False

    @staticmethod
    def _log_fallback(severity: int, title: str, message: str):
        """Webhook 실패 시 로컬 로그로."""
        label = SEVERITY_CONFIG[severity]["label"]
        full = f"[NOTIFIER FALLBACK {label}] {title}: {message}"
        if severity == NotificationSeverity.CRITICAL:
            logger.critical(full)
        elif severity == NotificationSeverity.WARN:
            logger.warning(full)
        else:
            logger.info(full)
