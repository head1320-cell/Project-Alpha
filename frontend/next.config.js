/** @type {import('next').NextConfig} */

// Same-origin API proxy. The browser calls "/api/backend/*" on the frontend's
// own origin; Next forwards it to the backend over the server-side network.
// BACKEND_URL is a RUNTIME env (read by `next start`), so it is NOT baked into
// the client bundle — set it per-deployment (docker network: http://backend:8000).
const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/+$/, "");

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
