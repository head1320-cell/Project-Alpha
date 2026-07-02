# 스크리너 유니버스 실수치화 + 숫자 정직화 + 100행 페이지네이션 — 설계 스펙

- 날짜: 2026-07-02
- 브랜치: `claude/keen-thompson-bdk3e8` (이 브랜치 외 푸시 금지, PR 명시 요청 시만)
- 상태: 설계 승인됨("그렇게 해") — 스펙 리뷰 대기
- 커밋 트레일러(필수):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NSAuFjWec6ZwXi9wq7SbrA
  ```
- 검증: 백엔드 `KIS_USE_MOCK=1 python -m pytest tests/ -q` + `ruff check`; 프론트 `cd frontend && npx tsc --noEmit && npx next build`. 현재 베이스라인 **657 passed / 10 skipped**.

## 사용자 요청 (원문 의도)

1. KRX 실제 상장 수(KOSPI 946 / KOSDAQ 1,822 / 전체 2,875, KONEX 107 포함)에 비해 스크리너 유니버스가 작음(전체 833 / KOSPI 395 / KOSDAQ 438 / KOSPI200 199 / ETF 69) → 실제 수에 맞게 세팅.
2. "검색된 기업"(685)과 "평가 완료"(833/833)가 왜 다른지 진단·개선.
3. "가상 스크롤"이 왜 있는지 설명, 렉 방지를 위해 **100행/페이지 페이지네이션**으로 교체.

## 진단 (원인 — 파일:라인, mock 실측으로 확인)

| 증상 | 원인 |
|---|---|
| 전체 833 / KOSPI 395 / KOSDAQ 438 | **적재 진행률 = 유니버스 크기.** `screener.py:864-880` `_resolve_universe`: 대형 유니버스(>250)는 `ingested_codes()`와 교집합. GCP의 factor_snapshot 적재가 833개(395+438=833 ✓)에서 중단된 상태. 시작 시 `_prewarm_real_data`(main_api.py:257-278)가 kospi200→kosdaq150→all_listed 순으로 백그라운드 적재하지만 DART throttle(0.15s)로 수 시간 소요, 컨테이너 재시작 시 스레드 사망. 적재 자체는 재개 가능(적재된 종목은 스냅샷 fast-path로 스킵). |
| 검색된 685 < 평가 833 | **유동성 게이트.** UI가 항상 `liquidity_floor:"relaxed"` 전송(TerminalScreener.tsx:210) → 시총≥300억·거래대금≥3억·스프레드≤1%(liquidity_gate.py:56-61)로 148개 무표시 탈락. mock 실측: kospi200 130→120, kosdaq150 150→141 — (평가−표시)==게이트 제외 수 정확 일치. |
| KOSPI200 "199/130" | 분자 X=`total_evaluated`(런타임 마스터 199), 분모 Y=`GET /universes`의 **하드코딩 프리셋**(screener_routes.py:184-189, kospi200=130·etf=40). 마스터 미반영 표시 버그. |
| "평가 완료 X" 의미 왜곡 | `total_evaluated=len(tickers)`(유니버스 크기, screener.py:562)인데 `SCREENER_MAX_LIVE_COMPUTE=400` 상한(screener.py:474-477)으로 실제 평가는 더 적을 수 있음 — 상한 발동 시 X가 과대표기(mock 실측: 500코드→X=500, 실평가 400). |
| 가상 스크롤 | 수백 행 DOM 렌더 렉 방지용 자체 윈도잉(TerminalScreener.tsx:35,389-395 — ROW_H=41, 보이는 ~20행만 렌더). "가상 스크롤 N행"은 전체 행수 라벨일 뿐. |
| 신규/캐시 | in-memory ValuationCache 미스/히트(screener.py:514-515). 스냅샷 복원 항목은 둘 다 아님 → 전부 스냅샷이면 "신규 0 · 캐시 0"으로 혼란. |
| KRX 공식 수와 구조 차이 | ① KONEX 마스터 미수집(kis_master_parser.py:28-30 — KOSPI/KOSDAQ URL만). ② `build_master_universe`(stock_master.py:455-490)가 **그룹코드 ST(주권)만** 포함 → 리츠(RT)·외국주(FS)·투자회사 등 KRX 공식 수 포함분 누락. |

## 범위 결정 (사용자 확정)

- **KONEX 제외** — KOSPI+KOSDAQ만(~2,768 목표).
- **KRX 공식 수에 맞춤** — ST 외 그룹(리츠·외국주 등) 포함. ETF/ETN/ELW는 계속 별도(제외).
- **유동성 게이트 기본 OFF** — 선택 필터로 전환, ON 시 제외 수 명시.
- **클라이언트 페이지네이션 100행/페이지** — 서버 페이징 아님(데이터는 이미 브라우저에 있음).

## 설계

### 1. 유니버스 그룹 확장 (백엔드 — stock_master.py)

- 모듈 상수 `UNIVERSE_GROUP_CODES = ("ST", "RT", "FS", "MF", "IF", "SC", "DR")`
  (주권·리츠·외국주권·투자회사·인프라투융자·선박투자·예탁증서. EF/EN/EW/SW/SR 제외 = ETF·ETN·ELW·신주인수권은 비포함, ETF는 기존 별도 유니버스 유지.)
- `build_master_universe`의 `kospi` / `kosdaq` / `all`(`all_listed`) 분기가 `grp(f) == "ST"` → `grp(f) in UNIVERSE_GROUP_CODES`.
- `kospi200`/`kosdaq150`의 `_topn` 폴백은 ST 유지(지수 편입은 주권 중심 — 플래그가 정상이면 폴백 미사용).
- **그룹별 집계 헬퍼** `master_composition() -> dict`: 시장별×그룹코드별 종목 수 반환(예: `{"KOSPI": {"ST": 840, "RT": 24, ...}, "KOSDAQ": {...}}`) — GCP에서 946/1,822 잔차 원인 확인용.

### 2. 적재 진행 가시화 (백엔드 + Data Infra + 스크리너 헤더)

- `db-status`(main_api.py:468~)에 추가: `universe_progress = {"kospi": {"master": M, "ingested": A}, "kosdaq": {...}, "all": {...}}` — master는 `build_master_universe` 크기, ingested는 그 목록∩`ingested_codes()`.
- Data Infra 탭(DbStatusPanel): 시장별 "적재 A / 마스터 M" 진행 표시(기존 테이블 행 or 요약 라인). 기존 "전체 적재" 버튼이 트리거(변경 없음 — factors 타깃이 이미 kospi200+kosdaq150+all_listed 순회, main_api.py:571-572).
- 스크리너 응답에 `ingested_count`(해당 유니버스의 적재 수) 포함 → 헤더에서 "적재 A/M" 표시, A<M이면 "Data Infra에서 전체 적재 실행" 안내 문구.
- 적재 로직 자체는 무변경(이미 재개 가능: 스냅샷 fast-path가 완료분 스킵, snapshot_db.py:184-205).

### 3. 숫자 정직화 (백엔드 응답 + /universes)

- `GET /universes`(screener_routes.py:180-189): 마스터 플래그 로드 시 `build_master_universe(kind)` 크기를 `size`로 반환, 마스터 없으면 기존 프리셋 폴백(샌드박스 안전). → "199/130" 해소(분모가 마스터 실크기로).
- `_run_advanced_core` 응답에 추가(기존 필드 유지 — 하위호환):
  - `universe_size`: 마스터 기준 유니버스 총원(M)
  - `ingested_count`: 적재분(A)
  - `evaluated_actual`: 실제 산출 아이템 수(복원+평가, 게이트 전)
  - `capped`: SCREENER_MAX_LIVE_COMPUTE 발동 여부
- 프론트 헤더 재구성(TerminalScreener.tsx:608-613):
  `검색된 기업 N개` (대표 수치, 유지) + 보조줄 `유니버스 M · 적재 A · 평가 E · [게이트 ON 시] 유동성 제외 K · 신규 x · 캐시 y · z초`
  - `capped=true`면 "평가 상한 400 발동" 배지.
  - "가상 스크롤 N행" 라벨 삭제.

### 4. 유동성 게이트 기본 OFF + 토글 (프론트 중심)

- TerminalScreener 기본 요청 `liquidity_floor: "relaxed"` → `"off"`.
- 필터 영역에 토글 칩 "유동성 게이트 (시총300억·거래대금3억)" — ON 시 `"relaxed"` 전송, 헤더에 `유동성 제외 K개`(응답의 `liquidity_gate.filtered_out` — 이미 반환 중) 표시.
- 결과: 기본 상태에서 **검색된 기업 == 평가 완료** (게이트로 인한 무설명 격차 소멸).
- 백엔드 무변경(off/relaxed 이미 지원). 다른 소비자(백테스트 브릿지 등)의 기존 기본값은 건드리지 않음.

### 5. 가상 스크롤 → 100행 페이지네이션 (프론트)

- 윈도잉 제거: `scrollTop`/`viewH` 상태, ROW_H/WINDOW_MIN 상수, onScroll 핸들러, topPad/botPad 스페이서(TerminalScreener.tsx:112-114,241,389-395,621).
- `const PAGE_SIZE = 100; const [page, setPage] = useState(0);` — 렌더는 `sortedItems.slice(page*100, (page+1)*100)`.
- 하단 페이지 바: `◀ 이전 · 1 2 … n · 다음 ▶` + "1–100 / 2,768" 표시. 페이지 수 많으면 현재±2 + 처음/끝 압축 표기.
- 정렬 변경·새 검색 시 `setPage(0)`. 페이지 전환 시 테이블 스크롤 최상단 리셋.
- CSV 내보내기·컬럼 선택·히트맵은 전체 `sortedItems` 기준 유지(변경 없음).
- CSS: `bsc-pager` 계열 신규(기존 디자인 토큰·mono 폰트 준수).

## 구현 순서(단계 커밋)

1. 백엔드 A: 그룹 확장 + `master_composition` + master-aware `/universes` (+ 합성 마스터 플래그 단위테스트, TDD).
2. 백엔드 B: 응답 정직 필드(universe_size/ingested_count/evaluated_actual/capped) + db-status universe_progress (+ 테스트).
3. 프론트 A: 게이트 토글(기본 off) + 헤더 재구성.
4. 프론트 B: 페이지네이션(윈도잉 제거) + CSS.
5. Data Infra 진행 표시.
6. 전체 검증(pytest/ruff/tsc/build + mock 라이브 렌더) → 푸시.

## 검증

- **샌드박스**: `save_master_flags`로 합성 마스터(ST/RT/FS/EF 혼합) 주입 → 그룹 확장·/universes 크기·composition 단위테스트. 회귀 657개 유지. tsc 0 · next build. mock 라이브로 페이지 바·헤더·게이트 토글 렌더 확인.
- **GCP(배포 후 사용자 확인)**: Data Infra "전체 적재" 실행 → db-status `universe_progress`로 KOSPI/KOSDAQ 적재가 마스터 크기까지 차오르는지 확인 → 스크리너 유니버스가 실수치(≈946/≈1,822/≈2,768) 도달. `master_composition`으로 KRX 공식 수와의 잔차(그룹 구성 차) 보고.

## 정직한 한계

- 샌드박스는 마스터 파일·DB·네트워크가 없어 **실제 946/1,822 도달은 GCP에서만 확인 가능**. 여기서는 로직(그룹 확장·교집합·표시)을 합성 데이터로 검증.
- KIS 마스터의 그룹 구성이 KRX 공식 집계와 1:1이 아닐 수 있음(수십 개 잔차 가능) — `master_composition`으로 원인을 투명하게 보고하고, 필요 시 포함 그룹을 조정.
- 전종목 적재 소요시간(DART throttle)은 이 설계 범위 밖(수 시간, 1회성). 완주 여부는 진행 UI로 확인.
