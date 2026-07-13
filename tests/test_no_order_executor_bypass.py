"""OrderExecutor(src.kis_order_executor) 직접 생성 우회 방지 — CI 가드.

src.kis_order_executor.OrderExecutor는 자체 안전장치가 전혀 없다(dry-run/한도/
킬스위치 검증 없이 곧장 client.place_order()를 호출) — 이 클래스에 안전장치를
적용하는 것은 오직 TradingEngine(src/engine/trading_engine.py, SafetyConfig)의
책임이다. 예전엔 main_api.py의 /api/v1/orders/execute·batch가 이 클래스를
TradingEngine 없이 `OrderExecutor(KISClient())`로 직접 생성해 6중 안전장치를
완전히 우회했다(Part 4에서 TradingEngine 경유로 재배선 — 이 테스트가 재발을
정적으로 차단).

이름만 같은 별개 클래스 src.execution.order_executor.OrderExecutor(Stage13 전용,
kill_switch/risk_gateway/audit_trail을 자체 구현)는 이 가드의 대상이 아니다 —
CLAUDE.md 승인 계획에서 명시적으로 범위 밖(별도 안전장치 시스템)으로 남겨짐.
같은 모듈의 PositionManager(읽기 전용 — 주문 능력 없음) import도 대상 아님.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SANCTIONED_FILE = "src/engine/trading_engine.py"

# from src.kis_order_executor import (... OrderExecutor ...) — PositionManager만 쓰는
# import는 매치하지 않도록 단어 경계(\b)로 OrderExecutor를 명시적으로 찾는다.
_IMPORT_RE = re.compile(r"from\s+src\.kis_order_executor\s+import\s+[^\n]*\bOrderExecutor\b")


def _scan_targets():
    yield REPO_ROOT / "main_api.py"
    yield from (REPO_ROOT / "src").rglob("*.py")


def test_import_regex_detects_bad_pattern():
    """가드 정규식이 실제로 위반 패턴을 잡아내는지(무의미하게 항상 통과하지 않는지) 확인."""
    bad = "from src.kis_order_executor import OrderExecutor\nexecutor = OrderExecutor(client)\n"
    assert _IMPORT_RE.search(bad)

    ok_position_only = "from src.kis_order_executor import PositionManager\n"
    assert not _IMPORT_RE.search(ok_position_only)

    ok_unrelated_class = "from src.execution.order_executor import OrderExecutor\n"
    assert not _IMPORT_RE.search(ok_unrelated_class)


def test_kis_order_executor_only_imported_from_trading_engine():
    violations = []
    for path in _scan_targets():
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == SANCTIONED_FILE:
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        if _IMPORT_RE.search(src):
            violations.append(rel)
    assert violations == [], (
        "src.kis_order_executor.OrderExecutor는 TradingEngine(safety=SafetyConfig) 없이 "
        f"직접 생성 금지(6중 안전장치 우회) — {SANCTIONED_FILE} 밖에서 import됨: {violations}"
    )
