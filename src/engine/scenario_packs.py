"""ScenarioPackV2 — 시나리오 팩 단일 레지스트리 (스펙 §5, Phase 9).

무엇이 문제였나
──────────────────────────────────────────────────────────────────────────────
시나리오 15종이 서로 모르는 세 곳에 흩어져 있었다 — `stress_test_analyzer.STRESS_SCENARIOS`
(가상 4) · `_HIST_WINDOWS`(역사 리플레이 4, 라우터 안에 상수로) · `kr_scenario_pack.SCENARIOS`
(국내팩). 그리고 **`model_type` 이 어디에도 없었다.** `/stress-scenarios` 는 `mode: "kr_pack"`
을 실어 보냈는데 그건 *패밀리*이지 인식론적 주장이 아니다 — 화면의 어디에도 "이 일곱은 가정이다"
라고 적혀 있지 않았다. 스펙 §5 가 막으려는 실패가 정확히 그것이다:
**가상 충격이 역사적 사실처럼 제시되는 것.**

이 모듈이 하는 일
──────────────────────────────────────────────────────────────────────────────
세 출처를 **감싼다**(옮겨 심지 않는다). 계수는 한 벌뿐이고, 여기에는 그 계수를 가리키는
`engine`/`engine_key` 와 §5 가 요구하는 두 축이 붙는다:

  · `family`      — 12개 패밀리 중 어디에 속하는가 (분류 축)
  · `model_type`  — 역사 리플레이인가 가정인가 (인식론 축)

★두 축을 하나로 합치면 안 된다★ §3.5 의 `data_status`/`research_usage` 와 같은 이유다.
`mode` 는 기존 소비자를 위해 **한 글자도 바꾸지 않고** 남긴다 — `model_type` 은 그 옆에 붙는다.

정체성(identity)
──────────────────────────────────────────────────────────────────────────────
코드로 정의된 팩에는 버전을 적을 DB 행이 없다. 그런데 재현 문제는 `timing_rule_sets.version`
과 똑같다 — `"semi_selloff"` 라고만 적힌 런은 계수가 바뀌는 순간 재현되지 않는다. 그래서
**정의 자체의 해시**를 정체성으로 쓴다. 누가 기억해서 올려 주지 않아도 충격이 바뀌면 같이
바뀐다.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ModelType(str, Enum):
    """이 결과가 무엇인지에 대한 주장. **팩은 이것 없이 만들어질 수 없다.**"""

    #: 적재된 실제 시세를 그대로 재생한다. 강도 배율이 적용되지 않는다.
    HISTORICAL_REPLAY = "historical_replay"
    #: 팩터 민감도로 추정한 가정 충격. 일어난 적 없는 일일 수 있다.
    HYPOTHETICAL = "hypothetical"


#: 스펙 §5 가 요구하는 12 패밀리. **순서와 개수가 스펙 그대로다** — 비어 있는 패밀리도
#: 목록에서 빠지지 않는다(빠지면 "없는 것" 과 "채운 것" 이 화면에서 구별되지 않는다).
FAMILIES: tuple[tuple[str, str], ...] = (
    ("historical_replay", "역사 리플레이"),
    ("growth_inflation", "성장·인플레 국면 충격"),
    ("correlation_hedge_failure", "상관 수렴·주식채권 헤지 실패"),
    ("volatility_liquidity", "변동성 급등·유동성 진공"),
    ("credit_tightening", "신용·금융환경 긴축"),
    ("krw_foreign_flow", "원화 충격·외국인 수급 반전"),
    ("semiconductor_chain", "반도체 밸류체인 급락"),
    ("valueup_unwind", "밸류업 되돌림"),
    ("earnings_dispersion", "어닝시즌 분산 확대"),
    ("retail_deleveraging", "개인 디레버리징·레버리지 ETF 스트레스"),
    ("shortsell_borrow", "공매도·대차 제도 변경"),
    ("user_authored", "사용자 정의"),
)
FAMILY_LABEL: dict[str, str] = dict(FAMILIES)

#: 정적 팩이 하나도 없는 패밀리는 **사유와 함께** 비어 있다고 말한다.
_EMPTY_FAMILY_REASON: dict[str, str] = {
    "user_authored": "사용자가 직접 정의한 팩을 저장하는 기능은 아직 없습니다 — "
                     "지금은 실행 요청에 팩 정의를 직접 실어 보낼 수 있고(저장되지 않음), "
                     "저장·버전·삭제는 Phase 10 소관입니다.",
}

# ── 역사 리플레이 윈도우 ──────────────────────────────────────────────────────
# `allocation_routes.py` 안의 모듈 상수였다. 세 출처 중 둘은 엔진에 있는데 하나만 라우터에
# 있으면 레지스트리가 라우터를 import 해야 한다 — 그래서 정의를 이쪽으로 옮겼다.
# ★가용성은 여기 없다★ 그건 DB 적재 범위에 달린 **런타임** 사실이고, 라우터가 판정한다.
HIST_WINDOWS: dict[str, dict] = {
    "hist_2008_gfc": {"label": "2008 금융위기", "start": "2007-10-01", "end": "2009-03-31"},
    "hist_2018_trade": {"label": "2018 미중 무역분쟁", "start": "2018-01-01", "end": "2019-01-31"},
    "hist_2020_covid": {"label": "2020 코로나 급락", "start": "2020-01-20", "end": "2020-08-31"},
    "hist_2022_rates": {"label": "2022 금리 충격", "start": "2022-01-01", "end": "2022-10-31"},
}

#: 기존 시나리오 id → 스펙 §5 패밀리. 새 팩을 추가하면 여기에도 한 줄.
_FAMILY_OF: dict[str, str] = {
    # M8 가상 충격
    "rate_hike_200bp": "growth_inflation",
    "oil_spike_50": "growth_inflation",
    "recession": "growth_inflation",
    "krw_depreciation": "krw_foreign_flow",
    # 국내 시나리오팩
    "shortsell_regulation": "shortsell_borrow",
    "leverage_unwind": "retail_deleveraging",
    "krw_sharp_move": "krw_foreign_flow",
    "semi_selloff": "semiconductor_chain",
    "valueup_collapse": "valueup_unwind",
    "earnings_dispersion": "earnings_dispersion",
    "retail_flow_reversal": "retail_deleveraging",
    "vol_shock_liquidity_vacuum": "volatility_liquidity",
    "credit_conditions_tightening": "credit_tightening",
    "corr_convergence_hedge_failure": "correlation_hedge_failure",
    "stagflation_regime": "growth_inflation",
}


@dataclass(frozen=True)
class ScenarioPack:
    pack_id: str
    label: str
    description: str
    family: str
    #: ★타입이 강제한다★ 문자열이 아니라 enum 이므로 "historical" 같은 오타가 조용히 통과할 수
    #: 없다. 스펙 §5 의 "역사/가정 라벨링을 타입 수준에서" 요구가 여기에 해당한다.
    model_type: ModelType
    source: str
    engine: str                 # m8 | hist_replay | kr_pack | inline
    engine_key: str
    content_hash: str

    @property
    def severity_applies(self) -> bool:
        """역사 리플레이는 실제 시세를 재생하므로 강도 배율이 성립하지 않는다."""
        return self.model_type is not ModelType.HISTORICAL_REPLAY

    @property
    def identity(self) -> str:
        """재현 좌표 — 런에 이것을 적어 두면 계수가 바뀌어도 알아챌 수 있다."""
        return f"{self.pack_id}@{self.content_hash}"

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id, "id": self.pack_id,
            "label": self.label, "description": self.description,
            "family": self.family, "family_label": FAMILY_LABEL.get(self.family, self.family),
            "model_type": self.model_type.value,
            "model_type_label": MODEL_TYPE_LABEL[self.model_type],
            "source": self.source,
            "engine": self.engine, "engine_key": self.engine_key,
            "content_hash": self.content_hash, "identity": self.identity,
            "severity_applies": self.severity_applies,
        }


MODEL_TYPE_LABEL: dict[ModelType, str] = {
    ModelType.HISTORICAL_REPLAY: "역사 리플레이 (실제 시세)",
    ModelType.HYPOTHETICAL: "가정 충격 (실제로 일어난 적 없음)",
}


def content_hash(definition: object) -> str:
    """정의 → 12자 해시. 정렬된 JSON 이라 키 순서가 바뀌어도 값은 그대로다."""
    blob = json.dumps(definition, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _m8_definition(key: str) -> dict:
    """M8 팩의 '정의'는 카탈로그 항목 **과 충격 함수 그 자체**다.

    ★카탈로그만 해싱하면 거짓말이 된다★ `STRESS_SCENARIOS[key]` 에는 label·description 뿐이고
    실제 계수는 `_stock_shock()` 코드 안에 있다. 카탈로그만 해싱하면 충격 모델을 통째로 바꿔도
    해시가 그대로여서, 재현되지 않는 런이 재현 가능한 것처럼 보인다. 그래서 함수 소스를 함께
    넣는다 — 국내팩처럼 계수가 데이터인 경우와 달리 여기서는 코드가 정의다.
    """
    from src.engine.stress_test_analyzer import STRESS_SCENARIOS, _stock_shock
    entry = dict(STRESS_SCENARIOS[key])
    try:
        src = inspect.getsource(_stock_shock)
    except OSError:                    # 소스를 못 읽는 배포 형태 — 침묵하지 않는다
        logger.warning("_stock_shock 소스를 읽지 못해 M8 팩 해시가 계수 변경을 추적하지 못합니다")
        src = "<source-unavailable>"
    return {"catalog": entry, "shock_fn": src}


def _build() -> dict[str, ScenarioPack]:
    from src.engine.kr_scenario_pack import SCENARIOS as KR
    from src.engine.stress_test_analyzer import STRESS_SCENARIOS as M8

    packs: dict[str, ScenarioPack] = {}

    for key, win in HIST_WINDOWS.items():
        packs[key] = ScenarioPack(
            pack_id=key, label=win["label"],
            description=f"{win['start']} ~ {win['end']} 실제 시세 리플레이",
            family="historical_replay",
            model_type=ModelType.HISTORICAL_REPLAY,
            source="적재된 실제 일봉 시세 리플레이",
            engine="hist_replay", engine_key=key,
            content_hash=content_hash({"start": win["start"], "end": win["end"]}))

    for key, v in M8.items():
        packs[key] = ScenarioPack(
            pack_id=key, label=v["label"], description=v["description"],
            family=_FAMILY_OF.get(key, "growth_inflation"),
            model_type=ModelType.HYPOTHETICAL,
            source="종목 펀더멘털·베타 민감도 기반 추정 충격 (M8 analyzer)",
            engine="m8", engine_key=key,
            content_hash=content_hash(_m8_definition(key)))

    for key, v in KR.items():
        packs[key] = ScenarioPack(
            pack_id=key, label=v["label"], description=v["description"],
            family=_FAMILY_OF.get(key, "user_authored"),
            model_type=ModelType.HYPOTHETICAL,
            source=v.get("source") or "국내 시장 구조 가정",
            engine="kr_pack", engine_key=key,
            # 계수·가정·시장 기본충격이 곧 정의다. label/description 이 바뀌어도 충격이 같으면
            # 해시는 같다 — 정체성은 표현이 아니라 모델을 가리켜야 한다.
            content_hash=content_hash({"market": v["market"], "factors": v["factors"],
                                       "assumptions": v["assumptions"]}))
    return packs


PACKS: dict[str, ScenarioPack] = _build()


def get_pack(pack_id: str) -> ScenarioPack | None:
    return PACKS.get(pack_id)


def families() -> list[dict]:
    """12 패밀리 전체 — 비어 있는 것도 **사유와 함께** 남는다."""
    out = []
    for fid, label in FAMILIES:
        n = sum(1 for p in PACKS.values() if p.family == fid)
        row = {"id": fid, "label": label, "count": n, "covered": n > 0}
        if n == 0:
            row["reason"] = _EMPTY_FAMILY_REASON.get(
                fid, "이 패밀리에는 아직 팩이 없습니다.")
        out.append(row)
    return out


def inline_pack(spec: dict) -> ScenarioPack:
    """사용자가 요청에 실어 보낸 팩 정의 → `ScenarioPack`.

    ★`model_type` 은 클라이언트에서 읽지 않는다★ 무조건 `HYPOTHETICAL` 이다. 사용자가 만든
    충격이 "역사적 사실" 이라고 주장할 수 있으면 §5 의 요구가 무의미해진다. 저장하지 않으므로
    이 팩은 요청 한 건 동안만 존재한다(저장·버전은 Phase 10).
    """
    definition = {"market": spec.get("market"), "factors": spec.get("factors"),
                  "assumptions": spec.get("assumptions")}
    h = content_hash(definition)
    return ScenarioPack(
        pack_id=f"user_{h}", label=str(spec.get("label") or "사용자 정의 시나리오"),
        description=str(spec.get("description") or "요청에 포함된 사용자 정의 충격"),
        family="user_authored", model_type=ModelType.HYPOTHETICAL,
        source="사용자 정의 (저장되지 않음 — 이 요청 한 건에만 적용)",
        engine="inline", engine_key=f"user_{h}", content_hash=h)


def compose_with_exposure(shock_pct: float, legs: dict[str, float]) -> dict[str, dict]:
    """시나리오 손실 × 다리별 노출 (스펙 §5 × Phase 7b 3자 비교).

    3자 비교는 다리마다 **노출(0~1)** 을 주고, 시나리오는 **손실(%)** 을 준다. 둘을 곱해
    합성한다 — 노출되지 않은 나머지는 현금이므로 충격을 받지 않는다.

    ★선형 근사라는 것을 숨기지 않는다★ 노출을 줄인 포트폴리오는 상관 구조도 달라지는데,
    이 곱셈은 그것을 반영하지 않는다. `run_scenario` 가 자기 선형 근사를 `notes` 에 적는 것과
    같은 이유로, 이 합성도 호출자가 그대로 표시할 문장을 함께 돌려준다.
    """
    out: dict[str, dict] = {}
    for name, exposure in legs.items():
        e = max(0.0, min(1.0, float(exposure)))
        out[name] = {
            "exposure": round(e, 4),
            "shock_pct": round(float(shock_pct) * e, 2),
            "cash_pct": round((1.0 - e) * 100, 2),
        }
    return out


COMPOSITION_NOTE = (
    "각 다리의 손실 = 시나리오 충격 × 그 다리의 위험자산 노출입니다(나머지는 현금으로 "
    "충격을 받지 않습니다). ★선형 합성이라 노출 축소에 따른 상관 구조 변화는 반영되지 "
    "않습니다★ — 방향은 맞지만 크기는 근사입니다."
)
