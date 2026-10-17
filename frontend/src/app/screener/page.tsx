"use client";

import TerminalScreener from "@/widgets/screener/TerminalScreener";

/** 종목 찾기 — 유니버스 고르기는 위젯의 조건 절 안으로 옮겼다(BU2 · 한 화면 한 일). */
export default function ScreenerPage() {
  return (
    <div className="tpage-fade">
      <TerminalScreener />
    </div>
  );
}
