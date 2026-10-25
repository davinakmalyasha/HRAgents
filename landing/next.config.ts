import type { NextConfig } from 'next'

const config: NextConfig = {
  // Static HTML, deployable on any static host; no Next server in production.
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
}

export default config
