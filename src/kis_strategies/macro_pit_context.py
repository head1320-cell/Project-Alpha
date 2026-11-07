"""백테스트 1회 동안의 매크로 시점(PIT) 판정을 든다.

## 왜 있는가

조건식의 매크로 토큰은 지금까지 **조회 시점의 라이브 값**(= 여러 번 개정된 최신본)
으로 평가됐다. `pit_macro` 에 시점 고정 경로가 있었지만 **운영 코드에서 그것을
부르는 호출부가 하나도 없었다.** 이 객체가 그 배선이다.

## 왜 명시적으로 넘기는가 — `ContextVar` 를 쓰지 않는 이유

저장소에 이미 `kis_data_fetcher._BAR_CONTEXT` 라는 암묵 컨텍스트 선례가 있고, 그
파일이 스스로 한계를 적어 두었다: **컨텍스트는 미는 스레드에서만 보인다.** 신호
생성을 병렬화하면 매크로 컨텍스트가 조용히 사라지고 라이브로 폴백한다 — 그리고
그 폴백은 ★조용한 룩어헤드★ 라서 결과만 보고는 알 수 없다.

그래서 인자로 넘기고, 빠뜨린 호출부는 `tests/test_macro_pit_context.py` 의 정적
트립와이어가 잡는다. (업계 표준인 gs-quant 의 `PricingContext` 는 암묵 스택을
쓰지만, 거기에는 이 저장소의 워커 스레드 문제가 없다.)

## 세 상태 — ★섞지 않는다★

    pit      실행 달력 전 구간을 빈티지로 평가했다
    live     빈티지가 없어 라이브로 평가했다 — ★룩어헤드★, 라벨이 붙는다
    blocked  값을 내지 못했다 — 조건이 평가되지 않는다 + 사유

★조회 실패는 `live` 가 아니라 `blocked` 다★ — 미상 ≠ 없음. DB 가 잠깐 죽었다고
전 실행이 조용히 룩어헤드 모드가 되면 안 되고, `live` 라벨은 "확인했더니 빈티지가
없었다" 로 읽힌다. 하지 않은 진술이다.

## 판정의 기준은 ★실행 달력★ 이다

`_base_series` 는 **종목별 프레임**을 받는다. 그 프레임의 첫 봉으로 판정하면
2010년 상장 종목은 `live`, 2020년 상장 종목은 `pit` 이 되어 **한 실행 안에서 같은
토큰이 두 가지 의미**를 갖는다. 그래서 판정은 토큰당 한 번, 실행 달력 기준이다.

누적기에서 `known` 은 줄지 않으므로 값이 없는 봉은 **반드시 앞쪽 접두**다. 그래서
"실행 달력 첫 봉에 값이 있는가" 하나로 전 구간 판정이 된다 — 커버리지 임계값 같은
자의적 기준이 필요 없다.
"""
from __future__ import annotations

import pandas as pd

PIT = "pit"
LIVE = "live"
BLOCKED = "blocked"

REASON_NO_VINTAGE_DEPTH = (
    "빈티지가 실행 구간의 시작을 덮지 못합니다 — 라이브(현재 개정본)로 평가했으므로 "
    "이 토큰이 쓰인 조건에는 룩어헤드가 있습니다."
)
REASON_NO_VINTAGE_AT_ALL = (
    "이 계열에는 적재된 빈티지가 없습니다 — 라이브(현재 개정본)로 평가했으므로 "
    "이 토큰이 쓰인 조건에는 룩어헤드가 있습니다."
)


def is_macro_token(name: str) -> bool:
    """매크로 리졸버가 아는 토큰인가.

    ★모르는 토큰을 기록하지 않는다★ `_base_series` 는 리졸버 체인이라 가격·수급
    토큰도 매크로 리졸버를 스친다. 그것들을 `blocked` 로 세면 라벨이 소음으로 가득
    차 정작 룩어헤드가 묻힌다.
    """
    from src.kis_strategies.factor_tokens import (
        ECOS_TOKENS,
        FRED_INDICATOR_TOKENS,
        FRED_TOKENS,
    )
    return name in ECOS_TOKENS or name in FRED_TOKENS or name in FRED_INDICATOR_TOKENS


class MacroPitContext:
    """실행 1회당 하나. 스토어 조회·판정·라벨을 모두 이 안에 가둔다."""

    def __init__(self, calendar):
        cal = pd.DatetimeIndex(calendar if calendar is not None else [])
        if len(cal) == 0:
            # ★기준 없는 판정은 종목별로 갈린다★ — 달력이 없으면 만들지 않는다.
            raise ValueError("MacroPitContext 에는 실행 달력이 필요합니다")
        self.calendar = cal
        #: 계열 → `(관측, 실패사유)`. ★계열당 1회만 읽는다★
        self.obs: dict[str, tuple] = {}
        #: 토큰 → `{"path": ..., "reason": ...}`
        self.path: dict[str, dict] = {}
        #: `(토큰, 프레임 모양)` → 시리즈. 종목마다 다시 누적하지 않는다.
        self._series: dict[tuple, pd.Series | None] = {}
        #: 토큰 → 개정이 **레그 판정**을 뒤집은 정도. PIT 인 토큰만 들어간다.
        self.revision: dict[str, dict] = {}

    #: ★주장의 크기를 이름이 정한다★ 이 수치는 최종 신호 차이가 아니다.
    REVISION_NOTE = (
        "매크로 **레그**(그 토큰 하나의 조건)의 참/거짓이 PIT 와 라이브에서 갈린 "
        "봉의 비율입니다. 논리 결합(and/or/every)이 이를 흡수하거나 증폭하므로 "
        "**최종 신호**가 갈린 비율은 아닙니다."
    )

    def measure_revision(self, name: str, df: pd.DataFrame, conds: list) -> None:
        """개정이 이 토큰의 레그 판정을 얼마나 뒤집었는지 잰다.

        Croushore & Stark (2001) 의 요지가 이것이다 — 개정이 **있었다**보다
        개정이 **결론을 바꾸었는가**가 답이다. 라벨(P4)에서 한 걸음 더 간다.

        ★PIT 인 토큰만 잰다★ 라이브로 떨어진 토큰에는 비교할 PIT 값이 없다.
        ★못 재면 `None` + 사유★ 라이브를 못 받거나 겹치는 유효 봉이 없으면
        "안 갈렸다(0%)" 가 아니라 **재지 못했다**.
        ★새 비교 의미를 만들지 않는다★ 조건식의 연산자 의미(`_vector_compare`)를
        그대로 쓴다 — 따로 구현하면 언젠가 갈라진다.
        """
        from src.kis_strategies.condition_strategy import (
            _apply_function,
            _apply_inner,
            _vector_compare,
        )
        from src.kis_strategies.factor_tokens import resolve_macro_token

        if name in self.revision or self.verdict(name) != PIT:
            return
        pit_s = self.resolve(df, name)
        if pit_s is None:
            return

        live_raw = resolve_macro_token(df, name)
        if live_raw is None:
            self.revision[name] = {
                "bars": 0, "flip": 0, "flip_pct": None,
                "reason": self._live_reason(name),
                "note": self.REVISION_NOTE,
            }
            return

        flip = both = 0
        for cond in conds:
            pair = [self._leg(s, cond, _apply_inner, _apply_function, _vector_compare)
                    for s in (pit_s, live_raw)]
            if any(p is None for p in pair):
                continue
            (v_pit, ok_pit), (v_live, ok_live) = pair
            usable = v_pit & v_live
            both += int(usable.sum())
            flip += int((usable & (ok_pit != ok_live)).sum())

        self.revision[name] = {
            "bars": both,
            "flip": flip,
            # ★분모 0 에 0.0 을 적지 않는다★ 겹치는 봉이 없으면 미상이다.
            "flip_pct": round(flip / both * 100, 1) if both else None,
            "reason": "" if both else "PIT 와 라이브가 모두 유효한 봉이 없습니다.",
            "note": self.REVISION_NOTE,
        }

    @staticmethod
    def _leg(base, cond, apply_inner, apply_function, vector_compare):
        """조건 하나의 (평가가능, 충족) 불리언 — 조건식과 **같은 함수 체인**."""
        s = apply_inner(base, cond)
        if s is None or len(s) == 0:
            return None
        s = apply_function(s, cond.get("function_id", "base"), cond.get("params") or {})
        if s is None or len(s) == 0:
            return None
        return vector_compare(s, cond.get("op", "gte"), cond.get("rhs"),
                              cond.get("rhs2"))

    # ── 판정 ────────────────────────────────────────────────────────────────
    def verdict(self, name: str) -> str:
        """토큰의 경로를 정한다 — ★토큰당 1회, 실행 달력 기준★."""
        rec = self.path.get(name)
        if rec is not None:
            return rec["path"]
        path, reason = self._decide(name)
        self.path[name] = {"path": path, "reason": reason}
        return path

    def _decide(self, name: str) -> tuple[str, str]:
        from src.kis_strategies.factor_tokens import (
            ECOS_TOKENS,
            REASON_PROVIDER_HAS_NO_VINTAGE,
            resolve_macro_token,
        )
        if name in ECOS_TOKENS:
            # 제공자에 빈티지 엔드포인트가 없다 — ★영구★. 쓰되 룩어헤드로 라벨한다.
            return LIVE, REASON_PROVIDER_HAS_NO_VINTAGE

        probe = pd.DataFrame(index=self.calendar)
        try:
            s = resolve_macro_token(probe, name, as_of="per_bar", obs_cache=self.obs)
        except Exception as e:  # noqa: BLE001
            return BLOCKED, f"빈티지 판정에 실패했습니다: {type(e).__name__}: {e}"

        # ★"못 읽었다" 를 "없다" 로 뭉개지 않는다★ — 사유가 남아 있으면 미상이다.
        for _sid, (_obs, why) in self.obs.items():
            if why:
                return BLOCKED, why

        if s is None:
            return LIVE, REASON_NO_VINTAGE_AT_ALL
        if len(s) == 0 or pd.isna(s.iloc[0]):
            # 값이 없는 봉은 앞쪽 접두이므로, 첫 봉이 비면 구간을 못 덮는 것이다.
            return LIVE, REASON_NO_VINTAGE_DEPTH
        self._series[(name, self._key(self.calendar))] = s
        return PIT, ""

    # ── 조회 ────────────────────────────────────────────────────────────────
    def resolve(self, df: pd.DataFrame, name: str):
        """이 프레임에 맞춘 매크로 시리즈. 판정에 따라 PIT 또는 라이브."""
        from src.kis_strategies.factor_tokens import resolve_macro_token

        path = self.verdict(name)
        if path == BLOCKED:
            return None

        key = (name, self._key(df.index))
        if key in self._series:
            cached = self._series[key]
            return None if cached is None else self._reindex(cached, df)

        if path == PIT:
            out = resolve_macro_token(df, name, as_of="per_bar", obs_cache=self.obs)
        else:
            # ★라이브도 같은 리졸버를 탄다★ 캐시·사유 기록이 한 곳에 있어야 한다.
            out = resolve_macro_token(df, name)
            if out is None and self.path[name]["path"] == LIVE:
                self.path[name] = {
                    "path": BLOCKED,
                    "reason": self._live_reason(name),
                }
                return None
        self._series[key] = out
        return out

    @staticmethod
    def _live_reason(name: str) -> str:
        from src.kis_strategies.factor_tokens import macro_availability
        bad = macro_availability().get("unavailable", {}).get(name) or {}
        return bad.get("reason") or "라이브 조회에 실패했습니다(사유 미상)."

    @staticmethod
    def _key(index) -> tuple:
        """프레임 인덱스의 **모양**. KRX 종목은 거래일 달력을 공유하므로 실행당
        한두 개면 충분하다 — 종목 수만큼 누적을 다시 돌리지 않기 위한 키다."""
        idx = pd.DatetimeIndex(index) if not isinstance(index, pd.DatetimeIndex) \
            else index
        if len(idx) == 0:
            return ("", "", 0)
        return (idx[0].isoformat(), idx[-1].isoformat(), len(idx))

    @staticmethod
    def _reindex(s: pd.Series, df: pd.DataFrame) -> pd.Series:
        out = s.copy()
        out.index = df.index
        return out

    # ── 보고 ────────────────────────────────────────────────────────────────
    def counts(self) -> dict:
        out = {PIT: 0, LIVE: 0, BLOCKED: 0}
        for rec in self.path.values():
            out[rec["path"]] = out.get(rec["path"], 0) + 1
        return out
