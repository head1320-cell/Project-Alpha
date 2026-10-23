"use client";

import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import Link from "next/link";

// ── PageHeader (PV style with breadcrumb) ────────────────────────────────────
interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumb?: { label: string; href?: string }[];
  actions?: React.ReactNode;
}
export function PageHeader({ title, subtitle, breadcrumb, actions }: PageHeaderProps) {
  return (
    <div className="pv-page-header">
      <div className="container-pv">
        {breadcrumb && (
          <div className="pv-breadcrumb">
            {breadcrumb.map((b, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                {b.href ? <Link href={b.href}>{b.label}</Link> : <span>{b.label}</span>}
                {i < breadcrumb.length - 1 && <ChevronRight size={11} />}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="pv-page-title">{title}</h1>
            {subtitle && <p className="pv-page-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      </div>
    </div>
  );
}

// ── PageContent ──────────────────────────────────────────────────────────────
export function PageContent({ children }: { children: React.ReactNode }) {
  return (
    <div className="container-pv py-6 px-3">
      {children}
    </div>
  );
}

// ── StatCard ────────────────────────────────────────────────────────────────
export function StatCard({
  label, value, sub, trend, size = "md",
}: {
  label: string;
  value: string | number;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  size?: "sm" | "md";
}) {
  const color = trend === "up" ? "var(--bs-success)" : trend === "down" ? "var(--bs-danger)" : "var(--bs-body-color)";
  const fontSize = size === "md" ? "1.25rem" : "1rem";
  return (
    <div className="card card-md">
      <div className="label mb-1.5">{label}</div>
      <div className="num" style={{ fontSize, fontWeight: 600, color, lineHeight: 1.2 }}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-[var(--bs-secondary-color)] mt-0.5">{sub}</div>}
    </div>
  );
}

// ── Tabs (PV horizontal underline tabs) ──────────────────────────────────────
interface TabsProps {
  tabs: string[];
  active: number;
  onChange: (i: number) => void;
}
export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="pv-tabs">
      {tabs.map((tab, i) => (
        <button
          key={tab}
          onClick={() => onChange(i)}
          className={clsx("pv-tab", { active: i === active })}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

// ── Spinner ──────────────────────────────────────────────────────────────────
export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ animation: "spin 0.7s linear infinite", color: "var(--bs-primary)" }}
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.2" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );
}

// ── Badge ────────────────────────────────────────────────────────────────────
export function Badge({
  children, variant = "blue",
}: {
  children: React.ReactNode;
  variant?: "green" | "red" | "amber" | "blue";
}) {
  const cls = {
    green: "badge badge-success",
    red:   "badge badge-danger",
    amber: "badge badge-warning",
    blue:  "badge badge-info",
  };
  return <span className={cls[variant]}>{children}</span>;
}

// ── Section ──────────────────────────────────────────────────────────────────
export function Section({
  title, children, action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="label">{title}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

// ── FormRow ───────────────────────────────────────────────────────────────────
export function FormRow({ children, cols = 4 }: { children: React.ReactNode; cols?: number }) {
  const grid = {
    1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3",
    4: "grid-cols-4", 5: "grid-cols-5", 6: "grid-cols-6",
  };
  return (
    <div className={clsx("grid gap-3", grid[cols as keyof typeof grid] ?? "grid-cols-4")}>
      {children}
    </div>
  );
}

// ── Field ─────────────────────────────────────────────────────────────────────
export function Field({
  label, children, hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-[var(--bs-secondary-color)]">
        {label}
      </label>
      {children}
      {hint && <div className="text-[11px] text-[var(--bs-secondary-color)] opacity-80">{hint}</div>}
    </div>
  );
}

// ── ErrorMsg ─────────────────────────────────────────────────────────────────
export function ErrorMsg({ msg }: { msg: string }) {
  return (
    <div className="py-2.5 px-3.5 rounded-[var(--bs-border-radius)] bg-[var(--bs-danger-bg)] text-[#58151c] border border-[rgba(220,53,69,0.25)] text-xs">
      {msg}
    </div>
  );
}

// ── Empty ────────────────────────────────────────────────────────────────────
export function Empty({ msg = "데이터 없음" }: { msg?: string }) {
  return (
    <div className="flex items-center justify-center p-10 text-[var(--bs-secondary-color)] text-[13px]">
      {msg}
    </div>
  );
}
