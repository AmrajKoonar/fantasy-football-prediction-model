import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [],
  },
  async redirects() {
    return [
      {
        source: "/sources",
        destination: "/about",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
