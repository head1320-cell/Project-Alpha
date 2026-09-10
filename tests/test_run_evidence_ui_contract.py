"""화면이 읽는 키가 **실제로 오는가** — 새 진단 셋의 프런트 계약

B2 에서 배운 것: 프런트는 백엔드가 준 것만 그린다. 화면이 `pb.mixed_tickers` 를
읽는데 백엔드가 그 키를 안 보내면 **조용히 `undefined`** 가 되고, 진단 줄이
사라지거나 "undefined종목" 이 뜬다. 타입스크립트는 런타임 응답을 검사하지 않는다.

프런트에 유닛 러너가 없어(Playwright 뿐) 소스를 읽어 키를 맞춘다 —
`test_fundamentals_pit_meta.py` §⑦ 과 같은 기법이고, 그 파일이 이미 `fp.` 를
같은 방식으로 건다.

★그리고 R1 이 고친 결함이 정확히 이 부류였다★ — 화면과 렌더러는 멀쩡한데
가운데 통로가 끊겨 아무것도 안 그려졌다. 그때는 이 검사가 없었다.
"""
import os
import pathlib
import re

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.engine.universe_select as US  # noqa: E402
from src.api.screener_routes import (  # noqa: E402
    ScreenToBacktestRequest,
    _screen_to_backtest_core,
)
from src.data.price_quality import (  # noqa: E402
    BASIS_UNIFORM_ADJUSTED,
    STATE_ADJUSTED,
    basis_rollup,
)
from src.engine.run_evidence import (  # noqa: E402
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    pit_evidence,
)

_TSX = pathlib.Path("frontend/src/widgets/backtester/BacktestResults.tsx")
_AST = {"logic": "AND", "conditions": [], "groups": []}


def _fn_body(name: str) -> str:
    """TSX 에서 함수 하나의 본문만 잘라낸다 — 다른 함수의 참조가 섞이지 않게."""
    src = _TSX.read_text(encoding="utf-8")
    start = src.index(f"function {name}(")
    return src[start:src.index("\n}\n", start)]


def _refs(body: str, var: str) -> set[str]:
    """`var.<키>` / `var?.<키>` 참조 — 옵셔널 체이닝도 같은 계약이다."""
    return set(re.findall(rf"\b{var}\??\.(\w+)", body))


# ═══════════════════════════════════════════════════════════════════════════
# 가격 정의
# ═══════════════════════════════════════════════════════════════════════════

def _price_meta() -> dict:
    return basis_rollup({"000660": BASIS_UNIFORM_ADJUSTED},
                        {"000660": STATE_ADJUSTED})


def test_the_price_lines_read_only_keys_the_backend_sends():
    keys = _refs(_fn_body("priceHonesty"), "pb")
    assert keys, "`pb.` 참조를 찾지 못했다 — 이 검사가 공허하다"
    missing = keys - set(_price_meta())
    assert not missing, f"화면이 읽는데 백엔드가 안 보내는 키: {sorted(missing)}"


def test_the_price_lines_read_only_real_sub_keys():
    """`pb.basis.<상태>` 도 계약이다 — 이름이 틀리면 조용히 0 으로 읽힌다."""
    body = _fn_body("priceHonesty")
    names = set(re.findall(r"\bpb\.basis\??\.(\w+)", body))
    assert names, "`pb.basis.` 참조를 찾지 못했다 — 이 검사가 공허하다"
    missing = names - set(_price_meta()["basis"])
    assert not missing, f"백엔드가 내지 않는 basis 상태: {sorted(missing)}"


# ═══════════════════════════════════════════════════════════════════════════
# 유니버스 — ★라우트가 실제로 내는 것과 맞춘다★
# ═══════════════════════════════════════════════════════════════════════════

def _universe_meta(monkeypatch) -> dict:
    class _Item:
        stock_code, corp_name, composite_score = "005930", "삼성전자", 1.0

    monkeypatch.setattr("src.api.screener_routes.get_screener",
                        lambda: type("S", (), {"run": lambda self, **k: type(
                            "R", (), {"items": [_Item()]})()})())
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", lambda **kw: {
        "error": False, "result": {"statistics": {}, "equity_curve": [],
                                   "equity_dates": [], "drawdown_curve": [],
                                   "monthly_returns": [], "trades": []}})
    monkeypatch.setattr(US, "tickers_asof", lambda d: [])
    out = _screen_to_backtest_core(ScreenToBacktestRequest(
        filter_ast=_AST, buy_conditions=None, sell_conditions=None,
        universe="all_asof", start_date="2023-01-02"))
    return out["universe"]


def test_the_universe_lines_read_only_keys_the_backend_sends(monkeypatch):
    keys = _refs(_fn_body("universeHonesty"), "uv")
    assert keys, "`uv.` 참조를 찾지 못했다 — 이 검사가 공허하다"
    missing = keys - set(_universe_meta(monkeypatch))
    assert not missing, f"화면이 읽는데 백엔드가 안 보내는 키: {sorted(missing)}"


def test_the_survivorship_values_the_screen_names_are_real():
    """★값도 계약이다★ 화면이 `"corrected"` 를 `"corrected_"` 로 적으면 조용히 빗나간다."""
    body = _fn_body("universeHonesty")
    named = set(re.findall(r'uv\.survivorship === "(\w+)"', body))
    assert named, "생존편향 값 비교를 찾지 못했다 — 이 검사가 공허하다"
    real = {US.SURVIVORSHIP_CORRECTED, US.SURVIVORSHIP_APPROXIMATED,
            US.SURVIVORSHIP_NOT_CORRECTED, US.SURVIVORSHIP_UNKNOWN}
    assert not named - real, f"백엔드에 없는 값: {sorted(named - real)}"


# ═══════════════════════════════════════════════════════════════════════════
# 판정 배지 — ★양방향★ 빠져도 넘쳐도 안 된다
# ═══════════════════════════════════════════════════════════════════════════

def _badge_keys() -> set[str]:
    src = _TSX.read_text(encoding="utf-8")
    block = src[src.index("const PIT_BADGE"):]
    block = block[:block.index("};")]
    return set(re.findall(r"^\s{2}(\w+):", block, re.M))


def test_the_badge_knows_every_status_the_backend_can_emit():
    """★모르는 상태가 오면 배지가 조용히 다른 라벨을 단다★"""
    backend = {STATUS_VERIFIED, STATUS_PARTIAL, STATUS_UNVERIFIED, STATUS_UNKNOWN}
    assert not backend - _badge_keys(), (
        f"화면이 모르는 판정: {sorted(backend - _badge_keys())}")


def test_the_badge_invents_no_status_of_its_own():
    """★짝★ 백엔드에 없는 상태를 화면이 들고 있으면 죽은 분기다."""
    backend = {STATUS_VERIFIED, STATUS_PARTIAL, STATUS_UNVERIFIED, STATUS_UNKNOWN}
    assert not _badge_keys() - backend, (
        f"백엔드가 내지 않는 판정: {sorted(_badge_keys() - backend)}")


def test_the_result_body_reads_only_evidence_keys_the_backend_sends():
    """배지·진단 목록이 읽는 `pit_evidence.<키>`."""
    src = _TSX.read_text(encoding="utf-8")
    keys = set(re.findall(r"\bres\.pit_evidence\??\.(\w+)", src))
    assert keys, "`res.pit_evidence.` 참조를 찾지 못했다 — 이 검사가 공허하다"
    produced = pit_evidence(price_basis=_price_meta(),
                            universe={"survivorship": "corrected", "reason": None},
                            macro_lookahead=None, fundamentals_pit=None)
    missing = keys - set(produced)
    assert not missing, f"화면이 읽는데 백엔드가 안 보내는 키: {sorted(missing)}"


# ═══════════════════════════════════════════════════════════════════════════
# ★테스트의 테스트★ — 항상 통과하는 검사를 배제한다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_tripwire_notices_a_key_the_backend_does_not_send():
    assert {"state", "지어낸키"} - set(_price_meta()) == {"지어낸키"}


def test_the_body_slicer_does_not_swallow_the_next_function():
    """★함수 경계를 못 자르면 다른 함수의 참조가 섞여 검사가 거짓이 된다★"""
    body = _fn_body("priceHonesty")
    assert "function universeHonesty" not in body, "본문 절단이 다음 함수까지 먹었다"
    assert "pb.state" in body, "본문 절단이 너무 짧다"
