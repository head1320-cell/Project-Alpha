/**
 * 내 계좌의 판 배치 — 판 넷 · 처음 배치 둘 (G6 2a-2 · 설계 §4.2 · §5.4 · 계획 §10)
 * ==========================================================================
 * 판 이름 = 판 안 절 제목(주문 제출 · 최근 주문 · 잔고 · 규칙 가동) — 설계 §4.2 의 '주문 · 주문 목록'으로 두면 같은 판에 이름이 둘 선다(계획 §10.1).
 * 넷 모두 titled(판 안 첫 절이 판 이름을 제목으로 단다 — 같은 제목은 하나만). 주문 제출은 닫지 않는다(옮기기만 — 설계 §1 '내 계좌의 안전').
 * 비상 정지 단추 · 모드 문장 · 합성 칩(문장 띠)과 주문 전송 경로는 판이 아니다 — 판 밖에 선다(MyAccountView).
 * 처음 배치의 이름은 쓰임의 묘사이고 도구가 고르거나 권하지 않는다. 처음 켤 때는 '주문'(주문 제출이 기본 배치와 같은 오른쪽 — 켜자마자 손에 익은 자리가 바뀌지 않게).
 * 최소 폭(판이 깨지지 않는 바닥 · 잰 값 2026-11-20 · 1920 × 1080 · 계획 §10.2a): 2a-1 · G5 와 같은 방법 — 판을 둘째 열에 혼자 두고 그 열을 16px 씩 줄여
 * 정해진 스크롤 틀 밖에서 판을 넘는 요소가 생기거나 판이 가로로 구르기 시작하는 폭 + 16. 판 내용은 가장 넓은 상태(실제 서버 · 계좌 · 가동 요청 · 끝까지 돈 가동 —
 * 주문 제출은 확인 줄을 연 채 · 규칙 가동은 요청 펼침 + 관제 + 가상 체결 펼침). 네 판 모두 글이 줄을 바꿔 좁아지므로 바닥이 낮다.
 * 새 열 폭(colNew 520 — 설계 값 · 잰 값 아님): 기본 배치의 주문 제출 폭(504)에 가까운 처음 놓을 자리. 처음 배치의 오른쪽 열도 같은 520.
 * 세 열의 최소 폭 합(가장 큰 셋 304 + 144 + 112 + 구분선 32 = 592)이 탭 보기의 가장 좁은 본문 폭(1280 창 → 1144)보다 작다 — 어떤 배치도 합쳐 보이지 않고
 * '배치' 메뉴가 폭으로 막는 일도 없다(순수 시험이 건다 · 그래서 끈 화면에서 판 폭을 따로 재지 않는다).
 */
import type { Layout, ScreenSpec } from "@/shared/ui/workspace/layout";

/** 탭 보기 문턱 — 분봉 화면(`widgets/intraday/splitPane.ts` 의 SPLIT_QUERY)과 같은 값. 위젯끼리 가져오지 않으려고 따로 두고 순수 시험이 같은지 건다. */
export const ACCOUNT_QUERY = "(min-width: 1280px) and (min-height: 800px)";

const L = (cols: Layout["cols"], closed: string[] = []): Layout => ({ v: 1, screen: "account", cols, closed });

export const ACCOUNT_WS: ScreenSpec = {
  screen: "account",
  panels: [
    { id: "order", name: "주문 제출", min: 112, closable: false, titled: true },      // 잰 값 — 96 에서 주문 금액 줄(.ma-amount-v · .ma-hint)이 16px 넘친다
    { id: "orders", name: "최근 주문", min: 96, closable: true, titled: true },       // 잰 값 — 80 에서 절 머리 · 거르기 칩이 6px 넘친다
    { id: "balance", name: "잔고", min: 144, closable: true, titled: true },         // 잰 값 — 128 에서 현금 · 평가 자산 줄이 8px 넘친다
    { id: "arming", name: "규칙 가동", min: 304, closable: true, titled: true },     // 잰 값 — 288 에서 관제 판(.ma-mon-live · .ma-mon-grid)이 4px 넘친다
  ],
  presets: [
    { id: "order", name: "주문", layout: L([
      { w: null, rows: [{ tabs: ["orders", "balance", "arming"], active: "orders" }] },
      { w: 520, rows: [{ tabs: ["order"], active: "order" }] },
    ]) },
    { id: "monitor", name: "관제", layout: L([
      { w: null, rows: [{ tabs: ["arming"], active: "arming" }] },
      { w: 520, rows: [{ tabs: ["orders"], active: "orders" }, { tabs: ["order", "balance"], active: "order", h: 0.5 }] },
    ]) },
  ],
  first: "order",
  colNew: 520,
};
