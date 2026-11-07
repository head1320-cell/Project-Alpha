"""실데이터 **능력 선언**이 실제 능력과 맞는지 — ★과장과 거짓 사유를 함께 막는다★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` 부록 7 · 선행: `3802ccc`

## 왜 이 파일이 생겼나

`3802ccc` 에서 주주환원 토큰의 죽은 미지원 사유를 정리하며 *"저장소 전체에는 17개가
더 남아 있다"* 고 상한 테스트로 기록해 뒀다. 그것을 정리하려고 실측했더니 17개가
**두 종류**였다.

1. **15개** — `_derive` 가 실파생을 붙여 이미 `supported` 인데 `UNSUPPORTED_REASONS`
   항목만 남은 죽은 사유. `token_support()` 가 `k not in supported` 로 걸러 UI 에는
   안 보이지만, 그 팩터가 mock 으로 내려가면 **거짓 사유가 뜬다**.
2. **2개** — ★반대 방향의 결함★. `남자직원수`·`여자직원수` 는 사유가 낡은 게 아니라
   **능력 선언이 과장된** 경우였다:

   ```python
   d["female_emp"] = round(emp * fr / 100)          # fr = female_ratio
   d["male_emp"]   = round(emp * (1 - fr / 100))
   ```

   `emp` 는 DART 실값이지만 `fr` 은 `MOCK_ONLY` 다 — `_real_business` 는 성별을
   내지 않는다(`employees`·`avg_salary`·`executives` 뿐). ★실값 × 합성비율 =
   합성★인데 픽커는 이 둘을 실데이터 팩터로 제공했다. 스크리너 조건
   `남자직원수 > 1000` 이 **날조된 값**으로 종목을 걸렀다. 이 저장소가 스스로 적어
   둔 원칙에 정면으로 어긋난다 — *"합성값 → 실데이터 원칙상 픽커/조건식에서
   비활성"*(`extended_factors_store.py`).

## 다루지 않은 셋째 — 설명 없는 가정 상수

`ccc`·`net_fin_asset` 은 `유동부채×0.35`·`총부채×0.5` 라는 가정을 쓴다. ★입력이 실
DART 값이라 위 둘과 성격이 다르다★ — 날조가 아니라 **모델링 근사**다. 그래서
강등하지 않고 **드러냈다**: 상수에 이름을 주고 사용자 설명문에 가정을 적었다.

## 짝 검증이 왜 필요한가

- E1(죽은 사유 0) 만 있으면 **"사유를 전부 지운다"** 로도 통과한다 → E2 가 막는다.
- E3(둘이 REAL_CAPABLE 아님) 만 있으면 **"전부 강등"** 으로도 통과한다 → E4 가 막는다.
- E7·E8(설명문에 가정) 만 있으면 상수 값이 조용히 바뀌어도 모른다 → E9 가 막는다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import io  # noqa: E402
import tokenize  # noqa: E402

import pytest  # noqa: E402

import src.kis_strategies.factor_tokens as ft  # noqa: E402
from src.data.extended_factors_store import (  # noqa: E402
    DPO_PAYABLES_RATIO,
    EXT_FACTOR_BY_ID,
    FINANCIAL_DEBT_RATIO,
    MOCK_ONLY_IDS,
    REAL_CAPABLE_IDS,
    ExtendedFactorsStore,
)

#: 오염된 의존 — 실값 × 합성비율
SYNTHETIC_PAIR = ("female_emp", "male_emp")
SYNTHETIC_TOKENS = ("남자직원수", "여자직원수")
#: ★같은 DART 호출에서 실제로 나오는 것들★ — 함께 강등하지 않는다
REAL_BUSINESS_IDS = ("employees", "avg_salary", "executives")


# ══════════════════════════════════════════════════════════════════════════
# 1) 죽은 사유 — ★0 이다★ (그리고 전부 지운 것이 아니다)
# ══════════════════════════════════════════════════════════════════════════
def test_no_supported_token_carries_an_unsupported_reason():
    """E1 — 지원되는데 미지원 사유가 남은 항목이 하나도 없다.

    `3802ccc` 의 상한(`<= 17`)을 **0** 으로 강화한 것이 이번 범위다.
    """
    supported = ft.token_support()["supported"]
    dead = sorted(k for k in ft.UNSUPPORTED_REASONS if k in supported)
    assert dead == [], f"이미 지원되는데 사유가 남아 있다: {dead}"


def test_unsupported_tokens_still_carry_reasons():
    """E2 ★짝★ — "사유를 전부 지운다" 는 구현을 배제한다.

    E1 만 있으면 `UNSUPPORTED_REASONS = {}` 로도 green 이 된다. 그러면 UI 배지가
    통째로 *"미지원 — 평가 시 무시됨"* 이라는 기본 문구로 퇴화한다.
    """
    ts = ft.token_support()
    assert len(ts["unsupported"]) >= 50, "미지원 사유가 통째로 사라졌다"
    # 진짜 미지원인 대표 항목들은 여전히 구체적 사유를 갖는다
    for tok in ("무형자산비중", "매입채무증가율", "공매도거래량", "자사주보유비율",
                "배당횟수", "목표주가수익률"):
        assert ts["unsupported"].get(tok), f"{tok} 의 사유가 사라졌다"


def test_the_two_surviving_derive_reasons_are_genuinely_underived():
    """E2 보강 — 남긴 둘이 **정말** 파생이 없는지 실측한다.

    사유를 지울지 남길지는 취향이 아니라 사실이다. `_derive` 결과에 키가 없어야
    "파생 미구현" 이 참이다.
    """
    got = ExtendedFactorsStore.get_default().get_factors("005930")
    derived = ExtendedFactorsStore.get_default()._derive("005930", dict(got))
    for fid in ("intangible_ratio", "payable_growth"):
        assert derived.get(fid) is None, f"{fid} 에 파생이 생겼다 — 사유를 지워야 한다"


# ══════════════════════════════════════════════════════════════════════════
# 2) 능력 선언 — ★오염된 둘만 내린다★
# ══════════════════════════════════════════════════════════════════════════
def test_synthetic_input_factors_are_not_declared_real_capable():
    """E3 — `female_emp`·`male_emp` 는 실데이터 팩터가 아니다."""
    for fid in SYNTHETIC_PAIR:
        assert fid not in REAL_CAPABLE_IDS, f"{fid} 가 실데이터 팩터로 선언됐다"
        assert fid in MOCK_ONLY_IDS, f"{fid} 가 MOCK_ONLY 로 떨어지지 않았다"


def test_the_genuinely_real_business_factors_stay_real_capable():
    """E4 ★짝★ — "전부 강등" 을 배제한다.

    `_real_business` 가 DART `empSttus`·`exctvSttus` 에서 **실제로** 받는 셋은
    그대로 둔다. 강등이 목적이 아니라 **의존이 오염된 것만** 내리는 것이 목적이다.
    """
    for fid in REAL_BUSINESS_IDS:
        assert fid in REAL_CAPABLE_IDS, f"{fid} 까지 강등됐다 — 범위를 넘었다"
        assert fid not in MOCK_ONLY_IDS


def test_the_demoted_tokens_are_unsupported_and_say_why():
    """E5 — 사용자에게 뜨는 사유가 **합성 입력**을 지목한다.

    ★`REASON_BIZREPORT`("사업보고서 미연동") 로는 거짓말이 된다★ — 사업보고서는
    연동돼 있다. 막힌 이유는 성별 비율에 실데이터 경로가 없다는 것이다.
    """
    ts = ft.token_support()
    for tok in SYNTHETIC_TOKENS:
        assert tok not in ts["supported"], f"{tok} 이 아직 픽커에 노출된다"
        reason = ts["unsupported"].get(tok, "")
        assert reason == ft.REASON_SYNTHETIC_INPUT, f"{tok} 의 사유가 다르다: {reason!r}"
        assert "합성" in reason and "직원수" in reason
        assert "미연동" not in reason, "연동돼 있는데 미연동이라고 말한다"


def test_the_ratio_they_depend_on_has_no_real_path():
    """E6 — ★강등의 근거를 사실로 못 박는다★

    `female_ratio` 가 `MOCK_ONLY` 라는 것이 §E3 의 유일한 근거다. 근거 없이 다시
    올리면(변이 U8) 이 테스트가 죽는다. 그리고 그 선언이 **자의적이지 않음**을
    소스 토큰으로 확인한다 — `_real_business` 는 성별을 내지 않는다.

    ★소스는 `tokenize` 로 본다★ — 문자열 grep 은 이 파일의 산문에 걸린다
    (이 저장소에서 세 번 겪었다).
    """
    assert "female_ratio" in MOCK_ONLY_IDS, "성별 비율에 실데이터 경로가 생겼는가?"

    import inspect

    src = inspect.getsource(ExtendedFactorsStore._real_business)
    produced = {
        t.string.strip("\"'")
        for t in tokenize.generate_tokens(io.StringIO(src).readline)
        if t.type in (tokenize.NAME, tokenize.STRING)
    }
    assert "female_ratio" not in produced, "_real_business 가 성별 비율을 낸다 — 재평가하라"
    assert "employees" in produced, "가드가 무의미해졌다 — 소스를 못 읽고 있다"


# ══════════════════════════════════════════════════════════════════════════
# 3) 가정 상수 — ★드러내되 값은 그대로★
# ══════════════════════════════════════════════════════════════════════════
def test_ccc_exposes_its_payables_assumption():
    """E7 — 상수에 이름이 있고, 사용자 설명문이 가정을 말한다."""
    assert DPO_PAYABLES_RATIO == pytest.approx(0.35)
    desc = EXT_FACTOR_BY_ID["ccc"].description
    assert "가정" in desc, f"근사임이 설명문에 없다: {desc!r}"
    assert "0.35" in desc, f"가정 계수가 설명문에 없다: {desc!r}"


def test_net_fin_asset_exposes_its_debt_assumption():
    """E8 — 동일. ★"(현금-부채)/시총" 은 사실이 아니었다★ — 부채의 절반만 쓴다."""
    assert FINANCIAL_DEBT_RATIO == pytest.approx(0.5)
    desc = EXT_FACTOR_BY_ID["net_fin_asset"].description
    assert "가정" in desc, f"근사임이 설명문에 없다: {desc!r}"
    assert "0.5" in desc, f"가정 계수가 설명문에 없다: {desc!r}"


@pytest.mark.parametrize("code,ccc,nfa", [("005930", 196.1, -36.78),
                                          ("000660", 50.2, -7.39)])
def test_naming_the_constants_did_not_change_the_numbers(code, ccc, nfa):
    """E9 — ★상수 명명은 순수 리팩터링이었다★

    리터럴을 상수로 바꾸면서 값이 바뀌는 것이 이 변경의 전형적 사고다(변이 U5).
    기준값은 리팩터링 **직전** 실측이다.
    """
    f = ExtendedFactorsStore.get_default().get_factors(code)
    assert f["ccc"] == pytest.approx(ccc)
    assert f["net_fin_asset"] == pytest.approx(nfa)


def test_demotion_did_not_stop_the_values_being_computed():
    """E9 짝 — ★강등은 **선언**을 고친 것이지 계산을 끈 것이 아니다★

    `_derive` 는 여전히 두 값을 낸다(mock 표시용). 바뀐 것은 픽커·조건식에서
    실데이터 팩터로 **팔리지 않는다**는 점이다. 계산까지 지우면 mock 화면에
    구멍이 생긴다.
    """
    f = ExtendedFactorsStore.get_default().get_factors("005930")
    assert f["female_emp"] == 9897 and f["male_emp"] == 19437


# ══════════════════════════════════════════════════════════════════════════
# 4) 델타 — ★줄어든 것이 정확히 그 둘이다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_thesis_bridge_narrowed_by_exactly_the_two():
    """E10 — 93 → 91. 재현으로 델타를 확인한 뒤 고정했다.

    ★다리가 좁아진 것이 아니라 건널 자격이 없던 둘을 내린 것이다.★
    """
    from src.engine.company_thesis import token_maps

    _, reach = token_maps()
    assert len(reach) == 91, f"도달 가능 필드가 91 에서 바뀌었다: {len(reach)}"
    for fid in SYNTHETIC_PAIR:
        assert fid not in reach, f"{fid} 이 다리에 돌아왔다 — 합성값이 조건식에 샌다"
    for fid in REAL_BUSINESS_IDS:
        assert fid in reach, f"{fid} 이 다리에서 사라졌다 — 델타가 둘을 넘었다"


def test_supported_token_count_dropped_by_exactly_the_two():
    """E11 — 316 → 314. 두 경로(`FUNDAMENTAL_ALIASES`·`_label_aliases`) 모두에서
    빠졌는지 확인한다 — 한쪽만 막으면 다른 쪽으로 여전히 노출된다.

    ★2026-09 · 314 → 322★ `FRED_INDICATOR_TOKENS` 8개(개정되는 매크로 계열 —
    CPI·고용·실업률·산업생산·통화량·소비자심리·실질GDP·금융환경지수)를 조건식
    어휘에 열었다. E11 의 강등(합성 팩터 2개 제거)은 그대로이고, 아래 단언들이
    그것을 계속 지킨다.

    ★수를 파생식으로 바꾸지 않는다★ — `314 + len(FRED_INDICATOR_TOKENS)` 로 적으면
    토큰을 더할 때마다 자동으로 통과해 이 가드가 죽는다. 정확한 수를 적고, 바뀔
    때마다 **왜** 바뀌었는지 여기에 남긴다.
    """
    supported = ft.token_support()["supported"]
    assert len(supported) == 322, f"지원 토큰 수가 322 에서 바뀌었다: {len(supported)}"
    for tok in SYNTHETIC_TOKENS:
        assert tok not in supported
    for tok in ("직원수", "평균급여", "임원수", "1인당매출액", "1인당영업이익"):
        assert tok in supported, f"{tok} 까지 사라졌다 — 강등이 번졌다"


def test_both_alias_paths_agree_on_the_demotion():
    """E11 짝 — 별칭 두 경로가 같은 판정을 쓴다(둘 다 `MOCK_ONLY_IDS` 기준)."""
    manual = {t for t, fid in ft.FUNDAMENTAL_ALIASES.items() if fid in SYNTHETIC_PAIR}
    auto = {t for t in ft._label_aliases() if t in SYNTHETIC_TOKENS}
    assert auto == set(), f"라벨 자동 별칭이 아직 노출한다: {auto}"
    supported = ft.token_support()["supported"]
    assert not (manual & set(supported)), f"수동 별칭이 아직 노출한다: {manual}"
