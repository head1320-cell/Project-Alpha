/** @type {import('next').NextConfig} */

// NOTE: backend proxying is handled at RUNTIME by the route handler at
// src/app/api/backend/[...path]/route.ts (reads BACKEND_URL per request).
// We intentionally do NOT use next.config.js `rewrites()` for this: rewrites
// bake their destination at BUILD time into routes-manifest.json, so a runtime
// BACKEND_URL would be ignored and the baked localhost:8000 would 500 inside a
// container. See that file's header for the full rationale.
//
// `redirects()` below is a different thing: it moves old **page** URLs (the removed
// step-by-step wizard, BL4) to the canvas. No API address is baked in. The query string
// is carried over by Next (`/allocation/macro?snapshot=x` → `/allocation?from=macro&snapshot=x`).
// Keep the stage list in sync with `src/entities/portfolio-graph/legacyScreens.ts`.
const LEGACY_STAGES = "overview|macro|construct|alphalab|thesis|timing|optimize|stress|explain|execution|journal|wizard";

const nextConfig = {
  async redirects() {
    return [
      { source: `/allocation/:stage(${LEGACY_STAGES})`, destination: "/allocation?from=:stage", permanent: false },
    ];
  },
};

module.exports = nextConfig;
