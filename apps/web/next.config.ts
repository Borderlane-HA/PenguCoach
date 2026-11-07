import type { NextConfig } from "next";

const internalApi = process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8000";

// alpha.88: `npm run build:demo` builds the public demo as static pages (GitHub Pages).
const demo = process.env.NEXT_PUBLIC_DEMO === "1";
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || undefined;

const demoConfig: NextConfig = {
  output: "export",
  basePath,
  trailingSlash: true,
  images: { unoptimized: true },
};

const nextConfig: NextConfig = demo ? demoConfig : {
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
