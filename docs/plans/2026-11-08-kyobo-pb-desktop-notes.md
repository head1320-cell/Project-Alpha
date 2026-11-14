# 교보증권 PB 업무 활용 — 데스크톱 실행 파일 · 교보증권 API/HTS 연동 조사 메모 (2026-11-08)

> **상태: 조사 메모. 결정·설계·승인 없음. 코드 변경 0.** 나중에 이 일을 다시 시작할 때 출발점으로 쓴다.
> 여기 적은 개수·파일 목록은 **2026-11-08 에 잰 값**이다. 코드가 진실이니 다시 시작할 때 §3 의 명령으로 다시 잰다.

## 1. 질문 (사용자, 2026-11-08)

"나중에 교보증권 PB 업무에 활용하려면 실행파일로 만들어 데스크앱으로 만들고, 교보증권 api, hts랑 현 소스코드 상으로 연동되게 가능한지."

답을 셋으로 나눈다: ① 데스크톱 실행 파일(§5) ② 교보증권 API·HTS 연동(§2~§4) ③ PB 업무에 쓰기 위한 전제(§6). ①은 기술 문제이고 만들 수 있다.
②는 **교보증권 API 의 형태가 미상**이라 답이 갈린다. ③은 회사가 답할 문제다.

## 2. 교보증권 API — ★있다: C/C++ 모듈 방식★ (2026-11-14 확인 · 세부 사양은 미상)

| 확인한 것 | 등급 |
|---|---|
| 웹 검색(2026-11-08)에서 교보증권 개발자 포털·API 문서를 찾지 못했다 | 관측 |
| 검색 결과 하나에 교보증권 사이트(`www.iprovest.com`)의 '오픈API · 오픈API사용신청' 메뉴가 보였다 | 관측(검색 요약) · 페이지는 열지 못함 |
| 이 세션의 네트워크에서 `www.iprovest.com` 은 DNS 실패(`ENOTFOUND`)로 열리지 않았다 | 관측 |
| 교보증권 Win.K(MTS)의 조건감시주문은 앱 안 기능이지 외부 프로그램용 API 가 아니다 | 검색 요약 |
| 비교: 한국투자증권(KIS Developers) · LS증권 · KB증권 · 메리츠증권은 앱 키 방식 REST(+WebSocket) API 를 공개한다. KB 는 2026-07 베타로 개인에게 열었다는 보도가 있다 | 검색 요약 · 미검증 |

**교보증권에 물어볼 것** (PB 라면 사내 디지털·IT 부서가 빠르다):
1. 외부 프로그램용 API 가 있나? 형태는 무엇인가 — REST/WebSocket 인가, Windows 전용 COM/OCX/DLL 인가(32비트만인가)?
2. 누가 신청하나 — 개인 고객 · 직원 · 법인(핀테크 제휴)? 직원이 고객 계좌에 쓸 수 있나?
3. 범위 — 시세(현재가·일봉·분봉) · 주문/정정/취소 · 잔고 · 체결 통보 · 국내/해외.
4. 모의투자 서버가 있나(이 저장소는 실계좌 전에 모의투자 검증이 필수 — CLAUDE.md §6).
5. 인증 방식 · 토큰 수명 · 호출 한도 · **오류 코드 문서**(이 저장소는 실패 종류를 코드로 가른다 — §3).
6. 약관상 프로그램 자동주문이 허용되나? 직원 업무 PC 에서 쓸 수 있나?

출처: [교보증권 사이트(열지 못함)](https://www.iprovest.com/index.jsp) · [KB증권 Open API](https://openapi.kbsec.com/intro) ·
[KB증권 개인 개방 보도(파이낸셜뉴스)](https://www.fnnews.com/news/202608041339192032) · [LS증권 통합 API](https://openapi.ls-sec.co.kr/intro) ·
[메리츠증권 Open API](https://github.com/meritz-securities) · [증권사 오픈API 경쟁 보도(뉴스투데이)](https://www.news2day.co.kr/article/20260901500312)

**후속 ①(2026-11-14 오전 — ★추론이 틀렸다★)** — 검색으로는 형태를 알 수 없었고(공개 개발자 포털·문서·사용 후기가 잡히지 않음 · 이 환경이 `www.iprovest.com` 을 막음), "개인용 REST 트레이딩 API 는 공개돼 있지 않을 가능성이 높다 · 구형 API 이거나 핀테크 연동 동의 메뉴일 수 있다"고 추론했다. ★REST 가 아닌 것은 맞았지만 '개인이 쓰는 API 가 없을 수 있다'는 쪽은 틀렸다★ — 아래 후속 ②.

**후속 ②(2026-11-14 — 관측)** — 사용자가 보낸 홈페이지 화면(`iprovest.com/cyber/serv…` · 2026-11-14 11:21 KST) — 옮겨 적음:

| 항목 | 화면에 적힌 것 |
|---|---|
| 이름 | 교보 OPEN HTS / OPEN API |
| 무엇인가 | "고객이 직접 제작한 투자전략 프로그램을 당사가 제공하는 모듈에 연결하여, 거래 등을 할 수 있도록 제공하는 서비스" |
| 가입 | 계좌 개설 뒤 'OPEN HTS/OPEN API 서비스 신청' → 사용할 API 에 대한 ★승인 처리 후★ 사용. 회사는 이용조건에 따라 신청을 승인 또는 거부할 수 있다 |
| 가능 상품 | 주식 · 선물 · 옵션 |
| 개발 언어 | C/C++ |
| 내려받기 | 'K Open API' |
| 신청 조건 | 위험선호형 투자자 · C/C++ 등으로 프로그래밍할 수 있는 고객 · 불법·유사 금융업(대여계좌 등)을 영위하지 않을 것 · 관련 상품 매매 경험 1년 이상 · 채무불이행자가 아닐 것 · 미성년자가 아닐 것(주식은 허용) · 신용정보조회 동의 |
| 해지 조건 | 내부 준칙에 어긋나는 불공정거래 · 6개월 이상 미거래 계좌 |

읽을 수 있는 것: ⑴ §4 의 길 가운데 ★둘째(모듈 + 내 PC 의 중계 프로그램)★가 해당한다 — 다만 화면에는 'C/C++ 모듈'까지만 있고 ★Windows 전용인지·32/64비트·함수 모양은 적혀 있지 않다(미상)★. ⑵ 모듈은 고객 자신의 PC 에서 고객 자신의 로그인으로 돈다 → §5 의 데스크톱 실행 파일이 본선이 된다(서버에 올린 서비스로는 이 모듈로 고객 주문을 낼 수 없다). ⑶ 서비스 정의가 "★고객이 직접 제작한★ 프로그램"이다 — 남이 만든 프로그램을 고객이 쓰는 것이 그 안인지는 이용조건 원문과 회사의 답이 필요하다([질문지](2026-11-14-company-questions.md) A12). ⑷ 가능 상품에 해외가 없다. ⑸ §2 의 질문 가운데 1·3 은 일부 풀렸고(형태 = C/C++ 모듈 · 상품 = 주식·선물·옵션) 2(직원)·4(모의투자)·5(한도·오류 코드)·6(자동주문·업무 PC)은 그대로 미상이다.

## 3. 지금 코드가 증권사에 묶인 모양 (2026-11-08 측정)

**연결 부품은 작다.** `src/execution/kis_client.py` 의 `KISClient` 가 하는 일: `place_order` · `cancel_order` · `get_balance` · `get_price` ·
`get_daily_ohlcv` · `get_minute_bars_today` · `get_minute_bars_dated` · `get_investor_daily`. 연습용 `MockKISClient` 도 같은 모양이다 —
★이름 붙은 인터페이스는 없지만 같은 모양의 클라이언트를 끼울 자리가 사실상 있다★. 진입점은 `get_kis_client(force_reload, *, account_id=None)` 하나.

**안전장치는 연결 부품 위에 있다.** 킬 스위치(`kill_switch.py`) · 위험 검사(`risk_gateway.py`) · 실행 모드(`order_executor.py` 의 SHADOW/PAPER/LIVE) ·
감사 기록(`audit_trail.py`) · 실계좌 관문(`live_gate_store.py`) · 계좌마다 실행기(`account_executors.py`). 증권사를 바꿔도 이 층은 그대로 쓴다.

**묶인 곳** — `kis_client` 를 가져다 쓰는 파일 30개:

- `src/api`: `account_order_routes.py` · `broker_account_routes.py` · `data_routes.py` · `stage13_routes.py`
- `src/data`(시세 수집): `extended_factors_store.py` · `kis_flows.py` · `krx_ingest.py` · `market_data.py` · `minute_bars.py` · `ohlcv_loader.py` · `price_quality.py`
- `src/domain`: `api_health.py` · `equity_observation.py` · `failure_streak.py` · `kill_action.py` · `kis_failure.py`
- `src/engine`: `screener.py` · `trading_engine.py`
- `src/execution`: `account_executors.py` · `api_failure_probe.py` · `broker_accounts.py` · `equity_history.py` · `kill_switch.py` · `kis_client.py` · `order_executor.py` · `risk_monitor.py`
- 그 밖: `src/data_sync.py` · `src/kis_backtest_engine.py` · `src/kis_order_executor.py` · `src/startup/lifecycle.py`

**KIS 응답 칸(`rt_cd` · `msg_cd` · `ODNO` · `output1/2` …)을 `kis_client.py` 밖에서 읽는 파일 10개** — 증권사를 바꾸려면 먼저 여기를
"증권사와 무관한 모양"으로 바꿔야 한다: `src/api/stage13_routes.py` · `src/domain/{api_health, breaker_change_gate, cost_provenance, failure_streak,
kis_failure, kis_rt_cd}.py` · `src/execution/{api_failure_probe, audit_trail, order_executor}.py`. 실패 분류(`kis_rt_cd`·`kis_failure`·
`breaker_change_gate`)는 KIS 코드표에 기대고, 그 표 자체도 아직 비어 있다(`docs/specs/kis-rt-cd-evidence.json` — 로드맵 '미상').

**계좌 저장 형식도 KIS 모양이다.** `broker_accounts` 표: `app_key_enc` · `app_secret_enc` · `account_no_enc`(8자리) · `account_prdt`(2자리) ·
`is_paper`. ★증권사 칸이 없다★.

다시 재는 명령:

```bash
grep -rlE 'kis_client|get_kis_client' src --include=*.py | sort
grep -rlE "rt_cd|msg_cd|ODNO|stck_prpr|output1|output2" src --include=*.py | grep -v kis_client.py | sort
grep -n "class BrokerAccount" -A 25 src/database.py
```

**보호 규칙(CLAUDE.md §6 — 최우선):** 기본 `dry_run=True` · `TradingEngine` 6중 안전장치 우회 금지 · `OrderExecutor` 를 `trading_engine.py` 밖에서
직접 생성 금지 · "KIS 연동은 `get_kis_client()` 단일 경로" · 실계좌 전 모의투자 검증 · mock 은 `mock_allowed()` 하나로만. ★진입점을 '증권사를 고르는
단일 경로'로 넓히는 일은 이 규칙을 고치는 일이라 읽기 전용 감사 → 설계 → 승인이 먼저다.★

## 4. 연동 길 — 교보 API 형태에 따라

| 형태 | 할 일 | 크기 |
|---|---|---|
| **REST(앱 키·시크릿 · KIS/LS/KB 와 비슷)** | ① 응답을 증권사와 무관한 모양으로(§3 의 10개 파일이 KIS 칸 대신 그 모양을 읽게) ② `broker_accounts` 에 증권사 칸 + 교보 계좌 형식 ③ 같은 모양의 교보 클라이언트(+ 그 mock) ④ 진입점이 계좌의 증권사를 보고 고르게(단일 경로 유지) ⑤ 교보 오류 코드표 — 문서에 없는 코드는 '미상'으로(지어내지 않음) ⑥ 시세 수집(`src/data`)을 교보 시세로 돌릴지, 다른 출처를 쓸지 결정 ⑦ 모의투자로 왕복 관측 | 중간 |
| **Windows 전용 COM/OCX/DLL(키움 OpenAPI+ · 대신 CYBOS 같은 방식)** | 위 ①~⑦ + Windows 에서만 도는 중계 프로그램(흔히 32비트 Python)을 따로 두고 백엔드와 로컬 소켓으로 잇는다. 앱도 Windows 전용이 된다 | 큼 · 깨지기 쉬움 |
| ↳ ★2026-11-14: 교보증권이 해당하는 길★ | 화면에 적힌 것은 'C/C++ 모듈'까지다. 중계 프로그램이 C/C++ 로 모듈에 붙고 백엔드와 로컬로 잇는 모양이 된다 — 운영체제·비트·함수 모양은 'K Open API' 꾸러미의 문서를 읽어야 정해진다(읽기 전용 감사 먼저) | 미상 → 문서를 읽은 뒤 |
| **HTS 화면 직접 조작(매크로·화면 읽기)** | ★하지 않는다★ — 약관 위반 소지 · 화면이 바뀌면 깨짐 · 주문이 이 저장소의 안전장치 밖으로 나감 | — |

## 5. 데스크톱 실행 파일 — 만들 수 있다

지금 구조: Python 백엔드(FastAPI · `uvicorn --workers 1` · 캐시·쿼터가 프로세스 안에 있음) + Next.js 14 화면(라우트 핸들러 중계
`frontend/src/app/api/backend/[...path]/route.ts`) + SQLite. 모두 한 PC 안에서 돈다. 저장소에 패키징 코드는 아직 없다(electron·tauri·pyinstaller 0).

**추천: Electron 껍데기 + 백엔드 실행 파일 동봉**

1. 백엔드를 PyInstaller 로 실행 파일 하나로(numpy · scipy · pandas · statsmodels · cryptography 포함 — 수백 MB).
2. 화면은 `next build` 의 standalone 출력(지금 `next.config` 에 `output: "standalone"` 이 없다 — 더해야 함) — Electron 이 가진 Node 로 띄운다.
3. Electron 주 프로세스가 켜질 때 빈 포트 둘을 골라 백엔드를 띄우고, 화면 서버를 `BACKEND_URL=http://127.0.0.1:<포트>` 로 띄운 뒤 창을 연다.
   ★중계가 `BACKEND_URL` 을 요청마다 실행 시점에 읽으므로 "API 주소를 빌드 타임에 박지 말 것" 규칙과 맞는다★. 끌 때 둘 다 내린다.
4. electron-builder 로 Windows 설치 파일.

**손볼 곳:** DB·기록 위치를 사용자 폴더로 · 키(`BROKER_CRED_KEY` · `ANTHROPIC_API_KEY` · 데이터 키)를 `.env` 대신 OS 자격 증명 저장소(Windows 자격 증명 관리자)로 ·
코드 서명(없으면 SmartScreen 경고) · 업데이트 방법 · 첫 실행 준비(`POST /api/v1/live/init-schema` 같은 운영자 준비를 앱이 대신) · 개발 기본값
`KIS_USE_MOCK=1` 을 배포판에서 어떻게 둘지.

**대안:** Tauri(가볍지만 화면 중계에 Node 가 필요해 결국 Node 도 동봉) · 사내 서버에 웹으로 두고 브라우저로 접속(가장 단순 — 사내 승인이 전제).

## 6. PB 업무에 쓰기 위한 전제 — ★회사가 답할 문제★ (아래는 일반론 · 확인 필요)

- **업무 PC 반입:** 증권사 업무 PC 는 망분리된 경우가 많아 외부 프로그램 설치나 외부 API 호출이 막힐 수 있다. IT·보안 승인이 필요할 수 있다.
- **고객 정보와 AI:** 고객 정보를 외부 AI(Claude API)로 보내는 것은 개인정보·신용정보 규정 문제다. 승인 전에는 AI 기능을 끈 배포판이 안전하다
  (이 앱은 키가 없으면 AI 가 사유와 함께 "보여 줄 수 없어요" 로 멈춘다 — 이미 있는 동작).
- **고객 계좌 주문:** PB 가 고객 계좌로 주문을 내는 것은 주문 대리·일임 규정 사항이다. 이 저장소의 실계좌 관문(`live_gate`)은 기본 막힘이다.
- **고객에게 보이는 화면·링크:** 유통 관문(`src/domain/distribution_gate.py`) 뒤에 있고 인가 선언 전에는 열리지 않는다(`tests/test_distribution_blocked.py`).

## 7. 추천 순서

1. **주문 연동 없이 리서치·제안 도구로 먼저** — 캔버스 설계 · 백테스트 · 고객 관리 · 고객 한 장 인쇄. 주문은 지금처럼 HTS 에서 사람이 낸다. 교보 API 없이 된다.
2. 데스크톱 실행 파일(§5) — 1 과 함께 갈 수 있다. 앱 코드 변경은 작다.
3. 교보에 §2 의 질문을 묻고, 회사 승인(§6)을 확인한다.
4. 답이 나오면 증권사 경계 **읽기 전용 감사** → 설계 → 승인 → §4 의 길.

## 8. 다시 시작할 때

- [ ] §2 질문의 답(특히 API 형태 · 모의투자 서버 · 오류 코드 문서)
- [ ] §6 의 회사 답
- [ ] §3 의 명령으로 다시 잼(개수가 바뀌었을 것이다)
- [ ] 범위를 고름: 데스크톱만 / 데스크톱 + 교보 시세 / 데스크톱 + 교보 주문
- [ ] 주문까지 간다면 CLAUDE.md §6 진입점 규칙 변경을 승인받음

## 하지 않은 것

교보증권 페이지를 직접 읽지 못했다(네트워크 막힘 — 그래서 §2 는 전부 미상) · 패키징 시험 빌드 · 교보 API 왕복 · 회사 규정 확인 · 코드 변경.
