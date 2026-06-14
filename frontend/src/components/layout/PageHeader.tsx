// 페이지 헤더 — 랜딩 eyebrow + index + title + intro + status 모티프를 셸로 이식.
// 기존 .terminal-h1 재사용(새 타이틀 CSS 없음). children = 우측 정렬 컨트롤
// (예: Screener Universe select, Company 티커바). 프레젠테이션 전용.
import React from "react";

export interface PageHeaderProps {
  eyebrow: string;
  index: string;
  title: string;
  intro?: string;
  status?: string;
  children?: React.ReactNode;
}

export default function PageHeader({ eyebrow, index, title, intro, status, children }: PageHeaderProps) {
  return (
    <header className="tpage-head">
      <div className="tpage-head-top">
        <span className="t-eyebrow">{eyebrow}</span>
        <span style={{ display: "flex", gap: 16, alignItems: "baseline" }}>
          <span className="tpage-index">{index}</span>
          {status && (
            <span className="tpage-status"><span className="tpage-status-dot" />{status}</span>
          )}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
        <h1 className="terminal-h1" style={{ marginBottom: 0 }}>{title}</h1>
        {children}
      </div>
      {intro && <p className="tpage-intro">{intro}</p>}
    </header>
  );
}
