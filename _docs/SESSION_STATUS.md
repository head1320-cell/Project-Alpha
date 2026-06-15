# SESSION STATUS — UI/Screener 대개편 핸드오프 (2026-06-15)

> 컨텍스트 압축 전 스냅샷. 브랜치 **`claude/keen-thompson-bdk3e8`** (최신 `124fd3b`, origin 푸시됨).
> 게이트 상시 통과: **tsc 0 errors, next build 15/15 pages**.
> 이전 엔진/백테스터·젠포트화 맥락 → `_docs/WORK_STATUS.md` + `CLAUDE.md`. 이 문서는 그 위에 올린 **UI·스크리너 레이어** 기록.

---

## 한 줄 요약
5개 툴 페이지를 **랜딩 디자인 언어로 통일** → 스크리너를 **버틀러(Butler) 벤치마크로 전면 재구축**(백테스터 FactorPickerModal 연동 + SSE 라이브 진행 + 표시컬럼/분포/히트맵/가상스크롤/0개진단 등) → 좌측 사이드바를 **호버-확장 아이콘 레일**로 전환.

## 커밋 흐름 (최신순)
- `124fd3b` 좌측 사이드바 호버-확장 아이콘 레일 (오버레이, 순수 CSS, 접힘56/펼침260)
- `d44a32a` 빈 컬럼 자동 숨김 · 칩 Δ 임팩트 · 방향성 히트맵
- `58dfbd0` 표시컬럼 분리 + 분포 히스토그램 · 전종목 가상스크롤 · 셀 히트맵 · 0개 진단
- `ea6b639` SSE 실시간 진행표시 + 시총 빠른필터 + 칩 미리보기 카운트
- `f6589a4` 백테스터 FactorPickerModal 연동 + 진행표시 + AND/OR·프리셋·CSV + 구 CSS 335줄 정리
- `4b1c26b` 버틀러 벤치마크 퀀트 스크리너 재구축 (팩터 rail + 라이브 리스트 + 기업분석 연결)
- `2a759a4` 4개 툴 페이지 랜딩 스타일 이식 (Screener·Macro·Company·Risk)

---

## 프론트엔드 핵심

### 공용 chrome (신규 컴포넌트)
- `components/layout/PageHeader.tsx` — eyebrow + `NN/05` index + title + intro + status. 모든 툴 페이지 상단.
- `components/layout/SectionHead.tsx` — 인덱스 달린 구분선 섹션 헤드.
- `components/common/MiniViz.tsx` — 랜딩 SVG 5종(bars/line/heat/rows/gauge) + `StatGrid`/`Stat`(큰 모노 KPI).
- `components/layout/TerminalShell.tsx` — **사이드바 호버-확장 레일**: 접힘 `--t-rail-w:56px`(아이콘만) ↔ 호버/`:focus-within` 펼침 260px. **오버레이**(사이드바 `position:absolute` + `.terminal-main { margin-left:56px }` → 본문 리플로우 0). 아이콘-우선 마크업으로 아이콘 앵커 고정. `.fade-x` 공통 페이드. 활성 모듈 좌측 액센트바+액센트 아이콘 유지. 하단 `.sidebar-foot`(접힘=점, 호버=점+텍스트).

### 스크리너 (`components/screener/TerminalScreener.tsx`) — **주력**
- 버틀러식 좌측 **'내 필터' rail** + 라이브 종목 리스트. 종목 클릭 → 하단 고정 액션바 "기업 분석 탭으로 가기" → `/insights` (sessionStorage `alpha_company_ticker` 핸드오프).
- **팩터 추가 = 백테스터의 `FactorPickerModal` 그대로 재사용**(똑같은 창). onInsert 픽 → `/factor-field-map`(젠포트명→스크리너 필드 id, 93 매핑)으로 해석 → 즉시 라이브 필터. 단면 스크리닝 불가 팩터(시계열·수급)는 안내 후 무시.
- **SSE 라이브 진행**: `screenerApiAdvanced.runAdvancedStream()` → "데이터 확충 중 N/유니버스 종목" 실시간(AbortController로 이전 스트림 취소). 완료 시 실측 total_evaluated/cache.
- **표시 컬럼 ≠ 필터 컬럼**: `⊞ 컬럼` 피커로 보기전용 컬럼 추가(localStorage `alpha_screener_cols`, 재스크리닝 없이 렌더만).
- **임계값 분포 히스토그램**: 칩 값 입력 포커스 시 그 팩터의 무필터 표본 분포 + 통과/미통과 + 임계선.
- **셀 방향성 히트맵**: higher_better 기준 좋을수록 길고 초록 / 나쁠수록 짧고 빨강(방향성 없으면 크기=중립).
- **가상 스크롤**: 결과 >60행이면 윈도잉(고정 행높이 41px, 스페이서 행). 선택은 하단 액션바.
- **0개 진단**: 결과 0이면 가장 제한적(단독 통과 최소) 조건을 짚어 완화 제안.
- 그 외: 빈 컬럼 자동 숨김(mock 시총), 칩 단독 카운트 + Δ임팩트(AND 조합서 제거 수), AND/OR 토글, 시총 빠른필터(전체/대형/중형/소형, 실데이터 의존), 전략 프리셋(localStorage), CSV(BOM), 즐겨찾기(★).
- 유니버스 드롭다운(`app/screener/page.tsx`): kospi50 / kospi200 / kosdaq150 / **전체(all_listed)** / mapped.
- 칩 카운트·표본·메인 결과 모두 `liquidity_floor: "relaxed"` 로 통일.

### 5개 페이지 (`app/{screener,macro,insights,risk-tools}/page.tsx`; `/backtest` 무변경)
- 모두 PageHeader + SectionHead + 토큰 색(`--color-bull/bear/caution`, 하드코딩 색 제거). Macro=REGIME MATRIX+StatGrid, Company=가치/점수 카드+게이지(종목명 h1→div로 중복 제거), Risk=StatGrid+casualties.

---

## 백엔드 (신규/변경)
- `src/api/screener_routes.py`:
  - `GET /api/v1/screener/factor-field-map` — 젠포트 팩터명 → 필드 id (FUNDAMENTAL_ALIASES + 라벨 별칭, FIELD_BY_ID 존재분만).
  - `POST /api/v1/screener/run-advanced-stream` — SSE. 종목별 평가 진행(done/total/misses, ~100 throttle) → result. `_run_advanced_core(req, progress_cb)` 로 run-advanced와 공용화(동작 불변).
  - `AdvancedRunRequest.limit` 상한 `le=200 → le=1000` (전종목 대응).
- `src/engine/screener.py`: `run(..., progress_cb=None)` — `as_completed` 루프에서 종목 완료마다 콜백.

---

## 실행 / 검증 (재현 절차)
```
# 백엔드 (mock)
cd /home/user/Project-Alpha && KIS_USE_MOCK=1 python3 -m uvicorn main_api:app --port 8000 --log-level warning   # (run_in_background)
# 프론트 (빌드 후 serve)
cd frontend && npx tsc --noEmit            # 0 errors
cd frontend && npx next build              # 15/15 pages
cd frontend && bash -lc 'exec npx next start -p 3000'   # (run_in_background; 포트 충돌 시 fuser -k 3000/tcp 먼저)
# 스크린샷: playwright(파이썬 설치됨) + chromium 직접 지정
#   executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox","--disable-gpu"]
#   호버 캡처는 page.hover(".terminal-sidebar"); 접힘 캡처는 page.mouse.move(900,450) 먼저.
```
스크래치 산출물: `/tmp/alpha_preview/*.png`, `*.py` (목업/라이브 스크린샷 스크립트).

## 정직한 한계
- mock 펀더멘털 일부 상수(roe_pct=6.73, 부채비율=65.40 등) → 색/분포 평평. **시총 mock null → 시총 컬럼 자동 숨김**. 실데이터(DART/KIS 키)서 분산·시총 채워짐.
- 가상 스크롤은 **>60행에서만**. mock `전체(all_listed)`는 마스터가 작아 ~50종목 → kospi200(120행)에서 확인. 실데이터 전체 ≈ 2,555.
- 단면 스크리닝 팩터 ≈ **132개**(펀더멘털 104 + 기술 28). 백테스터 ~300토큰 중 시계열함수(이동평균/순위 등)는 백테스트 전용이라 제외.
- 사이드바: 터치(호버 없음)는 접힌 채 유지(아이콘 탭→이동은 가능). 데스크톱 기관용 도구 전제.

## 환경/작업방식 메모
- `superpowers@superpowers-dev` v5.1.0 설치됨 — **이 원격 컨테이너 user scope(`~/.claude`), 임시**. 로컬 미설치라 사용자 customize 목록엔 없음. 스킬 강점(`verification-before-completion`=증거 후 완료 주장, `writing-plans`, `systematic-debugging`)을 기존 흐름에 접목하기로 합의.
- 모델: `claude-opus-4-8` (세션 설정). Ultracode on.

## 다음 후보
- 실데이터 검증(키 + verify_connection), 시총 **슬라이더** 실 UI(실데이터 후), 칩 Δ 보강, StrategyComparison/Macro 추가 다듬기, 사이드바 **터치 토글** 버튼, 구 스크리너 잔여 죽은 CSS 추가 정리.
