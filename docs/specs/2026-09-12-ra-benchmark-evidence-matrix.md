# 국내 로보어드바이저 4사 — ★증거 매트릭스★ (출처와 등급을 함께)

> 조회 2026-09-12 · 도구는 `WebSearch` 한 개 · ★`SRC_VERIFIED` 0건★(사유는 §0-2)
> 규칙: [`2026-09-12-ra-product-rules.md`](2026-09-12-ra-product-rules.md) §2 ·
> 원문 요구: [`../Project_Alpha_RA_Product_Master_Prompt.md`](../Project_Alpha_RA_Product_Master_Prompt.md)
>
> ★이 문서는 4사를 평가하지 않는다.★ *무엇을 만들었다고 말하는가* 를 모으고, 그
> 말의 **근거가 어디까지인지**를 적는다. 우열·추천·투자 판단은 여기 없다.

## 0. 읽기 전에

### 0-1. ★"AI Quantec" 과 "Quantit" 은 이름이 닮은 다른 회사다★

원문이 영문으로 적어 놔서 한국어로 옮기면 **반드시 한 번은 헷갈린다**.

| 원문 표기 | 한국어 상호 | 도메인 | 대표 제품 |
|---|---|---|---|
| AI Quantec | **콴텍**(에이아이콴텍) | `quantec.co.kr` | Q-Engine · Q-X |
| Quantit | **퀀팃**(퀀팃투자자문) | `quantit.io` · `qt-advisor.com` | Finter · 플랜잇 |

★조인하거나 훑어보는 사람이 섞을 위험이 크므로, 이 문서는 **한국어 상호**를
1차 표기로 쓴다.★ (같은 이유로 `scenario_packs_store.py` 가 `market` 대신
`market_shock` 이라는 이름을 쓴 선례가 있다.)

### 0-2. ★`SRC_VERIFIED` 가 0건인 이유는 회사가 아니라 이 환경이다★

`WebFetch` 가 **모든 외부 도메인**에서 `EGRESS_BLOCKED` 다 — 4사 공식 사이트도,
코스콤도, 인용한 언론사도, 대조군으로 시도한 `en.wikipedia.org` 까지. 실측했다.
`WebSearch` 만 동작하므로 아래 근거는 전부 **검색 엔진이 요약한 것**이고,
★URL 을 열어 원문과 대조하지 못했다★ ⇒ 최대 등급이 `SRC_INFERRED` 다.

사용자 환경에서 §5 의 URL 을 열면 그대로 `SRC_VERIFIED` 로 승급된다.

---

## 1. 솔루션퀀트 (SolutionQuant)

| 축 | 내용 | 등급 | 근거 |
|---|---|---|---|
| 사업모델 | 투자자문업·투자일임업. 2021-06-23 설립 | `SRC_INFERRED` | [saramin 기업정보](https://www.saramin.co.kr/zf_user/company-info/view/csn/Y252bWhTTCtKRjFmRUhDQVhvVDllUT09) · [rocketpunch](https://www.rocketpunch.com/companies/solrusyeonkweonteu) |
| 사업모델 | 대체데이터 플랫폼 **에이셀테크놀로지스의 자회사**(그 위는 FiscalNote) | `SRC_INFERRED` | [aiceltech.com](https://www.aiceltech.com/kr) · [블로그](https://www.blog.solutionquant.com/solq-221101/) |
| 자산배분 | 정형/비정형·퍼블릭/프라이빗 데이터를 자산에 **맵핑 → 클렌징 → 최적화 → 테스팅**. `100% Systematic Hedge Fund` 지향 | `SRC_INFERRED` | [블로그 운용 노하우](https://www.blog.solutionquant.com/solq-221101/) |
| 자산배분 | 우주산업성장지수: 사업보고서·애널리스트 리포트·뉴스 **텍스트 키워드 분석**으로 종목 선별 → 스코어링으로 비중 | `SRC_INFERRED` | [블로그 ETF](https://www.blog.solutionquant.com/etf-221103/) |
| 리스크 구조 | ★구체적 집중 규칙★ 편입 **10종목 제한** · 업스트림에 **80% 집중** · 업스트림 1위 **25%**, 차순위 3개 각 **15%** | `SRC_INFERRED` | [블로그 ETF](https://www.blog.solutionquant.com/etf-221103/) |
| UX | 공개된 리테일 앱 UX 를 확인하지 못함 | `SRC_UNKNOWN` | 검색 결과가 채용·기업정보·블로그에 몰려 있다 |
| 알고리즘 상세 | 스코어링 함수·팩터 정의·리밸런싱 주기 | `SRC_UNKNOWN` | 영업비밀. ★추측해 적지 않는다★ |

★우리에게 쓸모 있는 것★ — "분산이 아니라 **집중을 규칙으로 명시**한다" 는 발상.
등급별 상한(25/15/…)은 이 저장소의 `Constraints.group_caps_pct` 로 **이미 표현
가능한 모양**이다([갭 분석](2026-09-12-ra-gap-analysis.md) §3).

---

## 2. 콴텍 / AI QUANTEC

| 축 | 내용 | 등급 | 근거 |
|---|---|---|---|
| 사업모델 | 초개인화 자산관리 솔루션 **Q-Engine** 주축 | `SRC_INFERRED` | [공식 회사소개](https://www.quantec.co.kr/about/company)(열지 못함) · [thevc](https://thevc.kr/quantec) |
| 사업모델 | ★B2B2C★ NH투자증권과 `AI 어드바이저 솔루션` **구독 계약**, 비대면 투자상담 업무에 접목 | `SRC_INFERRED` | [ZDNet 2026-05-21](https://zdnet.co.kr/view/?no=20260521110105) · [내외일보](https://www.naewoeilbo.com/news/articleView.html?idxno=2353071) |
| 리스크 구조 | 핵심 위험관리 모듈 **Q-X** 가 **24시간 시장을 모니터링** | `SRC_INFERRED` | 위 보도 |
| 리스크 구조 | *"스트레스 시 방어자산으로 익스포저를 동적 이동"* (원문 프롬프트의 서술) | `SRC_UNKNOWN` | ★검색으로 확인하지 못했다.★ 확인된 것은 "24시간 모니터링" 까지다 |
| UX | 어드바이저가 고객 **보유 종목을 입력** → AI 정밀 진단 → **진단보고서** 생성 → 상담에 사용 | `SRC_INFERRED` | [ZDNet 2026-05-21](https://zdnet.co.kr/view/?no=20260521110105) |
| 자산배분 | 배분 방법론(모델·제약·리밸런싱 규칙) | `SRC_UNKNOWN` | 영업비밀 |
| 규모 | AUM·테스트베드 통과 알고리즘 수 | `SRC_UNKNOWN` | ★검색했으나 못 찾았다★ — 질의가 핀트 수치를 물고 왔다. 없는 것이 아니라 **우리가 못 찾은 것** |

★우리에게 쓸모 있는 것★ — ⑴ **보유 종목 진단**이 독립 제품이 된다는 점(우리는
기계가 있는데 표면이 없다) ⑵ 리스크 감시가 **상시 미들웨어**라는 점(우리는
탐지기가 있는데 **도는 데몬이 없다**).

**★"동적 방어자산 이동" 은 원문의 서술이지 확인된 사실이 아니다.★** 우리 설계가
그것을 모방한다면 근거는 *공개 확인된 콴텍의 동작*이 아니라 **우리 자신의 국면
로직**(`regime_adaptive_allocator` · `macro_overlay`)이다. 섞어 적지 않는다.

---

## 3. 퀀팃 / Quantit (플랜잇 · Plantit)

| 축 | 내용 | 등급 | 근거 |
|---|---|---|---|
| 사업모델 | **퀀팃투자자문 = 금융위 등록 투자자문사**, 데이터·알고리즘 기반 자문 | `SRC_INFERRED` | [qt-advisor.com](https://qt-advisor.com/en)(열지 못함) |
| 사업모델 | 증권·디지털자산 운용 핀테크. AI 모델 제작·검증·운용 플랫폼 **Finter** 보유 | `SRC_INFERRED` | [quantit.io](https://www.quantit.io/) · [quantit.ai](https://quantit.ai/ko) |
| 파이프라인 | ★분석 → 백테스트 → 전략 구현 → 자동매매 **전 과정을 연결**★, B2B-SaaS + 개인용 | `SRC_INFERRED` | 위 |
| 자산배분 | **플랜잇**: 개인 맞춤 포트폴리오 자동 구성·관리, **IRP 연금 자동 운용**, 시장 상황 기반 **동적 리밸런싱**, 일 단위 자산 조정 | `SRC_INFERRED` | [qt-advisor.com/en](https://qt-advisor.com/en) · [about](https://www.qt-advisor.com/en/about)(둘 다 열지 못함) |
| 리스크 구조 | 구체적 리스크 규칙 | `SRC_UNKNOWN` | 확인 못 함 |
| UX | 앱 화면·설명 UX | `SRC_UNKNOWN` | 확인 못 함 |
| ★TDF 글라이드패스★ | 원문은 "TDF 형 글라이드패스 디리스킹" 을 퀀팃의 강점으로 적었다 | ★`SRC_UNKNOWN`★ | **퀀팃과 글라이드패스를 잇는 근거를 찾지 못했다.** 검색은 TDF·글라이드패스의 **일반 설명**(자산운용사 TDF 상품, 학술 논문)만 돌려줬다 |

### ★원문의 한 항목을 확인하지 못했다★

"Quantit = TDF 글라이드패스" 는 이 조회에서 **뒷받침되지 않았다**. 세 가지 중
하나일 수 있고, 우리는 어느 것인지 모른다:

1. 사실인데 이 환경의 검색이 못 찾았다(공식 사이트가 막혀 있다)
2. 퀀팃의 IRP 자동운용을 TDF 로 일반화한 서술이다
3. 다른 회사의 기능이 섞였다

★그래서 글라이드패스는 "퀀팃이 한다" 가 아니라 **"연금 계좌에 필요한 기능"** 으로
로드맵에 넣는다.★ 기능의 타당성은 벤치마크와 무관하게 성립한다(TDF·글라이드패스
자체는 국내 연금 시장의 표준 개념이다 — `SRC_INFERRED`,
[키움투자자산운용 TDF 안내](https://www.kiwoomam.com/pension/KI0301000000M)).

---

## 4. 핀트 / 디셈버앤컴퍼니 (fint)

★4사 중 공개 근거가 가장 두껍다.★

| 축 | 내용 | 등급 | 근거 |
|---|---|---|---|
| 사업모델 | 2019-04 국내 최초 AI 투자일임 서비스. 투자자문·투자일임 라이선스 보유 | `SRC_INFERRED` | [나무위키 Fint](https://namu.wiki/w/Fint) · [공식](https://www.fint.co.kr/) |
| 사업모델 | AI 투자엔진 **ISAAC**(종목 선정·비중 결정·**매일** 포트폴리오 산출) + 운용 플랫폼 **PREFACE**(데이터 클렌징·연산·1:1 맞춤 포트폴리오 운용) | `SRC_INFERRED` | [스포츠경향 2026-08-20](https://sports.khan.co.kr/article/202608200105003/) |
| 사업모델 | RA 투자일임 시장 점유율 **72%**(2026-03 기준) · 총 AUM **5,200억원**(출시 7주년 시점) | `SRC_INFERRED` | 위 · [스포츠경향 2026-05-01](https://sports.khan.co.kr/article/202605010428003/) |
| 자산배분 | ★멀티계좌 허브★ 일반 + **연금저축 · IRP · ISA**(절세계좌 삼총사) | `SRC_INFERRED` | [스포츠경향 2026-05-28](https://sports.khan.co.kr/article/202505280056003) · [뉴스탭](https://www.newstap.co.kr/news/articleView.html?idxno=304897) |
| 자산배분 | 2021 개인연금저축(RA 일임 최초) · 2024-04 IRP 일임 · IRP 자문 1월 · ISA 자문 3월 · 연금 AUM 1,000억 돌파 | `SRC_INFERRED` ★연도 주의★ | [뉴스탭](https://www.newstap.co.kr/news/articleView.html?idxno=304897) · [연금 AUM](https://v.daum.net/v/20251202100815401) |
| UX | ★"오늘 내 자산이 움직인 이유"★ — AI 가 일일 자산 변동을 **요약**해 주는 투자화면 개편 | `SRC_INFERRED` | [벤처스퀘어](https://www.venturesquare.net/1109741) · [스포츠경향 2026-09-01](https://sports.khan.co.kr/article/202609010256003/) |
| 유통 | ★핀트 셀렉션★ 2026-06-22 출시. **외부 운용사·자문사의 전략**을 앱에서 직접 고르고 구독. 핀트의 AI 가 **수익률·안정성·운용 일관성**을 검증한 전략만 노출 | `SRC_INFERRED` | [핀테크경제신문](https://www.fintechtimes.co.kr/news/article.html?no=56876) |
| 알고리즘 상세 | ISAAC 의 모델·팩터·최적화 방식 | `SRC_UNKNOWN` | 영업비밀 |

★연도 표기 주의★ — 인용한 기사가 `올해 1월`/`3월` 이라고만 적어 **어느 해인지
확정할 수 없다**. 확정 전까지 "1월 IRP 자문 · 3월 ISA 자문(연도 미상)" 으로 둔다.
★미상을 연도로 지어내지 않는다.★

★우리에게 쓸모 있는 것★ — ⑴ **계좌 유형이 제품의 축**이라는 점(세제 혜택이
계좌마다 다르므로 배분 제약도 다르다) ⑵ 일일 변동 설명이 **요약 UX** 로 성립한다는
점 ⑶ 외부 전략 유통에는 **평가 기준(수익률·안정성·일관성)이 먼저** 있어야 한다는 점.

---

## 5. 코스콤 RA 테스트베드 — ★수익률 4종 중 하나의 정의★

| 내용 | 등급 | 근거 |
|---|---|---|
| 2016 도입. RA 알고리즘 심사·검증 공식 인프라 | `SRC_INFERRED` | [코스콤 심사단계](https://www.koscom.co.kr/portal/main/contents.do?menuNo=200590)(열지 못함) · [헤럴드경제](https://biz.heraldcorp.com/article/10663214) |
| 점검 항목: **분산투자 구조 · 투자자 성향 분석 반영 · 보안(해킹 방지) 체계** + 실환경 안정성 | `SRC_INFERRED` | [한국금융신문](https://www.fntimes.com/html/view.php?ud=202601271020542657179ad43907_18) |
| **사후운용심사** 2023-06 도입 — 상용화의 필수 절차 | `SRC_INFERRED` | [코스콤 공지](https://www.koscom.co.kr/portal/bbs/B0000064/view.do?nttId=29493) |

★통과율 수치가 출처마다 다르다★ — 한쪽은 *"누적 906개 참여 / 725개 통과, 약
80%"*, 다른 쪽은 *"23차까지 752개 중 639개"*, 또 다른 쪽은 *"운영 10년 합격률
85%"*. 기준 시점과 분모(참여 vs 심사완료)가 달라 보이지만 **확인하지 못했다**.
⇒ ★하나를 골라 적지 않는다.★ 통과율은 `SRC_UNKNOWN` 이고, 셋 다 URL 을 남긴다
([파이낸셜뉴스](https://www.fnnews.com/news/202504271833411275) · 위 둘).

**우리에게 의미** — 테스트베드 수익률은 **표준 심사 환경의 모의 운용**이다.
백테스트도 페이퍼도 실계좌도 아니다. [제품 규칙](2026-09-12-ra-product-rules.md) §3
의 4종 분리가 여기서 나온다.

---

## 6. ★승급 대기★ — 사용자 환경에서 열면 `SRC_VERIFIED` 가 되는 URL

열고 → 인용문을 그대로 옮기고 → 조회일을 적으면 등급이 오른다. ★요약을 옮기지 말고
원문 문장을 옮긴다.★

| 우선 | URL | 무엇을 확정하나 |
|---|---|---|
| 1 | `https://www.qt-advisor.com/en/about` | 퀀팃의 글라이드패스·적립식 여부 (§3 의 미확인 항목) |
| 2 | `https://www.quantec.co.kr/about/company` | Q-X 의 **방어자산 이동** 서술 유무 (§2 의 미확인 항목) |
| 3 | `https://www.koscom.co.kr/portal/main/contents.do?menuNo=200590` | 심사 단계·기간·기준, 통과율의 정확한 분모 |
| 4 | `https://solutionquant.com/` | 자문/일임 등록 상태와 상품 라인업 |
| 5 | `https://www.fint.co.kr/` | 계좌 유형별 지원 범위(일임 vs 자문) |
| 6 | `https://www.fintechtimes.co.kr/news/article.html?no=56876` | 핀트 셀렉션의 평가 기준 원문 |

---

## ★이 매트릭스가 주장하지 않는 것★

- **4사를 재현할 수 있다고 말하지 않는다.** 공개 정보로 알 수 있는 것은 *무엇을
  만들었다고 말하는가* 이지 *어떻게 만들었는가* 가 아니다. 알고리즘 칸이 전부
  `SRC_UNKNOWN` 인 것은 조사 실패가 아니라 ★정상적인 판정★이다.
- **우열을 매기지 않는다.** 성과·수익률·상품 비교는 여기 없다.
- **`SRC_INFERRED` 를 사실로 쓰지 않는다.** 설계 문서가 이 표를 인용할 때는
  등급을 함께 옮긴다.
- **없는 것을 "그 회사가 안 한다" 로 읽지 않는다.** `SRC_UNKNOWN` 은 **우리가
  모른다**는 뜻이다(CLAUDE.md §4, `미상 ≠ 0`).
