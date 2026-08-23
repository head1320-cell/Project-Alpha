/** @type {import('next').NextConfig} */

// NOTE: backend proxying is handled at RUNTIME by the route handler at
// src/app/api/backend/[...path]/route.ts (reads BACKEND_URL per request).
// We intentionally do NOT use next.config.js `rewrites()` for this: rewrites
// bake their destination at BUILD time into routes-manifest.json, so a runtime
// BACKEND_URL would be ignored and the baked localhost:8000 would 500 inside a
// container. See that file's header for the full rationale.
const nextConfig = {};

module.exports = nextConfig;
