# 조사 — 적용할 만한 공개 저장소(금융 · 웹디자인)와 2025년 이후 논문의 개념 (2026-11-16)

> **상태: 조사 문서(코드 0줄).** 받은 말 — "깃허브에서 본 프로젝트에 적용할 수 있는 최근 트렌드 · star 많은 파이낸스 · 웹디자인(레이아웃 · 폰트 · UI/UX) 레포를 전부 찾아 조사하고 추천.
> 2025년 이후 통계 · 투자 논문에 등장하는 개념(이중하강, e-means)도." 받은 결정(같은 날 · 질문 둘): **문서로 저장** · **e-값 순차 검정 · 분봉 결과의 봉 차트 · 트레이더 작업 공간** +
> "답변에 나온 각 개념을 적용하고, 작업하다가 더 좋은 방법이 있으면 적용". 적용 계획은 [구현 계획](../superpowers/plans/2026-11-16-evidence-and-trader-ux.md)이 갖는다.
>
> **등급과 한계 — 먼저 읽을 것**
> - 스타 수는 ★집계 사이트의 값★이다(2026-09~11 · 사이트마다 시점이 다르다). GitHub 에서 직접 확인하지 못했다 — 이 작업 세션의 GitHub 접근이 이 저장소로 한정돼 있다. 표의 수는 '대략'으로만 읽는다.
> - 논문은 ★초록과 2차 요약 수준★이다. 본문을 읽지 않았다. 구현에 쓰는 정의는 그 조각을 시작할 때 출처를 다시 읽어 구현 계획 문서에 못 박는다.
> - 라이선스 가운데 '(기억)'이라고 적은 것은 검색으로 확인하지 못한 것이다 — 들이기 전에 저장소의 LICENSE 를 읽는다.
> - 하위 에이전트는 쓰지 않았다(웹 검색 34회를 직접 했다).

## 0. 한 줄 요약

스타가 가장 많은 금융 저장소는 LLM 매매 에이전트이고 ★이 제품에는 들이지 않는다★("도구는 규칙 · 조건을 추천하지 않는다"와 충돌 · 장기 평가에서 우위가 사라진다는 보고).
쓸 만한 것은 스타는 적어도 빈자리를 메우는 것들이다 — 분할 창 · 긴 표의 가상화 · 인터페이스 지침 감사. 개념 쪽에서 새로 들일 것은 **e-값(언제 들여다봐도 유효한 검정)** 하나이고,
나머지 개념은 ★저장소에 이미 같은 뜻의 장치가 있어★ 그것을 분봉 쪽에 잇거나 문서 · 가드로 못 박는 일이다(§5).

## 1. 저장소의 지금 구성 (관측 2026-11-16 — 추천의 바탕)

| 층 | 있는 것 | 없는 것 |
|---|---|---|
| 프론트 | Next 16 · React 19 · `@xyflow/react` 12 · `recharts` 2.15(차트 파일 안에만 — ADR 004) · Tailwind 3.4 · Radix · `pretendard` · JetBrains Mono | 봉 차트 부품 · 분할 창 · 표 가상화 |
| 서버(통계) | `deflated_sharpe.py`(PSR · DSR) · `domain/multiplicity.py`(다중검정) · `conformal.py`(split conformal — 교환가능성 가정) · `research_preregistration.py` · `research_power.py` · `capability.py`(능력 사다리) · `causal_graph.py`(Granger — 구조적 인과가 아니라고 적는다) | 순차(언제든 유효한) 검정 |
| LLM | `services/narrative/claude_client.py` · `services/canvas_assist/service.py` 두 곳에서만 | 계산 · 결정 계층에는 없다(그 사실을 거는 시험은 아직 없다 — G7) |

## 2. 금융 저장소

### 2.1 도입 후보로 본 것

| 저장소 | 스타(대략) | 쓰임 | 받은 결정 |
|---|---|---|---|
| `koreainvestment/open-trading-api` | 미확인 | 한국투자증권 공식 샘플. 모의투자 주문(W5d)의 주문 코드 · 엔드포인트를 확인할 1차 자료 | ★고르지 않으셨다 — 하지 않는다★(기록만) |
| `tradingview/lightweight-charts` | 1.1만 | 봉 차트 | ★들이지 않는다 — §3.4 의 정정★ |
| `skfolio` | 미확인(2026-11 에도 릴리스) | scikit-learn 방식의 포트폴리오 라이브러리. 최적화기는 두고 교차검증(CPCV 등)의 대조 구현으로 | 이번 묶음에 없다(후보로 남긴다) |

### 2.2 참고만 하는 것

| 저장소 | 스타(대략) | 참고할 점 | 들이지 않는 까닭 |
|---|---|---|---|
| TradingAgents | 11만 | 에이전트의 추론을 화면에 보이는 방식 | LLM 이 매매 판단을 낸다 — "도구는 추천하지 않는다"와 충돌 |
| ai-hedge-fund | 6.4만 | 같음 | 같음 |
| Vibe-Trading(2026-04 공개 · MIT) | 3.5만 | 백테스터를 MCP 서버로 여는 방식 | 같음 |
| OpenBB | 7.4만 | 데이터 제공자를 갈아 끼우는 구조(로드맵 5단계 '증권사 중립 설계') | AGPL(기억) — 코드를 옮기지 않는다 |
| freqtrade | 5.6만 | 전략의 앞보기를 자동으로 찾는 명령(기억) | 암호화폐 봇 · GPL(기억) |
| qlib (+ RD-Agent) | 5만 (1.5만) | 시점 고정 데이터 구조(정정공시 이력 설계) | 자동 팩터 탐색은 시행 기록 없이는 쓰지 않는다 |
| nautilus_trader | 3만 | 백테스트와 실거래가 같은 코드를 쓰는 구조 · 틱 · 호가(로드맵 7단계) | 엔진을 갈아타지 않는다 |
| Kronos(AAAI 2026) | 1.5만+ | 봉 데이터 파운데이션 모델 | §5 의 ⑥ — 수익률 예측 근거가 약하다 |
| ghostfolio(AGPL) · wealthfolio | 각 0.9만 | 증권사 파일 가져오기 화면(매매일지의 열 맞추기) | AGPL 은 코드를 옮기지 않는다 |
| panda_quantflow · OpenAlgo Flow | 미확인 | 노드 기반 퀀트 캔버스(우리 캔버스의 비교 대상 — 후자는 같은 React Flow) | 참고 |

### 2.3 LLM 매매 에이전트를 들이지 않는 근거

FINSABER(Li · Kim · Cucuringu · Ma, arXiv 2505.07078 · KDD 2026 게재 승인)는 20년 · 100종목 이상으로 넓혀 다시 재면 ★기존에 보고된 LLM 전략의 우위가 크게 줄어든다★고 보고한다 —
강세장에서는 지나치게 조심하고 약세장에서는 지나치게 공격적이었다. 좁은 기간 · 적은 종목의 평가가 생존 편향 · 앞보기 · 자료 엿보기로 부풀려진다는 지적이다(초록 수준 — 본문 미독).

## 3. 웹디자인 저장소

### 3.1 이미 쓰고 있는 것

`@xyflow/react`(3.8만) · Radix(1.9만) · Pretendard(한글 UI 의 사실상 표준이라는 2026년 기사 · OFL) · `impeccable` 스킬(9만) · `ui-ux-pro-max` · `design-taste-frontend`. ★글꼴은 바꿀 이유를 찾지 못했다.★

### 3.2 후보

| 저장소 | 스타(대략) | 쓰임 | 계획 |
|---|---|---|---|
| `react-resizable-panels`(MIT) | 0.5만 | 분할 창의 크기 조절 · 키보드로 움직이는 구분선 | **G5** |
| `dockview`(MIT) | 0.3만 | 탭 도킹 · 창 띄우기 · 배치 저장 — 다중 모니터를 쓰는 전업 트레이더의 작업 공간 | **G6**(설계 문서 → 승인) |
| TanStack Table · Virtual | 미확인 | 긴 표(체결 · 시행 목록)의 가상화. 화면을 직접 그리는 방식이라 CSS 클래스 계약을 지킬 수 있다 | 후보로 남긴다 |
| `vercel-labs/agent-skills` | 3.3만 | 코드를 인터페이스 지침에 비춰 파일 · 줄 단위로 지적하는 감사 스킬 | 후보로 남긴다(남이 쓴 지시문이라 들이기 전에 읽는다) |
| React Aria(Adobe) | 미확인 | 시각 입력 칸 — 직접 구성 편집기의 시각 칸이 브라우저 지역 설정에 따라 달라지는 지금 한계 | 후보로 남긴다 |
| `uPlot` | 미확인 | 선이 아주 많아질 때의 대안(약 22KB) | ADR 004 가 `<canvas>` 렌더를 기각했다 — 다시 볼 조건이 생길 때만 |

### 3.3 스타는 많지만 지금 들이지 않는 것

shadcn/ui(12.5만) · Ant Design(10만) · MUI(9.9만) — 이미 Radix 위에 같은 방식으로 쓰고 있다. Tailwind 4 — 지금 3.4 이고 CSS 클래스가 E2E 계약이라 이주는 따로 정할 큰일이다.
Recharts 3 — ADR 004 가 재 보고 되돌린 기록 그대로(2.15 유지). `hallmark`(4~5만) · `emilkowalski/skills`(5.4만) — 같은 계열의 디자인 스킬을 이미 셋 쓰고 있다.

### 3.4 ★정정 — 봉 차트와 `lightweight-charts`★

조사 답변에서 분봉 결과의 봉 차트에 `lightweight-charts` 를 권했다. ★틀린 추천이다.★ ADR 004(2026-11-10 · 받은 결정)가 이미 막아 둔 길이다 —
§2.6 "다른 차트 라이브러리로 갈아타지 않는다" · §3 "`<canvas>` 렌더는 DOM 을 보는 E2E 계약 · 읽는 줄 접근성과 어긋난다". 결정 기록을 읽지 않고 권한 것이다.
→ 봉 차트는 ★손그림 SVG★로 한다(ADR 004 §2.3 의 '라이브러리가 못 그리는 문법' · 표식 규격 `shared/ui/chart/chartSpec.ts` · 읽는 줄 + 표 쌍둥이 + 키보드). 분봉 규칙은 하루 안에서 끝나므로
그림의 단위가 하루(최대 381봉)이고, 그 크기는 SVG 로 충분하다. 여러 날을 이어 확대 · 이동하는 차트가 필요해지면(틱 · 호가 단계) ADR 004 §4 의 '다시 볼 때'로 올린다.

## 4. 'e-means' 에 대하여 — ★정정 (2026-11-16 · 받은 말: "e-value 가 아니라 메타 연구진이 만든 e-means")★

처음 조사에서 그 이름의 논문을 찾지 못해 **e-값(e-value)** 으로 읽었다. ★틀린 읽기였다★ — 그 논문은 조사 엿새 전에 나와 있었다(내 검색의 실수 · HISTORY).
e-값은 따로 받은 결정('e-값 순차 검정')이라 그대로 진행한다(G1). 두 개념은 답하는 물음이 다르다 — e-값은 "결과를 여러 번 들여다봐도 유효한 검정", e-means 는 "군집 중심을 더 빨리 찾는 법"이다.

**e-means 가 무엇인가**(원 논문의 초록 · 저자 블로그 · ★기준 구현을 직접 읽은 것★ — faiss-cpu 1.16.0 의 `faiss/contrib/e_means`):
- 메타 FAIR 의 k-평균(Lloyd) 대체 군집화 — Bessa · Mazaré · Szilvasy · Touvron · Picard · Douze · Jégou, arXiv 2611.09501(2026-11). ★예측 모형이 아니다★ — 점들을 k 개 묶음으로 나누는 알고리즘이다.
- 작은 묶음(mini-batch)마다 군집별로 할당된 개수와 합의 지수이동평균을 갱신하고(구현의 식: `N ← γN + αn` · `c ← c + (αn / N)(s/n − c)` · `α = 1 − γ`), 걸음 크기 α 는 코사인 일정으로 줄인다.
  묶음 크기와 첫 걸음 크기는 n · k · 회차 수 T 의 경험 법칙(README 의 식 (1)~(3) — 큰 임베딩 자료에 맞춘 것)으로 정한다. 쓰이지 않는 군집은 큰 군집을 쪼개 되살린다(d ≤ 2 면 끈다). 마지막 회차의 할당으로 단순 평균을 다시 낸다.
- 저자의 주장: Lloyd 가 25회차에 닿는 손실을 1.4~2.6 회차에 넘는다 · GPU 시간 10~45배. 실험 규모는 큰 임베딩(최대 100억 개 · 군집 1,600만). README 는 n × k > 10¹⁰ 이면 GPU 를 권한다.

**이 저장소의 크기에서 재 본 것**(2026-11-16 · CPU 1스레드 · 기준 구현 그대로 · 30개 씨앗 · `synthetic_mechanism` — 매크로 축은 mock 게이트의 합성 자료 E0 다):

| 자료(n · 차원 · k) | e-means 기본(5회차) | e-means 25회차 | Lloyd 한 번 시작 | Lloyd 10번 시작 | 시간(ms) e-means 기본 · Lloyd 10번 |
|---|---|---|---|---|---|
| 매크로 축 kr 60개월(60 · 2 · 4) | +1.8% (90%: +18.4%) | 0.0% (+1.4%) | +14.5% (+28.8%) | 0.0% (+1.4%) | 16 · 3 |
| 매크로 축 us 60개월 | +4.2% (+11.3%) | 0.0% (+8.0%) | +10.0% (+14.2%) | +0.4% (+2.9%) | 14 · 3 |
| 매크로 축 kr 120개월(120 · 2 · 4) | +0.7% (+1.2%) | +0.2% (+0.9%) | +26.3% (+129.8%) | +0.7% (+1.2%) | 27 · 5 |
| 합성: 뚜렷이 뭉친 60점 | 0.0% (+246.6%) | 0.0% (0.0%) | +1.8% (+285.4%) | 0.0% (0.0%) | 16 · 4 |

칸의 값 = 군집 목적함수(제곱거리 합)가 가장 좋은 답(Lloyd · k-means++ · 100번 시작)보다 큰 정도의 중앙값(괄호는 90% 분위). 큰 규모(합성 가우스 덩어리 · 씨앗 하나 · Lloyd 는 무작위 시작 25회 반복):

| n · 차원 · k | e-means 기본 시간 ÷ Lloyd 시간 | e-means 손실 − Lloyd 손실 |
|---|---|---|
| 60 · 2 · 4 · 6,000 · 2 · 4 | 9~20배 느리다 | 0% |
| 60,000 · 16 · 64 | 같다 | +8.2% |
| 200,000 · 32 · 256 | 4.6배 빠르다 | +7.5% |
| 400,000 · 32 · 1,024 | 8.1배 빠르다 | −19.4% |

**읽은 것**: e-means 의 이점은 ★큰 n · k 에서 같은 손실을 빨리★ 다(위 표에서도 n · k 가 커질 때만 나타난다). 매크로 국면 모형의 군집 팔은 월 60~120점 · 2차원 · 군집 4개라 그 이점이 없다 — 더 느리고, 여러 번 시작한 Lloyd 보다 낫지 않다.
그리고 재 보다가 ★다른 문제★를 찾았다: 지금 군집 팔(`regime_ensemble._cluster_probs` — GMM · `random_state=0` · `n_init=3`)이 내는 '지금 국면'이 **난수 씨앗에 따라 바뀐다**(같은 mock 자료 · 씨앗 30개):
kr 60개월은 씨앗 0 이 Goldilocks 를 내지만 30개 가운데 24개는 Reflation · us 60개월은 네 국면에 10 · 7 · 11 · 2 로 흩어진다(가장 많은 답도 37%). 이 팔은 배분에 쓰이지 않는 진단 전용이지만(`USAGE_NOTE`), 화면이 보이는 답이 씨앗 하나의 우연이다.
→ 매크로에는 e-means 를 넣지 않는다(결정 2026-11-16 '가' · 2026-11-19 다시 확인 — 구현 계획 문서 §E1). 군집 팔은 씨앗 안정성과 k-평균 팔(M1)로 갔고, e-means 는 n · k 가 큰 자리인 하루 유형(T1)에 쓴다.

## 5. 2025년 이후 논문의 개념 — 요지 · 이미 있는 것 · 적용

| # | 개념 | 요지(초록 수준) | 저장소에 이미 있는 것 | 적용 |
|---|---|---|---|---|
| ① | **e-값 · e-과정** | 귀무가설 아래 기댓값이 1 이하인 음이 아닌 통계량. 곱해 가는 과정이 기준(1/α)을 ★어느 시점에든★ 넘으면 기각해도 오류율이 지켜진다 — 결과를 볼 때마다 검정해도 된다. 금융 적용: Wang · Wang · Ziegel "E-backtesting"(Management Science 2025) — 모형 없이 VaR · ES 를 사후검증 | 없다(DSR 은 표본이 고정된 검정이다) | **G1**(분봉 판정의 '순차 증거') · **G2**(괴리 보고 — 가정한 슬리피지의 검정) |
| ② | **이중하강 · '복잡성의 미덕' 논쟁** | 매개변수가 표본보다 많은 모형이 수익률 예측에 낫다는 주장(Kelly · Malamud · Zhou, JF 2024)에 2025년 비판 셋 — Nagel(짧은 학습 창의 결과를 복잡성 덕으로 볼 수 없다) · Buncic(절편 0 제약과 집계 방식이 만든 결과) · Cartea · Jin · Shi(예측 변수의 측정 오차가 이득을 제한). 연준 FEDS 2025-089 는 환율에서 '크게 제한적' | `capability.py` — 관측 48 · 모수 32 라는 이유로 4상태 HMM 을 기각한 능력 사다리 | **G3**(직접 구성 규칙의 조정 가능한 값 수 대비 거래 수를 판정의 사실로) |
| ③ | **LLM 앞보기 편향** | 모델이 평가 구간의 미래를 이미 학습했을 수 있다. 그 시점까지의 글로만 학습한 모델(ChronoBERT · ChronoGPT — He · Lv · Manela · Wu, 2025) | 캔버스 AI 보조는 서버 검사를 통과한 사실만 풀어 쓴다(예측에 쓰지 않는다) | **G7**(LLM 이 계산 · 결정 계층에 없다는 시험 + 제품 규칙 한 줄) |
| ④ | **가설 찍어내기(HARKing 의 산업화)** | 신호 3만 개를 캐 기준을 넘은 96개에 LLM 으로 이론을 붙여 논문 288편(Novy-Marx · Velikov, NBER 2025 → JEL 2026) | 분봉 시행 기록(`intraday_trials`) · `research_preregistration.py`(매크로) | **G3**(실행 전에 적는 가설 — 처음 적은 것만 남는다) |
| ⑤ | **인과 팩터 · '팩터 신기루'** | 통계 검정은 통과하나 인과 구조가 틀린 팩터 모형(López de Prado · Zoonekynd, 2025 — 일곱 단계 규약). 다중검정 보정은 모형 설정 오류를 잡지 못한다 | `causal_graph.py` 의 정직 라벨 · 다중검정 | **G3**(가설 칸이 묻는 것이 '기제' — 왜 통한다고 보는가) |
| ⑥ | **시계열 파운데이션 모델** | 학습 없이 바로 쓰면 일간 초과수익의 방향 적중이 50% 근처(Rahimikia · Ni · Wang, 2025). 금융 자료로 따로 학습하면 낫다는 것은 저자 주장. 2026-06 의 벤치마크는 예측 오차만 쟀다(매매 성과 없음) | — | ★코드로 옮기지 않는다★(§6) |
| ⑦ | **시계열용 등각 예측** | 수익률은 교환가능성이 깨진다 → 목표 오차율을 온라인으로 고치는 ACI(Gibbs · Candès) · 단일 자산 VaR 의 TCP(Aich 등, 2025) | `conformal.py`(교환가능성 가정) · `regime_forecast.py`(실현 적중률을 잰다) | **G7**(ACI 함수 + 쓰는 두 곳의 가정 표기 · 결정 불변) |
| ⑧ | **비용 반영 효율 경계** | 거래비용을 뺀 수익으로 전략을 견주고 비용을 목적식에 넣는다(Jensen · Kelly · Malamud · Pedersen, RFS 게재 예정) | 분봉 판정의 비용 관문 둘 · `allocation_backtest.simulate_walk_forward(cost_bps)` | **G7**(비용 뒤 값이 없는 비교 표면을 감사해 '비용 전 값'이라고 적는다) |
| ⑨ | **UPSA 수축** | 공분산의 새 비선형 수축 — 저분산 주성분을 버리지 않고 표본외 성과로 다시 단다(Kelly · Malamud · Pourmohammadi · Trojani, NBER w32004 · 2025 개정) | `robust_opt.py` · `estimator_evidence.py` | ★코드로 옮기지 않는다★(§6) |

덧붙임 — 장중 돌파(ORB): 저자 쪽 논문(Zarattini · Aziz · Barbon, 2023~2025 — 저자들에게 상업적 이해가 있다)은 수익을 보고하나, 2026년의 한 재현(개인 블로그 · 동료 심사 아님)은 비용을 빼면 0 에 가깝다고 적었다.
분봉 화면이 비용 전 · 후와 손익분기를 함께 보이는 지금 설계와 같은 방향이다. 통계적 점프 모형(Shu · Yu · Mulvey)은 2024년 글이라 이 표에 넣지 않았다.

## 6. 코드로 옮기지 않는 개념과 ★들이는 조건★

시계열 파운데이션 모델(⑥) · UPSA(⑨) · 통계적 점프 모형은 예측 · 추정 모형을 키우는 일이다. CLAUDE.md §5 의 순서("데이터 무결성을 고치기 전에 모델을 키우지 말고")와 §3("최적화기 의미 · 국면-배분 정책 변경은 별도 승인 사항")에 걸린다.
이 환경은 실데이터가 없어, 들여도 `synthetic_mechanism` 이상을 말할 수 없다. **금지가 아니라 순서다.** 들일 때 지나야 하는 것:

1. 데이터 출처 `E3`(실 과거) 이상 — 합성 위의 숫자로는 들이지 않는다.
2. 표본외 · 비용 뒤의 값으로 ★단순 기준★(직전 값 · 과거 평균 · 변동성만 맞춘 것)과 견준다.
3. 시행 횟수 보정(DSR)과 순차 증거(e-값 — G1).
4. 사전학습 모형이면 ★학습 자료의 끝 < 평가의 시작★(시점 정합 관문 — ③).
5. 배분 결정 경로에 닿으면 별도 승인.

## 7. 출처

금융 저장소: [9 Finance Repos Compared (2026)](https://ultralab.tw/en/blog/ai-finance-github-projects-2026) · [Top Fintech Open Source Projects](https://gittrend.io/best/fintech) ·
[awesome-open-source-trading](https://github.com/jinliyl/awesome-open-source-trading) · [microsoft/qlib](https://github.com/microsoft/qlib) · [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) ·
[Kronos (arXiv 2508.02739)](https://arxiv.org/html/2508.02739v1) · [Lightweight Charts v5](https://www.tradingview.com/blog/en/tradingview-lightweight-charts-version-5-50837) ·
[koreainvestment/open-trading-api](https://github.com/koreainvestment/open-trading-api) · [skfolio (arXiv 2507.04176)](https://arxiv.org/abs/2507.04176) ·
[panda_quantflow](https://www.sourcepulse.org/projects/11951791) · [Ghostfolio vs Wealthfolio](https://openalternative.co/compare/ghostfolio/vs/wealthfolio)

웹디자인 저장소: [Best React UI Component Libraries in 2026](https://prismic.io/blog/react-component-libraries) · [dockview](https://dockview.dev/docs/overview/introduction) ·
[react-resizable-panels](https://bestofjs.org/projects/react-resizable-panels) · [orioncactus/pretendard](https://github.com/orioncactus/pretendard) ·
[web-design-guidelines](https://skills.sh/vercel-labs/agent-skills/web-design-guidelines) · [Best Design System Repositories (2026)](https://gittrend.io/best/design-system) ·
[xyflow star history](https://www.star-history.com/xyflow/xyflow/) · [TanStack Charts — Compare Libraries](https://tanstack.com/charts/latest/docs/comparison)

논문: [Buncic — Simplified](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5239006) · [BFI WP 2025-104](https://bfi.uchicago.edu/wp-content/uploads/2025/08/BFI_WP_2025-104.pdf) ·
[FEDS 2025-089](https://www.federalreserve.gov/econres/feds/files/2025089pap.pdf) · [E-backtesting](https://pubsonline.informs.org/doi/fpi/10.1287/mnsc.2023.01659) ·
[Anytime-valid testing with e-values](https://arxiv.org/pdf/2606.00878) · [Causality and Factor Investing: A Primer](https://papers.ssrn.com/abstract=5277078) ·
[Chronologically Consistent LLMs](https://arxiv.org/abs/2502.21206v3) · [FINSABER](https://arxiv.org/html/2505.07078v5) · [AI-Powered (Finance) Scholarship](https://www.nber.org/papers/w33363) ·
[TSFM 영점 평가 (arXiv 2511.18578)](https://arxiv.org/pdf/2511.18578) · [TSFM 벤치마크 (arXiv 2606.27100)](https://arxiv.org/pdf/2606.27100) ·
[Temporal Conformal Prediction](https://arxiv.org/html/2507.05470v6) · [Implementable Efficient Frontier](https://papers.ssrn.com/abstract=4187217) ·
[Universal Portfolio Shrinkage](https://econpapers.repec.org/paper/nbrnberwo/32004.htm) · [Can Day Trading Really Be Profitable?](https://papers.ssrn.com/abstract=4416622) ·
[ORB 재현(개인 블로그)](https://www.mql5.com/en/blogs/post/776235)

e-means(§4 · 2026-11-16 정정): [arXiv 2611.09501](https://arxiv.org/abs/2611.09501) · [저자 블로그](https://e-means.github.io/) · [faiss contrib/e_means](https://github.com/facebookresearch/faiss/tree/main/contrib/e_means) ·
[Small Is Not Dead — 되살리기 조건의 후속 글(arXiv 2611.18238)](https://arxiv.org/abs/2611.18238) · [MarkTechPost 소개](https://www.marktechpost.com/2026/11/10/meta-fair-e-means-k-means-faiss/)

## 8. 이 문서가 주장하지 않는 것

어떤 저장소나 개념이 이 제품의 수익 · 예측력을 높인다는 말이 아니다. 스타 수는 관심의 크기이지 품질이나 쓰임의 증거가 아니다. 논문의 요지는 저자의 주장을 옮긴 것이고 이 저장소에서 재현한 것이 없다.
