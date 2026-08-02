/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  webpack: (config) => {
    config.resolve.alias.canvas = false
    return config
  }
}

module.exports = nextConfig
