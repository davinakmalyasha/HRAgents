import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import './globals.css'
import { SiteFooter } from '@/components/SiteFooter'
import { SiteHeader } from '@/components/SiteHeader'

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000'

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: 'HRAgents — a virtual HR team for the HR department of one',
    template: '%s · HRAgents',
  },
  description:
    'Self-hosted, open-source HR for hiring, onboarding, leave, payroll preparation and compliance. Models extract, deterministic code decides, named humans approve.',
  openGraph: {
    type: 'website',
    siteName: 'HRAgents',
    title: 'HRAgents — a virtual HR team for the HR department of one',
    description:
      'Self-hosted, open-source HR. Models extract, deterministic code decides, named humans approve. Every outcome reconstructible.',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'HRAgents' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'HRAgents — a virtual HR team for the HR department of one',
    description:
      'Self-hosted, open-source HR. Models extract, deterministic code decides, named humans approve.',
    images: ['/og.png'],
  },
  icons: { icon: '/favicon.svg' },
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  )
}
