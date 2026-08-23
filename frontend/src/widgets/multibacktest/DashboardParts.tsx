"use client";
// Multi-Strategy 백테스트 대시보드 표시 컴포넌트 + 공용 스타일 상수.
// (app/admin/multi-backtest/page.tsx에서 분리, 내용 불변)

import type React from "react";

export function Section({ title, subtitle, icon: Icon, children }: {
  title: string; subtitle: string; icon: any; children: React.ReactNode;
}) {
  return (
    <section style={{
      background: "#0a0e27", border: "1px solid #1e2d4a",
      borderRadius: 10, marginBottom: 16, overflow: "hidden",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "14px 20px", borderBottom: "1px solid #1e2d4a",
      }}>
        <Icon size={14} color="#1200ff" />
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 13, fontWeight: 700, color: "#fff",
                         margin: 0, textTransform: "uppercase",
                         letterSpacing: "0.04em" }}>{title}</h2>
          <p style={{ fontSize: 10, color: "#6b7fa3", margin: 0, marginTop: 2 }}>
            {subtitle}
          </p>
        </div>
      </div>
      <div style={{ padding: "16px 20px" }}>{children}</div>
    </section>
  );
}

export function KPICard({ label, value, color, highlight }: {
  label: string; value: string; color: string; highlight?: boolean;
}) {
  return (
    <div style={{
      padding: "12px 14px",
      background: highlight
        ? `linear-gradient(135deg, ${color}15, ${color}05)`
        : "#0a0e27",
      border: `1px solid ${highlight ? color + "40" : "#1e2d4a"}`,
      borderRadius: 8,
    }}>
      <div style={{ fontSize: 9, color: "#6b7fa3", fontWeight: 600,
                      textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color, marginTop: 4,
                      fontFamily: "'Roboto Mono', monospace" }}>
        {value}
      </div>
    </div>
  );
}

export const headerStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  marginBottom: 20, paddingBottom: 16, borderBottom: "1px solid #1e2d4a",
};

export const btnStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 6,
  padding: "7px 14px", borderRadius: 4, fontSize: 11,
  fontWeight: 600, cursor: "pointer",
  background: "#0a0e27", color: "#a7c8ff",
  border: "1px solid #1e2d4a",
};

export const loadingStyle: React.CSSProperties = {
  minHeight: "100vh", background: "#060a1a",
  display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center",
  fontFamily: "'Inter', sans-serif",
};

