# BH · 남은 것 — 안전 경로 정직성 · 귀인 항등식 · 백테스트 국면(R4-a)

작성 2026-09-25 · 앞 프로그램 BG(`docs/superpowers/specs/2026-09-24-multistrategy-restore-r1-r3-design.md`) ·
기록 `docs/HISTORY.md` 의 BH 항목(구현 후)

## 1. 왜

BG 가 멀티전략을 되살린 뒤 남은 것은 넷이었다: R4(매크로 피드 · 국면 분류기 · hrp_macro ·
systemic_risk_score)와 BG3 에서 찾은 귀인 문제. 위험도가 전혀 달라 네 조각으로 나눴고,
사용자가 셋을 골랐다.

## 2. 사용자가 정한 것

| 결정 | 답 |
|---|---|
| 범위 | **A 귀인 항등식 · B 안전 경로 정직성 · C 백테스트용 국면**. D(systemic_risk 생산 → `auto_risk` 무장)는 하지 않는다 |
| `hrp_macro` | **계속 거절** — 기울기 규칙은 새 배분 정책이고, 증거(실데이터 국면 이력)가 생긴 뒤 따로 설계한다 |
| `regime_change` 에서 국면이 미상인 날 | **트리거하지 않고 세어서 말한다** |
| 국면 시장 | **KR · US 둘 다** — *"나중에 KR 도 데이터 적재할 거야. 감안해서 진행해"* |

국면 시장 결정의 해석: 두 시장을 **같은 엄격 PIT 경로**로 계산하고, 가용성은 선언이 아니라
**빈티지 스토어의 실제 행**으로 정한다. KR 을 막는 하드코딩을 두지 않는다 — KR 빈티지가
적재되면 코드 변경 없이 KR 국면이 나온다.

## 3. 감사가 찾은 것 (실측, 2026-09-25)

**킬스위치·주문 게이트웨이**
- `systemic_risk_score` 의 생산자는 저장소에 없다. `auto_risk` 는 늘 unverified 로 보고된다(정직).
- 그러나 미상을 0 으로 읽는 곳이 넷 있다 — `kill_switch.py:256` · `risk_gateway.py:278` ·
  `realism_engine.py:470` · `narrative/prompts.py:266`. ★`realism_engine` 의 것은
  `regime_model` 이 생기는 순간 systemic risk **0.0 을 지어내는 함정**이다.★
- 게이트웨이 ⑧(국면 적응)은 `regime_state` 가 없으면 **기록 없이 건너뛴다**(else 없음).
  `mode` 키를 읽는데 분석기는 `recommended_mode` 를 낸다 — 어휘 불일치.
- readiness 라우트는 `regime_state=None` 을 하드코딩해 감시 데몬이 보는 국면을 모른다.
- 실제 트립 경계(≥85) 를 거는 테스트가 없다.

**귀인**
- 수익률 항등식: `net_t = EW_t + alloc_t + cost_t (+ cash_t, realism)`, `EW_t = 전략 수익
  단순평균`, `alloc_t = Σ(w−1/n)·r`.
- 분해기는 기준을 0 으로 하드코딩해 **EW 수익 전체를 잔차가 흡수**하고, 수익률에 없는
  **네팅을 '청산 효과' 스텝으로 더하며**, 매크로 조정(이미 가중 안에 있다)을 따로 더할
  자리이고, 현금 스텝이 없다. `selection_effect` 가 늘 None 이라 잔차는 늘 "미설명" 으로
  나와 위 문제들을 가렸다.
- `_persist` 가 `strategy_return` · `contribution` · `macro_adjustment` 에 **상수 0** 을
  저장한다 → 전략별 기여가 "0 으로 관측" 된다.

**국면**
- 단일 정의 `regime_axes`: `AXES`(kr·us) · `compute_axis_detail` · `quadrant` ·
  `quadrant_probs` · `QUADRANTS = Goldilocks/Reflation/Stagflation/Disinflation`
  (Deflation 은 의도적으로 제거했다).
- PIT 읽기 `pit_macro.series_as_of(key, as_of)` — 빈 `vintage_id` 를 버리고 공표가 `as_of`
  이하인 것만 준다.
- 엔진·귀인·프런트는 대문자 `DEFLATION` 어휘라 맞는 행이 0 이다.
- 엔진의 `regime_change` 는 실제로는 "월간 + 국면이 None 이면 매일" 이다.
- 이 환경의 빈티지는 0 건 — 지금은 두 시장 모두 대부분 미상이다.
- `stress_score` 를 `systemic_risk_score` 로 쓰는 것은 문서가 명시적으로 금지한다
  (HISTORY 14749 등).

## 4. 설계

### 4.1 B · 안전 경로 정직성 (BH1) — ★아무것도 무장하지 않는다★

**원칙: 입력이 있으면 판정(발동·차단)은 한 글자도 바뀌지 않는다. 바뀌는 것은 미상을 0 으로
읽는 곳과 조용한 건너뜀뿐이다.**

- `KillSwitch.should_auto_trigger` — `systemic_risk_score` 가 없거나 None 이면 분기를 건너뛴다
  (현재와 같은 결과). 0 을 만들지 않는다. 기존 `unverified_checks` 가 그대로 말한다.
- `RiskGateway` ⑧ — `regime_state` 없음 · `systemic_risk_score` 없음 · `mode` 없음은 각각
  `checks_unverified` 에 사유로 남는다. `recommended_mode` 를 `mode` 로 **매핑하지 않는다**
  (방어 모드 매수 차단이 켜지는 판정 변경이다 — 불일치는 사유 문구로 기록만 한다).
- readiness 라우트 — `lifecycle._monitor_regime_state` 를 `risk_monitor.current_regime_state`
  로 옮겨 데몬과 라우트가 **같은 입력**을 쓴다. `auto_risk` 는 여전히 inoperable 이고 사유가
  실제 상태를 말한다.
- `realism_engine._get_systemic_risk_pit` — 없으면 None. `prompts` — None 이면 "미상".

### 4.2 A · 귀인 항등식 (BH2)

**원칙: 분해는 수익률 항등식을 데이터로 검증하고, 수익률에 없는 것은 스텝이 아니다.**

- 엔진이 일별 `baseline_effect = EW_t` 를 싣고 저장한다(`multibacktest_daily.baseline_effect`,
  W1 관용구로 뒤늦게 붙는 칸, DEFAULT 없음 → 옛 행은 NULL = 미상). `_persist` 의 상수 0 을
  실제 값으로 바꾼다(`strategy_return = r`, `contribution = w·r`, `macro_adjustment` 실제).
- 항등식 드라이버 = `baseline_effect · allocation_effect · cost_effect · cash_effect`.
  `netting_effect` · `macro_effect` · `selection_effect` 는 **보고 전용**(스텝 아님):
  네팅은 수익률 밖 실측 절감, 매크로는 배분 효과의 내역, 선택 효과는 멀티전략에서 정의되지
  않음(전략 내부 선택은 EW 기준 안에 있다).
- ★항등식 검사★ — 일별 `|net − (EW + alloc + cost + cash_or_0)|` 의 최대값과 `identity_holds`.
  성립하면 현금 None 은 "이 엔진에 없음"(미상 아님)으로 읽는다.
- 워터폴: `동일가중 기준` → `배분 효과` → `거래 비용` → (`현금이자`) → `복리(기하−산술,
  계산값)` → `실제`. 성립하면 잔차 ≈ 0. 성립하지 않거나 기준이 미상이면 "미설명 잔차" +
  구체 사유. 네팅은 워터폴 밖 별도 줄.
- `daily_explanation.STRATEGY_DRIVERS` 도 같은 드라이버. 하루 잔차에는 복리가 없으므로
  "interaction" 명명을 하루 단위에서 쓰지 않는다.

### 4.3 C · 백테스트 국면 R4-a (BH3) — `hrp_macro` 는 계속 거절

- `src/engine/regime_model.py` — `MultiRegimeModel.classify_at(as_of, market, series_loader=
  pit_macro.series_as_of)`. `AXES[market]` 계열을 로더로 읽어 `compute_axis_detail` ·
  `quadrant` · `quadrant_probs` 로 판정한다(★새 분류기를 짜지 않는다★). 두 축 모두 성분 ≥ 1 ·
  합계 ≥ 3 일 때만 라벨, 아니면 None + 무엇이 없는지. `systemic_risk_score` 는 항상 None +
  사유(생산하지 않는다).
- `panel(trading_days, markets)` — 월 단위로 **결정일 전날까지 공표분**으로 판정하고 거래일에
  앞으로 채운다(그 시점까지 알 수 있던 라벨이라 룩어헤드가 아니다).
- 가용성 — `regime_model` 이 생기면 `MISSING` 에서 빠지고 `regime_change` 가 풀린다.
  `macro_feed` 는 남아 `hrp_macro` 는 422 그대로.
- 엔진 — `regime_market`(kr|us, 기본 kr) · 두 시장 라벨을 항상 싣는다.
  `regime_change` 는 첫 적격일 1회 배분 + **알려진 라벨 → 다른 알려진 라벨**일 때만
  리밸런싱. 요약 `regime_rebalance` · `regime_labels` 가 커버리지를 센다.
- 어휘 — `regime_axes.QUADRANTS` 하나. 미상은 별도 "미상" 칸.

## 5. 검증

TDD(red→green) · 변이 배터리(기준선 녹색 먼저, 무해 짝 생존) · 전체 게이트(ruff · pytest ·
tsc · eslint · next build) · BH2·BH3 브라우저 실물 E2E(mock). 커밋 BH1 · BH2 · BH3.

## 6. ★이 설계가 하지 않는 것★

- `systemic_risk_score` 생산 · `auto_risk` 무장(D) · `stress_score` 별칭.
- `hrp_macro` 기울기 규칙.
- 게이트웨이 `mode` ↔ `recommended_mode` 매핑(판정 변경).
- 빈티지 적재(데이터 작업 — 사용자 몫). KR 을 비-PIT(개정값)로 채우기.
