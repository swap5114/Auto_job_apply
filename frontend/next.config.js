/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [
          {
            type: "host",
            value: "auto-job-apply-frontend-831721132982.us-central1.run.app",
          },
        ],
        destination: "https://outra.online/:path*",
        permanent: true,
      },
    ];
  },
  async rewrites() {
    const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const cleanUrl = apiUrl.replace(/\/+$/, "");
    return [
      {
        source: "/api/:path*",
        destination: `${cleanUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;

