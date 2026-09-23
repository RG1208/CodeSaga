import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  // Keep the dev-only Next.js badge away from the sidebar footer.
  devIndicators: { position: "bottom-right" },
};

export default nextConfig;
