# 보존 정책 — ★무엇을 지워도 되고 무엇을 지우면 안 되는가★

> 실측 2026-09-12. ★단일 출처는 이 문서가 아니라 코드다★ —
> [`src/data/retention.py`](../../src/data/retention.py) 가 분류와 사유를 들고,
> [`tests/test_retention_policy.py`](../../tests/test_retention_policy.py) 가
> 그것을 **집행**한다. 이 문서는 *왜 그렇게 나눴는지* 를 적는다.
>
> 선행: [`DATA_PLATFORM_SPEC.md`](DATA_PLATFORM_SPEC.md) §5 ·
> [`INGESTION_ARCHITECTURE_V2.md`](INGESTION_ARCHITECTURE_V2.md)(빈티지).

## 0. 이 문서가 답하는 질문

`DATA_PLATFORM_SPEC.md` §5 가 스스로 적어 둔 공백이 있었다:

> **보존/삭제 정책이 없다.** … 지금 규모에서는 문제가 아니지만
> **그것이 결정된 적은 없다** — 기본값일 뿐이다.

"없다" 와 "안 지우기로 정했다" 는 다르다. 앞의 것은 **다음 사람이 용량 압박을
받으면 아무거나 지운다**는 뜻이고, 뒤의 것은 무엇을 지우면 안 되는지가 이름으로
남아 있다는 뜻이다. 이 문서와 그 테스트가 앞을 뒤로 바꾼다.

★그리고 이것은 삭제 기능이 아니다.★ 아래 어디에도 나이·크기 기준으로 행을
지우는 코드는 없고, 이번에 만들지도 않았다(§7).

---

## 1. ★분류의 축은 용량이 아니라 재수집 가능성★

직관은 "큰 것부터 지운다" 이고, 이 도메인에서 그 직관은 **정확히 틀렸다**.
가장 큰 표(`daily_prices`)가 되살릴 수 없는 쪽에 있고, 지워도 되는 것
(`factor_snapshot` 캐시)은 작다. 그래서 기준을 하나로 고정한다:

    ★지우면 다시 만들 수 있는가. 만들 수 있다면 '그때의 값' 으로 만들 수 있는가.★

두 번째 물음이 이 플랫폼 고유의 것이다. 제공자는 **오늘 값**을 준다. 오늘
다시 받은 값으로 과거를 채우면 그것은 복구가 아니라 **룩어헤드 주입**이다.

| 부류 | 판정 | 지우면 |
|---|---|---|
| ① 원천 관측 | ★영구★ | 능력을 잃는다(되돌릴 수 없다) |
| ② 감사 | ★영구★ | 바깥 요구에 답할 근거를 잃는다 — **미상이므로 영구** |
| ③ 결정 기록 | 기본 영구 | "그때 무엇을 보고 정했나" 가 사라진다 |
| ④ 재생성 가능 | 지워도 된다 | 워밍/동기화가 다시 돌 뿐 |
| ⑤ 계정 소유 | ★판단 주체가 다르다★ | 소유자가 정한다(탈퇴·삭제 요구) |

---

## 2. ①·② ★삭제 금지★ — 테스트가 지키는 목록

<!-- PROTECTED-LIST:START -->
**① 원천 관측** — `financials_vintages` · `macro_observations` ·
`financials_history` · `daily_prices` · `investor_flows`

**② 실거래 감사** — `live_orders` · `live_fills` · `live_daily_pnl` ·
`live_kill_events` · `live_audit_trail` · `reconciliation_history`
<!-- PROTECTED-LIST:END -->

사유는 **코드에 한 줄씩** 있다(`KEEP_FOREVER` · `AUDIT`). 요지만 옮기면:

- **빈티지 둘** — DART·ECOS 는 ★과거 접수본을 다시 주지 않는다★. 지우는 순간
  `history_as_of` · `statement_as_of` · `pit_macro` 가 답하던 as-of 조회가
  통째로 죽는다. 이 저장소가 P·V·T·U 에서 만든 능력이 바로 그것이다.
- **가격** — 재수집은 되지만 **상장폐지 종목은 못 받는다**. 지우면 시점
  유니버스를 다시 세울 수 없고 생존편향이 되돌아온다.
- **수급** — KIS 종목별 투자자 TR 은 **최근 ~30영업일만** 준다. 그 이전은
  비공식 KRX 백필뿐이고 이 환경에서는 그 도메인이 막혀 있다(실측).
- **실거래 기록 여섯** — ★규제·감사 요건은 이 저장소가 판단할 문제가 아니다.★
  확인하기 전에는 영구로 둔다. 이것은 결론이 아니라 **명시된 미상**이다.

### 무엇이 이것을 지키나

`tests/test_retention_policy.py` 가 `src/` · `scripts/` 를 전수로 읽어
위 표에 대한 `DELETE` · `TRUNCATE` 가 **하나라도 생기면 실패**한다.

★리터럴만 보면 거의 다 놓친다★ — 계획은 `DELETE FROM <표>` 리터럴을 찾는
것이었는데, 실제로 세어 보니 저장소의 삭제문 18곳 중 **16곳이
`DELETE FROM {_TABLE}`** 이다(모듈 상수를 f-string 으로 끼운다). 그래서 가드는
`ast` 로 모듈 최상위 문자열 상수를 읽어 **이름을 풀어서** 판정한다.

함께 거는 것:

| 무엇 | 왜 |
|---|---|
| `_bulk_refresh_table` 호출 인자 | 그 헬퍼는 **테이블명을 인자로 받는다** — 보호 표를 넘기면 그대로 지운다 |
| 이름을 못 푸는 삭제의 소재 | 지금은 그 헬퍼 하나뿐이다. 다른 곳에 생기면 가드가 닿지 않으므로 먼저 잡는다 |
| 삭제 대상이 **분류돼 있는가** | 분류 없는 삭제는 "지워도 되는지 판단한 적이 없다" 는 뜻이다 |
| **선언된 표가 전부 분류돼 있는가** | 새 표가 생기면 보존 판단을 강제한다 |

마지막 항목이 실제로 구멍을 찾아냈다 — `CREATE TABLE` 만 세면 ORM 선언
(`__tablename__`)이 안 보여서 여섯(`users` · `portfolios` · `trade_log` ·
`risk_snapshots` · `model_monitor_runs` · `stocks`)이 분류에서 통째로 빠져
있었다. ★한쪽 표기만 세면 반드시 빠진다★ — 이 저장소가 인덱스에서 이미
겪은 실수다(`DATA_PLATFORM_SPEC.md` §2).

---

## 3. ③ 결정 기록 — 기본 영구, 삭제는 막지 않는다

`backtest_runs` · `multibacktest_runs` · `multibacktest_daily` ·
`multibacktest_strategy_daily` · `strategy_registry` · `strategy_daily` ·
`research_runs` · `research_cases` ·
`alpha_registry` · `journal_entries` · `investment_decisions` ·
`investment_decision_legs` · `target_portfolio_versions` · `execution_plans` ·
`company_snapshots` · `regime_snapshots` · `scenario_packs` ·
`scenario_pack_versions` · `timing_rule_sets` · `timing_rule_set_versions` ·
`risk_snapshots` · `model_monitor_runs`

재생성은 되지만 ★그때의 입력으로는 안 된다★ — 빈티지가 그 사이 늘었고 매크로는
개정됐다. 오늘 다시 만든 스냅샷은 **다른 값**이지 복구가 아니다.

그런데도 삭제를 **금지하지는 않는다**. 사용자가 지목해 지우는 경로
(`DELETE … WHERE <id> = :id`)가 이미 있고 그것은 정상적인 CRUD 다. 막으면
기존 기능이 깨진다. ★금지가 아니라 순서다★ — 지우기 전에 무엇을 잃는지 안다.

### 크기 기준 정리의 후보 — ★수치는 아직 미상★

| 후보 | 왜 후보인가 | 정하려면 |
|---|---|---|
| `backtest_runs`.`result` | 실행당 수백 KB JSON. **유일하게 현실적인 후보** | 텔레메트리의 `result_bytes` 합계를 실 DB 에서 본다 |
| `multibacktest_strategy_daily` | 행이 실행×거래일×전략 — ★가장 빨리 는다★ | 같은 방식으로 행 수를 센다 |

★"90일" 같은 숫자를 여기 적지 않는다.★ 실 DB 의 행 수·용량을 관측한 적이
없고, 근거 없는 수치가 스펙에 박히면 다음 사람은 그것을 측정값으로 읽는다.

---

## 4. ④ 재생성 가능 — 지워도 잃는 것이 없다

`factor_snapshot` · `market_snapshot_equity` · `market_snapshot_ficc` ·
`instrument_master` · `local_portfolio_state` · `local_account_state` ·
`stocks`

공통점은 **시간 축이 없다는 것**이다. 캐시이거나 오늘 상태의 사본이라 애초에
과거를 담지 않는다(그래서 ①과 정확히 반대다).

- `market_snapshot_*` 는 이미 매 갱신마다 전체 교체된다 — 즉 **이미 지워지고
  있다**. 정책이 그 사실을 뒤늦게 인정할 뿐이다.
- `local_*` 는 대사할 때마다 브로커 응답으로 다시 채운다. ★브로커가 진실이다.★
- `stocks` 는 ★상장폐지를 담고 있지 않다★ — `is_active` 컬럼은 있지만 `0` 으로
  쓰는 코드가 저장소에 없다(실측). 담고 있었다면 ①이었을 표다.

---

## 5. ⑤ 계정 소유 — 이 저장소가 정할 문제가 아니다

`users` · `portfolios` · `trade_log`

지울지 말지는 **계정 소유자**가 정한다. 그래서 보호하지도, 재생성 가능이라고도
하지 않는다. `users` 삭제는 나머지 둘로 `ON DELETE CASCADE` 되도록 선언돼 있다.

★`trade_log` 와 `live_fills` 를 혼동하지 말 것★ — 이름이 비슷하지만 다른 표다.
실거래 감사 기록은 `live_*` 쪽이고 그것은 ②로 보호된다.

---

## 6. 파일 산출물 — 표가 아니라서 테스트가 못 건다

| 무엇 | 지금 상태 | 판단 |
|---|---|---|
| `src/data/dart_cache/*.json` | TTL 7일은 **읽을 때 무시**하는 판정이고 ★파일은 영원히 남는다★ | 만료 파일은 **지워도 안전하다**(원천에서 다시 받는다) |
| 분봉 parquet(날짜 파티션) | 계속 쌓인다 | 지우면 그 기간 분봉 체결이 일봉으로 떨어진다(`intraday.fallback` 이 센다) — 체결 모델의 정밀도와 맞바꾸는 선택 |

★지금 실제로 아픈 유일한 곳이 `dart_cache` 다.★ 만료 판정은 있는데 지우는
경로가 없다. 정책은 "지워도 된다" 로 정했고, **경로는 이번에 만들지 않았다**.

---

## 7. ★이 정책이 주장하지 않는 것★

- **보관 기간을 정한 것이 아니다.** 정한 것은 **분류와 불변식**이다. 숫자는
  실 DB 를 본 뒤이고, 그때 볼 계기는 §3 의 표에 적혀 있다.
- **디스크를 줄이지 않는다.** 삭제 코드를 만들지 않았다 — `dart_cache` 는
  여전히 쌓인다. 정책이 "지워도 된다" 고 말할 뿐이다.
- **감사 요건을 확인한 것이 아니다.** 실거래 표는 *"모르므로 영구"* 이고,
  그것은 결론이 아니라 **명시된 미상**이다.
- **④가 "쓸모없다" 는 뜻이 아니다.** 지우면 다시 채우는 비용이 든다(워밍·대사).
  잃는 것이 **데이터가 아니라 시간**이라는 뜻이다.

## 8. 다시 볼 조건

| 언제 | 무엇을 |
|---|---|
| 실 DB 를 볼 수 있게 되면 | `backtest_runs`의 `result_bytes` 합계와 `multibacktest_strategy_daily` 행 수 → §3 의 미상 수치 |
| 실계좌를 쓰기 시작하면 | ②의 법적 보존 요건 확인 → "모르므로 영구" 를 **아는 값**으로 |
| `dart_cache` 가 디스크를 압박하면 | 만료 파일 청소 경로(정책은 이미 허용한다) |
| 표를 새로 만들면 | ★테스트가 강제한다★ — 분류 없이는 통과하지 못한다 |
