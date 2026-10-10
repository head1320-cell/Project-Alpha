"""★트립와이어★ — 증거 축을 **단정**하는 화면은 그 증거를 읽어야 한다 (E4).

설계: `docs/superpowers/specs/2026-09-18-evidence-claim-design.md`

## 왜 이 파일이 생겼나

`PolicyBacktest.tsx` 가 `"OOS · look-ahead 없음"` 을 **하드코딩 상수**로 그리고
있었다. 응답에 근거 필드가 하나도 없는데도 결과만 나오면 무조건 렌더됐고, E2E 가
그 문구를 단정해 **테스트가 거짓 주장을 지키고** 있었다. ★AL 의
`selection_effect=0`, AM 의 `"dev"` 와 같은 모양 — 상수가 관측 행세를 한다.★

## ★어휘로 걸면 안 된다 — 실측 1 대 17★

"주장 어휘"(룩어헤드·OOS·검증됨·보장·안전·무결…) 검출기를 프런트 전수에 돌려
21건을 잡았는데 **진짜는 하나**, 약한 건 셋, 오탐 **열일곱**이었다:

  무위험이자율·무위험수익률·무위험금리 ×4   금융 용어(risk-free rate)
  `validated: "검증됨"`                      백엔드 enum 의 **번역**
  `alphaTouched ? "검증됨" : "미검증"`        **삼항 — 관측이다**
  `…"검증됨" 이 되지 않습니다`               **부정문**
  `시점 정합을 판정할 자료가 없습니다`       **모범적 미상 문장**
  `미래 수익을 보장하지 않습니다`            **면책**
  `look-ahead 주의`                          **경고**
  `macro_lookahead` · `IS / OOS`             **식별자 · 표 머리글**

신호 대 잡음이 1:17 이면 허용목록이 본문보다 길어지고, 그러면 다음 사람은 읽지
않고 한 줄 더 붙인다. ★그것은 "삭제하거나 상수로 박아도 통과하는 테스트" 의
사촌이다.★

## 그래서 **구조**로 건다

    ① 리터럴이 **부재·보장을 단정**한다 — `룩어헤드 없음` · `편향 없음` ·
       `시점 정합 확인` · `정합 보장`. ★`OOS`·`표본외`·`무위험`은 주장이 아니라
       **서술어**라 여기 없다★
    ② 부정·경고·면책·삼항·식별자·주석은 단정이 아니다 (실측 오탐 17건이 전부 여기)

★처음 설계는 달랐다 — 실측이 뒤집었다★ 원래 규칙은 *"단정하는데 **대응 응답
필드를 안 읽는다**"* 였다. 변이 배터리가 그것을 죽였다: 옛 상수 배지를 그대로
되돌려 놓아도 **통과했다.** `PolicyBacktest.tsx` 가 파일의 다른 곳에서
`lookahead_evidence` 를 읽고 있으니 면제된 것이다.

★증거를 읽는다고 상수로 단정할 권리가 생기지는 않는다.★ 상수 문자열은 파일이
무엇을 읽든 변하지 않는다. 그래서 응답 필드 참조는 **면제 사유에서 진단**으로
내렸다 — 위반 메시지가 *"이 파일은 그 값을 이미 받고 있으니 그것을 그려라"* 고
말할 뿐이다.

★이 파일이 지키는 것은 인스턴스가 아니라 부류다★ — 지금 고친 한 자리가 아니라
**앞으로 생길** 근거 없는 주장을 막는다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[1] / "frontend"
SRC = FRONTEND / "src"


# ═══════════════════════════════════════════════════════════════════════════════
# 축 레지스트리 — 무엇을 단정하면 무엇을 읽어야 하는가
# ═══════════════════════════════════════════════════════════════════════════════
#: `단정 패턴 → 그 주장을 뒷받침해야 하는 응답 필드들`.
#: ★무위험(risk-free)은 넣지 않는다★ — 정당한 금융 용어이고 주장이 아니다.
CLAIM_AXES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "no_lookahead": (
        (r"look-?ahead\s*없", r"룩어헤드\s*없", r"선견\s*없"),
        ("lookahead_evidence", "estimator_leakage", "execution_assumption",
         "macro_lookahead"),
    ),
    "pit_aligned": (
        (r"시점\s*정합\s*(?:됨|완료|확인)", r"\bPIT\s*(?:검증|정합)\s*(?:됨|완료)"),
        ("pit_evidence", "is_pit_verified", "pit"),
    ),
    "no_survivorship": (
        (r"생존\s*편향\s*없", r"편향\s*없"),
        ("survivorship", "universe_meta", "lookahead_evidence"),
    ),
    "guaranteed": (
        (r"보장합니다", r"보장됨", r"정합\s*보장", r"무결\s*보장"),
        ("evidence", "verdict", "verified", "run_id"),
    ),
}

#: ★주장이 아니라는 표지★ — 부정·경고·면책·미상 문장.
NEGATION = re.compile(
    r"않습니다|않는다|않음|아닙니다|아니다|못했|없었|주의|경고|"
    r"판정할\s*자료가\s*없|모릅니다|미상|되지\s*않")

#: 코드 식별자(필드명·enum 키)는 산문이 아니다.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

#: ★사유 없는 면제는 없다★ 값이 비면 아래 테스트가 실패한다.
#: 실측(2026-09-18): 오탐 17건은 규칙이 스스로 거르고, 남는 것은 **하나**다.
#:
#: ★목록이 세 번 바뀌었고 매번 실측이 이겼다★
#:   처음: 셋(랜딩 · journal 제목 · ResearchRunsPanel)
#:   둘째: `journal` 제목은 규칙이 애초에 잡지 않는다(여러 줄 리터럴) → 유령
#:   셋째: `ResearchRunsPanel` 은 `perf_label` 을 읽어 당시 규칙 ②가 해제 → 유령
#:   넷째: 변이 배터리가 ②를 죽였고(면제가 상수 배지를 통과시켰다) ②를 진단으로
#:         내리자 `ResearchRunsPanel` 이 **다시 필요**해졌다. 동시에 `OOS` 축을
#:         빼면서 랜딩은 **필요 없어졌다**.
#: ★필요 없는 면제는 유령이고, 유령은 "여기는 원래 예외" 라고 거짓말한다.★
#: `test_every_weak_claim_is_actually_needed` 가 매번 그것을 잡아냈다.
#:   다섯째(BL4): 마법사를 지우며 `ResearchRunsPanel` 도 사라졌다 → **면제 0**. 빈 목록은 "면제가 없다" 는
#:         좋은 상태다. 대신 스캐너가 살아 있는지는 그 파일이 쓰던 모양(`정합 보장`)을 심은 표본으로 지킨다
#:         (`test_the_scanner_is_not_dead`).
WEAK_CLAIMS: dict[str, str] = {}

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
#: 보간(`{}`)이 없는 **순수** 리터럴만 본다 — 보간이 있으면 값이 데이터에서 온다.
_JSX_TEXT = re.compile(r">([^<>{}]{2,200})<", re.S)
_STRING = re.compile(r"""(?<![\w$])["']([^"'\n{}]{2,200})["']""")


def _sources() -> list[pathlib.Path]:
    return sorted([*SRC.rglob("*.tsx"), *SRC.rglob("*.ts")])


def _rel(p: pathlib.Path) -> str:
    return str(p.relative_to(FRONTEND))


def _is_ternary_branch(line: str) -> bool:
    """★삼항의 가지는 상수가 아니다★ — 조건이 값을 고른다(= 관측이다)."""
    return "?" in line and ":" in line


def claims_in(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """이 파일이 **단정**하는 축들. `(axis, 리터럴, 줄번호)`."""
    raw = path.read_text(encoding="utf-8")
    body = _COMMENT.sub(" ", raw)          # ★주석은 주장이 아니다★
    out: list[tuple[str, str, int]] = []
    for lineno, line in enumerate(body.splitlines(), 1):
        if _is_ternary_branch(line):
            continue
        for rx in (_JSX_TEXT, _STRING):
            for m in rx.finditer(line):
                frag = " ".join(m.group(1).split())
                if not frag or IDENTIFIER.match(frag) or NEGATION.search(frag):
                    continue
                for axis, (pats, _fields) in CLAIM_AXES.items():
                    if any(re.search(p, frag, re.I) for p in pats):
                        out.append((axis, frag, lineno))
    return out


def reads_evidence(path: pathlib.Path, axis: str) -> bool:
    """이 파일이 그 축의 **응답 필드를 읽는가**. ★진단이지 면제가 아니다★

    위반 메시지에 *"이 값을 이미 받고 있다"* 를 덧붙이는 데 쓴다 — 고치는
    사람이 무엇을 그려야 할지 바로 알도록.
    """
    body = _COMMENT.sub(" ", path.read_text(encoding="utf-8"))
    _pats, fields = CLAIM_AXES[axis]
    return any(re.search(rf"\b{re.escape(f)}\b", body) for f in fields)


def violations() -> list[tuple[str, str, str, int]]:
    """`(파일, 축, 리터럴, 줄)` — **상수로 단정하는** 자리.

    ★`reads_evidence` 는 여기 없다★ — 변이 배터리가 가르친 것이다(위 머리글).
    파일이 증거를 읽는다는 사실은 상수 문자열을 관측으로 만들지 않는다.
    """
    out = []
    for p in _sources():
        rel = _rel(p)
        if rel in WEAK_CLAIMS:
            continue
        for axis, frag, lineno in claims_in(p):
            out.append((rel, axis, frag, lineno))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# ① 본 규칙
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_screen_asserts_evidence_it_does_not_read():
    """★증거를 안 읽는 화면은 증거를 주장할 수 없다★"""
    bad = violations()
    msg = []
    for f, ax, frag, ln in bad:
        hint = (" — ★이 파일은 이미 그 값을 받고 있다. 상수 대신 그것을 그려라★"
                if reads_evidence(FRONTEND / f, ax) else
                " — 응답에 근거가 없다. 백엔드가 먼저 실어야 한다")
        msg.append(f"{f}:{ln}  [{ax}] {frag}{hint}")
    assert not bad, "\n".join(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# ② ★테스트의 테스트★ — 규칙이 진짜를 잡는가 (항상-통과 배제)
# ═══════════════════════════════════════════════════════════════════════════════

#: E 이전 `PolicyBacktest.tsx` 의 실제 모양(응답을 읽지 않는 상수 배지).
_OLD_SHAPE = '''
export function PolicyBacktest() {
  return (
    <div className="as-bt-badges">
      <span className="as-bt-badge ok">OOS · look-ahead 없음</span>
    </div>
  );
}
'''


def test_the_rule_catches_the_shape_it_was_written_for(tmp_path):
    """★고친 그 모양이 돌아오면 반드시 걸린다★

    실물(`PolicyBacktest.tsx`)은 이제 고쳐졌으므로 본 규칙만으로는 이 규칙이
    **무엇이든 통과시키는 구현**과 구별되지 않는다. 옛 모양을 픽스처로 넣는다.
    """
    f = tmp_path / "OldPolicyBacktest.tsx"
    f.write_text(_OLD_SHAPE, encoding="utf-8")
    found = claims_in(f)
    assert found, "옛 상수 배지를 단정으로 잡지 못했다"
    assert {a for a, _, _ in found} == {"no_lookahead"}
    assert not reads_evidence(f, "no_lookahead"), "읽지도 않는데 읽는다고 판정했다"


def test_reading_the_evidence_clears_the_same_shape(tmp_path):
    """★짝★ — 응답을 읽으면 같은 문구라도 위반이 아니다(그것이 관측이다)."""
    f = tmp_path / "NewPolicyBacktest.tsx"
    f.write_text(_OLD_SHAPE.replace(
        "<div className=\"as-bt-badges\">",
        "<div className=\"as-bt-badges\" data-x={res.lookahead_evidence?.status}>"),
        encoding="utf-8")
    assert reads_evidence(f, "no_lookahead")


# ═══════════════════════════════════════════════════════════════════════════════
# ③ ★테스트의 테스트★ — 규칙이 오탐을 거르는가 (규칙이 어휘로 퇴화하면 red)
# ═══════════════════════════════════════════════════════════════════════════════
#
# 실측한 오탐 17건의 **모양**을 그대로 넣는다. 하나라도 걸리면 규칙이 다시 어휘
# 수준으로 내려갔다는 뜻이다.

_FALSE_POSITIVES = {
    "금융용어-무위험이자율": '<div className="x">무위험이자율 (r)</div>',
    "금융용어-무위험수익률": '<span>무위험 대비 위험조정수익 (초과수익/변동성)</span>',
    "금융용어-무위험금리": '<th>무위험금리 (Kₑ 주입)</th>',
    "enum번역": 'const S = { validated: "검증됨", retired: "폐기" };',
    "삼항": 'const sub = alphaTouched ? "검증됨" : "미검증";',
    "부정문": '<p>제외 전 기준이고, 그래서 이 실행은 "검증됨" 이 되지 않습니다.</p>',
    "미상문장": '<span>시점 정합을 판정할 자료가 없습니다.</span>',
    "미상문장2": '<span>시점 정합을 판정할 자료가 이 실행에 없습니다 — 검증됐다는 뜻이 아닙니다.</span>',
    "면책": '<em>미래 수익을 보장하지 않습니다.</em>',
    "경고": '<div>⚠ 당일 종가로 만든 신호를 시가에 체결하면 look-ahead — 주의</div>',
    "경고2": '<span>현재 스냅샷 기준 · look-ahead 주의</span>',
    "식별자": 'const key = "macro_lookahead";',
    "표머리글": '<th scope="col">IS</th>',
    "주석만": '// 룩어헤드 없음 · 정합 보장 — 주석은 주장이 아니다',
    # ── ★아래 넷은 패턴을 **실제로 맞힌 뒤** 필터에 걸린다★ ──────────────
    # 변이 배터리가 가르쳤다: 위 오탐들은 패턴에 닿지도 못해서 부정·삼항·식별자
    # 필터가 **한 번도 실행되지 않았고**, 필터를 통째로 지워도 전부 초록이었다.
    # ★공허한 분기는 증거가 아니다★(AL 의 변이 `d`). 그래서 진짜로 밟게 한다.
    "부정-패턴적중": '<p>이 실행이 룩어헤드 없음을 뜻하지는 않습니다.</p>',
    "면책-패턴적중": '<em>정합 보장을 하지 않습니다.</em>',
    "삼항-패턴적중": 'const t = ok ? "룩어헤드 없음" : "룩어헤드 미상";',
    "경고-패턴적중": '<span>⚠ 편향 없음을 확인하지 못했습니다 — 주의</span>',
}


@pytest.mark.parametrize("name", sorted(_FALSE_POSITIVES))
def test_the_rule_does_not_fire_on_measured_false_positives(tmp_path, name):
    """★규칙이 어휘로 퇴화하면 여기서 red 가 된다★ (실측 오탐 17건의 모양)"""
    f = tmp_path / f"{name}.tsx"
    f.write_text(_FALSE_POSITIVES[name], encoding="utf-8")
    assert not claims_in(f), f"{name}: {claims_in(f)}"


def test_the_false_positive_fixtures_are_not_empty():
    """★테스트의 테스트★ — 비면 위 전수 테스트가 공허하다."""
    assert len(_FALSE_POSITIVES) >= 10


# ═══════════════════════════════════════════════════════════════════════════════
# ④ 허용목록 규율
# ═══════════════════════════════════════════════════════════════════════════════

def test_every_weak_claim_has_a_reason():
    """★사유 없는 면제는 없다★ (면제가 0 이면 공허하게 통과한다 — 목록이 비는 것이 목표이므로 괜찮다)"""
    for path, reason in WEAK_CLAIMS.items():
        assert reason and reason.strip(), path


def test_the_weak_claim_files_exist():
    """면제가 유령을 가리키면 목록이 낡은 것이다."""
    for rel in WEAK_CLAIMS:
        assert (FRONTEND / rel).exists(), rel


def test_the_weak_claim_list_stays_short():
    """★허용목록이 본문보다 길면 다음 사람은 읽지 않는다★

    어휘 검출기를 그대로 썼다면 여기 17줄이 들어왔을 것이다. 구조 규칙으로
    좁혔기 때문에 셋으로 끝난다 — 이 숫자가 늘면 규칙을 다시 보라는 신호다.
    """
    assert len(WEAK_CLAIMS) <= 5


def test_the_fixed_widget_is_not_on_the_allow_list():
    """`PolicyBacktest` 는 면제가 아니라 **고쳤다**."""
    assert not any("PolicyBacktest" in p for p in WEAK_CLAIMS)


@pytest.mark.parametrize("rel", sorted(WEAK_CLAIMS))
def test_every_weak_claim_is_actually_needed(rel):
    """★유령 면제를 막는다★ — 면제를 빼면 **반드시** 위반이 되어야 한다.

    처음 목록에 없어도 되는 항목이 하나 있었다. 그런 줄은 다음 사람에게
    *"여기는 원래 예외"* 라고 거짓말하고, 정작 규칙이 그 파일을 보고 있지도
    않다는 사실을 가린다. 사유가 있다고 필요한 것은 아니다.
    """
    p = FRONTEND / rel
    # ★`reads_evidence` 를 여기서도 뺐다★ — ②가 진단으로 내려갔으므로 "필요한
    # 면제" 의 뜻도 바뀐다: 규칙이 이 파일에서 **단정을 찾는가** 하나뿐이다.
    assert claims_in(p), f"{rel} 은 면제가 필요 없다 — 목록에서 지우십시오"


def test_the_scanner_is_not_dead(tmp_path):
    """★공허한 통과를 막는다★ (AL 의 변이 `d` 가 가르친 것)

    본 규칙(`test_no_screen_asserts_evidence_it_does_not_read`)은 지금 **위반 0** 이고, BL4 로 마법사가 사라진 뒤에는
    운영 소스의 **단정 후보도 0** 이다(마지막 후보 `ResearchRunsPanel.tsx` 의 툴팁 "inputs/outputs 정합 보장" 이 마법사와
    함께 지워졌다). 스캐너가 죽어도 똑같이 초록이므로 둘을 가른다: ① 운영 소스를 실제로 훑는다(파일 수) ② 지워진 파일이
    쓰던 **바로 그 모양**을 심으면 잡는다 ③ 짝 — 같은 문장을 부정하면 잡지 않는다.
    """
    srcs = _sources()
    assert len(srcs) > 100, f"운영 소스를 {len(srcs)}개만 봤다 — 경로가 틀렸다"
    for p in srcs:
        claims_in(p)                                  # 어느 파일에서도 깨지지 않는다
    planted = tmp_path / "PlantedRunsPanel.tsx"
    planted.write_text('<button title="inputs/outputs 정합 보장">재계산</button>\n'
                       '<span>OOS · look-ahead 없음</span>\n', encoding="utf-8")
    axes = {ax for ax, _, _ in claims_in(planted)}
    assert {"guaranteed", "no_lookahead"} <= axes, axes
    negated = tmp_path / "NegatedRunsPanel.tsx"
    negated.write_text('<span>룩어헤드 없음을 판정할 자료가 없습니다</span>\n', encoding="utf-8")
    assert not claims_in(negated)
