# AY · `alpha_expr` 의 비대칭 — ★못 붙이는 이유를 검증되는 관측으로★

작성 2026-09-22 · 레지스트리 `src/domain/signal_supply.py` · 트립와이어
`tests/test_signal_supply.py` · 등급 `src/domain/signal_evidence.py` ·
선례 `src/engine/version_registry.MISSING_AXES` ·
앞 프로그램 [AX](2026-09-22-timing-origin-design.md) ·
기록 `docs/HISTORY.md` 의 AY 항목

## 1. AX 의 경고가 맞았다

AX 는 이 프로그램을 지정하면서 경고를 남겼다: *"`alpha_lab._load_fundamentals`
가 스토어를 우회해 `src.database` 를 직접 쿼리한다. 지금의 `origin` 어휘
(=스토어 모듈 이름)가 맞지 않는다. ★어휘를 늘리는 것이 정직하지 않다면 이
프로그램은 하지 않는 것이 맞다★."*

**감사했고 경고가 맞았다.** 그래서 ★등급을 붙이는 프로그램이 아니라, 못 붙이는
이유를 **스스로 무효화되는 관측**으로 만드는 프로그램★ 으로 모양을 바꿨다.

## 2. ★실측 — 같은 모듈 안에서 한쪽만 계층을 지킨다★

| | 로더 | `src/data/` 공급 모듈 |
|---|---|---|
| `_load_price_series` (10개) | `src.data.ohlcv_loader.load_ohlcv_unified` | ★있다★ |
| `_load_fundamentals` (7개) | `financials_history` 를 **직접 SELECT** | ★없다★ |

**이것이 이 프로그램의 발견이다.** 결함의 이름이 *"재무 적재 상태를 모른다"*
(AV 의 추측)가 아니라 ★"공급 모듈이 없다"★ 라는 **구조적 사실**로 바뀐다.

## 3. ★적히지 않았던 규칙을 적는다★

AW 가 `filter_ast.ORIGINS` 를, AX 가 `TIMING_ORIGINS` 를 만들며 여섯 값을
썼는데 **규칙이 한 번도 적히지 않았다**:

    ★`origin` 은 실재하는 `src/data/` 공급 모듈의 이름이다.★

여섯 값 모두 그러한데(실측) 아무도 걸지 않았다. `SUPPLY_PACKAGE = "src.data"`
가 규칙을 한 곳에 두고, 테스트가 **선언된 모든 값**을 실제로 임포트해 본다 —
★오타도 테이블 이름도 경로 문자열도 거기서 죽는다★. **AW·AX 를 소급으로
경화한다.**

그래서 `financials_history` 는 어휘에 넣지 않는다 — 모듈과 테이블은 다른
종류이고, 한 칸에 섞으면 다음 사람이 구별할 수 없다(AV 가 `E2` 두 척도에서,
AW 가 `FactorMeta.source` 에서 겪은 것과 같은 모양).

## 4. ★"모른다" 대신 "이것이 참인 동안은 못 붙인다"★

지금 7개에 붙은 사유는 `_REASON_UNMAPPED`(*"이 종류·카테고리의 뒷받침을
**모릅니다**"*)였다. **저장소는 다섯 가지를 아는데 모른다고 말하고 있었다.**

`version_registry.MissingAxis(key, label, reason, blocks)` 선례를 따르고
★`promotes_when`★ 한 칸을 더한다:

```python
@dataclass(frozen=True)
class UnsuppliedSignal:
    key: str            # "alpha_expr.fund"
    label: str
    reason: str         # ★실측한 사실만★ — 어디서 오는가
    blocks: str         # 이것 때문에 답할 수 없는 질문
    promotes_when: str  # ★무엇이 참이 되면 등급을 붙일 수 있나★
```

★그리고 그 조건이 아직 참인지를 테스트가 확인한다★:

- `_load_price_series` 가 `src.data.*` 를 **지난다**
- `_load_fundamentals` 가 `src.data.*` 를 **안 지나고** `src.database` 를 쓴다
- ★짝★ — 둘이 **다르다**(둘 다 지나거나 둘 다 안 지나면 이 프로그램의 전제가
  무너진 것이므로 죽는다)

**누군가 결함을 고치면 테스트가 red 가 되고 그것이 곧 승급 신호다.**
실패 메시지가 *"이제 `UNSUPPLIED` 에서 이 항목을 빼고 등급을 붙여라"* 라고
말한다. `MissingAxis` 의 docstring 이 *"사유 없이 '없다' 고만 적으면 갚을 수
없는 부채"* 라고 적어 둔 그대로다.

사유는 레지스트리에서 **읽는다** — ★등급 규칙에 문장을 베껴 적지 않는다★.
복사하면 레지스트리를 고쳐도 응답이 안 따라온다.

## 5. ★두 기계를 하나로★

`alpha_expr`(price) 10개는 `origin` 이 아니라
`KNOWN_BACKING[(KIND_ALPHA_EXPR, "price")]` 라는 **카테고리 표**로 등급을
받고 있었다(AW·AX 이전 방식). 같은 질문에 두 기계가 답하면 한쪽만 고쳐도 안
깨진다 — `source_registry` 가 같은 이유를 적어 두었다.

카테고리 표에서 그 줄을 빼고 `ohlcv_loader` 를 `BACKED_ORIGINS` 에 넣는다.
★등급 **값**은 바뀌지 않는다★(둘 다 mock 게이트로 `E0`/`E2`) — 테스트가
그것을 못 박는다. **기계는 바뀌고 답은 그대로여야 한다. 아니면 통합이 아니라
변경이다.**

## 6. ★개정 축 — 제 칸에 넣는다★ (사용자 결정)

`financials_history` 가 정정이 원본을 덮는 표라는 것은 사실이지만 **출처 축이
아니다**. `SignalDefinition.revision_policy` 가 이미 있고 어휘도 이미 있다
(`revised`·`not_revised`·`series_dependent`). `fund` 7개에 **`revised`** 를
싣는다 — 저장소가 `pit_store`·`kis_backtest_engine`·`valuation_distribution`
세 곳에 그렇게 적어 두었다.

★`price` 는 비운다★ — 수정주가가 소급 변경되는지를 **이 프로그램은 재지
않았다**. 안 잰 것을 `not_revised` 로 주장하면 그것이 지어내기다. 그리고
CLAUDE.md §6 이 `adj_close` 소비자를 승인 사항으로 못 박았다
(`_load_price_series` 는 `close` 를 쓴다 — **관측만** 한다).

## 7. 실측 결과

| | AX 이후 | AY 이후 |
|---|---|---|
| 등급이 붙은 신호 | 185 (86%) | **185 (86%)** |
| 미상 | 30 | **30** |

★등급 개수는 이 프로그램의 산출물이 아니다.★ 산출물은 넷이다:

1. `origin` 어휘 규칙이 **구조로** 걸렸다(AW·AX 소급 경화)
2. 사유가 산문에서 **검증되는 관측**이 됐다
3. **승급 조건이 코드**가 됐다 — 고쳐지면 red 로 알린다
4. 등급 경로가 **하나**로 합쳐졌다(값은 보존)

## 8. 어떤 질문에 답하는가

CLAUDE.md 2절의 네 질문 중 **어느 것도 아니다**. 증거 등급 `E1`(픽스처),
주장의 종류 `structural`. 어떤 투자 판단도 바꾸지 않는다.

## 9. ★이 설계가 하지 않는 것★

- **`alpha_lab.py` 를 한 줄도 고치지 않는다.** `fundamentals_store` 로 돌리면
  ★값이 바뀐다★ — 두 경로가 같은 표를 읽지 않는다(실측: `fundamentals_store`
  에 `financials_history` grep 0건). 승인 사항이다.
- **`financials_history` 를 `origin` 어휘에 넣지 않는다.**
- **`adj_close` 를 건드리지 않는다.** 관측만 한다.
- **`price` 의 `revision_policy` 를 주장하지 않는다.** 재지 않았다.
- **정정 사실을 출처 사유에 섞지 않는다.** 개정 축은 제 칸이 있다.
- **미상을 줄이는 것을 목표로 삼지 않는다.** 이번엔 **0개 줄어든다**.
- **새 척도를 만들지 않는다.** `PROV_*` · origin 어휘 · `revision_policy`
  어휘 전부 이미 있는 것이다.
- **화면을 만들지 않는다. 채점표를 올리지 않는다.**
