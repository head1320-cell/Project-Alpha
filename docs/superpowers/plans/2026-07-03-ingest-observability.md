# 적재 정체 해소 — Implementation Plan (의사결정 기록)

> 스펙: docs/superpowers/specs/2026-07-03-ingest-observability-design.md
> 실행: 인라인 TDD·작은 커밋. 구현 중 더 나은 방식 발견 시 이유를 남기고 수정(사용자 지시).
> 베이스라인 681 passed/10 skipped. 브랜치 claude/keen-thompson-bdk3e8.

## Task 1 (A) — cached() 빈값 영속 방지
- Test `tests/test_cached_empty.py`: builder→{} 시 snapshot_db.write 미호출 + 다음 호출 재시도(빈값 미고정),
  builder→정상 dict 시 write 1회·캐시 서빙, persist 히트가 {}면 miss 취급.
- Impl `src/data/mock_base.py cached()`: `hit` truthy일 때만 서빙; `value`가 truthy일 때만 persist,
  falsy면 in-memory TTL을 짧게(재시도 허용, 기본 60s — `EMPTY_RETRY_TTL`).

## Task 2 (B) — DART 사용량·쿼터 감지
- Test `tests/test_dart_usage.py`: `_get` fixture(requests.get monkeypatch)로 status 000/020 →
  usage 카운트·quota_exhausted, `dart_usage()` 형태.
- Impl `src/data/dart_client.py`: 모듈 `_USAGE` + `record()` + `dart_usage()` + `_get`에 집계,
  status "020" 또는 message에 "한도" → quota_exhausted=True.

## Task 3 (C) — ingest 상태 스토어 + progress + 조기 중단
- Test `tests/test_ingest_status.py`: ingest_universe(progress_cb) 호출 시 done/total/saved 누적,
  quota_exhausted=True monkeypatch 시 조기 중단+사유.
- Impl: `snapshot_db.ingest_universe(universe, progress_cb=None)` — 청크 후 cb(done,total,saved,failures);
  DART quota 확인 후 break. `main_api`: `_INGEST_STATUS` dict + `_run()`에서 기록(시작/진행/완료/예외),
  factors는 유니버스별 stage 라벨. db-status에 `ingest_status`+`dart_usage`.

## Task 4 (D-백엔드) — db-status 정확화
- daily_prices tickers: `pg_stats n_distinct` 추정(음수→비율×rows) 폴백, 실패 시 None.
  MIN/MAX 개별 q() 분리(각 5s 컷). readiness `백테스터(종목)`: `EXISTS` + rows>0.
- 값이 None이면 0으로 강제하지 않음(프론트 "—").

## Task 5 (E) — ingest-doctor
- Test `tests/test_ingest_doctor.py`: mock 모드 → 각 소스 {ok: False, message: 키/mock 안내} 형태.
- Impl `GET /api/v1/data/ingest-doctor`: DART 경량 실콜(키 있으면), KRX 지수 1일, KIS 토큰 상태,
  latency_ms, dart_usage 요약.

## Task 6 — 프론트 (DbStatusPanel + api.ts)
- 타입: ingest_status/dart_usage/doctor. INGEST 섹션: 타깃별 진행(done/total N%)·저장/실패·
  last_error 문구(빨강)·DART 사용량 라인. "연결 진단" 버튼→결과 3줄. ETF 버튼 라벨 "ETF 시세
  (크로스에셋 15)", UNIVERSE COVERAGE ETF 행 "가격 전용" 주석. tickers null→"—"(fmtNum 기존 처리 확인).

## Task 7 — 전체 검증 + CLAUDE.md + 푸시 + GCP 런북
- pytest(681+신규)/ruff/tsc/build, mock 라이브 스모크(db-status 응답 형태), CLAUDE.md 요약, push.
- 런북: 재배포 → Data Infra에서 ① 연결 진단 ② 일봉 "—"가 아닌 실측/추정 표시 확인
  ③ financials 완주 후 factors(전체) 실행 — 이제 진행/중단 사유가 화면에 뜸.
