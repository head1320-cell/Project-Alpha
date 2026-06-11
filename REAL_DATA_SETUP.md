# 실데이터 연동 가이드 (DART + KIS + KRX)

Project Alpha를 **mock에서 실데이터로 전환**하는 완전한 절차입니다.
당신의 서버에서만 키를 주입하며, 코드는 키 유무에 따라 자동 분기합니다.

---

## 📌 한눈에 보기

| 데이터 | 소스 | 키 | 채워지는 것 |
|---|---|---|---|
| 재무제표 | DART | `DART_API_KEY` | 35개 학술 펀더멘털 팩터 (GP/A·Altman Z·F-Score·EV/EBITDA…) + PIT 스냅샷 |
| 시세·실거래 | KIS | `KIS_APP_KEY/SECRET` | 실시간 시세·시총·PER·27개 기술지표·주문 |
| **역사 일봉 (장기 백테스트)** | **KRX OpenAPI** | `KRX_API_KEY` | **수년~20년 전종목 일봉 + 지수 + 시점 유니버스(생존편향 보정)** |

**전부 없어도 동작**합니다(mock). 키를 넣는 만큼 실데이터로 바뀝니다.
역할 분담: **KRX = 과거(백테스트 DB 적재) · DART = 재무 · KIS = 현재(실시간·주문)**.

---

## 1단계 — 키 발급 확인

### DART (무료)
1. https://opendart.fss.or.kr/ 가입
2. 인증키 신청 → 즉시 발급 (40자리)

### KIS (이미 보유)
- 모의투자용 / 실전용 앱키가 **다릅니다**. 둘 다 보유 중이면 OK.
- 데이터 조회만 할 거면 **실전 키 + 주문 안 함**이 일봉 데이터가 안정적입니다.

---

## 2단계 — `.env` 작성

```bash
cd ~/ficc-platform        # 배포 경로
cp .env.example .env
nano .env
```

아래 값을 채웁니다:

```bash
# ── DART (재무 실데이터) ──
DART_API_KEY=발급받은_40자리_키

# ── KIS (시세 실데이터) ──
KIS_USE_MOCK=0            # ★ 0 = 실데이터 (1이면 mock)
KIS_IS_PAPER=1           # 1 = 모의투자 키 / 0 = 실전 키

KIS_APP_KEY=앱키
KIS_APP_SECRET=앱시크릿
KIS_ACCOUNT_NO=12345678  # 계좌번호 앞 8자리
KIS_ACCOUNT_PRDT=01
```

> ⚠️ **키 종류와 KIS_IS_PAPER를 맞추세요.**
> 모의투자 키 → `KIS_IS_PAPER=1`, 실전 키 → `KIS_IS_PAPER=0`.
> 안 맞으면 "토큰 발급 실패" 또는 401 에러가 납니다.

---

## 3단계 — 연결 검증 (핵심!)

```bash
pip install python-dotenv   # .env 자동 로드 (없으면 export로 대체)
python verify_connection.py
```

성공 시 이렇게 출력됩니다:

```
【1】 DART 재무제표 — 005930
  ✓ corp_code 매핑: 005930 → 00126380
  ✓ 재무제표 조회 성공 (2024년, 연결)
      매출액:      3,008,000 억원
      영업이익:      65,000 억원
      ...
【2】 KIS 시세 — 005930
  ✓ 현재가 조회: 삼성전자 71,000원 (+1.20%)
      시가총액: 4,200,000 억원
  ✓ 일봉 조회: 60일
【3】 통합 — 실데이터 기반 학술 팩터
  ✓ 펀더멘털 팩터 = 실제 DART 데이터
      GP/A (Novy-Marx): 0.31
      Altman Z-Score: 4.2
      ...
【결과 요약】
  ✓ 완전 실데이터 연동 성공 — 실투자 분석 가능 상태
```

다른 종목 검증: `python verify_connection.py --stock 000660`

---

## 4단계 — 전체 플랫폼 실행

```bash
docker compose down
docker compose up --build -d
docker compose logs -f backend   # 로그 확인
```

브라우저에서 `http://서버IP:3000` → 스크리너 탭 → 이제 **실제 재무·시세**로 스크리닝됩니다.

---

## 5단계 — KRX 장기 백테스트 적재 (한 번만)

KRX OpenAPI(https://openapi.krx.co.kr 발급 키)는 **날짜 기준 전종목** API라
백테스트용 역사 DB를 채우는 공급원으로 씁니다. 백테스트는 적재된 DB에서 읽습니다(젠포트식).

```bash
# .env에 KRX_API_KEY 입력 후:
python verify_connection.py                      # 【5】 KRX 도달성·키·필드 정합 확인
python -m src.data.krx_ingest --start 2015-01-01 # 10년 백필 ≈ 5,000콜 ≈ 50분
```

- **재개 가능**: 중단돼도 재실행하면 적재된 날짜는 건너뜀 (`--max-days N`으로 쿼터 분할 가능)
- **지수 포함**: KOSPI/KOSDAQ 지수가 함께 적재 → 벤치마크·마켓타이밍 실데이터화
- **수정종가**: 완료 시 등락률 체인으로 `adj_close` 자동 재구성 (분할·증자 점프 제거)
- **생존편향 보정**: 백테스터에서 `universe="all_asof"` → 시작일 당시 거래 종목(이후 상폐 포함)으로 평가
- 적재 후 `python verify_connection.py`의 【5】(c)에서 거래일·종목 수 확인

---

## 🔧 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `corp_code를 찾을 수 없음` | corpCode.xml 미다운로드 | DART_API_KEY 확인 → 최초 실행 시 자동 다운로드 |
| KIS `토큰 발급 실패` | 키 종류 ≠ IS_PAPER | 모의/실전 키와 `KIS_IS_PAPER` 일치 확인 |
| KIS `1분당 1회 초과` | 토큰 재발급 과다 | 1분 대기 (토큰은 24h 캐시됨) |
| 일봉 데이터 부족 | 모의투자 기간 제약 | 실전 키로 `KIS_IS_PAPER=0` (주문 안 하면 안전) |
| `펀더멘털 = mock` | DART 키 없음/조회 실패 | verify_connection.py로 DART 단계 점검 |
| 재무가 0원 | 해당 연도 미공시 | 자동으로 직전 연도 재시도함 |

---

## 🔒 보안 체크리스트

```bash
# .gitignore 확인 (반드시 포함)
grep -E "^\.env$" .gitignore || echo ".env" >> .gitignore
grep "corp_code_cache.json" .gitignore || echo "src/data/corp_code_cache.json" >> .gitignore
```

- `.env`는 **절대 git 커밋 금지** (`.env.example`만 커밋)
- API 키를 채팅·이슈·로그에 노출 금지
- 실계좌(`KIS_IS_PAPER=0`)는 주문 코드가 **실제 자금을 거래**합니다. 데이터 조회만 할 거면 주문 함수를 호출하지 마세요.

---

## 📊 mock → 실데이터 전환 요약

| 설정 | 펀더멘털 | 시세/지표 |
|---|---|---|
| 키 없음 | mock | mock |
| DART만 | **실데이터** | mock |
| KIS만 (`USE_MOCK=0`) | mock | **실데이터** |
| 둘 다 | **실데이터** | **실데이터** |

`verify_connection.py`가 현재 어느 상태인지 항상 알려줍니다.

---

## 🚀 Google Cloud 배포 + 백테스터 실데이터 전환

GCP에서 실데이터로 돌릴 때, **백테스터의 어떤 기능이 mock→실데이터로 바뀌는지** 정리합니다.
(화면 상단 데이터 출처 배너가 실시간으로 현재 상태를 보여줍니다.)

### GCP 배포 절차 (요약)

```bash
# 1. Compute Engine VM (e2-small 이상) 또는 Cloud Run
# 2. 코드 배포 후 .env 작성 (위 2단계 참고)
# 3. 환경변수만 실데이터로 전환:
export KIS_USE_MOCK=0          # 시세 실데이터 ON
export KIS_APP_KEY=...          # 실전 앱키
export KIS_APP_SECRET=...
export DART_API_KEY=...         # 재무 실데이터 ON

# 4. 검증
python verify_connection.py     # 실/mock 상태 출력
python -c "from src.data.ohlcv_loader import load_ohlcv_unified; \
  df=load_ohlcv_unified('005930','2024-01-01','2024-03-01',prefer='kis'); \
  print('KIS 실데이터 OK' if not df.empty else 'KIS 미연결')"
```

### 백테스터 기능별 실데이터 영향

| 기능 (Phase) | mock 동작 | 실데이터 동작 | 키 |
|---|---|---|---|
| 체결가 종가류·피벗 (P0·P1) | OHLC mock | **실제 OHLC 기반** | KIS |
| TWAP/VWAP (P1) | (O+H+L+C)/4 근사 | 분봉 연결 시 정밀 | KIS 분봉 |
| 매도/매수 정밀화 (P2·P3) | 동작 (가격만 mock) | **실제 가격 기반** | KIS |
| **팩터가중** (P3) | composite_score 균일 → 무효 | **종목별 점수 차등 → 비중 차등** | DART |
| 종목선택 업종 (P4) | 업종 매핑 정상 | 동일 (매핑은 코드 내장) | — |
| **벤치마크 KOSPI** (P5) | 합성 지수 (~연 +20%) | **실제 코스피 지수** | KIS |

### 실데이터에서 비로소 의미 있어지는 것 (중요)

mock에서는 "동작은 하지만 의미가 제한적"인 기능이 있습니다. 실데이터 전환 시 자동 해소:

1. **팩터가중** — mock은 모든 종목 composite_score가 동일(79.21)이라 동일가중으로 폴백.
   DART 재무가 들어오면 종목마다 점수가 달라져 **고점수 종목에 비중이 실제로 쏠립니다.**
2. **벤치마크 대비** — mock 코스피는 합성 곡선. KIS 지수 데이터가 들어오면
   **실제 코스피 대비 초과수익(α)·베타(β)가 진짜 의미를 갖습니다.**
3. **당일시초가 체결** — mock은 시초가≈종가라 종가 체결과 유사.
   실데이터는 시가/종가가 달라 **체결가 선택이 수익률에 실제 영향**.

### 코스피 지수 데이터 소스 (벤치마크용)

`_compute_benchmark`는 "KOSPI"/"^KS11" 티커로 지수를 조회합니다.
KIS는 업종/지수 시세 API(`FHKUP03500100` 등)를 제공하므로, `_kis_ohlcv_df`에
지수 코드 분기를 추가하면 실제 코스피가 연결됩니다. (현재는 mock 합성 지수로 폴백)
