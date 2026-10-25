import type { MetadataRoute } from 'next'

const base = (process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000').replace(/\/$/, '')

export const dynamic = 'force-static'

const routes = [
  '/',
  '/open-source-ats-alternative/',
  '/payroll-preparation/',
  '/hr-automation-indonesia/',
  '/work-with-me/',
]

export default function sitemap(): MetadataRoute.Sitemap {
  return routes.map((route) => ({
    url: `${base}${route}`,
    lastModified: new Date('2026-10-25'),
    changeFrequency: 'monthly',
    priority: route === '/' ? 1 : 0.7,
  }))
}
