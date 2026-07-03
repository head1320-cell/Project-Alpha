# 적재(Ingest) 정체 해소 — 관측성 + DART 쿼터 감지 + 표시 정확화 설계 스펙

- 날짜: 2026-07-03
- 브랜치: `claude/keen-thompson-bdk3e8`
- 상태: 진단 완료 — 구현 진행 (사용자: "문제를 해결해줘" + 워크플로우 스펙커밋→계획→TDD 지시)
- 커밋 트레일러(필수): `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA`
- 검증: `KIS_USE_MOCK=1 python -m pytest tests/ -q`(베이스라인 **681 passed/10 skipped**) + ruff / tsc / next build.

## 증상 (GCP 스크린샷)
Data Infra에서 적재 버튼을 눌러도 UNIVERSE COVERAGE(KOSPI 417/921 등)가 늘지 않음.
일봉(주식) 8,484,984행인데 "종목 0 · 기간 —", 백테스터(종목) 준비상태 X.
사용자는 KRX OpenAPI 다수 승인 완료 — "KRX/DART로 가져오는 데 문제가 있는 건가?"

## 진단 (파일:라인 — 원인 사슬)

1. **일봉은 이미 들어와 있다 (KRX 정상)**: 848만 행 ≈ 전종목×10년. 그러나 `db_status`의
   `SELECT COUNT(DISTINCT ticker), MIN(trade_date), MAX(trade_date) FROM daily_prices`(main_api.py:534)가
   **statement_timeout 5초에 걸려 None** → 프론트가 "종목 0 · 기간 —"으로 오표시, `백테스터(종목)`
   readiness가 `tickers > 5` 조건(main_api.py:565)이라 **거짓 X**. → "적재 안 됨" 인상의 절반.
2. **펀더멘털 적재 정체 = DART 쿼터 경쟁 + 침묵 실패**:
   - 재무시계열(financials) 백필(2016~2025×전종목)과 factors 적재가 **같은 DART 키(일 20,000건)** 를 동시 소모.
   - 쿼터 초과 시 DART `status != "000"` → `dart_client._get`이 **logger.warning 후 None**(dart_client.py:243-246) — UI에는 아무 신호 없음.
   - 평가 경로: ValuationEngine 평가 실패 → item 미저장(failures만 증가) → `ffl:` 미기록 →
     `ingested_codes()`(snapshot_db.py:134, **ffl: 키 기준**) 정체 → 커버리지 "현상유지".
   - 진행 상태는 `_INGEST_RUNNING` boolean뿐(main_api.py:614-631) — 진행률/저장수/에러가 UI에 전무.
3. **빈 팩터 영속 오염 (잠재 버그)**: `mock_base.cached()`(mock_base.py:96-101)가 builder 결과를
   **빈 dict여도 무조건 persist** + `bulk_read` 히트가 `{}`여도 `is not None`으로 서빙(89-95) →
   쿼터 소진 시점에 시도된 종목은 빈 팩터가 TTL 동안 고정(재시도 차단).
4. **ETF 커버리지가 늘 수 없는 구조**: "etf" 버튼 = `prewarm_etf_universe`(크로스에셋 15종 시세,
   main_api.py:582-584). factors 체인은 (kospi200, kosdaq150, all_listed)만(main_api.py:588-590) —
   ETF 유니버스(1,250) 팩터 적재 경로 자체가 없음. 또한 ETF는 DART 재무가 없어 실모드 펀더멘털
   평가가 구조적으로 실패 → 이번 스코프에선 **정직 표기**로 처리(아래 D).

## 설계

### A. 빈 팩터 영속 오염 방지 (mock_base — 최소·저위험 핵심)
- `cached()`: builder 결과가 **falsy(빈 dict/None)면 persist 생략** + in-memory도 짧은 TTL(재시도 허용).
- persist 히트가 falsy면 **miss 취급**(재계산 기회) — `if hit:` (truthy) 조건.
- TDD: builder→{} 시 write 미호출·다음 호출서 재시도 / builder→정상값 시 기존과 동일.

### B. DART 사용량·쿼터 관측 (dart_client)
- 모듈 카운터: `_USAGE = {"requests": n, "errors": {status: n}, "last_error": {...}, "quota_exhausted": bool}`.
- `_get()`에서 요청/에러 집계, DART **사용한도 status "020"**(및 message에 '한도' 포함) 감지 시
  `quota_exhausted=True`. `dart_usage()` 공개 함수.
- TDD: 응답 fixture로 020 → quota_exhausted, usage 카운트.

### C. Ingest 진행/에러 상태 스토어 (main_api + snapshot_db)
- `_INGEST_STATUS[target] = {running, started_at, finished_at, progress: {done, total, stage},
  saved, failures, last_error, result}` (기존 `_INGEST_RUNNING` 유지 — 하위호환).
- `ingest_universe(universe, progress_cb=None)`: 청크마다 `cb(done, total, saved, failures)`
  (saved=`evaluated_actual`, failures=`failures` 합산). **DART `quota_exhausted`면 조기 중단** +
  `last_error="DART 일일 한도 초과 — 중단됨. 내일 재시도(캐시로 이어짐)"`.
- `_ingest_run("factors")`가 유니버스별 진행을 status에 기록. db-status 응답에 `ingest_status` +
  `dart_usage` 포함.
- TDD: mock으로 progress_cb 호출·saved 집계, quota 플래그 시 중단.

### D. db-status 표시 정확화 + ETF 정직 라벨
- daily_prices: `COUNT(DISTINCT ticker)` → **pg_stats n_distinct 추정** 폴백, MIN/MAX 개별 쿼리 분리.
  타임아웃/실패 시 **null**(0 금지) → 프론트 "—". `백테스터(종목)` readiness = `EXISTS(SELECT 1 ...)`
  (+ rows>0) — 즉시 판정.
- Data Infra: INGEST 섹션에 타깃별 **진행바(done/total)·저장/실패 수·마지막 에러 문구**,
  DART 사용량(요청/에러/한도 도달) 라인. ETF 버튼 라벨 "ETF 시세(크로스에셋 15)"로 정직화,
  UNIVERSE COVERAGE의 ETF 행에 "가격 전용 — 펀더멘털 적재 대상 아님" 주석.
- 프론트 dbStatus 타입 확장.

### E. 연결 진단(Ingest Doctor) — "KRX/DART 문제인가?"에 UI 즉답
- `GET /api/v1/data/ingest-doctor`: **실제 1콜 시험** — DART(기업개황 등 경량 endpoint),
  KRX(지수 1일 조회), KIS(토큰 상태). 각 `{ok, message, latency_ms}` + dart_usage 요약.
  mock 모드/키 없음 → `{ok: false, message: "키 미설정/mock 모드"}` (정직).
- Data Infra에 "연결 진단" 버튼 → 결과 3줄 표시.
- TDD: mock 모드 응답 형태.

## 구현 순서 (작은 커밋)
1. A: cached 빈값 영속 방지 (TDD)
2. B: dart_usage/쿼터 감지 (TDD)
3. C: ingest 상태 스토어 + progress_cb + 조기 중단 (TDD)
4. D-백엔드: db-status 쿼리 안전화 + readiness EXISTS + ingest_status/dart_usage 노출
5. E: ingest-doctor 엔드포인트 (TDD)
6. D/E-프론트: 진행바·에러·DART 사용량·닥터 버튼·ETF 정직 라벨·"—" 표시
7. 전체 검증 → CLAUDE.md → 푸시

## 정직한 한계
- 샌드박스는 GCP DB/실키 없음 — 로직은 mock/fixture로 검증, 실제 쿼터 수치·타임아웃 해소는
  GCP 재배포 후 Data Infra 화면에서 확인(이제 원인이 화면에 뜸).
- ETF 팩터(가격 전용) 적재는 별도 과제로 명시 — 이번엔 오해를 없애는 정직 표기까지.
- financials와 factors의 DART 쿼터 경쟁 자체는 남음 — 이제 한도 도달이 **보이고 중단·재개가
  자동**이므로 사용자가 순서를 선택 가능(권장: financials 완주 후 factors).
