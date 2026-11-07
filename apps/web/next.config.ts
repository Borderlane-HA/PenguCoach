import type { NextConfig } from "next";

const internalApi = process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Tour planning (alpha.87) and long local AI answers can take longer than the
  // 30 s Next.js default for proxied /api calls (Docker setups without nginx).
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${internalApi}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
