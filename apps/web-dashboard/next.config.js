/** @type {import('next').NextConfig} */
const nextConfig = {
  compress: false,
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/brain/:path*",
        destination: "http://agentic-brain:8001/api/:path*",
      },
      {
        source: "/api/gateway/:path*",
        destination: "http://api-gateway:8080/api/:path*",
      },
      {
        source: "/api/v1/hitl/:path*",
        destination: "http://schema-aligner:8001/api/v1/hitl/:path*",
      },
    ]
  },
  webpack: (config) => {
    config.resolve.alias.canvas = false
    return config
  }
}

module.exports = nextConfig
