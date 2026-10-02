"""배지 축 레지스트리 — ★통합하지 않고 **센다**★ (E5).

설계: `docs/superpowers/specs/2026-09-18-evidence-claim-design.md` · 채점표 #3 ⑴

## 채점표가 적은 것

*"기존 배지 넷이 그대로라 **같은 화면에 축이 다른 배지가 둘 이상** 보일 수 있다."*

사실이다. 그런데 그것은 **결함이 아니다.** `shared/ui/PerfLabel.tsx` 머리글이 이미
그렇게 적어 두었다:

    이 컴포넌트는 **성과의 종류**만 말하므로 같은 화면에 축이 다른 배지가 둘 이상
    보일 수 있다 — 그것은 결함이 아니라 사실이다.

축이 다르면 말하는 것이 다르다. `brun-badge`(PIT 시점 정합)와 `perf-label`
(성과의 종류)을 하나로 합치면 **두 질문을 섞는 것**이고, 그것이야말로
`CLAUDE.md` §2 가 금지하는 형태다.

## ★그래서 이 파일은 줄이지 않고 관측한다★

- 어느 배지가 **어느 축**을 말하는지 등록한다.
- 한 화면에 축이 몇 개 보이는지 **센다**.
- 레지스트리가 낡지 않도록, 등록된 클래스가 실제로 소스에 있는지 건다.

★이 파일은 "축이 둘 이상이면 안 된다" 고 주장하지 않는다.★ 주장하면 다음 사람이
합치게 되고, 합치면 정보가 준다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[1] / "frontend"
SRC = FRONTEND / "src"

# ── 축 ─────────────────────────────────────────────────────────────────────
#: 무슨 **성과**인가 (백테스트·모의·섀도·실계좌). `src/domain/perf_kind.py` 의 축.
AXIS_PERF_KIND = "perf_kind"
#: 무슨 **데이터**인가 (실데이터·합성). `mock_gate` 가 유일한 판정 기준.
AXIS_DATA_SOURCE = "data_source"
#: **시점 정합**인가 (R4 `run_evidence.pit_evidence`).
AXIS_PIT = "pit"
#: **룩어헤드**를 어디까지 통제했나 (E `allocation_evidence`).
AXIS_LOOKAHEAD = "lookahead"
#: 지금 어느 **실행 모드**인가 (SHADOW·PAPER·LIVE).
AXIS_RUN_MODE = "run_mode"

AXES = (AXIS_PERF_KIND, AXIS_DATA_SOURCE, AXIS_PIT, AXIS_LOOKAHEAD, AXIS_RUN_MODE)

AXIS_LABELS = {
    AXIS_PERF_KIND: "성과의 종류",
    AXIS_DATA_SOURCE: "데이터 출처",
    AXIS_PIT: "시점 정합",
    AXIS_LOOKAHEAD: "룩어헤드 통제",
    AXIS_RUN_MODE: "실행 모드",
}


class Badge:
    """정직 배지 하나 — 무엇을 그리고 **어느 축**을 말하는가.

    ★표지가 하나가 아닐 수 있다★ — 공용 컴포넌트는 클래스명이 컴포넌트 안에
    있고 화면에는 `<PerfLabel …>` 만 보인다. 클래스만 찾으면 그 화면이 축을
    말하지 **않는다고** 잘못 읽는다(실제로 처음에 그렇게 틀렸다).
    """

    def __init__(self, markers: tuple[str, ...], axes: tuple[str, ...], note: str):
        self.markers = markers
        self.axes = axes
        self.note = note

    @property
    def marker(self) -> str:
        """대표 표지 — 테스트 id 와 오류 문구에 쓴다."""
        return self.markers[0]


#: BU3 에서 `tbt-prov`(터미널 백테스터 결과 자리의 출처 표시)를 뺐다 — 그 결과 자리는 `result` 가 늘 `null` 이라
#: 한 번도 그려지지 않았고(거짓 약속), 지웠다. 결과의 데이터 출처는 결과 화면(`brun-badge`·`PerfLabel`)이 말한다.
#: ★장식 칩은 여기 없다★ — 증거·상태를 말하는 배지만 등록한다. 모든 `*badge*`
#: 클래스를 넣으면 목록이 스무 줄이 되고 아무도 읽지 않는다.
BADGES: tuple[Badge, ...] = (
    Badge(("perf-label", "<PerfLabel"), (AXIS_PERF_KIND, AXIS_DATA_SOURCE),
          "Z3 의 공용 컴포넌트. ★두 축을 한 배지 안에서 따로 그린다★ — "
          "`perf-label__kind` 와 `perf-label__data` 로 나뉘어 있어 섞이지 않는다."),
    Badge(("brun-badge",), (AXIS_DATA_SOURCE, AXIS_PIT),
          "백테스트 실행 화면. 같은 클래스가 두 번 쓰이는데 하나는 mock/real"
          "(데이터), 하나는 `res.pit_evidence` 를 읽는 PIT 배지다."),
    Badge(("data-lookahead",), (AXIS_LOOKAHEAD,),
          "E 가 만든 자리. 예전에는 마법사의 `as-bt-badge ok` 가 `\"OOS · look-ahead "
          "없음\"` 을 **상수로** 단정했다 — 이제 응답의 `lookahead_evidence` 를 "
          "읽는다. BL4 에서 마법사를 지워 캔버스 정책 백테스트 렌더러(`NodeResultPanel`)가 "
          "이 자리를 잇는다(데이터 축은 그 옆의 `PerfLabel`)."),
    Badge(("ca-mockbadge",), (AXIS_DATA_SOURCE,),
          "종목 카드의 합성 데이터 표시(`c.priceIsSynthetic`)."),
    Badge(("t-mode-badge",), (AXIS_RUN_MODE,),
          "관리자 패널의 `MODE: REAL/MOCK`(`st.config.kis_real`). ★데이터 축이 "
          "아니라 실행 모드다★ — 이름이 닮아 섞기 쉽다."),
)

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _widgets() -> list[pathlib.Path]:
    """화면만 본다 — 공용 컴포넌트(`shared/ui`)는 배지를 **정의**하지 그리지 않는다."""
    return sorted(p for p in SRC.rglob("*.tsx")
                  if "shared/ui" not in str(p.as_posix()))


def _renders_marker(body: str, marker: str) -> bool:
    if marker.startswith("<"):            # 컴포넌트 사용(`<PerfLabel …>`)
        return bool(re.search(rf"{re.escape(marker)}\b", body))
    if marker.startswith("data-"):        # JSX 속성
        return f"{marker}=" in body
    return bool(re.search(rf'["\'`][^"\'`]*\b{re.escape(marker)}\b', body))


def _renders(path: pathlib.Path, badge: Badge) -> bool:
    body = _COMMENT.sub(" ", path.read_text(encoding="utf-8"))
    return any(_renders_marker(body, m) for m in badge.markers)


def axes_on(path: pathlib.Path) -> set[str]:
    out: set[str] = set()
    for b in BADGES:
        if _renders(path, b):
            out.update(b.axes)
    return out


def observation() -> dict[str, set[str]]:
    """화면 → 그 화면이 말하는 축들. ★판정이 아니라 관측이다★"""
    return {str(p.relative_to(FRONTEND)): a
            for p in _widgets() if (a := axes_on(p))}


# ═══════════════════════════════════════════════════════════════════════════════
# 레지스트리가 낡지 않게
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_registry_is_not_empty():
    """★테스트의 테스트★ — 비면 아래가 전부 공허하다."""
    assert len(BADGES) >= 5


@pytest.mark.parametrize("badge", BADGES, ids=lambda b: b.marker)
def test_every_registered_badge_still_exists(badge):
    """★등록만 하고 사라진 배지는 거짓말이다★ — 클래스를 지우면 여기서 red."""
    hits = [p for p in SRC.rglob("*.tsx") if _renders(p, badge)]
    assert hits, f"{badge.marker} 를 그리는 자리가 없다 — 레지스트리를 갱신하라"


@pytest.mark.parametrize("badge", BADGES, ids=lambda b: b.marker)
def test_every_badge_declares_known_axes_and_a_reason(badge):
    assert badge.axes and set(badge.axes) <= set(AXES)
    assert badge.note and badge.note.strip()


def test_every_axis_is_actually_claimed_by_some_badge():
    """★쓰이지 않는 축은 어휘가 아니라 소망이다★"""
    claimed = {a for b in BADGES for a in b.axes}
    assert claimed == set(AXES), set(AXES) - claimed


def test_the_axis_labels_cover_the_axes():
    assert set(AXIS_LABELS) == set(AXES)


# ═══════════════════════════════════════════════════════════════════════════════
# 관측 — ★줄이지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_some_screen_shows_more_than_one_axis():
    """채점표 ⑴ 이 적은 사실을 **확인**한다 — 고치라는 뜻이 아니다.

    ★축이 다르면 말하는 것이 다르다★ — 합치면 두 질문을 섞는 것이고 그것이
    `CLAUDE.md` §2 가 금지하는 형태다. 이 테스트는 그 사실이 **관측된다**는
    것만 건다.
    """
    obs = observation()
    assert obs, "정직 배지를 그리는 화면이 하나도 없다고?"
    multi = {f: a for f, a in obs.items() if len(a) > 1}
    assert multi, "축이 둘 이상인 화면이 없다면 채점표 ⑴ 이 낡은 것이다"


def test_the_policy_backtest_now_speaks_three_axes():
    """E 의 결과 — 데이터·성과 종류·룩어헤드가 **각자** 말한다.

    예전에는 데이터 축 하나와 **근거 없는 상수** 하나였다.
    """
    # BL4 — 마법사 `PolicyBacktest.tsx` 를 지웠다. 캔버스 정책 백테스트 결과가 같은 세 축을 말한다
    # (데이터·성과 종류 = `PerfLabel`, 룩어헤드 = `data-lookahead`).
    p = SRC / "widgets" / "portfolio-graph" / "NodeResultPanel.tsx"
    assert axes_on(p) == {AXIS_DATA_SOURCE, AXIS_PERF_KIND, AXIS_LOOKAHEAD}


def test_the_run_mode_badge_is_not_a_data_badge():
    """★이름이 닮아 섞기 쉽다★ — `MODE: MOCK` 은 실행 모드이지 데이터가 아니다."""
    p = SRC / "widgets" / "admin" / "DbStatusPanel.tsx"
    assert AXIS_RUN_MODE in axes_on(p)
    assert AXIS_DATA_SOURCE not in axes_on(p)


def test_this_file_does_not_demand_a_single_axis():
    """★이 파일이 주장하지 않는 것★ — 합치라고 말하지 않는다.

    테스트의 테스트: 위 관측 테스트가 언젠가 "축은 하나여야 한다" 로 바뀌면
    이 파일의 목적이 뒤집힌다. 그 의도를 소스에 못 박는다.
    """
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "통합하지 않는다" in src or "줄이지 않는다" in src
