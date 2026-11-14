/**
 * 한 메뉴 안의 모드(하위 주소) — ADR 006 §7 "새 기능은 새 화면이 아니라 기존 모듈 안에 자리를 잡는다".
 * 같은 모듈의 화면들이 이 목록 하나를 쓴다(전환 줄의 순서와 이름이 화면마다 어긋나지 않게).
 */
export type Mode = { href: string; label: string };

/** 백테스트 — 일봉 조건식(포트폴리오 · 실행 기록 · 수익률) | 분봉 규칙(모의 체결 · 원 단위 · 관문 일곱). 엔진과 결과의 정의는 따로다. */
export const BACKTEST_MODES: readonly Mode[] = [
  { href: "/backtest", label: "일봉 조건식" },
  { href: "/backtest/intraday", label: "분봉 규칙" },
];

/** 내 계좌 — 계좌·주문(연결한 증권 계좌 · 주문 경로) | 매매일지(자기 체결 내역 파일의 관측 — 계좌를 연결하지 않아도 쓴다). */
export const ACCOUNT_MODES: readonly Mode[] = [
  { href: "/my-account", label: "계좌·주문" },
  { href: "/my-account/journal", label: "매매일지" },
];
