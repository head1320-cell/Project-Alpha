"""스타일 래칫 — ADR 007 §8 의 가드 (U0-c)
==============================================================================
ADR 007 은 척도(글자 · 반경 · 깊이 · 중단점)와 색의 뜻을 정했다. 지금 화면에는 그 척도 밖의 값이 이미 많다(감사가 셌다).
한 번에 고치지 않는다 — ★지금 수를 기준선으로 잠그고, 화면 조각이 제 화면을 옮길 때마다 내린다.★

## 세 겹으로 건다 (래칫마다)
1. **심은 위반을 센다** — 검사기가 고장 나 0 을 돌려도 초록으로 남는 일을 막는다("0건" 은 탐지기가 죽었을 때도 나오는 값이다).
2. **허용된 꼴은 세지 않는다** — 짝. 무엇이든 세는 검사기도 1 을 통과한다.
3. **지금 저장소 = 기준선** — 늘면 실패(새 위반). ★줄었는데 기준선을 내리지 않아도 실패★(낡은 기준선은 다음 위반이 들어올 틈이다).

## 무엇을 세나 — `tests/frontend_style_scan.py`(순수 함수 · 입력은 글)
`frontend/src/app/globals.css` 에서: 척도 밖 글자 크기 · 척도 밖 반경 · 날 `z-index` · 토큰 정의 밖의 hex · 척도 밖 중단점 · 모든 속성에 거는 전환 ·
등락색을 쓰는 선택자(목록) · 수 칸에 입힌 상태색(0 고정). `frontend/src/**/*.tsx` 에서: 요소의 `title=`(파일별) · 낱 `<table>` 을 그리는 파일(목록).

## 한계 (정직하게)
- ★글자를 훑는다★ — 인라인 `style={{…}}` · 실행 중에 지은 클래스 이름 · Tailwind 유틸리티로 적은 값은 보지 못한다. 다른 CSS 파일도 보지 않는다(지금은 `globals.css` 하나다 — 아래 시험이 그것을 건다).
- 다크 생성 구역(`BS5-GEN`)은 뺀다 — 생성기가 만든 글이고 `gen-dark-modules.mjs --check` 가 따로 건다.
- 중단점은 `(min-width: Npx)` · `(max-width: Npx)` 꼴만 본다(범위 문법 `width <= N` 은 이 저장소에 없다 — 아래 시험이 건다).
- 기준선의 수는 ★위반이 그만큼 있다는 관측★이지 그 값들이 괜찮다는 판정이 아니다.

기준선을 고칠 때: 줄였으면 내린다. 늘려야 한다면 그 까닭을 `docs/HISTORY.md` 에 적는다(ADR 007 §8).
같은 계층의 선례: `tests/test_css_specificity_guard.py` · `tests/test_frontend_claim_words.py`.
"""

from __future__ import annotations

import collections
import pathlib
import re

import pytest

from tests import frontend_style_scan as scan

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
GLOBALS_CSS = SRC / "app" / "globals.css"

# ── 기준선 (검사기가 센 값 · 2026-11-20) ─────────────────────────────────────────────────────────

#: 선언 수. 화면 조각이 옮길 때마다 내린다.
BASELINE_COUNTS: dict[str, int] = {
    "척도 밖 글자 크기": 586,
    "척도 밖 반경": 382,
    "날 z-index": 80,
    "토큰 정의 밖 hex": 240,
}

#: 척도(480 · 640 · 900 · 1280 · 1600 과 그 −1) 밖의 폭 조건 — 서로 다른 조건 글.
BASELINE_BREAKPOINTS: tuple[str, ...] = (
    "(max-width: 1000px)",
    "(max-width: 1080px)",
    "(max-width: 1100px)",
    "(max-width: 1180px)",
    "(max-width: 1200px)",
    "(max-width: 1365px)",
    "(max-width: 1439px)",
    "(max-width: 390px)",
    "(max-width: 420px)",
    "(max-width: 520px)",
    "(max-width: 560px)",
    "(max-width: 720px)",
    "(max-width: 760px)",
    "(max-width: 800px)",
    "(max-width: 820px)",
    "(min-width: 1001px)",
    "(min-width: 1680px)",
)

#: 모든 속성에 거는 전환을 가진 선택자 — 접근성 P0-2 가 0 으로 내린다(초점 고리가 늦게 그려지는 원인).
BASELINE_TRANSITION_ALL: tuple[str, ...] = (
    ".brun-btn",
    ".mc-ind",
    ".mc-tab",
    ".pv-tab",
    ".tbt-mode",
    ".tbt-saved-del",
    ".tscreener-handoff-clear",
)

#: 등락색 토큰을 쓰는 선택자의 허용 목록(ADR 007 §4-1 — 등락색은 수와 표식에만). 새 선택자는 여기 더하기 전에 그것이 수 · 표식인지 본다.
UPDOWN_ALLOW: tuple[str, ...] = (
    ".brun-attr-bar",
    ".cdl-down .cdl-body",
    ".cdl-down .cdl-wick",
    ".cdl-mark-buy .cdl-tick",
    ".cdl-mark-buy .cdl-tri",
    ".cdl-mark-sell .cdl-tick",
    ".cdl-mark-sell .cdl-tri",
    ".cdl-ov-buy",
    ".cdl-ov-sell",
    ".cdl-up .cdl-body",
    ".cdl-up .cdl-wick",
    ".ci-chg[data-dir=down], .ci-mini-chg[data-dir=down]",
    ".ci-chg[data-dir=up], .ci-mini-chg[data-dir=up]",
    ".ci-macro-bar[data-dir=down]",
    ".ci-macro-bar[data-dir=up]",
    ".ci-sumcard-d[data-dir=down]",
    ".ci-sumcard-d[data-dir=up]",
    ".ci-torn-v[data-dir=down]",
    ".ci-torn-v[data-dir=up]",
    ".devui-dn-table .devui-dn-down",
    ".devui-dn-table .devui-dn-up",
    '.itd-day-checkrow[data-status="different"] .itd-day-chip',
    '.ma-mon [data-dir="down"]',
    '.ma-mon [data-dir="up"]',
    '.ma-side [data-side="BUY"][aria-pressed="true"]',
    '.ma-side [data-side="SELL"][aria-pressed="true"]',
    ".rk .tstat-val.rk-dir[data-dir=down]",
    ".rk .tstat-val.rk-dir[data-dir=up]",
    ".rk-dir[data-dir=down], .rk-cell-v[data-dir=down]",
    ".rk-dir[data-dir=up], .rk-cell-v[data-dir=up]",
    '.rl-wf-row[data-dir="down"] .rl-wf-bar',
    '.rl-wf-row[data-dir="down"] .rl-wf-v',
    '.rl-wf-row[data-dir="up"] .rl-wf-bar',
    '.rl-wf-row[data-dir="up"] .rl-wf-v',
    '.tj [data-dir="down"]',
    '.tj [data-dir="up"]',
    ".tj-bucket-bar--down",
    ".tj-bucket-bar--up",
    ".tj-wf-bar--down",
    ".tj-wf-bar--up",
    '.tx-delta[data-dir="down"]',
    '.tx-delta[data-dir="up"]',
    'tr[data-sign="down"] .brun-attr-bar',
)

#: 요소의 `title=` — 파일별 수. 자판 · 손가락으로는 읽지 못하는 설명이라 U7(설명 층)이 걷는다. 새 설명은 `tx` 의 풀이 부품으로.
BASELINE_TITLE_ATTRS: dict[str, int] = {
    "frontend/src/app/allocation/page.tsx": 1,
    "frontend/src/features/case-bar/CaseBar.tsx": 1,
    "frontend/src/features/portfolio-graph-io/GraphFileIO.tsx": 2,
    "frontend/src/features/profile/ProfileMenu.tsx": 1,
    "frontend/src/shared/ui/AllocationMap.tsx": 2,
    "frontend/src/shared/ui/PerfLabel.tsx": 1,
    "frontend/src/widgets/portfolio-graph/BacktestResults.tsx": 2,
    "frontend/src/widgets/portfolio-graph/Branches.tsx": 4,
    "frontend/src/widgets/portfolio-graph/CanvasChrome.tsx": 3,
    "frontend/src/widgets/portfolio-graph/CanvasToolbar.tsx": 12,
    "frontend/src/widgets/portfolio-graph/ClientDocChip.tsx": 4,
    "frontend/src/widgets/portfolio-graph/CompanyModelResults.tsx": 1,
    "frontend/src/widgets/portfolio-graph/CompanyResults.tsx": 2,
    "frontend/src/widgets/portfolio-graph/GateRail.tsx": 3,
    "frontend/src/widgets/portfolio-graph/GhostLayer.tsx": 1,
    "frontend/src/widgets/portfolio-graph/Glance.tsx": 3,
    "frontend/src/widgets/portfolio-graph/GraphNode.tsx": 13,
    "frontend/src/widgets/portfolio-graph/GroupFrame.tsx": 16,
    "frontend/src/widgets/portfolio-graph/MacroResults.tsx": 2,
    "frontend/src/widgets/portfolio-graph/MacroW2Results.tsx": 1,
    "frontend/src/widgets/portfolio-graph/NodeInspector.tsx": 1,
    "frontend/src/widgets/portfolio-graph/NodePalette.tsx": 3,
    "frontend/src/widgets/portfolio-graph/NodeResultPanel.tsx": 1,
    "frontend/src/widgets/portfolio-graph/PortfolioCanvas.tsx": 8,
    "frontend/src/widgets/portfolio-graph/ProcedurePanel.tsx": 1,
    "frontend/src/widgets/portfolio-graph/RightPanel.tsx": 1,
    "frontend/src/widgets/portfolio-graph/RiskResults.tsx": 1,
    "frontend/src/widgets/portfolio-graph/RobustnessResults.tsx": 2,
    "frontend/src/widgets/portfolio-graph/SettingsPanel.tsx": 1,
    "frontend/src/widgets/portfolio-graph/SignalResults.tsx": 4,
    "frontend/src/widgets/portfolio-graph/StrategyResults.tsx": 3,
    "frontend/src/widgets/portfolio-graph/TickerInput.tsx": 1,
}

#: 낱 `<table>` 을 그리는 파일. 공용 표(U1)로 옮기면 목록에서 뺀다. 새 표는 공용 표로.
RAW_TABLE_FILES: tuple[str, ...] = (
    "frontend/src/app/dev/DensitySpecimen.tsx",
    "frontend/src/app/dev/ui/page.tsx",
    "frontend/src/features/cost-breakdown/CostBreakdown.tsx",
    "frontend/src/features/divergence-result/DivergenceResult.tsx",
    "frontend/src/features/intraday-day-types/DayTypeTable.tsx",
    "frontend/src/features/intraday-market-regime/RegimeCenters.tsx",
    "frontend/src/features/intraday-market-regime/RegimeFacts.tsx",
    "frontend/src/features/intraday-regime-split/RegimeDayTypesTable.tsx",
    "frontend/src/features/intraday-regime-split/RegimeSplitTable.tsx",
    "frontend/src/features/intraday-verdict/Verdict.tsx",
    "frontend/src/features/journal-result/parts.tsx",
    "frontend/src/shared/ui/chart/ChartReadout.tsx",
    "frontend/src/shared/ui/perf/CompareYearTable.tsx",
    "frontend/src/shared/ui/perf/DrawdownEpisodes.tsx",
    "frontend/src/shared/ui/perf/MonthGrid.tsx",
    "frontend/src/shared/ui/perf/PerfCompare.tsx",
    "frontend/src/shared/ui/perf/PerfTableView.tsx",
    "frontend/src/shared/ui/perf/RebalanceTable.tsx",
    "frontend/src/shared/ui/shadcn/table.tsx",
    "frontend/src/widgets/admin/DbStatusPanel.tsx",
    "frontend/src/widgets/backtester/BacktestCompare.tsx",
    "frontend/src/widgets/backtester/BacktestResults.tsx",
    "frontend/src/widgets/backtester/RunMonitor.tsx",
    "frontend/src/widgets/company/CompanyCockpit.tsx",
    "frontend/src/widgets/company/FinancialsDeepTab.tsx",
    "frontend/src/widgets/company/ModelsSection.tsx",
    "frontend/src/widgets/company/MoneySection.tsx",
    "frontend/src/widgets/company/RiskDeepTab.tsx",
    "frontend/src/widgets/company/ValuationTab.tsx",
    "frontend/src/widgets/intraday/SetupForm.tsx",
    "frontend/src/widgets/live-trading/SafetyTab.tsx",
    "frontend/src/widgets/macro/MacroIntelPanel.tsx",
    "frontend/src/widgets/macro/StudioPanel.tsx",
    "frontend/src/widgets/macro/analyticsParts.tsx",
    "frontend/src/widgets/macro/cockpitParts.tsx",
    "frontend/src/widgets/macro/visualParts.tsx",
    "frontend/src/widgets/portfolio-graph/ActResults.tsx",
    "frontend/src/widgets/portfolio-graph/AllocExtraResults.tsx",
    "frontend/src/widgets/portfolio-graph/BacktestResults.tsx",
    "frontend/src/widgets/portfolio-graph/Bl2Results.tsx",
    "frontend/src/widgets/portfolio-graph/Branches.tsx",
    "frontend/src/widgets/portfolio-graph/CheckResults.tsx",
    "frontend/src/widgets/portfolio-graph/ClientResults.tsx",
    "frontend/src/widgets/portfolio-graph/CompanyModelResults.tsx",
    "frontend/src/widgets/portfolio-graph/CompanyResults.tsx",
    "frontend/src/widgets/portfolio-graph/CoreSatelliteResults.tsx",
    "frontend/src/widgets/portfolio-graph/MacroResults.tsx",
    "frontend/src/widgets/portfolio-graph/MacroW2Results.tsx",
    "frontend/src/widgets/portfolio-graph/NodeResultPanel.tsx",
    "frontend/src/widgets/portfolio-graph/RegimeWeightingBlock.tsx",
    "frontend/src/widgets/portfolio-graph/RiskResults.tsx",
    "frontend/src/widgets/portfolio-graph/RobustnessResults.tsx",
    "frontend/src/widgets/portfolio-graph/RunHistory.tsx",
    "frontend/src/widgets/portfolio-graph/SignalResults.tsx",
    "frontend/src/widgets/portfolio-graph/StrategyResults.tsx",
    "frontend/src/widgets/portfolio-graph/WirePanel.tsx",
    "frontend/src/widgets/risk/StressCheck.tsx",
    "frontend/src/widgets/screener/TerminalScreener.tsx",
    "frontend/src/widgets/trade-journal/MapStep.tsx",
)


# ── 읽기 ────────────────────────────────────────────────────────────────────────────────────────


def _rules_of(css: str) -> list[scan.Rule]:
    return scan.css_rules(scan.strip_css_comments(scan.drop_generated(css)))


@pytest.fixture(scope="module")
def rules() -> list[scan.Rule]:
    return _rules_of(GLOBALS_CSS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tsx_files() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.tsx"))}


def _counter(pairs: list[tuple[str, str]], n: int = 8) -> str:
    c = collections.Counter(v for _, v in pairs)
    return " · ".join(f"{v} ×{k}" for v, k in c.most_common(n))


# ── 1 · 2. 검사기 자체 — 심은 위반은 세고, 허용된 꼴은 세지 않는다 ──────────────────────────────────

PLANTED = [
    (
        "척도 밖 글자 크기",
        scan.offscale_font_sizes,
        ".a { font-size: 13.5px; } .b { font-size: 15px !important; } @media (max-width: 640px) { .c { font-size: 10px; } }",
        3,
        ".a { font-size: 13px; } .b { font-size: var(--fs-base); } .c { font-size: 0.9em; } .d { font-size: clamp(12px, 2vw, 15px); } .e { font-size: 28px !important; } .f { font-size: inherit; }",
    ),
    (
        "척도 밖 반경",
        scan.offscale_radii,
        ".a { border-radius: 7px; } .b { border-top-left-radius: 6px; } .c { border-radius: 8px 3px; } .d { border-radius: 10px !important; }",
        4,
        ".a { border-radius: 8px; } .b { border-radius: var(--tx-r-row); } .c { border-radius: 50%; } .d { border-radius: 999px; } .e { border-radius: 0; } "
        ".f { border-radius: var(--r, 6px); } .g { border-radius: 12px 12px 0 0; } .h { border-radius: inherit; }",
    ),
    (
        "날 z-index",
        scan.raw_z_indexes,
        ".a { z-index: 9999; } .b { z-index: -1; } .c { z-index: 2 !important; }",
        3,
        ".a { z-index: var(--tx-z-float); } .b { z-index: auto; } .c { z-index: calc(var(--tx-z-modal) + 1); } .d { z-index: inherit; }",
    ),
    (
        "토큰 정의 밖 hex",
        scan.raw_hex,
        ".a { color: #ff0000; } .b { background: linear-gradient(#FFF, #0b0c0e80); } :root { color: #123; }",
        4,
        ":root { --x: #ff0000; } .dark { --y: #000; } .a { --local: #abc; color: var(--x); background: url(#fade); } .b { color: rgb(0 0 0); }",
    ),
    (
        "모든 속성에 거는 전환",
        scan.transition_all,
        ".a { transition: all .15s; } .b { transition-property: all; } .c { transition: .2s ease; } .d { transition: color .1s, all .2s; } .e { transition: all 150ms ease !important; }",
        5,
        ".a { transition: color .15s, background-color .15s; } .b { transition: none; } .c { transition: transform 200ms cubic-bezier(.2, .8, .2, 1); } "
        ".d { transition: var(--t); } .e { transition: opacity .2s ease-in-out 50ms; } .f { transition-property: color, border-color; } .g { transition: inherit; }",
    ),
]


@pytest.mark.parametrize(
    "name, fn, planted, want, allowed", PLANTED, ids=["font-size", "radius", "z-index", "hex", "transition-all"]
)
def test_검사기는_심은_위반을_세고_허용된_꼴은_세지_않는다(name, fn, planted, want, allowed):
    got = fn(_rules_of(planted))
    assert len(got) == want, f"{name}: 심은 위반 {want} 가운데 {len(got)} 만 셌다 — {got}"
    assert fn(_rules_of(allowed)) == [], f"{name}: 허용된 꼴을 위반으로 셌다"


def test_검사기는_척도_밖_중단점을_조건_글로_모은다():
    planted = """
      @media (max-width: 777px) { .a { color: red; } .b { color: red; } }
      @media (min-width: 700px) and (max-width:777px) { .c { color: red; } }
      @media (max-width: 640px) { @media (min-width: 333px) { .d { color: red; } } }
    """
    assert scan.offscale_breakpoints(_rules_of(planted)) == [
        "(max-width: 777px)",
        "(max-width:777px)",
        "(min-width: 333px)",
        "(min-width: 700px)",
    ]
    allowed = """
      @media (max-width: 640px) { .a { color: red; } }
      @media (min-width: 1280px) { .a { color: red; } }
      @media (max-width: 1279px) and (min-width: 900px) { .a { color: red; } }
      @media (prefers-reduced-motion: reduce) { .a { color: red; } }
      @media print { .a { color: red; } }
      @supports (width: 777px) { .a { color: red; } }
    """
    assert scan.offscale_breakpoints(_rules_of(allowed)) == []


def test_검사기는_주석과_생성_구역을_세지_않는다():
    """주석 안의 글 · 다크 생성 구역은 사람이 적은 값이 아니다 — 세면 기준선이 고칠 수 없는 수가 된다."""
    css = f"""
      /* .x {{ font-size: 15px; z-index: 5; color: #ff0000; }} */
      .a {{ font-size: 15px; }}
      {scan.GEN_BEGIN}
      .dark .g {{ color: #101010; font-size: 9px; z-index: 7; border-radius: 5px; transition: all 1s; }}
      {scan.GEN_END}
      .b {{ color: #00ff00; }}
    """
    r = _rules_of(css)
    assert [s for s, _ in scan.offscale_font_sizes(r)] == [".a"]
    assert scan.raw_hex(r) == [(".b", "#00ff00")]
    assert scan.raw_z_indexes(r) == [] and scan.offscale_radii(r) == [] and scan.transition_all(r) == []
    # 짝 ① 주석을 벗기지 않으면 주석 안의 글이 규칙으로 읽힌다(이 시험이 공허하지 않다)
    kept_comments = scan.css_rules(scan.drop_generated(css))
    assert [v for _, v in scan.raw_z_indexes(kept_comments)] == ["5"]
    assert sorted(h for _, h in scan.raw_hex(kept_comments)) == ["#00ff00", "#ff0000"]
    assert len(scan.offscale_font_sizes(kept_comments)) == 2
    # 짝 ② 생성 구역을 빼지 않으면 그 안의 값이 세어진다
    kept_gen = scan.css_rules(scan.strip_css_comments(css))
    assert [v for _, v in scan.raw_z_indexes(kept_gen)] == ["7"]
    assert sorted(h for _, h in scan.raw_hex(kept_gen)) == ["#00ff00", "#101010"]
    assert (
        len(scan.transition_all(kept_gen)) == 1
        and len(scan.offscale_radii(kept_gen)) == 1
        and len(scan.offscale_font_sizes(kept_gen)) == 2
    )


def test_검사기는_규칙을_빠짐없이_나눈다():
    """`@media` 안으로 들어가고 `@keyframes` · `@font-face` 는 건너뛴다 · 문자열 안의 중괄호 · 쌍반점에 속지 않는다."""
    css = """
      @import url("x.css");
      .a { color: red; content: "};{"; }
      @media (max-width: 640px) { .b, .c > .d { margin: 0; } }
      @keyframes spin { from { z-index: 1; } to { z-index: 2; } }
      @font-face { font-family: X; src: url(x.woff2); }
      @supports (display: grid) { .e { display: grid; } }
      .f { background: url("data:image/svg+xml;utf8,<svg/>"); width: calc((100% - 8px) / 2); }
    """
    r = _rules_of(css)
    assert [(x.selector, x.media) for x in r] == [
        (".a", ()),
        (".b, .c > .d", ("(max-width: 640px)",)),
        (".e", ()),
        (".f", ()),
    ]
    assert dict(r[0].decls) == {"color": "red", "content": '"};{"'}
    assert dict(r[3].decls) == {
        "background": 'url("data:image/svg+xml;utf8,<svg/>")',
        "width": "calc((100% - 8px) / 2)",
    }


def test_검사기는_등락색을_쓰는_선택자만_모은다():
    planted = ".x-cell { color: var(--tx-up-ink); } .y { background: var( --tx-down-soft ); } .z { border-color: var(--tx-up, red); }"
    assert scan.updown_selectors(_rules_of(planted)) == {".x-cell", ".y", ".z"}
    allowed = (
        ":root { --tx-up: #f00; --alias: var(--tx-up); } .a { color: var(--tx-upper); } .b { color: var(--tx-ink); }"
    )
    assert scan.updown_selectors(_rules_of(allowed)) == set()


def test_검사기는_수_칸의_상태색을_잡는다():
    planted = "td.num.bad { color: var(--tx-danger); } .pg-td-num { color: var(--tx-warn); } .row [data-num] { background: var(--tx-ok); } .a, .b > .num { color: var(--tx-danger); }"
    assert scan.status_on_number_selectors(_rules_of(planted)) == {
        "td.num.bad",
        ".pg-td-num",
        ".row [data-num]",
        ".a, .b > .num",
    }
    # 짝: 수 칸이 아닌 요소 · 수 칸 ★안의★ 다른 요소 · 상태색이 아닌 색 · 이름이 비슷한 클래스
    allowed = ".badge { color: var(--tx-danger); } .num .badge { color: var(--tx-danger); } td.num { color: var(--tx-ink); } .number { color: var(--tx-warn); } .row-numeric { color: var(--tx-ok); }"
    assert scan.status_on_number_selectors(_rules_of(allowed)) == set()


def test_검사기는_요소의_title_만_센다():
    tsx = "\n".join(
        [
            '<span title="설명">x</span>',  # 1 — 센다
            "<button",  # 2
            '  className="a"',  # 3
            "  onClick={() => (a > b ? go({ title: 1 }) : null)}",  # 4 — 식 안의 title 은 속성이 아니다
            "  title={`a ${b}`}",  # 5 — 센다(여러 줄에 걸친 꼬리표)
            ">",  # 6
            '<Section title="제목" />',  # 7 — 부품의 prop
            "<svg><title>그림</title></svg>",  # 8 — 요소 <title>
            '// <i title="주석">',  # 9
            '{/* <b title="주석"> */}',  # 10
            'const o = { title: "x", subtitle="y" };',  # 11
            '<Tabs.Item title="t" /><a data-title="d" href="#">',  # 12 — 점 붙은 부품 · 다른 속성 이름
        ]
    )
    assert scan.element_title_attrs(tsx) == [1, 5]


def test_검사기는_낱_table_을_가른다():
    assert scan.has_raw_table('<div><table className="x"><tbody /></table></div>') is True
    assert scan.has_raw_table("<table>") is True
    assert scan.has_raw_table("<Table rows={r} /> // <table>\n{/* <table> */}\n<tablet />") is False


# ── 3. 지금 저장소 = 기준선 ────────────────────────────────────────────────────────────────────────


def test_검사기가_실제로_globals_css_를_읽는다(rules):
    """공허한 통과를 막는다 — 규칙을 수천 개 나눴고, 이 묶음이 더한 토큰 블록이 그 안에 있다."""
    assert len(rules) > 5000, f"규칙 {len(rules)} — 해석기가 파일을 다 읽지 못했다"
    sels = {r.selector for r in rules}
    assert {'[data-density="compact"]', '[data-tier="work"]', ".terminal-main"} <= sels
    # 이 가드가 보는 CSS 는 이 파일 하나다 — 다른 CSS 파일이 생기면 범위를 넓힌다
    others = sorted(p.relative_to(ROOT).as_posix() for p in SRC.rglob("*.css") if p != GLOBALS_CSS)
    assert others == [], f"가드가 보지 않는 CSS 파일: {others}"
    # 범위 문법의 폭 조건은 검사기가 보지 못한다 — 생기면 검사기를 먼저 고친다
    assert not [m for r in rules for m in r.media if re.search(r"width\s*[<>]", m)], "범위 문법의 폭 조건이 생겼다"


def test_척도는_토큰_블록의_값과_같다(rules):
    """수치는 코드가 진실이다 — 검사기의 척도와 `:root` 의 토큰이 서로 다른 말을 하지 않는다."""
    root: dict[str, str] = {}
    for r in rules:
        if r.selector == ":root" and not r.media:
            root.update({k: v for k, v in r.decls if k.startswith("--tx-")})
    radii = {float(root[f"--tx-r-{i}"].removesuffix("px")) for i in (1, 2, 3, 4, 5)} | {
        float(root["--tx-r-pill"].removesuffix("px"))
    }
    assert radii | {0.0} == {float(x) for x in scan.RADIUS_SCALE_PX}
    # 밀도 토큰이 정한 글자 크기는 모두 척도 안이다
    fs = {
        float(v.removesuffix("px"))
        for r in rules
        if r.selector.startswith("[data-density=") or r.selector == ":root"
        for k, v in r.decls
        if k in ("--tx-fs-table", "--tx-fs-th")
    }
    assert fs and fs <= {float(x) for x in scan.FONT_SCALE_PX}, fs


COUNTERS = {
    "척도 밖 글자 크기": scan.offscale_font_sizes,
    "척도 밖 반경": scan.offscale_radii,
    "날 z-index": scan.raw_z_indexes,
    "토큰 정의 밖 hex": scan.raw_hex,
}


@pytest.mark.parametrize("name", list(COUNTERS), ids=["font-size", "radius", "z-index", "hex"])
def test_날_값의_수가_기준선과_같다(rules, name):
    got = COUNTERS[name](rules)
    base = BASELINE_COUNTS[name]
    assert len(got) <= base, (
        f"{name}: {len(got)} > 기준선 {base} — 새 날 값이 들어왔다. ADR 007 §3 의 척도 · 토큰을 쓴다.\n  많은 값: {_counter(got)}"
    )
    assert len(got) == base, f"{name}: {len(got)} < 기준선 {base} — 줄였다. `BASELINE_COUNTS` 를 {len(got)} 로 내린다."


def test_척도_밖_중단점이_기준선과_같다(rules):
    got = scan.offscale_breakpoints(rules)
    new = sorted(set(got) - set(BASELINE_BREAKPOINTS))
    gone = sorted(set(BASELINE_BREAKPOINTS) - set(got))
    assert not new, f"척도(480 · 640 · 900 · 1280 · 1600) 밖의 새 중단점: {new}"
    assert not gone, f"없어진 중단점이 기준선에 남았다 — `BASELINE_BREAKPOINTS` 에서 뺀다: {gone}"


def test_모든_속성에_거는_전환이_기준선과_같다(rules):
    got = sorted(s for s, _ in scan.transition_all(rules))
    new = sorted(set(got) - set(BASELINE_TRANSITION_ALL))
    gone = sorted(set(BASELINE_TRANSITION_ALL) - set(got))
    assert not new, f"모든 속성에 거는 전환이 새로 생겼다(초점 고리까지 늦춘다 — 바뀌는 속성만 적는다): {new}"
    assert not gone, f"고친 선택자가 기준선에 남았다 — `BASELINE_TRANSITION_ALL` 에서 뺀다: {gone}"
    assert len(got) == len(set(got)), "같은 선택자가 두 번 — 기준선을 수로 바꿔야 한다"


def test_등락색을_쓰는_선택자가_허용_목록과_같다(rules):
    got = scan.updown_selectors(rules)
    new = sorted(got - set(UPDOWN_ALLOW))
    gone = sorted(set(UPDOWN_ALLOW) - got)
    assert not new, f"등락색을 쓰는 새 선택자 — 수 · 표식이 맞는지 보고 `UPDOWN_ALLOW` 에 더한다(ADR 007 §4-1): {new}"
    assert not gone, f"더는 등락색을 쓰지 않는 선택자가 허용 목록에 남았다: {gone}"


def test_상태색은_수_칸에_입히지_않는다(rules):
    """ADR 007 §4-2 — 빨강이 '내렸다'와 '위험하다'를 함께 뜻하지 않게 한다. 기준선 없이 0 이다."""
    assert scan.status_on_number_selectors(rules) == set()


def test_요소의_title_이_기준선과_같다(tsx_files):
    got = {f: n for f, src in tsx_files.items() if (n := len(scan.element_title_attrs(src)))}
    more = {f: (BASELINE_TITLE_ATTRS.get(f, 0), n) for f, n in got.items() if n > BASELINE_TITLE_ATTRS.get(f, 0)}
    less = {f: (b, got.get(f, 0)) for f, b in BASELINE_TITLE_ATTRS.items() if got.get(f, 0) < b}
    assert not more, (
        f"요소의 `title=` 이 늘었다(자판 · 손가락으로는 읽지 못한다 — `tx` 의 풀이 부품을 쓴다) (기준선, 지금): {more}"
    )
    assert not less, f"줄였다 — `BASELINE_TITLE_ATTRS` 를 내린다 (기준선, 지금): {less}"


def test_낱_table_을_그리는_파일이_목록과_같다(tsx_files):
    got = {f for f, src in tsx_files.items() if scan.has_raw_table(src)}
    new = sorted(got - set(RAW_TABLE_FILES))
    gone = sorted(set(RAW_TABLE_FILES) - got)
    assert not new, f"낱 `<table>` 을 그리는 새 파일 — 공용 표를 쓴다(U1): {new}"
    assert not gone, f"표를 걷은 파일이 목록에 남았다 — `RAW_TABLE_FILES` 에서 뺀다: {gone}"
