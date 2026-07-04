# DART 재무시계열 백필 정체 — 마스터캐시 경쟁 + 수동트리거 무한루프 재사용 수정

- 날짜: 2026-07-04, 브랜치: `claude/keen-thompson-bdk3e8`
- 근거: 사용자 제공 GCP 로그(ingest-doctor/db-status/psql/docker logs) + 코드 확인.

## 진단 (확정)
- `ingest_status: {}` — 수동 "재무시계열" 버튼은 아직 실행된 적 없음(또는 재배포로 리셋). 즉 기존에
  의심한 "수동 버튼 무한루프 정지"는 **아직 발현되지 않은 잠재 버그**(여전히 실재, 아래서 같이 수정).
- **실제 정체 원인**: 부팅 시 KIS 마스터 수집(`_collect_master_bg`)과 DART 재무 백필
  (`_dart_history_backfill_bg`)이 **별도 스레드로 동시 시작**. 백필 루프의 첫 반복이 마스터 캐시가
  아직 채워지기 전에 실행되면 `_all_listed_tickers()`(`src/data_sync.py:115-122`)가 `load_master_flags()`
  빈 결과 → `[]` 반환 → `backfill_financials`가 `SEED_TICKERS`(30종목)로 조용히 폴백
  (`src/data/dart_history.py:138-141`). 로그가 정확히 이를 보여줌:
  `{'tickers': 30, 'calls': 0, 'saved': 0, 'skipped': 300, ...}` — 30종목×10년이 이미 skip(과거 실행분)
  이라 `stopped_at_quota` 없이 정상 종료로 보고되고, `_dart_history_backfill_bg`가 **24시간 sleep**
  (main_api.py `else: time.sleep(24*3600)`). DB엔 2,562종목이 있는데(과거엔 경쟁에서 안 걸렸거나 수동
  CLI 실행분) `last_fetch`가 이틀째 정지 — 정확히 "이 경쟁 상태에 갇힌 뒤 24h씩 헛도는" 패턴과 일치.
- **부수 버그(잠재)**: `_ingest_run("financials")`이 무한루프 `_dart_history_backfill_bg()`를 그대로
  호출 — 수동 버튼을 누르면 절대 안 끝나고 진행률도 없음(factors만 progress_cb 있음).

## 수정
1. `backfill_financials`(dart_history.py): `all_listed=True`인데 `_all_listed_tickers()`가 비어
   SEED로 폴백했으면 `stats["fallback_to_seed"]=True` 기록. `progress_cb(done,total,saved,calls)`
   옵션 인자 추가(종목 단위 보고).
2. NEW `main_api._dart_backfill_sleep_seconds(stats) -> int`(순수함수, TDD): quota면 3h, **fallback면
   짧은 재시도**(`DART_HISTORY_RETRY_SEC` 기본 300s), 정상 완료면 24h. `_dart_history_backfill_bg`가 이걸로 sleep.
3. `_ingest_run("financials")`: 무한루프 재사용 제거 → `backfill_financials(...)` 1회 직접 호출 +
   progress_cb를 `_INGEST_STATUS["financials"]`에 연결(factors와 동일 패턴). 수동 버튼이 실제로 끝남.

## 검증
- TDD: fallback 플래그(마스터 있음/없음 2케이스) + progress_cb 호출 + sleep_seconds 3분기.
- 회귀: 기존 test_dart_history.py 전체 + main_api ingest 테스트.
- GCP 확인 항목: 재배포 후 며칠 내 `last_fetch`가 갱신되는지, 재무시계열 버튼이 정상 종료(결과 반환)되는지.
