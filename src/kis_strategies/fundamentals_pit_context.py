"""재무 공시일의 ★출처★ — 실측 접수일인가, 정적 시차 추정인가 (V4)

무엇을 판정하는가
──────────────────────────────────────────────────────────────────────────────
재무 PIT 은 지금까지 **고정 시차 추정**이었다 — 연간 90일 · 분기 45일
(`pit_store.py:32-35`). 저장소가 그 한계를 스스로 적어 뒀다
(`company_snapshot_builder.py:158`: *"실제 공표일이 아니라 정적 시차 규칙으로
추정한 가용일"*). V1~V3 이 실측 접수일(`rcept_dt`)을 받아 쌓고 읽을 수 있게 했다.

이 컨텍스트는 실행 1회 동안 **기간마다** 그 둘 중 무엇을 썼는지 기록한다.

    measured   그 기간의 접수일을 실제로 관측했다
    estimated  빈티지가 없어 정적 시차로 추정했다  ← ★라벨 붙은 열화★
    unknown    빈티지 테이블을 읽지 못했다        ← ★추정과 같은 칸에 세지 않는다★

★`unknown` 을 `estimated` 에 섞지 않는 이유★ — "빈티지가 없다" 와 "있는지 못
봤다" 는 다른 진술이다. 섞으면 DB 가 잠깐 죽었을 때 추정 비율이 정상으로 보이고,
아무도 눈치채지 못한다. `pit_macro.load_vintage_obs` 가 매크로에서 같은 이유로
같은 구별을 한다.

★전환이 아니라 병합이다★
──────────────────────────────────────────────────────────────────────────────
`financials_vintages` 는 V2 이후로만 쌓이고, `dart_history.existing_keys` 가
3-튜플이라 이미 적재된 기간은 재조회되지 않는다. 그래서 **지금 사용자 DB 의 빈티지
테이블은 비어 있다.** 빈티지로 통째로 갈아타면 PIT 재무 조건이 전부 NaN 이 되어
백테스트가 조용히 퇴화한다. 기간마다 있으면 실측, 없으면 라벨 붙은 추정이다.

★왜 이 클래스가 절대 예외를 내지 않는가★
──────────────────────────────────────────────────────────────────────────────
호출부 `condition_strategy._pit_fund_series` 가 `_build_pit_base` 의 예외를
**통째로 삼켜** 패널을 `None` 으로 만든다. 그러면 PIT 재무 조건이 화면에 아무
표시 없이 건너뛰어진다. 그러니 실패는 예외가 아니라 **값**(`unknown` + 사유)이
되어야 한다. 생성자도 I/O 를 하지 않는다 — 실패할 자리를 두지 않는다.

★`MacroPitContext` 와 다른 점★
──────────────────────────────────────────────────────────────────────────────
매크로는 판정 단위가 **토큰**이고 실행 달력이 필요했다(상장일이 다른 종목 사이에서
한 토큰이 두 의미를 갖지 않게). 재무는 판정 단위가 **(종목, 기간)** 이고 데이터
유무로만 갈리므로 달력이 필요 없다. 없는 인자를 흉내 내지 않는다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MEASURED = "measured"
ESTIMATED = "estimated"
UNKNOWN = "unknown"

#: 접수 **당일** 봉에는 쓰지 않는다.
#:
#: DART 는 18시까지 접수를 받고 한국 장은 15:30 에 닫는다. 우리는 접수 **시각**을
#: 모른다(★미상★) — 그러니 장마감 뒤 접수분이 같은 날 봉에 섞일 수 있다.
#: V3 의 `dart_history.vintages_as_of` 가 *"그 안전 여유는 호출자가 **보이는
#: 자리에서** 준다"* 라고 적어 뒀고, 여기가 그 호출자다.
#:
#: ★상수에 이름이 있고 결과 메타에도 실린다★ — 몰래 하루를 빼면 반대로
#: "왜 하루 늦나" 를 아무도 찾지 못한다.
FILING_SAME_DAY_GUARD_DAYS = 1

REASON_MEASURED = ""          # ★측정된 것에는 사유를 달지 않는다★ (매크로의 pit 와 같다)
REASON_TICKER_HAS_NO_VINTAGES = (
    "이 종목에는 적재된 재무 빈티지가 없어 공시일을 정적 시차(연간 90일 · 분기 45일)로 "
    "추정했습니다. 실제 접수일과 다를 수 있고 그만큼 조기/지연 반영됩니다."
)
REASON_NO_VINTAGE_FOR_PERIOD = (
    "이 기간의 빈티지만 없어 공시일을 정적 시차로 추정했습니다 — 같은 종목의 다른 "
    "기간은 실측 접수일을 썼습니다."
)
REASON_TICKER_HAS_NO_FINANCIALS = (
    "적재된 재무가 없어 PIT 재무 조건이 평가되지 않았습니다 — 조건이 통째로 "
    "건너뛰어졌다는 뜻이지 조건이 거짓이었다는 뜻이 아닙니다."
)

#: 사유마다 붙이는 종목 예시의 상한. ★페이로드를 유니버스 크기에 비례시키지 않는다★
_SAMPLE_CAP = 3


class FundamentalsPitContext:
    """백테스트 1회 동안의 재무 공시일 출처를 든다.

    ★`None` 이면 오늘 동작 그대로★ — 스크리너·실시간 경로는 이걸 심지 않고,
    거기서는 추정 시차가 맞다(as-of 질문이 아니다).
    """

    def __init__(self, *, engine=None) -> None:
        self._engine = engine
        #: 종목 → `(빈티지 맵, 사유)`. ★종목당 1회만 읽는다★ 실패도 캐시한다 —
        #: 한 실행 안에서 DB 가 살았다 죽었다 하면 같은 종목이 봉마다 다른 판정을
        #: 받아 "기간 단위 판정" 이 깨진다(P1 이 매크로에서 같은 규율을 썼다).
        self._vintages: dict[str, tuple[dict, str | None]] = {}
        #: 종목 → `{measured, estimated, unknown}`. ★종목 키라 두 번 세지 않는다★
        #: `_build_pit_base` 는 `(종목, len(df))` 로 캐시되고 벡터화 경로와 per-bar
        #: 폴백 경로가 서로 다른 프레임을 넘기므로, 리스트로 누적하면 같은 종목이
        #: 여러 번 세어진다.
        self._periods: dict[str, dict[str, int]] = {}
        self._no_financials: set[str] = set()

    # ── 읽기 ──────────────────────────────────────────────────────────────
    def vintages_by_period(self, ticker: str) -> tuple[dict[tuple, list[dict]], str | None]:
        """`({(연도, 보고서): [빈티지 행, …]}, 사유)` — 접수 순 정렬.

        ★기간당 하나로 줄이지 않는다★ 최초 공시만 쓰면 정정을 영원히 못 보고,
        최종 정정만 쓰면 정정 전 봉이 **미래의 값**을 본다. 각 빈티지가 각자의
        접수일부터 값을 주는 것이 실제로 일어난 일이다.

        사유가 있으면 빈 맵 + 사유 — ★"빈티지가 없다" 가 아니라 "못 봤다"★.
        """
        cached = self._vintages.get(ticker)
        if cached is not None:
            return cached

        try:
            from src.data.dart_history import load_vintages
            rows, reason = load_vintages(ticker, engine=self._engine)
        except Exception as e:  # noqa: BLE001 — ★실패는 예외가 아니라 값이다★
            rows, reason = None, f"재무 빈티지를 읽지 못했습니다: {type(e).__name__}: {e}"

        out: dict[tuple, list[dict]] = {}
        for r in rows or []:
            try:
                key = (int(r["year"]), str(r["reprt"]))
            except Exception:  # noqa: BLE001 — 축을 못 읽는 행은 빈티지가 아니다
                continue
            out.setdefault(key, []).append(r)
        for v in out.values():
            v.sort(key=lambda r: (str(r.get("rcept_dt") or ""), str(r.get("rcept_no") or "")))

        got = (out, reason or None)
        self._vintages[ticker] = got
        return got

    # ── 기록 ──────────────────────────────────────────────────────────────
    def record(self, ticker: str, *, measured: int, estimated: int, unknown: int) -> None:
        """★종목당 1회만 반영★ — 같은 종목을 다시 봐도 건수가 늘지 않는다."""
        self._periods[str(ticker)] = {MEASURED: int(measured),
                                      ESTIMATED: int(estimated),
                                      UNKNOWN: int(unknown)}
        self._no_financials.discard(str(ticker))

    def note_no_financials(self, ticker: str) -> None:
        """적재가 없어 조건이 **건너뛰어진** 사실을 센다.

        지금까지 이 자리는 화면에 아무 표시가 없었다 — 조건이 거짓이었던 것과
        평가되지 않은 것이 같아 보였다.
        """
        tk = str(ticker)
        if tk not in self._periods:
            self._no_financials.add(tk)

    # ── 집계 ──────────────────────────────────────────────────────────────
    def counts(self) -> dict[str, int]:
        """단위는 ★(종목, 기간)★ — 신호도 봉도 아니다."""
        out = {MEASURED: 0, ESTIMATED: 0, UNKNOWN: 0}
        for c in self._periods.values():
            for k in out:
                out[k] += c.get(k, 0)
        return out

    def ticker_counts(self) -> dict[str, int]:
        """단위는 ★종목★ — 위와 섞어 읽지 않도록 따로 낸다."""
        out = {"measured_any": 0, "all_estimated": 0, "unknown": 0, "no_financials": 0}
        for c in self._periods.values():
            if c.get(MEASURED):
                out["measured_any"] += 1
            elif c.get(UNKNOWN):
                out["unknown"] += 1
            elif c.get(ESTIMATED):
                out["all_estimated"] += 1
        out["no_financials"] = len(self._no_financials)
        return out

    def reasons(self) -> dict[str, dict]:
        """사유 ★히스토그램★ — 종목별 맵이 아니다.

        매크로는 판정 단위가 토큰이라(~20개) 토큰별 맵이 가능했다. 재무는
        종목 수백 × 기간 ~40 이라 종목별 맵이면 페이로드가 유니버스에 비례해
        터진다(실행마다 저장되고, 브라우저로 가고, 텔레메트리에 복사된다).
        여기는 **사유 종류 ≤5 × (건수 2개 + 예시 종목 ≤3)** 으로 상한이 있다.
        ★건수는 그대로 다 싣는다★ — 줄인 것은 사유의 **모양**이지 양이 아니다.
        """
        acc: dict[str, dict] = {}

        def _bump(code: str, ticker: str, periods: int, reason: str) -> None:
            e = acc.setdefault(code, {"periods": 0, "tickers": 0,
                                      "_tk": set(), "reason": reason})
            e["periods"] += periods
            e["_tk"].add(ticker)

        for tk, c in sorted(self._periods.items()):
            vmap, v_reason = self._vintages.get(tk, ({}, None))
            if c.get(MEASURED):
                _bump("measured_filing_date", tk, c[MEASURED], REASON_MEASURED)
            if c.get(UNKNOWN):
                _bump("vintage_table_unreadable", tk, c[UNKNOWN],
                      v_reason or "빈티지 테이블을 읽지 못했습니다(사유 미상).")
            if c.get(ESTIMATED):
                if vmap:
                    _bump("no_vintage_for_period", tk, c[ESTIMATED], REASON_NO_VINTAGE_FOR_PERIOD)
                else:
                    _bump("ticker_has_no_vintages", tk, c[ESTIMATED], REASON_TICKER_HAS_NO_VINTAGES)
        for tk in sorted(self._no_financials):
            _bump("ticker_has_no_financials", tk, 0, REASON_TICKER_HAS_NO_FINANCIALS)

        for e in acc.values():
            tks = sorted(e.pop("_tk"))
            e["tickers"] = len(tks)
            e["sample_tickers"] = tks[:_SAMPLE_CAP]
        return acc
