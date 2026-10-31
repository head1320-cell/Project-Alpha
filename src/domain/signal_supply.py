"""신호의 **공급 모듈** — ★적히지 않았던 규칙을 적는다★ (AY, 순수 계층)
==============================================================================
소비자: `src/domain/signal_evidence.py`(출처 등급) · 검증
`tests/test_signal_supply.py` · 선례 `src/engine/version_registry.MISSING_AXES`

## 1. 규칙 — `origin` 은 무엇인가

AW 가 `filter_ast.ORIGINS` 를, AX 가 `timing_factor_meta.TIMING_ORIGINS` 를
만들면서 여섯 값을 썼는데 **규칙이 한 번도 적히지 않았다**:

    ★`origin` 은 실재하는 `src/data/` 공급 모듈의 이름이다.★

여섯 값 모두 그러한데(실측) 아무도 그것을 걸지 않았다. `SUPPLY_PACKAGE` 가
그 규칙을 한 곳에 두고, 테스트가 **모든 선언된 값**을 실제로 임포트해 본다.
오타도, 테이블 이름도, 경로 문자열도 거기서 죽는다.

## 2. ★규칙이 처음으로 부딪힌 자리★

`alpha_expr`(fund) 7개의 값은 `alpha_lab._load_fundamentals` 가
`financials_history` 를 **직접 SELECT** 해서 온다 — 어느 `src/data/` 모듈도
지나지 않는다. 같은 파일의 `_load_price_series` 는 `src.data.ohlcv_loader` 를
지난다. ★같은 모듈 안에서 한쪽만 계층을 지킨다.★

`financials_history` 를 `origin` 에 적으면 한 칸에 **모듈 이름**과 **테이블
이름** 두 종류가 섞여 다음 사람이 구별할 수 없다 — AV 가 `E2` 두 척도에서,
AW 가 `FactorMeta.source` 에서 겪은 것과 같은 모양이다. 그래서 적지 않는다.

## 3. ★"모른다" 대신 "이것이 참인 동안은 못 붙인다"★

등급을 억지로 붙이지도, 사유를 *"모릅니다"* 로 뭉개지도 않는다. **무엇을
관측했는지 · 그것이 어떤 질문을 막는지 · 무엇이 참이 되면 붙일 수 있는지**를
적고, ★그 조건이 아직 참인지를 테스트가 확인한다★. 누군가 결함을 고치면
테스트가 red 가 되고 **그것이 곧 승급 신호다**.

`version_registry.MissingAxis` 가 세운 선례에 `promotes_when` 한 칸을 더한
것이다 — 그 docstring 이 *"사유 없이 '없다' 고만 적으면 갚을 수 없는 부채"*
라고 적어 두었다.

## 4. ★이 모듈이 말하지 않는 것★

**개정(빈티지) 축을 말하지 않는다.** `financials_history` 가 정정이 원본을
덮는 표라는 것은 사실이지만 **다른 축**이고, 제 칸이 따로 있다
(`SignalDefinition.revision_policy` — 이미 `revised` 어휘를 쓴다).
한 사유에 두 축을 담으면 다음 사람이 어느 쪽을 고쳐야 하는지 모른다.
"""
from __future__ import annotations

from dataclasses import dataclass

#: ★`origin` 어휘의 규칙★ — 선언된 모든 출처는 이 패키지의 실재 모듈이다.
#: 테스트가 `importlib.import_module(f"{SUPPLY_PACKAGE}.{origin}")` 로 건다.
SUPPLY_PACKAGE = "src.data"


@dataclass(frozen=True)
class UnsuppliedSignal:
    """★`src/data/` 공급 모듈을 지나지 않는 신호 묶음★

    `version_registry.MissingAxis` 와 같은 모양이고 `promotes_when` 이 하나
    더 있다 — **언제 이 항목을 지울 수 있는지**를 적어 두지 않으면 레지스트리
    자체가 부채가 된다.
    """

    #: `"<kind>.<group>"` — 카탈로그에서 이 묶음을 가리키는 키.
    key: str
    label: str
    #: ★실측한 사실만★ — 어디서 오는가. 추측을 적지 않는다.
    reason: str
    #: 이것 때문에 **답할 수 없는 질문**.
    blocks: str
    #: ★무엇이 참이 되면 등급을 붙일 수 있나★ — 테스트가 이 조건을 지킨다.
    promotes_when: str


UNSUPPLIED: tuple[UnsuppliedSignal, ...] = (
    UnsuppliedSignal(
        key="alpha_expr.fund",
        label="알파 표현식 — 펀더멘털 피처",
        reason=("이 일곱 피처의 값은 alpha_lab._load_fundamentals 가 "
                "financials_history 표를 직접 SELECT 해서 옵니다 — "
                "src/data/ 의 어느 공급 모듈도 지나지 않아 출처를 물을 자리가 "
                "없습니다. 같은 모듈의 _load_price_series 는 ohlcv_loader 를 "
                "지납니다(비대칭). 표 이름은 모듈 이름과 다른 종류라 출처 "
                "어휘에 넣지 않습니다."),
        blocks=("\"이 값이 어느 적재 경로에서 왔고 그 경로가 합성인가\" 를 "
                "답할 수 없습니다. mock 게이트도 이 경로를 지배하지 않습니다."),
        promotes_when=("_load_fundamentals 가 src/data/ 의 공급 모듈을 지나게 "
                       "되면 그 모듈 이름이 곧 출처가 됩니다 — "
                       "tests/test_signal_supply.py 가 그때 red 로 알립니다."),
    ),
)

#: 키로 찾는 색인. ★반드시 `UNSUPPLIED` 에서 파생한다★ — 따로 적으면 두 읽기
#: 경로가 갈라진다(`source_registry` 가 같은 이유를 적어 두었다).
UNSUPPLIED_BY_KEY = {e.key: e for e in UNSUPPLIED}
