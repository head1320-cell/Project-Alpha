# ECOS 데이터 계약 감사 — ★"미검증"에서 "검증됨"으로 갈 수 있는가★

> 읽기 전용 감사. 선행 `432f554`(주기 축 신설) · 상위 감사
> [`2026-08-27-capability-lineage-audit.md`](2026-08-27-capability-lineage-audit.md)
>
> **결론을 먼저 적는다 — 갈 수 없다.** 이 환경에는 자격증명도 네트워크 경로도 없다.
> 그래서 검증하지 않고, **검증할 수 없다는 사실을 기록**하고 검증 가능한 날을
> 준비한다. 37계열 전부 **E0** 이며 증거 파일은 **빈 채로** 커밋된다.

---

## 0. 왜 라이브 검증이 불가능한가 (실측)

### 자격증명

```
BOK_API_KEY: 0 자        .env: 없음        .env.example:86 에 빈 슬롯만
```

### 네트워크

| 호스트 | 결과 |
|---|---|
| `ecos.bok.or.kr` | `curl: (56) CONNECT tunnel failed, response 403` |
| `www.bok.or.kr` | 000 (동일) |
| `api.stlouisfed.org` | 000 (동일) |

프록시가 이 호스트들에 CONNECT 를 허용하지 않는다. ★메타 API 도 문서 호스트도
닿지 않으므로 Phase 2(라이브 프로브)는 실행 자체가 불가능하다.★

### 저장소 안의 "ECOS 응답"은 증거가 아니다

`{"TIME": "20260102", "DATA_VALUE": ...}` 형태가 `tests/test_ecos_coordinates.py`·
`tests/test_factor_tokens.py` 에 있다. ★전부 손으로 쓴 테스트 더블이다.★
그것을 TIME 포맷의 증거로 인용하면 **순환논증**이 된다 — 검증하려는 가정을 그대로
담고 있기 때문이다. 저장소 전체에 캡처된 ECOS 응답도, 벤더링된 OpenAPI 스펙도 없다.

### ★`verified_live=True` 는 "주기 검증됨"이 아니다★ (이번 감사의 새 발견)

ECOS 8계열(`KR_BASE_RATE`·`KR_3Y`·`KR_10Y`·`KR_CPI`·`KR_IP`·`KR_LEADING_CYCLE`·
`USD_KRW`·`KOSPI`)이 이 플래그를 달고 있다. 근거를 추적한 결과:

| 추적 대상 | 실제로 무엇을 말하는가 |
|---|---|
| `100fc3a` 커밋 메시지 | *"기존 지표(BOK 8)… 그 코드들은 실호출로 검증된 적이 있다"* — ★캡처된 아티팩트 없는 주장★ |
| 같은 커밋의 다른 문장 | *"다섯 호스트가 전부 프록시 403 이라 실호출로 확인할 수 없다"* |
| `c31d81e` (40계열 확장) | *"이 환경은 ECOS 호스트가 프록시 403"* — 신규 32계열은 전부 `False` |
| 검증 경로 `verify_connection.py::check_ecos` | **값의 범위만** 본다 (USD 800~2500 · 국고채 0~15%). ★주기도 TIME 문자열도 기록하지 않는다★ |

즉 그 플래그가 증언하는 것은 *좌표가 값을 돌려주는 것 같다* 이지 *주기가 D 다* 가
아니다. **`verified_live` 와 `frequency` 는 서로 다른 사실이고, 전자가 후자를
함의하지 않는다.**

★조치하지 않았다★ — 8개를 `False` 로 내리는 것이 더 정직하지만 파급이 크다
(ECOS 9계열이 mock 폴백을 잃고 regime·allocation 개발 화면과 골든 스냅샷이 바뀐다).
**기록만 하고 별도 승인 사항으로 남긴다.**

---

## 1. 의존 지도 (Phase 0)

```
ECOS API ──403──✗  (이 환경)
    │
    ├─ BokClient.fetch_series(stat, item)        ★period 기본 "M" — 전 계열★
    │  └─ MacroCollector._collect_one ──→ MacroSeries(source, reason)
    │       └─ collect_all() ──→ 소비자 11개
    │            regime_analyzer.py:101          regime_snapshot_builder.py:42
    │            macro_analytics.py:216          macro_models/base.py:152
    │            factor_exposure.py:120          valuation/macro_sensitivity.py:301
    │            capability.py:123               macro_observation_store
    │            macro_routes                    kis_schema
    │            ★allocation_routes.py:465★
    │
    ├─ BokClient.fetch_item_list / fetch_table_list      메타 — 스크립트에서만
    ├─ BokClient.probe_series                            ★프로브 전용(신규)★
    │
    └─ factor_tokens._ecos_series(token)         period="D", YYYYMMDD 명시
         └─ ecos_rows_to_series   ★`len(t) != 8` 로 일별을 **가정**★
```

★수집 주기가 하중을 받는 이유가 이 지도다★ — `collect_all()` 이 regime 과
allocation 경로까지 닿는다. 증거가 생겨도 조회 주기 변경은 **별도 승인**이어야 한다.

**현재 상태 실측** — ECOS 40계열 중 `MOCK` 9 · `unavailable` 31.
MOCK 인 9개 = `verified_live` 8개 + 파생 `KR_TERM_SPREAD`(다리에서 출처를 물려받음).

---

## 2. 아홉 질문에 대한 답

| # | 질문 | 답 | 근거 |
|---|---|---|---|
| 1 | 각 계열의 실제 공표 주기 | ★✗ 37/37 미상★ | 메타 API 도달 불가 |
| 2 | 그 주기의 TIME 포맷 | ★✗★ | 코드의 `len(t)==8`(일별)은 **가정**이지 관측이 아니다 |
| 3 | 유효한 `(stat, item)` 쌍 | ✗ | `verified_live` 8개도 §0 때문에 증거가 아니다 |
| 4 | 현 엔드포인트로 실제 오는가 | ✗ | 호출 자체가 불가 |
| 5 | D/M/Q/A 로 올바로 조회하면 오는가 | ✗ | 동일 |
| 6 | 잘못된 주기로 조회 중인 계열 | ★부분 ✔★ | **37계열 전부 `period="M"`** 은 코드로 확정(`macro_collector.py` 의 `fetch_series(s, i)`). 그것이 *틀렸는지*는 1번이 미상이라 알 수 없다 |
| 7 | 명목 주기 ≠ 조회 주기 | ✗ | 6의 후반부와 같은 이유 |
| 8 | 주기를 확정할 수 없는 계열 | ★37/37★ | — |
| 9 | 증거를 체크인 인프라로 표현 가능한가 | ★✔★ | §3 — 이번에 만들었다 |

★6번이 유일하게 부분적으로 답할 수 있는 질문인 이유★ — 그것만이 **우리 코드에
대한 사실**이고 나머지는 전부 **ECOS 에 대한 사실**이기 때문이다.

---

## 3. 증거를 담는 인프라 (Q9)

`docs/specs/ecos-frequency-evidence.json` 이 사실과 **출처**를 함께 담는다.

```json
"KR_GDP": {"frequency": "Q", "time_sample": ["2024Q1"], "responding_period": "Q",
           "evidence_source": "StatisticItemList", "probed_at": "...", "grade": "E3"}
```

`source_registry` 가 그 파일을 읽어 `SourceSpec.frequency` 에 입힌다
(`_apply_frequency_evidence`). 규칙:

- **`grade` 가 `min_grade_to_apply`(E2) 미만이면 적용하지 않는다** — 낮은 확신이
  조용히 사실이 되는 경로를 막는다.
- 파일 없음·깨짐·`ECOS_CYCLES` 밖의 값 → **`None`**, 예외 없음.
- `_BY_KEY` 는 반드시 `_SPECS` 에서 파생한다 — `432f554` 에서 `_BY_KEY` 에만 쓰는
  변이가 실제로 살아남았다.

★이것이 `verified_live` 와 다른 점★ — `verified_live` 는 플래그만 코드에 있고
그것을 뒷받침하는 관측이 어디에도 없다. `frequency` 는 관측이 파일에 남고 diff 가
증거의 변화를 그대로 보여 준다.

### 등급

| 등급 | 뜻 |
|---|---|
| E0 | 증거 없음 — 코드/문서의 가정 (★지금 37계열 전부★) |
| E1 | 값이 오는 것은 봤으나 주기를 확정 못 함 |
| E2 | 메타 API 응답에서 주기 관측 |
| E3 | 메타 + 실제 TIME 값 교차 확인 |

---

## 4. 계열별 현황 — ★37행 전부 E0★

| key | 통계표 | 항목 | 라벨 | 단위 | frequency | verified_live | 증거 | TIME 포맷 | 등급 |
|---|---|---|---|---|---|---|---|---|---|
| `KR_BASE_RATE` | `722Y001` | `0101000` | 한국 기준금리 | % | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_3Y` | `817Y002` | `010195000` | 국고채 3년 | % | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_10Y` | `817Y003` | `010210000` | 국고채 10년 | % | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_CALL_RATE` | `817Y002` | `010101000` | 콜금리(익일물) | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_CD91` | `817Y002` | `010502000` | CD 91일 | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_1Y` | `817Y002` | `010190000` | 국고채 1년 | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_CORP3Y` | `817Y002` | `010200000` | 회사채 3년(AA-) | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_CORP_BBB3Y` | `817Y002` | `010320000` | 회사채 3년(BBB-) | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_TIPS10Y` | `817Y002` | `010211000` | 물가연동국고채 10년 | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_M1` | `101Y002` | `BBGA00` | M1 통화량(평잔) | 십억원 | `None` | — | 없음 | 미상 | **E0** |
| `KR_M2` | `101Y003` | `BBHA00` | M2 통화량(평잔) | 십억원 | `None` | — | 없음 | 미상 | **E0** |
| `KR_HOUSEHOLD_CREDIT` | `151Y001` | `1000000` | 가계신용 잔액 | 십억원 | `None` | — | 없음 | 미상 | **E0** |
| `KR_BANK_LOAN` | `104Y016` | `BCB8` | 예금은행 대출금 | 십억원 | `None` | — | 없음 | 미상 | **E0** |
| `KR_CPI` | `901Y009` | `0` | 소비자물가지수(CPI) | 지수 | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_CORE_CPI` | `901Y009` | `QB` | 근원 소비자물가(식료품·에너지 제외) | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_PPI` | `404Y014` | `*AA` | 생산자물가지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_SERVICE_PPI` | `404Y015` | `*AA` | 서비스업 생산자물가 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_GDP` | `200Y002` | `1400` | 실질 GDP | 십억원 | `None` | — | 없음 | 미상 | **E0** |
| `KR_IP` | `901Y033` | `A00` | 산업생산지수 | 지수 | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_LEADING_CYCLE` | `901Y067` | `I16E` | 경기선행지수 순환변동치 | 지수 | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_COINCIDENT_CYCLE` | `901Y067` | `I16D` | 경기동행지수 순환변동치 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_FACILITY_INVEST` | `901Y033` | `I11BC` | 설비투자지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_RETAIL_SALES` | `901Y033` | `I31A` | 소매판매액지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_CONSTRUCTION` | `901Y033` | `I41A` | 건설기성액 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_UNEMP` | `901Y027` | `I61BC` | 실업률 | % | `None` | — | 없음 | 미상 | **E0** |
| `KR_EMPLOYMENT_RATE` | `901Y027` | `I61E` | 고용률 | % | `None` | — | 없음 | 미상 | **E0** |
| `USD_KRW` | `731Y001` | `0000001` | 원/달러 환율 | 원 | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_EXPORT_VALUE` | `403Y001` | `*AA` | 수출금액지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_IMPORT_VALUE` | `403Y001` | `*AB` | 수입금액지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_EXPORT_VOLUME` | `403Y002` | `*AA` | 수출물량지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_IMPORT_VOLUME` | `403Y002` | `*AB` | 수입물량지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_CURRENT_ACCOUNT` | `301Y017` | `SA000` | 경상수지 | 백만달러 | `None` | — | 없음 | 미상 | **E0** |
| `KR_FX_RESERVE` | `732Y001` | `99` | 외환보유액 | 백만달러 | `None` | — | 없음 | 미상 | **E0** |
| `KOSPI` | `802Y001` | `0001000` | KOSPI 종합 | 포인트 | `None` | ✔ | 없음 | 미상 | **E0** |
| `KR_CSI` | `511Y002` | `FME` | 소비자심리지수(CSI) | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_BSI` | `512Y014` | `C0000` | 기업경기실사지수(제조업 업황) | 지수 | `None` | — | 없음 | 미상 | **E0** |
| `KR_HOUSE_PRICE` | `901Y062` | `P63AC` | 주택매매가격지수 | 지수 | `None` | — | 없음 | 미상 | **E0** |

파생 3계열(`KR_TERM_SPREAD`·`KR_CREDIT_SPREAD`·`KR_CREDIT_SPREAD_BBB`)은 조회
대상이 아니므로 제외했다 — 주기는 원계열에서 따라온다.

★`verified_live` 열의 ✔ 는 주기 증거가 아니다★ (§0).

---

## 5. 획득 계획 — 키가 생기는 날 무엇을 하는가

| 단계 | 무엇 | 비고 |
|---|---|---|
| A | `ecos.bok.or.kr` 에서 무료 키 발급 → `.env` 의 `BOK_API_KEY` | ★`.env` 커밋 금지★ |
| B | ★이 컨테이너가 아니라 로컬에서★ 돌린다 | 여기는 CONNECT 403 |
| C | `python3 scripts/verify_ecos_meta.py` (읽기 전용 리포트) | 먼저 눈으로 본다 |
| D | `python3 scripts/verify_ecos_meta.py --write` | E2 이상만 기록된다 |
| E | 증거 JSON **diff 를 사람이 검토** → 커밋 | 자동 승격 없음 |
| F | 그때 비로소 `collect_all` 주기 배선을 **별도 승인**으로 논의 | 트립와이어가 지킨다 |

### 쿼터 예산 (실측)

서로 다른 통계표 **23개** → 메타 23회. 스로틀 0.7초/회 ≈ **16초**.
TIME 프로브는 계열당 최대 1회(첫 성공에서 멈춘다), `--max-calls` 기본 60.
★대량 적재가 아니라 메타 검증이다★ — `probe_series` 의 `limit` 기본값은 **5행**이다.

### 프로브가 답하는 것과 답하지 못하는 것

| 질문 | 프로브가 답하는가 |
|---|---|
| Q1 주기 | ✔ 메타 주기 필드 |
| Q2 TIME 포맷 | ✔ ★응답 `TIME` 을 해석하지 않고 그대로 남긴다★ |
| Q3 좌표 유효성 | ✔ 항목 목록에 있는가 |
| Q4·Q5 응답 유무 | ✔ D·M·A 창으로 걸어 본다 |
| Q6·Q7 불일치 | ✔ `collector_mismatch` |
| **분기(Q) 요청 표기** | ★✗ — 부록 9★ 표기를 모르므로 거는 것 자체를 하지 않는다. 응답 `TIME` 에서 역으로 알아내야 한다 |

---

## 6. 하지 않은 것

- ★주기·TIME 포맷을 추측해 채우기★ — 증거 파일은 `series: {}` 로 커밋한다.
- ★손으로 쓴 테스트 더블을 증거로 인용하기★ — 순환논증이다.
- `verified_live` 8개 강등 — §0 에 기록만 하고 별도 승인 사항.
- 수집 주기 변경 — 증거가 생겨도 별도 승인.
- `fetch_series` 운영 동작 변경 — 프로브는 `probe_series` 로 분리했다.
- allocation · regime · BL/EP/MVO · T3 — 이 감사는 **데이터 계층 전용**이다.
