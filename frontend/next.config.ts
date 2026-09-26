import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["aws-amplify", "@aws-amplify/core"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8003/api/:path*",
      },
      {
        source: "/health",
        destination: "http://127.0.0.1:8003/health",
      },
    ];
  },
};

export default nextConfig;
