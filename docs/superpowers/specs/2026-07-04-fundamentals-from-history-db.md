# 스크리너 펀더멘털이 financials_history DB를 쓰도록 연결 — 유니버스 정체(884) 해소

- 날짜: 2026-07-04, 브랜치: `claude/keen-thompson-bdk3e8`
- 근거: 사용자 GCP 스크린샷 + 코드 확인.

## 진단 (확정)
- 스크리너 유니버스 크기 = `ingested_codes()` = `factor_snapshot`의 **`ffl:%` 키 수**(snapshot_db.py:134-143).
- `ffl:`는 `FundamentalsStore.get_factors → cached → _build_factors → _real_raw_financials`가 생성.
- **`_real_raw_financials`(fundamentals_store.py:200-)는 라이브 DART만 호출하고 `financials_history`
  DB를 전혀 안 읽음.** 운영에서 DART가 한도/throttle로 실패하면 `{}` 반환 → cached()가 (정당하게)
  빈값 영속 안 함(IO Task 1) → `ffl:` 미증가 → 유니버스 884 정체.
- 증거: 재무시계열(financials_history) 25,616행·2,562종목 백필됐고 factors "저장 2,349" 보고했으나
  factor_snapshot은 8,515→8,516(불변), DART 요청 8건뿐, 적재 884 고정. 두 데이터 경로가 분리됨.

## 설계 (DB-우선 주입 — 기존 파이프라인 재사용)
- NEW `FundamentalsStore._fs_from_history(stock_code, year) -> FinancialStatement | None`:
  `dart_history.history_snapshot(code, year, "11011")`(원 단위 원천)을 `FinancialStatement`로 매핑
  (revenue/operating_profit/net_income/gross_profit/total_*/current_*/operating_cf/shares/dps).
  핵심값(revenue·total_assets) 전부 없으면 None. is_mock=False(실데이터 판별 통과).
- NEW `FundamentalsStore._get_fs(dart, corp_code, stock_code, year)`: **DB 우선 → 라이브 DART 폴백**.
- `_real_raw_financials`: 최신·전년·3년전 재무 조회를 직접 DART → `_get_fs`로 교체. `dart.is_configured`
  없어도, corp_code 없어도 DB 데이터만 있으면 동작(early-return 완화). 배당은 corp_code 있을 때만 DART
  best-effort(실패 시 0 — 팩터 영속 비차단).
- 효과: 백필된 2,562종목이 **DART 쿼터 무소모**로 실 펀더멘털 → `ffl:` 영속 → 유니버스가 ~2,562로
  확장(financials_history에 없는 ~135종목은 정직하게 미포함).

## 단위
- financials_history는 원(raw DART, upsert_statement가 fs 필드 그대로 저장). `_real_raw_financials`의
  기존 `to_억(v)=v/1e8`가 그대로 적용 → DB(원)→억 변환 정확. 추가 변환 없음.

## TDD
- `_fs_from_history`가 snapshot dict→FS 매핑(필드·None 처리).
- 운영모드(KIS_USE_MOCK=0)+DART 미설정+history_snapshot 실데이터 → `_real_raw_financials` 비None,
  `get_factors`가 빈 dict 아님(roe 등 도출).
- history_snapshot None(백필 없음)+DART 미설정 → None(폴백 없음, 기존 동작).

## 검증
- 기존 test_realdata_parsing(45)·test_dart_history·펀더멘털 회귀 불변(DB 비면 DART 폴백 = 기존).
- GCP: 재배포 후 "펀더멘털 적재" 재실행 → factor_snapshot ffl: 급증, 스크리너 유니버스 ~2,562 도달.

## 정직한 한계
- financials_history에 없는 종목(신규상장 등 ~135)은 여전히 미포함 — 실데이터 없음(정직).
- 샌드박스는 DB 없어 로직만 검증, 실제 2,562 도달은 GCP.
