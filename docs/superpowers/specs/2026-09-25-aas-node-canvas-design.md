# BI · AAS 노드 캔버스 — 포트폴리오를 노드-링크 그래프로 설계·분석한다

작성 2026-09-25 · 결정 기록 `docs/decisions/adr-002-aas-node-canvas.md` · 기록 `docs/HISTORY.md` 의 BI 항목

## 1. 왜

사용자는 AAS(Allocation Studio, `/allocation`)를 10단계 마법사가 아니라 **ComfyUI 같은
노드-링크 다이어그램**으로 쓰려 한다 — 포트폴리오를 설계하고 분석하는 공간.

## 2. 사용자가 정한 것

| 결정 | 답 |
|---|---|
| 마법사 | **AAS 의 모든 작업·툴을 노드 환경으로 바꾼다** |
| 실행 | **백엔드 DAG 실행기** |
| 첫 노드 세트 | **핵심 사슬**, 이후 확장 |
| 저장 | **JSON 내보내기/불러오기** — 불러오면 **바로 노드-링크 조합이 뜬다**. 서버 역량이 커지면 백엔드 저장 |

해석: 마법사는 **도구가 노드로 옮겨지는 만큼** 걷는다. 한 번에 지우면 아직 노드가 없는
도구(스트레스·타이밍·실행 등)가 **소리 없이 사라진다**(CLAUDE.md §4 침묵 금지의 화면판).

## 3. 감사가 찾은 것 (실측, 2026-09-25)

- AAS = 게이트(`app/allocation/page.tsx`) + 10단계(`widgets/allocation/AllocationProvider.tsx`
  `STAGES`), 741줄 컨텍스트. 핵심 계산은 뭉친 `POST /api/v1/allocation/analyze`
  (`allocation_routes.run_analyze`) — 수익률 → 믿음(`build_belief`) → 최적화(`optimize`) →
  제약(`constrained_solve`) → 리스크(`_risk_contribution_report`·`_enb_report`) → 부가 패널.
  정책 백테스트는 `POST /allocation/backtest` → `walk_forward`.
- `run_analyze` 는 ★분석 파이프라인의 단일 출처★다 — 재현 엔드포인트가 그대로 부르고, 문서가
  *"같은 산수를 두 곳에 두면 반드시 갈라진다"* 고 적었다. **노드도 사본을 만들지 않는다.**
- `reactflow ^11.11.4` 설치됨, 쓰는 곳은 백테스트 탭 `features/strategy-builder` 뿐(저장 없음).
- 백엔드 DAG 패턴 `src/engine/dag_runner.py`(networkx 순환 검증 → 위상 정렬 → 레지스트리).
  스키마는 단일 종목 신호 전용이고 `_generate_gbm` 합성 경로가 있다 → **패턴만 쓰고 새로 만든다.**
- E2E 계약: `.aas-*`·`.as-*` 에 스펙 약 37개. ADR-001 번들 예산(`/allocation` 첫 로드 129 kB).

## 4. 설계

### 4.1 파일 포맷 (내보내기·불러오기의 단일 계약)

```json
{"format": "project-alpha.portfolio-graph", "version": 1,
 "meta": {"name": "…", "exported_at": "ISO-8601"},
 "nodes": [{"id": "n1", "type": "universe", "params": {…}, "position": {"x": 0, "y": 0}}],
 "edges": [{"id": "e1", "source": "n1", "source_port": "universe",
            "target": "n2", "target_port": "universe"}]}
```

- **파라미터·위치만** 담는다. 실행 결과는 담지 않는다 — 결과는 다시 실행해서 얻는다(재현).
- 백엔드 저장이 생겨도 같은 포맷을 DB 에 넣는다(포맷이 계약, 저장소는 교체 가능).
- `format`/`version` 이 다르면 **거부 + 사유**. 모르는 노드 타입·포트는 **버리지 않는다** —
  캔버스에 빨간 "미상 노드" + 사유로 뜨고 실행은 그 노드와 하류를 `blocked` 로 둔다.

### 4.2 포트 타입

`Universe` · `Returns` · `Belief` · `Views` · `Weights` · `RiskReport` · `BacktestResult`.
연결은 **출력 타입 == 입력 타입**일 때만. 입력 포트는 필수/선택이 선언돼 있다.

### 4.3 핵심 사슬 노드 (MVP)

| 노드 | 입력 | 출력 | 감싸는 함수 (사본 없음) |
|---|---|---|---|
| `universe` | — | Universe | 파라미터: 종목·현재 비중·벤치마크 |
| `returns` | Universe | Returns | `_load_clean_returns`(lookback·as_of, mock 게이트) |
| `views` | — | Views | BL 뷰 목록(`AllocationView` 검증) |
| `estimate` | Returns | Belief | `build_belief`(조건부 μ/Σ·검증 관문) |
| `optimizer` | Returns · Belief · Views(선택) | Weights | `optimize` + (제약 시) `constrained_solve` |
| `risk` | Weights | RiskReport | `_risk_contribution_report` · `_enb_report` |
| `backtest` | Returns · Weights | BacktestResult | `walk_forward`(Weights 가 정책을 나른다) |

Weights 는 가중치와 함께 **정책**(모델·δ·τ·뷰·제약)을 나른다 — 백테스트가 같은 정책을 시점
밖으로 재현하려면 가중치 숫자가 아니라 정책이 필요하다(`/backtest` 와 같은 뜻).

### 4.4 실행기

- `src/engine/portfolio_graph.py`(순수): 포맷 검증 · 포트 타입 검사 · 순환 거부 · 위상 정렬 ·
  레지스트리 · 노드별 결과 `{status: ok|blocked|failed, outputs, provenance, reason}`.
  실패한 노드의 하류는 `blocked` + *"상류 X 가 실패"* — 기본값으로 계속 돌지 않는다.
- `src/api/allocation_graph_nodes.py`: 위 표의 노드 처리기(`allocation_pipeline` 과 같은 층).
- 라우트 `src/api/allocation_graph_routes.py`: `GET …/graph/node-types`(팔레트의 단일 출처) ·
  `POST …/graph/validate` · `POST …/graph/run`.
- **provenance**: 노드마다 데이터 등급(E1 픽스처=mock 합성 / E3 실 과거), 쓴 절단일, 제외 종목,
  미상 사유. 가중치는 `perf_label` 과 같은 규칙(mock 게이트가 유일한 판정 기준).

### 4.5 캔버스 (프런트)

- `/allocation` 이 캔버스다. FSD: `entities/portfolio-graph`(타입·API·포맷 파서) ·
  `features/portfolio-graph-io`(내보내기·불러오기) · `widgets/portfolio-graph`(reactflow 캔버스·
  팔레트·인스펙터·결과 패널).
- 팔레트는 `node-types` 응답으로 그린다. 포트 색 = 타입. 타입이 안 맞는 연결은 캔버스가 거부.
- 실행 → 노드마다 상태 배지(ok·blocked·failed + 사유)와 데이터 등급 배지.
- 불러오기: 파일 선택·드래그앤드롭 → 파싱 → **즉시** 노드·링크·위치 복원 → `validate` 결과를
  노드별로 표시. 작업 중 상태는 sessionStorage(편의용, 신뢰 저장 아님).
- E2E 계약 클래스 `.pg-*`.

### 4.6 마법사 퇴역 순서

- BI4: 핵심 사슬이 대신하는 단계(Construct·Thesis·Optimize 의 계산, Explain 의 리스크 기여)를
  캔버스로 옮기고 그 화면·스펙을 **같은 커밋에서** 교체. 아직 노드가 없는 도구는 캔버스의
  "아직 노드화 안 된 도구" 목록으로 링크한다. 그 도구들이 기존 세션(`AllocationProvider`)에서
  포트폴리오를 읽으므로 **캔버스 → 세션 다리**(실행한 유니버스·가중치를 같은 세션 키에 쓴다)가
  필요한지 BI4 감사에서 확정한다.
- 이후: BJ 스트레스·시나리오·국면 → BK 스크리너·알파·타이밍·슬리브 → BL 실행계획·저널 →
  마법사·컨텍스트 완전 제거 → (서버 역량 확보 후) 백엔드 저장·ResearchRun 재현.

## 5. 검증

- 골든: 기본 사슬 그래프의 가중치·리스크 기여·ENB == 같은 입력의 `run_analyze` 응답(바이트
  수준 동일 값), 백테스트 노드 == `/allocation/backtest`.
- 짝: 상류 실패 → 하류 blocked(그리고 성공 그래프는 전부 ok) · 타입 불일치 거부(맞으면 통과) ·
  순환 거부 · 운영 모드(mock 불가)에서 합성 수익률 0 → `returns` failed + 사유.
- 변이 배터리 · 전체 게이트 · 브라우저 실물 E2E(추가·연결·실행·**내보내기→불러오기 왕복**·
  깨진 파일).

## 6. ★이 설계가 하지 않는 것★

최적화기·배분 정책 의미 변경 · 기존 백테스트 탭 DAG 변경 · 백엔드 그래프 저장 · 핵심 사슬
밖의 노드 · `/analyze` 의 부가 패널(프런티어·MC 클라우드·MC 분포)을 노드로 옮기기(이후 분석 노드).
