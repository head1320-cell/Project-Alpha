"""★트립와이어★ — 성과 숫자를 그리는 위젯은 **무슨 성과인지** 말해야 한다 (Z4).

설계: 애드덤 §4 / 합격기준 #3 · 어휘 `src/domain/perf_kind.py` ·
컴포넌트 `frontend/src/shared/ui/PerfLabel.tsx`.

★왜 pytest 가 프런트를 검사하는가★
─────────────────────────────────────────────────────────────────────────────
프런트에는 유닛 러너가 없다(Playwright E2E 와 `tsc` 뿐). 저장소는 이미 같은 이유로
프런트 계약을 pytest 로 걸어 왔다 — `tests/test_css_specificity_guard.py` ·
`tests/test_run_evidence_ui_contract.py`. 이 파일은 그 선례를 따른다.

★이 테스트가 막는 것은 "인스턴스" 가 아니라 "부류" 다★
지금 라벨을 붙인 열 개 화면이 아니라, **앞으로 생길** 라벨 없는 성과 화면을 막는다.
그래서 허용 목록은 짧고 **줄마다 사유가 있어야** 한다(아래 `ALLOWED` 의 값이 사유이고,
비어 있으면 테스트가 실패한다).

★계획에서 벗어난 지점 — 검출기를 돌려 보고 고쳤다★
계획(Z)의 부착 목록은 일곱이었다. 검출기를 실제로 돌리자 **넷이 더** 나왔다:
`CustomBacktestRunner` · `ParameterOptimizer` · `StrategyModal` · (그리고 위험
지표만 그리는) `CompanyCockpit`. 앞의 셋은 붙였고 넷째는 사유를 적어 허용했다.
목록을 손으로 세었으면 셋을 놓쳤다.

★문자열을 제외하지 않는다 — 계획 문장에서 의도적으로 벗어난다★
계획은 "주석/문자열에만 나오는 표기는 위반이 아니다" 라고 적었다. 그런데 이 저장소에서
지표 **라벨은 문자열 리터럴로 산다**(`{ key: "sharpe_ratio", label: "Sharpe" }`).
문자열을 빼면 검출기가 거의 장님이 된다(실측: 검출 28 → 대부분 소멸). 그래서
**주석만** 벗긴다. 그 선택이 옳은지는 아래 ⑪⑫ 짝이 못 박는다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[1] / "frontend"
WIDGETS = FRONTEND / "src" / "widgets"
COMPONENT = FRONTEND / "src" / "shared" / "ui" / "PerfLabel.tsx"

#: 성과 통계를 그린다는 **구조적** 신호. 한글 산문("수익률")은 너무 넓어 쓰지 않는다 —
#: 종목 수익률·기여도·기대수익 등 성과가 아닌 자리에도 나온다(실측 28개 중 9개).
METRIC_TOKENS = (
    r"total_return_pct", r"annualized_return_pct", r"sharpe_ratio", r"\bsharpe\b",
    r"max_drawdown_pct", r"\bcagr\b", r"sortino", r"calmar",
)

#: ★사유 없는 면제는 없다★ 값이 빈 문자열이면 아래 테스트가 실패한다.
ALLOWED: dict[str, str] = {
    "src/widgets/backtester/BacktestResults.tsx":
        "기존 `brun-badge`(PIT 시점정합) 배지를 유지한다 — E2E `backtest.spec.ts` 가 "
        "`.brun-*` 를 다수 단정하므로 이 커밋에서 건드리지 않는다(ADR 001).",
    "src/widgets/backtester/TerminalBacktester.tsx":
        "기존 `tbt-prov`(실데이터/합성) 배지를 유지한다 — 데이터 축은 이미 말하고 있다.",
    "src/widgets/allocation/PolicyBacktest.tsx":
        "기존 `as-bt-badge`(데이터+OOS) 배지를 유지한다 — `allocation-stages2.spec.ts:361` "
        "이 클래스를 붙잡고 있다.",
    "src/widgets/landing/HeroDeckLive.tsx":
        "랜딩 데모다. 숫자 옆에 '예시 수치' 캡션이 이미 붙어 있어 라벨보다 강하게 "
        "말하고 있다 — 같은 자리에 두 문장이 겹치면 오히려 약해진다.",
    "src/widgets/realism/RealismKPIs.tsx":
        "위젯의 요점 자체가 '백테스트 대 현실' 비교이고, 카드마다 "
        "'백테스트 과대평가 위험' 같은 자체 판정 문구를 낸다.",
    "src/widgets/realism/ComparativeEquityChart.tsx":
        "같은 대시보드(`RealismDashboard`)가 헤더에 `Mock Data / Live Backend` 를 "
        "상시 표시한다(데이터 축) — ★단, 종류 축은 여전히 화면 제목에만 있다★. "
        "`RealismKPIs` 와 같은 판단을 적용해 둘을 함께 다룬다(로드맵에 남은 갭으로 적음).",
    "src/widgets/company/CompanyCockpit.tsx":
        "★전략 성과가 아니다★ — 한 종목의 가격 이력에서 잰 위험 지표"
        "(VaR·ES·변동성·Sharpe·MDD)다. 여기에 '백테스트' 라벨을 붙이면 "
        "없는 시뮬레이션을 있다고 말하는 셈이다.",
    "src/widgets/allocation/AllocationProvider.tsx":
        "★화면이 아니다★ — 상태 제공자이고, 잡힌 `sharpe` 는 스터디 저장 시 만드는 "
        "저널 초안 **문자열**이다. 성과 패널을 그리지 않는다.",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 주석 제거 — 문자열은 남긴다(위 머리글의 이유)
# ═══════════════════════════════════════════════════════════════════════════════
def strip_comments(src: str) -> str:
    """TS/TSX 의 `//` 와 `/* */` 만 공백으로 바꾼다. 문자열 안은 건드리지 않는다."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                if src[i] == "\\":
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def renders_metrics(source: str) -> bool:
    body = strip_comments(source)
    return any(re.search(t, body, re.I) for t in METRIC_TOKENS)


def uses_perf_label(source: str) -> bool:
    body = strip_comments(source)
    return bool(re.search(r'from\s+"@/shared/ui/PerfLabel"', body))


def _widgets() -> list[pathlib.Path]:
    return sorted(WIDGETS.rglob("*.tsx"))


def _scan() -> dict[str, bool]:
    """지표를 그리는 위젯 → `PerfLabel` 을 쓰는가."""
    out: dict[str, bool] = {}
    for path in _widgets():
        text = path.read_text()
        if renders_metrics(text):
            out[str(path.relative_to(FRONTEND))] = uses_perf_label(text)
    return out


pytestmark = pytest.mark.skipif(not WIDGETS.exists(), reason="frontend 없음")


# ═══════════════════════════════════════════════════════════════════════════════
# ⑩ 본 계약
# ═══════════════════════════════════════════════════════════════════════════════
def test_every_metric_widget_labels_what_the_numbers_are():
    """★수익률·Sharpe·MDD 를 그리면 그것이 무엇인지도 그려야 한다★"""
    found = _scan()
    missing = sorted(k for k, labeled in found.items() if not labeled and k not in ALLOWED)
    assert not missing, (
        "성과 지표를 그리면서 `PerfLabel` 을 쓰지 않는 위젯입니다. "
        "붙이거나, ALLOWED 에 **사유와 함께** 등록하세요:\n  " + "\n  ".join(missing))


def test_the_allowlist_is_not_stale():
    """★고쳐 놓고 목록을 안 지우면 허용 목록이 거짓이 된다★"""
    found = _scan()
    ghosts = sorted(k for k in ALLOWED if k not in found)
    assert not ghosts, (
        "허용 목록에 있는데 더 이상 지표를 그리지 않는(또는 사라진) 파일입니다 — "
        "ALLOWED 에서 지우세요:\n  " + "\n  ".join(ghosts))

    now_labeled = sorted(k for k in ALLOWED if found.get(k))
    assert not now_labeled, (
        "이미 `PerfLabel` 을 쓰는데 허용 목록에 남아 있습니다 — 지우세요:\n  "
        + "\n  ".join(now_labeled))


def test_every_allowance_carries_a_substantive_reason():
    """★사유 없는 면제는 면제가 아니라 구멍이다★"""
    thin = sorted(k for k, why in ALLOWED.items() if len(why.strip()) < 40)
    assert not thin, f"사유가 너무 얇습니다(40자 미만): {thin}"


# ═══════════════════════════════════════════════════════════════════════════════
# ⑪⑫⑬ 테스트의 테스트 — "0건" 이 탐지기 고장일 때도 나오는 값이기 때문이다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_detector_actually_detects(tmp_path):
    """★가짜 소스에 지표를 넣으면 잡는가★"""
    fake = '''export function Fake() {
  return <div>{result.sharpe_ratio} / {result.max_drawdown_pct}</div>;
}'''
    assert renders_metrics(fake)
    assert not uses_perf_label(fake)


def test_the_detector_does_not_cry_wolf():
    """★짝★ 지표를 안 그리는 소스를 잡으면 안 된다 — 항상-거부 구현 배제."""
    innocent = '''export function Innocent() {
  return <div>{holdings.length}종목 · {weight.toFixed(1)}%</div>;
}'''
    assert not renders_metrics(innocent)


def test_metric_mentions_in_comments_are_not_a_violation():
    """★주석 오탐 배제★ 주석에만 있는 표기는 화면에 그려지지 않는다."""
    commented = '''// TODO: sharpe_ratio 와 max_drawdown_pct 를 여기 붙이자
/* calmar 도 cagr 도 아직 없다 */
export function Later() { return <div>준비 중</div>; }'''
    assert not renders_metrics(commented), (
        "주석 제거 단계가 죽었습니다 — 주석의 지표 표기를 위반으로 셉니다")


def test_strings_are_deliberately_not_stripped():
    """★문자열은 남긴다★ 이 저장소의 지표 라벨은 문자열 리터럴로 산다.

    계획 문장("주석/문자열")에서 의도적으로 벗어난 지점이고, 그 선택을 못 박는다.
    """
    as_string = '''const M = [{ key: "sharpe_ratio", label: "Sharpe" }];'''
    assert renders_metrics(as_string)


def test_the_scan_is_not_vacuous():
    """★공허 배제★ 검출 대상이 0개면 이 파일 전체가 아무 말도 하지 않는다."""
    found = _scan()
    assert len(found) >= 10, f"지표를 그리는 위젯이 {len(found)}개뿐입니다 — 검출기를 의심하세요"
    assert sum(found.values()) >= 5, "PerfLabel 을 쓰는 위젯이 너무 적습니다"


def test_the_allowlist_cannot_be_widened_to_everything():
    """★허용 목록이 전체 허용이 되면 계약이 사라진다★ (변이 f)"""
    found = _scan()
    assert len(ALLOWED) < len(found), (
        "허용 목록이 검출 대상 전체를 덮고 있습니다 — 그 순간 이 계약은 아무것도 막지 않습니다")


# ═══════════════════════════════════════════════════════════════════════════════
# ⑭ 컴포넌트 쪽 규율 — ★없으면 `unknown`★ (변이 i)
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_component_falls_back_to_unknown_not_backtest():
    """응답이 라벨을 안 줬을 때 `backtest` 를 그리면 **없는 사실**이 생긴다.

    ★이 정적 확인은 약하다★ — 소스 텍스트를 보는 것이지 동작을 보는 것이 아니다.
    진짜 못 박는 것은 `frontend/e2e/perf-label.spec.ts` 이고, 그것은 CI 가 돌린다.
    여기서는 "폴백이 unknown 이라고 적혀 있는가" 만 본다.
    """
    src = strip_comments(COMPONENT.read_text())
    m = re.search(r"if\s*\(!value[^)]*\)\s*\{(.*?)\}", src, re.S)
    assert m, "resolvePerfLabel 의 '값 없음' 분기를 찾지 못했습니다 — 구조가 바뀌었습니다"
    branch = m.group(1)
    assert '"unknown"' in branch, f"값이 없을 때 unknown 이 아닙니다: {branch.strip()[:120]}"
    for kind in ("backtest", "paper", "shadow", "live", "ra_testbed"):
        assert f'"{kind}"' not in branch, (
            f"값이 없을 때 `{kind}` 로 기울고 있습니다 — 미상은 라벨이 아닙니다")


def test_the_frontend_vocabulary_matches_the_backend():
    """★어휘가 둘로 갈라지면 화면과 응답이 다른 말을 한다★"""
    from src.domain.perf_kind import PERF_KINDS

    src = strip_comments(COMPONENT.read_text())
    m = re.search(r"PERF_KINDS\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "프런트 PERF_KINDS 를 찾지 못했습니다"
    fe = tuple(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert fe == PERF_KINDS, f"프런트 {fe} ≠ 백엔드 {PERF_KINDS}"
